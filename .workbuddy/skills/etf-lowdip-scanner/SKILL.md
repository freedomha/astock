---
name: etf-lowdip-scanner
description: Use when scanning A-share ETFs for **T2(底部构建) + T3a(反转初步确认, MA60仍下行) 低吸机会** per 行业ETF选股算法-SOP. Runs the full SOP pipeline — AUM/pool filter, T0-T8 trend-state machine (weekly-primary), 6-dimension 低吸 confidence scoring, composite ranking, then the 门口 = T2/T3a 小额试仓 gate enforced by four machine validations (action legality / cost-adjusted RR≥2 / position sizing / trading cost) via decision_engine.decide(trial=True) reading every param from records/portfolio_config.json. Output = ranked candidates with per-ETF verdict (可小额试仓 vs 被拦截) + planned entry / structural invalidation / first observation levels + order sizing, and an HTML report. Input is etf_kline_data.json (250-day klines); same-date bars are force-refreshed by default (--no-refresh to skip). Money-fund/bond flat-price ETFs are excluded. Chinese stock market convention: red=up, green=down.
---

# A股ETF 低吸机会扫描器 (T2 + T3a 小额试仓) v2

## Overview

依据《行业ETF选股算法-SOP》，实现**筛选 → 合成 → 择时 → 门控（门口=T2/T3a 小额试仓）→ 四道程序校验 → 下单计算**的完整闭环。运行完整 **T0-T8 趋势状态机**（周线为主，与 `etf-operation-plan` 一致），从全部 A 股 ETF 中筛出 **T2（底部构建）** 与 **T3a（反转初步确认，MA60 仍下行）** 两类允许小额试仓的标的，按**低吸置信度**排序，并对每个候选跑操作引擎的**四道程序校验**，给出**能否小额试仓**的机器判词与计划买入价/结构失效位/第一观察区，以及建议下单手数/金额。

> **低吸 vs 建仓边界（SOP 硬约束）**：本 skill 的**门口 = T2 / T3a 小额试仓**（每笔只开目标仓位的 10%）。完整建仓（分批增加核心仓）只允许 **T3b / T4** 白名单。T2 仅为小额试仓、T3a 需「小额、等待回踩」（MA60 仍向下，必须等 MA60 走平/转上才可加码）。**禁止在 T0/T1 抄底**。四个校验任一失败 → 自动降级 HOLD。

**新增 v2 能力**（相对 v1「仅扫描排序」）：
- 全量接入 `decision_engine.py`（复制自 `etf-operation-plan/operation_engine.py`），对每个 T2/T3a 候选执行 **decide(trial=True)** 四个校验
- 计算并输出：**结构失效位 = min(60,120日低)−0.5×ATR20**、**灾难保护位 = 支撑−1×ATR20**、**计划买入价**（回踩）、**第一观察区**（第一阻力）
- 所有金额/权重/成本参数一律读取 `records/portfolio_config.json`，**绝不硬编码**

目标状态判定：
- **T2 底部构建** = ① pos250 ≤ 35% + ② 低点抬高（近20日低点 > 前20日低点）+ ③ 周线非向下（且未落入 T0/T1/T6/T7/T8）
- **T3a 反转初步确认** = ② 周线转上 + ② 价格站上 MA60 + ③ 低点抬高，但 **MA60 仍向下**（sub_state = T3a；MA60 走平/向上则归为 T3b，属建仓白名单，本 skill 不列为低吸）

## Prerequisites

- 项目根目录存在 `etf_kline_data.json`（250日K线，ETF扫描器共享）
- 项目根目录存在 `all_etfs_larggest.json`（ETF列表，含名称与 AUM）
- 项目根目录存在 `records/portfolio_config.json`（SOP §七 参数来源；缺失则跳过四道校验）
- 项目根目录存在 `records/etf/*.json`（持仓流水，用于读取已持仓股份 → 影响仓位数量校验）
- Python 3.13 标准库即可，无第三方依赖
- 联网更新模式（可选）需要 Node.js 和 westock-data CLI

## Quick Start

```
1. 确保 etf_kline_data.json / all_etfs_larggest.json / records/portfolio_config.json 存在
2. 运行 analyze.py → T0-T8→低吸打分→四道程序校验→etf_lowdip_results.json
   - 刷新默认开启：当日bar自动用最新数据替换（15:00后用收盘数据；--no-refresh 跳过）
3. 运行 generate_report.py → reports/etf/etf_lowdip_report.html
4. 报告/输出中：PASS=可小额试仓(含手数/金额)，FAIL=被拦截(含失败的门)
```

## SOP 流程在本 skill 的落点

