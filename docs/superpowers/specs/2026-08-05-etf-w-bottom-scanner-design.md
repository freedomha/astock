# ETF W-Bottom Scanner — Design Spec

**Date**: 2026-08-05
**Status**: Approved
**Data**: `etf_kline_data.json` (338 ETFs, 120-day K-lines, data as of 2026-08-04)

## Overview

A phase-based ETF scanner that detects W-bottom (double bottom) patterns — a classic technical reversal signal. Detects two troughs at similar levels with a central peak, preceded by a downtrend. Outputs ranked, scored results with labels and an HTML report. Includes a backtesting module for historical validation.

## Architecture

```
etf_kline_data.json
       │
       ▼
  analyze.py ────► etf_w_bottom_results.json
       │                    │
       │            generate_report.py
       │                    │
       ▼                    ▼
  backtest.py     etf_w_bottom_report.html
```

Shared helpers (`lin_slope`, `atr`) reused from existing scanners. No new dependencies. Only standard library imports.

### K-line Data Handling

Follows the existing ETF scanner pattern: `analyze.py` checks if `etf_kline_data.json` exists in project root. If present, loads from disk (reuses shared data fetched by any other ETF scanner). If absent, fetches from westock-data (parallel, 8 workers, 4+6 retries) and saves to project root. The W-bottom scanner should never trigger a fresh fetch if the file already exists — this avoids redundant network calls when multiple scanners run in sequence.

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Skill definition following existing ETF scanner pattern |
| `analyze.py` | Phase-based detection + 8-dim scoring engine |
| `generate_report.py` | HTML report with ranked table + sparklines |
| `backtest.py` | Historical backtesting of W-bottoms |

Location: `.workbuddy/skills/etf-w-bottom-scanner/`

## Detection Pipeline: Sequential Phase Filters

Each ETF must pass all 5 phases. Any failure = filtered out (not scored).

### Phase 1: Prior Decline
- **Window**: T-120 to T-40 (indices 0-79 in oldest-first array)
- **Metric**: 40-day linear regression slope at T-40
- **Threshold**: slope ≤ -0.5% per day
- **Yield**: 129/338 (38.2%)
- **Rationale**: Confirms a meaningful downtrend preceded the W-bottom. A-share ETFs are volatile; stricter thresholds (e.g., -1.0%) would miss too many candidates.

### Phase 2: Left Trough Detection
- **Window**: T-40 to T-25 (indices 80-95)
- **Method**: Find lowest close in this window
- **Phase 3: Recovery to Peak**
  - **Window**: From left trough to T-12 (index up to 108)
  - **Method**: Find highest close
  - **Threshold**: Recovery from trough to peak ≥ 8%
- **Yield**: 65/129 (50.4%)
- **Rationale**: 8% is median recovery magnitude. Filters out noise-level bounces. Ensures the central peak is distinguishable.

### Phase 4: Right Trough Validation
- **Window**: T-12 to T (indices 108-120)
- **Method**: Find lowest close
- **Thresholds**:
  - Trough similarity: right trough within ±10% of left trough
  - Volume contraction: right trough 11-day avg volume ≤ 1.2× left trough
- **Yield**: 15/65 (23.1%)
- **Rationale**: ±10% is near median trough difference. Volume ≤ 1.2 allows for ETFs where volume doesn't contract cleanly (common in thematic/sector ETFs).

### Phase 5: Breakout Status
- **Confirmed** (W底确认): 2 of 3 most recent closes > peak AND current close > peak
- **Forming** (W底形成中): Right trough has formed, price recovering but not breached peak
- **Yield**: 9 confirmed + 6 forming = 15 total (4.4% of all ETFs)
- **Rationale**: 2-of-3 rule prevents false breakouts from single-day volatility.

## Scoring Engine: 8 Dimensions (max scoring ~97 pts, capped at 100)

