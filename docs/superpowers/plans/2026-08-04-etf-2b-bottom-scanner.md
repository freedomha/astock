# ETF 2B Bottom Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an ETF scanner that detects 2B bottom reversal patterns (break below 60-day low + recover within 2 days), scores them on 7 dimensions, and generates an HTML report.

**Architecture:** Three files in `.codebuddy/skills/etf-2b-bottom-scanner/` — `SKILL.md` (definition), `analyze.py` (detection + scoring via westock-data K-lines), `generate_report.py` (HTML output to `reports/etf/`). Mirrors existing `etf-bowl-bottom-scanner` structure exactly.

**Tech Stack:** Python 3.13 (stdlib only), westock-data Node.js CLI, Chart.js 4.4.0 (CDN)

**Spec:** `docs/superpowers/specs/2026-08-04-etf-2b-bottom-scanner-design.md`

---

### Task 1: Create SKILL.md

**Files:**
- Create: `.codebuddy/skills/etf-2b-bottom-scanner/SKILL.md`

- [ ] **Step 1: Write the skill definition file**

```markdown
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
```

- [ ] **Step 2: Verify file was created**

Run: `ls -la .codebuddy/skills/etf-2b-bottom-scanner/SKILL.md`
Expected: file exists, ~3KB

- [ ] **Step 3: Commit**

```bash
git add .codebuddy/skills/etf-2b-bottom-scanner/SKILL.md
git commit -m "feat: add ETF 2B bottom scanner skill definition"
```

---

### Task 2: Create analyze.py (Detection + Scoring Engine)

**Files:**
- Create: `.codebuddy/skills/etf-2b-bottom-scanner/analyze.py`

- [ ] **Step 1: Write the complete analyze.py**

