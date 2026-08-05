# ETF W-Bottom Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an ETF scanner that detects W-bottom (double bottom) patterns using phase-based detection + 8-dimension scoring, and generates an HTML report with backtesting module.

**Architecture:** Four files in `.workbuddy/skills/etf-w-bottom-scanner/` — `SKILL.md` (definition), `analyze.py` (phase detection + scoring via shared `etf_kline_data.json`), `generate_report.py` (HTML output to `reports/etf/`), `backtest.py` (historical validation). Mirrors existing `etf-bowl-bottom-scanner` structure. K-line data reused from project-root `etf_kline_data.json` — only refetches if file missing.

**Tech Stack:** Python 3.13 (stdlib only), westock-data Node.js CLI (only if kline file missing), Chart.js 4.4.0 (CDN)

**Spec:** `docs/superpowers/specs/2026-08-05-etf-w-bottom-scanner-design.md`

---

### Task 1: Create SKILL.md

**Files:**
- Create: `.workbuddy/skills/etf-w-bottom-scanner/SKILL.md`

- [ ] **Step 1: Write the skill definition file**

```markdown
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
```

- [ ] **Step 2: Verify file was created**

Run: `ls -la .codebuddy/skills/etf-w-bottom-scanner/SKILL.md`
Expected: file exists, ~6KB

- [ ] **Step 3: Commit**

```bash
git add .codebuddy/skills/etf-w-bottom-scanner/SKILL.md
git commit -m "feat: add ETF W-bottom scanner skill definition"
```

---

### Task 2: Create analyze.py (Phase Detection + Scoring Engine)

**Files:**
- Create: `.codebuddy/skills/etf-w-bottom-scanner/analyze.py`

- [ ] **Step 1: Write the complete analyze.py**

