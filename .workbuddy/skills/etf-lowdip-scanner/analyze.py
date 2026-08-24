#!/usr/bin/env python3
"""
A股ETF 低吸机会扫描器 (etf-lowdip-scanner) v1

对全部A股ETF运行 T0-T8 趋势状态机（来源: etf-operation-plan/trend_analysis.py,
v1.0 复制），筛出 **T2(底部构建)** 与 **T3a(反转初步确认, MA60仍下行)** 两类
允许低吸的标的，并按「低吸置信度」排序。

与 etf-t2-scanner 的区别:
- 目标状态从「仅T2」扩为「T2 + T3a」(SOP的T2/T3a低吸机会)
- 打分从「5维T2置信度(语义=接近T3升级)」改为「低吸置信度(语义=左侧低吸性价比)」
- 排除货币基金/债券类「价格近乎走平」标的（如 sh511850 招商财富宝），避免形态失真

数据输入: 项目根 etf_kline_data.json + all_etfs_larggest.json
可选联网更新: 复用 etf-bowl-bottom-scanner 的 update_kline_data 逻辑
"""
import glob
import json
import subprocess
import sys
import os
import time
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import util as _il

WESTOCK_BIN = "/Users/aldiadmin/.workbuddy/westock-data/scripts/index.js"
NODE_BIN = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"

KLINE_DAYS = 250
MAX_WORKERS = 8
CHECK_DAYS = 5

AUM_FLOOR = 5e8  # SOP Step1 硬门槛: 规模 > 5 亿, 避免清盘/流动性风险

# 排除价格近乎走平的货币基金/债券类 —— 无波动, spread近零, 会扭曲位次与形态打分
FLAT_PRICE_EXCLUDE = {
    "sh511850",  # 招商财富宝 (货币基金)
}

# ─── SOP 决策层（四道程序校验 + 结构失效位）参数与加载 ─────────────────────
# 所有金额/权重/成本参数一律取自 records/portfolio_config.json, 绝不在代码硬编码
PROJECT_ROOT = os.getcwd()
CONFIG_PATH = os.path.join(PROJECT_ROOT, "records", "portfolio_config.json")
RECORDS_ETF_DIR = os.path.join(PROJECT_ROOT, "records", "etf")

# SOP 结构失效位公式 (§六/§九): 结构支撑(60/120日低) − 0.5×ATR20; 灾难保护位 −1×ATR20
SUPPORT_LOOKBACKS = (60, 120)
STRUCT_INVALIDATION_MULT = 0.5
DISASTER_MULT = 1.0

# 小额试仓放行门槛: 低吸分 + rr_net 双阈值
# 完整建仓(操作计划)维持 rr>=2; 小额试仓(T2/T3a, ≤10%仓)用更低 TRIAL_RR_FLOOR, 用极小仓位换更宽 RR
TRIAL_SCORE_FLOOR = 50
TRIAL_RR_FLOOR = 1.2

# 第一观察区 / 计划买入价: 低吸计划设定为「回踩再买」——买在回踩支撑、目标看第一阻力
OBSERVATION_MULT = 1.0       # 第一观察区 = 第一阻力（近20日高），突破/触及后兑现或加仓
ENTRY_SHALLOW = 0.995        # 计划买入价 = min(MA20,现价) × 0.995（浅回踩）
# 若价格已远离结构支撑（反转初段涨幅大），RR 天然偏低——由校验4 裁决是否放行


def load_portfolio_config():
    """Load records/portfolio_config.json; returns None if missing."""
    if not os.path.exists(CONFIG_PATH):
        print(f"⚠ 未找到组合配置: {CONFIG_PATH}（跳过四道程序校验/下单计算）", file=sys.stderr)
        return None
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_position_record(code):
    """Load shares for a code from records/etf/*.json (交易流水)."""
    if not os.path.isdir(RECORDS_ETF_DIR):
        return 0
    for path in glob.glob(os.path.join(RECORDS_ETF_DIR, "*.json")):
        try:
            rec = json.load(open(path))
        except Exception:
            continue
        if rec.get("code") != code:
            continue
        shares, book = 0, 0.0
        for t in rec.get("trades", []):
            if t.get("action") == "buy":
                book += t.get("amount", 0); shares += t.get("shares", 0)
            elif t.get("action") == "sell":
                avg = book / shares if shares > 0 else 0.0
                book -= avg * t.get("shares", 0); shares -= t.get("shares", 0)
        return int(shares)
    return 0


