#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
季度定投计划 · 周度复评

用法：
  python3 review.py                     # 周度复评（默认，V1 连续评分）
  python3 review.py --quarter-end       # 季末执行模式：直接给下单指令
  python3 review.py --legacy-gate       # 回退到 T0-T8 状态门（对照/回滚）
  python3 review.py --json              # 额外打印机器可读 JSON
  python3 review.py --save              # 把本次指标追加到 review_history.json
  python3 review.py --mark-executed     # 把本季标记为已执行（成交后跑）
  python3 review.py --state <path>      # 指定状态文件

判定架构（冻结规格见 V1-SPEC.md / v1_spec.json）：
  硬门（溢价 / 回撤 / 风格组 / 数据质量 / 最小交易额）→ 不参与评分，违反即不买
  软分（Trend 30 / Momentum 30 / Risk 20 / Diversification 20）→ 只负责排序
  阈值（绝对下限 60 + 相对带 5）→ 唯一能产生「本季不买」的开关
  T0-T8 仅作描述性特征，不再决定买不买。

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

sys.path.insert(0, HERE)
import v1_score                                                        # noqa: E402

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


def fetch_premium(code):
    """通过 etf detail 取 收盘价/净值/申购状态 → 溢价率。QDII 溢价是硬门，必须查。"""
    d = _run([find_node(), f"{WD}/scripts/index.js", "etf", "detail", code, "--raw"])
    try:
        s = d["sections"][0][0]
        px, nav = s.get("closePrice"), s.get("nav")
        prem = (px / nav - 1) * 100 if px and nav else None
        return dict(px=px, nav=nav, prem=prem,
                    purchase=s.get("purchaseStatus"), etf_type=s.get("etfType"), date=s.get("date"))
    except (KeyError, IndexError, TypeError):
        return None


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
def proxy_returns(proxy_code, dates):
    """底层指数 lag1 收益：对每个 A 股交易日 d，取「d 之前最近两个美股交易日」的收益。
    理由：美股收盘早于 A 股开盘，同日对齐会把"未来"信息塞进当期，压低相关性。"""
    kl = fetch_kline(proxy_code, 600)
    if len(kl) < 60:
        return None
    m = {b["date"]: float(b["last"]) for b in kl}
    ds = sorted(m)
    r = {ds[i]: m[ds[i]] / m[ds[i - 1]] - 1 for i in range(1, len(ds))}
    out, last = [], None
    for d in dates:                      # dates 为升序的 A 股交易日（含首日）
        cand = [x for x in ds if x < d]
        if len(cand) >= 2:
            last = r.get(cand[-1], last)
        out.append(last)
    return out


def build_cov(codes, klines_by_code, bars, proxy_map=None):
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
    proxy_map = proxy_map or {}
    for c in codes:
        if c in proxy_map:
            px = proxy_returns(proxy_map[c], dates)
            if px and all(x is not None for x in px[1:]):
                rets[c] = [x for x in px[1:]]
                continue
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


