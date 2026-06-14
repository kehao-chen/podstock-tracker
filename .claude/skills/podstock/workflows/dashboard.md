# Workflow: dashboard

Goal: open the local Streamlit web UI to browse episodes, recommendations (with transcript
evidence), and buy-next-day performance.

The dashboard reads `data/podstock.duckdb` **read-only**, so it never needs a FinMind token
and never modifies data. Ingest/track first so there is something to show.

## Launch

From the project root:

```bash
just dash        # or: PORT=8502 just dash
```

This wraps the underlying launch (`uv run --with-requirements requirements.txt streamlit run
.claude/skills/podstock/dashboard/app.py …`); run that directly if `just` isn't available.
Streamlit prints a local URL (default http://localhost:8501) and opens the browser. Stop with
Ctrl-C. Override the DB with `PODSTOCK_DB=/path/to.duckdb` before the command if needed.

> The DB is single-writer: stop the dashboard before running a fetch/compute (those open the
> DB read-write and will otherwise hit a lock error), then relaunch.

## Information architecture (main category = Podcast)

1. **Pick a Podcast** in the sidebar → a summary aggregated across all its episodes.
2. **🏷️ 個股彙整** — every recommended stock ranked, weighted by **frequency × conviction**
   (see [../references/weighting.md](../references/weighting.md)): mentions, episodes, 淨推薦強度,
   平均信心, 加權超額報酬. Plus a bubble chart (推薦強度 vs 90d 加權效益, size = mentions).
   **Click a row** to drill into that stock.
3. **📉 個股明細** — a **Plotly candlestick** of the stock's full price history, with each
   mention's buy date marked, and a table of every mention (with transcript quote + timestamp).
4. **🎧 單一集數分析 (optional, collapsed at the bottom)** — pick one episode to see its
   summary and each recommendation with verbatim transcript evidence.

## Notes
- Data is cached for 60s; re-run a fetch/compute then refresh the page to see new numbers.
- A stock with one passing low-conviction mention ranks far below one pushed hard across many
  episodes — that's the weighting doing its job. Weighted effectiveness aligns direction
  (buy/watch count +alpha, avoid/sell count −alpha, hold excluded).
- If it shows "找不到資料庫", run **ingest-episode** then **track-performance** first.
- Chinese renders natively (browser), so no matplotlib CJK font setup is needed.
