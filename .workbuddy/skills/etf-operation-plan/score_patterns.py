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


EXTREMA_WINDOW = 5

def find_local_extrema(closes, window=EXTREMA_WINDOW):
    """Find local minima (valleys) and maxima (peaks) in close price series.
    
    Returns two lists of (index, price) tuples, ordered by index ascending.
    A point is a local extremum if it's the min/max within `window` bars on each side.
    """
    n = len(closes)
    lows = []
    highs = []
    
    for i in range(window, n - window):
        is_min = True
        is_max = True
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            if closes[j] <= closes[i]:
                is_min = False
            if closes[j] >= closes[i]:
                is_max = False
        
        if is_min:
            lows.append((i, closes[i]))
        if is_max:
            highs.append((i, closes[i]))
    
    return lows, highs


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


# ─── Box Consolidation Scoring ─────────────────────────────────────────────

def detect_box_bounces(highs, lows, closes, window_days):
    """
    Detect range quality by finding support/resistance touches.
    
    Uses local extrema detection within the window:
    - Finds local minima (support candidates) and local maxima (resistance candidates)
    - Clusters nearby extremes into support/resistance levels (within 2% tolerance)
    - Counts touches at each clustered level
    - Returns (max_support_touches, max_resistance_touches, support_level, resistance_level)
    """
    n = len(highs)
    if n < window_days:
        window_days = n
    
    h = highs[-window_days:]
    l = lows[-window_days:]
    c = closes[-window_days:]
    w = len(h)
    
    # Find local minima (support candidates): price within 5-day window where low is minimum
    local_mins = []
    for i in range(2, w - 2):
        if l[i] == min(l[i-2:i+3]):
            local_mins.append({"idx": i, "price": l[i], "close": c[i]})
    
    # Find local maxima (resistance candidates): price within 5-day window where high is maximum
    local_maxs = []
    for i in range(2, w - 2):
        if h[i] == max(h[i-2:i+3]):
            local_maxs.append({"idx": i, "price": h[i], "close": c[i]})
    
    # Filter out zero-priced extremes (data quality issue)
    local_mins = [x for x in local_mins if x["price"] > 0]
    local_maxs = [x for x in local_maxs if x["price"] > 0]
    
    if len(local_mins) < 2 or len(local_maxs) < 2:
        return 0, 0, 0, 0
    
    # Sort by price
    local_mins.sort(key=lambda x: x["price"])
    local_maxs.sort(key=lambda x: x["price"])
    
    # Cluster support levels (nearby lows within 3% tolerance)
    def cluster_levels(points, tolerance_pct=0.03):
        """Group nearby points into levels, count touches at each level."""
        if not points:
            return []
        clusters = []
        current = [points[0]]
        for p in points[1:]:
            avg = sum(x["price"] for x in current) / len(current)
            if avg <= 0:
                current.append(p)
            elif abs(p["price"] - avg) / avg < tolerance_pct:
                current.append(p)
            else:
                clusters.append(current)
                current = [p]
        clusters.append(current)
        
        results = []
        for cl in clusters:
            avg_price = sum(x["price"] for x in cl) / len(cl)
            results.append({
                "level": round(avg_price, 2),
                "touches": len(cl),
                "prices": [x["price"] for x in cl],
            })
        return results
    
    support_clusters = cluster_levels(local_mins, 0.025)
    resistance_clusters = cluster_levels(local_maxs, 0.025)
    
    # Find the strongest support and resistance clusters
    best_support = max(support_clusters, key=lambda x: x["touches"]) if support_clusters else {"level": 0, "touches": 0}
    best_resistance = max(resistance_clusters, key=lambda x: x["touches"]) if resistance_clusters else {"level": 0, "touches": 0}
    
    return best_support["touches"], best_resistance["touches"], best_support["level"], best_resistance["level"]


