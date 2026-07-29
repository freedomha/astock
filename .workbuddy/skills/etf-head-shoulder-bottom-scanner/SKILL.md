---
name: etf-head-shoulder-bottom-scanner
description: Use when analyzing A-share ETFs for head-shoulder-bottom (头肩底) reversal patterns — scan all 352 largest ETFs, detect 5-point geometric structure (left shoulder → head → right shoulder + neckline), score pattern quality, and label as 头肩底确认/头肩底形成中/头肩底候选. Chinese stock market convention: red=up, green=down.
---

# ETF Head-Shoulder-Bottom Scanner (ETF头肩底形态扫描) v1

## Overview

Quantitatively scans the 352 largest A-share ETFs (from `all_etfs_larggest.json`) for **head-shoulder-bottom (头肩底)** reversal patterns. This classic technical pattern consists of five key points: **Left Shoulder (左肩)** → **Peak1 (颈线左高点)** → **Head (头部)** → **Peak2 (颈线右高点)** → **Right Shoulder (右肩)**, with a **neckline (颈线)** connecting the two peaks.

The pattern represents selling pressure exhaustion: after three waves of selling (LS → Head → RS), the bears lose momentum, and the neckline breakout signals a potential trend reversal from downtrend to uptrend.

Uses `westock-data` to fetch ETF K-line data, then runs a multi-dimension scoring engine that evaluates pattern completeness, geometric validity, volume contraction, and time symmetry.

> The head-shoulder-bottom is a **bottom reversal pattern** — it signals the end of a downtrend and the beginning of an uptrend, unlike the bowl-bottom pattern which signals basing/consolidation.

## Prerequisites

- `westock-data` skill must be loaded first (use `Skill` tool with `"westock-data"`)
- Node.js at `/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node`
- Python 3.13 at `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`
- `all_etfs_larggest.json` exists at `.workbuddy/skills/etf-bowl-bottom-scanner/all_etfs_larggest.json`

## Quick Start

```
1. Ensure all_etfs_larggest.json exists
2. Run analyze.py → fetches K-line + detects HS patterns + scores → etf_hs_bottom_results.json & etf_kline_data.json
3. Run generate_report.py → etf_hs_bottom_report.html
4. present_files the HTML report
```

## Step-by-Step Workflow

### Step 1: Verify ETF Input

`analyze.py` automatically loads ETF codes from `.workbuddy/skills/etf-bowl-bottom-scanner/all_etfs_larggest.json` (352 ETFs). No manual enumeration needed.

### Step 2: Run Analysis

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON .codebuddy/skills/etf-head-shoulder-bottom-scanner/analyze.py
```

`analyze.py` does everything in one run:
- Loads ETF codes from `all_etfs_larggest.json` (352 ETFs)
- Fetches 250-day daily K-line for each ETF (parallel, 8 workers) → `etf_kline_data.json`
- Detects head-shoulder-bottom patterns with extrema-finding algorithm → `etf_hs_bottom_results.json`
- Prints summary with pattern labels

### Step 3: Generate HTML Report

```bash
$PYTHON .codebuddy/skills/etf-head-shoulder-bottom-scanner/generate_report.py
```

Produces `etf_hs_bottom_report.html` with: summary cards, annotated 250-day K-line sparklines for confirmed patterns (LS/H/RS points marked + neckline), TOP25 ranking table, detailed analysis cards. Present via `present_files`.

## Pattern Detection Algorithm

### Core Principle

A **true head-shoulder-bottom** requires a 5-point geometric structure in the price chart:

```
Price
  ^
  |    Peak1 ---- Neckline ---- Peak2
  |   /    \                    /
  |  /      \      /\          /
  | /        \    /  \        /
  |/    LS    \  /    \  RS  /
  |            \/ Head \    /
  +----------------------------> Time
