# ETF T2区间扫描器 Skill 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `etf-t2-scanner` skill，扫描全部A股ETF的T0-T8趋势状态，筛出T2（底部构建）区间标的并生成HTML报告。

**Architecture:** 复用 `etf-operation-plan/trend_analysis.py` 的T0-T8状态机（复制函数进新skill），读取项目根 `etf_kline_data.json` + `all_etfs_larggest.json`，T2标的按5维置信度打分（语义=「接近T3升级」），`analyze.py` 输出 `etf_t2_results.json`，`generate_report.py` 输出 `reports/etf/etf_t2_report.html`。可选联网更新（复用 bowl scanner 的 `update_kline_data` + `--refresh`）。

**Tech Stack:** Python 3.13 标准库（json/subprocess/sys/os/time/concurrent.futures/argparse/datetime）、Chart.js 4.4（CDN）、HTML。

**验证方式说明:** 本仓库无测试框架（AGENTS.md 确认），验证 = 运行脚本 + `python3 -c` 断言 + `node --check` JS 语法检查。

**来源文件行号参考（Task 2 复制用）：**
- `trend_analysis.py`（844行）：数值工具 41-98；K线解析 101-181；MA特征 215-266；波动率 328-341；周线特征 397-477；状态机分类 480-623
- `etf-bowl-bottom-scanner/analyze.py`：`run_westock` 30-43；`fetch_kline` 46-53；`load_etfs` 57-73；`update_kline_data` 363-459

---

### Task 1: 创建 skill 目录与 SKILL.md

**Files:**
- Create: `.workbuddy/skills/etf-t2-scanner/SKILL.md`

- [ ] **Step 1: 创建目录**

```bash
mkdir -p .workbuddy/skills/etf-t2-scanner
```

- [ ] **Step 2: 写入 SKILL.md**

```markdown
---
name: etf-t2-scanner
description: Use when scanning A-share ETFs for the T2 trend state (底部构建) — classify all ETFs with the T0-T8 trend-state machine (weekly-primary, used by etf-operation-plan), score T2 candidates on a 5-dimension confidence engine (approaching T3 upgrade), and output an HTML report. Input is etf_kline_data.json (250-day klines), no network fetch required unless --refresh. Chinese stock market convention: red=up, green=down.
---

# ETF T2区间扫描器 (ETF T2底部构建扫描) v1

## Overview

在全部 A 股 ETF 中寻找处于 **T2区间（底部构建）** 的标的。T2 是 `etf-operation-plan` 趋势状态机（T0-T8，周线为主）中的状态之一：

**T2 底部构建** = ① 价格处于250日区间低位（pos250 ≤ 35%）+ ② 低点开始抬高（近20日低点 > 前20日低点）+ ③ 周线非向下（且未落入 T0/T1/T6/T7/T8）。

本 skill 对全部 ETF 运行完整 T0-T8 分类（与 etf-operation-plan 完全一致），筛出 T2 标的，并按**置信度打分**排序 —— 分数语义 =「越接近 T3 反转确认」。

## Prerequisites

- 项目根目录存在 `etf_kline_data.json`（250日K线，ETF扫描器共享）
- 项目根目录存在 `all_etfs_larggest.json`（ETF列表，含名称）
- Python 3.13 标准库即可，无第三方依赖
- 联网更新模式（可选）需要 Node.js 和 westock-data CLI

## Quick Start

```
1. 确保 etf_kline_data.json 与 all_etfs_larggest.json 存在于项目根目录
2. 运行 analyze.py → 判定状态 + T2置信度打分 → etf_t2_results.json
   - 追加 --refresh 可强制刷新当日盘中数据为收盘数据（15:00后使用）
3. 运行 generate_report.py → reports/etf/etf_t2_report.html
4. present_files 展示 HTML 报告
```

## Step-by-Step Workflow

### Step 1: Run Analysis

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON .workbuddy/skills/etf-t2-scanner/analyze.py

# 收盘后刷新盘中数据:
$PYTHON .workbuddy/skills/etf-t2-scanner/analyze.py --refresh
```

`analyze.py` 流程：
- 加载 `all_etfs_larggest.json`（ETF名称）+ `etf_kline_data.json`（K线）
- （可选）检查数据新鲜度，联网追加最新K线；`--refresh` 替换当日盘中bar
- 对每只 ETF 计算：周线特征（完整周重采样）、MA特征（60/120/250）、结构（高低点）、波动率
- 运行 `classify_trend_state` 判定 T0-T8（含 T3a/T3b）
- T2 标的追加 5 维置信度打分 → 排序输出
- 保存 `etf_t2_results.json`（状态分布 + T2明细）
- 控制台打印状态分布统计 + T2 TOP 排名

### Step 2: Generate HTML Report

```bash
$PYTHON .workbuddy/skills/etf-t2-scanner/generate_report.py
```

产出 `reports/etf/etf_t2_report.html`：
- 摘要卡片（T0-T8 状态计数、T2总数、T2平均置信度）
- 状态分布柱状图（Chart.js，判断大盘筑底广度）
- T2置信度排名表（TOP 25）
- T2 TOP 前9名 120日K线缩略图
- T2 详细分析卡片（状态机reasons + 置信度分项）

## T0-T8 状态机要点

（完整逻辑复制自 `.workbuddy/skills/etf-operation-plan/trend_analysis.py` 的 `classify_trend_state`）

| 状态 | 含义 | 核心条件 |
|------|------|----------|
| T0 | 长期下降 | 周线向下+空头排列+低点降低 |
| T1 | 下降减速 | 周线向下但日线减速/反弹 |
| **T2** | **底部构建** | **pos250≤35% + 低点抬高 + 周线非向下** |
| T3a/T3b | 反转初步确认 | 周线转上+站上MA60（MA60向下/向上） |
| T4 | 中期上升确认 | 多头排列+高低点抬高+周线向上 |
| T5 | 上升加速 | 多头排列+强动量 |
| T6 | 高位整理 | 250日高位+走平 |
| T7 | 趋势衰竭 | 高位+均线转平/向下 |
| T8 | 结构破坏 | 周线跌破前低+向下 |

