#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 tstate_validation.json 生成自包含 HTML 报告。

所有正文数字在服务端注入（不依赖浏览器 JS 计算），图表数据单独以 JSON 传入。
输出：reports/research/T-State-Validation-20261022.html
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "research/tstate-validation/tstate_validation.json")
ECHARTS = os.path.join(ROOT, "research/assets/echarts.min.js")
OUT = os.path.join(ROOT, "reports/research/T-State-Validation-20261022.html")

D = json.load(open(SRC, encoding="utf-8"))
JS = open(ECHARTS, encoding="utf-8").read()


def n(x, nd=2, sign=False):
    if x is None:
        return "—"
    s = ("%+.*f" if sign else "%.*f") % (nd, x)
    return s.replace("-", "\u2212")


def cls(x):
    if x is None:
        return ""
    return "up" if x > 0 else ("down" if x < 0 else "")


def span(x, nd=2, unit="pp"):
    if x is None:
        return "—"
    c = cls(x)
    return '<span class="%s">%s%s</span>' % (c, n(x, nd, True), unit)


H = D["health"]
DEC = D["decomposition"]
CONC = D["concentration"]
BOOT = D["bootstrap"]
WF = D["walk_forward"]
HO = D["holdout"]
MS = D["max_stat"]
HG = D["horizon_grid"]
BR = D["breadth"]
NV = D["naive"]
MOM = D["momentum"]
EC = D["economics"]
T20 = D["tables"]["20"]
T3B20 = [r for r in T20["rows"] if r["state"] == "T3b"][0]
EXQ = CONC["ex_top_quarter"]
HO_T3B = [x for x in HO["states"] if x["state"] == "T3b"][0]
OOSH = HO["t3b_by_horizon"]

# ── 图表数据 ──────────────────────────────────────────────
chart = {
    "states": [r["state"] for r in T20["rows"]],
    "pooled": [r["excess_pooled"] for r in T20["rows"]],
    "cs": [r["excess_cs"] for r in T20["rows"]],
    "months": [m["m"] for m in CONC["months"]],
    "month_n": [m["n"] for m in CONC["months"]],
    "month_ex": [m["excess_cs"] if m["n"] >= 5 else None for m in CONC["months"]],
    "quarters": [q["q"] for q in CONC["quarters"]],
    "q_ex": [q["excess_cs"] for q in CONC["quarters"]],
    "q_n": [q["n"] for q in CONC["quarters"]],
    "boot": {
        "mode": ["ETF 聚类（211 组）", "自然月块（18 块）", "季度块（7 块）"],
        "abs": [BOOT[k]["abs_ci"] for k in ("etf", "month", "quarter")],
        "cs": [BOOT[k]["cs_ci"] for k in ("etf", "month", "quarter")],
    },
    "wf": {
        "label": [x["test"] for x in WF["timeline"]],
        "train": [x["train_excess"] for x in WF["timeline"]],
        "oos": [x["oos_excess"] if x["n_test"] >= 10 else None for x in WF["timeline"]],
        "t3b": [x["t3b_excess"] if x["t3b_n"] >= 10 else None for x in WF["timeline"]],
    },
    "ho": {
        "state": [x["state"] for x in HO["states"]],
        "train": [x["train_excess"] for x in HO["states"]],
        "test": [x["test_excess"] for x in HO["states"]],
    },
    "heat": {
        "states": list(reversed(sorted(HG["grid"]["20"].keys()))),
        "horizons": sorted(HG["grid"].keys(), key=lambda z: int(z)),
    },
    "hist": BR["hist"],
    "mom": {
        "label": ["Q%d %s~%s%%" % (b["bucket"], n(b["mom_lo"], 0), n(b["mom_hi"], 0)) for b in MOM["buckets"]],
        "t3b": [b["t3b_excess"] for b in MOM["buckets"]],
        "other": [b["other_excess"] for b in MOM["buckets"]],
        "diff": [b["diff"] for b in MOM["buckets"]],
    },
}
heat_data = []
for yi, s in enumerate(chart["heat"]["states"]):
    for xi, h in enumerate(chart["heat"]["horizons"]):
        v = HG["grid"][h].get(s)
        if v is not None:
            heat_data.append([xi, yi, v])
chart["heat"]["data"] = heat_data

# ── 表格渲染 ──────────────────────────────────────────────

def state_rows(rows):
    out = []
    for r in rows:
        rank = ""
        out.append(
            "<tr><td><b>%s</b></td><td>%d</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (r["state"], r["n"], r["etfs"], n(r["avg"]), span(r["excess_pooled"]),
               span(r["excess_cs"]), n(r["winrate"], 1) + "%", n(r["beat_cs_median"], 1) + "%"))
    return "".join(out)


def quarter_rows():
    out = []
    for q in CONC["quarters"]:
        if q["n"] == 0:
            out.append("<tr><td>%s</td><td>0</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>" % q["q"])
            continue
        hot = ' style="background:#fdf3f2"' if q["q"] == CONC["top_quarter"] else ""
        out.append("<tr%s><td>%s</td><td>%d</td><td>%s%%</td><td>%s%%</td><td>%s</td><td>%s</td><td>%s%%</td></tr>"
                   % (hot, q["q"], q["n"], n(q["share"], 1), n(q["occurrence"], 1),
                      n(q["avg"]), span(q["excess_cs"]), n(q["winrate"], 1)))
    return "".join(out)


def boot_rows():
    out = []
    names = {"etf": "按 ETF 聚类", "month": "按自然月分块", "quarter": "按季度分块"}
    for k in ("etf", "month", "quarter"):
        b = BOOT[k]
        out.append("<tr><td>%s</td><td>%d</td><td>%s ~ %s</td><td>%s ~ %s</td><td>%s%%</td></tr>"
                   % (names[k], b["clusters"],
                      n(b["abs_ci"][0]), n(b["abs_ci"][1]),
                      n(b["cs_ci"][0], 2, True), n(b["cs_ci"][1], 2, True),
                      n(b["cs_p_le0"], 1)))
    return "".join(out)


def wf_rows():
    out = []
    for x in WF["timeline"]:
        mark = ' style="background:#fdf3f2"' if x["test"] == "2025Q3" else ""
        out.append("<tr%s><td>%s</td><td>%s</td><td><b>%s</b></td><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>"
                   % (mark, x["train_end"], x["test"], x["picked"], span(x["train_excess"]),
                      x["train_t3b_n"], span(x["train_t3b_excess"]),
                      span(x["oos_excess"]) if x["n_test"] >= 10 else "n=%d 不足" % x["n_test"],
                      x["t3b_n"], span(x["t3b_excess"])))
    return "".join(out)