def analyze_box_consolidation(code, name, etype, kline_data):
    """
    Box consolidation (箱体震荡) analysis.
    
    Returns score (0-100), label, and detailed metrics.
    A tradable box range = moderate amplitude + flat trend + confirmed box + near support.
    """
    if not kline_data or len(kline_data) < 60:
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
    if len(records) < 60:
        return None
    records.sort(key=lambda x: x["date"])
    
    closes = [r["close"] for r in records]
    highs = [r["high"] for r in records]
    lows = [r["low"] for r in records]
    vols = [r["volume"] for r in records]
    n = len(closes)
    cur = closes[-1]
    
    # ---- 40-day window (中期) ----
    n40 = min(40, n)
    hi40 = max(highs[-n40:])
    lo40 = min(lows[-n40:])
    avg40 = sum(closes[-n40:]) / n40
    range40_pct = (hi40 - lo40) / avg40 * 100 if avg40 > 0 else 0
    pos40 = (cur - lo40) / (hi40 - lo40) if hi40 > lo40 else 0.5
    
    # ---- 90-day window (长期) ----
    n90 = min(90, n)
    hi90 = max(highs[-n90:])
    lo90 = min(lows[-n90:])
    avg90 = sum(closes[-n90:]) / n90
    range90_pct = (hi90 - lo90) / avg90 * 100 if avg90 > 0 else 0
    pos90 = (cur - lo90) / (hi90 - lo90) if hi90 > lo90 else 0.5
    
    # ---- Trend slopes ----
    t20 = lin_slope(closes, 20)
    t40 = lin_slope(closes, 40)
    t90 = lin_slope(closes, 90)
    
    # ---- Box bounce quality ----
    support_touches_40, resist_touches_40, sup_level_40, res_level_40 = detect_box_bounces(highs, lows, closes, 40)
    support_touches_90, resist_touches_90, sup_level_90, res_level_90 = detect_box_bounces(highs, lows, closes, 90)
    
    # Combined bounce quality
    total_bounces_40 = support_touches_40 + resist_touches_40
    total_bounces_90 = support_touches_90 + resist_touches_90
    
    # ---- ATR and volume ----
    atr20 = atr(highs, lows, closes, 20)
    atr90_val = atr(highs, lows, closes, 90)
    atr_ratio = atr20 / atr90_val if atr90_val > 0 else 1
    
    vol20 = sum(vols[-20:]) / 20
    vol60 = sum(vols[-60:]) / 60
    vol_ratio = vol20 / vol60 if vol60 > 0 else 1
    
    # ---- MA distances ----
    ma20 = sum(closes[-20:]) / 20
    ma40 = sum(closes[-n40:]) / n40
    ma90 = sum(closes[-n90:]) / n90
    d_ma20 = (cur - ma20) / ma20 * 100
    d_ma40 = (cur - ma40) / ma40 * 100
    d_ma90 = (cur - ma90) / ma90 * 100
    
    # ---- MA convergence: how close are MA20, MA40, MA90 to each other? ----
    ma_values = [ma20, ma40, ma90]
    ma_spread = (max(ma_values) - min(ma_values)) / ma20 * 100 if ma20 > 0 else 100
    
    # ---- Rate of change ----
    c5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if n >= 6 else 0
    c10 = (closes[-1] - closes[-11]) / closes[-11] * 100 if n >= 11 else 0
    c20_pct = (closes[-1] - closes[-21]) / closes[-21] * 100 if n >= 21 else 0
    
    # ---- Drawdown from 90d high ----
    dd90 = (cur - hi90) / hi90 * 100 if hi90 > 0 else 0
    
    # ---- Distance from 90d low ----
    dist_lo90 = (cur - lo90) / lo90 * 100 if lo90 > 0 else 0
    
    # ============ SCORING (max ~105, clamped 0-100) ============
    score = 0
    reasons = []
    
    # 1. 40-day range width (振幅) — max 25
    if 8 <= range40_pct <= 15:
        score += 25
        reasons.append(f"✅ 40日振幅理想({range40_pct:.1f}%) 适合差价")
    elif 5 <= range40_pct < 8:
        score += 15
        reasons.append(f"🟡 40日振幅适中({range40_pct:.1f}%) 差价空间略小")
    elif 15 < range40_pct <= 20:
        score += 12
        reasons.append(f"🟡 40日振幅较大({range40_pct:.1f}%) 差价空间充足")
    elif 20 < range40_pct <= 30:
        score += 5
        reasons.append(f"🟡 40日振幅偏大({range40_pct:.1f}%) 波动偏高")
    elif range40_pct > 30:
        score += 2
        reasons.append(f"❌ 40日振幅过大({range40_pct:.1f}%)")
    else:
        reasons.append(f"❌ 40日振幅过窄({range40_pct:.1f}%) 无差价空间")
    
    # 2. 90-day range width (振幅) — max 20
    if 10 <= range90_pct <= 20:
        score += 20
        reasons.append(f"✅ 90日振幅理想({range90_pct:.1f}%) 长线箱体")
    elif 5 <= range90_pct < 10:
        score += 12
        reasons.append(f"🟡 90日振幅适中({range90_pct:.1f}%)")
    elif 20 < range90_pct <= 30:
        score += 8
        reasons.append(f"🟡 90日振幅偏大({range90_pct:.1f}%)")
    elif range90_pct > 30:
        score += 3
        reasons.append(f"❌ 90日振幅过大({range90_pct:.1f}%)")
    else:
        reasons.append(f"❌ 90日振幅过窄({range90_pct:.1f}%)")
    
    # 3. Trend flatness 40d — max 20
    abs_t40 = abs(t40)
    if abs_t40 < 2:
        score += 20
        reasons.append(f"✅ 40日趋势平坦({t40:+.1f}%)")
    elif abs_t40 < 3:
        score += 15
        reasons.append(f"✅ 40日趋势平缓({t40:+.1f}%)")
    elif abs_t40 < 5:
        score += 8
        reasons.append(f"🟡 40日趋势微倾({t40:+.1f}%)")
    else:
        reasons.append(f"❌ 40日趋势明显({t40:+.1f}%)")
    
    # 4. Box bounce quality — max 15
    bounce_score = 0
    if support_touches_40 >= 3 and resist_touches_40 >= 3:
        bounce_score = 15
        reasons.append(f"✅ 箱体确认: 支撑{support_touches_40}触+阻力{resist_touches_40}触")
    elif support_touches_40 >= 2 and resist_touches_40 >= 2:
        bounce_score = 10
        reasons.append(f"🟡 箱体初现: 支撑{support_touches_40}触+阻力{resist_touches_40}触")
    elif support_touches_40 >= 1 and resist_touches_40 >= 1:
        bounce_score = 5
        reasons.append(f"🟡 箱体雏形: 支撑{support_touches_40}触+阻力{resist_touches_40}触")
    else:
        reasons.append(f"❌ 箱体不明确 支撑{support_touches_40}触+阻力{resist_touches_40}触")
    
    # Bonus for 90d box quality
    if support_touches_90 >= 3 and resist_touches_90 >= 3 and bounce_score < 15:
        bounce_score = max(bounce_score, 12)
    
    score += bounce_score
    
    # 5. Near support (entry signal) — max 10
    if pos40 <= 0.25:
        score += 10
        reasons.append(f"✅ 近箱底({pos40:.0%}) 买入区")
    elif pos40 <= 0.35:
        score += 6
        reasons.append(f"🟡 箱中偏底({pos40:.0%})")
    elif pos40 <= 0.65:
        score += 3
        reasons.append(f"🟡 箱中震荡({pos40:.0%})")
    else:
        reasons.append(f"⚠️ 近箱顶({pos40:.0%}) 追高风险")
    
    # 6. ATR compression — max 5
    if atr_ratio < 0.85:
        score += 5
        reasons.append(f"✅ 波幅压缩({atr_ratio:.0%})")
    elif atr_ratio < 1.0:
        score += 3
        reasons.append(f"🟡 波幅稳定({atr_ratio:.0%})")
    elif atr_ratio < 1.2:
        score += 1
        reasons.append(f"🟡 波幅正常({atr_ratio:.0%})")
    else:
        reasons.append(f"❌ 波幅放大({atr_ratio:.0%})")
    
    # 7. Volume stability — max 5
    if 0.7 <= vol_ratio <= 1.3:
        score += 5
        reasons.append(f"✅ 量能稳定({vol_ratio:.0%})")
    elif 0.5 <= vol_ratio <= 1.5:
        score += 3
        reasons.append(f"🟡 量能正常({vol_ratio:.0%})")
    else:
        reasons.append(f"❌ 量能异动({vol_ratio:.0%})")
    
    # 8. MA convergence bonus (均线粘合) — max +3
    if ma_spread < 2:
        score += 3
        reasons.append(f"✅ 均线粘合({ma_spread:.1f}%) +3pt")
    elif ma_spread < 4:
        score += 1
        reasons.append(f"🟡 均线趋合({ma_spread:.1f}%) +1pt")
    
    # ---- Penalties ----
    if abs_t40 > 8:
        penalty = 15
        score -= penalty
        reasons.append(f"🔴 强趋势惩罚({t40:+.1f}%) -{penalty}pt")
    
    if dd90 > -3:
        penalty = 10
        score -= penalty
        reasons.append(f"🔴 突破箱顶({dd90:+.1f}%) -{penalty}pt")
    
    if t40 < -6 and dd90 < -10:
        penalty = 10
        score -= penalty
        reasons.append(f"🔴 持续下跌({t40:+.1f}%) -{penalty}pt")
    
    score = max(0, min(100, score))
    
    # ---- Consolidation label ----
    is_box_40 = range40_pct >= 5 and abs_t40 < 5 and total_bounces_40 >= 4
    is_box_90 = range90_pct >= 8 and abs(t90) < 6 and total_bounces_90 >= 4
    is_narrow = range40_pct < 8 and range40_pct >= 3 and abs_t40 < 4
    is_wide = range40_pct > 20 and abs_t40 < 5
    is_downtrend = t40 < -8
    near_top = pos40 > 0.75

    if near_top and is_box_40 and score >= 45:
        label = "🟡 箱顶观望"
    elif is_box_40 and is_box_90 and score >= 70:
        label = "🟢 确认箱体(中长)"
    elif is_box_40 and score >= 60:
        label = "🟢 确认箱体(中期)"
    elif is_downtrend:
        label = "🔴 下跌趋势"
    elif is_narrow and score >= 45:
        label = "🟡 窄幅收敛"
    elif is_wide and score >= 45:
        label = "🟡 宽幅震荡"
    else:
        label = "⚪ 趋势行情"
    
    return {
        "code": code, "name": name, "type": etype,
        "score": score, "label": label,
        "current": round(cur, 2),
        "range40": round(range40_pct, 1),
        "range90": round(range90_pct, 1),
        "pos40": round(pos40 * 100, 1),
        "pos90": round(pos90 * 100, 1),
        "t20": round(t20, 1),
        "t40": round(t40, 1),
        "t90": round(t90, 1),
        "sup_touch_40": support_touches_40,
        "res_touch_40": resist_touches_40,
        "sup_level_40": round(sup_level_40, 2),
        "res_level_40": round(res_level_40, 2),
        "sup_touch_90": support_touches_90,
        "res_touch_90": resist_touches_90,
        "sup_level_90": round(sup_level_90, 2),
        "res_level_90": round(res_level_90, 2),
        "atr_ratio": round(atr_ratio, 2),
        "vol_ratio": round(vol_ratio, 2),
        "ma_spread": round(ma_spread, 1),
        "d_ma20": round(d_ma20, 1),
        "d_ma40": round(d_ma40, 1),
        "d_ma90": round(d_ma90, 1),
        "dd90": round(dd90, 1),
        "dist_lo90": round(dist_lo90, 1),
        "c5": round(c5, 1), "c10": round(c10, 1), "c20": round(c20_pct, 1),
        "reasons": reasons,
    }


