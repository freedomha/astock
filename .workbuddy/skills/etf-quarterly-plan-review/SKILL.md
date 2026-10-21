---
name: etf-quarterly-plan-review
description: Use when the user wants to review the quarterly contribution plan (季度定投计划 / 季定投复评 / 每周复评 / 该投了吗 / 检查定投计划), or asks whether this quarter's 3,000 元 contribution should be deployed and where. Reads plan_state.json (holdings with shares/cost/target weights, cash, six execution rules, executed-quarter flags) plus the plan report at reports/etf/allocation/20261021-季定投计划.html, pulls live quotes and 500-day klines from westock-data, delegates trend states to etf-operation-plan/trend_analysis.py, then: (a) computes weights / σp / RC50 share & absolute / A-share-value style-group risk on both 2-year and 1-year windows; (b) diffs each ETF's trend state against the previous run and flags upgrades (预备队启用) or degradations; (c) evaluates every target's gap and the five gates (state T3b/T4, **QDII premium ≤1.5%**, 2,000 元 minimum trade, 60% style-group cap, 3,000 元 cap) to produce the single legitimate order, lot-rounded — premium is read from etf detail (closePrice/nav/purchaseStatus) because a cross-border ETF at a high premium can lose 15%+ on premium convergence even if the underlying is flat; (d) checks drawdown / style / state triggers; (e) prints 无需动作 / 到季末该执行了 / 暂停复核, with --json and --save for archiving. Triggers on "周度复评"、"季定投"、"定投计划复评"、"这季该投吗"、"buy check"、"plan review".
---

# 季度定投计划 · 周度复评

## Overview

对**真实券商账户**的季度定投计划做例行检查，回答四个问题：

1. **组合现在偏离目标多少**——权重、σp、上证50 风险贡献（占比与绝对）、A股价值风格组风险（2 年／1 年双窗口）。
2. **谁的状态变了**——与上一次运行相比，哪只 ETF 升级（预备队可启用）或降级（当季改投）。
3. **这一季到底该买什么**——在四道门（状态门 / 最小交易额 / 风格组上限 / 单笔上限）下，唯一合法的下单指令与份数。
4. **有没有触发暂停/复核**——回撤 15%、风格组 60%、状态转弱。

**不预测行情、不给投资建议、不自动下单**，只做规则判定与下单计算。每周跑一次即可，**周中不交易**——额度按季释放。

## When to use

| 场景 | 命令 |
|------|------|
| 每周末例行复评 | `review.py` |
| 想知道"这季该投了吗、买哪只" | `review.py --quarter-end` |
| 需要机器可读结果 / 存档 | `--json` / `--save` |
| 成交后回填 | `review.py --mark-executed` |
| 数据源慢，只想看权重缺口 | 加 `--no-trend` |

## Prerequisites

- **westock-data CLI**：`~/.workbuddy/westock-data/scripts/index.js`；node 用 `find_node()` 自动定位（**勿硬编码版本号**，路径会漂移）。
- **Bash 调用必须 `dangerouslyDisableSandbox: true`**（网络访问）。
- Python 3（项目内用 `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`）。脚本**仅用标准库**，不依赖 numpy。
- 同项目 `etf-operation-plan/trend_analysis.py`（趋势状态机），由本脚本以子进程调用。

## Files

| 文件 | 作用 |
|------|------|
| `plan_state.json` | **唯一需要维护的配置**：持仓份额/成本/目标权重、现金、六条规则、季度执行标记、上次状态快照 |
| `review.py` | 主脚本 |
| `review_history.json` | `--save` 追加的指标历史（首次运行后生成） |

## 配置说明（plan_state.json）

```json
{
  "cash": 15300.80,
  "peak_value": null,
  "holdings": [
    { "code": "sh510050", "name": "上证50ETF华夏", "shares": 5200,
      "cost": 2.3381, "target_pct": 20.0, "locked": true,
      "role": "core-index", "note": "永久停止买入" }
  ],
  "style_group": ["sh510050", "sh512890"],
  "rules": {
    "quarterly_amount": 3000, "max_trade": 3000, "min_trade": 2000,
    "lot_size": 100, "style_group_limit_pct": 60.0,
    "drawdown_alert_pct": 15.0, "drawdown_recover_pct": 10.0,
    "cov_window_bars": 500, "cov_window_short_bars": 250,
    "gate_states": ["T3b", "T4"],
    "reserve_fill_states": ["T3b", "T4"],
    "fallback_nasdaq": ["sh513100", "sz159941", "sz159632", "sh513110"]
  },
  "executed": { "2026Q4": false }
}
```