def ho_rows():
    out = []
    for x in HO["states"]:
        hot = ' style="background:#fdf3f2"' if x["state"] == "T3b" else ""
        out.append("<tr%s><td><b>%s</b></td><td>%d</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s%%</td></tr>"
                   % (hot, x["state"], x["train_n"], span(x["train_excess"]), x["test_n"],
                      span(x["test_excess"]), n(x["test_abs"]),
                      n(x["test_win"], 1) if x["test_win"] is not None else "—"))
    return "".join(out)


def oosh_rows():
    out = []
    for x in OOSH:
        out.append("<tr><td>%d 日</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td></tr>"
                   % (x["h"], span(x["train_excess"]), x["test_n"], span(x["test_excess"]),
                      n(x["test_abs"]) if x["test_abs"] is not None else "—"))
    return "".join(out)


def cat_rows():
    out = []
    for c in BR["categories"]:
        out.append("<tr><td>%s</td><td>%d</td><td>%d</td><td>%s%%</td><td>%s</td><td>%s</td><td>%s%%</td></tr>"
                   % (c["cat"], c["n"], c["etfs"], n(c["share"], 1), n(c["avg"]),
                      span(c["excess_cs"]), n(c["winrate"], 1)))
    return "".join(out)


def ms_rows():
    out = []
    for s, v in MS["observed"].items():
        c = "up" if v > 0 else ("down" if v < 0 else "")
        out.append('<span class="chip %s"><b>%s</b>%s</span>' % (c, s, n(v, 2, True)))
    return "".join(out)


def naive_rows():
    order = [("t3b", "T3b（状态机）"), ("naive_ma60_up", "价 &gt; MA60 且 MA60 上行"), ("naive_and_t3b", "&nbsp;&nbsp;其中同时是 T3b"),
             ("naive_not_t3b", "&nbsp;&nbsp;其中不是 T3b"), ("naive_slope_only", "仅 MA60 上行（不看价格位置）"),
             ("all", "全样本")]
    out = []
    for k, label in order:
        g = NV[k]
        hot = ' style="background:#fdf3f2"' if k == "t3b" else ""
        out.append("<tr%s><td>%s</td><td>%d</td><td>%d</td><td>%s</td><td>%s</td><td>%s%%</td></tr>"
                   % (hot, label, g["n"], g["etfs"], n(g["avg"]), span(g["excess_cs"]), n(g["winrate"], 1)))
    return "".join(out)


def mom_rows():
    out = []
    for b in MOM["buckets"]:
        out.append("<tr><td>Q%d</td><td>%s ~ %s%%</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                   % (b["bucket"], n(b["mom_lo"], 1), n(b["mom_hi"], 1), b["n_t3b"],
                      span(b["t3b_excess"]), span(b["other_excess"]), span(b["diff"])))
    return "".join(out)


# ── 区间条（替代森林图，纯 CSS，避免 custom series 的坐标问题）──────────────
def forest_html():
    lo_s, hi_s = -3.2, 8.5
    span_ = hi_s - lo_s
    rows = [("ETF 聚类（211 组）", BOOT["etf"]), ("自然月块（18 块）", BOOT["month"]), ("季度块（7 块）", BOOT["quarter"])]

    def bar(v, kind):
        a, b = v[0], v[1]
        left = (a - lo_s) / span_ * 100
        w = max(0.6, (b - a) / span_ * 100)
        return '<div class="fbar %s" style="left:%.2f%%;width:%.2f%%"></div>' % (kind, left, w)

    ticks = "".join('<span style="left:%.2f%%">%s</span>' % ((t - lo_s) / span_ * 100, ("%g" % t).replace("-", "\u2212"))
                    for t in (-3, 0, 3, 6))
    out = ['<div class="forest">',
           '<div class="fscale"><div></div><div class="fticks">%s</div><div>pp（越窄越好）</div></div>' % ticks]
    for label, b in rows:
        out.append('<div class="frow"><div class="flab">%s</div>'
                   '<div class="ftrack"><div class="fzero" style="left:%.2f%%"></div>%s%s</div>'
                   '<div class="fval">超额 %s~%s<br>绝对 %s~%s</div></div>'
                   % (label, (0 - lo_s) / span_ * 100,
                      bar(b["abs_ci"], "abs"), bar(b["cs_ci"], "cs"),
                      n(b["cs_ci"][0], 2, True), n(b["cs_ci"][1], 2, True),
                      n(b["abs_ci"][0]), n(b["abs_ci"][1])))
    out.append('</div>')
    out.append('<div class="fkey"><i style="background:#2c5c8f"></i>绝对收益 95%CI'
               '<i style="background:#c0392b"></i>同日横截面超额 95%CI</div>')
    return "".join(out)


# ── 判决表 ──────────────────────────────────────────────
verdict = [
    ("基准换成同日横截面", "+4.33 → +1.57pp", "弱",
     "64% 的「超额」来自 T3b 出现在市场普涨的日子，不是选对了标的", "y"),
    ("剔除最强单季（2025Q3）", "%spp" % n(EXQ["excess_cs"], 2, True), "否",
     "%d 条观测剔除后，横截面超额转负，胜率回落到 %s%%" % (EXQ["n"], n(EXQ["winrate"], 1)), "r"),
    ("2026 严格样本外", "%spp（n=%d）" % (n(HO_T3B["test_excess"], 2, True), HO_T3B["test_n"]), "否",
     "2025 训练 +%s → 2026 检验 %s；排名从第 1 掉到第 %d" % (n(HO_T3B["train_excess"]), n(HO_T3B["test_excess"]),
                                                     HO["rank_test"].index("T3b") + 1), "r"),
    ("扩张窗口 walk-forward", "%spp/季" % n(WF["avg_oos_excess"], 2, True), "否",
     "%d 期检验，命中率 %s%%；最关键的 2025Q3 事前选的是 T0 不是 T3b" % (WF["n_periods"], n(WF["hit_rate"], 1)), "r"),
    ("季度块 bootstrap", "%s ~ %spp" % (n(BOOT["quarter"]["cs_ci"][0], 2, True), n(BOOT["quarter"]["cs_ci"][1], 2, True)), "不显著",
     "按季度重抽样，%s%% 的样本里横截面超额 ≤ 0" % n(BOOT["quarter"]["cs_le0"] if "cs_le0" in BOOT["quarter"] else BOOT["quarter"]["cs_p_le0"], 1), "y"),
    ("同日标签置换", "p &lt; 0.002", "是",
     "500 次置换无一达到 +1.57pp——标签确实携带横截面信息，不是纯噪声", "g"),
    ("朴素趋势规则对照", "+0.04 vs +1.57pp", "是",
     "「价&gt;MA60 且 MA60 上行」有 10,050 条观测只有 +0.04；T3b 是其 8.4% 的子集，却有 +1.57", "g"),
    ("横截面广度", "%s%% 的 ETF 为正" % n(BR["positive_share"], 1), "中性",
     "211 只 ETF 里正负各半，中位数仅 %spp；靠右尾若干只拉起来" % n(BR["etf_excess_median"]), "y"),
]
verdict_html = "".join(
    '<tr><td><b>%s</b></td><td class="mono">%s</td><td><span class="tag %s">%s</span></td><td class="l">%s</td></tr>'
    % (a, b, tag, c, d) for a, b, c, d, tag in verdict)

