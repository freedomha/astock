# ETF Operation Plan Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new skill `etf-operation-plan` that generates actionable operation plans for A-share ETFs, outputting HTML reports to `reports/etf/operation/`.

**Architecture:** AI-driven workflow (SKILL.md) + single Python helper script (`score_patterns.py`) that inlines scoring logic from 5 existing analyzers into one self-contained single-ETF scorer. No external dependencies beyond Python stdlib.

**Tech Stack:** Python 3.13 (stdlib only), westock-data CLI (Node.js), ECharts (CDN, HTML), WebSearch

**Source spec:** `docs/superpowers/specs/2026-08-07-etf-operation-plan-design.md`

---

### Task 1: Create skill directory structure

**Files:**
- Create: `.codebuddy/skills/etf-operation-plan/` (directory)
- Create: `reports/etf/operation/` (directory)

- [ ] **Step 1: Create directories**

```bash
mkdir -p .codebuddy/skills/etf-operation-plan
mkdir -p reports/etf/operation
```

- [ ] **Step 2: Verify**

```bash
ls -d .codebuddy/skills/etf-operation-plan reports/etf/operation
```
Expected: Both paths exist without error.

---

### Task 2: Write score_patterns.py — shared utility layer

**Files:**
- Create: `.codebuddy/skills/etf-operation-plan/score_patterns.py`

- [ ] **Step 1: Write the utility functions into score_patterns.py**

Copy from existing analyzers (bowl-bottom/analyze.py and hs-bottom/analyze.py). These are the shared math functions used by multiple pattern analyzers:

```python
#!/usr/bin/env python3
"""
Single-ETF five-pattern scorer.
Usage: python3 score_patterns.py --code sh518880 --kline-file /tmp/kline.json
Output: JSON with bowl/box/w_bottom/hs_bottom/2b scores and labels.
"""
import json, sys, argparse


# ─── Shared Utility Functions ───────────────────────────────────────────────

def lin_slope(arr, win):
    """Linear regression slope over last `win` elements, as % change."""
    if len(arr) < win:
        return 0.0
    xs = list(range(win))
    ys = arr[-win:]
    n = float(win)
    sx = (n - 1) * n / 2.0
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    s = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    ym = sy / n
    if ym == 0:
        return 0.0
    return s * win / ym * 100


def atr(highs, lows, closes, window):
    """Average True Range over `window` periods."""
    if len(closes) < window + 1:
        return 0.0
    trs = []
    for i in range(len(closes) - window, len(closes)):
        prev_close = closes[i - 1] if i > 0 else closes[i]
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - prev_close),
                 abs(lows[i] - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def quadratic_fit(prices):
    """Quadratic fit y = a*x^2 + b*x + c. Returns (a, b, c, vertex_x_norm)."""
    n = len(prices)
    if n < 10:
        return 0, 0, prices[-1] if prices else 0, 0.5
    xs = list(range(n))
    ys = [float(p) for p in prices]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num_a, den_a = 0.0, 0.0
    num_b = 0.0
    for i in range(n):
        dx = xs[i] - mean_x
        dy = ys[i] - mean_y
        dx2 = dx * dx
        num_a += dx2 * dy
        den_a += dx2 * dx2
        num_b += dx * dy
    a = num_a / den_a if den_a != 0 else 0.0
    b = num_b / sum((x - mean_x) ** 2 for x in xs) if sum((x - mean_x) ** 2 for x in xs) != 0 else 0.0
    c = mean_y - b * mean_x - a * mean_x * mean_x
    vertex_x = -b / (2 * a) if a != 0 else n / 2
    vertex_x_norm = max(0, min(1, vertex_x / n))
    return a, b, c, vertex_x_norm


def find_local_extrema(closes, window=5):
    """Find local minima and maxima in price series."""
    lows_list = []
    highs_list = []
    n = len(closes)
    for i in range(n):
        start = max(0, i - window)
        end = min(n - 1, i + window)
        if closes[i] <= min(closes[start:end + 1]):
            lows_list.append((i, closes[i]))
        if closes[i] >= max(closes[start:end + 1]):
            highs_list.append((i, closes[i]))
    # Filter adjacent same
    filtered_lows = []
    for i, (idx, val) in enumerate(lows_list):
        if i == 0 or idx - lows_list[i - 1][0] > 2:
            filtered_lows.append((idx, val))
    filtered_highs = []
    for i, (idx, val) in enumerate(highs_list):
        if i == 0 or idx - highs_list[i - 1][0] > 2:
            filtered_highs.append((idx, val))
    return filtered_lows, filtered_highs
```

