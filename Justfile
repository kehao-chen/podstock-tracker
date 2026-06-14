# Podstock Tracker — task runner (https://github.com/casey/just).
# Run `just` with no arguments to list recipes.
#
# DuckDB is single-writer: the dashboard holds a read lock while running, so stop it before
# any write recipe (store / prices / compute), then relaunch with `just dash`.

skill := ".claude/skills/podstock"
port  := env_var_or_default("PORT", "8501")

# list available recipes
default:
    @just --list

# launch the local Streamlit dashboard (http://localhost:8501, override with PORT=…); Ctrl-C to stop
dash:
    uv run --with-requirements requirements.txt \
      streamlit run {{skill}}/dashboard/app.py \
      --server.port {{port}} --server.address localhost --server.headless true

# store an extracted episode JSON into DuckDB (write — stop the dashboard first)
store file:
    uv run {{skill}}/scripts/store.py {{file}}

# fetch prices for every ticker in the DB + benchmarks (write — stop the dashboard first)
prices:
    uv run {{skill}}/scripts/fetch_prices.py

# compute buy-next-day returns + alpha (write — stop the dashboard first)
compute:
    uv run {{skill}}/scripts/compute_performance.py

# run an ad-hoc read-only SQL query, e.g. `just query "SELECT * FROM v_weighted LIMIT 20"`
query sql:
    uv run {{skill}}/scripts/query.py "{{sql}}"

# export authored data (episodes + recommendations) to git-tracked data/episodes/*.json (read)
export:
    uv run {{skill}}/scripts/export_episodes.py

# rebuild the DB from data/episodes/*.json, then refetch prices + recompute (write — stop the dashboard first)
rebuild:
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    files=(data/episodes/*/*.json)   # one level: data/episodes/<podcast>/<episode>.json
    if [ ${#files[@]} -eq 0 ]; then echo "no data/episodes/*/*.json to rebuild from"; exit 1; fi
    for f in "${files[@]}"; do
      echo "→ store $f"
      uv run {{skill}}/scripts/store.py "$f"
    done
    uv run {{skill}}/scripts/fetch_prices.py
    uv run {{skill}}/scripts/compute_performance.py
