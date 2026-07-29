---
name: sector-deep-analysis
description: Deep analysis of an A-share investment sector with structured investment recommendations. Produces a professional HTML research report covering macro context, sector structure, sector-index timing (bowl-bottom / position-in-range), key company financials, institutional consensus & ratings, research reports, policy catalysts, valuation comparison, and actionable allocation advice. Triggers on requests to analyze, review, or give investment advice on a specific sector/板块/行业, such as "深入分析XX板块并给出投资建议", "分析光伏行业", "XX板块现在什么状态".
---

# Sector Deep Analysis（板块深度分析）

## Overview

Produce a sell-side quality sector research report from a single user request like "深入分析商贸零售板块并给出投资建议". The output is a self-contained HTML file with ECharts charts, data tables, and actionable investment recommendations — not a chat reply.

## Prerequisites

This skill is **self-contained**. It relies only on `westock-data` (a built-in WorkBuddy skill binary) for all market data. Read the reference file in this skill's own `references/` directory before starting:

- `references/westock-data-parsing.md` — JSON parsing patterns for westock-data raw output (critical for correct data extraction; getting it wrong silently produces empty results or wrong numbers).

Always re-read this reference at the start of a session — the API quirks are easy to forget and have changed across versions.

## Workflow

### Step 1: Read the Parsing Reference

Read `references/westock-data-parsing.md` in this skill directory. It documents:
- The `--raw` JSON return shape for each command (quote / finance / kline / sector / consensus / rating / report / macro)
- Frequent pitfalls (batch wrap, newest-first kline, duplicate constituents, uppercase field names, etc.)

Do NOT trust memory — verify the actual shape against the reference each session.

### Step 2: Identify Sector & Get Structure

Use westock-data to find the sector code and its constituents.

```bash
WD="/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data"
NODE="/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"

# (a) If the sector code is already known (e.g. from a previously saved list),
#     skip the search. Otherwise:
$NODE $WD/scripts/index.js sector search <板块名>
# → Returns sector code like pt01801200 (申万一级行业) or pt01801170 (交通运输)

# (b) Get all constituents
$NODE $WD/scripts/index.js sector constituent <code> --raw > /tmp/sector_constituents.json
# → Returns a LIST of {SectorCode, StockCode, StockName}

# (c) Get sector ranking (to locate the sector among the 31 SW1 peers)
$NODE $WD/scripts/index.js sector ranking --raw > /tmp/sector_ranking.json
# → Returns {sections: [[...]]}, each item has name/changePct/turnoverRate/changePct5d/20d/leadStock
```

**Constituent dedup (mandatory)** — the constituent list usually contains duplicates (e.g. 交通运输 returned 175 rows but only 128 unique codes). Deduplicate by `StockCode`:

```python
import json
d = json.load(open('/tmp/sector_constituents.json'))
seen, uniq = set(), []
for s in d:
    if s['StockCode'] not in seen:
        seen.add(s['StockCode']); uniq.append(s)
print('Unique:', len(uniq))
```

From the unique constituents, identify 4-6 key companies covering the major sub-segments within the板块. For 交通 this means油运/集运/铁路/航空/港口/高速/快递/物流 — every distinct sub-track should have a representative leader. Selection criteria:
- Market cap relevance (largest = sector leader)
- Business model diversity (must cover each meaningful sub-sector)
- Recent news/catalyst exposure (run Step 6 on the shortlist)

### Step 3: Get Sector-Index Timing (Bowl-Bottom / Position-in-Range)

This step is **mandatory** — it is what separates a data report from a timing-aware research note. Fetch the sector INDEX kline (the sector code itself can be queried as a kline code) and compute its position.

```bash
$NODE $WD/scripts/index.js kline <sector_pt_code> --period day --limit 250 --raw > /tmp/sector_idx_kline.json
```