# ── 组装 ──────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>T-State Validation / Walk-Forward Research</title>
<script>__ECHARTS__</script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6f8;color:#2c3e50;line-height:1.72;padding:24px}
  .wrap{max-width:1120px;margin:0 auto}
  h1{font-size:25px;font-weight:700;margin-bottom:4px;letter-spacing:-.3px}
  .sub{color:#7f8c8d;font-size:13px;margin-bottom:20px}
  .card{background:#fff;border-radius:12px;padding:22px 26px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
  .card.hero{background:linear-gradient(135deg,#2a1f2e,#4a2b34);color:#fff}
  .card.hero h2{color:#fff;border:none}
  .card.hero p{color:#e8d5da}
  .card.hero b{color:#fff}
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
  .mono{font-variant-numeric:tabular-nums}
  .chart{width:100%;height:360px}.chart.tall{height:440px}.chart.sm{height:300px}
  .note{background:#fff9e6;border-left:3px solid #f0c040;padding:10px 14px;border-radius:4px;font-size:13px;color:#7a6a30;margin:12px 0}
  .note.warn{background:#fdeeee;border-left-color:#e74c3c;color:#8b3a3a}
  .note.ok{background:#eafaf1;border-left-color:#27ae60;color:#1e6b45}
  .note.blue{background:#eaf3fb;border-left-color:#2c5c8f;color:#1f4e79}
  .legend{font-size:12px;color:#7f8c8d;margin-top:6px}
  .kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0 4px}
  .kpibox{background:rgba(255,255,255,.10);border-radius:9px;padding:14px 12px;text-align:center;border:1px solid rgba(255,255,255,.14)}
  .kpibox .n{font-size:23px;font-weight:700;letter-spacing:-.5px}
  .kpibox .l{font-size:11.5px;color:#c9b6bc;margin-top:4px;line-height:1.4}
  .kpibox .s{font-size:11px;color:#9d8c93;margin-top:2px}
  ul,ol{margin:8px 0 8px 22px;font-size:14px;color:#4a5a6a}
  li{margin-bottom:6px}
  .muted{color:#95a5a6;font-size:12px}
  .tag{display:inline-block;padding:1px 8px;border-radius:4px;font-size:11px;font-weight:600;background:#e8f4ff;color:#2c5c8f}
  .tag.g{background:#eafaf1;color:#1e8449}.tag.y{background:#fff4e6;color:#c77c1f}
  .tag.r{background:#fdeeee;color:#c0392b}
  code{background:#eef2f5;padding:1px 5px;border-radius:3px;font-size:12px}
  .kv{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:10px 0}
  .kv div{background:#f8fafc;border-radius:8px;padding:10px 12px;font-size:13px}
  .kv b{display:block;font-size:17px;color:#1f3a5f;margin-bottom:1px}
  .foot{color:#95a5a6;font-size:12px;text-align:center;padding:6px 0 24px}
  .tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .forest{margin:14px 0 6px;font-size:12.5px}
  .frow{display:grid;grid-template-columns:132px 1fr 168px;align-items:center;gap:10px;margin-bottom:10px}
  .flab{color:#4a5a6a;text-align:right}
  .fval{color:#7f8c8d;font-variant-numeric:tabular-nums}
  .ftrack{position:relative;height:34px;background:#f8fafc;border-radius:5px}
  .fzero{position:absolute;top:0;bottom:0;width:1px;background:#c9d6e3}
  .fbar{position:absolute;height:10px;border-radius:2px}
  .fbar.abs{top:5px;background:#2c5c8f}
  .fbar.cs{top:19px;background:#c0392b}
  .fscale{display:grid;grid-template-columns:132px 1fr 168px;gap:10px;font-size:11px;color:#95a5a6;margin-bottom:2px}
  .fscale .fticks{position:relative;height:14px}
  .fscale .fticks span{position:absolute;transform:translateX(-50%)}
  .fkey{font-size:12px;color:#7f8c8d;margin-bottom:6px}
  .fkey i{display:inline-block;width:16px;height:7px;border-radius:2px;margin:0 4px 0 12px;vertical-align:middle}
  .chips{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
  .chip{display:inline-flex;align-items:center;gap:7px;background:#f8fafc;border:1px solid #eef1f4;border-radius:6px;padding:6px 11px;font-size:13px;font-variant-numeric:tabular-nums}
  .chip b{font-weight:700;color:#5a6b7b;font-size:12px}
  .chip.up{background:#fdf3f2;border-color:#f6d5d1}.chip.up span,.chip.up{color:#c0392b}
  .chip.down{background:#eefaf3;border-color:#d3f0e0}.chip.down{color:#1e8449}
</style>
</head>
<body>
<div class="wrap">

  <h1>T-State Validation <span style="color:#95a5a6;font-weight:400">/</span> Walk-Forward Research</h1>
  <div class="sub">被测命题：T3b 未来 20 日超额 <b>+4.33pp</b>、胜率 <b>75.9%</b>「有前瞻优势」
    · 样本：__N_SIG__ 条状态观测 / __N_ETF__ 只 ETF / __DATE_FROM__ ~ __DATE_TO__
    · 生成 __AS_OF__ · 全部数字由 <code>research/tstate-validation/analyze.py</code> 产出 · 非投资建议</div>

  <div class="card hero">
    <h2>判决：+4.33pp 不能作为「可泛化」的证据</h2>
    <p style="margin-bottom:12px">它是「<b>一个季度</b> ＋ <b>一个高动量分位</b>」的联合产物。剥掉时间效应后只剩 <b>+1.57pp</b>；剔除 2025Q3 后为 <b>−0.52pp</b>；2026 全年样本外为 <b>−1.46pp</b>；扩张窗口滚动检验平均 <b>−0.33pp/季</b>。与此同时，同日标签置换检验 p&lt;0.002——<b>T3b 不是纯噪声</b>，但它证明的东西远小于原结论声称的东西。</p>
    <div class="kpi">
      <div class="kpibox"><div class="n">__K1__</div><div class="l">同日横截面超额<br>（原口径 +4.33pp）</div><div class="s">时间效应占 __K1S__%</div></div>
      <div class="kpibox"><div class="n">__K2__</div><div class="l">剔除 2025Q3 后<br>（n=__K2N__）</div><div class="s">胜率 __K2W__%</div></div>
      <div class="kpibox"><div class="n">__K3__</div><div class="l">2026 严格样本外<br>（n=__K3N__）</div><div class="s">训练期 +__K3T__pp</div></div>
      <div class="kpibox"><div class="n">__K4__</div><div class="l">walk-forward 平均<br>（__K4N__ 期检验）</div><div class="s">命中率 __K4H__%</div></div>
    </div>
  </div>

  <div class="card">
    <h2>一、八道检验的判决表</h2>
    <p>「可泛化」需要样本外、跨时间、跨标的都站得住。八道检验里 2 道支持、5 道不支持、1 道中性——这个配比不足以支撑「A 类：数据支持」的定级。</p>
    <table>
      <thead><tr><th>检验</th><th>结果</th><th>支持可泛化？</th><th>读法</th></tr></thead>
      <tbody>__VERDICT__</tbody>
    </table>
    <div class="note warn" style="margin-bottom:0"><b>最刺眼的一条不是「样本外为负」，而是「事前根本选不出来」。</b>
      2025Q2 末那一轮做选择时，训练集里 T3b 的超额是 <b>__WFQ2EX__pp</b>（__WFQ2N__ 条），在 __WFQ2S__ 个合格状态里排第 __WFQ2R__，模型选了 T0；
      而紧接着的 2025Q3 正是 T3b 唯一的大胜季（+2.94pp、508 条）。<b>这个信号的最强证据，出现在它还不是最优候选的那个季度之后。</b></div>
  </div>

  <div class="card">
    <h2>二、基准：64% 的「超额」不是选券，是选时</h2>
    <p>原结论的基准是「全样本 20 日平均 +1.29%」。这个基准把「不同时间」和「不同标的」混在一起。拆成两层看：T3b 出现的那些日子，全市场平均后续 20 日涨 <b>__CSDAYS__%</b>；T3b 标的相对同日全市场再多 <b>__CSEX__pp</b>。</p>
    <div class="kv">
      <div><b>__ABS__%</b>T3b 的 20 日绝对收益</div>
      <div><b>__CSDAYS__%</b>信号日的全市场平均（＝时间效应）</div>
      <div><b>__CSEX__pp</b>同日横截面超额（＝选券效应）</div>
    </div>
    <div id="c1" class="chart"></div>
    <div class="legend">红＝池化超额（原报告口径，基准 = 全样本均值）；蓝＝同日横截面超额（基准 = 当天所有在场 ETF 等权）。同日口径下 <b>T8（结构破坏）反而排第一（+1.85pp），T3b 第二（+1.57pp）</b>——排名本身就不稳。</div>
    <table>
      <thead><tr><th>状态</th><th>观测</th><th>ETF</th><th>20日均值(%)</th><th>池化超额</th><th>同日横截面超额</th><th>胜率</th><th>跑赢同日中位数</th></tr></thead>
      <tbody>__STATEROWS__</tbody>
    </table>
    <div class="note"><b>为什么两个基准差这么多：</b>池化基准是「随便挑一天、随便挑一只」的期望；同日基准是「同一天里挑哪只」。前者包含「T3b 是不是出现在好时候」，后者只包含「T3b 是不是挑对了标的」。
      原报告要用 T3b 做<b>单标的择时</b>，两者都相关——但把 4.33pp 整体称作「信号优势」，等于把 β 择时算成了选券能力。</div>
  </div>

  <div class="card">
    <h2>三、时间聚集：841 条观测 ≠ 841 个证据</h2>
    <p>T3b 在 <b>__TOPQ__</b> 一季贡献了 <b>__TOPQS__%</b> 的观测，前两季合计 <b>__TOP2S__%</b>。按「同一 ETF 间隔 &gt;10 自然日算新的一段」计，真正独立的持有段只有 <b>__EPS__</b> 段（平均 __EPSLEN__ 个采样点）。</p>
    <div id="c2" class="chart"></div>
    <div class="legend">柱＝当月 T3b 观测数（左轴）；线＝当月同日横截面超额（右轴，pp；样本不足 5 条的月份不画线，避免单点噪声）。2025-06~08 三个月占了全部观测的 __H2S__%。</div>
    <h3>按季度</h3>
    <table>
      <thead><tr><th>季度</th><th>T3b 观测</th><th>占全部 T3b</th><th>当季出现率</th><th>20日均值(%)</th><th>同日超额</th><th>胜率</th></tr></thead>
      <tbody>__QROWS__</tbody>
    </table>
    <h3>按半年</h3>
    <table>
      <thead><tr><th>半年</th><th>观测</th><th>出现率</th><th>20日均值(%)</th><th>同日超额</th><th>胜率</th></tr></thead>
      <tbody>__HROWS__</tbody>
    </table>
    <div class="note warn" style="margin-bottom:0"><b>剔除 __TOPQ__ 后：</b>n=__EXQN__、20 日均值 <b>__EXQABS__%</b>、同日横截面超额 <b>__EXQEX__pp</b>、胜率 <b>__EXQW__%</b>（基准 52.8%）。
      一个季度的证据撑起了一个被写成「A 类、数据支持」的规则。</div>
  </div>

  <div class="card">
    <h2>四、置信区间：真正的宽度取决于你按什么聚类</h2>
    <p>841 条观测里有大量重叠：同一只 ETF 一次持有段内每 5 个交易日一个采样点，前瞻又取 20 日。按 ETF 聚类看起来显著（CI __BETF__），但<strong>同一个月里几十只 ETF 往往同时进入 T3b</strong>——ETF 之间不独立。按时间块重抽样，区间立刻变宽。</p>
    __FOREST__
    <table>
      <thead><tr><th>重抽样方式</th><th>独立单元</th><th>绝对收益 95%CI</th><th>同日超额 95%CI</th><th>bootstrap 中 ≤0 的比例</th></tr></thead>
      <tbody>__BOOTROWS__</tbody>
    </table>
    <div class="note"><b>读法：</b>「按 ETF 聚类显著、按时间聚类不显著」本身就是结论——说明这个信号的 <b>噪声主要在时间维度</b>，正是「一段行情决定结论」的形态。季度块只有 7 个，CI 宽是必然的；但这不是统计缺陷，这是样本本身的信息量就这么少。</div>
  </div>

  <div class="card">
    <h2>五、Walk-forward：扩张窗口下，事前选不出 T3b</h2>
    <p>规则：每个季度末，用<strong>截至当时</strong>的全部数据，按同日横截面超额挑出最优状态，下一季检验。不做任何未来信息泄漏。</p>
    <div id="c4" class="chart"></div>
    <div class="legend">红＝训练期（历史上该状态看起来多好）；灰＝下一季实际（样本外）；蓝虚线＝下一季 T3b 自己的表现（同期限样本不足 10 条不画）。红灰之间的落差就是「看起来」与「做起来」的距离。</div>
    <table>
      <thead><tr><th>训练截止</th><th>检验季</th><th>选中状态</th><th>训练超额</th><th>训练期 T3b 条数</th><th>训练期 T3b 超额</th><th>OOS 超额</th><th>同期 T3b 条数</th><th>同期 T3b 超额</th></tr></thead>
      <tbody>__WFROWS__</tbody>
    </table>
    <div class="note warn" style="margin-bottom:0"><b>关键一行是 2025Q3：</b>训练期 T3b 超额 −0.36pp、只有 228 条，模型选了 T0，OOS −1.01pp；而那一季 T3b 有 508 条、超额 +2.94pp。
      <b>换句话：让 T3b 成为「A 类证据」的那一季，恰恰是一个诚实的 walk-forward 会错过的季度。</b></div>
  </div>

  <div class="card">
    <h2>六、严格样本外：2026 年，中长端全为负</h2>
    <p>用 2025 全年训练、2026 全年检验（不做滚动，一次性切分）。T3b 训练期 +1.88pp，检验期 <b>−1.46pp</b>；在 2026 的 10 个状态里排第 <b>__HORANK__</b>。换期限也一样：</p>
    <div id="c5" class="chart"></div>
    <table>
      <thead><tr><th>状态</th><th>2025 观测</th><th>2025 超额</th><th>2026 观测</th><th>2026 超额</th><th>2026 绝对收益</th><th>2026 胜率</th></tr></thead>
      <tbody>__HOROWS__</tbody>
    </table>
    <h3>T3b 在不同前瞻期限上的样本内 vs 样本外</h3>
    <table>
      <thead><tr><th>期限</th><th>2025（训练）</th><th>2026 观测</th><th>2026（检验）</th><th>2026 绝对收益</th></tr></thead>
      <tbody>__OOSHROWS__</tbody>
    </table>
    <div class="note warn" style="margin-bottom:0"><b>形态本身就是证据：</b>样本内越强的期限（40 日 +3.75），样本外越差（−3.73）。如果 T3b 是真实漂移，衰减应该是同号的、幅度收窄；<b>符号翻转说明它是拟合到 2025 年那段行情的相位，而不是一个稳定的收益来源</b>。</div>
  </div>

  <div class="card">
    <h2>七、多重检验：50 格里挑出最好的一格</h2>
    <p>「T3b 20 日 +4.33pp」是从 <b>10 个状态 × 5 个期限 = 50 个格子</b>里挑出来的。格子越多，最大的那个越容易显得厉害——这是机械的。真正的问题是：<b>挑出来的那一格，比「随便一个格子」大多少？</b></p>
    <div id="c6" class="chart tall"></div>
    <div class="legend">颜色＝同日横截面超额（pp），红＝正，绿＝负。同一状态在不同期限上可以换符号（T8：20 日 +1.85 → 60 日 −0.83），说明「期限」本身就是一个自由度。</div>
    <h3>同日标签置换检验（保留每个日期的状态构成，只打乱哪只 ETF 拿到哪个标签）</h3>
    <div class="chips">__MSROWS__</div>
    <div class="note blue"><b>顺带一提：50 格里最大的一格恰是 T3b @ 40 日（+__BESTV__pp）。</b>但同一格在 2026 样本外是 <b>__BESTOOS__pp</b>——「最好的一格」与「最不耐久的一格」是同一个。</div>
    <div class="note ok"><b>这一关 T3b 是过的。</b>500 次同日置换，最大值的 95 分位只有 <b>__NULLP95__pp</b>，99 分位 <b>__NULLP99__pp</b>；实际观测到的 +1.57pp 一次都没被复制出来（p&lt;0.002）。
      <b>所以 T3b 里确实有横截面信息，不能一概归为噪声。</b>但请注意：这个检验证明的是「某个状态携带信息」，而全局最大的一格是 <b>__MAXSTATE__ @ +__MAXV__pp</b>，不是 T3b。</div>
  </div>

  <div class="card">
    <h2>八、那为什么它看起来像真的：两个支持性证据</h2>
    <h3>8.1 状态机确实在朴素规则之上加了东西</h3>
    <p>用 500 日 K 线重算一条不含状态机的朴素趋势规则：「收盘价 &gt; MA60 且 MA60 的 20 日斜率 &gt; 0」。它有 10,050 条观测，同日超额只有 +0.04pp。T3b 的观测 <b>99.9% 落在这条规则的范围内</b>，是它的 8.4% 子集，却拿到 +1.57pp。</p>
    <table>
      <thead><tr><th>口径</th><th>观测</th><th>ETF</th><th>20日均值(%)</th><th>同日超额</th><th>胜率</th></tr></thead>
      <tbody>__NAIVEROWS__</tbody>
    </table>
    <div class="note blue">这条对 T3b 有利：<b>多出来的条件（周线转上、低点抬高、MA60 上行）不是装饰</b>。它把「趋势向上」这个大集合里表现最差的部分切掉了。</div>

    <h3>8.2 但优势只存在于最高动量分位</h3>
    <p>把全部观测按「过去 20 日涨幅」五等分，在每个分位内比较 T3b 与非 T3b。除最高分位外，T3b 的超额是 0 或负；只有在「过去 20 日涨 6% 以上」这一档，T3b 才比同档其他标的再多 <b>+__MOMDIFF__pp</b>。</p>
    <div id="c7" class="chart"></div>
    <table>
      <thead><tr><th>动量分位</th><th>过去 20 日区间</th><th>T3b 条数</th><th>T3b 同日超额</th><th>同档其他标的</th><th>差值</th></tr></thead>
      <tbody>__MOMROWS__</tbody>
    </table>
    <div class="note"><b>这解释了为什么结论对季度这么敏感：</b>T3b 本质是「高位追涨」的确认信号，它的收益完全依赖「追进去之后还能再涨一段」——而 2025Q3 正是这种行情。换个季度，同样的形态没有同样的后续。</div>
  </div>

  <div class="card">
    <h2>九、广度：211 只 ETF 里，正负各半</h2>
    <div class="kv">
      <div><b>__BRN__</b>出现 T3b 的 ETF 数</div>
      <div><b>__BRPOS__%</b>其中同日超额为正的比例</div>
      <div><b>__BRMED__pp</b>单只 ETF 超额的中位数</div>
    </div>
    <div id="c8" class="chart sm"></div>
    <div class="legend">每只 ETF 的「平均同日超额」分布（pp）。四分位区间 __BRP25__ ~ __BRP75__，极值 __BRMIN__ / __BRMAX__——典型的「少数右尾撑起均值」。</div>
    <table>
      <thead><tr><th>类别</th><th>T3b 观测</th><th>ETF</th><th>占比</th><th>20日均值(%)</th><th>同日超额</th><th>胜率</th></tr></thead>
      <tbody>__CATROWS__</tbody>
    </table>
    <div class="note">类别为脚本按「实现波动率 + 名称」自动划分（波动率 &lt;3% 归现金类、&lt;8% 归债券）。<b>黄金 / 债券 / 现金类的样本只有个位数，不作为结论依据</b>，列出只为说明：跨资产类别看，T3b 的证据几乎全部来自 A 股权益 ETF（行业主题 90%）。</div>
  </div>

  <div class="card">
    <h2>十、经济显著性：就算有效，也不支撑现在的用法</h2>
    <div class="kv">
      <div><b>__FREQ__%</b>T3b 占全部观测的比例</div>
      <div><b>__PERYEAR__ 次/年</b>单只 ETF 平均遇到 T3b 的采样次数</div>
      <div><b>__DAYS__ 天/年</b>折算成处于该状态的时间</div>
    </div>
    <p>含义：<b>T3b 不是一个「一直在场」的策略状态，而是一个稀疏事件。</b>它覆盖的时间只占 __FREQ__%，单只 ETF 一年平均只有 __DAYS__ 个交易日处于该状态。用「20 日超额 +4.33pp」去描述一个一年触发一两次的事件，量级上就已经错位——那 4.33pp 是<b>事件发生时的条件均值</b>，不是<b>组合的年化收益</b>。</p>
    <p>成本不是问题：单次往返 0.10%（佣金 + 半价差）相对 __CSEX2__pp 的横截面超额只占 <b>__COSTR__%</b>。问题在频率与稳定性，不在摩擦。</p>
  </div>

  <div class="card">
    <h2>十一、局限（这些不改变方向，但会改变幅度）</h2>
    <ul>
      <li><b>2026 样本外只有 __HO3N__ 条 T3b 观测。</b>「−1.46pp」这个点估计本身也不可靠，能说的只是「没有出现正超额」，不能说是「证明无效」。</li>
      <li><b>单一市场周期。</b>2025-01 ~ 2026-08 只有一个完整的上行段。任何「跨周期可泛化」的判断，本样本都支撑不了。</li>
      <li><b>尾部样本被截断。</b>21,201 条观测里 20,178 条有完整 20 日前瞻（覆盖率 95.2%），末尾约 1,023 条因未来数据不足被剔除——它们全部集中在样本末端，会略微削弱 2026 后半段的代表性。</li>
      <li><b>重叠窗口。</b>20 日前瞻 + 5 日采样，相邻样本高度相关；有效样本量远小于 21,201。本文用聚类 bootstrap 处理，但聚类本身的个数（7 个季度）也很少。</li>
      <li><b>ETF 池有幸存者偏差。</b>用的是「今天规模最大的 329 只」，2025 年时点的小规模 ETF 不在池内。对横截面超额的影响较小（同一天内比较），对时间序列绝对收益的影响较大。</li>
      <li><b>状态定义不是拟合出来的</b>（周线转上 + 站上 MA60 + 低点抬高 + MA60 上行是事前写死的），这一点对 T3b 有利；但<b>「用 20 日、看 +4.33pp」是事后选的</b>，这一点对它不利。两者不能互相抵消。</li>
      <li><b>未做交易成本的回测。</b>本文只检验统计量，未模拟净值曲线。成本占比小（6.4%），但滑点在稀疏事件上可能更大。</li>
    </ul>
  </div>

  <div class="card" style="border:2px solid #c0392b">
    <h2 style="color:#c0392b">十二、对规则的含义</h2>
    <ol>
      <li><b>把 T3b 从「A 类：数据支持」降为「A−：仅样本内支持」或 B 类。</b>季定投报告第五节现写「规则 3 的 T3b 分支（20 日超额 +4.33pp、胜率 75.9%、跌&gt;10% 仅 1.2%）」。这个表述把<b>一个季度的样本内均值</b>写成了<b>统计结论</b>。
        建议改为：「20 日同日横截面超额 +1.57pp（样本内），剔除 2025Q3 后为 −0.52pp，2026 样本外为 −1.46pp；作为『允许买入』的条件保留，<b>不作为收益预期</b>」。</li>
      <li><b>换基准。</b>把所有状态统计的基准从「全样本均值」改成「同日横截面均值」，并同时给出「剔除最大季度」的数字。这两个数字应该和原数字并列出现，不能只留一个。</li>
      <li><b>「T4 无优势」在同日口径下仍成立</b>（−0.80pp，原 −1.21pp，方向不变）；但 <b>T0 变成 +0.79pp、T8 变成 +1.85pp</b>——「T0／T8 一律禁买」在同日口径下同样缺证据。原报告把这两条标为 C 类是对的，但正文里「T6 接近平均」的说法要连带修正：T6 在同日口径下是 −0.66pp，比原结论更差。</li>
      <li><b>不要用 T3b 做「收益预测」。</b>它更接近「风险时点的分类」：告诉你现在处在什么形态，不告诉你未来 20 日能拿多少。策略上把它当<b>准入条件</b>（gate）而不是<b>期望收益来源</b>（alpha），与季定投计划里「只稀释、不卖出」的定位一致。</li>
      <li><b>下一轮验证需要什么才叫「可泛化」：</b>① 至少跨两个完整市场周期；② 样本外 T3b 观测 ≥300 条（按当前频率约需 4~5 年）；③ 预先注册期限（不能事后从 50 格里挑）；④ 用季度块聚类报告 CI，而不是 ETF 聚类。</li>
    </ol>
    <div class="note blue" style="margin-bottom:0"><b>一句话：</b>这套状态机不是坏的，但它的证据强度被高估了。把「+4.33pp」换成「+1.57pp，且剔掉一个季度就归零」，它对决策的影响会从「可以加仓的理由」变成「可以买入的必要条件之一」——这两者对仓位的含义完全不同。</div>
  </div>

  <div class="foot">数据：backtest_trend_state_results.json（21,201 条状态观测）+ etf_kline_data_500.json ｜ 脚本：research/tstate-validation/analyze.py ｜ 种子 20261022 ｜ 仅供研究，不构成投资建议</div>
</div>

<script>
var DATA = __DATA__;
var CLR = {red:'#c0392b', green:'#27ae60', blue:'#2c5c8f', grey:'#95a5a6', ink:'#2c3e50', grid:'#eef1f4'};
var base = {textStyle:{fontFamily:'-apple-system,PingFang SC,sans-serif'}, tooltip:{trigger:'axis'},
            grid:{left:52,right:56,top:36,bottom:40}};
function ax(o){ return Object.assign({}, base, o); }
function barColor(v){ return v >= 0 ? CLR.red : CLR.green; }

// 1 状态 × 两个基准
echarts.init(document.getElementById('c1')).setOption(ax({
  tooltip:{trigger:'axis', valueFormatter:function(v){return v+'pp';}},
  legend:{data:['池化超额（原口径）','同日横截面超额'], top:4, textStyle:{fontSize:12}},
  xAxis:{type:'category', data:DATA.states, axisLabel:{fontSize:12}},
  yAxis:{type:'value', name:'20日超额 (pp)', nameTextStyle:{fontSize:11}, splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {name:'池化超额（原口径）', type:'bar', data:DATA.pooled, itemStyle:{color:'#e8a5a0'}, barGap:'10%'},
    {name:'同日横截面超额', type:'bar', data:DATA.cs, itemStyle:{color:CLR.blue}}
  ]
}));

// 2 月度 n + 超额
echarts.init(document.getElementById('c2')).setOption(ax({
  tooltip:{trigger:'axis'}, legend:{data:['T3b 观测数','同日超额'], top:4, textStyle:{fontSize:12}},
  xAxis:{type:'category', data:DATA.months, axisLabel:{fontSize:10, rotate:45}},
  yAxis:[{type:'value', name:'观测数', nameTextStyle:{fontSize:11}, splitLine:{lineStyle:{color:CLR.grid}}},
         {type:'value', name:'超额 (pp)', nameTextStyle:{fontSize:11}, splitLine:{show:false}}],
  series:[
    {name:'T3b 观测数', type:'bar', data:DATA.month_n, itemStyle:{color:'#c9d6e3'}},
    {name:'同日超额', type:'line', yAxisIndex:1, data:DATA.month_ex, smooth:false, symbolSize:5,
     lineStyle:{color:CLR.red, width:2}, itemStyle:{color:CLR.red}}
  ]
}));

// 4 walk-forward
echarts.init(document.getElementById('c4')).setOption(ax({
  tooltip:{trigger:'axis', valueFormatter:function(v){return (v==null?'n/a':v+'pp');}},
  legend:{data:['训练期超额','下一季实际（OOS）','下一季 T3b'], top:4, textStyle:{fontSize:12}},
  xAxis:{type:'category', data:DATA.wf.label, axisLabel:{fontSize:11}},
  yAxis:{type:'value', name:'同日超额 (pp)', nameTextStyle:{fontSize:11}, splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {name:'训练期超额', type:'bar', data:DATA.wf.train, itemStyle:{color:'#e8a5a0'}},
    {name:'下一季实际（OOS）', type:'bar', data:DATA.wf.oos, itemStyle:{color:CLR.grey}},
    {name:'下一季 T3b', type:'line', data:DATA.wf.t3b, symbolSize:6, lineStyle:{color:CLR.blue,width:2,type:'dashed'}, itemStyle:{color:CLR.blue}}
  ]
}));

// 5 训练 vs 检验
echarts.init(document.getElementById('c5')).setOption(ax({
  tooltip:{trigger:'axis', valueFormatter:function(v){return (v==null?'n/a':v+'pp');}},
  legend:{data:['2025（训练）','2026（检验）'], top:4, textStyle:{fontSize:12}},
  xAxis:{type:'category', data:DATA.ho.state, axisLabel:{fontSize:12}},
  yAxis:{type:'value', name:'同日超额 (pp)', nameTextStyle:{fontSize:11}, splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {name:'2025（训练）', type:'bar', data:DATA.ho.train, itemStyle:{color:'#e8a5a0'}},
    {name:'2026（检验）', type:'bar', data:DATA.ho.test, itemStyle:{color:CLR.blue}}
  ]
}));

// 6 热力图
echarts.init(document.getElementById('c6')).setOption({
  tooltip:{formatter:function(p){return DATA.heat.states[p.value[1]]+' · '+DATA.heat.horizons[p.value[0]]+'日<br/>同日超额 '+p.value[2]+'pp';}},
  grid:{left:70, right:80, top:20, bottom:40},
  xAxis:{type:'category', data:DATA.heat.horizons.map(function(h){return h+'日';}), splitArea:{show:true}},
  yAxis:{type:'category', data:DATA.heat.states, splitArea:{show:true}},
  visualMap:{min:-3, max:3, calculable:true, orient:'vertical', right:8, top:'middle',
             inRange:{color:['#1e8449','#7dcea0','#f5f6f8','#e8a5a0','#c0392b']},
             textStyle:{fontSize:11}, itemHeight:150},
  series:[{type:'heatmap', data:DATA.heat.data,
           label:{show:true, fontSize:10, formatter:function(p){return p.value[2];}},
           emphasis:{itemStyle:{shadowBlur:8, shadowColor:'rgba(0,0,0,.25)'}}}]
});

// 7 动量分位
echarts.init(document.getElementById('c7')).setOption(ax({
  tooltip:{trigger:'axis', valueFormatter:function(v){return (v==null?'n/a':v+'pp');}},
  legend:{data:['T3b','同档其他标的','差值'], top:4, textStyle:{fontSize:12}},
  xAxis:{type:'category', data:DATA.mom.label, axisLabel:{fontSize:10}},
  yAxis:{type:'value', name:'同日超额 (pp)', nameTextStyle:{fontSize:11}, splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {name:'T3b', type:'bar', data:DATA.mom.t3b, itemStyle:{color:CLR.red}},
    {name:'同档其他标的', type:'bar', data:DATA.mom.other, itemStyle:{color:'#c9d6e3'}},
    {name:'差值', type:'line', data:DATA.mom.diff, symbolSize:6, lineStyle:{color:CLR.ink,width:2}, itemStyle:{color:CLR.ink}}
  ]
}));

// 8 分布直方图
echarts.init(document.getElementById('c8')).setOption(ax({
  tooltip:{trigger:'axis'}, grid:{left:52,right:40,top:26,bottom:44},
  xAxis:{type:'category', data:DATA.hist.map(function(b){return b.lo+'~'+b.hi;}),
         axisLabel:{fontSize:10, rotate:30}, name:'每只 ETF 平均同日超额区间 (pp)', nameLocation:'middle', nameGap:32, nameTextStyle:{fontSize:11}},
  yAxis:{type:'value', name:'ETF 数', nameTextStyle:{fontSize:11}, splitLine:{lineStyle:{color:CLR.grid}}},
  series:[{type:'bar', data:DATA.hist.map(function(b){return {value:b.n, itemStyle:{color:(b.lo<0?CLR.green:CLR.red)}};})}]
}));
</script>
</body>
</html>
"""

def fill(html):
    rep = {
        "__ECHARTS__": JS,
        "__DATA__": json.dumps(chart, ensure_ascii=False),
        "__N_SIG__": "{:,}".format(H["n_signals"]),
        "__N_ETF__": str(H["n_etfs"]),
        "__DATE_FROM__": H["date_from"], "__DATE_TO__": H["date_to"],
        "__AS_OF__": D["meta"]["as_of"],
        "__K1__": "+%spp" % n(DEC["excess_cs"]),
        "__K1S__": n(DEC["timing_share"], 1),
        "__K2__": "%spp" % n(EXQ["excess_cs"], 2, True),
        "__K2N__": str(EXQ["n"]), "__K2W__": n(EXQ["winrate"], 1),
        "__K3__": "%spp" % n(HO_T3B["test_excess"], 2, True),
        "__K3N__": str(HO_T3B["test_n"]), "__K3T__": n(HO_T3B["train_excess"]),
        "__K4__": "%spp" % n(WF["avg_oos_excess"], 2, True),
        "__K4N__": str(WF["n_periods"]), "__K4H__": n(WF["hit_rate"], 1),
        "__VERDICT__": verdict_html,
        "__CSDAYS__": n(DEC["cs_on_signal_days"]),
        "__CSEX__": n(DEC["excess_cs"]),
        "__ABS__": n(DEC["abs"]),
        "__STATEROWS__": state_rows(T20["rows"]),
        "__TOPQ__": CONC["top_quarter"], "__TOPQS__": n(CONC["top_quarter_share"], 1),
        "__TOP2S__": n(CONC["top2_quarter_share"], 1),
        "__EPS__": str(CONC["episodes"]), "__EPSLEN__": n(CONC["avg_episode_len"]),
        "__H2S__": n(sum(m["n"] for m in CONC["months"] if m["m"] in ("2025-06", "2025-07", "2025-08"))
                     / CONC["n"] * 100, 1),
        "__QROWS__": quarter_rows(), "__HROWS__": "".join(
            "<tr><td>%s</td><td>%d</td><td>%s%%</td><td>%s</td><td>%s</td><td>%s%%</td></tr>"
            % (x["h"], x["n"], n(x["occurrence"], 1),
               n(x["avg"]) if x["avg"] is not None else "—",
               span(x["excess_cs"]), n(x["winrate"], 1) if x["winrate"] is not None else "—")
            for x in CONC["halves"]),
        "__EXQN__": str(EXQ["n"]), "__EXQABS__": n(EXQ["avg"]),
        "__EXQEX__": n(EXQ["excess_cs"], 2, True), "__EXQW__": n(EXQ["winrate"], 1),
        "__BETF__": "%s ~ %spp" % (n(BOOT["etf"]["cs_ci"][0], 2, True), n(BOOT["etf"]["cs_ci"][1], 2, True)),
        "__BOOTROWS__": boot_rows(), "__WFROWS__": wf_rows(), "__FOREST__": forest_html(),
        "__HORANK__": str(HO["rank_test"].index("T3b") + 1),
        "__HOROWS__": ho_rows(), "__OOSHROWS__": oosh_rows(),
        "__MSROWS__": ms_rows(),
        "__NULLP95__": n(MS["null_max_p95"]), "__NULLP99__": n(MS["null_max_p99"]),
        "__MAXSTATE__": MS["obs_max_state"], "__MAXV__": n(MS["obs_max"]),
        "__NAIVEROWS__": naive_rows(),
        "__MOMDIFF__": n([b for b in MOM["buckets"] if b["diff"] is not None][-1]["diff"]),
        "__MOMROWS__": mom_rows(),
        "__BRN__": str(BR["n_etfs"]), "__BRPOS__": n(BR["positive_share"], 1),
        "__BRMED__": n(BR["etf_excess_median"], 2, True),
        "__BRP25__": n(BR["etf_excess_p25"], 2, True), "__BRP75__": n(BR["etf_excess_p75"], 2, True),
        "__BRMIN__": n(BR["etf_excess_min"], 2, True), "__BRMAX__": n(BR["etf_excess_max"], 2, True),
        "__CATROWS__": cat_rows(),
        "__FREQ__": n(EC["freq_pct"], 2), "__PERYEAR__": n(EC["per_etf_samples_per_year"], 2),
        "__DAYS__": n(EC["trading_days_per_year_in_state"], 1),
        "__CSEX2__": n(DEC["excess_cs"]), "__COSTR__": n(EC["cost_vs_excess_ratio"], 1),
        "__HO3N__": str(HO_T3B["test_n"]),
        "__WFQ2EX__": n(WF["timeline"][1]["train_t3b_excess"], 2, True).replace("-", "−"),
        "__WFQ2N__": str(WF["timeline"][1]["train_t3b_n"]),
        "__WFQ2S__": str(WF["timeline"][1]["n_states_ranked"]),
        "__WFQ2R__": str(WF["timeline"][1]["train_t3b_rank"]),
        "__BESTV__": n(HG["best_cell"]["excess_cs"]),
        "__BESTOOS__": n([x for x in OOSH if x["h"] == HG["best_cell"]["horizon"]][0]["test_excess"], 2, True),
    }
    for k, v in rep.items():
        html = html.replace(k, v)
    import re as _re
    html = _re.sub(r'(?<!图>)(<table>.*?</table>)', r'<div class="tw">\1</div>', html, flags=_re.S)
    return html


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(fill(HTML))
    print("written", OUT, os.path.getsize(OUT))
