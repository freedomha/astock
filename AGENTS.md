# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## Project Overview

A-share quantitative analysis workspace producing sector and ETF research reports. Not a traditional software project — no package manager, build system, or test suite. All logic lives in standalone Python scripts under `.workbuddy/skills/`. Data source is Tencent 自选股 via the `westock-data` Node.js CLI. Output is self-contained HTML reports with Chart.js/ECharts visualizations.

Two categories of skills exist:
- **Sector scanners** (1 skill): bowl-bottom pattern scanning on 861 industry/concept sectors
- **ETF scanners** (6 skills): bowl-bottom, box-consolidation, W-bottom, head-shoulder-bottom, 2B-bottom pattern scanning + T2区间 state-machine scanning on 352 largest A-share ETFs
- **Deep analysis** (2 skills): sell-side quality research reports for individual sectors or ETFs

## Environment & Prerequisites

```
PYTHON=/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3
NODE=/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node
WD=/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data
WESTOCK=$WD/scripts/index.js
```

All Python scripts use only the standard library (`json`, `subprocess`, `sys`, `os`, `time`, `concurrent.futures`, `collections`).

## Key Commands

### Sector Scanners

```bash
# Bowl-bottom sector scan — fetches K-lines + scores 861 sectors, outputs bowl_bottom_results.json + sector_kline_data.json
$PYTHON .workbuddy/skills/bowl-bottom-sector-scanner/analyze.py

# Generate HTML report from scan results → reports/sectors/sector_bowl_report.html
$PYTHON .workbuddy/skills/bowl-bottom-sector-scanner/generate_report.py
```

### ETF Scanners

```bash
# ETF Bowl-Bottom — analyze + generate report
$PYTHON .workbuddy/skills/etf-bowl-bottom-scanner/analyze.py
$PYTHON .workbuddy/skills/etf-bowl-bottom-scanner/generate_report.py
$PYTHON .workbuddy/skills/etf-bowl-bottom-scanner/backtest.py  # optional backtest

# ETF Box Consolidation — analyze + generate report
$PYTHON .workbuddy/skills/etf-box-scanner/analyze.py
$PYTHON .workbuddy/skills/etf-box-scanner/generate_report.py

# ETF W-Bottom — analyze + generate report + backtest
$PYTHON .workbuddy/skills/etf-w-bottom-scanner/analyze.py
$PYTHON .workbuddy/skills/etf-w-bottom-scanner/generate_report.py
$PYTHON .workbuddy/skills/etf-w-bottom-scanner/backtest.py

# ETF Head-Shoulder Bottom — analyze + generate report + backtest
$PYTHON .workbuddy/skills/etf-head-shoulder-bottom-scanner/analyze.py
$PYTHON .workbuddy/skills/etf-head-shoulder-bottom-scanner/generate_report.py
$PYTHON .workbuddy/skills/etf-head-shoulder-bottom-scanner/backtest.py [kline_file]

# ETF 2B Bottom — analyze + generate report + backtest (standard + 500-day variants)
$PYTHON .workbuddy/skills/etf-2b-bottom-scanner/analyze.py
$PYTHON .workbuddy/skills/etf-2b-bottom-scanner/generate_report.py
$PYTHON .workbuddy/skills/etf-2b-bottom-scanner/backtest.py
$PYTHON .workbuddy/skills/etf-2b-bottom-scanner/backtest_500.py

# ETF T2区间 — analyze + generate report (T0-T8状态机, 筛出T2底部构建)
$PYTHON .workbuddy/skills/etf-t2-scanner/analyze.py
$PYTHON .workbuddy/skills/etf-t2-scanner/generate_report.py

# ETF Operation Plan — 趋势状态机回测（状态信号统计 + 硬约束策略模拟，含交易成本）
$PYTHON .workbuddy/skills/etf-operation-plan/backtest.py
$PYTHON .workbuddy/skills/etf-operation-plan/backtest.py --use-confirmed  # 暴露上调需连续2周确认
$PYTHON .workbuddy/skills/etf-operation-plan/backtest.py --code sh518880   # 单只ETF
$PYTHON .workbuddy/skills/etf-operation-plan/backtest.py --commission-rate 0.00025 --min-commission 5 --half-spread 0.0005 --position-value 30000  # 覆盖成本参数/名义本金
```

**Refresh intraday data (盘中刷新):** Append `--refresh` to any ETF `analyze.py` to force-refresh the latest trading day's kline bars. Use this after 15:00 when the cached data was fetched during market hours (e.g., 10:30 fetch). Without the flag, same-date bars are considered current and skipped.

