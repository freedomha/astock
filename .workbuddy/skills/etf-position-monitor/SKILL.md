---
name: etf-position-monitor
description: Use when the user wants to check pending ETF batch-buy trigger prices (剩余批次触发价提醒), run a periodic weight-drift / rebalance check (权重漂移 / 周末复评 / 该调仓了吗), or monitor satellite-position swing bands (卫星仓波段 / 高抛低吸 / 到上轨了吗). Reads one config (monitor_config.json — holdings with shares/cost/target weights, pending_batches with triggers, a 5/25 rebalance rule, and swing positions with core/satellite shares + band). Pulls live quotes and qfq klines from westock-data, then: (a) evaluates each batch trigger (price_below / price_above / price_below_ma / price_above_ma / time_elapsed, any|all mode); (b) computes actual vs target weights and flags 5/25 band breaches (绝对偏离 >5pp 或 相对偏离 >25%) with lot-rounded orders and per-trade cost; (c) for each swing position emits SELL / BUY / STOP / HOLD / WAIT by comparing price to upper band (sell satellite), lower band (buy back) and stop, plus round-trip cost vs captured move. Outputs a console report plus optional HTML. Triggers on "检查批次触发"、"持仓监控"、"权重漂移"、"周末复评"、"该调仓了吗"、"剩余批次"、"触发提醒"、"波段"、"高抛低吸"、"卫星仓".
---

# ETF 持仓监控（剩余批次触发 + 权重漂移）

## Overview

对**真实券商账户**做三类例行检查，读同一份配置：

1. **批次触发检查**——待执行的分批建仓订单，是否触及预设触发价／均线／时间条件。
2. **权重漂移检查**——按 5/25 规则判断组合是否偏离目标权重到该再平衡的程度，并给出**含手数取整与费用的调仓指令**。
3. **卫星仓波段检查**——核心仓不动的标的，用卫星仓做高抛低吸：现价触及上轨→卖出信号，触及下轨→买回信号，跌破止损→不再买回。

不预测行情、不给投资建议，只做**规则判定与下单计算**。

## When to use

| 场景 | 命令 |
|------|------|
| 盘后／盘中想知道"挂的批次到了吗" | `monitor.py --batch` |
| 每周末做权重漂移复评 | `monitor.py --drift` |
| 想知道"波段上轨/下轨到了吗" | `monitor.py --swing` |
| 例行完整检查（三者都做） | `monitor.py` |
| 需要留档／发给别人 | 加 `--html <path>` |
| 记录历史漂移 | 加 `--save-state` |

## Prerequisites

- **westock-data CLI**：`~/.workbuddy/westock-data/scripts/index.js`；node 用 `find_node()` 自动定位（路径会随版本漂移，勿硬编码）。
- **Bash 调用必须 `dangerouslyDisableSandbox: true`**（网络访问）。
- Python 3（项目内用 `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`）。

## Files

| 文件 | 作用 |
|------|------|
| `monitor_config.json` | **唯一需要维护的配置**：持仓、目标权重、待执行批次、漂移规则 |
| `monitor.py` | 主脚本 |
| `drift_history.json` | `--save-state` 追加的漂移历史（首次运行后生成） |

## 配置说明（monitor_config.json）

```json
{
  "as_of": "2026-10-16",
  "portfolio_value": 48533.20,
  "cash": 16786.80,
  "costs": { "commission_rate": 0.00025, "min_commission": 5.0,
             "half_spread": 0.0005, "lot_size": 100 },
  "holdings": [
    { "code": "sh518880", "name": "黄金ETF华安", "shares": 300,
      "cost": 8.5710, "target_weight_pct": 15.0, "role": "hedge" }
  ],
  "pending_batches": [
    { "id": "gold-2", "code": "sh518880", "name": "黄金ETF华安", "shares": 300,
      "desc": "黄金第2批",
      "trigger": { "mode": "any", "conditions": [
        { "type": "price_below", "level": 8.25, "label": "跌至 8.25 附近" }
      ]}}
  ],
  "rebalance": { "rule": "5/25", "band_abs_pct": 5.0, "band_rel_pct": 25.0 }
}
```