def _load_decision_engine():
    """Load decision_engine.py in the same skill dir (self-contained, no pip)."""
    spec = _il.spec_from_file_location(
        "lowdip_decision_engine",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "decision_engine.py"))
    mod = _il.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _three_validations(dengine, config, code, shares, price, decide_kwargs):
    """Run decide() with the four program validations; returns the verdict dict."""
    pos_cfg = (config.get("positions") or {}).get(code) or {}
    role = pos_cfg.get("role", "tactical_value")
    res = dengine.decide(
        role=role, config=config, code=code, shares=shares, price=price,
        **decide_kwargs, trial=True, trial_rr_floor=TRIAL_RR_FLOOR)
    v = res["validations"]
    verdict = "PASS" if (res["current_action"] == "ADD" and res.get("trial")
                         and v["action_legal"]["pass"] and v["risk_reward"]["pass"]
                         and v["sizing"]["pass"] and v["cost"]["pass"]) else "FAIL"
    gate = {"PASS": "可小额试仓", "FAIL": "被四道程序校验拦截"}.get(verdict, "FAIL")
    os_ = res["order_size"] or {}
    out = {
        "verdict": verdict, "gate": gate, "action": res["current_action"],
        "trial": bool(res.get("trial")),
        "rr_net": v["risk_reward"].get("rr"),
        "level": {
            "first_observation": decide_kwargs.get("first_observation"),
            "planned_entry": decide_kwargs.get("planned_entry"),
            "structural_invalidation": decide_kwargs.get("structural_invalidation"),
            "disaster_level": round(decide_kwargs["structural_invalidation"]
                                    - 1.0 * decide_kwargs["atr20"], 3)
            if decide_kwargs.get("atr20") and decide_kwargs.get("structural_invalidation")
            else None,
        },
        "order": {
            "pct_of_target": os_.get("pct_of_target"),
            "shares": os_.get("shares"),
            "amount": os_.get("amount"),
            "cost_amount": os_.get("cost_amount"),
            "cost_pct_of_trade": os_.get("cost_pct_of_trade"),
            "cost_share_of_reward_pct": os_.get("cost_share_of_reward_pct"),
            "current_weight_pct": os_.get("current_weight_pct"),
            "gap": os_.get("gap"),
            "target_value": os_.get("target_value"),
        },
        "validations": {
            "action_legal": {"pass": v["action_legal"]["pass"],
                             "rejected": v["action_legal"].get("rejected")},
            "risk_reward": {"pass": v["risk_reward"]["pass"], "rr": v["risk_reward"].get("rr"),
                            "reason": v["risk_reward"].get("reason")},
            "sizing": {"pass": v["sizing"]["pass"],
                       "checks": [{"label": c[0], "ok": c[1]}
                                  for c in v["sizing"].get("checks", [])]},
            "cost": {"pass": v["cost"]["pass"], "reasons": v["cost"].get("reasons", [])},
        },
    }
    return out


def _run_program_check(config, code, shares, price, score, ma, structure,
                       volatility, closes, highs, trend):
    """Build SOP 结构失效位/计划买入价/第一观察区, 并跑四道程序校验.

    结构失效位 = min(60日低, 120日低) − 0.5×ATR20; 灾难保护位再 −1×ATR20.
    计划买入价 / 第一观察区 以回踩 MA20 为参照 (SOP Step4 回踩再买).
    """
    if config is None:
        return None
    n = len(closes)
    low60 = min(closes[-60:]) if n >= 60 else min(closes)
    low120 = min(closes[-120:]) if n >= 120 else low60
    support = min(low60, low120)
    atr20 = volatility.get("atr20") or 0.0
    invalidation = round(support - STRUCT_INVALIDATION_MULT * atr20, 4)
    ma20 = ma.get("ma20")
    if not ma20 or ma20 <= 0:
        return None

    # 第一观察区 = 近20日高点（第一阻力）; 计划买入价 = min(MA20,现价)×0.995（回踩买）
    first_observation = round(max(highs[-20:]) * OBSERVATION_MULT, 4)
    entry_ref = min(ma20, closes[-1])
    planned_entry = round(entry_ref * ENTRY_SHALLOW, 4)

    # 低吸高分 + 满足趋势门控(非T0/T1) 才放行小额试仓决策; 其余直接判 FAIL
    tcode = trend.get("code")
    if score < TRIAL_SCORE_FLOOR or tcode in ("T0", "T1"):
        return {
            "verdict": "FAIL", "gate": "未达放行门槛（低吸分或趋势状态）",
            "action": "HOLD", "trial": False, "rr_net": None,
            "level": {"structure_support": round(support, 4), "atr20": round(atr20, 4),
                      "structural_invalidation": invalidation,
                      "planned_entry": planned_entry,
                      "first_observation": first_observation,
                      "disaster_level": round(invalidation - atr20, 3)},
            "order": None, "validations": None,
        }

    dengine = _load_decision_engine()
    dec = _three_validations(dengine, config, code, shares, price, {
        "state_code": tcode, "sub_state": trend.get("sub_state"),
        "structural_invalidation": invalidation,
        "planned_entry": planned_entry, "first_observation": first_observation,
        "atr20": atr20, "ma60_dir": ma.get("ma60_dir", "flat"),
    })
    dec["level"]["structure_support"] = round(support, 4)
    dec["level"]["atr20"] = round(atr20, 4)
    return dec


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
    """Aggregate daily bars into weekly bars (ISO week grouping)."""
    weeks = {}
    for r in records:
        try:
            d = dt.date.fromisoformat(r["date"][:10])
        except ValueError:
            continue
        key = (d.isocalendar()[0], d.isocalendar()[1])
        if key not in weeks:
            weeks[key] = {
                "week_start": r["date"], "open": r["open"], "close": r["close"],
                "high": r["high"], "low": r["low"], "volume": r["volume"],
            }
        else:
            w = weeks[key]
            w["close"] = r["close"]
            w["high"] = max(w["high"], r["high"])
            w["low"] = min(w["low"], r["low"])
            w["volume"] += r["volume"]
    return [weeks[k] for k in sorted(weeks)]


