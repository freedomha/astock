---
name: etf-operation-plan
description: Generate a medium-term (multi-week to ~6 months) operation plan for A-share ETFs anchored on a trend-state machine (T0-T8, with T3a/T3b) using complete-week direction, asset-type-specific drivers with mandatory source citation, and a five-gate decision framework that hard-constrains actions by trend state (no auxiliary pattern may override the primary trend). Outputs a focused HTML report with data status (daily vs weekly completeness), multi-caliber position state, trend state + migration, scenario framework, observation zones, layered exits, and re-evaluation triggers. Triggers on requests like "持仓接下来怎么操作", "帮我做操作计划", "XXETF接下来怎么做", "看看持仓怎么调整".
---

# ETF Operation Plan（ETF操作计划）

## Overview

Generate an actionable medium-term operation plan for A-share ETFs. Unlike `etf-deep-analysis` (comprehensive thesis-driven research), this skill answers **"how should I manage this position over the coming weeks-to-months?"**, anchored to current position data.

**核心设计原则（v3）**：

1. **趋势状态是主决策层，且不可被辅助层覆盖** — 五种底部形态降级为辅助证据。操作建议首先由中长期趋势状态决定，形态评分只做微调，**严禁**出现「趋势 T0 却因箱体/碗底分数高而低吸」的矛盾。动作由**硬约束矩阵**（见下）强制。
2. **周线定方向，日线定执行，盘中报价只决定触发提醒** — 周线判断使用**最后一个完整自然交易周**，当前未完成周仅作「预览」，不触发 T3/T4/T7/T8 的最终迁移。
3. **状态机 + 防抖动** — 趋势状态有历史持久化与合法迁移规则，避免周线边界来回切换；普通升级需连续 2 个完整周线确认。
4. **不同资产类型用不同驱动模板，且新闻必须可追溯** — 先识别资产类型（并区分商品期货 ETF 与商品/农业股票 ETF），再加载对应驱动；每个外部事实必须带来源证据，无来源时降级为「无充分可验证驱动」。
5. **五层门控** — 数据门 → 趋势门 → 资产逻辑门 → 风险收益门 → 组合门，逐层过滤后才生成操作计划。

**Output:** `reports/etf/operation/{YYYYMMDD}-{ETF简称}-操作建议.html`

## Prerequisites

- `westock-data` for ETF price/K-line data
- `score_patterns.py` (bundled) — five-pattern technical scoring, **auxiliary layer**
- `trend_analysis.py` (bundled) — trend-state machine (T0-T8 + T3a/T3b) + weekly features + state persistence, **primary layer**
- `operation_engine.py` (bundled) — machine-readable action decision with 3 program-level validations, **execution layer**
- `WebSearch` for asset-type-specific news/catalysts（必须记录来源）
- `records/portfolio_config.json` — 组合配置（可选；缺失时只输出百分比动作，不输出绝对金额）

## Trend-State Model（主决策层）

`trend_analysis.py` 分类出九态（T3 含 T3a/T3b 子态），并输出状态机迁移信息。

| 状态 | 名称 | 含义 |
|------|------|------|
| T0 | 长期下降 | 周线向下 + 空头排列 + 低点降低 |
| T1 | 下降减速 | 周线仍向下，但日线下跌减速或反弹 |
| T2 | 底部构建 | 近低位 + 低点抬高，筑底中 |
| T3a | 反转初步确认 | 价格结构转强，但 MA60 仍下行 |
| T3b | 反转初步确认 | 价格结构转强，MA60 走平或转上 |
| T4 | 中期上升确认 | 多头排列 + MA60/120 向上 + HH/HL + 周线向上 |
| T5 | 上升加速 | T4 基础上动量强劲、扩张 |
| T6 | 高位整理 | 近高位、动量走平 |
| T7 | 趋势衰竭 | 高位滞涨/动能背离 |
| T8 | 结构破坏 | 周线结构失效，中期逻辑破位 |

### 硬约束矩阵（动作由趋势状态强制决定，报告层不得自由覆盖）

