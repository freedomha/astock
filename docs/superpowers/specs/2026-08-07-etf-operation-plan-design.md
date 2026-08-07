# ETF Operation Plan Skill — Design Spec

**Date**: 2026-08-07
**Status**: Draft
**Author**: AI-assisted design session

---

## 1. Overview

A new skill (`etf-operation-plan`) that generates **actionable, medium-to-long-term operation plans** for A-share ETFs. The output is a self-contained HTML report saved to `reports/etf/operation/{YYYYMMDD}-{ETF简称}-操作建议.html`.

**Core differentiator from `etf-deep-analysis`**: Focused on the question "what should I do in the next period?" not "what is this ETF's full thesis?". Shorter time horizon (weeks, not months), always anchored to current position data.

## 2. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Execution mode | AI-driven + helper Python script | Flexibility for AI workflow, computational tasks offloaded to script |
| Input source | Both positions (memory/JSON) and arbitrary ETF code | Serves daily portfolio management AND ad-hoc analysis |
| Data freshness | Real-time pull (westock-data + WebSearch) | Operation decisions need the latest data |
| Scoring logic | Inline copy into `score_patterns.py` | Avoids cross-module import complexity across scanner directories |
| Time horizon | Medium-to-long-term (weeks) | User focus: not short-term trading. Scenarios are weekly, not daily |
| Scope | Full coverage converging to operations | Comprehensive analysis, but everything points to actionable decisions |
| Pattern scores | All 5 patterns (bowl, box, W, HS, 2B) | Complete picture of current technical state |
| Multi-ETF | Independent reports per ETF | Each ETF gets its own HTML, no portfolio-level aggregation |

## 3. Architecture

```
├── .codebuddy/skills/etf-operation-plan/
│   ├── SKILL.md                    # AI workflow instructions
│   └── score_patterns.py           # Single-ETF five-pattern scoring
└── reports/etf/operation/
    └── {YYYYMMDD}-{ETF简称}-操作建议.html
```

### Data Flow

```
持仓记录(memory/JSON) ─┐
westock-data quote     ─┤
westock-data kline(250d)─┼──→ score_patterns.py ──┐
WebSearch (news/catalyst)┤                        │
                          └────────────────────────┼──→ HTML Report
                                                   │
                             Position P&L calc ────┘
                             Key level computation
                             Scenario analysis
                             Decision matrix
```

### Helper Script: `score_patterns.py`

```
Input:  --code <etf_code> --kline-file <json_path>
Output: JSON with bowl/box/w_bottom/hs_bottom/2b scores + labels

Internal: Inline copies of scoring functions from:
  - etf-bowl-bottom-scanner/analyze.py   (bowl)
  - etf-box-scanner/analyze.py           (box)
  - etf-w-bottom-scanner/analyze.py      (W-bottom)
  - etf-head-shoulder-bottom-scanner/analyze.py (HS bottom)
  - etf-2b-bottom-scanner/analyze.py     (2B bottom)

Only essential scoring functions are copied, not the full scan pipeline.
All five scores computed in a single run against the same K-line data.
```

## 4. AI Workflow (SKILL.md)

### Step 1: Identify Target ETF(s)
- Read `memory/positions.md` for current holdings → primary targets
- Accept optional user-specified ETF code via conversation
- Resolve code → name from `all_etfs_larggest.json`

### Step 2: Fetch Real-Time Data
```bash
# Quote
$NODE $WD/scripts/index.js quote <code> --raw > /tmp/op_quote.json

# 250-day K-line
$NODE $WD/scripts/index.js kline <code> --period day --limit 250 --raw > /tmp/op_kline.json
```

### Step 3: Run Pattern Scoring
```bash
$PYTHON .workbuddy/skills/etf-operation-plan/score_patterns.py \
  --code <code> --kline-file /tmp/op_kline.json > /tmp/op_scores.json
```

### Step 4: Fetch News & Catalysts
```bash
WebSearch: "<ETF名称> 最新消息 2026"
WebSearch: "<ETF跟踪主题> 政策 催化"
```

### Step 5: Compute Position Metrics
- P&L: (current - cost) × shares
- P&L%: (current / cost - 1) × 100
- Position ratio: P&L amount / total portfolio (if available)

### Step 6: Compute Key Technical Levels
- S1: 60-day low → medium-term support
- S2: 120-day low → long-term support
- R1: 60-day high → medium-term resistance
- R2: 120-day high → long-term resistance
- Hard stop: 52-week low → bottom invalidation
- 60MA: 60-day moving average
- Cost anchor: entry price

