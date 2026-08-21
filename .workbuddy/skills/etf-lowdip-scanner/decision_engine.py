#!/usr/bin/env python3
"""
ETF operation decision engine — copied from
.workbuddy/skills/etf-operation-plan/operation_engine.py (v1.1 align).

Addition for etf-lowdip-scanner: a `trial` mode. When `trial=True` and the
trend state is T2 / T3a, the base action is forced to a **小额试仓 ADD**
(10% of target position, vs the 20% of a full 建仓 ADD). The four program
validations still run verbatim — action legality / risk-reward rr_net>=2 /
position sizing / trading cost — and a candidate that fails any gate is
demoted to HOLD (WAIT). This lets the SOP "门口" legally open tiny trial
positions in T2/T3a (which operation_engine's default T3b/T4-white-list does
not), without pretending trial == full 建仓.

All params come from records/portfolio_config.json (passed via `config`),
never hardcoded.
"""
import json


# ─── Action legality matrix ────────────────────────────────────────────────
FORBIDDEN = {
    "T0": {"ADD", "AVERAGE_DOWN", "CHASE"},
    "T1": {"ADD", "AVERAGE_DOWN", "CHASE"},
    "T2": {"CHASE"},
    "T3a": {"CHASE"},
    "T3b": {"CHASE"},
    "T4": {"CHASE"},
    "T5": {"ADD", "CHASE"},
    "T6": {"ADD", "CHASE"},
    "T7": {"ADD", "AVERAGE_DOWN", "CHASE"},
    "T8": {"ADD", "AVERAGE_DOWN", "CHASE"},
}

BASE_ACTION = {
    "T0": "REDUCE",
    "T1": "HOLD",
    "T2": "WAIT",
    "T3a": "HOLD",
    "T3b": "HOLD",
    "T4": "HOLD",
    "T5": "HOLD",
    "T6": "HOLD",
    "T7": "REDUCE",
    "T8": "EXIT",
}

CAN_ADD = {"T2", "T3a", "T3b", "T4"}

STATE_LABEL = {
    "T0": "长期下降", "T1": "下降减速", "T2": "底部构建",
    "T3": "反转初步确认", "T3a": "反转初步确认(MA60仍向下)", "T3b": "反转初步确认(MA60转上)",
    "T4": "中期上升确认", "T5": "上升加速", "T6": "高位整理",
    "T7": "趋势衰竭", "T8": "结构破坏",
}

# 小额试仓 = 10% of target position; 完整建仓 ADD = 20%
TRIAL_ADD_PCT = 10
FULL_ADD_PCT = 20


def is_core(role):
    return isinstance(role, str) and role.startswith("core")


def pct_of_target(action):
    return {"ADD": FULL_ADD_PCT, "REDUCE": 50, "EXIT": 100,
            "HOLD": None, "WAIT": None}.get(action)


# ─── Validation 1: action legality ────────────────────────────────────────
def validate_action(state_code, role, proposed_action):
    if state_code not in FORBIDDEN:
        return False, f"未知状态 {state_code}"
    forbid = FORBIDDEN[state_code]
    if proposed_action in forbid:
        return False, f"{state_code} + {proposed_action} => 拒绝"
    if is_core(role) and proposed_action == "CHASE":
        return False, f"核心仓位({role}) + CHASE => 拒绝"
    return True, "ok"


# ─── Validation 2: risk-reward (cost-adjusted) ─────────────────────────────
def validate_risk_reward(planned_entry, structural_invalidation, first_observation,
                         cost_per_share=0.0, rr_floor=2.0):
    if planned_entry is None or structural_invalidation is None or first_observation is None:
        return False, None, "缺少计划买入价/结构失效位/第一观察区，无法计算风险收益"
    reward = first_observation - planned_entry
    risk = planned_entry - structural_invalidation
    if risk <= 0:
        return False, 0.0, f"风险<=0（计划买入价 {planned_entry} 未高于失效位 {structural_invalidation}），无效"
    reward_net = reward - cost_per_share
    rr_net = reward_net / risk
    ok = rr_net >= rr_floor
    return ok, round(rr_net, 2), f"reward/risk = {rr_net:.2f}{'（含每股成本 ' + str(round(cost_per_share, 4)) + '）' if cost_per_share else ''}{'' if ok else f'（<{rr_floor}，禁止试仓/加仓）'}"