def week_completeness(records, intraday):
    """Return (daily_bar_status, weekly_bar_status)."""
    if not records:
        return "unknown", "unknown"
    last = dt.date.fromisoformat(records[-1]["date"][:10])
    daily = "intraday" if intraday else "complete"
    last_is_friday = last.weekday() == 4
    weekly = "complete" if (last_is_friday and not intraday) else "incomplete_current_week"
    return daily, weekly


def compute_ma_features(closes, highs, lows):
    """MA alignment, slopes, price-vs-MA distances."""
    n = len(closes)
    cur = closes[-1]

    ma20 = sum(closes[-20:]) / 20 if n >= 20 else None
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
        "ma20": round(ma20, 3) if ma20 else None,
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
    """Volatility regime: compressed / normal / expanding. Also exposes ATR20."""
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


def compute_weekly_features(weekly_bars, weekly_bar_status):
    """Weekly close, 10/20/40w MA, slope, ATR, volume, breakout/failure."""
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


def classify_trend_state(ma, structure, weekly, closes, highs, lows):
    """Classify the medium-term trend into one of T0..T8 (with T3a/T3b).

    与 etf-operation-plan/etf-t2-scanner 完全一致的状态机。T3 携带 sub_state:
    T3a = 结构转强但 MA60 仍下行; T3b = MA60 走平/向上。
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

    if wk_breakdown and wk_dir == "down":
        return st("T8", "结构破坏", "high", [
            "周线收盘连续两周跌破前期周线低点(中期结构失效)",
            f"周线方向向下(slope {wk_slope10:+.1f}%)",
            f"均线排列({ma.get('alignment')})",
        ])

    if pos250 >= 0.70 and ma60_dir != "up" and d20 <= 0.5:
        return st("T7", "趋势衰竭", "medium", [
            f"价格处于250日高位({pos250*100:.0f}%)",
            f"MA60斜率转平/向下({ma.get('ma60_slope_pct', 0):+.1f}%)",
            f"20日动量减弱({d20:+.1f}%)",
            "高位滞涨/动能背离，警惕顶部派发",
        ])

    if pos250 >= 0.70 and abs(d20) <= 2.0 and wk_dir != "down":
        return st("T6", "高位整理", "medium", [
            f"价格处于250日高位({pos250*100:.0f}%)",
            f"20日动量走平({d20:+.1f}%)",
            "高位区间震荡，等待方向选择",
        ])

    if wk_dir == "down":
        if bearish_align and not hl:
            return st("T0", "长期下降", "high", [
                f"周线向下(slope {wk_slope10:+.1f}%)",
                f"均线空头排列({ma.get('alignment')})",
                "低点仍在降低，中期趋势向下",
            ])
        if d20 < 0 and d_prior < 0 and d20 > d_prior:
            decel_pct = (d20 / d_prior) if d_prior != 0 else None
            ds = f"{decel_pct:.0%}" if decel_pct is not None else "n/a"
            return st("T1", "下降减速", "medium", [
                f"周线向下(slope {wk_slope10:+.1f}%)",
                f"日线下跌减速(减速比 {ds})",
                "下跌动能减弱，未确认见底",
            ])
        if d20 >= 0:
            return st("T1", "下降减速", "medium", [
                f"周线向下(slope {wk_slope10:+.1f}%)",
                f"日线20日动量转正({d20:+.1f}%)，属下降趋势中的反弹",
                "低点抬高但周线未转上，未确认反转",
            ])
        return st("T0", "长期下降", "high", [
            f"周线向下(slope {wk_slope10:+.1f}%)",
            "日线仍在下行且未见减速，中期趋势向下",
        ])

    if bullish_align and ma60_dir == "up" and ma120_dir == "up" and d20 >= 6 and hh and hl:
        return st("T5", "上升加速", "medium", [
            f"均线多头排列({ma.get('alignment')})",
            f"20日动量强劲({d20:+.1f}%)",
            "趋势加速，需警惕过热回调",
        ])

    if bullish_align and ma60_dir == "up" and ma120_dir == "up" and hl and wk_dir == "up":
        return st("T4", "中期上升确认", "high", [
            f"均线多头排列({ma.get('alignment')})",
            f"MA60/MA120向上(斜率 {ma.get('ma60_slope_pct', 0):+.1f}%/{ma.get('ma120_slope_pct', 0):+.1f}%)",
            "高点抬高+低点抬高，周线向上",
        ])

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

    if pos250 <= 0.35 and hl:
        return st("T2", "底部构建", "medium", [
            f"价格处于250日低位({pos250*100:.0f}%)",
            "低点开始抬高，正在筑底",
            f"周线方向 {wk_dir}(slope {wk_slope10:+.1f}%)",
        ])

    if bullish_align and ma60_dir == "up":
        return st("T4", "中期上升确认", "medium", [
            f"均线多头排列({ma.get('alignment')})",
            "MA60向上，趋势偏多",
        ])
    return st("T6", "高位整理", "low", [
        f"价格位置 {pos250*100:.0f}%，20日动量 {d20:+.1f}%",
        "信号混合，趋势方向不明确",
    ])


def _slope_r2(closes, win):
    """动量: (斜率% × R²) over `win` days, 语义=SOP 量价动量因子 (斜率×R²)."""
    n = len(closes)
    if n < win + 2:
        return 0.0
    ys = closes[-win:]
    import math
    lx = [math.log(y) for y in ys if y > 0]
    if len(lx) < 3:
        return 0.0
    seg = lx
    m = float(len(seg))
    xs = list(range(len(seg)))
    sx = sum(xs)
    sy = sum(seg)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, seg))
    den = m * sxx - sx * sx
    if den == 0:
        return 0.0
    s = (m * sxy - sx * sy) / den
    ym = sy / m
    ss_tot = sum((y - ym) ** 2 for y in seg)
    if ss_tot == 0:
        r2 = 0.0
    else:
        ss_res = sum((y - (ym + s * (x - (m - 1) / 2))) ** 2 for x, y in enumerate(seg))
        r2 = 1 - ss_res / ss_tot
    pct = (math.exp(s * m) - 1) * 100  # 窗口总涨幅%
    return pct * max(0.0, r2)


def score_lowdip(trend_sub, ma, weekly, volatility, closes, highs, lows):
    """低吸置信度打分, 满分100。语义=「左侧低吸性价比 + 接近T3b升级概率」。

    6维:
      1. 250日区间位置(pos250, 越低估越高)     max 25  (SOP估值锚)
      2. 低点抬高幅度(higher-low)              max 20  (结构转强)
      3. 动量斜率×R²(m20, 转强越好)            max 20  (SOP量价动量因子)
      4. 周线方向(flat/up越好)                 max 15  (筑底/反转催化)
      5. MA60斜率修复(越接近走平/转上越好)     max 10  (T3a→T3b关键)
      6. 波幅/量能(低波好捕、缩量回踩好)       max 10
    惩罚: 近20日动量 < -4% → -10(仍在下行, 左侧风险大)。
    """
    n = len(closes)
    cur = closes[-1]

    n250 = min(250, n)
    hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5

    # 1. pos250 (low position) max 25
    if pos250 <= 0.10:
        s_pos = 25
    elif pos250 <= 0.20:
        s_pos = 21
    elif pos250 <= 0.30:
        s_pos = 15
    elif pos250 <= 0.40:
        s_pos = 9
    else:
        s_pos = 3

    # 2. higher-low 幅度 max 20
    hl_pct = 0.0
    if n >= 40:
        lo_recent = min(lows[-20:])
        lo_prior = min(lows[-40:-20])
        hl_pct = (lo_recent - lo_prior) / lo_prior * 100 if lo_prior > 0 else 0.0
    if hl_pct >= 3:
        s_hl = 20
    elif hl_pct >= 1:
        s_hl = 15
    elif hl_pct >= 0.5:
        s_hl = 10
    elif hl_pct > 0:
        s_hl = 5
    else:
        s_hl = 0

    # 3. 动量斜率×R² (m20) max 20
    m20 = _slope_r2(closes, 20)
    m40 = _slope_r2(closes, 40) if n >= 42 else 0.0
    m60 = _slope_r2(closes, 60) if n >= 62 else 0.0
    mom = 0.5 * m20 + 0.3 * m40 + 0.2 * m60  # 短中长加权
    if mom >= 2:
        s_mom = 20
    elif mom >= 0.5:
        s_mom = 16
    elif mom >= 0:
        s_mom = 11
    elif mom >= -2:
        s_mom = 5
    else:
        s_mom = 0

    # 4. 周线方向 max 15
    wk_dir = weekly.get("direction", "flat")
    wk_slope = weekly.get("slope_10w_pct", 0.0)
    if wk_dir == "up":
        s_wk = 15
    elif wk_dir == "flat" and wk_slope > -0.5:
        s_wk = 11
    elif wk_dir == "flat":
        s_wk = 7
    else:
        s_wk = 2

    # 5. MA60斜率修复 max 10 (T3a→T3b 关键; T2 是MA60向下但低位)
    ma60_slope = ma.get("ma60_slope_pct", 0.0) or 0.0
    if ma60_slope >= -1:
        s_ma = 10
    elif ma60_slope >= -2:
        s_ma = 7
    elif ma60_slope >= -4:
        s_ma = 4
    else:
        s_ma = 1

    # 6. 量能/波幅 max 10
    vol_ratio = weekly.get("vol_ratio_weekly", 1.0)
    atr_ratio = volatility.get("atr_ratio", 1.0)
    s_vol = 0
    if vol_ratio < 0.85:
        s_vol += 5
    elif vol_ratio < 1.0:
        s_vol += 3
    if atr_ratio < 0.9:
        s_vol += 5
    elif atr_ratio < 1.05:
        s_vol += 3

    score = s_pos + s_hl + s_mom + s_wk + s_ma + s_vol

    # 惩罚: 近20日动量快速下跌
    t20 = lin_slope(closes, 20)
    if t20 < -4:
        score -= 10

    score = max(0, min(100, score))

    breakdown = {
        "pos250": round(pos250 * 100, 1), "pos_score": s_pos,
        "hl_pct": round(hl_pct, 2), "hl_score": s_hl,
        "m20": round(m20, 2), "m40": round(m40, 2), "m60": round(m60, 2),
        "mom": round(mom, 2), "mom_score": s_mom,
        "wk_dir": wk_dir, "wk_slope": round(wk_slope, 2), "wk_score": s_wk,
        "ma60_slope_pct": round(ma60_slope, 2), "ma_score": s_ma,
        "vol_ratio": round(vol_ratio, 2), "atr_ratio": round(atr_ratio, 2),
        "vol_score": s_vol,
        "t20": round(t20, 2), "penalty": -10 if t20 < -4 else 0,
    }
    reasons = [
        f"250日区间位置 {pos250*100:.0f}% (低估, 得{s_pos}/25)",
        f"低点抬高幅度 {hl_pct:+.1f}% (结构转强, 得{s_hl}/20)",
        f"动量斜率×R² {mom:+.2f} (m20 {m20:+.2f}, 得{s_mom}/20)",
        f"周线方向 {wk_dir}, slope10w {wk_slope:+.1f}% (得{s_wk}/15)",
        f"MA60斜率修复 {ma60_slope:+.1f}% (得{s_ma}/10)",
        f"周量比 {vol_ratio:.2f}, ATR比 {atr_ratio:.2f} (得{s_vol}/10)",
    ]
    if breakdown["penalty"]:
        reasons.append(f"惩罚: 近20日动量 {t20:+.1f}% < -4% (-10分)")
    return score, reasons, breakdown


def _t3b_rr_triggers(ma, weekly, volatility, highs, lows):
    """T3b 建仓的 RR_net 计算(与 _run_program_check 同口径):
    计划买入价=min(MA20,现价)×0.995(回踩买); 第一观察区=近20日高(第一阻力);
    结构失效位=min(60日低,120日低)−0.5×ATR20。返回 planned_entry / first_observation / rr_net。
    """
    n = len(highs)
    low60 = min(lows[-60:]) if n >= 60 else (min(lows) if lows else 0.0)
    low120 = min(lows[-120:]) if n >= 120 else low60
    support = min(low60, low120)
    atr20 = volatility.get("atr20") or 0.0
    ma20 = ma.get("ma20")
    if not ma20 or ma20 <= 0 or support <= 0:
        return None, None, None, None, None
    cur = highs[-1] if highs else 0.0
    invalidation = support - 0.5 * atr20
    first_observation = max(highs[-20:]) if n >= 20 else (max(highs) if highs else 0.0)
    entry_ref = min(ma20, cur)
    planned_entry = entry_ref * 0.995
    risk = planned_entry - invalidation
    reward = first_observation - planned_entry
    rr_net = (reward / risk) if risk > 0 else 0.0
    return planned_entry, first_observation, invalidation, atr20, rr_net


def score_t3b(trend_sub, ma, weekly, volatility, closes, highs, lows):
    """T3b 建仓评分, 满分100。语义=「右侧趋势已确认, 但不在高位/过热处追」.
    优先级: 宁可错过, 不可高位套牢。

    7维 (新口径, 满分合计 100):
      1. 250日区间位置(pos250, 越低空间越大)        max 20 (已准入, 略降给 RR 腾权重)
      2. 距MA20乖离(bell: 回踩到MA20附近适中最好)     max 20 (保留精华)
      3. 低点抬高幅度(结构健康)                      max 15
      4. 周线/中期趋势强度                          max 15 (已准入, 略降)
      5. RR_net(新增: 买在回踩/目标看第一阻力/结构失效止损) max 15
      6. 量能波幅(分流: 回踩买=缩量企稳好; 突破加仓=放量好) max 10
      7. MA60 斜率(走平/转上强度)                   max 5  (与准入门重叠, 降权)
    RR_net<1.5 = 一票否决(整分强制归挡, 标记 veto)。
    惩罚阈值归一化到 ×ATR: 距MA20乖离>0.9×ATR20 或近20日涨幅>20% 判过热。
    """
    n = len(closes)
    cur = closes[-1]

    n250 = min(250, n)
    hi250, lo250 = max(highs[-n250:]), min(lows[-n250:])
    pos250 = (cur - lo250) / (hi250 - lo250) if hi250 > lo250 else 0.5

    ma20 = ma.get("ma20")
    ma60 = ma.get("ma60")
    dev20 = (cur / ma20 - 1.0) * 100 if ma20 else 0.0
    dev60 = (cur / ma60 - 1.0) * 100 if ma60 else 0.0
    adev20 = abs(dev20)
    atr20 = volatility.get("atr20") or 0.0
    # 惩罚档位按 ATR 归一: 乖离相对 1×ATR20 / 1.3×ATR20 分档
    dev20_1a = abs(dev20) / (atr20 / cur * 100) if atr20 > 0 and cur > 0 else 0.0

    # 1. pos250 (低位置=更大空间) max 20
    if pos250 <= 0.25:
        s_pos = 20
    elif pos250 <= 0.40:
        s_pos = 16
    elif pos250 <= 0.55:
        s_pos = 12
    elif pos250 <= 0.70:
        s_pos = 8
    elif pos250 <= 0.85:
        s_pos = 4
    else:
        s_pos = 1

    # 2. 距MA20乖离 bell max 20 (0~3%=最佳回踩点)
    if adev20 <= 3:
        s_dev = 20
    elif adev20 <= 5:
        s_dev = 16
    elif adev20 <= 8:
        s_dev = 11
    elif adev20 <= 12:
        s_dev = 6
    else:
        s_dev = 1

    # 3. 低点抬高 max 15
    hl_pct = 0.0
    if n >= 40:
        lo_recent = min(lows[-20:])
        lo_prior = min(lows[-40:-20])
        hl_pct = (lo_recent - lo_prior) / lo_prior * 100 if lo_prior > 0 else 0.0
    if hl_pct >= 3:
        s_hl = 15
    elif hl_pct >= 1:
        s_hl = 12
    elif hl_pct >= 0.5:
        s_hl = 8
    elif hl_pct > 0:
        s_hl = 4
    else:
        s_hl = 0

    # 4. 周线/中期趋势强度 max 15
    wk_dir = weekly.get("direction", "flat")
    wk_slope = weekly.get("slope_10w_pct", 0.0)
    if wk_dir == "up" and wk_slope >= 1:
        s_wk = 15
    elif wk_dir == "up":
        s_wk = 12
    elif wk_dir == "flat" and wk_slope > -0.5:
        s_wk = 8
    else:
        s_wk = 2

    # 5. RR_net max 15 (买在回踩, 目标第一阻力, 结构失效止损)
    planned_entry, first_observation, invalidation, _a20, rr_net = _t3b_rr_triggers(
        ma, weekly, volatility, highs, lows)
    rr_veto = (rr_net is not None and rr_net < 1.5)
    if rr_net is None:
        s_rr = 0
    elif rr_net >= 3.0:
        s_rr = 15
    elif rr_net >= 2.5:
        s_rr = 12
    elif rr_net >= 2.0:
        s_rr = 9
    elif rr_net >= 1.5:
        s_rr = 5
    else:
        s_rr = 0

    # 6. 量能波幅 max 10 —— 按建仓类型分流: 回踩买(首仓)=缩量企稳好; 突破加仓=放量好
    vol_ratio = weekly.get("vol_ratio_weekly", 1.0)
    atr_ratio = volatility.get("atr_ratio", 1.0)
    entry_type = "trial_dip"  # 本评分为 T3b 首仓回踩买; T3b→T4 突破加仓另走 trigger(放量)
    s_vol = 0
    if vol_ratio < 0.85:
        s_vol += 5
    elif vol_ratio < 1.05:
        s_vol += 3
    if atr_ratio < 0.9:
        s_vol += 5
    elif atr_ratio < 1.05:
        s_vol += 3

    # 7. MA60 斜率 max 5
    ma60_slope = ma.get("ma60_slope_pct", 0.0) or 0.0
    if ma60_slope >= 1:
        s_ma = 5
    elif ma60_slope >= 0:
        s_ma = 4
    elif ma60_slope >= -1:
        s_ma = 2
    else:
        s_ma = 1

    score = s_pos + s_dev + s_hl + s_wk + s_rr + s_vol + s_ma

    # 惩罚: 高位/过热 (档位按 ATR 归一)
    penalty = []
    if pos250 > 0.85:
        score -= 12; penalty.append(f"250日区间位 {pos250*100:.0f}% 高位 (追高风险 -12)")
    # 乖离超过 1.3×ATR20 → 过热; 超过 0.9×ATR20 → 偏热
    if dev20_1a > 1.3:
        score -= 12; penalty.append(f"距MA20 {dev20:+.1f}% = {dev20_1a:.1f}×ATR20 过热 (乖离过大 -12)")
    elif dev20_1a > 0.9:
        score -= 6; penalty.append(f"距MA20 {dev20:+.1f}% = {dev20_1a:.1f}×ATR20 乖离偏大 (-6)")

    # RR_net<1.5 一票否决: RR 维度本来就只得 0, 再叠加重罚, 使其必然跌出可建仓档(<50),
    # 但不抹平其他维度, 榜单内仍能排序、区分「矮子里拔将军」。原因内明确标记, 报告显示⚑否决。
    if rr_veto:
        score -= 40
        penalty.append(f"RR_net {rr_net:.2f} < 1.5 一票否决 (目标近20日高≈现价, 无上行空间, 买入易套牢)")

    score = max(0, min(100, score))

    breakdown = {
        "pos250": round(pos250 * 100, 1), "pos_score": s_pos,
        "dev20": round(dev20, 2), "dev60": round(dev60, 2), "dev_score": s_dev,
        "dev_atr_mult": round(dev20_1a, 2),
        "hl_pct": round(hl_pct, 2), "hl_score": s_hl,
        "wk_dir": wk_dir, "wk_slope": round(wk_slope, 2), "wk_score": s_wk,
        "rr_net": round(rr_net, 2) if rr_net is not None else None,
        "rr_score": s_rr, "rr_veto": rr_veto,
        "planned_entry": round(planned_entry, 4) if planned_entry else None,
        "first_observation": round(first_observation, 4) if first_observation else None,
        "structural_invalidation": round(invalidation, 4) if invalidation else None,
        "vol_ratio": round(vol_ratio, 2), "atr_ratio": round(atr_ratio, 2), "vol_score": s_vol,
        "entry_type": entry_type,
        "ma60_slope_pct": round(ma60_slope, 2), "ma_score": s_ma,
        "atr20": round(atr20, 4),
        "penalty": penalty,
    }
    reasons = [
        f"250日区间位置 {pos250*100:.0f}% (越低越有空间, 得{s_pos}/20)",
        f"距MA20 {dev20:+.1f}% ({dev20_1a:.1f}×ATR20, 回踩越近越好, 得{s_dev}/20)",
        f"低点抬高幅度 {hl_pct:+.1f}% (结构健康, 得{s_hl}/15)",
        f"周线方向 {wk_dir}, slope10w {wk_slope:+.1f}% (得{s_wk}/15)",
        f"RR_net {rr_net:.2f} (买{planned_entry if planned_entry else '-'}/止{invalidation if invalidation else '-'}/目标{first_observation if first_observation else '-'}, 得{s_rr}/15)",
        f"量能: 回踩买(首仓)缩量企稳, 周量比{vol_ratio:.2f}/ATR比{atr_ratio:.2f} (得{s_vol}/10); 突破加仓需放量另判",
        f"MA60斜率 {ma60_slope:+.1f}% (得{s_ma}/5)",
    ] + [f"惩罚: {p}" for p in penalty]
    return score, reasons, breakdown


def analyze_etf(code, name, etype, size_b, kline_data, config=None):
    """对单只ETF运行状态机; 若为T2/T3a则附加低吸置信度打分 + 四道程序校验, 若为T3b附加建仓评分。"""
    if code in FLAT_PRICE_EXCLUDE:
        return None
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
        "code": code, "name": name, "type": etype, "size_b": size_b,
        "trend_state": trend,
        "pos250": round(pos250 * 100, 1),
        "drawdown_250d": round(dd_high, 1),
        "current": round(cur, 3),
        "ma": {"price_vs_ma60_pct": ma.get("price_vs_ma60_pct"),
               "ma60_slope_pct": ma.get("ma60_slope_pct"),
               "ma60_dir": ma.get("ma60_dir"),
               "alignment": ma.get("alignment")},
        "structure": structure,
        "weekly": {"direction": weekly.get("direction"),
                   "slope_10w_pct": weekly.get("slope_10w_pct"),
                   "vol_ratio_weekly": weekly.get("vol_ratio_weekly"),
                   "num_weeks": weekly.get("num_weeks")},
        "volatility": volatility,
    }

    tcode = trend.get("code")
    tsub = trend.get("sub_state")
    # 评分范围 = 低吸目标(T2底部构建 + T3a反转初步, 低吸分) + 建仓白名单(T3b, 建仓分)
    if tcode == "T3" and tsub == "T3b":
        score, reasons, breakdown = score_t3b(
            tsub, ma, weekly, volatility, closes, highs, lows)
        result["lowdip_score"] = score
        result["lowdip_reasons"] = reasons
        result["lowdip_breakdown"] = breakdown
        result["group"] = "T3b"
    elif tcode == "T2" or (tcode == "T3" and tsub == "T3a"):
        score, reasons, breakdown = score_lowdip(
            tsub, ma, weekly, volatility, closes, highs, lows)
        result["lowdip_score"] = score
        result["lowdip_reasons"] = reasons
        result["lowdip_breakdown"] = breakdown
        result["group"] = tsub or tcode  # "T3a"/"T2"

        # Step5/七: 四道程序校验 + 结构失效位 —— 仅对可小额试仓的 T2/T3a 判定
        shares = load_position_record(code) if config else 0
        prog = _run_program_check(config, code, shares, cur, score,
                                  ma, structure, volatility, closes, highs, trend)
        result["program_check"] = prog
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
    """Check cached kline data and append latest records if any are missing."""
    if not etfs:
        return 0

    sample_code = etfs[0]["code"]
    sample_data = run_westock("kline", sample_code, "--period", "day", "--limit", str(CHECK_DAYS))
    if not sample_data or not isinstance(sample_data, list) or len(sample_data) == 0:
        print("  ⚠ 无法获取最新交易日期, 跳过更新检查")
        return 0
    latest_available_date = sample_data[0]["date"]

    to_update = []
    to_refresh = []
    for e in etfs:
        code = e["code"]
        cached = kline_data.get(code)
        if not cached or not isinstance(cached, list) or len(cached) == 0:
            to_update.append(code)
            continue
        latest_cached_date = cached[0]["date"]
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
                        kline_data[code] = new_data
                        updated += 1
                    elif cached and isinstance(cached, list) and len(cached) > 0:
                        latest_cached_date = cached[0]["date"]
                        new_records = [r for r in new_data if r["date"] > latest_cached_date]
                        if new_records:
                            kline_data[code] = new_records + cached
                            updated += 1
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

    if updated > 0:
        with open(kline_file, "w") as f:
            json.dump(kline_data, f, ensure_ascii=False)
        print(f"K线数据已保存: {kline_file}")

    return updated


def main():
    refresh_today = "--no-refresh" not in sys.argv
    print("=" * 60)
    print("A股ETF 低吸机会扫描 (T0-T8状态机, 目标 T2 + T3a)")
    if refresh_today:
        print("🔄 盘中刷新模式: 同日期数据将用最新数据替换 (默认开启, --no-refresh 关闭)")
    print("=" * 60)

    print("\n📋 加载ETF列表...")
    etfs = load_etfs()
    if not etfs:
        print("❌ 未找到ETF列表。请确保 all_etfs_larggest.json 存在于项目根目录。")
        return
    # SOP Step1 硬门槛: 规模大于 AUM_FLOOR, 避免清盘/流动性风险
    etfs = [e for e in etfs if (e.get("size") or 0) >= AUM_FLOOR]
    print(f"共加载 {len(etfs)} 只ETF (AUM ≥ {AUM_FLOOR/1e8:.0f}亿)")

    kline_file = os.path.join(os.getcwd(), "etf_kline_data.json")
    if not os.path.exists(kline_file):
        print(f"❌ 未找到K线数据: {kline_file}")
        return
    print(f"\n📊 加载K线数据: {kline_file}")
    with open(kline_file) as f:
        kline_data = json.load(f)
    print(f"已加载 {len(kline_data)} 只ETF K线数据")

    if refresh_today:
        updated = update_kline_data(kline_data, etfs, kline_file, refresh_today)
        if updated > 0:
            print(f"已更新 {updated} 只ETF")
        else:
            print("K线数据已是最新，无需更新")

    print("\n🔍 运行T0-T8趋势状态机...")
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    # SOP 程序校验层: 组合配置 + 持仓流水 (金额/权重/成本参数全部来自 config)
    config = load_portfolio_config()
    results = []
    for e in etfs:
        kl = kline_data.get(e["code"])
        if not kl:
            continue
        r = analyze_etf(e["code"], e["name"], e["type"], e.get("size"), kl,
                        config=config)
        if r:
            results.append(r)

    # 筛出低吸目标 (T2 + T3a) 与建仓白名单(T3b), 按低吸置信度排序
    t2_list = [r for r in results if r["trend_state"]["code"] == "T2"]
    t3a_list = [r for r in results if r["trend_state"]["code"] == "T3" and r["trend_state"].get("sub_state") == "T3a"]
    t3b_list = [r for r in results if r["trend_state"]["code"] == "T3" and r["trend_state"].get("sub_state") == "T3b"]
    t2_list.sort(key=lambda x: x.get("lowdip_score", 0), reverse=True)
    t3a_list.sort(key=lambda x: x.get("lowdip_score", 0), reverse=True)
    t3b_list.sort(key=lambda x: x.get("lowdip_score", 0), reverse=True)

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

    def print_panel(title, lst):
        print(f"\n🏆 {title}: {len(lst)} 只")
        print(f"{'排名':<4}{'ETF':<16}{'低吸分':<6}{'校验':<6}{'250位%':<8}{'马60斜率':<8}{'动量':<8}")
        print("-" * 76)
        for i, r in enumerate(lst[:20]):
            b = r.get("lowdip_breakdown", {})
            pc = r.get("program_check") or {}
            verdict = pc.get("verdict", "-") if pc else "-"
            print(f"{i+1:<4}{r['name']:<16}{r.get('lowdip_score', 0):<6}{verdict:<6}"
                  f"{b.get('pos250', '-'):<8}{b.get('ma60_slope_pct', '-'):<8}"
                  f"{b.get('mom', 0): <+8.1f}")

    print_panel("T3a 低吸候选 (反转初步确认, MA60仍下行)", t3a_list)
    print_panel("T2 低吸候选 (底部构建)", t2_list)
    print_panel("T3b 建仓白名单 (MA60走平/转上)", t3b_list)

    # 四道程序校验汇总
    pass_count = 0
    fail_reasons = {}
    for r in (t3a_list + t2_list):
        pc = r.get("program_check")
        if not pc:
            continue
        if pc.get("verdict") == "PASS":
            pass_count += 1
        else:
            gate = pc.get("gate", "未知")
            fail_reasons[gate] = fail_reasons.get(gate, 0) + 1
    print(f"\n✅ 四道程序校验结果: 可小额试仓 {pass_count} 只; 拦截 {len(t3a_list)+len(t2_list)-pass_count} 只")
    for k, v in sorted(fail_reasons.items(), key=lambda x: -x[1]):
        print(f"   ❌ {k}: {v}")

    out = {
        "meta": {
            "generated": dt.datetime.now().isoformat(),
            "sample_size": len(results),
            "aum_floor": AUM_FLOOR,
            "kline_file": kline_file,
            "config_file": CONFIG_PATH,
        },
        "state_distribution": dist,
        "t3a_count": len(t3a_list),
        "t2_count": len(t2_list),
        "t3b_count": len(t3b_list),
        "program_check_summary": {
            "pass": pass_count,
            "fail": len(t3a_list) + len(t2_list) - pass_count,
            "fail_gates": fail_reasons,
        },
        "results": results,
    }
    results_file = os.path.join(skill_dir, "etf_lowdip_results.json")
    with open(results_file, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n分析结果已保存: {results_file}")


if __name__ == "__main__":
    main()