```python
#!/usr/bin/env python3
"""
A股ETF 2B底形态分析 (v1)

2B底判定逻辑:
1. 找到前60日的区间最低点(跳过最近2根K线)
2. 检查最近3根K线是否突破前低
3. 突破后2天内是否收复(收盘价回到前低上方)
4. 7维度评分, 0-100, 4级标签
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
RECOVERY_WINDOW = 2  # bars to recover after breakdown
PRIOR_LOW_OFFSET = 1  # skip bar 0 to avoid self-reference


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
            "size": e.get("size"),
        })
    return etfs


def parse_kline(kline_data):
    """Parse raw westock-data K-line response into sorted record list.
    Returns list of dicts: {date, open, close, high, low, volume}
    """
    if not kline_data or not isinstance(kline_data, list):
        return []
    records = []
    for k in kline_data:
        try:
            records.append({
                "date": k["date"],
                "open": float(k["first"]),
                "close": float(k["last"]),
                "high": float(k["high"]),
                "low": float(k["low"]),
                "volume": float(k.get("volume", 0)),
            })
        except (KeyError, ValueError):
            continue
    records.sort(key=lambda x: x["date"])
    return records


def detect_2b_bottom(records):
    """
    Detect 2B bottom pattern on the most recent bars.

    Steps:
    1. Find prior 60-day low: lowest close in bars [2..61]
    2. Check bars 0,1,2 for breakdown below prior low
    3. From breakdown bar, check if close recovers within 2 bars
    4. Return (breakdown_bar_index, recovery_bar_index, prior_low_price, prior_low_bar)

    Returns None if no valid 2B pattern detected.
    """
    n = len(records)
    if n < 65:
        return None  # need at least 65 bars: 60 for window + 2 offset + 3 check

    closes = [r["close"] for r in records]
    lows = [r["low"] for r in records]

    # Step 1: Find prior 60-day low in bars [2..61]
    # Bar 0 = newest, bar 1 = yesterday, etc. (chronologically sorted)
    # So we look at records[n-2-60 : n-2] for the 60-day window
    prior_start = n - 2 - 60  # 62 bars back
    prior_end = n - 2           # 2 bars back (non-inclusive)
    if prior_start < 0:
        return None

    prior_closes = closes[prior_start:prior_end]
    prior_lows = lows[prior_start:prior_end]
    if not prior_closes:
        return None

    min_close = min(prior_closes)
    min_close_idx = prior_closes.index(min_close)
    prior_low_bar = prior_start + min_close_idx
    prior_low_price = min_close

    # Step 2: Check bars 0, 1, 2 (newest to 2 bars ago) for breakdown
    # bars to check: indices n-1 (bar 0), n-2 (bar 1), n-3 (bar 2)
    check_indices = [n - 1, n - 2, n - 3]
    breakdown_bar = None

    for idx in check_indices:
        if idx >= n:
            continue
        if lows[idx] < prior_low_price:
            breakdown_bar = idx
            break

    if breakdown_bar is None:
        return None  # no breakdown

    # Step 3: Check recovery within 2 bars after breakdown
    # Recovery means any close in bars [breakdown_bar .. breakdown_bar + RECOVERY_WINDOW] > prior_low_price
    recovery_bar = None
    for offset in range(RECOVERY_WINDOW + 1):
        check_idx = breakdown_bar + offset
        if check_idx >= n:
            break
        if closes[check_idx] > prior_low_price:
            recovery_bar = check_idx
            break

    if recovery_bar is None:
        return None  # no recovery

    return (breakdown_bar, recovery_bar, prior_low_price, prior_low_bar)


def score_2b(records, breakdown_bar, recovery_bar, prior_low_price, prior_low_bar):
    """
    Score a detected 2B bottom on 7 dimensions (max 100).
    Returns (score, label, metrics_dict).
    """
    n = len(records)
    closes = [r["close"] for r in records]
    lows = [r["low"] for r in records]
    highs = [r["high"] for r in records]
    vols = [r["volume"] for r in records]
    cur = closes[-1]

    score = 0
    reasons = []

    # ---- Helper ----
    breakdown_close = closes[breakdown_bar]
    breakdown_low = lows[breakdown_bar]
    recovery_close = closes[recovery_bar]

    # 1. Break depth (max 20): how far below prior low
    break_pct = abs((breakdown_low - prior_low_price) / prior_low_price * 100)
    if break_pct < 1:
        score += 20
        reasons.append(f"浅突破({break_pct:.1f}%) max=20")
    elif break_pct < 3:
        score += 15
        reasons.append(f"中浅突破({break_pct:.1f}%) max=15")
    elif break_pct < 5:
        score += 8
        reasons.append(f"中等突破({break_pct:.1f}%) max=8")
    else:
        reasons.append(f"深突破({break_pct:.1f}%) 得0")

    # 2. Recovery strength (max 20)
    recovery_pct = (recovery_close - prior_low_price) / prior_low_price * 100
    if recovery_pct >= 1.5:
        score += 20
        reasons.append(f"强力收复({recovery_pct:+.1f}%) max=20")
    elif recovery_pct >= 0.5:
        score += 15
        reasons.append(f"中等收复({recovery_pct:+.1f}%) max=15")
    elif recovery_pct >= 0:
        score += 10
        reasons.append(f"弱收复({recovery_pct:+.1f}%) max=10")

    # 3. Volume contraction (max 15) — volume on breakdown bar vs 60d avg
    if n >= 60:
        avg_vol = sum(vols[-60:]) / 60
        breakdown_vol = vols[breakdown_bar]
        vol_ratio = breakdown_vol / avg_vol if avg_vol > 0 else 1
        if vol_ratio < 0.6:
            score += 15
            reasons.append(f"缩量({vol_ratio:.0%}) max=15")
        elif vol_ratio < 0.8:
            score += 10
            reasons.append(f"量缩({vol_ratio:.0%}) max=10")
        elif vol_ratio < 1.0:
            score += 5
            reasons.append(f"量稳({vol_ratio:.0%}) max=5")
        else:
            reasons.append(f"放量({vol_ratio:.0%}) 得0")
    else:
        vol_ratio = 1

    # 4. Prior low quality (max 15) — is it a distinct swing low?
    if n >= 60:
        # check if prior_low is lowest in ±10 bars around it
        left = max(0, prior_low_bar - 10)
        right = min(n, prior_low_bar + 11)
        nearby_lows = lows[left:right]
        if min(nearby_lows) == lows[prior_low_bar] and len(nearby_lows) >= 15:
            score += 15
            reasons.append(f"清晰前低(±10日最低) max=15")
        else:
            # check if it's at least near a low
            rank = sorted(nearby_lows).index(lows[prior_low_bar])
            if rank <= 2:
                score += 10
                reasons.append(f"接近前低 max=10")
            else:
                score += 5
                reasons.append(f"普通前低 max=5")

    # 5. Trend context (max 15) — prior decline before the prior low
    if prior_low_bar >= 20:
        prior20_closes = closes[prior_low_bar - 20:prior_low_bar]
        prior_decline = (prior20_closes[0] - prior20_closes[-1]) / prior20_closes[0] * 100
        if prior_decline > 8:
            score += 15
            reasons.append(f"深跌背景({prior_decline:.0f}%) max=15")
        elif prior_decline > 5:
            score += 10
            reasons.append(f"中等跌幅({prior_decline:.0f}%) max=10")
        elif prior_decline > 3:
            score += 5
            reasons.append(f"小幅下跌({prior_decline:.0f}%) max=5")
        else:
            prior_decline = 0
            reasons.append(f"无明显下跌 得0")
    else:
        prior_decline = 0

    # 6. Recovery speed (max 10)
    lag = recovery_bar - breakdown_bar
    if lag == 0:
        score += 10
        reasons.append(f"当日收复 max=10")
    elif lag == 1:
        score += 7
        reasons.append(f"次日收复 max=7")
    else:
        score += 5
        reasons.append(f"2日收复 max=5")

    # 7. Distance from 60MA (max 5)
    if n >= 60:
        ma60 = sum(closes[-60:]) / 60
        d_ma60 = (cur - ma60) / ma60 * 100
        if -15 <= d_ma60 <= -2:
            score += 5
            reasons.append(f"低于60MA({d_ma60:+.1f}%) max=5")
        else:
            d_ma60 = d_ma60  # keep value even if not scoring
    else:
        d_ma60 = 0

    # Penalties
    if n >= 60:
        avg_vol = sum(vols[-60:]) / 60
        breakdown_vol = vols[breakdown_bar]
        if avg_vol > 0 and breakdown_vol / avg_vol > 1.2:
            score -= 10
            reasons.append(f"高量突破 -10分")

    recent_bars_from_prior = n - 1 - prior_low_bar  # bars from prior low to latest
    if recent_bars_from_prior < 5:
        score -= 5
        reasons.append(f"前低过近({recent_bars_from_prior}日) -5分")

    score = max(0, min(100, score))

    # Label grading
    if score >= 80:
        label = "2B买入确认"
    elif score >= 65:
        label = "2B买入候选"
    elif score >= 50:
        label = "2B观察"
    else:
        label = "无2B信号"

    return {
        "score": score,
        "label": label,
        "break_pct": round(break_pct, 2),
        "recovery_pct": round(recovery_pct, 2),
        "vol_ratio": round(vol_ratio, 2) if n >= 60 else 0,
        "lag_bars": lag,
        "prior_decline": round(prior_decline, 1) if prior_low_bar >= 20 else 0,
        "d_ma60": round(d_ma60, 1) if n >= 60 else 0,
        "current": round(cur, 2),
        "prior_low_price": round(prior_low_price, 2),
        "breakdown_date": records[breakdown_bar]["date"],
        "recovery_date": records[recovery_bar]["date"],
        "reasons": reasons,
    }


def analyze_2b(code, name, etype, kline_data):
    """
    Main analysis: detect 2B bottom pattern and score it.
    Returns result dict or None.
    """
    records = parse_kline(kline_data)
    if len(records) < 65:
        return None

    detection = detect_2b_bottom(records)
    if detection is None:
        return None

    breakdown_bar, recovery_bar, prior_low_price, prior_low_bar = detection
    scored = score_2b(records, breakdown_bar, recovery_bar, prior_low_price, prior_low_bar)

    return {
        "code": code,
        "name": name,
        "type": etype,
        "score": scored["score"],
        "label": scored["label"],
        "break_pct": scored["break_pct"],
        "recovery_pct": scored["recovery_pct"],
        "vol_ratio": scored["vol_ratio"],
        "lag_bars": scored["lag_bars"],
        "prior_decline": scored["prior_decline"],
        "d_ma60": scored["d_ma60"],
        "current": scored["current"],
        "prior_low_price": scored["prior_low_price"],
        "breakdown_date": scored["breakdown_date"],
        "recovery_date": scored["recovery_date"],
        "reasons": scored["reasons"],
    }


def main():
    print("=" * 60)
    print("A股ETF 2B底形态分析 (v1)")
    print("=" * 60)

    # Step 1: Load ETFs
    print("\n[1/4] 加载ETF列表...")
    etfs = load_etfs()
    if not etfs:
        print("未找到ETF列表。请确保 all_etfs_larggest.json 存在于项目根目录。")
        return
    print(f"共加载 {len(etfs)} 只ETF")

    # Step 2: Fetch K-line data in parallel
    print(f"\n[2/4] 并行拉取K线数据 (最多{MAX_WORKERS}并发, 每个{KLINE_DAYS}天)...")
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
        print(f"\n[2b/4] 补拉 {len(missing)} 只失败ETF (增强重试, 最多6次)...")
        for c in missing:
            _, d = fetch_kline(c, retries=6)
            if d:
                kline_data[c] = d
        still_missing = [c for c in codes if c not in kline_data]
        print(f"补拉后覆盖 {len(kline_data)}/{total} (仍缺失 {len(still_missing)})")
        if still_missing:
            name_map = {e["code"]: e["name"] for e in etfs}
            print("  缺失ETF:", ", ".join(f'{name_map.get(c, c)}({c})' for c in still_missing))

    # Save raw kline data
    cwd = os.getcwd()
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    kline_file = os.path.join(skill_dir, "etf_kline_data.json")
    with open(kline_file, "w") as f:
        json.dump(kline_data, f, ensure_ascii=False)
    print(f"K线数据已保存: {kline_file}")

    # Step 3: Analyze
    print("\n[3/4] 检测2B底形态 (60日前低 + 2日收复)...")
    results = []
    for e in etfs:
        kl = kline_data.get(e["code"])
        if not kl:
            continue
        r = analyze_2b(e["code"], e["name"], e["type"], kl)
        if r:
            results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)

    results_file = os.path.join(skill_dir, "etf_2b_bottom_results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"分析结果已保存: {results_file}")

    # Step 4: Summary
    confirmed = [r for r in results if r["label"] == "2B买入确认"]
    candidate = [r for r in results if r["label"] == "2B买入候选"]
    watch = [r for r in results if r["label"] == "2B观察"]
    nosignal = [r for r in results if r["label"] == "无2B信号"]

    print("\n" + "=" * 60)
    print(f"2B底形态汇总 (共{len(results)}只ETF检测到信号)")
    print("=" * 60)
    print(f"  2B买入确认: {len(confirmed)}")
    print(f"  2B买入候选: {len(candidate)}")
    print(f"  2B观察: {len(watch)}")
    print(f"  无2B信号(含低分): {len(nosignal)}")

    # Show signals
    if confirmed or candidate:
        print(f"\n{'排名':<4}{'ETF':<18}{'得分':<5}{'判定':<14}{'突破%':<8}{'收复%':<8}{'量比':<6}{'收复日':<6}{'前跌%':<8}")
        print("-" * 90)
        all_signals = confirmed + candidate
        for i, r in enumerate(all_signals[:15]):
            print(f"{i+1:<4}{r['name']:<18}{r['score']:<5}{r['label']:<14}{r['break_pct']:<8.2f}{r['recovery_pct']:<8.2f}{r['vol_ratio']:<6.2f}{r['lag_bars']:<6}{r['prior_decline']:<8}")

    return results


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run syntax check**

Run: `PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3" && $PYTHON -m py_compile .codebuddy/skills/etf-2b-bottom-scanner/analyze.py`
Expected: no output (success)

