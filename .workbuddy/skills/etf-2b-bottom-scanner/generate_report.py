#!/usr/bin/env python3
"""
生成 A股ETF 2B底部形态分析 HTML 报告 (v2)
- 摘要卡片 (已确认/待确认/观察)
- 2B信号ETF 60日 K线缩略图 (Chart.js, 标注前低参考线)
- TOP25 综合得分排名表
- 已确认 ETF 详细分析卡片
"""

import json
import os
from datetime import datetime


def build_report(results, klines, output_path):
    today = datetime.now().strftime("%Y-%m-%d")

    # Filter out v3 quality-filtered results (score=0, missing scoring details)
    results = [r for r in results if r.get("score", 0) > 0]

    # v2: group by confirmed status
    confirmed_all = [r for r in results if r.get("confirmed")]
    unconfirmed_all = [r for r in results if not r.get("confirmed")]
    confirmed_high = [r for r in confirmed_all if r["score"] >= 80]
    unconf_high = [r for r in unconfirmed_all if r["score"] >= 80]
    total = len(results)

    # Display signals: confirmed first by score, then unconfirmed high-score
    display_signals = confirmed_all + unconf_high

    # Build chart datasets for top 9 confirmed signals
    chart_blocks = []
    for r in confirmed_all[:9]:
        recs = sorted(klines.get(r["code"], []), key=lambda x: x["date"])[-60:]
        closes = [round(float(x.get("last", x.get("close", 0))), 2) for x in recs]
        dates = [x["date"][:10] for x in recs]
        ref_line = [r["prior_low_price"]] * len(closes)
        chart_blocks.append({
            "name": r["name"], "type": r["type"], "score": r["score"],
            "label": r["label"], "closes": closes, "dates": dates,
            "refLine": ref_line,
            "priorLow": r["prior_low_price"],
            "breakPct": r["break_pct"],
            "recoveryPct": r["recovery_pct"],
            "volRatio": r["vol_ratio"],
        })

    # Build full ranking table rows (top 25)
    table_rows = []
    for i, r in enumerate(results[:25]):
        # v2: color by confirmed status + score tier
        if r.get("confirmed"):
            if r["score"] >= 80:
                lc = "#27ae60"
            elif r["score"] >= 65:
                lc = "#2980b9"
            else:
                lc = "#e67e22"
        else:
            if r["score"] >= 80:
                lc = "#f39c12"
            else:
                lc = "#95a5a6"
        lag_text = f"{r['lag_bars']}天" if r["lag_bars"] > 0 else "同日"
        entry_d = r.get("entry_date") or "-"
        table_rows.append(f"""
        <tr>
          <td><b>{i+1}</b></td>
          <td><b>{r['name']}</b><br><span class="muted">{r['type']}</span></td>
          <td><span style="color:{lc};font-weight:600">{r['label']}</span></td>
          <td><b>{r['score']}</b></td>
          <td class="neg">{r['break_pct']}%</td>
          <td class="pos">{r['recovery_pct']:+.1f}%</td>
          <td>{r['vol_ratio']:.0%}</td>
          <td>{lag_text}</td>
          <td class="neg">{r['prior_decline']}%</td>
          <td class="{'pos' if r['d_ma60']>0 else 'neg'}">{r['d_ma60']:+.1f}%</td>
          <td>{entry_d}</td>
        </tr>""")

    # Detail cards for confirmed signals (up to 9)
    detail_cards = []
    for i, r in enumerate(confirmed_all[:9]):
        if r["score"] >= 80:
            border_color = "#27ae60"
        elif r["score"] >= 65:
            border_color = "#2980b9"
        else:
            border_color = "#e67e22"
        reasons_html = "".join(f"<li>{x}</li>" for x in r["reasons"])
        entry_d = r.get("entry_date") or "-"
        detail_cards.append(f"""
        <div class="detail-card" style="border-left-color:{border_color}">
          <div class="detail-head">
            <span class="rank" style="background:{border_color}">#{i+1}</span>
            <h3>{r['name']}</h3>
            <span class="badge" style="background:{border_color}">{r['label']}</span>
            <span class="score-badge">得分 {r['score']}/100</span>
          </div>
          <div class="detail-grid">
            <div class="metric"><span class="ml">入场价格</span><span class="mv">{r['current']}</span></div>
            <div class="metric"><span class="ml">前低价格</span><span class="mv">{r['prior_low_price']}</span></div>
            <div class="metric"><span class="ml">跌破幅度</span><span class="mv neg">{r['break_pct']}%</span></div>
            <div class="metric"><span class="ml">回升幅度</span><span class="mv pos">{r['recovery_pct']:+.1f}%</span></div>
            <div class="metric"><span class="ml">放量比</span><span class="mv">{r['vol_ratio']:.0%}</span></div>
            <div class="metric"><span class="ml">回升时间</span><span class="mv">{r['lag_bars']}天</span></div>
            <div class="metric"><span class="ml">前期跌幅</span><span class="mv neg">{r['prior_decline']}%</span></div>
            <div class="metric"><span class="ml">距60MA</span><span class="mv {'pos' if r['d_ma60']>0 else 'neg'}">{r['d_ma60']:+.1f}%</span></div>
            <div class="metric"><span class="ml">破位日期</span><span class="mv">{r['breakdown_date']}</span></div>
            <div class="metric"><span class="ml">回升日期</span><span class="mv">{r['recovery_date']}</span></div>
            <div class="metric"><span class="ml">入场日期</span><span class="mv">{entry_d}</span></div>
          </div>
          <div class="reasons"><b>判定依据:</b><ul>{reasons_html}</ul></div>
        </div>""")

    chart_json = json.dumps(chart_blocks, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股ETF 2B底部形态分析报告 · {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:#f5f6fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#0d3b0d 0%,#1a5c1a 50%,#2d8a2d 100%); color:#fff; padding:36px 30px; border-radius:12px; margin-bottom:24px; box-shadow:0 4px 20px rgba(0,0,0,0.15); }}
.header h1 {{ font-size:26px; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.85; font-size:14px; }}
.header .meta {{ margin-top:14px; display:flex; gap:24px; font-size:13px; opacity:0.75; flex-wrap:wrap; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-bottom:28px; }}
.summary-card {{ background:#fff; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.summary-card .number {{ font-size:30px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#7f8c8d; margin-top:4px; }}
.c-blue .number {{ color:#2980b9; }}
.c-green .number {{ color:#27ae60; }}
.c-blue2 .number {{ color:#2e86c1; }}
.c-orange .number {{ color:#f39c12; }}
.c-gray .number {{ color:#7f8c8d; }}
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
.charts-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:18px; margin-bottom:28px; }}
.chart-card {{ background:#fff; border-radius:10px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.chart-card h4 {{ font-size:15px; margin-bottom:4px; display:flex; align-items:center; gap:8px; }}
.chart-card .sub {{ font-size:12px; color:#7f8c8d; margin-bottom:10px; }}
.chart-box {{ height:150px; position:relative; }}
.detail-card {{ background:#fff; border-radius:10px; padding:20px; margin-bottom:18px; box-shadow:0 2px 10px rgba(0,0,0,0.06); border-left:4px solid #27ae60; }}
.detail-head {{ display:flex; align-items:center; gap:12px; margin-bottom:14px; flex-wrap:wrap; }}
.detail-head .rank {{ background:#27ae60; color:#fff; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; }}
.detail-head h3 {{ font-size:18px; }}
.badge {{ color:#fff; padding:3px 10px; border-radius:12px; font-size:12px; }}
.score-badge {{ background:#34495e; color:#fff; padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
.detail-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:14px; }}
.metric {{ background:#f8f9fa; padding:9px 12px; border-radius:6px; }}
.metric .ml {{ font-size:12px; color:#7f8c8d; display:block; }}
.metric .mv {{ font-size:15px; font-weight:600; }}
.reasons {{ background:#f8f9fa; padding:12px 16px; border-radius:6px; }}
.reasons ul {{ list-style:none; margin-top:6px; }}
.reasons li {{ padding:2px 0; font-size:13px; }}
.note {{ background:#e8f5e9; border-left:4px solid #27ae60; padding:14px 18px; border-radius:6px; margin:20px 0; font-size:13px; }}
.disclaimer {{ background:#fdecea; border-radius:8px; padding:16px 20px; margin-top:28px; font-size:12px; color:#c0392b; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>📉 A股ETF 2B底部形态分析报告 v2</h1>
  <div class="subtitle">全市场352只规模最大ETF的2B底部假突破检测 · 含2阳确认机制 · 来自 all_etfs_larggest.json</div>
  <div class="meta">
    <span>📅 数据日期: {today}</span>
    <span>📊 样本: 352 只ETF</span>
    <span>📈 K线周期: 日线 250 天</span>
    <span>🔍 算法: 2B规则 (Victor Sperandeo) · 7维度评分引擎 v2</span>
  </div>
</div>

<div class="summary-cards">
  <div class="summary-card c-gray"><div class="number">{total}</div><div class="label">检测到2B信号</div></div>
  <div class="summary-card c-green"><div class="number">{len(confirmed_all)}</div><div class="label">✅ 已确认 (2阳通过)</div></div>
  <div class="summary-card c-green"><div class="number">{len(confirmed_high)}</div><div class="label">🟢 可买入 (≥80+确认)</div></div>
  <div class="summary-card c-orange"><div class="number">{len(unconfirmed_all)}</div><div class="label">⏳ 待确认 (缺2阳)</div></div>
  <div class="summary-card c-orange"><div class="number">{len(unconf_high)}</div><div class="label">🔍 高评分待确认 (≥80)</div></div>
</div>

<div class="note">
  <b>📌 2B底部规则 v2 (Victor Sperandeo + 2阳确认):</b><br>
  1. 价格跌破前60日低点，在2个交易日内快速回升至该低点之上 = 假突破信号<br>
  2. <b>【v2新增】回升后需出现2根阳线 (close &gt; open) 才确认进场</b> — 回测显示此机制将20日胜率从49%提升至52%，均收益从+1.7%提升至+2.4%<br>
  <b>评分维度:</b> 7维度 (max 100) = 跌破深度20 + 回升力度20 + 放量收缩15 + 前低质量15 + 趋势深度15 + 回升速度10 + 距60MA 5 − 惩罚项。
</div>

<div class="section-title">🏆 已确认2B信号 — K线缩略图 <span class="count">(展示前{min(len(confirmed_all), 9)}名 · 60日走势 · 红色虚线 = 前低参考价)</span></div>
{"<div class='charts-grid' id='chartsGrid'></div>" if chart_blocks else "<p style='color:#95a5a6;font-size:13px;'>暂无已确认信号，等待2阳确认中...</p>"}

<div class="section-title">📊 综合得分排名 (TOP 25) <span class="count">颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>形态判定</th><th>得分</th><th>跌破%</th><th>回升%</th><th>量比</th><th>回升时间</th><th>前跌%</th><th>距60MA</th><th>入场日</th>
</tr></thead>
<tbody>
{''.join(table_rows)}
</tbody></table>
</div>

<div class="section-title">📝 已确认信号 详细分析</div>
{''.join(detail_cards) if detail_cards else '<p style="color:#95a5a6;font-size:13px;">暂无已确认信号。</p>'}

<div class="disclaimer">
  ⚠️ <b>风险提示:</b> 本报告仅基于历史价格形态的客观量化分析，不构成任何投资建议。2B底部形态识别属于经典技术分析方法，但不代表形态一定能成功反转；
  假突破后仍可能继续下跌，或回升后再次破低。投资有风险，决策需谨慎。请结合基本面、资金面、宏观环境综合判断。
  数据来源: 腾讯自选股行情接口，可能存在延迟，以交易所官方数据为准。
</div>

</div>

<script>
const chartData = {chart_json};
const colors = ['#e74c3c','#2980b9','#9b59b6','#16a085','#e67e22','#34495e','#1abc9c','#d35400','#8e44ad'];
const grid = document.getElementById('chartsGrid');
if (grid) {{
  chartData.forEach((c, idx) => {{
    const card = document.createElement('div');
    card.className = 'chart-card';
    card.innerHTML = `
      <h4><span style="color:${{colors[idx%colors.length]}}">●</span> ${{c.name}}</h4>
      <div class="sub">得分${{c.score}} · ${{c.label}} · 破深${{c.breakPct}}% · 回升${{c.recoveryPct}}% · 量比${{(c.volRatio*100).toFixed(0)}}%</div>
      <div class="chart-box"><canvas></canvas></div>
    `;
    grid.appendChild(card);
    const ctx = card.querySelector('canvas');
    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: c.dates,
        datasets: [
          {{ data: c.closes, borderColor: colors[idx%colors.length], backgroundColor: colors[idx%colors.length]+'15', borderWidth: 1.8, pointRadius:0, fill:true, tension:0.35 }},
          {{ data: c.refLine, borderColor: '#e74c3c', borderWidth: 1.2, borderDash: [5,5], pointRadius:0, fill:false, tension:0 }}
        ]
      }},
      options: {{
        responsive:true, maintainAspectRatio:false,
        plugins: {{ legend:{{display:false}}, tooltip:{{ callbacks:{{ title:(i)=>c.dates[i[0].dataIndex], label:(i)=>i.datasetIndex===0?'价格 '+i.parsed.y:'前低 '+i.parsed.y }}}}}},
        scales: {{ x: {{ display:false }}, y: {{ display:true, position:'right', ticks:{{ font:{{size:9}}, color:'#95a5a6' }}, grid:{{ color:'#f0f2f5' }} }} }}
      }}
    }});
  }});
}}
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Report saved to {output_path}")


def main():
    cwd = os.getcwd()
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results_file = os.path.join(skill_dir, "etf_2b_bottom_results.json")
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    outdir = os.path.join(cwd, "reports", "etf")
    os.makedirs(outdir, exist_ok=True)
    output = os.path.join(outdir, "etf_2b_bottom_report.html")

    if not os.path.exists(results_file):
        print(f"ERROR: Results file not found: {results_file}")
        print("Run analyze.py first to generate results.")
        return
    if not os.path.exists(kline_file):
        print(f"ERROR: K-line data not found: {kline_file}")
        print("Run analyze.py first to fetch K-line data.")
        return

    with open(results_file, encoding="utf-8") as f:
        results = json.load(f)
    with open(kline_file, encoding="utf-8") as f:
        klines = json.load(f)
    build_report(results, klines, output)


if __name__ == "__main__":
    main()
