# Podstock Tracker

[English](README.md) | **正體中文**

追蹤財經 Podcast 上喊出的個股，量化「跟著買到底有沒有用」。目前從 **股癌 Gooaye** 開始。

每一集的逐字稿(透過 [Podwise](https://podwise.ai))由一個 subagent 閱讀，抽出每一檔被推薦的
股票 —— 含**立場(buy/sell/hold/avoid/watch)、期間(短/中/長線)、信心度**，以及一段**逐字
的逐字稿引文 + 時間戳，供查證**。這些標的存進 DuckDB，接著模擬在該集播出**隔一個交易日**買進，
計算短/中/長期報酬，以及相對大盤的超額報酬(alpha)。最後用一個本地 Streamlit dashboard 瀏覽全部。

```
Podwise CLI ──► 逐字稿 + 摘要 + metadata
                       │
                  subagent(抽取契約)
                       │  結構化 JSON(ticker、立場、期間、引文+時間戳)
                       ▼
                  DuckDB  ◄── FinMind 日線價(台股還原權息)+ 大盤指數
                       │
                  隔日買進報酬 + alpha ──► Streamlit dashboard
```

## 快速開始

```bash
# 1. 一次性:複製 env 範本並填入你的 FinMind token
cp .env.example .env        # 然後編輯 FINMIND_TOKEN(免費 token：https://finmindtrade.com/)

# 2. 啟動本地 dashboard(http://localhost:8501)
just dash
```

各項指令(recipe)用 [just](https://github.com/casey/just) 執行(`brew install just`);直接打
`just` 不帶參數就會列出全部。另一個前置需求是 [uv](https://docs.astral.sh/uv/) —— 它會按需安裝
每支腳本的依賴(以 PEP 723 inline 方式宣告),所以**不需要手動 `pip install`**。DuckDB 檔案會在
第一次 ingest 時自動建立於 `data/podstock.duckdb`。

## 專案結構

引擎是一個自包含的 **Claude Code Skill**,放在 `.claude/skills/podstock/` —— skill 把自己的
scripts、references、workflows 和 dashboard 綁在一起,維持可攜性。專案根目錄則放進入點與設定。

```
.
├── README.md            ← 英文版
├── README.zh-TW.md      ← 你正在看這份(正體中文)
├── CLAUDE.md            ← 給 Claude Code session 的操作須知
├── Justfile             ← 任務指令(just dash · just prices · just compute · …)
├── requirements.txt     ← 依賴清單(uv 自動安裝)
├── .env / .env.example  ← FINMIND_TOKEN(已 gitignore)
├── data/
│   ├── episodes/<節目>/*.json  ← 各節目的作者抽取個股,git 追蹤(source of truth)
│   └── podstock.duckdb         ← 可重建的快取(已 gitignore)
└── .claude/skills/podstock/
    ├── SKILL.md             ← skill 進入點 / workflow 路由(source of truth)
    ├── workflows/           ← ingest-episode · track-performance · analyze · dashboard
    ├── references/          ← schema.md · extraction.md · weighting.md
    ├── scripts/             ← store.py · fetch_prices.py · compute_performance.py · query.py · schema.sql
    └── dashboard/app.py     ← Streamlit web UI
```

## Python 環境:uv + inline 依賴

這個專案**不需要建立 virtualenv、也不需要跑 `pip install`**。它靠 [uv](https://docs.astral.sh/uv/)
加上一個 Python 標準 —— **PEP 723「inline script metadata」**。每支獨立腳本都在檔案頂端用一段
註解宣告自己的依賴,例如 `scripts/fetch_prices.py`:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb>=1.0", "pandas>=2.0", "requests>=2.31"]
# ///
```

當你執行 `uv run scripts/fetch_prices.py`,uv 會讀這段區塊、建立一個只裝這些套件的**暫存環境**
(快取在 `~/.cache/uv`,第一次之後幾乎瞬間),跑完腳本,而且完全不動到你的全域 Python。為什麼
這樣做,而不是用單一的 `pyproject.toml` + `.venv`:

- **每支腳本各自隔離** —— `query.py` 只需要 `duckdb`,不會被硬塞 streamlit/plotly。
- **自包含、可攜** —— 把單一腳本複製到別處,`uv run` 它就能跑;依賴跟著程式碼走,不必先做專案設定。
- **零環境管理** —— 沒有 `.venv/` 要建立、啟用、gitignore 或定期同步。

一句話:inline metadata 把「要哪些依賴」從**專案層級**降到**單檔層級**。這也是為什麼這裡的
`requirements.txt` 是給人看的方便清單,而不是要你手動安裝的東西。

**唯一的例外 —— dashboard。** `dashboard/app.py` 是被 `streamlit run` 啟動的,而不是
`uv run app.py`,所以 uv 沒辦法讀它的 inline 區塊(uv 只會解析「它直接執行的那支腳本」的 inline
metadata)。因此 dashboard 的依賴改放在 `requirements.txt`,由 Justfile 的 `dash` recipe 以
`uv run --with-requirements requirements.txt streamlit run …` 餵進去 —— 一樣是暫存環境的概念,
只是來源從註解區塊換成一個檔案。

之後若想**鎖定確切版本**(inline 區塊只記 `>=` 下限),uv 可以幫腳本就地上鎖:
`uv lock --script scripts/fetch_prices.py`。另外 `uv add --script scripts/fetch_prices.py <套件>`
會直接幫你改寫某支腳本的 inline 依賴。

## 操作資料

以下指令都從專案根目錄執行。平常是透過 Claude Code 驅動(由 skill 路由工作),但也可以用 `just`
手動跑:

```bash
just store /tmp/episode.json     # 存入一集已抽取的 episode JSON              (寫入)
just prices                      # 為資料庫裡所有 ticker + 大盤指數抓價         (寫入)
just compute                     # 計算隔日買進報酬 + alpha                    (寫入)
just query "SELECT * FROM v_weighted LIMIT 20"   # 臨時的唯讀 SQL              (唯讀)
```

每個 recipe 都只是 `uv run .claude/skills/podstock/scripts/<script>.py` 的薄包裝 —— 確切指令
見 [Justfile](Justfile)。

> **DuckDB 是單寫(single-writer)。** dashboard 執行中會持有讀鎖,所以**跑任何寫入 recipe 前要先
> 把它停掉**(`just store` / `just prices` / `just compute`),否則會撞到 lock error;寫完再用
> `just dash` 重新啟動。

資料模型(資料表 `episodes`、`recommendations`、`prices`、`dividends`、`performance`,以及
`v_performance` / `v_weighted` 兩個 view)記錄在
[references/schema.md](.claude/skills/podstock/references/schema.md)。dashboard 使用的
頻率 × 信心度加權,說明在
[references/weighting.md](.claude/skills/podstock/references/weighting.md)。

## 備份與同步

`data/podstock.duckdb` 是**可重建的快取,不納入版控**。真正的 source of truth 是作者資料 ——
每一集抽取出的個股 —— 匯出成 **`data/episodes/<節目>/`** 底下的逐集 JSON(依節目分層,集數編號
就不會跨節目撞名),**這個目錄才進 git**。價格、股利、績效都是衍生資料(從 FinMind 重抓、重算),
所以不存。

```bash
just export     # DB → data/episodes/<節目>/*.json   (ingest 完跑一次,然後 commit)
just rebuild    # data/episodes/<節目>/*.json → DB,接著重抓價格 + 重算
```

跨機器同步:commit `data/episodes/` 並 push;另一台機器 pull 之後跑 `just rebuild`。JSON 小又
可 diff,git 會清楚顯示每一集改了什麼,而且**完全沒有弄壞 live 資料庫的風險** —— **不要把
`.duckdb` 本身丟進 Dropbox/iCloud/Drive**,資料夾同步可能在寫入中途弄壞單寫資料庫,或在兩台
機器開啟時產生 conflict copy。

> `just export` 是唯讀(隨時可跑);`just rebuild` 會寫入,所以要先停掉 dashboard。

## 注意事項與限制

- **價格**來自 FinMind。台股已針對現金/股票股利做還原(免費版沒有 還原股價 資料集)。大盤指數:
  `^TWII`(台股報酬指數)、`^GSPC`(美股)。**日股 ticker 不支援** FinMind 的路由 —— 會存進來但
  不計價。
- **只記錄具體的個別證券。** 含糊的題材/類股談論(「光通訊類股」、「AI 概念股」)會刻意忽略 ——
  「提到」不等於「叫你買」,對某個類股有看法也不算一筆推薦。
- 較長期間(90/365 天)在集數還沒走完前樣本數很小 —— 隨時間重跑 `compute_performance.py` 把它
  們補滿。看每個數字時,都要連同它的樣本數一起看。
