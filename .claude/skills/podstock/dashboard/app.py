"""Podstock dashboard — local Streamlit UI over the DuckDB database.

Information architecture (main category = Podcast):
  1. Pick a Podcast  → aggregated summary across all its episodes
  2. 個股彙整         → stocks ranked, weighted by frequency × conviction; pick one to drill in
  3. 個股明細         → Plotly candlestick of full price history + every mention as a marker
  4. 單一集數分析 (optional, below) → one episode's recommendations with transcript evidence

Launch (from the project root):
    just dash       # wraps `uv run --with-requirements requirements.txt streamlit run ...`

Unlike the four standalone scripts, this file has no inline (PEP 723) deps: its entrypoint is
`streamlit run`, not `uv run app.py`, so uv reads the dependency list from requirements.txt
instead (see the Justfile). Reads the database read-only. No FinMind token needed here.
"""
import os
from pathlib import Path

import altair as alt
import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DB = os.environ.get("PODSTOCK_DB") or str(PROJECT_ROOT / "data" / "podstock.duckdb")
HORIZON_LABELS = {"short": "短", "medium": "中", "long": "長", "unspecified": "—"}

st.set_page_config(page_title="Podstock 選股追蹤", page_icon="📈", layout="wide")


@st.cache_resource
def connect():
    return duckdb.connect(DB, read_only=True)


@st.cache_data(ttl=60)
def q(sql: str, params=None) -> pd.DataFrame:
    return connect().execute(sql, params or []).df()


def fmt_pct(x):
    return "—" if pd.isnull(x) else f"{x*100:.1f}%"


def weighted_excess(df: pd.DataFrame, col: str) -> float:
    """Conviction-weighted, direction-aligned average excess return.
    buy/watch count +excess, avoid/sell count -excess (benefit of avoiding), hold excluded."""
    d = df[df["stance_sign"] != 0].dropna(subset=[col]).copy()
    w = d["conviction_weight"]
    if d.empty or w.sum() == 0:
        return np.nan
    dir_excess = d[col] * np.sign(d["stance_sign"])
    return float((w * dir_excess).sum() / w.sum())


# ---- guard ----
if not Path(DB).exists():
    st.title("📈 Podstock")
    st.warning(f"找不到資料庫:`{DB}`\n\n請先用 podstock skill ingest 至少一集。")
    st.stop()

w_all = q("SELECT * FROM v_weighted")
if w_all.empty:
    st.title("📈 Podstock")
    st.info("資料庫沒有推薦資料。請先 ingest 一集並 track-performance。")
    st.stop()

w_all["signed_strength"] = w_all["conviction_weight"] * w_all["stance_sign"]

# ===== sidebar: main category = Podcast =====
with st.sidebar:
    st.header("📻 Podcast")
    podcasts = sorted(w_all["podcast_name"].dropna().unique().tolist())
    podcast = st.selectbox("選擇節目", podcasts, index=0)
    st.divider()
    st.caption("加權邏輯:推薦強度 = 信心度(high 1.0／med 0.6／low 0.3) × 立場(buy +1／watch +0.3／avoid −1)。效益以信心度加權、依立場對齊方向。")
    st.caption(f"DB: `{DB}`")

w = w_all[w_all["podcast_name"] == podcast].copy()

st.title(f"📈 {podcast}")
st.caption("解析 Podcast 推薦個股 → 模擬隔日買進 → 對比大盤衡量效益。來源:Podwise(逐字稿)+ FinMind(股價)。")

# ===== podcast-level KPIs =====
n_ep = w["episode_id"].nunique()
n_rec = len(w)
n_stock = w["ticker"].replace("", np.nan).dropna().nunique()
wavg90 = weighted_excess(w, "excess_90d")
c1, c2, c3, c4 = st.columns(4)
c1.metric("集數", n_ep)
c2.metric("推薦數", n_rec)
c3.metric("提及個股", int(n_stock))
c4.metric("加權 90 天超額", fmt_pct(wavg90), help="信心度加權、方向對齊的平均 alpha")

# ===== 個股彙整 (aggregate by stock) =====
st.subheader("🏷️ 個股彙整(依提及頻率 × 信心度加權)")

named = w[w["ticker"].notna() & (w["ticker"] != "")].copy()
if named.empty:
    st.info("此節目尚無可彙整的個股(推薦均無 ticker)。")
    st.stop()

