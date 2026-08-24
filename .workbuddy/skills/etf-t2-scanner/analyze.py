#!/usr/bin/env python3
"""
A股ETF T2区间扫描器 (v1)

对全部A股ETF运行 T0-T8 趋势状态机（来源: etf-operation-plan/trend_analysis.py,
v1.0 复制），筛出 T2(底部构建) 标的，并按 5 维置信度打分排序
(语义 = 接近T3升级)。

数据输入: 项目根 etf_kline_data.json + all_etfs_larggest.json
可选联网更新: 复用 etf-bowl-bottom-scanner 的 update_kline_data 逻辑
"""
import json
import subprocess
import sys
import os
import time
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK_BIN = "/Users/aldiadmin/.workbuddy/westock-data/scripts/index.js"
NODE_BIN = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"

KLINE_DAYS = 250
MAX_WORKERS = 8
CHECK_DAYS = 5

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


# ─── T2 confidence scoring (语义=接近T3升级) ─────────────────────────────

def score_t2(ma, weekly, volatility, closes, highs, lows):
    """5维置信度打分, 满分100。返回 (score, reasons, breakdown)。"""
    n = len(closes)
    cur = closes[-1]

    # 1. 低点抬高幅度 (max 30)
    hl_pct = 0.0
    if n >= 40:
        lo_recent = min(lows[-20:])
        lo_prior = min(lows[-40:-20])
        hl_pct = (lo_recent - lo_prior) / lo_prior * 100 if lo_prior > 0 else 0.0
    if hl_pct >= 3:
        s_hl = 30
    elif hl_pct >= 1:
        s_hl = 22
    elif hl_pct >= 0.5:
        s_hl = 15
    elif hl_pct > 0:
        s_hl = 8
    else:
        s_hl = 0

    # 2. 距250日低点距离 (max 25)
    n250 = min(250, n)
    hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5
    if pos250 <= 0.10:
        s_pos = 25
    elif pos250 <= 0.20:
        s_pos = 20
    elif pos250 <= 0.30:
        s_pos = 12
    else:
        s_pos = 5

    # 3. 周线斜率回升 (max 20)
    wk_slope = weekly.get("slope_10w_pct", 0.0)
    wk_dir = weekly.get("direction", "flat")
    if wk_dir == "up":
        s_wk = 20
    elif wk_dir == "flat" and wk_slope > -0.5:
        s_wk = 15
    elif wk_dir == "flat":
        s_wk = 10
    else:
        s_wk = 5

    # 4. 距MA60距离 (max 15)
    d_ma60 = ma.get("price_vs_ma60_pct")
    if d_ma60 is None:
        s_ma = 5
    elif -15 <= d_ma60 <= -2:
        s_ma = 15
    elif -20 <= d_ma60 < -15:
        s_ma = 9
    elif -2 < d_ma60 <= 3:
        s_ma = 10
    else:
        s_ma = 4

    # 5. 量能/波幅 (max 10)
    vol_ratio = weekly.get("vol_ratio_weekly", 1.0)
    atr_ratio = volatility.get("atr_ratio", 1.0)
    s_vol = 0
    if vol_ratio < 0.8:
        s_vol += 5
    elif vol_ratio < 1.0:
        s_vol += 3
    if atr_ratio < 0.85:
        s_vol += 5
    elif atr_ratio < 1.0:
        s_vol += 3

    score = s_hl + s_pos + s_wk + s_ma + s_vol

    # 惩罚: 近20日动量快速下跌
    t20 = lin_slope(closes, 20)
    if t20 < -4:
        score -= 10

    score = max(0, min(100, score))

    breakdown = {
        "hl_pct": round(hl_pct, 2), "hl_score": s_hl,
        "pos250": round(pos250 * 100, 1), "pos_score": s_pos,
        "wk_slope": round(wk_slope, 2), "wk_dir": wk_dir, "wk_score": s_wk,
        "d_ma60": d_ma60, "ma_score": s_ma,
        "vol_ratio": round(vol_ratio, 2), "atr_ratio": round(atr_ratio, 2),
        "vol_score": s_vol,
        "t20": round(t20, 2), "penalty": -10 if t20 < -4 else 0,
    }
    reasons = [
        f"低点抬高幅度 {hl_pct:+.1f}% (得{s_hl}/30)",
        f"250日区间位置 {pos250*100:.0f}% (得{s_pos}/25)",
        f"周线方向 {wk_dir}, slope10w {wk_slope:+.1f}% (得{s_wk}/20)",
        f"距MA60 {d_ma60 if d_ma60 is not None else 'n/a'}% (得{s_ma}/15)",
        f"周量比 {vol_ratio:.2f}, ATR比 {atr_ratio:.2f} (得{s_vol}/10)",
    ]
    if breakdown["penalty"]:
        reasons.append(f"惩罚: 近20日动量 {t20:+.1f}% < -4% (-10分)")
    return score, reasons, breakdown


