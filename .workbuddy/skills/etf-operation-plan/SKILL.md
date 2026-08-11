---
name: etf-operation-plan
description: Generate a medium-to-long-term operation plan for A-share ETFs based on current positions, real-time market data, technical patterns, and market news. Outputs a focused HTML report answering "what to do in the next period" with specific price levels and scenario analysis. Triggers on requests like "下个交易日怎么操作", "帮我做操作计划", "XXETF接下来怎么办", "看看持仓怎么做".
---

# ETF Operation Plan（ETF操作计划）

## Overview

Generate an actionable medium-to-long-term operation plan for A-share ETFs. Unlike `etf-deep-analysis` (which produces a comprehensive thesis-driven research report), this skill focuses on the **"what should I do now?"** question, anchored to current position data.

**Output:** `reports/etf/operation/{YYYYMMDD}-{ETF简称}-操作建议.html`

## Prerequisites

- `westock-data` for ETF price/K-line data
- `score_patterns.py` (bundled with this skill) for five-pattern technical scoring
- `WebSearch` for market news and catalysts

## Quick Start

```bash
WD="/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data"
NODE="/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"

# Step 1: Identify target ETF(s) from memory/positions.md or user input

# Step 2: Fetch real-time data
$NODE $WD/scripts/index.js quote <code> --raw > /tmp/op_quote.json
$NODE $WD/scripts/index.js kline <code> --period day --limit 250 --raw > /tmp/op_kline.json

# Step 3: Run pattern scoring
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py \
  --code <code> --kline-file /tmp/op_kline.json > /tmp/op_scores.json

# Step 4: WebSearch for news/catalysts (run in parallel)
# WebSearch: "<ETF名称> 最新消息 2026"
# WebSearch: "<ETF跟踪主题/标的> 政策 催化"

# Step 5-9: Compute position metrics, key levels, scenarios, decision, risk
# Step 10: Generate HTML → reports/etf/operation/
# Step 11: Present report path to user
```

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

# Current quote (use dangerouslyDisableSandbox: true)
$NODE $WD/scripts/index.js quote <code> --raw > /tmp/op_quote.json

# 250-day K-line (fresh fetch each run — no stale cache issue)
$NODE $WD/scripts/index.js kline <code> --period day --limit 250 --raw > /tmp/op_kline.json
```

**Data timing**: K-line is fetched fresh each run (no persistent cache). If run during market hours (9:30-15:00 Beijing time), today's bar is intraday (盘中) data — OHLCV only reflects partial session. For full post-close (收盘) data, run after 15:00.

Quote fields to extract (from BatchResult wrapper): `price`, `prev_close`, `high`, `low`, `volume`, `amount`, `change_percent`, `chg_5d`, `chg_20d`, `chg_60d`, `chg_ytd`, `high_52week`, `low_52week`, `wb_ratio`

### Step 3: Run Pattern Scoring

```bash
$PYTHON .codebuddy/skills/etf-operation-plan/score_patterns.py \
  --code <code> --kline-file /tmp/op_kline.json > /tmp/op_scores.json
```

Extract `bowl`, `box`, `w_bottom`, `hs_bottom`, `2b` scores and labels from the JSON output.

### Step 4: Fetch News & Catalysts

Run WebSearch in parallel (use AskUserQuestion or Agent tool as needed):

```
WebSearch: "<ETF名称> 最新消息 2026"
WebSearch: "<ETF跟踪主题/标的> 政策 催化 2026"
```

Classify each result:
- **硬催化**: Price movements, policy documents, earnings revisions — tangible, quantifiable
- **软催化**: Analyst opinions, sentiment shifts, concept rotation — reference only
- **风险事件**: Regulatory risks, macro headwinds, sector headwinds

If no meaningful news found, note: "当前无重大催化，技术面为主要决策依据"

### Step 5: Compute Position Metrics

From `memory/positions.md` or user-provided position data:
- Entry price, shares, cost
- P&L = (current - cost) * shares
- P&L% = (current / cost - 1) * 100

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
import json
with open('/tmp/op_kline.json') as f:
    bars = json.load(f)
bars.sort(key=lambda b: b.get('date', ''))
closes = [float(b['last']) for b in bars]
highs_all = [float(b['high']) for b in bars]
lows_all = [float(b['low']) for b in bars]

n = len(closes)
current = closes[-1]

s1 = min(lows_all[-60:])
s2 = min(lows_all[-120:])
r1 = max(highs_all[-60:])
r2 = max(highs_all[-120:])
ma60 = sum(closes[-60:]) / 60
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

Use two-phase f-string approach:
1. Pre-compute all dynamic data as Python variables
2. Build HTML with f-string template (use `{{` / `}}` for literal braces in CSS/JS)

**HTML Structure:**

1. **Header** — ETF name, code, date
2. **一、持仓速览卡片** — Cost/Current/P&L/P&L%, color-coded
3. **二、技术关键位** — Table of S1/S2/R1/R2/Hard Stop/60MA/Cost Anchor, with distance from current (%)
4. **三、形态速评** — Five-pattern score table, highlight most relevant pattern
5. **四、场景推演** — Three scenario cards (bullish/range/bearish): trigger conditions, probability, specific action
6. **五、消息面速览** — News table: item, type (硬催化/软催化/风险事件), impact, timeframe. If none: "当前无重大催化"
7. **六、综合决策矩阵** — Decision table (bold, prominent): direction/logic/action/operation/target/next review
8. **七、风险监控** — Watch signals table: signal/current/threshold/triggered action
9. **八、免责声明** — Data sources, "不构成投资建议", data timestamp

**Style Rules:**
- A-share convention: red = up (涨), green = down (跌) — `.up {color: #c0392b}`, `.down {color: #27ae60}`
- Light background (`#f5f7fa`), gradient header in ETF-appropriate color
- ECharts CDN for any charts
- HTML tables for structured data
- Sell-side tags: `<span class="tag tag-buy">买入</span>`, `<span class="tag tag-hold">标配</span>`
- Section numbering: 一、二、三、...

**JS syntax check (mandatory before delivery):**
```bash
# Extract <script> blocks, save to temp .js, then:
node --check /tmp/_op_check.js
# Must pass with zero errors before presenting to user
```

### Step 11: Present Report

1. Present file path as deliverable
2. Chat summary: ETF name, pattern status, direction, specific operation
3. Do NOT paste HTML content in chat

## Multi-ETF Handling

For multiple ETFs (e.g., both positions, or user specifies several):
- Process sequentially through Steps 2-10 for each ETF
- Data fetching (Step 2) and news search (Step 4) can be parallelized across ETFs
- Each ETF gets its own HTML report at `reports/etf/operation/{YYYYMMDD}-{ETF简称}-操作建议.html`

## Important Notes

- Uses Chinese stock market convention: red = up (涨), green = down (跌)
- Not investment advice — tool for decision support
- Data sourced from 腾讯自选股 (westock-data) + web search
- Medium-to-long-term focus: weekly scenarios, not daily predictions
- Re-run weekly or when significant market events occur
- westock-data must use `dangerouslyDisableSandbox: true` in Bash calls
- **Data freshness**: Unlike batch scanners, this skill fetches kline data fresh each run (no caching). Today's bar is intraday (盘中) during 9:30-15:00, post-close (收盘) after 15:00. For most accurate analysis, run after market close.
