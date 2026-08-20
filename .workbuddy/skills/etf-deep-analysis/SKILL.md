---
name: etf-deep-analysis
description: Deep analysis of an A-share ETF with structured investment recommendations. Produces a professional HTML research report covering ETF timing (bowl-bottom / position-in-range), holdings quality, fund flow sentiment, discount/premium analysis, peer comparison, theme catalysts, and actionable allocation advice with a position-building protocol (建仓协议): trend-state pre-gate (T0-T8 from etf-operation-plan, T0/T1 blocks new positions), preconditions, action mapping, staged entry plan, and position conclusion matrix. Triggers on requests to deeply analyze a specific ETF, such as "深入分析XXETF", "分析旅游ETF", "XXETF现在什么状态", "帮我看看XXETF能不能买".
---

# ETF Deep Analysis（ETF深度分析）

## Overview

Produce a sell-side quality **single-ETF research report** from a user request like "深入分析旅游ETF富国". The output is a self-contained HTML file with ECharts charts, data tables, and actionable investment recommendations — not a chat reply.

Unlike the **etf-bowl-bottom-scanner** (which batch-scans 352 ETFs for technical patterns only), this skill does a **deep fundamental + technical + flow analysis** on ONE specific ETF, producing a full research report.

**建仓结论受趋势状态门控（PRIMARY）**：任何 建仓/加仓 结论必须先跑 `etf-operation-plan` 的趋势状态机 `trend_analysis.py`（T0–T8，含子态）。**T0/T1 一律降级为「等待确认」**——碗底评分再高也禁止左侧试仓/建仓/加仓，与 etf-operation-plan 硬约束矩阵保持一致（形态分不可覆盖趋势状态）。

## Prerequisites

This skill relies on:
- `westock-data` for ETF price/K-line/quote data
- `WebSearch` for ETF holdings, fund flow, theme news, and catalysts
- Bowl-bottom timing engine (embedded inline — no external Python needed)
- `trend_analysis.py` (bundled with `etf-operation-plan` skill) — T0-T8 trend-state machine, **建仓前置门（PRIMARY）**

Data sources priority: **westock-data first**, `WebSearch` as fallback for data westock-data doesn't provide (holdings, fund flow, news).

## Workflow

### Step 1: Identify the ETF

Search for the target ETF in `all_etfs_larggest.json` (located at `.workbuddy/skills/etf-bowl-bottom-scanner/all_etfs_larggest.json` or project root). Match by name keyword (case-insensitive partial match).

If the ETF is found, extract: `code`, `name`, `size` (net asset value), `totalMV` (total market value).

```python
import json
with open('.workbuddy/skills/etf-bowl-bottom-scanner/all_etfs_larggest.json') as f:
    etfs = json.load(f)
target = [e for e in etfs if '<keyword>' in e['name']]
```

If NOT found in the JSON, use WebSearch: `<ETF名称> ETF代码` to find the code.

### Step 2: Fetch ETF Market Data

Use westock-data to get the ETF's price and K-line history.

```bash
WD="/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data"
NODE="/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"

# (a) ETF current quote
$NODE $WD/scripts/index.js quote <etf_code> --raw > /tmp/etf_quote.json

# (b) ETF 250-day K-line
$NODE $WD/scripts/index.js kline <etf_code> --period day --limit 250 --raw > /tmp/etf_kline.json
```

**Quote→ETF-specific fields to extract** (from the raw JSON, see references for parsing):
- `last` / `current` — latest price (现价)
- `nav` — net asset value (净值, if available; some ETFs report this)
- `volume` — trading volume
- `amount` — trading amount (成交额)
- `turnover_rate` — turnover rate (换手率)
- `amplitude` — intraday amplitude (振幅)
- `changePct` — daily change %
- `high52w` / `low52w` — 52-week range