Compute and report in the HTML:
- **Current close**, 250-day high/low, **position in 250-day range (0-100%)** — <20% = bottom, >80% = top
- **120-day position** (same calculation over a 120-day window)
- **60-day trend** (linear-regression slope × 60 / mean × 100, in %)
- **20-day trend** (same over 20 days) — a 20-day trend flipping positive after a deep 60-day slide is the classic "企稳 / bowl-bottom completion" signal
- **YTD change** (current / first-bar-of-year open − 1)
- **Drawdown from 120-day high** — thin drawdown (> -5%) means the sector is near highs (not a bottom)

A sector near its 250-day 17% low with a 60-day trend of -15% but a 20-day trend of +1.7% is in the **left-side buy zone** — flag this in the TL;DR.

### Step 4: Get Company-Level Data

For each of the 4-6 key companies, fetch **five** data types. Run them in parallel via a single bash loop (each `--raw` call is independent).

```bash
LEADERS="sh601919,sh600026,sh601872,sh601816,sh601006,sz002352,sh600233,sh600009,sh601021,sh601111"

# 1. Quote — batch in ONE call (BatchResult wrap!)
$NODE $WD/scripts/index.js quote $LEADERS --raw > /tmp/quotes.json

# 2. Financials — per-stock (per-code finance is reliable; batch often returns empty TTM for some)
for c in sh601919 sh600026 sh601872 sh601816 sh601006; do
  $NODE $WD/scripts/index.js finance $c --type lrb --num 5 --raw > /tmp/fin_$c.json
done

# 3. K-line — only fetch if individual price-action commentary is needed;
#    the sector index kline from Step 3 is usually enough for the report.

# 4. Consensus (机构一致预期) — KEY for forward EPS / 净利增速 / forward PE
for c in sh601919 sh600026 sh601872; do
  $NODE $WD/scripts/index.js consensus $c --raw > /tmp/cons_$c.json
done

# 5. Rating + 6. Report — institutional ratings & latest research titles
for c in sh601919 sh600026 sh601872; do
  $NODE $WD/scripts/index.js rating $c --raw > /tmp/rat_$c.json
  $NODE $WD/scripts/index.js report $c --limit 3 --raw > /tmp/rep_$c.json
done
```

**Critical JSON parsing quirks — see `references/westock-data-parsing.md` for full code samples**:
- `quote --raw` with multiple codes returns a **BatchResult dict** `{success, status, data:[{symbol, data:{...}}], errors, metadata}` — NOT a plain list. Iterate `data[]`, each item's `data` sub-field holds the quote.
- `finance --raw` with `--type lrb` returns a **flat list** (NOT nested in sections) — each element is one period. Pick the first element with a non-null `OperatingRevenueTTM`.
- `consensus --raw` returns a list of year-keyed dicts (2026/2027/2028) — extract 2026E EPS, 营收YoY, 净利YoY, PE, institutionCnt.
- `rating --raw` returns `{forecastInstitutions, ratingBuyCnt, ratingIncCnt, ratingCnt}` — sparse but useful for the "机构观点" table.
- `report --raw` returns a list of `{title, orgName, pubDate}` — extract first 3 titles for the research-view table.

### Step 5: Get Macro Context

Use westock-data macro indicators **first**; only fall back to WebSearch when westock returns `MACRO_002` or null. In recent versions, `pmi`, `gdp`, `core_indicators_cur` actually work; retail-specific commands (社零 by category) sometimes fail.

```bash
# Try these first (they DO return data in current builds):
$NODE $WD/scripts/index.js macro indicator pmi --year 2025 --raw
$NODE $WD/scripts/index.js macro indicator gdp --year 2025 --raw
$NODE $WD/scripts/index.js macro indicator core_indicators_cur --raw   # 社零/CPI/PPI current
```

If a macro indicator fails (returns `{"success": false, "error": {"code": "MACRO_002"}}`), then:
```
WebSearch: "2026年 社会消费品零售总额 同比 国家统计局 最新"
WebSearch: "2026年 CPI PPI 最新 国家统计局"
```