| 状态 | 核心仓位 | 战术仓位 | 禁止动作 |
|------|---------|---------|---------|
| T0 | 降低或退出 | **禁止新增** | 低吸、补仓、摊低成本、增加核心仓、维持核心仓并加仓 |
| T1 | 观察或降低 | **禁止新增** | 低吸、补仓、摊低成本、把反弹当反转加仓 |
| T2 | 原核心仓可观察 | 仅小额试仓 | 重仓抄底 |
| T3a | 维持为主 | 小额、等待回踩 | 积极加仓 |
| T3b | 维持 | 可分批增加 | 追高 |
| T4 | 维持 | 回踩增加 | 追高 |
| T5 | 维持 | 不追高 | 追高 |
| T6 | 维持或降战术仓 | 不新增 | 追高 |
| T7 | 保护收益、降低 | 减少 | 任何新增 |
| T8 | 降低或退出 | **禁止新增** | 任何新增 |

**例外模式**：T0/T1 若要输出「低吸/补仓/加仓」，必须显式进入例外模式，并写出：例外原因、最大风险预算、退出条件。默认不启用。

**强制校验**（生成报告前必须自查）：
```python
if trend_state in ("T0", "T1"):
    prohibit = {"低吸", "补仓", "摊低成本", "增加核心仓", "维持核心仓并加仓"}
    # 操作计划不得出现上述任何动作，除非显式声明例外模式
```

### 状态机与合法迁移

`trend_analysis.py --state-file <path> --save-state` 持久化每只 ETF 的上一次状态与连续周数。输出：

| 字段 | 含义 |
|------|------|
| previous_state | 上次状态 |
| effective_state | 本次生效状态（应用迁移规则后） |
| consecutive_weeks | 连续保持周数 |
| migration_type | initial / same / normal_advance / jump / degradation / breakdown / blocked |
| confirmation | confirmed / pending |
| note | 迁移说明 |

迁移规则：
- 生命周期 `T0→T1→T2→T3→T4→T5→T6→T7→T8`
- **普通升级**：连续 2 个完整周线确认
- **进入 T8**：重大破位，立即降级生效
- **T0 直接跳 T4/T5**：原则上禁止（逐级确认）
- **T7 恢复 T4**：必须经 T6 或满足特别恢复条件
- 状态切换有防抖动：未达到连续确认要求时，保持上一状态（`pending`）

### 周线数据完整性

`data_quality` 拆两个字段：
```json
{"daily_bar_status": "complete", "weekly_bar_status": "incomplete_current_week"}
```

- `daily_bar_status`：`intraday`（盘中）或 `complete`（收盘后）
- `weekly_bar_status`：`complete`（最后一根日线为周五且非盘中）或 `incomplete_current_week`（周中运行，当周未完成）

趋势主判断（周线斜率、10/20/40 周均线、周线突破/失效、T0-T8 分类）**只用最后一个完整自然交易周**。当前周数据仅作为 `weekly.preview`「预览状态」，**不得**直接触发 T3/T4/T7/T8 的最终迁移（重大结构破坏除外）。

## Asset Type & Driver Templates（模块 3）

**必须先识别资产类型，再加载对应驱动**。识别时**必须看跟踪指数与成分权重，不能只看基金名称关键词**。

### 资产类别与暴露映射

区分四类，避免把商品价格直接当作股票 ETF 的强催化：

| 资产类别 | `asset_class` | 说明 |
|----------|---------------|------|
| 商品现货/期货 ETF | `commodity_futures_etf` | 直接持有期货/现货（如黄金、豆粕、原油） |
| 商品生产商股票 ETF | `equity_sector_etf`（commodity producer） | 持有上游资源股 |
| 农业产业链股票 ETF | `equity_sector_etf`（agri chain） | 持有种业/加工/贸易等产业链公司 |
| 主题概念 ETF | `theme_etf` | 概念主题，成分与名称直觉可能不一致 |