# ─── W-Bottom Scoring ─────────────────────────────────────────────────────

def score_w_bottom(closes, volumes, lt_idx, lt_val, pk_idx, pk_val, rt_idx, rt_val, status):
    """
    Score a detected W-bottom on 8 dimensions (max ~97 pts, capped at 100).
    Returns (score, label, reasons_list).
    """
    score = 0
    reasons = []

    # 1. Trough Symmetry (20 pts)
    tdiff = abs(rt_val / lt_val - 1) * 100
    if tdiff <= 1:
        s = 20
        reasons.append(f"极佳双底对称(差{tdiff:.1f}%)+20")
    elif tdiff <= 3:
        s = 17
        reasons.append(f"良好双底对称(差{tdiff:.1f}%)+17")
    elif tdiff <= 6:
        s = 12
        reasons.append(f"双底对称(差{tdiff:.1f}%)+12")
    else:
        s = 5
        reasons.append(f"双底基本对称(差{tdiff:.1f}%)+5")
    score += s

    # 2. Recovery Magnitude (15 pts)
    recovery = (pk_val / lt_val - 1) * 100
    if recovery >= 15:
        s = 15
        reasons.append(f"强反弹({recovery:.1f}%)+15")
    elif recovery >= 12:
        s = 12
        reasons.append(f"反弹较强({recovery:.1f}%)+12")
    elif recovery >= 10:
        s = 8
        reasons.append(f"反弹适中({recovery:.1f}%)+8")
    else:
        s = 3
        reasons.append(f"反弹偏弱({recovery:.1f}%)+3")
    score += s

    # 3. Right Trough Elevation (15 pts)
    rt_ele = (rt_val / lt_val - 1) * 100
    if rt_ele >= 3:
        s = 15
        reasons.append(f"右底抬高{rt_ele:.1f}%+15")
    elif rt_ele >= 1:
        s = 10
        reasons.append(f"右底略高{rt_ele:.1f}%+10")
    elif rt_ele >= 0:
        s = 5
        reasons.append(f"右底持平+5")
    else:
        s = 0
        reasons.append(f"右底更低{rt_ele:.1f}%+0")
    score += s

    # 4. Volume Contraction (12 pts)
    lt_start = max(0, lt_idx - 5)
    lt_end = min(len(volumes), lt_idx + 6)
    rt_start = max(0, rt_idx - 5)
    rt_end = min(len(volumes), rt_idx + 6)
    lvol = sum(volumes[lt_start:lt_end]) / max(1, lt_end - lt_start)
    rvol = sum(volumes[rt_start:rt_end]) / max(1, rt_end - rt_start)
    vr = rvol / lvol if lvol > 0 else 1
    if vr <= 0.7:
        s = 12
        reasons.append(f"量能显著收缩(VR={vr:.2f})+12")
    elif vr <= 0.9:
        s = 9
        reasons.append(f"量能收缩(VR={vr:.2f})+9")
    elif vr <= 1.0:
        s = 6
        reasons.append(f"量能持平(VR={vr:.2f})+6")
    else:
        s = 2
        reasons.append(f"量能略增(VR={vr:.2f})+2")
    score += s

    # 5. Prior Decline Depth (10 pts)
    d_high = max(closes[:80])
    d_low = min(closes[:80])
    decline_pct = (d_high - d_low) / d_high * 100 if d_high > 0 else 0
    if decline_pct >= 15:
        s = 10
        reasons.append(f"前期深跌({decline_pct:.1f}%)+10")
    elif decline_pct >= 10:
        s = 7
        reasons.append(f"前期跌幅充分({decline_pct:.1f}%)+7")
    elif decline_pct >= 5:
        s = 3
        reasons.append(f"前期小幅下跌({decline_pct:.1f}%)+3")
    score += s

    # 6. Time Symmetry (5 pts)
    left_days = pk_idx - lt_idx
    right_days = rt_idx - pk_idx
    if left_days > 0 and right_days > 0:
        ratio = left_days / right_days
        if 0.7 <= ratio <= 1.3:
            s = 5
            reasons.append(f"时间对称({left_days}d/{right_days}d)+5")
        elif 0.5 <= ratio <= 1.5:
            s = 3
            reasons.append(f"时间基本对称({left_days}d/{right_days}d)+3")
        else:
            s = 1
            reasons.append(f"时间不对称({left_days}d/{right_days}d)+1")
    else:
        s = 0
    score += s

    # 7. Breakout Strength (10 pts, confirmed only)
    if status == "确认":
        bopct = (closes[-1] / pk_val - 1) * 100
        if bopct >= 5:
            s = 10
            reasons.append(f"强势突破({bopct:.1f}%)+10")
        elif bopct >= 3:
            s = 7
            reasons.append(f"有效突破({bopct:.1f}%)+7")
        elif bopct >= 0:
            s = 4
            reasons.append(f"微弱突破({bopct:.1f}%)+4")
    else:
        s = 0
    score += s

    # 8. Formation Quality (10 pts)
    q = 0
    p1_slope = lin_slope(closes[:80], 40) or 0
    if p1_slope < -0.3:
        q += 3
        reasons.append("平滑下跌+3")
    elif p1_slope < -0.1:
        q += 2
        reasons.append("温和下跌+2")
    elif p1_slope < 0:
        q += 1
    pk_surr = closes[max(0, pk_idx - 3):min(len(closes), pk_idx + 4)]
    pk_avg = sum(pk_surr) / len(pk_surr) if pk_surr else pk_val
    pk_ratio = pk_val / pk_avg if pk_avg > 0 else 1
    if pk_ratio > 1.03:
        q += 3
        reasons.append("峰位突出+3")
    elif pk_ratio > 1.01:
        q += 2
    else:
        q += 1
    rt_rec_high = max(closes[rt_idx:min(len(closes), rt_idx + 6)]) if rt_idx < len(closes) else rt_val
    rt_rec_ratio = rt_rec_high / rt_val if rt_val > 0 else 1
    if rt_rec_ratio > 1.03:
        q += 4
        reasons.append("右底V形反弹+4")
    elif rt_rec_ratio > 1.01:
        q += 3
        reasons.append("右底反弹+3")
    else:
        q += 1
    q = min(q, 10)
    score += q

    score = min(score, 100)

    # Label grading
    if score >= 55:
        label = "W底确认" if status == "确认" else "W底形成中"
    elif score >= 45:
        label = "W底形成中" if status == "形成中" else "W底确认"
    elif score >= 35:
        label = "W底候选"
    else:
        label = "非W底"

    return score, label, reasons


