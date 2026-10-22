#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-State Validation / Walk-Forward Research

问题：T3b 的 +4.33pp（20 日、胜率 75.9%）是可泛化的信号，还是 2025Q3 这一段样本的结构性偶然？

输入
  .workbuddy/skills/etf-operation-plan/backtest_trend_state_results.json  (21,201 条状态观测)
  etf_kline_data_500.json                                                 (500 日 K 线：朴素规则、动量控制、波动分类)
  all_etfs_larggest.json                                                  (名称)

输出
  research/tstate-validation/tstate_validation.json

只用标准库；随机过程固定种子，可复现。
"""

import json
import os
import random
import statistics as st
from collections import defaultdict, Counter
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIGNALS = os.path.join(ROOT, ".workbuddy/skills/etf-operation-plan/backtest_trend_state_results.json")
KLINES = os.path.join(ROOT, "etf_kline_data_500.json")
UNIVERSE = os.path.join(ROOT, "all_etfs_larggest.json")
OUT = os.path.join(ROOT, "research/tstate-validation/tstate_validation.json")

STATES = ["T0", "T1", "T2", "T3a", "T3b", "T4", "T5", "T6", "T7", "T8"]
HORIZONS = [5, 10, 20, 40, 60]
SEED = 20261022


# ─────────────────────────── 基础工具 ───────────────────────────

def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def median(xs):
    return st.median(xs) if xs else 0.0


def quarter(d):
    return "%sQ%d" % (d[:4], (int(d[5:7]) - 1) // 3 + 1)


def month(d):
    return d[:7]


def half(d):
    return "%sH%d" % (d[:4], 1 if int(d[5:7]) <= 6 else 2)


def pct(x, nd=2):
    return round(x, nd)


def days_between(a, b):
    ya, ma, da = int(a[:4]), int(a[5:7]), int(a[8:10])
    yb, mb, db = int(b[:4]), int(b[5:7]), int(b[8:10])
    return (date(yb, mb, db) - date(ya, ma, da)).days


# ─────────────────────────── 分类（数据驱动 + 名称） ───────────────────────────

def classify(name, code, vol_ann):
    """用实现波动率先把「现金类 / 债券」切出来，再按名称分权益类。

    仅按代码前缀会出错：sh511 段里既有货币基金（511600/511820/511850），
    也有 30 年国债（511090）、转债（511380）——后两者波动可以到两位数。
    """
    if vol_ann is not None and vol_ann < 3.0:
        return "现金类"
    if "货币" in name or "添益" in name or "日利" in name or "保证金" in name or "天天金" in name or "日日鑫" in name or "财富宝" in name or "添利" in name:
        return "现金类"
    if "债" in name:
        return "债券"
    if vol_ann is not None and vol_ann < 8.0:
        return "债券"
    if "黄金" in name or "白银" in name or "有色" in name and "黄金" in name:
        return "黄金"
    cross = ("纳指", "标普", "恒生", "港股", "中概", "德国", "日经", "法国", "美国",
             "海外", "亚太", "印度", "越南", "东南亚", "沙特", "H股", "中韩", "东证", "纳斯达克")
    if any(k in name for k in cross):
        return "跨境"
    wide = ("沪深300", "上证50", "中证500", "中证1000", "中证2000", "创业板", "科创50",
            "科创100", "上证180", "深证100", "MSCI", "A50", "A500", "中证A", "上证380",
            "深证成指", "双创", "北证", "上证综指", "中证800", "中证100")
    if any(k in name for k in wide):
        return "宽基"
    return "行业主题"


# ─────────────────────────── 载入 ───────────────────────────

def load():
    raw = json.load(open(SIGNALS, encoding="utf-8"))
    uni = {x["code"]: x for x in json.load(open(UNIVERSE, encoding="utf-8"))}
    klines = json.load(open(KLINES, encoding="utf-8"))

    # 年化波动（最后 250 根）
    vol = {}
    for code, bars in klines.items():
        cl = [b["last"] for b in bars[:251]]
        rets = [cl[i] / cl[i + 1] - 1 for i in range(len(cl) - 1) if cl[i + 1] > 0]
        if len(rets) > 30:
            vol[code] = st.pstdev(rets) * (252 ** 0.5) * 100

    rows = []
    for x in raw["signals"]:
        name = uni.get(x["code"], {}).get("name", x["code"])
        r = dict(x)
        r["name"] = name
        r["cat"] = classify(name, x["code"], vol.get(x["code"]))
        r["q"] = quarter(x["date"])
        r["m"] = month(x["date"])
        r["h"] = half(x["date"])
        rows.append(r)
    return raw, rows, klines, uni, vol


# ─────────────────────────── 基准 ───────────────────────────

def build_benchmarks(rows, field="fwd20d"):
    """B0 池化（原报告口径）/ B1 同日横截面 / 同日横截面中位数。"""
    dated = defaultdict(list)
    for r in rows:
        v = r.get(field)
        if v is not None:
            dated[r["date"]].append(v)
    return (mean([r[field] for r in rows if r.get(field) is not None]),
            {d: mean(v) for d, v in dated.items()},
            {d: median(v) for d, v in dated.items()},
            dated)


def state_table(rows, field="fwd20d"):
    pooled, cs, cs_med, dated = build_benchmarks(rows, field)
    out = []
    for s in STATES:
        g = [r for r in rows if r["effective_state"] == s and r.get(field) is not None]
        if not g:
            continue
        vals = [r[field] for r in g]
        b2 = []
        for r in g:
            others = dated[r["date"]]
            if len(others) > 1:
                b2.append(r[field] - (sum(others) - r[field]) / (len(others) - 1))
        out.append({
            "state": s, "n": len(g), "etfs": len({r["code"] for r in g}),
            "avg": pct(mean(vals)), "median": pct(median(vals)),
            "winrate": pct(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
            "beat_cs_median": pct(sum(1 for r in g if r[field] > cs_med[r["date"]]) / len(g) * 100, 1),
            "excess_pooled": pct(mean(vals) - pooled),
            "excess_cs": pct(mean([r[field] - cs[r["date"]] for r in g])),
            "excess_cs_exself": pct(mean(b2)) if b2 else None,
            "cs_mean_on_those_days": pct(mean([cs[r["date"]] for r in g])),
        })
    return {"horizon": int(field.replace("fwd", "").replace("d", "")),
            "pooled_mean": pct(pooled), "n_obs": sum(x["n"] for x in out),
            "n_dates": len(cs), "rows": out}


# ─────────────────────────── 时间聚集 ───────────────────────────

def concentration(rows, s="T3b"):
    g = [r for r in rows if r["effective_state"] == s and r.get("fwd20d") is not None]
    cs = build_benchmarks(rows)[1]
    byq, bym = defaultdict(list), defaultdict(list)
    for r in g:
        byq[r["q"]].append(r)
        bym[r["m"]].append(r)
    tot = Counter(r["q"] for r in rows if r.get("fwd20d") is not None)

    qrows = []
    for q in sorted({r["q"] for r in rows}):
        gg = byq.get(q, [])
        if not gg:
            qrows.append({"q": q, "n": 0, "share": 0, "universe": tot.get(q, 0),
                          "occurrence": 0, "avg": None, "excess_cs": None, "winrate": None})
            continue
        vals = [r["fwd20d"] for r in gg]
        qrows.append({
            "q": q, "n": len(gg), "share": pct(len(gg) / len(g) * 100, 1),
            "universe": tot.get(q, 0),
            "occurrence": pct(len(gg) / tot[q] * 100, 1) if tot.get(q) else 0,
            "avg": pct(mean(vals)),
            "excess_cs": pct(mean([r["fwd20d"] - cs[r["date"]] for r in gg])),
            "winrate": pct(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
        })

    mrows = []
    for m in sorted({r["m"] for r in rows}):
        gg = bym.get(m, [])
        if not gg:
            mrows.append({"m": m, "n": 0, "excess_cs": None, "avg": None})
        else:
            vals = [r["fwd20d"] for r in gg]
            mrows.append({"m": m, "n": len(gg),
                          "excess_cs": pct(mean([r["fwd20d"] - cs[r["date"]] for r in gg])),
                          "avg": pct(mean(vals))})

    # episode：同一 ETF 两次信号间隔 > 10 个自然日 → 新的一段
    byc = defaultdict(list)
    for r in g:
        byc[r["code"]].append(r["date"])
    lens = []
    for c, ds in byc.items():
        ds.sort()
        cur = 1
        for i in range(1, len(ds)):
            if days_between(ds[i - 1], ds[i]) > 10:
                lens.append(cur)
                cur = 1
            else:
                cur += 1
        lens.append(cur)
    top_q = max(qrows, key=lambda x: x["n"])

    # 半年切分
    halves = []
    for hh in sorted({r["h"] for r in rows}):
        gg = [r for r in g if r["h"] == hh]
        hh_all = [r for r in rows if r["h"] == hh and r.get("fwd20d") is not None]
        halves.append({"h": hh, "n": len(gg),
                       "universe": len(hh_all),
                       "occurrence": pct(len(gg) / len(hh_all) * 100, 1) if hh_all else 0,
                       "avg": pct(mean([r["fwd20d"] for r in gg])) if gg else None,
                       "excess_cs": pct(mean([r["fwd20d"] - cs[r["date"]] for r in gg])) if gg else None,
                       "winrate": pct(sum(1 for r in gg if r["fwd20d"] > 0) / len(gg) * 100, 1) if gg else None})

    return {
        "state": s, "n": len(g), "n_etfs": len(byc),
        "obs_per_etf": pct(len(g) / len(byc), 1),
        "episodes": len(lens), "avg_episode_len": pct(mean(lens), 2),
        "max_episode_len": max(lens), "episodes_ge2": sum(1 for x in lens if x >= 2),
        "top_quarter": top_q["q"], "top_quarter_share": pct(top_q["n"] / len(g) * 100, 1),
        "top2_quarter_share": pct(sum(x["n"] for x in sorted(qrows, key=lambda z: -z["n"])[:2]) / len(g) * 100, 1),
        "n_quarters_with_signal": sum(1 for x in qrows if x["n"] > 0),
        "quarters": qrows, "months": mrows, "halves": halves,
        "ex_top_quarter": ex_quarter(rows, s, top_q["q"]),
    }


def ex_quarter(rows, s, q):
    cs = build_benchmarks(rows)[1]
    g = [r for r in rows if r["effective_state"] == s and r.get("fwd20d") is not None and r["q"] != q]
    vals = [r["fwd20d"] for r in g]
    return {"q_removed": q, "n": len(g), "avg": pct(mean(vals)),
            "excess_cs": pct(mean([r["fwd20d"] - cs[r["date"]] for r in g])),
            "winrate": pct(sum(1 for v in vals if v > 0) / len(vals) * 100, 1)}


# ─────────────────────────── 聚类推断 ───────────────────────────

def bootstrap(rows, s="T3b", field="fwd20d", B=3000, seed=SEED):
    _, cs, _, _ = build_benchmarks(rows, field)
    g = [r for r in rows if r["effective_state"] == s and r.get(field) is not None]

    def stat(sample):
        vals = [r[field] for r in sample]
        return mean(vals), mean([r[field] - cs[r["date"]] for r in sample]), \
            sum(1 for v in vals if v > 0) / len(vals) * 100

    out = {}
    for mode, key in (("etf", "code"), ("month", "m"), ("quarter", "q")):
        clusters = defaultdict(list)
        for r in g:
            clusters[r[key]].append(r)
        keys = list(clusters)
        rnd = random.Random(seed)
        sims = []
        for _ in range(B):
            sample = []
            for _ in range(len(keys)):
                sample += clusters[rnd.choice(keys)]
            sims.append(stat(sample))
        lo, hi = int(B * 0.025), int(B * 0.975)
        a, e, w = sorted(x[0] for x in sims), sorted(x[1] for x in sims), sorted(x[2] for x in sims)
        out[mode] = {"clusters": len(keys),
                     "abs_ci": [pct(a[lo]), pct(a[hi])],
                     "cs_ci": [pct(e[lo]), pct(e[hi])],
                     "win_ci": [pct(w[lo], 1), pct(w[hi], 1)],
                     "cs_p_le0": pct(sum(1 for x in sims if x[1] <= 0) / B * 100, 1)}
    pt = stat(g)
    out["point"] = {"abs": pct(pt[0]), "cs_excess": pct(pt[1]), "winrate": pct(pt[2], 1)}
    out["n"] = len(g)
    return out


# ─────────────────────────── Walk-forward ───────────────────────────

def walk_forward(rows, field="fwd20d", min_train_obs=150):
    """扩张窗口：只用截止日之前的数据选状态，检验下一季。选状态准则 = 训练期同日横截面超额。"""
    cs = build_benchmarks(rows, field)[1]
    qs = sorted({r["q"] for r in rows})
    timeline = []
    for i in range(len(qs) - 1):
        train_q, test_q = qs[: i + 1], qs[i + 1]
        train = [r for r in rows if r["q"] in train_q and r.get(field) is not None]
        test = [r for r in rows if r["q"] == test_q and r.get(field) is not None]
        if not test:
            continue
        ex = {s: mean([r[field] - cs[r["date"]] for r in train if r["effective_state"] == s]) for s in STATES}
        cnt = {s: sum(1 for r in train if r["effective_state"] == s) for s in STATES}
        ex = {s: v for s, v in ex.items() if cnt[s] >= min_train_obs}
        if not ex:
            continue
        best = max(ex, key=ex.get)
        t3b_rank = 1 + sum(1 for v in ex.values() if v > ex.get("T3b", -99))
        gt = [r for r in test if r["effective_state"] == best]
        gt3 = [r for r in test if r["effective_state"] == "T3b"]
        timeline.append({
            "train_end": train_q[-1], "test": test_q,
            "picked": best, "train_excess": pct(ex[best]),
            "train_t3b_n": cnt["T3b"], "train_t3b_excess": pct(ex.get("T3b", 0.0)),
            "train_t3b_rank": t3b_rank, "n_states_ranked": len(ex),
            "n_test": len(gt),
            "oos_excess": pct(mean([r[field] - cs[r["date"]] for r in gt])) if gt else None,
            "oos_abs": pct(mean([r[field] for r in gt])) if gt else None,
            "t3b_n": len(gt3),
            "t3b_excess": pct(mean([r[field] - cs[r["date"]] for r in gt3])) if gt3 else None,
        })
    valid = [x for x in timeline if x["oos_excess"] is not None and x["n_test"] >= 10]
    hits = [x for x in valid if x["picked"] == "T3b"]
    return {
        "timeline": timeline, "n_periods": len(valid),
        "picked_t3b": len(hits),
        "avg_oos_excess": pct(mean([x["oos_excess"] for x in valid])) if valid else None,
        "avg_oos_excess_when_t3b": pct(mean([x["oos_excess"] for x in hits])) if hits else None,
        "hit_rate": pct(sum(1 for x in valid if x["oos_excess"] > 0) / len(valid) * 100, 1) if valid else None,
        "t3b_quarters_oos": pct(mean([x["t3b_excess"] for x in valid if x["t3b_excess"] is not None]), 1) if valid else None,
    }


def holdout(rows, field="fwd20d"):
    """严格样本外：2025 全年训练 → 2026 全部检验。"""
    cs = build_benchmarks(rows, field)[1]
    tr = [r for r in rows if r["date"][:4] == "2025" and r.get(field) is not None]
    te = [r for r in rows if r["date"][:4] == "2026" and r.get(field) is not None]
    out = {"train_n": len(tr), "test_n": len(te), "states": []}
    for s in STATES:
        a = [r for r in tr if r["effective_state"] == s]
        b = [r for r in te if r["effective_state"] == s]
        if len(a) < 100:
            continue
        out["states"].append({
            "state": s, "train_n": len(a),
            "train_excess": pct(mean([r[field] - cs[r["date"]] for r in a])),
            "train_abs": pct(mean([r[field] for r in a])),
            "test_n": len(b),
            "test_excess": pct(mean([r[field] - cs[r["date"]] for r in b])) if b else None,
            "test_abs": pct(mean([r[field] for r in b])) if b else None,
            "test_win": pct(sum(1 for r in b if r[field] > 0) / len(b) * 100, 1) if b else None,
        })
    out["rank_train"] = [x["state"] for x in sorted(out["states"], key=lambda z: -z["train_excess"])]
    out["rank_test"] = [x["state"] for x in sorted([y for y in out["states"] if y["test_excess"] is not None],
                                                   key=lambda z: -z["test_excess"])]
    # T3b 各期限的样本外表现
    oos_h = []
    for h in HORIZONS:
        f = "fwd%dd" % h
        c = build_benchmarks(rows, f)[1]
        a = [r for r in rows if r["date"][:4] == "2025" and r.get(f) is not None and r["effective_state"] == "T3b"]
        b = [r for r in rows if r["date"][:4] == "2026" and r.get(f) is not None and r["effective_state"] == "T3b"]
        oos_h.append({"h": h,
                      "train_excess": pct(mean([r[f] - c[r["date"]] for r in a])) if a else None,
                      "test_excess": pct(mean([r[f] - c[r["date"]] for r in b])) if b else None,
                      "test_abs": pct(mean([r[f] for r in b])) if b else None,
                      "test_n": len(b)})
    out["t3b_by_horizon"] = oos_h
    return out


# ─────────────────────────── 多重检验 ───────────────────────────

def max_stat(rows, field="fwd20d", reps=500, seed=SEED):
    """同日标签置换：保留每个日期的状态构成，只打乱「哪只 ETF 拿到哪个标签」。"""
    _, cs, _, _ = build_benchmarks(rows, field)
    dated = defaultdict(list)
    for r in rows:
        if r.get(field) is not None:
            dated[r["date"]].append(r)
    flat = [r for dd in dated.values() for r in dd]
    obs = {}
    for s in STATES:
        g = [r for r in flat if r["effective_state"] == s]
        if len(g) >= 200:
            obs[s] = mean([r[field] - cs[r["date"]] for r in g])

    rnd = random.Random(seed)
    keys = list(dated)
    per_state_null = {s: [] for s in obs}
    nulls = []
    for _ in range(reps):
        acc = defaultdict(list)
        for d in keys:
            labels = [r["effective_state"] for r in dated[d]]
            rnd.shuffle(labels)
            for r, lab in zip(dated[d], labels):
                acc[lab].append(r[field] - cs[d])
        for s in obs:
            if acc.get(s):
                per_state_null[s].append(mean(acc[s]))
        cand = [mean(v) for k, v in acc.items() if len(v) >= 200]
        nulls.append(max(cand) if cand else 0.0)

    nulls.sort()
    real_max = max(obs.values())
    rank = 1 + sum(1 for v in obs.values() if v > obs["T3b"])
    return {
        "observed": {k: pct(v) for k, v in sorted(obs.items(), key=lambda t: -t[1])},
        "obs_max": pct(real_max), "obs_max_state": max(obs, key=obs.get),
        "null_max_p50": pct(nulls[reps // 2]),
        "null_max_p95": pct(nulls[int(reps * 0.95)]),
        "null_max_p99": pct(nulls[int(reps * 0.99)]),
        "p_value_max": pct(sum(1 for x in nulls if x >= real_max) / reps, 3),
        "p_value_t3b": pct(sum(1 for x in per_state_null["T3b"] if x >= obs["T3b"]) / reps, 3),
        "n_states_tested": len(obs), "reps": reps, "t3b_rank": rank,
    }


def horizon_grid(rows):
    """状态 × 期限 的网格：报告只报了 5 个期限，但"最好的那一格"是事后挑出来的。"""
    grid = {}
    for h in HORIZONS:
        t = state_table(rows, "fwd%d" % 0 if False else "fwd%dd" % h)
        grid[h] = {r["state"]: r["excess_cs"] for r in t["rows"]}
    cells = [(v, s, h) for h, d in grid.items() for s, v in d.items() if v is not None]
    cells.sort(reverse=True)
    return {"grid": grid, "best_cell": {"state": cells[0][1], "horizon": cells[0][2], "excess_cs": cells[0][0]},
            "top5": [{"state": s, "horizon": h, "excess_cs": v} for v, s, h in cells[:5]],
            "n_cells": len(cells)}


# ─────────────────────────── 广度 ───────────────────────────

def breadth(rows, s="T3b", field="fwd20d"):
    cs = build_benchmarks(rows, field)[1]
    g = [r for r in rows if r["effective_state"] == s and r.get(field) is not None]
    per = defaultdict(list)
    for r in g:
        per[r["code"]].append(r[field] - cs[r["date"]])
    etf_stats = [(c, mean(v), len(v)) for c, v in per.items()]
    by_cat = defaultdict(list)
    for r in g:
        by_cat[r["cat"]].append(r)
    cats = []
    for c, gg in sorted(by_cat.items(), key=lambda t: -len(t[1])):
        vals = [r[field] for r in gg]
        cats.append({"cat": c, "n": len(gg), "share": pct(len(gg) / len(g) * 100, 1),
                     "avg": pct(mean(vals)),
                     "excess_cs": pct(mean([r[field] - cs[r["date"]] for r in gg])),
                     "winrate": pct(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
                     "etfs": len({r["code"] for r in gg})})
    dist = sorted(x[1] for x in etf_stats)
    bins = [-12, -6, -3, -1, 0, 1, 3, 6, 12, 30]
    hist = []
    for i in range(len(bins) - 1):
        hist.append({"lo": bins[i], "hi": bins[i + 1],
                     "n": sum(1 for v in dist if bins[i] <= v < bins[i + 1])})
    return {
        "n_etfs": len(etf_stats),
        "positive_share": pct(sum(1 for _, m, _ in etf_stats if m > 0) / len(etf_stats) * 100, 1),
        "etf_excess_p25": pct(dist[len(dist) // 4]),
        "etf_excess_median": pct(median(dist)),
        "etf_excess_p75": pct(dist[len(dist) * 3 // 4]),
        "etf_excess_min": pct(dist[0]), "etf_excess_max": pct(dist[-1]),
        "categories": cats, "hist": hist,
        "per_etf_top": [{"code": c, "excess": pct(m), "n": n} for c, m, n in sorted(etf_stats, key=lambda t: -t[2])[:8]],
        "per_etf_bottom": [{"code": c, "excess": pct(m), "n": n} for c, m, n in sorted(etf_stats, key=lambda t: t[1])[:8]],
    }


# ─────────────────────────── 朴素规则 / 动量控制 ───────────────────────────

def naive_rules(rows, klines, field="fwd20d"):
    cs = build_benchmarks(rows, field)[1]
    chrono = {c: [b["last"] for b in reversed(bars)] for c, bars in klines.items()}

    groups = {"naive_ma60_up": [], "naive_slope_only": [], "t3b": [], "all": []}
    for r in rows:
        if r.get(field) is None:
            continue
        cl = chrono.get(r["code"])
        i = r["idx"]
        if not cl or i >= len(cl):
            continue
        excess = r[field] - cs[r["date"]]
        groups["all"].append((r[field], excess, r))
        if i >= 79:
            m_now = mean(cl[i - 59:i + 1])
            m_prev = mean(cl[i - 79:i - 19])
            slope = (m_now / m_prev - 1) * 100 if m_prev else 0
            if slope > 0:
                groups["naive_slope_only"].append((r[field], excess, r))
            if cl[i] > m_now and slope > 0:
                groups["naive_ma60_up"].append((r[field], excess, r))
        if r["effective_state"] == "T3b":
            groups["t3b"].append((r[field], excess, r))

    overlap = [x for x in groups["naive_ma60_up"] if x[2]["effective_state"] == "T3b"]
    naive_not = [x for x in groups["naive_ma60_up"] if x[2]["effective_state"] != "T3b"]

    def agg(g):
        if not g:
            return None
        vals = [x[0] for x in g]
        return {"n": len(g), "avg": pct(mean(vals)),
                "excess_cs": pct(mean([x[1] for x in g])),
                "winrate": pct(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
                "etfs": len({x[2]["code"] for x in g})}

    return {"t3b": agg(groups["t3b"]), "naive_ma60_up": agg(groups["naive_ma60_up"]),
            "naive_slope_only": agg(groups["naive_slope_only"]),
            "naive_and_t3b": agg(overlap), "naive_not_t3b": agg(naive_not),
            "all": agg(groups["all"]),
            "t3b_inside_naive_pct": pct(len(overlap) / len(groups["t3b"]) * 100, 1) if groups["t3b"] else None,
            "naive_coverage_of_t3b": pct(len(overlap) / len(groups["naive_ma60_up"]) * 100, 1) if groups["naive_ma60_up"] else None}


def momentum_control(rows, klines, field="fwd20d", buckets=5):
    cs = build_benchmarks(rows, field)[1]
    chrono = {c: [b["last"] for b in reversed(bars)] for c, bars in klines.items()}
    recs = []
    for r in rows:
        if r.get(field) is None:
            continue
        cl = chrono.get(r["code"])
        i = r["idx"]
        if not cl or i < 20 or i >= len(cl):
            continue
        recs.append({"mom": (cl[i] / cl[i - 20] - 1) * 100, "exc": r[field] - cs[r["date"]],
                     "t3b": r["effective_state"] == "T3b"})
    recs.sort(key=lambda x: x["mom"])
    n = len(recs)
    out = []
    for b in range(buckets):
        seg = recs[b * n // buckets:(b + 1) * n // buckets]
        a = [x for x in seg if x["t3b"]]
        o = [x for x in seg if not x["t3b"]]
        out.append({"bucket": b + 1, "mom_lo": pct(seg[0]["mom"], 1), "mom_hi": pct(seg[-1]["mom"], 1),
                    "n_t3b": len(a), "n_other": len(o),
                    "t3b_excess": pct(mean([x["exc"] for x in a])) if a else None,
                    "other_excess": pct(mean([x["exc"] for x in o])),
                    "diff": pct(mean([x["exc"] for x in a]) - mean([x["exc"] for x in o])) if a else None})
    n_t3b = sum(1 for x in recs if x["t3b"])
    return {"buckets": out, "n": n, "n_t3b": n_t3b,
            "t3b_in_top_bucket_pct": pct(sum(1 for x in recs[n - n // buckets:] if x["t3b"]) / max(1, n_t3b) * 100, 1)}


# ─────────────────────────── 经济显著性 ───────────────────────────

def economics(rows, s="T3b", field="fwd20d"):
    g = [r for r in rows if r["effective_state"] == s and r.get(field) is not None]
    allobs = [r for r in rows if r.get(field) is not None]
    dates = sorted({r["date"] for r in allobs})
    yrs = max(0.1, days_between(dates[0], dates[-1]) / 365.25)
    cs = build_benchmarks(rows, field)[1]
    cs_excess = mean([r[field] - cs[r["date"]] for r in g])
    n_etf = len({r["code"] for r in allobs})
    return {
        "freq_pct": pct(len(g) / len(allobs) * 100),
        "n": len(g), "span_years": pct(yrs, 2), "n_etfs": n_etf,
        "dates_with_signal": len({r["date"] for r in g}),
        "dates_with_signal_pct": pct(len({r["date"] for r in g}) / len(dates) * 100, 1),
        "avg_etfs_in_signal_per_date": pct(len(g) / len({r["date"] for r in g}), 1),
        "per_etf_samples_per_year": pct(len(g) / n_etf / yrs, 2),
        "trading_days_per_year_in_state": pct(len(g) / n_etf / yrs * 5, 1),
        "roundtrip_cost_pct": 0.10,
        "cost_vs_excess_ratio": pct(0.10 / max(0.01, abs(cs_excess)) * 100, 1),
    }


# ─────────────────────────── 主流程 ───────────────────────────

def main():
    raw, rows, klines, uni, vol = load()
    allobs = [r for r in rows if r.get("fwd20d") is not None]

    health = {
        "n_signals": len(rows), "n_with_fwd20": len(allobs),
        "n_etfs": len({r["code"] for r in rows}),
        "n_dates": len({r["date"] for r in allobs}),
        "date_from": min(r["date"] for r in rows), "date_to": max(r["date"] for r in rows),
        "eval_step": raw["config"]["eval_step"],
        "obs_per_date": pct(len(allobs) / len({r["date"] for r in allobs}), 1),
        "fwd20_coverage": pct(len(allobs) / len(rows) * 100, 1),
        "categories": [{"cat": k, "n": v, "share": pct(v / len(allobs) * 100, 1)}
                       for k, v in Counter(r["cat"] for r in allobs).most_common()],
        "state_share": [{"state": s, "n": sum(1 for r in allobs if r["effective_state"] == s),
                         "pct": pct(sum(1 for r in allobs if r["effective_state"] == s) / len(allobs) * 100, 1)}
                        for s in STATES],
        "n_vol_labeled": sum(1 for r in rows if r["code"] in vol),
    }

    tables = {h: state_table(rows, "fwd%dd" % h) for h in HORIZONS}
    conc = concentration(rows)
    boot = bootstrap(rows)
    wf = walk_forward(rows)
    ho = holdout(rows)
    ms = max_stat(rows)
    hg = horizon_grid(rows)
    br = breadth(rows)
    naive = naive_rules(rows, klines)
    mom = momentum_control(rows, klines)
    econ = economics(rows)

    t3b = [x for x in tables[20]["rows"] if x["state"] == "T3b"][0]
    decomp = {
        "abs": t3b["avg"], "excess_pooled": t3b["excess_pooled"],
        "cs_on_signal_days": t3b["cs_mean_on_those_days"],
        "excess_cs": t3b["excess_cs"],
        "timing_part": pct(t3b["excess_pooled"] - t3b["excess_cs"]),
        "timing_share": pct((t3b["excess_pooled"] - t3b["excess_cs"]) / t3b["excess_pooled"] * 100, 1),
        "selection_share": pct(t3b["excess_cs"] / t3b["excess_pooled"] * 100, 1),
    }

    out = {
        "meta": {"title": "T-State Validation / Walk-Forward Research", "as_of": "2026-10-22",
                 "source": "backtest_trend_state_results.json + etf_kline_data_500.json",
                 "seed": SEED, "claim_under_test": "T3b 未来 20 日超额 +4.33pp、胜率 75.9%"},
        "health": health, "decomposition": decomp, "tables": tables,
        "concentration": conc, "bootstrap": boot, "walk_forward": wf, "holdout": ho,
        "max_stat": ms, "horizon_grid": hg, "breadth": br, "naive": naive,
        "momentum": mom, "economics": econ,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("written", OUT)
    summary = {
        "decomp": decomp, "ex_top_quarter": conc["ex_top_quarter"],
        "bootstrap": {k: ({kk: vv for kk, vv in v.items() if kk in ("cs_ci", "abs_ci", "cs_p_le0", "clusters")}
                           if isinstance(v, dict) else v) for k, v in boot.items() if k != "point"},
        "walk_forward": {k: v for k, v in wf.items() if k != "timeline"},
        "holdout_t3b": [x for x in ho["states"] if x["state"] == "T3b"],
        "max_stat": ms, "best_cell": hg["best_cell"], "naive": naive, "economics": econ,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