每个非现货 ETF 必须输出暴露映射：
```json
{
  "asset_class": "equity_sector_etf",
  "theme": "grain_industry",
  "direct_commodity_exposure": "low_or_indirect",
  "main_transmission_channels": ["input_cost", "product_price", "inventory_gain_loss", "policy"]
}
```
注意：商品价格上涨对农业/商品股票**不总是单向利好**——原料型企业成本上升、种业/上游受益、加工企业毛利承压。驱动分析必须先查跟踪指数和成分权重。

### 驱动模板

| 资产类型 | 中长期主要关注点 | 驱动搜索模板 | 建议基准 |
|----------|------------------|--------------|----------|
| 黄金 | 金价、实际利率、美元、人民币汇率、跟踪误差 | 金价、实际利率、美元 | 人民币黄金现货或跟踪标的 |
| 债券 | 利率曲线、久期、信用利差 | 利率、国债收益率、货币政策 | 对应久期债券指数 |
| 商品(现货) | 期现结构、展期收益、库存、供需 | 库存、供需、期现价差 | 商品指数 |
| 跨境 | 底层指数、汇率、时区差、溢折价、额度 | 底层指数、汇率、溢折价 | 底层指数 + 汇率 |
| 红利 | 股息稳定性、利率环境、行业集中度 | 股息率、利率环境 | 宽基 + 红利母指数 |
| 宽基 | 盈利周期、估值、流动性、风险偏好 | 盈利增速、估值分位、流动性 | 沪深300或中证全指 |
| 行业 | 行业盈利、政策、供需、库存、产能 | 景气度、政策、供需、库存 | 中证全指 + 一级行业指数 |

### 相对强弱的基准要求

`trend_analysis` 支持可选 `--benchmark-file`。**有基准**才可称为「相对强弱」；**无基准**时只能输出「自身动量改善」（`relative_strength.self_momentum`），不得称「相对强弱改善」。

## 催化剂证据结构（强制引用与事实校验）

报告中的每个外部事实必须附带结构化来源。**没有结构化来源时，只允许输出**：

> 当前未取得足够可验证的宏观驱动数据，操作判断以价格趋势为主。

```json
{
  "claim": "实际利率下降有利于黄金",
  "source_title": "...",
  "publisher": "...",
  "published_at": "...",
  "retrieved_at": "...",
  "url": "...",
  "evidence_type": "hard_data | soft_opinion | risk_event",
  "asset_link": "direct | indirect | unrelated",
  "freshness_days": 3,
  "verified_by_second_source": true
}
```

**新闻不作为交易触发器**，只作为：趋势解释、风险提醒、复评触发器。禁止「看到利好新闻就把 T0 改成低吸」。

## 风险边界（波动率自适应，替代「结构位下方 2%」）

不同资产波动差异大，固定 2% 不等价。结构失效位缓冲用：

```python
buffer = max(tick_size * n, atr20 * atr_multiplier, structural_level * minimum_pct)
```

并配合「连续 N 日收盘确认」或「完整周线确认」。`trend_analysis` 已输出 `volatility.atr20` 供计算。

- 价格距离：用 ATR 或实现波动率归一化
- 结构破位：价格位 + 0.5~1.0 ATR 缓冲
- 均线转向：斜率除以同期波动率
- 突破确认：收盘突破 + 持续期 + 成交量完整性

## 五层门控决策框架

操作计划必须依次通过五层门，任一层不过即降级输出。

### Gate 1：数据门
以下任一情况**禁止新增仓位建议**（输出「仅观察，不生成新增仓位动作」）：
- K 线不足（<120 日）
- 当前周未完成且状态刚切换
- 行情时间异常
- 新闻没有来源
- 跟踪标的无法确认
- 价格或成交量存在异常跳点

### Gate 2：趋势门
见「硬约束矩阵」。趋势状态直接决定核心/战术仓位动作与禁止动作。

### Gate 3：资产逻辑门
不看是否有利好新闻，判断：
1. 底层驱动是否仍成立
2. 是否直接作用于 ETF 成分（经暴露映射）
3. 是否已被价格计入
4. 是否与技术趋势一致

