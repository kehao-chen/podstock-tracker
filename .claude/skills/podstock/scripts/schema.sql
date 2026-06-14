-- Podstock DuckDB schema
-- Run via scripts/store.py (auto-applied on first use). Safe to re-run (idempotent).

-- One row per analysed podcast episode.
CREATE TABLE IF NOT EXISTS episodes (
    episode_id    VARCHAR PRIMARY KEY,   -- Podwise numeric id (string), e.g. '5947814'
    episode_url   VARCHAR,               -- canonical Podwise dashboard URL
    podcast_name  VARCHAR,
    title         VARCHAR,
    publish_date  DATE,                  -- air date; "buy next day" anchors on this
    language      VARCHAR,               -- transcript language used for extraction
    summary       VARCHAR,               -- Podwise AI summary (verbatim)
    keywords      VARCHAR,               -- JSON array of strings, stored as text
    duration_sec  INTEGER,              -- episode length if known, else NULL
    ingested_at   TIMESTAMP DEFAULT now()
);

-- One row per (episode, stock) recommendation extracted from the transcript.
CREATE SEQUENCE IF NOT EXISTS rec_seq START 1;
CREATE TABLE IF NOT EXISTS recommendations (
    rec_id             BIGINT PRIMARY KEY DEFAULT nextval('rec_seq'),
    episode_id         VARCHAR NOT NULL,
    ticker             VARCHAR,          -- normalised symbol, e.g. '2330.TW', 'AAPL', 'NVDA'
    company_name       VARCHAR,          -- name as spoken, e.g. '台積電'
    market             VARCHAR,          -- 'TW' | 'US' | 'HK' | 'JP' | 'OTHER'
    stance             VARCHAR,          -- 'buy' | 'sell' | 'hold' | 'avoid' | 'watch'
    horizon            VARCHAR,          -- 'short' | 'medium' | 'long' | 'unspecified'  (短線/中線/長線)
    conviction         VARCHAR,          -- 'high' | 'medium' | 'low' | 'unspecified'
    rationale          VARCHAR,          -- short paraphrase of the reasoning given
    target_price       DOUBLE,           -- mentioned target/price, else NULL
    evidence_quote     VARCHAR,          -- VERBATIM transcript fragment supporting this rec
    evidence_timestamp VARCHAR,          -- timestamp of the quote as printed in transcript
    speaker            VARCHAR,          -- who said it, if labelled
    extracted_at       TIMESTAMP DEFAULT now()
);

-- Daily OHLCV per ticker, populated by fetch_prices.py from yfinance.
CREATE TABLE IF NOT EXISTS prices (
    ticker    VARCHAR,
    date      DATE,
    open      DOUBLE,
    high      DOUBLE,
    low       DOUBLE,
    close     DOUBLE,
    adj_close DOUBLE,   -- dividend/split adjusted; returns are computed on this
    volume    BIGINT,
    PRIMARY KEY (ticker, date)
);

-- Taiwan dividend events (from FinMind TaiwanStockDividend), used to back-adjust TW prices
-- to total return on the free tier (which lacks TaiwanStockPriceAdj). Kept for the dashboard.
CREATE TABLE IF NOT EXISTS dividends (
    ticker        VARCHAR,   -- Yahoo-style symbol, e.g. '2330.TW'
    ex_date       DATE,      -- ex-dividend trading date
    cash_dividend DOUBLE,    -- cash per share (CashEarningsDistribution)
    stock_ratio   DOUBLE,    -- share multiplier from stock dividend (StockEarningsDistribution/10)
    PRIMARY KEY (ticker, ex_date)
);

-- Computed buy-next-day performance per recommendation, written by compute_performance.py.
CREATE TABLE IF NOT EXISTS performance (
    rec_id        BIGINT PRIMARY KEY,
    ticker        VARCHAR,
    benchmark     VARCHAR,        -- index used for excess return, e.g. '^TWII'
    buy_date      DATE,           -- first trading day strictly after publish_date
    buy_price     DOUBLE,
    ret_7d        DOUBLE,         -- (price_at_horizon / buy_price) - 1
    ret_30d       DOUBLE,         -- short  期
    ret_90d       DOUBLE,         -- medium 期
    ret_365d      DOUBLE,         -- long   期
    bench_ret_7d  DOUBLE,
    bench_ret_30d DOUBLE,
    bench_ret_90d DOUBLE,
    bench_ret_365d DOUBLE,
    -- excess_* = ret_* - bench_ret_* (alpha vs market); computed in the view below
    computed_at   TIMESTAMP DEFAULT now()
);

-- Convenience view joining everything an analyst needs, with excess (alpha) returns.
CREATE OR REPLACE VIEW v_performance AS
SELECT
    p.rec_id,
    e.podcast_name,
    e.title,
    e.publish_date,
    r.ticker,
    r.company_name,
    r.market,
    r.stance,
    r.horizon,
    r.conviction,
    p.buy_date,
    p.buy_price,
    p.ret_7d,   p.ret_30d,   p.ret_90d,   p.ret_365d,
    p.ret_7d   - p.bench_ret_7d   AS excess_7d,
    p.ret_30d  - p.bench_ret_30d  AS excess_30d,
    p.ret_90d  - p.bench_ret_90d  AS excess_90d,
    p.ret_365d - p.bench_ret_365d AS excess_365d,
    r.rationale,
    r.evidence_quote,
    r.evidence_timestamp,
    r.speaker,
    e.episode_url
FROM performance p
JOIN recommendations r USING (rec_id)
JOIN episodes e ON e.episode_id = r.episode_id;

-- Per-recommendation view with weighting inputs, for podcast-level aggregation.
--   conviction_weight: how strongly the call was pushed (high=1.0 … unspecified=0.4)
--   stance_sign:       direction (buy=+1, watch=+0.3, hold=0, avoid/sell=-1)
--   signed_strength = conviction_weight * stance_sign  → a single "推薦強度" in [-1, 1]
-- A stock mentioned across many episodes accumulates strength (frequency weighting);
-- weak/low-conviction or non-buy mentions contribute little or negatively.
-- excess_* are alpha vs benchmark (NULL until performance is computed / horizon elapses).
CREATE OR REPLACE VIEW v_weighted AS
SELECT
    r.rec_id,
    e.episode_id,
    e.podcast_name,
    e.title,
    e.publish_date,
    r.ticker,
    r.company_name,
    r.market,
    r.stance,
    r.horizon,
    r.conviction,
    CASE r.conviction WHEN 'high' THEN 1.0 WHEN 'medium' THEN 0.6
                      WHEN 'low' THEN 0.3 ELSE 0.4 END AS conviction_weight,
    CASE r.stance WHEN 'buy' THEN 1.0 WHEN 'watch' THEN 0.3 WHEN 'hold' THEN 0.0
                  WHEN 'avoid' THEN -1.0 WHEN 'sell' THEN -1.0 ELSE 0.0 END AS stance_sign,
    p.buy_date,
    p.buy_price,
    p.ret_7d, p.ret_30d, p.ret_90d, p.ret_365d,
    p.ret_7d   - p.bench_ret_7d   AS excess_7d,
    p.ret_30d  - p.bench_ret_30d  AS excess_30d,
    p.ret_90d  - p.bench_ret_90d  AS excess_90d,
    p.ret_365d - p.bench_ret_365d AS excess_365d,
    r.rationale,
    r.evidence_quote,
    r.evidence_timestamp,
    r.speaker,
    e.episode_url
FROM recommendations r
JOIN episodes e ON e.episode_id = r.episode_id
LEFT JOIN performance p ON p.rec_id = r.rec_id;