**K-line parsing** (newest-first, `last` is close price):
```python
import json, sys
raw = json.load(open('/tmp/etf_kline.json'))
bars = raw if isinstance(raw, list) else raw.get('data', raw.get('klines', []))
bars.sort(key=lambda b: b.get('date',''))  # oldest-first for analysis
closes = [float(b['last']) for b in bars]
volumes = [float(b.get('volume', 0)) for b in bars]
```

### Step 3: Compute ETF Timing (Bowl-Bottom / Position-in-Range)

Apply the bowl-bottom scoring engine from `etf-bowl-bottom-scanner` **inline** (use Python via Bash, not a separate script). This is the technical foundation of the analysis.

**Core metrics to compute:**

| Metric | Formula | Threshold |
|--------|---------|-----------|
| **pos120** | (close - 120d_low) / (120d_high - 120d_low) × 100 | ≤20% = bottom zone; ≤10% = extreme bottom |
| **pos250** | (close - 250d_low) / (250d_high - 250d_low) × 100 | ≤25% = bottom zone |
| **decel_ratio** | abs(20d_return) / max(abs(40d_return/2), 0.01) | <0.8 = stabilized; <1.0 = decelerating; >1 = accelerating down |
| **higher_low** | (10d_recent_low - 10d_prior_low) / 10d_prior_low × 100 | >0 = higher low forming |
| **trend_20d** | linreg slope over last 20 closes × 20 / mean × 100 | % change over 20d |
| **trend_60d** | linreg slope over last 60 closes × 60 / mean × 100 | % change over 60d |
| **drawdown_120d** | (close - 120d_high) / 120d_high × 100 | > -5% = near highs (penalty) |
| **below_60ma** | (close - 60d_ma) / 60d_ma × 100 | -12% to -2% = bottom zone |
| **vol_contraction** | avg_vol_20d / avg_vol_60d | <0.7 = volume drying up (basing) |
| **atr_compression** | atr_20d / atr_60d | <0.7 = volatility compressing |

**Scoring (max 100):**

| Dimension | Max | Criteria |
|-----------|-----|----------|
| 120-day position | 25 | ≤10%=25, ≤20%=20, ≤30%=12 |
| 250-day position | 20 | ≤15%=20, ≤25%=15, ≤35%=8 |
| Bowl shape (decel + stabilize) | 20 | decel<0.8 & flat=20; decel<1.0=14 |
| Higher-low bonus | 5 | raised >0.5%=5 |
| U-shape curvature (quadratic fit on 120d closes) | 10 | convex (a>0) + vertex in recent third=10 |
| Volume contraction (20d/60d) | 8 | <0.7=8, <0.85=5 |
| Volatility compression (ATR) | 7 | <0.7=7, <0.85=5 |
| Below 60MA | 10 | -12% to -2%=10 |

**Penalties:** recent crash (20d < -8%) = -15pts; near highs (drawdown > -5%) = -20pts.

**Label grading:**

| Label | Criteria |
|-------|----------|
| 🟢 确认碗底 | bottom zone + decel<0.8 + higher_low + score≥65 |
| 🟢 碗底确认中 | bottom zone + (stabilized OR decel+higher_low) + score≥58 |
| 🟡 减速筑底 | bottom zone + decel<1.0 + score≥50 |
| 🟡 低位盘整 | bottom zone + flat 20d |
| 🔴 下跌中继 | trend_20d < -6% |
| ⚪ 观望 | otherwise |

**Trend-State Gate（趋势前置门，建仓必检，PRIMARY）**

碗底评分只是辅助层，不可单独决定建仓。给出任何 建仓/加仓 结论前，必须用 Step 2 已抓取的 K 线运行 `etf-operation-plan` 的趋势状态机（**只读状态历史，不加 `--save-state`，不回写**）：

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
STATE=".workbuddy/skills/etf-operation-plan/trend_state_history.json"
$PYTHON .workbuddy/skills/etf-operation-plan/trend_analysis.py \
  --code <etf_code> --kline-file /tmp/etf_kline.json \
  --state-file $STATE > /tmp/etf_trend.json
