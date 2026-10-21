#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
季度定投计划 · 周度复评

用法：
  python3 review.py                     # 周度复评（默认）
  python3 review.py --quarter-end       # 季末执行模式：直接给下单指令
  python3 review.py --json              # 额外打印机器可读 JSON
  python3 review.py --save              # 把本次指标追加到 review_history.json
  python3 review.py --mark-executed     # 把本季标记为已执行（成交后跑）
  python3 review.py --state <path>      # 指定状态文件

依赖：westock-data CLI（~/.workbuddy/westock-data）+ 同项目 etf-operation-plan/trend_analysis.py。
Bash 调用需 dangerouslyDisableSandbox: true（网络访问）。

本脚本只做「规则判定」，不给投资建议，也不自动下单。
"""
import argparse
import calendar
import datetime as dt
import glob
import json
import math
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_STATE = os.path.join(HERE, "plan_state.json")
HISTORY = os.path.join(HERE, "review_history.json")
WD = os.path.expanduser("~/.workbuddy/westock-data")
TREND = os.path.join(ROOT, ".workbuddy", "skills", "etf-operation-plan", "trend_analysis.py")

ANN = math.sqrt(252)


# ─────────────────────────── 数据获取 ───────────────────────────
def find_node():
    c = sorted(glob.glob(os.path.expanduser("~/.workbuddy/binaries/node/versions/*/bin/node")))
    return c[-1] if c else "node"


def _run(args, timeout=120, retries=3):
    last = None
    for _ in range(retries):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            d = json.loads(r.stdout)
            return d
        except Exception as e:                                     # noqa: BLE001
            last = e
            time.sleep(1.0)
    sys.stderr.write(f"[warn] fetch failed: {args[-2:]} ({last})\n")
    return None


def fetch_quotes(codes):
    """批量报价 → {code: {price, name, ...}}"""
    d = _run([find_node(), f"{WD}/scripts/index.js", "quote", ",".join(codes), "--raw"])
    out = {}
    if isinstance(d, dict) and "data" in d:
        for it in d["data"] or []:
            if isinstance(it, dict) and "symbol" in it:
                out[it["symbol"]] = it.get("data") or {}
    elif isinstance(d, list):
        for it in d:
            if isinstance(it, dict):
                out[it.get("code") or it.get("symbol")] = it
    return out


def fetch_kline(code, limit=500):
    d = _run([find_node(), f"{WD}/scripts/index.js", "kline", code,
              "--period", "day", "--limit", str(limit), "--raw"])
    if isinstance(d, dict):
        d = d.get("data") or d.get("klines") or []
    if not isinstance(d, list):
        return []
    return sorted(d, key=lambda b: b["date"])          # 统一升序，末位＝最新


def trend_state(code, klines, intraday):
    """调用 etf-operation-plan/trend_analysis.py，返回 (T码, 标签, 关键指标) """
    if not os.path.exists(TREND) or len(klines) < 60:
        return None
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(klines, f)
        cmd = [sys.executable, TREND, "--code", code, "--kline-file", path]
        if intraday:
            cmd.append("--intraday")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        d = json.loads(r.stdout)
        t, m, w = d["trend_state"], d["ma"], d["weekly"]
        sub = t.get("sub_state")
        return dict(
            code=t["code"], eff=(sub or t["code"]), label=t["label"], conf=t["confidence"],
            sub=sub,
            price_vs_ma60=m.get("price_vs_ma60_pct"),
            ma60=m.get("ma60"), ma60_dir=m.get("ma60_dir"),
            weekly_dir=w.get("direction"), weekly_slope=w.get("slope_10w_pct"),
            dd=d.get("drawdown", {}).get("drawdown_from_250d_high_pct"),
            reasons=t.get("reasons") or [],
        )
    except Exception as e:                                          # noqa: BLE001
        sys.stderr.write(f"[warn] trend_state {code} failed: {e}\n")
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ─────────────────────────── 组合计算 ───────────────────────────
def build_cov(codes, klines_by_code, bars):
    """按交易日对齐，返回 (Σ 为 list[list], 实际交易日数, 收益率字典)。纯标准库实现。"""
    maps = {}
    for c in codes:
        maps[c] = {b["date"]: float(b["last"]) for b in klines_by_code.get(c, [])}
    common = None
    for c in codes:
        s = set(maps[c])
        common = s if common is None else (common & s)
    if not common:
        return None, 0, {}
    dates = sorted(common)[-(bars + 1):]
    if len(dates) < 60:
        return None, 0, {}
    rets = {}
    for c in codes:
        v = [maps[c][d] for d in dates]
        rets[c] = [(v[i] / v[i - 1] - 1) for i in range(1, len(v))]
    n = len(codes)
    m = len(rets[codes[0]])
    means = [sum(rets[c]) / m for c in codes]
    S = [[0.0] * n for _ in range(n)]
    for i in range(n):
        ri = rets[codes[i]]
        for j in range(i, n):
            rj = rets[codes[j]]
            s = sum((ri[k] - means[i]) * (rj[k] - means[j]) for k in range(m)) / (m - 1)
            S[i][j] = S[j][i] = s
    return S, m, rets


def matvec(S, w):
    return [sum(S[i][j] * w[j] for j in range(len(w))) for i in range(len(w))]


def metrics(codes, market_values, cash, S):
    tot = sum(market_values) + cash
    w = [v / tot for v in market_values]
    sw = matvec(S, w)
    var = sum(w[i] * sw[i] for i in range(len(w)))
    sd = math.sqrt(var) * ANN * 100
    rc = [(w[i] * sw[i] / var * 100) for i in range(len(w))]
    return dict(tot=tot, weights=w, sd=sd, rc=rc,
                w_pct={c: w[i] * 100 for i, c in enumerate(codes)})


# ─────────────────────────── 季度工具 ───────────────────────────
def quarter_of(d):
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def quarter_end_date(d):
    m = ((d.month - 1) // 3 + 1) * 3
    last = calendar.monthrange(d.year, m)[1]
    e = dt.date(d.year, m, last)
    while e.weekday() >= 5:
        e -= dt.timedelta(days=1)
    return e


def trading_days_between(a, b):
    """粗略（只剔周末，不剔节假日）"""
    n, cur = 0, a
    while cur < b:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def now_is_intraday(now):
    return now.weekday() < 5 and 9 <= now.hour < 15


# ─────────────────────────── 主流程 ───────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=DEFAULT_STATE)
    ap.add_argument("--quarter-end", action="store_true", help="季末执行模式")
    ap.add_argument("--json", action="store_true", help="打印 JSON")
    ap.add_argument("--save", action="store_true", help="追加到 review_history.json")
    ap.add_argument("--mark-executed", action="store_true", help="把本季标记为已执行")
    ap.add_argument("--no-trend", action="store_true", help="跳过趋势状态机（快跑）")
    a = ap.parse_args()

    st = json.load(open(a.state))
    holdings = st["holdings"]
    rules = st["rules"]
    cash = float(st["cash"])
    codes = [h["code"] for h in holdings]
    style_codes = st.get("style_group", [])
    now = dt.datetime.now()
    q = quarter_of(now.date())

    if a.mark_executed:
        st.setdefault("executed", {})[q] = True
        st["as_of"] = now.date().isoformat()
        json.dump(st, open(a.state, "w"), ensure_ascii=False, indent=2)
        print(f"✅ 已把 {q} 标记为已执行。")
        print("⚠️  别忘了同步更新 plan_state.json 里的 holdings[].shares 与 cash，")
        print("    以及 records/etf/*.json 的成交流水。")
        return

    # ── 行情 + K 线
    q_all = fetch_quotes(codes)
    missing = [c for c in codes if c not in q_all]
    if missing:
        print(f"❌ 报价缺失：{missing}，数据源可能限流，请重试。")
        return 1
    prices = {c: float(q_all[c]["price"]) for c in codes}
    names = {c: q_all[c].get("name", c) for c in codes}

    klines = {c: fetch_kline(c, max(rules["cov_window_bars"], 250) + 10) for c in codes}
    empty = [c for c in codes if len(klines[c]) < 60]
    if empty:
        print(f"❌ K 线不足：{empty}")
        return 1

    # ── 协方差（双窗口）
    S2, n2, _ = build_cov(codes, klines, rules["cov_window_bars"])
    S1, n1, _ = build_cov(codes, klines, rules["cov_window_short_bars"])
    mv = [holdings[i]["shares"] * prices[holdings[i]["code"]] for i in range(len(codes))]
    m2 = metrics(codes, mv, cash, S2)
    m1 = metrics(codes, mv, cash, S1)
    idx = {c: i for i, c in enumerate(codes)}
    style_rc2 = sum(m2["rc"][idx[c]] for c in style_codes if c in idx)
    style_rc1 = sum(m1["rc"][idx[c]] for c in style_codes if c in idx)
    rc50 = m2["rc"][0]
    rc50_abs = rc50 / 100 * m2["sd"]

    # ── 趋势状态
    states = {}
    if not a.no_trend:
        intraday = now_is_intraday(now)
        for c in codes:
            states[c] = trend_state(c, klines[c], intraday)

    # ── 状态变化（与上次运行对比）
    prev = st.get("last_states") or {}
    changes = []
    for c in codes:
        s_ = states.get(c)
        if not s_:
            continue
        cur_eff = s_["eff"]
        old_eff = prev.get(c)
        if old_eff and old_eff != cur_eff:
            up = (old_eff not in rules["gate_states"] and cur_eff in rules["gate_states"])
            down = (old_eff in rules["gate_states"] and cur_eff not in rules["gate_states"])
            changes.append(dict(code=c, name=names[c], old=old_eff, new=cur_eff,
                                dir="up" if up else ("down" if down else "flat")))

    # ── 峰值 / 回撤
    peak = st.get("peak_value") or m2["tot"]
    peak = max(peak, m2["tot"])
    dd = (m2["tot"] / peak - 1) * 100 if peak else 0.0

    # ── 缺口与候选
    rows = []
    for h in holdings:
        c = h["code"]
        w = m2["w_pct"][c]
        tgt = h["target_pct"]
        gap_pp = tgt - w
        gap_amt = tgt / 100 * m2["tot"] - h["shares"] * prices[c]
        s = states.get(c)
        gate = bool(s and s["eff"] in rules["gate_states"])
        blocked = []
        if h.get("locked"):
            blocked = ["锁定不买"]
        elif not gate:
            blocked.append("状态门")
        if not h.get("locked") and c in style_codes and max(style_rc2, style_rc1) > rules["style_group_limit_pct"]:
            blocked.append("风格组>%.0f%%" % rules["style_group_limit_pct"])
        if not h.get("locked") and gap_amt <= 0:
            blocked.append("已达标")
        rows.append(dict(code=c, name=names[c], px=prices[c], w=w, tgt=tgt,
                         gap_pp=gap_pp, gap_amt=gap_amt, state=s,
                         eligible=len(blocked) == 0, blocked=blocked,
                         shares=h["shares"]))

    # ── 本季下单建议
    cand = [r for r in rows if r["eligible"] and r["gap_amt"] > 0]
    action = None
    if cand:
        pick = max(cand, key=lambda r: r["gap_amt"])
        amt = min(rules["max_trade"], pick["gap_amt"])
        shares = int(amt // (pick["px"] * rules["lot_size"])) * rules["lot_size"]
        cost = shares * pick["px"]
        if cost >= rules["min_trade"]:
            action = dict(code=pick["code"], name=pick["name"], px=pick["px"],
                          shares=shares, cost=cost, gap=pick["gap_amt"], blocked=[])
        else:
            action = dict(code=None, reason=f"{pick['name']} 缺口 {pick['gap_amt']:.0f} 元 < 最小交易额 "
                                            f"{rules['min_trade']} 元 → 留现金")

    # ── 触发检查
    trig = []
    if dd <= -rules["drawdown_alert_pct"]:
        trig.append(("🔴 组合回撤", f"{dd:.1f}% ≤ -{rules['drawdown_alert_pct']:.0f}%",
                     "暂停全部定投，预备队不动，全面复核"))
    if max(style_rc2, style_rc1) > rules["style_group_limit_pct"]:
        trig.append(("🟠 风格组超限",
                     f"2年 {style_rc2:.1f}% / 1年 {style_rc1:.1f}% > {rules['style_group_limit_pct']:.0f}%",
                     "禁买红利类（低相关腿不受限）"))
    for ch in changes:
        r = next((x for x in rows if x["code"] == ch["code"]), None)
        if ch["dir"] == "up" and ch["new"] in rules["reserve_fill_states"]:
            trig.append(("🟢 状态恢复", f"{ch['name']} {ch['old']} → {ch['new']}",
                         f"预备队可一次性补足缺口约 {r['gap_amt']:,.0f} 元" if r else "可评估补仓"))
        elif ch["dir"] == "down" and ch["old"] in rules["gate_states"]:
            trig.append(("🟠 状态转弱", f"{ch['name']} {ch['old']} → {ch['new']}",
                         "当季改投次优合格标的；无则留现金"))

    # ── 输出
    qe = quarter_end_date(now.date())
    left = trading_days_between(now.date(), qe)
    done = st.get("executed", {}).get(q, False)
    intraday = now_is_intraday(now)
    bar_date = klines[codes[0]][-1]["date"] if klines[codes[0]] else "?"

    W = 74
    print("═" * W)
    print(f" 季度定投计划 · {'季末执行' if a.quarter_end else '周度复评'}")
    if a.no_trend:
        print(" ⚠ 已跳过趋势状态机（--no-trend）：所有标的视为状态门不通过")
    print(f" {now:%Y-%m-%d %H:%M} | 最新 K 线 {bar_date}{'（盘中未定稿）' if intraday else '（收盘）'}")
    print("═" * W)

    pos_pct = (1 - cash / m2["tot"]) * 100
    print(f"\n【组合】总资产 {m2['tot']:,.0f} | 仓位 {pos_pct:.1f}% | 现金 {cash:,.0f} ({cash / m2['tot'] * 100:.1f}%)")
    print(f"【风险】σp {m2['sd']:.2f}% | RC50 占比 {rc50:.1f}% | 绝对贡献 {rc50_abs:.2f}%")
    print(f"       风格组 {style_rc2:.1f}%（2年）/ {style_rc1:.1f}%（1年）"
          f" | 回撤 {dd:+.1f}%（峰值 {peak:,.0f}）")

    print(f"\n【标的】")
    hdr = f"  {'代码':10}{'名称':16}{'现价':>8}{'权重':>8}{'目标':>7}{'缺口':>12}  {'状态':<14}"
    print(hdr)
    print("  " + "─" * (W - 4))
    for r in rows:
        s = r["state"]
        stxt = f"{s['eff']} {s['label'][:6]}" if s else "—"
        if r["eligible"]:
            mark = "可买"
        else:
            mark = "/".join(r["blocked"])[:14]
        print(f"  {r['code']:10}{r['name'][:14]:16}{r['px']:>8.3f}{r['w']:>7.1f}%{r['tgt']:>6.1f}%"
              f"{r['gap_pp']:>+7.1f}pp{r['gap_amt']:>+9,.0f}  {stxt:<14} {mark}")

    print(f"\n【本季 {q}】已执行：{'是' if done else '否'} | 距季末约 {left} 个交易日（{qe}）")
    if action:
        if action.get("code"):
            print(f"  若此刻执行：买 {action['name']} {action['shares']:,} 份 × {action['px']:.3f}"
                  f" = {action['cost']:,.2f} 元（缺口 {action['gap']:,.0f}）")
            if action["code"] == "sh513100":
                print("  ⚠ QDII：下单前查溢价，>1.5% 换 sz159941 / sz159632 / sh513110 中最低者；")
                print("     4 只全超 1.5% 则当季留现金。")
        else:
            print(f"  {action['reason']}")
    else:
        print("  无合格标的 → 留现金")

    if changes:
        print(f"\n【状态变化】较上次运行")
        for ch in changes:
            icon = {"up": "🔺", "down": "🔻", "flat": "▫"}[ch["dir"]]
            print(f"  {icon} {ch['name']}：{ch['old']} → {ch['new']}")
    elif prev:
        print(f"\n【状态变化】无（与上次一致）")

    print(f"\n【触发】")
    if trig:
        for t, cond, act in trig:
            print(f"  {t}：{cond}")
            print(f"     → {act}")
    else:
        print("  ✓ 无触发")

    print(f"\n【结论】")
    if dd <= -rules["drawdown_alert_pct"]:
        print("  暂停定投，复核组合。")
    elif a.quarter_end and not done:
        print("  季末执行窗口：按上方指令下单，成交后跑 --mark-executed 并更新 shares/cash。")
    elif done:
        print(f"  本季（{q}）已执行，本周仅监控，无需动作。")
    else:
        print("  本周无需动作；等季末（%s）再执行。" % qe)
    print("═" * W)

    # ── 存档
    snap = dict(date=now.date().isoformat(), quarter=q, bar_date=bar_date,
                total=m2["tot"], cash=cash, cash_pct=cash / m2["tot"] * 100,
                sd=m2["sd"], rc50=rc50, rc50_abs=rc50_abs,
                style2=style_rc2, style1=style_rc1, drawdown=dd, peak=peak,
                states={c: (states[c]["eff"] if states.get(c) else None) for c in codes},
                action=action, triggers=[t[0] for t in trig], executed=done,
                changes=changes)

    if a.save:
        hist = []
        if os.path.exists(HISTORY):
            try:
                hist = json.load(open(HISTORY))
            except json.JSONDecodeError:
                hist = []
        hist = [h for h in hist if h.get("date") != snap["date"]] + [snap]
        json.dump(hist, open(HISTORY, "w"), ensure_ascii=False, indent=2)
        print(f"\n已追加 {HISTORY}（共 {len(hist)} 条）")

    st["peak_value"] = peak
    if states:
        st["last_states"] = {c: states[c]["eff"] for c in codes if states.get(c)}
    st["last_run"] = now.isoformat(timespec="seconds")
    json.dump(st, open(a.state, "w"), ensure_ascii=False, indent=2)

    if a.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
