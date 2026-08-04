#!/usr/bin/env python3
"""
A股ETF 2B底部形态检测与评分引擎 (v1)

2B规则 (Victor Sperandeo):
价格跌破前60日低点后,在2个交易日内收盘回升至该低点之上
→ 假突破信号,表明做空动能衰竭,趋势可能反转

检测逻辑:
1. 找前60日最低收盘价 (bars[2..61])
2. 检查 bars 0-2 是否有低点跌破该底线
3. 检查跌破后2个交易日内是否收盘回升至该底线之上

评分引擎: 7维度 (max 100)
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
            "size": e.get("size"),
        })
    return etfs


def parse_kline(kline_data):
    """
    Parse raw kline data from westock-data.
    
    Input: list of {date, first, last, high, low, volume} newest-first
    Output: list of {date, open, close, high, low, volume} sorted oldest-first
    Returns None if not enough data.
    """
    if not kline_data or len(kline_data) < 80:
        return None
    
    records = []
    for k in kline_data:
        try:
            records.append({
                "date": k["date"],
                "open": float(k["first"]),
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
    return records


def detect_2b_bottom(records):
    """
    Detect a 2B bottom reversal pattern.
    
    Algorithm:
    1. Find prior 60-day low: lowest close in records[n-2-60 : n-2]
    2. Check breakdown on bars n-1, n-2, n-3: any low < prior_low_price?
    3. Check recovery within 2 bars after breakdown: close > prior_low_price?
    
    Returns (breakdown_bar_index, recovery_bar_index, prior_low_price, prior_low_bar_index)
    or None if no detection.
    
    Bar numbering (reverse from end):
      records[n-1] = bar 0 (newest)
      records[n-2] = bar 1
      records[n-3] = bar 2
      ...
      records[n-2-60] ... records[n-3] = prior 60-day window
    """
    n = len(records)
    if n < 63:
        return None
    
    # Step 1: Find prior 60-day low (bars 2..61 in reverse, i.e. n-2-60 to n-3)
    prior_start = n - 2 - 60  # index n-62
    prior_end = n - 2         # exclusive: n-2
    
    if prior_start < 0:
        prior_start = 0
    
    prior_window = records[prior_start:prior_end]
    if len(prior_window) < 30:
        return None
    
    prior_low_price = min(r["close"] for r in prior_window)
    # Find the actual index of the prior low in the original records
    prior_low_bar = None
    for i in range(prior_start, prior_end):
        if records[i]["close"] == prior_low_price:
            prior_low_bar = i
            break
    
    if prior_low_bar is None:
        return None
    
    # Step 2: Check breakdown on bars 0, 1, 2 (newest, 1d ago, 2d ago)
    # Check bars: n-1 (bar 0), n-2 (bar 1), n-3 (bar 2)
    breakdown_bars = [n - 1, n - 2, n - 3]
    breakdown_bar = None
    
    for bar_idx in breakdown_bars:
        if bar_idx < 0:
            continue
        if records[bar_idx]["low"] < prior_low_price:
            breakdown_bar = bar_idx
            break
    
    if breakdown_bar is None:
        return None
    
    # Step 3: Check recovery within 2 bars after breakdown
    # recovery can be same bar (bar_idx), bar+1, bar+2
    recovery_bar = None
    for offset in range(3):  # 0, 1, 2
        check_idx = breakdown_bar + offset
        if check_idx >= n:
            break
        if records[check_idx]["close"] > prior_low_price:
            recovery_bar = check_idx
            break
    
    if recovery_bar is None:
        return None
    
    return (breakdown_bar, recovery_bar, prior_low_price, prior_low_bar)


def score_2b(records, breakdown_bar, recovery_bar, prior_low_price, prior_low_bar):
    """
    Score the 2B bottom pattern on 7 dimensions (max 100).
    
    Returns dict with score, label, and detailed metrics.
    """
    n = len(records)
    closes = [r["close"] for r in records]
    highs = [r["high"] for r in records]
    lows = [r["low"] for r in records]
    vols = [r["volume"] for r in records]
    cur = closes[-1]
    
    # ---- Dimension 1: Break depth (max 20) ----
    breakdown_low = records[breakdown_bar]["low"]
    break_depth_pct = (prior_low_price - breakdown_low) / prior_low_price * 100
    
    if break_depth_pct < 1:
        score_d1 = 20
    elif break_depth_pct <= 3:
        score_d1 = 15
    elif break_depth_pct <= 5:
        score_d1 = 8
    else:
        score_d1 = 0
    
    # ---- Dimension 2: Recovery strength (max 20) ----
    recovery_close = records[recovery_bar]["close"]
    recovery_pct = (recovery_close - prior_low_price) / prior_low_price * 100
    
    if recovery_pct >= 1.5:
        score_d2 = 20
    elif recovery_pct >= 0.5:
        score_d2 = 15
    elif recovery_pct >= 0:
        score_d2 = 10
    else:
        score_d2 = 0
    
    # ---- Dimension 3: Volume contraction (max 15) ----
    if n >= 60:
        vol_breakdown = records[breakdown_bar]["volume"]
        vol_avg60 = sum(vols[-60:]) / 60
        vol_ratio = vol_breakdown / vol_avg60 if vol_avg60 > 0 else 1
    else:
        vol_ratio = 1
    
    if vol_ratio < 0.8:
        score_d3 = 15
    elif vol_ratio <= 1.0:
        score_d3 = 10
    else:
        score_d3 = 5
    
    # ---- Dimension 4: Prior low quality (max 15) ----
    # Check if prior_low is the lowest close in ±10 bars around it
    check_start = max(0, prior_low_bar - 10)
    check_end = min(n, prior_low_bar + 11)
    nearby_closes = closes[check_start:check_end]
    nearby_low_rank = sum(1 for c in nearby_closes if c < prior_low_price)
    
    window_size = check_end - check_start
    if nearby_low_rank == 0 and window_size >= 15:
        score_d4 = 15  # distinct swing low
    elif nearby_low_rank <= 1:
        score_d4 = 10  # reasonable
    else:
        score_d4 = 5   # minor
    
    # ---- Dimension 5: Trend context (max 15) ----
    # Decline in 20 bars before the prior low
    decline_start = max(0, prior_low_bar - 20)
    if prior_low_bar - decline_start >= 5:
        first_close = closes[decline_start]
        last_close = closes[prior_low_bar]
        if first_close > 0:
            prior_decline = (first_close - last_close) / first_close * 100
        else:
            prior_decline = 0
    else:
        prior_decline = 0
    
    if prior_decline > 8:
        score_d5 = 15
    elif prior_decline > 5:
        score_d5 = 10
    elif prior_decline > 3:
        score_d5 = 5
    else:
        score_d5 = 0
    
    # ---- Dimension 6: Recovery speed (max 10) ----
    lag = recovery_bar - breakdown_bar
    if lag == 0:
        score_d6 = 10  # same-day
    elif lag == 1:
        score_d6 = 7   # 1d lag
    elif lag == 2:
        score_d6 = 5   # 2d lag
    else:
        score_d6 = 0
    
    # ---- Dimension 7: Distance from 60MA (max 5) ----
    if n >= 60:
        ma60 = sum(closes[-60:]) / 60
        d_ma60 = (cur - ma60) / ma60 * 100
    else:
        ma60 = sum(closes) / n
        d_ma60 = (cur - ma60) / ma60 * 100
    
    if -15 <= d_ma60 <= -2:
        score_d7 = 5
    else:
        score_d7 = 0
    
    # ---- Penalties ----
    penalties = 0
    penalty_reasons = []
    
    # Penalty: High volume breakdown (>120% of 60d avg)
    if vol_ratio > 1.2:
        penalties += 10
        penalty_reasons.append(f"放量跌破(量比{vol_ratio:.0%}) -10pt")
    
    # Penalty: Prior low too recent (<5 bars before breakdown)
    bars_since_prior_low = breakdown_bar - prior_low_bar
    if bars_since_prior_low < 5:
        penalties += 5
        penalty_reasons.append(f"前低过近({bars_since_prior_low}bars) -5pt")
    
    # ---- Total score ----
    score = score_d1 + score_d2 + score_d3 + score_d4 + score_d5 + score_d6 + score_d7 - penalties
    score = max(0, min(100, score))
    
    # ---- Label ----
    if score >= 80:
        label = "🟢 2B买入确认"
    elif score >= 65:
        label = "🟢 2B买入候选"
    elif score >= 50:
        label = "🟡 2B观察"
    else:
        label = "⚪ 无2B信号"
    
    # ---- Reasons ----
    reasons = []
    reasons.append(f"跌破深度: {break_depth_pct:.1f}% ({score_d1}/20)")
    reasons.append(f"回升力度: {recovery_pct:+.1f}% ({score_d2}/20)")
    reasons.append(f"量能对比: {vol_ratio:.0%} ({score_d3}/15)")
    
    if score_d4 == 15:
        reasons.append(f"前低质量: 独立摆动低点 ({score_d4}/15)")
    elif score_d4 == 10:
        reasons.append(f"前低质量: 次低点 ({score_d4}/15)")
    else:
        reasons.append(f"前低质量: 次要低点 ({score_d4}/15)")
    
    reasons.append(f"前期跌幅: {prior_decline:.1f}% ({score_d5}/15)")
    reasons.append(f"回升速度: {lag}天 ({score_d6}/10)")
    
    if score_d7 == 5:
        reasons.append(f"距60MA: {d_ma60:+.1f}% ({score_d7}/5)")
    else:
        reasons.append(f"距60MA: {d_ma60:+.1f}% (不达标 {score_d7}/5)")
    
    for pr in penalty_reasons:
        reasons.append(f"⚠️ {pr}")
    
    return {
        "score": score,
        "label": label,
        "current": round(cur, 2),
        "breakdown_bar": breakdown_bar,
        "recovery_bar": recovery_bar,
        "prior_low_price": round(prior_low_price, 2),
        "prior_low_bar": prior_low_bar,
        "break_pct": round(break_depth_pct, 2),
        "recovery_pct": round(recovery_pct, 2),
        "vol_ratio": round(vol_ratio, 2),
        "prior_decline": round(prior_decline, 1),
        "lag_bars": lag,
        "d_ma60": round(d_ma60, 1),
        "d1": score_d1, "d2": score_d2, "d3": score_d3,
        "d4": score_d4, "d5": score_d5, "d6": score_d6, "d7": score_d7,
        "penalties": penalties,
        "breakdown_date": records[breakdown_bar]["date"],
        "recovery_date": records[recovery_bar]["date"],
        "prior_low_date": records[prior_low_bar]["date"],
        "reasons": reasons,
    }


def analyze_2b(code, name, etype, kline_data):
    """
    Analyze a single ETF for 2B bottom detection.
    
    Returns scored result dict or None if no valid data/pattern.
    """
    if not kline_data:
        return None
    
    records = parse_kline(kline_data)
    if not records:
        return None
    
    detected = detect_2b_bottom(records)
    if detected is None:
        return None
    
    breakdown_bar, recovery_bar, prior_low_price, prior_low_bar = detected
    
    result = score_2b(records, breakdown_bar, recovery_bar, prior_low_price, prior_low_bar)
    result["code"] = code
    result["name"] = name
    result["type"] = etype
    
    return result


def main():
    print("=" * 60)
    print("A股ETF 2B底部形态检测 (v1)")
    print("=" * 60)
    
    # Step 1: Load ETFs
    print("\n📋 加载ETF列表...")
    etfs = load_etfs()
    if not etfs:
        print("⚠️ ETF列表未找到。请确保 all_etfs_larggest.json 存在于项目根目录。")
        return
    print(f"共加载 {len(etfs)} 只ETF")
    
    # Step 2: Load or fetch K-line data (shared project-root file)
    kline_file = os.path.join(os.getcwd(), "etf_kline_data.json")
    if os.path.exists(kline_file):
        print(f"\n📊 加载共享K线数据: {kline_file}")
        with open(kline_file) as f:
            kline_data = json.load(f)
        print(f"已加载 {len(kline_data)} 只ETF K线数据")
    else:
        print(f"\n📊 并行拉取K线数据 (最多{MAX_WORKERS}并发, 每只{KLINE_DAYS}天)...")
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
            print(f"\n🔁 补拉 {len(missing)} 个失败ETF (增强重试, 最多6次)...")
            for c in missing:
                _, d = fetch_kline(c, retries=6)
                if d:
                    kline_data[c] = d
            still_missing = [c for c in codes if c not in kline_data]
            print(f"补拉后覆盖 {len(kline_data)}/{total} (仍缺失 {len(still_missing)})")
            if still_missing:
                name_map = {e["code"]: e["name"] for e in etfs}
                print("  缺失ETF:", ", ".join(f'{name_map.get(c, c)}({c})' for c in still_missing[:10]))
                if len(still_missing) > 10:
                    print(f"  ... 还有 {len(still_missing) - 10} 个")

        # Save to shared project root file
        with open(kline_file, "w") as f:
            json.dump(kline_data, f, ensure_ascii=False)
        print(f"K线数据已保存: {kline_file}")
    
    # Step 3: Analyze 2B patterns
    print("\n🔍 检测2B底部形态...")
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results = []
    for e in etfs:
        kl = kline_data.get(e["code"])
        if not kl:
            continue
        r = analyze_2b(e["code"], e["name"], e["type"], kl)
        if r:
            results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)
    
    # Save results to skill directory
    results_file = os.path.join(skill_dir, "etf_2b_bottom_results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"分析结果已保存: {results_file}")
    
    # Step 4: Summary
    confirmed = [r for r in results if r["label"] == "🟢 2B买入确认"]
    candidate = [r for r in results if r["label"] == "🟢 2B买入候选"]
    watch = [r for r in results if r["label"] == "🟡 2B观察"]
    no_signal = [r for r in results if r["label"] == "⚪ 无2B信号"]
    
    print("\n" + "=" * 60)
    print(f"🏆 2B底部检测汇总 (共{len(results)}只ETF检测到2B信号)")
    print("=" * 60)
    print(f"  🟢 2B买入确认 (≥80): {len(confirmed)}")
    print(f"  🟢 2B买入候选 (65-79): {len(candidate)}")
    print(f"  🟡 2B观察 (50-64): {len(watch)}")
    print(f"  ⚪ 无2B信号 (<50): {len(no_signal)}")
    
    # No signals at all
    total_etfs = len(etfs)
    no_detect = total_etfs - len(results)
    print(f"  未检测到2B形态: {no_detect}/{total_etfs}")
    
    # Top results table
    top_n = min(25, len(results))
    if top_n > 0:
        print(f"\n{'排名':<4}{'ETF名称':<22}{'得分':<5}{'判定':<14}{'破位日':<12}{'回升日':<12}{'破深%':<7}{'回升%':<7}{'量比':<6}{'前跌%':<7}{'滞后':<4}")
        print("-" * 120)
        for i, r in enumerate(results[:top_n]):
            print(f"{i+1:<4}{r['name']:<22}{r['score']:<5}{r['label']:<14}{r['breakdown_date']:<12}{r['recovery_date']:<12}{r['break_pct']:<7}{r['recovery_pct']:<7}{r['vol_ratio']:<6.0%}{r['prior_decline']:<7}{r['lag_bars']:<4}")
    
    # Detailed for confirmed
    if confirmed:
        print("\n" + "=" * 60)
        print("📝 2B买入确认ETF详细分析")
        print("=" * 60)
        for i, r in enumerate(confirmed):
            print(f"\n{i+1}. {r['name']} — {r['label']} 得分:{r['score']}/100")
            print(f"   当前价: {r['current']} | 前低:{r['prior_low_price']} ({r['prior_low_date']})")
            print(f"   破位: {r['breakdown_date']}(深{r['break_pct']}%) | 回升: {r['recovery_date']}(+{r['recovery_pct']:.1f}%)")
            print(f"   滞后: {r['lag_bars']}天 | 前期跌幅: {r['prior_decline']}% | 量比: {r['vol_ratio']:.0%} | 距60MA: {r['d_ma60']:+.1f}%")
            print(f"   评分详情: D1(破深)={r['d1']} D2(回升)={r['d2']} D3(量)={r['d3']} D4(前低质)={r['d4']} D5(前跌)={r['d5']} D6(速度)={r['d6']} D7(60MA)={r['d7']} 惩罚={r['penalties']}")
            for reason in r["reasons"]:
                print(f"     {reason}")
    
    return results


if __name__ == "__main__":
    main()
