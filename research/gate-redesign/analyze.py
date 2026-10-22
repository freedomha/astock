#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势门重设计：连续评分 + 硬门 vs T0-T8（M0）vs 极简趋势（M2）

三个模型
  M0  T0-T8 状态门（现状）：合格集 {T3b,T4}；分散腿放宽到 {T1,T2,T3a,T3b,T4}
  M1  连续评分：Trend 30 / Momentum 30 / Risk 20 / Diversification 20
  M2  极简：P > MA200，按 6M/12M 双动量排序，要求 ΔRC50 < 0

两层评估
  A 信号层（高样本）：21,201 条状态下，连续分数能否比 T3b 哑变量更好地排序未来 20 日收益
  B 政策层（低样本）：5 只持仓，每季 3,000 元，只稀释不卖出，逐季比较

输出 research/gate-redesign/gate_results.json
"""

import json
import os
import statistics as st
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SIGNALS = os.path.join(ROOT, ".workbuddy/skills/etf-operation-plan/backtest_trend_state_results.json")
KLINES = os.path.join(ROOT, "etf_kline_data_500.json")
PRICES = os.path.join(HERE, "prices.json")
OUT = os.path.join(HERE, "gate_results.json")

T3B_GATE = {"T3b", "T4"}
DIVER_GATE = {"T1", "T2", "T3a", "T3b", "T4"}
MENU = ["sh510050", "sh513500", "sz159941", "sh512890", "sh518880"]
NAMES = {"sh510050": "上证50", "sh513500": "标普500", "sz159941": "纳指", "sh512890": "红利低波", "sh518880": "黄金"}
STYLE = ["sh510050", "sh512890"]
TARGET = {"sh510050": 0.20, "sh513500": 0.20, "sz159941": 0.15, "sh512890": 0.15, "sh518880": 0.10}


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def pct(x, nd=2):
    return round(x, nd)


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def quarter(d):
    return "%sQ%d" % (d[:4], (int(d[5:7]) - 1) // 3 + 1)


# ══════════════════════════ 特征与评分 ══════════════════════════

def build_series(bars):
    """bars 为 newest-first，返回 oldest-first 的 close 与 date。"""
    b = list(reversed(bars))
    return [x["last"] for x in b], [x["date"] for x in b]


def ma(cl, n, i):
    if i + 1 < n:
        return None
    return sum(cl[i - n + 1:i + 1]) / n


def features(cl, i):
    if i < 200:
        return None
    p = cl[i]
    m20, m60, m120, m200 = ma(cl, 20, i), ma(cl, 60, i), ma(cl, 120, i), ma(cl, 200, i)
    if not all([m20, m60, m120, m200]):
        return None
    def slope(n, lag=20):
        a, b = ma(cl, n, i), ma(cl, n, i - lag)
        return (a / b - 1) * 100 if a and b else 0.0
    r20 = (p / cl[i - 20] - 1) * 100
    r60 = (p / cl[i - 60] - 1) * 100
    r120 = (p / cl[i - 120] - 1) * 100
    r250 = (p / cl[i - 250] - 1) * 100 if i >= 250 else r120
    rets20 = [cl[j] / cl[j - 1] - 1 for j in range(i - 19, i + 1)]
    rets60 = [cl[j] / cl[j - 1] - 1 for j in range(i - 59, i + 1)]
    v20 = st.pstdev(rets20) * (252 ** 0.5) * 100
    v60 = st.pstdev(rets60) * (252 ** 0.5) * 100
    hi250 = max(cl[max(0, i - 249):i + 1])
    dd = (p / hi250 - 1) * 100
    return dict(p=p, ma20=m20, ma60=m60, ma120=m120, ma200=m200,
                s60=slope(60), s120=slope(120), s200=slope(200, 60),
                r20=r20, r60=r60, r120=r120, r250=r250,
                v20=v20, v60=v60, dd=dd, above200=p > m200)


def tent(x, peak, hw):
    return max(0.0, 1 - abs(x - peak) / hw)


def score_trend(f):
    """0-30：价格对 MA60 的溢价（10）＋ MA60 斜率（10）＋ MA120 斜率（10）。"""
    t1 = 10 * clip((f["p"] / f["ma60"] - 1) * 100 / 8.0, 0, 1)
    t2 = 10 * clip(f["s60"] / 5.0, 0, 1)
    t3 = 10 * clip(f["s120"] / 8.0, 0, 1)
    return t1 + t2 + t3


def score_mom(f):
    """0-30：钟形。峰值 20日+6% / 60日+14% / 120日+26%；过热回落到 0。"""
    return 10 * tent(f["r20"], 6, 14) + 10 * tent(f["r60"], 14, 26) + 10 * tent(f["r120"], 26, 46)


def score_risk(f):
    """0-20：波动（8）＋ 距 250 日高回撤（6）＋ 短期跳涨惩罚（6）。"""
    v = f["v20"]
    if v <= 18:
        a = 8.0
    elif v <= 25:
        a = 8 - (v - 18) / 7 * 4
    elif v <= 35:
        a = 4 - (v - 25) / 10 * 4
    else:
        a = 0.0
    d = 6 * tent(f["dd"], -10, 18)          # 回撤 10% 最好，0% 与 28% 都低
    j = 6 * clip(1 - (f["r20"] - 20) / 15, 0, 1) if f["r20"] > 20 else 6.0
    return a + d + j


def score_mom_mono(f):
    """0-30：单调版（越高越好，上限封顶），用于检验钟形假设。"""
    return 10 * clip(f["r20"] / 18.0, 0, 1) + 10 * clip(f["r60"] / 40.0, 0, 1) + 10 * clip(f["r120"] / 70.0, 0, 1)


def score_core(f):
    t, m, r = score_trend(f), score_mom(f), score_risk(f)
    return dict(trend=pct(t), mom=pct(m), risk=pct(r), total=pct(t + m + r),
                mom_mono=pct(score_mom_mono(f)))


# ══════════════════════════ A 信号层 ══════════════════════════

def signal_layer():
    raw = json.load(open(SIGNALS, encoding="utf-8"))
    kl = json.load(open(KLINES, encoding="utf-8"))
    ser = {}
    for c, bars in kl.items():
        cl, dt = build_series(bars)
        ser[c] = (cl, {d: i for i, d in enumerate(dt)})

    rows = []
    for s in raw["signals"]:
        if s.get("fwd20d") is None:
            continue
        c, d = s["code"], s["date"]
        cl, ix = ser.get(c, (None, None))
        if not cl:
            continue
        i = ix.get(d)
        if i is None:
            continue
        f = features(cl, i)
        if not f:
            continue
        sc = score_core(f)
        rows.append(dict(code=c, date=d, state=s["effective_state"], fwd=s["fwd20d"],
                         q=quarter(d), **sc, score_tm=pct(sc["trend"] + sc["mom"]),
                         score_v7=pct(sc["trend"] + sc["mom_mono"] + sc["risk"]),
                         **{k: f[k] for k in ("r20", "r60", "r120", "v20", "dd", "above200")}))

    # 同日横截面基准
    byd = defaultdict(list)
    for r in rows:
        byd[r["date"]].append(r["fwd"])
    cs = {k: mean(v) for k, v in byd.items()}
    for r in rows:
        r["exc"] = r["fwd"] - cs[r["date"]]

    def agg(g):
        if not g:
            return dict(n=0, abs=None, exc=None, win=None, sd=None, cvar=None)
        v = sorted(x["fwd"] for x in g)
        k = max(1, len(v) // 20)
        return dict(n=len(g), abs=pct(mean([x["fwd"] for x in g])),
                    exc=pct(mean([x["exc"] for x in g])),
                    win=pct(sum(1 for x in g if x["fwd"] > 0) / len(g) * 100, 1),
                    sd=pct(st.pstdev(v), 2), cvar=pct(mean(v[:k]), 2))

    # 分数五分位（全样本，事后切分，仅用于单调性展示）
    def quintiles(key):
        g = sorted(rows, key=lambda x: x[key])
        n = len(g)
        out = []
        for i in range(5):
            seg = g[i * n // 5:(i + 1) * n // 5]
            out.append(dict(bucket=i + 1, lo=pct(seg[0][key], 1), hi=pct(seg[-1][key], 1), **agg(seg)))
        return out

    # IC：每个日期内的秩相关
    def spearman(xs, ys):
        n = len(xs)
        if n < 20:
            return None
        def rank(v):
            s = sorted(range(n), key=lambda i: v[i])
            r = [0] * n
            for pos, i in enumerate(s):
                r[i] = pos
            return r
        rx, ry = rank(xs), rank(ys)
        mx, my = mean(rx), mean(ry)
        num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
        den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
        return num / den if den else None

    ic = {}
    for key in ("trend", "mom", "mom_mono", "risk", "total", "score_tm"):
        per = []
        for d in {r["date"] for r in rows}:
            g = [r for r in rows if r["date"] == d]
            v = spearman([r[key] for r in g], [r["fwd"] for r in g])
            if v is not None:
                per.append(v)
        ic[key] = dict(mean=pct(mean(per), 3), pos_share=pct(sum(1 for x in per if x > 0) / len(per) * 100, 1), n_dates=len(per))

    # 头对头：T3b 哑变量 vs 连续分数顶五分位
    t3b = [r for r in rows if r["state"] == "T3b"]
    top = sorted(rows, key=lambda x: -x["total"])[:len(rows) // 5]
    top_t3b = [r for r in top if r["state"] == "T3b"]
    head = {
        "t3b": agg(t3b),
        "top20_total": agg(top),
        "top20_total_overlap_t3b": pct(len(top_t3b) / len(top) * 100, 1),
        "t3b_inside_top20": pct(len(top_t3b) / len(t3b) * 100, 1) if t3b else None,
    }

    # 分期
    def period(sub, label):
        return dict(label=label, t3b=agg([r for r in sub if r["state"] == "T3b"]),
                    top20=agg(sorted(sub, key=lambda x: -x["total"])[:max(1, len(sub) // 5)]) if sub else agg([]))
    periods = [period([r for r in rows if r["q"] != "2025Q3"], "剔除2025Q3"),
               period([r for r in rows if r["q"] == "2025Q3"], "仅2025Q3"),
               period([r for r in rows if r["date"][:4] == "2026"], "2026")]

    # 消融：只用 Trend / +Mom / +Risk
    ab = []
    for key, label in (("trend", "仅 Trend(30)"), ("trend_mom", "Trend+Mom(60)"), ("total", "Trend+Mom+Risk(80)")):
        if key == "trend_mom":
            g = sorted(rows, key=lambda x: -(x["trend"] + x["mom"]))
        elif key == "trend":
            g = sorted(rows, key=lambda x: -x["trend"])
        else:
            g = sorted(rows, key=lambda x: -x["total"])
        n = len(g)
        ab.append(dict(label=label, top=agg(g[:n // 5]), bottom=agg(g[-n // 5:])))

    # 变体：不同"评分 → 买入集合"的构造方式
    def top_set(rows_, key, share=0.2):
        g = sorted(rows_, key=lambda x: -x[key])
        return g[:max(1, int(len(g) * share))]

    def filt(rows_):
        return [r for r in rows_ if r["v20"] <= 35 and r["dd"] >= -30]

    variants = []
    for label, key, use_filter in (
            ("V1 总评 30/30/20/20", "total", False),
            ("V2 仅 Trend(30)", "trend", False),
            ("V3 Trend+Mom(60)", "score_tm", False),
            ("V4 Trend+Mom ＋风险否决", "score_tm", True),
            ("V5 单调动量(30)", "mom_mono", False),
            ("V6 T3b 哑变量", None, False),
            ("V7 只把钟形换单调(30/30/20)", "score_v7", False)):
        base = filt(rows) if use_filter else rows
        if key is None:
            pick = [r for r in base if r["state"] == "T3b"]
        else:
            pick = top_set(base, key)
        variants.append(dict(
            label=label, n=len(pick),
            all=agg(pick),
            ex_q3=agg([r for r in pick if r["q"] != "2025Q3"]),
            y2026=agg([r for r in pick if r["date"][:4] == "2026"]),
            q3=agg([r for r in pick if r["q"] == "2025Q3"])))

    return dict(n=len(rows), dates=len({r["date"] for r in rows}), etfs=len({r["code"] for r in rows}),
                variants=variants,
                quintiles={k: quintiles(k) for k in ("total", "trend", "mom", "risk")},
                ic=ic, head=head, periods=periods, ablation=ab,
                state_dummy={s: agg([r for r in rows if r["state"] == s]) for s in
                             ("T0", "T1", "T2", "T3a", "T3b", "T4", "T5", "T6", "T7", "T8")})


# ══════════════════════════ B 政策层 ══════════════════════════

def load_prices():
    raw = json.load(open(PRICES, encoding="utf-8"))
    out = {}
    for c, bars in raw.items():
        cl, dt = build_series(bars)
        out[c] = (cl, {d: i for i, d in enumerate(dt)}, dt)
    return out


def policy_layer():
    P = load_prices()
    dates = sorted({d for c in P for d in P[c][2]})
    dates = [d for d in dates if d >= "2025-01-02"]
    # 建每日价格矩阵（前向填充）
    px = {}
    for c, (cl, ix, dt) in P.items():
        last, m = None, {}
        for d in dates:
            i = ix.get(d)
            if i is not None:
                last = cl[i]
            m[d] = last
        px[c] = m

    start_val = 48472.0
    w0 = {"sh510050": 0.3075, "sh513500": 0.1751, "sz159941": 0.0, "sh512890": 0.1496, "sh518880": 0.0521}
    cash0 = start_val * (1 - sum(w0.values()))
    shares0 = {c: start_val * w0[c] / px[c][dates[0]] for c in MENU}

    # 状态（M0）与特征
    raw = json.load(open(SIGNALS, encoding="utf-8"))
    state_at = defaultdict(dict)
    for s in raw["signals"]:
        state_at[s["code"]][s["date"]] = s["effective_state"]

    def state_on(code, d):
        """取 <= d 的最近一个状态。"""
        ks = [k for k in state_at.get(code, {}) if k <= d]
        return state_at[code][max(ks)] if ks else None

    def feats(c, d):
        cl, ix, _ = P[c]
        i = ix.get(d)
        return features(cl, i) if i is not None else None

    DIDX = {d: i for i, d in enumerate(dates)}

    def rc50_and_style(sh, cash, d):
        """用 250 日协方差算 RC50 与风格组风险。"""
        i = DIDX[d]
        lo = max(0, i - 250)
        win = dates[lo:i + 1]
        if len(win) < 60:
            return None, None
        rets = {}
        for c in MENU:
            r = []
            for k in range(1, len(win)):
                a, b = px[c][win[k - 1]], px[c][win[k]]
                r.append((b / a - 1) if a and b else 0.0)
            rets[c] = r
        n = len(rets[MENU[0]])
        C = [[0.0] * len(MENU) for _ in MENU]
        for a in range(len(MENU)):
            for b in range(a, len(MENU)):
                ra, rb = rets[MENU[a]], rets[MENU[b]]
                ma_, mb_ = mean(ra), mean(rb)
                cov = sum((x - ma_) * (y - mb_) for x, y in zip(ra, rb)) / max(1, n - 1)
                C[a][b] = C[b][a] = cov * 252
        tot = sum(sh.values()) + cash
        w = [sh[c] / tot for c in MENU]
        s = [sum(C[a][b] * w[b] for b in range(len(MENU))) for a in range(len(MENU))]
        var = sum(w[a] * s[a] for a in range(len(MENU)))
        if var <= 0:
            return None, None
        i50 = MENU.index("sh510050")
        rc50 = w[i50] * s[i50] / var * 100
        gw = [w[a] if MENU[a] in STYLE else 0.0 for a in range(len(MENU))]
        gs = [sum(C[a][b] * gw[b] for b in range(len(MENU))) for a in range(len(MENU))]
        style = sum(gw[a] * gs[a] for a in range(len(MENU))) / var * 100
        return rc50, style

    def delta_rc50(sh, cash, d, cand, amount=1000.0):
        """从现金挪 amount 到 cand，RC50 的变化（pp，负=改善）。"""
        tot = sum(sh.values()) + cash
        if cash < amount:
            return None
        sh2 = dict(sh)
        sh2[cand] += amount
        a, _ = rc50_and_style(sh, cash, d)
        b, _ = rc50_and_style(sh2, cash - amount, d)
        return None if (a is None or b is None) else b - a

    def portfolio_dd_ok(sh, cash, d, peak):
        v = sum(sh[c] * px[c][d] for c in MENU) + cash
        return v >= peak * 0.85, v

    # 首个三模型都可判定的季度末
    q_all = [d for i, d in enumerate(dates) if i + 1 < len(dates) and quarter(d) != quarter(dates[i + 1])]
    q_all = [d for d in q_all if d >= "2025-03-01"]
    q_use = []
    for d in q_all:
        if all(feats(c, d) for c in MENU):
            q_use.append(d)
    q_use = q_use[:]

    def run(model):
        sh = dict(shares0)
        cash = cash0
        peak = start_val
        nav, cashs, log = [], [], []
        bought = 0.0
        for d in dates:
            v = sum(sh[c] * px[c][d] for c in MENU) + cash
            peak = max(peak, v)
            nav.append((d, v))
            cashs.append(cash)
            if d not in q_use:
                continue
            cash += 3000.0
            invest_total = v + 3000
            gap = {c: TARGET[c] * invest_total - sh[c] * px[c][d] for c in MENU if c != "sh510050"}
            ok, _ = portfolio_dd_ok(sh, cash, d, peak)
            if not ok:
                log.append(dict(date=d, pick=None, reason="回撤>15% 暂停"))
                continue
            pick, detail = None, ""
            if model == "M0":
                elig = []
                for c in MENU:
                    if c == "sh510050":
                        continue
                    st_ = state_on(c, d)
                    gate = DIVER_GATE if c in ("sh513500", "sz159941", "sh518880") else T3B_GATE
                    if st_ in gate:
                        elig.append(c)
                if elig:
                    pick = max(elig, key=lambda c: gap[c])
                detail = "合格:" + ("/".join(NAMES[c] for c in elig) if elig else "无")
            elif model == "M1":
                sc = {}
                for c in MENU:
                    if c == "sh510050":
                        continue
                    f = feats(c, d)
                    if not f:
                        continue
                    base = score_core(f)
                    drc = delta_rc50(sh, cash, d, c, 1000.0)
                    div = 20 * clip(-(drc or 0) / 0.15, 0, 1) if drc is not None else 0.0
                    sc[c] = dict(base, div=pct(div), total100=pct(base["total"] + div))
                if sc:
                    best = max(sc, key=lambda c: sc[c]["total100"])
                    detail = "最高分 %s=%.1f" % (NAMES[best], sc[best]["total100"])
                    if sc[best]["total100"] >= 70:
                        pick = best
                    else:
                        detail += "（<70 不买）"
            else:
                cand = []
                for c in MENU:
                    if c == "sh510050":
                        continue
                    f = feats(c, d)
                    if not f or not f["above200"]:
                        continue
                    drc = delta_rc50(sh, cash, d, c, 1000.0)
                    if drc is not None and drc < 0:
                        cand.append((0.5 * f["r120"] + 0.5 * f["r250"], c))
                if cand:
                    pick = max(cand)[1]
                    detail = "MA200上且ΔRC<0，动量最优 %s" % NAMES[pick]
                else:
                    detail = "无标的满足 MA200+ΔRC<0"
            if pick is None:
                log.append(dict(date=d, pick=None, reason=detail))
                continue
            if pick in STYLE:
                _, style = rc50_and_style(sh, cash, d)
                if style is not None and style > 60:
                    log.append(dict(date=d, pick=None, reason="风格组>60%"))
                    continue
            amt = min(3000.0, max(0.0, gap[pick]), cash)
            if amt < 2000:
                log.append(dict(date=d, pick=None, reason="缺口<2000（%s）" % NAMES[pick]))
                continue
            lot = int(amt / px[pick][d] / 100) * 100
            if lot <= 0:
                log.append(dict(date=d, pick=None, reason="不足一手"))
                continue
            cost = lot * px[pick][d]
            sh[pick] += lot
            cash -= cost
            bought += cost
            log.append(dict(date=d, pick=pick, name=NAMES[pick], lot=lot, cost=pct(cost), reason=detail))
        end_v = nav[-1][1]
        contrib = start_val + 3000.0 * len(q_use)
        rets = [nav[i][1] / nav[i - 1][1] - 1 for i in range(1, len(nav)) if nav[i - 1][1] > 0]
        vol = st.pstdev(rets) * (252 ** 0.5) * 100
        peaks, mdd = nav[0][1], 0.0
        for _, v in nav:
            peaks = max(peaks, v)
            mdd = min(mdd, v / peaks - 1)
        rc_end, style_end = rc50_and_style(sh, cash, dates[-1])
        return dict(model=model, end=pct(end_v), contributed=pct(contrib),
                    total_ret=pct((end_v / contrib - 1) * 100),
                    vol=pct(vol), mdd=pct(mdd * 100),
                    sharpe=pct((end_v / contrib - 1) * 100 / vol, 2) if vol else None,
                    trades=sum(1 for x in log if x.get("pick")),
                    bought=pct(bought), cash_end=pct(cash),
                    cash_ratio=pct(mean([c / v * 100 for (d, v), c in zip(nav, cashs) if v > 0])),
                    rc50_end=pct(rc_end) if rc_end is not None else None,
                    style_end=pct(style_end) if style_end is not None else None,
                    nav=[[d, pct(v, 0)] for d, v in nav], log=log)

    # ── 阈值行为（不优化收益，只量化"这道门多难通过"）──────────────
    def thr_stats():
        rows = []
        for d in dates:
            vals = {}
            for c in MENU:
                if c == "sh510050":
                    continue
                f = feats(c, d)
                if not f:
                    continue
                core = score_core(f)["total"]
                drc = delta_rc50(shares0, cash0, d, c, 1000.0)
                div = 20 * clip(-(drc or 0) / 0.15, 0, 1) if drc is not None else 0.0
                vals[c] = core + div
            if len(vals) >= 4:
                b = max(vals.values())
                n_near = sum(1 for v in vals.values() if v >= b - 5)
                rows.append(dict(d=d, best=pct(b), n_near=n_near,
                                 n60=sum(1 for v in vals.values() if v >= 60),
                                 n70=sum(1 for v in vals.values() if v >= 70)))
        bests = sorted(r["best"] for r in rows)
        floors = {}
        for th in (50, 55, 60, 65, 70, 75):
            floors[th] = pct(sum(1 for b in bests if b >= th) / len(bests) * 100, 1)
        dec = [r for r in rows if r["d"] in q_use]
        return dict(n_days=len(rows),
                    q10=pct(bests[int(len(bests) * .1)]), q25=pct(bests[int(len(bests) * .25)]),
                    median=pct(bests[len(bests) // 2]), q75=pct(bests[int(len(bests) * .75)]),
                    q90=pct(bests[int(len(bests) * .9)]),
                    pass_rate=floors,
                    near5_median=pct(st.median([r["n_near"] for r in rows]), 1),
                    decisions=dec)

    res = {m: run(m) for m in ("M0", "M1", "M2")}
    # 现金基准：一分不投
    base = dict(end=pct(start_val + 3000.0 * len(q_use)),
                contributed=pct(start_val + 3000.0 * len(q_use)),
                note="全部留现金（同节奏每季 +3,000）")
    return dict(start=start_val, dates=[dates[0], dates[-1]], n_days=len(dates),
                q_ends=q_use,
                models=res, cash_only=base, thresholds=thr_stats(),
                weights0=w0, cash0=pct(cash0))


def main():
    print("A 信号层…")
    A = signal_layer()
    print("  n=%d dates=%d" % (A["n"], A["dates"]))
    print("B 政策层…")
    B = policy_layer()
    out = dict(meta=dict(as_of="2026-10-22",
                         note="连续评分 vs T0-T8 vs 极简趋势；政策层样本极短，仅作可行性演示"),
               signal=A, policy=B)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("written", OUT)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "nav" and kk != "log"}
                      for k, v in B["models"].items()}, ensure_ascii=False, indent=1))
    print("cash_only", B["cash_only"])
    print("IC", json.dumps(A["ic"], ensure_ascii=False))
    print("head", json.dumps(A["head"], ensure_ascii=False))


if __name__ == "__main__":
    main()
