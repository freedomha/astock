#!/usr/bin/env python3
"""
生成 A股ETF T2区间扫描 HTML 报告 (v1)
- 摘要卡片 (状态分布 + T2统计)
- 状态分布柱状图 (Chart.js)
- T2置信度排名表 (TOP 25)
- T2 TOP 前9名 120日K线缩略图 (Chart.js)
- T2 详细分析卡片 (状态机reasons + 置信度分项)
"""

import json
import os
from datetime import datetime


def build_report(out, klines, output_path):
    today = datetime.now().strftime("%Y-%m-%d")

    results = out["results"]
    dist = out["state_distribution"]
    t2_list = [r for r in results if r["trend_state"]["code"] == "T2"]
    t2_list.sort(key=lambda x: x.get("t2_score", 0), reverse=True)
    total = len(results)
    t2_count = len(t2_list)
    avg_score = out.get("t2_avg_score")

    state_colors = {
        "T0": "#e74c3c", "T1": "#e67e22", "T2": "#27ae60", "T3": "#2ecc71",
        "T3a": "#2ecc71", "T3b": "#1abc9c", "T4": "#3498db", "T5": "#9b59b6",
        "T6": "#95a5a6", "T7": "#8e44ad", "T8": "#c0392b",
    }

    # ---- State distribution bar chart data ----
    state_keys = sorted(dist, key=lambda x: (int(x[1]) if x[1][:1].isdigit() else 9, x))
    dist_labels = json.dumps(state_keys, ensure_ascii=False)
    dist_values = json.dumps([dist[k] for k in state_keys], ensure_ascii=False)
    dist_colors = json.dumps([state_colors.get(k[:2], "#7f8c8d") for k in state_keys], ensure_ascii=False)

    # ---- Ranking table (top 25 T2) ----
    table_rows = []
    for i, r in enumerate(t2_list[:25]):
        b = r.get("t2_breakdown", {})
        score = r.get("t2_score", 0)
        score_cls = "pos" if score >= 70 else ("warn" if score >= 50 else "muted")
        wk_cls = "pos" if b.get("wk_dir") == "up" else ("warn" if b.get("wk_dir") == "flat" else "neg")
        table_rows.append(f"""
        <tr>
          <td><b>{i+1}</b></td>
          <td><b>{r['name']}</b><br><span class="muted">{r['code']}</span></td>
          <td><span class="score-badge {score_cls}">{score}</span></td>
          <td class="low">{b.get('pos250', '-')}%</td>
          <td class="{'pos' if b.get('hl_pct', 0) > 0 else 'neg'}">{b.get('hl_pct', 0):+}%</td>
          <td class="{wk_cls}">{b.get('wk_dir', '-')} ({b.get('wk_slope', 0):+.1f}%)</td>
          <td class="{'neg' if (b.get('d_ma60') or 0) < 0 else 'pos'}">{b.get('d_ma60', '-')}%</td>
          <td>{b.get('vol_ratio', '-')}</td>
          <td>{b.get('atr_ratio', '-')}</td>
        </tr>""")

    # ---- Sparkline charts for top 9 T2 ----
    chart_blocks = []
    for r in t2_list[:9]:
        recs = sorted(klines.get(r["code"], []), key=lambda x: x["date"])[-120:]
        closes = [round(float(x["last"]), 2) for x in recs]
        dates = [x["date"][:10] for x in recs]
        b = r.get("t2_breakdown", {})
        chart_blocks.append({
            "name": r["name"], "code": r["code"], "score": r.get("t2_score", 0),
            "closes": closes, "dates": dates,
            "pos250": b.get("pos250"), "hl": b.get("hl_pct"), "wk": b.get("wk_dir"),
        })
    chart_json = json.dumps(chart_blocks, ensure_ascii=False)

    # ---- Detail cards for all T2 ----
    detail_cards = []
    for i, r in enumerate(t2_list[:25]):
        trend = r["trend_state"]
        state_reasons = "".join(f"<li>{x}</li>" for x in trend.get("reasons", []))
        t2_reasons = "".join(f"<li>{x}</li>" for x in r.get("t2_reasons", []))
        b = r.get("t2_breakdown", {})
        score = r.get("t2_score", 0)
        border = "#27ae60" if score >= 70 else ("#f39c12" if score >= 50 else "#95a5a6")
        detail_cards.append(f"""
        <div class="detail-card" style="border-left-color:{border}">
          <div class="detail-head">
            <span class="rank" style="background:{border}">#{i+1}</span>
            <h3>{r['name']}</h3>
            <span class="muted">{r['code']}</span>
            <span class="score-badge">置信度 {score}/100</span>
          </div>
          <div class="detail-grid">
            <div class="metric"><span class="ml">当前价格</span><span class="mv">{r['current']}</span></div>
            <div class="metric"><span class="ml">250日区间位</span><span class="mv low">{b.get('pos250', '-')}%</span></div>
            <div class="metric"><span class="ml">250日回撤</span><span class="mv neg">{r['drawdown_250d']}%</span></div>
            <div class="metric"><span class="ml">低点抬高</span><span class="mv {'pos' if b.get('hl_pct', 0) > 0 else 'neg'}">{b.get('hl_pct', 0):+}%</span></div>
            <div class="metric"><span class="ml">周线方向</span><span class="mv">{b.get('wk_dir', '-')}</span></div>
            <div class="metric"><span class="ml">周线斜率10w</span><span class="mv">{b.get('wk_slope', 0):+.1f}%</span></div>
            <div class="metric"><span class="ml">距MA60</span><span class="mv {'neg' if (b.get('d_ma60') or 0) < 0 else 'pos'}">{b.get('d_ma60', '-')}%</span></div>
            <div class="metric"><span class="ml">周量比</span><span class="mv">{b.get('vol_ratio', '-')}</span></div>
            <div class="metric"><span class="ml">ATR比(20/60)</span><span class="mv">{b.get('atr_ratio', '-')}</span></div>
            <div class="metric"><span class="ml">近20日动量</span><span class="mv {'neg' if (b.get('t20') or 0) < 0 else 'pos'}">{b.get('t20', 0):+.1f}%</span></div>
            <div class="metric"><span class="ml">均线排列</span><span class="mv muted">{r['ma']['alignment']}</span></div>
            <div class="metric"><span class="ml">周线数据</span><span class="mv muted">{r['weekly'].get('num_weeks', '-')}周</span></div>
          </div>
          <div class="reasons"><b>状态机判定依据 (T2):</b><ul>{state_reasons}</ul></div>
          <div class="reasons" style="margin-top:8px"><b>置信度分项:</b><ul>{t2_reasons}</ul></div>
        </div>""")

    dist_t1 = dist.get("T1", 0)
    dist_t3 = sum(v for k, v in dist.items() if k.startswith("T3"))

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股ETF T2底部构建扫描报告 · {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:#f5f6fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#0f3d1e 0%,#14532d 50%,#1a6b3a 100%); color:#fff; padding:36px 30px; border-radius:12px; margin-bottom:24px; box-shadow:0 4px 20px rgba(0,0,0,0.15); }}
.header h1 {{ font-size:26px; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.85; font-size:14px; }}
.header .meta {{ margin-top:14px; display:flex; gap:24px; font-size:13px; opacity:0.75; flex-wrap:wrap; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(6,1fr); gap:14px; margin-bottom:28px; }}
.summary-card {{ background:#fff; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.summary-card .number {{ font-size:30px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#7f8c8d; margin-top:4px; }}
.c-green .number {{ color:#27ae60; }} .c-orange .number {{ color:#e67e22; }} .c-red .number {{ color:#e74c3c; }}
.c-blue .number {{ color:#2980b9; }} .c-gray .number {{ color:#7f8c8d; }} .c-purple .number {{ color:#8e44ad; }}
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
.note {{ background:#eaf7ef; border-left:4px solid #27ae60; padding:14px 18px; border-radius:6px; margin:20px 0; font-size:13px; }}
.disclaimer {{ background:#fdecea; border-radius:8px; padding:16px 20px; margin-top:28px; font-size:12px; color:#c0392b; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>🏗️ A股ETF T2底部构建扫描报告</h1>
  <div class="subtitle">T0-T8趋势状态机扫描 · T2区间(底部构建)候选 · 置信度=接近T3升级概率</div>
  <div class="meta">
    <span>📅 数据日期: {today}</span>
    <span>📊 样本: {total} 只ETF</span>
    <span>📈 K线周期: 日线 250 天</span>
    <span>🔍 算法: T0-T8状态机 + 5维置信度打分</span>
  </div>
</div>

<div class="summary-cards">
  <div class="summary-card c-green"><div class="number">{t2_count}</div><div class="label">🏗️ T2 底部构建</div></div>
  <div class="summary-card c-green"><div class="number">{avg_score if avg_score is not None else '-'}</div><div class="label">T2平均置信度</div></div>
  <div class="summary-card c-orange"><div class="number">{dist_t1}</div><div class="label">T1 下降减速</div></div>
  <div class="summary-card c-green"><div class="number">{dist_t3}</div><div class="label">T3 反转确认中</div></div>
  <div class="summary-card c-red"><div class="number">{dist.get('T0', 0)}</div><div class="label">T0 长期下降</div></div>
  <div class="summary-card c-gray"><div class="number">{total - t2_count - dist_t1 - dist_t3 - dist.get('T0', 0)}</div><div class="label">其他状态</div></div>
</div>

<div class="note">
  <b>📌 T2 判定逻辑:</b> ① 250日区间位置 ≤ 35% + ② 低点抬高（近20日低点 > 前20日低点）+ ③ 周线非向下（且未落入T0/T1/T6/T7/T8）。
  置信度打分 5 维: 低点抬高幅度(30) + 距250日低点(25) + 周线斜率回升(20) + 距MA60(15) + 量能/波幅(10)。
  高分(≥70) = 最接近 T3 反转确认，可按操作计划 T2 档（小额试仓，约25%）观察。
</div>

<div class="section-title">📊 趋势状态分布 <span class="count">(全部ETF, 判断大盘筑底广度)</span></div>
<div class="dist-chart-box"><canvas id="distChart"></canvas></div>

<div class="section-title">🏆 T2 置信度排名 (TOP 25) <span class="count">颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>置信度</th><th>250日位</th><th>抬底%</th><th>周线方向</th><th>距MA60</th><th>周量比</th><th>ATR比</th>
</tr></thead>
<tbody>
{''.join(table_rows)}
</tbody></table>
</div>

<div class="section-title">📈 T2 高分ETF — K线缩略图 <span class="count">(前9名 120日走势)</span></div>
<div class="charts-grid" id="chartsGrid"></div>

<div class="section-title">📝 T2 详细分析</div>
{''.join(detail_cards)}

<div class="disclaimer">
  ⚠️ <b>风险提示:</b> 本报告仅基于历史价格形态的客观量化分析，不构成任何投资建议。T2为底部构建状态，
  存在继续下跌 (跌回T1/T0) 的可能；T2→T3升级需周线转上+站上MA60确认。投资有风险，决策需谨慎。
  请结合基本面、资金面、宏观环境综合判断。数据来源: 腾讯自选股行情接口，可能存在延迟，以交易所官方数据为准。
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

const chartData = {chart_json};
const colors = ['#e74c3c','#2980b9','#9b59b6','#16a085','#e67e22','#34495e','#1abc9c','#d35400','#8e44ad'];
const grid = document.getElementById('chartsGrid');
chartData.forEach((c, idx) => {{
  const card = document.createElement('div');
  card.className = 'chart-card';
  card.innerHTML = `
    <h4><span style="color:${{colors[idx%colors.length]}}">●</span> ${{c.name}}</h4>
    <div class="sub">置信度${{c.score}} · 250日位${{c.pos250}}% · 抬底${{c.hl}}% · 周线${{c.wk}}</div>
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
    results_file = os.path.join(skill_dir, "etf_t2_results.json")
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    outdir = os.path.join(cwd, "reports", "etf")
    os.makedirs(outdir, exist_ok=True)
    output = os.path.join(outdir, "etf_t2_report.html")

    with open(results_file) as f:
        out = json.load(f)
    with open(kline_file) as f:
        klines = json.load(f)
    build_report(out, klines, output)


if __name__ == "__main__":
    main()
