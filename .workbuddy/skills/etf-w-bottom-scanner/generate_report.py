#!/usr/bin/env python3
"""
生成 A股ETF W底形态分析 HTML 报告 (v1)
- 摘要卡片 (确认/形成中/候选)
- W底信号ETF 120日K线缩略图 (Chart.js, 标注左底+峰顶+右底+突破)
- TOP25 综合得分排名表
- W底信号ETF详细分析卡片
"""

import json
import os
from datetime import datetime


def build_report(results, klines, output_path):
    today = datetime.now().strftime("%Y-%m-%d")

    confirmed = [r for r in results if "确认" in r["label"]]
    forming = [r for r in results if "形成中" in r["label"]]
    candidate = [r for r in results if "候选" in r["label"]]

    # Build chart datasets for top signals
    chart_blocks = []
    for r in results[:9]:
        kdata = klines.get(r["code"], [])
        recs = sorted(kdata, key=lambda x: x["date"])[-120:]
        closes = [round(float(x["last"]), 2) for x in recs]
        dates = [x["date"][:10] for x in recs]
        chart_blocks.append({
            "name": r["name"], "type": r.get("type", "ETF"), "score": r["score"],
            "label": r["label"], "closes": closes, "dates": dates,
            "left_trough": r["left_trough"], "right_trough": r["right_trough"],
            "peak": r["peak"], "current": r["current"],
            "recovery": r["recovery_pct"], "diff": r["trough_diff_pct"],
            "vr": r["vol_ratio"], "status": r.get("status", ""),
        })

    # Build full ranking table rows (top 25)
    table_rows = []
    for i, r in enumerate(results[:25]):
        lc = {"W底确认": "#27ae60", "W底形成中": "#2980b9", "W底候选": "#f39c12", "非W底": "#95a5a6"}.get(r["label"], "#333")
        status_badge = "&#x2705;" if r.get("status") == "确认" else "&#x23F3;"
        table_rows.append(f"""
        <tr>
          <td><b>{i + 1}</b></td>
          <td><b>{r['name']}</b><br><span class="muted">{r.get('type', 'ETF')}</span></td>
          <td><span style="color:{lc};font-weight:600">{r['label']}</span></td>
          <td><b>{r['score']}</b></td>
          <td>{r.get('status', '')} {status_badge}</td>
          <td class="pos">{r['recovery_pct']}%</td>
          <td class="neg">{r['trough_diff_pct']}%</td>
          <td>{r['vol_ratio']}</td>
          <td class="pos">{r.get('rt_elevation_pct', 0):.1f}%</td>
          <td class="neg">{r['current']}</td>
        </tr>""")

    # Detail cards for all signals
    detail_cards = []
    for i, r in enumerate(results[:9]):
        reasons_html = "".join(f"<li>{x}</li>" for x in r.get("reasons", []))
        lc = {"W底确认": "#27ae60", "W底形成中": "#2980b9", "W底候选": "#f39c12"}.get(r["label"], "#27ae60")
        detail_cards.append(f"""
        <div class="detail-card" style="border-left-color:{lc}">
          <div class="detail-head">
            <span class="rank" style="background:{lc}">#{i + 1}</span>
            <h3>{r['name']}</h3>
            <span class="badge" style="background:{lc}">{r['label']}</span>
            <span class="score-badge">&#24471;&#20998; {r['score']}/100</span>
          </div>
          <div class="detail-grid">
            <div class="metric"><span class="ml">&#24403;&#21069;&#20215;&#26684;</span><span class="mv">{r['current']}</span></div>
            <div class="metric"><span class="ml">&#24038;&#24213;&#20215;&#26684;</span><span class="mv neg">{r['left_trough']}</span></div>
            <div class="metric"><span class="ml">&#23792;&#39030;&#20215;&#26684;</span><span class="mv pos">{r['peak']}</span></div>
            <div class="metric"><span class="ml">&#21491;&#24213;&#20215;&#26684;</span><span class="mv">{r['right_trough']}</span></div>
            <div class="metric"><span class="ml">&#21453;&#24377;&#24133;&#24230;</span><span class="mv pos">{r['recovery_pct']}%</span></div>
            <div class="metric"><span class="ml">&#21452;&#24213;&#20559;&#24046;</span><span class="mv">{r['trough_diff_pct']}%</span></div>
            <div class="metric"><span class="ml">&#21491;&#24213;&#25260;&#39640;</span><span class="mv pos">{r.get('rt_elevation_pct', 0):.1f}%</span></div>
            <div class="metric"><span class="ml">&#25104;&#20132;&#37327;&#27604;</span><span class="mv">{r['vol_ratio']}</span></div>
            <div class="metric"><span class="ml">&#21069;&#26399;&#36300;&#24133;</span><span class="mv neg">{r.get('prior_decline_pct', 0)}%</span></div>
            <div class="metric"><span class="ml">&#24038;&#24213;&#26085;&#26399;</span><span class="mv">{r.get('lt_date', '')[:10]}</span></div>
            <div class="metric"><span class="ml">&#23792;&#39030;&#26085;&#26399;</span><span class="mv">{r.get('pk_date', '')[:10]}</span></div>
            <div class="metric"><span class="ml">&#21491;&#24213;&#26085;&#26399;</span><span class="mv">{r.get('rt_date', '')[:10]}</span></div>
          </div>
          <div class="reasons"><b>&#35780;&#20998;&#20381;&#25454;:</b><ul>{reasons_html}</ul></div>
        </div>""")

    chart_json = json.dumps(chart_blocks, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A&#32929;ETF W&#24213;&#24418;&#24577;&#20998;&#26512;&#25253;&#21578; &#183; {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:#f5f6fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#1a3a5c 0%,#0d4d6e 50%,#0a2a44 100%); color:#fff; padding:36px 30px; border-radius:12px; margin-bottom:24px; box-shadow:0 4px 20px rgba(0,0,0,0.15); }}
.header h1 {{ font-size:26px; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.85; font-size:14px; }}
.header .meta {{ margin-top:14px; display:flex; gap:24px; font-size:13px; opacity:0.75; flex-wrap:wrap; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:28px; }}
.summary-card {{ background:#fff; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.summary-card .number {{ font-size:30px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#7f8c8d; margin-top:4px; }}
.c-green .number {{ color:#27ae60; }}
.c-blue .number {{ color:#2980b9; }}
.c-orange .number {{ color:#e67e22; }}
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
.detail-head .rank {{ color:#fff; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; }}
.detail-head h3 {{ font-size:18px; }}
.badge {{ color:#fff; padding:3px 10px; border-radius:12px; font-size:12px; }}
.score-badge {{ background:#34495e; color:#fff; padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
.detail-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px; }}
.metric {{ background:#f8f9fa; padding:9px 12px; border-radius:6px; }}
.metric .ml {{ font-size:12px; color:#7f8c8d; display:block; }}
.metric .mv {{ font-size:15px; font-weight:600; }}
.reasons {{ background:#f8f9fa; padding:12px 16px; border-radius:6px; }}
.reasons ul {{ list-style:none; margin-top:6px; }}
.reasons li {{ padding:2px 0; font-size:13px; }}
.note {{ background:#e8f4fd; border-left:4px solid #2980b9; padding:14px 18px; border-radius:6px; margin:20px 0; font-size:13px; }}
.disclaimer {{ background:#fdecea; border-radius:8px; padding:16px 20px; margin-top:28px; font-size:12px; color:#c0392b; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>A&#32929;ETF W&#24213;&#24418;&#24577;&#20998;&#26512;&#25253;&#21578;</h1>
  <div class="subtitle">&#21508;&#26495;&#22359;&#35268;&#27169;&#26368;&#22823;ETF&#30340;W&#24213;&#24418;&#24577;&#25195;&#25551; &#183; &#26469;&#33258; all_etfs_larggest.json</div>
  <div class="meta">
    <span>&#25253;&#21578;&#26085;&#26399;: {today}</span>
    <span>&#25195;&#25551;&#33539;&#22260;: 352 &#21482;ETF</span>
    <span>K&#32447;&#21608;&#26399;: &#26085;&#32447; 250 &#22825;</span>
    <span>&#31639;&#27861;: 5&#38454;&#27573;&#27969;&#27700;&#32447; + 8&#32500;&#35780;&#20998;</span>
  </div>
</div>

<div class="summary-cards">
  <div class="summary-card c-gray"><div class="number">352</div><div class="label">&#25195;&#25551;ETF&#24635;&#25968;</div></div>
  <div class="summary-card c-green"><div class="number">{len(confirmed)}</div><div class="label">W&#24213;&#30830;&#35748;</div></div>
  <div class="summary-card c-blue"><div class="number">{len(forming)}</div><div class="label">W&#24213;&#24418;&#25104;&#20013;</div></div>
  <div class="summary-card c-orange"><div class="number">{len(candidate)}</div><div class="label">W&#24213;&#20505;&#36873;</div></div>
</div>

<div class="note">
  <b>W&#24213;&#21028;&#23450;&#36923;&#36753;:</b> 5&#38454;&#27573;&#27969;&#27700;&#32447;&#26816;&#27979; &#8212; &#9312;&#21069;&#26399;&#19979;&#36300;(40&#26085;&#26012;&#29575;&#8804;-0.005%/&#26085;) &#8594; &#9313;&#24038;&#24213;&#24418;&#25104;(T-40&#33267;T-25) &#8594; &#9314;&#21453;&#24377;&#33267;&#23792;&#39030;(&#8805;8%) &#8594; &#9315;&#21491;&#24213;&#39564;&#35777;(&#177;10%&#20869;, &#37327;&#33021;&#8804;1.2x) &#8594; &#9316;&#31361;&#30772;&#30830;&#35748;(2/3&#26085;&#25910;&#20110;&#23792;&#39030;&#20043;&#19978;)&#12290;
  <b>W&#24213;&#30830;&#35748;</b>&#34920;&#31034;&#24050;&#23436;&#25104;&#39048;&#32447;&#31361;&#30772;, <b>W&#24213;&#24418;&#25104;&#20013;</b>&#34920;&#31034;&#21452;&#24213;&#32467;&#26500;&#23436;&#25972;&#20294;&#23578;&#26410;&#31361;&#30772;, <b>W&#24213;&#20505;&#36873;</b>&#20026;&#24369;&#20449;&#21495;&#12290;
</div>

<div class="section-title">W&#24213;&#20449;&#21495;ETF &#8212; K&#32447;&#32553;&#30053;&#22270; <span class="count">(&#23637;&#31034;&#21069;9&#21517; 120&#26085;&#36208;&#21183;)</span></div>
<div class="charts-grid" id="chartsGrid"></div>

<div class="section-title">&#32508;&#21512;&#24471;&#20998;&#25490;&#21517; (TOP 25) <span class="count">&#39068;&#33394;: &#28072;&#32418;&#36300;&#32511; (A&#32929;&#24815;&#20363;)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF&#21517;&#31216;</th><th>&#24418;&#24577;&#21028;&#23450;</th><th>&#24471;&#20998;</th><th>&#29376;&#24577;</th><th>&#21453;&#24377;%</th><th>&#21452;&#24213;&#24046;%</th><th>&#37327;&#27604;</th><th>&#21491;&#24213;&#25260;&#39640;%</th><th>&#24403;&#21069;&#20215;</th>
</tr></thead>
<tbody>
{''.join(table_rows)}
</tbody></table>
</div>

<div class="section-title">W&#24213;&#20449;&#21495;ETF&#35814;&#32454;&#20998;&#26512;</div>
{''.join(detail_cards)}

<div class="disclaimer">
  <b>&#39118;&#38505;&#25552;&#31034;:</b> &#26412;&#25253;&#21578;&#20165;&#22522;&#20110;&#21382;&#21490;&#20215;&#26684;&#24418;&#24577;&#30340;&#23458;&#35266;&#37327;&#21270;&#20998;&#26512;&#65292;&#19981;&#26500;&#25104;&#20219;&#20309;&#25237;&#36164;&#24314;&#35758;&#12290;W&#24213;&#24418;&#24577;&#35782;&#21035;&#23646;&#20110;&#25216;&#26415;&#20998;&#26512;&#26041;&#27861;&#65292;&#23384;&#22312;&#35823;&#21028;&#21487;&#33021;&#65307;
  &#21452;&#24213;&#32467;&#26500;&#24182;&#38750;100%&#20934;&#30830;&#65292;&#39048;&#32447;&#31361;&#30772;&#21518;&#20173;&#21487;&#33021;&#22238;&#36393;&#22833;&#36133;&#12290;&#25237;&#36164;&#26377;&#39118;&#38505;&#65292;&#20915;&#31574;&#38656;&#35880;&#24910;&#12290;&#35831;&#32467;&#21512;&#22522;&#26412;&#38754;&#12289;&#36164;&#37329;&#38754;&#12289;&#23439;&#35266;&#29615;&#22659;&#32508;&#21512;&#21028;&#26029;&#12290;
  &#25968;&#25454;&#26469;&#28304;: &#33150;&#35759;&#33258;&#36873;&#32929;&#34892;&#24773;&#25509;&#21475;&#65292;&#21487;&#33021;&#23384;&#22312;&#24310;&#36831;&#65292;&#20197;&#20132;&#26131;&#25152;&#23448;&#26041;&#25968;&#25454;&#20026;&#20934;&#12290;
</div>

</div>

<script>
const chartData = {chart_json};
const colors = ['#e74c3c','#2980b9','#9b59b6','#16a085','#e67e22','#34495e','#1abc9c','#d35400','#8e44ad'];
const grid = document.getElementById('chartsGrid');
chartData.forEach((c, idx) => {{
  const card = document.createElement('div');
  card.className = 'chart-card';
  card.innerHTML = `
    <h4><span style="color:${{colors[idx%colors.length]}}">&#9679;</span> ${{c.name}}</h4>
    <div class="sub">${{c.label}} &#183; &#24471;&#20998;${{c.score}} &#183; &#21453;&#24377;${{c.recovery}}% &#183; &#20559;&#24046;${{c.diff}}% &#183; VR${{c.vr}}</div>
    <div class="chart-box"><canvas></canvas></div>
  `;
  grid.appendChild(card);

  const ctx = card.querySelector('canvas').getContext('2d');
  const ltLine = new Array(c.closes.length).fill(c.left_trough);
  const pkLine = new Array(c.closes.length).fill(c.peak);
  const rtLine = new Array(c.closes.length).fill(c.right_trough);

  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: c.dates,
      datasets: [
        {{ data: c.closes, borderColor: colors[idx%colors.length], backgroundColor: colors[idx%colors.length]+'15', borderWidth: 1.8, pointRadius: 0, fill: true, tension: 0.35, label: '&#25910;&#30424;&#20215;' }},
        {{ data: ltLine, borderColor: '#16a085', borderDash: [5,5], borderWidth: 1, pointRadius: 0, fill: false, label: '&#24038;&#24213;='+c.left_trough }},
        {{ data: pkLine, borderColor: '#e67e22', borderDash: [3,3], borderWidth: 1, pointRadius: 0, fill: false, label: '&#23792;&#39030;='+c.peak }},
        {{ data: rtLine, borderColor: '#2980b9', borderDash: [5,5], borderWidth: 1, pointRadius: 0, fill: false, label: '&#21491;&#24213;='+c.right_trough }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{display: false}}, tooltip: {{ callbacks: {{ title: (i) => c.dates[i[0].dataIndex], label: (i) => (i.datasetIndex===0?'&#20215;&#26684; ':'&#21442;&#32771;&#32447; ')+i.parsed.y }}}}}},
      scales: {{ x: {{ display: false }}, y: {{ display: true, position: 'right', ticks: {{ font: {{size: 9}}, color: '#95a5a6' }}, grid: {{ color: '#f0f2f5' }} }} }}
    }}
  }});
}});
</script>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"Report saved to {output_path}")


def main():
    cwd = os.getcwd()
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results_file = os.path.join(skill_dir, "etf_w_bottom_results.json")
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    outdir = os.path.join(cwd, "reports", "etf")
    os.makedirs(outdir, exist_ok=True)
    output = os.path.join(outdir, "etf_w_bottom_report.html")

    if not os.path.exists(results_file):
        print(f"Results file not found: {results_file}", file=sys.stderr)
        print("Run analyze.py first to generate detection results.", file=sys.stderr)
        return

    with open(results_file) as f:
        results = json.load(f)
    with open(kline_file) as f:
        klines = json.load(f)
    build_report(results, klines, output)


if __name__ == "__main__":
    import sys
    main()