注：本扫描器使用**原始分类**（不包含操作计划的迁移状态机持久化与连续周确认规则 —— 那是单ETF操作计划专用的）。

## T2 置信度打分（满分100，语义=「接近T3升级」）

| 维度 | 满分 | 计分规则 |
|------|------|----------|
| 低点抬高幅度 | 30 | 近20日低点vs前20日低点：≥3% = 30；≥1% = 22；≥0.5% = 15；>0 = 8 |
| 距250日低点距离 | 25 | pos250 ≤10% = 25；≤20% = 20；≤30% = 12；其他 = 5 |
| 周线斜率回升 | 20 | 周线up = 20；flat且slope>-0.5 = 15；flat = 10；down = 5 |
| 距MA60距离 | 15 | -15%~-2% = 15；-20~-15% = 9；-2~3% = 10；其他 = 4 |
| 量能/波幅 | 10 | 周量比<0.8 = 5（<1.0 = 3）+ ATR比<0.85 = 5（<1.0 = 3） |

**惩罚:** 近20日动量 t20 < -4% → -10分（分数截断 0-100）。

## Interpretation Guidance

- **高分T2**（≥70）：筑底结构完整，低点抬升显著+周线走平，最接近T3确认，可按操作计划 T2 档（原核心仓可观察/小额试仓，约25%）关注。
- **中分T2**（50-69）：筑底进行中，需观察低点是否继续抬高。
- **低分T2**（<50）：刚进入筑底或抬升微弱，等待进一步证据。
- **状态分布**: 若大量ETF同时处于 T1/T2（下降减速/底部构建），可能预示市场整体筑底；若 T0 占比高，市场仍处于系统性下跌。
- T2 → T3a/T3b 升级需周线转上+站上MA60，可关注高分T2是否出现该信号。

## Important Notes

- 使用A股颜色惯例：**红涨绿跌**（与美国/欧洲相反）。
- 仅量化扫描，**不构成投资建议**。
- 数据来自腾讯自选股接口（经 westock-data），可能有延迟；本地 JSON 若不刷新可能过期。
- 与 `etf-operation-plan` 的状态判定完全一致（同一状态机代码），可互相印证。
```

- [ ] **Step 3: 验证 frontmatter 完整性**

```bash
head -5 .workbuddy/skills/etf-t2-scanner/SKILL.md
```
Expected: `---`、`name: etf-t2-scanner`、`description: ...`

- [ ] **Step 4: Commit**

```bash
git add .workbuddy/skills/etf-t2-scanner/SKILL.md
git commit -m "feat: add etf-t2-scanner skill definition"
```

---

### Task 2: analyze.py — 状态机核心（复制）+ 导入验证

**Files:**
- Create: `.workbuddy/skills/etf-t2-scanner/analyze.py`

- [ ] **Step 1: 创建 analyze.py 骨架并复制状态机函数**

```bash
cat > .workbuddy/skills/etf-t2-scanner/analyze.py << 'PYEOF'
#!/usr/bin/env python3
"""
A股ETF T2区间扫描器 (v1)

对全部A股ETF运行 T0-T8 趋势状态机（来源: etf-operation-plan/trend_analysis.py,
v1.0 复制），筛出 T2(底部构建) 标的，并按 5 维置信度打分排序
(语义 = 接近T3升级)。

数据输入: 项目根 etf_kline_data.json + all_etfs_larggest.json
可选联网更新: 复用 etf-bowl-bottom-scanner 的 update_kline_data 逻辑
"""
import json
import subprocess
import sys
import os
import time
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK_BIN = "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data/scripts/index.js"
NODE_BIN = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"

KLINE_DAYS = 250
MAX_WORKERS = 8
CHECK_DAYS = 5


