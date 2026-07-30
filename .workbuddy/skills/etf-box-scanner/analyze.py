#!/usr/bin/env python3
"""
A股ETF箱体震荡形态分析 (v1)

判定逻辑核心: 可做中線差价的箱体震荡 = 
① 振幅适中(8-20%) ② 趋势平坦 ③ 箱体确认(多次触顶触底) ④ 位置有利(近支撑)

评分引擎专为中线差价设计:
- 40日/90日双窗口箱体检测
- 支撑阻力触及次数(箱体质量)
- ATR压缩 + 量能稳定验证
- 7维度打分 (max 100)
- 6级形态标签
"""

import json
import subprocess
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK_BIN = "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data/scripts/index.js"
NODE_BIN = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"

KLINE_DAYS = 250
MAX_WORKERS = 8


def run_westock(*args):
    """Run a westock-data command and return JSON output."""
    cmd = [NODE_BIN, WESTOCK_BIN] + list(args) + ["--raw"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
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
        print(f"Input file not found: {input_path}", file=sys.stderr)
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


def lin_slope(arr, win):
    """Linear regression slope over last `win` points, returned as % change over the window."""
    if len(arr) < win:
        return 0
    y = arr[-win:]
    x = list(range(win))
    xm, ym = sum(x) / win, sum(y) / win
    num = sum((x[i] - xm) * (y[i] - ym) for i in range(win))
    den = sum((x[i] - xm) ** 2 for i in range(win))
    s = num / den if den else 0
    return s * win / ym * 100 if ym else 0


def atr(highs, lows, closes, window):
    """Average True Range using True Range: max(H-L, |H-prev_C|, |L-prev_C|)."""
    n = len(closes)
    if n < window + 1:
        return 0
    tr_sum = 0
    start = n - window
    for i in range(start, n):
        if i > 0:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_sum += tr
    return tr_sum / window if window else 0


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
    # Lower = more converged (均线粘合)
    
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
    # Strong trend
    if abs_t40 > 8:
        penalty = 15
        score -= penalty
        reasons.append(f"🔴 强趋势惩罚({t40:+.1f}%) -{penalty}pt")
    
    # Breaking above range (trending up)
    if dd90 > -3:
        penalty = 10
        score -= penalty
        reasons.append(f"🔴 突破箱顶({dd90:+.1f}%) -{penalty}pt")
    
    # Breaking below range (trending down)
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


def main():
    print("=" * 60)
    print("A股ETF箱体震荡形态分析 (v1)")
    print("=" * 60)
    
    # Step 1: Load ETFs
    print("\nLoading ETF list...")
    etfs = load_etfs()
    if not etfs:
        print("ERROR: ETF list not found. Ensure all_etfs_larggest.json exists in project root.")
        return
    print(f"Loaded {len(etfs)} ETFs")
    
    # Step 2: Fetch K-line data in parallel
    print(f"\nFetching K-line data (max {MAX_WORKERS} concurrent, {KLINE_DAYS} days each)...")
    codes = [e["code"] for e in etfs]
    kline_data = {}
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
                    print(f"  Progress: {done}/{total}")
            except Exception as e:
                print(f"  {code} fetch error: {e}")
                done += 1
    print(f"Fetched {len(kline_data)}/{total} ETF K-lines")
    
    # Re-fetch failures
    missing = [c for c in codes if c not in kline_data]
    if missing:
        print(f"\nRetrying {len(missing)} failed ETFs (up to 6 retries)...")
        for c in missing:
            _, d = fetch_kline(c, retries=6)
            if d:
                kline_data[c] = d
        still_missing = [c for c in codes if c not in kline_data]
        print(f"After retry: {len(kline_data)}/{total} (still missing {len(still_missing)})")
        if still_missing:
            name_map = {e["code"]: e["name"] for e in etfs}
            print("  Missing:", ", ".join(f'{name_map.get(c, c)}({c})' for c in still_missing))
    
    # Save raw kline data
    cwd = os.getcwd()
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    kline_file = os.path.join(skill_dir, "etf_box_kline_data.json")
    with open(kline_file, "w") as f:
        json.dump(kline_data, f, ensure_ascii=False)
    print(f"K-line data saved: {kline_file}")
    
    # Step 3: Analyze box consolidation
    print("\nAnalyzing box consolidation patterns...")
    results = []
    for e in etfs:
        kl = kline_data.get(e["code"])
        if not kl:
            continue
        r = analyze_box_consolidation(e["code"], e["name"], e["type"], kl)
        if r:
            results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)
    
    results_file = os.path.join(skill_dir, "etf_box_results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Results saved: {results_file}")
    
    # Step 4: Summary
    box_long = [r for r in results if "中长" in r["label"]]
    box_medium = [r for r in results if "中期" in r["label"] and "中长" not in r["label"]]
    box_top = [r for r in results if r["label"].startswith("🟡 箱顶")]
    narrow = [r for r in results if r["label"].startswith("🟡 窄幅")]
    wide = [r for r in results if r["label"].startswith("🟡 宽幅")]
    downtrend = [r for r in results if r["label"].startswith("🔴")]
    trend = [r for r in results if r["label"].startswith("⚪")]
    
    print("\n" + "=" * 60)
    print(f"Box Consolidation Summary ({len(results)} ETFs total)")
    print("=" * 60)
    print(f"  🟢 确认箱体(中长): {len(box_long)}")
    print(f"  🟢 确认箱体(中期): {len(box_medium)}")
    print(f"  🟡 箱顶观望: {len(box_top)}")
    print(f"  🟡 窄幅收敛: {len(narrow)}")
    print(f"  🟡 宽幅震荡: {len(wide)}")
    print(f"  🔴 下跌趋势: {len(downtrend)}")
    print(f"  ⚪ 趋势行情: {len(trend)}")
    
    print(f"\n{'#':<4}{'ETF':<18}{'Scr':<4}{'Label':<16}{'40dr%':<7}{'90dr%':<7}{'t40%':<7}{'S/R':<7}{'Pos':<6}")
    print("-" * 90)
    for i, r in enumerate(results[:20]):
        sr = f"{r['sup_touch_40']}/{r['res_touch_40']}"
        print(f"{i+1:<4}{r['name']:<18}{r['score']:<4}{r['label']:<16}{r['range40']:<7}{r['range90']:<7}{r['t40']:+<7}{sr:<7}{r['pos40']:<6}%")
    
    # Detailed for confirmed boxes
    if box_long or box_medium:
        print("\n" + "=" * 60)
        print("Confirmed Box ETFs — Detail Analysis")
        print("=" * 60)
        for i, r in enumerate(box_long + box_medium):
            print(f"\n{i+1}. {r['name']} — {r['label']} Score:{r['score']}/100")
            print(f"   Price: {r['current']} | 40d Range: {r['range40']}% | 90d Range: {r['range90']}%")
            print(f"   Trend 20d:{r['t20']:+}% | 40d:{r['t40']:+}% | 90d:{r['t90']:+}%")
            print(f"   Box40: S={r['sup_level_40']}({r['sup_touch_40']}t) R={r['res_level_40']}({r['res_touch_40']}t)")
            print(f"   90d: S={r['sup_level_90']}({r['sup_touch_90']}t) R={r['res_level_90']}({r['res_touch_90']}t)")
            print(f"   pos40:{r['pos40']}% | ATR ratio:{r['atr_ratio']} | Vol ratio:{r['vol_ratio']}")
            print(f"   MA spread:{r['ma_spread']}% | 5d:{r['c5']:+}% | 10d:{r['c10']:+}% | 20d:{r['c20']:+}%")
            print(f"   Reasons:")
            for re in r["reasons"]:
                print(f"     {re}")
    
    return results


if __name__ == "__main__":
    main()