def delta_rc50(codes, mv, cash, S, i, amount=1000.0):
    """从现金挪 amount 到 codes[i]，RC50（上证50 风险占比）的变化，pp。负值=改善。

    这是 Diversification 分的唯一输入——它直接对齐「每千元降多少集中度」，
    而不是 1−ρ 这种间接代理。
    """
    if cash < amount or S is None:
        return None
    base = metrics(codes, mv, cash, S)
    mv2 = list(mv)
    mv2[i] += amount
    after = metrics(codes, mv2, cash - amount, S)
    return after["rc"][0] - base["rc"][0]


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
    ap.add_argument("--legacy-gate", action="store_true",
                    help="回退到 T0-T8 状态门（对照/回滚）；默认用 V1 连续评分")
    a = ap.parse_args()

    st = json.load(open(a.state))
    holdings = st["holdings"]
    rules = st["rules"]
    legacy = bool(a.legacy_gate or rules.get("gate_mode") == "legacy")
    a.legacy_gate = legacy
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
    prem_codes = codes + [c for c in rules.get("fallback_nasdaq", []) if c not in codes]
    prem = {c: fetch_premium(c) for c in prem_codes}
    # 估值价格统一用 etf detail 的官方收盘价（与净值同日），取不到才退回实时报价
    for c in codes:
        px = (prem.get(c) or {}).get("px")
        if px:
            prices[c] = float(px)

    klines = {c: fetch_kline(c, max(rules["cov_window_bars"], 250) + 10) for c in codes}
    empty = [c for c in codes if len(klines[c]) < 60]
    if empty:
        print(f"❌ K 线不足：{empty}")
        return 1

    # ── 协方差（双窗口）
    pmap = rules.get("qdii_proxy") or {}
    S2, n2, _ = build_cov(codes, klines, rules["cov_window_bars"], pmap)
    S1, n1, _ = build_cov(codes, klines, rules["cov_window_short_bars"], pmap)
    mv = [holdings[i]["shares"] * prices[holdings[i]["code"]] for i in range(len(codes))]
    m2 = metrics(codes, mv, cash, S2)
    m1 = metrics(codes, mv, cash, S1)
    idx = {c: i for i, c in enumerate(codes)}
    style_rc2 = sum(m2["rc"][idx[c]] for c in style_codes if c in idx)
    style_rc1 = sum(m1["rc"][idx[c]] for c in style_codes if c in idx)
    rc50 = m2["rc"][0]
    rc50_abs = rc50 / 100 * m2["sd"]

    # ── V1 连续评分（Trend / Momentum / Risk / Diversification）
    spec = v1_score.load_spec()
    scores = {}
    for c in codes:
        cl = [float(b["last"]) for b in (klines.get(c) or [])]
        if len(cl) < 121:
            scores[c] = None
            continue
        drc = delta_rc50(codes, mv, cash, S2, idx[c])
        scores[c] = v1_score.score(cl, len(cl) - 1, drc, spec)

    # ── 趋势状态
    states = {}
    if not a.no_trend:
        intraday = now_is_intraday(now)
        sprox = rules.get("state_proxy") or {}
        for c in codes:
            if c in sprox:
                pk = fetch_kline(sprox[c], 600)
                st_ = trend_state(sprox[c], pk, intraday)
                if st_:
                    st_["src"] = f"底层指数 {sprox[c]}"
                states[c] = st_
            else:
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
        cap_tot = m2["tot"] + float(rules["quarterly_amount"])
        gap_pp = tgt - w
        gap_amt = tgt / 100 * cap_tot - h["shares"] * prices[c]
        s = states.get(c)
        sc = scores.get(c)
        blocked = []
        if h.get("locked"):
            blocked = ["锁定不买"]
        elif a.legacy_gate:
            allowed_states = rules.get("gate_overrides", {}).get(c, rules["gate_states"])
            if not (s and s["eff"] in allowed_states):
                blocked.append("状态门")
        if not h.get("locked") and c in style_codes and max(style_rc2, style_rc1) > rules["style_group_limit_pct"]:
            blocked.append("风格组>%.0f%%" % rules["style_group_limit_pct"])
        if not h.get("locked") and gap_amt <= 0:
            blocked.append("已达标")
        pm = prem.get(c) or {}
        if not h.get("locked") and pm.get("prem") is not None \
                and pm["prem"] > rules.get("max_premium_pct", 1.5):
            blocked.append(f"溢价{pm['prem']:+.1f}%")
        rows.append(dict(code=c, name=names[c], px=prices[c], w=w, tgt=tgt,
                         gap_pp=gap_pp, gap_amt=gap_amt, state=s, score=sc,
                         eligible=len(blocked) == 0, blocked=blocked,
                         shares=h["shares"], prem=prem.get(c)))

    # ── 本季下单建议
    if a.legacy_gate:
        cand = [r for r in rows if r["eligible"] and r["gap_amt"] > 0]
        sel_note = "T0-T8 状态门（--legacy-gate）"
        max_score = None
    else:
        hard_ok = [r for r in rows if r["eligible"] and r["gap_amt"] > 0 and r["score"]]
        pool = [dict(code=r["code"], score=r["score"]["total"], gap=r["gap_amt"]) for r in hard_ok]
        picked, max_score, sel_note = v1_score.select(pool, spec)
        ok_codes = {p["code"] for p in picked}
        cand = [r for r in hard_ok if r["code"] in ok_codes]
    action = None
    if cand:
        if a.legacy_gate:
            pick = max(cand, key=lambda r: r["gap_amt"])
        else:
            pick = max(cand, key=lambda r: (r["score"]["total"], r["gap_amt"]))
        amt = min(rules["max_trade"], pick["gap_amt"])
        shares = int(amt // (pick["px"] * rules["lot_size"])) * rules["lot_size"]
        cost = shares * pick["px"]
        if cost >= rules["min_trade"]:
            action = dict(code=pick["code"], name=pick["name"], px=pick["px"],
                          shares=shares, cost=cost, gap=pick["gap_amt"],
                          score=(pick["score"]["total"] if pick.get("score") else None),
                          reason=sel_note, blocked=[])
        else:
            action = dict(code=None, reason=f"{pick['name']} 缺口 {pick['gap_amt']:.0f} 元 < 最小交易额 "
                                            f"{rules['min_trade']} 元 → 留现金")
    elif not a.legacy_gate:
        action = dict(code=None, reason=f"{sel_note} → 留现金")

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
        if a.legacy_gate:
            r = next((x for x in rows if x["code"] == ch["code"]), None)
            if ch["dir"] == "up" and ch["new"] in rules["reserve_fill_states"]:
                trig.append(("🟢 状态恢复", f"{ch['name']} {ch['old']} → {ch['new']}",
                             f"预备队可一次性补足缺口约 {r['gap_amt']:,.0f} 元" if r else "可评估补仓"))
            elif ch["dir"] == "down" and ch["old"] in rules["gate_states"]:
                trig.append(("🟠 状态转弱", f"{ch['name']} {ch['old']} → {ch['new']}",
                             "当季改投次优合格标的；无则留现金"))

    # ── 逐行判定：硬门 → 阈值（口径与最终下单一致）
    floor = spec["threshold"]["absolute_floor"]
    band = spec["threshold"]["relative_band"]
    for r in rows:
        sv = r.get("score")
        if a.legacy_gate:
            r["pass_all"] = r["eligible"] and r["gap_amt"] > 0
        else:
            r["pass_all"] = bool(not r["blocked"] and r["gap_amt"] > 0 and sv
                                 and sv["total"] >= floor
                                 and (max_score is None or sv["total"] >= max_score - band))

    # ── 恢复条件（任一生效即可恢复）
    resume = rules.get("resume") or {}
    nasdaq = rules.get("fallback_nasdaq", [])
    nas_ok = [c for c in nasdaq if (prem.get(c) or {}).get("prem") is not None]
    prim = rules.get("nasdaq_primary")
    if prim and prim in nas_ok:
        best_nas = prim                      # 只认首选标的的溢价，不用备选最低值替代
    else:
        best_nas = min(nas_ok, key=lambda c: prem[c]["prem"]) if nas_ok else None
    cond_premium = dict(
        id="premium", met=False,
        label=("任一纳指ETF溢价收敛至 %.1f%% 以内（且底层状态合格）" if a.legacy_gate
               else "任一纳指ETF溢价收敛至 %.1f%% 以内（之后按 V1 评分判定）") % rules.get("max_premium_pct", 1.5),
        detail="—")
    lim = rules.get("max_premium_pct", 1.5)
    nas_state_ok = any((states.get(c) or {}).get("eff") in rules["gate_states"]
                       for c in nasdaq if c in codes)
    ok_nas = [c for c in nas_ok if prem[c]["prem"] <= lim]
    if ok_nas and nas_state_ok:
        pick = min(ok_nas, key=lambda c: prem[c]["prem"])
        cond_premium.update(met=True,
                            detail=f"可买 {prem[pick].get('name', pick)} {prem[pick]['prem']:+.2f}%"
                                   f"（四只中溢价最低），底层状态亦合格")
    elif ok_nas:
        pick = min(ok_nas, key=lambda c: prem[c]["prem"])
        cond_premium.update(met=False,
                            detail=f"{prem[pick].get('name', pick)} 溢价 {prem[pick]['prem']:+.2f}% 已达标，"
                                   f"但底层指数状态不合格（{__import__('json').dumps({c:(states.get(c) or {}).get('eff') for c in nasdaq if c in codes}, ensure_ascii=False)}）")
    elif nas_ok:
        best = min(nas_ok, key=lambda c: prem[c]["prem"])
        cond_premium.update(met=False,
                            detail=f"最低 {prem[best].get('name', best)} {prem[best]['prem']:+.2f}%"
                                   f"（还需回落 {max(0.0, prem[best]['prem'] - lim):.1f}pp）")
    gold = next((r for r in rows if r["code"] == "sh518880"), None)
    gold_states = rules.get("gate_overrides", {}).get("sh518880", rules["gate_states"])
    cond_gold = dict(id="gold_t1", met=False,
                     label=("黄金进入分散腿合格集 {T1,T2,T3a,T3b,T4}" if a.legacy_gate
                            else "黄金当前形态（观察项，不再触发买入）"), detail="—")
    if gold and gold.get("state"):
        gs = gold["state"]
        ok_prem = (gold.get("prem") or {}).get("prem")
        ok_prem = ok_prem is not None and ok_prem <= rules.get("max_premium_pct", 1.5)
        cond_gold.update(met=(gs["eff"] in gold_states and ok_prem),
                         detail=f"当前 {gs['eff']} {gs['label']}｜周线 {gs.get('weekly_slope')}%"
                                f"｜距MA60 {gs.get('price_vs_ma60')}%｜溢价 {(gold.get('prem') or {}).get('prem', 0):+.2f}%")
    resume_rows = [cond_premium, cond_gold]

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
        print(" ⚠ 已跳过趋势状态机（--no-trend）：T 码列为空；V1 评分不受影响")
    print(f" {now:%Y-%m-%d %H:%M} | 最新 K 线 {bar_date}{'（盘中未定稿）' if intraday else '（收盘）'}")
    print(f" 判定架构 {'T0-T8 状态门（legacy）' if a.legacy_gate else 'V1：硬门 → 软分 → Eligibility Floor %d / Candidate Band %d' % (spec['threshold']['absolute_floor'], spec['threshold']['relative_band'])}")
    print("═" * W)

    pos_pct = (1 - cash / m2["tot"]) * 100
    print(f"\n【组合】总资产 {m2['tot']:,.0f} | 仓位 {pos_pct:.1f}% | 现金 {cash:,.0f} ({cash / m2['tot'] * 100:.1f}%)")
    pnote = "QDII已用指数代理" if pmap else "全用场内价"
    print(f"【风险】σp {m2['sd']:.2f}% | RC50 占比 {rc50:.1f}% | 绝对贡献 {rc50_abs:.2f}%  ({pnote})")
    print(f"       风格组 {style_rc2:.1f}%（2年）/ {style_rc1:.1f}%（1年）"
          f" | 回撤 {dd:+.1f}%（峰值 {peak:,.0f}）")

    print(f"\n【标的】")
    hdr = f"  {'代码':10}{'名称':14}{'现价':>7}{'溢价':>8}{'权重':>7}{'目标':>6}{'缺口':>10}{'评分':>6}  {'状态':<13}"
    print(hdr)
    print("  " + "─" * (W - 4))
    for r in rows:
        s = r["state"]
        stxt = f"{s['eff']} {s['label'][:5]}" if s else "—"
        if s and s.get("src"):
            stxt += "※"
        if c in (rules.get("state_suspect") or []):
            stxt += " ⚠"
        if r.get("pass_all"):
            mark = "可买"
        elif r["blocked"]:
            mark = "/".join(r["blocked"])[:14]
        elif r.get("score"):
            mark = "分数不足"
        else:
            mark = "无评分"
        pm = r.get("prem") or {}
        pr = f"{pm['prem']:+.2f}%" if pm.get("prem") is not None else "—"
        if pm.get("prem") is not None and pm["prem"] > rules.get("max_premium_pct", 1.5):
            pr = pr + "!"
        sv = r.get("score")
        stotal = f"{sv['total']:.0f}" if sv else "—"
        print(f"  {r['code']:10} {r['name'][:11]:<12} {r['px']:>7.3f} {pr:>8} {r['w']:>6.1f}% {r['tgt']:>5.1f}%"
              f" {r['gap_amt']:>+9,.0f} {stotal:>6}  {stxt:<17} {mark}")

    # ── V1 评分明细
    if not a.legacy_gate:
        print(f"\n【评分】V1 = Trend30 + Mom30 + Risk20 + Div20 = 100")
        print(f"  {'代码':10}{'名称':12}{'Trend':>7}{'Mom':>7}{'Risk':>7}{'Div':>7}{'ΔRC50':>8}{'合计':>7}  {'过门':<8}")
        print("  " + "─" * (W - 4))
        for r in sorted(rows, key=lambda x: -(x["score"]["total"] if x["score"] else -1)):
            sv = r.get("score")
            if not sv:
                continue
            tag = "✓" if r.get("pass_all") else ("硬门" if r["blocked"] else "分数不足")
            drc = sv.get("drc50")
            print(f"  {r['code']:10} {r['name'][:10]:<12}{sv['trend']:>7.1f}{sv['momentum']:>7.1f}"
                  f"{sv['risk']:>7.1f}{sv['div']:>7.1f}"
                  f"{(f'{drc:+.3f}' if drc is not None else '—'):>8}{sv['total']:>7.1f}  {tag:<8}")
        if max_score is not None:
            print(f"  Eligibility Floor {floor} ＋ Candidate Band {band}。硬门通过者最高分 {max_score:.1f}"
                  f" → 候选需 ≥ {max(max_score - band, floor):.1f}（被硬门否决的不参与比较）")
        else:
            print(f"  Eligibility Floor {floor} ＋ Candidate Band {band}（无硬门通过者）")
        if any(sv["div"] >= spec["score"]["diversification"]["points"] for sv in scores.values() if sv):
            print(f"  注：Div 已饱和（ΔRC50 ≤ {spec['score']['diversification']['full_at_pp']}），"
                  f"现金比例高时任何买入都能稀释 RC50，此时 Div 退化为门而非区分项。")

    lim = rules.get("max_premium_pct", 1.5)
    over = [r for r in rows if (r.get("prem") or {}).get("prem") is not None
            and r["prem"]["prem"] > lim]
    disc = [r for r in rows if (r.get("prem") or {}).get("prem") is not None
            and r["prem"]["prem"] < -lim]
    if over:
        print(f"\n【溢价】> {lim}% 上限，买入一律禁止：")
        for r in over:
            pm = r["prem"]
            tag = "｜不可申购·套利进不来，溢价难收敛" if pm.get("purchase") == "不可申购" else ""
            print(f"  {r['name']}：{pm['prem']:+.2f}%（净值 {pm['nav']} / 收盘 {pm['px']}）{tag}")
    if disc:
        print(f"【折价】< -{lim}%，买入相对划算（不构成门槛）：")
        for r in disc:
            pm = r["prem"]
            print(f"  {r['name']}：{pm['prem']:+.2f}%（净值 {pm['nav']} / 收盘 {pm['px']}）")

    print(f"\n【本季 {q}】已执行：{'是' if done else '否'} | 距季末约 {left} 个交易日（{qe}）"
          f"{'｜今天即决策日' if left == 0 else ''}")
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

    if not cand:
        if a.legacy_gate:
            allmet = all(r_["met"] for r_ in resume_rows)
            print(f"\n【等待恢复】恢复策略：A 或 B 任一成立即恢复长期执行")
            for tag, rc_ in zip(("A", "B"), resume_rows):
                icon = "✅" if rc_["met"] else "⏳"
                print(f"  {icon} 条件{tag}｜{rc_['label']}")
                print(f"          {rc_['detail']}")
            print(f"  当前：{'全部满足' if allmet else '均未满足'}"
                  f"{'（下一季可按常规执行）' if allmet else '（继续空仓）'}")
            print("  备注：四只中哪只先满足就买哪只，多只满足取溢价最低；"
                  "且必须底层指数状态合格（当前 usNDX=T6，不在合格池）。")
        else:
            print(f"\n【本季不买】{sel_note}")
            print(f"  只有 Eligibility Floor {spec['threshold']['absolute_floor']} 能产生「不买」；"
                  f"Candidate Band {spec['threshold']['relative_band']} 只收窄候选集。")
            for rc_ in resume_rows:
                icon = "✅" if rc_["met"] else "⏳"
                print(f"  {icon} {rc_['label']}")
                print(f"     {rc_['detail']}")

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
    elif action is None and not cand:
        met = [r_["id"] for r_ in resume_rows if r_["met"]]
        if met:
            print(f"  观察条件已满足（{', '.join(met)}），下季按常规规则执行。")
        elif a.legacy_gate:
            print(f"  空仓等待：本季 3,000 元并入现金，等溢价收敛或黄金转 T1 后恢复。")
        else:
            print(f"  本季不买：{sel_note}。3,000 元并入现金。")
    else:
        print(f"  本周无需动作；等季末（{qe}）再执行。")
    print("═" * W)

    # ── 存档
    snap = dict(date=now.date().isoformat(), quarter=q, bar_date=bar_date,
                days_to_qe=left, is_decision_day=(left == 0),
                mode="legacy" if a.legacy_gate else "v1",
                spec_version=spec.get("version"),
                total=m2["tot"], cash=cash, cash_pct=cash / m2["tot"] * 100,
                sd=m2["sd"], rc50=rc50, rc50_abs=rc50_abs,
                style2=style_rc2, style1=style_rc1, drawdown=dd, peak=peak,
                states={c: (states[c]["eff"] if states.get(c) else None) for c in codes},
                scores={c: ({k: scores[c][k] for k in ("trend", "momentum", "risk", "div", "total")}
                            if scores.get(c) else None) for c in codes},
                rows=[dict(code=r["code"], name=r["name"], px=r["price"] if "price" in r else r["px"],
                           weight=r["w"], target=r["tgt"], gap=r["gap_amt"],
                           score=(r["score"]["total"] if r.get("score") else None),
                           drc50=(r["score"]["drc50"] if r.get("score") else None),
                           blocked=r["blocked"], pass_all=r.get("pass_all", False))
                      for r in rows],
                score_max=max_score, selection=sel_note,
                premium={c: (prem[c]["prem"] if prem.get(c) else None) for c in codes},
                action=action, triggers=[t[0] for t in trig], executed=done,
                changes=changes,
                resume={r_["id"]: r_["met"] for r_ in resume_rows},
                resume_detail={r_["id"]: r_["detail"] for r_ in resume_rows})

    if a.save:
        hist = []
        if os.path.exists(HISTORY):
            try:
                hist = json.load(open(HISTORY))
            except json.JSONDecodeError:
                hist = []
        hist = [h for h in hist if h.get("date") != snap["date"]] + [snap]
        json.dump(hist, open(HISTORY, "w"), ensure_ascii=False, indent=2)
        print(f"\n已追加 {HISTORY}（共 {len(hist)} 条｜距季末 {left} 个交易日"
              f"{'，决策日' if left == 0 else '，监控记录'}）")

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
