#!/usr/bin/env python3
"""
ETF 2B底部形态 500日数据回测

适配500日K线数据进行回测，保留原算法所有逻辑：
- 逐bar滑动窗口检测2B底部
- 7维度评分
- 3种入场模式对比 (无确认 / 1阳确认 / 2阳确认)
- 新增: 90d前瞻、季度分解

数据源: etf_kline_data_500.json
"""

import json
import os
from collections import defaultdict

KLINE_FILE = os.path.join(os.getcwd(), "etf_kline_data_500.json")
FORWARD_DAYS = [5, 10, 20, 30, 60, 90]
MIN_BARS = 63


# ─── Data Loading ─────────────────────────────────────────────────────

def load_klines(filepath):
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
                    "open": float(k.get("first", k.get("open"))),
                    "close": float(k["last"]),
                    "high": float(k["high"]),
                    "low": float(k["low"]),
                    "volume": float(k.get("volume", 0)),
                })
            except (KeyError, ValueError, TypeError):
                continue
        if len(records) < MIN_BARS:
            continue
        records.sort(key=lambda x: x["date"])
        etfs[code] = records
    return etfs


# ─── 2B Detection ─────────────────────────────────────────────────────

def detect_2b_at_bar(records, bar_idx):
    n = len(records)
    prior_start = bar_idx - 2 - 60
    prior_end = bar_idx - 2
    if prior_start < 0:
        return None
    prior_window = records[prior_start:prior_end]
    if len(prior_window) < 30:
        return None
    prior_low_price = min(r["close"] for r in prior_window)
    prior_low_bar = None
    for j in range(prior_start, prior_end):
        if records[j]["close"] == prior_low_price:
            prior_low_bar = j
            break
    if prior_low_bar is None:
        return None
    if records[bar_idx]["low"] >= prior_low_price:
        return None
    breakdown_bar = bar_idx
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
    n = len(records)
    closes = [r["close"] for r in records]
    vols = [r["volume"] for r in records]

    # D1: Break depth (max 20)
    breakdown_low = records[breakdown_bar]["low"]
    break_pct = (prior_low_price - breakdown_low) / prior_low_price * 100
    if break_pct < 1: d1 = 20
    elif break_pct <= 3: d1 = 15
    elif break_pct <= 5: d1 = 8
    else: d1 = 0

    # D2: Recovery strength (max 20)
    recovery_close = records[recovery_bar]["close"]
    recovery_pct = (recovery_close - prior_low_price) / prior_low_price * 100
    if recovery_pct >= 1.5: d2 = 20
    elif recovery_pct >= 0.5: d2 = 15
    elif recovery_pct >= 0: d2 = 10
    else: d2 = 0

    # D3: Volume contraction (max 15)
    vol_breakdown = records[breakdown_bar]["volume"]
    if n >= 60:
        vol_avg60 = sum(vols[-60:]) / 60
    else:
        vol_avg60 = sum(vols) / n
    vol_ratio = vol_breakdown / vol_avg60 if vol_avg60 > 0 else 1
    if vol_ratio < 0.8: d3 = 15
    elif vol_ratio <= 1.0: d3 = 10
    else: d3 = 5

    # D4: Prior low quality (max 15)
    check_start = max(0, prior_low_bar - 10)
    check_end = min(n, prior_low_bar + 11)
    nearby_closes = closes[check_start:check_end]
    nearby_low_rank = sum(1 for c in nearby_closes if c < prior_low_price)
    window_size = check_end - check_start
    if nearby_low_rank == 0 and window_size >= 15: d4 = 15
    elif nearby_low_rank <= 1: d4 = 10
    else: d4 = 5

    # D5: Trend context (max 15)
    decline_start = max(0, prior_low_bar - 20)
    if prior_low_bar - decline_start >= 5:
        first_close = closes[decline_start]
        last_close = closes[prior_low_bar]
        prior_decline = (first_close - last_close) / first_close * 100 if first_close > 0 else 0
    else:
        prior_decline = 0
    if prior_decline > 8: d5 = 15
    elif prior_decline > 5: d5 = 10
    elif prior_decline > 3: d5 = 5
    else: d5 = 0

    # D6: Recovery speed (max 10)
    lag = recovery_bar - breakdown_bar
    if lag == 0: d6 = 10
    elif lag == 1: d6 = 7
    elif lag == 2: d6 = 5
    else: d6 = 0

    # D7: Distance from 60MA (max 5)
    if n >= 60:
        ma60 = sum(closes[-60:]) / 60
        d_ma60 = (closes[-1] - ma60) / ma60 * 100
    else:
        ma60 = sum(closes) / n
        d_ma60 = (closes[-1] - ma60) / ma60 * 100
    if -15 <= d_ma60 <= -2: d7 = 5
    else: d7 = 0

    # Penalties
    penalties = 0
    if vol_ratio > 1.2: penalties += 10
    bars_since_prior = breakdown_bar - prior_low_bar
    if bars_since_prior < 5: penalties += 5

    score = d1 + d2 + d3 + d4 + d5 + d6 + d7 - penalties
    score = max(0, min(100, score))

    return {
        "score": score,
        "breakdown_date": records[breakdown_bar]["date"],
        "recovery_date": records[recovery_bar]["date"],
        "prior_low_date": records[prior_low_bar]["date"],
        "prior_low_price": round(prior_low_price, 2),
        "signal_close": round(records[recovery_bar]["close"], 3),
        "break_pct": round(break_pct, 2),
        "recovery_pct": round(recovery_pct, 2),
        "vol_ratio": round(vol_ratio, 2),
        "prior_decline": round(prior_decline, 1),
        "lag_bars": lag,
        "d1": d1, "d2": d2, "d3": d3, "d4": d4, "d5": d5, "d6": d6, "d7": d7,
        "penalties": penalties,
    }