# 盘中数据加 --intraday
```

提取：`state_machine.effective_state`（无 `state_machine` 时用 `trend_state.code`）、`effective_sub_state`（或 `sub_state`）、`data_quality`。门控规则：

| 趋势状态 | 建仓结论约束 |
|---|---|
| T0 / T1 | **一律降级为「等待确认」**：禁止左侧试仓/建仓/加仓/摊低成本，无论碗底评分多高 |
| T2 | 观察名单，至多小额试仓（不重仓抄底） |
| T3a | 等待回踩确认，不建议积极建仓 |
| T3b / T4 / T5 | 可按评分走建仓动作分层（仍需过其余前置门） |
| T6 / T7 | 不新增，只持有/减仓 |
| T8 | 禁止新增，建议降低/退出 |

碗底评分与趋势状态冲突时（如 bowl 72 分但状态 T0），**以趋势状态为准**；碗底评分只用于「等待确认后，谁的左侧布局优先级更高」的辅助排序。

**例外模式（默认不启用）**：如需在 T0/T1 输出左侧建仓，必须显式声明三项——例外原因、最大风险预算（占组合 %）、退出条件，并在报告中标注「例外模式」。未显式声明时一律按门控规则降级。

### Step 4: Get ETF Holdings & Underlying Structure

ETF holdings are NOT available from westock-data — use **WebSearch**.

**Search queries (run in parallel):**

```
WebSearch: "<ETF名称> 前十大重仓股 2026"
WebSearch: "<ETF名称> 跟踪指数 成分股"
WebSearch: "<ETF名称> 行业分布 配置"
```

Extract:
- **Tracking index**: What index does this ETF track? (e.g., 中证旅游主题指数)
- **Top 10 holdings**: Stock names, codes, weight %
- **Sector allocation**: Industry breakdown of the portfolio
- **Concentration**: Top 5 weight sum (high concentration = high single-stock risk)
- **Number of holdings**: Total stocks in the portfolio

**For each top holding (5-8 stocks)**, fetch quote data to assess the ETF's underlying quality:

```bash
$NODE $WD/scripts/index.js quote <stock_codes_comma_separated> --raw > /tmp/holdings_quote.json
```

### Step 5: Get Fund Flow & Scale Data

ETF fund flow data is NOT available from westock-data — use **WebSearch**.

```
WebSearch: "<ETF名称> 基金规模 份额变化 2026"
WebSearch: "<ETF名称> 资金流向 净申购"
```

Extract:
- **Current fund size** (total net asset value, 基金规模)
- **Share outstanding trend**: growing (net inflows) or shrinking (net outflows)?

Also compute discount/premium from Step 2 data: `(price - nav) / nav × 100`
- Discount < -1% = ETF trading below NAV (potential value signal)
- Premium > 1% = ETF trading above NAV (overbought)
- |discount| < 1% = fair price (efficient market making)

### Step 6: Peer Comparison

Find similar ETFs in the same theme/sector for comparison. Search `all_etfs_larggest.json` for ETFs with related names or track the same/similar index.

```python
peers = [e for e in etfs if any(kw in e['name'] for kw in related_keywords)]
```

For each peer, fetch:
- Current price and YTD performance via westock-data `quote`
- Fund size comparison (from JSON)
- Key differentiating feature (expense ratio, tracking index, fund manager)

### Step 7: Get Theme Catalysts & News

Use WebSearch for theme-specific catalysts (westock-data doesn't have news).

```
WebSearch: "<ETF主题/板块> 政策 催化 2026"
WebSearch: "<ETF名称> 新闻 利好"
WebSearch: "<前十大重仓股中龙头> 业绩 2026"
```

Classify each catalyst:
- **Hard catalyst**: Policy documents, earnings revisions, contract wins, price changes (tangible)
- **Soft catalyst**: Sentiment, analyst upgrades, concept rotation, overseas mapping (less reliable)
- **Risk event**: Regulatory risk, macro headwind, sector headwind

### Step 8: Apply ETF Analysis Framework (7-Layer)

Apply this framework **inline** — no external reference needed. Every layer must produce a concrete conclusion, not a description.

**Layer 1 — Core Logic (核心逻辑):**
What is the investment thesis for this ETF?
- What theme/sector does it represent?
- What macro cycle is it riding?
- What is the market's current narrative? Is it correct?
- **Variant perception is mandatory**: What is the market mispricing about this ETF/theme?

**Layer 2 — Trading Position (交易位置):**
Use Step 3 results. Classify as one of: 极低位 / 低位企稳 / 左侧买点 / 启动确认 / 主升 / 拥挤 / 回撤修复.

**Layer 3 — Holdings Quality (持仓质量):**
Evaluate the top holdings:
- Are they leaders or laggards in their sub-sectors?
- What's the earnings trajectory (from quote chg_20d/60d/YTD)?
- Is the portfolio concentrated or diversified?
- Any single-stock risk (>15% weight)?

**Layer 4 — Fund Flow Sentiment (资金流向):**
- Is the ETF seeing net inflows or outflows?
- Is fund size growing (smart money) or shrinking (retail capitulation)?
- Counter-flow opportunity: large outflows + bottoming technicals = contrarian signal

**Layer 5 — Valuation & Discount/Premium (估值与折溢价):**
- Is the ETF trading at a discount or premium to NAV?
- What's the valuation of the underlying index/basket?
- Historical context: is current pricing extreme vs. history?

**Layer 6 — Catalyst Intensity (催化强度):**
Rank catalysts from Step 7 by:
- Probability of occurrence (high/medium/low)
- Impact if realized (large/medium/small)
- Timeline (immediate / 1-3 months / 3-6 months)

**Layer 7 — Explicit Recommendation (明确建议):**
One of: **买入/加仓** | **持有/标配** | **观察/等待** | **减仓/回避**

Must include:
- Trend state (T0-T8 + 子态) from the trend gate — 买入/加仓 requires T3b or above (T2 at most 小额试仓)
- Recommended position size (as % of total portfolio)
- Entry strategy — apply the **Position Building Protocol** (建仓协议) below: run preconditions → map score to action → output staged entry plan
- Stop-loss level
- Target return and holding period
- Key risk to monitor that would invalidate the thesis

### Step 9: Produce HTML Report

Write a self-contained HTML file to `reports/etf/`: `<ETF简称>ETF深度分析-YYYYMMDD.html` (create the directory if it doesn't exist).

**Critical: HTML generation methodology.** Do NOT attempt to embed Python code inside a triple-quoted HTML string by closing/reopening the string — Python `print()` output goes to stdout, not back into the string variable. Use a **two-phase f-string approach** instead:

**Phase 1** — Pre-compute all dynamic data as Python variables. This includes:
- K-line data as JSON arrays (`json.dumps([[date, close, close, close, close], ...])`)
- 60MA values as JSON arrays
- High/low boundaries for chart axes
- All metric values (pos120, score, label, etc.)

**Phase 2** — Build the HTML as an f-string (triple-quoted with `f'''...'''`). Use `{{` / `}}` to escape literal curly braces in CSS and JS, and `{var}` to insert pre-computed values.

```python
import json

