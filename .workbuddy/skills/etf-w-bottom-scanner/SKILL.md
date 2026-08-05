---
name: etf-w-bottom-scanner
description: Use when analyzing A-share ETFs for W-bottom (W底 / double bottom) reversal patterns — scan all 352 largest ETFs using phase-based detection (prior decline → left trough → peak → right trough → breakout), score on 8 dimensions, and label as W底确认/W底形成中/W底候选. Chinese stock market convention: red=up, green=down.
---

# ETF W-Bottom Scanner (ETF W底形态扫描) v1

## Overview

Quantitatively scans the 352 largest A-share ETFs (from `all_etfs_larggest.json` in project root) for **W-bottom reversal patterns** (W底 / double bottom). The W-bottom is a classic technical reversal pattern consisting of two troughs at similar levels separated by a central peak, following a prior downtrend.

Detection uses a **phase-based pipeline**: the ETF must pass sequential validation through 5 phases (prior decline → left trough → recovery to peak → right trough validation → breakout status) before being scored on 8 dimensions.

Uses shared K-line data from project-root `etf_kline_data.json` (reused by all ETF scanners). Only refetches if the file doesn't exist.

## Prerequisites

- Node.js at `/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node`
- Python 3.13 at `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`
- `all_etfs_larggest.json` must exist in project root
- `etf_kline_data.json` in project root is auto-detected and reused; westock-data only called if it's missing

## Quick Start

```
1. Ensure all_etfs_larggest.json exists in project root
2. Run analyze.py → detects W-bottoms + scores + saves etf_w_bottom_results.json
3. Run generate_report.py → reports/etf/etf_w_bottom_report.html
4. Optional: Run backtest.py → backtest_w_bottom_results.json + summary
5. present_files the HTML report
```

## Step-by-Step Workflow

### Step 1: Verify Input

`analyze.py` automatically loads ETF codes from `all_etfs_larggest.json` (352 ETFs) and K-line data from `etf_kline_data.json` (project root, shared). No manual enumeration needed.

### Step 2: Run Analysis

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON .codebuddy/skills/etf-w-bottom-scanner/analyze.py
```

`analyze.py` does everything in one run:
- Loads ETF codes from `all_etfs_larggest.json` (352 ETFs)
- Loads K-line data from `etf_kline_data.json` (project root). If absent, fetches 250-day K-lines via westock-data (parallel, 8 workers, 4+6 retries) and saves to project root.
- Runs phase-based W-bottom detection + 8-dim scoring → `etf_w_bottom_results.json` (in skill dir)
- Prints summary with W-bottom labels

### Step 3: Generate HTML Report

```bash
$PYTHON .codebuddy/skills/etf-w-bottom-scanner/generate_report.py
```

Produces `reports/etf/etf_w_bottom_report.html` with: summary cards, W-bottom annotated K-line sparklines for top candidates, TOP25 ranking table, detailed analysis cards. Present via `present_files`.

### Step 4 (Optional): Run Backtest

```bash
$PYTHON .codebuddy/skills/etf-w-bottom-scanner/backtest.py
```

Walks historical K-line data, simulates W-bottom detection at past dates, measures N-day forward returns. Outputs `backtest_w_bottom_results.json` with win rate, avg return, max drawdown by label.

## Phase-Based Detection Pipeline

The scanner applies 5 sequential phase filters. Any failure at a phase = ETF filtered out.

### Phase 1: Prior Decline
- **Window**: T-120 to T-40 (indices 0-79, oldest-first)
- **Metric**: 40-day linear regression slope at T-40
- **Threshold**: slope ≤ -0.5% per day
- **Yield**: ~129 of 338 ETFs (38.2%)

### Phase 2-3: Left Trough to Peak Recovery
- **Window**: T-40 to T-25 (left trough), then from trough to T-12 (peak)
- **Metric**: Recovery from left trough to central peak
- **Threshold**: recovery ≥ 8%
- **Yield**: ~65 of 129 (50.4% of Phase 1 passers)

### Phase 4: Right Trough Validation
- **Window**: T-12 to T (right trough)
- **Trough similarity**: Right trough within ±10% of left trough
- **Volume contraction**: Right trough 11-day avg volume ≤ 1.2× left trough
- **Yield**: ~15 of 65 (23.1% of Phase 2 passers)

### Phase 5: Breakout Status
- **W底确认 (confirmed)**: 2 of 3 most recent closes above peak AND current close > peak
- **W底形成中 (forming)**: Double trough visible, price recovering but not yet breached peak

## Scoring Engine (8 dimensions, max ~97 pts, capped at 100)

| # | Dimension | Max | Scoring Tiers |
|---|-----------|-----|---------------|
| 1 | Trough Symmetry | 20 | diff≤1%: 20, ≤3%: 17, ≤6%: 12, >6%: 5 |
| 2 | Recovery Magnitude | 15 | ≥15%: 15, ≥12%: 12, ≥10%: 8, <10%: 3 |
| 3 | Right Trough Elevation | 15 | RT>LT by ≥3%: 15, ≥1%: 10, ≥0%: 5, RT<LT: 0 |
| 4 | Volume Contraction | 12 | VR≤0.7: 12, ≤0.9: 9, ≤1.0: 6, ≤1.2: 2 |
| 5 | Prior Decline Depth | 10 | drawdown≥15%: 10, ≥10%: 7, ≥5%: 3 |
| 6 | Time Symmetry | 5 | L/R 0.7-1.3: 5, 0.5-1.5: 3, else: 1 |
| 7 | Breakout Strength | 10 | cur>peak by ≥5%: 10, ≥3%: 7, ≥1%: 4 (confirmed only) |
| 8 | Formation Quality | 10 | Decline smoothness(0-3) + peak distinctiveness(0-3) + right V-recovery(0-4) |

## Label Grading System

| Label | Threshold | Description |
|-------|-----------|-------------|
| 🟢 W底确认 | ≥55 (confirmed) or ≥45 (lower-score confirmed) | Confirmed breakout, investable signal |
| 🟢 W底形成中 | ≥55 or ≥45 (forming status) | Structure visible, awaiting breakout |
| 🟡 W底候选 | ≥35 | Basic structure visible, weaker quality |
| ⚪ 非W底 | <35 | Does not qualify |

## Interpretation Guidance

- Focus on **🟢 W底确认** ETFs — these have the strongest W-bottom evidence with confirmed neckline breakout.
- **🟢 W底形成中** ETFs show complete double-trough structure but haven't broken out yet — monitor for breakout confirmation.
- **🟡 W底候选** ETFs have visible structure but with lower quality on some dimensions.
- W-bottom is a **reversal formation** — the prior decline provides context; a confirmed breakout above the central peak is the trigger.
- All detected W-bottoms in the current scan showed right trough ≥ left trough (universally bullish).
- When multiple ETFs from the same sector (科创, 半导体) show W-bottoms simultaneously, it may indicate sector-level reversal.

## Important Notes

- Uses Chinese stock market color convention: **red = up (涨)**, **green = down (跌)** — opposite to US/EU.
- This is a quantitative scan only — **not investment advice**.
- Data sourced from 腾讯自选股 via westock-data skill; may have delay, trust exchange official data.
- K-line data is shared (`etf_kline_data.json` in project root) — reused by all ETF scanners. Only refetched if the file is missing.