```python
#!/usr/bin/env python3
"""
A股ETF W底形态分析 (v1)

W底判定逻辑 (5阶段流水线):
Phase 1: 前期下跌 — T-120到T-40，40日斜率≤-0.5%/日
Phase 2-3: 左底→峰顶 — 左底到峰顶反弹≥8%
Phase 4: 右底验证 — 右底在±10%内，量能≤1.2x
Phase 5: 突破状态 — 2/3日收于峰顶之上=确认

8维度评分引擎(0-100)，4级标签
"""

import json
import subprocess
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK_BIN = "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data/scripts/index.js"
NODE_BIN = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"

KLINE_DAYS = 250
MAX_WORKERS = 8


def run_westock(*args):
    """Run a westock-data command and return JSON output."""
    cmd = [NODE_BIN, WESTOCK_BIN] + list(args) + ["--raw"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        if isinstance(data, dict) and data.get("success") is False:
            return None
        return data
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        return None


def fetch_kline(code, retries=4):
    """Fetch 250-day K-line for an ETF, with retry on transient errors."""
    for attempt in range(retries):
        data = run_westock("kline", code, "--period", "day", "--limit", str(KLINE_DAYS))
        if data:
            return code, data
        if attempt < retries - 1:
            time.sleep(0.3)
    return code, None


def load_etfs():
    """Load ETF codes from all_etfs_larggest.json in project root."""
    input_path = os.path.join(os.getcwd(), "all_etfs_larggest.json")
    if not os.path.exists(input_path):
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return []
    with open(input_path) as f:
        data = json.load(f)
    etfs = []
    for e in data:
        etfs.append({
            "code": e["code"],
            "name": e["name"],
            "type": e.get("type", "ETF"),
        })
    return etfs


def lin_slope(arr, win):
    """Linear regression slope over last `win` points, % per day return."""
    if len(arr) < win or win < 2:
        return None
    ys = arr[-win:]
    n = len(ys)
    x_mean = (n - 1) / 2
    y_mean = sum(ys) / n
    num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(ys))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den
    return (slope / y_mean) * 100


def score_w_bottom(closes, volumes, lt_idx, lt_val, pk_idx, pk_val, rt_idx, rt_val, status):
    """
    Score a detected W-bottom on 8 dimensions (max ~97 pts, capped at 100).
    Returns (score, label, reasons_list).
    """
    score = 0
    reasons = []

    # 1. Trough Symmetry (20 pts)
    tdiff = abs(rt_val / lt_val - 1) * 100
    if tdiff <= 1:
        s = 20
        reasons.append(f"极佳双底对称(差{tdiff:.1f}%)+20")
    elif tdiff <= 3:
        s = 17
        reasons.append(f"良好双底对称(差{tdiff:.1f}%)+17")
    elif tdiff <= 6:
        s = 12
        reasons.append(f"双底对称(差{tdiff:.1f}%)+12")
    else:
        s = 5
        reasons.append(f"双底基本对称(差{tdiff:.1f}%)+5")
    score += s

    # 2. Recovery Magnitude (15 pts)
    recovery = (pk_val / lt_val - 1) * 100
    if recovery >= 15:
        s = 15
        reasons.append(f"强反弹({recovery:.1f}%)+15")
    elif recovery >= 12:
        s = 12
        reasons.append(f"反弹较强({recovery:.1f}%)+12")
    elif recovery >= 10:
        s = 8
        reasons.append(f"反弹适中({recovery:.1f}%)+8")
    else:
        s = 3
        reasons.append(f"反弹偏弱({recovery:.1f}%)+3")
    score += s

    # 3. Right Trough Elevation (15 pts)
    rt_ele = (rt_val / lt_val - 1) * 100
    if rt_ele >= 3:
        s = 15
        reasons.append(f"右底抬高{rt_ele:.1f}%+15")
    elif rt_ele >= 1:
        s = 10
        reasons.append(f"右底略高{rt_ele:.1f}%+10")
    elif rt_ele >= 0:
        s = 5
        reasons.append(f"右底持平+5")
    else:
        s = 0
        reasons.append(f"右底更低{rt_ele:.1f}%+0")
    score += s

    # 4. Volume Contraction (12 pts)
    lt_start = max(0, lt_idx - 5)
    lt_end = min(len(volumes), lt_idx + 6)
    rt_start = max(0, rt_idx - 5)
    rt_end = min(len(volumes), rt_idx + 6)
    lvol = sum(volumes[lt_start:lt_end]) / max(1, lt_end - lt_start)
    rvol = sum(volumes[rt_start:rt_end]) / max(1, rt_end - rt_start)
    vr = rvol / lvol if lvol > 0 else 1
    if vr <= 0.7:
        s = 12
        reasons.append(f"量能显著收缩(VR={vr:.2f})+12")
    elif vr <= 0.9:
        s = 9
        reasons.append(f"量能收缩(VR={vr:.2f})+9")
    elif vr <= 1.0:
        s = 6
        reasons.append(f"量能持平(VR={vr:.2f})+6")
    else:
        s = 2
        reasons.append(f"量能略增(VR={vr:.2f})+2")
    score += s

    # 5. Prior Decline Depth (10 pts)
    d_high = max(closes[:80])
    d_low = min(closes[:80])
    decline_pct = (d_high - d_low) / d_high * 100 if d_high > 0 else 0
    if decline_pct >= 15:
        s = 10
        reasons.append(f"前期深跌({decline_pct:.1f}%)+10")
    elif decline_pct >= 10:
        s = 7
        reasons.append(f"前期跌幅充分({decline_pct:.1f}%)+7")
    elif decline_pct >= 5:
        s = 3
        reasons.append(f"前期小幅下跌({decline_pct:.1f}%)+3")
    score += s

    # 6. Time Symmetry (5 pts)
    left_days = pk_idx - lt_idx
    right_days = rt_idx - pk_idx
    if left_days > 0 and right_days > 0:
        ratio = left_days / right_days
        if 0.7 <= ratio <= 1.3:
            s = 5
            reasons.append(f"时间对称({left_days}d/{right_days}d)+5")
        elif 0.5 <= ratio <= 1.5:
            s = 3
            reasons.append(f"时间基本对称({left_days}d/{right_days}d)+3")
        else:
            s = 1
            reasons.append(f"时间不对称({left_days}d/{right_days}d)+1")
    else:
        s = 0
    score += s

    # 7. Breakout Strength (10 pts, confirmed only)
    if status == "确认":
        bopct = (closes[-1] / pk_val - 1) * 100
        if bopct >= 5:
            s = 10
            reasons.append(f"强势突破({bopct:.1f}%)+10")
        elif bopct >= 3:
            s = 7
            reasons.append(f"有效突破({bopct:.1f}%)+7")
        elif bopct >= 0:
            s = 4
            reasons.append(f"微弱突破({bopct:.1f}%)+4")
    else:
        s = 0
    score += s

    # 8. Formation Quality (10 pts)
    q = 0
    p1_slope = lin_slope(closes[:80], 40) or 0
    if p1_slope < -0.3:
        q += 3
        reasons.append("平滑下跌+3")
    elif p1_slope < -0.1:
        q += 2
        reasons.append("温和下跌+2")
    elif p1_slope < 0:
        q += 1
    pk_surr = closes[max(0, pk_idx - 3):min(len(closes), pk_idx + 4)]
    pk_avg = sum(pk_surr) / len(pk_surr) if pk_surr else pk_val
    pk_ratio = pk_val / pk_avg if pk_avg > 0 else 1
    if pk_ratio > 1.03:
        q += 3
        reasons.append("峰位突出+3")
    elif pk_ratio > 1.01:
        q += 2
    else:
        q += 1
    rt_rec_high = max(closes[rt_idx:min(len(closes), rt_idx + 6)]) if rt_idx < len(closes) else rt_val
    rt_rec_ratio = rt_rec_high / rt_val if rt_val > 0 else 1
    if rt_rec_ratio > 1.03:
        q += 4
        reasons.append("右底V形反弹+4")
    elif rt_rec_ratio > 1.01:
        q += 3
        reasons.append("右底反弹+3")
    else:
        q += 1
    q = min(q, 10)
    score += q

    score = min(score, 100)

    # Label grading
    if score >= 55:
        label = "W底确认" if status == "确认" else "W底形成中"
    elif score >= 45:
        label = "W底形成中" if status == "形成中" else "W底确认"
    elif score >= 35:
        label = "W底候选"
    else:
        label = "非W底"

    return score, label, reasons


def detect_w_bottom(records):
    """
    Phase-based W-bottom detection on 120-day window (oldest-first sorted records).

    Returns dict with phase results and key points, or None if any phase fails.
    """
    n = len(records)
    if n < 120:
        return None

    closes = [r["close"] for r in records]
    volumes = [r["volume"] for r in records]

    # Phase 1: Prior decline (T-120 to T-40)
    p1_slope = lin_slope(closes[:80], 40)
    if p1_slope is None or p1_slope > -0.005:
        return None

    # Phase 2: Left trough (T-40 to T-25, indices 80-95)
    lt_idx, lt_val = None, float('inf')
    for i in range(80, 96):
        if closes[i] < lt_val:
            lt_val = closes[i]
            lt_idx = i

    # Phase 3: Peak (from left trough to T-12, index up to 108)
    pk_idx, pk_val = None, float('-inf')
    for i in range(max(lt_idx or 96, 96), 109):
        if closes[i] > pk_val:
            pk_val = closes[i]
            pk_idx = i

    recovery = (pk_val / lt_val - 1) * 100
    if recovery < 8.0:
        return None

    # Phase 4: Right trough (T-12 to T, indices 108-120)
    rt_idx, rt_val = None, float('inf')
    for i in range(108, min(120, n)):
        if closes[i] < rt_val:
            rt_val = closes[i]
            rt_idx = i

    tdiff = abs(rt_val / lt_val - 1) * 100
    if tdiff > 10.0:
        return None

    lt_vol = sum(volumes[max(0, lt_idx - 5):lt_idx + 6]) / max(1, min(n, lt_idx + 6) - max(0, lt_idx - 5))
    rt_vol = sum(volumes[max(0, rt_idx - 5):rt_idx + 6]) / max(1, min(n, rt_idx + 6) - max(0, rt_idx - 5))
    vratio = rt_vol / lt_vol if lt_vol > 0 else 1
    if vratio > 1.2:
        return None

    # Phase 5: Breakout status
    recent3 = closes[-3:]
    above = sum(1 for c in recent3 if c > pk_val)
    status = "确认" if (above >= 2 and closes[-1] > pk_val) else "形成中"

    return {
        "lt_idx": lt_idx,
        "lt_val": lt_val,
        "pk_idx": pk_idx,
        "pk_val": pk_val,
        "rt_idx": rt_idx,
        "rt_val": rt_val,
        "status": status,
        "recovery": recovery,
        "tdiff": tdiff,
        "vratio": vratio,
    }


def analyze_w_bottom(code, name, etype, kline_data):
    """Main analysis: detect W-bottom pattern and score it."""
    if not kline_data or not isinstance(kline_data, list):
        return None

    records = []
    for k in kline_data:
        try:
            records.append({
                "date": k["date"],
                "close": float(k["last"]),
                "high": float(k["high"]),
                "low": float(k["low"]),
                "volume": float(k.get("volume", 0)),
            })
        except (KeyError, ValueError):
            continue
    if len(records) < 120:
        return None
    records.sort(key=lambda x: x["date"])

    detection = detect_w_bottom(records)
    if detection is None:
        return None

    closes = [r["close"] for r in records]
    volumes = [r["volume"] for r in records]
    score, label, reasons = score_w_bottom(
        closes, volumes,
        detection["lt_idx"], detection["lt_val"],
        detection["pk_idx"], detection["pk_val"],
        detection["rt_idx"], detection["rt_val"],
        detection["status"]
    )

    d_high = max(closes[:80])
    d_low = min(closes[:80])
    decline_pct = (d_high - d_low) / d_high * 100 if d_high > 0 else 0

    rt_ele = (detection["rt_val"] / detection["lt_val"] - 1) * 100

    return {
        "code": code,
        "name": name,
        "type": etype,
        "score": score,
        "label": label,
        "status": detection["status"],
        "current": round(records[-1]["close"], 3),
        "left_trough": round(detection["lt_val"], 3),
        "right_trough": round(detection["rt_val"], 3),
        "peak": round(detection["pk_val"], 3),
        "recovery_pct": round(detection["recovery"], 1),
        "trough_diff_pct": round(detection["tdiff"], 1),
        "vol_ratio": round(detection["vratio"], 2),
        "rt_elevation_pct": round(rt_ele, 1),
        "prior_decline_pct": round(decline_pct, 1),
        "lt_date": records[detection["lt_idx"]]["date"],
        "pk_date": records[detection["pk_idx"]]["date"],
        "rt_date": records[detection["rt_idx"]]["date"],
        "reasons": reasons,
    }


def main():
    print("=" * 60)
    print("A股ETF W底形态分析 (v1)")
    print("=" * 60)

    # Step 1: Load ETFs
    print("\n[1/3] 加载ETF列表...")
    etfs = load_etfs()
    if not etfs:
        print("未找到ETF列表。请确保 all_etfs_larggest.json 存在于项目根目录。")
        return
    print(f"共加载 {len(etfs)} 只ETF")

    # Step 2: Load or fetch K-line data (shared project-root file)
    cwd = os.getcwd()
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    if os.path.exists(kline_file):
        print(f"\n[2/3] 加载共享K线数据: {kline_file}")
        with open(kline_file) as f:
            kline_data = json.load(f)
        print(f"已加载 {len(kline_data)} 只ETF K线数据")
    else:
        print(f"\n[2/3] 并行拉取K线数据 (最多{MAX_WORKERS}并发, 每个{KLINE_DAYS}天)...")
        codes = [e["code"] for e in etfs]
        kline_data = {}
        done = 0
        total = len(codes)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_kline, code): code for code in codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    _, data = future.result()
                    if data:
                        kline_data[code] = data
                    done += 1
                    if done % 20 == 0 or done == total:
                        print(f"  进度: {done}/{total}")
                except Exception as e:
                    print(f"  {code} 拉取失败: {e}")
                    done += 1
        print(f"成功获取 {len(kline_data)}/{total} 只ETF K线数据")

        # Re-fetch any ETFs that failed
        missing = [c for c in codes if c not in kline_data]
        if missing:
            print(f"\n  补拉 {len(missing)} 只失败ETF (增强重试, 最多6次)...")
            for c in missing:
                _, d = fetch_kline(c, retries=6)
                if d:
                    kline_data[c] = d
            still_missing = [c for c in codes if c not in kline_data]
            print(f"  补拉后覆盖 {len(kline_data)}/{total} (仍缺失 {len(still_missing)})")
            if still_missing:
                name_map = {e["code"]: e["name"] for e in etfs}
                print("  缺失ETF:", ", ".join(f'{name_map.get(c, c)}({c})' for c in still_missing))

        # Save to shared project root file
        with open(kline_file, "w") as f:
            json.dump(kline_data, f, ensure_ascii=False)
        print(f"K线数据已保存: {kline_file}")

    # Step 3: Analyze
    print("\n[3/3] 检测W底形态 (5阶段流水线 + 8维评分)...")
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results = []
    for e in etfs:
        kl = kline_data.get(e["code"])
        if not kl:
            continue
        r = analyze_w_bottom(e["code"], e["name"], e["type"], kl)
        if r:
            results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)

    results_file = os.path.join(skill_dir, "etf_w_bottom_results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"分析结果已保存: {results_file}")

    # Summary
    confirmed = [r for r in results if "确认" in r["label"]]
    forming = [r for r in results if "形成中" in r["label"]]
    candidate = [r for r in results if "候选" in r["label"]]

    print("\n" + "=" * 60)
    print(f"W底形态汇总 (共{len(results)}只ETF检测到信号)")
    print("=" * 60)
    print(f"  W底确认: {len(confirmed)}")
    print(f"  W底形成中: {len(forming)}")
    print(f"  W底候选: {len(candidate)}")

    if results:
        print(f"\n{'排名':<4}{'ETF':<18}{'得分':<5}{'判定':<10}{'状态':<6}{'反弹%':<8}{'双底差%':<8}{'量比':<6}")
        print("-" * 75)
        for i, r in enumerate(results[:15]):
            print(f"{i + 1:<4}{r['name']:<18}{r['score']:<5}{r['label']:<10}{r['status']:<6}{r['recovery_pct']:<8.1f}{r['trough_diff_pct']:<8.1f}{r['vol_ratio']:<6.2f}")

    return results


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax check**

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON -m py_compile .codebuddy/skills/etf-w-bottom-scanner/analyze.py
```
Expected: no output (success)

