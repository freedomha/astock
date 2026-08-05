#!/usr/bin/env python3
"""
A股ETF W底形态回测 (v1)

模拟在历史时点检测W底形态，统计N日后收益。
方法: 在120日窗口上滑动，以每个120日窗口的末尾作为"当前"时点，
运行W底检测逻辑，记录检测结果和N日(5/10/20/40)后的收益情况。
"""

import json
import os


def lin_slope(arr, win):
    if len(arr) < win or win < 2:
        return None
    ys = arr[-win:]
    n = len(ys)
    x_mean = (n - 1) / 2
    y_mean = sum(ys) / n
    num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(ys))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den
    return (slope / y_mean) * 100


def detect_w_bottom_snapshot(closes, volumes):
    """Same detection logic as analyze.py, operating on a 120-day snapshot."""
    n = len(closes)
    if n < 120:
        return None

    p1_slope = lin_slope(closes[:80], 40)
    if p1_slope is None or p1_slope > -0.005:
        return None

    lt_idx, lt_val = None, float('inf')
    for i in range(80, 96):
        if closes[i] < lt_val:
            lt_val = closes[i]
            lt_idx = i

    # Peak search from left trough + 1 to T-12 (fixed: was max(lt_idx, 96) bug)
    pk_idx, pk_val = None, float('-inf')
    for i in range(lt_idx + 1, 109):
        if closes[i] > pk_val:
            pk_val = closes[i]
            pk_idx = i

    recovery = (pk_val / lt_val - 1) * 100
    if recovery < 8.0:
        return None

    rt_idx, rt_val = None, float('inf')
    for i in range(108, min(120, n)):
        if closes[i] < rt_val:
            rt_val = closes[i]
            rt_idx = i

    tdiff = abs(rt_val / lt_val - 1) * 100
    if tdiff > 10.0:
        return None

    lt_vol = sum(volumes[max(0, lt_idx - 5):lt_idx + 6]) / max(1, min(n, lt_idx + 6) - max(0, lt_idx - 5))
    rt_vol = sum(volumes[max(0, rt_idx - 5):rt_idx + 6]) / max(1, min(n, rt_idx + 6) - max(0, rt_idx - 5))
    vratio = rt_vol / lt_vol if lt_vol > 0 else 1
    if vratio > 1.2:
        return None

    recent3 = closes[-3:]
    above = sum(1 for c in recent3 if c > pk_val)
    status = "确认" if (above >= 2 and closes[-1] > pk_val) else "形成中"

    return {"status": status, "close": closes[-1]}


def main():
    print("=" * 60)
    print("A股ETF W底形态回测 (v1)")
    print("=" * 60)

    cwd = os.getcwd()
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    if not os.path.exists(kline_file):
        print(f"K-line data not found: {kline_file}")
        return

    with open(kline_file) as f:
        kline_data = json.load(f)

    forward_days = [5, 10, 20, 40]
    all_trades = []

    print(f"\n扫描 {len(kline_data)} 只ETF的历史W底信号...")
    total_windows = 0
    total_signals = 0

    for code, raw in kline_data.items():
        if not isinstance(raw, list) or len(raw) < 160:
            continue

        records = []
        for k in raw:
            try:
                records.append({
                    "date": k["date"],
                    "close": float(k["last"]),
                    "volume": float(k.get("volume", 0)),
                })
            except (KeyError, ValueError):
                continue

        if len(records) < 160:
            continue
        records.sort(key=lambda x: x["date"])
        closes = [r["close"] for r in records]
        volumes = [r["volume"] for r in records]

        n = len(records)
        for end in range(140, n):
            window_closes = closes[end - 120:end]
            window_vols = volumes[end - 120:end]
            detection = detect_w_bottom_snapshot(window_closes, window_vols)
            total_windows += 1

            if detection is None:
                continue

            total_signals += 1
            entry_price = detection["close"]
            trade = {"code": code, "date": records[end - 1]["date"], "status": detection["status"], "entry": entry_price}

            for fd in forward_days:
                if end + fd < n:
                    exit_price = closes[end + fd]
                    ret = (exit_price / entry_price - 1) * 100
                    trade[f"ret_{fd}d"] = round(ret, 2)
                else:
                    trade[f"ret_{fd}d"] = None

            all_trades.append(trade)

    print(f"\n扫描窗口: {total_windows}, 检测信号: {total_signals}")

    for status in ["确认", "形成中"]:
        trades = [t for t in all_trades if t["status"] == status]
        if not trades:
            print(f"\n  {status}: 无信号")
            continue

        print(f"\n  {status}信号: {len(trades)} 次")
        for fd in forward_days:
            valid = [t[f"ret_{fd}d"] for t in trades if t[f"ret_{fd}d"] is not None]
            if not valid:
                print(f"    {fd}日: 无数据")
                continue
            avg_ret = sum(valid) / len(valid)
            win_count = sum(1 for r in valid if r > 0)
            win_rate = win_count / len(valid) * 100
            max_gain = max(valid)
            max_loss = min(valid)
            print(f"    {fd}日收益: 均值 {avg_ret:+.2f}%, 胜率 {win_rate:.1f}%, 最大 {max_gain:+.2f}% / {max_loss:+.2f}% (n={len(valid)})")

    skill_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(skill_dir, "backtest_w_bottom_results.json")
    with open(output_file, "w") as f:
        json.dump({
            "total_windows": total_windows,
            "total_signals": total_signals,
            "trades": all_trades,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n回测结果已保存: {output_file}")


if __name__ == "__main__":
    main()
