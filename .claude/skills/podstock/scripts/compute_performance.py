# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.0", "pandas>=2.0"]
# ///
"""Compute buy-next-day performance for every recommendation and write the performance table.

For each recommendation:
  buy_date  = first trading day STRICTLY AFTER the episode's publish_date
  buy_price = adj_close on buy_date
  ret_Nd    = adj_close on the first trading day on/after (buy_date + N calendar days)
              divided by buy_price, minus 1
  bench_*   = same calculation on the market's benchmark index

Horizons: 7d, 30d (短期), 90d (中期), 365d (長期). Edit HORIZONS to change.
A horizon that has not elapsed yet (no future price data) is left NULL.

Usage:
    uv run scripts/compute_performance.py
    uv run scripts/compute_performance.py --db data/podstock.duckdb
"""
import argparse
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd

DEFAULT_DB = os.environ.get("PODSTOCK_DB", "data/podstock.duckdb")
SCHEMA = Path(__file__).parent / "schema.sql"
HORIZONS = [7, 30, 90, 365]
BENCHMARKS = {"TW": "^TWII", "US": "^GSPC", "HK": "^HSI", "JP": "^N225"}


def price_series(con, ticker):
    df = con.execute(
        "SELECT date, adj_close FROM prices WHERE ticker = ? AND adj_close IS NOT NULL ORDER BY date",
        [ticker],
    ).df()
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["adj_close"].sort_index()


def price_after(series, target_ts):
    """adj_close on the first trading day on/after target_ts, or None."""
    if series is None:
        return None, None
    idx = series.index.searchsorted(pd.Timestamp(target_ts), side="left")
    if idx >= len(series):
        return None, None
    return float(series.iloc[idx]), series.index[idx].date()


def returns_for(series, buy_ts):
    """(buy_price, {Nd: ret}) using first trading day strictly after buy anchor."""
    buy_price, buy_date = price_after(series, buy_ts)
    if buy_price is None:
        return None, None, {}
    rets = {}
    for n in HORIZONS:
        px, _ = price_after(series, pd.Timestamp(buy_date) + pd.Timedelta(days=n))
        rets[n] = (px / buy_price - 1) if px is not None else None
    return buy_price, buy_date, rets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()

    con = duckdb.connect(args.db)
    con.execute(SCHEMA.read_text(encoding="utf-8"))

    recs = con.execute(
        """SELECT r.rec_id, r.ticker, r.market, e.publish_date
           FROM recommendations r JOIN episodes e ON e.episode_id = r.episode_id
           WHERE r.ticker IS NOT NULL AND r.ticker <> '' AND e.publish_date IS NOT NULL"""
    ).df()
    if recs.empty:
        print("no recommendations with a ticker + publish_date to compute")
        return 0

    series_cache: dict[str, object] = {}

    def get_series(t):
        if t not in series_cache:
            series_cache[t] = price_series(con, t)
        return series_cache[t]

    written = 0
    for _, row in recs.iterrows():
        ticker = row["ticker"]
        bench = BENCHMARKS.get(row["market"])
        # buy anchor = day after publish; price_after with strict-after handled by +1 day
        buy_anchor = pd.Timestamp(row["publish_date"]) + pd.Timedelta(days=1)

        buy_price, buy_date, rets = returns_for(get_series(ticker), buy_anchor)
        if buy_price is None:
            print(f"  ! rec {row['rec_id']} {ticker}: no price near {buy_anchor.date()} (fetch prices?)")
            continue

        b_rets = {n: None for n in HORIZONS}
        if bench:
            _, _, b_rets = returns_for(get_series(bench), buy_anchor)
            b_rets = b_rets or {n: None for n in HORIZONS}

        con.execute("DELETE FROM performance WHERE rec_id = ?", [int(row["rec_id"])])
        con.execute(
            """INSERT INTO performance
               (rec_id, ticker, benchmark, buy_date, buy_price,
                ret_7d, ret_30d, ret_90d, ret_365d,
                bench_ret_7d, bench_ret_30d, bench_ret_90d, bench_ret_365d)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                int(row["rec_id"]), ticker, bench, buy_date, buy_price,
                rets.get(7), rets.get(30), rets.get(90), rets.get(365),
                b_rets.get(7), b_rets.get(30), b_rets.get(90), b_rets.get(365),
            ],
        )
        written += 1

    con.close()
    print(f"computed performance for {written} recommendation(s) -> {args.db}")
    print("query results with: uv run scripts/query.py 'SELECT * FROM v_performance'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
