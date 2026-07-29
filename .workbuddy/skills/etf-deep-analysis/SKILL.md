---
name: etf-deep-analysis
description: Deep analysis of an A-share ETF with structured investment recommendations. Produces a professional HTML research report covering ETF timing (bowl-bottom / position-in-range), holdings quality, fund flow sentiment, discount/premium analysis, peer comparison, theme catalysts, and actionable allocation advice. Triggers on requests to deeply analyze a specific ETF, such as "深入分析XXETF", "分析旅游ETF", "XXETF现在什么状态", "帮我看看XXETF能不能买".
---

# ETF Deep Analysis（ETF深度分析）

## Overview

Produce a sell-side quality **single-ETF research report** from a user request like "深入分析旅游ETF富国". The output is a self-contained HTML file with ECharts charts, data tables, and actionable investment recommendations — not a chat reply.

Unlike the **etf-bowl-bottom-scanner** (which batch-scans 352 ETFs for technical patterns only), this skill does a **deep fundamental + technical + flow analysis** on ONE specific ETF, producing a full research report.

## Prerequisites

This skill relies on:
- `westock-data` for ETF price/K-line/quote data
- `WebSearch` for ETF holdings, fund flow, theme news, and catalysts
- Bowl-bottom timing engine (embedded inline — no external Python needed)

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
- Recommended position size (as % of total portfolio)
- Entry strategy (一次性 / 分批 / 定投)
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
3. **ETF snapshot dashboard** — cards: 现价/净值, 折溢价率, 基金规模, 碗底评分/标签, YTD涨跌, 20日/60日涨跌
4. **Technical timing section** — ECharts line chart (250-day K-line with 60MA overlay, markLine at前低, markPoint at current), bowl-bottom score callout
5. **Holdings analysis** — Top 10 holdings table (名称/代码/权重/当日涨跌/20日/60日/YTD) + pie chart (行业分布)
6. **Fund flow chart** — if data available: bar chart of fund size over time; otherwise: discount/premium bar chart
7. **Peer comparison table** — 名称/代码/规模/折溢价/碗底评分/YTD/跟踪指数
8. **Catalyst timeline** — table with 催化事件/类型(hard/soft)/概率/影响/时间窗口
9. **Bull vs Bear** — two-column layout: 多头逻辑 (left, green) vs 空头逻辑 (right, red)
10. **Risk callout** — prominent box: 主要风险 + monitoring signal
11. **配置建议** — explicit recommendation table: 方向/建议/仓位/入场方式/止损/目标/持有期
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
2. Accompany with a concise chat summary: ETF name, bowl-bottom label/score, position in range, key variant perception, recommendation, and one-line risk.
3. Do NOT paste HTML content in chat — point to the file.

## Action Classification

Every analysis conclusion must map to one of:
- **仓位动作**: `买入` | `加仓` | `标配` | `减仓` | `清仓`
- **观察动作**: `观察名单` | `等待确认` | `重新评估` | `放弃`
- **入场策略**: `一次性建仓` | `分批买入` | `定投` | `网格交易`
- **卖研风格**: `超配` | `标配` | `低配` | `左侧` | `回避`

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

- Uses Chinese stock market convention: **red = up (涨)**, **green = down (跌)**.
- ETF analysis is a tool for decision support — **not investment advice**.
- ETF bowl-bottom ≠ underlying index bottom (always check tracking error).
- Data sourced from 腾讯自选股 (westock-data) + public web search; may have delays.
- Re-run regularly to track bowl-bottom progression: 减速筑底 → 确认中 → 确认碗底.
- Fund flow data from web search is lagging (typically updated weekly/monthly).
- For ETFs tracking overseas assets (QDII), consider exchange rate impact.
