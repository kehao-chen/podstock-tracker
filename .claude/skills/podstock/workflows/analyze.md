# Workflow: analyze

Goal: answer "do these podcast stock calls actually work?" by aggregating `v_performance`.
All queries run through the read-only runner:

```bash
uv run .claude/skills/podstock/scripts/query.py "<SQL>"
```

Start from the `v_performance` view (see [../references/schema.md](../references/schema.md)).
Pick the questions that match what the user asked; don't dump everything.

## Effectiveness by horizon (the core question)
Average return and average alpha (excess vs market) for buy calls, by stated horizon:

```sql
SELECT horizon,
       count(*)                               AS n,
       round(avg(ret_30d)  * 100, 2)          AS avg_ret_30d_pct,
       round(avg(ret_90d)  * 100, 2)          AS avg_ret_90d_pct,
       round(avg(ret_365d) * 100, 2)          AS avg_ret_365d_pct,
       round(avg(excess_30d)  * 100, 2)       AS avg_alpha_30d_pct,
       round(avg(excess_90d)  * 100, 2)       AS avg_alpha_90d_pct,
       round(avg(excess_365d) * 100, 2)       AS avg_alpha_365d_pct
FROM v_performance
WHERE stance = 'buy'
GROUP BY horizon ORDER BY horizon;
```

## Hit rate (share of calls that beat the market)
```sql
SELECT horizon,
       round(avg((excess_30d  > 0)::INT) * 100, 1) AS beat_mkt_30d_pct,
       round(avg((excess_90d  > 0)::INT) * 100, 1) AS beat_mkt_90d_pct,
       count(*) AS n
FROM v_performance
WHERE stance = 'buy' AND excess_30d IS NOT NULL
GROUP BY horizon ORDER BY horizon;
```

## Does conviction matter?
```sql
SELECT conviction, round(avg(excess_90d)*100,2) AS avg_alpha_90d_pct, count(*) AS n
FROM v_performance WHERE stance='buy' GROUP BY conviction ORDER BY avg_alpha_90d_pct DESC;
```

## Which podcast / host has the best calls?
```sql
SELECT podcast_name,
       round(avg(excess_90d)*100,2) AS avg_alpha_90d_pct,
       round(avg((excess_90d>0)::INT)*100,1) AS beat_mkt_pct,
       count(*) AS n
FROM v_performance WHERE stance='buy' AND excess_90d IS NOT NULL
GROUP BY podcast_name HAVING n >= 3 ORDER BY avg_alpha_90d_pct DESC;
```

## Best / worst individual calls (with the receipts)
```sql
SELECT publish_date, podcast_name, company_name, horizon,
       round(ret_90d*100,1) AS ret_90d_pct, round(excess_90d*100,1) AS alpha_90d_pct,
       evidence_timestamp, evidence_quote
FROM v_performance WHERE stance='buy' AND ret_90d IS NOT NULL
ORDER BY excess_90d DESC LIMIT 10;          -- flip to ASC for the worst
```

Always surface `evidence_quote` + `evidence_timestamp` + `episode_url` alongside standout
calls so the user can verify against the original transcript.

## Export for external tools
```bash
uv run .claude/skills/podstock/scripts/query.py --csv "SELECT * FROM v_performance" > performance.csv
```

## Reporting guidance
- Lead with the answer (e.g. "long-horizon buy calls averaged +X% alpha over 90 days across N
  calls"), then show the supporting table.
- Always report **n** — small samples are not conclusions. Say so when n is small.
- Distinguish raw return from **alpha**: a call can be "up" only because the whole market was.
- Repeat the caveats from track-performance when presenting results.