| # | Dimension | Max Pts | Scoring Tiers |
|---|-----------|---------|---------------|
| 1 | Trough Symmetry | 20 | diff ≤ 1%: 20, ≤ 3%: 17, ≤ 6%: 12, > 6%: 5 |
| 2 | Recovery Magnitude | 15 | ≥ 15%: 15, ≥ 12%: 12, ≥ 10%: 8, < 10%: 3 |
| 3 | Right Trough Elevation | 15 | RT > LT by ≥ 3%: 15, ≥ 1%: 10, ≥ 0%: 5, RT < LT: 0 |
| 4 | Volume Contraction | 12 | VR ≤ 0.7: 12, ≤ 0.9: 9, ≤ 1.0: 6, ≤ 1.2: 2 |
| 5 | Prior Decline Depth | 10 | drawdown ≥ 15%: 10, ≥ 10%: 7, ≥ 5%: 3 |
| 6 | Time Symmetry | 5 | L/R ratio 0.7–1.3: 5, 0.5–1.5: 3, else: 1 |
| 7 | Breakout Strength | 10 | cur > peak by ≥ 5%: 10, ≥ 3%: 7, ≥ 1%: 4 (confirmed only) |
| 8 | Formation Quality | 10 | Decline smoothness (0-3) + peak distinctiveness (0-3) + right V-recovery (0-4) |

## Label Grading

| Label | Threshold | Description |
|-------|-----------|-------------|
| W底确认 | ≥ 55 (confirmed) or ≥ 45 (lower-score confirmed) | Confirmed breakout, investable signal |
| W底形成中 | ≥ 55 or ≥ 45 (forming status) | Structure visible, awaiting breakout confirmation |
| W底候选 | ≥ 35 | Basic structure visible, weaker quality |
| 非W底 | < 35 | Does not qualify as a valid W-bottom |

Labels use internal breakout status (Phase 5) as override for the confirmed vs forming distinction.

## Verified Results (2026-08-04 Data)

**15 W-bottoms detected out of 338 ETFs**

Score range: 42–62 (avg 52.3, median 52)

| Label | Count |
|-------|-------|
| W底确认 | 9 |
| W底形成中 | 3 |
| W底候选 | 3 |

Sample top candidates: 科创芯片ETF嘉实 (62), 沪深港科技50ETF (59), 半导体龙头ETF工银 (58), 创新100ETF (58)

## Key Design Decisions

1. **Phase-based over template correlation**: Phase segmentation produces more interpretable results with clear pass/fail criteria per phase. Aligns with the existing head-shoulder-bottom scanner's structure-based approach.
2. **Relaxed volume filter (≤ 1.2x)**: ETFs, especially thematic ones (科创, 半导体), don't always show textbook volume contraction during W-bottom formation. A 1.2x cap catches real patterns while excluding overtly expanding-volume breakdowns.
3. **±10% trough similarity**: A-share ETFs typically show 8–12% trough-to-trough variation. ±10% is near the median and produces a manageable candidate count (29) before volume filtering.
4. **8% recovery minimum**: Median recovery from trough to peak is 8.2% — this threshold cleanly splits the distribution and ensures the central peak is meaningful.
5. **Time symmetry reduced to 5pts**: The rigid 120-day window creates asymmetric L/R dwell times in most cases. The dimension still provides discriminating power (forms give 1pt, balanced give up to 5pts) but doesn't dominate scoring.

## analyze.py Structure

```
run_westock(*args)        # subprocess call to westock-data CLI (only used if kline file missing)
fetch_kline(code, retries) # Fetch with retry (only used if kline file missing)
load_etfs()               # Load ETF codes from all_etfs_larggest.json
lin_slope(arr, win)        # Shared helper: linear regression slope
score_w_bottom(...)        # Phase detection + 8-dim scoring engine
main()                     # Orchestrator
```

### main() Flow
1. Load ETF list from `all_etfs_larggest.json`
2. Check `etf_kline_data.json` → load if exists, fetch+save if not
3. Run phase pipeline + scoring on each ETF
4. Save results to `etf_w_bottom_results.json` (in skill dir)

## Dependencies

- **Input**: `etf_kline_data.json` (project root, 11.4MB, 338 ETFs, newest-first daily K-lines)
- **ETF list**: `all_etfs_larggest.json` (project root, reused by all ETF scanners)
- **Python**: `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`
- **westock-data** (only if kline file missing): `/Applications/WorkBuddy.app/.../westock-data/scripts/index.js`
- **Shared helpers**: `lin_slope()` reused from existing scanner code pattern

## Report Output

- **Format**: Self-contained HTML with Chart.js sparklines
- **A-share color convention**: Red = up (涨), green = down (跌)
- **Sell-side style tags**: 超配/标配/低配 (not required at scanner level, but available for deep analysis follow-up)
- **Layout**: TOP N ranking table + detail cards per ETF with W-bottom phase annotations
