#!/usr/bin/env python3
"""
头肩底形态回测 (Head-Shoulder-Bottom Backtest)

Walk through rolling 250-day windows. When a pattern is detected,
record forward returns to evaluate predictive power.

Imports scoring engine from analyze.py — always tests current engine version.

Usage:
  python3 backtest.py [kline_data_file]   # default: etf_kline_data_500.json in project root
"""

import json
import os
import sys
from collections import defaultdict

# Ensure the skill directory is on the path so we can import analyze
_skill_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_skill_dir, "..", "..", ".."))
sys.path.insert(0, _skill_dir)

from analyze import (
    find_local_extrema,
    find_head_shoulder_pattern,
    score_pattern,
    label_pattern,
)


def backtest(klines_by_etf, window_size=250, step=20):
    """
    For each ETF, walk through rolling windows.
    At each window: detect pattern, record forward returns at [5, 10, 20, 60, 120] days.
    """
    signals = {
        "🟢 头肩底确认": [],
        "🟢 头肩底形成中": [],
        "🟡 头肩底候选": [],
        "baseline": [],
    }

    total_windows = 0
    pattern_windows = 0

    for code, records in klines_by_etf.items():
        n = len(records)
        dates = [r["date"] for r in records]
        closes = [r["close"] for r in records]
        highs_p = [r["high"] for r in records]
        lows_p = [r["low"] for r in records]
        vols = [r["volume"] for r in records]

        for end_idx in range(window_size, n - 120, step):
            total_windows += 1
            start_idx = end_idx - window_size
            win_closes = closes[start_idx:end_idx]
            win_highs = highs_p[start_idx:end_idx]
            win_lows = lows_p[start_idx:end_idx]
            win_vols = vols[start_idx:end_idx]

            valley_list, peak_list = find_local_extrema(win_closes)
            pattern = find_head_shoulder_pattern(valley_list, peak_list, win_closes, win_vols)

            score = pattern["score"] if pattern else 0
            rtn = pattern.get("rs_to_neck_pct", 99) if pattern else 99
            label = label_pattern(score, rtn) if pattern else "非头肩底"

            entry_price = closes[end_idx - 1] if end_idx > 0 else 0
            fwd = {}
            for horizon in [5, 10, 20, 60, 120]:
                fwd_idx = end_idx + horizon
                if fwd_idx < len(closes):
                    fwd[horizon] = (closes[fwd_idx] - entry_price) / entry_price * 100
                else:
                    fwd[horizon] = None

            if label.startswith("🟢") or label.startswith("🟡"):
                # head_shoulder_confirm / head_shoulder_forming / head_shoulder_candidate
                pattern_windows += 1
                signals[label].append({
                    "code": code,
                    "date": dates[end_idx - 1],
                    "score": score,
                    "label": label,
                    "fwd": fwd,
                })
            else:
                signals["baseline"].append({
                    "code": code,
                    "date": dates[end_idx - 1],
                    "fwd": fwd,
                })

    return signals, total_windows, pattern_windows


def compute_stats(signal_list):
    if not signal_list:
        return {}
    horizons = [5, 10, 20, 60, 120]
    stats = {}
    for h in horizons:
        returns = [s["fwd"][h] for s in signal_list if s["fwd"].get(h) is not None]
        if not returns:
            continue
        pos = sum(1 for r in returns if r > 0)
        avg = sum(returns) / len(returns)
        win_rate = pos / len(returns) * 100 if returns else 0
        stats[h] = {
            "count": len(returns),
            "avg_return": round(avg, 2),
            "win_rate": round(win_rate, 1),
            "max": round(max(returns), 2),
            "min": round(min(returns), 2),
        }
    return stats