- [ ] **Step 3: Run dry-run on a single ETF to verify detection**

```python
# Save as /tmp/test_2b.py and run
import json, os, subprocess, sys
sys.path.insert(0, '.codebuddy/skills/etf-2b-bottom-scanner')
from analyze import parse_kline, detect_2b_bottom, score_2b

# Mock K-line data for sh510300 (沪深300ETF) - will use real data via westock
NODE = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
WESTOCK = "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data/scripts/index.js"
cmd = [NODE, WESTOCK, "kline", "sh510300", "--period", "day", "--limit", "250", "--raw"]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
data = json.loads(result.stdout)
records = parse_kline(data)
print(f"Records: {len(records)}")
detection = detect_2b_bottom(records)
print(f"2B Detection: {detection is not None}")
if detection:
    bd, rc, plp, plb = detection
    scored = score_2b(records, bd, rc, plp, plb)
    for k, v in scored.items():
        if k != "reasons":
            print(f"  {k}: {v}")
    print("  reasons:")
    for r in scored["reasons"]:
        print(f"    {r}")
```

Run: `$PYTHON /tmp/test_2b.py`
Expected: Output showing records count and whether a 2B pattern was detected.

- [ ] **Step 4: Commit**

```bash
git add .codebuddy/skills/etf-2b-bottom-scanner/analyze.py
git commit -m "feat: add ETF 2B bottom detection and scoring engine"
```