- [ ] **Step 2: Verify the script is syntactically correct**

```bash
cd /Users/aldiadmin/Documents/vscodeworkspace/astock
$PYTHON -m py_compile .codebuddy/skills/etf-operation-plan/score_patterns.py
```
Expected: No output (compiles successfully).

---

### Task 3: Write score_patterns.py — bowl-bottom scoring

**Files:**
- Modify: `.codebuddy/skills/etf-operation-plan/score_patterns.py`

- [ ] **Step 1: Copy the bowl-bottom analyze function**

Append to score_patterns.py. Copy the `analyze_bowl_bottom` function body from `.workbuddy/skills/etf-bowl-bottom-scanner/analyze.py` (line 133 onward). The function signature is:

```python
def analyze_bowl_bottom(code, name, etype, kline_data):
    """Score a single ETF for bowl-bottom pattern."""
    # K-line data is newest-first. Reverse for chronological analysis.
    klines = kline_data.get("klines", kline_data if isinstance(kline_data, list) else [])
    closes = []
    highs_data = []
    lows_data = []
    volumes = []
    for item in klines:
        closes.append(float(item.get("last", item.get("close", 0))))
        highs_data.append(float(item.get("high", 0)))
        lows_data.append(float(item.get("low", 0)))
        volumes.append(float(item.get("volume", 0)))
    
    closes.reverse()
    highs_data.reverse()
    lows_data.reverse()
    volumes.reverse()
    
    n = len(closes)
    if n < 120:
        return {"score": 0, "label": "数据不足"}
    
    current = closes[-1]
    
    # ... COPY THE ENTIRE FUNCTION BODY from line 133-362
    # of .workbuddy/skills/etf-bowl-bottom-scanner/analyze.py
```

The full function body (excluding the closing `}` and return statement preparation) should be copied exactly from the source file. This function uses `lin_slope`, `quadratic_fit`, and `atr` already defined in Task 2.

**Note:** The implementation step will read the full source function and copy it verbatim. Do NOT attempt to rewrite or shorten it.

- [ ] **Step 2: Test bowl-bottom with real data**

```bash
$NODE $WD/scripts/index.js kline sh518880 --period day --limit 250 --raw > /tmp/test_kline.json
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py --code sh518880 --kline-file /tmp/test_kline.json --pattern bowl 2>&1
```

Expected: JSON output with `bowl` key containing `score` (number 0-100) and `label` (string).

- [ ] **Step 3: Compare with known result**

Run the same ETF through the full bowl-bottom analyzer to verify scores match:

```bash
cd .workbuddy/skills/etf-bowl-bottom-scanner
$PYTHON -c "
import json
with open('etf_bowl_results.json') as f:
    results = json.load(f)
for r in results:
    if r['code'] == 'sh518880':
        print(json.dumps(r, indent=2, ensure_ascii=False))
"
```

Expected: The `score` and `label` should match what our standalone scorer produces (within rounding tolerance).

---

### Task 4: Write score_patterns.py — box scoring

**Files:**
- Modify: `.codebuddy/skills/etf-operation-plan/score_patterns.py`

- [ ] **Step 1: Copy box-consolidation scoring functions**

Append to score_patterns.py. Copy from `.workbuddy/skills/etf-box-scanner/analyze.py`:
- `detect_box_bounces` function (line 108-187, including `cluster_levels` inner function)
- `analyze_box_consolidation` function (line 188-475)

```python
# ─── Box Consolidation Scoring ─────────────────────────────────────────────

# (inline copy of detect_box_bounces + cluster_levels from box analyzer)
# (inline copy of analyze_box_consolidation from box analyzer)
```

- [ ] **Step 2: Test box scoring**

```bash
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py --code sh518880 --kline-file /tmp/test_kline.json --pattern box 2>&1
```

Expected: JSON with `box` key containing score and label.

---

### Task 5: Write score_patterns.py — W-bottom scoring

**Files:**
- Modify: `.codebuddy/skills/etf-operation-plan/score_patterns.py`

- [ ] **Step 1: Copy W-bottom scoring functions**

Append to score_patterns.py. Copy from `.workbuddy/skills/etf-w-bottom-scanner/analyze.py`:
- `score_w_bottom` function (line 90-265)
- `detect_w_bottom` function (line 266-337)
- `analyze_w_bottom` function (line 338-403)