rows = []
for tic, g in named.groupby("ticker"):   # group by ticker so name variants merge
    name = g["company_name"].mode().iloc[0] if not g["company_name"].mode().empty else g["company_name"].iloc[0]
    mkt = g["market"].mode().iloc[0] if not g["market"].mode().empty else g["market"].iloc[0]
    rows.append({
        "ticker": tic, "company_name": name, "market": mkt,
        "mentions": len(g),
        "episodes": g["episode_id"].nunique(),
        "net_strength": g["signed_strength"].sum(),
        "avg_conviction": g["conviction_weight"].mean(),
        "stances": "/".join(sorted(g["stance"].unique())),
        "w_excess_30d": weighted_excess(g, "excess_30d"),
        "w_excess_90d": weighted_excess(g, "excess_90d"),
        "last_mention": g["publish_date"].max(),
    })
agg = pd.DataFrame(rows).sort_values(["net_strength", "mentions"], ascending=False).reset_index(drop=True)

left, right = st.columns([3, 2])
with left:
    st.caption("點選一列、或用下方「個股明細」的下拉選單,即可切換個股")
    event = st.dataframe(
        agg[["company_name", "ticker", "mentions", "episodes", "net_strength",
             "avg_conviction", "stances", "w_excess_90d", "last_mention"]],
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
        column_config={
            "company_name": "公司", "ticker": "代碼", "mentions": "提及次數",
            "episodes": "集數", "net_strength": st.column_config.NumberColumn("淨推薦強度", format="%.2f"),
            "avg_conviction": st.column_config.NumberColumn("平均信心", format="%.2f"),
            "stances": "立場", "last_mention": "最近提及",
            "w_excess_90d": st.column_config.NumberColumn("加權90天超額", format="%.1f%%"),
        },
    )
with right:
    st.caption("推薦強度 vs 90 天加權效益(泡泡大小=提及次數)")
    bub = agg.dropna(subset=["w_excess_90d"]).copy()
    if not bub.empty:
        chart = alt.Chart(bub).mark_circle(opacity=0.7).encode(
            x=alt.X("net_strength:Q", title="淨推薦強度"),
            y=alt.Y("w_excess_90d:Q", title="加權90天超額", axis=alt.Axis(format="%")),
            size=alt.Size("mentions:Q", title="提及次數", scale=alt.Scale(range=[60, 600])),
            color=alt.Color("market:N", title="市場"),
            tooltip=["company_name", "ticker", "mentions",
                     alt.Tooltip("net_strength:Q", format=".2f"),
                     alt.Tooltip("w_excess_90d:Q", format=".1%")],
        ).properties(height=300)
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("尚無已計算效益(可能 horizon 未到期)。")

# ===== 個股明細 (drill-down) =====
# Switch via an explicit selectbox; clicking a table row also switches (change-detected so a
# manual selectbox pick is not overridden on the next rerun).
labels = [f"{r.company_name} ({r.ticker})" for r in agg.itertuples()]
if st.session_state.get("sel_stock") not in labels:   # podcast changed / first run
    st.session_state.pop("sel_stock", None)
sel_rows = event.selection.rows if event and event.selection else []
if sel_rows:
    clicked = labels[sel_rows[0]]
    if st.session_state.get("_last_click") != clicked:
        st.session_state["_last_click"] = clicked
        st.session_state["sel_stock"] = clicked

st.subheader("📉 個股明細")
sel_label = st.selectbox("選擇個股", labels, key="sel_stock")
sel_idx = labels.index(sel_label)
sel_ticker = agg.iloc[sel_idx]["ticker"]
sel_name = agg.iloc[sel_idx]["company_name"]

px = q("SELECT date, open, high, low, close, adj_close, volume FROM prices WHERE ticker = ? ORDER BY date", [sel_ticker])
mentions = named[named["ticker"] == sel_ticker].sort_values("publish_date")

if px.empty:
    st.info("此個股尚無股價資料,請先跑 fetch_prices.py。")
