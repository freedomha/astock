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

**Single code** returns a dict with a `data` field. **Multiple codes (batch)** returns a **BatchResult** dict. The two shapes are different.

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
# d is a dict of quote fields directly
```

### Batch (multiple codes, comma-separated)

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
items = d.get('data', [])
for r in items:
    x = r['data']
    name, price = x['name'], x['price']
```

### Key fields (all in `data` sub-dict for batch; top-level for single)
- `name`, `price`, `change_percent`
- `pe_ratio` (TTM), `pe_fwd` (forward), `pe_lyr`
- `pb_ratio`
- `dividend_ratio_ttm` (股息率%, already x100)
- `total_market_cap`, `circulating_market_cap` (亿元, may be 0)
- `chg_5d`, `chg_10d`, `chg_20d`, `chg_60d`, `chg_ytd` (all in %)
- `high_52week`, `low_52week`
- `turnover_rate`, `volume_ratio`

**Pitfall**: `total_market_cap` sometimes returns 0.
**Pitfall**: For batch, never assume the result is a list -- always check `isinstance(d, dict) and 'data' in d` first.

## kline — K-line / Price History

**Data is newest-first** (arr[0] = most recent date). Works for stocks, ETFs, and sector indices.

```bash
$NODE $WD/scripts/index.js kline sh601919 --period day --limit 250 --raw
```

Returns a list of bars, newest first:
```json
[
  {"date": "2026-07-23", "open": ..., "last": 2020.08, "high": ..., "low": ..., "volume": ..., "amount": ..., "exchange": "0.92"},
  ...
]
```

Parse:
```python
d = json.loads(raw)
arr = d if isinstance(d, list) else d.get('data', d)
arr = sorted(arr, key=lambda x: x['date'])  # oldest first for analysis

closes = [float(x['last']) for x in arr]
highs  = [float(x['high']) for x in arr]
lows   = [float(x['low'])  for x in arr]
n = len(closes)

# Position in 250-day range (0-100%, low=bottom)
n250 = min(250, n)
hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
pos_250 = (closes[-1] - lo250) / (hi250 - lo250) * 100 if hi250 > lo250 else 50

# Linear regression trend
x = list(range(60)); y = closes[-60:]
xm, ym = sum(x)/60, sum(y)/60
slope = sum((x[i]-xm)*(y[i]-ym) for i in range(60)) / sum((x[i]-xm)**2 for i in range(60))
trend_60 = slope * 60 / ym * 100
```

**Pitfall**: Index 0 = today (newest first). Sort ascending before analysis.
**Pitfall**: `last` is the close price; `close` does NOT exist. `exchange` is turnover rate (%).

## sector — Sector Queries

```bash
# Search by name
$NODE $WD/scripts/index.js sector search 交通运输

# Get constituents (DEDUP mandatory)
$NODE $WD/scripts/index.js sector constituent pt01801170 --raw

# Sector ranking
$NODE $WD/scripts/index.js sector ranking --raw
```

Constituent dedup:
```python
seen, uniq = set(), []
for s in d:
    if s['StockCode'] not in seen:
        seen.add(s['StockCode']); uniq.append(s)
```

## consensus — Institutional Consensus (机构一致预期)

```bash
$NODE $WD/scripts/index.js consensus sh601919 --raw
```

Returns list of year-keyed dicts:
```json
[
  {"year": 2026, "eps": 1.56, "revenue": 22196734.13, "netProfit": 2385541.33,
   "pe": 9.68, "pb": 0.91, "revenueYoy": 1.12, "netProfitYoy": -22.72, "institutionCnt": 19}
]
```

Parse:
```python
records = {r['year']: r for r in d}
r26 = records.get(2026)
eps_26 = r26['eps']              # 元
rev_26 = r26['revenue'] / 10000  # 万元 → 亿元
pe_fwd = r26['pe']
inst_cnt = r26['institutionCnt'] # 拥挤度 proxy
```

**Pitfall**: `revenue` and `netProfit` are in 万元. Divide by 10000 for 亿元.

## rating — Institutional Ratings

```bash
$NODE $WD/scripts/index.js rating sh601919 --raw
```
Returns: `{"forecastInstitutions": 1, "ratingBuyCnt": 1, "ratingIncCnt": 0, "ratingCnt": 1}`

## report — Research Report Titles

```bash
$NODE $WD/scripts/index.js report sh601919 --limit 3 --raw
```
Returns list of `{title, orgName, pubDate}`. Parse机构 from `【...】` in title.

## macro — Macro Indicators

Working commands:
```bash
$NODE $WD/scripts/index.js macro indicator pmi --year 2025 --raw
$NODE $WD/scripts/index.js macro indicator gdp --year 2025 --raw
$NODE $WD/scripts/index.js macro indicator core_indicators_cur --raw
```

Fall back to WebSearch on `MACRO_002` errors.

## finance — Financial Statements

```bash
$NODE $WD/scripts/index.js finance sh601919 --type lrb --num 5 --raw
```
Returns flat list, newest first. Fields are PascalCase, STRING values.
Find first record with non-null `OperatingRevenueTTM`.

**Pitfall**: Per-stock only (one code at a time). Batch finance returns empty.
