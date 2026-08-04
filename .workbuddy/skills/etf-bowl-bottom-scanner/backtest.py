#!/usr/bin/env python3
"""
ETF碗底形态回测脚本

目标：利用历史K线数据，模拟算法在不同历史时点的评分/标签输出，
      并追踪后续实际走势，验证碗底信号的可靠性。

核心思路：
  对每个ETF，在多个历史时间点T处运行 analyze_bowl_bottom()，
  只使用T时刻之前的数据（避免未来函数），然后统计：
  - T+N日后涨跌幅
  - 信号（确认碗底/减速筑底/下跌中继）与后续走势的对应关系
  - 胜率（信号后上涨概率）、平均收益、最大回撤

输出：
  - backtest_results.json：每只ETF每个时点的详细回测记录
  - backtest_summary.txt：汇总统计报告
"""

import json
import sys
import os
from pathlib import Path

# ====== 复用原分析算法的核心函数（直接内联，不导入）======

def lin_slope(arr, win):
    if len(arr) < win:
        return 0
    y = arr[-win:]
    x = list(range(win))
    xm, ym = sum(x) / win, sum(y) / win
    num = sum((x[i] - xm) * (y[i] - ym) for i in range(win))
    den = sum((x[i] - xm) ** 2 for i in range(win))
    s = num / den if den else 0
    return s * win / ym * 100 if ym else 0


def quadratic_fit(prices):
    n = len(prices)
    if n < 10:
        return 0, 0, 0
    xs = list(range(n))
    xm = sum(xs) / n
    ym = sum(prices) / n
    sxx = sum((x - xm) ** 2 for x in xs)
    sxxxx = sum((x - xm) ** 4 for x in xs)
    sxxyy = 0
    sxy = 0
    for x, y in zip(xs, prices):
        dx = x - xm
        sxxyy += dx * dx * (y - ym)
        sxy += dx * (y - ym)
    den = n * sxxxx - sxx * sxx
    if den == 0:
        return 0, 0, 0
    a = (n * sxxyy - sxx * sxy) / den
    b = (sxy - a * sxx) / sxx if sxx != 0 else 0
    vx = -b / (2 * a) if a != 0 else 0
    return a, b, vx


