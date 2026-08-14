#!/usr/bin/env python3
"""
ETF operation decision engine.

Computes **machine-readable** operation actions with three program-level
validations, so the report layer cannot hand-wave a conclusion that the trend
state forbids. The six output fields are:

    current_action         HOLD | ADD | REDUCE | EXIT | WAIT
    action_reason          当前生效趋势状态及核心证据
    trigger_conditions     触发动作的可计算条件（增/减/退，各带 order size）
    order_size             本次调整占目标仓位的比例（有组合配置时附绝对金额）
    invalidation_condition 本次操作逻辑失效条件
    next_review_trigger    下一次重新计算条件

Validations (all enforced in code, not just declared in prose):
    1. validate_action        state + role vs proposed action legality
    2. validate_risk_reward   reward/risk >= 2 required for tactical adds
    3. validate_sizing        gap / add-cap / risk-budget / max-weight caps

Usage:
    from operation_engine import decide
    result = decide(state_code="T1", sub_state=None, role="core_hedge",
                    config=..., shares=300, book_cost=8.637, price=9.042,
                    structural_invalidation=8.16, planned_entry=8.75,
                    first_observation=9.44, atr20=0.126, ma60_dir="down")
"""
import json


# ─── Action legality matrix ────────────────────────────────────────────────
# Forbidden actions per trend state. CHASE = 追高, AVERAGE_DOWN = 摊低成本.
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

# Base action per state (before role/validation refinement)
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

# Can this state ever accumulate a tactical add (subject to RR >= 2)?
CAN_ADD = {"T2", "T3a", "T3b", "T4"}

# Per-state action_reason prefix
STATE_LABEL = {
    "T0": "长期下降", "T1": "下降减速", "T2": "底部构建",
    "T3a": "反转初步确认(MA60仍向下)", "T3b": "反转初步确认(MA60转上)",
    "T4": "中期上升确认", "T5": "上升加速", "T6": "高位整理",
    "T7": "趋势衰竭", "T8": "结构破坏",
}


def is_core(role):
    """Roles starting with 'core' are core positions; others are tactical."""
    return isinstance(role, str) and role.startswith("core")


def pct_of_target(action):
    """Order size as % of target position, per action (no config needed)."""
    return {"ADD": 20, "REDUCE": 50, "EXIT": 100, "HOLD": None, "WAIT": None}.get(action)


# ─── Validation 1: action legality ────────────────────────────────────────
def validate_action(state_code, role, proposed_action):
    """Return (allowed: bool, reason: str)."""
    if state_code not in FORBIDDEN:
        return False, f"未知状态 {state_code}"
    forbid = FORBIDDEN[state_code]
    if proposed_action in forbid:
        return False, f"{state_code} + {proposed_action} => 拒绝"
    # A core position never chases or adds except in confirmed uptrend
    if is_core(role) and proposed_action == "CHASE":
        return False, f"核心仓位({role}) + CHASE => 拒绝"
    return True, "ok"


# ─── Validation 2: risk-reward ────────────────────────────────────────────
def validate_risk_reward(planned_entry, structural_invalidation, first_observation):
    """reward = first_observation - planned_entry; risk = planned_entry - invalidation.
    Return (pass: bool, rr: float|None, reason: str)."""
    if planned_entry is None or structural_invalidation is None or first_observation is None:
        return False, None, "缺少计划买入价/结构失效位/第一观察区，无法计算风险收益"
    reward = first_observation - planned_entry
    risk = planned_entry - structural_invalidation
    if risk <= 0:
        return False, 0.0, f"风险<=0（计划买入价 {planned_entry} 未高于失效位 {structural_invalidation}），无效"
    rr = reward / risk
    ok = rr >= 2.0
    return ok, round(rr, 2), f"reward/risk = {rr:.2f}{'' if ok else '（<2，禁止加仓）'}"


# ─── Validation 3: position sizing ────────────────────────────────────────
def validate_sizing(proposed_amount, target_gap, single_add_cap,
                    expected_loss, risk_budget, adj_weight_pct, max_weight_pct):
    """Return (pass: bool, checks: list[(label, bool)])."""
    checks = [
        ("建议买入金额<=目标仓位缺口", proposed_amount <= target_gap + 1e-9),
        ("建议买入金额<=单次增仓上限", proposed_amount <= single_add_cap + 1e-9),
        ("预计损失<=单标的风险预算", expected_loss <= risk_budget + 1e-9),
        ("调整后权重<=最大权重", adj_weight_pct <= max_weight_pct + 1e-9),
    ]
    return all(ok for _, ok in checks), checks


