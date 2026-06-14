# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.0"]
# ///
"""Store one episode + its extracted recommendations into the DuckDB database.

Usage:
    uv run scripts/store.py path/to/episode.json
    uv run scripts/store.py path/to/episode.json --db data/podstock.duckdb

The JSON file must match the contract in references/extraction.md:

    {
      "episode": { "episode_id", "episode_url", "podcast_name", "title",
                   "publish_date", "language", "summary", "keywords", "duration_sec" },
      "recommendations": [ { "ticker", "company_name", "market", "stance",
                             "horizon", "conviction", "rationale", "target_price",
                             "evidence_quote", "evidence_timestamp", "speaker" }, ... ]
    }

Re-running for the same episode_id replaces that episode's episodes row and all of its
recommendations (idempotent re-ingest), so it is safe to re-run after fixing extraction.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import duckdb

DEFAULT_DB = os.environ.get("PODSTOCK_DB", "data/podstock.duckdb")
SCHEMA = Path(__file__).parent / "schema.sql"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file", help="episode JSON produced by the extraction step")
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()

    data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    ep = data["episode"]
    recs = data.get("recommendations", [])
    eid = str(ep["episode_id"])

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db)
    con.execute(SCHEMA.read_text(encoding="utf-8"))

    # Idempotent re-ingest: drop any prior rows for this episode first.
    con.execute("DELETE FROM recommendations WHERE episode_id = ?", [eid])
    con.execute("DELETE FROM episodes WHERE episode_id = ?", [eid])

    con.execute(
        """INSERT INTO episodes
           (episode_id, episode_url, podcast_name, title, publish_date,
            language, summary, keywords, duration_sec)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            eid,
            ep.get("episode_url"),
            ep.get("podcast_name"),
            ep.get("title"),
            ep.get("publish_date"),
            ep.get("language"),
            ep.get("summary"),
            json.dumps(ep.get("keywords", []), ensure_ascii=False),
            ep.get("duration_sec"),
        ],
    )

    for r in recs:
        con.execute(
            """INSERT INTO recommendations
               (episode_id, ticker, company_name, market, stance, horizon,
                conviction, rationale, target_price, evidence_quote,
                evidence_timestamp, speaker)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                eid,
                r.get("ticker"),
                r.get("company_name"),
                r.get("market"),
                r.get("stance"),
                r.get("horizon"),
                r.get("conviction"),
                r.get("rationale"),
                r.get("target_price"),
                r.get("evidence_quote"),
                r.get("evidence_timestamp"),
                r.get("speaker"),
            ],
        )

    con.close()
    print(f"stored episode {eid} ({ep.get('title','')[:40]}…) with {len(recs)} recommendation(s) -> {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