### Gate 4：风险收益门
只有 `目标观察区空间 / 结构失效风险 >= 2` 才输出「增加战术仓」。不足时：即使趋势向上，也只持有，不新增。

### Gate 5：组合门
- **单标的模式**：只判断该持仓内部动作（默认）
- **组合模式**：加入总资产、目标权重、风险预算、相关性后，才能判断「是否重仓 / 加 20% / 行业集中度 / 黄金超配 / 共同风险暴露」

缺少组合总资产或目标仓位时，**不得输出「加仓 20% 总资产」**，只能输出「相对目标仓位的动作」。

## 组合配置（区分目标仓位与当前仓位）

交易流水（`records/etf/*.json`）只有份额与成本，不含总资产、目标权重、风险预算。为输出绝对买卖数量，需独立配置 `records/portfolio_config.json`：

```json
{
  "portfolio_value": 100000,
  "max_portfolio_drawdown_pct": 10,
  "positions": {
    "sh518880": {"role": "core_hedge", "target_weight_pct": 10, "max_weight_pct": 15, "risk_budget_pct": 0.8},
    "sh512710": {"role": "tactical", "target_weight_pct": 5, "max_weight_pct": 8, "risk_budget_pct": 0.5}
  }
}
```

据此计算：

```
目标市值 = 组合总资产 × 目标权重
仓位缺口 = 目标市值 − 当前市值
单次可买金额 = min(仓位缺口 × 当前状态增仓比例, 本次最大风险预算 / 单份价格风险)
单份价格风险 = 计划买入价 − 结构失效价
最大风险预算 = 组合总资产 × 本标的风险预算比例
```

**无配置时**：只输出明确价位与「目标仓位百分比动作」，**不生成绝对买卖份额**。

## 操作引擎（机器可判定的六项输出）

每份报告最终输出六项**机器可判定字段**，由 `operation_engine.py` 计算，报告正文只解释、不另行生成结论：

```yaml
current_action: HOLD | ADD | REDUCE | EXIT | WAIT
action_reason: 当前生效趋势状态及核心证据
trigger_condition: 触发动作的可计算条件（增/减/退，各带 order size）
order_size: 本次调整占目标仓位的比例（有组合配置时附绝对金额）
invalidation_condition: 本次操作逻辑失效条件
next_review_trigger: 下一次重新计算条件
```

不要只输出「回踩增加 / 跌破后减少 / 趋势转强后再买」，必须落到可执行条件与具体比例。示例：

```
当前动作：不新增，维持现有仓位
增加条件（全部满足）：完整周线由 T2/T3a 迁移为 T3b；MA60 斜率走平或转正；
  日线回踩 MA20/MA60 后收盘重新站回；reward/risk >= 2
  满足后首次增加目标仓位 20%；第二周继续确认且未明显扩张，再增加 20%
降低条件：连续两日收盘低于结构失效位 → 降低战术仓 50%
退出条件：完整周线进入 T8 或跌破灾难保护位 → 退出剩余战术仓（核心仓由组合用途决定）
```

## 三道程序级强制校验（代码执行，非报告声明）

`operation_engine.py` 强制执行，任一失败即降级动作：

### 1. 动作合法性校验
```python
validate_action(effective_state, position_role, proposed_action)
# T0 + ADD => 拒绝；T1 + AVERAGE_DOWN => 拒绝；T5 + CHASE => 拒绝；
# T7 + ADD => 拒绝；T8 + ADD => 拒绝
```

### 2. 风险收益校验
```python
reward = first_observation_price - planned_entry
risk = planned_entry - structural_invalidation_price
rr = reward / risk          # 仅 rr >= 2 才允许增加战术仓
```

### 3. 仓位数量校验
```
建议买入金额 <= 目标仓位缺口
建议买入金额 <= 单次增仓上限
预计损失 <= 单标的风险预算
调整后权重 <= 最大权重
```
任一失败 → 自动降级为 HOLD 或减少下单数量。

