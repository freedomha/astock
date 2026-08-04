---
name: etf-2b-bottom-scanner
description: Use when analyzing A-share ETFs for 2B bottom (2B底) reversal patterns — scan all 352 largest ETFs, detect false breakdowns (price breaks below prior 60-day low then recovers within 2 days), score on 7 dimensions, and label as 2B买入确认/2B买入候选/2B观察. Chinese stock market convention: red=up, green=down.
---

# ETF 2B Bottom Scanner (ETF 2B底形态扫描) v1

## Overview

Quantitatively scans the 352 largest A-share ETFs (from `all_etfs_larggest.json` in project root) for **2B bottom reversal patterns** (2B底形态). The 2B rule (Victor Sperandeo) detects a classic false breakdown: the ETF price breaks below a prior 60-day low, but immediately recovers above it within 2 trading days — signaling selling exhaustion and potential trend reversal.

Unlike bowl-bottom (gradual deceleration) and head-shoulder-bottom (5-point structure), the 2B pattern is a **single-bar event** — an aggressive reversal signal that indicates the prior low was the true bottom.

> The 2B bottom is a **reversal pattern** — it signals that the prior low area has been tested and held, and the trend may reverse from down to up. It differs from the bowl-bottom pattern which signals basing/consolidation.

Uses `westock-data` to fetch ETF K-line data, then runs a 7-dimension scoring engine.

## Prerequisites

- `westock-data` skill must be loaded first (use `Skill` tool with `"westock-data"`)
- Node.js at `/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node`
- Python 3.13 at `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`
- `all_etfs_larggest.json` must exist in project root

## Quick Start

```
1. Ensure all_etfs_larggest.json exists in project root
2. Run analyze.py → fetches K-line + detects 2B patterns + scores → saves etf_2b_bottom_results.json & etf_kline_data.json
3. Run generate_report.py → reports/etf/etf_2b_bottom_report.html
4. present_files the HTML report
```

## Step-by-Step Workflow

### Step 1: Verify ETF Input

`analyze.py` automatically loads ETF codes from `all_etfs_larggest.json` in project root (352 ETFs). No manual enumeration needed.

### Step 2: Run Analysis

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON .codebuddy/skills/etf-2b-bottom-scanner/analyze.py
```

`analyze.py` does everything in one run:
- Loads ETF codes from `all_etfs_larggest.json` (352 ETFs)
- Fetches 250-day daily K-line for each ETF (parallel, 8 workers) → `etf_kline_data.json` (in skill directory)
- Detects 2B patterns on recent bars → `etf_2b_bottom_results.json` (in skill directory)
- Prints summary with 2B labels

### Step 3: Generate HTML Report

```bash
$PYTHON .codebuddy/skills/etf-2b-bottom-scanner/generate_report.py
```

Produces `reports/etf/etf_2b_bottom_report.html` with: summary cards, 60-day K-line sparklines for 2B signals with prior low + breakdown + recovery bars annotated, TOP25 ranking table, detailed analysis cards. Present via `present_files`.

## 2B Detection Logic

For each ETF, on the **most recent bars**:

1. **Find prior 60-day low** — lowest close in bars [2..61] (exclude bars 0-1 to avoid self-reference)
2. **Check breakdown** — on bars 0, 1, 2: did price make a new low below the prior 60-day benchmark?
3. **Check recovery** — within 2 bars after the breakdown bar, did the close recover above the prior 60-day low?

A detection requires **both** the breakdown and the recovery.

## Scoring Engine (7 dimensions, max 100)

| # | Dimension | Max | Logic |
|---|-----------|-----|-------|
| 1 | Break depth | 20 | <1% below = 20; 1-3% = 15; 3-5% = 8; >5% = 0 |
| 2 | Recovery strength | 20 | close ≥1.5% above prior low = 20; ≥0.5% = 15; ≥0% = 10 |
| 3 | Volume contraction | 15 | vol <60d avg = 15; <80% = 10; <100% = 5 |
| 4 | Prior low quality | 15 | distinct swing low (lowest in ±10d) = 15; reasonable = 10; minor = 5 |
| 5 | Trend context | 15 | prior decline (20d before prior low) >8% = 15; >5% = 10; >3% = 5 |
| 6 | Recovery speed | 10 | same-day = 10; 1d lag = 7; 2d lag = 5 |
| 7 | Distance from 60MA | 5 | price -15% to -2% below 60MA = 5 |

**Penalties:**
- High volume breakdown (>120% of 60d avg) = -10pts
- Prior 60-day low too recent (<5 bars ago) = -5pts

**Score clamped:** 0-100

## Label Grading System

| Label | Score | Meaning |
|-------|-------|---------|
| 🟢 2B买入确认 | ≥80 | High-confidence 2B bottom, confirmed reversal |
| 🟢 2B买入候选 | 65-79 | Likely 2B bottom, monitor for confirmation |
| 🟡 2B观察 | 50-64 | Weak 2B signal, insufficient pattern quality |
| ⚪ 无2B信号 | <50 | No valid 2B pattern detected |

## Interpretation Guidance

- Focus on **🟢 2B买入确认** ETFs — these have the strongest 2B bottom evidence (shallow break + fast strong recovery + volume contraction).
- **🟢 2B买入候选** ETFs show a valid 2B pattern but with lower confidence — monitor for follow-through buying.
- **🟡 2B观察** ETFs have a marginal breakdown/recovery that may not constitute a true 2B.
- A 2B signal is a **point-in-time event** — it fires on a specific bar, unlike bowl-bottom which is a state. The scan checks if a signal is currently active.
- Not all 2B signals lead to sustained reversals — combine with volume, trend depth, and market context.
- When multiple ETFs from the same sector show 2B signals simultaneously, it may indicate sector-level basing.

## Important Notes

- Uses Chinese stock market color convention: **red = up (涨)**, **green = down (跌)** — opposite to US/EU.
- This is a quantitative scan only — **not investment advice**.
- Data sourced from 腾讯自选股 via westock-data skill; may have delay, trust exchange official data.
- Re-run daily to check for fresh 2B signals.