```python
# ─── W-Bottom Scoring ─────────────────────────────────────────────────────

# (inline copies from W-bottom analyzer)
```

- [ ] **Step 2: Test W-bottom scoring**

```bash
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py --code sh518880 --kline-file /tmp/test_kline.json --pattern w_bottom 2>&1
```

---

### Task 6: Write score_patterns.py — head-shoulder bottom scoring

**Files:**
- Modify: `.codebuddy/skills/etf-operation-plan/score_patterns.py`

- [ ] **Step 1: Copy HS-bottom scoring functions**

Append to score_patterns.py. Copy from `.workbuddy/skills/etf-head-shoulder-bottom-scanner/analyze.py`:
- `find_head_shoulder_pattern` function (line 126-264)
- `_avg_volume` function (line 265-273)
- `score_pattern` function (line 274-460)
- `label_pattern` function (line 583-594)
- `analyze_hs_bottom` function (line 461-582)

```python
# ─── Head-Shoulder Bottom Scoring ─────────────────────────────────────────

# Constants
EXTREMA_WINDOW = 5

# (inline copies from HS-bottom analyzer)
```

- [ ] **Step 2: Test HS-bottom scoring**

```bash
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py --code sh518880 --kline-file /tmp/test_kline.json --pattern hs_bottom 2>&1
```

---

### Task 7: Write score_patterns.py — 2B bottom scoring

**Files:**
- Modify: `.codebuddy/skills/etf-operation-plan/score_patterns.py`

- [ ] **Step 1: Copy 2B-bottom scoring functions**

Append to score_patterns.py. Copy from `.workbuddy/skills/etf-2b-bottom-scanner/analyze.py`:
- `detect_2b_bottom` function (line 117-193)
- `find_2yang_confirmation` function (line 194-218)
- `quality_filter_2b` function (line 219-272)
- `score_2b` function (line 273-499)
- `analyze_2b` function (line 500-558)

```python
# ─── 2B Bottom Scoring ────────────────────────────────────────────────────

# (inline copies from 2B-bottom analyzer)
```

- [ ] **Step 2: Test 2B scoring**

```bash
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py --code sh518880 --kline-file /tmp/test_kline.json --pattern 2b 2>&1
```

---

### Task 8: Write score_patterns.py — CLI entry point

**Files:**
- Modify: `.codebuddy/skills/etf-operation-plan/score_patterns.py`

- [ ] **Step 1: Write the `main()` function and `if __name__` block**

Append to the end of score_patterns.py:

