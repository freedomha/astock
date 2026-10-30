---
name: etf-quarterly-plan-review
description: Use when the user wants to review the quarterly contribution plan (季度定投计划 / 季定投复评 / 每周复评 / 该投了吗 / 检查定投计划), or asks whether this quarter's 3,000 元 contribution should be deployed and where. Reads plan_state.json (holdings with shares/cost/target weights, cash, rules, executed-quarter flags) plus the frozen V1 spec (v1_spec.json / V1-SPEC.md), pulls live quotes and 500-day klines from westock-data, delegates trend states to etf-operation-plan/trend_analysis.py **as a descriptive feature only**, then: (a) computes weights / σp / RC50 share & absolute / A-share-value style-group risk on both 2-year and 1-year windows; (b) scores every candidate with the frozen V1 model — Trend 30 + Momentum 30 + Risk 20 + Diversification 20 = 100, where Diversification is the RC50 improvement per 1,000 元; (c) applies HARD GATES first (QDII premium ≤1.5%, portfolio drawdown, 60% style-group cap, 2,000 元 minimum trade, 3,000 元 cap) — these are reject-only and never scored; (d) then applies the threshold rule (absolute floor 60 AND max_score − 5) to decide buy vs cash, ranks survivors by score, picks the largest gap, lot-rounds; (e) prints 无需动作 / 到季末该执行了 / 暂停复核, with --json and --save for archiving; --legacy-gate falls back to the retired T0-T8 state gate for comparison. Triggers on "周度复评"、"季定投"、"定投计划复评"、"这季该投吗"、"buy check"、"plan review".
---

# 季度定投计划 · 周度复评

## Overview

对**真实券商账户**的季度定投计划做例行检查，回答四个问题：

1. **组合现在偏离目标多少**——权重、σp、上证50 风险贡献（占比与绝对）、A股价值风格组风险（2 年／1 年双窗口）。
2. **谁的状态变了**——与上一次运行相比，哪只 ETF 的 T 码升级或降级（**仅供参考**，不再决定买卖）。
3. **这一季到底该买什么**——硬门过滤 → V1 连续评分排序 → 阈值判定 → 唯一合法的下单指令与份数。
4. **有没有触发暂停/复核**——回撤 15%、风格组 60%。

**不预测行情、不给投资建议、不自动下单**，只做规则判定与下单计算。每周跑一次即可，**周中不交易**——额度按季释放。

## 判定架构（V1，2026-10-22 冻结）

```
HARD GATES（只做否决，不参与评分）
  ├ QDII 静态溢价 ≤ 5.0%（同指数取组内最低）
  ├ 回撤幅度 ≥15%（Drawdown ≤ −15%）→ 暂停；取总资产/持仓两口径更深者
  ├ 风格组（上证50+红利低波）风险 ≤ 60%（双窗口）
  ├ 数据质量 / 单笔 < 2,000 元
  ↓ PASS
SOFT SCORE（0–100，只负责排序）
  ├ Trend            30   价格对 MA60 溢价 + MA60/MA120 斜率
  ├ Momentum（钟形）  30   20/60/120 日收益，过热扣分
  ├ Risk Fitness     20   波动 + 回撤 + 跳涨
  └ Diversification  20   −ΔRC50 / 每 1,000 元
  ↓
Eligibility Floor 60 ＋ Candidate Band (max − 5)
  ↓
按分排序 → 缺口 → 买入 ≤ 3,000 元
```

**T0–T8 不参与买/不买判断**，只作为描述性特征写入输出。原因见
`reports/research/T-State-Validation-20261022.html` 与 `Gate-Redesign-20261022.html`：
T3b 的超额 64% 来自时间效应，剔除 2025Q3 后为 −0.52pp、2026 样本外 −1.46pp。

**完整公式、证据等级、变更管控见 `V1-SPEC.md`（本目录）。改动前必读第 6 节。**

## When to use

| 场景 | 命令 |
|------|------|
| 每周末例行复评 | `review.py` |
| 想知道"这季该投了吗、买哪只" | `review.py --quarter-end` |
| 需要机器可读结果 / 存档 | `--json` / `--save` |
| 要一份 HTML 报告（与本次判定同源） | `review.py --report` |
| 成交后回填 | `review.py --mark-executed` |
| 数据源慢，只想看评分与缺口 | 加 `--no-trend`（T 码留空，评分照算） |
| 对照/回滚到旧状态门 | `--legacy-gate` |

## Prerequisites