def detect_w_bottom(records):
    """
    Phase-based W-bottom detection on 120-day window (oldest-first sorted records).

    Returns dict with phase results and key points, or None if any phase fails.
    """
    n = len(records)
    if n < 120:
        return None

    closes = [r["close"] for r in records]
    volumes = [r["volume"] for r in records]

    # Phase 1: Prior decline (T-120 to T-40)
    p1_slope = lin_slope(closes[:80], 40)
    if p1_slope is None or p1_slope > -0.005:
        return None

    # Phase 2: Left trough (T-40 to T-25, indices 80-95)
    lt_idx, lt_val = None, float('inf')
    for i in range(80, 96):
        if closes[i] < lt_val:
            lt_val = closes[i]
            lt_idx = i

    # Phase 3: Peak (from left trough to T-12, index up to 108)
    pk_idx, pk_val = None, float('-inf')
    for i in range(lt_idx + 1, 109):
        if closes[i] > pk_val:
            pk_val = closes[i]
            pk_idx = i

    recovery = (pk_val / lt_val - 1) * 100
    if recovery < 8.0:
        return None

    # Phase 4: Right trough (T-12 to T, indices 108-120)
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

    # Phase 5: Breakout status
    recent3 = closes[-3:]
    above = sum(1 for c in recent3 if c > pk_val)
    status = "确认" if (above >= 2 and closes[-1] > pk_val) else "形成中"

    return {
        "lt_idx": lt_idx,
        "lt_val": lt_val,
        "pk_idx": pk_idx,
        "pk_val": pk_val,
        "rt_idx": rt_idx,
        "rt_val": rt_val,
        "status": status,
        "recovery": recovery,
        "tdiff": tdiff,
        "vratio": vratio,
    }


