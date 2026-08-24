---
name: bowl-bottom-sector-scanner
description: Use when analyzing A-share sectors/themes for bowl-bottom (碗底) bottoming patterns — scan sectors, score each on an enhanced engine (range position + U-shape fit + trend deceleration ratio + higher-low detection), and label as 确认碗底/减速筑底/下跌中继. Chinese stock market convention: red=up, green=down.
---

# Bowl-Bottom Sector Scanner (碗底形态题材扫描) v2

## Overview

Quantitatively scans A-share sectors (申万一级行业 + 聚源产业概念) for bowl-bottom (saucer-bottom) chart patterns. A bowl-bottom pattern = the sector declined to its range low, then **decelerated and stabilized** with **higher lows forming** — the classic basing formation before a potential reversal.

Uses `westock-data` to fetch sector lists and K-line data, then runs an enhanced multi-dimension scoring engine that **distinguishes true bowl bottoms from persistent downtrends**.

> ⚠️ **v1 → v2 关键改进**: v1 仅凭"区间低位+近期走平"打分，会把"仍在下跌"的板块误判为碗底（如某板块20日跌31%仍得60分）。v2 新增**减速比**、**低点抬升**、**U形拟合**三重验证，剔除伪碗底。

## Prerequisites

- `westock-data` skill must be loaded first (use `Skill` tool with `"westock-data"`)
- Node.js at `/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node`
- Python 3.13 at `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`

## Quick Start

```
1. Load westock-data skill
2. (Optional) Ensure sector lists present — 全市场概念清单已内置 all_concept_sectors.json；申万一级行业需 sw1_sectors.json（缺则按下方 Step 1 拉取）
3. Run analyze.py → fetches K-line + scores + saves bowl_bottom_results.json & sector_kline_data.json
4. Run generate_report.py → sector_bowl_report.html
5. present_files the HTML report
```

## Step-by-Step Workflow

### Step 1: Sector Lists (概念清单已内置)

概念板块的完整清单 **已随 skill 内置** 在 `all_concept_sectors.json`（830 个：聚源产业概念 721 + 风格概念 78 + 地域概念 31），无需每次拉取。`analyze.py` 自动从该文件加载。

申万一级行业（`sw1_sectors.json`）默认优先读取 skill 目录本地文件，缺失时回退到 `/tmp/sw1_sectors.json`。如需重新生成：

```bash
WESTOCK="/Users/aldiadmin/.workbuddy/westock-data/scripts/index.js"
NODE="/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
SKILL_DIR="$(dirname "$0")/.workbuddy/skills/bowl-bottom-sector-scanner"

# 申万一级行业（31 个）
$NODE $WESTOCK sector list industry_list_sw1 --raw > $SKILL_DIR/sw1_sectors.json
# 全市场概念板块（如需刷新：产业/风格/地域三类分别枚举后合并）
```

### Step 2: Run Enhanced Analysis

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON analyze.py
```

`analyze.py` does everything in one run:
- Loads sector codes from the skill-bundled `all_concept_sectors.json` + 本地 `sw1_sectors.json`（共 861 个板块）
- Fetches 250-day daily K-line for each sector (parallel, 8 workers) → `sector_kline_data.json`
- Scores each sector with the enhanced engine → `bowl_bottom_results.json`
- Prints summary with bowl-bottom labels

### Step 3: Generate HTML Report

```bash
$PYTHON generate_report.py
```

Produces `sector_bowl_report.html` with: summary cards, 120-day K-line sparklines for confirmed bowl-bottoms, TOP25 ranking table, detailed analysis cards. Present via `present_files`.

## Enhanced Scoring Engine (v2)

### Core Principle

A **true bowl-bottom** requires THREE conditions simultaneously:
1. **区间底部** — price near 120/250-day range low (position ≤ 25%)
2. **前期下跌后近期趋稳** — prior decline (前40日) followed by recent stabilization (近20日), measured by **deceleration ratio < 0.8**
3. **低点抬升** — recent 10-day low > prior 10-day low (higher low forming)

### Key Metrics

| Metric | What it measures | Why it matters |
|--------|-----------------|----------------|
| **减速比 (decel_ratio)** | 近20日跌幅 ÷ 前40日(等效20日)跌幅 | <1 = decelerating; ≈0 = decline stopped; >1 = accelerating down |
| **低点抬升 (higher_low)** | 近10日低点 vs 前10日低点 | True bowl bottom forms higher lows; still-making-new-lows = downtrend |
| **U形曲率 (curvature)** | Quadratic fit ax²+bx+c on 120-day closes | a>0 (convex) + vertex in recent third = U-shape confirmed |
| **区间位置 (pos120/pos250)** | Current price position in N-day range | ≤10% = extreme low (bottom zone) |

### Scoring Dimensions (max 100, clamped)

| Dimension | Max | Criteria |
|-----------|-----|----------|
| 120-day range position | 25 | ≤10% = 25, ≤20% = 20, ≤30% = 12 |
| 250-day range position | 20 | ≤15% = 20, ≤25% = 15, ≤35% = 8 |
| Bowl shape (prior decline + recent stabilize) | 20 | decel<0.8 & flat = 20; decel<1.0 = 14 |
| Higher-low bonus | 5 | raised low >0.5% = 5 |
| U-shape curvature fit | 10 | convex + vertex recent = 10 |
| Volume contraction (20d/60d) | 8 | <0.7 = 8, <0.85 = 5 |
| Volatility compression (ATR) | 7 | <0.7 = 7, <0.85 = 5 |
| Below 60MA | 10 | -12% to -2% = 10 |

**Penalties:** recent crash (20d < -8%) = -15pts; near highs (drawdown > -5%) = -20pts.

### Label Grading System

| Label | Criteria | Meaning |
|-------|----------|---------|
| 🟢 确认碗底 | bottom zone + stabilized (decel<0.8) + higher low + score≥65 | High-confidence basing |
| 🟢 碗底确认中 | bottom zone + (stabilized OR decelerating+higher low) + score≥58 | Likely basing, monitor |
| 🟡 减速筑底 | bottom zone + decelerating (decel<1.0) + score≥50 | Slowing but not yet stabilized |
| 🟡 低位盘整 | bottom zone + flat 20-day | Sideways at low, no clear bowl |
| 🔴 下跌中继 | 20-day trend < -6% | Still falling, NOT a bottom |
| ⚪ 观望 | otherwise | Not in bottom zone |

## Interpretation Guidance

- Focus on **🟢 确认碗底** sectors — these have the strongest bowl-bottom evidence (decline stopped + higher lows).
- **🟡 减速筑底** sectors are early-stage candidates — the decline is slowing but hasn't stabilized; wait for confirmation.
- **🔴 下跌中继** sectors are traps — they may be at range lows but are still actively falling ("底部之下还有底").
- When **many sectors** simultaneously show 确认碗底, it may signal broad market basing.
- A bowl-bottom is a **necessary but not sufficient** condition for reversal — combine with fundamentals, capital flows, and macro.

## Important Notes

- Uses Chinese stock market color convention: **red = up (涨)**, **green = down (跌)** — opposite to US/EU.
- This is a quantitative scan only — **not investment advice**.
- Sector bowl-bottom ≠ individual stock bottom.
- Data sourced from 腾讯自选股 via westock-data skill; may have delay, trust exchange official data.
- Re-run regularly (e.g., weekly) to track bowl-bottom progression: 减速筑底 → 确认中 → 确认碗底.
