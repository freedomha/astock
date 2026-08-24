#!/usr/bin/env python3
"""
A股ETF头肩底形态分析 (v1)

头肩底判定逻辑:
1. 寻找250日K线的局部极值点(峰与谷)
2. 遍历连续三谷(v1,v2,v3)，检查v2<v1且v2<v3(中间谷最低=头部)
3. 找到v1-v2和v2-v3之间的最高峰，构成颈线
4. 多维度评分: 模式完整性、头部深度、肩部对称、颈线质量、量能萎缩、时间对称、区间位置
5. 标签分级: 头肩底确认 / 头肩底形成中 / 头肩底候选 / 非头肩底
"""

import json
import subprocess
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK_BIN = "/Users/aldiadmin/.workbuddy/westock-data/scripts/index.js"
NODE_BIN = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"

KLINE_DAYS = 250
MAX_WORKERS = 8
CHECK_DAYS = 5  # Fetch this many days for the quick staleness check
EXTREMA_WINDOW = 10  # bars on each side for local extrema detection


def run_westock(*args):
    """Run a westock-data command and return JSON output."""
    cmd = [NODE_BIN, WESTOCK_BIN] + list(args) + ["--raw"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        if isinstance(data, dict) and data.get("success") is False:
            return None
        return data
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        return None


def fetch_kline(code, retries=4):
    """Fetch 250-day K-line for an ETF, with retry on transient errors."""
    for attempt in range(retries):
        data = run_westock("kline", code, "--period", "day", "--limit", str(KLINE_DAYS))
        if data:
            return code, data
        if attempt < retries - 1:
            time.sleep(0.3)
    return code, None


def load_etfs():
    """Load ETF codes from all_etfs_larggest.json in project root."""
    input_path = os.path.join(os.getcwd(), "all_etfs_larggest.json")
    if not os.path.exists(input_path):
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        return []
    with open(input_path) as f:
        data = json.load(f)
    etfs = []
    for e in data:
        etfs.append({
            "code": e["code"],
            "name": e["name"],
            "type": e.get("type", "ETF"),
            "size": e.get("size"),
        })
    return etfs


def atr(prices, window):
    """Average True Range (simplified, using close-to-close)."""
    s = 0
    for i in range(len(prices) - window, len(prices)):
        if i > 0:
            s += abs(prices[i] - prices[i-1])
    return s / window if window else 0


def lin_slope(arr, win):
    """Linear regression slope over last `win` points, returned as % change."""
    if len(arr) < win:
        return 0
    y = arr[-win:]
    x = list(range(win))
    xm, ym = sum(x) / win, sum(y) / win
    num = sum((x[i] - xm) * (y[i] - ym) for i in range(win))
    den = sum((x[i] - xm) ** 2 for i in range(win))
    s = num / den if den else 0
    return s * win / ym * 100 if ym else 0


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
        
        # Shoulders should not be too far apart in price (within 15% — tighter for better symmetry)
        shoulder_max = max(v1_price, v3_price)
        shoulder_min = min(v1_price, v3_price)
        if shoulder_max > 0 and (shoulder_max - shoulder_min) / shoulder_min > 0.15:
            continue
        
        # Minimum time between shoulders and head (at least 10 bars)
        if v2_idx - v1_idx < 10 or v3_idx - v2_idx < 10:
            continue
        
        # Prior downtrend check: LS must form after a real decline, not in a sideways/up market.
        # Head-shoulder-bottom is a REVERSAL pattern — compute quality metrics for scoring.
        early_start = max(0, v1_idx - 40)
        early_prices = closes[early_start:v1_idx] if v1_idx > early_start else closes[:1]
        early_high = max(early_prices) if early_prices else v1_price
        prior_decline = (early_high - v1_price) / early_high * 100 if early_high > 0 else 0
        
        # LS position in 120-day range (was it near the bottom of a real decline?)
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
        
        # Hard filter: neckline must be roughly horizontal (±7% max — tightened from v1)
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
        
        # RS recovery - is RS recently rising?
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
    # All 5 points found and in correct order
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
    
    # ---- 4. Neckline flatness (max 12, increased) ----
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
        # High range position = weaker reversal signal, apply penalty
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
    # Prior decline insufficient (LS didn't form after real downtrend)
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
    
    # LS formed too high in range (in an uptrend, not after a real decline)
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
    
    # Volume expansion (contradicts selling exhaustion thesis)
    if vr > 1.3:
        score -= 15
        reasons.append(f"⚠️ 量度异常放大({vr:.0%})")
    
    # RS too far from neckline (pattern not developing)
    if rtn > 20:
        score -= 10
        reasons.append(f"⚠️ 右肩远离颈线({rtn:.1f}%)")
    
    # Too many extrema (messy pattern)
    if len(lows) > 15 or len(highs) > 15:
        score -= 10
        reasons.append(f"⚠️ 走势杂乱(谷{len(lows)}/峰{len(highs)})")
    
    # Head not truly lowest? (safety check)
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
    
    # ---- Always compute basic metrics for all ETFs ----
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
        # No pattern found
        base["score"] = 0
        base["label"] = "⚪ 非头肩底"
        base["has_pattern"] = False
        base["reasons"] = [f"❌ 未找到符合条件的头肩底形态(共{len(valley_list)}谷{len(peak_list)}峰)"]
        return base
    
    # Pattern found - merge pattern details
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
    rs_rising = pattern.get("rs_rising", False)
    
    if score >= 72 and rtn <= 8:
        base["label"] = "🟢 头肩底确认"
    elif score >= 52 and rtn <= 12:
        base["label"] = "🟢 头肩底形成中"
    elif score >= 40:
        base["label"] = "🟡 头肩底候选"
    else:
        base["label"] = "⚪ 非头肩底"

    return base


def label_pattern(score, rs_to_neck_pct):
    """Standalone label function — callable from backtest.py and other tools."""
    if score >= 72 and rs_to_neck_pct <= 8:
        return "🟢 头肩底确认"
    elif score >= 52 and rs_to_neck_pct <= 12:
        return "🟢 头肩底形成中"
    elif score >= 40:
        return "🟡 头肩底候选"
    else:
        return "⚪ 非头肩底"


def update_kline_data(kline_data, etfs, kline_file, refresh_today=False):
    """
    Check cached kline data and append latest records if any are missing.

    Strategy:
    1. Fetch a small sample (CHECK_DAYS days) for the first ETF to determine
       the latest available trading date from the data source.
    2. Compare each cached ETF's newest date against the latest available.
    3. For ETFs needing an update, fetch fresh 250-day data in parallel and
       prepend only records newer than the cached newest date.
    4. New ETFs not in cache are fetched and added whole.
    5. Save the merged result back to disk.

    When refresh_today=True, ETFs whose latest cached date equals the
    latest available date are also refreshed — this replaces intraday
    (盘中) data with the latest bars from the data source.

    Returns the number of ETFs updated.
    """
    if not etfs:
        return 0

    # ---- Quick check: get the latest available date from data source ----
    sample_code = etfs[0]["code"]
    sample_data = run_westock("kline", sample_code, "--period", "day", "--limit", str(CHECK_DAYS))
    if not sample_data or not isinstance(sample_data, list) or len(sample_data) == 0:
        print("  ⚠ 无法获取最新交易日期, 跳过更新检查")
        return 0
    latest_available_date = sample_data[0]["date"]

    # ---- Determine which ETFs need an update ----
    to_update = []
    to_refresh = []  # ETFs whose today-bar needs refresh (same date, possibly intraday)
    for e in etfs:
        code = e["code"]
        cached = kline_data.get(code)
        if not cached or not isinstance(cached, list) or len(cached) == 0:
            to_update.append(code)
            continue
        latest_cached_date = cached[0]["date"]  # newest-first
        if latest_cached_date < latest_available_date:
            to_update.append(code)
        elif refresh_today and latest_cached_date == latest_available_date:
            to_refresh.append(code)

    all_to_process = to_update + to_refresh
    if not all_to_process:
        if refresh_today:
            print("  盘中数据已刷新为收盘数据")
        return 0

    refresh_desc = f" (+{len(to_refresh)} 只刷新今日盘中数据)" if to_refresh else ""
    print(f"\n🔄 需要更新 {len(all_to_process)} 只ETF的K线数据 (最新交易日: {latest_available_date}){refresh_desc}")

    # ---- Fetch and merge in parallel ----
    updated = 0
    failed = 0
    total = len(all_to_process)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_kline, code): code for code in all_to_process}
        for future in as_completed(futures):
            code = futures[future]
            try:
                _, new_data = future.result()
                if new_data and isinstance(new_data, list) and len(new_data) > 0:
                    cached = kline_data.get(code, [])
                    if code in to_refresh:
                        # Replace entire dataset — refreshes intraday bar with latest from source
                        kline_data[code] = new_data
                        updated += 1
                    elif cached and isinstance(cached, list) and len(cached) > 0:
                        latest_cached_date = cached[0]["date"]
                        new_records = [r for r in new_data if r["date"] > latest_cached_date]
                        if new_records:
                            kline_data[code] = new_records + cached
                            updated += 1
                        # else: no new records to append (up to date)
                    else:
                        kline_data[code] = new_data
                        updated += 1
                else:
                    failed += 1
                if (updated + failed) % 20 == 0:
                    print(f"  更新进度: {updated + failed}/{total}")
            except Exception as e:
                failed += 1
                print(f"  {code} 更新失败: {e}")

    print(f"更新完成: {updated} 成功, {failed} 失败")

    # ---- Save merged data ----
    if updated > 0:
        with open(kline_file, "w") as f:
            json.dump(kline_data, f, ensure_ascii=False)
        print(f"K线数据已保存: {kline_file}")

    return updated


