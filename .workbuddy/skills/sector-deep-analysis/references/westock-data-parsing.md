# westock-data JSON Parsing Guide

Critical patterns for extracting data from westock-data `--raw` JSON output. Getting these wrong silently produces empty results or wrong numbers.

## Invocation

westock-data is a Node.js script, not a system binary:

```bash
WD="/Users/aldiadmin/.workbuddy/westock-data"
NODE="/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
$NODE $WD/scripts/index.js <command> [params] --raw
```

## quote — Real-time Quote

**Single code** returns a dict with a `data` field. **Multiple codes (batch)** — the common sector-analysis case — returns a **BatchResult** dict. The two shapes are different.

### Single code

```bash
$NODE $WD/scripts/index.js quote sh601919 --raw
```
Returns:
```json
{"code": "sh601919", "name": "中远海控", "price": 15.13, "pe_ratio": 9.22, "pb_ratio": 1.01, ...}
```
Parse:
```python
import json
d = json.loads(raw)
# d is a dict of quote fields directly — access d['price'], d['pe_ratio'], etc.
```

### Batch (multiple codes, comma-separated) — RECOMMENDED for sector work

```bash
$NODE $WD/scripts/index.js quote sh601919,sh600026,sh601872 --raw
```
Returns a **BatchResult wrap**:
```json
{
  "success": true,
  "status": "ok",
  "data": [
    {"symbol": "sh601919", "data": {<full quote dict>}},
    {"symbol": "sh600026", "data": {<full quote dict>}}
  ],
  "errors": [],
  "metadata": {...}
}
```
Parse:
```python
d = json.loads(raw)
items = d.get('data', [])                # list — each item wraps a 'data' sub-field
for r in items:
    x = r['data']                        # the real quote dict
    name, price = x['name'], x['price']
    pe, pb = x['pe_ratio'], x['pb_ratio']
    chg_ytd = x.get('chg_ytd', 0)
    chg_20d = x.get('chg_20d', 0)
    chg_60d = x.get('chg_60d', 0)
    div = x.get('dividend_ratio_ttm', 0)
    hi52, lo52 = x['high_52week'], x['low_52week']
    cap = x['total_market_cap']          # may be 0 — see pitfall
```

### Key fields (all in `data` sub-dict for batch; top-level for single)
- `name`, `price`, `change_percent`
- `pe_ratio` (TTM), `pe_fwd` (forward), `pe_lyr`
- `pb_ratio`
- `dividend_ratio_ttm` (股息率%, already ×100)
- `total_market_cap`, `circulating_market_cap` (亿元, may be 0)
- `chg_5d`, `chg_10d`, `chg_20d`, `chg_60d`, `chg_ytd` (all in %)
- `high_52week`, `low_52week`
- `turnover_rate`, `volume_ratio`

**Pitfall**: `total_market_cap` sometimes returns 0. If market cap is needed, compute from `price * total_shares` or cross-check via WebSearch. In the 2026-07 build the field is reliable and in 亿元 units.

**Pitfall**: For batch, never assume the result is a list — always check `isinstance(d, dict) and 'data' in d` first. Old code that does `d[0]` will throw on batch output.

## finance — Financial Statements

**With `--type lrb` (profit statement) and `--num N`, returns a FLAT LIST of period records** (not nested in sections). The bare `finance <code>` without `--type` does return a `{sections: [[...]]}` shape — these are two different commands, do not confuse them.

### Recommended form (profit statement, list output)

```bash
$NODE $WD/scripts/index.js finance sh601919 --type lrb --num 5 --raw
```
Returns a list, newest period first:
```json
[
  {"_date": "2026-06-30", "EndDate": "2026-06-30", "SecuCode": "sh601919"},  // 半年报未披露时字段稀疏
  {"_date": "2026-03-31", "EndDate": "2026-03-31", "OperatingRevenue": "...",
   "OperatingRevenueTTM": "...", "NPParentCompanyOwners": "...",
   "NPParentCompanyOwnersTTM": "...", "GrossProfitTTM": "...",
   "BasicEPS": "0.38", "OperatingCost": "...", ...},
  ...
]
```

