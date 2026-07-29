# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## Project Overview

A-share quantitative analysis workspace producing sector research reports. Not a traditional software project — no package manager, build system, or test suite. All logic lives in standalone Python scripts under `.workbuddy/skills/`. Data source is Tencent 自选股 via the `westock-data` Node.js CLI. Output is self-contained HTML reports with Chart.js/ECharts visualizations.

## Environment & Prerequisites

```
PYTHON=/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3
NODE=/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node
WD=/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data
WESTOCK=$WD/scripts/index.js
```

All Python scripts use only the standard library (`json`, `subprocess`, `sys`, `os`, `time`, `concurrent.futures`, `collections`).

## Key Commands

```bash
# Bowl-bottom sector scan — fetches K-lines + scores 861 sectors, outputs bowl_bottom_results.json + sector_kline_data.json
$PYTHON .workbuddy/skills/bowl-bottom-sector-scanner/analyze.py

# Generate HTML report from scan results → sector_bowl_report.html
$PYTHON .workbuddy/skills/bowl-bottom-sector-scanner/generate_report.py

# One-time fetch: enumerate all 830 Juyuan concept sectors + their 250-day K-lines
$PYTHON fetch_all_concepts.py

# Call westock-data CLI directly (for sector deep analysis):
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

The project is organized around two AI skills (defined in `.workbuddy/skills/`):

### 1. Bowl-Bottom Sector Scanner (`bowl-bottom-sector-scanner/`)

Quantitatively scans 861 A-share sectors for saucer-bottom (碗底) chart patterns.

- **`SKILL.md`** — Skill definition: workflow steps, v2 enhanced scoring engine specs (8 dimensions, max 100 points), label grading system (确认碗底/碗底确认中/减速筑底/低位盘整/下跌中继/观望)
- **`analyze.py`** (496 lines) — Main engine: `run_westock()`, `fetch_kline()`, `load_sectors()`, `lin_slope()`, `quadratic_fit()`, `atr()`, `analyze_bowl_bottom()`, `main()`. Loads sector codes from bundled `all_concept_sectors.json` + local `sw1_sectors.json`, fetches 250-day K-lines in parallel (8 workers, 4+6 retries), scores each sector, outputs `bowl_bottom_results.json` + `sector_kline_data.json`
- **`generate_report.py`** (257 lines) — Reads JSON results, builds HTML with Chart.js sparklines, TOP25 ranking table, detailed analysis cards → `sector_bowl_report.html`
- **`all_concept_sectors.json`** (101 KB) — 830 Juyuan concept sector codes (industry 721 + style 78 + area 31), bundled with the skill

Key scoring engine logic: A true bowl-bottom requires (1) price near range low, (2) prior decline now decelerating (decel_ratio < 0.8), (3) recent higher lows forming. Penalties: recent crash (20d < -8%) → -15pts; near highs (drawdown > -5%) → -20pts.

### 2. Sector Deep Analysis (`sector-deep-analysis/`)

Produces sell-side quality HTML research reports for a specific sector.

- **`SKILL.md`** — 9-step workflow: read parsing reference → identify sector → get timing (bowl-bottom/position) → company-level data (quote/finance/consensus/rating/report) → macro context → catalysts/news → 7-layer analysis framework → produce HTML report → write memory
- **`references/westock-data-parsing.md`** (453 lines) — Critical JSON parsing patterns for every westock-data command, including pitfalls (BatchResult wrapper, newest-first kline, duplicate constituents, uppercase field names)

The 7-layer analysis framework: core logic → trading position → catalyst intensity → fund preference → crowding & valuation → style rotation → explicit ranking. Must identify a **variant perception** (what the market is mispricing).

## Critical Conventions

### westock-data Usage
- **Must use `dangerouslyDisableSandbox: true`** in Bash tool calls — the sandbox blocks network, causing empty results
- **Data source has high transient failure rates** — always retry (up to 10x), reject `success:false`, empty arrays, and `null` strings
- **Concept sector codes (pt02GNxxxx) cannot be used directly for K-lines** — they return `[]`. Use constituent stock K-lines to build an equal-weight/market-cap-weighted index instead. Shenwan industry codes (pt0180xxxx) work normally
- `WD` and `NODE` environment variables do not persist across Bash calls — always use absolute paths

### JSON Parsing Quirks (see `references/westock-data-parsing.md` for full details)
- `quote --raw` with multiple codes returns `{success, status, data: [{symbol, data: {...}}], errors, metadata}` — NOT a plain list
- `finance --raw` returns a flat list (not nested in sections) — pick first element with non-null fields
- `consensus --raw` returns year-keyed dicts (2026/2027/2028) — extract forward estimates from the earliest year
- K-line data is **newest-first**

### Report Conventions
- **A-share color convention: red = up (涨), green = down (跌)** — opposite to US/EU markets
- Reports use sell-side style tags: 超配/标配/低配/左侧/回避 for allocation; 加仓/减仓/清仓 for position actions
- HTML reports: light background (gradient header in sector-related color), dark text, ECharts for charts, red-up/green-down text coloring
- Report naming: `<板块名>板块深度分析-YYYYMMDD.html` in project root
- **JS syntax check required** before delivering any HTML report: `node --check /tmp/_check.js` on extracted inline scripts

## Project Files (Root Directory)

| File | Size | Purpose |
|------|------|---------|
| `fetch_all_concepts.py` | 127 lines | One-time: enumerate all concept sectors + fetch K-lines |
| `bowl_bottom_results.json` | 704 KB | Scored + labeled results for 842 sectors |
| `sector_kline_data.json` | 30 MB | Raw 250-day K-line data for all sectors |
| `sector_bowl_report.html` | — | Bowl-bottom scan HTML report |
| `*板块深度分析-*.html` | — | Sector deep analysis reports (dated) |
