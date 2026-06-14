# Workflow: track-performance

Goal: for the stored recommendations, simulate buying the stock **the first trading day after
the episode aired** and measure short/medium/long-term effectiveness vs the market.

Run this after ingesting episodes, and re-run later as more time elapses (horizons that
haven't passed yet stay `NULL` until prices exist).

## 1. Fetch prices

Downloads daily history (default source **FinMind**; requires `FINMIND_TOKEN` in `.env`) for
every distinct ticker in `recommendations`, plus the benchmark index for each market
(`^TWII`, `^GSPC`, …):

```bash
uv run .claude/skills/podstock/scripts/fetch_prices.py
```

Source routing (symbols are stored Yahoo-style):
- `*.TW` / `*.TWO` → FinMind `TaiwanStockPrice` (raw), **back-adjusted for cash + stock
  dividends** via `TaiwanStockDividend` so returns reflect total return (free tier has no
  `TaiwanStockPriceAdj`). Dividend events are also saved to the `dividends` table.
- `^TWII` → FinMind `TaiwanStockTotalReturnIndex` (TAIEX); `^GSPC`/US → FinMind `USStockPrice`.

Options: limit to symbols (`… fetch_prices.py 2330.TW ^TWII`), or fall back to yfinance
adjusted prices with `--source yfinance` (no token needed).

If a ticker reports "no data", the symbol is likely wrong (check the `.TW`/`.TWO` suffix or
the US ticker). Fix it by re-running **ingest-episode** with the corrected ticker
(`query.py` is read-only, so it can't patch the DB).

## 2. Compute returns

```bash
uv run .claude/skills/podstock/scripts/compute_performance.py
```

This writes the `performance` table:
- `buy_date` / `buy_price` — first trading day strictly after `publish_date`, on `adj_close`.
- `ret_7d`, `ret_30d` (短期), `ret_90d` (中期), `ret_365d` (長期).
- `bench_ret_*` — same windows on the market index.
- The `v_performance` view adds `excess_Nd = ret_Nd - bench_ret_Nd` (alpha vs market).

## 3. Show the result

```bash
uv run .claude/skills/podstock/scripts/query.py \
  "SELECT publish_date, company_name, ticker, stance, horizon,
          ret_30d, ret_90d, ret_365d, excess_30d, excess_90d
   FROM v_performance ORDER BY publish_date DESC LIMIT 30"
```

Summarise for the user in plain language: which calls beat the market and over what horizon.
For deeper aggregation (hit-rate, average alpha by horizon/podcast/conviction), go to the
**analyze** workflow.

## Caveats to state honestly
- Returns are model prices (buy at next day's adjusted close), not real fills — no slippage,
  fees, or liquidity assumptions.
- TW prices are back-adjusted from raw + dividends (free FinMind tier). Cash dividends are
  exact; 配股 (stock dividends) use the standard share-ratio factor — spot-check unusual ones.
- Price data can have gaps/errors; spot-check surprising numbers against the chart.
- A horizon showing `NULL` simply hasn't elapsed yet — re-run later.