# ─── Trigger templates ─────────────────────────────────────────────────────
def build_triggers(state_code, sub_state, structural_invalidation, planned_entry,
                   first_observation, ma60_dir, atr20):
    """Generate add/reduce/exit triggers with order sizes, tied to state."""
    triggers = []

    # ADD triggers — only for states that can add, subject to RR gate
    if state_code in CAN_ADD:
        need = "T3b" if state_code in ("T2", "T3a") else state_code
        cond_parts = []
        if state_code in ("T2", "T3a"):
            cond_parts.append(f"完整周线状态迁移为 {need}")
        if state_code in ("T2", "T3a", "T3b", "T4"):
            cond_parts.append("MA60 斜率走平或转正")
            cond_parts.append("日线回踩 MA20/MA60 附近后收盘重新站回")
        cond_parts.append(f"reward/risk（{first_observation}−{planned_entry} vs {planned_entry}−{structural_invalidation}）>= 2")
        triggers.append({
            "type": "add",
            "condition": " 且 ".join(cond_parts),
            "size_pct": 20,
            "size_desc": "首次增加目标仓位 20%（第二周继续确认且未明显扩张，再增加 20%）",
        })

    # REDUCE trigger
    if structural_invalidation is not None:
        triggers.append({
            "type": "reduce",
            "condition": f"连续 2 日收盘低于结构失效位（{structural_invalidation}）",
            "size_pct": 50,
            "size_desc": "降低战术仓位 50%",
        })

    # EXIT trigger
    exit_cond = "完整周线进入 T8"
    if atr20 and structural_invalidation is not None:
        disaster = round(structural_invalidation - 1.0 * atr20, 3)
        exit_cond += f"，或单日收盘跌破灾难保护位（{disaster}，超 1 ATR）"
    triggers.append({
        "type": "exit",
        "condition": exit_cond,
        "size_pct": 100,
        "size_desc": "退出剩余战术仓位（核心仓位是否退出由组合用途决定）",
    })

    return triggers


# ─── Main decision ─────────────────────────────────────────────────────────
def decide(state_code, sub_state=None, role="core", config=None, code=None,
           shares=0, book_cost=0.0, price=0.0,
           structural_invalidation=None, planned_entry=None,
           first_observation=None, atr20=None, ma60_dir="flat"):
    """Return the six machine-readable fields plus validation audit trail."""
    # Effective state (sub-state T3a/T3b maps to its own code for action rules)
    eff_state = state_code

    # Proposed base action from state, refined by role
    proposed = BASE_ACTION.get(state_code, "HOLD")
    # Tactical role may be more active on T3b/T4 (add on pullback); core stays HOLD
    if state_code in ("T3b", "T4") and not is_core(role):
        proposed = "ADD"
    # Tactical role exits outright in T0/T8 (no long-term logic to hold onto)
    if state_code in ("T0", "T8") and not is_core(role):
        proposed = "EXIT"

    # Validation 1: collect forbidden actions for this state (audit trail)
    legal_checks = []
    for candidate in ("ADD", "AVERAGE_DOWN", "CHASE"):
        allowed, reason = validate_action(state_code, role, candidate)
        if not allowed:
            legal_checks.append(reason)
    action_legal = proposed not in FORBIDDEN.get(state_code, set())

    # If the proposed action is forbidden (defensive), downgrade to HOLD.
    if proposed in FORBIDDEN.get(state_code, set()):
        proposed = "HOLD"

    # Validation 2: risk-reward gate for ADD
    rr_pass, rr, rr_reason = (None, None, "不适用（当前非加仓动作）")
    if proposed == "ADD":
        rr_pass, rr, rr_reason = validate_risk_reward(planned_entry, structural_invalidation, first_observation)
        if not rr_pass:
            proposed = "HOLD"
            rr_reason += " → 动作降级为 HOLD"

    # Validation 3: sizing (only when config present)
    sizing_pass = True
    sizing_checks = []
    order_size = None
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

        # single-add cap = 20% of gap (first batch), risk budget = portfolio * budget%
        single_add_cap = max(gap, 0.0) * 0.20
        risk_budget = portfolio_value * risk_budget_pct / 100.0

        if proposed == "ADD":
            unit_risk = (planned_entry - structural_invalidation) if planned_entry and structural_invalidation else 0.0
            affordable_by_risk = risk_budget / unit_risk if unit_risk > 0 else float("inf")
            proposed_amount = min(single_add_cap, gap)  # capped by gap
            # also cap by risk budget
            proposed_amount = min(proposed_amount, affordable_by_risk)
            adj_value = current_value + proposed_amount
            adj_weight = adj_value / portfolio_value * 100 if portfolio_value else 0.0
            expected_loss = (planned_entry - structural_invalidation) / planned_entry * proposed_amount if planned_entry else 0.0

            sizing_pass, sizing_checks = validate_sizing(
                proposed_amount, gap, single_add_cap, expected_loss, risk_budget, adj_weight, max_weight)
            if not sizing_pass:
                proposed = "HOLD"
            else:
                order_size = {
                    "pct_of_target": 20,
                    "amount": round(proposed_amount, 2),
                    "target_value": round(target_value, 2),
                    "current_value": round(current_value, 2),
                    "gap": round(gap, 2),
                    "current_weight_pct": round(current_weight, 1),
                }
        else:
            # non-ADD: report sizing context without a buy order
            order_size = {
                "pct_of_target": None,
                "amount": None,
                "target_value": round(target_value, 2),
                "current_value": round(current_value, 2),
                "gap": round(gap, 2),
                "current_weight_pct": round(current_weight, 1),
            }
            if current_weight > max_weight:
                sizing_pass = False
                sizing_checks.append(("调整后权重<=最大权重", False))
    else:
        # no config: percentage-level action only, no absolute amounts
        order_size = {"pct_of_target": pct_of_target(proposed), "amount": None,
                      "note": "未提供组合配置，仅输出相对目标仓位的百分比动作"}

    # Fill pct_of_target for non-ADD actions in the config path too
    if order_size is not None and order_size.get("pct_of_target") is None:
        order_size["pct_of_target"] = pct_of_target(proposed)

    # Build trigger conditions
    triggers = build_triggers(state_code, sub_state, structural_invalidation,
                              planned_entry, first_observation, ma60_dir, atr20)

    # Forbidden actions summary
    forbidden = sorted(FORBIDDEN.get(state_code, set()))

    # Invalidation & review
    invalidation = f"当前逻辑基于 {state_code}（{STATE_LABEL.get(state_code,'')}）"
    if structural_invalidation is not None:
        invalidation += f"；收盘连续跌破结构失效位 {structural_invalidation} 即失效"
    if state_code in ("T0", "T1"):
        invalidation += "；若周线转上进入 T3b 则逻辑升级为可增仓"

    next_review = "周五收盘后（完整周线形成后重新计算），或提前触及上述任意触发位"

    return {
        "current_action": proposed,
        "action_reason": f"{state_code}{('('+sub_state+')') if sub_state else ''} {STATE_LABEL.get(state_code,'')}：{base_reason(state_code, role)}",
        "trigger_conditions": triggers,
        "order_size": order_size,
        "invalidation_condition": invalidation,
        "next_review_trigger": next_review,
        "forbidden_actions": forbidden,
        "validations": {
            "action_legal": {"pass": action_legal, "rejected": legal_checks},
            "risk_reward": {"pass": rr_pass, "rr": rr, "reason": rr_reason},
            "sizing": {"pass": sizing_pass, "checks": sizing_checks},
        },
    }