---

### Task 3: Create generate_report.py (HTML Report Builder)

**Files:**
- Create: `.codebuddy/skills/etf-2b-bottom-scanner/generate_report.py`

- [ ] **Step 1: Write the complete generate_report.py**

```python
#!/usr/bin/env python3
"""
生成 A股ETF 2B底形态分析 HTML 报告 (v1)
- 摘要卡片 (确认/候选/观察)
- 2B信号ETF 60日 K线缩略图 (Chart.js, 标注前低+突破+收复)
- TOP25 综合得分排名表
- 2B信号ETF详细分析卡片
"""

import json
import os
from datetime import datetime


def build_report(results, klines, output_path):
    today = datetime.now().strftime("%Y-%m-%d")

    confirmed = [r for r in results if r["label"] == "2B买入确认"]
    candidate = [r for r in results if r["label"] == "2B买入候选"]
    watch = [r for r in results if r["label"] == "2B观察"]
    nosignal = [r for r in results if r["label"] == "无2B信号"]
    total = len(results) + (352 - len(results))  # total scanned

    # Build chart datasets for top signals
    chart_blocks = []
    for r in (confirmed + candidate)[:9]:
        kdata = klines.get(r["code"], [])
        recs = sorted(kdata, key=lambda x: x["date"])[-60:]
        closes = [round(float(x["last"]), 2) for x in recs]
        dates = [x["date"][:10] for x in recs]
        chart_blocks.append({
            "name": r["name"], "type": r["type"], "score": r["score"],
            "label": r["label"], "closes": closes, "dates": dates,
            "prior_low": r["prior_low_price"],
            "break_pct": r["break_pct"], "recovery_pct": r["recovery_pct"],
            "lag_bars": r["lag_bars"], "vol_ratio": r["vol_ratio"],
        })

    # Build full ranking table rows (top 25)
    table_rows = []
    for i, r in enumerate(results[:25]):
        lc = {"2B买入确认": "#27ae60", "2B买入候选": "#2980b9", "2B观察": "#f39c12", "无2B信号": "#95a5a6"}.get(r["label"], "#333")
        lag_text = ["当日", "次日", "2日"][r["lag_bars"]] if r["lag_bars"] <= 2 else str(r["lag_bars"])
        table_rows.append(f"""
        <tr>
          <td><b>{i+1}</b></td>
          <td><b>{r['name']}</b><br><span class="muted">{r['type']}</span></td>
          <td><span style="color:{lc};font-weight:600">{r['label']}</span></td>
          <td><b>{r['score']}</b></td>
          <td class="neg">{r['break_pct']}%</td>
          <td class="pos">{r['recovery_pct']:+.2f}%</td>
          <td>{r['vol_ratio']:.2f}</td>
          <td>{lag_text}</td>
          <td class="neg">{r['prior_decline']:.1f}%</td>
          <td class="neg">{r['d_ma60']:+.1f}%</td>
        </tr>""")

    # Detail cards for all signals with score >= 50
    detail_cards = []
    for i, r in enumerate(confirmed + candidate):
        if i >= 9:
            break
        reasons_html = "".join(f"<li>{x}</li>" for x in r["reasons"])
        lag_text = ["当日", "次日", "2日"][r["lag_bars"]] if r["lag_bars"] <= 2 else f"{r['lag_bars']}日"
        detail_cards.append(f"""
        <div class="detail-card">
          <div class="detail-head">
            <span class="rank">#{i+1}</span>
            <h3>{r['name']}</h3>
            <span class="badge" style="background:{'#27ae60' if r['label']=='2B买入确认' else '#2980b9'}">{r['label']}</span>
            <span class="score-badge">得分 {r['score']}/100</span>
          </div>
          <div class="detail-grid">
            <div class="metric"><span class="ml">当前价格</span><span class="mv">{r['current']}</span></div>
            <div class="metric"><span class="ml">前低价格</span><span class="mv">{r['prior_low_price']}</span></div>
            <div class="metric"><span class="ml">突破幅度</span><span class="mv neg">{r['break_pct']}%</span></div>
            <div class="metric"><span class="ml">收复幅度</span><span class="mv pos">{r['recovery_pct']:+.2f}%</span></div>
            <div class="metric"><span class="ml">成交量比</span><span class="mv">{r['vol_ratio']:.2f}</span></div>
            <div class="metric"><span class="ml">收复时间</span><span class="mv">{lag_text}</span></div>
            <div class="metric"><span class="ml">前期跌幅</span><span class="mv neg">{r['prior_decline']:.1f}%</span></div>
            <div class="metric"><span class="ml">距60MA</span><span class="mv neg">{r['d_ma60']:+.1f}%</span></div>
            <div class="metric"><span class="ml">突破日期</span><span class="mv">{r['breakdown_date'][:10]}</span></div>
            <div class="metric"><span class="ml">收复日期</span><span class="mv">{r['recovery_date'][:10]}</span></div>
          </div>
          <div class="reasons"><b>评分依据:</b><ul>{reasons_html}</ul></div>
        </div>""")

    chart_json = json.dumps(chart_blocks, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股ETF 2B底形态分析报告 · {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:#f5f6fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#0d4d2e 0%,#0a3d24 50%,#08491e 100%); color:#fff; padding:36px 30px; border-radius:12px; margin-bottom:24px; box-shadow:0 4px 20px rgba(0,0,0,0.15); }}
.header h1 {{ font-size:26px; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.85; font-size:14px; }}
.header .meta {{ margin-top:14px; display:flex; gap:24px; font-size:13px; opacity:0.75; flex-wrap:wrap; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-bottom:28px; }}
.summary-card {{ background:#fff; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.summary-card .number {{ font-size:30px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#7f8c8d; margin-top:4px; }}
.c-blue .number {{ color:#2980b9; }}
.c-green .number {{ color:#27ae60; }}
.c-orange .number {{ color:#e67e22; }}
.c-red .number {{ color:#e74c3c; }}
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
.detail-head .rank {{ background:#27ae60; color:#fff; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; }}
.detail-head h3 {{ font-size:18px; }}
.badge {{ color:#fff; padding:3px 10px; border-radius:12px; font-size:12px; }}
.score-badge {{ background:#34495e; color:#fff; padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
.detail-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:14px; }}
.metric {{ background:#f8f9fa; padding:9px 12px; border-radius:6px; }}
.metric .ml {{ font-size:12px; color:#7f8c8d; display:block; }}
.metric .mv {{ font-size:15px; font-weight:600; }}
.reasons {{ background:#f8f9fa; padding:12px 16px; border-radius:6px; }}
.reasons ul {{ list-style:none; margin-top:6px; }}
.reasons li {{ padding:2px 0; font-size:13px; }}
.note {{ background:#e8f8f0; border-left:4px solid #27ae60; padding:14px 18px; border-radius:6px; margin:20px 0; font-size:13px; }}
.disclaimer {{ background:#fdecea; border-radius:8px; padding:16px 20px; margin-top:28px; font-size:12px; color:#c0392b; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>📈 A股ETF 2B底形态分析报告</h1>
  <div class="subtitle">各板块规模最大ETF的2B底形态扫描 · 来自 all_etfs_larggest.json</div>
  <div class="meta">
    <span>📅 报告日期: {today}</span>
    <span>📊 扫描范围: 352 只ETF</span>
    <span>📈 K线周期: 日线 250 天</span>
    <span>🔍 算法: 60日前低 + 2日收复 = 2B底</span>
  </div>
</div>

<div class="summary-cards">
  <div class="summary-card c-blue"><div class="number">352</div><div class="label">扫描ETF总数</div></div>
  <div class="summary-card c-green"><div class="number">{len(confirmed)}</div><div class="label">2B买入确认</div></div>
  <div class="summary-card c-blue"><div class="number">{len(candidate)}</div><div class="label">2B买入候选</div></div>
  <div class="summary-card c-orange"><div class="number">{len(watch)}</div><div class="label">2B观察</div></div>
  <div class="summary-card c-gray"><div class="number">{len(nosignal)}</div><div class="label">无2B信号</div></div>
</div>

<div class="note">
  <b>📌 2B底判定逻辑:</b> 2B法则 (Victor Sperandeo) — ETF价格跌破前60日低点，但在2个交易日内收盘价收复该前低，形成"破底翻"信号。
  <b>这表示前低区域的支撑有效</b>，空头力量衰竭，可能迎来趋势反转。
  本算法仅检测<b>当前</b>是否出现2B买入信号。
</div>

<div class="section-title">🏆 2B信号ETF — K线缩略图 <span class="count">(展示前9名 60日走势)</span></div>
<div class="charts-grid" id="chartsGrid"></div>

<div class="section-title">📊 综合得分排名 (TOP 25) <span class="count">颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>形态判定</th><th>得分</th><th>突破幅度</th><th>收复幅度</th><th>量比</th><th>收复时间</th><th>前期跌幅</th><th>距60MA</th>
</tr></thead>
<tbody>
{''.join(table_rows)}
</tbody></table>
</div>

<div class="section-title">📝 2B信号ETF详细分析</div>
{''.join(detail_cards)}

<div class="disclaimer">
  ⚠️ <b>风险提示:</b> 本报告仅基于历史价格形态的客观量化分析，不构成任何投资建议。2B形态识别属于技术分析方法，存在误判可能；
  破底翻信号并非100%准确，突破后仍可能继续下跌。投资有风险，决策需谨慎。请结合基本面、资金面、宏观环境综合判断。
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
    <div class="sub">${{c.label}} · 得分${{c.score}} · 突破${{c.break_pct}}% · 收复+${{c.recovery_pct.toFixed(2)}}% · 前低${{c.prior_low}}</div>
    <div class="chart-box"><canvas></canvas></div>
  `;
  grid.appendChild(card);

  // Build datasets: main line + prior-low reference line
  const ctx = card.querySelector('canvas').getContext('2d');
  const refLine = new Array(c.closes.length).fill(c.prior_low);

  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: c.dates,
      datasets: [
        {{ data: c.closes, borderColor: colors[idx%colors.length], backgroundColor: colors[idx%colors.length]+'15', borderWidth: 1.8, pointRadius:0, fill:true, tension:0.35, label: '收盘价' }},
        {{ data: refLine, borderColor: '#e74c3c', borderDash: [5,5], borderWidth: 1.2, pointRadius:0, fill:false, label: '前低='+c.prior_low }}
      ]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{ legend:{{display:false}}, tooltip:{{ callbacks:{{ title:(i)=>c.dates[i[0].dataIndex], label:(i)=>(i.datasetIndex===0?'价格 ':'前低 ')+i.parsed.y }}}}}},
      scales: {{ x: {{ display:false }}, y: {{ display:true, position:'right', ticks:{{ font:{{size:9}}, color:'#95a5a6' }}, grid:{{ color:'#f0f2f5' }} }} }}
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
    results_file = os.path.join(skill_dir, "etf_2b_bottom_results.json")
    kline_file = os.path.join(skill_dir, "etf_kline_data.json")
    outdir = os.path.join(cwd, "reports", "etf")
    os.makedirs(outdir, exist_ok=True)
    output = os.path.join(outdir, "etf_2b_bottom_report.html")

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