def main():
    # Determine kline file path
    if len(sys.argv) > 1:
        kline_file = sys.argv[1]
    else:
        kline_file = os.path.join(_project_root, "etf_kline_data_500.json")

    print(f"Loading kline data from: {kline_file}")
    with open(kline_file) as f:
        raw_data = json.load(f)

    print(f"Loaded {len(raw_data)} ETFs")
    print("Processing rolling 250-day windows (step=20)...")

    # Convert to chronological format (newest-first → oldest-first)
    klines_chrono = {}
    for code, bars in raw_data.items():
        if not isinstance(bars, list) or len(bars) < 250:
            continue
        records = []
        for k in reversed(bars):
            try:
                records.append({
                    "date": k["date"],
                    "close": float(k["last"]),
                    "high": float(k["high"]),
                    "low": float(k["low"]),
                    "volume": float(k.get("volume", 0)),
                })
            except (KeyError, ValueError, TypeError):
                continue
        if len(records) >= 250:
            klines_chrono[code] = records

    print(f"Valid ETFs with >=250 bars: {len(klines_chrono)}")

    print("\nRunning backtest...")
    signals, total_windows, pattern_windows = backtest(klines_chrono)

    print(f"\n{'='*80}")
    print(" 头肩底形态回测结果 (Head-Shoulder-Bottom Backtest)")
    print(f"{'='*80}")
    print(f" 总检测窗口: {total_windows}")
    print(f" 有形态信号: {pattern_windows} ({pattern_windows/total_windows*100:.1f}%)")
    print()

    horizons = [5, 10, 20, 60, 120]
    label_order = ["🟢 头肩底确认", "🟢 头肩底形成中", "🟡 头肩底候选"]

    # Baseline stats
    baseline = compute_stats(signals["baseline"])
    print(f"--- 无形态基线 (共 {len(signals['baseline'])} 窗口) ---")
    for h in horizons:
        if h in baseline:
            s = baseline[h]
            print(f"  {h:>3}日: 平均{s['avg_return']:+6.2f}%  胜率{s['win_rate']:5.1f}%  (n={s['count']})")
    print()

    # Signal stats
    for label in label_order:
        slist = signals.get(label, [])
        stats = compute_stats(slist)
        print(f"--- {label} (共 {len(slist)} 信号) ---")
        if not stats:
            print("  无信号")
            continue
        for h in horizons:
            if h in stats:
                s = stats[h]
                b = baseline.get(h, {})
                excess = ""
                if b and b.get("avg_return") is not None:
                    ex = s["avg_return"] - b["avg_return"]
                    excess = f"  超额:{ex:+.2f}%"
                print(f"  {h:>3}日: 平均{s['avg_return']:+6.2f}%  胜率{s['win_rate']:5.1f}%  (n={s['count']}){excess}")
        print()

    # Detailed signal analysis
    print(f"\n{'='*80}")
    print(" 头肩底确认 信号详情 (Top 15)")
    print(f"{'='*80}")
    confirmed = sorted(signals["🟢 头肩底确认"], key=lambda x: x["score"], reverse=True)[:15]
    for i, s in enumerate(confirmed):
        fwd_str = " | ".join(
            f"{h}d:{s['fwd'][h]:+.1f}%" for h in [5, 10, 20, 60, 120] if s['fwd'].get(h) is not None
        )
        print(f"  {i+1}. {s['code']} {s['date']} score={s['score']} | {fwd_str}")

    # Save summary results to skill directory
    output_file = os.path.join(_skill_dir, "hs_bottom_backtest_results.json")
    summary = {
        "total_windows": total_windows,
        "pattern_windows": pattern_windows,
        "signal_counts": {
            "🟢 头肩底确认": len(signals["🟢 头肩底确认"]),
            "🟢 头肩底形成中": len(signals["🟢 头肩底形成中"]),
            "🟡 头肩底候选": len(signals["🟡 头肩底候选"]),
            "baseline": len(signals["baseline"]),
        },
        "baseline_stats": baseline,
        "signal_stats": {
            label: compute_stats(signals[label])
            for label in label_order
        },
    }
    with open(output_file, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {output_file}")


if __name__ == "__main__":
    main()
