#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势门重设计报告：连续评分 + 硬门 vs T0-T8 vs 极简趋势。"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(HERE, "gate_results.json")
ECHARTS = os.path.join(ROOT, "research/assets/echarts.min.js")
OUT = os.path.join(ROOT, "reports/research/Gate-Redesign-20261022.html")

D = json.load(open(SRC, encoding="utf-8"))
A, P = D["signal"], D["policy"]
JS = open(ECHARTS, encoding="utf-8").read()


def n(x, nd=2, sign=False):
    if x is None:
        return "—"
    return (("%+.*f" if sign else "%.*f") % (nd, x)).replace("-", "\u2212")


def sp(x, nd=2):
    if x is None:
        return "—"
    return '<span class="%s">%s</span>' % ("up" if x > 0 else ("down" if x < 0 else ""), n(x, nd, True))


def tag(t):
    return {"g": "g", "y": "y", "r": "r"}.get(t, "")


VAR = {v["label"][:2]: v for v in A["variants"]}
chart = {
    "ic": {
        "name": ["Trend", "Momentum(钟形)", "Momentum(单调)", "Risk", "Trend+Mom", "总分80"],
        "val": [A["ic"][k]["mean"] for k in ("trend", "mom", "mom_mono", "risk", "score_tm", "total")],
        "pos": [A["ic"][k]["pos_share"] for k in ("trend", "mom", "mom_mono", "risk", "score_tm", "total")],
    },
    "vq": {
        "label": ["Q1", "Q2", "Q3", "Q4", "Q5"],
        "total": [r["exc"] for r in A["quintiles"]["total"]],
        "trend": [r["exc"] for r in A["quintiles"]["trend"]],
        "risk": [r["exc"] for r in A["quintiles"]["risk"]],
        "mom": [r["exc"] for r in A["quintiles"]["mom"]],
    },
    "var": {
        "label": [v["label"] for v in A["variants"]],
        "short": [v["label"][:2] for v in A["variants"]],
        "exc": [v["all"]["exc"] for v in A["variants"]],
        "sd": [v["all"]["sd"] for v in A["variants"]],
        "cvar": [v["all"]["cvar"] for v in A["variants"]],
        "q3": [v["q3"]["exc"] for v in A["variants"]],
        "exq3": [v["ex_q3"]["exc"] for v in A["variants"]],
        "y26": [v["y2026"]["exc"] for v in A["variants"]],
        "n": [v["all"]["n"] for v in A["variants"]],
    },
    "diff": {
        "date": [x[0] for x in P["models"]["M0"]["nav"]][::5],
        "M1": [round(a[1] - b[1], 0) for a, b in zip(P["models"]["M1"]["nav"][::5], P["models"]["M0"]["nav"][::5])],
        "M2": [round(a[1] - b[1], 0) for a, b in zip(P["models"]["M2"]["nav"][::5], P["models"]["M0"]["nav"][::5])],
    },
    "thr": {
        "floor": [50, 55, 60, 65, 70, 75],
        "pass": [P["thresholds"]["pass_rate"][str(t)] for t in (50, 55, 60, 65, 70, 75)],
    },
    "nav": {
        "date": [x[0] for x in P["models"]["M0"]["nav"]][::5],
        "M0": [x[1] for x in P["models"]["M0"]["nav"]][::5],
        "M1": [x[1] for x in P["models"]["M1"]["nav"]][::5],
        "M2": [x[1] for x in P["models"]["M2"]["nav"]][::5],
        "cash": [P["cash_only"]["end"]] * len([x for x in P["models"]["M0"]["nav"]][::5]),
    },
}
# 现金曲线：起点 + 每季 3000 阶跃
step, cur = [], P["start"]
cashes = []
qi = 0
for i, (d, _) in enumerate(P["models"]["M0"]["nav"]):
    if qi < len(P["q_ends"]) and d >= P["q_ends"][qi]:
        cur += 3000
        qi += 1
    cashes.append(cur)
chart["nav"]["cash"] = cashes[::5]


def var_rows():
    out = []
    for v in A["variants"]:
        a = v["all"]
        ratio = a["exc"] / a["sd"] if a["sd"] else None
        hl = ' style="background:#f2f7fd"' if v["label"].startswith("V1") else (
            ' style="background:#fdf3f2"' if v["label"].startswith("V6") else "")
        out.append("<tr%s><td><b>%s</b></td><td>%d</td><td>%s</td><td>%s%%</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                   % (hl, v["label"], a["n"], sp(a["exc"]), n(a["win"], 1), n(a["sd"]),
                      n(a["cvar"]), n(ratio, 3), sp(v["q3"]["exc"]), sp(v["ex_q3"]["exc"]), sp(v["y2026"]["exc"])))
    return "".join(out)


