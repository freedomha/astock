#!/usr/bin/env python3
"""
ETF 持仓监控：剩余批次触发价提醒 + 权重漂移检查(5/25)

用法：
  python3 monitor.py                    # 全量检查（批次触发 + 权重漂移）
  python3 monitor.py --batch            # 只查批次触发
  python3 monitor.py --drift            # 只查权重漂移
  python3 monitor.py --html out.html    # 额外输出 HTML
  python3 monitor.py --config <path>    # 指定配置(默认同目录 monitor_config.json)
  python3 monitor.py --save-state       # 把本次结果追加到 drift_history.json

依赖：westock-data CLI（~/.workbuddy/westock-data）。Bash 调用需 dangerouslyDisableSandbox。
"""
import argparse
import glob
import json
import math
import os
import subprocess
import sys
import time
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "monitor_config.json")
STATE_FILE = os.path.join(HERE, "drift_history.json")
WD = os.path.expanduser("~/.workbuddy/westock-data")


def find_node():
    cands = sorted(glob.glob(os.path.expanduser("~/.workbuddy/binaries/node/versions/*/bin/node")))
    return cands[-1] if cands else "node"


def _run(args, timeout=90, retries=3):
    last = None
    for _ in range(retries):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            d = json.loads(r.stdout)
            return d["data"] if isinstance(d, dict) and "data" in d else d
        except Exception as e:
            last = e
            time.sleep(1.0)
    return None


_QCACHE, _KCACHE = {}, {}


def fetch_quote(code):
    if code in _QCACHE:
        return _QCACHE[code]
    d = _run([find_node(), f"{WD}/scripts/index.js", "quote", code, "--raw"])
    if isinstance(d, list) and d:
        d = d[0]
    d = d if isinstance(d, dict) else None
    if d is not None:
        _QCACHE[code] = d
    return d


def fetch_kline(code, limit=250):
    key = (code, limit)
    if key in _KCACHE:
        return _KCACHE[key]
    d = _run([find_node(), f"{WD}/scripts/index.js", "kline", code,
              "--period", "day", "--limit", str(limit), "--fq", "qfq", "--raw"])
    d = d if isinstance(d, list) else []
    if d:
        _KCACHE[key] = d
    return d


def ma_of(klines, period):
    """klines 为 newest-first"""
    px = [float(b["last"]) for b in klines[:period]]
    return sum(px) / len(px) if len(px) == period else None


def eval_condition(cond, px, mas, today):
    ty = cond.get("type")
    if ty == "price_below":
        lv = cond["level"]
        return px <= lv, f"现价 {px:.3f} {'≤' if px <= lv else '>'} 触发 {lv}"
    if ty == "price_above":
        lv = cond["level"]
        return px >= lv, f"现价 {px:.3f} {'≥' if px >= lv else '<'} 触发 {lv}"
    if ty == "price_below_ma":
        m = mas.get(cond.get("ma"))
        if m is None:
            return False, f"MA{cond.get('ma')} 数据不足"
        return px <= m, f"现价 {px:.3f} {'≤' if px <= m else '>'} MA{cond['ma']} {m:.3f}"
    if ty == "price_above_ma":
        m = mas.get(cond.get("ma"))
        if m is None:
            return False, f"MA{cond.get('ma')} 数据不足"
        return px > m, f"现价 {px:.3f} {'>' if px > m else '≤'} MA{cond['ma']} {m:.3f}"
    if ty == "time_elapsed":
        ref = datetime.strptime(cond["ref_date"], "%Y-%m-%d").date()
        days = (today - ref).days
        return days >= cond["days"], f"距 {cond['ref_date']} 已 {days} 天（门槛 {cond['days']} 天）"
    return False, f"未知触发类型 {ty}"