def main():
    refresh_today = "--no-refresh" not in sys.argv
    print("=" * 60)
    print("A股ETF头肩底形态分析 (v2)")
    if refresh_today:
        print("🔄 盘中刷新模式: 同日期数据将用最新数据替换 (默认开启, --no-refresh 关闭)")
    print("=" * 60)
    
    # Step 1: Load ETFs
    print("\n[1/4] 加载ETF列表...")
    etfs = load_etfs()
    if not etfs:
        print("ERROR: 未找到ETF列表。请确保 all_etfs_larggest.json 存在。")
        return
    print(f"共加载 {len(etfs)} 只ETF")
    
    # Step 2: Check for existing K-line data
    cwd = os.getcwd()
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    kline_data = {}
    
    if os.path.exists(kline_file):
        print(f"\n[2/4] 发现已有K线数据: {kline_file}")
        try:
            with open(kline_file) as f:
                kline_data = json.load(f)
            print(f"已加载 {len(kline_data)} 只ETF的K线数据 (跳过拉取)")

            # Append latest data if available
            updated = update_kline_data(kline_data, etfs, kline_file, refresh_today)
            if updated > 0:
                print(f"已追加 {updated} 只ETF的最新记录")
            else:
                print("K线数据已是最新，无需更新")
        except Exception:
            print("读取失败，将重新拉取")
            kline_data = {}
    
    if not kline_data:
        print(f"\n[2/4] 并行拉取K线数据 (最多{MAX_WORKERS}并发, 每个{KLINE_DAYS}天)...")
        codes = [e["code"] for e in etfs]
        done = 0
        total = len(codes)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_kline, code): code for code in codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    _, data = future.result()
                    if data:
                        kline_data[code] = data
                    done += 1
                    if done % 20 == 0 or done == total:
                        print(f"  进度: {done}/{total}")
                except Exception as e:
                    print(f"  {code} 拉取失败: {e}")
                    done += 1
        print(f"成功获取 {len(kline_data)}/{total} 只ETF K线数据")
        
        # Re-fetch failures
        missing = [c for c in codes if c not in kline_data]
        if missing:
            print(f"\n  补拉 {len(missing)} 只失败ETF (增强重试, 最多6次)...")
            for c in missing:
                _, d = fetch_kline(c, retries=6)
                if d:
                    kline_data[c] = d
            still_missing = [c for c in codes if c not in kline_data]
            print(f"  补拉后覆盖 {len(kline_data)}/{total} (仍缺失 {len(still_missing)})")
        
        with open(kline_file, "w") as f:
            json.dump(kline_data, f, ensure_ascii=False)
        print(f"K线数据已保存: {kline_file}")
    
    # Step 3: Analyze patterns
    print("\n[3/4] 分析头肩底形态...")
    results = []
    for i, e in enumerate(etfs):
        kl = kline_data.get(e["code"])
        if not kl:
            continue
        r = analyze_hs_bottom(e["code"], e["name"], e["type"], kl)
        if r:
            results.append(r)
        if (i + 1) % 50 == 0:
            print(f"  进度: {i+1}/{len(etfs)}")
    
    results.sort(key=lambda x: x["score"], reverse=True)
    
    results_file = os.path.join(skill_dir, "etf_hs_bottom_results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"分析结果已保存: {results_file}")
    
    # Step 4: Summary
    confirmed = [r for r in results if r["label"] == "🟢 头肩底确认"]
    forming = [r for r in results if r["label"] == "🟢 头肩底形成中"]
    candidate = [r for r in results if r["label"] == "🟡 头肩底候选"]
    none_ = [r for r in results if r["label"] == "⚪ 非头肩底"]
    
    print("\n" + "=" * 60)
    print(f" 头肩底形态汇总 (共{len(results)}只ETF)")
    print("=" * 60)
    print(f"  🟢 头肩底确认: {len(confirmed)}")
    print(f"  🟢 头肩底形成中: {len(forming)}")
    print(f"  🟡 头肩底候选: {len(candidate)}")
    print(f"  ⚪ 非头肩底: {len(none_)}")
    
    has_pattern = [r for r in results if r.get("has_pattern")]
    print(f"\n 有3谷形态结构: {len(has_pattern)} 只ETF")
    
    if has_pattern:
        print(f"\n{'排名':<4}{'ETF':<20}{'得分':<5}{'判定':<14}{'头深%':<7}{'肩对%':<7}{'颈斜%':<7}{'量缩':<6}{'时对':<6}{'右距颈%':<8}")
        print("-" * 100)
        for i, r in enumerate(has_pattern[:20]):
            hd = r.get("head_depth", 0)
            ss = r.get("shoulder_sym", 0)
            ns = r.get("neck_slope", 0)
            vr = r.get("vol_rs_ls", 1)
            ts = r.get("time_sym", 0)
            rtn = r.get("rs_to_neck_pct", 99)
            print(f"{i+1:<4}{r['name']:<20}{r['score']:<5}{r['label']:<14}{hd:<7.1f}{ss:<7.0%}{ns:<+7.1f}{vr:<6.2f}{ts:<6.2f}{rtn:<8.1f}")
    
    # Detailed for confirmed
    if confirmed or forming:
        print("\n" + "=" * 60)
        print(" 头肩底确认/形成中 ETF 详细分析")
        print("=" * 60)
        for i, r in enumerate((confirmed + forming)[:15]):
            print(f"\n{i+1}. {r['name']} — {r['label']} 得分:{r['score']}/100")
            print(f"   当前: {r['current']} | 120日位:{r['pos120']}% | 250日位:{r['pos250']}%")
            if r.get("has_pattern"):
                print(f"   左肩价:{r.get('v1_price', 'N/A')} | 头部价:{r.get('v2_price', 'N/A')} | 右肩价:{r.get('v3_price', 'N/A')}")
                print(f"   颈线: {r.get('peak1_price', 'N/A')}→{r.get('peak2_price', 'N/A')} (斜率{r.get('neck_slope', 0):+.1f}%)")
                print(f"   头深:{r.get('head_depth', 0):.1f}% | 肩对:{r.get('shoulder_sym', 0):.0%} | 时对:{r.get('time_sym', 0):.2f}")
                print(f"   量缩:{r.get('vol_rs_ls', 1):.2f} | 右距颈线:{r.get('rs_to_neck_pct', 99):.1f}%")
            print(f"   判定依据:")
            for d in r.get("reasons", []):
                print(f"     {d}")
    
    return results


if __name__ == "__main__":
    main()