def atr(highs, lows, closes, window):
    n = len(closes)
    if n < 2 or window <= 0:
        return 0
    start = max(1, n - window)
    s = 0
    count = 0
    for i in range(start, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        s += tr
        count += 1
    return s / count if count else 0


def analyze_bowl_bottom(name, closes, highs, lows, vols, n=None):
    """
    与原analyze.py逻辑完全一致，但接受已处理好的价格序列，
    而不是原始JSON K线数据。
    n可以指定只使用前n个数据点（用于回测的时点截断）。
    """
    if n is not None:
        closes = closes[:n]
        highs = highs[:n]
        lows = lows[:n]
        vols = vols[:n]

    n_items = len(closes)
    if n_items < 80:
        return None

    cur = closes[-1]

    # ---- Position in range ----
    n120 = min(120, n_items)
    n250_ = min(250, n_items)
    hi120, lo120 = max(highs[-n120:]), min(lows[-n120:])
    hi250, lo250 = max(highs[-n250_:]), min(lows[-n250_:])
    pos120 = (cur - lo120) / (hi120 - lo120) if hi120 > lo120 else 0.5
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5
    dd120 = (cur - hi120) / hi120 * 100 if hi120 > 0 else 0
    dist_low = (cur - lo120) / lo120 * 100 if lo120 > 0 else 0

    # ---- Trend windows ----
    t20 = lin_slope(closes, 20)
    t60 = lin_slope(closes, 60)
    if n_items >= 60:
        seg = closes[-60:-20]
        t_prior = lin_slope(seg, len(seg))
    else:
        t_prior = 0

    # ---- Deceleration ratio ----
    t20_rate = t20
    t_prior_rate20 = t_prior / 2.0
    if t_prior_rate20 < -0.1:
        decel_ratio = t20_rate / t_prior_rate20
    else:
        decel_ratio = 1.0

    # ---- Higher-low check ----
    if n_items >= 60:
        low_recent10 = min(lows[-10:])
        low_prior10 = min(lows[-20:-10])
        higher_low = low_recent10 > low_prior10
        hl_pct = (low_recent10 - low_prior10) / low_prior10 * 100 if low_prior10 > 0 else 0
    else:
        higher_low = False
        hl_pct = 0

    # ---- Volume & volatility ----
    vol20 = sum(vols[-20:]) / 20
    vol60 = sum(vols[-60:]) / 60
    vol_ratio = vol20 / vol60 if vol60 > 0 else 1
    atr20 = atr(highs, lows, closes, 20)
    atr60 = atr(highs, lows, closes, 60)
    atr_ratio = atr20 / atr60 if atr60 > 0 else 1

    # ---- MA distances ----
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    d_ma20 = (cur - ma20) / ma20 * 100
    d_ma60 = (cur - ma60) / ma60 * 100

    # ---- Quadratic U-shape fit over last 120 days ----
    seg120 = closes[-120:] if n_items >= 120 else closes
    a_coef, b_coef, vx = quadratic_fit(seg120)
    seg_len = len(seg120)
    mean_price = sum(seg120) / seg_len
    curvature = a_coef * seg_len * seg_len / mean_price * 100 if mean_price else 0
    vx_frac = vx / seg_len if seg_len else 0
    is_convex = curvature > 0.05
    vertex_recent = 0.35 < vx_frac < 0.95

    # ============ SCORING ============
    score = 0

    # 1. 120-day range position (max 25)
    if pos120 <= 0.10:
        score += 25
    elif pos120 <= 0.20:
        score += 20
    elif pos120 <= 0.30:
        score += 12
    elif pos120 <= 0.40:
        score += 5

    # 2. 250-day range position (max 20)
    if pos250 <= 0.15:
        score += 20
    elif pos250 <= 0.25:
        score += 15
    elif pos250 <= 0.35:
        score += 8

    # 3. BOWL SHAPE (max 20)
    if t_prior < -5 and -2 <= t20 <= 3 and decel_ratio < 0.8:
        score += 20
    elif t_prior < -5 and -3 <= t20 <= 4 and decel_ratio < 1.0:
        score += 14
    elif -4 <= t20 <= 4:
        score += 8
    elif t20 < -6:
        score -= 5

    # 3b. Higher-low bonus (max 5)
    if higher_low and hl_pct > 0.5:
        score += 5
    elif higher_low:
        score += 2

    # 4. Quadratic U-shape curvature (max 10)
    if is_convex and vertex_recent:
        score += 10
    elif is_convex:
        score += 5

    # 5. Volume contraction (max 8)
    if vol_ratio < 0.7:
        score += 8
    elif vol_ratio < 0.85:
        score += 5
    elif vol_ratio < 1.0:
        score += 3

    # 6. Volatility compression (max 7)
    if atr_ratio < 0.7:
        score += 7
    elif atr_ratio < 0.85:
        score += 5
    elif atr_ratio < 1.0:
        score += 2

    # 7. Below 60MA (max 10)
    if -12 <= d_ma60 <= -2:
        score += 10
    elif -20 <= d_ma60 < -12:
        score += 6
    elif -2 <= d_ma60 <= 3:
        score += 4

    # Hard penalties
    if t20 < -8:
        score -= 15
    if dd120 > -5:
        score -= 20

    score = max(0, min(100, score))

    # ---- Bowl confirmation label ----
    bottom_zone = pos120 <= 0.25 and pos250 <= 0.25
    stabilized = -2 <= t20 <= 3 and decel_ratio < 0.8 and t_prior < -5
    decelerating = -3 <= t20 <= 4 and decel_ratio < 1.0 and t_prior < -5
    if bottom_zone and stabilized and higher_low and score >= 65:
        label = "确认碗底"
    elif bottom_zone and (stabilized or (decelerating and higher_low)) and score >= 58:
        label = "碗底确认中"
    elif bottom_zone and decelerating and score >= 50:
        label = "减速筑底"
    elif bottom_zone and -4 <= t20 <= 5:
        label = "低位盘整"
    elif t20 < -6:
        label = "下跌中继"
    else:
        label = "观望"

    return {
        "score": score,
        "label": label,
        "current": round(cur, 4),
        "pos120": round(pos120 * 100, 1),
        "pos250": round(pos250 * 100, 1),
        "drawdown120": round(dd120, 1),
        "t20": round(t20, 1),
        "t60": round(t60, 1),
        "t_prior": round(t_prior, 1),
        "decel_ratio": round(decel_ratio, 2),
        "higher_low": higher_low,
        "hl_pct": round(hl_pct, 1),
        "curvature": round(curvature, 2),
        "vertex_frac": round(vx_frac, 2),
        "vol_ratio": round(vol_ratio, 2),
        "atr_ratio": round(atr_ratio, 2),
        "d_ma20": round(d_ma20, 1),
        "d_ma60": round(d_ma60, 1),
    }


def parse_kline(raw_kline_data):
    """Parse raw K-line JSON (from westock-data) into sorted arrays."""
    records = []
    for k in raw_kline_data:
        try:
            records.append({
                "date": k["date"],
                "close": float(k["last"]),
                "high": float(k["high"]),
                "low": float(k["low"]),
                "volume": float(k.get("volume", 0)),
            })
        except (KeyError, ValueError):
            continue
    if len(records) < 80:
        return None
    records.sort(key=lambda x: x["date"])
    return {
        "dates": [r["date"] for r in records],
        "closes": [r["close"] for r in records],
        "highs": [r["high"] for r in records],
        "lows": [r["low"] for r in records],
        "vols": [r["volume"] for r in records],
    }


def compute_forward_returns(closes, from_idx, periods):
    """
    Compute forward returns from `from_idx` for each lookahead period.
    Returns dict of {period: pct_change} or None if insufficient data.
    """
    results = {}
    entry_price = closes[from_idx - 1]  # the "current" price at signal time
    for p in periods:
        target_idx = from_idx - 1 + p
        if target_idx < len(closes):
            exit_price = closes[target_idx]
            results[f"fwd{p}d"] = round((exit_price - entry_price) / entry_price * 100, 2)
        else:
            results[f"fwd{p}d"] = None
    # Max drawdown over forward period
    max_dd = 0
    peak = entry_price
    for i in range(from_idx - 1, min(from_idx - 1 + max(periods), len(closes))):
        price = closes[i]
        peak = max(peak, price)
        dd = (price - peak) / peak * 100
        max_dd = min(max_dd, dd)
    results["fwd_max_dd"] = round(max_dd, 2)
    return results


def main():
    # Load K-line data
    kline_file = os.path.join(os.getcwd(), "etf_kline_data_500.json")
    if not os.path.exists(kline_file):
        print(f"❌ 未找到K线数据文件: {kline_file}")
        sys.exit(1)

    print("📊 加载K线数据...")
    with open(kline_file) as f:
        raw_data = json.load(f)

    # Config
    MIN_HISTORY = 120       # 至少120个交易日的历史数据才能评估
    EVAL_STEP = 10          # 每隔10个交易日评估一次
    FORWARD_PERIODS = [5, 10, 20, 30, 60, 90]  # 前瞻期

    all_results = []
    etf_summaries = {}

    etf_list = list(raw_data.items())
    total = len(etf_list)

    print(f"📊 共{total}只ETF，开始回测...")
    print(f"   参数: 最少历史={MIN_HISTORY}天, 评估间隔={EVAL_STEP}天, 前瞻期={FORWARD_PERIODS}")
    print()

    for ei, (code, raw_kline) in enumerate(etf_list):
        parsed = parse_kline(raw_kline)
        if not parsed:
            continue

        n = len(parsed["closes"])
        # Evaluate at multiple historical points
        eval_points = list(range(MIN_HISTORY, n - max(FORWARD_PERIODS), EVAL_STEP))
        if not eval_points:
            eval_points = [n - 1]  # at least current point

        etf_signals = {"确认碗底": [], "碗底确认中": [], "减速筑底": [], "低位盘整": [], "下跌中继": [], "观望": []}

        for t in eval_points:
            analysis = analyze_bowl_bottom(
                name="",  # not needed for backtest
                closes=parsed["closes"],
                highs=parsed["highs"],
                lows=parsed["lows"],
                vols=parsed["vols"],
                n=t,
            )
            if not analysis:
                continue

            fwd = compute_forward_returns(parsed["closes"], t, FORWARD_PERIODS)

            record = {
                "code": code,
                "eval_date": parsed["dates"][t - 1],
                "eval_idx": t - 1,
                "price": analysis["current"],
                "score": analysis["score"],
                "label": analysis["label"],
                "pos120": analysis["pos120"],
                "pos250": analysis["pos250"],
                "decel_ratio": analysis["decel_ratio"],
                "higher_low": analysis["higher_low"],
                "t20": analysis["t20"],
                "t_prior": analysis["t_prior"],
                **fwd,
            }
            all_results.append(record)
            etf_signals[analysis["label"]].append(record)

        if (ei + 1) % 50 == 0:
            print(f"  进度: {ei+1}/{total}")

    print(f"\n✅ 回测完成，共{len(all_results)}个评估时点")

    # ========== Summary Statistics ==========
    print("\n" + "=" * 80)
    print("📊 回测汇总报告")
    print("=" * 80)

    # Group by label
    label_stats = {}
    for label in ["确认碗底", "碗底确认中", "减速筑底", "低位盘整", "下跌中继", "观望"]:
        group = [r for r in all_results if r["label"] == label]
        if not group:
            continue

        stats = {"count": len(group), "unique_etfs": len(set(r["code"] for r in group))}
        for period in FORWARD_PERIODS:
            key = f"fwd{period}d"
            valid_returns = [r[key] for r in group if r[key] is not None]
            if valid_returns:
                win_count = sum(1 for v in valid_returns if v > 0)
                stats[f"{key}_avg"] = round(sum(valid_returns) / len(valid_returns), 2)
                stats[f"{key}_winrate"] = round(win_count / len(valid_returns) * 100, 1)
                stats[f"{key}_median"] = round(sorted(valid_returns)[len(valid_returns) // 2], 2)
                stats[f"{key}_best"] = round(max(valid_returns), 2)
                stats[f"{key}_worst"] = round(min(valid_returns), 2)
                stats[f"{key}_n"] = len(valid_returns)
        label_stats[label] = stats

    # Print label summary
    header = f"{'信号':<12}{'次数':<6}{'ETF数':<6}"
    for p in FORWARD_PERIODS:
        header += f"{p}日均%:<10{p}d胜率:<9"
    print(header)
    print("-" * 100)

    for label, s in label_stats.items():
        row = f"{label:<12}{s['count']:<6}{s['unique_etfs']:<6}"
        for p in FORWARD_PERIODS:
            k = f"fwd{p}d"
            if f"{k}_avg" in s:
                row += f"{s[f'{k}_avg']:<10}{s[f'{k}_winrate']:<9}%"
            else:
                row += f"{'N/A':<10}{'N/A':<9}"
        print(row)

    # ========== Key insight: 确认碗底 信号分析 ==========
    confirmed = [r for r in all_results if r["label"] == "确认碗底"]
    print(f"\n{'='*80}")
    print(f"🎯 关键信号分析: 确认碗底 (共{len(confirmed)}次, {len(set(r['code'] for r in confirmed))}只ETF)")
    print(f"{'='*80}")

    for p in FORWARD_PERIODS:
        key = f"fwd{p}d"
        valid = [r for r in confirmed if r[key] is not None]
        if not valid:
            continue
        avg_ret = sum(r[key] for r in valid) / len(valid)
        win_rate = sum(1 for r in valid if r[key] > 0) / len(valid) * 100
        best = max(r[key] for r in valid)
        worst = min(r[key] for r in valid)
        print(f"  {p}日后: 平均 {avg_ret:+.2f}% | 胜率 {win_rate:.1f}% | 最好 {best:+.2f}% | 最差 {worst:+.2f}%")

    # Best / Worst examples
    if confirmed and any(r.get("fwd20d") is not None for r in confirmed):
        valid_20 = [r for r in confirmed if r.get("fwd20d") is not None]
        valid_20.sort(key=lambda x: -(x["fwd20d"] or -999))
        print(f"\n  🟢 最成功示例 (20日后收益最高Top 5):")
        for i, r in enumerate(valid_20[:5]):
            print(f"    {i+1}. {r['code']} @{r['eval_date']} 买入{r['price']:.2f} "
                  f"→ 20日后 {r['fwd20d']:+.2f}%")

        valid_20.sort(key=lambda x: (x.get("fwd20d") or 999))
        print(f"\n  🔴 最失败示例 (20日后收益最低Top 5):")
        for i, r in enumerate(valid_20[:5]):
            print(f"    {i+1}. {r['code']} @{r['eval_date']} 买入{r['price']:.2f} "
                  f"→ 20日后 {r['fwd20d']:+.2f}%")

    # ========== Quarterly breakdown ==========
    print(f"\n{'='*80}")
    print(f"📅 按季度分解 (确认碗底 + 碗底确认中)")
    print(f"{'='*80}")

    key_signals = [r for r in all_results if r["label"] in ["确认碗底", "碗底确认中"]]
    from collections import defaultdict
    quarterly = defaultdict(list)
    for r in key_signals:
        d = r["eval_date"]
        q = d[:4] + "-Q" + str((int(d[5:7]) - 1) // 3 + 1)
        quarterly[q].append(r)

    for q in sorted(quarterly.keys()):
        signals = quarterly[q]
        n = len(signals)
        f20 = [r["fwd20d"] for r in signals if r.get("fwd20d") is not None]
        f60 = [r["fwd60d"] for r in signals if r.get("fwd60d") is not None]
        f90 = [r["fwd90d"] for r in signals if r.get("fwd90d") is not None]
        s20 = f"{sum(f20)/len(f20):+.1f}%({sum(1 for v in f20 if v>0)/len(f20)*100:.0f}%胜)" if f20 else "N/A"
        s60 = f"{sum(f60)/len(f60):+.1f}%({sum(1 for v in f60 if v>0)/len(f60)*100:.0f}%胜)" if f60 else "N/A"
        s90 = f"{sum(f90)/len(f90):+.1f}%({sum(1 for v in f90 if v>0)/len(f90)*100:.0f}%胜)" if f90 else "N/A"
        print(f"  {q}: {n}次 | 20d={s20} | 60d={s60} | 90d={s90}")

    # ========== Best-performing ETF bowl signals ==========
    print(f"\n{'='*80}")
    print(f"🏆 历史最佳碗底信号 Top 10 (按90日收益)")
    print(f"{'='*80}")
    ranked = sorted(key_signals, key=lambda x: -(x.get("fwd90d") or -9999))
    for i, r in enumerate(ranked[:10]):
        print(f"  {i+1}. {r['code']} @{r['eval_date']} {r['label']}(得分{r['score']}) → 20d:{r.get('fwd20d','?')}% 60d:{r.get('fwd60d','?')}% 90d:{r.get('fwd90d','?')}%")

    # Save results
    output_file = os.path.join(os.getcwd(), "etf_bowl_backtest_500_results.json")
    with open(output_file, "w") as f:
        json.dump({
            "config": {
                "min_history": MIN_HISTORY,
                "eval_step": EVAL_STEP,
                "forward_periods": FORWARD_PERIODS,
                "total_etfs": total,
                "total_eval_points": len(all_results),
            },
            "label_summary": label_stats,
            "results": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n📁 详细结果已保存: {output_file}")

    return all_results


if __name__ == "__main__":
    main()