def analyze_w_bottom(code, name, etype, kline_data):
    """Main analysis: detect W-bottom pattern and score it."""
    if not kline_data or not isinstance(kline_data, list):
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
    if len(records) < 120:
        return None
    records.sort(key=lambda x: x["date"])

    # Use most recent 120 days for pattern detection
    window = records[-120:]
    detection = detect_w_bottom(window)
    if detection is None:
        return None

    closes = [r["close"] for r in window]
    volumes = [r["volume"] for r in window]
    score, label, reasons = score_w_bottom(
        closes, volumes,
        detection["lt_idx"], detection["lt_val"],
        detection["pk_idx"], detection["pk_val"],
        detection["rt_idx"], detection["rt_val"],
        detection["status"]
    )

    d_high = max(closes[:80])
    d_low = min(closes[:80])
    decline_pct = (d_high - d_low) / d_high * 100 if d_high > 0 else 0

    rt_ele = (detection["rt_val"] / detection["lt_val"] - 1) * 100

    return {
        "code": code,
        "name": name,
        "type": etype,
        "score": score,
        "label": label,
        "status": detection["status"],
        "current": round(records[-1]["close"], 3),
        "left_trough": round(detection["lt_val"], 3),
        "right_trough": round(detection["rt_val"], 3),
        "peak": round(detection["pk_val"], 3),
        "recovery_pct": round(detection["recovery"], 1),
        "trough_diff_pct": round(detection["tdiff"], 1),
        "vol_ratio": round(detection["vratio"], 2),
        "rt_elevation_pct": round(rt_ele, 1),
        "prior_decline_pct": round(decline_pct, 1),
        "lt_date": window[detection["lt_idx"]]["date"],
        "pk_date": window[detection["pk_idx"]]["date"],
        "rt_date": window[detection["rt_idx"]]["date"],
        "reasons": reasons,
    }


# ─── Head-Shoulder Bottom Scoring ─────────────────────────────────────────