## 今日操作卡（HTML 顶部必含）

每份 HTML 顶部先给「今日操作卡」，不让用户从十章节找结论：

```
今日操作卡
当前状态：T1 下降减速，effective，持续 2 个完整周
当前动作：持有，不新增
已有仓位：300 份，当前占目标仓位 60%
增加触发：完整周线进入 T3b 且日线回踩 MA60 后重新站稳 → 首次增加目标仓位 20%
降低触发：连续 2 日收盘低于 MA60 → 降低战术仓 25%
退出触发：完整周线进入 T8，或单日收盘跌破灾难保护位超过 1 ATR
禁止动作：T1 不追高、不补仓、不因新闻增加仓位
下次复评：周五收盘后，或提前触及上述触发位
```

趋势、形态、基本面、新闻全部用于**解释这张卡**，不得让报告正文重新自由生成不同结论。

## Workflow

### Step 1: Identify Target ETF(s)

读 `records/etf/*.json`。每文件 `{ETF简称}{code}.json` 只存 `name`/`code`/`trades[]`。**`records/etf` 是纯交易流水，绝不回写现价/盈亏/止损位**。

```json
{"date": "2026-08-05", "action": "buy", "price": 8.637, "shares": 300, "amount": 2591.10}
```

### Step 2: Fetch Real-Time Data

```bash
WD="/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data"
NODE="/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
$NODE $WD/scripts/index.js quote <code> --raw > /tmp/op_quote.json
$NODE $WD/scripts/index.js kline <code> --period day --limit 250 --raw > /tmp/op_kline.json
```
（westock-data 必须 `dangerouslyDisableSandbox: true`）

### Step 3: Trend-State Machine（PRIMARY，含周线完整性）

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
STATE=".workbuddy/skills/etf-operation-plan/trend_state_history.json"
$PYTHON .workbuddy/skills/etf-operation-plan/trend_analysis.py \
  --code <code> --kline-file /tmp/op_kline.json \
  --state-file $STATE --save-state > /tmp/op_trend.json
# 盘中加 --intraday；有基准加 --benchmark-file <bench.json>
```

提取：`trend_state`（含 `sub_state`）、`data_quality`（daily/weekly bar status）、`weekly`（含 `preview`）、`ma`、`structure`、`relative_strength`（`self_momentum` vs `benchmark`）、`state_machine`（迁移信息）。

**当 `weekly_bar_status == "incomplete_current_week"`**：趋势判断以 `weekly`（完整周）为准，`weekly.preview` 仅作提示，不触发最终迁移。

### Step 4: Five-Pattern Scoring（AUXILIARY）

```bash
$PYTHON .workbuddy/skills/etf-operation-plan/score_patterns.py \
  --code <code> --kline-file /tmp/op_kline.json > /tmp/op_scores.json
```
输出每种形态：是否检测到、形成阶段、是否确认、失效位置、证据原因、冲突信号。不比较绝对分数，不把多个相关底部形态当多份独立证据。**形态分不可覆盖趋势状态动作**（见硬约束矩阵）。

### Step 5: Asset-Type Drivers（必须带来源）

按资产类型模板 WebSearch，每个事实记录 `catalyst_evidence`（来源标题/机构/发布时间/抓取时间/URL/类型/资产关联/新鲜度/是否交叉验证）。无来源则降级输出「无充分可验证驱动」。

### Step 6: Position Metrics（多成本口径）

```python
import json, glob, os
def load_positions(records_dir="records/etf"):
    positions = []
    for path in sorted(glob.glob(os.path.join(records_dir, "*.json"))):
        rec = json.load(open(path))
        shares = 0; book = 0.0; invested = 0.0; recovered = 0.0; realized = 0.0
        for t in rec.get("trades", []):
            if t["action"] == "buy":
                invested += t["amount"]; book += t["amount"]; shares += t["shares"]
            elif t["action"] == "sell":
                avg = book / shares if shares > 0 else 0.0
                realized += (t["amount"] - avg * t["shares"])
                book -= avg * t["shares"]; recovered += t["amount"]; shares -= t["shares"]
        if shares > 0:
            positions.append({"code": rec["code"], "name": rec["name"], "shares": shares,
                              "book_avg_cost": book/shares,
                              "break_even": (invested-recovered)/shares,
                              "realized_pnl": realized})
    return positions
