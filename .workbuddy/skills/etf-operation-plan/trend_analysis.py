#!/usr/bin/env python3
"""
ETF medium-term trend-state + weekly analysis for operation planning.

Purpose
-------
The five pattern scorers (score_patterns.py) detect *bottoming* formations and
are inherently bullish-biased. This module provides the primary decision layer
that the operation plan must anchor on: a **trend-state model (T0-T8)** plus
weekly-level features, trend persistence / relative-strength evidence, and a
**state machine** that persists history and enforces legal migrations.

It does NOT emit buy/sell conclusions. It outputs structured evidence that the
report (SKILL.md workflow) interprets under a hard constraint matrix.

Key rules implemented here
--------------------------
- Weekly (周线) is the primary direction signal; **trend uses the last complete
  natural trading week only** — the current incomplete week is reported as a
  "preview" and never triggers a final T3/T4/T7/T8 migration (except structural
  breakdown).
- T3 is split into T3a (price structure strengthening but MA60 still down) and
  T3b (MA60 flat or turning up). Only T3b allows active tactical adds.
- State machine: persists last state + consecutive-week count; enforces legal
  migrations (normal advance needs 2 complete weeks; T0→T4 forbidden; →T8
  immediate; T7→T4 must route through T6).

Usage
-----
    python3 trend_analysis.py --code sh518880 --kline-file /tmp/op_kline.json \
        [--benchmark-file /tmp/bench.json] [--intraday] \
        [--state-file state.json]
"""
import json
import sys
import os
import argparse
import datetime as dt


# ─── Shared numeric utilities (self-contained) ─────────────────────────────

def lin_slope(arr, win):
    """Linear regression slope over last `win` elements, as % change."""
    arr = [float(x) for x in arr if x is not None]
    if len(arr) < win:
        return 0.0
    ys = arr[-win:]
    n = float(win)
    xs = list(range(win))
    sx = (n - 1) * n / 2.0
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    den = n * sxx - sx * sx
    if den == 0:
        return 0.0
    s = (n * sxy - sx * sy) / den
    ym = sy / n
    if ym == 0:
        return 0.0
    return s * win / ym * 100


