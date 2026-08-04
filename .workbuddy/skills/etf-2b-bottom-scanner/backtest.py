#!/usr/bin/env python3
"""
2B底部形态回测脚本

从 etf_kline_data.json 加载历史K线数据，
滑动窗口遍历所有历史时点，检测2B底部信号，
并统计信号后的收益率表现。

回测范围: 每只ETF在250个交易日中，从第62bar开始到倒数第3bar
前向收益: 5日、10日、20日、60日
"""

import json
import os
import sys
from collections import defaultdict

# ─── Config ───────────────────────────────────────────────────────────

KLINE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "etf_kline_data.json")
FORWARD_DAYS = [5, 10, 20, 60]
MIN_BARS = 63  # need at least 63 bars for 2B detection


# ─── Data Loading ─────────────────────────────────────────────────────

def load_klines(filepath):
    """Load etf_kline_data.json, parse into oldest-first records."""
    with open(filepath) as f:
        raw = json.load(f)

    etfs = {}
    for code, kline_data in raw.items():
        if not kline_data or len(kline_data) < MIN_BARS:
            continue
        records = []
        for k in kline_data:
            try:
                records.append({
                    "date": k["date"],
                    "open": float(k["open"]),
                    "close": float(k["last"]),
                    "high": float(k["high"]),
                    "low": float(k["low"]),
                    "volume": float(k.get("volume", 0)),
                })
            except (KeyError, ValueError):
                continue

        if len(records) < MIN_BARS:
            continue

        # Sort oldest-first
        records.sort(key=lambda x: x["date"])
        etfs[code] = records

    return etfs


# ─── 2B Detection (per-bar sliding window) ────────────────────────────

def detect_2b_at_bar(records, bar_idx):
    """
    Check if there's a 2B bottom signal at bar bar_idx.
    Returns (breakdown_bar, recovery_bar, prior_low_price, prior_low_bar) or None.
    """
    n = len(records)

    # Need prior 60-day window: bars [bar_idx - 2 - 60, bar_idx - 2]
    prior_start = bar_idx - 2 - 60
    prior_end = bar_idx - 2  # exclusive
    if prior_start < 0:
        return None

    prior_window = records[prior_start:prior_end]
    if len(prior_window) < 30:
        return None

    prior_low_price = min(r["close"] for r in prior_window)

    # Find the bar index of the prior low
    prior_low_bar = None
    for j in range(prior_start, prior_end):
        if records[j]["close"] == prior_low_price:
            prior_low_bar = j
            break
    if prior_low_bar is None:
        return None

    # Breakdown check: bar low < prior low
    if records[bar_idx]["low"] >= prior_low_price:
        return None
    breakdown_bar = bar_idx

    # Recovery check: within 0-2 bars after breakdown, close > prior low
    recovery_bar = None
    for offset in range(3):
        check_idx = breakdown_bar + offset
        if check_idx >= n:
            break
        if records[check_idx]["close"] > prior_low_price:
            recovery_bar = check_idx
            break

    if recovery_bar is None:
        return None

    return (breakdown_bar, recovery_bar, prior_low_price, prior_low_bar)