def check_batches(cfg, today):
    out = []
    for b in cfg.get("pending_batches", []):
        code = b["code"]
        q = fetch_quote(code)
        if not q:
            out.append(dict(b, ok=None, px=None, detail="行情获取失败"))
            continue
        px = float(q["price"])
        kl = fetch_kline(code)
        mas = {p: ma_of(kl, p) for p in (5, 10, 20, 60, 120)}
        t = b.get("trigger", {})
        conds = t.get("conditions", [])
        results = [eval_condition(c, px, mas, today) for c in conds]
        hits = [r[0] for r in results]
        ok = any(hits) if t.get("mode", "any") == "any" else all(hits)
        cost = max(cfg["costs"]["min_commission"],
                   b["shares"] * px * cfg["costs"]["commission_rate"]) + \
               b["shares"] * px * cfg["costs"]["half_spread"]
        out.append(dict(b, ok=ok, px=px, mas=mas, detail=results,
                        amount=b["shares"] * px, cost=cost,
                        cost_pct=cost / (b["shares"] * px) * 100 if b["shares"] else 0))
    return out


def check_drift(cfg):
    rows, total = [], cfg["cash"]
    qcache = {}
    for h in cfg["holdings"]:
        q = fetch_quote(h["code"])
        qcache[h["code"]] = q
        px = float(q["price"]) if q else None
        mv = h["shares"] * px if px else None
        if mv is not None:
            total += mv
        rows.append(dict(h, px=px, mv=mv))
    rb = cfg["rebalance"]
    for r in rows:
        r["actual_pct"] = (r["mv"] / total * 100) if (total and r["mv"] is not None) else None
        r["dev_abs"] = (r["actual_pct"] - r["target_weight_pct"]) if r["actual_pct"] is not None else None
        r["dev_rel"] = (abs(r["dev_abs"]) / r["target_weight_pct"] * 100) if r["dev_abs"] is not None else None
        r["breach"] = None
        if r["dev_abs"] is not None:
            r["breach"] = (abs(r["dev_abs"]) > rb["band_abs_pct"]) or (r["dev_rel"] > rb["band_rel_pct"])
        # 目标金额与调整手数
        r["target_mv"] = r["target_weight_pct"] / 100 * total
        if r["px"] and r["mv"] is not None:
            delta = r["target_mv"] - r["mv"]
            lots = math.floor(abs(delta) / r["px"] / cfg["costs"]["lot_size"]) * cfg["costs"]["lot_size"]
            r["trade_shares"] = lots if delta > 0 else -lots
            r["trade_amount"] = lots * r["px"]
            if lots:
                r["trade_cost"] = max(cfg["costs"]["min_commission"],
                                      lots * r["px"] * cfg["costs"]["commission_rate"]) + \
                                  lots * r["px"] * cfg["costs"]["half_spread"]
            else:
                r["trade_cost"] = 0.0
    cash_actual = cfg["cash"] / total * 100 if total else None
    cash_target = 100 - sum(h["target_weight_pct"] for h in cfg["holdings"])
    return dict(total=total, rows=rows, cash=cash_actual, cash_target=cash_target,
                cash_breach=(cash_actual is not None and
                             (abs(cash_actual - cash_target) > rb["band_abs_pct"] or
                              abs(cash_actual - cash_target) / cash_target * 100 > rb["band_rel_pct"])),
                rb=rb)