Key macro indicators by sector type:
- **Retail / consumer**: 社零总额 + 限额以上 + 分业态 (便利店/超市/百货/专业店/品牌专卖) + 分品类 (汽车/家电/化妆品/通讯器材) + CPI/PPI
- **Industrial / manufacturing**: PMI (新订单/出口订单/库存) + PPI + 工业增加值 + 固定资产投资
- **Transportation**: PMI (出口订单 49 = 货运承压) + PPI (油价传导) + 进出口金额 + 油价/汇率
- **Tech**: 软件/IT 产业增加值 + 政策补贴 + 国产化率

**Always check the publication date** in results — use the latest released data, and note the typical release calendar (mid-month for previous month, Jan 19 for prior-year GDP).

### Step 6: Get Sector Catalysts & News

WebSearch for sector-specific themes (this is where WebSearch is genuinely necessary — westock does not carry thematic news):
```
WebSearch: "<sector keywords> 政策 催化 2026"
WebSearch: "<key company name> 业绩 调改 转型 2026"
```

Common catalyst types by sector:
- Retail: 胖东来调改 / 以旧换新 / 跨境电商政策 / 免税政策 / 海南封关
- Transportation: 提价（高铁票价上调）/ 油价 / OPEC+ 增产 / 汇率 / 旺季运价 / 以旧换新（货运汽车）
- Manufacturing: 产能出清 / 海外订单 / 技术突破
- Tech: 政策补贴 / 技术路线变化 / 产业链国产化

### Step 7: Analyze Using the Sector-Comparison Framework

Apply this 7-layer framework inline (no external reference needed):

1. **Core logic (核心逻辑)**: Why is the market pricing this sector the way it is? What drives forward upside? For交通运输 the answer was "oil-tanker cycle peak + 集运 digestion + 航空 bottom — all three coexist within one板块".
2. **Trading position (位置)**: Use Step 3 numbers. One of: 极低位 / 低位企稳 / 启动确认 / 主升 / 拥挤 / 回撤修复. A 17.5% 250-day position with 20d turning positive = "低位企稳，左侧买点".
3. **Catalyst intensity (催化强度)**: Hard (earnings预增 / policy文件 / orders) vs soft (sentiment / overseas mapping / 题材接力). Rank油运 26Q2 预增 +200% = hard; 自动驾驶出租车概念 = soft.
4. **Fund preference (资金偏好)**: Lead-stock turnover, 机构持仓变化, 北向流入. Quote data gives `turnover_rate`, `chg_20d`, `chg_60d`.
5. **Crowding & valuation (拥挤度与估值)**: Overcrowded sectors have short-term risk even with good logic. Use `consensus` institutionCnt + PB / 股息率 / 破净率 as the拥挤度 signals. PB<1 pervasive = bottoming signal not crowded.
6. **Style rotation (风格轮动)**: When size / value / growth trade-off matters, layer in the 10y国债利率 environment. Low-rate era favors high-dividend (交通运输红利 PE 8~15, 股息 4%~6.7% is scarce现金流).
7. **Must give a ranking (明确排名)**: 短期优先 / 中期优先 / 跟踪 / 等待. Never equivocate. If you cannot articulate variant perception, output "跟踪/放弃" — do not force a thesis.

**Variant perception (变异认知) is mandatory**: Identify what the market is mispricing. Examples that worked:
- "市场用集运周期下行杀全板块，但油运是全球定价资产，26E 净利 +200% 已被业绩预告锁死，PE 7倍一并砸杀 → 错杀"
- "红利股息率 6.66%，10年期国债 1.7% 时代是稀缺现金流资产，PB 0.59 破净提供安全垫"
- "三大航 YTD 跌 36%~40%，悲观预期充分，Q4 油价回落+春运是高弹性右侧"

If you cannot find a variant perception, **explicitly say "monitor" or "pass"** — do not manufacture one.

### Step 8: Produce HTML Report

Write a self-contained HTML file to the project working directory with the name `<板块名>板块深度分析-YYYYMMDD.html`.

