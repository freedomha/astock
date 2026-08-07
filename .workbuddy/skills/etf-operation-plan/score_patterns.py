#!/usr/bin/env python3
"""
Single-ETF five-pattern scorer.
Usage: python3 score_patterns.py --code sh518880 --kline-file /tmp/kline.json
Output: JSON with bowl/box/w_bottom/hs_bottom/2b scores and labels.
"""
import json, sys, argparse


# ─── Shared Utility Functions ───────────────────────────────────────────────

def lin_slope(arr, win):
    """Linear regression slope over last `win` elements, as % change."""
    if len(arr) < win:
        return 0.0
    xs = list(range(win))
    ys = arr[-win:]
    n = float(win)
    sx = (n - 1) * n / 2.0
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    s = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    ym = sy / n
    if ym == 0:
        return 0.0
    return s * win / ym * 100


def atr(highs, lows, closes, window):
    """Average True Range over `window` periods."""
    if len(closes) < window + 1:
        return 0.0
    trs = []
    for i in range(len(closes) - window, len(closes)):
        prev_close = closes[i - 1] if i > 0 else closes[i]
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - prev_close),
                 abs(lows[i] - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def quadratic_fit(prices):
    """Quadratic fit y = a*x^2 + b*x + c. Returns (a, b, c, vertex_x_norm)."""
    n = len(prices)
    if n < 10:
        return 0, 0, prices[-1] if prices else 0, 0.5
    xs = list(range(n))
    ys = [float(p) for p in prices]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num_a, den_a = 0.0, 0.0
    num_b = 0.0
    for i in range(n):
        dx = xs[i] - mean_x
        dy = ys[i] - mean_y
        dx2 = dx * dx
        num_a += dx2 * dy
        den_a += dx2 * dx2
        num_b += dx * dy
    a = num_a / den_a if den_a != 0 else 0.0
    b = num_b / sum((x - mean_x) ** 2 for x in xs) if sum((x - mean_x) ** 2 for x in xs) != 0 else 0.0
    c = mean_y - b * mean_x - a * mean_x * mean_x
    vertex_x = -b / (2 * a) if a != 0 else n / 2
    vertex_x_norm = max(0, min(1, vertex_x / n))
    return a, b, c, vertex_x_norm


def find_local_extrema(closes, window=5):
    """Find local minima and maxima in price series."""
    lows_list = []
    highs_list = []
    n = len(closes)
    for i in range(n):
        start = max(0, i - window)
        end = min(n - 1, i + window)
        if closes[i] <= min(closes[start:end + 1]):
            lows_list.append((i, closes[i]))
        if closes[i] >= max(closes[start:end + 1]):
            highs_list.append((i, closes[i]))
    # Filter adjacent same
    filtered_lows = []
    for i, (idx, val) in enumerate(lows_list):
        if i == 0 or idx - lows_list[i - 1][0] > 2:
            filtered_lows.append((idx, val))
    filtered_highs = []
    for i, (idx, val) in enumerate(highs_list):
        if i == 0 or idx - highs_list[i - 1][0] > 2:
            filtered_highs.append((idx, val))
    return filtered_lows, filtered_highs
