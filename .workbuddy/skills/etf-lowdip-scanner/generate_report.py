#!/usr/bin/env python3
"""
生成 A股ETF 低吸机会(T2+T3a)扫描 HTML 报告 (v1)
- 摘要卡片 (状态分布 + T3a/T2统计)
- 状态分布柱状图 (Chart.js)
- T3a / T2 低吸置信度排名表 (各 TOP 25)
- T3a/T2 高分前9名 120日K线缩略图
- 详细分析卡片 (状态机reasons + 低吸置信度分项)
"""

import json
import os
from datetime import datetime


def build_report(out, klines, output_path):
    today = datetime.now().strftime("%Y-%m-%d")

    results = out["results"]
    dist = out["state_distribution"]
    t3a_list = [r for r in results if r["trend_state"]["code"] == "T3"
                and r["trend_state"].get("sub_state") == "T3a"]
    t2_list = [r for r in results if r["trend_state"]["code"] == "T2"]
    t3b_list = [r for r in results if r["trend_state"]["code"] == "T3"
                and r["trend_state"].get("sub_state") == "T3b"]
    t3a_list.sort(key=lambda x: x.get("lowdip_score", 0), reverse=True)
    t2_list.sort(key=lambda x: x.get("lowdip_score", 0), reverse=True)
    t3b_list.sort(key=lambda x: x.get("lowdip_score", 0), reverse=True)
    total = len(results)
    t3a_count = len(t3a_list)
    t2_count = len(t2_list)
    t3b_count = len(t3b_list)

    def avg_score(lst):
        if not lst:
            return None
        return round(sum(r.get("lowdip_score", 0) for r in lst) / len(lst), 1)

    avg_t3a = avg_score(t3a_list)
    avg_t2 = avg_score(t2_list)
    avg_t3b = avg_score(t3b_list)

    state_colors = {
        "T0": "#e74c3c", "T1": "#e67e22", "T2": "#27ae60", "T3": "#2ecc71",
        "T3a": "#2ecc71", "T3b": "#1abc9c", "T4": "#3498db", "T5": "#9b59b6",
        "T6": "#95a5a6", "T7": "#8e44ad", "T8": "#c0392b",
    }

    def fmt_ma(v):
        return '-' if v is None else v

    # ---- State distribution bar chart data ----
    state_keys = sorted(dist, key=lambda x: (int(x[1]) if x[1][:1].isdigit() else 9, x))
    dist_labels = json.dumps(state_keys, ensure_ascii=False)
    dist_values = json.dumps([dist[k] for k in state_keys], ensure_ascii=False)
    dist_colors = json.dumps([state_colors.get(k[:2], "#7f8c8d") for k in state_keys], ensure_ascii=False)

    def build_table(lst, group=None):
        rows = []
        for i, r in enumerate(lst[:25]):
            b = r.get("lowdip_breakdown", {})
            is_t3b = r.get("group") == "T3b" or group == "T3b"
            score = r.get("lowdip_score", 0)
            score_cls = "pos" if score >= 65 else ("warn" if score >= 50 else "muted")
            wk_cls = "pos" if b.get("wk_dir") == "up" else ("warn" if b.get("wk_dir") == "flat" else "neg")
            # 动量(低吸) / 距MA20乖离(T3b 建仓): 红追高绿回踩(A股)
            if is_t3b:
                dev20 = b.get("dev20", 0)
                heat = 'pos' if dev20 > 8 else ('neg' if dev20 < 3 else 'warn')
                mom_cell = f'<td class="{heat}">MA20 {dev20:+.1f}%</td>'
                pen = [p for p in (b.get("penalty") or [])]
                pen_tag = '<span class="muted">' + '; '.join(pen) + '</span>' if pen else '<span class="muted">-</span>'
                rr_n = b.get("rr_net")
                rr_cls = "pos" if rr_n is not None and rr_n >= 1.5 else ("neg" if rr_n is not None else "muted")
                rr_tag = f'{rr_n:.2f}' if rr_n is not None else '-'
                if b.get("rr_veto"):
                    rr_tag += ' <span class="score-badge neg">⚑否决</span>'
                chk = (f'<td>{pen_tag}</td>'
                       f'<td class="{rr_cls}">{rr_tag}</td>'
                       f'<td class="low">{b.get("planned_entry", "-")}</td>'
                       f'<td class="neg">{b.get("first_observation", "-")}</td>'
                       f'<td class="muted">-</td>')
            else:
                mom = b.get("mom", 0)
                mom_cell = f'<td class="{"pos" if mom > 0 else "neg"}">{mom:+.2f}</td>'
                pc = r.get("program_check") or {}
                verdict = pc.get("verdict", "-")
                if verdict == "PASS":
                    vtag = '<span class="score-badge pos">✅ 可试仓</span>'
                elif verdict == "FAIL":
                    vtag = '<span class="score-badge muted">⛔ FAIL</span>'
                else:
                    vtag = '<span class="muted">-</span>'
                lv = pc.get("level") or {}
                rr = pc.get("rr_net")
                rr_html = (f'<span class="{"pos" if (rr or 0) >= 1.2 else "neg"}">{rr}</span>'
                           if rr is not None else '<span class="muted">-</span>')
                chk = f'<td>{vtag}</td><td>{rr_html}</td>' \
                      f'<td class="low">{lv.get("planned_entry", "-")}</td>' \
                      f'<td class="neg">{lv.get("structural_invalidation", "-")}</td>' \
                      f'<td>{lv.get("first_observation", "-")}</td>'
            rows.append(f"""
        <tr>
          <td><b>{i+1}</b></td>
          <td><b>{r['name']}</b><br><span class="muted">{r['code']}</span></td>
          <td><span class="score-badge {score_cls}">{score}</span></td>
          <td class="low">{b.get('pos250', '-')}%</td>
          <td class="{'pos' if b.get('hl_pct', 0) > 0 else 'neg'}">{b.get('hl_pct', 0):+}%</td>
          <td class="{wk_cls}">{b.get('wk_dir', '-')} ({b.get('wk_slope', 0):+.1f}%)</td>
          <td class="{'neg' if (b.get('ma60_slope_pct') or 0) < 0 else 'pos'}">{fmt_ma(b.get('ma60_slope_pct'))}%</td>
          {mom_cell}
          {chk}
        </tr>""")
        return "".join(rows)

    # ---- Sparkline charts: one grid per group (T3a/T2/T3b) ----
    def _charts(group_list):
        blocks = []
        for r in group_list[:9]:
            recs = sorted(klines.get(r["code"], []), key=lambda x: x["date"])[-120:]
            closes = [round(float(x["last"]), 2) for x in recs]
            dates = [x["date"][:10] for x in recs]
            b = r.get("lowdip_breakdown", {})
            blocks.append({
                "name": r["name"], "code": r["code"], "score": r.get("lowdip_score", 0),
                "group": r.get("group", "-"), "closes": closes, "dates": dates,
                "pos250": b.get("pos250"), "hl": b.get("hl_pct"), "wk": b.get("wk_dir"),
            })
        return json.dumps(blocks, ensure_ascii=False)

    chart_t3a = _charts(t3a_list)
    chart_t2 = _charts(t2_list)
    chart_t3b = _charts(t3b_list)

    # ---- Detail cards: per-group top N (确保 T3b 也出现) ----
    detail_cards = []
    combined = t3a_list[:12] + t2_list[:5] + t3b_list[:15]
    for i, r in enumerate(combined):
        trend = r["trend_state"]
        state_reasons = "".join(f"<li>{x}</li>" for x in trend.get("reasons", []))
        ld_reasons = "".join(f"<li>{x}</li>" for x in r.get("lowdip_reasons", []))
        b = r.get("lowdip_breakdown", {})
        score = r.get("lowdip_score", 0)
        border = "#27ae60" if score >= 65 else ("#f39c12" if score >= 50 else "#95a5a6")
        group_label = {"T3a": "T3a 低吸", "T2": "T2 低吸", "T3b": "T3b 建仓"}.get(r.get("group"), "低吸")
        score_label = "建仓分数" if r.get("group") == "T3b" else "低吸分数"
        b_mom_html = ""
        if r.get("group") == "T3b":
            dev20 = b.get("dev20", 0); dev60 = b.get("dev60", 0)
            b_mom_html = f'<div class="metric"><span class="ml">距MA20乖离</span><span class="mv {"pos" if dev20>8 else ("neg" if dev20<3 else "warn")}">{dev20:+.1f}%</span></div>' \
                         f'<div class="metric"><span class="ml">距MA60乖离</span><span class="mv {"pos" if dev60>15 else ("neg" if dev60<3 else "warn")}">{dev60:+.1f}%</span></div>' \
                         f'<div class="metric"><span class="ml">RR_net</span><span class="mv {"pos" if (b.get("rr_net") or 0) >= 1.5 else "neg"}">{b.get("rr_net", "-")}{" ⚑否决" if b.get("rr_veto") else ""}</span></div>'
        else:
            b_mom_html = f'<div class="metric"><span class="ml">动量 斜率×R²</span><span class="mv {"pos" if (b.get("mom") or 0) > 0 else "neg"}">{b.get("mom", 0):+.2f}</span></div>' \
                         f'<div class="metric"><span class="ml">近20日动量</span><span class="mv {"neg" if (b.get("t20") or 0) < 0 else "pos"}">{b.get("t20", 0):+.1f}%</span></div>'
        detail_cards.append(f"""
        <div class="detail-card" style="border-left-color:{border}">
          <div class="detail-head">
            <span class="rank" style="background:{border}">#{i+1}</span>
            <h3>{r['name']}</h3>
            <span class="muted">{r['code']}</span>
            <span class="tag">{group_label}</span>
            <span class="score-badge">{"/".join(score_label.split("分数"))} {score}/100</span>
          </div>
          <div class="detail-grid">
            <div class="metric"><span class="ml">当前价格</span><span class="mv">{r['current']}</span></div>
            <div class="metric"><span class="ml">250日区间位</span><span class="mv low">{b.get('pos250', '-')}%</span></div>
            <div class="metric"><span class="ml">250日回撤</span><span class="mv neg">{r['drawdown_250d']}%</span></div>
            <div class="metric"><span class="ml">低点抬高</span><span class="mv {'pos' if b.get('hl_pct', 0) > 0 else 'neg'}">{b.get('hl_pct', 0):+}%</span></div>
            {b_mom_html}
            <div class="metric"><span class="ml">周线方向</span><span class="mv">{b.get('wk_dir', '-')}</span></div>
            <div class="metric"><span class="ml">MA60斜率</span><span class="mv {'neg' if (b.get('ma60_slope_pct') or 0) < 0 else 'pos'}">{fmt_ma(b.get('ma60_slope_pct'))}%</span></div>
            <div class="metric"><span class="ml">距MA60</span><span class="mv">{fmt_ma(r['ma'].get('price_vs_ma60_pct'))}%</span></div>
            <div class="metric"><span class="ml">周量比</span><span class="mv">{b.get('vol_ratio', '-')}</span></div>
            <div class="metric"><span class="ml">ATR比(20/60)</span><span class="mv">{b.get('atr_ratio', '-')}</span></div>
            <div class="metric"><span class="ml">均线排列</span><span class="mv muted">{r['ma']['alignment']}</span></div>
          </div>
          <div class="reasons"><b>状态机判定依据 ({group_label}):</b><ul>{state_reasons}</ul></div>
          <div class="reasons" style="margin-top:8px"><b>{score_label}分项:</b><ul>{ld_reasons}</ul></div>
        </div>""")

    dist_t1 = dist.get("T1", 0)
    dist_t3b = sum(v for k, v in dist.items() if k == "T3(T3b)")
    dist_t4 = dist.get("T4", 0)
    other = total - t3a_count - t2_count - t3b_count - dist_t1 - dist.get("T0", 0) - dist_t4

    # 四道程序校验汇总 (来自 analyze 阶段)
    chk = out.get("program_check_summary") or {}
    chk_pass = chk.get("pass", 0)
    chk_fail = chk.get("fail", 0)
    chk_fail_gates = chk.get("fail_gates") or {}
    fail_gate_html = "".join(
        f'<span class="fail-gate">{k} ×{v}</span>' for k, v in chk_fail_gates.items())

    # 详细卡片里附加四道程序校验明细
    def validation_html(pc):
        if not pc:
            return '<div class="reasons"><b>程序校验:</b> 无（非 T2/T3a 候选）</div>'
        vtag = '<span class="score-badge pos">✅ 可小额试仓</span>' if pc.get("verdict") == "PASS" \
            else '<span class="score-badge muted">⛔ 被拦截</span>'
        lv = pc.get("level") or {}
        lv_h = (f'结构支撑 <b>{lv.get("structure_support", "-")}</b> · ATR20 <b>{lv.get("atr20", "-")}</b> · '
                f'结构失效位 <b class="neg">{lv.get("structural_invalidation", "-")}</b> · '
                f'灾难保护位 <b class="neg">{lv.get("disaster_level", "-")}</b>')
        o = pc.get("order") or {}
        ord_h = ("建议小额 <b class=\"pos\">{0} 份 / ¥{1}</b>（目标仓 {2}%）".format(
                    o.get("shares") if o.get("shares") is not None else "-",
                    o.get("amount") if o.get("amount") is not None else "-",
                    o.get("pct_of_target") if o.get("pct_of_target") is not None else "-")
                 if o and o.get("shares") else
                 "⛔ 无可下单手数（条件不满足或金额不足）")
        vs = pc.get("validations") or {}
        vrows = []
        order_map = [("action_legal", "动作合法性"), ("risk_reward", "风险收益"),
                     ("sizing", "仓位数量"), ("cost", "交易成本")]
        for key, label in order_map:
            val = vs.get(key) or {}
            ok = val.get("pass")
            mark = "✅" if ok else "❌"
            detl = val.get("reason") or val.get("rejected") or val.get("reasons")
            if isinstance(detl, list):
                detl = "；".join(str(x) for x in detl)
            rr = val.get("rr")
            rr_s = f"（RR {rr}）" if rr is not None and key == "risk_reward" else ""
            vrows.append(f'<li>{mark} <b>{label}</b>{rr_s}'
                         f'{(" — " + str(detl)) if detl else ""}</li>')
        return f"""
        <div class="reasons" style="margin-top:8px">
          <b>四道程序校验 ({vtag}):</b> <div class="lvline">{lv_h}</div>
          <div class="ordline">{ord_h}</div>
          <ul>{''.join(vrows)}</ul>
        </div>"""

    # 重写 detail_cards，在低吸分项后追加程序校验明细
    for card_idx, r in enumerate(combined):
        pc = r.get("program_check")
        if pc:
            close_idx = detail_cards[card_idx].rfind("</div>")
            detail_cards[card_idx] = (detail_cards[card_idx][:close_idx]
                                      + validation_html(pc) + "</div>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股ETF 低吸机会(T2+T3a)扫描报告 · {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:#f5f6fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#7a1f1f 0%,#a93226 50%,#c0392b 100%); color:#fff; padding:36px 30px; border-radius:12px; margin-bottom:24px; box-shadow:0 4px 20px rgba(0,0,0,0.15); }}
.header h1 {{ font-size:26px; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.85; font-size:14px; }}
.header .meta {{ margin-top:14px; display:flex; gap:24px; font-size:13px; opacity:0.75; flex-wrap:wrap; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(6,1fr); gap:14px; margin-bottom:28px; }}
.summary-card {{ background:#fff; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.summary-card .number {{ font-size:30px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#7f8c8d; margin-top:4px; }}
.chk-cards {{ grid-template-columns:repeat(2,1fr); margin-bottom:12px; }}
.c-green .number {{ color:#27ae60; }} .c-orange .number {{ color:#e67e22; }} .c-red .number {{ color:#e74c3c; }}
.c-blue .number {{ color:#2980b9; }} .c-gray .number {{ color:#7f8c8d; }} .c-teal .number {{ color:#1abc9c; }}
.section-title {{ font-size:19px; font-weight:600; margin:28px 0 14px; padding-bottom:10px; border-bottom:2px solid #ecf0f1; display:flex; align-items:center; gap:8px; }}
.section-title .count {{ font-size:13px; color:#7f8c8d; font-weight:400; }}
.table-wrapper {{ background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 2px 10px rgba(0,0,0,0.06); margin-bottom:28px; overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#f8f9fa; padding:11px 9px; text-align:left; font-weight:600; color:#5a6473; white-space:nowrap; border-bottom:2px solid #e8eaed; }}
td {{ padding:10px 9px; border-bottom:1px solid #f0f2f5; white-space:nowrap; }}
tr:hover td {{ background:#fafbfc; }}
.muted {{ color:#95a5a6; font-size:12px; }}
.pos {{ color:#e74c3c; font-weight:600; }}
.neg {{ color:#16a085; font-weight:600; }}
.low {{ color:#e67e22; font-weight:600; }}
.warn {{ color:#e67e22; font-weight:600; }}
.tag {{ padding:2px 8px; border-radius:10px; background:#fdeaea; color:#c0392b; font-size:12px; font-weight:600; }}
.score-badge {{ padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
.score-badge.pos {{ background:#e8f8f0; color:#27ae60; }}
.score-badge.warn {{ background:#fef5e7; color:#e67e22; }}
.score-badge.muted {{ background:#f0f2f5; color:#7f8c8d; }}
.dist-chart-box {{ height:280px; background:#fff; border-radius:10px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.06); margin-bottom:28px; }}
.charts-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:18px; margin-bottom:28px; }}
.chart-card {{ background:#fff; border-radius:10px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.chart-card h4 {{ font-size:15px; margin-bottom:4px; display:flex; align-items:center; gap:8px; }}
.chart-card .sub {{ font-size:12px; color:#7f8c8d; margin-bottom:10px; }}
.chart-box {{ height:150px; position:relative; }}
.detail-card {{ background:#fff; border-radius:10px; padding:20px; margin-bottom:18px; box-shadow:0 2px 10px rgba(0,0,0,0.06); border-left:4px solid #27ae60; }}
.detail-head {{ display:flex; align-items:center; gap:12px; margin-bottom:14px; flex-wrap:wrap; }}
.detail-head .rank {{ color:#fff; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; }}
.detail-head h3 {{ font-size:18px; }}
.detail-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px; }}
.metric {{ background:#f8f9fa; padding:9px 12px; border-radius:6px; }}
.metric .ml {{ font-size:12px; color:#7f8c8d; display:block; }}
.metric .mv {{ font-size:15px; font-weight:600; }}
.reasons {{ background:#f8f9fa; padding:12px 16px; border-radius:6px; }}
.reasons ul {{ list-style:none; margin-top:6px; }}
.reasons li {{ padding:2px 0; font-size:13px; }}
.lvline {{ margin-top:4px; font-size:12.5px; }}
.ordline {{ margin-top:4px; font-size:12.5px; }}
.fail-gate {{ display:inline-block; margin:2px 6px 2px 0; padding:2px 10px; border-radius:10px; background:#fdecea; color:#c0392b; font-size:12px; }}
.note {{ background:#fdecea; border-left:4px solid #c0392b; padding:14px 18px; border-radius:6px; margin:20px 0; font-size:13px; }}
.note.green {{ background:#eaf7ef; border-left-color:#27ae60; }}
.disclaimer {{ background:#eee; border-radius:8px; padding:16px 20px; margin-top:28px; font-size:12px; color:#7f8c8d; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>🪝 A股ETF 低吸机会扫描报告</h1>
  <div class="subtitle">T0-T8趋势状态机 · 低吸候选 = T2(底部构建) + T3a(反转初步确认, MA60仍下行)</div>
  <div class="meta">
    <span>📅 数据日期: {today}</span>
    <span>📊 样本: {total} 只ETF</span>
    <span>📈 K线周期: 日线 250 天</span>
    <span>🔍 算法: T0-T8状态机 + 6维低吸置信度</span>
  </div>
</div>

<div class="summary-cards">
  <div class="summary-card c-green"><div class="number">{t3a_count}</div><div class="label">🔶 T3a 低吸候选</div></div>
  <div class="summary-card c-green"><div class="number">{avg_t3a if avg_t3a is not None else '-'}</div><div class="label">T3a平均低吸分</div></div>
  <div class="summary-card c-teal"><div class="number">{t2_count}</div><div class="label">🏗️ T2 低吸候选</div></div>
  <div class="summary-card c-teal"><div class="number">{avg_t2 if avg_t2 is not None else '-'}</div><div class="label">T2平均低吸分</div></div>
  <div class="summary-card c-blue"><div class="number">{t3b_count}</div><div class="label">🔷 T3b 建仓白名单</div></div>
  <div class="summary-card c-green"><div class="number">{dist_t4}</div><div class="label">T4 强势持有</div></div>
</div>

<div class="summary-cards chk-cards">
  <div class="summary-card c-green"><div class="number">{chk_pass}</div><div class="label">✅ 可通过校验 · 可小额试仓</div></div>
  <div class="summary-card c-red"><div class="number">{chk_fail}</div><div class="label">⛔ 被程序校验拦截</div></div>
</div>

<div class="note">
  <b>📌 四道程序校验 (SOP §七) 结果:</b> {fail_gate_html or '<span class="muted">无候选</span>'}
  每个 T2/T3a 候选都跑操作引擎 <b>decide(trial=True)</b> 的四个校验 — 动作合法性 / 成本调整后 RR / 仓位数量 / 交易成本。
  小额试仓(T2/T3a, ≤25%目标仓, 默认注入 25% 目标仓)用<b>更低 RR 下限(≥1.2)</b>，用极小仓位换更宽 RR；完整建仓仍须 RR≥2。
  任一失败自动降级 HOLD。所有金额/权重/成本参数来自 <b>records/portfolio_config.json</b>（不硬编码）。
</div>

<div class="note">
  <b>📌 低吸 vs 建仓边界 (SOP 硬约束):</b> 本报告只列 <b>T2</b>(底部构建) 与 <b>T3a</b>(反转初步确认, MA60仍下行) 的<b>小额低吸试仓</b>候选。
  完整建仓（分批增加核心仓）仅限 <b>T3b/T4</b> 白名单；<b>禁止在 T0/T1 抄底</b>。
  T2 = 小额试仓；T3a = 小额、等待回踩（MA60 未走平前不加码）。
  具体下单仍须通过操作计划的四道程序校验（趋势-动作硬约束 / RR / 仓位 / 交易成本；小额试仓 RR≥1.2，完整建仓 RR≥2）。
</div>

<div class="section-title">📊 趋势状态分布 <span class="count">(全部ETF, 判断大盘筑底广度)</span></div>
<div class="dist-chart-box"><canvas id="distChart"></canvas></div>

<div class="section-title">🔶 T3a 低吸榜单 (TOP 25) <span class="count">颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>低吸分</th><th>250日位</th><th>抬底%</th><th>周线方向</th><th>MA60斜率</th><th>动量×R²</th>
<th>程序校验</th><th>RR</th><th>计划买入</th><th>结构失效位</th><th>第一观察区</th>
</tr></thead>
<tbody>
{build_table(t3a_list, group="T3a")}
</tbody></table>
</div>

<div class="section-title">🏗️ T2 低吸榜单 (TOP 25) <span class="count">颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>低吸分</th><th>250日位</th><th>抬底%</th><th>周线方向</th><th>MA60斜率</th><th>动量×R²</th>
<th>程序校验</th><th>RR</th><th>计划买入</th><th>结构失效位</th><th>第一观察区</th>
</tr></thead>
<tbody>
{build_table(t2_list, group="T2")}
</tbody></table>
</div>

<div class="section-title">🔷 T3b 建仓白名单榜单 (TOP 25) <span class="count">建仓分=「趋势已确认 + 不在高位过热处追」· 颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>建仓分</th><th>250日位</th><th>抬底%</th><th>周线方向</th><th>MA60斜率</th><th>距MA20乖离</th>
<th>高位/过热预警</th><th>RR_net</th><th>计划买入</th><th>第一观察区</th><th>结构失效位</th>
</tr></thead>
<tbody>
{build_table(t3b_list, group="T3b")}
</tbody></table>
</div>

<div class="note green">
  <b>💡 高分说明:</b> 低吸分语义 = 「左侧低吸性价比 + 接近T3b升级概率」。
  6维: 250日区间位置(25, 越低估越高) + 低点抬高(20) + 动量斜率×R²(20) + 周线方向(15) + MA60斜率修复(10, T3a→T3b关键) + 量能波幅(10)。
  高分(≥65) = 估值低 + 结构转强 + 动量转正，最接近 T3b 升级；但仍属<b>小额低吸</b>，非建仓信号。
</div>

<div class="section-title">📈 T3a 高分ETF — K线缩略图 <span class="count">(前9名 120日走势)</span></div>
<div class="charts-grid" id="chartsGridT3a"></div>

<div class="section-title">📈 T2 高分ETF — K线缩略图 <span class="count">(前9名 120日走势)</span></div>
<div class="charts-grid" id="chartsGridT2"></div>

<div class="section-title">📈 T3b 高分ETF — K线缩略图 <span class="count">(前9名 120日走势)</span></div>
<div class="charts-grid" id="chartsGridT3b"></div>

<div class="section-title">📝 低吸候选详细分析</div>
{''.join(detail_cards)}

<div class="disclaimer">
  ⚠️ <b>风险提示:</b> 本报告仅基于历史价格形态的客观量化分析，不构成任何投资建议。
  T2/T3a 为<b>底部/反转早期状态，仍存在回落可能（T2→T1/T0、T3a 假突破）</b>；完整建仓仅限 T3b/T4，且须通过操作计划四道程序校验（本报告仅提示小额低吸候选）。
  MA60 未走平/转上前，T3a 不加码。数据来源: 腾讯自选股行情接口，可能存在延迟，以交易所官方数据为准。
</div>

</div>

<script>
const distLabels = {dist_labels};
const distValues = {dist_values};
const distColors = {dist_colors};
new Chart(document.getElementById('distChart'), {{
  type: 'bar',
  data: {{
    labels: distLabels,
    datasets: [{{ data: distValues, backgroundColor: distColors, borderRadius: 4, barPercentage: 0.7 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: (i) => i.parsed.y + ' 只' }} }}
    }},
    scales: {{
      x: {{ ticks: {{ font: {{ size: 12 }}, color: '#5a6473' }}, grid: {{ display: false }} }},
      y: {{ ticks: {{ precision: 0, color: '#95a5a6' }}, grid: {{ color: '#f0f2f5' }} }}
    }}
  }}
}});

const chartDataT3a = {chart_t3a};
const chartDataT2 = {chart_t2};
const chartDataT3b = {chart_t3b};
const colors = ['#e74c3c','#2980b9','#9b59b6','#16a085','#e67e22','#34495e','#1abc9c','#d35400','#8e44ad'];
function renderGrid(gridId, rows) {{
  const grid = document.getElementById(gridId);
  rows.forEach((c, idx) => {{
    const card = document.createElement('div');
    card.className = 'chart-card';
    card.innerHTML = `
      <h4><span style="color:${{colors[idx%colors.length]}}">●</span> ${{c.name}}</h4>
      <div class="sub">[${{c.group}}] 低吸${{c.score}} · 250日位${{c.pos250}}% · 抬底${{c.hl}}% · 周线${{c.wk}}</div>
      <div class="chart-box"><canvas></canvas></div>
    `;
    grid.appendChild(card);
    const ctx = card.querySelector('canvas');
    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: c.dates,
        datasets: [{{ data: c.closes, borderColor: colors[idx%colors.length], backgroundColor: colors[idx%colors.length]+'15', borderWidth: 1.8, pointRadius:0, fill:true, tension:0.35 }}]
      }},
      options: {{
        responsive:true, maintainAspectRatio:false,
        plugins: {{ legend:{{display:false}}, tooltip:{{ callbacks:{{ title:(i)=>c.dates[i[0].dataIndex], label:(i)=>'价格 '+i.parsed.y }}}}}},
        scales: {{ x: {{ display:false }}, y: {{ display:true, position:'right', ticks:{{ font:{{size:9}}, color:'#95a5a6' }}, grid:{{ color:'#f0f2f5' }} }} }}
      }}
    }});
  }});
}}
renderGrid('chartsGridT3a', chartDataT3a);
renderGrid('chartsGridT2', chartDataT2);
renderGrid('chartsGridT3b', chartDataT3b);
</script>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"Report saved to {output_path}")


def main():
    cwd = os.getcwd()
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results_file = os.path.join(skill_dir, "etf_lowdip_results.json")
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    outdir = os.path.join(cwd, "reports", "etf")
    os.makedirs(outdir, exist_ok=True)
    output = os.path.join(outdir, "etf_lowdip_report.html")

    with open(results_file) as f:
        out = json.load(f)
    with open(kline_file) as f:
        klines = json.load(f)
    build_report(out, klines, output)


if __name__ == "__main__":
    main()