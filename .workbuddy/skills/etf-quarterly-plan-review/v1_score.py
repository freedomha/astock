#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1 连续评分引擎（Production 冻结规格）

规格来源：`v1_spec.json`（本目录）＋ `V1-SPEC.md`。
研究依据：`reports/research/Gate-Redesign-20261022.html`。

设计要点（改动前请先读 V1-SPEC.md 第 8 节变更管控）：
  · Trend / Momentum / Risk 由均线与收益率直接算出，纯函数，无状态；
  · Diversification 需要组合上下文（ΔRC50 / 每 1,000 元），由调用方传入；
  · T0-T8 状态不参与评分，只作为描述性特征。

本模块只用标准库。
"""

import json
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "v1_spec.json")

DEFAULT_SPEC = {
    "score": {
        "weights": {"trend": 30, "momentum": 30, "risk": 20, "diversification": 20},
        "trend": {"dist_to_ma60_full_pct": 8.0, "ma60_slope_full_pct": 5.0, "ma120_slope_full_pct": 8.0},
        "momentum": {"shape": "bell", "legs": [
            {"window": 20, "peak_pct": 6.0, "half_width_pct": 14.0},
            {"window": 60, "peak_pct": 14.0, "half_width_pct": 26.0},
            {"window": 120, "peak_pct": 26.0, "half_width_pct": 46.0}]},
        "risk": {"vol_band_pct": [18.0, 25.0, 35.0], "vol_points": [8.0, 4.0, 0.0],
                 "dd_peak_pct": -10.0, "dd_half_width_pct": 18.0, "dd_points": 6.0,
                 "jump_start_pct": 20.0, "jump_zero_pct": 35.0, "jump_points": 6.0},
        "diversification": {"full_at_pp": -0.15, "points": 20.0},
    },
    "threshold": {"absolute_floor": 60, "relative_band": 5, "no_candidate_action": "cash"},
}


def load_spec(path=SPEC_PATH):
    """读 v1_spec.json；缺失或损坏时退回内置默认值（与文件同值）。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        s = d.get("score") or {}
        for k, v in DEFAULT_SPEC["score"].items():
            s.setdefault(k, v)
        d["score"] = s
        t = d.get("threshold") or {}
        for k, v in DEFAULT_SPEC["threshold"].items():
            t.setdefault(k, v)
        d["threshold"] = t
        return d
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_SPEC))


# ─────────────────────────── 基础 ───────────────────────────
def clip(x, lo, hi):
    return max(lo, min(hi, x))


def sma(closes, n, i):
    """i 处（含）的 n 日均线；不足返回 None。"""
    if i + 1 < n:
        return None
    return sum(closes[i - n + 1:i + 1]) / n


def slope_pct(closes, n, i, lag=20):
    """MA(n) 在 i 相对 i-lag 的百分比斜率。"""
    a, b = sma(closes, n, i), sma(closes, n, i - lag)
    if not a or not b:
        return None
    return (a / b - 1) * 100


def realized_vol(closes, i, window=20):
    """年化已实现波动（百分数）。"""
    if i + 1 < window + 1:
        return None
    rets = [closes[j] / closes[j - 1] - 1 for j in range(i - window + 1, i + 1)
            if closes[j - 1] > 0]
    if len(rets) < window // 2:
        return None
    return st.pstdev(rets) * (252 ** 0.5) * 100


def features(closes, i):
    """计算 i 处的原始特征。closes 为升序。需要至少 120 根。"""
    if i < 120:
        return None
    p = closes[i]
    m60, m120 = sma(closes, 60, i), sma(closes, 120, i)
    if not m60 or not m120:
        return None
    ret = {}
    for w in (20, 60, 120):
        ret[w] = (p / closes[i - w] - 1) * 100 if closes[i - w] > 0 else 0.0
    hi = max(closes[max(0, i - 249):i + 1])
    return dict(
        price=p, ma60=m60, ma120=m120,
        dist_ma60=(p / m60 - 1) * 100,
        s60=slope_pct(closes, 60, i) or 0.0,
        s120=slope_pct(closes, 120, i) or 0.0,
        r20=ret[20], r60=ret[60], r120=ret[120],
        vol20=realized_vol(closes, i, 20) or 0.0,
        dd250=(p / hi - 1) * 100 if hi > 0 else 0.0,
    )