```

1. **Left Shoulder (LS)**: Price declines to a low, then rises to form **Peak1**
2. **Head**: Price declines further below LS low to form the lowest point, then rises to form **Peak2**
3. **Right Shoulder (RS)**: Price declines again but stays above the Head, forming the right shoulder
4. **Neckline**: The line connecting Peak1 and Peak2 — should be roughly horizontal

### Detection Steps

1. **Find local extrema** — Identify significant peaks and valleys over the 250-day window (minimum 20-bar separation)
2. **Walk through valleys** — Look for 3 consecutive valleys where the middle is lowest (v1 ≈ LS, v2 = Head, v3 ≈ RS)
3. **Verify peaks** — Find the highest peaks between v1-v2 and v2-v3 to define the neckline
4. **Validate geometry** — Check: Head < LS, Head < RS, shoulders within ±15% of each other
5. **Score quality** — Rate pattern on 8 dimensions (see below)

### Key Metrics

| Metric | What it measures | Why it matters |
|--------|-----------------|----------------|
| **肩部对称性** | LS vs RS price ratio | Ideal: LS ≈ RS; asymmetry weakens pattern |
| **头部深度** | Head vs shoulders | Head must be significantly lower (≥2%) |
| **颈线斜率** | Slope of Peak1→Peak2 line | Should be horizontal (±5%); steep slope = invalid |
| **量度萎缩** | Volume during LS vs Head vs RS | Declining volume = selling exhaustion |
| **时间对称性** | LS→Head vs Head→RS days | Should be roughly equal (0.4–2.5x) |
| **右肩位置** | RS vs neckline distance | RS approaching neckline = imminent breakout |

### Scoring Dimensions (max 100, clamped)

| Dimension | Max | Criteria |
|-----------|-----|----------|
| Pattern completeness (5 points) | 30 | All 5 points found in correct order |
| Head depth vs shoulders | 15 | Head ≥2% below both shoulders = 15; ≥1% = 10 |
| Shoulder symmetry (LS vs RS) | 10 | LS/RS within ±5% = 10; ±10% = 7; ±15% = 4 |
| Neckline quality (flatness) | 10 | Slope < ±3% = 10; < ±5% = 7; < ±8% = 4 |
| Volume contraction (LS→RS) | 10 | Vol_RS < 0.7×Vol_LS = 10; < 0.85 = 7 |
| Range position (120/250-day) | 10 | pos120 ≤ 30% = 10; ≤ 50% = 5 |
| Time symmetry (LS→H vs H→RS) | 8 | Ratio 0.6–1.5 = 8; 0.4–2.5 = 4 |
| RS recovery trend | 7 | RS rising (5d > 0) or near neckline = 7 |

**Penalties:** Head not lowest = -30; pattern too messy (>8 local extrema) = -10; recent crash (20d < -8%) = -10.

### Label Grading System

| Label | Criteria | Meaning |
|-------|----------|---------|
| 🟢 头肩底确认 | Full pattern + score≥70 + RS approaching neckline | Complete reversal pattern, high confidence |
| 🟢 头肩底形成中 | 4+ points identified + score≥55 | Pattern nearly complete, monitor for confirmation |
| 🟡 头肩底候选 | 3-4 points + score≥40 | Partial pattern forming, needs more development |
| ⚪ 非头肩底 | No clear pattern or score<40 | Not a head-shoulder-bottom |

## Interpretation Guidance

- Focus on **🟢 头肩底确认** ETFs — these have the strongest reversal signal with all 5 points verified.
- **🟢 头肩底形成中** ETFs are near completion — watch for RS to approach the neckline for breakout.
- **🟡 头肩底候选** ETFs have early pattern signals — may develop into a full pattern over 1-2 weeks.
- The neckline is the key confirmation level — a **breakout above neckline with volume** confirms the reversal.
- A head-shoulder-bottom is a **bullish reversal pattern** — it signals potential trend change from down to up.
- Combine with bowl-bottom analysis for confirmation: ETFs showing both patterns carry stronger conviction.
- The pattern is invalidated if price breaks below the Head low before a neckline breakout.

## Important Notes

- Uses Chinese stock market color convention: **red = up (涨)**, **green = down (跌)** — opposite to US/EU.
- This is a quantitative scan only — **not investment advice**.
- Head-shoulder-bottom pattern may fail if the market continues to decline.
- Data sourced from 腾讯自选股 via westock-data skill; may have delay, trust exchange official data.
- Re-run regularly (e.g., weekly) to track pattern development: 候选 → 形成中 → 确认.
- **Complementary to bowl-bottom scan**: Use both skills together — bowl-bottom identifies basing zones, head-shoulder-bottom identifies specific reversal triggers.