# ─── Validation 3: position sizing ────────────────────────────────────────
def validate_sizing(proposed_amount, target_gap, single_add_cap,
                    expected_loss, risk_budget, adj_weight_pct, max_weight_pct):
    checks = [
        ("建议买入金额<=目标仓位缺口", proposed_amount <= target_gap + 1e-9),
        ("建议买入金额<=单次增仓上限", proposed_amount <= single_add_cap + 1e-9),
        ("预计损失<=单标的风险预算", expected_loss <= risk_budget + 1e-9),
        ("调整后权重<=最大权重", adj_weight_pct <= max_weight_pct + 1e-9),
    ]
    return all(ok for _, ok in checks), checks


# ─── Validation 4: trading cost（小资金致命项进入决策链）────────────────────
def validate_cost(shares, trade_price, commission_rate, min_commission, half_spread,
                  impact_pct, lot_size, planned_entry, first_observation,
                  structural_invalidation, max_cost_pct_of_trade=1.0,
                  max_cost_pct_of_reward=15.0, rr_floor=2.0):
    reasons = []
    if shares < lot_size:
        return False, None, [f"订单份额 {shares} 低于最小交易单位（1手={lot_size}份）"]

    amount = shares * trade_price
    commission = max(min_commission, amount * commission_rate)
    spread = amount * half_spread
    impact = amount * impact_pct
    cost = commission + spread + impact
    cost_pct_of_trade = cost / amount * 100 if amount > 0 else 0.0
    cost_per_share = cost / shares

    if cost_pct_of_trade > max_cost_pct_of_trade:
        reasons.append(f"单边成本 {cost_pct_of_trade:.2f}% 超阈值 {max_cost_pct_of_trade}%"
                       f"（最低佣金 {min_commission:.0f} 元主导，成交额仅 {amount:.0f} 元）")

    reward = (first_observation - planned_entry) if (first_observation and planned_entry) else 0.0
    cost_share_of_reward = (cost_per_share / reward * 100) if reward > 0 else float("inf")
    if reward <= 0 or cost_share_of_reward > max_cost_pct_of_reward:
        r = f"成本吃掉预期收益 {cost_share_of_reward:.1f}% 超阈值 {max_cost_pct_of_reward}%" \
            if reward > 0 else "第一观察区未高于计划买入价，预期收益<=0"
        reasons.append(r)

    risk = (planned_entry - structural_invalidation) if (planned_entry and structural_invalidation) else 0.0
    reward_net = reward - cost_per_share
    rr_net = reward_net / risk if risk > 0 else 0.0
    if rr_net < rr_floor:
        reasons.append(f"成本调整后 RR = {rr_net:.2f} < {rr_floor}")

    ok = not reasons
    cost_info = {
        "amount": round(amount, 2),
        "shares": shares,
        "cost_amount": round(cost, 2),
        "cost_pct_of_trade": round(cost_pct_of_trade, 3),
        "cost_per_share": round(cost_per_share, 4),
        "cost_share_of_reward": round(cost_share_of_reward, 2) if reward > 0 else None,
        "rr_net": round(rr_net, 2),
    }
    return ok, cost_info, reasons


# ─── Trigger templates ─────────────────────────────────────────────────────
def build_triggers(state_code, sub_state, structural_invalidation, planned_entry,
                   first_observation, ma60_dir, atr20, role="core", trial=False):
    triggers = []
    core = is_core(role)
    pos_label = "核心仓" if core else "战术仓"
    entry_word = "小额试仓" if trial else "分批加仓"

    if state_code in CAN_ADD:
        need = "T3b" if state_code in ("T2", "T3a") else state_code
        cond_parts = []
        if state_code in ("T2", "T3a"):
            cond_parts.append(f"完整周线状态迁移为 {need}")
        if state_code in ("T2", "T3a", "T3b", "T4"):
            cond_parts.append("MA60 斜率走平或转正")
            cond_parts.append("日线回踩 MA20/MA60 附近后收盘重新站回")
        cond_parts.append(f"reward/risk（{first_observation}−{planned_entry} vs {planned_entry}−{structural_invalidation}）>= 2（成本调整后）")
        cond_parts.append("通过交易成本门（单边成本占比/成本占预期收益/最小1手）")
        triggers.append({
            "type": ("trial_add" if trial else "add"),
            "condition": " 且 ".join(cond_parts),
            "size_pct": TRIAL_ADD_PCT if trial else FULL_ADD_PCT,
            "size_desc": f"{entry_word}{pos_label}目标仓位 {TRIAL_ADD_PCT if trial else FULL_ADD_PCT}%"
                         f"（{'T2/T3a 小额试仓，周线升级后可按建仓节奏加仓' if trial else '第二周继续确认且未明显扩张，再增加 20%'}）",
        })

    if structural_invalidation is not None:
        triggers.append({
            "type": "reduce",
            "condition": f"连续 2 日收盘低于结构失效位（{structural_invalidation}）",
            "size_pct": 50,
            "size_desc": f"降低{pos_label} 50%",
        })

    exit_cond = "完整周线进入 T8"
    if atr20 and structural_invalidation is not None:
        disaster = round(structural_invalidation - 1.0 * atr20, 3)
        exit_cond += f"，或单日收盘跌破灾难保护位（{disaster}，超 1 ATR）"
    triggers.append({
        "type": "exit",
        "condition": exit_cond,
        "size_pct": 100,
        "size_desc": ("退出剩余核心仓（是否清仓由组合用途决定）" if core
                      else "退出剩余战术仓（核心仓位是否退出由组合用途决定）"),
    })

    return triggers