**Structure** (sell-side report style — match the order):
1. **Header** — title, date, sector rating badge (低配/标配/超配 + 中性偏多/谨慎等 qualifier)
2. **TL;DR conclusion card** — 结论先行, 3-5 sentences with the variant perception bolded
3. **Key metrics dashboard** — 4-6 metric cards (YTD, 26E growth, 股息率区间, biggest drawdown, etc.)
4. **Sector timing section** — Step 3 charts: 月线走势 (ECharts line with markPoint + markLine for前低), callout for "key signal"
5. **Sector structure & divergence** — ECharts grouped bar (sub-segment 26E growth) + toggleable data table; **this is the most important chart** — the whole point is that sectors are sums of sub-tracks
6. **Key company valuation table** — 子赛道 tag + 现价/当日/20日/60日/YTD/PE-TTM/PE-26E/PB/股息/52周区间 for all 15-20 leaders
7. **Financial quality radar** — ECharts radar comparing 5-7 leaders on 营收/净利/毛利率/净利率
8. **重点公司拆解** — narrative sub-sections per top 6-8 names, citing research report机构 + 观点 + 催化 + 风险
9. **机构观点表** — consensus + rating + report titles, with 评级 tags
10. **政策催化表** — table of policy + date + impact + 受益方向 tags
11. **多头 vs 空头 two-column** — bulleted; followed by 主要风险 callout
12. **配置建议表** — 方向 tag / 标的 / 建议 / 逻辑 / 时间维度; plus 操作框架 callout with a suggested portfolio组合 (e.g. "40% 红利 + 25% 油运 + 20% 成长 + 15% 期权") and止损信号
13. **板块评级汇总表** — 景气结构/估值/股息/资金/催化/风险 → 综合评级
14. **免责声明** — sources + 不构成投资建议 + 数据截止

**Style rules**:
- Light background (linear-gradient header in 板块-related主色, e.g. 交通运输 #0f3d5c/#1976a4, 消费 #1e3a5f/#2c5282), dark text (研报风)
- 红涨绿跌 — A股惯例: `.pos` green for涨/利好, `.neg` red for跌/利空 (NOTE: A股 visual convention is红涨绿跌; for text-value semantic coloring use red=up-green=down text but ensure the value's *direction* (positive growth) is the天津 color — use `.pos` (green text) for positive numbers, `.neg` (red text) for negative numbers, regardless of红/绿 background semantics. Most A股 research reports use this瓶 text-colorscheme.)
- ECharts for data charts, tables for lookup data
- Every data point has a source line + timestamp
- Section number + Chinese title (`一、`, `二、`) — sell-side report convention
- Use `<span class="tag tag-g/-y/-r/-b">` for recommendation/benefit tags

**JS syntax check (mandatory before delivery)**:
```bash
# Extract inline <script> from HTML, save to temp .js, then:
node --check /tmp/_check.js
# Must pass with zero errors before presenting to user
```

### Step 9: Write Memory & Present

1. Append a work log to `.workbuddy/memory/YYYY-MM-DD.md` (create if missing) — note the板块 analyzed, key findings, rating, and HTML output path.
2. Present the HTML file path to the user as the final deliverable (do not paste HTML contents in chat — point to the file).

## Action Classification

Every analysis conclusion must map to one of these recommendation verbs:
- **仓位动作**: `加仓` | `加码` | `持有` | `减仓` | `清仓` | `平空` | `对冲`
- **观察动作**: `观察名单` | `等待证据` | `重新评估` | `放弃`
- **卖研风格 (recommend for the 配置建议表)**: `超配` | `标配` | `低配` | `标配/加码` | `标配/左侧` | `主题关注` | `回避`

Use the sell-side style tags (超配/标配/低配/左侧/回避) inside the HTML 配置建议表; use the仓位动作 verbs (加仓/减仓/清仓) in the chat reply that accompanies the file delivery.

## Resources

### references/
- `westock-data-parsing.md` — JSON parsing patterns for westock-data raw output (critical for correct data extraction). Read this BEFORE fetching any data.