Parse:
```python
d = json.loads(raw)              # list
# Find first record with actual TTM revenue (some early periods may be sparse)
rec = next((r for r in d if r.get('OperatingRevenueTTM')), None)
if rec is None:
    print('no TTM record — fall back to WebSearch')
else:
    rev  = float(rec['OperatingRevenueTTM'])     # TTM 营业收入 (元)
    np   = float(rec['NPParentCompanyOwnersTTM'])  # TTM 归母净利 (元)
    gp   = float(rec.get('GrossProfitTTM', 0))
    gm   = gp / rev * 100 if rev else 0
    npm  = np  / rev * 100 if rev else 0
    # 转亿元 display:
    rev_yi, np_yi = rev / 1e8, np / 1e8
```

### Bare form (returns sections)
```bash
$NODE $WD/scripts/index.js finance sh601919 --raw
```
Returns `{sections: [[...], [...], [...]]}` — three parallel statement-type lists (lrb / zhsz / yeb provisional snapshots), often all sparse. **Prefer `--type lrb --num 5` for sector work.**

### Key field names (exact uppercase — case-sensitive!)
- `_date` / `EndDate` → report period (e.g. "2026-03-31")
- `OperatingRevenue` → 营业收入 (single period, in 元)
- `OperatingRevenueTTM` → TTM revenue
- `NPParentCompanyOwners` → 归母净利润 (single period)
- `NPParentCompanyOwnersTTM` → TTM net profit
- `OperatingCost` / `OperatingCostTTM`
- `GrossProfitTTM`
- `OperatingProfit` / `OperatingProfitTTM`
- `BasicEPS` / `DilutedEPS`
- `OperatingExpense`, `FinancialExpense`

**Pitfall**: Using lowercase `operating_revenue` or `net_profit` returns None. Field names are PascalCase.

**Pitfall**: Field values are STRINGS — always `float()` before arithmetic.

**Pitfall**: Single-quarter fields have `_Q` suffix (e.g. `NPParentCompanyOwners_Q`). TTM fields have `TTM` suffix. Non-suffix = cumulative. For sector comparison use TTM (or cumulative if TTM absent). Never mix `_Q` and non-`_Q`.

**Pitfall**: When batch-querying finance (`finance sh601919,sh600026 ...`), some codes reliably return empty TTM records even when single-code query works. **Always call finance one code at a time** in a bash loop.

## kline — K-line / Price History

**Data is newest-first** (arr[0] = most recent date). The same endpoint works for stocks, ETFs, **and sector indices** (using the sector `pt` code).

```bash
# Stock kline
$NODE $WD/scripts/index.js kline sh601919 --period day --limit 120 --raw

# Sector index kline (for Step 3 sector timing)
$NODE $WD/scripts/index.js kline pt01801170 --period day --limit 250 --raw
```

Returns a list of bars, newest first:
```json
[
  {"date": "2026-07-23", "open": ..., "last": 2020.08, "high": ..., "low": ..., "volume": ..., "amount": ..., "exchange": "0.92"},
  {"date": "2026-07-22", ...},
  ...
]
```

Parse:
```python
d = json.loads(raw)
arr = d if isinstance(d, list) else d.get('data', d)
# arr[0] = today, arr[-1] = oldest

# Always sort ascending for trend analysis:
arr = sorted(arr, key=lambda x: x['date'])

closes = [float(x['last']) for x in arr]
highs  = [float(x['high']) for x in arr]
lows   = [float(x['low'])  for x in arr]
n = len(closes)
cur = closes[-1]

# Position in 250-day range (0-100%, low=bottom)
n250 = min(250, n)
hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
pos_250 = (cur - lo250) / (hi250 - lo250) * 100 if hi250 > lo250 else 50

# 60-day linear-regression trend (%)
x = list(range(60)); y = closes[-60:]
xm, ym = sum(x)/60, sum(y)/60
slope = sum((x[i]-xm)*(y[i]-ym) for i in range(60)) / sum((x[i]-xm)**2 for i in range(60))
trend_60 = slope * 60 / ym * 100

# 20-day trend (lower window — detects bottoms turning)
x = list(range(20)); y = closes[-20:]
xm, ym = sum(x)/20, sum(y)/20
slope = sum((x[i]-xm)*(y[i]-ym) for i in range(20)) / sum((x[i]-xm)**2 for i in range(20))
trend_20 = slope * 20 / ym * 100

# YTD change (need to find first bar of year)
ytd_bars = [k for k in arr if k['date'] >= '2026-01-01']
ytd_chg = (cur / float(ytd_bars[0]['open']) - 1) * 100 if ytd_bars else 0
```