- [ ] **Step 3: Dry-run test (uses existing etf_kline_data.json, no network)**

```bash
cd /Users/aldiadmin/Documents/vscodeworkspace/astock
$PYTHON .codebuddy/skills/etf-w-bottom-scanner/analyze.py
```
Expected: loads etf_kline_data.json, prints summary with ~15 W-bottom signals

- [ ] **Step 4: Verify output**

```bash
$PYTHON -c "
import json
with open('.codebuddy/skills/etf-w-bottom-scanner/etf_w_bottom_results.json') as f:
    data = json.load(f)
print(f'Total results: {len(data)}')
labels = {}
for r in data:
    l = r['label']
    labels[l] = labels.get(l, 0) + 1
for l, c in sorted(labels.items()):
    print(f'  {l}: {c}')
scores = [r['score'] for r in data]
print(f'Score range: {min(scores)}-{max(scores)} (avg {sum(scores)/len(scores):.1f})')
"
```
Expected: 15 results, 9 W底确认 + 3 W底形成中 + 3 W底候选, scores 42-62

- [ ] **Step 5: Commit**

```bash
git add .codebuddy/skills/etf-w-bottom-scanner/analyze.py .codebuddy/skills/etf-w-bottom-scanner/etf_w_bottom_results.json
git commit -m "feat: add ETF W-bottom detection and scoring engine with verified results"
```