# Phase 1: pre-compute all data
with open('/tmp/etf_kline.json') as f:
    data = json.load(f)
bars = data if isinstance(data, list) else data.get('data', [])
bars.sort(key=lambda b: b.get('date',''))
closes = [float(b['last']) for b in bars]
dates = [b['date'] for b in bars]
h250 = max(float(b['high']) for b in bars)
l250 = min(float(b['low']) for b in bars)
close = closes[-1]

ma60_vals = [
    round(sum(closes[i-59:i+1])/60, 3) if i >= 59 else None
    for i in range(len(closes))
]
kline_js = json.dumps([[d, c, c, c, c] for d, c in zip(dates, closes)])
ma_js = json.dumps(ma60_vals)

# Phase 2: f-string template with {{escaped}} curly braces
html = f'''<!DOCTYPE html>
<html>
...
<style>
.card{{background:#fff;}} /* {{ }} become literal { } in the output */
</style>
<script>
var rawData = {kline_js};   /* pre-computed value inserted here */
var maData = {ma_js};
var markLine = {{yAxis: {l250}}};
var option = {{
  yAxis: {{min: {round(l250*0.98,2)}, max: {round(h250*1.02,2)}}}
}};
</script>
</html>'''

import os
os.makedirs('reports/etf', exist_ok=True)
with open('reports/etf/XXXETF深度分析-YYYYMMDD.html', 'w', encoding='utf-8') as f:
    f.write(html)