- **westock-data CLI**：`~/.workbuddy/westock-data/scripts/index.js`；node 用 `find_node()` 自动定位（**勿硬编码版本号**，路径会漂移）。
- **Bash 调用必须 `dangerouslyDisableSandbox: true`**（网络访问）。
- Python 3（项目内用 `/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3`）。脚本**仅用标准库**，不依赖 numpy。
- 同项目 `etf-operation-plan/trend_analysis.py`（趋势状态机），由本脚本以子进程调用——**仅用于展示 T 码，不影响买卖判定**。

## Files

| 文件 | 作用 |
|------|------|
| `plan_state.json` | **唯一需要维护的配置**：持仓份额/成本/目标权重、现金、规则、季度执行标记、上次状态快照 |
| `v1_spec.json` | **V1 冻结参数**（权重/公式阈值/变更管控）。机器可读，`v1_score.py` 启动时加载 |
| `V1-SPEC.md` | V1 规格说明书：公式、证据等级、变更流程、已知局限 |
| `v1_score.py` | 评分引擎：`features()` / `score()` / `select()`，纯函数，无网络 |
| `review.py` | 主脚本（取数 + 组合风险 + 评分 + 判定 + 输出） |
| `review_history.json` | `--save` 追加的指标历史（首次运行后生成）。每条带 `days_to_qe`（距季末交易日数）与 `is_decision_day`，用来区分监控记录与决策日 |

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

### 执行规则（硬门 0～2、4～5 ＋ 评分门 3）

**硬门（只做否决，不参与评分）**

0. **QDII 溢价门（最硬的一道）**：买入前查 `etf detail` 的 `closePrice / nav`，**溢价 > `max_premium_pct`（5.0%）一律不买**。
   **同指数多只 ETF 时只取组内（可申购优先）溢价最低者**（`premium_group_min`）：纳指组 9 只、标普组 4 只，定义在 `rules.premium_groups`。
   2026-10-22 由 1.5% 调为 5.0%，理由见 V1-SPEC 变更记录 v1.3；本次调参只允许一次，复评不早于 2027Q3（该比值为**静态溢价**：分母是最近一期已公布 NAV，QDII 净值滞后 1~3 个交易日、接口不返回净值日期，**不等于同日 IOPV**——用于风控筛查足够，不可当精确套利依据）；折价不构成门槛（买入相对划算，仅提示）。跨境 ETF 在**不可申购**时套利资金进不来，溢价可持续也可突然收敛——按高溢价买入，标的不动也可能亏 15%。**所有纳指 ETF 共用同一底层，溢价会同步走高，换标的往往没用**。
1. 每季 3,000 元，单笔上限 3,000；缺口按 `目标权重 × 总资产 − 当前市值` 每季重算，**不跨季结转额度**。
2. **单笔 < 2,000 元跳过**（5 元最低佣金 = 0.25%，高于策略容忍度）。
3. **Eligibility Floor ＋ Candidate Band（唯一决定「买不买」的一层）**：
   - 每个候选算 `Score = Trend 30 + Momentum 30 + Risk 20 + Diversification 20`；
   - **Eligibility Floor = 60**（绝对资格线）：`Score ≥ 60` 才可能买；
   - **Candidate Band = max − 5**（相对候选带）：在已过 Floor 的标的中，只保留 `Score ≥ max − 5` 的；
   - **评分层里只有 Floor 能产生「本季不买」**——但硬门在前一步就可以独立否决（今天的 4/5 就是硬门挡的）；Band 永远挡不住买入，只把候选集从 4 只收窄到约 2 只；
   - 通过硬门的标的按 Score 降序，分差 <1 时取缺口更大者，每季至多 1 只；
   - 60 / 5 是**预注册候选值**，只经过行为验证（会在最弱季度 2026Q1 挡住），**没有收益验证**。
4. **风格组 60% 上限只约束同因子标的**（`style_group` 内的红利类）；**低相关腿（纳指/标普/黄金）不受此限**——它们的作用就是把该组占比压下去，若也受限则规则自我否定。
5. **双窗口判定**：2 年与 1 年窗口的风格组风险**都**低于 60% 才放行红利类。
6. **数据质量**：报价缺失 / K 线不足 60 根 / 接口异常 → 本次评估作废（退出码 1），不静默降级。
L. **锁定（菜单政策）**：`holdings[].locked=true` 的标的不参与排序、不占候选名额，只能改配置文件解除。

**T 码（仅描述性，不参与判定）**

- 跨境 ETF 的 T 码用底层指数判定（`state_proxy`：`sz159941→usNDX`、`sh513500→usINX`），输出带 `※`；
- 升级/降级只写入【状态变化】供参考。**只有 `--legacy-gate` 时 T 码才恢复为门**（`gate_states` / `gate_overrides`）。