def score_2b_at_bar(records, breakdown_bar, recovery_bar, prior_low_price, prior_low_bar):
    """
    Score a detected 2B pattern. Same logic as analyze.py.
    Returns dict with score, label, and detail dimensions.
    """
    n = len(records)
    closes = [r["close"] for r in records]
    vols = [r["volume"] for r in records]

    # D1: Break depth (max 20)
    breakdown_low = records[breakdown_bar]["low"]
    break_depth_pct = (prior_low_price - breakdown_low) / prior_low_price * 100
    if break_depth_pct < 1:
        d1 = 20
    elif break_depth_pct <= 3:
        d1 = 15
    elif break_depth_pct <= 5:
        d1 = 8
    else:
        d1 = 0

    # D2: Recovery strength (max 20)
    recovery_close = records[recovery_bar]["close"]
    recovery_pct = (recovery_close - prior_low_price) / prior_low_price * 100
    if recovery_pct >= 1.5:
        d2 = 20
    elif recovery_pct >= 0.5:
        d2 = 15
    elif recovery_pct >= 0:
        d2 = 10
    else:
        d2 = 0

    # D3: Volume contraction (max 15)
    if n >= 60:
        vol_breakdown = records[breakdown_bar]["volume"]
        vol_avg60 = sum(vols[-60:]) / 60
        vol_ratio = vol_breakdown / vol_avg60 if vol_avg60 > 0 else 1
    else:
        vol_ratio = 1
    if vol_ratio < 0.8:
        d3 = 15
    elif vol_ratio <= 1.0:
        d3 = 10
    else:
        d3 = 5

    # D4: Prior low quality (max 15)
    check_start = max(0, prior_low_bar - 10)
    check_end = min(n, prior_low_bar + 11)
    nearby_closes = closes[check_start:check_end]
    nearby_low_rank = sum(1 for c in nearby_closes if c < prior_low_price)
    window_size = check_end - check_start
    if nearby_low_rank == 0 and window_size >= 15:
        d4 = 15
    elif nearby_low_rank <= 1:
        d4 = 10
    else:
        d4 = 5

    # D5: Trend context (max 15)
    decline_start = max(0, prior_low_bar - 20)
    if prior_low_bar - decline_start >= 5:
        first_close = closes[decline_start]
        last_close = closes[prior_low_bar]
        prior_decline = (first_close - last_close) / first_close * 100 if first_close > 0 else 0
    else:
        prior_decline = 0
    if prior_decline > 8:
        d5 = 15
    elif prior_decline > 5:
        d5 = 10
    elif prior_decline > 3:
        d5 = 5
    else:
        d5 = 0

    # D6: Recovery speed (max 10)
    lag = recovery_bar - breakdown_bar
    if lag == 0:
        d6 = 10
    elif lag == 1:
        d6 = 7
    elif lag == 2:
        d6 = 5
    else:
        d6 = 0

    # D7: Distance from 60MA (max 5)
    if n >= 60:
        ma60 = sum(closes[-60:]) / 60
        cur = closes[-1]
        d_ma60 = (cur - ma60) / ma60 * 100
    else:
        ma60 = sum(closes) / n
        d_ma60 = (closes[-1] - ma60) / ma60 * 100
    if -15 <= d_ma60 <= -2:
        d7 = 5
    else:
        d7 = 0

    # Penalties
    penalties = 0
    if vol_ratio > 1.2:
        penalties += 10
    bars_since_prior = breakdown_bar - prior_low_bar
    if bars_since_prior < 5:
        penalties += 5

    # Total
    score = d1 + d2 + d3 + d4 + d5 + d6 + d7 - penalties
    score = max(0, min(100, score))

    # Label
    if score >= 80:
        label = "2B买入确认"
    elif score >= 65:
        label = "2B买入候选"
    elif score >= 50:
        label = "2B观察"
    else:
        label = "无2B信号"

    return {
        "score": score,
        "label": label,
        "breakdown_date": records[breakdown_bar]["date"],
        "recovery_date": records[recovery_bar]["date"],
        "prior_low_date": records[prior_low_bar]["date"],
        "breakdown_bar": breakdown_bar,
        "recovery_bar": recovery_bar,
        "prior_low_bar": prior_low_bar,
        "prior_low_price": round(prior_low_price, 2),
        "signal_close": records[recovery_bar]["close"],
        "break_pct": round(break_depth_pct, 2),
        "recovery_pct": round(recovery_pct, 2),
        "vol_ratio": round(vol_ratio, 2),
        "prior_decline": round(prior_decline, 1),
        "lag_bars": lag,
        "d1": d1, "d2": d2, "d3": d3, "d4": d4, "d5": d5, "d6": d6, "d7": d7,
        "penalties": penalties,
    }


def compute_forward_returns(records, signal_bar, forward_days):
    """
    Compute forward returns from signal_bar close.
    Returns dict of {f'ret_{d}d': pct} for each horizon.
    Returns None for horizons where not enough data.
    """
    signal_close = records[signal_bar]["close"]
    rets = {}
    for d in forward_days:
        target_idx = signal_bar + d
        if target_idx < len(records):
            future_close = records[target_idx]["close"]
            ret = (future_close - signal_close) / signal_close * 100
            rets[f"ret_{d}d"] = round(ret, 2)
        else:
            rets[f"ret_{d}d"] = None
    return rets


def find_confirmation_bars(records, start_bar, num_bullish=1):
    """
    Find N consecutive bullish bars (close > open) starting from start_bar.
    
    Returns (entry_bar, confirmed) where:
    - entry_bar: index of last bullish bar in the sequence (entry point)
    - confirmed: True if N bullish bars found, False otherwise
    
    If insufficient bars, returns (None, False).
    """
    n = len(records)
    bullish_count = 0
    entry_bar = None
    
    for offset in range(n - start_bar):
        bar_idx = start_bar + offset
        if bar_idx >= n:
            break
        if records[bar_idx]["close"] > records[bar_idx]["open"]:
            bullish_count += 1
            entry_bar = bar_idx
            if bullish_count >= num_bullish:
                return (entry_bar, True)
        # Note: we don't reset on non-bullish, we require consecutive?
        # Actually the user said "1-2根阳线确认", meaning just need 1-2 bullish bars
        # Let's implement it as: find N bullish bars, not necessarily consecutive
        # Because the condition is "close > open" on any bar after recovery
    
    if entry_bar is not None and num_bullish == 1:
        # Found at least one bullish bar
        return (entry_bar, True)
    
    return (None, False)