```
输出五项：剩余份额、账面持仓均价、资金回本价、已实现盈亏、未实现盈亏（= (现价−账面均价)×份额）、总盈亏。

### Step 7: Key Levels & Layered Exits（模块 5）

关键位：S1(60日低)/S2(120日低)/R1(60日高)/R2(120日高)/MA60/MA120/250日位置/成本锚/结构支撑位。

三层退出（**不用 52 周低点作统一硬止损**）：

| 层级 | 用途 | 动作 |
|------|------|------|
| 趋势观察位 | 接近时提高观察频率 | 不立即交易 |
| 结构失效位 | 中期高低点结构/重要区间被破坏 | 降低战术仓位 |
| 灾难保护位 | 极端行情最终退出 | 降低核心仓位/清仓 |

结构失效位 = 结构支撑 + 波动率缓冲（`buffer` 公式）+ 收盘确认 + 持续时间确认。**避免仅因盘中瞬间跌破而清仓**。

### Step 8: Scenarios（1-3 个月，无未经校准概率）

| 情景 | 触发条件 | 动作 |
|------|----------|------|
| 主场景 | 延续当前趋势状态 | 对应硬约束矩阵动作 |
| 备选场景 | 相邻状态迁移 | 调整战术仓位 |
| 失效场景 | 结构失效位破坏/资产逻辑失效 | 降低核心仓位 |

每情景附：确认条件、失效条件、仓位后果、**证据强度（高/中/低）**、**数据完整度（高/中/低）**。**不输出未经回测校准的百分比**。

### Step 9: Decision Matrix（模块 6，经五层门控 + 三道程序校验）

调用 `operation_engine.py` 输出机器可判定六项字段（`current_action`/`action_reason`/`trigger_conditions`/`order_size`/`invalidation_condition`/`next_review_trigger`），并强制执行三道校验（动作合法性 / 风险收益 / 仓位数量）。

```bash
$PYTHON .workbuddy/skills/etf-operation-plan/operation_engine.py \
  --state T1 --role core_hedge --code sh518880 \
  --config records/portfolio_config.json \
  --shares 300 --book-cost 8.637 --price 9.042 \
  --invalidation 8.16 --entry 8.75 --observation 9.44 --atr20 0.126 --ma60-dir down
