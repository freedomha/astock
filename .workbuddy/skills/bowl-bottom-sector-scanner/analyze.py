#!/usr/bin/env python3
"""
A股题材板块碗底形态分析 (增强版 v2)

增强点（相比 v1）:
1. 双窗口趋势减速比 = 近20日跌幅 / 前40日(等效20日)跌幅
   - 减速比 < 0.8 表示跌势明显减速（碗底右沿形成中）
   - 剔除"前期走平+近期破位"的伪碗底
2. 低点抬升检测 = 近10日低点 vs 前10日低点
   - 真碗底应形成抬高的低点（higher low）
3. 二次曲线 U 形拟合 = 对120日收盘价拟合 ax²+bx+c
   - a>0（凸性）+ 谷点位于近期 = U 形碗底
4. 形态分级标签: 🟢确认碗底 / 🟢确认中 / 🟡减速筑底 / 🟡低位盘整 / 🔴下跌中继 / ⚪观望

判定逻辑核心: 真碗底 = ① 区间底部 + ② 前期下跌后近期趋稳(减速) + ③ 低点抬升
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
    """Fetch 250-day K-line for a sector, with retry on transient errors.

    The westock kline endpoint intermittently returns [] (empty) for sector codes;
    retrying almost always succeeds. Returns (code, data) where data is None on final failure.
    """
    for attempt in range(retries):
        data = run_westock("kline", code, "--period", "day", "--limit", str(KLINE_DAYS))
        if data:
            return code, data
        if attempt < retries - 1:
            time.sleep(0.3)
    return code, None


def load_sectors():
    """Load sector codes.

    Concepts come from the skill-local full universe (all_concept_sectors.json, 830 个
    聚源概念板块). 申万一级行业 come from a skill-local sw1_sectors.json if present,
    otherwise fall back to /tmp/sw1_sectors.json (legacy).
    """
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    sectors = []

    # 全市场概念板块（产业/风格/地域）— skill 内置完整清单
    concept_path = os.path.join(skill_dir, "all_concept_sectors.json")
    if os.path.exists(concept_path):
        with open(concept_path) as f:
            for s in json.load(f):
                sectors.append({"code": s["code"], "name": s["name"], "type": s.get("type", "聚源概念")})
    else:
        legacy = "/tmp/concept_sectors.json"
        if os.path.exists(legacy):
            with open(legacy) as f:
                for s in json.load(f):
                    sectors.append({"code": s["code"], "name": s["name"], "type": "聚源产业概念"})

    # 申万一级行业 — skill 本地优先，/tmp 兜底
    sw1_path = os.path.join(skill_dir, "sw1_sectors.json")
    if not os.path.exists(sw1_path):
        sw1_path = "/tmp/sw1_sectors.json"
    if os.path.exists(sw1_path):
        with open(sw1_path) as f:
            for s in json.load(f):
                sectors.append({"code": s["code"], "name": s["name"], "type": "申万一级行业"})
    return sectors


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


def atr(prices, window):
    """Average True Range (simplified, using close-to-close)."""
    s = 0
    for i in range(len(prices) - window, len(prices)):
        if i > 0:
            s += abs(prices[i] - prices[i - 1])
    return s / window if window else 0


def analyze_bowl_bottom(code, name, stype, kline_data):
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
    n250 = min(250, n)
    hi120, lo120 = max(highs[-n120:]), min(lows[-n120:])
    hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
    pos120 = (cur - lo120) / (hi120 - lo120) if hi120 > lo120 else 0.5
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5
    dd120 = (cur - hi120) / hi120 * 100 if hi120 > 0 else 0
    dist_low = (cur - lo120) / lo120 * 100 if lo120 > 0 else 0

    # ---- Trend windows ----
    t20 = lin_slope(closes, 20)
    t60 = lin_slope(closes, 60)
    # Prior window: the 40-day segment ending 20 days ago (days -60..-20)
    if n >= 60:
        seg = closes[-60:-20]
        t_prior = lin_slope(seg, len(seg))
    else:
        t_prior = 0

    # ---- Deceleration ratio ----
    # Normalize both to ~20-day equivalent rate. t_prior is over ~40 days -> divide by 2.
    t20_rate = t20
    t_prior_rate20 = t_prior / 2.0
    if t_prior_rate20 < -1:
        decel_ratio = t20_rate / t_prior_rate20  # <1 = decelerating
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
    atr20 = atr(closes, 20)
    atr60 = atr(closes, 60)
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

    # ============ ENHANCED SCORING (max ~110, clamped 0-100) ============
    score = 0
    reasons = []

    # 1. Bottom zone: 120-day range position (max 25)
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
    if t20 < -8:  # recent crash
        score -= 15
    if dd120 > -5:  # near highs, not a bottom
        score -= 20

    score = max(0, min(100, score))

    # ---- Bowl confirmation label (refined) ----
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
        "code": code, "name": name, "type": stype,
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


def main():
    print("=" * 60)
    print("A股题材板块碗底形态分析 (增强版 v2)")
    print("=" * 60)

    # Step 1: Load sectors
    print("\n📋 加载板块列表...")
    sectors = load_sectors()
    sw1_cnt = sum(1 for s in sectors if s['type'] == '申万一级行业')
    print(f"共加载 {len(sectors)} 个板块 ({sw1_cnt} 申万一级 + {len(sectors)-sw1_cnt} 产业概念)")

    if not sectors:
        print("⚠️ 未找到板块列表。概念板块请从 skill 目录的 all_concept_sectors.json 加载；")
        print("   若缺失，请先枚举：")
        print("   $NODE $WESTOCK sector list concept_list_industry --raw > <skill_dir>/all_concept_sectors.json")
        print("   $NODE $WESTOCK sector list industry_list_sw1 --raw > <skill_dir>/sw1_sectors.json")
        return

    # Step 2: Fetch K-line data in parallel
    print(f"\n📊 并行拉取K线数据 (最多{MAX_WORKERS}并发, 每个{KLINE_DAYS}天)...")
    codes = [s["code"] for s in sectors]
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
                if done % 10 == 0 or done == total:
                    print(f"  进度: {done}/{total}")
            except Exception as e:
                print(f"  {code} 拉取失败: {e}")
                done += 1
    print(f"成功获取 {len(kline_data)}/{total} 个板块K线数据")

    # Re-fetch any sectors that failed (transient empty responses) — 保证全量覆盖
    missing = [c for c in codes if c not in kline_data]
    if missing:
        print(f"\n🔁 补拉 {len(missing)} 个失败板块 (增强重试, 最多6次)...")
        for c in missing:
            _, d = fetch_kline(c, retries=6)
            if d:
                kline_data[c] = d
        still_missing = [c for c in codes if c not in kline_data]
        print(f"补拉后覆盖 {len(kline_data)}/{total} (仍缺失 {len(still_missing)})")
        if still_missing:
            name_map = {s["code"]: s["name"] for s in sectors}
            print("  缺失板块:", ", ".join(f'{name_map.get(c, c)}({c})' for c in still_missing))

    # Save raw kline data
    kline_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sector_kline_data.json")
    kline_file = os.path.normpath(kline_file)
    # Fallback: write alongside results in cwd
    cwd = os.getcwd()
    kline_file = os.path.join(cwd, "sector_kline_data.json")
    with open(kline_file, "w") as f:
        json.dump(kline_data, f, ensure_ascii=False)
    print(f"K线数据已保存: {kline_file}")

    # Step 3: Analyze
    print("\n🔍 分析碗底形态 (增强算法: 减速比+低点抬升+U形拟合)...")
    results = []
    for s in sectors:
        kl = kline_data.get(s["code"])
        if not kl:
            continue
        r = analyze_bowl_bottom(s["code"], s["name"], s["type"], kl)
        if r:
            results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)

    results_file = os.path.join(cwd, "bowl_bottom_results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"分析结果已保存: {results_file}")

    # Step 4: Summary
    confirmed = [r for r in results if r["label"].startswith("🟢")]
    forming = [r for r in results if r["label"].startswith("🟡")]
    crash = [r for r in results if r["label"].startswith("🔴")]
    watch = [r for r in results if r["label"].startswith("⚪")]

    print("\n" + "=" * 60)
    print(f"🏆 碗底形态汇总 (共{len(results)}个板块)")
    print("=" * 60)
    print(f"  🟢 碗底确认/确认中: {len(confirmed)}")
    print(f"  🟡 减速筑底/低位盘整: {len(forming)}")
    print(f"  🔴 下跌中继: {len(crash)}")
    print(f"  ⚪ 观望: {len(watch)}")

    print(f"\n{'排名':<4}{'板块':<12}{'类型':<10}{'得分':<5}{'判定':<14}{'120位%':<8}{'250位%':<8}{'近20日':<8}{'前40日':<8}{'减速':<6}{'抬底':<5}")
    print("-" * 95)
    for i, r in enumerate(results[:20]):
        hl = "是" if r["higher_low"] else "否"
        print(f"{i+1:<4}{r['name']:<12}{r['type']:<10}{r['score']:<5}{r['label']:<14}{r['pos120']:<8}{r['pos250']:<8}{r['t20']:+<8}{r['t_prior']:+<8}{r['decel_ratio']:<6}{hl:<5}")

    # Detailed for confirmed
    if confirmed:
        print("\n" + "=" * 60)
        print("📝 碗底确认题材详细分析")
        print("=" * 60)
        for i, r in enumerate(confirmed):
            print(f"\n{i+1}. {r['name']} ({r['type']}) — {r['label']} 得分:{r['score']}/100")
            print(f"   当前: {r['current']} | 120日位:{r['pos120']}% | 250日位:{r['pos250']}%")
            print(f"   近5日:{r['c5']:+}% | 近10日:{r['c10']:+}% | 近20日:{r['c20']:+}%")
            print(f"   60日趋势:{r['t60']:+}% | 前40日:{r['t_prior']:+}% | 减速比:{r['decel_ratio']}")
            print(f"   低点抬升:{'是' if r['higher_low'] else '否'}({r['hl_pct']:+}%) | U形曲率:{r['curvature']}")
            print(f"   量比:{r['vol_ratio']} | 波幅比:{r['atr_ratio']} | 距60MA:{r['d_ma60']:+}%")
            print(f"   判定依据:")
            for d in r["reasons"]:
                print(f"     {d}")

    return results


if __name__ == "__main__":
    main()