# ─── Main decision ─────────────────────────────────────────────────────────
def decide(state_code, sub_state=None, role="core", config=None, code=None,
           shares=0, book_cost=0.0, price=0.0,
           structural_invalidation=None, planned_entry=None,
           first_observation=None, atr20=None, ma60_dir="flat",
           commission_rate=None, min_commission=None, half_spread=None,
           impact_pct=None, lot_size=None, max_cost_pct_of_trade=None,
           max_cost_pct_of_reward=None, trial=False, trial_rr_floor=1.2):
    costs_cfg = (config or {}).get("costs") or {}
    commission_rate = commission_rate if commission_rate is not None else costs_cfg.get("commission_rate", 0.00025)
    min_commission = min_commission if min_commission is not None else costs_cfg.get("min_commission", 5.0)
    half_spread = half_spread if half_spread is not None else costs_cfg.get("half_spread", 0.0005)
    impact_pct = impact_pct if impact_pct is not None else costs_cfg.get("impact_pct", 0.0)
    lot_size = lot_size if lot_size is not None else costs_cfg.get("lot_size", 100)
    max_cost_pct_of_trade = max_cost_pct_of_trade if max_cost_pct_of_trade is not None else costs_cfg.get("max_cost_pct_of_trade", 1.0)
    max_cost_pct_of_reward = max_cost_pct_of_reward if max_cost_pct_of_reward is not None else costs_cfg.get("max_cost_pct_of_reward", 15.0)

    # 小额试仓(T2/T3a)用更低 RR 门槛放行极小仓位; 完整建仓保持 rr>=2(=rr_floor 默认)
    trial_rr_floor = trial_rr_floor if trial_rr_floor is not None else 1.2

    # trend_analysis 返回 code="T3" + sub_state=T3a/T3b；归一化为子态以命中硬约束矩阵
    if state_code == "T3" and sub_state in ("T3a", "T3b"):
        state_code = sub_state
        sub_state = None

    proposed = BASE_ACTION.get(state_code, "HOLD")
    if state_code in ("T3b", "T4") and not is_core(role):
        proposed = "ADD"
    if state_code in ("T0", "T8") and not is_core(role):
        proposed = "EXIT"

    # 小额试仓门控：T2 / T3a 允许打开小额试仓偏仓（SOP 门口=T2/T3a小额试仓）
    trial_state = trial and state_code in ("T2", "T3a")

    legal_checks = []
    for candidate in ("ADD", "AVERAGE_DOWN", "CHASE"):
        allowed, reason = validate_action(state_code, role, candidate)
        if not allowed:
            legal_checks.append(reason)
    action_legal = proposed not in FORBIDDEN.get(state_code, set())

    if proposed in FORBIDDEN.get(state_code, set()):
        proposed = "HOLD"

    # T2/T3a 小额试仓：base action 默认是 WAIT/HOLD，试仓模式将之提升为小额 ADD
    trial_mode = False
    if trial_state:
        proposed = "ADD"
        trial_mode = True
        if "T2 + ADD" in legal_checks or "T3a + ADD" in legal_checks:
            # defensive, should not happen (ADD legal in T2/T3a)
            proposed = "HOLD"
            trial_mode = False

    rr_pass, rr, rr_reason = (None, None, "不适用（当前非加仓动作）")
    if proposed == "ADD":
        rr_pass, rr, rr_reason = validate_risk_reward(planned_entry, structural_invalidation, first_observation,
                                                      rr_floor=trial_rr_floor if trial_mode else 2.0)
        if not rr_pass:
            proposed = "HOLD"
            rr_reason += " → 动作降级为 HOLD"

    sizing_pass = True
    sizing_checks = []
    order_size = None
    cost_pass = True
    cost_info = None
    cost_reasons = ["不适用（当前非加仓动作或价格不可用，未计算金额级交易成本）"]
    if config and price > 0:
        portfolio_value = config.get("portfolio_value", 0)
        pos_cfg = (config.get("positions") or {}).get(code, {}) if code else {}
        target_weight = pos_cfg.get("target_weight_pct", 0)
        max_weight = pos_cfg.get("max_weight_pct", 100)
        risk_budget_pct = pos_cfg.get("risk_budget_pct", 1.0)

        target_value = portfolio_value * target_weight / 100.0
        current_value = shares * price
        gap = target_value - current_value
        current_weight = current_value / portfolio_value * 100 if portfolio_value else 0.0

        single_add_cap = max(gap, 0.0) * (TRIAL_ADD_PCT / 100.0 if trial_mode else (FULL_ADD_PCT / 100.0))
        risk_budget = portfolio_value * risk_budget_pct / 100.0

        if proposed == "ADD":
            unit_risk = (planned_entry - structural_invalidation) if planned_entry and structural_invalidation else 0.0
            affordable_by_risk = risk_budget / unit_risk if unit_risk > 0 else 0.0
            proposed_amount = min(single_add_cap, gap)
            proposed_amount = min(proposed_amount, affordable_by_risk)
            adj_value = current_value + proposed_amount
            adj_weight = adj_value / portfolio_value * 100 if portfolio_value else 0.0
            expected_loss = (planned_entry - structural_invalidation) / planned_entry * proposed_amount if planned_entry else 0.0

            sizing_pass, sizing_checks = validate_sizing(
                proposed_amount, gap, single_add_cap, expected_loss, risk_budget, adj_weight, max_weight)
            if not sizing_pass:
                proposed = "HOLD"

            cost_pass, cost_info, cost_reasons = True, None, []
            trade_price = planned_entry or price
            if sizing_pass and proposed == "ADD" and trade_price > 0:
                cap_shares = min(int(gap / trade_price / lot_size) * lot_size,
                                 int(single_add_cap / trade_price / lot_size) * lot_size,
                                 int(affordable_by_risk / trade_price / lot_size) * lot_size)
                lot_shares = min(int(proposed_amount / trade_price / lot_size) * lot_size, cap_shares)
                cost_pass, cost_info, cost_reasons = validate_cost(
                    lot_shares, trade_price, commission_rate, min_commission, half_spread,
                    impact_pct, lot_size, planned_entry, first_observation,
                    structural_invalidation, max_cost_pct_of_trade, max_cost_pct_of_reward,
                    rr_floor=trial_rr_floor if trial_mode else 2.0)
                if not cost_pass:
                    proposed = "HOLD"
                    cost_reasons = [r + " → 动作降级为 HOLD" for r in cost_reasons]
            else:
                cost_reasons = ["不适用（已降级/非加仓/价格不可用）"]

            add_pct = TRIAL_ADD_PCT if trial_mode else FULL_ADD_PCT
            if proposed == "ADD" and cost_pass and cost_info:
                order_size = {
                    "pct_of_target": add_pct,
                    "amount": round(cost_info["amount"], 2),
                    "shares": cost_info["shares"],
                    "cost_amount": round(cost_info["cost_amount"], 2),
                    "cost_pct_of_trade": cost_info["cost_pct_of_trade"],
                    "cost_per_share": cost_info["cost_per_share"],
                    "cost_share_of_reward_pct": cost_info["cost_share_of_reward"],
                    "rr_net": cost_info["rr_net"],
                    "target_value": round(target_value, 2),
                    "current_value": round(current_value, 2),
                    "gap": round(gap, 2),
                    "current_weight_pct": round(current_weight, 1),
                }
            else:
                order_size = {
                    "pct_of_target": None,
                    "amount": None,
                    "shares": None,
                    "cost_amount": None,
                    "cost_pct_of_trade": None,
                    "cost_per_share": None,
                    "cost_share_of_reward_pct": None,
                    "rr_net": None,
                    "target_value": round(target_value, 2),
                    "current_value": round(current_value, 2),
                    "gap": round(gap, 2),
                    "current_weight_pct": round(current_weight, 1),
                }
                if current_weight > max_weight:
                    sizing_pass = False
                    sizing_checks.append(("调整后权重<=最大权重", False))
        else:
            order_size = {
                "pct_of_target": None,
                "amount": None,
                "shares": None,
                "cost_amount": None,
                "cost_pct_of_trade": None,
                "cost_per_share": None,
                "cost_share_of_reward_pct": None,
                "rr_net": None,
                "target_value": round(target_value, 2),
                "current_value": round(current_value, 2),
                "gap": round(gap, 2),
                "current_weight_pct": round(current_weight, 1),
            }
            if current_weight > max_weight:
                sizing_pass = False
                sizing_checks.append(("调整后权重<=最大权重", False))
            if proposed in ("REDUCE", "EXIT"):
                exit_pct = 0.5 if proposed == "REDUCE" else 1.0
                exit_amount = current_value * exit_pct
                exit_cost = (max(min_commission, exit_amount * commission_rate)
                             + exit_amount * (half_spread + impact_pct))
                order_size["exit_cost_estimate"] = round(exit_cost, 2)
    else:
        order_size = {"pct_of_target": pct_of_target(proposed), "amount": None,
                      "note": "未提供组合配置，仅输出相对目标仓位的百分比动作"}

    if order_size is not None and order_size.get("pct_of_target") is None:
        order_size["pct_of_target"] = pct_of_target(proposed)

    triggers = build_triggers(state_code, sub_state, structural_invalidation,
                              planned_entry, first_observation, ma60_dir, atr20, role,
                              trial=trial_mode)

    forbidden = sorted(FORBIDDEN.get(state_code, set()))

    invalidation = f"当前逻辑基于 {state_code}（{STATE_LABEL.get(state_code,'')}）"
    if structural_invalidation is not None:
        invalidation += f"；收盘连续跌破结构失效位 {structural_invalidation} 即失效"
    if state_code in ("T0", "T1"):
        invalidation += "；若周线转上进入 T3b 则逻辑升级为可增仓"

    next_review = "周五收盘后（完整周线形成后重新计算），或提前触及上述任意触发位"

    return {
        "current_action": proposed,
        "action_reason": f"{state_code}{('('+sub_state+')') if sub_state else ''} {STATE_LABEL.get(state_code,'')}：{base_reason(state_code, role)}{'（小额试仓门控）' if trial_mode else ''}",
        "trial": trial_mode,  # True = 本动作是小额试仓(T2/T3a)，非完整建仓
        "trigger_conditions": triggers,
        "order_size": order_size,
        "invalidation_condition": invalidation,
        "next_review_trigger": next_review,
        "forbidden_actions": forbidden,
        "validations": {
            "action_legal": {"pass": action_legal, "rejected": legal_checks},
            "risk_reward": {"pass": rr_pass, "rr": rr, "reason": rr_reason},
            "sizing": {"pass": sizing_pass, "checks": sizing_checks},
            "cost": {"pass": cost_pass, "reasons": cost_reasons, "info": cost_info},
        },
    }