```bash
# Run ETF scanner with intraday-to-close refresh
$PYTHON .workbuddy/skills/etf-bowl-bottom-scanner/analyze.py --refresh
```

### Data Fetching

```bash
# One-time fetch: enumerate all 830 Juyuan concept sectors + their 250-day K-lines
$PYTHON fetch_all_concepts.py

# Fetch 500-day K-lines for all ETFs (extended data for backtests)
$PYTHON fetch_500.py
```

### westock-data CLI (for deep analysis)

```bash
$NODE $WESTOCK sector search <板块名>              # Find sector code
$NODE $WESTOCK sector constituent <code> --raw     # List constituents
$NODE $WESTOCK kline <code> --period day --limit 250 --raw  # Fetch K-line
$NODE $WESTOCK quote sh601919,sh600026 --raw       # Batch quote (returns BatchResult wrapper)
$NODE $WESTOCK finance <code> --type lrb --num 5 --raw  # Financial statements
$NODE $WESTOCK consensus <code> --raw              # Analyst consensus estimates
$NODE $WESTOCK rating <code> --raw                 # Institutional ratings
$NODE $WESTOCK report <code> --limit 3 --raw       # Latest research report titles
$NODE $WESTOCK macro indicator pmi --year 2025 --raw  # Macro indicators
```

## Architecture & Data Flow

```
westock-data CLI (Node.js) → raw JSON → Python scripts → processed JSON → HTML reports
```

### Skill Inventory