**Bowl-bottom / left-side buy signal** — flag in TL;DR if all three hold:
- `pos_250 < 25` (near bottom of range)
- `trend_60 < -5` (deep slide)
- `trend_20` flipping positive (`-2 < trend_20 < 4` after a long downtrend)

**Pitfall**: If you assume chronological order (oldest first) and compute `arr[-1]/arr[0]`, you get the INVERSE. Always remember: **index 0 = today**, or sort ascending first.

**Pitfall**: `last` is the close price; `close` does NOT exist as a field. `exchange` is the turnover rate (换手%), not the exchange name.

## sector — Sector Queries

```bash
# Search by name (returns list of matches)
$NODE $WD/scripts/index.js sector search 交通运输
# → [{"code": "pt01801170", "name": "交通运输", "sectorCode": "sw1_pt01801170"}]

# Get all constituents
$NODE $WD/scripts/index.js sector constituent pt01801170 --raw > /tmp/c.json
# → Returns a LIST of {SectorCode, StockCode, StockName}

# List all SW1 sectors
$NODE $WD/scripts/index.js sector list industry_list_sw1 --limit 50 --raw
# → List of {code, name, sectorCode} — no performance data

# Sector ranking (cross-sector performance snapshot)
$NODE $WD/scripts/index.js sector ranking --raw
# → Returns {sections: [[...]]}, each item:
#   {name, changePct, turnoverRate, changePct5d, changePct20d, leadStock}
```

### Constituent deduplication (mandatory)

The constituent endpoint frequently returns duplicates (e.g. 交通运输 returned 175 rows for 128 unique stocks — likely because of SW1/SW2 dual classification inclusion). Always deduplicate:

```python
import json
d = json.load(open('/tmp/c.json'))
seen, uniq = set(), []
for s in d:
    if s['StockCode'] not in seen:
        seen.add(s['StockCode']); uniq.append(s)
print(f'Unique: {len(uniq)} (from {len(d)} raw)')
```

### Sector ranking parse

```python
d = json.load(open('/tmp/sector_ranking.json'))
for sec in d['sections']:
    for item in sec:
        # Filter to your sector's sub-tracks by name match
        if any(kw in item['name'] for kw in ['交通','运输','铁路','港口','航运','公路','物流','航空']):
            print(item['name'], item['changePct'], item['leadStock'])
```

**Pitfall**: `sector list --raw` returns only code/name/sectorCode — no price data. To locate the target sector's performance cross-section, use `sector ranking` and filter.

**Pitfall**: `sector info <code>` may return "无法提取数据列" — unreliable. Use `kline <pt_code>` + `sector ranking` instead.

## consensus — Institutional Consensus (机构一致预期)

**Critical for forward-looking valuation (26E/27E EPS, 净利增速, forward PE).** Always fetch consensus for the 4-6 key companies.

```bash
$NODE $WD/scripts/index.js consensus sh601919 --raw
```
Returns a list of year-keyed dicts, **not sorted**:
```json
[
  {"year": 2028, "eps": 0.95, "revenue": 21104622.73, "netProfit": 1456775.82,
   "pe": 15.86, "pb": 0.81, "ps": 1.10,
   "revenueYoy": -1.77, "netProfitYoy": -16.36, "institutionCnt": 0},
  {"year": 2026, "eps": 1.56, "revenue": 22196734.13, "netProfit": 2385541.33,
   "pe": 9.68, "pb": 0.91, "ps": 1.04,
   "revenueYoy": 1.12, "netProfitYoy": -22.72, "institutionCnt": 19},
  {"year": 2027, "eps": 1.14, ...}
]
```