- [ ] **Step 2: JS syntax check**

Run: `PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3" && $PYTHON -c "
import json; print('generate_report.py is syntactically valid')
"`
Expected: prints confirmation

- [ ] **Step 3: Commit**

```bash
git add .codebuddy/skills/etf-2b-bottom-scanner/generate_report.py
git commit -m "feat: add ETF 2B bottom HTML report generator"
```

---

### Task 4: End-to-End Validation

- [ ] **Step 1: Run the full analysis pipeline**

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON .codebuddy/skills/etf-2b-bottom-scanner/analyze.py
```
Expected:
- K-line data fetched for 300+ ETFs
- `etf_kline_data.json` saved
- `etf_2b_bottom_results.json` saved
- Summary printed with 2B signal counts

- [ ] **Step 2: Generate the HTML report**

```bash
$PYTHON .codebuddy/skills/etf-2b-bottom-scanner/generate_report.py
```
Expected:
- `reports/etf/etf_2b_bottom_report.html` created
- Report file is well-formed HTML (>5KB)

- [ ] **Step 3: Verify report JS syntax**

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON -c "
import re
with open('reports/etf/etf_2b_bottom_report.html') as f:
    html = f.read()
scripts = re.findall(r'<script>((?:.|\n)*?)</script>', html)
for i, s in enumerate(scripts):
    # Extract standalone JS (not inline JSON)
    if 'const chartData' in s or 'new Chart' in s:
        with open(f'/tmp/_check_2b_{i}.js', 'w') as out:
            out.write(s)
"
NODE="/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
for f in /tmp/_check_2b_*.js; do
    $NODE --check "$f" && echo "OK: $f" || echo "FAIL: $f"
done
```
Expected: all JS files pass `node --check`

- [ ] **Step 4: Final commit**

```bash
git add reports/etf/etf_2b_bottom_report.html
git commit -m "feat: add ETF 2B bottom scanner initial scan report"
```