def analyze_etf(code, name, etype, kline_data):
    """对单只ETF运行状态机; 若为T2则附加置信度打分。返回结果dict或None。"""
    records = parse_kline(kline_data)
    if not records:
        return None

    closes = [r["close"] for r in records]
    highs = [r["high"] for r in records]
    lows = [r["low"] for r in records]

    daily_status, weekly_status = week_completeness(records, False)
    weekly_bars = resample_weekly(records)

    ma = compute_ma_features(closes, highs, lows)
    structure = compute_structure(closes, highs, lows)
    volatility = compute_volatility(highs, lows, closes)
    weekly = compute_weekly_features(weekly_bars, weekly_status)
    trend = classify_trend_state(ma, structure, weekly, closes, highs, lows)

    n250 = min(250, len(closes))
    hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
    cur = closes[-1]
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5
    dd_high = (cur - hi250) / hi250 * 100 if hi250 > 0 else 0.0

    result = {
        "code": code, "name": name, "type": etype,
        "trend_state": trend,
        "pos250": round(pos250 * 100, 1),
        "drawdown_250d": round(dd_high, 1),
        "current": round(cur, 3),
        "ma": {"price_vs_ma60_pct": ma.get("price_vs_ma60_pct"),
               "alignment": ma.get("alignment"),
               "ma60_dir": ma.get("ma60_dir")},
        "structure": structure,
        "weekly": {"direction": weekly.get("direction"),
                   "slope_10w_pct": weekly.get("slope_10w_pct"),
                   "vol_ratio_weekly": weekly.get("vol_ratio_weekly"),
                   "num_weeks": weekly.get("num_weeks")},
        "volatility": volatility,
    }
    if trend.get("code") == "T2":
        score, reasons, breakdown = score_t2(
            ma, weekly, volatility, closes, highs, lows)
        result["t2_score"] = score
        result["t2_reasons"] = reasons
        result["t2_breakdown"] = breakdown
    return result


# ─── Data update (from etf-bowl-bottom-scanner/analyze.py) ─────────────────

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
        print(f"❌ Input file not found: {input_path}", file=sys.stderr)
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


def update_kline_data(kline_data, etfs, kline_file, refresh_today=False):
    """
    Check cached kline data and append latest records if any are missing.
    (函数体逐字符复制自 etf-bowl-bottom-scanner/analyze.py 的 update_kline_data)
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


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    refresh_today = "--no-refresh" not in sys.argv
    print("=" * 60)
    print("A股ETF T2区间扫描 (T0-T8状态机)")
    if refresh_today:
        print("🔄 盘中刷新模式: 同日期数据将用最新数据替换 (默认开启, --no-refresh 关闭)")
    print("=" * 60)

    # Step 1: Load ETF list
    print("\n📋 加载ETF列表...")
    etfs = load_etfs()
    if not etfs:
        print("❌ 未找到ETF列表。请确保 all_etfs_larggest.json 存在于项目根目录。")
        return
    print(f"共加载 {len(etfs)} 只ETF")

    # Step 2: Load kline data
    kline_file = os.path.join(os.getcwd(), "etf_kline_data.json")
    if not os.path.exists(kline_file):
        print(f"❌ 未找到K线数据: {kline_file}")
        return
    print(f"\n📊 加载K线数据: {kline_file}")
    with open(kline_file) as f:
        kline_data = json.load(f)
    print(f"已加载 {len(kline_data)} 只ETF K线数据")

    # Step 3: Optional network update
    if refresh_today:
        updated = update_kline_data(kline_data, etfs, kline_file, refresh_today)
        if updated > 0:
            print(f"已更新 {updated} 只ETF")
        else:
            print("K线数据已是最新，无需更新")

    # Step 4: Classify all ETFs
    print("\n🔍 运行T0-T8趋势状态机...")
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results = []
    for e in etfs:
        kl = kline_data.get(e["code"])
        if not kl:
            continue
        r = analyze_etf(e["code"], e["name"], e["type"], kl)
        if r:
            results.append(r)

    # Step 5: Summary + save
    t2_list = [r for r in results if r["trend_state"]["code"] == "T2"]
    t2_list.sort(key=lambda x: x.get("t2_score", 0), reverse=True)

    dist = {}
    for r in results:
        c = r["trend_state"]["code"]
        sub = r["trend_state"].get("sub_state")
        key = c + (f"({sub})" if sub else "")
        dist[key] = dist.get(key, 0) + 1

    print("\n" + "=" * 60)
    print(f"📊 趋势状态分布 (共{len(results)}只ETF)")
    print("=" * 60)
    for k in sorted(dist, key=lambda x: (int(x[1]) if x[1].isdigit() else 9, x)):
        print(f"  {k}: {dist[k]}")

    print(f"\n🏆 T2底部构建标的: {len(t2_list)} 只")
    print(f"\n{'排名':<4}{'ETF':<18}{'置信度':<6}{'250位%':<8}{'抬底%':<8}{'周线':<8}{'距MA60':<8}")
    print("-" * 80)
    for i, r in enumerate(t2_list[:20]):
        b = r.get("t2_breakdown", {})
        print(f"{i+1:<4}{r['name']:<18}{r.get('t2_score', 0):<6}{b.get('pos250', '-'):<8}"
              f"{b.get('hl_pct', 0): <+8.1f}{b.get('wk_dir', '-'):<8}{b.get('d_ma60', '-'):<8}")

    out = {
        "meta": {
            "generated": dt.datetime.now().isoformat(),
            "sample_size": len(results),
            "kline_file": kline_file,
        },
        "state_distribution": dist,
        "t2_count": len(t2_list),
        "t2_avg_score": round(sum(r.get("t2_score", 0) for r in t2_list) / len(t2_list), 1) if t2_list else None,
        "results": results,
    }
    results_file = os.path.join(skill_dir, "etf_t2_results.json")
    with open(results_file, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n分析结果已保存: {results_file}")


if __name__ == "__main__":
    main()