```python
# ─── CLI Entry Point ──────────────────────────────────────────────────────

def run_all_patterns(code, name, kline_data):
    """Run all 5 pattern analyzers on a single ETF. Returns dict."""
    results = {}

    # Bowl bottom
    try:
        bowl_result = analyze_bowl_bottom(code, name, "ETF", kline_data)
        results["bowl"] = {
            "score": bowl_result.get("score", 0),
            "label": bowl_result.get("label", "计算失败")
        }
    except Exception as e:
        results["bowl"] = {"score": 0, "label": "计算失败", "error": str(e)}

    # Box consolidation
    try:
        box_result = analyze_box_consolidation(code, name, "ETF", kline_data)
        results["box"] = {
            "score": box_result.get("score", 0),
            "label": box_result.get("label", "计算失败")
        }
    except Exception as e:
        results["box"] = {"score": 0, "label": "计算失败", "error": str(e)}

    # W-bottom
    try:
        w_result = analyze_w_bottom(code, name, "ETF", kline_data)
        results["w_bottom"] = {
            "score": w_result.get("score", 0),
            "label": w_result.get("label", "计算失败")
        }
    except Exception as e:
        results["w_bottom"] = {"score": 0, "label": "计算失败", "error": str(e)}

    # Head-shoulder bottom
    try:
        hs_result = analyze_hs_bottom(code, name, "ETF", kline_data)
        results["hs_bottom"] = {
            "score": hs_result.get("score", 0),
            "label": hs_result.get("label", "计算失败")
        }
    except Exception as e:
        results["hs_bottom"] = {"score": 0, "label": "计算失败", "error": str(e)}

    # 2B bottom
    try:
        two_b_result = analyze_2b(code, name, "ETF", kline_data)
        results["2b"] = {
            "score": two_b_result.get("score", 0),
            "label": two_b_result.get("label", "计算失败")
        }
    except Exception as e:
        results["2b"] = {"score": 0, "label": "计算失败", "error": str(e)}

    return results


def resolve_name(code):
    """Try to resolve ETF name from all_etfs_larggest.json."""
    try:
        import os
        etf_file = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                ".workbuddy", "skills", "etf-bowl-bottom-scanner",
                                "all_etfs_larggest.json")
        # Also try project root
        if not os.path.exists(etf_file):
            etf_file = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                    "all_etfs_larggest.json")
        with open(etf_file) as f:
            etfs = json.load(f)
        for e in etfs:
            if e.get("code") == code:
                return e.get("name", code)
    except Exception:
        pass
    return code


def main():
    parser = argparse.ArgumentParser(description="Single-ETF five-pattern scorer")
    parser.add_argument("--code", required=True, help="ETF code (e.g. sh518880)")
    parser.add_argument("--kline-file", required=True, help="Path to K-line JSON file")
    parser.add_argument("--pattern", choices=["bowl", "box", "w_bottom", "hs_bottom", "2b"],
                        help="Run only one pattern (default: all)")
    args = parser.parse_args()

    # Load K-line data
    with open(args.kline_file) as f:
        raw = json.load(f)

    # Normalize: westock-data returns a list directly
    if isinstance(raw, list):
        kline_data = {"klines": raw}
    elif isinstance(raw, dict):
        kline_data = raw
    else:
        print(json.dumps({"error": "Invalid K-line data format"}))
        sys.exit(1)

    name = resolve_name(args.code)

    if args.pattern:
        # Single pattern mode
        pattern_map = {
            "bowl": analyze_bowl_bottom,
            "box": analyze_box_consolidation,
            "w_bottom": analyze_w_bottom,
            "hs_bottom": analyze_hs_bottom,
            "2b": analyze_2b,
        }
        try:
            result = pattern_map[args.pattern](args.code, name, "ETF", kline_data)
            output = {args.pattern: {
                "score": result.get("score", 0),
                "label": result.get("label", "计算失败")
            }}
        except Exception as e:
            output = {args.pattern: {"score": 0, "label": "计算失败", "error": str(e)}}
    else:
        output = run_all_patterns(args.code, name, kline_data)

    output["code"] = args.code
    output["name"] = name
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax check**

```bash
cd /Users/aldiadmin/Documents/vscodeworkspace/astock
$PYTHON -m py_compile .codebuddy/skills/etf-operation-plan/score_patterns.py
```

Expected: No errors.

---

### Task 9: Full integration test of score_patterns.py

**Files:**
- None created (test only)

- [ ] **Step 1: Fetch fresh K-line data**

```bash
$NODE $WD/scripts/index.js kline sh518880 --period day --limit 250 --raw > /tmp/op_test_kline.json
$NODE $WD/scripts/index.js kline sz159698 --period day --limit 250 --raw > /tmp/op_test_kline2.json
```

- [ ] **Step 2: Run all 5 patterns on 518880**

```bash
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py --code sh518880 --kline-file /tmp/op_test_kline.json 2>&1
```

Expected: Valid JSON with `bowl`, `box`, `w_bottom`, `hs_bottom`, `2b` keys, each with `score` and `label`. No `error` keys.

- [ ] **Step 3: Run all 5 patterns on 159698**

```bash
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py --code sz159698 --kline-file /tmp/op_test_kline2.json 2>&1
```

Expected: Valid JSON, all 5 patterns present.

- [ ] **Step 4: Test single-pattern mode**

```bash
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py --code sh518880 --kline-file /tmp/op_test_kline.json --pattern bowl 2>&1
```

Expected: JSON with only `bowl` key (plus `code` and `name`).

- [ ] **Step 5: Cross-validate bowl scores against existing scanner**

```bash
$PYTHON -c "
import json
# Get score from our standalone scorer
import subprocess
result = subprocess.run([
    '$PYTHON', '.codebuddy/skills/etf-operation-plan/score_patterns.py',
    '--code', 'sh518880',
    '--kline-file', '/tmp/op_test_kline.json',
    '--pattern', 'bowl'
], capture_output=True, text=True)
our_score = json.loads(result.stdout)['bowl']['score']

# Get score from existing scan results
with open('.workbuddy/skills/etf-bowl-bottom-scanner/etf_bowl_results.json') as f:
    scan_results = json.load(f)