def compute_forward_returns(records, signal_bar, forward_days):
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
    # Max drawdown
    peak = signal_close
    max_dd = 0
    for i in range(signal_bar, min(signal_bar + max(forward_days), len(records))):
        price = records[i]["close"]
        peak = max(peak, price)
        dd = (price - peak) / peak * 100
        max_dd = min(max_dd, dd)
    rets["max_dd"] = round(max_dd, 2)
    return rets


def find_confirmation_bars(records, start_bar, num_bullish=1):
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
    return (None, False)


def dedup_signals(signals):
    dedup = {}
    for s in signals:
        key = (s["code"], s["signal_date"])
        if key not in dedup or s["score"] > dedup[key]["score"]:
            dedup[key] = s
    result = list(dedup.values())
    result.sort(key=lambda x: x["score"], reverse=True)
    return result


def run_backtest():
    print("=" * 80)
    print("ETF 2B底部形态 历史回测 (500日数据)")
    print("=" * 80)

    print(f"\n加载K线数据: {KLINE_FILE}")
    etfs = load_klines(KLINE_FILE)
    print(f"加载 {len(etfs)} 只ETF (每只>={MIN_BARS}条K线)")

    total_bars = sum(len(r) for r in etfs.values())
    print(f"总K线条数: {total_bars}, 平均每只{total_bars/len(etfs):.0f}条")

    all_signals = []
    confirmed_1yang = []
    confirmed_2yang = []

    done = 0
    total_etfs = len(etfs)

    for code, records in etfs.items():
        n = len(records)
        for bar_idx in range(62, n - 2):
            detected = detect_2b_at_bar(records, bar_idx)
            if detected is None:
                continue

            breakdown_bar, recovery_bar, prior_low_price, prior_low_bar = detected
            scored = score_2b_at_bar(records, breakdown_bar, recovery_bar,
                                     prior_low_price, prior_low_bar)

            # baseline: no confirmation, entry at recovery bar
            forward_rets = compute_forward_returns(records, recovery_bar, FORWARD_DAYS)
            signal = {
                "code": code,
                "signal_date": scored["recovery_date"],
                "breakdown_date": scored["breakdown_date"],
                "score": scored["score"],
                "close": scored["signal_close"],
                "prior_low": scored["prior_low_price"],
                "break_pct": scored["break_pct"],
                "recovery_pct": scored["recovery_pct"],
                "vol_ratio": scored["vol_ratio"],
                "prior_decline": scored["prior_decline"],
                "lag_bars": scored["lag_bars"],
                "mode": "no_confirm",
                "entry_bar": recovery_bar,
                "entry_date": scored["recovery_date"],
                "entry_price": scored["signal_close"],
            }
            signal.update(forward_rets)
            all_signals.append(signal)

            # 1-yang confirmation
            entry_1y, conf_1y = find_confirmation_bars(records, recovery_bar, num_bullish=1)
            if conf_1y and entry_1y is not None:
                conf_rets_1 = compute_forward_returns(records, entry_1y, FORWARD_DAYS)
                conf_signal_1 = {
                    "code": code,
                    "signal_date": scored["recovery_date"],
                    "entry_date": records[entry_1y]["date"],
                    "breakdown_date": scored["breakdown_date"],
                    "score": scored["score"],
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
                    "entry_price": round(records[entry_1y]["close"], 3),
                }
                conf_signal_1.update(conf_rets_1)
                confirmed_1yang.append(conf_signal_1)

            # 2-yang confirmation
            entry_2y, conf_2y = find_confirmation_bars(records, recovery_bar, num_bullish=2)
            if conf_2y and entry_2y is not None:
                conf_rets_2 = compute_forward_returns(records, entry_2y, FORWARD_DAYS)
                conf_signal_2 = {
                    "code": code,
                    "signal_date": scored["recovery_date"],
                    "entry_date": records[entry_2y]["date"],
                    "breakdown_date": scored["breakdown_date"],
                    "score": scored["score"],
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
                    "entry_price": round(records[entry_2y]["close"], 3),
                }
                conf_signal_2.update(conf_rets_2)
                confirmed_2yang.append(conf_signal_2)

        done += 1
        if done % 50 == 0:
            print(f"  进度: {done}/{total_etfs} 原始信号累计{len(all_signals)}")

    print(f"\n检测完成: 原始2B={len(all_signals)} | 1阳确认={len(confirmed_1yang)} | 2阳确认={len(confirmed_2yang)}")

    # Deduplicate
    all_signals = dedup_signals(all_signals)
    confirmed_1yang = dedup_signals(confirmed_1yang)
    confirmed_2yang = dedup_signals(confirmed_2yang)
    print(f"去重后: 原始={len(all_signals)} | 1阳确认={len(confirmed_1yang)} | 2阳确认={len(confirmed_2yang)}")

    # ─── Tiered Statistics ─────────────────────────────────────────────
    tiers = {
        "2B买入确认(≥80)": lambda s: s["score"] >= 80,
        "2B买入候选(65-79)": lambda s: 65 <= s["score"] < 80,
        "2B观察(50-64)": lambda s: 50 <= s["score"] < 65,
    }

    mode_configs = [
        ("原始 (无确认, 回升日入场)", all_signals),
        ("1阳线确认 (回升后1阳入场)", confirmed_1yang),
        ("2阳线确认 (回升后2阳入场)", confirmed_2yang),
    ]

    for mode_name, signals_list in mode_configs:
        print("\n" + "=" * 100)
        print(f"📊 {mode_name} — 分层收益统计")
        print("=" * 100)

        tier_signals = {tier: [s for s in signals_list if filt(s)] for tier, filt in tiers.items()}
        tier_signals["全部信号"] = signals_list

        header = f"{'分层':<22}"
        for d in FORWARD_DAYS:
            header += f"{'N':>5}  {'win%':>6}  {'avg%':>7}  {'max%':>7}  {'min%':>7}"
        print(header)
        print("-" * 100)

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
                    row += f"{n:>5}  {win:>3}/{n:<3}  {avg_r:>+6.1f}%  {max_r:>+6.1f}%  {min_r:>+6.1f}%"
                else:
                    row += f"{'N/A':>5}  {'N/A':>6}  {'N/A':>7}  {'N/A':>7}  {'N/A':>7}"
            print(row)

    # ─── 3-mode comparison summary ─────────────────────────────────────
    print("\n" + "=" * 100)
    print("🔍 三种模式对比 (全部信号)")
    print("=" * 100)
    header2 = f"{'模式':<30} {'信号':>6}"
    for d in FORWARD_DAYS:
        header2 += f"  {d}d胜率  {d}d均收"
    print(header2)
    print("-" * 100)

    for mode_name, signals_list in mode_configs:
        total = len(signals_list)
        row = f"{mode_name:<30} {total:>6}"
        for d in FORWARD_DAYS:
            ret_key = f"ret_{d}d"
            vals = [s[ret_key] for s in signals_list if s[ret_key] is not None]
            if vals:
                win_pct = sum(1 for v in vals if v > 0) / len(vals) * 100
                avg_r = sum(vals) / len(vals)
                row += f"  {win_pct:>5.1f}%  {avg_r:>+6.1f}%"
            else:
                row += f"  {'N/A':>5}   {'N/A':>6}"
        print(row)

    # ─── Quarterly breakdown ───────────────────────────────────────────
    print("\n" + "=" * 100)
    print("📅 按季度分解 (2阳确认, ≥80分高信号)")
    print("=" * 100)
    high_2y = [s for s in confirmed_2yang if s["score"] >= 80]
    quarterly = defaultdict(list)
    for s in high_2y:
        d = s["signal_date"]
        q = d[:4] + "-Q" + str((int(d[5:7]) - 1) // 3 + 1)
        quarterly[q].append(s)

    for q in sorted(quarterly.keys()):
        signals = quarterly[q]
        n = len(signals)
        for d_ in [20, 60, 90]:
            key = f"ret_{d_}d"
            vals = [s[key] for s in signals if s.get(key) is not None]
            if vals:
                avg = sum(vals)/len(vals)
                wr = sum(1 for v in vals if v>0)/len(vals)*100
                print(f"  {q}: {n}次信号 | {d_}d均{avg:+.1f}% 胜率{wr:.0f}%" if d_==20 else f"          | {d_}d均{avg:+.1f}% 胜率{wr:.0f}%")
            else:
                print(f"  {q}: {n}次信号 | {d_}d: N/A")

    # ─── Best/Worst signals ────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("🏆 2阳确认高评分(≥80) — 20日收益 Top 10")
    print("=" * 100)
    top_2y = sorted(high_2y, key=lambda x: -(x.get("ret_20d") or -9999))
    for i, s in enumerate(top_2y[:10]):
        print(f"  {i+1}. {s['code']} @{s['signal_date']} 得分{s['score']} "
              f"→ 5d:{s.get('ret_5d','?')}% 10d:{s.get('ret_10d','?')}% "
              f"20d:{s.get('ret_20d','?')}% 60d:{s.get('ret_60d','?')}% 90d:{s.get('ret_90d','?')}%")

    # Save results
    output_file = os.path.join(os.getcwd(), "etf_2b_backtest_500_results.json")
    with open(output_file, "w") as f:
        json.dump({
            "config": {"kline_file": KLINE_FILE, "forward_days": FORWARD_DAYS},
            "summary": {
                "baseline_count": len(all_signals),
                "confirmed_1yang_count": len(confirmed_1yang),
                "confirmed_2yang_count": len(confirmed_2yang),
            },
            "baseline": all_signals,
            "confirmed_1yang": confirmed_1yang,
            "confirmed_2yang": confirmed_2yang,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n📁 结果已保存: {output_file}")

    return all_signals, confirmed_1yang, confirmed_2yang


if __name__ == "__main__":
    run_backtest()
