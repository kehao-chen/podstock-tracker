---
name: podstock
description: "Track stock recommendations made on podcasts and measure whether following them works. Uses the Podwise CLI to fetch a stock/finance podcast episode's transcript, summary, and metadata; a subagent extracts each recommended ticker with its stance (buy/sell/hold/watch), horizon (短線/中線/長線), conviction, rationale, and a VERBATIM transcript quote + timestamp for verification; everything is stored in DuckDB. Then it simulates buying each stock the trading day after the episode aired and reports short/medium/long-term return and alpha vs the market. Use when the user wants to ingest/analyse a finance podcast episode, extract stock picks from a transcript, or evaluate the effectiveness of podcast stock calls."
version: 0.1.0
metadata:
  clawdbot:
    emoji: "📈"
---

# Podstock

Analyse stock-related podcasts: extract the stocks an episode recommends (with auditable
transcript evidence), then track how those calls would have performed if bought the day after
the episode aired — short, medium, and long term, versus the market.

## How it works

```
Podwise CLI ──► transcript + summary + metadata
                       │
                  subagent (references/extraction.md)
                       │  structured JSON (ticker, stance, horizon, quote+timestamp)
                       ▼
                  DuckDB  ◄── yfinance daily prices
                       │
                  buy-next-day returns + alpha vs benchmark ──► analysis
```

Why these choices: **Podwise** already turns audio into clean, timestamped transcripts and
summaries. A **subagent** reads the (large) transcript so it never bloats the main context and
returns only structured data. **DuckDB** is an embedded analytical database — perfect for the
`GROUP BY`/window aggregations this analysis needs, with no server to run. Prices come from
**FinMind** (Taiwan-market authority; TW back-adjusted for dividends, US adjusted, plus
benchmark indices), with yfinance as a fallback. A **Streamlit** dashboard provides a local
web UI over the DuckDB.

## References (load on demand — not all upfront)

- [references/schema.md](references/schema.md) — the DuckDB data model, `v_performance` and `v_weighted` views.
- [references/extraction.md](references/extraction.md) — the subagent's extraction contract and field rules. Load before the extraction step.
- [references/weighting.md](references/weighting.md) — frequency × conviction weighting used by the podcast summary.

## Environment check

Before any workflow, verify tooling:

```bash
podwise config show      # must say "configuration ok"; if not, run: podwise auth
uv --version             # uv runs the Python scripts (deps installed on demand — no manual setup)
test -f .env && echo ".env present" || echo "missing .env (needs FINMIND_TOKEN for prices)"
```

If `podwise` is missing or unauthorised, stop and help the user install/auth it (see the
official Podwise skill at https://github.com/hardhackerlabs/podwise-cli). Prices need a
**FinMind token** in `.env` (`FINMIND_TOKEN=...`; copy from `.env.example`) — or use
`fetch_prices.py --source yfinance` without a token. The DuckDB file is created automatically
on first store at `data/podstock.duckdb` (override via `PODSTOCK_DB`).

For exact `podwise` command syntax, the official Podwise skill is the source of truth; the
ingest workflow embeds the few commands this skill needs.

## Workflow routing

**`workflows/ingest-episode.md`** — get an episode into the database.
- "Analyse this episode / podcast: <URL>" · "What stocks did this episode recommend?"
- "Ingest <show> latest episodes" · "Extract the stock picks from this transcript"

**`workflows/track-performance.md`** — price the stored calls.
- "How did those picks do?" · "Track performance" · "Buy-next-day returns"
- "Update the returns" (re-run as horizons elapse)

**`workflows/analyze.md`** — aggregate effectiveness.
- "Do these podcast stock calls actually work?" · "Hit rate / average alpha by horizon"
- "Which podcast has the best calls?" · "Best and worst calls with evidence"

**`workflows/dashboard.md`** — open the local Streamlit web UI.
- "Open the dashboard" · "Show me the web UI" · "Launch the dashboard / Streamlit"

Typical first run for one episode = ingest → track-performance → analyze (or dashboard), in order.

If a request matches more than one workflow, ask one clarifying question. If the user just
wants a one-off DuckDB query, run `scripts/query.py "<SQL>"` directly.