else:
    px["date"] = pd.to_datetime(px["date"])
    has_ohlc = px[["open", "high", "low"]].notna().all(axis=None)

    opt1, opt2 = st.columns([2, 3])
    with opt1:
        ctype = st.radio("圖表類型", (["K 線", "折線(收盤)"] if has_ohlc else ["折線(收盤)"]),
                         horizontal=True)
    with opt2:
        show_adj = st.checkbox("疊加還原收盤線(報酬計算基準)", value=not has_ohlc)

    fig = go.Figure()
    if ctype == "K 線" and has_ohlc:
        fig.add_trace(go.Candlestick(
            x=px["date"], open=px["open"], high=px["high"], low=px["low"], close=px["close"],
            name="K 線", increasing_line_color="#d62728", decreasing_line_color="#2ca02c"))
    else:
        fig.add_trace(go.Scatter(x=px["date"], y=px["close"], mode="lines",
                                 name="收盤", line=dict(color="#1f77b4", width=2)))
    if show_adj:
        fig.add_trace(go.Scatter(x=px["date"], y=px["adj_close"], mode="lines",
                                 name="還原收盤", line=dict(color="#ff7f0e", width=1, dash="dot")))
    # mark each mention's buy_date
    for _, m in mentions.iterrows():
        if pd.notnull(m["buy_date"]):
            bd = pd.to_datetime(m["buy_date"])
            fig.add_vline(x=bd, line_width=1, line_dash="dash", line_color="#888")
            fig.add_annotation(x=bd, y=1, yref="paper", showarrow=False, yanchor="bottom",
                               text=f"{m['stance']}·{HORIZON_LABELS.get(m['horizon'],'')}",
                               font=dict(size=10, color="#555"))
    fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0),
                      xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    st.plotly_chart(fig, use_container_width=True)

st.caption(f"此個股在「{podcast}」被提及 {len(mentions)} 次:")
md = mentions[["publish_date", "title", "stance", "horizon", "conviction",
               "excess_90d", "evidence_timestamp", "evidence_quote", "speaker"]].copy()
st.dataframe(
    md, use_container_width=True, hide_index=True,
    column_config={
        "publish_date": "發布日", "title": "集數", "stance": "立場", "horizon": "期間",
        "conviction": "信心", "evidence_timestamp": "時間軸", "evidence_quote": "逐字稿原文",
        "speaker": "講者",
        "excess_90d": st.column_config.NumberColumn("90天超額", format="%.1f%%"),
    },
)

# ===== 單一集數分析 (optional sub-category) =====
st.divider()
with st.expander("🎧 單一集數分析（選用）", expanded=False):
    # All episodes for this podcast — including ones with 0 recommendations,
    # so the Podwise summary is still browsable. Rec counts come from w (v_weighted).
    eps = q(
        "SELECT episode_id, publish_date, title, episode_url, summary "
        "FROM episodes WHERE podcast_name = ? ORDER BY publish_date DESC",
        [podcast],
    )
    rec_counts = w.groupby("episode_id").size()
    eps["n_rec"] = eps["episode_id"].map(rec_counts).fillna(0).astype(int)

    only_with_recs = st.checkbox("只顯示有推薦的集數", value=False)
    shown = eps[eps["n_rec"] > 0] if only_with_recs else eps
    if shown.empty:
        st.info("此節目沒有任何含推薦的集數。")
        st.stop()

    shown = shown.copy()
    shown["label"] = (
        shown["publish_date"].astype(str)
        + " · " + shown["title"].str.slice(0, 50)
        + shown["n_rec"].map(lambda n: f"（{n} 推薦）" if n else "（無推薦）")
    )
    pick = st.selectbox("選擇集數", shown["label"])
    erow = shown[shown["label"] == pick].iloc[0]
    st.markdown(f"**{erow['title']}** · {erow['publish_date']} · [Podwise]({erow['episode_url']})")
    if erow["summary"]:
        with st.expander("Podwise 摘要", expanded=erow["n_rec"] == 0):
            st.write(erow["summary"])
    er = w[w["episode_id"] == erow["episode_id"]].sort_values("evidence_timestamp")
    st.caption(f"推薦 {len(er)} 筆")
    for _, rr in er.iterrows():
        st.markdown(f"**{rr['company_name']}** `{rr['ticker'] or '—'}` · {rr['stance']} / {rr['horizon']} / {rr['conviction']}"
                    + (f" · 90天超額 {fmt_pct(rr['excess_90d'])}" if pd.notnull(rr["excess_90d"]) else ""))
        st.caption(f"🕘 {rr['evidence_timestamp']} · {rr['speaker'] or ''} — {rr['rationale']}")
        st.markdown(f"> {rr['evidence_quote']}")