def render_console(cfg, batches, drift, today):
    L = []
    L.append("=" * 78)
    L.append(f"ETF 持仓监控  ·  {today.isoformat()}")
    L.append("=" * 78)
    if batches is not None:
        L.append("\n【批次触发检查】")
        fired = [b for b in batches if b.get("ok")]
        L.append(f"  待执行 {len(batches)} 批，今日触发 {len(fired)} 批")
        for b in batches:
            mark = "✅ 已触发" if b.get("ok") else ("⚠️ 数据缺失" if b.get("ok") is None else "⏳ 未触发")
            L.append(f"\n  [{mark}] {b.get('desc', b['id'])} — {b['name']}({b['code']})  {b['shares']}份")
            if b.get("px") is not None:
                L.append(f"      现价 {b['px']:.3f}｜预计金额 {b['amount']:.0f}元｜费用 {b['cost']:.2f}元({b['cost_pct']:.2f}%)")
            for lab, msg in (b.get("detail") or []):
                L.append(f"      {'√' if lab else '×'} {msg}")
        if fired:
            L.append("\n  → 触发的批次可执行：按计划份数买入即可（单笔≥5,000元可摊薄最低佣金）。")
    if drift is not None:
        L.append(f"\n【权重漂移检查】规则 {drift['rb']['rule']}"
                 f"（绝对>{drift['rb']['band_abs_pct']}pp 或 相对>{drift['rb']['band_rel_pct']}%）")
        L.append(f"  组合总市值 {drift['total']:.2f} 元\n")
        L.append(f"  {'资产':<22}{'现价':>8}{'市值':>10}{'占比':>8}{'目标':>8}{'绝对偏离':>9}{'相对偏离':>9}  状态")
        for r in drift["rows"]:
            dev = f"{r['dev_abs']:+.2f}pp" if r["dev_abs"] is not None else "—"
            rel = f"{r['dev_rel']:.1f}%" if r["dev_rel"] is not None else "—"
            st = "⚠️超限" if r["breach"] else ("✓" if r["breach"] is not None else "—")
            L.append(f"  {r['name'][:20]:<22}{(r['px'] or 0):>8.3f}{(r['mv'] or 0):>10.0f}"
                     f"{(r['actual_pct'] or 0):>7.2f}%{r['target_weight_pct']:>7.1f}%{dev:>9}{rel:>9}  {st}")
        L.append(f"  {'现金':<22}{'—':>8}{cfg['cash']:>10.0f}{(drift['cash'] or 0):>7.2f}%"
                 f"{drift['cash_target']:>7.1f}%{'—':>9}{'—':>9}  {'⚠️超限' if drift['cash_breach'] else '✓'}")
        breach = [r for r in drift["rows"] if r["breach"]] + (["现金"] if drift["cash_breach"] else [])
        if breach:
            L.append(f"\n  → 需再平衡：{len(breach)} 项超限。建议调整（含手数取整与费用）：")
            for r in drift["rows"]:
                if r["breach"] and r.get("trade_shares"):
                    side = "买入" if r["trade_shares"] > 0 else "卖出"
                    L.append(f"      {side} {r['name']} {abs(r['trade_shares'])}份 "
                             f"≈{r['trade_amount']:.0f}元（费用{r['trade_cost']:.2f}元）")
        else:
            L.append("\n  → 无资产超限，无需再平衡。")
    L.append("\n" + "-" * 78)
    L.append("提示：价格类触发每日可查；权重漂移建议每周末（完整周线形成后）跑一次。")
    return "\n".join(L)