Parse:
```python
d = json.loads(raw)              # list
records = {r['year']: r for r in d}
r26 = records.get(2026)
r27 = records.get(2027)
if r26:
    eps_26    = r26['eps']                # 2026E EPS
    rev_yoy   = r26['revenueYoy']         # 营收同比 %
    np_yoy    = r26['netProfitYoy']       # 归母净利同比 %
    pe_fwd    = r26['pe']                 # forward PE
    inst_cnt  = r26['institutionCnt']    # 覆盖机构数 — 拥挤度 proxy
```

**Field units**:
- `eps` → 元
- `revenue`, `netProfit` → 万元 (note: NOT 元 — convert by /10000 to亿)
- `revenueYoy`, `netProfitYoy` → % (already ×100)
- `pe`, `pb`, `ps` → 倍

**Pitfall**: `revenue` and `netProfit` are in 万元. For display in亿元 divide by 10000 (`r['revenue'] / 10000`).

**Pitfall**: `institutionCnt` for outer years (2028) is often 0 — no coverage yet. Use it as a 拥挤度 / 关注度 signal for current year (2026/2027); 32+ = heavily covered, <5 = neglected.

**Pitfall**: For low-coverage stocks the list can be empty or have only one year. Handle gracefully.

## rating — Institutional Ratings (评级聚合)

```bash
$NODE $WD/scripts/index.js rating sh601919 --raw
```
Returns a dict:
```json
{
  "forecastInstitutions": 1,
  "ratingBuyCnt": 1,
  "ratingIncCnt": 0,
  "ratingCnt": 1
}
```

Parse:
```python
d = json.loads(raw)
buy = d.get('ratingBuyCnt', 0)         # 买入评级数
inc = d.get('ratingIncCnt', 0)         # 增持评级数
tot = d.get('ratingCnt', 0)            # 评级总数
fct = d.get('forecastInstitutions', 0)  # 预测机构数
tag = '强烈推荐' if buy > 0 and inc == 0 else '买入/增持' if (buy + inc) > 0 else '—'
```

**Pitfall**: The rating summary is sparse — usually only 1-2 institutions submit, even for big caps. Treat absence as "no consensus", not as "sell". Cross-reference with `consensus` institutionCnt and the `report` titles below.

## report — Research Report Titles & Orgs

```bash
$NODE $WD/scripts/index.js report sh601919 --limit 3 --raw
```
Returns a list of dicts (recent reports first):
```json
[
  {"title": "【天风证券】中远海控(601919)：量价提升 周期上行", "orgName": "天风证券", "pubDate": "..."},
  {"title": "【招商证券】中远海控(601919)：26Q1盈利环比改善 公司仍具备投资价值", ...},
  ...
]
```

Parse:
```python
d = json.loads(raw)
items = d if isinstance(d, list) else d.get('data', [])
for r in items[:3]:
    title    = r.get('title', '')        # full title with【机构名】prefix
    # The机构 name is bracketed at the start: 【xxx证券】
    org = title.split('】')[0].lstrip('【') if '】' in title else r.get('orgName', '')
    body = title.split('】', 1)[1] if '】' in title else title
```

**Pitfall**: Some report records nest titles with the机构 bracket already inside `title`; others separate it into `orgName`. Always parse the `【...】` prefix from `title` first, fall back to `orgName`.

**Pitfall**: `pubDate` field is often empty or null in the current build. Do not rely on it for排序 — assume the list is already most-recent-first.

## macro — Macro Indicators

Several `macro indicator` commands DO return real data in the 2026-07 build; the old "macro always fails, use WebSearch" assumption is out of date. Try westock first, fall back only on `MACRO_002`.

### Working commands