Each level: price, distance from current (%), meaning.

### Step 7: Scenario Analysis (Weekly)
| Scenario | Trigger | Probability | Action |
|----------|---------|-------------|--------|
| Bullish | Stands above 60MA + pattern confirming | Estimated from current technicals | Add to target position, raise trailing stop |
| Range-bound | Between S1-R1, no pattern change | Neutral probability | Hold, wait for confirmation |
| Bearish | Breaks hard stop or key support | Estimated from historical vol | Execute stop-loss discipline |

### Step 8: Decision Matrix
| Dimension | Output |
|-----------|--------|
| Direction | Bullish / Neutral / Bearish |
| Core logic | One-line thesis validation |
| Position action | Add / Hold / Reduce / Exit |
| Specific operation | Trigger price + action (e.g., "Add 150 shares if closes above 9.0") |
| Target price | Medium-term (1-3 month) target + logic |
| Next review | When/under what conditions to re-evaluate |

### Step 9: Risk Monitor
3-5 high-priority watch signals with:
- Current status
- Danger threshold
- Triggered action

### Step 10: Generate HTML Report
Save to `reports/etf/operation/{YYYYMMDD}-{ETF简称}-操作建议.html`.

Use two-phase f-string approach:
1. Pre-compute all data as Python variables
2. Build HTML with f-string template

JS syntax check before delivery: `node --check /tmp/_op_check.js`

## 5. HTML Report Structure

### Section 1: Position Snapshot Card
- Cost / Current price / P&L / P&L% / Position ratio
- Visual: color-coded P&L display (red = profit, green = loss)

### Section 2: Key Technical Levels
- Table: S1, S2, R1, R2, Hard Stop, 60MA, Cost Anchor
- Each: price, distance from current (%), meaning interpretation
- Optional: mini chart with horizontal lines marking these levels

### Section 3: Pattern Assessment
- Table: 5 patterns (bowl, box, W, HS, 2B) with scores and labels
- Highlight the most relevant pattern for the current situation

### Section 4: Scenario Analysis
- Three scenarios (bullish/range-bound/bearish) in card layout
- Each: trigger conditions, probability (qualitative), specific action
- Color-coded: green tint for bullish, neutral for range, red tint for bearish

### Section 5: News & Catalysts
- Table: news item, type (hard/soft/risk), impact, timeframe
- Only items with meaningful impact are included
- If no relevant news: "当前无重大催化，技术面为主要决策依据"

### Section 6: Decision Matrix
- Table: direction, core logic, position action, specific operation, target, next review
- Bold and prominent — this is the core deliverable

### Section 7: Risk Monitor
- Table: signal, current status, danger threshold, triggered action
- 3-5 items max
- Color-coded urgency levels

### Section 8: Disclaimer
- Data sources
- "不构成投资建议"
- Data timestamp

### Style Rules
- A-share convention: red = up (涨), green = down (跌)
- Light background, gradient header in theme color
- ECharts for any charts (K-line with level overlays)
- HTML tables for structured data
- Sell-side tags: 买入/加仓/标配/减仓/清仓
- Section numbering: 一、二、三、...

## 6. File Structure

```
.codebuddy/skills/etf-operation-plan/
├── SKILL.md                          # AI workflow instructions (~200 lines)
└── score_patterns.py                 # Five-pattern single-ETF scorer (~400 lines)

reports/etf/operation/
└── {YYYYMMDD}-{ETF简称}-操作建议.html  # Generated reports
```

## 7. SKILL.md Frontmatter

```yaml
---
name: etf-operation-plan
description: Generate a medium-to-long-term operation plan for A-share ETFs
  based on current positions, real-time market data, technical patterns,
  and market news. Outputs a focused HTML report answering "what to do
  in the next period" with specific price levels and scenarios.
  Triggers on requests like "下个交易日怎么操作", "帮我做操作计划",
  "XXETF接下来怎么办", "看看持仓怎么做".
---
```

## 8. Open Questions

None — all design decisions confirmed during brainstorming session.

## 9. Implementation Plan

The implementation will be driven by the `writing-plans` skill after user review of this spec.

Key implementation tasks:
1. Create `.codebuddy/skills/etf-operation-plan/` directory
2. Write `SKILL.md` with the 10-step AI workflow
3. Write `score_patterns.py` — inline copies of scoring functions from 5 existing analyzers
4. Create `reports/etf/operation/` directory
5. Test with a real ETF (黄金ETF华安 518880) to validate end-to-end flow