```

**Template escaping rules in f-strings:**
- `{{` → literal `{` in output (for CSS selectors: `.card{{...}}`)
- `{var}` → Python variable value
- `{{b}}` → literal `{b}` in output (for JS template strings)
- `{{function(v) {{ return v.slice(5); }}}}` → JS arrow function in output

**HTML Structure** (sell-side ETF report style):

**HTML Structure** (sell-side ETF report style):

1. **Header** — ETF name, code, date, rating badge (买入/标配/观察/回避)
2. **TL;DR conclusion card** — 3-5 sentence verdict, variant perception bolded
3. **ETF snapshot dashboard** — cards: 现价/净值, 折溢价率, 基金规模, 趋势状态(T0-T8+子态), 碗底评分/标签, YTD涨跌, 20日/60日涨跌
4. **Technical timing section** — ECharts line chart (250-day K-line with 60MA overlay, markLine at前低, markPoint at current), bowl-bottom score callout, trend-state gate result (T0-T8 + 子态 + 建仓门控结论)
5. **Holdings analysis** — Top 10 holdings table (名称/代码/权重/当日涨跌/20日/60日/YTD) + pie chart (行业分布)
6. **Fund flow chart** — if data available: bar chart of fund size over time; otherwise: discount/premium bar chart
7. **Peer comparison table** — 名称/代码/规模/折溢价/碗底评分/YTD/跟踪指数
8. **Catalyst timeline** — table with 催化事件/类型(hard/soft)/概率/影响/时间窗口
9. **Bull vs Bear** — two-column layout: 多头逻辑 (left, green) vs 空头逻辑 (right, red)
10. **Risk callout** — prominent box: 主要风险 + monitoring signal
11. **配置建议** — explicit recommendation table: 方向/建议/仓位/入场方式/止损/目标/持有期 + **建仓结论矩阵** (Position Conclusion Matrix)
12. **免责声明** — sources + 不构成投资建议 + 数据截止时间

**Style rules:**
- Light background, gradient header in theme-appropriate color
- 红涨绿跌: `.up` / `.pos` = red for涨, `.down` / `.neg` = green for跌
- ECharts for data charts, HTML tables for lookup data
- Sell-side style tags: `<span class="tag tag-buy">买入</span>`, `<span class="tag tag-hold">标配</span>`
- Section numbering: 一、二、三、...

**JS syntax check (mandatory before delivery):**
```bash
# Extract inline <script> from HTML, save to temp .js, then:
node --check /tmp/_etf_check.js
# Must pass with zero errors before presenting to user
```

### Step 10: Present Report

1. Present the HTML file path to the user as the final deliverable.
2. Accompany with a concise chat summary: ETF name, trend state (T0-T8 + 子态), bowl-bottom label/score, position in range, key variant perception, recommendation, and one-line risk.
3. Do NOT paste HTML content in chat — point to the file.

## Action Classification

Every analysis conclusion must map to one of:
- **仓位动作**: `买入` | `加仓` | `标配` | `减仓` | `清仓`
- **观察动作**: `观察名单` | `等待确认` | `重新评估` | `放弃`
- **入场策略**: `一次性建仓` | `分批买入` | `定投` | `网格交易`
- **卖研风格**: `超配` | `标配` | `低配` | `左侧` | `回避`

## Position Building Protocol（建仓协议）

This protocol upgrades the report from a research document to an actionable **建仓操作手册**. Every 建仓/加仓 recommendation must pass the trend-state gate (T0/T1 → 等待确认), the preconditions, map to a position action, output a staged entry plan, and include the 建仓结论矩阵.

### Position Building Preconditions（建仓前置过滤器）

Before giving any 建仓/加仓 recommendation, check the following **hard gates**. If ANY gate fails, the default action is `观察`/`回避` unless explicitly overridden:

1. **Equity ETF only** — Must be an equity ETF (股票型/主题型/行业型). Skip 建仓 analysis for money market ETFs (银华日利等) and bond ETFs.
2. **Trend-state gate (趋势前置门，PRIMARY)** — 必须先跑 `trend_analysis.py`（见 Step 3 Trend-State Gate）。T0/T1 → 建仓结论一律降级为「等待确认」；T8 → 禁止新增。趋势门优先于碗底评分，不可被高分覆盖。例外模式默认不启用。
3. **Fund size > 500M preferred** — Institutional-grade size (> 500M RMB) preferred. (衔接 基金规模风险 section)
4. **Size < 100M → 观察/回避** — If fund size < 100M RMB, default action = 观察/回避 unless liquidity is explicitly acceptable (e.g., small size but high daily turnover).
5. **Liquidity sufficiency** — Average daily turnover amount (日均成交额) must be sufficient for the user's intended position. Rule of thumb: intended position ≤ 10% of average daily turnover; otherwise reduce the position or wait.
6. **NAV availability** — NAV or a reliable proxy (IOPV / underlying index level) must be available for discount/premium calculation. If unavailable, the discount/premium analysis is downgraded to qualitative only.
7. **K-line integrity** — If K-line data is incomplete or cannot be parsed reliably, the recommendation must be downgraded to `观察`.
8. **ETF-specific weakness check** — If the ETF is near its 250-day low but the underlying index is NOT, mark as **ETF-specific weakness** (fund flow, tracking error, dividend withholding), NOT a sector-bottom opportunity. (衔接 Tracking Error section)

### Position Action Mapping（建仓动作分层）

Map the bowl-bottom score + hard overrides to a concrete position action:

| Score | Position Action |
|-------|-----------------|
| < 50 | 观察/不建仓 |
| 50–58 | 加入观察名单，仅允许小额试仓或等待确认 |
| 58–65 | 左侧试仓，建议 1%–3% |
| 65–75 | 分批建仓，建议 3%–5% |
| > 75 | 可加到标准仓位，但仍需结合资金流和催化确认 |

**Hard overrides (override the score-based action):**
- If trend state is **T0/T1** (from `trend_analysis.py`) → override to **等待确认**（左侧建仓禁止；趋势门优先于任何碗底评分）
- If trend state is **T8** → override to **减仓/回避**（禁止新增）
- If `trend_20d < -6%` → override to **等待确认** (下跌中继)
- If `drawdown_120d > -5%` → **prohibit new position** unless the catalyst is strong (near highs)
- If fund size < 100M → override to **回避** or **观察**
- If any Precondition gate fails → **观察/回避**

### Entry Plan（分批买入规则）

For any 建仓 recommendation, always output a staged entry plan:

- **First tranche (首仓)**: 30%–40% of the planned ETF allocation
- **Second tranche (第二笔)**: after price stabilizes above the 20MA or a higher low is confirmed
- **Third tranche (第三笔)**: after 60MA reclaim or catalyst confirmation
- **Stop adding (停止加仓)**: if price breaks the prior low with volume expansion, or complete-week trend state migrates to T0/T8
- **一次性建仓** is only allowed when: score is high (>75), liquidity is strong, AND the catalyst is near-term. Never recommend 一次性建仓 by default.

### Position Conclusion Matrix（建仓结论矩阵）

Every report must include this table in the 配置建议 section:

| 项目 | 结论 |
|------|------|
| 是否适合建仓 | 是 / 否 / 等待 |
| 趋势状态 | T0-T8（含子态）；T0/T1 = 等待确认、T8 = 禁止新增 |
| 建仓类型 | 左侧试仓 / 分批建仓 / 右侧确认 / 不建仓 |
| 建议首仓 | x% |
| 计划总仓位 | x% |
| 加仓触发 | 条件 A、B、C |
| 停止加仓 | 条件 A、B、C |
| 止损条件 | 价格 / 逻辑 / 结构 |
| 复盘频率 | 每周 / 每月 |
| 结论可信度 | 高 / 中 / 低 |

## ETF-Specific Considerations

### Discount/Premium Analysis
ETFs can trade away from NAV. Key thresholds:
- **Discount > 2%**: Potential value opportunity (buy ETF at discount to underlying)
- **Premium > 2%**: Overbought signal (paying above NAV)
- **Persistent premium**: May indicate strong demand + limited creation mechanism
- **Persistent discount**: May indicate structural issues (low liquidity, high tracking error)

### Tracking Error
If the ETF is near its 250-day low but the underlying index is NOT, the ETF is cheap for ETF-specific reasons (low liquidity, dividend withholding, etc.) — not a sector-bottom signal.

### Fund Size Risk
- **Size < 100M RMB**: Liquidity risk, wide bid-ask spread, potential delisting
- **Size 100M–500M**: Medium risk, monitor
- **Size > 500M**: Healthy, institutional-grade

### Money Market / Bond ETFs
Skip bowl-bottom analysis for money market ETFs (银华日利, etc.) and bond ETFs — the framework is designed for equity ETFs.

## Troubleshooting

### trend_analysis.py fails or returns error
If the trend-state script fails or returns `{"error": "insufficient kline data"}`, treat the trend gate as **not passed**: downgrade any 建仓/加仓 recommendation to 「等待确认」 and note the data limitation in the report.

### quote command returns empty `[]`
The `quote --raw` command may return `[]` for some ETF codes. **Fallback:** use `kline --limit 1` to get the latest bar which contains `last` (close), `open`, `high`, `low`, `volume`, `amount`. This is reliable for all ETF codes.

```bash
$NODE $WD/scripts/index.js kline <code> --period day --limit 1 --raw
```

Similarly, for holding stock quotes: if `quote` returns empty data fields, use `kline --limit 1` per stock instead.

### HTML report has broken/missing <script> tags
This happens when attempting to embed Python code inside a triple-quoted HTML string using `print()`. `print()` writes to stdout, not into the string variable. Always use the two-phase f-string approach described in Step 9.

### Multiple ETFs in one request
The skill is designed for single-ETF analysis. If the user asks for multiple ETFs (e.g., "分析A和B"), process them **sequentially** — complete Step 1–9 for the first ETF, then the second. Web searches can be parallelized across both ETFs in Step 4-7 to save time.

### Report output directory
All reports must be saved to `reports/etf/`. Create the directory if it doesn't exist. This keeps the project root clean.

## Important Notes

- **趋势门是建仓结论的硬前置**：必须先跑 `trend_analysis.py`，T0/T1 → 一律降级「等待确认」、T8 → 禁止新增；碗底评分不可覆盖趋势状态（与 etf-operation-plan 硬约束矩阵一致）。
- Uses Chinese stock market convention: **red = up (涨)**, **green = down (跌)**.
- ETF analysis is a tool for decision support — **not investment advice**.
- ETF bowl-bottom ≠ underlying index bottom (always check tracking error).
- Data sourced from 腾讯自选股 (westock-data) + public web search; may have delays.
- Re-run regularly to track bowl-bottom progression: 减速筑底 → 确认中 → 确认碗底.
- Fund flow data from web search is lagging (typically updated weekly/monthly).
- For ETFs tracking overseas assets (QDII), consider exchange rate impact.