```

| 维度 | 输出 |
|------|------|
| 趋势状态 | T0-T8 + 子态 + 迁移信息 |
| 方向 | 看多/中性/看空（多周期） |
| 核心逻辑 | 一句话验证中长期逻辑 |
| 仓位动作 | HOLD/ADD/REDUCE/EXIT/WAIT（引擎决定，受三道校验） |
| 战术仓位动作 | 回踩加/突破减/观望（受硬约束矩阵） |
| 持有期 | 多周至 ~6 个月 |
| 具体操作 | 触发价 + 分批定量（绝不一把梭） |
| 观察区间 | 3-6 个月目标观察区（见 Step 10） |
| 下次复评 | 复评条件（见 Step 11） |

### Step 10: Target Observation Zones（模块 8，3-6 个月）

不给单一目标价，给「第一观察区/第二观察区/趋势跟随退出条件」。方法可追溯：
1. 前期中长期压力区（120/250 日高点或成交密集区）
2. 箱体量度空间
3. W 底/头肩底量度空间
4. 波动率区间（±N×ATR）
5. 风险收益比约束（≥1:2 才值得战术加仓）

方法不一致时输出区间并降置信。风险收益门（Gate 4）校验：`目标空间 / 结构失效风险 >= 2`。

### Step 11: Re-Evaluation（模块 7）

四类复评：定期（月度/完整月线形成后）、事件（重大政策/指数调整/利率汇率变化）、价格（触支撑/压力/失效位）、趋势（周线状态变化/MA120 方向变化/相对强弱反转）。

### Step 12: Generate HTML Report

保存到 `reports/etf/operation/{YYYYMMDD}-{ETF简称}-操作建议.html`。两阶段 f-string（CSS/JS 字面花括号用 `{{`/`}}`）。

**HTML 结构**：
- **顶部「今日操作卡」** — 当前状态、当前动作、已有仓位（占目标仓位%）、增加/降低/退出触发（带 order size）、禁止动作、下次复评、程序校验摘要
- **正文 10 节**（仅解释今日操作卡，不另行生成结论）：
1. **数据状态** — 行情时间、最后完整交易日、daily_bar_status、weekly_bar_status、是否含盘中数据、K线数
2. **持仓状态** — 剩余份额、账面均价、资金回本价、已实现/未实现/总盈亏、相对目标仓位
3. **ETF属性和核心驱动** — 资产类型（含暴露映射）、跟踪标的、驱动、风险变量、驱动状态、**catalyst_evidence 来源**
4. **中长期趋势状态** — 周线趋势（完整周）、日线趋势、均线排列与斜率、高低点结构、相对强弱/自身动量、回撤与波动、**状态机迁移信息**
5. **技术结构和形态** — 支撑/压力区、突破/失效位（含波动率缓冲）、五形态辅助评分、冲突说明
6. **未来1-3个月情景** — 主/备选/失效 + 确认/失效条件 + 证据强度与数据完整度
7. **操作计划** — 仓位动作（核心/战术/预留，受硬约束矩阵）、分批触发、不应采取的动作、最大可接受风险
8. **未来3-6个月观察区间** — 第一/第二观察区 + 计算方法 + 趋势跟随退出
9. **下次复评条件** — 定期/价格/趋势/事件
10. **风险和限制** — 数据限制、模型限制、未校准指标、组合配置提醒、免责

**Style**：红涨绿跌（`.up #c0392b` / `.down #27ae60`）、浅色背景、ECharts、卖方标签、章节「一、二、…」。

**JS 语法检查（交付前强制）**：抽取 `<script>` 块 → `node --check`，零错误才交付。

### Step 13: Present Report

交付路径 + 聊天摘要（ETF、趋势状态+迁移、方向、具体操作）。不粘贴 HTML。

## Multi-ETF Handling

多 ETF：每只依次走 Step 2-12；数据抓取与新闻搜索可并行；每只独立 HTML。

## Important Notes

- A 股红涨绿跌；非投资建议；数据源 westock-data + WebSearch
- **趋势状态是主决策层，硬约束矩阵不可被形态分覆盖**（T0/T1 禁止低吸/补仓/摊低成本）
- **周线用完整自然交易周**，当前周仅预览
- **状态机防抖动**：普通升级需连续 2 周确认，T8 破位立即生效
- **新闻必须带来源**，无来源降级输出；新闻不作交易触发器
- **区分商品期货 ETF 与商品/农业股票 ETF**，看跟踪指数与成分权重
- **相对强弱需明确基准**，无基准只称「自身动量」
- **风险边界用波动率自适应**，不用固定 2%
- **五层门控**：数据→趋势→资产逻辑→风险收益→组合
- 复评四类触发，非「每月一次」
- **动作由 `operation_engine.py` 决定**：六项机器可判定字段 + 三道程序校验（动作合法性/风险收益/仓位数量），任一失败自动降级
- **今日操作卡是最终结论**，HTML 顶部必含，正文只解释
- `records/etf` 仅存交易流水；`records/portfolio_config.json` 存组合配置（总资产/目标权重/风险预算），缺失时只输出百分比动作
- 操作计划写入 HTML 或 memory
- westock-data Bash 必须 `dangerouslyDisableSandbox: true`
- 状态持久化文件：`.workbuddy/skills/etf-operation-plan/trend_state_history.json`（每次运行 `--save-state` 更新）