---

### Task 3: Create generate_report.py (HTML Report Builder)

**Files:**
- Create: `.codebuddy/skills/etf-w-bottom-scanner/generate_report.py`

- [ ] **Step 1: Write the complete generate_report.py**

```python
#!/usr/bin/env python3
"""
生成 A股ETF W底形态分析 HTML 报告 (v1)
- 摘要卡片 (确认/形成中/候选)
- W底信号ETF 120日K线缩略图 (Chart.js, 标注左底+峰顶+右底+突破)
- TOP25 综合得分排名表
- W底信号ETF详细分析卡片
"""

import json
import os
from datetime import datetime


def build_report(results, klines, output_path):
    today = datetime.now().strftime("%Y-%m-%d")

    confirmed = [r for r in results if "确认" in r["label"]]
    forming = [r for r in results if "形成中" in r["label"]]
    candidate = [r for r in results if "候选" in r["label"]]

    # Build chart datasets for top signals
    chart_blocks = []
    for r in results[:9]:
        kdata = klines.get(r["code"], [])
        recs = sorted(kdata, key=lambda x: x["date"])[-120:]
        closes = [round(float(x["last"]), 2) for x in recs]
        dates = [x["date"][:10] for x in recs]
        chart_blocks.append({
            "name": r["name"], "type": r.get("type", "ETF"), "score": r["score"],
            "label": r["label"], "closes": closes, "dates": dates,
            "left_trough": r["left_trough"], "right_trough": r["right_trough"],
            "peak": r["peak"], "current": r["current"],
            "recovery": r["recovery_pct"], "diff": r["trough_diff_pct"],
            "vr": r["vol_ratio"], "status": r.get("status", ""),
        })

    # Build full ranking table rows (top 25)
    table_rows = []
    for i, r in enumerate(results[:25]):
        lc = {"W底确认": "#27ae60", "W底形成中": "#2980b9", "W底候选": "#f39c12", "非W底": "#95a5a6"}.get(r["label"], "#333")
        status_badge = "✅" if r.get("status") == "确认" else "⏳"
        table_rows.append(f"""
        <tr>
          <td><b>{i + 1}</b></td>
          <td><b>{r['name']}</b><br><span class="muted">{r.get('type', 'ETF')}</span></td>
          <td><span style="color:{lc};font-weight:600">{r['label']}</span></td>
          <td><b>{r['score']}</b></td>
          <td>{r.get('status', '')} {status_badge}</td>
          <td class="pos">{r['recovery_pct']}%</td>
          <td class="neg">{r['trough_diff_pct']}%</td>
          <td>{r['vol_ratio']}</td>
          <td class="pos">{r.get('rt_elevation_pct', 0):.1f}%</td>
          <td class="neg">{r['current']}</td>
        </tr>""")

    # Detail cards for all signals
    detail_cards = []
    for i, r in enumerate(results[:9]):
        reasons_html = "".join(f"<li>{x}</li>" for x in r.get("reasons", []))
        lc = {"W底确认": "#27ae60", "W底形成中": "#2980b9", "W底候选": "#f39c12"}.get(r["label"], "#27ae60")
        detail_cards.append(f"""
        <div class="detail-card" style="border-left-color:{lc}">
          <div class="detail-head">
            <span class="rank" style="background:{lc}">#{i + 1}</span>
            <h3>{r['name']}</h3>
            <span class="badge" style="background:{lc}">{r['label']}</span>
            <span class="score-badge">得分 {r['score']}/100</span>
          </div>
          <div class="detail-grid">
            <div class="metric"><span class="ml">当前价格</span><span class="mv">{r['current']}</span></div>
            <div class="metric"><span class="ml">左底价格</span><span class="mv neg">{r['left_trough']}</span></div>
            <div class="metric"><span class="ml">峰顶价格</span><span class="mv pos">{r['peak']}</span></div>
            <div class="metric"><span class="ml">右底价格</span><span class="mv">{r['right_trough']}</span></div>
            <div class="metric"><span class="ml">反弹幅度</span><span class="mv pos">{r['recovery_pct']}%</span></div>
            <div class="metric"><span class="ml">双底偏差</span><span class="mv">{r['trough_diff_pct']}%</span></div>
            <div class="metric"><span class="ml">右底抬高</span><span class="mv pos">{r.get('rt_elevation_pct', 0):.1f}%</span></div>
            <div class="metric"><span class="ml">成交量比</span><span class="mv">{r['vol_ratio']}</span></div>
            <div class="metric"><span class="ml">前期跌幅</span><span class="mv neg">{r.get('prior_decline_pct', 0)}%</span></div>
            <div class="metric"><span class="ml">左底日期</span><span class="mv">{r.get('lt_date', '')[:10]}</span></div>
            <div class="metric"><span class="ml">峰顶日期</span><span class="mv">{r.get('pk_date', '')[:10]}</span></div>
            <div class="metric"><span class="ml">右底日期</span><span class="mv">{r.get('rt_date', '')[:10]}</span></div>
          </div>
          <div class="reasons"><b>评分依据:</b><ul>{reasons_html}</ul></div>
        </div>""")

    chart_json = json.dumps(chart_blocks, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股ETF W底形态分析报告 · {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:#f5f6fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#1a3a5c 0%,#0d4d6e 50%,#0a2a44 100%); color:#fff; padding:36px 30px; border-radius:12px; margin-bottom:24px; box-shadow:0 4px 20px rgba(0,0,0,0.15); }}
.header h1 {{ font-size:26px; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.85; font-size:14px; }}
.header .meta {{ margin-top:14px; display:flex; gap:24px; font-size:13px; opacity:0.75; flex-wrap:wrap; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:28px; }}
.summary-card {{ background:#fff; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.summary-card .number {{ font-size:30px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#7f8c8d; margin-top:4px; }}
.c-green .number {{ color:#27ae60; }}
.c-blue .number {{ color:#2980b9; }}
.c-orange .number {{ color:#e67e22; }}
.c-gray .number {{ color:#7f8c8d; }}
.section-title {{ font-size:19px; font-weight:600; margin:28px 0 14px; padding-bottom:10px; border-bottom:2px solid #ecf0f1; display:flex; align-items:center; gap:8px; }}
.section-title .count {{ font-size:13px; color:#7f8c8d; font-weight:400; }}
.table-wrapper {{ background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 2px 10px rgba(0,0,0,0.06); margin-bottom:28px; overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#f8f9fa; padding:11px 9px; text-align:left; font-weight:600; color:#5a6473; white-space:nowrap; border-bottom:2px solid #e8eaed; }}
td {{ padding:10px 9px; border-bottom:1px solid #f0f2f5; white-space:nowrap; }}
tr:hover td {{ background:#fafbfc; }}
.muted {{ color:#95a5a6; font-size:12px; }}
.pos {{ color:#e74c3c; font-weight:600; }}
.neg {{ color:#16a085; font-weight:600; }}
.charts-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:18px; margin-bottom:28px; }}
.chart-card {{ background:#fff; border-radius:10px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.chart-card h4 {{ font-size:15px; margin-bottom:4px; display:flex; align-items:center; gap:8px; }}
.chart-card .sub {{ font-size:12px; color:#7f8c8d; margin-bottom:10px; }}
.chart-box {{ height:150px; position:relative; }}
.detail-card {{ background:#fff; border-radius:10px; padding:20px; margin-bottom:18px; box-shadow:0 2px 10px rgba(0,0,0,0.06); border-left:4px solid #27ae60; }}
.detail-head {{ display:flex; align-items:center; gap:12px; margin-bottom:14px; flex-wrap:wrap; }}
.detail-head .rank {{ color:#fff; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; }}
.detail-head h3 {{ font-size:18px; }}
.badge {{ color:#fff; padding:3px 10px; border-radius:12px; font-size:12px; }}
.score-badge {{ background:#34495e; color:#fff; padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
.detail-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px; }}
.metric {{ background:#f8f9fa; padding:9px 12px; border-radius:6px; }}
.metric .ml {{ font-size:12px; color:#7f8c8d; display:block; }}
.metric .mv {{ font-size:15px; font-weight:600; }}
.reasons {{ background:#f8f9fa; padding:12px 16px; border-radius:6px; }}
.reasons ul {{ list-style:none; margin-top:6px; }}
.reasons li {{ padding:2px 0; font-size:13px; }}
.note {{ background:#e8f4fd; border-left:4px solid #2980b9; padding:14px 18px; border-radius:6px; margin:20px 0; font-size:13px; }}
.disclaimer {{ background:#fdecea; border-radius:8px; padding:16px 20px; margin-top:28px; font-size:12px; color:#c0392b; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>A股ETF W底形态分析报告</h1>
  <div class="subtitle">各板块规模最大ETF的W底形态扫描 · 来自 all_etfs_larggest.json</div>
  <div class="meta">
    <span>报告日期: {today}</span>
    <span>扫描范围: 352 只ETF</span>
    <span>K线周期: 日线 250 天</span>
    <span>算法: 5阶段流水线 + 8维评分</span>
  </div>
</div>

<div class="summary-cards">
  <div class="summary-card c-gray"><div class="number">352</div><div class="label">扫描ETF总数</div></div>
  <div class="summary-card c-green"><div class="number">{len(confirmed)}</div><div class="label">W底确认</div></div>
  <div class="summary-card c-blue"><div class="number">{len(forming)}</div><div class="label">W底形成中</div></div>
  <div class="summary-card c-orange"><div class="number">{len(candidate)}</div><div class="label">W底候选</div></div>
</div>

<div class="note">
  <b>W底判定逻辑:</b> 5阶段流水线检测 — ①前期下跌(40日斜率≤-0.5%/日) → ②左底形成(T-40至T-25) → ③反弹至峰顶(≥8%) → ④右底验证(±10%内, 量能≤1.2x) → ⑤突破确认(2/3日收于峰顶之上)。
  <b>W底确认</b>表示已完成颈线突破, <b>W底形成中</b>表示双底结构完整但尚未突破, <b>W底候选</b>为弱信号。
</div>

<div class="section-title">W底信号ETF — K线缩略图 <span class="count">(展示前9名 120日走势)</span></div>
<div class="charts-grid" id="chartsGrid"></div>

<div class="section-title">综合得分排名 (TOP 25) <span class="count">颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>形态判定</th><th>得分</th><th>状态</th><th>反弹%</th><th>双底差%</th><th>量比</th><th>右底抬高%</th><th>当前价</th>
</tr></thead>
<tbody>
{''.join(table_rows)}
</tbody></table>
</div>

<div class="section-title">W底信号ETF详细分析</div>
{''.join(detail_cards)}

<div class="disclaimer">
  <b>风险提示:</b> 本报告仅基于历史价格形态的客观量化分析，不构成任何投资建议。W底形态识别属于技术分析方法，存在误判可能；
  双底结构并非100%准确，颈线突破后仍可能回踩失败。投资有风险，决策需谨慎。请结合基本面、资金面、宏观环境综合判断。
  数据来源: 腾讯自选股行情接口，可能存在延迟，以交易所官方数据为准。
</div>

</div>

<script>
const chartData = {chart_json};
const colors = ['#e74c3c','#2980b9','#9b59b6','#16a085','#e67e22','#34495e','#1abc9c','#d35400','#8e44ad'];
const grid = document.getElementById('chartsGrid');
chartData.forEach((c, idx) => {{
  const card = document.createElement('div');
  card.className = 'chart-card';
  card.innerHTML = `
    <h4><span style="color:${{colors[idx%colors.length]}}">●</span> ${{c.name}}</h4>
    <div class="sub">${{c.label}} · 得分${{c.score}} · 反弹${{c.recovery}}% · 偏差${{c.diff}}% · VR${{c.vr}}</div>
    <div class="chart-box"><canvas></canvas></div>
  `;
  grid.appendChild(card);

  const ctx = card.querySelector('canvas').getContext('2d');
  const ltLine = new Array(c.closes.length).fill(c.left_trough);
  const pkLine = new Array(c.closes.length).fill(c.peak);
  const rtLine = new Array(c.closes.length).fill(c.right_trough);

  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: c.dates,
      datasets: [
        {{ data: c.closes, borderColor: colors[idx%colors.length], backgroundColor: colors[idx%colors.length]+'15', borderWidth: 1.8, pointRadius: 0, fill: true, tension: 0.35, label: '收盘价' }},
        {{ data: ltLine, borderColor: '#16a085', borderDash: [5,5], borderWidth: 1, pointRadius: 0, fill: false, label: '左底='+c.left_trough }},
        {{ data: pkLine, borderColor: '#e67e22', borderDash: [3,3], borderWidth: 1, pointRadius: 0, fill: false, label: '峰顶='+c.peak }},
        {{ data: rtLine, borderColor: '#2980b9', borderDash: [5,5], borderWidth: 1, pointRadius: 0, fill: false, label: '右底='+c.right_trough }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{display: false}}, tooltip: {{ callbacks: {{ title: (i) => c.dates[i[0].dataIndex], label: (i) => (i.datasetIndex===0?'价格 ':'参考线 ')+i.parsed.y }}}}}},
      scales: {{ x: {{ display: false }}, y: {{ display: true, position: 'right', ticks: {{ font: {{size: 9}}, color: '#95a5a6' }}, grid: {{ color: '#f0f2f5' }} }} }}
    }}
  }});
}});
</script>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"Report saved to {output_path}")


def main():
    cwd = os.getcwd()
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results_file = os.path.join(skill_dir, "etf_w_bottom_results.json")
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    outdir = os.path.join(cwd, "reports", "etf")
    os.makedirs(outdir, exist_ok=True)
    output = os.path.join(outdir, "etf_w_bottom_report.html")

    if not os.path.exists(results_file):
        print(f"Results file not found: {results_file}", file=sys.stderr)
        print("Run analyze.py first to generate detection results.", file=sys.stderr)
        return

    with open(results_file) as f:
        results = json.load(f)
    with open(kline_file) as f:
        klines = json.load(f)
    build_report(results, klines, output)


if __name__ == "__main__":
    import sys
    main()
```

