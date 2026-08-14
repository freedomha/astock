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

Usage:
  python3 .workbuddy/skills/etf-operation-plan/backtest.py \
      [--kline-file <path>] [--code sh518880] [--max-etfs N] \
      [--eval-step 5] [--min-history 150] [--use-confirmed] \
      [--output backtest_trend_state_results.json]
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


def simulate_strategy(closes, daily, n):
    start = next((i for i in range(n) if daily[i] is not None), None)
    if start is None or start + 1 >= n:
        return None, None

    s_rets, b_rets, exposures = [], [], []
    for i in range(start + 1, n):
        dr = closes[i] / closes[i - 1] - 1
        exp = EXPOSURE[daily[i]]
        b_rets.append(dr)
        s_rets.append(exp * dr)
        exposures.append(exp)
    return compute_metrics(s_rets, exposures), compute_metrics(b_rets, [1.0] * len(b_rets))


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
def backtest_etf(code, records, cfg):
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
    signals = build_signal_records(evals, seq, closes, n, code)
    daily = build_daily_exposure(evals, seq, n, cfg.use_confirmed)
    strat_metrics, bh_metrics = simulate_strategy(closes, daily, n)
    transitions = collect_transitions(evals, seq, closes, n)

    return {
        "signals": signals,
        "strategy": strat_metrics,
        "buyhold": bh_metrics,
        "transitions": transitions,
    }


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

    cfg = argparse.Namespace(
        eval_step=args.eval_step,
        min_history=args.min_history,
        use_confirmed=args.use_confirmed,
    )

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
    print(f"ETF 数: {len(items)}")

    all_signals = []
    strat_list, bh_list = [], []
    per_etf = {}
    transitions_all = defaultdict(list)
    n_done = 0

    for code, raw in items:
        records = load_kline(raw, args.min_history + 5)
        if records is None:
            continue
        res = backtest_etf(code, records, cfg)
        if res is None:
            continue
        all_signals.extend(res["signals"])
        if res["strategy"] and res["buyhold"]:
            strat_list.append(res["strategy"])
            bh_list.append(res["buyhold"])
            per_etf[code] = {
                "strategy": res["strategy"],
                "buyhold": res["buyhold"],
            }
        for to_state, evs in res["transitions"].items():
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
    print_strategy(strategy_avg, buyhold_avg, len(strat_list))

    if len(strat_list) > 0:
        print(f"\n策略跑赢买入持有的 ETF 占比: {strategy_avg['win_vs_buyhold_ratio']:.1f}% "
              f"({win_vs_bh}/{len(strat_list)})")

    trans_summary = summarize_transitions(transitions_all)
    print_transitions(trans_summary)

    if args.code and per_etf:
        code = args.code
        print(f"\n单 ETF 详情: {code}")
        print(f"  策略:   {json.dumps(per_etf[code]['strategy'], ensure_ascii=False)}")
        print(f"  持有:   {json.dumps(per_etf[code]['buyhold'], ensure_ascii=False)}")

    # 保存
    output = {
        "config": {
            "kline_file": kline_file,
            "eval_step": args.eval_step,
            "min_history": args.min_history,
            "use_confirmed": args.use_confirmed,
            "exposure_map": EXPOSURE,
            "forward_days": FORWARD_DAYS,
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
    with open(args.output, "w") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"\n回测结果已保存: {args.output}（{os.path.getsize(args.output) / 1024 / 1024:.1f} MB）")


if __name__ == "__main__":
    main()