def render_html(cfg, batches, drift, today, path):
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;")
    rows_b = ""
    for b in (batches or []):
        st = "已触发" if b.get("ok") else ("数据缺失" if b.get("ok") is None else "未触发")
        cls = "ok" if b.get("ok") else "no"
        det = "".join(f"<li>{esc(m)}</li>" for _, m in (b.get("detail") or []))
        rows_b += (f"<tr><td>{esc(b.get('desc',''))}</td><td>{esc(b['name'])}<br><span class=m>{esc(b['code'])}</span></td>"
                   f"<td>{b['shares']}份</td><td class='{cls}'>{st}</td><td><ul>{det}</ul></td></tr>")
    rows_d = ""
    if drift:
        for r in drift["rows"]:
            st = "超限" if r["breach"] else "正常"
            cls = "no" if r["breach"] else "ok"
            tr = ""
            if r["breach"] and r.get("trade_shares"):
                side = "买入" if r["trade_shares"] > 0 else "卖出"
                tr = f"{side} {abs(r['trade_shares'])}份 ≈{r['trade_amount']:.0f}元"
            rows_d += (f"<tr><td>{esc(r['name'])}</td><td>{r['px']:.3f}</td><td>{r['mv']:.0f}</td>"
                       f"<td>{r['actual_pct']:.2f}%</td><td>{r['target_weight_pct']:.1f}%</td>"
                       f"<td>{r['dev_abs']:+.2f}pp</td><td>{r['dev_rel']:.1f}%</td>"
                       f"<td class='{cls}'>{st}</td><td>{tr}</td></tr>")
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>ETF持仓监控 {today}</title><style>
body{{font-family:-apple-system,"PingFang SC",sans-serif;background:#f5f6f8;color:#2c3e50;padding:24px;line-height:1.7}}
.wrap{{max-width:1000px;margin:0 auto}}h1{{font-size:22px}}h2{{font-size:17px;color:#1f3a5f;border-bottom:2px solid #ecf0f1;padding-bottom:8px;margin:18px 0 10px}}
.card{{background:#fff;border-radius:12px;padding:20px 24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:8px 10px;border-bottom:1px solid #eef1f4;text-align:right}}
th{{background:#f8fafc;color:#5a6b7b}}th:first-child,td:first-child{{text-align:left}}
.ok{{color:#27ae60;font-weight:600}}.no{{color:#c0392b;font-weight:600}}.m{{color:#95a5a6;font-size:11px}}
ul{{margin:0 0 0 16px;padding:0;font-size:12px;color:#5a6b7b}}.sub{{color:#7f8c8d;font-size:13px}}
</style></head><body><div class="wrap">
<h1>ETF 持仓监控</h1><div class="sub">{today} · 批次触发 + 权重漂移（{esc(cfg['rebalance']['rule'])}）</div>
<div class="card"><h2>批次触发检查</h2><table>
<thead><tr><th>批次</th><th>标的</th><th>份数</th><th>状态</th><th>判据</th></tr></thead><tbody>{rows_b}</tbody></table></div>
<div class="card"><h2>权重漂移检查</h2><table>
<thead><tr><th>资产</th><th>现价</th><th>市值</th><th>占比</th><th>目标</th><th>绝对偏离</th><th>相对偏离</th><th>状态</th><th>建议调整</th></tr></thead>
<tbody>{rows_d}</tbody></table></div>
<div class="card"><div class="sub">阈值：绝对偏离&gt;{cfg['rebalance']['band_abs_pct']}pp 或 相对偏离&gt;{cfg['rebalance']['band_rel_pct']}% 触发再平衡。
费用口径：佣金 max(5元, 成交额×万2.5) + 单边价差0.05%。非投资建议。</div></div>
</div></body></html>"""
    open(path, "w", encoding="utf-8").write(html)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--batch", action="store_true", help="只查批次")
    ap.add_argument("--drift", action="store_true", help="只查权重漂移")
    ap.add_argument("--html", default=None)
    ap.add_argument("--save-state", action="store_true")
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    today = date.today()
    do_batch = args.batch or not (args.batch or args.drift)
    do_drift = args.drift or not (args.batch or args.drift)

    batches = check_batches(cfg, today) if do_batch else None
    drift = check_drift(cfg) if do_drift else None

    print(render_console(cfg, batches, drift, today))
    if args.html:
        p = render_html(cfg, batches, drift, today, args.html)
        print(f"\nHTML 已写入：{p}")
    if args.save_state and drift:
        hist = []
        if os.path.exists(STATE_FILE):
            try:
                hist = json.load(open(STATE_FILE, encoding="utf-8"))
            except Exception:
                hist = []
        hist.append({"date": today.isoformat(), "total": round(drift["total"], 2),
                     "weights": {r["code"]: round(r["actual_pct"], 2) for r in drift["rows"]},
                     "cash_pct": round(drift["cash"], 2),
                     "breach": [r["name"] for r in drift["rows"] if r["breach"]]})
        json.dump(hist, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"状态已保存：{STATE_FILE}")


if __name__ == "__main__":
    main()
