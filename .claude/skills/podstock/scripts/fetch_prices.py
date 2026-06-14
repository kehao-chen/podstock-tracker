# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.0", "pandas>=2.0", "requests>=2.31"]
# ///
"""Download daily prices into the prices table. Default source: FinMind.

Routing by symbol (symbols are stored Yahoo-style in the DB):
  *.TW / *.TWO   -> FinMind TaiwanStockPrice (raw close); back-adjusted to total return
                    using TaiwanStockDividend (free tier has no TaiwanStockPriceAdj)
  ^TWII          -> FinMind TaiwanStockTotalReturnIndex (TAIEX)  [TW benchmark]
  ^GSPC / other ^ -> FinMind USStockPrice (index id as-is)        [US benchmark]
  anything else  -> FinMind USStockPrice (Adj_Close)              [US stocks]

Usage:
    uv run scripts/fetch_prices.py                 # all tickers in DB + benchmarks
    uv run scripts/fetch_prices.py 2330.TW LITE    # explicit symbols
    uv run scripts/fetch_prices.py --source yfinance   # fallback to yfinance

Requires FINMIND_TOKEN (read from the environment or a .env file in the project root).
Idempotent: existing (ticker, date) rows are replaced.

Note on TW free tier: prices are back-adjusted for CASH and STOCK dividends so holding-period
returns reflect total return. If a stock dividend (配股) is present it is applied as a share
multiplier; verify unusual cases against the chart.
"""
import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import requests

DEFAULT_DB = os.environ.get("PODSTOCK_DB", "data/podstock.duckdb")
SCHEMA = Path(__file__).parent / "schema.sql"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
BENCHMARKS = {"TW": "^TWII", "US": "^GSPC", "HK": "^HSI", "JP": "^N225"}


# ---------- token / .env ----------
def load_token() -> str:
    tok = os.environ.get("FINMIND_TOKEN")
    if not tok:
        for p in (Path(".env"), Path(__file__).resolve().parents[4] / ".env"):
            if p.exists():
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("FINMIND_TOKEN=") and not line.startswith("#"):
                        tok = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            if tok:
                break
    if not tok:
        sys.exit("FINMIND_TOKEN not set. Add it to .env or `export FINMIND_TOKEN=...`")
    return tok


# ---------- FinMind ----------
def finmind(token, dataset, data_id, start, end):
    r = requests.get(
        FINMIND_URL,
        params={"dataset": dataset, "data_id": data_id, "start_date": start, "end_date": end},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    if r.status_code == 402:
        sys.exit("FinMind quota exceeded (HTTP 402). Wait an hour or upgrade tier.")
    j = r.json()
    if j.get("status") != 200:
        raise RuntimeError(f"{dataset}/{data_id}: {j.get('msg', 'error')}")
    return pd.DataFrame(j.get("data", []))


def classify(sym):
    if sym.endswith((".TW", ".TWO")):
        return "tw", sym.rsplit(".", 1)[0]
    if sym == "^TWII":
        return "twindex", "TAIEX"
    if sym.startswith("^"):
        return "us", sym
    return "us", sym


def tw_dividends(token, code, start, end):
    """Return DataFrame[ex_date, cash, stock_ratio] for ex-dates within [start, end]."""
    try:
        df = finmind(token, "TaiwanStockDividend", code, "2000-01-01", end)
    except RuntimeError:
        return pd.DataFrame(columns=["ex_date", "cash", "stock_ratio"])
    if df.empty:
        return pd.DataFrame(columns=["ex_date", "cash", "stock_ratio"])
    rows = []
    for _, r in df.iterrows():
        ex = r.get("CashExDividendTradingDate") or r.get("StockExDividendTradingDate") or ""
        if not ex:
            continue
        cash = float(r.get("CashEarningsDistribution") or 0)
        stock = float(r.get("StockEarningsDistribution") or 0) / 10.0  # 元 face-value -> share ratio
        if cash == 0 and stock == 0:
            continue
        rows.append({"ex_date": ex, "cash": cash, "stock_ratio": stock})
    d = pd.DataFrame(rows)
    if not d.empty:
        d["ex_date"] = pd.to_datetime(d["ex_date"])
        d = d[(d["ex_date"] >= pd.Timestamp(start)) & (d["ex_date"] <= pd.Timestamp(end))]
    return d


def back_adjust(price_df, div_df):
    """Add an adj_close column: raw close back-adjusted for dividends -> total return.
    price_df has columns date (Timestamp), close. div_df has ex_date, cash, stock_ratio."""
    price_df = price_df.sort_values("date").reset_index(drop=True)
    adj = price_df["close"].astype(float).copy()
    if div_df is None or div_df.empty:
        price_df["adj_close"] = adj
        return price_df
    for _, ev in div_df.sort_values("ex_date").iterrows():
        ex = ev["ex_date"]
        prior = price_df[price_df["date"] < ex]
        if prior.empty:
            continue
        p_ref = float(prior["close"].iloc[-1])
        if p_ref <= 0:
            continue
        ratio = (p_ref - ev["cash"]) / p_ref / (1.0 + ev["stock_ratio"])
        mask = price_df["date"] < ex
        adj.loc[mask] = adj.loc[mask] * ratio
    price_df["adj_close"] = adj
    return price_df


def fetch_finmind(con, token, sym, start, end):
    kind, data_id = classify(sym)
    div_rows = []
    if kind == "tw":
        raw = finmind(token, "TaiwanStockPrice", data_id, start, end)
        if raw.empty:
            return None, div_rows
        df = pd.DataFrame({
            "date": pd.to_datetime(raw["date"]),
            "open": raw["open"].astype(float), "high": raw["max"].astype(float),
            "low": raw["min"].astype(float), "close": raw["close"].astype(float),
            "volume": raw["Trading_Volume"].astype("Int64"),
        })
        divs = tw_dividends(token, data_id, start, end)
        df = back_adjust(df, divs)
        div_rows = [(sym, r["ex_date"].date(), float(r["cash"]), float(r["stock_ratio"]))
                    for _, r in divs.iterrows()] if not divs.empty else []
    elif kind == "twindex":
        raw = finmind(token, "TaiwanStockTotalReturnIndex", data_id, start, end)
        if raw.empty:
            return None, div_rows
        df = pd.DataFrame({"date": pd.to_datetime(raw["date"]), "close": raw["price"].astype(float)})
        for c in ("open", "high", "low"):
            df[c] = None
        df["adj_close"] = df["close"]
        df["volume"] = None
    else:  # us / index via USStockPrice
        raw = finmind(token, "USStockPrice", data_id, start, end)
        if raw.empty:
            return None, div_rows
        df = pd.DataFrame({
            "date": pd.to_datetime(raw["date"]),
            "open": raw["Open"].astype(float), "high": raw["High"].astype(float),
            "low": raw["Low"].astype(float), "close": raw["Close"].astype(float),
            "adj_close": raw["Adj_Close"].astype(float), "volume": raw["Volume"].astype("Int64"),
        })
    return df, div_rows


def fetch_yfinance(sym, start):
    import yfinance as yf
    df = yf.download(sym, start=start, auto_adjust=False, progress=False)
    if df is None or df.empty:
        return None
    if getattr(df.columns, "nlevels", 1) > 1:
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    df = df.rename(columns={"adj_close": "adj_close"})
    if "adj_close" not in df:
        df["adj_close"] = df["close"]
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "open", "high", "low", "close", "adj_close", "volume"]]


