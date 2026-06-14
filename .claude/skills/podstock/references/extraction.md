# Stock-recommendation extraction (subagent contract)

This is the rubric the analysis **subagent** follows when reading a transcript. The whole
point of using a subagent is to keep the (large) transcript out of the main context — the
subagent reads it and returns only structured JSON.

## Output contract

The subagent must return **one JSON object** matching exactly this shape (UTF-8, keep
Chinese verbatim). `scripts/store.py` consumes this file directly.

```json
{
  "episode": {
    "episode_id": "5947814",
    "episode_url": "https://podwise.ai/dashboard/episodes/5947814",
    "podcast_name": "新唐人電視台",
    "title": "完整集數標題…",
    "publish_date": "2025-10-23",
    "language": "Traditional-Chinese",
    "summary": "Podwise 產生的摘要（逐字保留）",
    "keywords": ["半導體", "台積電", "AI"],
    "duration_sec": null
  },
  "recommendations": [
    {
      "ticker": "2330.TW",
      "company_name": "台積電",
      "market": "TW",
      "stance": "buy",
      "horizon": "long",
      "conviction": "high",
      "rationale": "主持人認為先進製程訂單滿載，長期競爭力強",
      "target_price": null,
      "evidence_quote": "台積電這一波我覺得長線還是站在買方，先進製程根本供不應求…",
      "evidence_timestamp": "00:12:34",
      "speaker": "侯永清"
    }
  ]
}
```

If the episode contains **no** stock recommendation, return `"recommendations": []`. Do not
invent tickers.

## Field rules

- **ticker** — normalise to a Yahoo Finance symbol so prices can be fetched later:
  - Taiwan listed (上市): `<code>.TW` → 台積電 = `2330.TW`
  - Taiwan OTC (上櫃 TPEx): `<code>.TWO`
  - US: bare ticker → `AAPL`, `NVDA`, `TSLA`
  - HK: `<code>.HK` (e.g. `0700.HK`); JP: `<code>.T`
  - If only a company name is spoken and the code is unambiguous, supply the ticker. `null`
    is allowed **only** when a *specific named security* was recommended but you cannot
    resolve its exact symbol — fill `company_name` so it can be resolved later. Do **not**
    use `null` to record a vague theme or sector basket (see the rule below).
- **market** — one of `TW` / `US` / `HK` / `JP` / `OTHER`. Drives benchmark selection
  (`^TWII`, `^GSPC`, …) for excess-return / alpha.
- **stance** — `buy` | `sell` | `hold` | `avoid` | `watch`. Use `watch` for "留意/觀察"
  without a clear buy call; `avoid` for "不要碰/看空但非放空".
- **horizon** — the holding view as stated: `short` (短線/當沖/波段內), `medium`
  (中線/數週至數月), `long` (長線/存股/數季以上), or `unspecified` if not stated.
- **conviction** — how strongly it was pushed: `high` (重押/明確推薦), `medium`, `low`
  (順帶一提), or `unspecified`.
- **rationale** — one or two sentences paraphrasing the *reason* given (catalyst, earnings,
  product cycle, valuation…). Keep it short; the quote carries the proof.
- **target_price** — numeric target/price if explicitly mentioned, else `null`.
- **evidence_quote** — **VERBATIM** transcript text (do not paraphrase, do not translate).
  This is the audit trail; it must be copyable back into the transcript. Keep it focused
  (roughly one to three sentences) around the call.
- **evidence_timestamp** — the timestamp printed next to that line in the transcript, copied
  as-is (e.g. `00:12:34` or `12:34`). If the line has no timestamp, use the nearest one
  above it. Never fabricate a timestamp.
- **speaker** — the speaker label from the transcript if present, else `null`.

## Extraction guidance

- One row **per (stock, distinct call)**. If the same stock is recommended twice with
  different horizons (e.g. 短線出場、長線續抱), emit two rows.
- Capture only *actual* recommendations or clear directional opinions on a specific
  tradeable security — not every company merely *mentioned* in passing news.
- **Ignore category / theme / sector-level talk that names no specific security.** A view
  like "光通訊類股有機會" or "漲價題材推不動股價" is a market opinion, not a recordable
  recommendation — do **not** emit a row for it (no `null`-ticker placeholder for themes).
  Only record it if he points to a *specific named stock* (which then gets a ticker, or
  `null` only if the symbol is genuinely unresolvable).
- A named ETF/index counts as a specific security and is fine (e.g. `0050.TW`, `SPY`).
- Stay faithful: if the host hedges ("不是建議大家買，只是分享"), still record it but set
  `conviction` low and let the quote show the hedge.
- Prefer the Traditional-Chinese transcript for Chinese-language shows so quotes match.
