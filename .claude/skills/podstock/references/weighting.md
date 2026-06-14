# Weighting: frequency × conviction

A stock can be **mentioned across many episodes**, and **a mention is not a buy call**. So the
podcast-level summary weights each recommendation rather than counting them equally. Encoded
in the `v_weighted` view ([../scripts/schema.sql](../scripts/schema.sql)) and aggregated in the
dashboard.

## Per-recommendation weights

| input | values |
|---|---|
| `conviction_weight` | high `1.0` · medium `0.6` · low `0.3` · unspecified `0.4` |
| `stance_sign` | buy `+1` · watch `+0.3` · hold `0` · avoid `−1` · sell `−1` |

`signed_strength = conviction_weight × stance_sign` → a single "推薦強度" in `[-1, +1]`.
A hard buy = +1.0; a passing low-conviction watch ≈ +0.09; an avoid = negative.

## Per-stock aggregation (within a podcast)

- **mentions / episodes** — raw frequency (how often / in how many episodes it came up).
- **net_strength** = Σ `signed_strength` — frequency × conviction combined: talked about a
  lot *and* pushed hard → high; mentioned once in passing → near zero; warned against → negative.
- **avg_conviction** = mean `conviction_weight`.
- **weighted effectiveness** (e.g. `w_excess_90d`): conviction-weighted, **direction-aligned**
  average excess return —
  `Σ(conviction_weight × dir_excess) / Σ(conviction_weight)`, where `dir_excess = excess × sign(stance_sign)`
  (buy/watch use +alpha, avoid/sell use −alpha = the benefit of having avoided it, hold excluded).

## Podcast-level effectiveness

The same weighted-excess formula over **all** of the podcast's recommendations → "if you
followed this show, weighted by how strongly and often it pushed each call, what alpha did you
get". Always read it next to the sample size — a few calls is not a verdict.

## Tuning

The weight tables are deliberately simple and live in one place (the `v_weighted` view). Adjust
the `CASE` values there if you want, e.g. to make conviction matter more or to treat `watch`
as fully neutral. Re-apply by running any write script (e.g. `compute_performance.py`).
