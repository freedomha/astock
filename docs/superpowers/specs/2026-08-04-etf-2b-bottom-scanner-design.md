# ETF 2B Bottom Scanner — Design Spec

**Date:** 2026-08-04
**Status:** Approved

## Overview

Quantitatively scans the 352 largest A-share ETFs for **2B bottom reversal patterns** (2B底形态). The 2B rule (Victor Sperandeo) detects a false breakdown: price breaks below a prior 60-day low but immediately recovers above it within 2 trading days, signaling selling exhaustion and potential trend reversal.

### What makes a 2B signal

1. **Prior 60-day low identified** — the lowest close in the 60-bar window ending 2 bars ago (exclude the trigger bars themselves)
2. **Breakdown** — price makes a new low below the prior 60-day low (on bars 0..2, i.e. current bar down to 2 bars ago)
3. **Fast recovery** — the close recovers above the prior 60-day low within 2 trading days after the breakdown bar
4. **Current signal only** — only the most recent bars are scanned; this answers "what ETF is a 2B buy *right now*"

## Architecture

```
all_etfs_larggest.json (352 ETFs)
    │
    ▼
analyze.py
    │  ├─ Load ETF codes from all_etfs_larggest.json
    │  ├─ Fetch 250-day K-line per ETF (parallel, 8 workers, 4 retries)
    │  ├─ Detect 2B pattern on most recent bars only
    │  ├─ Score each detection (7 dimensions, max 100)
    │  └─ Assign label grade
    │
    ▼
etf_2b_bottom_results.json + etf_kline_data.json (in skill directory)
    │
    ▼
generate_report.py
    │
    ▼
reports/etf/etf_2b_bottom_report.html
```

## Detection Algorithm

### Step 1: Find prior 60-day low

Look at bars [2..61] (skip bar 0 and 1 to avoid self-reference). Find the minimum close and record the bar index.

### Step 2: Check for breakdown

On bars 0, 1, 2 (current bar working backward): check if any bar made a low below the prior 60-day low. If no breakdown on any of these bars → no signal.

### Step 3: Check recovery

From the breakdown bar, check if within the next 2 bars the close recovers above the prior 60-day low. Recovery windows:
- Breakdown on bar 0 → same-day signal (if today hasn't made new low, check bar 1 or 2 were the breakdown)
- Breakdown on bar 1 → check bars 1 and 0
- Breakdown on bar 2 → check bars 2, 1, and 0

If no recovery within 2 bars → no signal.

### Step 4: Multiple signals

If multiple breakdown bars all recover, use the earliest one and score it.

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

## Label Grading

| Label | Score | Meaning |
|-------|-------|---------|
| 🟢 2B买入确认 | ≥80 | High-confidence 2B bottom, confirmed reversal |
| 🟢 2B买入候选 | 65-79 | Likely 2B bottom, monitor for confirmation |
| 🟡 2B观察 | 50-64 | Weak 2B signal, insufficient pattern quality |
| ⚪ 无2B信号 | <50 | No valid 2B pattern detected |

## Report Design

### Output

`reports/etf/etf_2b_bottom_report.html`

### Sections

1. **Header** — Scan date, total ETFs scanned, green-themed gradient
2. **Summary cards** — Total signals, by label (🟢确认 / 🟢候选 / 🟡观察), top 3 ETFs
3. **Signals table** — All detected 2B signals ranked by score desc:
   - Code, Name, Label, Score, Break depth, Recovery strength, Volume, Pattern detail
   - Sortable/filterable
4. **Detail cards** — For each confirmed/candidate signal:
   - 60-day K-line sparkline (Chart.js) with prior low marked + breakdown bar + recovery bar annotated
   - Score breakdown by dimension (radar or bar chart)
   - Key metrics summary

### Visual conventions

- A-share color convention: red = up, green = down
- Chart.js for sparklines (consistent with existing ETF scanners)
- Light background, dark text, responsive layout

## Files Created

| File | Purpose |
|------|---------|
| `.codebuddy/skills/etf-2b-bottom-scanner/SKILL.md` | Skill definition + workflow |
| `.codebuddy/skills/etf-2b-bottom-scanner/analyze.py` | Detection + scoring engine |
| `.codebuddy/skills/etf-2b-bottom-scanner/generate_report.py` | HTML report builder |

### Data files (generated at runtime)

| File | Location |
|------|----------|
| `etf_2b_bottom_results.json` | `.codebuddy/skills/etf-2b-bottom-scanner/` |
| `etf_kline_data.json` | `.codebuddy/skills/etf-2b-bottom-scanner/` |

## Prerequisites

- `westock-data` CLI available
- Node.js at `/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node`
- Python 3.13 at `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`
- `all_etfs_larggest.json` in project root
- Uses only Python standard library (consistent with project conventions)

## Edge Cases

- **No prior 60-day low found** — skip ETF, label as 无2B信号
- **K-line data fetch failure** — retry 4x (consistent with existing scanners), skip on persistent failure
- **Breakdown + recovery spans data boundary** — ensure bars exist for full recovery window
- **Stale data** — scan date is today; if most recent K-line is >3d old, flag as data warning
- **Multiple breakdowns in window** — use earliest, score that one
