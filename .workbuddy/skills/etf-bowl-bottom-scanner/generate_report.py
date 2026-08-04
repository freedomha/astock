#!/usr/bin/env python3
"""
生成 A股ETF碗底形态分析 HTML 报告 (v1)
- 摘要卡片 (确认/筑底/下跌中继/观望)
- 碗底确认ETF 120日 K线缩略图 (Chart.js)
- TOP25 综合得分排名表
- 碗底确认ETF详细分析卡片
"""

import json
import os
from datetime import datetime


def build_report(results, klines, output_path):
    today = datetime.now().strftime("%Y-%m-%d")

    confirmed = [r for r in results if r["label"].startswith("🟢")]
    forming = [r for r in results if r["label"].startswith("🟡")]
    crash = [r for r in results if r["label"].startswith("🔴")]
    watch = [r for r in results if r["label"].startswith("⚪")]
    total = len(results)

    # Build chart datasets for top confirmed ETFs
    chart_blocks = []
    for r in confirmed[:9]:
        recs = sorted(klines.get(r["code"], []), key=lambda x: x["date"])[-120:]
        closes = [round(float(x["last"]), 2) for x in recs]
        dates = [x["date"][:10] for x in recs]
        chart_blocks.append({
            "name": r["name"], "type": r["type"], "score": r["score"],
            "label": r["label"], "closes": closes, "dates": dates,
            "pos120": r["pos120"], "t20": r["t20"], "t_prior": r["t_prior"],
            "decel": r["decel_ratio"], "hl": r["higher_low"],
        })

    # Build full ranking table rows (top 25)
    table_rows = []
    for i, r in enumerate(results[:25]):
        lc = {"🟢": "#27ae60", "🟡": "#f39c12", "🔴": "#e74c3c", "⚪": "#95a5a6"}.get(r["label"][0], "#333")
        hl_tag = '<span class="tag-green">抬底</span>' if r["higher_low"] else '<span class="tag-red">新低</span>'
        table_rows.append(f"""
        <tr>
          <td><b>{i+1}</b></td>
          <td><b>{r['name']}</b><br><span class="muted">{r['type']}</span></td>
          <td><span style="color:{lc};font-weight:600">{r['label']}</span></td>
          <td><b>{r['score']}</b></td>
          <td class="{'low' if r['pos120']<=20 else ''}">{r['pos120']}%</td>
          <td class="{'low' if r['pos250']<=20 else ''}">{r['pos250']}%</td>
          <td class="{'pos' if r['t20']>0 else 'neg'}">{r['t20']:+}%</td>
          <td class="neg">{r['t_prior']:+}%</td>
          <td>{r['decel_ratio']}</td>
          <td>{hl_tag}</td>
          <td class="neg">{r['drawdown120']}%</td>
          <td class="neg">{r['d_ma60']:+}%</td>
        </tr>""")

    # Detail cards for confirmed
    detail_cards = []
    for i, r in enumerate(confirmed[:9]):
        reasons_html = "".join(f"<li>{x}</li>" for x in r["reasons"])
        detail_cards.append(f"""
        <div class="detail-card">
          <div class="detail-head">
            <span class="rank">#{i+1}</span>
            <h3>{r['name']}</h3>
            <span class="badge" style="background:#27ae60">{r['label']}</span>
            <span class="score-badge">得分 {r['score']}/100</span>
          </div>
          <div class="detail-grid">
            <div class="metric"><span class="ml">当前价格</span><span class="mv">{r['current']}</span></div>
            <div class="metric"><span class="ml">120日区间位</span><span class="mv">{r['pos120']}%</span></div>
            <div class="metric"><span class="ml">250日区间位</span><span class="mv">{r['pos250']}%</span></div>
            <div class="metric"><span class="ml">120日回撤</span><span class="mv neg">{r['drawdown120']}%</span></div>
            <div class="metric"><span class="ml">距120日低点</span><span class="mv">{r['dist_low120']}%</span></div>
            <div class="metric"><span class="ml">近5日</span><span class="mv {'neg' if r['c5']<0 else 'pos'}">{r['c5']:+}%</span></div>
            <div class="metric"><span class="ml">近10日</span><span class="mv {'neg' if r['c10']<0 else 'pos'}">{r['c10']:+}%</span></div>
            <div class="metric"><span class="ml">近20日</span><span class="mv {'neg' if r['c20']<0 else 'pos'}">{r['c20']:+}%</span></div>
            <div class="metric"><span class="ml">60日趋势</span><span class="mv neg">{r['t60']:+}%</span></div>
            <div class="metric"><span class="ml">减速比</span><span class="mv">{r['decel_ratio']}</span></div>
            <div class="metric"><span class="ml">低点抬升</span><span class="mv {'pos' if r['higher_low'] else 'neg'}">{'是' if r['higher_low'] else '否'} ({r['hl_pct']:+}%)</span></div>
            <div class="metric"><span class="ml">U形曲率</span><span class="mv">{r['curvature']}</span></div>
            <div class="metric"><span class="ml">量比(20/60)</span><span class="mv">{r['vol_ratio']}</span></div>
            <div class="metric"><span class="ml">波幅比</span><span class="mv">{r['atr_ratio']}</span></div>
            <div class="metric"><span class="ml">距20MA</span><span class="mv {'neg' if r['d_ma20']<0 else 'pos'}">{r['d_ma20']:+}%</span></div>
            <div class="metric"><span class="ml">距60MA</span><span class="mv neg">{r['d_ma60']:+}%</span></div>
          </div>
          <div class="reasons"><b>判定依据:</b><ul>{reasons_html}</ul></div>
        </div>""")

    chart_json = json.dumps(chart_blocks, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股ETF碗底形态分析报告 · {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:#f5f6fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%); color:#fff; padding:36px 30px; border-radius:12px; margin-bottom:24px; box-shadow:0 4px 20px rgba(0,0,0,0.15); }}
.header h1 {{ font-size:26px; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.85; font-size:14px; }}
.header .meta {{ margin-top:14px; display:flex; gap:24px; font-size:13px; opacity:0.75; flex-wrap:wrap; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-bottom:28px; }}
.summary-card {{ background:#fff; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.summary-card .number {{ font-size:30px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#7f8c8d; margin-top:4px; }}
.c-green .number {{ color:#27ae60; }}
.c-orange .number {{ color:#e67e22; }}
.c-red .number {{ color:#e74c3c; }}
.c-blue .number {{ color:#2980b9; }}
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
.low {{ color:#e67e22; font-weight:600; }}
.tag-green {{ background:#e8f8f0; color:#27ae60; padding:2px 6px; border-radius:4px; font-size:11px; }}
.tag-red {{ background:#fdecea; color:#e74c3c; padding:2px 6px; border-radius:4px; font-size:11px; }}
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
.detail-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px; }}
.metric {{ background:#f8f9fa; padding:9px 12px; border-radius:6px; }}
.metric .ml {{ font-size:12px; color:#7f8c8d; display:block; }}
.metric .mv {{ font-size:15px; font-weight:600; }}
.reasons {{ background:#f8f9fa; padding:12px 16px; border-radius:6px; }}
.reasons ul {{ list-style:none; margin-top:6px; }}
.reasons li {{ padding:2px 0; font-size:13px; }}
.note {{ background:#fff8e1; border-left:4px solid #f39c12; padding:14px 18px; border-radius:6px; margin:20px 0; font-size:13px; }}
.disclaimer {{ background:#fdecea; border-radius:8px; padding:16px 20px; margin-top:28px; font-size:12px; color:#c0392b; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>🥣 A股ETF碗底形态分析报告</h1>
  <div class="subtitle">各板块规模最大ETF的碗底形态扫描 · 来自 all_etfs_larggest.json</div>
  <div class="meta">
    <span>📅 数据日期: {today}</span>
    <span>📊 样本: {total} 只ETF</span>
    <span>📈 K线周期: 日线 250 天</span>
    <span>🔍 算法: 区间位置 + U形拟合 + 双窗口减速 + 低点抬升</span>
  </div>
</div>

<div class="summary-cards">
  <div class="summary-card c-blue"><div class="number">{total}</div><div class="label">分析ETF总数</div></div>
  <div class="summary-card c-green"><div class="number">{len(confirmed)}</div><div class="label">🟢 碗底确认/确认中</div></div>
  <div class="summary-card c-orange"><div class="number">{len(forming)}</div><div class="label">🟡 减速筑底中</div></div>
  <div class="summary-card c-red"><div class="number">{len(crash)}</div><div class="label">🔴 下跌中继</div></div>
  <div class="summary-card c-gray"><div class="number">{len(watch)}</div><div class="label">⚪ 观望</div></div>
</div>

<div class="note">
  <b>📌 碗底判定逻辑 (增强版):</b> 真碗底 = ① 处于 120/250 日区间底部 (位置≤25%) + ② 前期明显下跌后近期趋稳/走平 (减速比&lt;0.8) + ③ 低点抬升 (近10日低点&gt;前10日低点)。
  <b>减速比</b> = 近20日跌幅 ÷ 前40日(等效20日)跌幅，越小代表跌势减速越明显 (0≈已止跌)。
  本算法会剔除"仍在创新低"的伪碗底。
</div>

<div class="section-title">🏆 碗底确认ETF — K线缩略图 <span class="count">(展示前9名 120日走势)</span></div>
<div class="charts-grid" id="chartsGrid"></div>

<div class="section-title">📊 综合得分排名 (TOP 25) <span class="count">颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>形态判定</th><th>得分</th><th>120日位</th><th>250日位</th><th>近20日</th><th>前40日</th><th>减速比</th><th>低点</th><th>120日回撤</th><th>距60MA</th>
</tr></thead>
<tbody>
{''.join(table_rows)}
</tbody></table>
</div>

<div class="section-title">📝 碗底确认ETF详细分析</div>
{''.join(detail_cards)}

<div class="disclaimer">
  ⚠️ <b>风险提示:</b> 本报告仅基于历史价格形态的客观量化分析，不构成任何投资建议。碗底形态识别属于技术分析方法，存在误判可能；
  处于底部区间的ETF可能继续下跌 (底部之下还有底)。投资有风险，决策需谨慎。请结合基本面、资金面、宏观环境综合判断。
  数据来源: 腾讯自选股行情接口，可能存在延迟，以交易所官方数据为准。
</div>

</div>

<script>
const chartData = {chart_json};
const colors = ['#e74c3c','#2980b9','#9b59b6','#16a085','#e67e22','#34495e','#1abc9c','#d35400','#8e44ad'];
const grid = document.getElementById('chartsGrid');
chartData.forEach((c, idx) => {{
  const card = document.createElement('div');
  card.className = 'chart-card';
  const hlText = c.hl ? '抬底✓' : '新低✗';
  const hlColor = c.hl ? '#27ae60' : '#e74c3c';
  card.innerHTML = `
    <h4><span style="color:${{colors[idx%colors.length]}}">●</span> ${{c.name}}</h4>
    <div class="sub">得分${{c.score}} · 120日位${{c.pos120}}% · 近20日${{c.t20>0?'+':''}}${{c.t20}}% · 减速${{c.decel}} · <span style="color:${{hlColor}}">${{hlText}}</span></div>
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
</script>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"Report saved to {output_path}")


def main():
    cwd = os.getcwd()
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    results_file = os.path.join(skill_dir, "etf_bowl_results.json")
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    outdir = os.path.join(cwd, "reports", "etf")
    os.makedirs(outdir, exist_ok=True)
    output = os.path.join(outdir, "etf_bowl_report.html")

    with open(results_file) as f:
        results = json.load(f)
    with open(kline_file) as f:
        klines = json.load(f)
    build_report(results, klines, output)


if __name__ == "__main__":
    main()