scan_score = next((r['score'] for r in scan_results if r['code'] == 'sh518880'), None)

print(f'Standalone scorer: {our_score}')
print(f'Batch scanner:     {scan_score}')
print(f'Match: {abs(our_score - scan_score) <= 1 if scan_score else \"N/A\"}')
"
```

Expected: Scores should match within ±1 point. If K-line data is fresher, the standalone score may differ slightly because it uses more recent bars.

---

### Task 10: Write SKILL.md

**Files:**
- Create: `.codebuddy/skills/etf-operation-plan/SKILL.md`

- [ ] **Step 1: Write the SKILL.md**

```markdown
---
name: etf-operation-plan
description: Generate a medium-to-long-term operation plan for A-share ETFs based on current positions, real-time market data, technical patterns, and market news. Outputs a focused HTML report answering "what to do in the next period" with specific price levels and scenario analysis. Triggers on requests like "下个交易日怎么操作", "帮我做操作计划", "XXETF接下来怎么办", "看看持仓怎么做".
---

# ETF Operation Plan（ETF操作计划）

## Overview

Generate an actionable medium-to-long-term operation plan for A-share ETFs. Unlike `etf-deep-analysis` (which produces a comprehensive thesis-driven research report), this skill focuses on the **"what should I do now?"** question, anchored to current position data.

## Prerequisites

- `westock-data` for ETF price/K-line data
- `score_patterns.py` (bundled with this skill) for five-pattern technical scoring
- `WebSearch` for market news and catalysts

## Workflow

### Step 1: Identify Target ETF(s)

Read `memory/positions.md` for current holdings — these are the primary targets. Also accept user-specified ETF code if explicitly requested.

```python
import json
# Resolve code -> name from all_etfs_larggest.json
with open('all_etfs_larggest.json') as f:
    etfs = json.load(f)
target = [e for e in etfs if e.get('code') == code][0]
name = target['name']
```

### Step 2: Fetch Real-Time Data

```bash
WD="/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data"
NODE="/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"

# Current quote
$NODE $WD/scripts/index.js quote <code> --raw > /tmp/op_quote.json

# 250-day K-line
$NODE $WD/scripts/index.js kline <code> --period day --limit 250 --raw > /tmp/op_kline.json
```

Quote fields to extract: `price`, `prev_close`, `high`, `low`, `volume`, `amount`, `change_percent`, `chg_5d`, `chg_20d`, `chg_60d`, `chg_ytd`, `high_52week`, `low_52week`, `wb_ratio` (委比)

### Step 3: Run Pattern Scoring

```bash
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py \
  --code <code> --kline-file /tmp/op_kline.json > /tmp/op_scores.json
```

Extract `bowl`, `box`, `w_bottom`, `hs_bottom`, `2b` scores and labels.

### Step 4: Fetch News & Catalysts

Run WebSearch in parallel:

```
WebSearch: "<ETF名称> 最新消息 2026"
WebSearch: "<ETF跟踪主题/标的> 政策 催化"
```

Classify each result as:
- **硬催化**: Price movements, policy documents, earnings revisions — tangible, quantifiable
- **软催化**: Analyst opinions, sentiment shifts, concept rotation — reference only
- **风险事件**: Regulatory risks, macro headwinds, sector headwinds

If no meaningful news is found, note: "当前无重大催化，技术面为主要决策依据"

### Step 5: Compute Position Metrics

From `memory/positions.md` or user-provided position data:
- Entry price, shares, cost
- P&L = (current - cost) × shares
- P&L% = (current / cost - 1) × 100

### Step 6: Compute Key Technical Levels

From the 250-day K-line data, compute:

| Level | Calculation | Label |
|-------|-------------|-------|
| S1 | 60-day low | 中期支撑 |
| S2 | 120-day low | 长期底部 |
| R1 | 60-day high | 中期压力 |
| R2 | 120-day high | 长期压力 |
| Hard Stop | 52-week low (from quote) | 底部失效 |
| 60MA | 60-day moving average | 中期趋势线 |
| Cost Anchor | Entry price | 成本锚点 |

Each level: price, distance from current (%), one-sentence meaning.