| Skill | Directory | Scripts | Target | Output |
|-------|-----------|---------|--------|--------|
| Bowl-Bottom Sector | `bowl-bottom-sector-scanner/` | analyze.py (495L), generate_report.py (257L) | 861 sectors | bowl_bottom_results.json |
| ETF Bowl-Bottom | `etf-bowl-bottom-scanner/` | analyze.py (573L), generate_report.py (260L), backtest.py (529L) | 352 ETFs | etf_bowl_results.json |
| ETF Box | `etf-box-scanner/` | analyze.py (693L), generate_report.py (315L) | 352 ETFs | etf_box_results.json |
| ETF W-Bottom | `etf-w-bottom-scanner/` | analyze.py (597L), generate_report.py (264L), backtest.py (178L) | 352 ETFs | etf_w_bottom_results.json |
| ETF HS Bottom | `etf-head-shoulder-bottom-scanner/` | analyze.py (821L), generate_report.py (415L), backtest.py (232L) | 352 ETFs | etf_hs_bottom_results.json |
| ETF 2B Bottom | `etf-2b-bottom-scanner/` | analyze.py (807L), generate_report.py (295L), backtest.py (516L), backtest_500.py (471L) | 352 ETFs | etf_2b_bottom_results.json |
| ETF T2区间 | `etf-t2-scanner/` | analyze.py (T0-T8状态机+5维置信度), generate_report.py | 352 ETFs | etf_t2_results.json |
| ETF Operation Plan | `etf-operation-plan/` | trend_analysis.py (844L), score_patterns.py (2056L), operation_engine.py (363L), backtest.py (577L) | 1 held ETF | reports/etf/operation/*-操作建议.html + backtest_trend_state_results.json |
| Sector Deep Analysis | `sector-deep-analysis/` | AI-driven, no scripts | 1 sector | reports/sectors/<name>.html |
| ETF Deep Analysis | `etf-deep-analysis/` | AI-driven, no scripts | 1 ETF | reports/etf/<name>.html |

All ETF scanners share common infrastructure: input from `all_etfs_larggest.json` (352 largest ETFs), K-line data from `etf_kline_data.json` (250-day) or `etf_kline_data_500.json` (500-day), and output HTML to `reports/etf/`.

### 1. Bowl-Bottom Sector Scanner (`bowl-bottom-sector-scanner/`)

Quantitatively scans 861 A-share sectors for saucer-bottom (碗底) chart patterns.

- **`SKILL.md`** — Skill definition: workflow steps, v2 enhanced scoring engine specs (8 dimensions, max 100 points), label grading system (确认碗底/碗底确认中/减速筑底/低位盘整/下跌中继/观望)
- **`analyze.py`** (495 lines) — Main engine: `run_westock()`, `fetch_kline()`, `load_sectors()`, `lin_slope()`, `quadratic_fit()`, `atr()`, `analyze_bowl_bottom()`, `main()`. Loads sector codes from bundled `all_concept_sectors.json` + local `sw1_sectors.json`, fetches 250-day K-lines in parallel (8 workers, 4+6 retries), scores each sector, outputs `bowl_bottom_results.json` + `sector_kline_data.json`
- **`generate_report.py`** (257 lines) — Reads JSON results, builds HTML with Chart.js sparklines, TOP25 ranking table, detailed analysis cards → `reports/sectors/sector_bowl_report.html`
- **`all_concept_sectors.json`** (101 KB) — 830 Juyuan concept sector codes (industry 721 + style 78 + area 31), bundled with the skill

Key scoring engine logic: A true bowl-bottom requires (1) price near range low, (2) prior decline now decelerating (decel_ratio < 0.8), (3) recent higher lows forming. Penalties: recent crash (20d < -8%) → -15pts; near highs (drawdown > -5%) → -20pts.

### 2. ETF Bowl-Bottom Scanner (`etf-bowl-bottom-scanner/`)

Same 8-dimension scoring engine as the sector version, applied to 352 ETFs. Labels: 确认碗底/碗底确认中/减速筑底/低位盘整/下跌中继/观望. Backtest module included (250-day and 500-day variants).

### 3. ETF Box Scanner (`etf-box-scanner/`)

Detects box-consolidation patterns for medium-term swing trading (中线差价). Requires range width 8-20%, flat trend, multiple support/resistance touches. Rewards high-confidence box ranges from both 40d and 90d windows. Labels: 确认箱体(中长)/确认箱体(中期)/箱顶观望/窄幅收敛/宽幅震荡/下跌趋势/趋势行情. No backtest module.

### 4. ETF W-Bottom Scanner (`etf-w-bottom-scanner/`)

Phase-based W-bottom detection pipeline: prior decline → left trough → peak recovery → right trough validation → breakout status. Labels: W底确认/W底形成中/W底候选/非W底. 8-dimension scoring (max ~97 pts). Reuses shared `etf_kline_data.json`.

### 5. ETF Head-Shoulder Bottom Scanner (`etf-head-shoulder-bottom-scanner/`)

Finds 5-point geometric structure: Left Shoulder → Peak1 → Head → Peak2 → Right Shoulder with neckline (头肩底). v2 optimizations: tighter neckline slope (+-7%), tighter shoulder spread (15%), heavier neckline weight. Labels: 头肩底确认/头肩底形成中/头肩底候选/非头肩底. Backtest: 头肩底确认 has 67.3% 20d win rate with +0.73% excess vs baseline.

### 6. ETF 2B Bottom Scanner (`etf-2b-bottom-scanner/`)

Detects false breakdowns where price breaks below prior 60-day low then recovers within 2 days (Victor Sperandeo 2B rule). v3 adds quality pre-filter (recovery >= 0.75%, volume contraction < 0.8, prior decline 5-15%). v2 adds 2-yang confirmation (2 bullish bars after recovery). Labels: 2B买入确认/2B买入候选(已确认)/2B观察(已确认) and various 待2阳确认 variants. Two backtest variants: 250-day and 500-day (`backtest_500.py`).

### 7. Sector Deep Analysis (`sector-deep-analysis/`)

Produces sell-side quality HTML research reports for a specific sector.

- **`SKILL.md`** — 9-step workflow: read parsing reference → identify sector → get timing (bowl-bottom/position) → company-level data (quote/finance/consensus/rating/report) → macro context → catalysts/news → 7-layer analysis framework → produce HTML report → write memory
- **`references/westock-data-parsing.md`** (453 lines) — Critical JSON parsing patterns for every westock-data command, including pitfalls (BatchResult wrapper, newest-first kline, duplicate constituents, uppercase field names)

### 8. ETF Deep Analysis (`etf-deep-analysis/`)

Produces sell-side quality HTML research reports for a specific ETF.

- **`SKILL.md`** — 10-step AI-driven workflow: identify ETF → fetch quote/K-line → compute bowl-bottom timing → WebSearch holdings/sector allocation → fund flow + discount/premium → peer ETF comparison → theme catalysts/news → 7-layer analysis framework → produce HTML report → present summary
- **`references/westock-data-parsing.md`** — JSON parsing reference (shared with sector version)

The 7-layer analysis framework: core logic → trading position → catalyst intensity → fund preference → crowding & valuation → style rotation → explicit ranking. Must identify a **variant perception** (what the market is mispricing).

## Critical Conventions

### westock-data Usage
- **Must use `dangerouslyDisableSandbox: true`** in Bash tool calls — the sandbox blocks network, causing empty results
- **Data source has high transient failure rates** — always retry (up to 10x), reject `success:false`, empty arrays, and `null` strings
- **Concept sector codes (pt02GNxxxx) cannot be used directly for K-lines** — they return `[]`. Use constituent stock K-lines to build an equal-weight/market-cap-weighted index instead. Shenwan industry codes (pt0180xxxx) work normally
- `WD` and `NODE` environment variables do not persist across Bash calls — always use absolute paths
- **Kline data fetched during market hours is intraday (盘中):** the `update_kline_data()` logic only compares dates, so a same-date bar fetched at 10:30 won't be refreshed at 15:01. Use `--refresh` to force-replace today's bar with post-close data.

### JSON Parsing Quirks (see `references/westock-data-parsing.md` for full details)
- `quote --raw` with multiple codes returns `{success, status, data: [{symbol, data: {...}}], errors, metadata}` — NOT a plain list
- `finance --raw` returns a flat list (not nested in sections) — pick first element with non-null fields
- `consensus --raw` returns year-keyed dicts (2026/2027/2028) — extract forward estimates from the earliest year
- K-line data is **newest-first**

### Report Conventions
- **A-share color convention: red = up (涨), green = down (跌)** — opposite to US/EU markets
- Reports use sell-side style tags: 超配/标配/低配/左侧/回避 for allocation; 加仓/减仓/清仓 for position actions
- HTML reports: light background (gradient header in sector-related color), dark text, ECharts for charts, red-up/green-down text coloring
- Report naming: `<板块名>板块深度分析-YYYYMMDD.html` for sectors, `<ETF简称>ETF深度分析-YYYYMMDD.html` for ETFs
- **JS syntax check required** before delivering any HTML report: `node --check /tmp/_check.js` on extracted inline scripts

## Project Files

### Root-Level Scripts

| File | Lines | Purpose |
|------|-------|---------|
| `fetch_all_concepts.py` | 127 | One-time: enumerate all concept sectors + fetch K-lines |
| `fetch_500.py` | 98 | Fetch 500-day extended K-lines for all ETFs (for backtests) |

### Root-Level Data Files

| File | Size | Purpose |
|------|------|---------|
| `all_etfs.json` | 119 KB | Complete list of A-share ETFs |
| `all_etfs_larggest.json` | 47 KB | 352 largest ETFs (input for all ETF scanners) |
| `etf_kline_data.json` | 11.5 MB | 250-day K-line data for all ETFs (shared across scanners) |
| `etf_kline_data_500.json` | 21.4 MB | 500-day extended K-line data (for backtests) |
| `etf_bowl_backtest_results.json` | 606 KB | Bowl-bottom backtest (250-day) |
| `etf_bowl_backtest_500_results.json` | 3.97 MB | Bowl-bottom backtest (500-day) |
| `etf_2b_backtest_500_results.json` | 3.43 MB | 2B bottom backtest (500-day) |

### Skill Directory Data Files

| File | Size | Purpose |
|------|------|---------|
| `bowl-bottom-sector-scanner/bowl_bottom_results.json` | 704 KB | Scored + labeled results for 842 sectors |
| `bowl-bottom-sector-scanner/sector_kline_data.json` | 30 MB | Raw 250-day K-line data for all sectors |
| `bowl-bottom-sector-scanner/all_concept_sectors.json` | 101 KB | 830 Juyuan concept sector codes (bundled) |
| `etf-bowl-bottom-scanner/etf_bowl_results.json` | 280 KB | ETF bowl-bottom scan results |
| `etf-box-scanner/etf_box_results.json` | 364 KB | ETF box-consolidation scan results |
| `etf-w-bottom-scanner/etf_w_bottom_results.json` | 35 KB | ETF W-bottom scan results |
| `etf-w-bottom-scanner/backtest_w_bottom_results.json` | 381 KB | W-bottom backtest results |
| `etf-head-shoulder-bottom-scanner/etf_hs_bottom_results.json` | 178 KB | ETF HS bottom scan results |
| `etf-head-shoulder-bottom-scanner/hs_bottom_backtest_results.json` | 3 KB | HS bottom backtest results |
| `etf-2b-bottom-scanner/etf_2b_bottom_results.json` | 5 KB | ETF 2B bottom scan results |
| `etf-t2-scanner/etf_t2_results.json` | 411 KB | ETF T2区间(T0-T8状态机) scan results |

### Report Output

| Directory | Contents |
|-----------|----------|
| `reports/sectors/` | Sector bowl report + deep analysis reports |
| `reports/etf/` | 6 × scanner reports (`etf_*_report.html`) + ETF deep analysis reports |

### Trade Records

| Directory | Contents |
|-----------|----------|
| `records/etf/` | Persistent position records for tracked ETFs |