| SOP | 实现 |
|-----|------|
| Step0-1 标的池+硬门槛 | `AUM_FLOOR=5e8` 剔除<s5亿；剔除货币/债券近平价标的 |
| Step2 四维因子打分 | 6维低吸置信度打分（250日位置锚=估值差代理；动量=斜率×R²；周线/MA60/量能≈景气-动量代理） |
| Step3 综合合成排序 | 加权合成 `lowdip_score` 0-100，T3a 组 / T2 组各自排序 |
| Step4 趋势门控 | 只保留 T2 / T3a；T0/T1 直接剔除（禁止低吸） |
| Step5 组合构建+执行 | **门口=T2/T3a 小额试仓**：`decide(trial=True)` 四道校验 + 下单手数/金额 |
| Step6 复评调仓 | （扫描侧不执行调仓；由 `etf-operation-plan` 周频复评，本 skill 输出触发位） |
| §七 四道程序校验 | 全量接入 `decision_engine.decide(trial=True)` |

## Step-by-Step Workflow

### Step 1: Run Analysis

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON .workbuddy/skills/etf-lowdip-scanner/analyze.py

# 刷新默认开启，跳过刷新用 --no-refresh:
$PYTHON .workbuddy/skills/etf-lowdip-scanner/analyze.py --no-refresh
```

`analyze.py` 流程：
- 加载 `all_etfs_larggest.json` + `etf_kline_data.json` + `records/portfolio_config.json` + `records/etf/*.json`
- **AUM 硬门槛**：剔除 size < 5亿；**排除货币/债券近平价标的**（sh511850 等）
- 默认联网刷新当日bar（`--no-refresh` 跳过）
- 对每只 ETF 计算周线特征、MA特征(20/60/120/250)、结构(高低点)、波动率(ATR)
- 运行 `classify_trend_state` 判定 T0-T8（含 T3a/T3b）
- 对 **T2 与 T3a**：6 维低吸打分 → `_run_program_check()` 跑四道校验 → 分别排序
- 保存 `etf_lowdip_results.json`（状态分布 + T2/T3a 明细 + 每个候选的 `program_check`）
- 控制台打印状态分布 + T3a/T2 榜单 + 四道校验通过/拦截汇总

### Step 2: Generate HTML Report

```bash
$PYTHON .workbuddy/skills/etf-lowdip-scanner/generate_report.py
```

产出 `reports/etf/etf_lowdip_report.html`：
- 摘要卡片（状态计数、T3a/T2 总数与均值）+ 四道校验通过/拦截汇总卡
- 状态分布柱状图（Chart.js）
- T3a / T2 榜单（TOP 25，含**程序校验判词、RR、计划买入、结构失效位、第一观察区**列）
- T2/T3a 高分前 9 名 120日K线缩略图
- T2/T3a 详细分析卡片（状态机 reasons + 低吸分项 + **四道校验明细 + 建议手数/金额**）

### Step 3: 读取「可小额试仓」候选

机器判词（每个候选的 `program_check`）：
- **`verdict = "PASS"`** → 四道校验全过，`order` 给出建议 **小额试仓手数/金额**（=目标仓 10%）
- **`verdict = "FAIL"`** → 至少一道校验拦截，`validations` 给出失败的门与原因（多为 RR 未达试仓下限 / 低于 1 手 / 成本占比超限 / 金额不足）

## 四道程序校验（SOP §七，全量接入）

对每个 T2/T3a 候选，运行 `decision_engine.decide(trial=True)` 的四个校验，任一失败自动 `HOLD`：

1. **动作合法性（趋势-动作硬约束）**：T0/T1+ADD/AVERAGE_DOWN/CHASE 拒绝；T5/T7+CHASE/ADD 拒绝；T8+新增 拒绝。
2. **风险收益（成本调整后 + 止损前置）**：无结构失效位 → 拒绝；`rr_net = (第一观察区 − 计划买入价 − 每股成本) / (计划买入价 − 结构失效价)`。**小额试仓(T2/T3a, ≤10%仓)用更低下限 RR≥1.2**（极小仓位换取更宽 RR）；完整建仓仍须 RR≥2 → 拒绝。
3. **仓位数量**：建议买入金额 ≤ 目标仓位缺口 & ≤ 单次增仓上限；预计损失 ≤ 单标的风险预算(风险预算=portfolio_value×risk_budget_pct)；调整后权重 ≤ max_weight_pct(25%)；总仓位 ≤ portfolio_value×90%。
4. **交易成本（小资金致命项）**：可买手数 < 1手(100份) → 拒绝；单边成本/成交额 > 1% → 拒绝（最低5元佣金主导千元以下订单）；成本/预期收益 > 15% → 拒绝。

**关键位定义（SOP §六）**：
- 结构失效位 = min(60日低, 120日低) − **0.5×ATR20**
- 灾难保护位 = 结构支撑 − **1×ATR20**
- 计划买入价 = min(MA20, 现价) × 0.995（**回踩再买**）
- 第一观察区 = 近期第一阻力（近20日高点）

所有参数来自 `records/portfolio_config.json`（`portfolio_value`/`positions[].target_weight_pct`/`max_weight_pct`/`risk_budget_pct`/`costs.*`），代码不硬编码。ETF 免印花税；佣金万 2.5、单笔最低 5 元；单边价差 0.05%；1手=100份。3万本金下千元订单常被最低佣金拦截而自动降 HOLD——这是分批/低换手的成本依据。

## T0-T8 状态机要点

（完整逻辑复制自 `.workbuddy/skills/etf-operation-plan/trend_analysis.py` 的 `classify_trend_state`）

| 状态 | 含义 | 核心条件 | 本skill |
|------|------|----------|---------|
| T0 | 长期下降 | 周线向下+空头排列+低点降低 | ❌ 禁止低吸 |
| T1 | 下降减速 | 周线向下但日线减速/反弹 | ❌ 禁止低吸 |
| **T2** | **底部构建** | **pos250≤35% + 低点抬高 + 周线非向下** | **✅ 小额试仓(10%)** |
| **T3a** | 反转初步确认 | 周线转上+站上MA60 但 **MA60仍向下** | **✅ 小额、等待回踩** |
| T3b | 反转确认 | 周线转上+站上MA60 + **MA60走平/向上** | 建仓白名单（不做低吸） |
| T4 | 中期上升确认 | 多头排列+高低点抬高+周线向上 | 建仓白名单（不做低吸） |
| T5 | 上升加速 | 多头排列+强动量 | ❌ 高位不低吸 |
| T6 | 高位整理 | 250日高位+走平 | ❌ |
| T7 | 趋势衰竭 | 高位+均线转平/向下 | ❌ |
| T8 | 结构破坏 | 周线跌破前低+向下 | ❌ 退出 |

注：本扫描器使用**原始分类**（不含 `etf-operation-plan` 的迁移状态机持久化与连续周确认）。低吸动作合法性由本 skill 内建的 `decision_engine.decide(trial=True)` 四道校验裁定（与 `etf-operation-plan/operation_engine.py` 同源）。

## 低吸置信度打分（满分100，语义=「左侧低吸性价比 + 接近T3b升级概率」）

| 维度 | 满分 | 计分规则 |
|------|------|----------|
| 250日区间位置 | 25 | pos250 ≤10% = 25；≤20% = 21；≤30% = 15；≤40% = 9；其他 = 3（估值锚） |
| 低点抬高幅度 | 20 | 近20日低点vs前20日：≥3% = 20；≥1% = 15；≥0.5% = 10；>0 = 5；否则 0 |
| 动量 斜率×R² | 20 | mom=0.5·m20+0.3·m40+0.2·m60；≥2 = 20；≥0.5 = 16；≥0 = 11；≥-2 = 5；否则 0 |
| 周线方向 | 15 | 周线up = 15；flat且slope>-0.5 = 11；flat = 7；down = 2 |
| MA60斜率修复 | 10 | ≥-1% = 10；≥-2% = 7；≥-4% = 4；否则 1（T3a→T3b 关键）|
| 量能/波幅 | 10 | 周量比<0.85 = 5（<1.0 = 3）+ ATR比<0.9 = 5（<1.05 = 3） |

动量因子公式 = **年化斜率 × R²**（对 `win` 日对数价格线性回归），语义对应 SOP「斜率×R²」量价动量因子。

**惩罚:** 近20日动量 t20 < -4% → -10分（仍在下行，左侧风险大，分数截断 0-100）。

## Interpretation Guidance

- **`PASS`（可小额试仓）**：四道校验全过，可按 `order.shares/amount` 开 **10% 目标仓**的试仓单。仍非建仓——周线升级 T3b 后再按 `etf-operation-plan` 分批建仓节奏加仓。
- **T3a 高分（≥65）**：反转初步确认 + MA60 接近走平，最接近 T3b 升级，可小额定投/等待回踩关注。
- **T2 高分（≥65）**：筑底结构完整 + 低估值 + 周线走平，可按 T2 档小额试仓观察。
- **中分（50-64）**：低吸性价比一般，需观察低点是否继续抬高、动量是否转正。
- **低分（<50）**：刚筑底或仍在左侧下行，等待进一步证据，避免过早低吸。
- **状态分布**：若大量 ETF 同时处于 T1/T2（下降减速/底部构建），可能预示市场整体筑底；若 T0 占比高，市场仍系统性下跌，低吸需更保守。
- **upgrade 信号**：T2→T3a/T3b、T3a→T3b 需周线转上+站上MA60+MA60走平。高分 T2/T3a 若出现该信号，可关注能否进入建仓白名单。

## Important Notes

- 使用A股颜色惯例：**红涨绿跌**（与美国/欧洲相反）。
- **门口 = T2/T3a 小额试仓（10% 目标仓）**，不是完整建仓。完整建仓（分批增加核心仓）仅限 T3b/T4，且须通过操作引擎四道程序校验。
- 本 skill 内建四道校验与下单计算，参数全部来自 `records/portfolio_config.json`；`decision_engine.py` 与 `etf-operation-plan/operation_engine.py` 同源，结论可互相印证。
- 仅量化扫描与机器判词，**不构成投资建议**。
- 数据来自腾讯自选股接口（经 westock-data），可能有延迟；本地 JSON 若不刷新可能过期。
- 与 `etf-operation-plan` / `etf-t2-scanner` 的状态判定基于同一状态机代码，可互相印证。