- `holdings[].shares` 为**实际持有份额**；`cash` 为可用现金。两者之和＝总资产。
- **`target_weight_pct` 合计必须 = 100（含现金）**；现金目标 = 100 − Σ持仓目标。
- `pending_batches[].shares` 为该批计划的份数。

### 支持的触发类型

| type | 参数 | 命中条件 | 典型用途 |
|------|------|---------|---------|
| `price_below` | `level` | 现价 ≤ level | 逢跌分批（如黄金跌至 8.25） |
| `price_above` | `level` | 现价 ≥ level | 突破追入 |
| `price_below_ma` | `ma`（5/10/20/60/120） | 现价 ≤ MA | 回踩均线买入（如红利回踩 MA20） |
| `price_above_ma` | `ma` | 现价 > MA | 止跌确认（如黄金站回 MA60） |
| `time_elapsed` | `ref_date`,`days` | 距 ref_date ≥ days | 时间分批 |

- `trigger.mode`：`any`（任一条件命中即触发，默认）或 `all`（全部满足）。
- **建议用 `any` + `time_elapsed` 兜底**，避免纯价格条件长期不触发导致资金闲置。

### 权重漂移规则（5/25）

任一资产满足 **绝对偏离 > `band_abs_pct`(默认5pp)** 或 **相对偏离 > `band_rel_pct`(默认25%)** 即提示再平衡（先到即执行）。输出会给出目标金额、差值与**取整到 1 手（100 份）后的买卖指令及费用**。

### 卫星仓波段规则

```json
"swing": { "positions": [
  { "code": "sh510050", "name": "上证50ETF华夏",
    "core_shares": 3700, "satellite_shares": 1500, "satellite_state": "holding",
    "band_mode": "fixed", "ref_price": 2.866, "band_pct": 2.5, "stop_pct": 5.0,
    "note": "..." }
]}
```

- **`core_shares` 不动**（保持配置）；`satellite_shares` 用于波段。
- `satellite_state`：`holding`（当前持有卫星仓，等卖出信号）/ `sold`（已卖出，等买回信号）。**成交后必须切换此字段**。
- `band_mode`：`fixed`（以 `ref_price` 为中心）/ `ma`（以 `MA(ma_period)` 为中心，自适应）。
- 关键位由中心价推出：上轨 `center×(1+band_pct%)`、下轨 `center×(1−band_pct%)`、止损 `center×(1−stop_pct%)`。

**信号判定**

| 状态 | 条件 | 信号 |
|------|------|------|
| holding | 现价 ≥ 上轨 | **SELL** 卖出卫星仓 |
| holding | 现价 ≤ 止损位 | **WARN** 核心仓需复核 |
| holding | 其他 | HOLD |
| sold | 现价 ≤ 止损位 | **STOP** 趋势破位，不买回 |
| sold | 现价 ≤ 下轨 | **BUY** 买回卫星仓 |
| sold | 其他 | WAIT |

输出同时给出**往返成本率**与**单次捕获幅度 − 成本 = 净收益**，用于判断该波段是否划算。

**波段适配性筛选（建仓前先做）**：只有当 ETF **均值回归属性**（用 Lo-MacKinlay 方差比 VR5，<0.9 才有回归基础；≈1.0 是随机游走，不该做波段）**且** `2×band_pct > 3×往返成本率` 时才值得设波段。仓位过小（卫星仓 < ~3,000 元）会因最低佣金 5 元使成本率 >0.5%，此时应放弃或合并。

## Workflow

### Step 1（仅当持仓/批次变化时）更新配置