```bash
# PMI (manufacturing + non-manufacturing, monthly)
$NODE $WD/scripts/index.js macro indicator pmi --year 2025 --raw
# Returns list of monthly records with PMI_PMI_MANU, PMI_PMI_MANU_ORDER_NEW,
#   PMI_PMI_MANU_ORDER_EXPORT (49 = 货运承压 signal), PMI_NON_MANU_BIZ_ACT, etc.

# GDP (quarterly contributions)
$NODE $WD/scripts/index.js macro indicator gdp --year 2025 --raw
# Returns list with GDP_CONTRI_CONSUME_CUM, GDP_CONTRI_IMPORT_CUR, etc.

# Current core indicators (社零/CPI/PPI, latest month)
$NODE $WD/scripts/index.js macro indicator core_indicators_cur --raw
# Returns {sections: [[{CONSUMP_CONSUMP_CUR_YOY, CONSUMP_CAR_CUM_YOY, PPI_PPI_YOY, CPI_*}]]}
```

### Parse core_indicators_cur

```python
d = json.loads(raw)
for section in d.get('sections', []):
    for row in section:
        ret_cur_yoy = row.get('CONSUMP_CONSUMP_CUR_YOY')      # 当月社零同比 %
        car_yoy     = row.get('CONSUMP_CAR_CUM_YOY')           # 汽车类累计同比 %
        phone_yoy   = row.get('CONSUMP_PHONE_CUM_YOY')         # 通讯器材累计同比 %
        ppi_yoy     = row.get('PPI_PPI_YOY')
        info_date   = row.get('CONSUMP_INFO_DATE')            # e.g. 20260715 = 发布日期
```

### Failing indicators (use WebSearch)

Commands that may still fail with `MACRO_002`:
- `macro indicator freight` (货运量 — not exposed)
- `macro indicator total_retail` (社零 by format — partially exposed in core_indicators_cur)

For sector-specific macro (港口吞吐量, 民航客运量, 快递业务量, 油价Brent, 汇率USDCNH):
```
WebSearch: "2026年 港口吞吐量 同比 交通运输部"
WebSearch: "Brent 油价 2026年7月"
WebSearch: "2026年 民航旅客运输量"
```

**Pitfall**: macro indicator records do NOT include a consistent date field — some use `INFO_DATE`, some `END_DATE`, some use none. Identify the date by the field name pattern (`*_INFO_DATE` = 发布日, `*_END_DATE` = 数据期末日).

**Pitfall**: Always check `success: false` and `error.code: "MACRO_002"` in the response; if present, command is unsupported and you must downgrade to WebSearch.

## Batch Query Pattern

For efficiency, fetch data for multiple codes in one bash call by looping:

```bash
for c in sh601919 sh600026 sh601872 sh601816; do
  $NODE $WD/scripts/index.js finance $c --type lrb --num 5 --raw > /tmp/fin_$c.json
  $NODE $WD/scripts/index.js consensus $c --raw > /tmp/cons_$c.json
  $NODE $WD/scripts/index.js rating $c --raw > /tmp/rat_$c.json
  $NODE $WD/scripts/index.js report $c --limit 3 --raw > /tmp/rep_$c.json
done
```

Or query quotes in ONE batched call (quote is the only command that natively supports comma-separated multi-code and returns BatchResult):

```bash
$NODE $WD/scripts/index.js quote sh601919,sh600026,sh601872,sh601816 --raw > /tmp/quotes.json
```

Always pipe through Python for reliable extraction — raw JSON is verbose. Don't try to parse JSON in bash.

## Quick Reference — Data Fetch Order for a Sector Report

For a sector with code `pt0XXX` and 4-6 leader codes `[L1, L2, ..., L6]`:

1. `kline pt0XXX --period day --limit 250 --raw` (sector timing)
2. `sector ranking --raw` (cross-sector context)
3. `quote L1,L2,L3,L4,L5,L6 --raw` (one batched call — BatchResult)
4. Loop per leader:
   - `finance Li --type lrb --num 5 --raw`
   - `consensus Li --raw`
   - `rating Li --raw`
   - `report Li --limit 3 --raw`
5. Try macro indicators (pmi / gdp / core_indicators_cur); fall back to WebSearch as needed.
6. WebSearch for sector-specific news / policy catalysts (not available from westock).

Total API calls per sector: ~25-30 (kline + ranking + 1 quote batch + 4-6 × 4 finance/consensus/rating/report + macro attempts). Roughly 1-2 minutes wall time on a warm machine.