- `holdings[].shares` 为**实际持有份额**，`cash` 为可用现金，两者之和＝总资产。
- `target_pct` 合计（含现金隐含 100 − Σ）应自洽；现金没有独立字段，由 100 − Σ 隐含。
- `locked: true` 的标的**永不买入**（当前是上证50，只靠新资金稀释）。
- **`cash` / `shares` 必须与实际券商持仓一致**——本 skill 不从 `records/etf/*.json` 反推（流水可能不完整）。
- 会计状态（`peak_value` / `last_states` / `last_run`）由脚本自动维护，不要手改。

### 七条执行规则（脚本内置，改规则改 `rules`）

0. **QDII 溢价门（最硬的一道）**：买入前查 `etf detail` 的 `closePrice / nav`，**溢价 > `max_premium_pct`（1.5%）一律不买**；折价不构成门槛（买入相对划算，仅提示）。跨境 ETF 在**不可申购**时套利资金进不来，溢价可持续也可突然收敛——按高溢价买入，标的不动也可能亏 15%。**所有纳指 ETF 共用同一底层，溢价会同步走高，换标的往往没用**。
1. 每季 3,000 元，单笔上限 3,000；缺口按 `目标权重 × 总资产 − 当前市值` 每季重算，**不跨季结转额度**。
2. **单笔 < 2,000 元跳过**（5 元最低佣金 = 0.25%，高于策略容忍度）。
3. 只买**状态合格**（`gate_states`）的标的，多头候选取缺口最大者，每季至多 1 只。**支持按标的重载**：`gate_overrides` 中的标的用各自的状态集——当前黄金 `sh518880` 放宽到 `T1` 及以上（它是不付溢价的唯一分散腿），T0 仍禁，不接飞刀。
4. **风格组 60% 上限只约束同因子标的**（`style_group` 内的红利类）；**低相关腿（纳指/标普/黄金）不受此限**——它们的作用就是把该组占比压下去，若也受限则规则自我否定。
5. **双窗口判定**：2 年与 1 年窗口的风格组风险**都**低于 60% 才放行红利类。
6. 兜底（可选，当前未启用）：当季无成交时买分散腿 2,000～3,000 元，受三条保护约束（距 52 周低 <5% 不触发、回撤暂停期不触发、缺口 <2,000 不触发）。

### 空仓等待与恢复（当前生效）

当没有任何标的过门时，本季 **3,000 元并入现金**，进入"空仓等待"，**恢复策略为"任一条件成立"**：

| 条件 | 判定 | 说明 |
|---|---|---|
| **A 溢价收敛** | 任一纳指 ETF（`fallback_nasdaq` 四只）溢价 ≤ `max_premium_pct` | 溢价收敛后纳指仍要过状态门（当前 T4） |
| **B 黄金转 T1** | 黄金状态 ∈ `gate_overrides` 允许集 且 溢价合理 | 黄金当前折价，一旦转 T1 立刻可买 |

⚠ **A 的陷阱**：溢价若靠价格下跌而收敛，纳指的 T4 可能同时失效——恢复时必须重判状态，不能看到"溢价<1.5%"就直接下单。

复评输出会打印【等待恢复】段，逐条给出距离（还需回落多少 pp、当前是什么状态），用于观察进展。

## Workflow

### Step 1（仅当成交/持仓变化时）更新配置

- 买入成交 → `holdings[].shares` 增加，`cash` 减少（金额＋费用）。
- 卖出成交 → `cash` 增加，`shares` 减少。
- 成交后跑 `review.py --mark-executed` 把本季标记为已执行（它只改标记，**不改进份额**，仍要手动改 Step 1）。
- 同步把成交记入 `records/etf/*.json` 流水，与本配置互为校验。

### Step 2 运行