> **为什么废除状态门**：T3b 的 20 日超额 64% 来自时间效应（那些日子全市场都在涨），剔除 2025Q3 后为 −0.52pp、2026 样本外 −1.46pp；
> 且 5 只标的的菜单上 T-state 门 5 个季度只放行 1 次——它不只是在防止错误投资，也在阻止资产配置发生。详见两份研究报告。

### 空仓时看什么

V1 模式下没有「恢复条件」这个概念——每季独立按 `Score ≥ 60` 判定：分数够了就买，不够就留现金。
输出会打印【本季不买】+ 两条**观察项**（溢价距离、黄金状态），只用于解释"为什么现在没得买"，不是恢复门槛：

| 观察项 | 含义 |
|---|---|
| 纳指溢价 | 还需回落多少 pp 才可能进入候选（溢价是最常见的硬门否决原因） |
| 黄金 T 码 | 当前处于什么形态；**仅供理解输出，不再触发买入** |

`--legacy-gate` 下恢复为旧逻辑：A 溢价收敛 或 B 黄金转 T1，任一成立即恢复。

> **规则证据等级（2026-10-22 更新）**：
> - **A（数据支持）**：硬门 / 软分的职责划分（Risk 的 IC 为负但压波动、钟形动量优于单调、连续评分未翻符号）
> - **B（风控政策）**：溢价门、风格组、金额约束、回撤暂停
> - **C（待验证）**：阈值 60/5 的具体取值、Div 的 `full_at_pp=−0.15`、14:45 下单
>
> **状态门已从规则中移除**（T0-T8 降为描述性特征）。原「T3b +4.33pp、胜率 75.9%」是池化基准下的样本内数字，
> 剔除 2025Q3 为 −0.52pp、2026 样本外 −1.46pp；同日置换检验 p<0.002 说明它不是噪声，但强度只够当准入条件，不够当收益预期。
>
> **不在本 skill 范围内**：债券效率测算、8 季路径模拟。这些只存在于决策存档报告中。

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
$PY $SK/review.py --report           # 判定 + 生成 HTML 报告
$PY $SK/review.py --save --report    # 推荐：存档 + 出报告（本季决策存档）
```

> Bash 调用需 `dangerouslyDisableSandbox: true`。

`--report` 把**本次运行已经算好的快照**写成临时文件交给 `research/plan-v14/generate.py`（`--snapshot`），
不在生成器里二次取数——否则盘中重跑会让报告分数与控制台分数不一致。与 `--json` 同用时，报告路径打到 stderr，stdout 保持纯 JSON。

### Step 3 解读输出

| 段落 | 看什么 |
|------|--------|
| 【组合】 | 仓位、现金占比。现金持续 >35% 说明合格标的太少，不是执行不到位 |
| 【风险】 | **RC50 占比**（份额）与**绝对贡献**（占比×σp）要一起看，单独看占比会被"加高波动资产"机械稀释 |
| 【标的】 | `可买` ＝ **硬门全过 且 分数达阈值**；`分数不足` ＝ 硬门过了但 Score < 下限；其余显示被哪道硬门挡住（锁定/风格组/已达标/溢价）。溢价列带 `!` 表示超限 |
| 【评分】 | V1 分项明细。看三样：① 谁的分最高；② `ΔRC50` 是否为负（Div 是否饱和）；③ 阈值行给出的「候选需 ≥ X」 |
| 【溢价】/【折价】 | 溢价 >5.0% 列黑名单（含**已持仓**，用于判断"预备队补缺口"该不该补）；折价仅作参考 |
| 【状态变化】 | **仅供参考**（T 码已不参与判定）。`--legacy-gate` 下才恢复为「预备队可补 / 当季改投」 |
| 【本季】 | 已执行？距季末几天？此刻执行会买什么、多少份、多少钱 |
| 【本季不买】 | 空仓时出现，给出 `sel_note`（如「最高分 41.4 < 绝对下限 60」）+ 两条观察项 |
| 【触发】 | 🟠 风格组超限 / 🔴 回撤 → 硬门动作。T 码变化在 V1 模式**不触发** |
| 【结论】 | 无需动作 / 季末执行 / 暂停复核 |

### Step 4 执行

只有 **`--quarter-end` 且未执行** 才下单。下单前：

1. 用**收盘价**重跑一次（盘中 bar 会让 Trend / Momentum 分项与 T 码同时抖动）。
2. QDII（纳指/标普）**查组内全部候选溢价**，取最低的一只；最低者仍 >5.0% → 当季不买该腿。
3. 份数取整到 100 的倍数，金额 ≤3,000 且 ≥2,000。
4. 若当日分数与 `--quarter-end` 时相差 >5 分，以当日收盘重算为准（阈值是绝对分，会随价格移动）。

## 与报告的关系

- `review.py --report` 直接出报告，产物为 `reports/etf/allocation/<快照日期>-季定投计划-v14.2.html`（按日期命名，不覆盖历史存档）。
  生成器是 `research/plan-v14/generate.py`，它既可 `--snapshot <json>` 吃外部快照（`--report` 走这条），也可不带参数自己跑一次 `review.py --json`。
- 报告与 skill **同源**：报告里的每个数字都来自同一次 `review.py` 运行，不存在第二套口径。
- `reports/etf/allocation/20261021-季定投计划.html`（v13）是**旧规则的存档**，其中「规则 3 状态门」已被 V1 取代，引用时注意版本。
- `reports/research/T-State-Validation-20261022.html`：T3b 为什么被降级；`Gate-Redesign-20261022.html`：V1 的设计依据与七变体对抗。
- 本目录 `V1-SPEC.md` / `v1_spec.json` 是**生产口径的唯一来源**；研究目录的同名文件是研究快照，若冲突以本目录为准。
- 报告里数字是某一时点的快照；脚本**每次实时重算**，因此 σp、RC50 会有 ±0.5pp 的漂移（价格变动 + 窗口滚动），**属正常**，不要当成矛盾。
- 若报告规则变了，先改 `plan_state.json` 的 `rules`，再同步更新 SKILL.md 第六节的规则描述。

## Important Notes

- **周中不交易**：额度按季释放。周度复评只用于发现状态变化与提前识别风险。
- **状态机口径**：`trend_analysis.py` 返回 `T3` + `sub_state=T3b`，脚本用 `eff = sub or code`；**不要**用 `T3` 直接比 `T3b`。V1 模式下 T 码仅展示，`--legacy-gate` 才做门判定。
- **缺口分母**：用**投入后总资产**（当前总资产 + 当季 3,000），与报告判定表一致。用投入前的值会系统性低估缺口。
- **价格口径**：估值价格取 `etf detail` 的 `closePrice`（与净值同日），取不到才退回实时报价；否则同一标的会出现两个价格。
- **⚠ 跨境 ETF 的 T 码会被溢价污染**：状态机吃的是场内价格，而 QDII 场内价 = 净值 + 溢价。实测 513100 在 2026-10 被判 T4「中期上升确认」，但同期净值仅 +8%、价格 +22.9%，用底层指数（`kline usNDX`）跑出来是 **T6 信号混合**。**对跨境 ETF，T 码只能当参考，真实趋势要用净值或底层指数复核**；溢价门才是第一道闸。
- **溢价会污染协方差**：RC50 / σp / 相关性同样用场内价格算，QDII 的溢价波动会抬高波动率、扭曲相关性。当前未改用净值序列，属已知偏差。
- **评分随价格逐日变化**：阈值是绝对分（60），价格移动会改变分数。**季末以收盘价重算的结果为准**；周中分数只用于观察。
- **日频可以跑，但决策日固定**：`--save` 每天收盘后跑都行，记录里 `days_to_qe` 会递减；`days_to_qe==0` 那天才是决策日（`is_decision_day=true`）。
  不要在"分数首次穿线"的日子下单——那是另一套未注册的规则（回测 7 个季度里 5 个会给出不同标的/时点）。
- **Div 会饱和**：现金比例 31.7% 时，任意非上证50 标的的 ΔRC50 都在 −1.7~−2.3pp，远超 `full_at_pp=−0.15`，因此 Div 恒为 20。
  排序不受影响（同一常数），但**阈值 60 实际等价于核心分 ≥40**。现金降到 10% 以下前，Div 事实上是「非上证50」的门。
- **权重与阈值不得在样本内调整**：变更需满足 V1-SPEC 第 6 节（≥8 个新决策点 + 事前假设 + 另一段数据验证）。
- **周末运行**：周六/周日跑时最新 K 线是周五收盘，`bar_date` 会显示周五日期，属正常。
- **数据源限流**：报价缺失会直接报错退出（不静默降级）。重试即可；`--no-trend` 只跳过 T 码计算（评分仍算，需 K 线）。
- **`--legacy-gate` 的用途**：回滚与对照，不是并行策略。若连续 8 个季度 M2（MA200+双动量+ΔRC）不劣于 V1，才讨论替换（见 V1-SPEC 第 5 节）。
- 涨跌配色遵循 A 股习惯（红涨绿跌）。非投资建议。