# ─── Shared numeric utilities (from trend_analysis.py:41-98) ────────────────
PYEOF
```

然后逐段追加（用 `cat >>`），每段源码**逐字符复制**自 `trend_analysis.py` 对应行号：
- 41-98（`lin_slope`/`atr`/`ma_series`/`dir_label`）
- 101-181（`parse_kline`/`resample_weekly`/`week_completeness`）
- 215-266（`compute_ma_features`）
- 328-341（`compute_volatility`）
- 397-477（`compute_weekly_features` + `_preview_block`）
- 480-623（`classify_trend_state`）

```bash
# 校验复制完整性: 函数名计数应为预期值
grep -c "^def \|^    def " .workbuddy/skills/etf-t2-scanner/analyze.py
```
Expected: 12 个函数定义（lin_slope, atr, ma_series, dir_label, parse_kline, resample_weekly, week_completeness, compute_ma_features, compute_volatility, compute_weekly_features, _preview_block, classify_trend_state）。

- [ ] **Step 2: 导入自检（仅标准库）**

```bash
/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('m', '.workbuddy/skills/etf-t2-scanner/analyze.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert callable(m.classify_trend_state)
assert callable(m.compute_weekly_features)
assert callable(m.parse_kline)
print('OK: state machine functions imported cleanly')
"
```
Expected: `OK: state machine functions imported cleanly`

- [ ] **Step 3: 用真实数据快速验证状态机正确性**

```bash
/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -c "
import importlib.util, json
spec = importlib.util.spec_from_file_location('m', '.workbuddy/skills/etf-t2-scanner/analyze.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
with open('etf_kline_data.json') as f: data = json.load(f)
from collections import Counter
counts = Counter()
n_ok = 0
for code, kl in list(data.items())[:50]:
    recs = m.parse_kline(kl)
    if not recs: continue
    closes = [r['close'] for r in recs]; highs = [r['high'] for r in recs]; lows = [r['low'] for r in recs]
    ds, ws = m.week_completeness(recs, False)
    wb = m.resample_weekly(recs)
    ma = m.compute_ma_features(closes, highs, lows)
    st = m.compute_structure(closes, highs, lows)
    vv = m.compute_volatility(highs, lows, closes)
    wk = m.compute_weekly_features(wb, ws)
    t = m.classify_trend_state(ma, st, wk, closes, highs, lows)
    counts[t['code']] += 1; n_ok += 1
print('classified:', n_ok, 'state distribution:', dict(counts))
assert n_ok > 40
"
```
Expected: `classified: ~50` 且分布中 T2 数量合理（0-N 均正常，断言仅检查分类不崩溃）。

- [ ] **Step 4: Commit**

```bash
git add .workbuddy/skills/etf-t2-scanner/analyze.py
git commit -m "feat(etf-t2-scanner): copy T0-T8 state machine core"
```

---

### Task 3: analyze.py — T2 置信度打分 + 完整分析流程

**Files:**
- Modify: `.workbuddy/skills/etf-t2-scanner/analyze.py`（追加到文件末尾，`main()` 之前）

- [ ] **Step 1: 追加置信度打分与联网更新代码**

在 analyze.py 末尾（`classify_trend_state` 之后）追加以下完整代码：

```python
# ─── T2 confidence scoring (语义=接近T3升级) ─────────────────────────────

def score_t2(ma, weekly, volatility, closes, highs, lows):
    """5维置信度打分, 满分100。返回 (score, reasons, breakdown)。"""
    n = len(closes)
    cur = closes[-1]

    # 1. 低点抬高幅度 (max 30)
    hl_pct = 0.0
    if n >= 40:
        lo_recent = min(lows[-20:])
        lo_prior = min(lows[-40:-20])
        hl_pct = (lo_recent - lo_prior) / lo_prior * 100 if lo_prior > 0 else 0.0
    if hl_pct >= 3:
        s_hl = 30
    elif hl_pct >= 1:
        s_hl = 22
    elif hl_pct >= 0.5:
        s_hl = 15
    elif hl_pct > 0:
        s_hl = 8
    else:
        s_hl = 0

    # 2. 距250日低点距离 (max 25)
    n250 = min(250, n)
    hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5
    if pos250 <= 0.10:
        s_pos = 25
    elif pos250 <= 0.20:
        s_pos = 20
    elif pos250 <= 0.30:
        s_pos = 12
    else:
        s_pos = 5

    # 3. 周线斜率回升 (max 20)
    wk_slope = weekly.get("slope_10w_pct", 0.0)
    wk_dir = weekly.get("direction", "flat")
    if wk_dir == "up":
        s_wk = 20
    elif wk_dir == "flat" and wk_slope > -0.5:
        s_wk = 15
    elif wk_dir == "flat":
        s_wk = 10
    else:
        s_wk = 5

    # 4. 距MA60距离 (max 15)
    d_ma60 = ma.get("price_vs_ma60_pct")
    if d_ma60 is None:
        s_ma = 5
    elif -15 <= d_ma60 <= -2:
        s_ma = 15
    elif -20 <= d_ma60 < -15:
        s_ma = 9
    elif -2 < d_ma60 <= 3:
        s_ma = 10
    else:
        s_ma = 4

    # 5. 量能/波幅 (max 10)
    vol_ratio = weekly.get("vol_ratio_weekly", 1.0)
    atr_ratio = volatility.get("atr_ratio", 1.0)
    s_vol = 0
    if vol_ratio < 0.8:
        s_vol += 5
    elif vol_ratio < 1.0:
        s_vol += 3
    if atr_ratio < 0.85:
        s_vol += 5
    elif atr_ratio < 1.0:
        s_vol += 3

    score = s_hl + s_pos + s_wk + s_ma + s_vol

    # 惩罚: 近20日动量快速下跌
    t20 = lin_slope(closes, 20)
    if t20 < -4:
        score -= 10

    score = max(0, min(100, score))

    breakdown = {
        "hl_pct": round(hl_pct, 2), "hl_score": s_hl,
        "pos250": round(pos250 * 100, 1), "pos_score": s_pos,
        "wk_slope": round(wk_slope, 2), "wk_dir": wk_dir, "wk_score": s_wk,
        "d_ma60": d_ma60, "ma_score": s_ma,
        "vol_ratio": round(vol_ratio, 2), "atr_ratio": round(atr_ratio, 2),
        "vol_score": s_vol,
        "t20": round(t20, 2), "penalty": -10 if t20 < -4 else 0,
    }
    reasons = [
        f"低点抬高幅度 {hl_pct:+.1f}% (得{s_hl}/30)",
        f"250日区间位置 {pos250*100:.0f}% (得{s_pos}/25)",
        f"周线方向 {wk_dir}, slope10w {wk_slope:+.1f}% (得{s_wk}/20)",
        f"距MA60 {d_ma60 if d_ma60 is not None else 'n/a'}% (得{s_ma}/15)",
        f"周量比 {vol_ratio:.2f}, ATR比 {atr_ratio:.2f} (得{s_vol}/10)",
    ]
    if breakdown["penalty"]:
        reasons.append(f"惩罚: 近20日动量 {t20:+.1f}% < -4% (-10分)")
    return score, reasons, breakdown


def analyze_etf(code, name, etype, kline_data):
    """对单只ETF运行状态机; 若为T2则附加置信度打分。返回结果dict或None。"""
    records = parse_kline(kline_data)
    if not records:
        return None

    closes = [r["close"] for r in records]
    highs = [r["high"] for r in records]
    lows = [r["low"] for r in records]

    daily_status, weekly_status = week_completeness(records, False)
    weekly_bars = resample_weekly(records)

    ma = compute_ma_features(closes, highs, lows)
    structure = compute_structure(closes, highs, lows)
    volatility = compute_volatility(highs, lows, closes)
    weekly = compute_weekly_features(weekly_bars, weekly_status)
    trend = classify_trend_state(ma, structure, weekly, closes, highs, lows)

    n250 = min(250, len(closes))
    hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
    cur = closes[-1]
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5
    dd_high = (cur - hi250) / hi250 * 100 if hi250 > 0 else 0.0

    result = {
        "code": code, "name": name, "type": etype,
        "trend_state": trend,
        "pos250": round(pos250 * 100, 1),
        "drawdown_250d": round(dd_high, 1),
        "current": round(cur, 3),
        "ma": {"price_vs_ma60_pct": ma.get("price_vs_ma60_pct"),
               "alignment": ma.get("alignment"),
               "ma60_dir": ma.get("ma60_dir")},
        "structure": structure,
        "weekly": {"direction": weekly.get("direction"),
                   "slope_10w_pct": weekly.get("slope_10w_pct"),
                   "vol_ratio_weekly": weekly.get("vol_ratio_weekly"),
                   "num_weeks": weekly.get("num_weeks")},
        "volatility": volatility,
    }
    if trend.get("code") == "T2":
        score, reasons, breakdown = score_t2(
            ma, weekly, volatility, closes, highs, lows)
        result["t2_score"] = score
        result["t2_reasons"] = reasons
        result["t2_breakdown"] = breakdown
    return result


# ─── Data update (from etf-bowl-bottom-scanner/analyze.py) ─────────────────

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
        print(f"❌ Input file not found: {input_path}", file=sys.stderr)
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


def update_kline_data(kline_data, etfs, kline_file, refresh_today=False):
    """
    Check cached kline data and append latest records if any are missing.
    (逐字符复制自 etf-bowl-bottom-scanner/analyze.py 的 update_kline_data)
    """
    if not etfs:
        return 0

    # ---- Quick check: get the latest available date from data source ----
    sample_code = etfs[0]["code"]
    sample_data = run_westock("kline", sample_code, "--period", "day", "--limit", str(CHECK_DAYS))
    if not sample_data or not isinstance(sample_data, list) or len(sample_data) == 0:
        print("  ⚠ 无法获取最新交易日期, 跳过更新检查")
        return 0
    latest_available_date = sample_data[0]["date"]

    # ---- Determine which ETFs need an update ----
    to_update = []
    to_refresh = []  # ETFs whose today-bar needs refresh (same date, possibly intraday)
    for e in etfs:
        code = e["code"]
        cached = kline_data.get(code)
        if not cached or not isinstance(cached, list) or len(cached) == 0:
            to_update.append(code)
            continue
        latest_cached_date = cached[0]["date"]  # newest-first
        if latest_cached_date < latest_available_date:
            to_update.append(code)
        elif refresh_today and latest_cached_date == latest_available_date:
            to_refresh.append(code)

    all_to_process = to_update + to_refresh
    if not all_to_process:
        if refresh_today:
            print("  盘中数据已刷新为收盘数据")
        return 0

    refresh_desc = f" (+{len(to_refresh)} 只刷新今日盘中数据)" if to_refresh else ""
    print(f"\n🔄 需要更新 {len(all_to_process)} 只ETF的K线数据 (最新交易日: {latest_available_date}){refresh_desc}")

    # ---- Fetch and merge in parallel ----
    updated = 0
    failed = 0
    total = len(all_to_process)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_kline, code): code for code in all_to_process}
        for future in as_completed(futures):
            code = futures[future]
            try:
                _, new_data = future.result()
                if new_data and isinstance(new_data, list) and len(new_data) > 0:
                    cached = kline_data.get(code, [])
                    if code in to_refresh:
                        # Replace entire dataset — refreshes intraday bar with latest from source
                        kline_data[code] = new_data
                        updated += 1
                    elif cached and isinstance(cached, list) and len(cached) > 0:
                        latest_cached_date = cached[0]["date"]
                        new_records = [r for r in new_data if r["date"] > latest_cached_date]
                        if new_records:
                            kline_data[code] = new_records + cached
                            updated += 1
                        # else: no new records to append (up to date)
                    else:
                        kline_data[code] = new_data
                        updated += 1
                else:
                    failed += 1
                if (updated + failed) % 20 == 0:
                    print(f"  更新进度: {updated + failed}/{total}")
            except Exception as e:
                failed += 1
                print(f"  {code} 更新失败: {e}")

    print(f"更新完成: {updated} 成功, {failed} 失败")

    # ---- Save merged data ----
    if updated > 0:
        with open(kline_file, "w") as f:
            json.dump(kline_data, f, ensure_ascii=False)
        print(f"K线数据已保存: {kline_file}")

    return updated