def atr(highs, lows, closes, window):
    """Average True Range over `window` periods."""
    if len(closes) < window + 1:
        return 0.0
    trs = []
    for i in range(len(closes) - window, len(closes)):
        prev_close = closes[i - 1] if i > 0 else closes[i]
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - prev_close),
                 abs(lows[i] - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def ma_series(values, win):
    """Rolling mean series; leading entries are None. Returns list aligned to input."""
    out = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= win:
            running -= values[i - win]
        if i >= win - 1:
            out[i] = running / win
    return out


def dir_label(slope_pct, flat_thresh=0.3):
    """Map a slope (%) to up / flat / down."""
    if slope_pct > flat_thresh:
        return "up"
    if slope_pct < -flat_thresh:
        return "down"
    return "flat"


# ─── K-line parsing & resampling ───────────────────────────────────────────

def parse_kline(kline_data):
    """Normalize raw westock-data kline (newest-first) to oldest-first records.

    Each record: {date, open, close, high, low, volume}.
    Returns None if fewer than 60 usable bars.
    """
    if not kline_data:
        return None
    if isinstance(kline_data, dict):
        kline_data = kline_data.get("klines", kline_data.get("data", []))
    if not isinstance(kline_data, list):
        return None

    records = []
    for k in kline_data:
        try:
            o = float(k.get("first", k.get("open")))
            c = float(k["last"])
            records.append({
                "date": str(k["date"]),
                "open": o,
                "close": c,
                "high": float(k["high"]),
                "low": float(k["low"]),
                "volume": float(k.get("volume", 0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    if len(records) < 60:
        return None
    records.sort(key=lambda x: x["date"])
    return records


def resample_weekly(records):
    """Aggregate daily bars into weekly bars (ISO week grouping).

    Each weekly bar: {week_start, open, close, high, low, volume}.
    """
    weeks = {}
    for r in records:
        try:
            d = dt.date.fromisoformat(r["date"][:10])
        except ValueError:
            continue
        key = (d.isocalendar()[0], d.isocalendar()[1])  # (year, week)
        if key not in weeks:
            weeks[key] = {
                "week_start": r["date"],
                "open": r["open"],
                "close": r["close"],
                "high": r["high"],
                "low": r["low"],
                "volume": r["volume"],
            }
        else:
            w = weeks[key]
            w["close"] = r["close"]
            w["high"] = max(w["high"], r["high"])
            w["low"] = min(w["low"], r["low"])
            w["volume"] += r["volume"]
    return [weeks[k] for k in sorted(weeks)]


def week_completeness(records, intraday):
    """Return (daily_bar_status, weekly_bar_status).

    daily:  intraday if the last bar is the in-progress session, else complete.
    weekly: complete only when the last bar closes the natural week (Friday)
            and is not intraday; otherwise the current week is incomplete and
            must be excluded from trend/classification.
    """
    if not records:
        return "unknown", "unknown"
    last = dt.date.fromisoformat(records[-1]["date"][:10])
    daily = "intraday" if intraday else "complete"
    last_is_friday = last.weekday() == 4  # Mon=0 ... Fri=4
    weekly = "complete" if (last_is_friday and not intraday) else "incomplete_current_week"
    return daily, weekly


def data_quality(records, intraday):
    """Report completeness / integrity of the daily series."""
    n = len(records)
    first_date = records[0]["date"]
    last_date = records[-1]["date"]
    last_is_today = last_date[:10] == dt.date.today().isoformat()

    gaps = 0
    for i in range(1, n):
        try:
            a = dt.date.fromisoformat(records[i - 1]["date"][:10])
            b = dt.date.fromisoformat(records[i]["date"][:10])
            if (b - a).days > 10:
                gaps += 1
        except ValueError:
            continue

    daily_status, weekly_status = week_completeness(records, intraday)

    return {
        "num_bars": n,
        "first_date": first_date,
        "last_date": last_date,
        "last_bar_is_today": last_is_today,
        "daily_bar_status": daily_status,
        "weekly_bar_status": weekly_status,
        "num_large_gaps": gaps,
        "sufficient_for_weekly": n >= 120,
    }


# ─── Trend persistence / structure indicators ─────────────────────────────

def compute_ma_features(closes, highs, lows):
    """MA alignment, slopes, price-vs-MA distances."""
    n = len(closes)
    cur = closes[-1]

    ma60 = sum(closes[-60:]) / 60 if n >= 60 else None
    ma120 = sum(closes[-120:]) / 120 if n >= 120 else None
    ma250 = sum(closes[-250:]) / 250 if n >= 250 else None

    s60 = ma_series(closes, 60)
    s120 = ma_series(closes, 120)
    s250 = ma_series(closes, 250) if n >= 250 else None

    ma60_slope = lin_slope([x for x in s60 if x is not None], 20)
    ma120_slope = lin_slope([x for x in s120 if x is not None], 20)
    ma250_slope = lin_slope([x for x in s250 if x is not None], 20) if s250 else 0.0

    alignment = "price"
    if ma60 is not None:
        alignment += (" > ma60" if cur > ma60 else " < ma60")
    if ma120 is not None and ma60 is not None:
        alignment += (" > ma120" if ma60 > ma120 else " < ma120")
    if ma250 is not None and ma120 is not None:
        alignment += (" > ma250" if ma120 > ma250 else " < ma250")

    bullish_align = (cur > (ma60 or cur)) and ((ma60 is None) or (ma120 is None) or ma60 > ma120) \
        and ((ma120 is None) or (ma250 is None) or ma120 > ma250)

    bearish_align = (cur < (ma60 or cur)) and ((ma60 is None) or (ma120 is None) or ma60 < ma120) \
        and ((ma120 is None) or (ma250 is None) or ma120 < ma250)

    d_ma60 = (cur - ma60) / ma60 * 100 if ma60 else None
    d_ma120 = (cur - ma120) / ma120 * 100 if ma120 else None

    return {
        "ma60": round(ma60, 3) if ma60 else None,
        "ma120": round(ma120, 3) if ma120 else None,
        "ma250": round(ma250, 3) if ma250 else None,
        "ma60_slope_pct": round(ma60_slope, 2),
        "ma120_slope_pct": round(ma120_slope, 2),
        "ma250_slope_pct": round(ma250_slope, 2),
        "ma60_dir": dir_label(ma60_slope),
        "ma120_dir": dir_label(ma120_slope),
        "ma250_dir": dir_label(ma250_slope),
        "alignment": alignment,
        "bullish_alignment": bullish_align,
        "bearish_alignment": bearish_align,
        "price_vs_ma60_pct": round(d_ma60, 2) if d_ma60 is not None else None,
        "price_vs_ma120_pct": round(d_ma120, 2) if d_ma120 is not None else None,
    }


def compute_structure(closes, highs, lows):
    """Higher-high / higher-low structure over two comparison windows."""
    n = len(closes)
    if n < 60:
        return {"higher_high": None, "higher_low": None, "pattern": "insufficient_data",
                "recent_high": None, "recent_low": None, "prior_high": None, "prior_low": None}
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    prior_high = max(highs[-40:-20])
    prior_low = min(lows[-40:-20])

    hh = recent_high > prior_high
    hl = recent_low > prior_low

    if hh and hl:
        pattern = "higher_high_higher_low"
    elif hh and not hl:
        pattern = "higher_high_lower_low"
    elif not hh and hl:
        pattern = "lower_high_higher_low"
    else:
        pattern = "lower_high_lower_low"

    return {
        "higher_high": hh,
        "higher_low": hl,
        "pattern": pattern,
        "recent_high": round(recent_high, 3),
        "recent_low": round(recent_low, 3),
        "prior_high": round(prior_high, 3),
        "prior_low": round(prior_low, 3),
    }


def compute_extension(closes, highs, lows):
    """How far price is extended above/below MA60, measured in ATR units."""
    n = len(closes)
    if n < 61:
        return {"state": "unknown", "extended": None, "price_vs_ma60_atr": None}
    cur = closes[-1]
    ma60 = sum(closes[-60:]) / 60
    a20 = atr(highs, lows, closes, 20)
    dist_atr = (cur - ma60) / a20 if a20 > 0 else 0.0

    if dist_atr >= 3.0:
        state = "over_extended"
    elif dist_atr >= 2.0:
        state = "extended"
    elif dist_atr <= -2.0:
        state = "deeply_below_ma"
    elif dist_atr <= -1.0:
        state = "below_ma"
    else:
        state = "not_extended"

    return {"state": state, "extended": dist_atr >= 2.0,
            "price_vs_ma60_atr": round(dist_atr, 2)}


def compute_volatility(highs, lows, closes):
    """Volatility regime: compressed / normal / expanding. Also exposes ATR20
    for volatility-normalised buffers in the report layer."""
    a20 = atr(highs, lows, closes, 20)
    a60 = atr(highs, lows, closes, 60)
    ratio = a20 / a60 if a60 > 0 else 1.0
    if ratio < 0.75:
        state = "compressed"
    elif ratio > 1.25:
        state = "expanding"
    else:
        state = "normal"
    return {"atr20": round(a20, 4), "atr60": round(a60, 4),
            "atr_ratio": round(ratio, 2), "state": state}


def compute_relative_strength(closes, benchmark_closes):
    """Self momentum (60d vs 120d) and optional benchmark-relative strength.

    If no benchmark is provided, the field is labelled "self_momentum" and must
    NOT be described as "relative strength" in the report — it is self-relative
    momentum only.
    """
    n = len(closes)
    if n < 120:
        ret60 = ret120 = None
    else:
        ret60 = (closes[-1] - closes[-61]) / closes[-61] * 100
        ret120 = (closes[-1] - closes[-121]) / closes[-121] * 100

    if ret60 is not None and ret120 is not None:
        if ret60 > ret120 + 2:
            self_momentum = "improving"
        elif ret60 < ret120 - 2:
            self_momentum = "weakening"
        else:
            self_momentum = "neutral"
    else:
        self_momentum = "unknown"

    result = {
        "self_momentum": self_momentum,
        "ret_60d_pct": round(ret60, 2) if ret60 is not None else None,
        "ret_120d_pct": round(ret120, 2) if ret120 is not None else None,
    }

    if benchmark_closes and len(benchmark_closes) >= 120:
        b60 = (benchmark_closes[-1] - benchmark_closes[-61]) / benchmark_closes[-61] * 100
        b120 = (benchmark_closes[-1] - benchmark_closes[-121]) / benchmark_closes[-121] * 100
        excess60 = (ret60 - b60) if ret60 is not None else None
        if excess60 is not None:
            if excess60 > 2:
                vs_bench = "outperforming"
            elif excess60 < -2:
                vs_bench = "underperforming"
            else:
                vs_bench = "in_line"
        else:
            vs_bench = "unknown"
        result["benchmark"] = {
            "ret_60d_pct": round(b60, 2),
            "ret_120d_pct": round(b120, 2),
            "excess_60d_pct": round(excess60, 2) if excess60 is not None else None,
            "vs_benchmark": vs_bench,
        }

    return result


# ─── Weekly features (complete weeks only + preview) ───────────────────────

def compute_weekly_features(weekly_bars, weekly_bar_status):
    """Weekly close, 10/20/40w MA, slope, ATR, volume, breakout/failure.

    `weekly_bars` must already EXCLUDE the incomplete current week when
    weekly_bar_status == "incomplete_current_week". If it still contains the
    partial week, it is dropped here and exposed as `preview`.
    """
    if weekly_bar_status == "incomplete_current_week" and len(weekly_bars) >= 1:
        preview = weekly_bars[-1]
        complete = weekly_bars[:-1]
    else:
        preview = None
        complete = weekly_bars

    if len(complete) < 12:
        base = {"sufficient": False, "num_weeks": len(complete)}
        base["preview"] = _preview_block(preview)
        return base

    wc = [b["close"] for b in complete]
    wh = [b["high"] for b in complete]
    wl = [b["low"] for b in complete]
    wv = [b["volume"] for b in complete]

    ma10 = sum(wc[-10:]) / 10
    ma20 = sum(wc[-20:]) / 20 if len(wc) >= 20 else None
    ma40 = sum(wc[-40:]) / 40 if len(wc) >= 40 else None

    slope10 = lin_slope(wc, 10)
    slope20 = lin_slope(wc, 20) if len(wc) >= 20 else slope10

    a_week = atr(wh, wl, wc, 10)

    vol_recent = sum(wv[-5:]) / 5
    vol_prior = sum(wv[-15:-5]) / 10 if len(wv) >= 15 else vol_recent
    vol_ratio = vol_recent / vol_prior if vol_prior > 0 else 1.0

    high_10 = max(wh[-10:])
    low_10 = min(wl[-10:])

    prior_high_10 = max(wh[-12:-2]) if len(wh) >= 12 else high_10
    prior_low_10 = min(wl[-12:-2]) if len(wl) >= 12 else low_10
    breakout = wc[-1] > prior_high_10 and wc[-2] > prior_high_10
    breakdown = wc[-1] < prior_low_10 and wc[-2] < prior_low_10

    direction = "up" if slope10 > 0.5 else ("down" if slope10 < -0.5 else "flat")

    out = {
        "sufficient": True,
        "num_weeks": len(complete),
        "last_complete_week_close": round(wc[-1], 3),
        "ma10w": round(ma10, 3),
        "ma20w": round(ma20, 3) if ma20 else None,
        "ma40w": round(ma40, 3) if ma40 else None,
        "slope_10w_pct": round(slope10, 2),
        "slope_20w_pct": round(slope20, 2),
        "direction": direction,
        "atr_weekly": round(a_week, 4),
        "vol_ratio_weekly": round(vol_ratio, 2),
        "high_10w": round(high_10, 3),
        "low_10w": round(low_10, 3),
        "breakout_confirmed": breakout,
        "breakdown_confirmed": breakdown,
    }
    if preview is not None:
        out["preview"] = _preview_block(preview)
    return out


def _preview_block(preview_bar):
    if not preview_bar:
        return None
    return {
        "note": "当前周尚未完成，仅作预览，不参与趋势判断",
        "week_start": preview_bar["week_start"],
        "provisional_close": round(preview_bar["close"], 3),
        "provisional_high": round(preview_bar["high"], 3),
        "provisional_low": round(preview_bar["low"], 3),
    }


# ─── Trend state model (T0-T8, with T3a/T3b) ───────────────────────────────

def classify_trend_state(ma, structure, weekly, closes, highs, lows):
    """Classify the medium-term trend into one of T0..T8 (with T3a/T3b).

    Weekly is primary; structural breakdown and exhaustion are checked first so
    a top/break is never missed. T3 carries a sub_state: T3a = structure
    strengthening but MA60 still down; T3b = MA60 flat/up.
    """
    n = len(closes)
    cur = closes[-1]

    n250 = min(250, n)
    hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5
    dd_high = (cur - hi250) / hi250 * 100 if hi250 > 0 else 0.0

    d20 = lin_slope(closes, 20)
    if n >= 80:
        d_prior = lin_slope(closes[-60:-20], 40)
    else:
        d_prior = 0.0

    wk_dir = weekly.get("direction", "flat")
    wk_slope10 = weekly.get("slope_10w_pct", 0.0)
    wk_breakdown = weekly.get("breakdown_confirmed", False)
    ma60_dir = ma.get("ma60_dir", "flat")
    ma120_dir = ma.get("ma120_dir", "flat")
    bullish_align = ma.get("bullish_alignment", False)
    bearish_align = ma.get("bearish_alignment", False)
    hh = structure.get("higher_high")
    hl = structure.get("higher_low")
    ma60 = ma.get("ma60")
    price_above_ma60 = ma60 is not None and cur > ma60

    def st(code, label, confidence, reasons, sub=None):
        return {"code": code, "label": label, "confidence": confidence,
                "reasons": reasons, "sub_state": sub}

    # T8 结构破坏 — weekly breakdown confirmed + weekly down (immediate)
    if wk_breakdown and wk_dir == "down":
        return st("T8", "结构破坏", "high", [
            "周线收盘连续两周跌破前期周线低点(中期结构失效)",
            f"周线方向向下(slope {wk_slope10:+.1f}%)",
            f"均线排列({ma.get('alignment')})",
        ])

    # T7 趋势衰竭 — near highs but momentum flattening / rolling over
    if pos250 >= 0.70 and ma60_dir != "up" and d20 <= 0.5:
        return st("T7", "趋势衰竭", "medium", [
            f"价格处于250日高位({pos250*100:.0f}%)",
            f"MA60斜率转平/向下({ma.get('ma60_slope_pct', 0):+.1f}%)",
            f"20日动量减弱({d20:+.1f}%)",
            "高位滞涨/动能背离，警惕顶部派发",
        ])

    # T6 高位整理 — near highs, flat daily slope, weekly not down
    if pos250 >= 0.70 and abs(d20) <= 2.0 and wk_dir != "down":
        return st("T6", "高位整理", "medium", [
            f"价格处于250日高位({pos250*100:.0f}%)",
            f"20日动量走平({d20:+.1f}%)",
            "高位区间震荡，等待方向选择",
        ])

    # Down-week handling (weekly direction down)
    if wk_dir == "down":
        # T0: full bearish alignment + lower lows → pure long-term downtrend
        if bearish_align and not hl:
            return st("T0", "长期下降", "high", [
                f"周线向下(slope {wk_slope10:+.1f}%)",
                f"均线空头排列({ma.get('alignment')})",
                "低点仍在降低，中期趋势向下",
            ])
        # T1: decline decelerating (both windows negative, recent less negative)
        if d20 < 0 and d_prior < 0 and d20 > d_prior:
            decel_pct = (d20 / d_prior) if d_prior != 0 else None
            ds = f"{decel_pct:.0%}" if decel_pct is not None else "n/a"
            return st("T1", "下降减速", "medium", [
                f"周线向下(slope {wk_slope10:+.1f}%)",
                f"日线下跌减速(减速比 {ds})",
                "下跌动能减弱，未确认见底",
            ])
        # T1: bounce within downtrend (recent momentum turned positive, weekly not yet up)
        if d20 >= 0:
            return st("T1", "下降减速", "medium", [
                f"周线向下(slope {wk_slope10:+.1f}%)",
                f"日线20日动量转正({d20:+.1f}%)，属下降趋势中的反弹",
                "低点抬高但周线未转上，未确认反转",
            ])
        # d20 < 0 and not decelerating → still a clean downtrend
        return st("T0", "长期下降", "high", [
            f"周线向下(slope {wk_slope10:+.1f}%)",
            "日线仍在下行且未见减速，中期趋势向下",
        ])

    # T5 上升加速 — full bull alignment + strong momentum + extended
    if bullish_align and ma60_dir == "up" and ma120_dir == "up" and d20 >= 6 and hh and hl:
        return st("T5", "上升加速", "medium", [
            f"均线多头排列({ma.get('alignment')})",
            f"20日动量强劲({d20:+.1f}%)",
            "趋势加速，需警惕过热回调",
        ])

    # T4 中期上升确认 — full bull alignment + HH/HL + weekly up
    if bullish_align and ma60_dir == "up" and ma120_dir == "up" and hl and wk_dir == "up":
        return st("T4", "中期上升确认", "high", [
            f"均线多头排列({ma.get('alignment')})",
            f"MA60/MA120向上(斜率 {ma.get('ma60_slope_pct', 0):+.1f}%/{ma.get('ma120_slope_pct', 0):+.1f}%)",
            "高点抬高+低点抬高，周线向上",
        ])

    # T3 反转初步确认 — weekly turning up + price reclaimed MA60 + higher low.
    # Sub-state: T3a (MA60 still down) vs T3b (MA60 flat/up).
    if wk_dir == "up" and price_above_ma60 and hl:
        if ma60_dir == "up":
            return st("T3", "反转初步确认", "high", [
                f"周线转上(slope {wk_slope10:+.1f}%)",
                f"价格站上MA60({ma.get('price_vs_ma60_pct', 0):+.1f}%)",
                "MA60转上，反转确认（T3b，可分批增加战术仓）",
            ], sub="T3b")
        return st("T3", "反转初步确认", "medium", [
            f"周线转上(slope {wk_slope10:+.1f}%)",
            f"价格站上MA60({ma.get('price_vs_ma60_pct', 0):+.1f}%)",
            "低点抬高，但MA60仍向下（T3a，反转初步确认，需等待MA60走平/转上）",
        ], sub="T3a")

    # T2 底部构建 — near lows + higher low forming + weekly flat/turning
    if pos250 <= 0.35 and hl:
        return st("T2", "底部构建", "medium", [
            f"价格处于250日低位({pos250*100:.0f}%)",
            "低点开始抬高，正在筑底",
            f"周线方向 {wk_dir}(slope {wk_slope10:+.1f}%)",
        ])

    # Fallback
    if bullish_align and ma60_dir == "up":
        return st("T4", "中期上升确认", "medium", [
            f"均线多头排列({ma.get('alignment')})",
            "MA60向上，趋势偏多",
        ])
    return st("T6", "高位整理", "low", [
        f"价格位置 {pos250*100:.0f}%，20日动量 {d20:+.1f}%",
        "信号混合，趋势方向不明确",
    ])


# ─── State machine (persistence + legal migrations) ────────────────────────

T_RANK = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4,
          "T5": 5, "T6": 6, "T7": 7, "T8": 8}


def migrate(prev, raw_code, raw_sub):
    """Apply migration legality rules.

    Returns (effective_code, effective_sub, migration_type, confirmation, note).
    """
    if prev is None:
        return raw_code, raw_sub, "initial", "pending", "首次观察，需至少连续2个完整周线确认"

    prev_code = prev.get("state", "T0")
    if prev_code == raw_code:
        return raw_code, raw_sub, "same", "pending", "状态保持不变，需连续2个完整周线确认"

    dp, dr = T_RANK.get(prev_code, 0), T_RANK.get(raw_code, 0)
    delta = dr - dp

    # Entering T8: immediate breakdown, always allowed
    if raw_code == "T8":
        return raw_code, raw_sub, "breakdown", "confirmed", "重大结构破坏，立即降级生效"

    # T7 -> T4 recovery must route through T6
    if prev_code == "T7" and raw_code in ("T4", "T5"):
        return prev_code, prev.get("sub_state"), "blocked", "pending", "T7→T4被禁止，需先经T6高位整理"

    # Large bullish jump from T0/T1 straight to T4/T5: forbidden
    if prev_code in ("T0", "T1") and raw_code in ("T4", "T5"):
        return prev_code, prev.get("sub_state"), "blocked", "pending", "T0/T1直接跳T4/T5原则上禁止，需逐级确认"

    if delta == 1:
        return raw_code, raw_sub, "normal_advance", "pending", "正常前进，需连续2个完整周线确认"
    if delta > 1:
        return raw_code, raw_sub, "jump", "pending", "跨级前进，需更强证据（≥2个完整周线）"
    return raw_code, raw_sub, "degradation", "pending", "降级，需连续2个完整周线确认"


def apply_state_machine(code, raw_trend, state_file, save_state):
    """Load previous state, apply migration rules, persist, return machine block."""
    prev = None
    if state_file and os.path.exists(state_file):
        try:
            with open(state_file) as f:
                store = json.load(f)
            prev = store.get(code)
        except Exception:
            prev = None

    raw_code = raw_trend["code"]
    raw_sub = raw_trend.get("sub_state")

    eff_code, eff_sub, mtype, conf, note = migrate(prev, raw_code, raw_sub)

    # consecutive-week counting: new state resets to 1; blocked/same state keeps counting
    consecutive = 1
    if prev and prev.get("state") == eff_code:
        consecutive = prev.get("consecutive_weeks", 0) + 1

    machine = {
        "previous_state": prev.get("state") if prev else None,
        "previous_sub_state": prev.get("sub_state") if prev else None,
        "raw_state": raw_code,
        "raw_sub_state": raw_sub,
        "effective_state": eff_code,
        "effective_sub_state": eff_sub,
        "consecutive_weeks": consecutive,
        "migration_type": mtype,
        "confirmation": "confirmed" if consecutive >= 2 else conf,
        "note": note,
    }

    if save_state and state_file:
        store = {}
        if os.path.exists(state_file):
            try:
                with open(state_file) as f:
                    store = json.load(f)
            except Exception:
                store = {}
        store[code] = {
            "state": eff_code,
            "sub_state": eff_sub,
            "consecutive_weeks": consecutive,
            "last_update": dt.date.today().isoformat(),
        }
        try:
            with open(state_file, "w") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return machine


# ─── Main ──────────────────────────────────────────────────────────────────

def analyze(code, name, kline_data, benchmark_data=None, intraday=False,
            state_file=None, save_state=False):
    records = parse_kline(kline_data)
    if not records:
        return {"error": "insufficient kline data", "code": code, "name": name}

    closes = [r["close"] for r in records]
    highs = [r["high"] for r in records]
    lows = [r["low"] for r in records]

    daily_status, weekly_status = week_completeness(records, intraday)
    weekly_bars = resample_weekly(records)

    bench_closes = None
    if benchmark_data:
        bench_records = parse_kline(benchmark_data)
        if bench_records:
            bench_closes = [r["close"] for r in bench_records]

    ma = compute_ma_features(closes, highs, lows)
    structure = compute_structure(closes, highs, lows)
    extension = compute_extension(closes, highs, lows)
    volatility = compute_volatility(highs, lows, closes)
    rel_str = compute_relative_strength(closes, bench_closes)
    weekly = compute_weekly_features(weekly_bars, weekly_status)

    # Drawdown state
    n250 = min(250, len(closes))
    hi250 = max(highs[-n250:])
    dd_high = (closes[-1] - hi250) / hi250 * 100 if hi250 > 0 else 0.0
    if dd_high < -20:
        dd_state = "deep"
    elif dd_high < -8:
        dd_state = "recovering" if structure.get("higher_low") else "drawdown"
    else:
        dd_state = "normal"

    trend = classify_trend_state(ma, structure, weekly, closes, highs, lows)

    result = {
        "code": code,
        "name": name,
        "data_quality": data_quality(records, intraday),
        "trend_state": trend,
        "ma": ma,
        "structure": structure,
        "weekly": weekly,
        "relative_strength": rel_str,
        "drawdown": {
            "drawdown_from_250d_high_pct": round(dd_high, 2),
            "state": dd_state,
        },
        "extension": extension,
        "volatility": volatility,
    }

    if state_file:
        result["state_machine"] = apply_state_machine(code, trend, state_file, save_state)

    return result


def resolve_name(code):
    search_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                     "all_etfs_larggest.json"),
    ]
    for etf_file in search_paths:
        try:
            if os.path.exists(etf_file):
                with open(etf_file) as f:
                    etfs = json.load(f)
                for e in etfs:
                    if e.get("code") == code:
                        return e.get("name", code)
        except Exception:
            continue
    return code


def main():
    p = argparse.ArgumentParser(description="ETF trend-state + weekly analysis")
    p.add_argument("--code", required=True)
    p.add_argument("--kline-file", required=True)
    p.add_argument("--benchmark-file", help="optional benchmark kline JSON")
    p.add_argument("--intraday", action="store_true",
                   help="mark last daily bar as intraday (盘中) data")
    p.add_argument("--state-file", help="path to JSON persistence file for the state machine")
    p.add_argument("--save-state", action="store_true",
                   help="persist effective state to --state-file")
    args = p.parse_args()

    with open(args.kline_file) as f:
        kline_data = json.load(f)

    benchmark_data = None
    if args.benchmark_file:
        with open(args.benchmark_file) as f:
            benchmark_data = json.load(f)

    name = resolve_name(args.code)
    result = analyze(args.code, name, kline_data, benchmark_data, args.intraday,
                     args.state_file, args.save_state)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
