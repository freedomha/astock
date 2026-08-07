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
    """Fit y = ax^2 + bx + c to prices (x = 0..n-1). Return (a, b, vertex_x)."""
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


# ─── Bowl-Bottom Scoring ──────────────────────────────────────────────────

def analyze_bowl_bottom(code, name, etype, kline_data):
    """
    Enhanced bowl-bottom analysis.
    Returns score (0-100), label, and detailed metrics.
    A true bowl-bottom = at range low + prior decline then recent stabilization (deceleration) + higher lows.
    """
    if not kline_data or len(kline_data) < 80:
        return None

    records = []
    for k in kline_data:
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

    closes = [r["close"] for r in records]
    highs = [r["high"] for r in records]
    lows = [r["low"] for r in records]
    vols = [r["volume"] for r in records]
    n = len(closes)
    cur = closes[-1]

    # ---- Position in range ----
    n120 = min(120, n)
    n250_val = min(250, n)
    hi120, lo120 = max(highs[-n120:]), min(lows[-n120:])
    hi250, lo250 = max(highs[-n250_val:]), min(lows[-n250_val:])
    pos120 = (cur - lo120) / (hi120 - lo120) if hi120 > lo120 else 0.5
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5
    dd120 = (cur - hi120) / hi120 * 100 if hi120 > 0 else 0
    dist_low = (cur - lo120) / lo120 * 100 if lo120 > 0 else 0

    # ---- Trend windows ----
    t20 = lin_slope(closes, 20)
    t60 = lin_slope(closes, 60)
    if n >= 60:
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
    if n >= 60:
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

    # ---- Rate of change ----
    c5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if n >= 6 else 0
    c10 = (closes[-1] - closes[-11]) / closes[-11] * 100 if n >= 11 else 0
    c20 = (closes[-1] - closes[-21]) / closes[-21] * 100 if n >= 21 else 0

    # ---- Quadratic U-shape fit over last 120 days ----
    seg120 = closes[-120:] if n >= 120 else closes
    a_coef, b_coef, vx = quadratic_fit(seg120)
    seg_len = len(seg120)
    mean_price = sum(seg120) / seg_len
    curvature = a_coef * seg_len * seg_len / mean_price * 100 if mean_price else 0
    vx_frac = vx / seg_len if seg_len else 0
    is_convex = curvature > 0.05
    vertex_recent = 0.35 < vx_frac < 0.95

    # ============ SCORING (max ~110, clamped 0-100) ============
    score = 0
    reasons = []

    # 1. 120-day range position (max 25)
    if pos120 <= 0.10:
        score += 25; reasons.append(f"✅ 120日极低位({pos120*100:.0f}%)")
    elif pos120 <= 0.20:
        score += 20; reasons.append(f"✅ 120日低位({pos120*100:.0f}%)")
    elif pos120 <= 0.30:
        score += 12; reasons.append(f"🟡 120日中低位({pos120*100:.0f}%)")
    elif pos120 <= 0.40:
        score += 5; reasons.append(f"🟡 120日中位({pos120*100:.0f}%)")
    else:
        reasons.append(f"❌ 120日高位({pos120*100:.0f}%)")

    # 2. 250-day range position (max 20)
    if pos250 <= 0.15:
        score += 20; reasons.append(f"✅ 250日极低位({pos250*100:.0f}%)")
    elif pos250 <= 0.25:
        score += 15; reasons.append(f"✅ 250日低位({pos250*100:.0f}%)")
    elif pos250 <= 0.35:
        score += 8; reasons.append(f"🟡 250日中低位({pos250*100:.0f}%)")
    else:
        reasons.append(f"❌ 250日高位({pos250*100:.0f}%)")

    # 3. BOWL SHAPE — recent flattening after prior decline (KEY, max 20)
    if t_prior < -5 and -2 <= t20 <= 3 and decel_ratio < 0.8:
        score += 20; reasons.append(f"✅ 碗形:前期跌({t_prior:+.0f}%)后近期企稳({t20:+.1f}%) 减速{decel_ratio:.0%}")
    elif t_prior < -5 and -3 <= t20 <= 4 and decel_ratio < 1.0:
        score += 14; reasons.append(f"🟡 趋稳:前期跌({t_prior:+.0f}%)近期减速({t20:+.1f}%) 减速{decel_ratio:.0%}")
    elif -4 <= t20 <= 4:
        score += 8; reasons.append(f"🟡 近期走平({t20:+.1f}%)")
    elif t20 < -6:
        score -= 5; reasons.append(f"❌ 近期破位下跌({t20:+.1f}%)")
    else:
        reasons.append(f"❌ 60日趋势明显({t60:+.1f}%)")

    # 3b. Higher-low bonus (max 5)
    if higher_low and hl_pct > 0.5:
        score += 5; reasons.append(f"✅ 近10日抬底({hl_pct:+.1f}%)")
    elif higher_low:
        score += 2; reasons.append(f"🟡 低点微抬({hl_pct:+.1f}%)")
    else:
        reasons.append(f"❌ 仍创新低({hl_pct:+.1f}%)")

    # 4. Quadratic U-shape curvature (max 10)
    if is_convex and vertex_recent:
        score += 10; reasons.append(f"✅ U形拟合(曲率{curvature:.2f},谷位{vx_frac:.0%})")
    elif is_convex:
        score += 5; reasons.append(f"🟡 凸形(曲率{curvature:.2f})")

    # 5. Volume contraction (max 8)
    if vol_ratio < 0.7:
        score += 8; reasons.append(f"✅ 缩量({vol_ratio:.0%})")
    elif vol_ratio < 0.85:
        score += 5; reasons.append(f"✅ 量缩({vol_ratio:.0%})")
    elif vol_ratio < 1.0:
        score += 3; reasons.append(f"🟡 量稳({vol_ratio:.0%})")
    else:
        reasons.append(f"❌ 放量({vol_ratio:.0%})")

    # 6. Volatility compression (max 7)
    if atr_ratio < 0.7:
        score += 7; reasons.append(f"✅ 波幅压缩({atr_ratio:.0%})")
    elif atr_ratio < 0.85:
        score += 5; reasons.append(f"✅ 波幅降({atr_ratio:.0%})")
    elif atr_ratio < 1.0:
        score += 2; reasons.append(f"🟡 波幅稳({atr_ratio:.0%})")
    else:
        reasons.append(f"❌ 波幅大({atr_ratio:.0%})")

    # 7. Below 60MA (max 10)
    if -12 <= d_ma60 <= -2:
        score += 10; reasons.append(f"✅ 低于60MA({d_ma60:+.1f}%)")
    elif -20 <= d_ma60 < -12:
        score += 6; reasons.append(f"🟡 远低于60MA({d_ma60:+.1f}%)")
    elif -2 <= d_ma60 <= 3:
        score += 4; reasons.append(f"🟡 接近60MA({d_ma60:+.1f}%)")
    else:
        reasons.append(f"❌ 高于60MA({d_ma60:+.1f}%)")

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
        label = "🟢 确认碗底"
    elif bottom_zone and (stabilized or (decelerating and higher_low)) and score >= 58:
        label = "🟢 碗底确认中"
    elif bottom_zone and decelerating and score >= 50:
        label = "🟡 减速筑底"
    elif bottom_zone and -4 <= t20 <= 5:
        label = "🟡 低位盘整"
    elif t20 < -6:
        label = "🔴 下跌中继"
    else:
        label = "⚪ 观望"

    return {
        "code": code, "name": name, "type": etype,
        "score": score, "label": label,
        "current": round(cur, 2),
        "pos120": round(pos120 * 100, 1),
        "pos250": round(pos250 * 100, 1),
        "drawdown120": round(dd120, 1),
        "dist_low120": round(dist_low, 1),
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
        "c5": round(c5, 1), "c10": round(c10, 1), "c20": round(c20, 1),
        "reasons": reasons,
    }