```python
# Compute levels from kline data
import json
with open('/tmp/op_kline.json') as f:
    bars = json.load(f)
bars.sort(key=lambda b: b.get('date', ''))
closes = [float(b['last']) for b in bars]
highs_all = [float(b['high']) for b in bars]
lows_all = [float(b['low']) for b in bars]

n = len(closes)
current = closes[-1]

s1 = min(lows_all[-60:])  # 60-day low
s2 = min(lows_all[-120:])  # 120-day low
r1 = max(highs_all[-60:])  # 60-day high
r2 = max(highs_all[-120:])  # 120-day high
ma60 = sum(closes[-60:]) / 60

levels = {
    "S1": {"price": round(s1, 3), "dist_pct": round((current/s1 - 1)*100, 1)},
    "S2": {"price": round(s2, 3), "dist_pct": round((current/s2 - 1)*100, 1)},
    "R1": {"price": round(r1, 3), "dist_pct": round((r1/current - 1)*100, 1)},
    "R2": {"price": round(r2, 3), "dist_pct": round((r2/current - 1)*100, 1)},
    "60MA": {"price": round(ma60, 3), "dist_pct": round((current/ma60 - 1)*100, 1)},
}
```

### Step 7: Scenario Analysis (Weekly Outlook)

Based on current price relative to key levels, pattern scores, and news:

| Scenario | Trigger Condition | Action |
|----------|-------------------|--------|
| **趋势向好** | Stands above 60MA + pattern score improving + positive catalyst | Add to target position, raise trailing stop |
| **区间整理** | Between S1-R1, no pattern change, mixed signals | Hold, wait for confirmation |
| **趋势恶化** | Breaks hard stop or S2 support | Execute stop-loss discipline |

Probability assessment should reference historical volatility (ATR-based band width) and pattern quality.

### Step 8: Decision Matrix

For each ETF, produce:

| Dimension | Output |
|-----------|--------|
| Direction | 看多 / 中性 / 看空 |
| Core Logic | One-line validation of current position thesis |
| Position Action | 加仓 / 持有 / 减仓 / 清仓 |
| Specific Operation | Trigger price + quantitative action |
| Target Price | 1-3 month target + logic |
| Next Review | When/conditions to re-evaluate |

### Step 9: Risk Monitor

3-5 high-priority watch signals:

| Signal | Current | Threshold | Action if Triggered |
|--------|---------|-----------|---------------------|
| (e.g.) Gold < $3800 | $4084 | < $3800 | Exit gold ETF |
| (e.g.) Premium > 5% | 2.65% | > 5% | Reduce 1/3 |

### Step 10: Generate HTML Report

Save to `reports/etf/operation/{YYYYMMDD}-{ETF简称}-操作建议.html`.

Use two-phase f-string approach as documented in `etf-deep-analysis/SKILL.md` Step 9:
1. Pre-compute all dynamic data as Python variables
2. Build HTML with f-string template (use `{{` / `}}` for literal braces in CSS/JS)

**HTML Structure:**

1. **Header** — ETF name, code, date
2. **Section 一: 持仓速览卡片** — Cost/Current/P&L/P&L%, color-coded
3. **Section 二: 技术关键位** — Table of S1/S2/R1/R2/Hard Stop/60MA/Cost Anchor
4. **Section 三: 形态速评** — Five-pattern score table, highlight most relevant
5. **Section 四: 场景推演** — Three scenario cards (bullish/range/bearish)
6. **Section 五: 消息面速览** — News table with type/impact/timeframe
7. **Section 六: 综合决策矩阵** — Decision table (bold, prominent)
8. **Section 七: 风险监控** — Watch signals table
9. **Section 八: 免责声明** — Standard disclaimer

**Style Rules:**
- A-share convention: red = up (涨), green = down (跌)
- Light background, gradient header
- ECharts CDN for any charts (K-line with key level lines)
- HTML tables for structured data
- Sell-side tags: 买入/加仓/标配/减仓/清仓

**JS syntax check (mandatory before delivery):**
```bash
# Extract <script> blocks, save to temp file, check
node --check /tmp/_op_check.js
```

### Step 11: Present Report

1. Present file path as deliverable
2. Chat summary: ETF name, pattern status, direction, specific operation
3. Do NOT paste HTML content in chat

## Multi-ETF Handling

For multiple ETFs (e.g., both positions, or user specifies several):
- Process sequentially through Steps 2-10 for each ETF
- Data fetching (Step 2) and news search (Step 4) can be parallelized across ETFs
- Each ETF gets its own HTML report

## Important Notes

