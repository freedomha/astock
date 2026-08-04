# ETF Skills Shared K-line Data

**Date:** 2026-08-04
**Status:** Implemented

## Problem

Four ETF scanner skills (bowl-bottom, 2b-bottom, box, head-shoulder-bottom) each independently fetched the same 250-day K-line data for the same 352 ETFs, creating ~44 MB of redundant data (`etf_kline_data.json` in each skill directory). This waste multiplied: 4 scans meant 4 redundant fetch cycles for identical data.

## Solution

All ETF scanner skills now share a single `etf_kline_data.json` in the project root. Each skill's `analyze.py` checks for the shared file before fetching:

- **File exists** → load from it (skip network fetch)
- **File missing** → fetch all 352 ETFs, save to shared file, then proceed with analysis

Each skill's `generate_report.py` also reads from the shared file.

## Changes Made

8 files modified across 4 skills:

| Skill | analyze.py | generate_report.py |
|-------|-----------|-------------------|
| etf-bowl-bottom-scanner | Add check-before-fetch + save to cwd | Read from cwd |
| etf-2b-bottom-scanner | Add check-before-fetch + save to cwd | Read from cwd |
| etf-box-scanner | Add check-before-fetch + save to cwd | Read from cwd |
| etf-head-shoulder-bottom-scanner | Change path from skill_dir to cwd | Read from cwd |

Pattern for `analyze.py`:
```python
kline_file = os.path.join(os.getcwd(), "etf_kline_data.json")
if os.path.exists(kline_file):
    # load from shared file
else:
    # fetch + save to shared file
```

Pattern for `generate_report.py`:
```python
kline_file = os.path.join(cwd, "etf_kline_data.json")
```

## Design Decisions

- **Per-skill copies of utility functions** — each skill keeps its own `run_westock()`, `fetch_kline()`, `load_etfs()`. No shared utility module. Simpler, no import dependencies.
- **Results files stay per-skill** — `etf_bowl_results.json`, `etf_2b_bottom_results.json`, etc. remain in their skill directories. Only K-line data is shared.
- **No auto-refresh** — if shared file exists, it's used as-is. User must delete it to trigger a fresh fetch.

## Files Not Changed

- `etf-deep-analysis` — no Python scripts, fetches on-the-fly for single ETF analysis
- SKILL.md files — documentation references still mention old paths (non-critical)