def find_head_shoulder_pattern(lows, highs, closes, volumes):
    """Find the best head-shoulder-bottom pattern from valley triplets.
    
    Walks through valley triplets (v1, v2, v3) where v2 is the head (lowest).
    Validates geometry, finds connecting peaks for neckline, and scores.
    
    Returns dict with pattern details or None if no valid pattern found.
    """
    if len(lows) < 3:
        return None
    
    n = len(closes)
    candidates = []
    
    for i in range(len(lows) - 2):
        v1_idx, v1_price = lows[i]
        v2_idx, v2_price = lows[i + 1]
        v3_idx, v3_price = lows[i + 2]
        
        # Head (v2) must be the lowest
        if not (v2_price < v1_price and v2_price < v3_price):
            continue
        
        # Right shoulder should be in the last ~30% of the chart to be relevant
        if v3_idx < n * 0.65:
            continue
        
        # Shoulders should not be too far apart in price (within 15%)
        shoulder_max = max(v1_price, v3_price)
        shoulder_min = min(v1_price, v3_price)
        if shoulder_max > 0 and (shoulder_max - shoulder_min) / shoulder_min > 0.15:
            continue
        
        # Minimum time between shoulders and head (at least 10 bars)
        if v2_idx - v1_idx < 10 or v3_idx - v2_idx < 10:
            continue
        
        # Prior downtrend check
        early_start = max(0, v1_idx - 40)
        early_prices = closes[early_start:v1_idx] if v1_idx > early_start else closes[:1]
        early_high = max(early_prices) if early_prices else v1_price
        prior_decline = (early_high - v1_price) / early_high * 100 if early_high > 0 else 0
        
        # LS position in 120-day range
        ls_n120 = min(120, v1_idx + 1)
        ls_hi = max(closes[max(0, v1_idx - ls_n120 + 1):v1_idx + 1])
        ls_lo = min(closes[max(0, v1_idx - ls_n120 + 1):v1_idx + 1])
        ls_pos = (v1_price - ls_lo) / (ls_hi - ls_lo) * 100 if ls_hi > ls_lo else 50
        
        # Find peaks between valleys for neckline
        peak1_idx, peak1_price = None, float('-inf')
        peak2_idx, peak2_price = None, float('-inf')
        
        for p_idx, p_price in highs:
            if v1_idx < p_idx < v2_idx:
                if p_price > peak1_price:
                    peak1_idx, peak1_price = p_idx, p_price
            if v2_idx < p_idx < v3_idx:
                if p_price > peak2_price:
                    peak2_idx, peak2_price = p_idx, p_price
        
        if peak1_idx is None or peak2_idx is None:
            continue
        
        # Neckline slope (%)
        neck_slope = (peak2_price - peak1_price) / peak1_price * 100 if peak1_price > 0 else 0
        
        # Hard filter: neckline must be roughly horizontal (±7% max)
        if abs(neck_slope) > 7:
            continue
        
        # Volume analysis
        vol_ls = _avg_volume(volumes, v1_idx - 10, v1_idx + 10)
        vol_head = _avg_volume(volumes, v2_idx - 10, v2_idx + 10)
        vol_rs = _avg_volume(volumes, v3_idx - 10, v3_idx + 10)
        vol_rs_ls = vol_rs / vol_ls if vol_ls > 0 else 1.0
        vol_head_ls = vol_head / vol_ls if vol_ls > 0 else 1.0
        
        # Time symmetry
        days_ls_to_head = v2_idx - v1_idx
        days_head_to_rs = v3_idx - v2_idx
        time_sym = days_ls_to_head / days_head_to_rs if days_head_to_rs > 0 else 0
        time_sym = min(time_sym, 1 / time_sym) if time_sym > 0 else 0  # normalize to 0-1
        
        # Head depth
        head_depth_ls = (v1_price - v2_price) / v1_price * 100 if v1_price > 0 else 0
        head_depth_rs = (v3_price - v2_price) / v3_price * 100 if v3_price > 0 else 0
        head_depth = min(head_depth_ls, head_depth_rs)
        
        # Hard filter: head must be significantly lower than shoulders (≥0.5%)
        if head_depth < 0.5:
            continue
        
        # Shoulder symmetry
        shoulder_sym = 1.0 - abs(v1_price - v3_price) / max(v1_price, v3_price) if max(v1_price, v3_price) > 0 else 0
        
        # RS recovery
        rs_rising = closes[v3_idx] > closes[v3_idx - 5] if v3_idx >= 5 else False
        
        # Distance from RS to neckline
        neckline_at_rs = peak1_price + (peak2_price - peak1_price) * (v3_idx - peak1_idx) / (peak2_idx - peak1_idx) if peak2_idx > peak1_idx else peak1_price
        rs_to_neck_pct = (neckline_at_rs - v3_price) / v3_price * 100 if v3_price > 0 else 0
        
        candidates.append({
            "v1_idx": v1_idx, "v1_price": round(v1_price, 3),
            "v2_idx": v2_idx, "v2_price": round(v2_price, 3),
            "v3_idx": v3_idx, "v3_price": round(v3_price, 3),
            "peak1_idx": peak1_idx, "peak1_price": round(peak1_price, 3),
            "peak2_idx": peak2_idx, "peak2_price": round(peak2_price, 3),
            "neck_slope": round(neck_slope, 2),
            "vol_rs_ls": round(vol_rs_ls, 2),
            "vol_head_ls": round(vol_head_ls, 2),
            "time_sym": round(time_sym, 2),
            "head_depth": round(head_depth, 2),
            "shoulder_sym": round(shoulder_sym, 2),
            "rs_rising": rs_rising,
            "rs_to_neck_pct": round(rs_to_neck_pct, 2),
            "prior_decline": round(prior_decline, 1),
            "ls_pos": round(ls_pos, 0),
        })
    
    if not candidates:
        return None
    
    # Score each candidate
    for c in candidates:
        c["score_raw"] = score_pattern(c, closes, lows, highs)
    
    # Sort: prefer patterns with RS closest to end, then by score
    candidates.sort(key=lambda x: (-x["v3_idx"], -x["score_raw"]))
    
    best = candidates[0]
    best["score"] = best["score_raw"]
    del best["score_raw"]
    
    return best


def _avg_volume(volumes, start, end):
    """Average volume in a window, clamped to valid range."""
    start = max(0, start)
    end = min(len(volumes), end)
    if end <= start:
        return 0
    return sum(volumes[start:end]) / (end - start)


