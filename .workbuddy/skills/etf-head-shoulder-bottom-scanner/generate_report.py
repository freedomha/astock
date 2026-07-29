#!/usr/bin/env python3
"""
生成 A股ETF头肩底形态分析 HTML 报告 (v1)
- 摘要卡片 (确认/形成中/候选/非头肩底)
- 头肩底确认ETF 250日 K线缩略图 (Chart.js, 标注左肩/头/右肩/颈线)
- TOP25 综合得分排名表
- 头肩底确认/形成中 ETF 详细分析卡片
"""

import json
import os
from datetime import datetime


def build_report(results, klines, output_path):
    today = datetime.now().strftime("%Y-%m-%d")

    confirmed = [r for r in results if r["label"] == "🟢 头肩底确认"]
    forming = [r for r in results if r["label"] == "🟢 头肩底形成中"]
    candidate = [r for r in results if r["label"] == "🟡 头肩底候选"]
    none_ = [r for r in results if r["label"] == "⚪ 非头肩底"]
    total = len(results)

    has_pattern = [r for r in results if r.get("has_pattern")]

    # Build chart datasets for top confirmed + forming ETFs (show pattern annotations)
    chart_blocks = []
    display_list = (confirmed + forming + candidate)[:12]
    for r in display_list:
        if not r.get("has_pattern"):
            continue
        recs = sorted(klines.get(r["code"], []), key=lambda x: x["date"])[-250:]
        closes = [round(float(x["last"]), 2) for x in recs]
        dates = [x["date"][:10] for x in recs]

        # Calculate pattern point indices relative to the displayed window
        total_kline = len(recs)
        v1_rel = r.get("v1_idx") - (250 - total_kline) if r.get("v1_idx") is not None else None
        v2_rel = r.get("v2_idx") - (250 - total_kline) if r.get("v2_idx") is not None else None
        v3_rel = r.get("v3_idx") - (250 - total_kline) if r.get("v3_idx") is not None else None
        pk1_rel = r.get("peak1_idx") - (250 - total_kline) if r.get("peak1_idx") is not None else None
        pk2_rel = r.get("peak2_idx") - (250 - total_kline) if r.get("peak2_idx") is not None else None

        # Neckline data: line from peak1 to peak2 (extended to right edge)
        neckline = []
        if pk1_rel is not None and pk2_rel is not None:
            pk1 = pk1_rel
            pk2 = pk2_rel
            p1_price = r.get("peak1_price", 0)
            p2_price = r.get("peak2_price", 0)
            if pk2 > pk1 and pk1 >= 0 and pk2 < total_kline:
                slope = (p2_price - p1_price) / (pk2 - pk1)
                for x in range(pk1, total_kline):
                    y = p1_price + slope * (x - pk1)
                    neckline.append({"x": x, "y": round(y, 2)})

        chart_blocks.append({
            "name": r["name"], "type": r["type"], "score": r["score"],
            "label": r["label"], "closes": closes, "dates": dates,
            "v1_idx": v1_rel, "v2_idx": v2_rel, "v3_idx": v3_rel,
            "pk1_idx": pk1_rel, "pk2_idx": pk2_rel,
            "v1_price": r.get("v1_price"), "v2_price": r.get("v2_price"), "v3_price": r.get("v3_price"),
            "peak1_price": r.get("peak1_price"), "peak2_price": r.get("peak2_price"),
            "neckline": neckline,
            "head_depth": r.get("head_depth", 0),
            "neck_slope": r.get("neck_slope", 0),
            "rs_to_neck_pct": r.get("rs_to_neck_pct", 99),
            "pos120": r["pos120"],
        })

    # Build full ranking table rows (top 25)
    table_rows = []
    for i, r in enumerate(results[:25]):
        label_colors = {"🟢 头肩底确认": "#27ae60", "🟢 头肩底形成中": "#2ecc71", "🟡 头肩底候选": "#f39c12", "⚪ 非头肩底": "#95a5a6"}
        lc = label_colors.get(r["label"], "#333")
        if r.get("has_pattern"):
            hd = r.get("head_depth", 0)
            ns = r.get("neck_slope", 0)
            rtn = r.get("rs_to_neck_pct", 99)
            pattern_info = f"头深{hd:.1f}% 颈斜{ns:+.1f}% 距颈{rtn:.1f}%"
        else:
            pattern_info = "—"

        table_rows.append(f"""
        <tr>
          <td><b>{i+1}</b></td>
          <td><b>{r['name']}</b><br><span class="muted">{r['type']}</span></td>
          <td><span style="color:{lc};font-weight:600">{r['label']}</span></td>
          <td><b>{r['score']}</b></td>
          <td class="{'low' if r['pos120']<=30 else ''}">{r['pos120']}%</td>
          <td class="{'pos' if r['t20']>0 else 'neg'}">{r['t20']:+}%</td>
          <td class="neg">{r['t60']:+}%</td>
          <td class="{'pos' if r['c10']>0 else 'neg'}">{r['c10']:+}%</td>
          <td class="neg">{r['d_ma60']:+}%</td>
          <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;font-size:11px">{pattern_info}</td>
        </tr>""")

    # Detail cards for confirmed + forming
    detail_cards = []
    for i, r in enumerate((confirmed + forming)[:12]):
        reasons_html = "".join(f"<li>{x}</li>" for x in r.get("reasons", []))
        label_bg = {"🟢 头肩底确认": "#27ae60", "🟢 头肩底形成中": "#2ecc71"}.get(r["label"], "#3498db")
        
        pattern_metrics = ""
        if r.get("has_pattern"):
            pattern_metrics = f"""
            <div class="metric"><span class="ml">左肩价格</span><span class="mv">{r.get('v1_price', 'N/A')}</span></div>
            <div class="metric"><span class="ml">头部价格</span><span class="mv neg">{r.get('v2_price', 'N/A')}</span></div>
            <div class="metric"><span class="ml">右肩价格</span><span class="mv">{r.get('v3_price', 'N/A')}</span></div>
            <div class="metric"><span class="ml">颈线(左)</span><span class="mv">{r.get('peak1_price', 'N/A')}</span></div>
            <div class="metric"><span class="ml">颈线(右)</span><span class="mv">{r.get('peak2_price', 'N/A')}</span></div>
            <div class="metric"><span class="ml">颈线斜率</span><span class="mv">{r.get('neck_slope', 0):+.1f}%</span></div>
            <div class="metric"><span class="ml">头部深度</span><span class="mv">{r.get('head_depth', 0):.1f}%</span></div>
            <div class="metric"><span class="ml">肩部对称</span><span class="mv">{r.get('shoulder_sym', 0):.0%}</span></div>
            <div class="metric"><span class="ml">时间对称</span><span class="mv">{r.get('time_sym', 0):.2f}</span></div>
            <div class="metric"><span class="ml">量缩(RS/LS)</span><span class="mv">{r.get('vol_rs_ls', 1):.2f}</span></div>
            <div class="metric"><span class="ml">右距颈线</span><span class="mv">{r.get('rs_to_neck_pct', 99):.1f}%</span></div>
            """

        detail_cards.append(f"""
        <div class="detail-card">
          <div class="detail-head">
            <span class="rank">#{i+1}</span>
            <h3>{r['name']}</h3>
            <span class="badge" style="background:{label_bg}">{r['label']}</span>
            <span class="score-badge">得分 {r['score']}/100</span>
          </div>
          <div class="detail-grid">
            <div class="metric"><span class="ml">当前价格</span><span class="mv">{r['current']}</span></div>
            <div class="metric"><span class="ml">120日区间位</span><span class="mv">{r['pos120']}%</span></div>
            <div class="metric"><span class="ml">250日区间位</span><span class="mv">{r['pos250']}%</span></div>
            <div class="metric"><span class="ml">近5日</span><span class="mv {'neg' if r['c5']<0 else 'pos'}">{r['c5']:+}%</span></div>
            <div class="metric"><span class="ml">近10日</span><span class="mv {'neg' if r['c10']<0 else 'pos'}">{r['c10']:+}%</span></div>
            <div class="metric"><span class="ml">近20日</span><span class="mv {'neg' if r['c20']<0 else 'pos'}">{r['c20']:+}%</span></div>
            <div class="metric"><span class="ml">60日趋势</span><span class="mv neg">{r['t60']:+}%</span></div>
            <div class="metric"><span class="ml">量比(20/60)</span><span class="mv">{r.get('vol_ratio', 1):.2f}</span></div>
            {pattern_metrics}
          </div>
          <div class="reasons"><b>判定依据:</b><ul>{reasons_html}</ul></div>
        </div>""")

    chart_json = json.dumps(chart_blocks, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股ETF头肩底形态分析报告 · {today}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; background:#f5f6fa; color:#2c3e50; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; padding:20px; }}
.header {{ background:linear-gradient(135deg,#1a0a2e 0%,#2d1b69 50%,#6c3a9e 100%); color:#fff; padding:36px 30px; border-radius:12px; margin-bottom:24px; box-shadow:0 4px 20px rgba(0,0,0,0.15); }}
.header h1 {{ font-size:26px; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.85; font-size:14px; }}
.header .meta {{ margin-top:14px; display:flex; gap:24px; font-size:13px; opacity:0.75; flex-wrap:wrap; }}
.summary-cards {{ display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin-bottom:28px; }}
.summary-card {{ background:#fff; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.summary-card .number {{ font-size:30px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:#7f8c8d; margin-top:4px; }}
.c-green .number {{ color:#27ae60; }}
.c-blue .number {{ color:#2ecc71; }}
.c-orange .number {{ color:#f39c12; }}
.c-red .number {{ color:#e74c3c; }}
.c-gray .number {{ color:#7f8c8d; }}
.section-title {{ font-size:19px; font-weight:600; margin:28px 0 14px; padding-bottom:10px; border-bottom:2px solid #ecf0f1; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
.section-title .count {{ font-size:13px; color:#7f8c8d; font-weight:400; }}
.legend {{ display:flex; gap:14px; font-size:12px; margin-left:auto; color:#7f8c8d; }}
.legend span {{ display:flex; align-items:center; gap:4px; }}
.legend .dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
.table-wrapper {{ background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 2px 10px rgba(0,0,0,0.06); margin-bottom:28px; overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#f8f9fa; padding:11px 9px; text-align:left; font-weight:600; color:#5a6473; white-space:nowrap; border-bottom:2px solid #e8eaed; }}
td {{ padding:10px 9px; border-bottom:1px solid #f0f2f5; white-space:nowrap; }}
tr:hover td {{ background:#fafbfc; }}
.muted {{ color:#95a5a6; font-size:12px; }}
.pos {{ color:#e74c3c; font-weight:600; }}
.neg {{ color:#16a085; font-weight:600; }}
.low {{ color:#e67e22; font-weight:600; }}
.charts-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:18px; margin-bottom:28px; }}
.chart-card {{ background:#fff; border-radius:10px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.06); }}
.chart-card h4 {{ font-size:15px; margin-bottom:4px; display:flex; align-items:center; gap:8px; }}
.chart-card .sub {{ font-size:12px; color:#7f8c8d; margin-bottom:10px; }}
.chart-box {{ height:180px; position:relative; }}
.detail-card {{ background:#fff; border-radius:10px; padding:20px; margin-bottom:18px; box-shadow:0 2px 10px rgba(0,0,0,0.06); border-left:4px solid #6c3a9e; }}
.detail-head {{ display:flex; align-items:center; gap:12px; margin-bottom:14px; flex-wrap:wrap; }}
.detail-head .rank {{ background:#6c3a9e; color:#fff; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; }}
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
.note {{ background:#f3e8ff; border-left:4px solid #6c3a9e; padding:14px 18px; border-radius:6px; margin:20px 0; font-size:13px; }}
.disclaimer {{ background:#fdecea; border-radius:8px; padding:16px 20px; margin-top:28px; font-size:12px; color:#c0392b; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1> A股ETF头肩底形态分析报告</h1>
  <div class="subtitle">各板块规模最大ETF的头肩底形态扫描 · 左肩→头部→右肩+颈线</div>
  <div class="meta">
    <span> 数据日期: {today}</span>
    <span> 样本: {total} 只ETF</span>
    <span> K线周期: 日线 250 天</span>
    <span> 算法: 局部极值 → 三谷验证 → 颈线拟合 → 多维度评分</span>
  </div>
</div>

<div class="summary-cards">
  <div class="summary-card c-blue"><div class="number">{total}</div><div class="label">分析ETF总数</div></div>
  <div class="summary-card c-green"><div class="number">{len(confirmed)}</div><div class="label"> 头肩底确认</div></div>
  <div class="summary-card c-blue"><div class="number">{len(forming)}</div><div class="label"> 头肩底形成中</div></div>
  <div class="summary-card c-orange"><div class="number">{len(candidate)}</div><div class="label"> 头肩底候选</div></div>
  <div class="summary-card c-gray"><div class="number">{len(none_)}</div><div class="label"> 非头肩底</div></div>
</div>

<div class="note">
  <b> 头肩底形态判定逻辑:</b> 头肩底是经典底部反转形态，由五部分组成: <b>左肩</b> → <b>颈线左高点</b> → <b>头部(最低)</b> → <b>颈线右高点</b> → <b>右肩</b>。
  头必须是最低点，左右肩价差&lt;20%，颈线应大致水平，量能从左肩到右肩递减(卖压耗尽)。
  <b>右肩接近颈线</b>时是最佳观察点，突破颈线则确认反转。
  本算法通过寻找局部极值点，在250日K线中识别符合条件的头肩底结构。
</div>

<div class="section-title"> 头肩底确认/形成中ETF — K线形态缩略图 <span class="count">(展示前{min(len(display_list), 12)}名 250日走势 · 标注:  左肩 头部 右肩 ━颈线)</span>
  <div class="legend">
    <span><span class="dot" style="background:#3498db"></span>左肩</span>
    <span><span class="dot" style="background:#e74c3c"></span>头部</span>
    <span><span class="dot" style="background:#2ecc71"></span>右肩</span>
    <span><span style="border-bottom:2px dashed #f39c12;display:inline-block;width:20px"></span>颈线</span>
  </div>
</div>
<div class="charts-grid" id="chartsGrid"></div>

<div class="section-title"> 综合得分排名 (TOP 25) <span class="count">颜色: 涨红跌绿 (A股惯例)</span></div>
<div class="table-wrapper">
<table>
<thead><tr>
<th>#</th><th>ETF名称</th><th>形态判定</th><th>得分</th><th>120日位</th><th>近20日</th><th>60日趋势</th><th>近10日</th><th>距60MA</th><th>形态信息</th>
</tr></thead>
<tbody>
{''.join(table_rows)}
</tbody></table>
</div>

<div class="section-title"> 头肩底确认/形成中 ETF 详细分析</div>
{''.join(detail_cards)}

<div class="disclaimer">
  ⚠️ <b>风险提示:</b> 本报告仅基于历史价格形态的客观量化分析，不构成任何投资建议。头肩底形态识别属于技术分析方法，存在误判可能；
  形态可能在颈线突破前失败，或在突破后出现回踩。底部形态的完成不等于立即上涨。投资有风险，决策需谨慎。
  请结合基本面、资金面、宏观环境综合判断。数据来源: 腾讯自选股行情接口，可能存在延迟，以交易所官方数据为准。
</div>

</div>

<script>
const chartData = {chart_json};
const colors = ['#6c3a9e','#e74c3c','#2980b9','#16a085','#e67e22','#8e44ad','#2c3e50','#d35400','#1abc9c'];
const grid = document.getElementById('chartsGrid');

chartData.forEach((c, idx) => {{
  const card = document.createElement('div');
  card.className = 'chart-card';
  card.innerHTML = `
    <h4><span style="color:${{colors[idx%colors.length]}}">●</span> ${{c.name}}</h4>
    <div class="sub">得分${{c.score}} · ${{c.label}} · 头深${{(c.head_depth||0).toFixed(1)}}% · 颈斜${{(c.neck_slope||0).toFixed(1)}}% · 右距颈${{(c.rs_to_neck_pct||99).toFixed(1)}}%</div>
    <div class="chart-box"><canvas></canvas></div>
  `;
  grid.appendChild(card);
  
  const ctx = card.querySelector('canvas');
  const datasets = [{{
    data: c.closes,
    borderColor: colors[idx%colors.length],
    backgroundColor: colors[idx%colors.length] + '15',
    borderWidth: 1.8,
    pointRadius: 0,
    fill: true,
    tension: 0.35,
    label: '价格'
  }}];

  // Add neckline if available
  if (c.neckline && c.neckline.length) {{
    datasets.push({{
      data: c.neckline.map(p => p.y),
      borderColor: '#f39c12',
      borderWidth: 1.5,
      borderDash: [6, 3],
      pointRadius: 0,
      fill: false,
      tension: 0,
      label: '颈线',
      order: 1
    }});
  }}

  // Mark LS, Head, RS as scatter points
  const annotations = [];
  if (c.v1_idx !== null && c.v2_idx !== null && c.v3_idx !== null &&
      c.v1_idx >= 0 && c.v2_idx >= 0 && c.v3_idx >= 0 &&
      c.v1_idx < c.closes.length && c.v2_idx < c.closes.length && c.v3_idx < c.closes.length) {{
    const lsData = new Array(c.closes.length).fill(null);
    lsData[c.v1_idx] = c.closes[c.v1_idx];
    datasets.push({{
      data: lsData,
      borderColor: '#3498db',
      backgroundColor: '#3498db',
      pointRadius: 6,
      pointHoverRadius: 8,
      pointStyle: 'rect',
      showLine: false,
      label: '左肩',
      order: 0
    }});

    const headData = new Array(c.closes.length).fill(null);
    headData[c.v2_idx] = c.closes[c.v2_idx];
    datasets.push({{
      data: headData,
      borderColor: '#e74c3c',
      backgroundColor: '#e74c3c',
      pointRadius: 7,
      pointHoverRadius: 9,
      pointStyle: 'triangle',
      showLine: false,
      label: '头部',
      order: 0
    }});

    const rsData = new Array(c.closes.length).fill(null);
    rsData[c.v3_idx] = c.closes[c.v3_idx];
    datasets.push({{
      data: rsData,
      borderColor: '#2ecc71',
      backgroundColor: '#2ecc71',
      pointRadius: 6,
      pointHoverRadius: 8,
      pointStyle: 'rectRot',
      showLine: false,
      label: '右肩',
      order: 0
    }});
  }}

  new Chart(ctx, {{
    type: 'line',
    data: {{ labels: c.dates, datasets: datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            title: (items) => {{
              const idx2 = items[0].dataIndex;
              const name = items[0].dataset.label || '';
              return (name ? name + ' · ' : '') + c.dates[idx2] + ' · ¥' + items[0].parsed.y;
            }}
          }}
        }}
      }},
      scales: {{
        x: {{ display: false }},
        y: {{ display: true, position: 'right', ticks: {{ font: {{size:9}}, color: '#95a5a6', maxTicksLimit: 5 }}, grid: {{ color: '#f0f2f5' }} }}
      }}
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
    results_file = os.path.join(cwd, "etf_hs_bottom_results.json")
    kline_file = os.path.join(cwd, "etf_kline_data.json")
    output = os.path.join(cwd, "etf_hs_bottom_report.html")

    if not os.path.exists(results_file):
        print(f"ERROR: Results file not found: {results_file}")
        print("Run analyze.py first to generate results.")
        return
    if not os.path.exists(kline_file):
        print(f"ERROR: K-line data not found: {kline_file}")
        print("Run analyze.py first to fetch K-line data.")
        return

    with open(results_file) as f:
        results = json.load(f)
    with open(kline_file) as f:
        klines = json.load(f)
    build_report(results, klines, output)


if __name__ == "__main__":
    main()