成交或调整批次后，改 `monitor_config.json`：
- 买入成交 → `holdings[].shares` 增加，`cash` 减少（=成交金额+费用）；从 `pending_batches` 删除该批。
- 卖出现金流入 → `cash` 增加。
- 新增批次 → 在 `pending_batches` 追加。
- **波段成交** → 买卖卫星仓**不改变 `holdings[].shares`**（总份额不变），但要：
  - 切换 `swing.positions[].satellite_state`（`holding` ↔ `sold`）；
  - 把 `ref_price` 重设为**新波段区间的中心**（例如刚在上轨卖出，则以当前价为新区间中枢），否则下一轮会立刻反向触发。

> 建议同时把成交记入 `records/etf/*.json`（纯交易流水格式 `{name, code, trades[]}`），与本配置互为校验。

### Step 2 运行

```bash
PY="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
SK=".workbuddy/skills/etf-position-monitor"
$PY $SK/monitor.py                      # 完整检查（批次 + 漂移 + 波段）
$PY $SK/monitor.py --batch              # 只查批次触发（盘中常跑）
$PY $SK/monitor.py --swing              # 只查卫星仓波段（盘中常跑）
$PY $SK/monitor.py --drift --save-state # 周末漂移复评并存档
$PY $SK/monitor.py --html reports/etf/monitor/$(date +%Y%m%d)-持仓监控.html
```

### Step 3 解读输出

- **批次**：`✅ 已触发` 即可按计划份数下单；`⏳ 未触发` 显示还差多少（如"现价 8.555 > 触发 8.25"）。
- **漂移**：`⚠️超限` 的资产会给出建议调整份数、金额与费用；全部 `✓` 则无需动作。
- **波段**：`🔴 卖出信号` / `🟢 买回信号` 可直接执行；`⛔ 止损` 表示趋势破位、不买回；`⏳` 为无动作。同时看**净收益**（捕获幅度 − 往返成本）是否为正。
- 每笔会显示**费用与费用率**——**单笔金额越小费用率越高**（最低佣金 5 元主导），据此决定是否合并批次。

### Step 4 执行与回填

按输出下单后，回到 Step 1 更新配置。价格类触发可每日查；权重漂移按**周**（完整周线形成后）或**月**跑。

## 成本口径（与 etf-operation-plan 一致）

```
单笔费用 = max(5元, 成交额 × 佣金率万2.5) + 成交额 × 单边价差0.05%
```

- ETF **免印花税**；最小交易单位 **1 手 = 100 份**，不足 1 手不成交。
- **小额分批的成本惩罚**：2,500 元订单费用率约 0.20%（纯最低佣金），5,000 元约 0.11%，10,000 元约 0.075%。**单笔尽量 ≥5,000 元**。

## Important Notes

- **不改动 `records/etf/`，也不读写 `records/portfolio_config.json`**（后者属于 `etf-operation-plan` / `etf-lowdip-scanner`，格式与语义不同）。本 skill 只维护自己目录下的 `monitor_config.json`。
- 配置里的 `shares` 必须与实际券商持仓一致；本 skill **不会**从 `records/etf` 反推份额（历史流水可能不完整）。
- **波段与再平衡会互相干扰**：波段改变的是"卫星仓在哪只标的上"，会打乱目标权重。建议**只动卫星仓**，并在季度再平衡时把总份额归位。
- **T+0 / T+1 差异**：股票 ETF（510050 上证50、512890 红利低波、159698 粮食）是 **T+1**，当天买不能当天卖；黄金 ETF（518880）与跨境 ETF（513500 标普500）是 **T+0**。这决定波段的最小周期。
- 触发是**价格/时间判定**，不含趋势状态过滤。若需要 T0-T8 趋势门与硬约束矩阵，请用 `etf-operation-plan`。
- 同一标的多批次会共享一次 kline 请求（带缓存与 3 次重试），避免触发数据源限流导致 MA 计算失败。
- 涨跌配色遵循 A 股习惯（红涨绿跌）。非投资建议。
