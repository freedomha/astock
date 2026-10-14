#!/usr/bin/env python3
"""
ETF操作计划 趋势状态机回测 (v1)

回测 etf-operation-plan 的核心决策层：
  1) 趋势状态机 (T0-T8 + T3a/T3b)  —— 信号级预测力验证
  2) 硬约束矩阵 (趋势状态 → 仓位动作) —— 策略级模拟验证

三部分输出：
  Part 1  状态信号统计   — 每个历史时点分类趋势状态，统计后续 5/10/20/40/60 日
                          收益（均值/胜率/中位数/最好/最差），并与全样本基线对比。
  Part 2  策略模拟       — 按硬约束矩阵把 effective 状态映射为仓位暴露，模拟
                          长期多头策略（空仓持币收益为 0），与买入持有对比
                          （总收益/年化/最大回撤/年化波动/夏普/平均暴露）。
  Part 3  关键迁移分析   — 进入 T3b/T4（升级）、T8（破位）、T0/T1（转弱）后
                          的 20/40 日收益，验证「趋势状态是主决策层」可执行性。

实现要点：
  - 复用 trend_analysis.py 的分类管线（parse/resample/ma/structure/weekly/classify），
    不重复实现算法，保证与实盘口径一致。
  - 含状态机迁移规则：调用 ta.migrate()（合法迁移、T8 立即生效、T0/T1→T4/T5 禁止），
    连续周数按「评估时点」的 ISO 周计数（同周不递增），不用 dt.date.today()。
  - 周线完整性：每个历史时点只使用最后一个完整自然交易周，当周仅作 preview，
    天然无未来函数。
  - 数据：默认仓库根 etf_kline_data_500.json（346 ETF × 500 日），
    可回退 etf_kline_data.json（250 日）。

回撤止盈（可选，默认关闭；--trailing-tp / --tp-grid）
  概念区分（重要）：本规则是【盈利侧暴露上限（ceiling）】，与下面两者都不是一回事——
    (i) 亏损侧的 结构失效位 / 灾难保护位 三层退出（SKILL.md「三层退出」、
        operation_engine.py 的 reduce/exit 触发）——那是「跌破支撑才减仓」；
    (ii) 状态 T7「保护收益、降低」——T7 的进入条件是 pos250 >= 0.70
         （trend_analysis.py 的 classify_trend_state），对「250 日分位从未达到
         0.70」的标的【结构性不可达】。典型例子：某 ETF 从 250 日高点深跌后强
         反弹，浮盈曾达 +10.7%，但 250 日分位峰值仅 37.5% → 永远进不了 T7，
         于是一路回吐到负收益而无任何减仓信号。本规则补的就是这个洞。
  规则：
    · 峰值锚点 = 持仓建立以来的最高收盘（peak_close），建仓日锚点 entry_close；
      持仓归零后全部锚点重置（防陈旧上限将来静默重新绑定）。
    · 触发：peak_close > entry_close*(1+gain)  且
            peak_close - close >= max(atr_k*ATR20, min_pct*peak_close)
    · 触发时冻结上限 cap_exp = reduce * (shares*price / position_value)
      （reduce=0.5 即把「触发时持有的名义市值」减半）。
    · 生效：tgt_exp = min(EXPOSURE[state], cap_exp) —— min() 保证【只减不增】。
    · 解除：回到 T4/T5/T6 且价格创出高于触发前峰值的新高（rearm）；
            或仓位被状态机打到 0（clear）。
  口径说明：
    · 上限用「冻结的暴露比例」而非份额数——基线模型是每日再平衡到固定名义市值，
      份额数上限会引入一个非再平衡的新策略，与基线不可比。
    · 同 bar 触发 + 同 bar 成交（用 close[i]）；状态机作用于 close[idx-1]，
      故本规则刻意比状态机「快一根 bar」（价格信号 vs 结构信号）。
    · 网格 A/B：--tp-grid 'gain=8,k=2,min=4,reduce=0.5;...'，结果写 --tp-output。

Usage:
  python3 .workbuddy/skills/etf-operation-plan/backtest.py \
      [--kline-file <path>] [--code sh518880] [--max-etfs N] \
      [--eval-step 5] [--min-history 150] [--use-confirmed] \
      [--commission-rate 0.00025] [--min-commission 5] [--half-spread 0.0005] \
      [--impact-pct 0] [--lot-size 100] [--position-value 20000] \
      [--output backtest_trend_state_results.json] \
      [--trailing-tp] [--tp-gain 0.08] [--tp-atr-k 2.0] [--tp-min-pct 0.04] \
      [--tp-reduce 0.5] [--tp-grid 'gain=8,k=2,min=4,reduce=0.5;...'] \
      [--tp-output backtest_tp_ab_results.json]

交易成本模型（官方口径：ETF 免印花税；佣金万2.5-3 最低5元/笔；最小交易单位 1手=100份）：
  每笔交易成本 = max(最低佣金, 成交额×佣金率) + 成交额×(单边价差 + 冲击成本)
  - 份额按 1 手（lot_size）取整，买不足 1 手不成交（最小交易单位）。
  - 同时输出 net（含成本）与 gross（无成本），cost_drag = gross − net。
  - 买入持有基准计入一次建仓 + 一次清仓成本。
  成本参数来源：CLI > records/portfolio_config.json["costs"] > 内置默认。
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date

_skill_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_skill_dir, "..", "..", ".."))
sys.path.insert(0, _skill_dir)

import trend_analysis as ta  # noqa: E402

# ─── 硬约束矩阵 → 单标的仓位暴露（核心仓口径，可调） ───────────────────────
# 映射来源 SKILL.md「硬约束矩阵」：
#   T0/T1  降低或退出，禁止新增      → 空仓
#   T2     原核心仓可观察，仅小额试仓 → 25%
#   T3a    维持为主，小额等待回踩     → 50%
#   T3b    维持，可分批增加          → 75%
#   T4/T5/T6 维持/不追高             → 100%
#   T7     保护收益，降低            → 50%
#   T8     降低或退出，禁止新增      → 空仓
EXPOSURE = {
    "T0": 0.0, "T1": 0.0, "T2": 0.25, "T3a": 0.50, "T3b": 0.75,
    "T4": 1.0, "T5": 1.0, "T6": 1.0, "T7": 0.50, "T8": 0.0,
    "T3": 0.60,  # 兜底（正常情况下 T3 必带 T3a/T3b 子态）
}

STATE_ORDER = ["T0", "T1", "T2", "T3a", "T3b", "T4", "T5", "T6", "T7", "T8"]
FORWARD_DAYS = [5, 10, 20, 40, 60]

# ─── 交易成本默认参数（官方口径，可用 CLI / portfolio_config.json["costs"] 覆盖）────
COST_DEFAULTS = {
    "commission_rate": 0.00025,  # 佣金万2.5（全佣含规费），官方区间万0.5-3
    "min_commission": 5.0,       # 单笔最低佣金5元
    "half_spread": 0.0005,       # 单边买卖价差 0.05%（1-2 tick，官方最小报价0.001元）
    "impact_pct": 0.0,           # 冲击成本占成交额%（默认0，散户订单远小于盘口）
    "lot_size": 100,             # 最小交易单位 1手=100份（上交所官方）
}

# ─── 回撤止盈默认参数（盈利侧暴露上限：只减不增；默认关闭）──────────────────
# gain   触发所需最小浮盈（相对建仓日收盘，peak_close > entry_close*(1+gain)）
# atr_k  回撤阈值 ATR 倍数：max(atr_k*ATR20, min_pct*peak_close)
# min_pct 回撤阈值的最小百分比（低波动资产下限，与 SKILL 波动率自适应口径一致）
# reduce 触发后暴露上限系数（0.5 = 相对触发时持有的名义市值减半）
TP_DEFAULTS = {
    "gain": 0.08,
    "atr_k": 2.0,
    "min_pct": 0.04,
    "reduce": 0.5,
}


def eff_key(eff_code, eff_sub):
    """effective 状态 → 暴露映射键（T3 用子态 T3a/T3b）。"""
    if eff_code == "T3" and eff_sub in EXPOSURE:
        return eff_sub
    return eff_code


# ─── K 线加载（newest-first → oldest-first）─────────────────────────────────
def load_kline(raw, min_bars):
    records = []
    if isinstance(raw, dict):
        raw = raw.get("klines", raw.get("data", []))
    if not isinstance(raw, list):
        return None
    for k in reversed(raw):
        try:
            records.append({
                "date": str(k["date"]),
                "open": float(k.get("first", k.get("open", k["last"]))),
                "close": float(k["last"]),
                "high": float(k["high"]),
                "low": float(k["low"]),
                "volume": float(k.get("volume", 0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    records.sort(key=lambda x: x["date"])
    return records if len(records) >= min_bars else None


def atr_series(highs, lows, closes, window=20):
    """滚动 ATR 序列（对齐输入），前 window-1 项为 None。

    口径与 trend_analysis.atr 一致（window 个真实波幅 TR 的简单平均）：
    atr_series(...)[-1] == ta.atr(highs, lows, closes, window)（>= window+1 根后）。
    回撤止盈用 atr_series[i]（含当日），无未来函数。
    """
    n = len(closes)
    out = [None] * n
    trs = []
    for i in range(n):
        prev = closes[i - 1] if i > 0 else closes[i]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
        if i >= window - 1:
            out[i] = sum(trs[i - window + 1:i + 1]) / window
    return out


# ─── 历史时点快照：只用 end_idx 之前的数据分类趋势状态 ─────────────────────
def snapshot(records, end_idx):
    recs = records[:end_idx]
    if len(recs) < 60:
        return None
    closes = [r["close"] for r in recs]
    highs = [r["high"] for r in recs]
    lows = [r["low"] for r in recs]

    # intraday=False：历史时点一律视为收盘后数据
    _daily, weekly_status = ta.week_completeness(recs, intraday=False)
    weekly_bars = ta.resample_weekly(recs)
    ma = ta.compute_ma_features(closes, highs, lows)
    structure = ta.compute_structure(closes, highs, lows)
    weekly = ta.compute_weekly_features(weekly_bars, weekly_status)
    raw = ta.classify_trend_state(ma, structure, weekly, closes, highs, lows)

    return {
        "date": recs[-1]["date"],
        "raw_state": raw["code"],
        "raw_sub": raw.get("sub_state"),
    }


# ─── 状态机模拟（评估时点日期计数连续周，非今天） ───────────────────────────
def simulate_state_machine(evals):
    """evals: list of snapshot dicts（按时间顺序）。

    返回每个评估点的 effective 状态记录：effective_state / effective_sub /
    consecutive_weeks / migration_type / confirmation。
    """
    prev = None          # {"state": ..., "sub_state": ...}
    prev_date = None
    consecutive = 0
    seq = []

    for e in evals:
        d = date.fromisoformat(e["date"][:10])
        week = d.isocalendar()[:2]
        raw_code, raw_sub = e["raw_state"], e["raw_sub"]

        eff_code, eff_sub, mtype, conf, _note = ta.migrate(prev, raw_code, raw_sub)

        if prev is not None and prev["state"] == eff_code:
            # 同状态：跨周才递增（防抖动，与实盘连续周口径一致）
            if prev_date is not None and prev_date.isocalendar()[:2] != week:
                consecutive += 1
            # 同周不递增，保持原值
        else:
            consecutive = 1

        seq.append({
            "effective_state": eff_code,
            "effective_sub": eff_sub,
            "consecutive_weeks": consecutive,
            "migration_type": mtype,
            "confirmation": "confirmed" if consecutive >= 2 else conf,
        })
        prev = {"state": eff_code, "sub_state": eff_sub}
        prev_date = d

    return seq


# ─── Part 1: 信号级统计 ────────────────────────────────────────────────────
def _aggregate(vals):
    if not vals:
        return None
    avg = sum(vals) / len(vals)
    pos = sum(1 for v in vals if v > 0)
    srt = sorted(vals)
    return {
        "count": len(vals),
        "avg": round(avg, 2),
        "winrate": round(pos / len(vals) * 100, 1),
        "median": round(srt[len(srt) // 2], 2),
        "best": round(max(vals), 2),
        "worst": round(min(vals), 2),
    }


def build_signal_records(evals, seq, closes, n, code):
    """每个评估点 → 信号记录（effective 状态 + 后续 N 日收益）。"""
    signals = []
    for (idx, snap), st in zip(evals, seq):
        key = eff_key(st["effective_state"], st["effective_sub"])
        entry = closes[idx - 1]
        rec = {
            "code": code,
            "date": snap["date"],
            "idx": idx - 1,
            "raw_state": snap["raw_state"],
            "raw_sub": snap["raw_sub"],
            "effective_state": key,
            "consecutive_weeks": st["consecutive_weeks"],
            "confirmation": st["confirmation"],
            "migration_type": st["migration_type"],
        }
        for fd in FORWARD_DAYS:
            if idx - 1 + fd < n:
                rec[f"fwd{fd}d"] = round((closes[idx - 1 + fd] / entry - 1) * 100, 2)
            else:
                rec[f"fwd{fd}d"] = None
        signals.append(rec)
    return signals


def compute_signal_stats(signals):
    groups = defaultdict(list)
    for s in signals:
        groups[s["effective_state"]].append(s)

    baseline = {}
    for fd in FORWARD_DAYS:
        vals = [s[f"fwd{fd}d"] for s in signals if s[f"fwd{fd}d"] is not None]
        baseline[fd] = _aggregate(vals)

    stats = {}
    for st in STATE_ORDER:
        g = groups.get(st, [])
        sts = {"count": len(g), "etfs": len(set(s["code"] for s in g))}
        for fd in FORWARD_DAYS:
            vals = [s[f"fwd{fd}d"] for s in g if s[f"fwd{fd}d"] is not None]
            agg = _aggregate(vals)
            if agg and baseline.get(fd):
                agg["excess_vs_baseline"] = round(agg["avg"] - baseline[fd]["avg"], 2)
            sts[f"fwd{fd}d"] = agg
        stats[st] = sts
    return stats, baseline


# ─── Part 2: 策略模拟 ──────────────────────────────────────────────────────
def build_daily_exposure(evals, seq, n, use_confirmed):
    """每日活跃暴露键。默认用 effective 状态；
    use_confirmed=True 时，暴露上调（且非 T8）需待该状态连续 2 周确认，
    暴露下调立即生效 —— 验证防抖动/连续周确认的价值。"""
    daily = [None] * n
    active = None
    for k, (idx, _snap) in enumerate(evals):
        st = seq[k]
        key = eff_key(st["effective_state"], st["effective_sub"])
        if active is None:
            active = key
        elif use_confirmed:
            new_exp = EXPOSURE[key]
            old_exp = EXPOSURE[active]
            # 上调暴露且状态未确认 → 延迟到下一评估点（T8 破位立即生效）
            if new_exp > old_exp and key != "T8" and st["confirmation"] != "confirmed":
                pass  # 保持 active
            else:
                active = key
        else:
            active = key
        end = evals[k + 1][0] if k + 1 < len(evals) else n
        for i in range(idx, end):
            daily[i] = active
    return daily


def compute_metrics(daily_rets, exposure_series, rf=0.0):
    if not daily_rets:
        return None
    eq = 1.0
    curve = []
    for r in daily_rets:
        eq *= (1 + r)
        curve.append(eq)
    total = eq - 1
    nd = len(daily_rets)
    ann = (1 + total) ** (252.0 / nd) - 1 if total > -1.0 else -1.0

    peak, mdd = 0.0, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)

    mean = sum(daily_rets) / nd
    var = sum((r - mean) ** 2 for r in daily_rets) / nd
    sd = math.sqrt(var)
    vol_ann = sd * math.sqrt(252)
    sharpe = (mean - rf / 252.0) / sd * math.sqrt(252) if sd > 0 else 0.0
    avg_exp = sum(exposure_series) / len(exposure_series) if exposure_series else 0.0

    return {
        "total_return_pct": round(total * 100, 2),
        "annualized_pct": round(ann * 100, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "ann_vol_pct": round(vol_ann * 100, 2),
        "sharpe": round(sharpe, 2),
        "avg_exposure": round(avg_exp, 3),
        "days": nd,
    }


def _tp_event(kind, i, price, state, peak, entry, atr, cap, shares, pv):
    """回撤止盈事件记录（kind: fire / rearm / clear）。日期由调用方按 i 映射。"""
    return {
        "event": kind,
        "i": i,
        "state": state,
        "price": round(price, 4),
        "peak_close": round(peak, 4) if peak is not None else None,
        "entry_close": round(entry, 4) if entry is not None else None,
        "retrace_pct": round((peak - price) / peak * 100, 2) if peak else None,
        "atr20": round(atr, 4) if atr else None,
        "cap_exp": round(cap, 4) if cap is not None else None,
        "shares": shares,
        "exposure": round(shares * price / pv, 4) if shares else 0.0,
    }


def simulate_strategy(closes, daily, n, cost, position_value,
                      atr20=None, tp_cfg=None, collect_path=False):
    """份额制策略模拟，含交易成本模型（小资金最低佣金/价差/冲击/最小交易单位）。

    daily: 每日活跃暴露键（effective 状态 → 目标暴露）。
    每日 close 按目标暴露调整份额（决策于前一日 close，当日 close 成交，保守无未来函数），
    份额按 1 手取整；买不足 1 手不成交（最小交易单位）；期末清仓。
    每笔交易成本 = max(最低佣金, 成交额×佣金率) + 成交额×(单边价差+冲击)，从净值扣除。
    净值曲线逐日构建（盈亏与成本折叠进当日收益），net/gross 天数对齐。

    atr20/tp_cfg: 可选，回撤止盈（盈利侧暴露上限）。tp_cfg=None 时本函数行为与
    不传该参数时逐位一致（所有新分支跳过）。上限只减不增：
        tgt_exp = min(EXPOSURE[daily[i]], cap_exp)
    collect_path=True 时额外返回逐日暴露/状态路径与事件列表（仅单标的 case study 用）。

    Returns (net_metrics, gross_metrics, bh_metrics, trade_count, cost_drag_pct,
             total_cost_pct, tp_info)。
    net = 含成本；gross = 同份额路径但不扣成本；bh = 买入持有（一次建仓+一次清仓成本）。
    """
    start = next((i for i in range(n) if daily[i] is not None), None)
    if start is None or start + 1 >= n:
        return None, None, None, 0, 0.0, 0.0, None
    lot = cost["lot_size"]

    def trade_cost(amount):
        return max(cost["min_commission"], amount * cost["commission_rate"]) \
            + amount * (cost["half_spread"] + cost["impact_pct"])

    shares = 0
    eq_net, eq_gross = 1.0, 1.0
    eq_net_curve, eq_gross_curve = [], []
    exp_by_day = []
    trades = 0
    total_cost_frac = 0.0

    # ── 回撤止盈局部状态（函数局部，绝不共享，避免跨标的泄漏上限）─────────
    tp_on = tp_cfg is not None and atr20 is not None
    entry_close = peak_close = pre_fire_peak = cap_exp = None
    tp_fires = tp_rearms = tp_clears = tp_binding = tp_cap_days = 0
    tp_log = [] if (tp_on and collect_path) else None
    state_path = [] if collect_path else None

    for i in range(start, n):
        prev_close = closes[i - 1] if i > start else closes[i]
        exp_by_day.append(shares * prev_close / position_value if shares else 0.0)

        # 当日盈亏（持仓份额 × close[i-1] → close[i]），首日仅建仓不计盈亏
        if i > start and shares > 0:
            pnl = shares * (closes[i] - closes[i - 1]) / position_value
            eq_net *= (1 + pnl)
            eq_gross *= (1 + pnl)

        price = closes[i]

        # ── 回撤止盈：维护锚点 / 判定触发 / 判定重新武装 ──────────────────
        # 用 close[i]（含当日）同时做判断与成交，与 sim 的「同 bar close 成交」一致。
        if tp_on:
            a = atr20[i] or 0.0
            if shares == 0:
                # 仓位被状态机打到 0：清空全部锚点与上限（防陈旧上限将来静默重新绑定）
                if cap_exp is not None:
                    tp_clears += 1
                    if tp_log is not None:
                        tp_log.append(_tp_event("clear", i, price, daily[i],
                                                peak_close, entry_close, a, cap_exp,
                                                shares, position_value))
                entry_close = peak_close = pre_fire_peak = cap_exp = None
            else:
                if entry_close is None:            # (重)建仓日锚点
                    entry_close = price
                    peak_close = price
                elif price > peak_close:
                    peak_close = price
                if cap_exp is None:
                    gain_ok = peak_close > entry_close * (1 + tp_cfg["gain"])
                    retr_thr = max(tp_cfg["atr_k"] * a, peak_close * tp_cfg["min_pct"])
                    retrace_ok = retr_thr > 0 and (peak_close - price) >= retr_thr
                    if gain_ok and retrace_ok:
                        cap_exp = tp_cfg["reduce"] * (shares * price / position_value)
                        pre_fire_peak = peak_close
                        tp_fires += 1
                        if tp_log is not None:
                            tp_log.append(_tp_event("fire", i, price, daily[i],
                                                    peak_close, entry_close, a, cap_exp,
                                                    shares, position_value))
                else:
                    # 重新武装：确认上升趋势 且 价格创出高于触发前峰值的新高
                    if daily[i] in ("T4", "T5", "T6") and price > pre_fire_peak:
                        cap_exp = pre_fire_peak = None
                        peak_close = price
                        tp_rearms += 1
                        if tp_log is not None:
                            tp_log.append(_tp_event("rearm", i, price, daily[i],
                                                    peak_close, entry_close, a, None,
                                                    shares, position_value))

        # 在当日 close 调整到目标暴露（决策基于前一日 close 算出的状态）
        # 回撤止盈只做「上限」：min() 保证目标暴露 <= 状态机暴露，永不抬高仓位。
        base_exp = EXPOSURE[daily[i]]
        tgt_exp = base_exp
        if tp_on and cap_exp is not None:
            if cap_exp < base_exp:
                tp_binding += 1
            else:
                tp_cap_days += 1                 # 上限存在但当日未绑定（保留，不下调）
            tgt_exp = min(base_exp, cap_exp)
            if os.environ.get("ETF_TP_ASSERT"):
                assert tgt_exp <= base_exp + 1e-12, "trailing TP must never raise exposure"
        target_shares = int(tgt_exp * position_value / price / lot) * lot
        if target_shares != shares:
            amount = abs(target_shares - shares) * price
            if amount > 0:
                cf = trade_cost(amount) / position_value
                eq_net *= (1 - cf)
                total_cost_frac += cf
                trades += 1
            shares = target_shares

        # 建仓日补锚点（首日 shares 由 0 变正，上面 TP 块跑在成交之前）
        if tp_on and shares > 0 and entry_close is None:
            entry_close = price
            peak_close = price
        if collect_path:
            state_path.append(daily[i])

        eq_net_curve.append(eq_net)
        eq_gross_curve.append(eq_gross)

    # 期末清仓（net 扣成本，gross 不扣；两曲线同步追加保持天数对齐）
    if shares > 0:
        cf = trade_cost(shares * closes[-1]) / position_value
        eq_net *= (1 - cf)
        total_cost_frac += cf
        trades += 1
        eq_net_curve.append(eq_net)
        eq_gross_curve.append(eq_gross)
        exp_by_day.append(shares * closes[-1] / position_value)

    net_rets = [eq_net_curve[j] / eq_net_curve[j - 1] - 1 for j in range(1, len(eq_net_curve))]
    gross_rets = [eq_gross_curve[j] / eq_gross_curve[j - 1] - 1 for j in range(1, len(eq_gross_curve))]
    net_m = compute_metrics(net_rets, exp_by_day[:len(net_rets)]) if net_rets else None
    gross_m = compute_metrics(gross_rets, exp_by_day[:len(gross_rets)]) if gross_rets else None

    # 买入持有（一次建仓 + 一次清仓成本，公平对比）
    bh_pairs = []
    buy_shares = int(position_value / closes[start] / lot) * lot
    if buy_shares > 0:
        bh_pairs.append((-trade_cost(buy_shares * closes[start]) / position_value, 1.0))
        for i in range(start + 1, n):
            bh_pairs.append((buy_shares * (closes[i] - closes[i - 1]) / position_value, 1.0))
        bh_pairs.append((-trade_cost(buy_shares * closes[-1]) / position_value, 1.0))
    bh_m = compute_metrics([p[0] for p in bh_pairs], [p[1] for p in bh_pairs]) if bh_pairs else None

    cost_drag = 0.0
    if gross_m and net_m:
        cost_drag = round(gross_m["total_return_pct"] - net_m["total_return_pct"], 2)

    tp_info = None
    if tp_on:
        tp_info = {
            "fires": tp_fires, "rearms": tp_rearms, "clears": tp_clears,
            "binding_days": tp_binding, "cap_offset_days": tp_cap_days,
            "events": tp_log,
            "exposure_path": exp_by_day[:len(net_rets)] if collect_path else None,
            "state_path": state_path[:len(net_rets)] if collect_path else None,
        }
    return net_m, gross_m, bh_m, trades, cost_drag, round(total_cost_frac * 100, 2), tp_info


# ─── Part 3: 关键迁移事件 ──────────────────────────────────────────────────
def collect_transitions(evals, seq, closes, n):
    events = defaultdict(list)
    prev_key = None
    for (idx, snap), st in zip(evals, seq):
        key = eff_key(st["effective_state"], st["effective_sub"])
        if prev_key is not None and key != prev_key:
            entry = closes[idx - 1]
            rec = {
                "date": snap["date"],
                "from": prev_key,
                "to": key,
                "migration_type": st["migration_type"],
            }
            for fd in (20, 40):
                if idx - 1 + fd < n:
                    rec[f"fwd{fd}d"] = round((closes[idx - 1 + fd] / entry - 1) * 100, 2)
                else:
                    rec[f"fwd{fd}d"] = None
            events[key].append(rec)
        prev_key = key
    return events


def summarize_transitions(events):
    out = {}
    for to_state, evs in sorted(events.items()):
        agg = {"count": len(evs)}
        for fd in (20, 40):
            vals = [e[f"fwd{fd}d"] for e in evs if e[f"fwd{fd}d"] is not None]
            agg[f"fwd{fd}d"] = _aggregate(vals)
        out[to_state] = agg
    return out


# ─── 打印 ──────────────────────────────────────────────────────────────────
def print_signal_stats(stats, baseline):
    print("\n" + "=" * 92)
    print(" Part 1 状态信号统计（后续 N 日收益，超额 = 该状态均值 − 全样本基线均值）")
    print("=" * 92)
    print(f"{'状态':<5}{'次数':>6}{'N日':>4}{'均值%':>9}{'胜率%':>8}{'中位%':>8}{'最好%':>9}{'最差%':>9}{'超额%':>9}")
    print("-" * 92)
    for st in STATE_ORDER:
        s = stats[st]
        if s["count"] == 0:
            print(f"{st:<5}{0:>6}  （无信号）")
            continue
        for fd in FORWARD_DAYS:
            agg = s[f"fwd{fd}d"]
            if agg is None:
                continue
            ex = agg.get("excess_vs_baseline", "  —")
            print(f"{st:<5}{s['count']:>6}{fd:>5}{agg['avg']:>+8.2f}{agg['winrate']:>8.1f}"
                  f"{agg['median']:>+8.2f}{agg['best']:>+9.2f}{agg['worst']:>+9.2f}"
                  f"{ex if isinstance(ex, str) else f'{ex:+.2f}':>9}")
    print("-" * 92)
    b = baseline[20]
    print(f"基线(全样本) 20日: 均值 {b['avg']:+.2f}%  胜率 {b['winrate']:.1f}%  n={b['count']}")


def print_strategy(strategy, buyhold, n_etfs):
    print("\n" + "=" * 92)
    print(f" Part 2 硬约束矩阵策略 vs 买入持有（{n_etfs} 只 ETF 平均）")
    print("=" * 92)
    if not strategy:
        print("  无足够数据")
        return
    keys = [
        ("total_return_pct", "总收益%"),
        ("annualized_pct", "年化%"),
        ("max_drawdown_pct", "最大回撤%"),
        ("ann_vol_pct", "年化波动%"),
        ("sharpe", "夏普"),
        ("avg_exposure", "平均暴露"),
    ]
    print(f"{'指标':<12}{'策略':>12}{'买入持有':>12}{'差值':>12}")
    print("-" * 92)
    for k, label in keys:
        s = strategy.get(k, float("nan"))
        b = buyhold.get(k, float("nan"))
        diff = s - b
        print(f"{label:<12}{s:>12.2f}{b:>12.2f}{diff:>+12.2f}")
    if strategy.get("days"):
        print(f"（模拟区间平均 {strategy['days']} 个交易日）")


def print_transitions(trans):
    print("\n" + "=" * 92)
    print(" Part 3 关键迁移事件（迁移到目标状态后的后续收益）")
    print("=" * 92)
    print(f"{'目标状态':<8}{'事件数':>6}{'20日均%':>10}{'20日胜率%':>10}{'40日均%':>10}{'40日胜率%':>10}")
    print("-" * 92)
    for to_state in STATE_ORDER:
        agg = trans.get(to_state)
        if not agg or agg["count"] == 0:
            continue
        a20 = agg["fwd20d"] or {}
        a40 = agg["fwd40d"] or {}
        print(f"{to_state:<8}{agg['count']:>6}"
              f"{a20.get('avg', float('nan')):>+10.2f}{a20.get('winrate', float('nan')):>10.1f}"
              f"{a40.get('avg', float('nan')):>+10.2f}{a40.get('winrate', float('nan')):>10.1f}")


# ─── 主流程 ────────────────────────────────────────────────────────────────
def _prepare(records, cfg, need_atr=False):
    """共享预处理（与 TP 无关，成本最高的分类步骤只跑一次，供 A/B 各变体复用）。

    纯搬移自 backtest_etf 的 evals/seq/daily 构造，口径必须保持不变。
    Returns (n, closes, evals, seq, daily, atr20) 或 None。
    """
    n = len(records)
    closes = [r["close"] for r in records]

    evals = []
    for idx in range(cfg.min_history, n, cfg.eval_step):
        snap = snapshot(records, idx)
        if snap is not None:
            evals.append((idx, snap))
    if len(evals) < 2:
        return None

    seq = simulate_state_machine([s for _, s in evals])
    daily = build_daily_exposure(evals, seq, n, cfg.use_confirmed)
    atr20 = None
    if need_atr:
        atr20 = atr_series([r["high"] for r in records],
                           [r["low"] for r in records], closes, 20)
    return n, closes, evals, seq, daily, atr20


def backtest_etf(code, records, cfg):
    need_atr = getattr(cfg, "tp_cfg", None) is not None
    prep = _prepare(records, cfg, need_atr)
    if prep is None:
        return None
    n, closes, evals, seq, daily, atr20 = prep
    signals = build_signal_records(evals, seq, closes, n, code)
    net_m, gross_m, bh_m, trades, cost_drag, total_cost_pct, tp_info = simulate_strategy(
        closes, daily, n, cfg.cost, cfg.position_value,
        atr20=atr20, tp_cfg=getattr(cfg, "tp_cfg", None),
        collect_path=getattr(cfg, "collect_path", False))
    transitions = collect_transitions(evals, seq, closes, n)

    out = {
        "signals": signals,
        "strategy": net_m,
        "strategy_gross": gross_m,
        "buyhold": bh_m,
        "transitions": transitions,
        "trade_count": trades,
        "cost_drag_pct": cost_drag,
        "total_cost_pct": total_cost_pct,
    }
    if tp_info is not None:
        out["tp_stats"] = {k: tp_info[k] for k in
                           ("fires", "rearms", "clears", "binding_days", "cap_offset_days")}
        out["tp_events"] = [{**e, "date": records[e["i"]]["date"]}
                            for e in (tp_info.get("events") or [])]
        out["tp_exposure_path"] = tp_info.get("exposure_path")
        out["tp_state_path"] = tp_info.get("state_path")
    return out


def backtest_etf_grid(code, records, cfg, variants):
    """A/B：一次预处理 + 多变体廉价模拟（分类最贵，只跑一次）。

    variants: [(name, tp_cfg_or_None), ...]；tp_cfg=None 即基线。
    Returns {"signals", "transitions", "variants": {name: {...}}} 或 None。
    """
    prep = _prepare(records, cfg, need_atr=True)
    if prep is None:
        return None
    n, closes, evals, seq, daily, atr20 = prep
    signals = build_signal_records(evals, seq, closes, n, code)
    transitions = collect_transitions(evals, seq, closes, n)

    variants_out = {}
    for name, tp_cfg in variants:
        net_m, gross_m, bh_m, trades, cost_drag, total_cost_pct, tp_info = simulate_strategy(
            closes, daily, n, cfg.cost, cfg.position_value,
            atr20=atr20, tp_cfg=tp_cfg, collect_path=getattr(cfg, "collect_path", False))
        variants_out[name] = {
            "strategy": net_m,
            "strategy_gross": gross_m,
            "buyhold": bh_m,
            "trade_count": trades,
            "cost_drag_pct": cost_drag,
            "total_cost_pct": total_cost_pct,
            "tp_stats": None if tp_info is None else
                {k: tp_info[k] for k in
                 ("fires", "rearms", "clears", "binding_days", "cap_offset_days")},
        }
        if tp_info is not None:
            variants_out[name]["tp_events"] = [{**e, "date": records[e["i"]]["date"]}
                                               for e in (tp_info.get("events") or [])]
            variants_out[name]["tp_exposure_path"] = tp_info.get("exposure_path")
            variants_out[name]["tp_state_path"] = tp_info.get("state_path")
    return {"signals": signals, "transitions": transitions, "variants": variants_out}


def main():
    p = argparse.ArgumentParser(description="ETF操作计划趋势状态机回测")
    p.add_argument("--kline-file", help="K线数据 JSON 路径（默认仓库根 etf_kline_data_500.json，回退 250 日文件）")
    p.add_argument("--code", help="只回测单只 ETF")
    p.add_argument("--max-etfs", type=int, default=0, help="限制回测 ETF 数量（快速验证用）")
    p.add_argument("--eval-step", type=int, default=5, help="评估间隔（交易日），默认 5（≈周频）")
    p.add_argument("--min-history", type=int, default=150, help="最少历史数据（日），默认 150")
    p.add_argument("--use-confirmed", action="store_true",
                   help="暴露上调需连续 2 周确认（验证防抖动），下调立即生效；T8 立即")
    p.add_argument("--output", default=os.path.join(_skill_dir, "backtest_trend_state_results.json"),
                   help="输出 JSON 路径")
    # 交易成本参数（默认取自 records/portfolio_config.json["costs"]，否则内置官方默认）
    p.add_argument("--commission-rate", type=float, default=None, help="佣金费率（万2.5=0.00025）")
    p.add_argument("--min-commission", type=float, default=None, help="单笔最低佣金（元）")
    p.add_argument("--half-spread", type=float, default=None, help="单边买卖价差（占价格比例，0.05%%=0.0005）")
    p.add_argument("--impact-pct", type=float, default=None, help="冲击成本占成交额比例")
    p.add_argument("--lot-size", type=int, default=None, help="最小交易单位（1手=100份）")
    p.add_argument("--position-value", type=float, default=None,
                   help="单标的策略名义本金（默认取 portfolio_config.portfolio_value，否则 20000）；越小最低佣金拖累越明显")
    # 回撤止盈（盈利侧暴露上限；默认关闭；与 T7 / 结构失效位概念不同，见模块 docstring）
    p.add_argument("--trailing-tp", action="store_true",
                   help="启用回撤止盈（暴露上限，只减不增）")
    p.add_argument("--tp-gain", type=float, default=TP_DEFAULTS["gain"],
                   help="触发所需最小浮盈（相对建仓日收盘），默认 0.08")
    p.add_argument("--tp-atr-k", type=float, default=TP_DEFAULTS["atr_k"],
                   help="回撤阈值 ATR 倍数，默认 2.0")
    p.add_argument("--tp-min-pct", type=float, default=TP_DEFAULTS["min_pct"],
                   help="回撤阈值最小百分比，默认 0.04")
    p.add_argument("--tp-reduce", type=float, default=TP_DEFAULTS["reduce"],
                   help="触发后暴露上限系数，默认 0.5（减半）")
    p.add_argument("--tp-grid", default=None,
                   help="A/B 网格：分号分隔变体，如 'gain=8,k=2,min=4,reduce=0.5;gain=10,k=2,min=5,reduce=0.5'"
                        "（自动包含 baseline；gain/min 按百分数，k/reduce 为倍数）")
    p.add_argument("--tp-output", default=os.path.join(_skill_dir, "backtest_tp_ab_results.json"),
                   help="A/B 对比输出 JSON 路径")
    args = p.parse_args()

    kline_file = args.kline_file
    if not kline_file:
        cand = os.path.join(_project_root, "etf_kline_data_500.json")
        if os.path.exists(cand):
            kline_file = cand
        else:
            cand = os.path.join(_project_root, "etf_kline_data.json")
            if os.path.exists(cand):
                kline_file = cand
    if not kline_file or not os.path.exists(kline_file):
        print(f"未找到 K 线数据文件: {kline_file}")
        sys.exit(1)

    with open(kline_file) as f:
        raw_data = json.load(f)

    # 交易成本参数：CLI > records/portfolio_config.json["costs"] > 内置官方默认
    cost = dict(COST_DEFAULTS)
    position_value = 20000
    pcfg_path = os.path.join(_project_root, "records", "portfolio_config.json")
    if os.path.exists(pcfg_path):
        try:
            with open(pcfg_path) as f:
                pcfg = json.load(f)
            if isinstance(pcfg.get("costs"), dict):
                cost.update(pcfg["costs"])
            if pcfg.get("portfolio_value"):
                position_value = pcfg["portfolio_value"]
        except Exception:
            pass
    for k, v in (("commission_rate", args.commission_rate), ("min_commission", args.min_commission),
                 ("half_spread", args.half_spread), ("impact_pct", args.impact_pct),
                 ("lot_size", args.lot_size)):
        if v is not None:
            cost[k] = v
    if args.position_value:
        position_value = args.position_value

    cfg = argparse.Namespace(
        eval_step=args.eval_step,
        min_history=args.min_history,
        use_confirmed=args.use_confirmed,
        cost=cost,
        position_value=position_value,
    )

    # ── 回撤止盈：单参数模式 / A/B 网格模式（网格自动含 baseline）────────
    def _parse_grid(spec):
        vs = [("baseline", None)]
        for chunk in spec.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            kv = dict(part.split("=", 1) for part in chunk.split(",") if "=" in part)
            c = {"gain": float(kv.get("gain", 8)) / 100.0,
                 "atr_k": float(kv.get("k", 2.0)),
                 "min_pct": float(kv.get("min", 4)) / 100.0,
                 "reduce": float(kv.get("reduce", 0.5))}
            nm = "gain%g_k%g_min%g_r%g" % (c["gain"] * 100, c["atr_k"],
                                           c["min_pct"] * 100, c["reduce"])
            vs.append((nm, c))
        return vs

    tp_variants = _parse_grid(args.tp_grid) if args.tp_grid else None
    tp_cfg = None
    if args.trailing_tp and not tp_variants:
        tp_cfg = {"gain": args.tp_gain, "atr_k": args.tp_atr_k,
                  "min_pct": args.tp_min_pct, "reduce": args.tp_reduce}
    cfg.tp_cfg = tp_cfg
    # 仅在单标的 case study 时收集逐日路径/事件，避免全量输出膨胀
    cfg.collect_path = bool(args.code) and (tp_cfg is not None or tp_variants is not None)

    items = list(raw_data.items())
    if args.code:
        items = [(c, r) for c, r in items if c == args.code]
        if not items:
            print(f"未找到 ETF: {args.code}")
            sys.exit(1)
    if args.max_etfs > 0:
        items = items[: args.max_etfs]

    print(f"加载 K 线: {kline_file}")
    print(f"回测配置: eval_step={args.eval_step}  min_history={args.min_history}"
          f"  use_confirmed={args.use_confirmed}")
    print(f"成本模型: 佣金 {cost['commission_rate']*10000:.1f}‱(最低{cost['min_commission']:.0f}元) "
          f"单边价差 {cost['half_spread']*100:.2f}% 冲击 {cost['impact_pct']*100:.2f}% "
          f"最小{cost['lot_size']}份 | 名义本金 {position_value:.0f}元")
    print(f"ETF 数: {len(items)}")
    if tp_variants:
        print(f"回撤止盈 A/B 网格: {len(tp_variants)} 个变体（含 baseline） -> {args.tp_output}")
    elif tp_cfg:
        print(f"回撤止盈: 开启 gain={tp_cfg['gain']:.0%} k={tp_cfg['atr_k']:g} "
              f"min={tp_cfg['min_pct']:.0%} reduce={tp_cfg['reduce']:g}")

    all_signals = []
    strat_list, gross_list, bh_list = [], [], []
    cost_drag_list, trade_list = [], []
    per_etf = {}
    transitions_all = defaultdict(list)
    n_done = 0
    variant_agg = {}
    case_study = None
    if tp_variants:
        for name, _ in tp_variants:
            variant_agg[name] = {"strategy": [], "trade": [], "cost_drag": [],
                                 "fires": 0, "rearms": 0, "clears": 0, "etfs_fired": 0,
                                 "improved_ret": 0, "improved_mdd": 0}

    for code, raw in items:
        records = load_kline(raw, args.min_history + 5)
        if records is None:
            continue
        if tp_variants:
            gridres = backtest_etf_grid(code, records, cfg, tp_variants)
            if gridres is None:
                continue
            all_signals.extend(gridres["signals"])
            variants = gridres["variants"]
            base = variants["baseline"]
            transitions_src = gridres["transitions"]
            if args.code:
                case_study = {"code": code, "variants": variants}
        else:
            res = backtest_etf(code, records, cfg)
            if res is None:
                continue
            all_signals.extend(res["signals"])
            variants = None
            base = res
            transitions_src = res["transitions"]
            if args.code and res.get("tp_stats") is not None:
                case_study = {"code": code, "baseline": res}

        if base["strategy"] and base["buyhold"]:
            strat_list.append(base["strategy"])
            if base["strategy_gross"]:
                gross_list.append(base["strategy_gross"])
            bh_list.append(base["buyhold"])
            cost_drag_list.append(base["cost_drag_pct"])
            trade_list.append(base["trade_count"])
            per_etf[code] = {
                "strategy": base["strategy"],
                "strategy_gross": base["strategy_gross"],
                "buyhold": base["buyhold"],
                "trade_count": base["trade_count"],
                "cost_drag_pct": base["cost_drag_pct"],
                "total_cost_pct": base["total_cost_pct"],
            }
        if variants:
            b_strat = base["strategy"]
            for name, v in variants.items():
                agg = variant_agg[name]
                if v["strategy"] and b_strat:
                    agg["strategy"].append(v["strategy"])
                    agg["trade"].append(v["trade_count"])
                    agg["cost_drag"].append(v["cost_drag_pct"])
                    if v["strategy"]["total_return_pct"] > b_strat["total_return_pct"]:
                        agg["improved_ret"] += 1
                    if v["strategy"]["max_drawdown_pct"] > b_strat["max_drawdown_pct"]:
                        agg["improved_mdd"] += 1
                    ts = v.get("tp_stats")
                    if ts:
                        agg["fires"] += ts["fires"]
                        agg["rearms"] += ts["rearms"]
                        agg["clears"] += ts["clears"]
                        if ts["fires"] > 0:
                            agg["etfs_fired"] += 1
        for to_state, evs in transitions_src.items():
            transitions_all[to_state].extend(evs)
        n_done += 1
        if n_done % 50 == 0:
            print(f"  进度: {n_done}/{len(items)}")

    print(f"\n有效 ETF 数: {n_done}，信号评估点: {len(all_signals)}")

    # 汇总
    state_stats, baseline = compute_signal_stats(all_signals)
    print_signal_stats(state_stats, baseline)

    def _avg(metrics_list, key):
        vals = [m[key] for m in metrics_list if key in m]
        return sum(vals) / len(vals) if vals else float("nan")

    strategy_avg = {
        k: round(_avg(strat_list, k), 2) for k in
        ("total_return_pct", "annualized_pct", "max_drawdown_pct",
         "ann_vol_pct", "sharpe", "avg_exposure")
    }
    buyhold_avg = {
        k: round(_avg(bh_list, k), 2) for k in
        ("total_return_pct", "annualized_pct", "max_drawdown_pct",
         "ann_vol_pct", "sharpe", "avg_exposure")
    }
    win_vs_bh = sum(1 for s, b in zip(strat_list, bh_list)
                    if s["total_return_pct"] > b["total_return_pct"])
    strategy_avg["win_vs_buyhold_ratio"] = round(win_vs_bh / len(strat_list) * 100, 1) if strat_list else 0.0
    strategy_avg["etfs"] = len(strat_list)
    strategy_avg["cost_drag_pct"] = round(sum(cost_drag_list) / len(cost_drag_list), 2) if cost_drag_list else 0.0
    strategy_avg["avg_trade_count"] = round(sum(trade_list) / len(trade_list), 1) if trade_list else 0.0
    print_strategy(strategy_avg, buyhold_avg, len(strat_list))

    if len(strat_list) > 0:
        print(f"策略跑赢买入持有的 ETF 占比: {strategy_avg['win_vs_buyhold_ratio']:.1f}% "
              f"({win_vs_bh}/{len(strat_list)})")
        print(f"平均成本拖累(策略总收益 gross→net): {strategy_avg['cost_drag_pct']:+.2f}% | "
              f"平均交易次数: {strategy_avg['avg_trade_count']}")

    trans_summary = summarize_transitions(transitions_all)
    print_transitions(trans_summary)

    if args.code and per_etf:
        code = args.code
        print(f"\n单 ETF 详情: {code}")
        print(f"  策略(net): {json.dumps(per_etf[code]['strategy'], ensure_ascii=False)}")
        print(f"  策略(gross): {json.dumps(per_etf[code]['strategy_gross'], ensure_ascii=False)}")
        print(f"  买入持有: {json.dumps(per_etf[code]['buyhold'], ensure_ascii=False)}")
        print(f"  交易次数: {per_etf[code]['trade_count']} | 成本拖累: {per_etf[code]['cost_drag_pct']:+.2f}% | "
              f"总成本占比: {per_etf[code]['total_cost_pct']}%")

    # 保存
    output = {
        "config": {
            "kline_file": kline_file,
            "eval_step": args.eval_step,
            "min_history": args.min_history,
            "use_confirmed": args.use_confirmed,
            "exposure_map": EXPOSURE,
            "forward_days": FORWARD_DAYS,
            "cost_model": cost,
            "position_value": position_value,
            "etfs": n_done,
        },
        "state_signal_stats": state_stats,
        "baseline_stats": baseline,
        "strategy_summary": strategy_avg,
        "buyhold_summary": buyhold_avg,
        "transitions": trans_summary,
        "per_etf": per_etf,
        "signals": all_signals,
    }
    # 仅在启用回撤止盈时注入配置（保证关闭时输出与改动前逐位一致）
    if tp_cfg or tp_variants:
        output["config"]["trailing_tp"] = {
            "enabled": True,
            "params": tp_cfg,
            "grid": None if not tp_variants else [n for n, _ in tp_variants],
            "concept_note": (
                "盈利侧暴露上限（只减不增），独立于 (i) 亏损侧 结构失效位/灾难保护位 三层退出 "
                "与 (ii) 状态 T7「保护收益、降低」。T7 进入条件为 pos250>=0.70"
                "（trend_analysis.classify_trend_state），对 250 日分位从未达 0.70 的标的"
                "（如深跌后强反弹的标的）结构性不可达 —— 本规则用于补该缺口。"
            ),
        }
    with open(args.output, "w") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"\n回测结果已保存: {args.output}（{os.path.getsize(args.output) / 1024 / 1024:.1f} MB）")

    # ── 回撤止盈 A/B 汇总输出 ────────────────────────────────────────────
    if not tp_variants:
        return

    def _vavg(mlist, key):
        vals = [m[key] for m in mlist if key in m]
        return round(sum(vals) / len(vals), 2) if vals else None

    vkeys = ("total_return_pct", "annualized_pct", "max_drawdown_pct",
             "ann_vol_pct", "sharpe", "avg_exposure")
    base_summary = {k: _vavg(variant_agg["baseline"]["strategy"], k) for k in vkeys}
    base_summary["avg_trade_count"] = (
        round(sum(variant_agg["baseline"]["trade"]) / len(variant_agg["baseline"]["trade"]), 1)
        if variant_agg["baseline"]["trade"] else None)
    base_summary["cost_drag_pct"] = (round(sum(variant_agg["baseline"]["cost_drag"])
                                           / len(variant_agg["baseline"]["cost_drag"]), 2)
                                     if variant_agg["baseline"]["cost_drag"] else None)
    base_summary["etfs"] = len(variant_agg["baseline"]["strategy"])

    variants_out = []
    for name, params in tp_variants:
        agg = variant_agg[name]
        summ = {k: _vavg(agg["strategy"], k) for k in vkeys}
        n = len(agg["strategy"])
        summ["avg_trade_count"] = round(sum(agg["trade"]) / len(agg["trade"]), 1) if agg["trade"] else None
        summ["cost_drag_pct"] = round(sum(agg["cost_drag"]) / len(agg["cost_drag"]), 2) if agg["cost_drag"] else None
        summ["etfs"] = n
        delta = None
        if n and base_summary["etfs"]:
            delta = {k: (None if (summ[k] is None or base_summary[k] is None)
                         else round(summ[k] - base_summary[k], 2))
                     for k in ("total_return_pct", "annualized_pct", "max_drawdown_pct",
                               "ann_vol_pct", "sharpe", "avg_exposure", "cost_drag_pct")}
            delta["avg_trade_count"] = (round(summ["avg_trade_count"] - base_summary["avg_trade_count"], 1)
                                        if summ["avg_trade_count"] is not None
                                        and base_summary["avg_trade_count"] is not None else None)
        variants_out.append({
            "name": name,
            "params": params,
            "summary": summ,
            "delta_vs_baseline": delta,
            "tp_activity": {"fire_count": agg["fires"], "rearm_count": agg["rearms"],
                            "clear_count": agg["clears"], "etfs_fired": agg["etfs_fired"]},
            "distribution": {"etfs_improved_return": agg["improved_ret"],
                             "etfs_improved_mdd": agg["improved_mdd"]},
        })

    ab = {
        "config": {
            "kline_file": kline_file, "eval_step": args.eval_step,
            "min_history": args.min_history, "use_confirmed": args.use_confirmed,
            "cost_model": cost, "position_value": position_value, "etfs": n_done,
            "tp_grid": [{"name": n, "params": p} for n, p in tp_variants],
        },
        "baseline_strategy": base_summary,
        "buyhold_summary": buyhold_avg,
        "variants": variants_out,
    }
    if case_study:
        ab["case_study"] = case_study
    with open(args.tp_output, "w") as f:
        json.dump(ab, f, ensure_ascii=False)

    # 控制台对比表
    hdr = f"{'变体':<24}{'总收益%':>9}{'年化%':>8}{'最大回撤%':>10}{'波动%':>8}{'夏普':>7}{'暴露':>7}{'换手':>7}{'成本拖累%':>10}{'触发数':>7}{'触发标的':>8}"
    print("\n" + "=" * len(hdr.encode("gbk", errors="ignore")))
    print(" 回撤止盈 A/B（策略均值；baseline = 关闭该规则）")
    print("=" * len(hdr.encode("gbk", errors="ignore")))
    print(hdr)
    print("-" * len(hdr.encode("gbk", errors="ignore")))
    for v in variants_out:
        s = v["summary"]
        print(f"{v['name']:<24}{s['total_return_pct']:>9.2f}{s['annualized_pct']:>8.2f}"
              f"{s['max_drawdown_pct']:>10.2f}{s['ann_vol_pct']:>8.2f}{s['sharpe']:>7.2f}"
              f"{s['avg_exposure']:>7.3f}{s['avg_trade_count']:>7.1f}{s['cost_drag_pct']:>10.2f}"
              f"{v['tp_activity']['fire_count']:>7}{v['tp_activity']['etfs_fired']:>8}")
    print(f"\nA/B 对比已保存: {args.tp_output}（{os.path.getsize(args.tp_output) / 1024 / 1024:.1f} MB）")

    if case_study:
        print("\n单标的 case study:")
        for name, v in case_study.get("variants", {}).items():
            if not v["strategy"]:
                continue
            evs = v.get("tp_events") or []
            print(f"  [{name}] 总收益 {v['strategy']['total_return_pct']:+.2f}% | "
                  f"最大回撤 {v['strategy']['max_drawdown_pct']:+.2f}% | "
                  f"夏普 {v['strategy']['sharpe']:.2f} | 换手 {v['trade_count']}")
            for e in evs:
                print(f"       {e['event']:<6} {e['date']}  price={e['price']}  "
                      f"peak={e['peak_close']}  entry={e['entry_close']}  "
                      f"回撤={e['retrace_pct']}%  cap_exp={e['cap_exp']}")


if __name__ == "__main__":
    main()
