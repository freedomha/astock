#!/usr/bin/env python3
"""
A股ETF W底形态分析 (v1)

W底判定逻辑 (5阶段流水线):
Phase 1: 前期下跌 — T-120到T-40，40日斜率≤-0.005%/日
Phase 2-3: 左底→峰顶 — 左底到峰顶反弹≥8%
Phase 4: 右底验证 — 右底在±10%内，量能≤1.2x
Phase 5: 突破状态 — 2/3日收于峰顶之上=确认

8维度评分引擎(0-100)，4级标签
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
        })
    return etfs


def lin_slope(arr, win):
    """Linear regression slope over last `win` points, % per day return."""
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
    print("A股ETF W底形态分析 (v1)")
    if refresh_today:
        print("🔄 盘中刷新模式: 同日期数据将用最新数据替换 (默认开启, --no-refresh 关闭)")
    print("=" * 60)

    # Step 1: Load ETFs
    print("\n[1/3] 加载ETF列表...")
    etfs = load_etfs()
    if not etfs:
        print("未找到ETF列表。请确保 all_etfs_larggest.json 存在于项目根目录。")
        return
    print(f"共加载 {len(etfs)} 只ETF")

    # Step 2: Load or fetch K-line data (shared project-root file)
    cwd = os.getcwd()
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    if os.path.exists(kline_file):
        print(f"\n[2/3] 加载共享K线数据: {kline_file}")
        with open(kline_file) as f:
            kline_data = json.load(f)
        print(f"已加载 {len(kline_data)} 只ETF K线数据")

        # Append latest data if available
        updated = update_kline_data(kline_data, etfs, kline_file, refresh_today)
        if updated > 0:
            print(f"已追加 {updated} 只ETF的最新记录")
        else:
            print("K线数据已是最新，无需更新")
    else:
        print(f"\n[2/3] 并行拉取K线数据 (最多{MAX_WORKERS}并发, 每个{KLINE_DAYS}天)...")
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
                        print(f"  进度: {done}/{total}")
                except Exception as e:
                    print(f"  {code} 拉取失败: {e}")
                    done += 1
        print(f"成功获取 {len(kline_data)}/{total} 只ETF K线数据")

        # Re-fetch any ETFs that failed
        missing = [c for c in codes if c not in kline_data]
        if missing:
            print(f"\n  补拉 {len(missing)} 只失败ETF (增强重试, 最多6次)...")
            for c in missing:
                _, d = fetch_kline(c, retries=6)
                if d:
                    kline_data[c] = d
            still_missing = [c for c in codes if c not in kline_data]
            print(f"  补拉后覆盖 {len(kline_data)}/{total} (仍缺失 {len(still_missing)})")
            if still_missing:
                name_map = {e["code"]: e["name"] for e in etfs}
                print("  缺失ETF:", ", ".join(f'{name_map.get(c, c)}({c})' for c in still_missing))

        # Save to shared project root file
        with open(kline_file, "w") as f:
            json.dump(kline_data, f, ensure_ascii=False)
        print(f"K线数据已保存: {kline_file}")

    # Step 3: Analyze
    print("\n[3/3] 检测W底形态 (5阶段流水线 + 8维评分)...")
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results = []
    for e in etfs:
        kl = kline_data.get(e["code"])
        if not kl:
            continue
        r = analyze_w_bottom(e["code"], e["name"], e["type"], kl)
        if r:
            results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)

    results_file = os.path.join(skill_dir, "etf_w_bottom_results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"分析结果已保存: {results_file}")

    # Summary
    confirmed = [r for r in results if "确认" in r["label"]]
    forming = [r for r in results if "形成中" in r["label"]]
    candidate = [r for r in results if "候选" in r["label"]]

    print("\n" + "=" * 60)
    print(f"W底形态汇总 (共{len(results)}只ETF检测到信号)")
    print("=" * 60)
    print(f"  W底确认: {len(confirmed)}")
    print(f"  W底形成中: {len(forming)}")
    print(f"  W底候选: {len(candidate)}")

    if results:
        print(f"\n{'排名':<4}{'ETF':<18}{'得分':<5}{'判定':<10}{'状态':<6}{'反弹%':<8}{'双底差%':<8}{'量比':<6}")
        print("-" * 75)
        for i, r in enumerate(results[:15]):
            print(f"{i + 1:<4}{r['name']:<18}{r['score']:<5}{r['label']:<10}{r['status']:<6}{r['recovery_pct']:<8.1f}{r['trough_diff_pct']:<8.1f}{r['vol_ratio']:<6.2f}")

    return results


if __name__ == "__main__":
    main()