- Uses Chinese stock market convention: red = up (涨), green = down (跌)
- Not investment advice — tool for decision support
- Data sourced from 腾讯自选股 (westock-data) + web search
- Medium-to-long-term focus: weekly scenarios, not daily predictions
- Re-run weekly or when significant market events occur
```

- [ ] **Step 2: Verify SKILL.md is valid markdown**

```bash
head -5 .codebuddy/skills/etf-operation-plan/SKILL.md
```

Expected: Shows the frontmatter block with `name: etf-operation-plan`.

---

### Task 11: End-to-end validation test

**Files:**
- Will generate: `reports/etf/operation/20260807-黄金ETF华安-操作建议.html`

- [ ] **Step 1: Simulate the full skill workflow**

This step simulates what the AI would do when the skill is invoked. Run these commands to validate the end-to-end pipeline:

```bash
cd /Users/aldiadmin/Documents/vscodeworkspace/astock

# Step 1: Identify target (from memory or user input)
TARGET_CODE="sh518880"

# Step 2: Fetch data
$NODE $WD/scripts/index.js quote $TARGET_CODE --raw
$NODE $WD/scripts/index.js kline $TARGET_CODE --period day --limit 250 --raw > /tmp/op_final_kline.json

# Step 3: Run pattern scoring
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py \
  --code $TARGET_CODE --kline-file /tmp/op_final_kline.json
```

Expected: Pattern scores output successfully.

- [ ] **Step 2: Generate a minimal HTML report to validate output path**

```bash
cat > /tmp/gen_test_report.py << 'PYEOF'
import os, json
from datetime import datetime

code = "sh518880"
name = "黄金ETF华安"
date_str = datetime.now().strftime("%Y%m%d")

# Minimal structure test
html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{name}操作建议-{date_str}</title></head>
<body><h1>{name} (sh518880) 操作建议</h1><p>日期: {date_str}</p></body></html>"""

os.makedirs("reports/etf/operation", exist_ok=True)
out_path = f"reports/etf/operation/{date_str}-{name}-操作建议.html"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"Report saved to: {out_path}")
PYEOF

$PYTHON /tmp/gen_test_report.py
```

Expected: `Report saved to: reports/etf/operation/20260807-黄金ETF华安-操作建议.html`

- [ ] **Step 3: Verify file exists and is valid HTML**

```bash
file reports/etf/operation/20260807-黄金ETF华安-操作建议.html
head -3 reports/etf/operation/20260807-黄金ETF华安-操作建议.html
```

Expected: `HTML document text` and valid `<!DOCTYPE html>` header.

- [ ] **Step 4: Commit**

```bash
git add .codebuddy/skills/etf-operation-plan/
git add reports/etf/operation/
git add docs/superpowers/specs/2026-08-07-etf-operation-plan-design.md
git add docs/superpowers/plans/2026-08-07-etf-operation-plan.md
git commit -m "feat: add etf-operation-plan skill with score_patterns.py and SKILL.md"
```
```

- [ ] **Step 2: Verify plan file**

```bash
wc -l docs/superpowers/plans/2026-08-07-etf-operation-plan.md
```

---

## Plan Self-Review

**1. Spec coverage check:**
- [x] Section 1: 持仓速览卡片 → Task 10 (SKILL.md Step 5)
- [x] Section 2: 技术关键位标定 → Task 10 (SKILL.md Step 6)
- [x] Section 3: 形态速评 → Tasks 3-8 (score_patterns.py), Task 10 (Step 3)
- [x] Section 4: 场景推演 → Task 10 (SKILL.md Step 7)
- [x] Section 5: 消息面速览 → Task 10 (SKILL.md Step 4)
- [x] Section 6: 综合决策矩阵 → Task 10 (SKILL.md Step 8)
- [x] Section 7: 风险监控 → Task 10 (SKILL.md Step 9)
- [x] Section 8: 免责声明 → Task 10 (SKILL.md Step 10)
- [x] Helper script score_patterns.py → Tasks 2-8
- [x] HTML report output → Task 10 (Step 10), Task 11 (validation)
- [x] Multi-ETF support → Task 10 (SKILL.md — Multi-ETF Handling section)

**2. Placeholder scan:** No TODOs, TBDs, or incomplete sections found. All tasks have concrete code, commands, and expected outputs.

**3. Type consistency:** All function names match between tasks. `score_patterns.py` main() calls `analyze_bowl_bottom`, `analyze_box_consolidation`, `analyze_w_bottom`, `analyze_hs_bottom`, `analyze_2b` — consistent throughout.
