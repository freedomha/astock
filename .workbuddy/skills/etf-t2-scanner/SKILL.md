---
name: etf-t2-scanner
description: Use when scanning A-share ETFs for the T2 trend state (底部构建) — classify all ETFs with the T0-T8 trend-state machine (weekly-primary, used by etf-operation-plan), score T2 candidates on a 5-dimension confidence engine (approaching T3 upgrade), and output an HTML report. Input is etf_kline_data.json (250-day klines); same-date bars are force-refreshed by default (--no-refresh to skip). Chinese stock market convention: red=up, green=down.
---

# ETF T2区间扫描器 (ETF T2底部构建扫描) v1

## Overview

在全部 A 股 ETF 中寻找处于 **T2区间（底部构建）** 的标的。T2 是 `etf-operation-plan` 趋势状态机（T0-T8，周线为主）中的状态之一：

**T2 底部构建** = ① 价格处于250日区间低位（pos250 ≤ 35%）+ ② 低点开始抬高（近20日低点 > 前20日低点）+ ③ 周线非向下（且未落入 T0/T1/T6/T7/T8）。

本 skill 对全部 ETF 运行完整 T0-T8 分类（与 etf-operation-plan 完全一致），筛出 T2 标的，并按**置信度打分**排序 —— 分数语义 =「越接近 T3 反转确认」。

## Prerequisites

- 项目根目录存在 `etf_kline_data.json`（250日K线，ETF扫描器共享）
- 项目根目录存在 `all_etfs_larggest.json`（ETF列表，含名称）
- Python 3.13 标准库即可，无第三方依赖
- 联网更新模式（可选）需要 Node.js 和 westock-data CLI

## Quick Start

```
1. 确保 etf_kline_data.json 与 all_etfs_larggest.json 存在于项目根目录
2. 运行 analyze.py → 判定状态 + T2置信度打分 → etf_t2_results.json
   - 刷新默认开启：当日bar自动用最新数据替换（15:00后用收盘数据；--no-refresh 跳过）
3. 运行 generate_report.py → reports/etf/etf_t2_report.html
4. present_files 展示 HTML 报告
```

## Step-by-Step Workflow

### Step 1: Run Analysis

```bash
PYTHON="/Users/aldiadmin/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
$PYTHON .workbuddy/skills/etf-t2-scanner/analyze.py

# 刷新默认开启，跳过刷新用 --no-refresh:
$PYTHON .workbuddy/skills/etf-t2-scanner/analyze.py --no-refresh
```

`analyze.py` 流程：
- 加载 `all_etfs_larggest.json`（ETF名称）+ `etf_kline_data.json`（K线）
- 默认联网刷新当日bar（`--no-refresh` 跳过）
- 对每只 ETF 计算：周线特征（完整周重采样）、MA特征（60/120/250）、结构（高低点）、波动率
- 运行 `classify_trend_state` 判定 T0-T8（含 T3a/T3b）
- T2 标的追加 5 维置信度打分 → 排序输出
- 保存 `etf_t2_results.json`（状态分布 + T2明细）
- 控制台打印状态分布统计 + T2 TOP 排名

### Step 2: Generate HTML Report

```bash
$PYTHON .workbuddy/skills/etf-t2-scanner/generate_report.py
```

产出 `reports/etf/etf_t2_report.html`：
- 摘要卡片（T0-T8 状态计数、T2总数、T2平均置信度）
- 状态分布柱状图（Chart.js，判断大盘筑底广度）
- T2置信度排名表（TOP 25）
- T2 TOP 前9名 120日K线缩略图
- T2 详细分析卡片（状态机reasons + 置信度分项）

## T0-T8 状态机要点

（完整逻辑复制自 `.workbuddy/skills/etf-operation-plan/trend_analysis.py` 的 `classify_trend_state`）

| 状态 | 含义 | 核心条件 |
|------|------|----------|
| T0 | 长期下降 | 周线向下+空头排列+低点降低 |
| T1 | 下降减速 | 周线向下但日线减速/反弹 |
| **T2** | **底部构建** | **pos250≤35% + 低点抬高 + 周线非向下** |
| T3a/T3b | 反转初步确认 | 周线转上+站上MA60（MA60向下/向上） |
| T4 | 中期上升确认 | 多头排列+高低点抬高+周线向上 |
| T5 | 上升加速 | 多头排列+强动量 |
| T6 | 高位整理 | 250日高位+走平 |
| T7 | 趋势衰竭 | 高位+均线转平/向下 |
| T8 | 结构破坏 | 周线跌破前低+向下 |

注：本扫描器使用**原始分类**（不包含操作计划的迁移状态机持久化与连续周确认规则 —— 那是单ETF操作计划专用的）。

## T2 置信度打分（满分100，语义=「接近T3升级」）

| 维度 | 满分 | 计分规则 |
|------|------|----------|
| 低点抬高幅度 | 30 | 近20日低点vs前20日低点：≥3% = 30；≥1% = 22；≥0.5% = 15；>0 = 8 |
| 距250日低点距离 | 25 | pos250 ≤10% = 25；≤20% = 20；≤30% = 12；其他 = 5 |
| 周线斜率回升 | 20 | 周线up = 20；flat且slope>-0.5 = 15；flat = 10；down = 5 |
| 距MA60距离 | 15 | -15%~-2% = 15；-20~-15% = 9；-2~3% = 10；其他 = 4 |
| 量能/波幅 | 10 | 周量比<0.8 = 5（<1.0 = 3）+ ATR比<0.85 = 5（<1.0 = 3） |

**惩罚:** 近20日动量 t20 < -4% → -10分（分数截断 0-100）。

## Interpretation Guidance

- **高分T2**（≥70）：筑底结构完整，低点抬升显著+周线走平，最接近T3确认，可按操作计划 T2 档（原核心仓可观察/小额试仓，约25%）关注。
- **中分T2**（50-69）：筑底进行中，需观察低点是否继续抬高。
- **低分T2**（<50）：刚进入筑底或抬升微弱，等待进一步证据。
- **状态分布**: 若大量ETF同时处于 T1/T2（下降减速/底部构建），可能预示市场整体筑底；若 T0 占比高，市场仍处于系统性下跌。
- T2 → T3a/T3b 升级需周线转上+站上MA60，可关注高分T2是否出现该信号。

## Important Notes

- 使用A股颜色惯例：**红涨绿跌**（与美国/欧洲相反）。
- 仅量化扫描，**不构成投资建议**。
- 数据来自腾讯自选股接口（经 westock-data），可能有延迟；本地 JSON 若不刷新可能过期。
- 与 `etf-operation-plan` 的状态判定完全一致（同一状态机代码），可互相印证。