def base_reason(state_code, role):
    m = {
        "T0": "周线向下+空头排列+低点降低，中期趋势向下",
        "T1": "周线仍向下但日线减速/反弹，未确认反转",
        "T2": "近低位+低点抬高，筑底中",
        "T3": "价格结构转强，MA60方向决定 T3a/T3b",
        "T3a": "价格结构转强但MA60仍下行，反转初步确认",
        "T3b": "MA60走平/转上，反转确认可分批加仓",
        "T4": "多头排列+MA60/120向上+HH/HL，中期上升确认",
        "T5": "趋势加速但过热，不追高",
        "T6": "高位整理，等待方向选择",
        "T7": "高位滞涨/动能背离，警惕顶部",
        "T8": "周线结构失效，中期逻辑破位",
    }
    return m.get(state_code, "")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ETF lowdip trial decision engine")
    p.add_argument("--state", required=True)
    p.add_argument("--sub-state", default=None)
    p.add_argument("--role", default="core")
    p.add_argument("--config", default=None)
    p.add_argument("--code", default=None)
    p.add_argument("--shares", type=float, default=0)
    p.add_argument("--price", type=float, default=0)
    p.add_argument("--invalidation", type=float, default=None)
    p.add_argument("--entry", type=float, default=None)
    p.add_argument("--observation", type=float, default=None)
    p.add_argument("--atr20", type=float, default=None)
    p.add_argument("--ma60-dir", default="flat")
    p.add_argument("--trial", action="store_true")
    args = p.parse_args()

    config = None
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    result = decide(
        state_code=args.state, sub_state=args.sub_state, role=args.role,
        config=config, code=args.code, shares=args.shares, price=args.price,
        structural_invalidation=args.invalidation, planned_entry=args.entry,
        first_observation=args.observation, atr20=args.atr20,
        ma60_dir=args.ma60_dir, trial=args.trial,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))