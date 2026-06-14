# Data model

The database is a single DuckDB file, default `data/podstock.duckdb` (override with the
`PODSTOCK_DB` env var). DDL lives in [scripts/schema.sql](../scripts/schema.sql) and is
applied automatically by every script — you never have to create it by hand.

DuckDB is used because this is analytical work: columnar scans, easy `GROUP BY`/window
aggregation, native CSV/Parquet export, and no server to run. The Python `duckdb` package is
pulled in on demand by `uv run` (the `duckdb` CLI is **not** required).

## Tables

| table             | grain                          | written by                |
|-------------------|--------------------------------|---------------------------|
| `episodes`        | one analysed podcast episode   | `store.py`                |
| `recommendations` | one (episode, stock) call      | `store.py`                |
| `prices`          | one (ticker, trading day)      | `fetch_prices.py`         |
| `dividends`       | one TW ex-dividend event       | `fetch_prices.py`         |
| `performance`     | one recommendation's returns   | `compute_performance.py`  |

### episodes
Podwise `episode_id` is the primary key. `publish_date` (air date) is the anchor for the
"buy the next trading day" rule. `summary` and `keywords` are kept from Podwise for context;
`keywords` is a JSON array stored as text (query with `json_extract` / `unnest`).

### recommendations
The audit trail lives here: `evidence_quote` (verbatim transcript fragment) and
`evidence_timestamp` let you jump back to the exact moment of the call. `ticker` is a Yahoo
Finance symbol so prices join cleanly; `horizon` records 短線/中線/長線; `stance` records
buy/sell/hold/avoid/watch. See [extraction.md](extraction.md) for field semantics.

### prices
Daily OHLCV. Returns are computed on `adj_close`. Default source is **FinMind**: US via
`USStockPrice` (already adjusted); TW via `TaiwanStockPrice` (raw `close`) **back-adjusted to
`adj_close`** using `dividends` (free tier lacks `TaiwanStockPriceAdj`). Benchmarks (`^TWII`
= TAIEX total-return index, `^GSPC`) are stored here as ordinary tickers. `fetch_prices.py
--source yfinance` is the fallback (needs no token).

### dividends
TW ex-dividend events (cash per share + stock-dividend share ratio) from FinMind, used to
back-adjust TW prices and available for the dashboard. Keyed by `(ticker, ex_date)`.

### performance
Computed returns at 7/30/90/365-day horizons plus the matching benchmark returns. `buy_date`
is the first trading day strictly after `publish_date`; a horizon with no elapsed price data
yet is `NULL`.

## v_performance (view)
The analyst-facing join of all four tables. Adds **excess (alpha)** columns
`excess_Nd = ret_Nd - bench_ret_Nd` — the part of the move not explained by the market, i.e.
the real "效益" of following the call. Most analysis should start from this view.

## Horizon convention
`ret_7d` ≈ immediate reaction, `ret_30d` = 短期, `ret_90d` = 中期, `ret_365d` = 長期.
Change the set by editing `HORIZONS` in `compute_performance.py` and the columns in
`schema.sql` together.
