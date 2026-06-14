# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.0"]
# ///
"""Export authored data (episodes + recommendations) to per-episode JSON under data/episodes/.

This directory is the git-tracked source of truth; data/podstock.duckdb is a rebuildable cache.
The output round-trips with store.py — `just rebuild` feeds these files back in. Prices,
dividends, and performance are NOT exported (re-fetched from FinMind and recomputed instead).

Read-only on the database, so it is safe to run while the dashboard is up.

    uv run .claude/skills/podstock/scripts/export_episodes.py   # or: just export
"""
import json
import os
import re
import sys
from pathlib import Path

import duckdb

DB = os.environ.get("PODSTOCK_DB", "data/podstock.duckdb")
OUT = Path("data/episodes")

# Mirror store.py's input contract / column order so the round-trip is lossless.
EP_COLS = ["episode_id", "episode_url", "podcast_name", "title", "publish_date",
           "language", "summary", "keywords", "duration_sec"]
REC_COLS = ["ticker", "company_name", "market", "stance", "horizon", "conviction",
            "rationale", "target_price", "evidence_quote", "evidence_timestamp", "speaker"]


def slug(episode_id: str, title: str, publish_date: str | None) -> str:
    """Stable, human-readable filename: the EP number if present (股癌-style), else the air
    date (daily shows without numbering), else the episode id. Collisions are disambiguated
    with the episode id by the caller."""
    m = re.search(r"EP\d+", title or "")
    if m:
        return m.group(0)
    if publish_date:
        return str(publish_date)            # YYYY-MM-DD
    return f"ep_{episode_id}"


def podcast_dir(podcast_name: str) -> str:
    """Filesystem-safe directory name for a show. Episodes are nested per podcast so EP
    numbers can't collide across shows (many podcasts have an 'EP100')."""
    name = (podcast_name or "unknown").strip()
    name = re.sub(r"[\\/:*?\"<>|]+", "-", name)   # strip path-hostile chars; keep CJK + spaces
    return re.sub(r"\s+", " ", name) or "unknown"


def main() -> None:
    if not Path(DB).exists():
        sys.exit(f"database not found: {DB} (ingest something first)")
    con = duckdb.connect(DB, read_only=True)
    OUT.mkdir(parents=True, exist_ok=True)

    episodes = con.execute(
        f"SELECT {', '.join(EP_COLS)} FROM episodes ORDER BY publish_date, episode_id"
    ).fetchall()

    written = 0
    used: set[str] = set()                 # paths claimed this run, to catch same-day collisions
    for row in episodes:
        ep = dict(zip(EP_COLS, row))
        if ep["publish_date"] is not None:
            ep["publish_date"] = str(ep["publish_date"])          # DATE -> 'YYYY-MM-DD'
        kw = ep["keywords"]                                        # stored as JSON text
        try:
            ep["keywords"] = json.loads(kw) if isinstance(kw, str) and kw.strip() else (kw or [])
        except (ValueError, TypeError):
            ep["keywords"] = []

        recs = con.execute(
            f"SELECT {', '.join(REC_COLS)} FROM recommendations WHERE episode_id = ? ORDER BY rec_id",
            [ep["episode_id"]],
        ).fetchall()
        obj = {"episode": ep, "recommendations": [dict(zip(REC_COLS, r)) for r in recs]}

        show = OUT / podcast_dir(ep["podcast_name"])
        show.mkdir(parents=True, exist_ok=True)
        name = slug(ep["episode_id"], ep["title"], ep["publish_date"])
        path = show / f"{name}.json"
        if str(path) in used:                                     # two episodes → same slug this run
            path = show / f"{name}_{ep['episode_id']}.json"
        used.add(str(path))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")                                          # trailing newline = clean git diffs
        written += 1

    con.close()
    print(f"exported {written} episode(s) -> {OUT}/")


if __name__ == "__main__":
    main()