# ---------- DB plumbing ----------
def distinct_tickers(con):
    rows = con.execute(
        "SELECT DISTINCT ticker FROM recommendations WHERE ticker IS NOT NULL AND ticker <> ''"
    ).fetchall()
    tickers = {r[0] for r in rows}
    for (m,) in con.execute("SELECT DISTINCT market FROM recommendations WHERE market IS NOT NULL").fetchall():
        if m in BENCHMARKS:
            tickers.add(BENCHMARKS[m])
    return sorted(tickers)


def start_date(con):
    row = con.execute("SELECT min(publish_date) FROM episodes").fetchone()
    earliest = row[0] if row and row[0] else date.today() - timedelta(days=400)
    return (earliest - timedelta(days=10)).isoformat()


def store_prices(con, sym, df):
    df = df.where(pd.notnull(df), None)
    rows = [
        (sym, r["date"].date(),
         _f(r.get("open")), _f(r.get("high")), _f(r.get("low")),
         _f(r.get("close")), _f(r.get("adj_close")),
         int(r["volume"]) if pd.notnull(r.get("volume")) else None)
        for _, r in df.iterrows()
    ]
    con.execute("DELETE FROM prices WHERE ticker = ?", [sym])
    con.executemany(
        "INSERT INTO prices (ticker,date,open,high,low,close,adj_close,volume) VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    return len(rows)


def _f(v):
    try:
        if v is None or (isinstance(v, float) and v != v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--source", choices=["finmind", "yfinance"], default="finmind")
    ap.add_argument("--start")
    args = ap.parse_args()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db)
    con.execute(SCHEMA.read_text(encoding="utf-8"))

    tickers = args.tickers or distinct_tickers(con)
    if not tickers:
        print("no tickers to fetch (ingest some episodes first)")
        return 0
    start = args.start or start_date(con)
    end = date.today().isoformat()
    token = load_token() if args.source == "finmind" else None
    print(f"[{args.source}] fetching {len(tickers)} symbol(s) from {start}: {', '.join(tickers)}")

    for sym in tickers:
        try:
            if args.source == "finmind":
                df, div_rows = fetch_finmind(con, token, sym, start, end)
            else:
                df, div_rows = fetch_yfinance(sym, start), []
        except Exception as e:  # noqa: BLE001
            print(f"  ! {sym}: {e}")
            continue
        if df is None or df.empty:
            print(f"  ! {sym}: no data")
            continue
        n = store_prices(con, sym, df)
        if div_rows:
            con.execute("DELETE FROM dividends WHERE ticker = ?", [sym])
            con.executemany(
                "INSERT INTO dividends (ticker, ex_date, cash_dividend, stock_ratio) VALUES (?,?,?,?)",
                div_rows,
            )
        extra = f", {len(div_rows)} dividend event(s)" if div_rows else ""
        print(f"  {sym}: {n} rows{extra}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