def score_pattern(p, closes, lows, highs):
    """Score a head-shoulder-bottom pattern candidate (max 100)."""
    score = 0
    reasons = []
    n = len(closes)
    cur = closes[-1]
    
    # ---- 1. Pattern completeness (max 30) ----
    all_points = all(k in p for k in ["v1_idx", "v2_idx", "v3_idx", "peak1_idx", "peak2_idx"])
    order_ok = (p["v1_idx"] < p["peak1_idx"] < p["v2_idx"] < p["peak2_idx"] < p["v3_idx"])
    
    if all_points and order_ok:
        score += 30
        reasons.append(f"✅ 模式完整(5点确认)")
    elif all_points:
        score += 20
        reasons.append(f"🟡 模式基本完整")
    elif p.get("v1_idx") is not None and p.get("v2_idx") is not None and p.get("v3_idx") is not None:
        score += 12
        reasons.append(f"🟡 三谷存在")
    
    # ---- 2. Head depth vs shoulders (max 15) ----
    hd = p.get("head_depth", 0)
    if hd >= 2.0:
        score += 15
        reasons.append(f"✅ 头部深度充分({hd:.1f}%)")
    elif hd >= 1.0:
        score += 8
        reasons.append(f"🟡 头深一般({hd:.1f}%)")
    else:
        reasons.append(f"❌ 头深不足({hd:.1f}%)")
    
    # ---- 3. Shoulder symmetry (max 10) ----
    ss = p.get("shoulder_sym", 0)
    if ss >= 0.95:
        score += 10
        reasons.append(f"✅ 肩部对称({ss:.0%})")
    elif ss >= 0.90:
        score += 7
        reasons.append(f"✅ 肩部较对称({ss:.0%})")
    elif ss >= 0.85:
        score += 4
        reasons.append(f"🟡 肩部偏差({ss:.0%})")
    else:
        reasons.append(f"❌ 肩部不对称({ss:.0%})")
    
    # ---- 4. Neckline flatness (max 12) ----
    ns = abs(p.get("neck_slope", 99))
    if ns <= 3:
        score += 12
        reasons.append(f"✅ 颈线平坦(斜率{ns:+.1f}%)")
    elif ns <= 5:
        score += 9
        reasons.append(f"✅ 颈线较平(斜率{ns:+.1f}%)")
    elif ns <= 7:
        score += 5
        reasons.append(f"🟡 颈线倾斜(斜率{ns:+.1f}%)")
    else:
        reasons.append(f"❌ 颈线陡峭(斜率{ns:+.1f}%)")
    
    # ---- 5. Volume contraction LS→RS (max 8) ----
    vr = p.get("vol_rs_ls", 1.0)
    if vr < 0.70:
        score += 8
        reasons.append(f"✅ 量度萎缩({vr:.0%})")
    elif vr < 0.85:
        score += 5
        reasons.append(f"✅ 量度缩({vr:.0%})")
    elif vr < 1.0:
        score += 3
        reasons.append(f"🟡 量度平稳({vr:.0%})")
    else:
        reasons.append(f"❌ 量度放大({vr:.0%})")
    
    # ---- 6. Range position (max 10) ----
    n120 = min(120, n)
    hi120 = max(closes[-n120:])
    lo120 = min(closes[-n120:])
    pos120 = (cur - lo120) / (hi120 - lo120) if hi120 > lo120 else 0.5
    
    if pos120 <= 0.30:
        score += 10
        reasons.append(f"✅ 底部区间({pos120*100:.0f}%)")
    elif pos120 <= 0.50:
        score += 5
        reasons.append(f"🟡 中低位({pos120*100:.0f}%)")
    else:
        if pos120 > 0.80:
            score -= 5
            reasons.append(f"⚠️ 高位风险({pos120*100:.0f}%)")
        elif pos120 > 0.70:
            score -= 3
            reasons.append(f"⚠️ 偏高位({pos120*100:.0f}%)")
        else:
            reasons.append(f"❌ 中高位({pos120*100:.0f}%)")
    
    # ---- 7. Time symmetry (max 8) ----
    ts = p.get("time_sym", 0)
    if ts >= 0.60:
        score += 8
        reasons.append(f"✅ 时间对称({ts:.2f})")
    elif ts >= 0.40:
        score += 4
        reasons.append(f"🟡 时间偏斜({ts:.2f})")
    else:
        reasons.append(f"❌ 时间不对({ts:.2f})")
    
    # ---- 8. RS recovery / breakout tendency (max 7) ----
    rtn = p.get("rs_to_neck_pct", 99)
    if rtn <= 3:
        score += 7
        reasons.append(f"✅ 右肩接近颈线(距{rtn:.1f}%)")
    elif rtn <= 8:
        score += 4
        reasons.append(f"🟡 右肩距颈线{rtn:.1f}%")
    elif p.get("rs_rising"):
        score += 2
        reasons.append(f"🟡 右肩上升中")
    else:
        reasons.append(f"❌ 右肩远离颈线({rtn:.1f}%)")
    
    # ---- Penalties ----
    pd = p.get("prior_decline", 99)
    if pd < 3:
        score -= 15
        reasons.append(f"⚠️ 前置跌幅不足({pd:.0f}%): 非真正下跌后反转")
    elif pd < 5:
        score -= 10
        reasons.append(f"⚠️ 前置跌幅偏弱({pd:.0f}%)")
    elif pd < 8:
        score -= 5
        reasons.append(f"⚠️ 前置跌幅一般({pd:.0f}%)")
    else:
        reasons.append(f"✅ 前置跌幅充分({pd:.0f}%)")
    
    lp = p.get("ls_pos", 50)
    if lp > 75:
        score -= 10
        reasons.append(f"⚠️ 左肩高位({lp:.0f}%): 形态处于上涨区间")
    elif lp > 60:
        score -= 5
        reasons.append(f"⚠️ 左肩偏高({lp:.0f}%)")
    elif lp <= 35:
        reasons.append(f"✅ 左肩低位({lp:.0f}%)")
    
    # Recent crash
    t20 = lin_slope(closes[-20:], 20) if n >= 20 else 0
    if t20 < -12:
        score -= 20
        reasons.append(f"⚠️ 近20日暴跌({t20:+.1f}%)")
    elif t20 < -8:
        score -= 10
        reasons.append(f"⚠️ 近20日下跌({t20:+.1f}%)")
    
    # Volume expansion
    if vr > 1.3:
        score -= 15
        reasons.append(f"⚠️ 量度异常放大({vr:.0%})")
    
    # RS too far from neckline
    if rtn > 20:
        score -= 10
        reasons.append(f"⚠️ 右肩远离颈线({rtn:.1f}%)")
    
    # Too many extrema
    if len(lows) > 15 or len(highs) > 15:
        score -= 10
        reasons.append(f"⚠️ 走势杂乱(谷{len(lows)}/峰{len(highs)})")
    
    # Head not truly lowest
    v2_price = p.get("v2_price", 0)
    v1_price = p.get("v1_price", 0)
    v3_price = p.get("v3_price", 0)
    if v1_price > 0 and v2_price > 0 and v3_price > 0:
        if v2_price >= v1_price or v2_price >= v3_price:
            score -= 30
            reasons.append(f"⚠️ 头部非最低点")
    
    score = max(0, min(100, score))
    p["reasons"] = reasons
    return score


