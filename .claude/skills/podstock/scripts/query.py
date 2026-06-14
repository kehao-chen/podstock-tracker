# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.0"]
# ///
"""Run an ad-hoc SQL query against the podstock DuckDB and print the result.

Usage:
    uv run scripts/query.py "SELECT * FROM v_performance ORDER BY excess_30d DESC LIMIT 20"
    uv run scripts/query.py --file analysis.sql
    uv run scripts/query.py --csv "SELECT * FROM v_performance" > out.csv

Handy starting points:
    SELECT count(*) FROM episodes;
    SELECT count(*) FROM recommendations;
    -- average alpha by horizon, only buy-stance calls:
    SELECT horizon,
           avg(excess_30d) AS avg_excess_30d,
           avg(excess_90d) AS avg_excess_90d,
           count(*)        AS n
    FROM v_performance WHERE stance = 'buy' GROUP BY horizon ORDER BY horizon;
"""
import argparse
import os
import sys
from pathlib import Path

import duckdb

DEFAULT_DB = os.environ.get("PODSTOCK_DB", "data/podstock.duckdb")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sql", nargs="?", help="SQL string to run")
    ap.add_argument("--file", help="read SQL from a file instead")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--csv", action="store_true", help="output CSV instead of a table")
    args = ap.parse_args()

    sql = Path(args.file).read_text(encoding="utf-8") if args.file else args.sql
    if not sql:
        ap.error("provide a SQL string or --file")
    if not Path(args.db).exists():
        print(f"database not found: {args.db} (ingest an episode first)", file=sys.stderr)
        return 1

    con = duckdb.connect(args.db, read_only=True)
    rel = con.sql(sql)
    if rel is None:
        return 0
    if args.csv:
        import csv
        w = csv.writer(sys.stdout)
        w.writerow(rel.columns)
        w.writerows(rel.fetchall())
    else:
        print(rel)  # DuckDB renders an aligned table
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