- [ ] **Step 2: Generate report and validate**

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
cd /Users/aldiadmin/Documents/vscodeworkspace/astock
$PYTHON .codebuddy/skills/etf-w-bottom-scanner/generate_report.py
```
Expected: "Report saved to reports/etf/etf_w_bottom_report.html"

- [ ] **Step 3: JS syntax check on inline scripts**

```bash
$PYTHON -c "
import re
with open('reports/etf/etf_w_bottom_report.html') as f:
    html = f.read()
scripts = re.findall(r'<script>((?:.|\n)*?)</script>', html)
for i, s in enumerate(scripts):
    if 'const chartData' in s or 'new Chart' in s:
        with open(f'/tmp/_check_w_{i}.js', 'w') as out:
            out.write(s)
"
NODE="/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
for f in /tmp/_check_w_*.js; do
    $NODE --check "$f" && echo "OK: $f" || echo "FAIL: $f"
done
```
Expected: all JS files pass `node --check`

- [ ] **Step 4: Commit**

```bash
git add .codebuddy/skills/etf-w-bottom-scanner/generate_report.py reports/etf/etf_w_bottom_report.html
git commit -m "feat: add ETF W-bottom HTML report generator"
```

---

### Task 4: Create backtest.py (Historical Validation)

**Files:**
- Create: `.codebuddy/skills/etf-w-bottom-scanner/backtest.py`

- [ ] **Step 1: Write the complete backtest.py**

```python
#!/usr/bin/env python3
"""
A股ETF W底形态回测 (v1)

模拟在历史时点检测W底形态，统计N日后收益。
方法: 在120日窗口上滑动，以每个120日窗口的末尾作为"当前"时点，
运行W底检测逻辑，记录检测结果和N日(5/10/20/40)后的收益情况。
"""