def analyze_hs_bottom(code, name, etype, kline_data):
    """Analyze an ETF for head-shoulder-bottom pattern."""
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
    highs_p = [r["high"] for r in records]
    lows_p = [r["low"] for r in records]
    vols = [r["volume"] for r in records]
    n = len(closes)
    cur = closes[-1]
    
    # Find local extrema
    valley_list, peak_list = find_local_extrema(closes)
    
    # Find head-shoulder pattern
    pattern = find_head_shoulder_pattern(valley_list, peak_list, closes, vols)
    
    # ---- Always compute basic metrics ----
    n120 = min(120, n)
    n250 = min(250, n)
    hi120, lo120 = max(highs_p[-n120:]), min(lows_p[-n120:])
    hi250, lo250 = max(highs_p[-n250:]), min(lows_p[-n250:])
    pos120 = (cur - lo120) / (hi120 - lo120) if hi120 > lo120 else 0.5
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5
    
    t20 = lin_slope(closes, 20)
    t60 = lin_slope(closes, 60) if n >= 60 else 0
    
    c5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if n >= 6 else 0
    c10 = (closes[-1] - closes[-11]) / closes[-11] * 100 if n >= 11 else 0
    c20 = (closes[-1] - closes[-21]) / closes[-21] * 100 if n >= 21 else 0
    
    vol20 = sum(vols[-20:]) / 20 if n >= 20 else 0
    vol60 = sum(vols[-60:]) / 60 if n >= 60 else 0
    vol_ratio = vol20 / vol60 if vol60 > 0 else 1
    
    ma20 = sum(closes[-20:]) / 20 if n >= 20 else cur
    ma60 = sum(closes[-60:]) / 60 if n >= 60 else cur
    d_ma20 = (cur - ma20) / ma20 * 100
    d_ma60 = (cur - ma60) / ma60 * 100
    
    base = {
        "code": code, "name": name, "type": etype,
        "current": round(cur, 2),
        "pos120": round(pos120 * 100, 1),
        "pos250": round(pos250 * 100, 1),
        "t20": round(t20, 1),
        "t60": round(t60, 1),
        "c5": round(c5, 1), "c10": round(c10, 1), "c20": round(c20, 1),
        "vol_ratio": round(vol_ratio, 2),
        "d_ma20": round(d_ma20, 1),
        "d_ma60": round(d_ma60, 1),
        "num_valleys": len(valley_list),
        "num_peaks": len(peak_list),
    }
    
    if pattern is None:
        base["score"] = 0
        base["label"] = "⚪ 非头肩底"
        base["has_pattern"] = False
        base["reasons"] = [f"❌ 未找到符合条件的头肩底形态(共{len(valley_list)}谷{len(peak_list)}峰)"]
        return base
    
    # Pattern found
    base["has_pattern"] = True
    base["score"] = pattern["score"]
    base["reasons"] = pattern.get("reasons", [])
    base["head_depth"] = pattern.get("head_depth", 0)
    base["shoulder_sym"] = pattern.get("shoulder_sym", 0)
    base["neck_slope"] = pattern.get("neck_slope", 0)
    base["vol_rs_ls"] = pattern.get("vol_rs_ls", 1)
    base["time_sym"] = pattern.get("time_sym", 0)
    base["rs_to_neck_pct"] = pattern.get("rs_to_neck_pct", 99)
    base["v1_idx"] = pattern.get("v1_idx")
    base["v2_idx"] = pattern.get("v2_idx")
    base["v3_idx"] = pattern.get("v3_idx")
    base["peak1_idx"] = pattern.get("peak1_idx")
    base["peak2_idx"] = pattern.get("peak2_idx")
    base["v1_price"] = pattern.get("v1_price")
    base["v2_price"] = pattern.get("v2_price")
    base["v3_price"] = pattern.get("v3_price")
    base["peak1_price"] = pattern.get("peak1_price")
    base["peak2_price"] = pattern.get("peak2_price")
    base["rs_rising"] = pattern.get("rs_rising", False)
    
    # Label
    score = pattern["score"]
    rtn = pattern.get("rs_to_neck_pct", 99)
    
    if score >= 72 and rtn <= 8:
        base["label"] = "🟢 头肩底确认"
    elif score >= 52 and rtn <= 12:
        base["label"] = "🟢 头肩底形成中"
    elif score >= 40:
        base["label"] = "🟡 头肩底候选"
    else:
        base["label"] = "⚪ 非头肩底"

    return base