# ─────────────────────────── 三个自足组件 ───────────────────────────
def score_trend(f, spec):
    c = spec["score"]["trend"]
    t1 = 10 * clip(f["dist_ma60"] / c["dist_to_ma60_full_pct"], 0, 1)
    t2 = 10 * clip(f["s60"] / c["ma60_slope_full_pct"], 0, 1)
    t3 = 10 * clip(f["s120"] / c["ma120_slope_full_pct"], 0, 1)
    return t1 + t2 + t3


def _tent(x, peak, hw):
    return max(0.0, 1 - abs(x - peak) / hw) if hw > 0 else 0.0


def score_momentum(f, spec):
    m = spec["score"]["momentum"]
    leg = m["legs"]
    vals = [f["r20"], f["r60"], f["r120"]]
    if m.get("shape", "bell") == "bell":
        return sum(10 * _tent(vals[k], leg[k]["peak_pct"], leg[k]["half_width_pct"]) for k in range(3))
    # 单调版仅用于研究对照，不作为默认
    caps = (18.0, 40.0, 70.0)
    return sum(10 * clip(vals[k] / caps[k], 0, 1) for k in range(3))


def score_risk(f, spec):
    r = spec["score"]["risk"]
    b1, b2, b3 = r["vol_band_pct"]
    p8, p4, p0 = r["vol_points"]
    v = f["vol20"]
    if v <= b1:
        a = p8
    elif v <= b2:
        a = p8 - (v - b1) / max(1e-9, b2 - b1) * (p8 - p4)
    elif v <= b3:
        a = p4 - (v - b2) / max(1e-9, b3 - b2) * (p4 - p0)
    else:
        a = 0.0
    d = r["dd_points"] * _tent(f["dd250"], r["dd_peak_pct"], r["dd_half_width_pct"])
    if f["r20"] > r["jump_start_pct"]:
        j = r["jump_points"] * clip(1 - (f["r20"] - r["jump_start_pct"]) /
                                    max(1e-9, r["jump_zero_pct"] - r["jump_start_pct"]), 0, 1)
    else:
        j = r["jump_points"]
    return a + d + j


def score_diversification(delta_rc50_pp, spec):
    """delta_rc50_pp：从现金挪 1,000 元到该标的，RC50 的变化（pp，负=改善）。"""
    if delta_rc50_pp is None:
        return 0.0
    c = spec["score"]["diversification"]
    return c["points"] * clip(-delta_rc50_pp / abs(c["full_at_pp"]), 0, 1)


def score(closes, i, delta_rc50_pp=None, spec=None):
    """返回 {trend, momentum, risk, div, total, features}；数据不足返回 None。"""
    spec = spec or DEFAULT_SPEC
    f = features(closes, i)
    if not f:
        return None
    t, m, r = score_trend(f, spec), score_momentum(f, spec), score_risk(f, spec)
    d = score_diversification(delta_rc50_pp, spec)
    return dict(trend=round(t, 1), momentum=round(m, 1), risk=round(r, 1),
                div=round(d, 1), drc50=(None if delta_rc50_pp is None else round(delta_rc50_pp, 4)),
                total=round(t + m + r + d, 1), features=f)


# ─────────────────────────── 阈值 ───────────────────────────
def select(candidates, spec=None):
    """硬门之后做阈值筛选。

    candidates: [{'code':..., 'score': float, 'gap': float}]
    规则：score >= floor 且 score >= max_score - band；其余进现金。
    返回 (eligible_list, max_score, reason)
    """
    spec = spec or DEFAULT_SPEC
    t = spec["threshold"]
    if not candidates:
        return [], None, "无候选（硬门全否决）"
    mx = max(c["score"] for c in candidates)
    floor = t["absolute_floor"]
    band = t["relative_band"]
    ok = [c for c in candidates if c["score"] >= floor and c["score"] >= mx - band]
    if not ok:
        return [], mx, f"最高分 {mx:.1f} < 绝对下限 {floor}"
    return ok, mx, f"{len(ok)} 只过门（最高 {mx:.1f}）"
