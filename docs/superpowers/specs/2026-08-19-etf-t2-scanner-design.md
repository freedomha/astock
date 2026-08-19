# ETF T2区间扫描器 Skill 设计文档

日期: 2026-08-19
状态: 已获用户批准

## 背景

用户需要一个新 skill，用于在全部 A 股 ETF 中寻找处于 **T2区间（底部构建）** 的标的。输入为项目根目录已存在的 `etf_kline_data.json`（348只ETF、250日K线，newest-first），输出为 HTML 报告。参考现有 skill `etf-bowl-bottom-scanner` 的结构。

T2 定义来自 `etf-operation-plan/trend_analysis.py` 的 T0-T8 趋势状态机：
- **T2 底部构建** = `pos250 ≤ 0.35`（250日区间位置≤35%）+ 低点抬高（近20日低点>前20日低点）+ 周线非向下（且未满足T0/T1/T6/T7/T8条件）

## 设计决策（来自澄清问题）

| 问题 | 决策 |
|------|------|
| T2判定方式 | 复用完整 T0-T8 状态机（与操作计划体系一致） |
| T2内部排序 | 加置信度打分排序（语义=「接近T3升级」） |
| 报告范围 | T2为主 + 状态分布上下文（柱状图展示T0-T8分布） |
| 数据更新 | 支持联网更新（复用 bowl scanner 的 update_kline_data + --refresh） |
| 状态机代码复用 | 复制进新skill（保持仓库自包含风格，注明来源） |

## 目录结构

```
.workbuddy/skills/etf-t2-scanner/
├── SKILL.md               # skill定义：T2语义、评分表、解读指南
├── analyze.py             # 主引擎：读数据(+可选联网更新) → 状态机判定 → T2打分 → etf_t2_results.json
├── generate_report.py     # 读结果 → reports/etf/etf_t2_report.html
└── etf_t2_results.json    # 输出（运行时生成）
```

## analyze.py 流程

1. **数据加载**：读 `all_etfs_larggest.json`（ETF名称）+ 项目根 `etf_kline_data.json`
2. **可选联网更新**：复用 bowl scanner 的 `update_kline_data` 逻辑（含 `--refresh` 盘中刷新）
3. **T0-T8 状态机**：从 `etf-operation-plan/trend_analysis.py` 复制以下函数（注明来源版本）：
   - 数值工具：`lin_slope`/`atr`/`ma_series`/`dir_label`
   - K线处理：`parse_kline`/`resample_weekly`/`week_completeness`
   - 特征：`compute_ma_features`/`compute_structure`/`compute_extension`/`compute_volatility`/`compute_weekly_features`
   - 核心：`classify_trend_state`（T0-T8，含T3a/T3b）
   - **不含**迁移状态机持久化（单ETF操作计划专用；扫描器用原始分类）
4. **T2置信度打分**（5维，满分100，语义=「接近T3升级」）：

   | 维度 | 满分 | 说明 |
   |------|------|------|
   | 低点抬高幅度 | 30 | 近20日低点 vs 前20日低点，抬得越多分越高 |
   | 距250日低点距离 | 25 | pos250 越低分越高 |
   | 周线斜率回升 | 20 | slope_10w 越接近0/向上分越高 |
   | 距MA60距离 | 15 | 处于 -15%~-2% 区间最佳 |
   | 量能/波幅 | 10 | 周量比收缩 + ATR压缩 |

   惩罚：近20日动量 t20 < -4% → -10分
5. **输出**：`etf_t2_results.json` = 全部ETF的状态分布 + T2项（置信度、证据指标、判定理由）
6. **控制台摘要**：状态分布统计 + T2 TOP 排名

## generate_report.py 报告结构（→ reports/etf/etf_t2_report.html）

- 头部：标题「ETF T2底部构建扫描报告」、数据日期、样本数
- 摘要卡片：T0-T8 各状态计数、T2总数、T2平均置信度
- 状态分布上下文：Chart.js 柱状图展示 T0-T8 分布
- T2置信度排名表（TOP 25）：名称/置信度/pos250/抬底幅度/周线斜率/距MA60
- K线缩略图：T2 TOP 前9名 120日走势（Chart.js）
- 详细卡片：T2 每只的判定依据（状态机reasons + 置信度分项）
- 风险提示：A股涨红跌绿、仅量化分析非投资建议

## SKILL.md

- frontmatter（name/description）
- T2语义定义（引用T0-T8状态机）
- 运行步骤（analyze.py → generate_report.py，--refresh 说明）
- 置信度评分表
- 解读指南（T2对应操作计划25%试仓位等衔接说明）

## 约定

- A股颜色惯例：红涨绿跌
- 纯标准库 Python
- 报告输出到 `reports/etf/`
- 仅量化扫描，非投资建议