def shape_rows():
    out = []
    for lab, key, ic_key in (("钟形（你提的）", "V1", "mom"), ("单调（越高越好）", "V7", "mom_mono")):
        v = VAR[key]
        a = v["all"]
        out.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                   % (lab, sp(A["ic"][ic_key]["mean"], 3), sp(a["exc"]), n(a["sd"]),
                      n(a["cvar"]), sp(v["ex_q3"]["exc"]), sp(v["y2026"]["exc"])))
    return "".join(out)


def ic_rows():
    out = []
    names = {"trend": "Trend 0~30", "mom": "Momentum 钟形 0~30", "mom_mono": "Momentum 单调 0~30",
             "risk": "Risk 0~20", "score_tm": "Trend+Momentum 0~60", "total": "总分 0~80（30/30/20）"}
    for k in ("trend", "mom", "mom_mono", "risk", "score_tm", "total"):
        v = A["ic"][k]
        out.append("<tr><td>%s</td><td>%s</td><td>%s%%</td><td>%d</td></tr>"
                   % (names[k], sp(v["mean"], 3), n(v["pos_share"], 1), v["n_dates"]))
    return "".join(out)


def thr_rows():
    read = {50: "等于不设门（几乎每天都买）", 55: "仅在极端弱市挡住", 60: "只在最弱季度挡住",
            65: "约七分之一的日子无标的", 70: "近三成日子无标的", 75: "半数日子空仓"}
    out = []
    for t in (50, 55, 60, 65, 70, 75):
        v = P["thresholds"]["pass_rate"][str(t)]
        hl = ' style="background:#f2f7fd"' if t == 60 else ""
        out.append("<tr%s><td><b>%d</b></td><td>%s%%</td><td class='l'>%s</td></tr>" % (hl, t, n(v, 1), read[t]))
    return "".join(out)


def dec_rows():
    out = []
    for r in P["thresholds"]["decisions"]:
        p70 = "买" if r["n70"] > 0 else '<span class="muted">现金</span>'
        p60 = "买" if r["n60"] > 0 else '<span class="muted">现金</span>'
        hl = ' style="background:#fdeeee"' if r["n60"] == 0 else ""
        out.append("<tr%s><td>%s</td><td>%s</td><td>%d</td><td>%d</td><td>%d</td><td>%s</td><td>%s</td></tr>"
                   % (hl, r["d"], n(r["best"], 1), r["n70"], r["n60"], r["n_near"], p70, p60))
    return "".join(out)


def policy_rows():
    out = []
    rows = [("M0 T0-T8 状态门", P["models"]["M0"]), ("M1 连续评分 30/30/20/20", P["models"]["M1"]),
            ("M2 极简 MA200+双动量+ΔRC", P["models"]["M2"])]
    for label, m in rows:
        out.append("<tr><td><b>%s</b></td><td>%d</td><td>%s%%</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                   % (label, m["trades"], n(m["total_ret"]), n(m["vol"]), n(m["mdd"]),
                      n(m["cash_ratio"], 1), sp(m["rc50_end"]), sp(m["style_end"]), n(m["bought"], 0)))
    c = P["cash_only"]
    out.append("<tr><td>全部留现金</td><td>0</td><td>0.00%</td><td>0.00</td><td>0.00</td><td>100.0</td><td>—</td><td>—</td><td>0</td></tr>")
    return "".join(out)


def log_rows():
    out = []
    for i, d in enumerate(P["q_ends"]):
        cells = []
        for m in ("M0", "M1", "M2"):
            lg = [x for x in P["models"][m]["log"] if x["date"] == d]
            if not lg:
                cells.append("—")
                continue
            x = lg[0]
            cells.append(("<b>%s</b> %d股 %s元" % (x["name"], x["lot"], n(x["cost"], 0))) if x.get("pick")
                         else '<span class="muted">不买 · %s</span>' % x["reason"])
        out.append("<tr><td>%s</td><td class='l'>%s</td><td class='l'>%s</td><td class='l'>%s</td></tr>" % (d, *cells))
    return "".join(out)


HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>趋势门重设计：连续评分 + 硬门 vs T0-T8</title>
<script>__ECHARTS__</script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6f8;color:#2c3e50;line-height:1.72;padding:24px}
  .wrap{max-width:1120px;margin:0 auto}
  h1{font-size:25px;font-weight:700;margin-bottom:4px;letter-spacing:-.3px}
  .sub{color:#7f8c8d;font-size:13px;margin-bottom:20px}
  .card{background:#fff;border-radius:12px;padding:22px 26px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
  .card.hero{background:linear-gradient(135deg,#12263a,#1f3a5f);color:#fff}
  .card.hero h2{color:#fff;border:none}.card.hero p{color:#cfe0ef}.card.hero b{color:#fff}
  h2{font-size:18px;font-weight:700;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #ecf0f1;color:#1f3a5f}
  h3{font-size:15px;font-weight:600;margin:18px 0 8px;color:#34495e}
  p{font-size:14px;color:#4a5a6a;margin-bottom:10px}
  table{width:100%;border-collapse:collapse;font-size:13px;margin:10px 0}
  th,td{padding:8px 10px;text-align:right;border-bottom:1px solid #eef1f4;vertical-align:top}
  th{background:#f8fafc;color:#5a6b7b;font-weight:600;white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  td.l{text-align:left}
  tbody tr:hover{background:#fafbfc}
  .up{color:#c0392b;font-weight:600}.down{color:#27ae60;font-weight:600}
  .tw{overflow-x:auto}
  .chart{width:100%;height:350px}
  .note{background:#fff9e6;border-left:3px solid #f0c040;padding:10px 14px;border-radius:4px;font-size:13px;color:#7a6a30;margin:12px 0}
  .note.warn{background:#fdeeee;border-left-color:#e74c3c;color:#8b3a3a}
  .note.ok{background:#eafaf1;border-left-color:#27ae60;color:#1e6b45}
  .note.blue{background:#eaf3fb;border-left-color:#2c5c8f;color:#1f4e79}
  .legend{font-size:12px;color:#7f8c8d;margin-top:6px}
  .kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0 4px}
  .kpibox{background:rgba(255,255,255,.10);border-radius:9px;padding:14px 12px;text-align:center;border:1px solid rgba(255,255,255,.14)}
  .kpibox .n{font-size:22px;font-weight:700;letter-spacing:-.5px}
  .kpibox .l{font-size:11.5px;color:#b9cddf;margin-top:4px;line-height:1.4}
  ul,ol{margin:8px 0 8px 22px;font-size:14px;color:#4a5a6a}
  li{margin-bottom:6px}
  .muted{color:#95a5a6;font-size:12px}
  code{background:#eef2f5;padding:1px 5px;border-radius:3px;font-size:12px}
  .foot{color:#95a5a6;font-size:12px;text-align:center;padding:6px 0 24px}
  .arch{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:12px 0}
  .arch div{border-radius:9px;padding:14px 16px;font-size:13px}
  .arch .hard{background:#fdeeee;border:1px solid #f6d5d1}
  .arch .soft{background:#eaf3fb;border:1px solid #d3e3f2}
  .arch b{display:block;margin-bottom:6px;font-size:13.5px}
</style></head><body><div class="wrap">

<h1>趋势门重设计 <span style="color:#95a5a6;font-weight:400">/</span> 连续评分 + 硬门</h1>
<div class="sub">M0 = T0-T8 状态门（现状） · M1 = 连续评分 30/30/20/20 · M2 = MA200 + 双动量 + ΔRC<sub>50</sub>
 · 信号层 __N__ 条观测 / __D__ 个采样日 / __E__ 只 ETF · 政策层 __QN__ 次季度决策 · 2026-10-22 · 非投资建议</div>

<div class="card hero">
  <h2>结论：架构对，配方基本对，只有一处必须改 —— T3b 要从「门」降为「特征」</h2>
  <p style="margin-bottom:12px">七个变体里，只有 <b>V1（你提的 30/30/20/20）</b> 与 <b>V3（Trend+Momentum 60/60）</b> 在三个子样本上全部为正、且最低一段 ≥ +0.44：
  V1 是 __V1Q3__ / __V1EX__ / __V1Y26__，V3 是 __V3Q3__ / __V3EX__ / __V3Y26__（Q3 / 非 Q3 / 2026）。V3 在 Q3 略高，<b>V1 在 2026 明显更高</b>。
  T3b 哑变量样本内最强（__T3BE__），但另两段是 __T3BEX__ / __T3BY26__。<b>连续评分不是更强的选券器，它是没有翻符号的那个。</b></p>
  <div class="kpi">
    <div class="kpibox"><div class="n">__V1EX__</div><div class="l">V1 非 2025Q3 超额<br>（T3b：__T3BEX__）</div></div>
    <div class="kpibox"><div class="n">__V1Y26__</div><div class="l">V1 在 2026 年<br>（T3b：__T3BY26__）</div></div>
    <div class="kpibox"><div class="n">1 / 3 / 4</div><div class="l">5 个季度里实际买入次数<br>M0 / M1 / M2</div></div>
    <div class="kpibox"><div class="n">__RC0__ → __RC2__</div><div class="l">期末 RC50：M0 / M2<br>（结构差异，非运气）</div></div>
  </div>
</div>

<div class="card">
  <h2>一、先确认：硬门 / 软分 的二分是对的</h2>
  <p>你的架构把「不可接受的风险」和「值不值得买」分开，这个划分在数据上有直接支持：四个软分组件里，只有 Trend 和 Momentum 与未来收益同向；Risk 的横截面信息是<strong>反的</strong>（IC __ICRISK__）。如果把它们混在一张分数里当 alpha 用，总分反而被拖低。</p>
  <div class="arch">
    <div class="hard"><b>硬门（不参与评分）</b>
      QDII 溢价 ≤1.5% · 组合回撤 &gt;15% 暂停 · 风格组 ≤60% · 数据质量。<br>
      <span class="muted">共同特征：违反时不是「不够优秀」，而是「性质不同的风险」。回测中溢价门无法复现（见第六节）。</span></div>
    <div class="soft"><b>软分（用于排序与仓位）</b>
      Trend 30 · Momentum 30 · Risk 20 · Diversification 20。<br>
      <span class="muted">共同特征：可以连续恶化、可以互相补偿。Risk / Div 的作用是压波动，不是提高期望收益。</span></div>
  </div>
  <div class="note blue">这个二分解释了一个容易被误读的现象：<b>Risk 组件的 IC 是负的，但它不是坏组件。</b>
    把它加权进总分，前 20% 组合的收益标准差从 __SD_TREND__ 降到 __SD_TOTAL__、5% 尾部从 __CV_TREND__ 改善到 __CV_TOTAL__（单位风险收益反而持平）。
    <b>用 IC 评价保险，会得出「保险有害」的错误结论。</b></div>
</div>

<div class="card">
  <h2>二、组件解剖：三个发现，两个反直觉</h2>
  <div class="tw"><table>
    <thead><tr><th>组件</th><th>横截面 IC（均值）</th><th>IC 为正的交易日占比</th><th>交易日数</th></tr></thead>
    <tbody>__ICROWS__</tbody>
  </table></div>
  <div id="c1" class="chart"></div>
  <div class="legend">IC = 当日截面内「分数 vs 未来 20 日收益」的秩相关，再对交易日取均值。<b>只用当日观测 ≥20 只的 __ICD__ 个交易日</b>——采样网格是按 ETF 交错的，__D__ 个采样日里中位数只有 5 只 ETF，凑不出横截面。</div>

  <h3>发现 1（反直觉）：钟形动量不是缺陷，是保险</h3>
  <table>
    <thead><tr><th>动量形状</th><th>IC</th><th>未调仓收益</th><th>收益标准差</th><th>5% 尾部</th><th>非 2025Q3</th><th>2026</th></tr></thead>
    <tbody>__SHAPEROWS__</tbody>
  </table>
  <div class="note ok">单调动量的 IC 是钟形的 3 倍，样本内收益也高 60%——<b>但一换到非 Q3 样本就掉到 +0.13。</b>
    钟形把「过去 20 日涨 20% 以上」的标的剔除，正好剔掉了 2025Q3 之后最容易反转的那批。<b>你担心的「追涨」问题，数据说你担心对了。</b></div>

  <h3>发现 2（反直觉）：Risk 应留在评分里，不要改成硬否决</h3>
  <p>把 Risk 从「20 分」改成「v20&gt;35% 或回撤&gt;30% 直接不买」：样本内超额几乎不变（__V4E__ vs __V1E__），但 2026 从 <b>__V1Y26BARE__ 掉到 __V4Y26__</b>。硬否决在样本外反而更差——因为它把「波动略高但趋势完好」的标的整段砍掉。</p>

  <h3>发现 3（顺理成章）：总分不是单调的，但比 T3b 稳</h3>
  <div id="c2" class="chart"></div>
  <div class="legend">五个分数分位的未来 20 日超额（同日横截面去均值）。总分 Q1 −0.39 → Q5 +0.52，但 Q1 &lt; Q2（不严格单调）；Trend 更单调；Risk 是反向单调——高 Risk 分（低波动）对应更低收益。</div>
</div>

<div class="card">
  <h2>三、七个变体对抗：唯一的判据是「换样本还正不正」</h2>
  <div class="tw"><table>
    <thead><tr><th>变体</th><th>观测</th><th>全样本超额</th><th>胜率</th><th>标准差</th><th>5% 尾部</th><th>超额/标准差</th><th>仅 2025Q3</th><th>非 2025Q3</th><th>2026</th></tr></thead>
    <tbody>__VARROWS__</tbody>
  </table></div>
  <div id="c3" class="chart"></div>
  <div class="legend">横轴＝收益标准差（越低越稳），纵轴＝同日横截面超额，气泡＝观测数。左上角是理想区：高超额、低波动。V6（T3b）在最左但纵轴最高——它是「样本内最陡、样本外最脆」的那一个。</div>
  <div id="c4" class="chart"></div>
  <div class="legend">同一批观测按三个子样本切开。V1 / V3 的柱子高度接近（稳定）；V2 / V5 / V7 在 2025Q3 很高、其余两段塌下来；V6 在 Q3 最高、其余两段为负。</div>
  <div class="note warn" style="margin-bottom:0"><b>要诚实的一点：</b>2026 是「非 2025Q3」的子集，所以真正独立的切片只有两个（Q3 vs 非 Q3）。
    七个变体也是事后构造的——但 <b>V1 是你在看到这些数据之前就提出的</b>，这一点对它有额外的证据价值；其余六个是我为了对抗它而造的，不能反过来证明 V1。</div>
</div>

<div class="card">
  <h2>四、政策层：5 次决策，收益分不出高下，但分散度分得出</h2>
  <p>同一组合、同一注资节奏（每季末 3,000 元）、同一初始权重，只有「买什么」由模型决定。起点 __START__ 元，全程共 __QN__ 次决策、累计投入 __CONTRIB__ 元。</p>
  <div class="tw"><table>
    <thead><tr><th>模型</th><th>买入次数</th><th>累计收益率</th><th>年化波动</th><th>最大回撤</th><th>平均现金占比</th><th>期末 RC50</th><th>期末风格组</th><th>累计买入额</th></tr></thead>
    <tbody>__POLICYROWS__</tbody>
  </table></div>
  <div id="c5" class="chart"></div>
  <div class="legend">四条曲线几乎完全重合——这就是结论。前 8 个月的差异全部来自存量持仓，与模型无关；之后三条线仍然贴在一起。</div>
  <div id="c6" class="chart" style="height:230px"></div>
  <div class="legend">把上图的差值放大：相对 M0 的总资产差额（元）。全路径最大偏离约 <b>__MAXDIFF__</b> 元，期末差 <b>__DIFF__</b> 元——量级是「千分之一到百分之一」，而累计投入是 __CONTRIB__ 元。</div>
  <h3>逐季决策记录</h3>
  <div class="tw"><table>
    <thead><tr><th>季度末</th><th>M0 状态门</th><th>M1 连续评分</th><th>M2 极简</th></tr></thead>
    <tbody>__LOGROWS__</tbody>
  </table></div>
  <div class="note warn"><b>收益差不可判定：</b>最好与最差相差 __DIFF__ 元（占累计投入 __DIFFP__%），而这只来自 5 次决策中的 3 次方向差异。
    换成统计语言：5 个样本点、单次 3,000 元对 __START__ 元存量影响不到 6%，<b>这个差异连一个标准差都够不上</b>。任何「M2 比 M0 好 X%」的说法都是把单条路径当成期望。</div>
  <div class="note ok"><b>但分散度是可判定的：</b>期末 RC50 —— M0 __RC0__、M1 __RC1__、M2 __RC2__。这个差异不是运气：M0 五季只买入 1 次（其余四季「合格:无」），
    结构几乎没被新钱触及；M1/M2 各买入 3~4 次，纳指与黄金的权重被真正推上去。<b>「只稀释不卖出」的前提是「有钱投出去」，而 T-state 门在这个组合上基本不投。</b></div>
</div>

<div class="card" style="border:2px solid #2c5c8f">
  <h2 style="color:#2c5c8f">五、落地建议（按证据强度排序）</h2>
  <ol>
    <li><b>保留 30/30/20/20，不要现在调权重。</b>它是仅有的两个「三段全为正」构造之一，且 2026 段最高（__V1Y26__ vs V3 的 __V3Y26__）；样本内更高的 V5／V7 全部在样本外塌掉。调权重只有 5 个季度数据支撑，必然过拟合。</li>
    <li><b>T3b 降为 <code>feature.state = T3b</code>，不再决定买不买。</b>这条你的判断和数据完全一致：T3b 的增量在非 Q3 为 −0.84、2026 为 −1.44，而它在报告里承担了「A 类：数据支持」的角色。</li>
    <li><b>阈值改成「绝对下限 60 ＋ 相对带 5」，不用纯相对阈值。</b>纯相对阈值（≥当期最高分−5）<strong>永远挡不住买入</strong>——当期最高分天然满足它，它只决定候选集宽度。见第六节。60 与 5 是预注册候选值，只经过「行为验证」（会挡住最弱的 2026Q1），<strong>没有经过收益验证</strong>。</li>
    <li><b>Risk 留在评分里。</b>改成硬否决后样本外从 +0.71 掉到 +0.17。它的职责是压波动（标准差 10.5→8.2、尾部 −20.8→−12.3），不是提高期望。</li>
    <li><b>Momentum 保留钟形。</b>单调版样本内更高但样本外塌陷，这正是「追涨」的代价。</li>
    <li><b>M2 作为常设 challenger，不要现在替换。</b>它样本内最好（+8.64% vs M1 +7.74%），但差距 573 元、4 次决策，不足以支撑替换。让它再跑 4 个季度。</li>
  </ol>
  <div class="note blue" style="margin-bottom:0"><b>一句话：</b>你不需要一个更聪明的趋势门；你需要一个<strong>不会因为等不到 T3b 而整季空仓</strong>的排序器。
    T-state 的问题不是「信号不够好」，而是「可用频率太低」——在 5 只标的的菜单上，它 5 个季度只放行 1 次。</div>
</div>

<div class="card">
  <h2>六、阈值规则：绝对下限才是「买不买」的开关</h2>
  <p>先把一个几何事实说清楚：<b>「分数 ≥ 当期最高分 − 5」这条规则永远不可能阻止买入。</b>当期最高分自己必然满足它。
  相对阈值只能做两件事：<b>把候选集从 4 只收窄到 __NEAR5__ 只左右</b>，以及在候选之间提供第二道筛。真正决定「这一季买不买」的，<b>只能是绝对下限</b>。</p>
  <div class="note warn">所以上一版建议的「把 70 换成 max−5」是错的：它在最弱的季度会把 48~55 分的标的全部放行，正好把趋势门想避免的问题重新引入。<b>你反对得对。</b></div>
  <h3>绝对下限有多严格（__THN__ 个交易日，五只标的中最高分）</h3>
  <div class="tw"><table>
    <thead><tr><th>下限</th><th>最高分 ≥ 下限的交易日占比</th><th>读法</th></tr></thead>
    <tbody>__THRROWS__</tbody>
  </table></div>
  <div class="legend">最高分的分布：p10 __THQ10__、p25 __THQ25__、中位 __THMED__、p75 __THQ75__、p90 __THQ90__。</div>
  <h3>五个决策日：极端季度长什么样</h3>
  <div class="tw"><table>
    <thead><tr><th>季度末</th><th>最高分</th><th>≥70 的候选数</th><th>≥60 的候选数</th><th>落在 max−5 内的候选数</th><th>floor 70</th><th>floor 60</th></tr></thead>
    <tbody>__DECROWS__</tbody>
  </table></div>
  <div class="note ok"><b>这一步只验证行为，不验证收益：</b>floor 60 唯一的作用点就是 2026Q1（最高 57.2）——它会在那个最弱的季度挡住买入，而在其余四季放行。
    这正是「要有现金选项、但不能常年空仓」的平衡点。相反，floor 70 会在 5 季里挡掉 2 季，floor 50 则一季都挡不住。<b>60 是否「正确」仍未证明；能证明的只是它通过了一次行为检查。</b></div>
</div>

<div class="card">
  <h2>七、局限（会改变幅度，不改变方向）</h2>
  <ul>
    <li><b>溢价门无法回测。</b>接口不提供历史 NAV / IOPV 序列，只有当日静态溢价。因此「QDII 溢价 ≤1.5%」在所有回测里都是<strong>假设已通过</strong>的——M0/M1/M2 都买过纳指，实盘当时可能一笔都买不了。</li>
    <li><b>政策层只有 5 次决策。</b>见第四节的警告。这个层的作用是<strong>验证管道能跑通、暴露行为差异</strong>，不是给模型排名。</li>
    <li><b>信号层样本从 21,201 降到 __N__。</b>因为 MA200 要求 200 根历史，最早的 4 个月被截掉；2025Q3 仍在样本内。</li>
    <li><b>QDII 用场内价。</b>纳指/标普的 2025Q3 收益里有溢价扩张，会同时抬高 M1/M2 的分数与收益。</li>
    <li><b>2026 与「非 Q3」重叠</b>，不是三个独立切片，是 2 + 1。</li>
    <li><b>采样网格交错。</b>状态机每 5 个交易日采样一次，但各 ETF 的偏移不同，所以 __D__ 个采样日里只有 __ICD__ 个能凑出 ≥20 只的横截面（其余中位数仅 5 只）。IC 与「同日横截面超额」在稀疏日上噪声较大；分位与变体表用的是全部观测，因此更稳健但仍然不精确。</li>
    <li><b>变体是事后构造的。</b>七个变体里挑最好看的有选择偏差；V1 的优势在于它先于数据存在，其余变体不享有这个待遇。</li>
  </ul>
</div>

<div class="foot">数据：etf_kline_data_500.json（346 只 ETF）＋ prices.json（5 只持仓 + 沪深300，2026-10-22 收盘）＋ backtest_trend_state_results.json（T 码）
 ｜ 脚本：research/gate-redesign/analyze.py ｜ 仅供研究，不构成投资建议</div>
</div>

<script>
var DATA = __DATA__;
var CLR = {red:'#c0392b', green:'#27ae60', blue:'#2c5c8f', grey:'#95a5a6', ink:'#2c3e50', grid:'#eef1f4'};
var base = {textStyle:{fontFamily:'-apple-system,PingFang SC,sans-serif'}, tooltip:{trigger:'axis'},
            grid:{left:56,right:56,top:36,bottom:44}};
function ax(o){ return Object.assign({}, base, o); }
function col(v){ return v >= 0 ? CLR.red : CLR.green; }

echarts.init(document.getElementById('c1')).setOption(ax({
  tooltip:{trigger:'axis', formatter:function(p){return p[0].name+'<br/>IC '+p[0].value+'<br/>正IC占比 '+p[1].value+'%';}},
  xAxis:{type:'category', data:DATA.ic.name, axisLabel:{fontSize:11, rotate:18}},
  yAxis:{type:'value', name:'IC', splitLine:{lineStyle:{color:CLR.grid}}},
  series:[{type:'bar', data:DATA.ic.val.map(function(v){return {value:v, itemStyle:{color:col(v)}};}),
           label:{show:true, position:'top', fontSize:11}}]
}));

echarts.init(document.getElementById('c2')).setOption(ax({
  legend:{data:['总分','Trend','Risk','Momentum'], top:4, textStyle:{fontSize:12}},
  xAxis:{type:'category', data:DATA.vq.label, axisLabel:{fontSize:12}},
  yAxis:{type:'value', name:'20日超额 (pp)', splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {name:'总分', type:'line', data:DATA.vq.total, symbolSize:7, lineStyle:{width:3, color:CLR.blue}, itemStyle:{color:CLR.blue}},
    {name:'Trend', type:'line', data:DATA.vq.trend, symbolSize:6, lineStyle:{width:2, color:'#e67e22'}, itemStyle:{color:'#e67e22'}},
    {name:'Risk', type:'line', data:DATA.vq.risk, symbolSize:6, lineStyle:{width:2, type:'dashed', color:CLR.green}, itemStyle:{color:CLR.green}},
    {name:'Momentum', type:'line', data:DATA.vq.mom, symbolSize:6, lineStyle:{width:2, type:'dotted', color:CLR.grey}, itemStyle:{color:CLR.grey}}
  ]
}));

echarts.init(document.getElementById('c3')).setOption({
  tooltip:{formatter:function(p){return p.data[2]+'<br/>标准差 '+p.data[0]+'<br/>超额 '+p.data[1]+'pp';}},
  grid:{left:60,right:40,top:26,bottom:44},
  xAxis:{type:'value', name:'收益标准差', nameLocation:'middle', nameGap:28, splitLine:{lineStyle:{color:CLR.grid}}},
  yAxis:{type:'value', name:'20日超额 (pp)', splitLine:{lineStyle:{color:CLR.grid}}},
  series:[{type:'scatter', symbolSize:16,
    data:DATA.var.label.map(function(l,i){return [DATA.var.sd[i], DATA.var.exc[i], l];}),
    itemStyle:{color:CLR.blue},
    label:{show:true, formatter:function(p){return p.data[2].slice(0,2);}, position:'top', fontSize:11},
    markLine:{silent:true, symbol:'none', lineStyle:{color:CLR.grey, type:'dashed'}, data:[{yAxis:0}]}}]
});

echarts.init(document.getElementById('c4')).setOption(ax({
  tooltip:{trigger:'axis', valueFormatter:function(v){return (v==null?'n/a':v+'pp');}},
  legend:{data:['仅 2025Q3','非 2025Q3','2026'], top:4, textStyle:{fontSize:12}},
  xAxis:{type:'category', data:DATA.var.short, axisLabel:{fontSize:12}},
  yAxis:{type:'value', name:'超额 (pp)', splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {name:'仅 2025Q3', type:'bar', data:DATA.var.q3, itemStyle:{color:'#e8a5a0'}},
    {name:'非 2025Q3', type:'bar', data:DATA.var.exq3, itemStyle:{color:CLR.blue}},
    {name:'2026', type:'bar', data:DATA.var.y26, itemStyle:{color:'#7fb3d5'}}
  ]
}));

echarts.init(document.getElementById('c5')).setOption({
  tooltip:{trigger:'axis'}, legend:{data:['M0 状态门','M1 连续评分','M2 极简','全部现金'], top:4, textStyle:{fontSize:12}},
  grid:{left:70,right:40,top:36,bottom:44},
  xAxis:{type:'category', data:DATA.nav.date, axisLabel:{fontSize:10, formatter:function(v){return v.slice(2,7);}}},
  yAxis:{type:'value', name:'总资产 (元)', scale:true, splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {name:'M0 状态门', type:'line', data:DATA.nav.M0, symbol:'none', lineStyle:{width:2, color:CLR.grey}},
    {name:'M1 连续评分', type:'line', data:DATA.nav.M1, symbol:'none', lineStyle:{width:2, color:CLR.blue}},
    {name:'M2 极简', type:'line', data:DATA.nav.M2, symbol:'none', lineStyle:{width:2, color:CLR.red}},
    {name:'全部现金', type:'line', data:DATA.nav.cash, symbol:'none', lineStyle:{width:1.5, type:'dashed', color:'#b3bec9'}}
  ]

});

echarts.init(document.getElementById('c6')).setOption({
  tooltip:{trigger:'axis'}, legend:{data:['M1 − M0','M2 − M0'], top:0, textStyle:{fontSize:11}},
  grid:{left:64,right:36,top:28,bottom:36},
  xAxis:{type:'category', data:DATA.diff.date, axisLabel:{fontSize:9, formatter:function(v){return v.slice(2,7);}}},
  yAxis:{type:'value', name:'差额 (元)', scale:true, splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {name:'M1 − M0', type:'line', data:DATA.diff.M1, symbol:'none', lineStyle:{width:1.8, color:CLR.blue}},
    {name:'M2 − M0', type:'line', data:DATA.diff.M2, symbol:'none', lineStyle:{width:1.8, color:CLR.red}},
    {type:'line', data:DATA.diff.M1.map(function(){return 0;}), symbol:'none', lineStyle:{width:1, type:'dashed', color:'#c9d6e3'}, tooltip:{show:false}}
  ]
});
</script>
</body></html>
"""

V1 = VAR["V1"]
T3B = VAR["V6"]
DIFF = max(m["end"] for m in P["models"].values()) - min(m["end"] for m in P["models"].values())
_a = [x[1] for x in P["models"]["M0"]["nav"]]
MAXDIFF = max(abs(P["models"][m]["nav"][i][1] - _a[i])
              for m in ("M1", "M2") for i in range(len(_a)))
rep = {
    "__ECHARTS__": JS, "__DATA__": json.dumps(chart, ensure_ascii=False),
    "__N__": "{:,}".format(A["n"]), "__ICD__": str(A["ic"]["trend"]["n_dates"]), "__D__": str(A["dates"]), "__E__": str(A["etfs"]),
    "__QN__": str(len(P["q_ends"])),
    "__V1Q3__": n(V1["q3"]["exc"], 2, True),
    "__V3Q3__": n(VAR["V3"]["q3"]["exc"], 2, True), "__V3EX__": n(VAR["V3"]["ex_q3"]["exc"], 2, True),
    "__V3Y26__": n(VAR["V3"]["y2026"]["exc"], 2, True), "__V1EX__": n(V1["ex_q3"]["exc"], 2, True),
    "__V1Y26__": n(V1["y2026"]["exc"], 2, True),
    "__T3BE__": n(T3B["all"]["exc"], 2, True), "__T3BEX__": n(T3B["ex_q3"]["exc"], 2, True),
    "__T3BY26__": n(T3B["y2026"]["exc"], 2, True),
    "__RC0__": n(P["models"]["M0"]["rc50_end"], 1), "__RC1__": n(P["models"]["M1"]["rc50_end"], 1),
    "__RC2__": n(P["models"]["M2"]["rc50_end"], 1),
    "__ICRISK__": n(A["ic"]["risk"]["mean"], 3, True),
    "__SD_TREND__": n(VAR["V2"]["all"]["sd"]), "__SD_TOTAL__": n(VAR["V1"]["all"]["sd"]),
    "__CV_TREND__": n(VAR["V2"]["all"]["cvar"]), "__CV_TOTAL__": n(VAR["V1"]["all"]["cvar"]),
    "__ICROWS__": ic_rows(), "__SHAPEROWS__": shape_rows(),
    "__V1E__": n(V1["all"]["exc"], 2, True), "__V4E__": n(VAR["V4"]["all"]["exc"], 2, True),
    "__V4Y26__": n(VAR["V4"]["y2026"]["exc"], 2, True),
    "__V1Y26BARE__": n(V1["y2026"]["exc"], 2, True), "__VARROWS__": var_rows(), "__POLICYROWS__": policy_rows(),
    "__LOGROWS__": log_rows(), "__THRROWS__": thr_rows(), "__DECROWS__": dec_rows(),
    "__THN__": str(P["thresholds"]["n_days"]),
    "__NEAR5__": ("%g" % P["thresholds"]["near5_median"]),
    "__THQ10__": n(P["thresholds"]["q10"], 1), "__THQ25__": n(P["thresholds"]["q25"], 1),
    "__THMED__": n(P["thresholds"]["median"], 1), "__THQ75__": n(P["thresholds"]["q75"], 1),
    "__THQ90__": n(P["thresholds"]["q90"], 1),
    "__START__": "{:,.0f}".format(P["start"]), "__CONTRIB__": "{:,.0f}".format(P["models"]["M0"]["contributed"]),
    "__DIFF__": "{:,.0f}".format(DIFF), "__MAXDIFF__": "{:,.0f}".format(MAXDIFF), "__DIFFP__": n(DIFF / P["models"]["M0"]["contributed"] * 100, 2),
}

if __name__ == "__main__":
    html = HTML
    for k, v in rep.items():
        html = html.replace(k, v)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(html)
    print("written", OUT, os.path.getsize(OUT))