def base_reason(state_code, role):
    """One-line reason for the base action."""
    m = {
        "T0": "周线向下+空头排列+低点降低，中期趋势向下",
        "T1": "周线仍向下但日线减速/反弹，未确认反转",
        "T2": "近低位+低点抬高，筑底中",
        "T3a": "价格结构转强但MA60仍下行，反转初步确认",
        "T3b": "MA60走平/转上，反转确认可分批加仓",
        "T4": "多头排列+MA60/120向上+HH/HL，中期上升确认",
        "T5": "趋势加速但过热，不追高",
        "T6": "高位整理，等待方向选择",
        "T7": "高位滞涨/动能背离，警惕顶部",
        "T8": "周线结构失效，中期逻辑破位",
    }
    return m.get(state_code, "")


# ─── CLI ───────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(description="ETF operation decision engine")
    p.add_argument("--state", required=True, help="trend state code e.g. T1")
    p.add_argument("--sub-state", default=None)
    p.add_argument("--role", default="core")
    p.add_argument("--code", required=True, help="ETF code for config lookup")
    p.add_argument("--config", help="path to portfolio_config.json")
    p.add_argument("--shares", type=float, default=0)
    p.add_argument("--book-cost", type=float, default=0)
    p.add_argument("--price", type=float, default=0)
    p.add_argument("--invalidation", type=float, default=None)
    p.add_argument("--entry", type=float, default=None)
    p.add_argument("--observation", type=float, default=None)
    p.add_argument("--atr20", type=float, default=None)
    p.add_argument("--ma60-dir", default="flat")
    args = p.parse_args()

    config = None
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    result = decide(
        state_code=args.state, sub_state=args.sub_state, role=args.role,
        config=config, code=args.code,
        shares=args.shares, book_cost=args.book_cost, price=args.price,
        structural_invalidation=args.invalidation, planned_entry=args.entry,
        first_observation=args.observation, atr20=args.atr20, ma60_dir=args.ma60_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