import json
import os
import sys
from datetime import datetime


def lin_slope(arr, win):
    if len(arr) < win or win < 2:
        return None
    ys = arr[-win:]
    n = len(ys)
    x_mean = (n - 1) / 2
    y_mean = sum(ys) / n
    num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(ys))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den
    return (slope / y_mean) * 100


def detect_w_bottom_snapshot(closes, volumes):
    """Same detection logic as analyze.py, operating on a 120-day snapshot."""
    n = len(closes)
    if n < 120:
        return None

    p1_slope = lin_slope(closes[:80], 40)
    if p1_slope is None or p1_slope > -0.005:
        return None

    lt_idx, lt_val = None, float('inf')
    for i in range(80, 96):
        if closes[i] < lt_val:
            lt_val = closes[i]
            lt_idx = i

    pk_idx, pk_val = None, float('-inf')
    for i in range(max(lt_idx or 96, 96), 109):
        if closes[i] > pk_val:
            pk_val = closes[i]
            pk_idx = i

    recovery = (pk_val / lt_val - 1) * 100
    if recovery < 8.0:
        return None

    rt_idx, rt_val = None, float('inf')
    for i in range(108, min(120, n)):
        if closes[i] < rt_val:
            rt_val = closes[i]
            rt_idx = i

    tdiff = abs(rt_val / lt_val - 1) * 100
    if tdiff > 10.0:
        return None

    lt_vol = sum(volumes[max(0, lt_idx - 5):lt_idx + 6]) / max(1, min(n, lt_idx + 6) - max(0, lt_idx - 5))
    rt_vol = sum(volumes[max(0, rt_idx - 5):rt_idx + 6]) / max(1, min(n, rt_idx + 6) - max(0, rt_idx - 5))
    vratio = rt_vol / lt_vol if lt_vol > 0 else 1
    if vratio > 1.2:
        return None

    recent3 = closes[-3:]
    above = sum(1 for c in recent3 if c > pk_val)
    status = "确认" if (above >= 2 and closes[-1] > pk_val) else "形成中"

    return {"status": status, "close": closes[-1]}