```bash
PY="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
SK=".workbuddy/skills/etf-quarterly-plan-review"
$PY $SK/review.py                    # 周度复评
$PY $SK/review.py --quarter-end      # 季末执行模式
$PY $SK/review.py --save --json      # 存档 + 机器可读
```

> Bash 调用需 `dangerouslyDisableSandbox: true`。

### Step 3 解读输出

| 段落 | 看什么 |
|------|--------|
| 【组合】 | 仓位、现金占比。现金持续 >35% 说明合格标的太少，不是执行不到位 |
| 【风险】 | **RC50 占比**（份额）与**绝对贡献**（占比×σp）要一起看，单独看占比会被"加高波动资产"机械稀释 |
| 【标的】 | `可买` ＝ 五道门全过；否则显示被哪道门挡住（锁定/状态门/风格组/已达标/溢价）。溢价列带 `!` 表示超限 |
| 【溢价】/【折价】 | 溢价 >1.5% 列黑名单（含**已持仓**，用于判断"预备队补缺口"该不该补）；折价仅作参考 |
| 【状态变化】 | 周度复评的核心增量。升级到 T3b/T4 → 预备队可补；降级出 T3b/T4 → 当季改投 |
| 【本季】 | 已执行？距季末几天？此刻执行会买什么、多少份、多少钱 |
| 【等待恢复】 | 空仓时出现。条件 A（溢价收敛）／B（黄金转 T1），任一满足即恢复，附当前差距 |
| 【触发】 | 🟢 状态恢复 / 🟠 风格组超限 / 🟠 状态转弱 / 🔴 回撤 → 按提示动作 |
| 【结论】 | 无需动作 / 季末执行 / 暂停复核 |

### Step 4 执行

只有 **`--quarter-end` 且未执行** 才下单。下单前：

1. 用**收盘价**重跑一次（盘中 bar 会让 T3b/T4 边界抖动）。
2. QDII（纳指/标普）**查溢价**，>1.5% 换 `fallback_nasdaq` 里最低的一只；4 只全超 → 当季留现金。
3. 份数取整到 100 的倍数，金额 ≤3,000 且 ≥2,000。

## 与报告的关系

- 报告 `reports/etf/allocation/20261021-季定投计划.html` 是**决策存档**（含甲/丙路径、债券口径、窗口敏感性等论证），本 skill 是**执行监控**。
- 报告里数字是某一时点的快照；脚本**每次实时重算**，因此 σp、RC50 会有 ±0.5pp 的漂移（价格变动 + 窗口滚动），**属正常**，不要当成矛盾。
- 若报告规则变了，先改 `plan_state.json` 的 `rules`，再同步更新 SKILL.md 第六节的规则描述。

## Important Notes

- **周中不交易**：额度按季释放。周度复评只用于发现状态变化与提前识别风险。
- **状态机口径**：`trend_analysis.py` 返回 `T3` + `sub_state=T3b`，脚本用 `eff = sub or code` 做门判定；**不要**用 `T3` 直接比 `T3b`。
- **⚠ 跨境 ETF 的 T 码会被溢价污染**：状态机吃的是场内价格，而 QDII 场内价 = 净值 + 溢价。实测 513100 在 2026-10 被判 T4「中期上升确认」，但同期净值仅 +8%、价格 +22.9%，用底层指数（`kline usNDX`）跑出来是 **T6 信号混合**。**对跨境 ETF，T 码只能当参考，真实趋势要用净值或底层指数复核**；溢价门才是第一道闸。
- **溢价会污染协方差**：RC50 / σp / 相关性同样用场内价格算，QDII 的溢价波动会抬高波动率、扭曲相关性。当前未改用净值序列，属已知偏差。
- **状态机降级有 pending 确认期**，单日跳变不会立刻改判；这也是本 skill **不另设价格止损**的原因——价格止损会与规则 3 互相抵消（跌破 MA60 时规则 3 已禁买，缓冲轮不到生效）。
- **周末运行**：周六/周日跑时最新 K 线是周五收盘，`bar_date` 会显示周五日期，属正常。
- **数据源限流**：报价缺失会直接报错退出（不静默降级）。重试即可；`--no-trend` 可跳过 5 次趋势计算加快。
- 涨跌配色遵循 A 股习惯（红涨绿跌）。非投资建议。
