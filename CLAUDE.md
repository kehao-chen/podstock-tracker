# CLAUDE.md

Operating notes for Claude Code working in this repo. The project tracks stock calls made on
finance podcasts (currently 股癌 Gooaye) and scores them. See [README.md](README.md) for the
human overview.

## Where everything lives

The engine is a self-contained Skill at **`.claude/skills/podstock/`**. Its `SKILL.md` is the
**source of truth** for how to ingest/track/analyse — read it before doing podstock work; it
routes to `workflows/` and `references/`. Don't reimplement what the scripts already do.

- `scripts/` — `store.py` (load episode JSON), `fetch_prices.py` (FinMind), `compute_performance.py`, `query.py` (read-only SQL), `schema.sql`.
- `references/` — `schema.md` (data model), `extraction.md` (subagent contract), `weighting.md`.
- `dashboard/app.py` — the Streamlit UI. Launch with `just dash` from the project root.

Common recipes live in the root `Justfile`: `just dash` (dashboard), `just store <file>`,
`just prices`, `just compute`, `just query "<SQL>"`, `just export`, `just rebuild`. Run `just`
to list them.

## Source of truth vs. cache

`data/podstock.duckdb` is a **rebuildable cache, gitignored.** The tracked source of truth is
**`data/episodes/<podcast>/*.json`** (authored picks per episode, nested per show so EP numbers
can't collide across podcasts; store.py's input shape). Prices /
dividends / performance are derived and not stored. After ingesting, run `just export` to
refresh the JSON snapshot and commit it; `just rebuild` reconstructs the DB from it (store →
fetch prices → compute). Sync across machines = commit `data/episodes/` + `just rebuild` on
pull. Never put the `.duckdb` in folder-sync (Dropbox/iCloud) — single-writer, corrupts mid-write.

## Hard constraints — read before acting

- **DuckDB is single-writer.** The running dashboard holds a read lock. **Stop the dashboard
  before any write script** (`store.py` / `fetch_prices.py` / `compute_performance.py`),
  then relaunch with `just dash`. `query.py` is read-only and safe alongside the dashboard.
  To write ad-hoc, open a read-write `duckdb.connect('data/podstock.duckdb')` — `query.py`
  will reject UPDATE/INSERT.
- **FinMind token** lives in `.env` as `FINMIND_TOKEN` (gitignored — never commit or echo it).
  Prices need it; without one, `fetch_prices.py --source yfinance` is the fallback.
- **Only record specific named securities.** Ignore vague theme/sector/category talk — see
  the extraction contract. A mention ≠ a buy call (the weighting handles conviction/stance).

## Standard pipeline

For an episode: **ingest → track-performance → analyze/dashboard**, in that order. Batch
ingest spawns one extraction subagent per episode (keeps large transcripts out of context);
each fetches its own transcript via `podwise` and returns structured JSON per the contract.

## Conventions

- Tickers are Yahoo-style: TW上市 `.TW`, 上櫃 `.TWO`, US bare, HK `.HK`, JP `.T`. 台積電 = `2330.TW` (not `TSM`).
- Run scripts with `uv run` from the project root (deps are inline PEP 723 — no manual install).
- Conviction is kept at 4 levels (high/medium/low/unspecified) — don't add finer scoring.
