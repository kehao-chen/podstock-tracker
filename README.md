# Podstock Tracker

**English** | [正體中文](README.zh-TW.md)

Track the stock calls made on finance podcasts and measure whether following them
actually works. Starting with **股癌 Gooaye**.

Each episode's transcript (via [Podwise](https://podwise.ai)) is read by a subagent that
extracts every recommended stock — with stance, horizon, conviction, and a **verbatim
transcript quote + timestamp for verification (查證)**. Picks are stored in DuckDB, then
"bought" the trading day *after* the episode aired and scored for short/medium/long-term
return and alpha vs the market. A local Streamlit dashboard browses it all.

```
Podwise CLI ──► transcript + summary + metadata
                       │
                  subagent (extraction contract)
                       │  structured JSON (ticker, stance, horizon, quote+timestamp)
                       ▼
                  DuckDB  ◄── FinMind daily prices (TW back-adjusted) + benchmarks
                       │
                  buy-next-day returns + alpha ──► Streamlit dashboard
```

## Quick start

```bash
# 1. one-time: copy the env template and add your FinMind token
cp .env.example .env        # then edit FINMIND_TOKEN (free token at https://finmindtrade.com/)

# 2. launch the local dashboard (http://localhost:8501)
just dash
```

Recipes are run with [just](https://github.com/casey/just) (`brew install just`); run `just`
with no arguments to list them. [uv](https://docs.astral.sh/uv/) is the other prerequisite —
it installs each script's dependencies on demand (declared inline, PEP 723), so there is no
manual `pip install`. The DuckDB file is created automatically at `data/podstock.duckdb` on
first ingest.

## How the project is organised

The engine is a self-contained **Claude Code Skill** under `.claude/skills/podstock/` — the
skill bundles its own scripts, references, workflows, and the dashboard so it stays portable.
The project root holds the entry points and config.

```
.
├── README.md            ← you are here (English)
├── README.zh-TW.md      ← 正體中文版
├── CLAUDE.md            ← operating notes for Claude Code sessions
├── Justfile             ← task runner (just dash · just prices · just compute · …)
├── requirements.txt     ← dependency reference (uv installs these automatically)
├── .env / .env.example  ← FINMIND_TOKEN (gitignored)
├── data/
│   ├── episodes/<podcast>/*.json  ← authored picks per show, git-tracked (source of truth)
│   └── podstock.duckdb            ← rebuildable cache (gitignored)
└── .claude/skills/podstock/
    ├── SKILL.md             ← skill entry point / workflow routing (source of truth)
    ├── workflows/           ← ingest-episode · track-performance · analyze · dashboard
    ├── references/          ← schema.md · extraction.md · weighting.md
    ├── scripts/             ← store.py · fetch_prices.py · compute_performance.py · query.py · schema.sql
    └── dashboard/app.py     ← the Streamlit web UI
```

## Python environment: uv + inline dependencies

There is **no virtualenv to create and no `pip install` to run**. The project leans on
[uv](https://docs.astral.sh/uv/) and a Python standard called **PEP 723 "inline script
metadata"**. Each standalone script declares its own dependencies in a comment block at the
top — for example `scripts/fetch_prices.py`:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.0", "pandas>=2.0", "requests>=2.31"]
# ///
```

When you run `uv run scripts/fetch_prices.py`, uv reads that block, builds a small **ephemeral
environment** with exactly those packages (cached under `~/.cache/uv`, so it's instant after
the first time), runs the script, and tears nothing into your global Python. Why this instead
of a single `pyproject.toml` + `.venv`:

- **Per-script isolation** — `query.py` only needs `duckdb`; it never drags in streamlit/plotly.
- **Self-contained & portable** — copy a script elsewhere and `uv run` it; the deps travel with
  the code, no project setup required.
- **Nothing to manage** — no `.venv/` to build, activate, gitignore, or keep in sync.

In short: inline metadata moves "which dependencies" from the *project* level down to the
*single-file* level. That's why `requirements.txt` here is a convenience list for humans, not
something you install by hand.

**One exception — the dashboard.** `dashboard/app.py` is started by `streamlit run`, not by
`uv run app.py`, so uv can't read an inline block from it (uv only parses inline metadata for
the script it runs *directly*). Its dependencies therefore live in `requirements.txt`, and the
Justfile's `dash` recipe feeds them in with `uv run --with-requirements requirements.txt
streamlit run …` — same ephemeral-environment idea, just sourced from a file instead of a
comment block.

If you later want to **pin exact versions** (inline blocks only record `>=` floors), uv can
lock a script in place: `uv lock --script scripts/fetch_prices.py`. And `uv add --script
scripts/fetch_prices.py <pkg>` edits a script's inline deps for you.

## Working with the data

Run these from the project root. They're driven through Claude Code (the skill routes the
work), but can be run by hand via `just` too:

```bash
just store /tmp/episode.json     # store an extracted episode JSON              (write)
just prices                      # fetch prices for every ticker + benchmarks   (write)
just compute                     # compute buy-next-day returns + alpha         (write)
just query "SELECT * FROM v_weighted LIMIT 20"   # ad-hoc read-only SQL         (read)
```

Each recipe is a thin wrapper over `uv run .claude/skills/podstock/scripts/<script>.py` — see
the [Justfile](Justfile) for the exact commands.

> **DuckDB is single-writer.** The dashboard holds a read lock while running, so **stop it
> before any write recipe** (`just store` / `just prices` / `just compute`) or you'll hit a
> lock error, then relaunch with `just dash`.

The data model (tables `episodes`, `recommendations`, `prices`, `dividends`, `performance`
and the `v_performance` / `v_weighted` views) is documented in
[references/schema.md](.claude/skills/podstock/references/schema.md). The frequency × conviction
weighting used by the dashboard is in
[references/weighting.md](.claude/skills/podstock/references/weighting.md).

## Backup & sync

`data/podstock.duckdb` is a **rebuildable cache and is not version-controlled.** The source of
truth is the authored data — each episode's extracted picks — exported as per-episode JSON
under **`data/episodes/<podcast>/`** (nested per show, so episode numbers can't collide across
podcasts), which *is* tracked in git. Prices, dividends, and performance are derived (re-fetched
from FinMind and recomputed), so they aren't stored.

```bash
just export     # DB → data/episodes/<podcast>/*.json   (run after ingesting, then commit)
just rebuild    # data/episodes/<podcast>/*.json → DB, then refetch prices + recompute
```

To sync across machines: commit `data/episodes/` and push; on the other machine, pull then
`just rebuild`. The JSON is small and diffable, so git shows exactly what changed per episode,
and there's no risk of corrupting a live database — **don't put the `.duckdb` itself in
Dropbox/iCloud/Drive**; folder-sync can corrupt a single-writer DB mid-write, or create
conflict copies if it's opened on two machines.

> `just export` is read-only (safe anytime). `just rebuild` writes, so stop the dashboard first.

## Notes & caveats

- **Prices** come from FinMind. TW prices are back-adjusted for cash/stock dividends (the free
  tier lacks 還原股價). Benchmarks: `^TWII` (TW total-return), `^GSPC` (US). **JP tickers are
  not supported** on FinMind's routing — they're stored but left unpriced.
- **Recommendations only cover specific named securities.** Vague theme/sector talk
  ("光通訊類股", "AI 概念股") is intentionally ignored — a mention is not a buy call, and a
  sector view is not a recommendation.
- Longer horizons (90/365 day) have small samples until episodes mature — re-run
  `compute_performance.py` over time to fill them in. Read every number next to its sample size.
