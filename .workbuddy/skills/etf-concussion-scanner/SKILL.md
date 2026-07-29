---
name: etf-concussion-scanner
description: Use when analyzing A-share ETFs for box-consolidation (箱体震荡) patterns suitable for medium-term swing trading (中线差价) — scan all largest ETFs, score on range width + trend flatness + bounce quality, label as 确认箱体/窄幅收敛/趋势行情.
---

# ETF Concussion Scanner (ETF箱体震荡形态扫描) v1

## Overview

Quantitatively scans the largest A-share ETFs (from `all_etfs_larggest.json` in project root) for **箱体震荡 (box consolidation)** patterns suitable for medium-term swing trading.

A tradable box range requires:
1. **Range wide enough for swing profits** — 8-20% 振幅 ideal for 中期差价
2. **No trend** — price stays within the range, slope near zero
3. **Range quality** — multiple touches of support/resistance confirm the box
4. **Position signal** — current position in range (near support = entry opportunity)

Uses `westock-data` to fetch ETF K-line data, then runs a specialized concussion scoring engine that **rewards tradable box ranges, not narrow dead ranges.**

> **核心改进**: 本算法专为**中线差价**设计 — 筛选振幅足够做波段、但又非单边趋势的箱体震荡ETF。

## Prerequisites

- `westock-data` skill must be loaded first (use `Skill` tool with `"westock-data"`)
- Node.js at `/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node`
- Python 3.13 at `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`
- `all_etfs_larggest.json` must exist in project root

## Quick Start

```
1. Ensure all_etfs_larggest.json exists in project root
2. Run analyze.py → fetches K-line + scores + saves etf_concussion_results.json & etf_concussion_kline_data.json
3. Run generate_report.py → reports/etf/etf_concussion_report.html
4. present_files the HTML report
```

## Step-by-Step Workflow

### Step 1: Verify ETF Input

`analyze.py` automatically loads ETF codes from `all_etfs_larggest.json` in project root. No manual enumeration needed.

### Step 2: Run Analysis

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON .codebuddy/skills/etf-concussion-scanner/analyze.py
```

`analyze.py` does everything in one run:
- Loads ETF codes from `all_etfs_larggest.json`
- Fetches 250-day daily K-line for each ETF (parallel, 8 workers) → `etf_concussion_kline_data.json`
- Scores each ETF with the concussion engine → `etf_concussion_results.json`
- Prints summary with box-consolidation labels

### Step 3: Generate HTML Report

```bash
$PYTHON .codebuddy/skills/etf-concussion-scanner/generate_report.py
```

Produces `reports/etf/etf_concussion_report.html` with: summary cards, 90-day K-line sparklines for confirmed box ETFs, TOP25 ranking table, detailed analysis cards. Present via `present_files`.

## Concussion Scoring Engine

### Core Principle

A **tradable box range** requires FOUR conditions simultaneously:
1. **振幅适中** — range width 8-20% (wide enough for swing, not trending)
2. **趋势平坦** — 40-day slope near zero (no breakout direction)
3. **箱体确认** — multiple support/resistance touches confirm the box boundary
4. **位置优势** — near support = good entry, near resistance = caution

### Windowing
- **中期 (Medium-term)**: 40 days
- **长期 (Long-term)**: 90 days
- K-line fetch: 250 days (for MA120 and reference)

### Scoring Dimensions (max 100, clamped)

| Dimension | Max | Criteria |
|-----------|-----|----------|
| 40d range width (振幅) | 25 | 8-15% = 25 (ideal swing), 5-8% = 15, 15-20% = 12, 20-30% = 5, <5% = 0 |
| 90d range width (振幅) | 20 | 10-20% = 20 (长线箱体), 5-10% = 12, 20-30% = 8 |
| Trend flatness 40d | 20 | abs(slope40)<2% = 20, <3% = 15, <5% = 8 |
| Range quality (bounce count) | 15 | ≥3 support + ≥3 resistance touches = 15 |
| Near support (entry signal) | 10 | pos40 ≤ 25% = 10, ≤ 35% = 6 |
| ATR compression | 5 | atr20/atr90 < 0.85 = 5 |
| Volume stability | 5 | vol_ratio near 1.0 = 5 |

**Penalties:**
- Strong 40d trend (|slope| > 8%) = -15pts
- Price breaking above 90d high (>5%) = -10pts (trending up)
- Price breaking below 90d low (<-5%) = -10pts (trending down)

### Label Grading System

| Label | Criteria | Meaning |
|-------|----------|---------|
| 🟢 确认箱体(中长) | 40d+90d both box range, score≥70 | Best swing opportunity |
| 🟢 确认箱体(中期) | 40d box range, score≥60 | Medium swing opportunity |
| 🟡 窄幅收敛 | Range narrow but consolidating, score≥45 | Watch for range expansion |
| 🟡 宽幅震荡 | Wide range but flat, score≥45 | Cautious swing, narrower gap |
| 🔴 下跌趋势 | 40d slope < -8% | In downtrend, avoid |
| ⚪ 趋势行情 | Otherwise trending | Skip |

### Key Metrics Explained

| Metric | What it measures | Why it matters |
|--------|-----------------|----------------|
| **40d振幅** | (hi40 - lo40) / avg * 100 | Core: is there enough room to swing trade? |
| **90d振幅** | (hi90 - lo90) / avg * 100 | Long-term box boundary confirmation |
| **40d斜率** | Linear regression slope % | Must be near zero for true consolidation |
| **箱体质量** | #support touches + #resistance touches | More touches = more reliable box boundary |
| **位置(pos40)** | (cur - lo) / (hi - lo) in 40d | Near support = low risk entry zone |
| **ATR压缩** | atr20 / atr90 ratio | Compression confirms consolidation ending |
| **量能稳定** | vol20 / vol60 ratio | Stable volume during consolidation |

## Interpretation Guidance

- Focus on **🟢 确认箱体(中长)** ETFs — these have confirmed box ranges in both medium and long term, offering the best swing trading setup. Buy near 箱底, sell near 箱顶.
- **🟢 确认箱体(中期)** ETFs have good medium-term boxes but may have wider long-term amplitude.
- **🟡 窄幅收敛** ETFs are early-stage candidates — range is forming but not yet wide enough for profitable swings. Monitor for range expansion.
- **🟡 宽幅震荡** ETFs have tradable ranges but higher volatility — use tighter position sizing.
- When **many large ETFs** simultaneously show 确认箱体, it may signal broad market consolidation (适合中线操作).
- A box consolidation is a **price pattern, not a fundamental signal** — combine with sector themes and capital flows.

## Important Notes

- Uses Chinese stock market color convention: **red = up (涨)**, **green = down (跌)** — opposite to US/EU.
- This is a quantitative scan only — **not investment advice**.
- Box range signals may break — always set stop-loss below 箱底.
- Data sourced from 腾讯自选股 via westock-data skill; may have delay, trust exchange official data.
- Re-run regularly (e.g., weekly) to track box boundary evolution and position changes.