```

注意：`subprocess` 已在 Task 2 的导入区包含。

- [ ] **Step 2: 追加 main()**

```python
# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    refresh_today = "--refresh" in sys.argv
    print("=" * 60)
    print("A股ETF T2区间扫描 (T0-T8状态机)")
    if refresh_today:
        print("🔄 盘中刷新模式: 同日期数据将用最新数据替换")
    print("=" * 60)

    # Step 1: Load ETF list
    print("\n📋 加载ETF列表...")
    etfs = load_etfs()
    if not etfs:
        print("❌ 未找到ETF列表。请确保 all_etfs_larggest.json 存在于项目根目录。")
        return
    print(f"共加载 {len(etfs)} 只ETF")

    # Step 2: Load kline data
    kline_file = os.path.join(os.getcwd(), "etf_kline_data.json")
    if not os.path.exists(kline_file):
        print(f"❌ 未找到K线数据: {kline_file}")
        return
    print(f"\n📊 加载K线数据: {kline_file}")
    with open(kline_file) as f:
        kline_data = json.load(f)
    print(f"已加载 {len(kline_data)} 只ETF K线数据")

    # Step 3: Optional network update
    if refresh_today:
        updated = update_kline_data(kline_data, etfs, kline_file, refresh_today)
        if updated > 0:
            print(f"已更新 {updated} 只ETF")
        else:
            print("K线数据已是最新，无需更新")

    # Step 4: Classify all ETFs
    print("\n🔍 运行T0-T8趋势状态机...")
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results = []
    for e in etfs:
        kl = kline_data.get(e["code"])
        if not kl:
            continue
        r = analyze_etf(e["code"], e["name"], e["type"], kl)
        if r:
            results.append(r)

    # Step 5: Summary + save
    t2_list = [r for r in results if r["trend_state"]["code"] == "T2"]
    t2_list.sort(key=lambda x: x.get("t2_score", 0), reverse=True)

    dist = {}
    for r in results:
        c = r["trend_state"]["code"]
        sub = r["trend_state"].get("sub_state")
        key = c + (f"({sub})" if sub else "")
        dist[key] = dist.get(key, 0) + 1

    print("\n" + "=" * 60)
    print(f"📊 趋势状态分布 (共{len(results)}只ETF)")
    print("=" * 60)
    for k in sorted(dist, key=lambda x: (int(x[1]) if x[1].isdigit() else 9, x)):
        print(f"  {k}: {dist[k]}")

    print(f"\n🏆 T2底部构建标的: {len(t2_list)} 只")
    print(f"\n{'排名':<4}{'ETF':<18}{'置信度':<6}{'250位%':<8}{'抬底%':<8}{'周线':<8}{'距MA60':<8}")
    print("-" * 80)
    for i, r in enumerate(t2_list[:20]):
        b = r.get("t2_breakdown", {})
        print(f"{i+1:<4}{r['name']:<18}{r.get('t2_score', 0):<6}{b.get('pos250', '-'):<8}"
              f"{b.get('hl_pct', 0):+<8}{b.get('wk_dir', '-'):<8}{b.get('d_ma60', '-'):<8}")

    out = {
        "meta": {
            "generated": dt.datetime.now().isoformat(),
            "sample_size": len(results),
            "kline_file": kline_file,
        },
        "state_distribution": dist,
        "t2_count": len(t2_list),
        "t2_avg_score": round(sum(r.get("t2_score", 0) for r in t2_list) / len(t2_list), 1) if t2_list else None,
        "results": results,
    }
    results_file = os.path.join(skill_dir, "etf_t2_results.json")
    with open(results_file, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n分析结果已保存: {results_file}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 全量运行验证**

```bash
/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 .workbuddy/skills/etf-t2-scanner/analyze.py
```
Expected: 状态分布打印正常，T2列表非空（数量不限），`etf_t2_results.json` 生成。

- [ ] **Step 4: 结果JSON结构断言**

```bash
/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -c "
import json
with open('.workbuddy/skills/etf-t2-scanner/etf_t2_results.json') as f:
    out = json.load(f)
assert 'state_distribution' in out and 'results' in out
assert out['t2_count'] == sum(1 for r in out['results'] if r['trend_state']['code'] == 'T2')
for r in out['results']:
    if r['trend_state']['code'] == 'T2':
        assert 0 <= r['t2_score'] <= 100
        assert len(r['t2_breakdown']) == 14
        assert len(r['t2_reasons']) >= 5
print('OK: t2_count =', out['t2_count'], 'avg score =', out['t2_avg_score'])
"
```
Expected: `OK: t2_count = N, avg score = M`

- [ ] **Step 5: 单ETF与操作计划交叉验证（可选但推荐）**

```bash
# 任选报告中的一只T2 ETF, 用操作计划脚本验证状态一致
/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 .workbuddy/skills/etf-operation-plan/trend_analysis.py --code sh510300 --kline-file /tmp/op_kline.json 2>/dev/null | /Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -c "import json,sys; d=json.load(sys.stdin); print('operation-plan state:', d.get('trend_state', {}).get('code'))"
```
说明：需要先导出单只ETF的K线文件到 /tmp/op_kline.json（可选验证，失败不阻塞）。

- [ ] **Step 6: Commit**

```bash
git add .workbuddy/skills/etf-t2-scanner/analyze.py .workbuddy/skills/etf-t2-scanner/etf_t2_results.json
git commit -m "feat(etf-t2-scanner): T2 confidence scoring + full analysis pipeline"
```

---

### Task 4: generate_report.py — HTML 报告

**Files:**
- Create: `.workbuddy/skills/etf-t2-scanner/generate_report.py`

- [ ] **Step 1: 写入 generate_report.py 完整代码**

```python
#!/usr/bin/env python3
"""
生成 A股ETF T2区间扫描 HTML 报告 (v1)
- 摘要卡片 (状态分布 + T2统计)
- 状态分布柱状图 (Chart.js)
- T2置信度排名表 (TOP 25)
- T2 TOP 前9名 120日K线缩略图 (Chart.js)
- T2 详细分析卡片 (状态机reasons + 置信度分项)
"""

import json
import os
from datetime import datetime


def build_report(out, klines, output_path):
    today = datetime.now().strftime("%Y-%m-%d")

    results = out["results"]
    dist = out["state_distribution"]
    t2_list = [r for r in results if r["trend_state"]["code"] == "T2"]
    t2_list.sort(key=lambda x: x.get("t2_score", 0), reverse=True)
    total = len(results)
    t2_count = len(t2_list)
    avg_score = out.get("t2_avg_score")

    state_colors = {
        "T0": "#e74c3c", "T1": "#e67e22", "T2": "#27ae60", "T3": "#2ecc71",
        "T3a": "#2ecc71", "T3b": "#1abc9c", "T4": "#3498db", "T5": "#9b59b6",
        "T6": "#95a5a6", "T7": "#8e44ad", "T8": "#c0392b",
    }

    # ---- State distribution bar chart data ----
    state_keys = sorted(dist, key=lambda x: (int(x[1]) if x[1][:1].isdigit() else 9, x))
    dist_labels = json.dumps(state_keys, ensure_ascii=False)
    dist_values = json.dumps([dist[k] for k in state_keys], ensure_ascii=False)
    dist_colors = json.dumps([state_colors.get(k[:2], "#7f8c8d") for k in state_keys], ensure_ascii=False)

    # ---- Ranking table (top 25 T2) ----
    table_rows = []
    for i, r in enumerate(t2_list[:25]):
        b = r.get("t2_breakdown", {})
        score = r.get("t2_score", 0)
        score_cls = "pos" if score >= 70 else ("warn" if score >= 50 else "muted")
        wk_cls = "pos" if b.get("wk_dir") == "up" else ("warn" if b.get("wk_dir") == "flat" else "neg")
        table_rows.append(f"""
        <tr>
          <td><b>{i+1}</b></td>
          <td><b>{r['name']}</b><br><span class="muted">{r['code']}</span></td>
          <td><span class="score-badge {score_cls}">{score}</span></td>
          <td class="low">{b.get('pos250', '-')}%</td>
          <td class="{'pos' if b.get('hl_pct', 0) > 0 else 'neg'}">{b.get('hl_pct', 0):+}%</td>
          <td class="{wk_cls}">{b.get('wk_dir', '-')} ({b.get('wk_slope', 0):+.1f}%)</td>
          <td class="{'neg' if (b.get('d_ma60') or 0) < 0 else 'pos'}">{b.get('d_ma60', '-')}%</td>
          <td>{b.get('vol_ratio', '-')}</td>
          <td>{b.get('atr_ratio', '-')}</td>
        </tr>""")

    # ---- Sparkline charts for top 9 T2 ----
    chart_blocks = []
    for r in t2_list[:9]:
        recs = sorted(klines.get(r["code"], []), key=lambda x: x["date"])[-120:]
        closes = [round(float(x["last"]), 2) for x in recs]
        dates = [x["date"][:10] for x in recs]
        b = r.get("t2_breakdown", {})
        chart_blocks.append({
            "name": r["name"], "code": r["code"], "score": r.get("t2_score", 0),
            "closes": closes, "dates": dates,
            "pos250": b.get("pos250"), "hl": b.get("hl_pct"), "wk": b.get("wk_dir"),
        })
    chart_json = json.dumps(chart_blocks, ensure_ascii=False)

    # ---- Detail cards for all T2 ----
    detail_cards = []
    for i, r in enumerate(t2_list[:25]):
        trend = r["trend_state"]
        state_reasons = "".join(f"<li>{x}</li>" for x in trend.get("reasons", []))
        t2_reasons = "".join(f"<li>{x}</li>" for x in r.get("t2_reasons", []))
        b = r.get("t2_breakdown", {})
        score = r.get("t2_score", 0)
        border = "#27ae60" if score >= 70 else ("#f39c12" if score >= 50 else "#95a5a6")
        detail_cards.append(f"""
        <div class="detail-card" style="border-left-color:{border}">
          <div class="detail-head">
            <span class="rank" style="background:{border}">#{i+1}</span>
            <h3>{r['name']}</h3>
            <span class="muted">{r['code']}</span>
            <span class="score-badge">置信度 {score}/100</span>
          </div>
          <div class="detail-grid">
            <div class="metric"><span class="ml">当前价格</span><span class="mv">{r['current']}</span></div>
            <div class="metric"><span class="ml">250日区间位</span><span class="mv low">{b.get('pos250', '-')}%</span></div>
            <div class="metric"><span class="ml">250日回撤</span><span class="mv neg">{r['drawdown_250d']}%</span></div>
            <div class="metric"><span class="ml">低点抬高</span><span class="mv {'pos' if b.get('hl_pct', 0) > 0 else 'neg'}">{b.get('hl_pct', 0):+}%</span></div>
            <div class="metric"><span class="ml">周线方向</span><span class="mv">{b.get('wk_dir', '-')}</span></div>
            <div class="metric"><span class="ml">周线斜率10w</span><span class="mv">{b.get('wk_slope', 0):+.1f}%</span></div>
            <div class="metric"><span class="ml">距MA60</span><span class="mv {'neg' if (b.get('d_ma60') or 0) < 0 else 'pos'}">{b.get('d_ma60', '-')}%</span></div>
            <div class="metric"><span class="ml">周量比</span><span class="mv">{b.get('vol_ratio', '-')}</span></div>
            <div class="metric"><span class="ml">ATR比(20/60)</span><span class="mv">{b.get('atr_ratio', '-')}</span></div>
            <div class="metric"><span class="ml">近20日动量</span><span class="mv {'neg' if (b.get('t20') or 0) < 0 else 'pos'}">{b.get('t20', 0):+.1f}%</span></div>
            <div class="metric"><span class="ml">均线排列</span><span class="mv muted">{r['ma']['alignment']}</span></div>
            <div class="metric"><span class="ml">周线数据</span><span class="mv muted">{r['weekly'].get('num_weeks', '-')}周</span></div>
          </div>
          <div class="reasons"><b>状态机判定依据 (T2):</b><ul>{state_reasons}</ul></div>
          <div class="reasons" style="margin-top:8px"><b>置信度分项:</b><ul>{t2_reasons}</ul></div>
        </div>""")

    dist_t1 = dist.get("T1", 0)
    dist_t3 = sum(v for k, v in dist.items() if k.startswith("T3"))

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股ETF T2底部构建扫描报告 · {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:#f5f6fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#0f3d1e 0%,#14532d 50%,#1a6b3a 100%); color:#fff; padding:36px 30px; border-radius:12px; margin-bottom:24px; box-shadow:0 4px 20px rgba(0,0,0,0.15); }}
.header h1 {{ font-size:26px; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.85; font-size:14px; }}
.header .meta {{ margin-top:14px; display:flex; gap:24px; font-size:13px; opacity:0.75; flex-wrap:wrap; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(6,1fr); gap:14px; margin-bottom:28px; }}
.summary-card {{ background:#fff; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.summary-card .number {{ font-size:30px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#7f8c8d; margin-top:4px; }}
.c-green .number {{ color:#27ae60; }} .c-orange .number {{ color:#e67e22; }} .c-red .number {{ color:#e74c3c; }}
.c-blue .number {{ color:#2980b9; }} .c-gray .number {{ color:#7f8c8d; }} .c-purple .number {{ color:#8e44ad; }}
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
.low {{ color:#e67e22; font-weight:600; }}
.warn {{ color:#e67e22; font-weight:600; }}
.score-badge {{ padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
.score-badge.pos {{ background:#e8f8f0; color:#27ae60; }}
.score-badge.warn {{ background:#fef5e7; color:#e67e22; }}
.score-badge.muted {{ background:#f0f2f5; color:#7f8c8d; }}
.dist-chart-box {{ height:280px; background:#fff; border-radius:10px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.06); margin-bottom:28px; }}
.charts-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:18px; margin-bottom:28px; }}
.chart-card {{ background:#fff; border-radius:10px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.chart-card h4 {{ font-size:15px; margin-bottom:4px; display:flex; align-items:center; gap:8px; }}
.chart-card .sub {{ font-size:12px; color:#7f8c8d; margin-bottom:10px; }}
.chart-box {{ height:150px; position:relative; }}
.detail-card {{ background:#fff; border-radius:10px; padding:20px; margin-bottom:18px; box-shadow:0 2px 10px rgba(0,0,0,0.06); border-left:4px solid #27ae60; }}
.detail-head {{ display:flex; align-items:center; gap:12px; margin-bottom:14px; flex-wrap:wrap; }}
.detail-head .rank {{ color:#fff; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; }}
.detail-head h3 {{ font-size:18px; }}
.detail-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px; }}
.metric {{ background:#f8f9fa; padding:9px 12px; border-radius:6px; }}
.metric .ml {{ font-size:12px; color:#7f8c8d; display:block; }}
.metric .mv {{ font-size:15px; font-weight:600; }}
.reasons {{ background:#f8f9fa; padding:12px 16px; border-radius:6px; }}
.reasons ul {{ list-style:none; margin-top:6px; }}
.reasons li {{ padding:2px 0; font-size:13px; }}
.note {{ background:#eaf7ef; border-left:4px solid #27ae60; padding:14px 18px; border-radius:6px; margin:20px 0; font-size:13px; }}
.disclaimer {{ background:#fdecea; border-radius:8px; padding:16px 20px; margin-top:28px; font-size:12px; color:#c0392b; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>🏗️ A股ETF T2底部构建扫描报告</h1>
  <div class="subtitle">T0-T8趋势状态机扫描 · T2区间(底部构建)候选 · 置信度=接近T3升级概率</div>
  <div class="meta">
    <span>📅 数据日期: {today}</span>
    <span>📊 样本: {total} 只ETF</span>
    <span>📈 K线周期: 日线 250 天</span>
    <span>🔍 算法: T0-T8状态机 + 5维置信度打分</span>
  </div>
</div>

<div class="summary-cards">
  <div class="summary-card c-green"><div class="number">{t2_count}</div><div class="label">🏗️ T2 底部构建</div></div>
  <div class="summary-card c-green"><div class="number">{avg_score if avg_score is not None else '-'}</div><div class="label">T2平均置信度</div></div>
  <div class="summary-card c-orange"><div class="number">{dist_t1}</div><div class="label">T1 下降减速</div></div>
  <div class="summary-card c-green"><div class="number">{dist_t3}</div><div class="label">T3 反转确认中</div></div>
  <div class="summary-card c-red"><div class="number">{dist.get('T0', 0)}</div><div class="label">T0 长期下降</div></div>
  <div class="summary-card c-gray"><div class="number">{total - t2_count - dist_t1 - dist_t3 - dist.get('T0', 0)}</div><div class="label">其他状态</div></div>
</div>

<div class="note">
  <b>📌 T2 判定逻辑:</b> ① 250日区间位置 ≤ 35% + ② 低点抬高（近20日低点 > 前20日低点）+ ③ 周线非向下（且未落入T0/T1/T6/T7/T8）。
  置信度打分 5 维: 低点抬高幅度(30) + 距250日低点(25) + 周线斜率回升(20) + 距MA60(15) + 量能/波幅(10)。
  高分(≥70) = 最接近 T3 反转确认，可按操作计划 T2 档（小额试仓，约25%）观察。
</div>

<div class="section-title">📊 趋势状态分布 <span class="count">(全部ETF, 判断大盘筑底广度)</span></div>
<div class="dist-chart-box"><canvas id="distChart"></canvas></div>

<div class="section-title">🏆 T2 置信度排名 (TOP 25) <span class="count">颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>置信度</th><th>250日位</th><th>抬底%</th><th>周线方向</th><th>距MA60</th><th>周量比</th><th>ATR比</th>
</tr></thead>
<tbody>
{''.join(table_rows)}
</tbody></table>
</div>

<div class="section-title">📈 T2 高分ETF — K线缩略图 <span class="count">(前9名 120日走势)</span></div>
<div class="charts-grid" id="chartsGrid"></div>

<div class="section-title">📝 T2 详细分析</div>
{''.join(detail_cards)}

<div class="disclaimer">
  ⚠️ <b>风险提示:</b> 本报告仅基于历史价格形态的客观量化分析，不构成任何投资建议。T2为底部构建状态，
  存在继续下跌 (跌回T1/T0) 的可能；T2→T3升级需周线转上+站上MA60确认。投资有风险，决策需谨慎。
  请结合基本面、资金面、宏观环境综合判断。数据来源: 腾讯自选股行情接口，可能存在延迟，以交易所官方数据为准。
</div>

</div>

<script>
const distLabels = {dist_labels};
const distValues = {dist_values};
const distColors = {dist_colors};
new Chart(document.getElementById('distChart'), {{
  type: 'bar',
  data: {{
    labels: distLabels,
    datasets: [{{ data: distValues, backgroundColor: distColors, borderRadius: 4, barPercentage: 0.7 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: (i) => i.parsed.y + ' 只' }} }}
    }},
    scales: {{
      x: {{ ticks: {{ font: {{ size: 12 }}, color: '#5a6473' }}, grid: {{ display: false }} }},
      y: {{ ticks: {{ precision: 0, color: '#95a5a6' }}, grid: {{ color: '#f0f2f5' }} }}
    }}
  }}
}});

const chartData = {chart_json};
const colors = ['#e74c3c','#2980b9','#9b59b6','#16a085','#e67e22','#34495e','#1abc9c','#d35400','#8e44ad'];
const grid = document.getElementById('chartsGrid');
chartData.forEach((c, idx) => {{
  const card = document.createElement('div');
  card.className = 'chart-card';
  card.innerHTML = `
    <h4><span style="color:${{colors[idx%colors.length]}}">●</span> ${{c.name}}</h4>
    <div class="sub">置信度${{c.score}} · 250日位${{c.pos250}}% · 抬底${{c.hl}}% · 周线${{c.wk}}</div>
    <div class="chart-box"><canvas></canvas></div>
  `;
  grid.appendChild(card);
  const ctx = card.querySelector('canvas');
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: c.dates,
      datasets: [{{ data: c.closes, borderColor: colors[idx%colors.length], backgroundColor: colors[idx%colors.length]+'15', borderWidth: 1.8, pointRadius:0, fill:true, tension:0.35 }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{ legend:{{display:false}}, tooltip:{{ callbacks:{{ title:(i)=>c.dates[i[0].dataIndex], label:(i)=>'价格 '+i.parsed.y }}}}}},
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
    results_file = os.path.join(skill_dir, "etf_t2_results.json")
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    outdir = os.path.join(cwd, "reports", "etf")
    os.makedirs(outdir, exist_ok=True)
    output = os.path.join(outdir, "etf_t2_report.html")

    with open(results_file) as f:
        out = json.load(f)
    with open(kline_file) as f:
        klines = json.load(f)
    build_report(out, klines, output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行生成报告**

```bash
/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 .workbuddy/skills/etf-t2-scanner/generate_report.py
```
Expected: `Report saved to reports/etf/etf_t2_report.html`

- [ ] **Step 3: 提取内联JS并做语法检查（AGENTS.md 要求）**

```bash
python3 -c "
import re
html = open('reports/etf/etf_t2_report.html').read()
scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
open('/tmp/_check.js', 'w').write(scripts[-1])
print('extracted', len(scripts[-1]), 'chars')
" && /Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node --check /tmp/_check.js && echo "JS OK"
```
Expected: `extracted N chars` + `JS OK`

- [ ] **Step 4: 报告内容断言**

```bash
/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -c "
import json
html = open('reports/etf/etf_t2_report.html').read()
out = json.load(open('.workbuddy/skills/etf-t2-scanner/etf_t2_results.json'))
t2 = sum(1 for r in out['results'] if r['trend_state']['code'] == 'T2')
assert 'T2底部构建' in html and '风险提示' in html
assert f'{t2}' in html
assert 'distChart' in html and 'chartsGrid' in html
print('OK: report contains', t2, 'T2 entries')
"
```
Expected: `OK: report contains N T2 entries`

- [ ] **Step 5: Commit**

```bash
git add .workbuddy/skills/etf-t2-scanner/generate_report.py reports/etf/etf_t2_report.html
git commit -m "feat(etf-t2-scanner): HTML report generator"
```

---

### Task 5: 端到端验证 + AGENTS.md 更新

**Files:**
- Modify: `AGENTS.md`（Skill Inventory 表 + 关键命令段）

- [ ] **Step 1: 端到端重跑（无 --refresh 的纯本地模式）**

```bash
/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 .workbuddy/skills/etf-t2-scanner/analyze.py && /Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 .workbuddy/skills/etf-t2-scanner/generate_report.py
```
Expected: 两步均成功，无异常栈。

- [ ] **Step 2: 更新 AGENTS.md**

在 AGENTS.md 的 ETF Scanners 段追加：

```markdown
# ETF T2区间 — analyze + generate report (T0-T8状态机, 筛出T2底部构建)
$PYTHON .workbuddy/skills/etf-t2-scanner/analyze.py
$PYTHON .workbuddy/skills/etf-t2-scanner/generate_report.py
```

在 Skill Inventory 表追加一行：

```markdown
| ETF T2区间 | `etf-t2-scanner/` | analyze.py (T0-T8状态机+5维置信度), generate_report.py | 352 ETFs | etf_t2_results.json |
```

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: register etf-t2-scanner in AGENTS.md"
```
