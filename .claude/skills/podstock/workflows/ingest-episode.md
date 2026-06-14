# Workflow: ingest-episode

Goal: turn one podcast episode into stored, auditable stock-recommendation rows.

Pipeline: **resolve → fetch (Podwise) → extract (subagent) → store (DuckDB)**.

Inputs you may get from the user: a Podwise/YouTube/Xiaoyuzhou URL, or a show + keyword to
search for. Work in the project root so `data/podstock.duckdb` and `/tmp/*.json` paths line up.

## 1. Resolve the episode

If given a URL, use it directly. If given keywords, find the episode:

```bash
podwise search episode "<keywords>" --limit 10 --json
```

Pick the right result with the user if ambiguous. Record `episode_url`, `title`,
`podcast_name`, and **`publish_date`** (the air date — this is what "buy next day" anchors
on; `get` does not always print it, so capture it here). The numeric id at the end of the
URL is the `episode_id`.

## 2. Make sure it is processed, then fetch content

```bash
podwise get summary "<episode_url>"
```

If this errors with `episode has not been processed yet`, the episode must be processed
first (**this consumes Podwise credits — confirm with the user before running**):

```bash
podwise process "<episode_url>"        # async; polls until done
```

Once available, fetch the artifacts. For Chinese-language shows pass
`--lang Traditional-Chinese` so quotes match what you store:

```bash
podwise get transcript "<episode_url>" > /tmp/transcript.md
podwise get summary    "<episode_url>" > /tmp/summary.md
podwise get keywords   "<episode_url>" > /tmp/keywords.md
podwise get chapters   "<episode_url>" > /tmp/chapters.md   # optional, helps locate calls
```

The transcript carries timestamps and speaker labels — these are the audit trail, so keep
them.

## 3. Extract recommendations with a subagent

Spawn a **subagent** (Agent tool, `subagent_type: "general-purpose"`) so the large transcript
stays out of the main context. Give it:

- the full contents of [../references/extraction.md](../references/extraction.md) (the contract + rules),
- the episode metadata you resolved in step 1 (id, url, podcast_name, title, publish_date, language),
- the transcript, summary, and keywords files from step 2.

Instruct it to **write the JSON object to `/tmp/episode.json`** (exactly the contract shape)
and return only a short confirmation. Emphasise: `evidence_quote` must be **verbatim**
transcript text and `evidence_timestamp` copied as printed — never paraphrased or invented.

If there are no recommendations, the subagent still writes the episode block with
`"recommendations": []` (we still record that the episode was reviewed).

## 4. Store into DuckDB

```bash
uv run .claude/skills/podstock/scripts/store.py /tmp/episode.json
```

(Re-running for the same `episode_id` cleanly replaces it, so fixing an extraction and
re-storing is safe.)

## 5. Report back

Tell the user what was stored: episode title, count of recommendations, and a quick list of
`ticker / stance / horizon`. Then suggest running **track-performance** (immediately for old
episodes; later, once horizons elapse, for recent ones).

## Batch ingest (a show's recent episodes)

`podwise drill <podcast-url> --latest N --json` lists episodes (`--latest` is **days**, not a
count). Then:

> **Podwise free tier rate-limits bursts.** Do NOT spawn many extraction subagents that each
> call `podwise get` — e.g. 20 subagents × 3 calls = a 60-call burst will exhaust the quota
> and leave subagents fabricating placeholder summaries. Instead **decouple fetch from extract**:
>
> 1. **Fetch serially in the main loop** to local files (`podwise get transcript/summary/keywords`
>    for each episode, with a short `sleep` between, bailing if you see `rate limit exceeded`).
>    Save to e.g. `/tmp/<show>_fetch/{transcript,summary,keywords}_<id>.txt`.
> 2. **Then spawn extraction subagents that read those local files** — zero API calls, so they
>    can run in parallel with no rate-limit risk.
>
> Episodes that return `episode has not been processed yet` need `podwise process` (costs a
> credit) — collect them and confirm with the user rather than processing silently.

After extraction, store each JSON (step 4), then run **track-performance** and **`just export`**
to refresh the git-tracked snapshot.