# ─── Main Backtest ────────────────────────────────────────────────────

def run_backtest():
    print("=" * 70)
    print("ETF 2B底部形态 历史回测")
    print("=" * 70)

    # Load data
    print(f"\n加载K线数据: {KLINE_FILE}")
    etfs = load_klines(KLINE_FILE)
    print(f"加载 {len(etfs)} 只ETF (每只>=63条K线)")

    # Scan for signals
    all_signals = []
    confirmed_1yang = []
    confirmed_2yang = []

    for code, records in etfs.items():
        n = len(records)
        for bar_idx in range(62, n - 2):
            detected = detect_2b_at_bar(records, bar_idx)
            if detected is None:
                continue

            breakdown_bar, recovery_bar, prior_low_price, prior_low_bar = detected
            scored = score_2b_at_bar(records, breakdown_bar, recovery_bar,
                                     prior_low_price, prior_low_bar)

            # Baseline: entry at recovery bar (no confirmation)
            forward_rets = compute_forward_returns(records, recovery_bar, FORWARD_DAYS)
            signal = {
                "code": code,
                "signal_date": scored["recovery_date"],
                "breakdown_date": scored["breakdown_date"],
                "score": scored["score"],
                "label": scored["label"],
                "close": round(scored["signal_close"], 3),
                "prior_low": scored["prior_low_price"],
                "break_pct": scored["break_pct"],
                "recovery_pct": scored["recovery_pct"],
                "vol_ratio": scored["vol_ratio"],
                "prior_decline": scored["prior_decline"],
                "lag_bars": scored["lag_bars"],
                "mode": "no_confirm",
                "entry_bar": recovery_bar,
                "entry_date": scored["recovery_date"],
            }
            signal.update(forward_rets)
            all_signals.append(signal)

            # Confirmed: entry after 1 bullish bar post-recovery
            entry_1y, conf_1y = find_confirmation_bars(records, recovery_bar, num_bullish=1)
            if conf_1y and entry_1y is not None:
                conf_rets_1 = compute_forward_returns(records, entry_1y, FORWARD_DAYS)
                conf_signal_1 = {
                    "code": code,
                    "signal_date": scored["recovery_date"],
                    "entry_date": records[entry_1y]["date"],
                    "breakdown_date": scored["breakdown_date"],
                    "score": scored["score"],
                    "label": scored["label"],
                    "close": round(records[entry_1y]["close"], 3),
                    "prior_low": scored["prior_low_price"],
                    "break_pct": scored["break_pct"],
                    "recovery_pct": scored["recovery_pct"],
                    "vol_ratio": scored["vol_ratio"],
                    "prior_decline": scored["prior_decline"],
                    "lag_bars": scored["lag_bars"],
                    "confirm_lag": entry_1y - recovery_bar,
                    "mode": "confirm_1yang",
                    "entry_bar": entry_1y,
                }
                conf_signal_1.update(conf_rets_1)
                confirmed_1yang.append(conf_signal_1)

            # Confirmed: entry after 2 bullish bars post-recovery
            entry_2y, conf_2y = find_confirmation_bars(records, recovery_bar, num_bullish=2)
            if conf_2y and entry_2y is not None:
                conf_rets_2 = compute_forward_returns(records, entry_2y, FORWARD_DAYS)
                conf_signal_2 = {
                    "code": code,
                    "signal_date": scored["recovery_date"],
                    "entry_date": records[entry_2y]["date"],
                    "breakdown_date": scored["breakdown_date"],
                    "score": scored["score"],
                    "label": scored["label"],
                    "close": round(records[entry_2y]["close"], 3),
                    "prior_low": scored["prior_low_price"],
                    "break_pct": scored["break_pct"],
                    "recovery_pct": scored["recovery_pct"],
                    "vol_ratio": scored["vol_ratio"],
                    "prior_decline": scored["prior_decline"],
                    "lag_bars": scored["lag_bars"],
                    "confirm_lag": entry_2y - recovery_bar,
                    "mode": "confirm_2yang",
                    "entry_bar": entry_2y,
                }
                conf_signal_2.update(conf_rets_2)
                confirmed_2yang.append(conf_signal_2)

    print(f"\n检测到 原始2B信号: {len(all_signals)} | 1阳确认: {len(confirmed_1yang)} | 2阳确认: {len(confirmed_2yang)}")

    # ─── Deduplicate all three lists ──
    def dedup_signals(signals, key_fn=lambda s: (s["code"], s["signal_date"])):
        dedup = {}
        for s in signals:
            key = key_fn(s)
            if key not in dedup or s["score"] > dedup[key]["score"]:
                dedup[key] = s
        result = list(dedup.values())
        result.sort(key=lambda x: x["score"], reverse=True)
        return result

    all_signals = dedup_signals(all_signals, lambda s: (s["code"], s["signal_date"]))
    confirmed_1yang = dedup_signals(confirmed_1yang)
    confirmed_2yang = dedup_signals(confirmed_2yang)
    print(f"去重后: 原始={len(all_signals)} | 1阳确认={len(confirmed_1yang)} | 2阳确认={len(confirmed_2yang)}")

    # ─── Side-by-side comparison ──
    tiers = {
        "2B买入确认 (≥80)": lambda s: s["score"] >= 80,
        "2B买入候选 (65-79)": lambda s: 65 <= s["score"] < 80,
        "2B观察 (50-64)": lambda s: 50 <= s["score"] < 65,
    }

    mode_configs = [
        ("原始 (无确认, 回升日入场)", all_signals),
        ("1阳线确认 (回升后1根阳线入场)", confirmed_1yang),
        ("2阳线确认 (回升后2根阳线入场)", confirmed_2yang),
    ]

    for mode_name, signals_list in mode_configs:
        print("\n" + "=" * 80)
        print(f"📊 {mode_name} — 分层收益统计")
        print("=" * 80)

        tier_signals = {tier: [s for s in signals_list if filt(s)] for tier, filt in tiers.items()}
        tier_signals["全部信号"] = signals_list

        header = f"{'分层':<22}"
        for d in FORWARD_DAYS:
            header += f"{'N':>5}  {'win%':>6}  {'avg%':>7}  {'max%':>7}  {'min%':>7}  {'hit%':>6}"
        print(header)
        print("-" * 130)

        for tier_name, sigs in tier_signals.items():
            row = f"{tier_name:<22}"
            for d in FORWARD_DAYS:
                ret_key = f"ret_{d}d"
                vals = [s[ret_key] for s in sigs if s[ret_key] is not None]
                if vals:
                    n = len(vals)
                    win = sum(1 for v in vals if v > 0)
                    avg_r = sum(vals) / n
                    max_r = max(vals)
                    min_r = min(vals)
                    hit = win / n * 100
                    row += f"{n:>5}  {win:>3}/{n:<3}  {avg_r:>+6.1f}%  {max_r:>+6.1f}%  {min_r:>+6.1f}%  {hit:>5.1f}%"
                else:
                    row += f"{'N/A':>5}  {'N/A':>6}  {'N/A':>7}  {'N/A':>7}  {'N/A':>7}  {'N/A':>6}"
            print(row)

        # 20日分位统计
        ret_key = "ret_20d"
        vals = sorted([s[ret_key] for s in signals_list if s[ret_key] is not None])
        if vals:
            n = len(vals)
            win = sum(1 for v in vals if v > 0)
            avg_r = sum(vals) / n
            p25 = vals[int(n * 0.25)]
            p50 = vals[int(n * 0.50)]
            p75 = vals[int(n * 0.75)]
            print(f"\n  20日分位: N={n} win={win}/{n} ({win/n*100:.1f}%) avg={avg_r:+.2f}% "
                  f"P25={p25:+.2f}% P50={p50:+.2f}% P75={p75:+.2f}%")

    # ─── Comparison Summary ───────────────────────────────────────────
    print("\n" + "=" * 80)
    print("🔍 三种模式核心指标对比 (全部信号)")
    print("=" * 80)
    print(f"\n{'模式':<30} {'信号数':>6}  ", end="")
    for d in FORWARD_DAYS:
        print(f"{d}日胜率{'':>4}  {d}日均收益{'':>4}", end="  ")
    print()
    print("-" * 115)

    for mode_name, signals_list in mode_configs:
        total = len(signals_list)
        row = f"{mode_name:<30} {total:>6}  "
        for d in FORWARD_DAYS:
            ret_key = f"ret_{d}d"
            vals = [s[ret_key] for s in signals_list if s[ret_key] is not None]
            if vals:
                win_pct = sum(1 for v in vals if v > 0) / len(vals) * 100
                avg_r = sum(vals) / len(vals)
                row += f"{win_pct:>5.1f}%          {avg_r:>+6.1f}%     "
            else:
                row += f"{'N/A':>5}           {'N/A':>6}      "
        print(row)

    return all_signals, confirmed_1yang, confirmed_2yang


if __name__ == "__main__":
    signals_baseline, signals_1yang, signals_2yang = run_backtest()


if __name__ == "__main__":
    signals = run_backtest()