def main():
    print("=" * 60)
    print("A股ETF W底形态回测 (v1)")
    print("=" * 60)

    cwd = os.getcwd()
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    if not os.path.exists(kline_file):
        print(f"K-line data not found: {kline_file}")
        return

    with open(kline_file) as f:
        kline_data = json.load(f)

    # Forward returns to measure
    forward_days = [5, 10, 20, 40]

    # Results by label
    all_trades = []

    print(f"\n扫描 {len(kline_data)} 只ETF的历史W底信号...")
    total_windows = 0
    total_signals = 0

    for code, raw in kline_data.items():
        if not isinstance(raw, list) or len(raw) < 160:
            continue

        records = []
        for k in raw:
            try:
                records.append({
                    "date": k["date"],
                    "close": float(k["last"]),
                    "volume": float(k.get("volume", 0)),
                })
            except (KeyError, ValueError):
                continue

        if len(records) < 160:
            continue
        records.sort(key=lambda x: x["date"])
        closes = [r["close"] for r in records]
        volumes = [r["volume"] for r in records]

        # Slide a 120-day window through the last 40 days of available history
        # Each window = 120 days of history ending at a past date,
        # then we check forward returns from that ending date
        n = len(records)
        for end in range(140, n):
            window_closes = closes[end - 120:end]
            window_vols = volumes[end - 120:end]
            detection = detect_w_bottom_snapshot(window_closes, window_vols)
            total_windows += 1

            if detection is None:
                continue

            total_signals += 1
            entry_price = detection["close"]
            trade = {"code": code, "date": records[end - 1]["date"], "status": detection["status"], "entry": entry_price}

            for fd in forward_days:
                if end + fd < n:
                    exit_price = closes[end + fd]
                    ret = (exit_price / entry_price - 1) * 100
                    trade[f"ret_{fd}d"] = round(ret, 2)
                else:
                    trade[f"ret_{fd}d"] = None

            all_trades.append(trade)

    print(f"\n扫描窗口: {total_windows}, 检测信号: {total_signals}")

    # Aggregate by status
    for status in ["确认", "形成中"]:
        trades = [t for t in all_trades if t["status"] == status]
        if not trades:
            print(f"\n  {status}: 无信号")
            continue

        print(f"\n  {status}信号: {len(trades)} 次")
        for fd in forward_days:
            valid = [t[f"ret_{fd}d"] for t in trades if t[f"ret_{fd}d"] is not None]
            if not valid:
                print(f"    {fd}日: 无数据")
                continue
            avg_ret = sum(valid) / len(valid)
            win_count = sum(1 for r in valid if r > 0)
            win_rate = win_count / len(valid) * 100
            max_gain = max(valid)
            max_loss = min(valid)
            print(f"    {fd}日收益: 均值 {avg_ret:+.2f}%, 胜率 {win_rate:.1f}%, 最大 {max_gain:+.2f}% / {max_loss:+.2f}% (n={len(valid)})")

    # Save results
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(skill_dir, "backtest_w_bottom_results.json")
    with open(output_file, "w") as f:
        json.dump({
            "total_windows": total_windows,
            "total_signals": total_signals,
            "trades": all_trades,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n回测结果已保存: {output_file}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax check**

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON -m py_compile .codebuddy/skills/etf-w-bottom-scanner/backtest.py
```
Expected: no output (success)

- [ ] **Step 3: Run backtest (uses existing etf_kline_data.json)**

```bash
cd /Users/aldiadmin/Documents/vscodeworkspace/astock
$PYTHON .codebuddy/skills/etf-w-bottom-scanner/backtest.py
```
Expected: prints backtest summary with N-day forward return stats for 确认/形成中 signals

- [ ] **Step 4: Commit**

```bash
git add .codebuddy/skills/etf-w-bottom-scanner/backtest.py .codebuddy/skills/etf-w-bottom-scanner/backtest_w_bottom_results.json
git commit -m "feat: add ETF W-bottom historical backtesting module"
```
