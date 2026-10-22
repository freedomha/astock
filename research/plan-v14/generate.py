#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成季度定投计划报告 v14.1（硬门 + V1 连续评分）。

数据来源只有一个：`review.py --json` 的快照。报告与 skill 同源，避免两套口径。
证据数字来自两份研究报告的 JSON（T-State Validation / Gate Redesign）。

输出：reports/etf/allocation/20261022-季定投计划-v14.1.html
"""

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SKILL = os.path.join(ROOT, ".workbuddy/skills/etf-quarterly-plan-review")
OUT = os.path.join(ROOT, "reports/etf/allocation/20261022-季定投计划-v14.1.html")
ECHARTS = os.path.join(ROOT, "research/assets/echarts.min.js")

sys.path.insert(0, SKILL)
import v1_score                                                        # noqa: E402


def load_json(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def run_review():
    """跑一次 review.py，拿 --json 快照（用临时状态文件，不改生产状态）。"""
    tmp = os.path.join(tempfile.mkdtemp(), "plan_state.json")
    shutil.copy(os.path.join(SKILL, "plan_state.json"), tmp)
    r = subprocess.run([sys.executable, os.path.join(SKILL, "review.py"),
                        "--state", tmp, "--json"],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise SystemExit("review.py failed:\n" + r.stderr[-2000:])
    txt = r.stdout
    i = txt.rindex("\n{")
    return json.loads(txt[i:])


def n(x, nd=2, sign=False):
    if x is None:
        return "—"
    return (("%+.*f" if sign else "%.*f") % (nd, x)).replace("-", "\u2212")


def sp(x, nd=2):
    if x is None:
        return "—"
    c = "up" if x > 0 else ("down" if x < 0 else "")
    return '<span class="%s">%s</span>' % (c, n(x, nd, True))


def main():
    S = run_review()
    spec = v1_score.load_spec()
    GR = load_json(os.path.join(ROOT, "research/gate-redesign/gate_results.json"), {})
    SEG = load_json(os.path.join(HERE, "seg_ic.json"), {})
    TV = load_json(os.path.join(ROOT, "research/tstate-validation/tstate_validation.json"), {})
    JS = open(ECHARTS, encoding="utf-8").read()

    rows = S["rows"]
    codes = [r["code"] for r in rows]
    sc = S["scores"]
    thr = spec["threshold"]
    floor, band = thr["absolute_floor"], thr["relative_band"]

    # 证据数字
    gr_variants = {v["label"][:2]: v for v in GR.get("signal", {}).get("variants", [])}
    V1 = gr_variants.get("V1", {})
    V6 = gr_variants.get("V6", {})
    TH = GR.get("policy", {}).get("thresholds", {})
    dec = TH.get("decisions", [])
    tv_dec = TV.get("decomposition", {})
    tv_conc = TV.get("concentration", {})
    tv_exq = tv_conc.get("ex_top_quarter", {})

    # 图表数据
    srows = sorted(rows, key=lambda x: -(x["score"] or -1))
    chart = {
        "names": [r["name"].replace("ETF", "")[:6] for r in srows],
        "trend": [(sc[r["code"]] or {}).get("trend", 0) for r in srows],
        "mom": [(sc[r["code"]] or {}).get("momentum", 0) for r in srows],
        "risk": [(sc[r["code"]] or {}).get("risk", 0) for r in srows],
        "div": [(sc[r["code"]] or {}).get("div", 0) for r in srows],
        "total": [(sc[r["code"]] or {}).get("total", 0) for r in srows],
        "floor": [int(k) for k in sorted((TH.get("pass_rate") or {}).keys(), key=lambda z: int(z))],
        "pass": [TH.get("pass_rate", {}).get(k, 0) for k in
                 sorted((TH.get("pass_rate") or {}).keys(), key=lambda z: int(z))],
        "dec_dates": [d["d"] for d in dec],
        "dec_best": [d["best"] for d in dec],
        "dec_floor": [floor] * len(dec),
    }

    def score_rows():
        out = []
        for r in sorted(rows, key=lambda x: -(x["score"] or -1)):
            c = r["code"]
            s = sc.get(c) or {}
            tag = "✓ 可买" if r.get("pass_all") else ("硬门：" + "/".join(r["blocked"]) if r["blocked"] else "分数不足")
            cls = "g" if r.get("pass_all") else ("r" if r["blocked"] else "y")
            out.append("<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><span class='tag %s'>%s</span></td></tr>"
                       % (r["name"][:10], n(s.get("trend"), 1), n(s.get("momentum"), 1),
                          n(s.get("risk"), 1), n(s.get("div"), 1), n(r.get("drc50"), 3),
                          "<b>%s</b>" % n(s.get("total"), 1), n(r["gap"], 0, True), cls, tag))
        return "".join(out)

    def gate_rows():
        out = []
        for r in rows:
            pm = S["premium"].get(r["code"])
            prem = "%s%%%s" % (n(pm, 2, True), " !" if pm is not None and pm > 1.5 else "")
            gate = "—" if not r["blocked"] else "、".join(r["blocked"])
            out.append("<tr><td>%s</td><td>%s</td><td class='l'>%s</td><td>%s</td></tr>"
                       % (r["name"][:10], prem, gate, "通过" if not r["blocked"] else "否决"))
        return "".join(out)

    def thr_rows():
        out = []
        read = {50: "等于不设门", 55: "仅极端弱市挡住", 60: "只在最弱季度挡住",
                65: "约七分之一的日子无标的", 70: "近三成日子无标的", 75: "半数日子空仓"}
        for f, p_ in zip(chart["floor"], chart["pass"]):
            hl = ' style="background:#f2f7fd"' if f == floor else ""
            out.append("<tr%s><td><b>%d</b></td><td>%s%%</td><td class='l'>%s</td></tr>" % (hl, f, n(p_, 1), read.get(f, "")))
        return "".join(out)

    def seg_rows():
        """V1 各组件的分段 IC（全样本 / 剔除2025Q3 / 2026）。"""
        def cell(d):
            if not d:
                return '<span class="muted">—</span>'
            c = "up" if d["mean"] > 0 else ("down" if d["mean"] < 0 else "")
            return ('<span class="%s">%s</span><br><span class="muted" style="font-size:11px;white-space:nowrap">'
                    't %s → %s</span>' % (c, n(d["mean"], 3, True),
                                          n(d["tstat"], 2, True), n(d["nw_tstat"], 2, True)))
        rows_ = [("Trend", "30", "trend", "普通 t 唯一过 2；NW 修正后 1.31，剔除 2025Q3 后 &lt;1"),
                 ("Momentum<br>（钟形）", "30", "mom", "三段同号、幅度都小——最稳也最弱"),
                 ("Risk", "20", "risk", "IC≈0 甚至为负；它的作用是压波动，不是选券"),
                 ("Diversification", "20", "div", "依赖组合持仓，信号层无定义；政策层恒 20、横截面方差为零"),
                 ("<b>总分</b>", "100", "total", "三段全正；普通 t 也只 1.65，NW 后 1.07")]
        out = []
        for name, w, key, note in rows_:
            if key == "div":
                out.append("<tr><td><b>%s</b> <span class=\"muted\">(%s)</span></td>"
                           "<td colspan=\"3\" style=\"text-align:center\"><span class=\"muted\">不可评估</span></td>"
                           "<td class=\"l\">%s</td></tr>" % (name, w, note))
                continue
            out.append("<tr><td><b>%s</b> <span class=\"muted\">(%s)</span></td><td>%s</td><td>%s</td><td>%s</td>"
                       "<td class=\"l\">%s</td></tr>" % (name, w, cell(SEG["全样本"][key]),
                                                          cell(SEG["剔除2025Q3"][key]), cell(SEG["2026"][key]), note))
        return "".join(out)

    def dec_rows():
        out = []
        for d in dec:
            ok60 = "放行" if d["n60"] > 0 else '<span class="muted">不放行</span>'
            hl = ' style="background:#fdeeee"' if d["n60"] == 0 else ""
            out.append("<tr%s><td>%s</td><td>%s</td><td>%d</td><td>%d</td><td>%s</td></tr>"
                       % (hl, d["d"], n(d["best"], 1), d["n60"], d["n70"], ok60))
        return "".join(out)

    act = S.get("action") or {}
    buying = bool(act.get("code"))
    is_dec = bool(S.get("is_decision_day"))
    hero_title = ("本季买入：%s %s 份" % (act.get("name"), "{:,}".format(act.get("shares") or 0))) if buying \
        else ("本季不买：留现金" if is_dec else "当前观察：若今日为决策日 → 不买")
    hero_sub = (("分数 %s ≥ %d，缺口 %s 元" % (n(act.get("score"), 1), floor, "{:,.0f}".format(act.get("gap") or 0)))
                if buying else S.get("selection", ""))

    rcl = S["rc50"]
    rcabs = S["rc50_abs"]
    style2, style1 = S["style2"], S["style1"]
    style_over = max(style2, style1) > spec["hard_gates"]["style_group_max_pct"]

    # ── HTML
    HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>季度定投计划 v14.1 · 硬门 + 连续评分</title>
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
  .chart{width:100%;height:340px}
  .note{background:#fff9e6;border-left:3px solid #f0c040;padding:10px 14px;border-radius:4px;font-size:13px;color:#7a6a30;margin:12px 0}
  .note.warn{background:#fdeeee;border-left-color:#e74c3c;color:#8b3a3a}
  .note.ok{background:#eafaf1;border-left-color:#27ae60;color:#1e6b45}
  .note.blue{background:#eaf3fb;border-left-color:#2c5c8f;color:#1f4e79}
  .legend{font-size:12px;color:#7f8c8d;margin-top:6px}
  .kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:14px 0 4px}
  .kpibox{background:rgba(255,255,255,.10);border-radius:9px;padding:14px 12px;text-align:center;border:1px solid rgba(255,255,255,.14)}
  .kpibox .n{font-size:21px;font-weight:700;letter-spacing:-.5px}
  .kpibox .l{font-size:11.5px;color:#b9cddf;margin-top:4px;line-height:1.4}
  ul,ol{margin:8px 0 8px 22px;font-size:14px;color:#4a5a6a}
  li{margin-bottom:6px}
  .muted{color:#95a5a6;font-size:12px}
  .tag{display:inline-block;padding:1px 8px;border-radius:4px;font-size:11px;font-weight:600;background:#e8f4ff;color:#2c5c8f}
  .tag.g{background:#eafaf1;color:#1e8449}.tag.y{background:#fff4e6;color:#c77c1f}.tag.r{background:#fdeeee;color:#c0392b}
  code{background:#eef2f5;padding:1px 5px;border-radius:3px;font-size:12px}
  .foot{color:#95a5a6;font-size:12px;text-align:center;padding:6px 0 24px}
  .nw{white-space:nowrap}
  .flow{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:14px 0;font-size:12.5px;text-align:center}
  .flow div{background:#f8fafc;border-radius:8px;padding:10px 8px;border:1px solid #eef1f4}
  .flow b{display:block;font-size:12px;color:#1f3a5f;margin-bottom:3px}
  .flow .g{background:#fdeeee;border-color:#f6d5d1}
  .flow .s{background:#eaf3fb;border-color:#d3e3f2}
  .flow .t{background:#eafaf1;border-color:#cdeada}
</style></head><body><div class="wrap">

<h1>季度定投计划 <span class="tag">v14.1</span> <span style="color:#95a5a6;font-weight:400">/</span> 硬门 + 连续评分</h1>
<div class="sub">每季新增 3,000 元 · 快照 __DATE__ __TIME__ · K 线 __BAR__ · 规格 v__SPECV__（预注册，变更分级见 §十一） · 距季末 __DTOQ__ 个交易日 · 全部数字由 review.py 同源产出 · 非投资建议</div>

<div class="card hero">
  <h2>__HERO__</h2>
  <p style="margin-bottom:12px">__HEROSUB__。架构已从「T0-T8 状态门」换成「<b>硬门 + 连续评分</b>」：硬门只否决不可接受的风险，评分只负责排序。<b>「不买」有两个来源：硬门可以独立否决（不可被高分抵消），评分层里则只有 Eligibility Floor 能挡；Candidate Band 只收窄候选集、永远不会单独造成「不买」。</b>
    今天的不买来自前者——4 只被硬门否决，不是分数不够。</p>
  <div class="kpi">
    <div class="kpibox"><div class="n">__TOTAL__</div><div class="l">总资产<br>现金 __CASHPCT__%</div></div>
    <div class="kpibox"><div class="n">__SMAX__</div><div class="l">硬门通过者最高分<br>Eligibility Floor __FLOOR__</div></div>
    <div class="kpibox"><div class="n">__RC__</div><div class="l">RC50 占比<br>绝对 __RCABS__%</div></div>
    <div class="kpibox"><div class="n">__STYLE2__ / __STYLE1__</div><div class="l">风格组风险 %<br>2 年 / 1 年</div></div>
  </div>
</div>

<div class="card">
  <h2>一、架构：三个职责分离</h2>
  <div class="flow">
    <div class="g"><b>HARD GATES</b>溢价 ≤1.5%<br>回撤 ≥15%（DD ≤ −15%）暂停<br>风格组 ≤60%（组内）<br>锁定不买<br>数据质量作废</div>
    <div class="s"><b>SOFT SCORE</b>Trend 30<br>Momentum 30（钟形）<br>Risk 20<br>Diversification 20</div>
    <div class="t"><b>ELIGIBILITY</b>Floor = __FLOOR__<br>Band = max − __BAND__<br>两者同时满足<br>否则 → 现金</div>
    <div><b>EXECUTE</b>按分排序<br>→ 缺口<br>→ 单笔 ≥2,000<br>→ 买入 ≤3,000</div>
  </div>
  <table>
    <thead><tr><th>层</th><th>回答的问题</th><th>典型规则</th><th>能否被「分数高」抵消</th></tr></thead>
    <tbody>
      <tr><td><b>硬门</b></td><td class="l">这个风险我是否根本不该承担？</td><td class="l">溢价（规则 0）、风格组（4/5）、锁定（L）、数据质量（6）、回撤（D）<br><span class="muted">注：单笔 &lt;2,000 不是风险门，是执行规则（规则 2），在最后一格</span></td><td>不能</td></tr>
      <tr><td><b>软分</b></td><td class="l">在可买的里面，哪个现在更值得优先？</td><td class="l">趋势 / 动量 / 波动 / 分散</td><td>能</td></tr>
      <tr><td><b>阈值</b></td><td class="l">今天到底有没有值得买的？</td><td class="l"><b>Eligibility Floor</b> = __FLOOR__（绝对资格线）<br><b>Candidate Band</b> = max − __BAND__（相对候选带）</td><td>—</td></tr>
    </tbody>
  </table>
  <div class="note blue">这三个问题的答案性质不同，混在一张表里就会互相抵消。
    最典型的是 <b>Risk 组件</b>：横截面 IC 是 __ICRISK__（负），单看预测收益像是有害的；但它把 top20 的收益标准差从 __SDT__ 压到 __SD1__、5% 尾部从 __CVT__ 改善到 __CV1__。
    <b>用 IC 评价保险，会得出「保险有害」的结论——但保费必须写明：</b>代价是 top20 的同日横截面超额从 __EXC_NORISK__pp 降到 __EXC_V1__pp（−__COST__pp/20 日）。
    口径：__POOL__ 个观测、319 只 ETF，取总分前 20%（3,322 条）；标准差与尾部单位均为「20 日收益 %」，尾部＝最差 5% 的均值。</div>
</div>

<div class="card">
  <h2>二、为什么废除状态门：三条证据 ＋ 一条限定</h2>
  <ol>
    <li><b>+4.33pp 里 64% 是时间效应。</b>完整链条：T3b 日原始 20 日收益 <b>5.62%</b>，池化基准 1.29%，差 <b>4.33pp</b>；
      这 4.33pp 中，同日全市场平均（<b>4.05%</b>）比池化基准高出的 <b>2.76pp（64%）</b>来自「那些日子什么都在涨」，
      T3b 相对同日全市场只再多 <b>__CSEX__pp（36%）</b>，这才是选券效应。<span class="muted">（不要用 4.05/4.33=94% 解读——分母不是超额，是绝对收益。）</span></li>
    <li><b>一个季度撑起全部结论。</b>2025Q3 一季贡献 <b>__TOPQS__%</b> 的观测；剔除后横截面超额 <b>__EXQ__pp</b>、胜率 __EXQW__%。2026 样本外 <b>__OOS26__pp</b>。</li>
    <li><b>在 5 只标的的菜单上，它几乎不投。</b>政策层回测的 5 个季度里，状态门只放行 <b>__M0T__ 次</b>买入。
      <b>这是「上限」不是「预期」</b>：该回测没有溢价数据，等于假设溢价门永远通过；真实历史上 QDII 常年溢价，实际能买的次数只会更少。
      它不只是在防止错误投资，也在阻止资产配置发生——<b>「只稀释不卖出」的前提是「有钱投得出去」。</b></li>
  </ol>
  <div class="note warn" style="margin-bottom:0">同日置换检验 p&lt;0.002 只说明：<b>全样本存在统计可识别的横截面关联，但稳定性和样本外表现不足以支持其作为交易硬门。</b>
    所以正确的处理不是删掉它，而是<b>降级为描述性特征</b>——报告里仍然显示 T 码，但它不再决定买卖。</div>
</div>

<div class="card">
  <h2>三、今日评分</h2>
  <div class="tw"><table>
    <thead><tr><th>标的</th><th>Trend</th><th>Mom</th><th>Risk</th><th>Div</th><th>ΔRC50</th><th>合计</th><th>缺口</th><th>判定</th></tr></thead>
    <tbody>__SCOREROWS__</tbody>
  </table></div>
  <div id="c1" class="chart"></div>
  <div class="legend">堆叠＝四个分项之和（0–100）。红色虚线为 <b>Eligibility Floor __FLOOR__</b>。</div>
  <div class="note">__DIVNOTE__</div>
  <div class="legend">注：合计基于未取整的分项相加，与表内四列相加可能差 0.1（如红利 6.5+16.6+17.8+20.0＝60.9，合计 60.8）。</div>
</div>

<div class="card">
  <h2>四、硬门判定</h2>
  <div class="tw"><table>
    <thead><tr><th>标的</th><th>静态溢价</th><th>否决原因</th><th>结果</th></tr></thead>
    <tbody>__GATEROWS__</tbody>
  </table></div>
  <p><b>「锁定不买」的定义：</b>上证50 在 <code>plan_state.json</code> 中 <code>locked=true</code>，属于
    <b>菜单政策</b>而非风险门——它不参与评分排序，也不占用候选名额。触发条件写死为「该标的 locked」，与缺口正负无关；
    缺口 −4,508 只是结果，不是原因。任何要解除锁定的动作都必须改配置文件，不能由评分或规则自行放开。</p>
  <p><b>溢价是本季最主要的否决来源。</b>QDII 场内价 = 净值 + 溢价，套利通道关闭时溢价可持续也可突然收敛；
    按 +13.7% 的溢价买入，即使底层不动，收敛到 2% 也意味着 −10% 以上的损失。这条是 B 类风控政策，<b>不可被高分抵消</b>。</p>
  <div class="note warn" style="margin-bottom:0"><b>已知盲区：溢价门无法回测。</b>接口不提供历史 NAV / IOPV 序列，只有当日静态溢价，
    因此研究报告里的所有历史模拟都等于「假设溢价门通过」。历史结论不能证明「当时真的买得到」。</div>
</div>

<div class="card" style="border:2px solid #c0392b">
  <h2 style="color:#c0392b">五、本季结论</h2>
  <p style="font-size:15px"><b>__HEADLINE__</b></p>
  <p><b>原因是硬门，不是分数。</b>5 只里 4 只被硬门否决：纳指（溢价 __PREM_NDX__）、标普（溢价 __PREM_SPX__）、
    红利低波（风格组 __STYLE2__%）、上证50（锁定不买）。唯一通过硬门的是黄金，<b>41.4 分 &lt; Eligibility Floor __FLOOR__</b>。
    可投菜单实际只剩 1 只，这不是「评分不够灵活」，是<b>可选标的被硬门压缩到近乎没有</b>。</p>
  <div class="note warn"><b>时点说明：距季末 __DTOQ__ 个交易日，这是季中观察，不是正式决策。</b>
    正式决策在 2026-12-31 收盘后做，届时溢价可能已收敛。
    （参考：2026-09-30 若只看全池分数，最高 __DEC0930__ 会触发买入。但<b>当时没有留下决策记录</b>——
    <code>review_history.json</code> 只有 2026-10-21 起的两条，v13 报告里唯一一次逐标的溢价实测是 <b>2026-10-21</b>（四只纳指 10%~16%），不是 09-30。
    所以这一格<b>缺的是记录，不是数据</b>：即使现在回补当天的静态溢价，也只能得到「当时的价格与净值」，回补不了「当时是否可申购」。
    本报告不据此声称「错过了一次买入」。）</div>
  <div class="note"><b>与旧版的差别不在本季结论，在「以后怎么判」。</b>旧版要等一个可能永不出现的 T 码组合，
    新版每季重算分数——但这句话有个前提：<b>硬门必须先放行</b>。本季恰恰卡在硬门，所以「分够了就买」在这里并不成立。</div>
</div>

<div class="card">
  <h2>六、组合风险</h2>
  <div class="kpi" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpibox" style="background:#f8fafc;border:1px solid #eef1f4"><div class="n" style="color:#1f3a5f">__SD__%</div><div class="l" style="color:#7f8c8d">σp（组合波动）</div></div>
    <div class="kpibox" style="background:#f8fafc;border:1px solid #eef1f4"><div class="n" style="color:#1f3a5f">__RC__%</div><div class="l" style="color:#7f8c8d">上证50 风险占比</div></div>
    <div class="kpibox" style="background:#f8fafc;border:1px solid #eef1f4"><div class="n" style="color:#1f3a5f">__RCABS__%</div><div class="l" style="color:#7f8c8d">绝对风险贡献</div></div>
    <div class="kpibox" style="background:#f8fafc;border:1px solid #eef1f4"><div class="n" style="color:#1f3a5f">__DD__%</div><div class="l" style="color:#7f8c8d">回撤（取较深口径）<br>__DDBOX__</div></div>
  </div>
  <p>风格组（上证50＋红利低波）风险：<b>2 年 __STYLE2__% ／ 1 年 __STYLE1__%</b>。__STYLENOTE__</p>
  <div class="note">RC50 占比与绝对贡献要一起看：单独看占比会被「加高波动资产」机械稀释。
    251 日滚动窗口里风格组最低仍 62.1%、从未低于 60%——所以规则 4/5 的约束与窗口选择无关。</div>
  <div class="note warn"><b>回撤口径：</b>总资产口径（__DDT__%，峰值 __PEAK__ 含历次注资）会被每季 3,000 元的现金注入机械抬高，
    <b>系统性低估回撤</b>。因此回撤门取「总资产」与「持仓市值」（__DDHTXT__，峰值 __PEAKH__）中更深的那个。
    持仓口径对买入同样会抬高峰值，所以它也不是严格的资金流中性口径；真正干净的做法是用 v12 的双口径 NAV（按成交流水回放），当前未接入。__DDHNOTE__</div>
</div>

<div class="card">
  <h2>七、阈值的证据：只验证行为，不验证收益</h2>
  <p>下图是「五只标的中最高分（<b>未扣硬门</b>）」在过去 __THN__ 个交易日的通过率。<b>在评分层里，只有 Eligibility Floor 60 能产生「不买」</b>——但硬门可以先一步独立否决，今天的 4/5 就是这么被挡的；
    Candidate Band（max − __BAND__）两层都挡不住买入——当季最高分天然满足它，它只把候选集从 4 只收窄到约 2 只。
    注意两者的分母不同：本段是「全池最高分」，第三节表格是「硬门通过者最高分」，后者才决定本季买不买。</p>
  <div class="note warn"><b>这些「通过率」是上限，不是投出率。</b>历史上没有溢价序列，无法复现溢价门；
    按今天的实测，全池最高分 70.9 过 Floor，但<b>硬门之后只剩 41.4</b>，结果仍是现金。
    因此下文「5 个决策日里 4 次会买」只能读作<b>「分数这一关会放行几次」</b>，不能读作「V1 每年能投出去几次」。</div>
  <div id="c2" class="chart"></div>
  <div class="tw"><table>
    <thead><tr><th>Eligibility Floor</th><th>有候选的交易日占比</th><th>读法</th></tr></thead>
    <tbody>__THRROWS__</tbody>
  </table></div>
  <h3>五个历史决策日：最弱的季度长什么样</h3>
  <div id="c3" class="chart" style="height:260px"></div>
  <div class="tw"><table>
    <thead><tr><th>季度末</th><th>全池最高分<br><span style="font-weight:400">未扣硬门</span></th><th>≥60 的候选数</th><th>≥70 的候选数</th><th>分数关放行？<br><span style="font-weight:400">不代表最终会买</span></th></tr></thead>
    <tbody>__DECROWS__</tbody>
  </table></div>
  <div class="note ok" style="margin-bottom:0">下一步要看的是：在 <b>≥4 个新的季度决策点</b>之前，不得用收益对 V1 做「优于/劣于」判断。
    计数起点是 <b>2026Q4</b>（本季为第一次），随后 2027Q1／Q2／Q3，<b>最早 2027Q3 末</b>才能凑满 4 个。
    <span class="muted">注意不要和 V1-SPEC §6 的「8 个决策点」混淆：8 个是<b>改权重/调阈值</b>的门槛，4 个是<b>允许用收益评判 V1</b> 的门槛，两者用途不同。</span>
    复评只看行为指标：符号一致性、<b>扣硬门后的真实投出率</b>、现金比、RC50 方向、纪律偏差。<b>60 与 __BAND__ 是预注册候选值，没有收益验证。</b></div>
</div>

<div class="card">
  <h2>八、执行规则</h2>
  <table>
    <thead><tr><th>#</th><th>规则</th><th>证据等级</th></tr></thead>
    <tbody>
      <tr><td>0</td><td class="l"><b>溢价门</b>：静态溢价 &gt; 1.5% 一律不买；折价不构成门槛</td><td>B 风控政策</td></tr>
      <tr><td>1</td><td class="l"><b>金额</b>：每季 3,000，单笔 ≤3,000，缺口按投入后总资产重算，不跨季结转</td><td>B</td></tr>
      <tr><td>2</td><td class="l"><b>最小额</b>：单笔 &lt;2,000 跳过（5 元佣金 = 0.25%）</td><td>B</td></tr>
      <tr><td>3</td><td class="l"><b>Eligibility Floor</b> = __FLOOR__（绝对资格线）＋ <b>Candidate Band</b> = max − __BAND__（相对候选带）。
        两个条件的 <b>max 一律指「硬门通过者中的最高分」</b>，不是全池最高分（今天两者差 __GAPMAX__ 分）。<b>评分层里只有 Floor 能产生「不买」；硬门可独立否决；Band 只收窄候选集</b></td><td>C 待验证（行为已验证）</td></tr>
      <tr><td>4</td><td class="l"><b>风格组</b>：60% 上限约束组内标的——<b>红利低波</b>与<b>上证50</b>都算。上证50 当前 <code>locked=true</code>（规则 L），锁定优先于本规则；若将来解锁，它同样受 60% 限制，不能因为「核心指数」豁免</td><td>B</td></tr>
      <tr><td>5</td><td class="l"><b>双窗口</b>：2 年与 1 年均低于 60% 才放行<b>组内标的（红利低波 ＋ 上证50）</b></td><td>B</td></tr>
      <tr><td>6</td><td class="l"><b>数据质量</b>：报价缺失 / K 线不足 60 根 / 接口异常 → <b>本次评估作废</b>（不静默降级、不部分计算）。脚本遇到这类情况直接退出码 1</td><td>B</td></tr>
      <tr><td>L</td><td class="l"><b>锁定（菜单政策，非风险门）</b>：<code>plan_state.holdings[].locked</code> 为真的标的不参与排序、不占候选名额、不可由评分放开。当前只有上证50</td><td>B</td></tr>
      <tr><td>D</td><td class="l"><b>回撤</b>：回撤幅度 <b>≥15%（Drawdown ≤ −15%）</b> → 暂停全部买入；收窄至 <b>&gt; −10%</b> 且复核通过后恢复。
        回撤取「总资产」与「持仓市值」两口径中<b>更深</b>的一个（见第六节）</td><td>B</td></tr>
    </tbody>
  </table>
  <h3>资金分配顺序（规则 1–3 的补充）</h3>
  <ol>
    <li>取候选集，按 Score 降序（分差 &lt;1 时比缺口）；</li>
    <li><b>按顺序逐个尝试</b>：对每只算 <code>min(3,000, 缺口)</code> 并以 100 份取整，若金额 ≥2,000 即下单；</li>
    <li>若某只不足 2,000，<b>顺延到下一只</b>（不是直接放弃本季）；</li>
    <li><b>不做拆分</b>——每季至多一笔，不允许把 3,000 拆成两只各 1,500。</li>
  </ol>
  <p class="muted">下单时点：季末最后一个交易日收盘后计算，下一交易日 14:45 之后下单（唯一一笔异常滑点 +76.8bps 来自盘中追价）。</p>
</div>

<div class="card">
  <h2>九、与 v13 的差异</h2>
  <div class="tw"><table>
    <thead><tr><th>项目</th><th>v13（状态门）</th><th>v14.1（V1）</th></tr></thead>
    <tbody>
      <tr><td>买不买由什么决定</td><td class="l">T 码 ∈ {T3b,T4}（分散腿放宽到 T1+）</td><td class="l">Eligibility Floor __FLOOR__ ＋ Candidate Band max − __BAND__</td></tr>
      <tr><td>T 码的角色</td><td class="l">硬门（有否决权）</td><td class="l">描述性特征（只展示）</td></tr>
      <tr><td>硬门</td><td class="l">溢价 / 回撤 / 风格组</td><td class="l"><b>硬门（扩充）</b>：溢价 / 风格组不变；回撤改为「总资产 / 持仓市值」双口径取更深者；<b>新增</b>锁定（菜单政策）与数据质量作废</td></tr>
      <tr><td>候选排序</td><td class="l">缺口最大者</td><td class="l">分数优先，分差 &lt;1 再比缺口</td></tr>
      <tr><td>「恢复」概念</td><td class="l">A 溢价收敛 / B 黄金转 T1</td><td class="l">无——每季独立按分数判定</td></tr>
      <tr><td>证据基础</td><td class="l">T3b +4.33pp（池化基准、样本内）</td><td class="l"><b>V1 自身</b>：Trend IC __ICTREND__、总分 IC __ICTOTAL__；Risk 把 top20 标准差 __SDT__→__SD1__、尾部 __CVT__→__CV1__（代价 __COST__pp）；
        Floor 60 在 300 日样本里 __PASS60__% 有候选、在最弱季 2026Q1 挡住</td></tr>
    </tbody>
  </table></div>
  <div class="note warn"><b>本版（V1）的证据不是 T3b 的 +1.57pp。</b>那是<b>被本版降级的方案</b>的证据，且它自身在剔除 2025Q3 后为 −0.52pp、2026 为 −1.44pp。
    用一份「三段里只有一段为正」的证据给新方案背书，逻辑上不成立。</div>

  <h3>同一套分段检验，对 V1 自己也做一遍</h3>
  <p>要避免双重标准，V1 必须接受和 T3b 完全相同的切法：全样本 → 剔除 2025Q3 → 2026 样本外。
    下表是各分项与总分的分日秩相关 IC（只用当日 ≥20 只的稠密横截面，括号内为 IC 均值的 t 值）。
    三段的采样日分别是 __SDAY0__ / __SDAY1__ / __SDAY2__ 个，但能凑出 ≥20 只横截面的只有 __ICN0__ / __ICN1__ / __ICN2__ 个——这就是 IC 的样本量。</p>
</p>
  <div class="tw"><table>
    <thead><tr><th>分项（权重）</th><th>全样本<br><span style="font-weight:400">__ICN0__ 个 IC 日<br>t → NW t</span></th>
      <th>剔除 2025Q3<br><span style="font-weight:400">__ICN1__ 个 IC 日<br>t → NW t</span></th>
      <th>2026 样本外<br><span style="font-weight:400">__ICN2__ 个 IC 日<br>t → NW t</span></th><th>读法</th></tr></thead>
    <tbody>__SEGROWS__</tbody>
  </table></div>
  <div class="note warn"><b>t 值必须看 NW 那一列。</b>IC 日平均间隔 <b>__GAP0__ 个交易日</b>，而前瞻窗口是 <b>20 日</b>——相邻 IC 的收益窗口重叠约 4 倍，普通 t 明显偏大。
    表中同时给出普通 t 与 Newey-West t（滞后 __NWLAG__ 期）。<b>全样本 Trend 的普通 t=2.04 是唯一过 2 的数字，NW 修正后只剩 __ICNWT2__；其余全部低于 1.35。</b>
    所以「V1 未经验证」不是措辞保守，是数字本身就这样——按普通 t 不该称显著，按 NW t 更不该。</div>
  <div class="note"><b>结论必须照实写：</b>符号确实三段不翻（trend / momentum / 总分全为正），<b>但幅度和显著性都由 2025Q3 支撑</b>——
    总分 IC 从全样本 __ICTOTAL_S__（普通 t=__ICTOTT__、<b>NW t=__ICNWT__</b>）掉到剔除后 __ICTTOTEX__（NW t=__ICNWEX__）、2026 __ICTTOT26__（NW t=__ICNW26__）。
    这和 T3b 不是两种证据，是<b>同一段行情下的同一种证据，只是方向稳定一点</b>。所以本报告不再主张「V1 已被验证」，只主张「V1 没有翻符号，因而值得按预注册规则跑下去」。</div>
  <div class="note warn"><b>两个分项没有独立证据，必须点名：</b>
    <b>Momentum（权重 30）</b>的全样本 IC 只有 __ICMOM__（t=__ICMOMT__），虽然三段同号但幅度微弱；
    <b>Diversification（权重 20）</b>连 IC 都算不出来——它依赖组合持仓，信号层（319 只 ETF 横截面）无法定义；在政策层它又恒等于 20（饱和），<b>横截面方差为零</b>。
    也就是说 <b>50 分权重里有 20 分完全没有横截面证据</b>，这是 V1 目前最薄弱的地方，见第十节。</div>
  <div class="note blue" style="margin-bottom:0">旧报告仍保留在 <code>reports/etf/allocation/20261021-季定投计划.html</code>，作为历史决策存档；
    其中「规则 3 状态门」已被本版取代，引用时请注意。</div>
</div>

<div class="card">
  <h2>十、局限与失效条件</h2>
  <ul>
    <li><b>IC 的适用范围被外推过。</b>第九节所有 IC 都来自 <b>319 只 ETF 的横截面</b>（每日稠密日 ≥20 只），
      而本计划的菜单只有 <b>5 只，能评分的最多 4 只</b>。「在 319 只里排前 20%」和「在 4 只里排第一」不是同一个问题——
      横截面 IC 为正，<b>不保证 4 只里挑出来的那只优于另外三只</b>。政策层 5 个决策点就是这个外推的唯一实测，而它不可判定。
      这是 V1 从「研究结论」到「下单动作」之间最大的一道缝。</li>
    <li><b>权重未经证据校准。</b>30/30/20/20 是<b>预注册</b>值，不是拟合结果：Momentum 的全样本 IC 只有 +__ICMOM__（NW t=__ICMOMNW__），
      却与 Trend 同权 30；Div 的 IC 根本算不出来，却占 20。这就是为什么现在调权重更危险——<b>没有一段独立验证能告诉你该往哪调</b>。</li>
    <li><b>Div 分项有设计缺陷（未修）。</b>它只看 RC50 的改善，不看风格组：红利低波买入后 RC50 下降（拿满 20 分），
      却同时推高本来就 78.6% 的风格组风险——<b>分散分项在奖励一个加剧集中度的动作</b>。
      不立即改的原因：改 Div 会改变合格集，属模型变更（V1-SPEC 第 6 节）。
      候选修法：① Div 输入改为 max(−ΔRC50, −Δ风格组)；② 风格组成员 Div 封顶（如 ≤5 分）。二者都需要样本外验证。</li>
    <li><b>Div 在当前现金比例下饱和。</b>任意非上证50 的 ΔRC50 都在 −1.7~−2.3pp，远超规格 −0.15，所以 Div 恒为 20，
      排序不受影响但 <b>Floor __FLOOR__ 实际等价于核心分 ≥40</b>。第七节的 300 日校准样本同样是「Div 饱和」状态，口径一致；
      但现金降到 10% 以下后 Div 会重新有区分度，Floor 的等效核心分会随之上移，届时必须重新校准。</li>
    <li><b>回撤口径不干净。</b>总资产口径会被注资抬高、低估回撤；持仓口径会被买入抬高。当前取两者较深者，仍非严格的资金流中性口径。
      正解是 v12 的双口径 NAV（按成交流水回放），尚未接入。</li>
    <li><b>政策层数字的口径。</b>「RC50 __RC50A__% vs __RC50B__%」出自 Gate-Redesign 政策层回测：
      初始 48,472 元、5 次季度决策、累计投入 63,472 元、2025-09~2026-10、250 日协方差窗口、<b>未计溢价门</b>；
      与今天组合的 RC50 __RC__% 不是同一时点、也不是同一资金规模，不能直接比较。</li>
    <li><b>政策层样本极短。</b>5 个季度决策、期末收益差 647 元——不可判定。只有 RC50 的方向差异有结构性含义。</li>
    <li><b>溢价门不可回测，且是「静态溢价」。</b>分母是最近一期已公布 NAV，QDII 净值滞后 1~3 个交易日，不是同日 IOPV；
      美股隔夜波动会让它偏离真实溢价 ±1~2%。在 1.5% 阈值附近（例如 1.2% 或 1.9%）可能误判，需人工复核。</li>
    <li><b>QDII 用场内价算协方差</b>（已用指数代理做 lag1 修正），仍含跟踪误差与汇率缺口。</li>
    <li><b>投出率不可预期。</b>第七节的「5 季 4 次」是分数关的上限，未扣硬门。本季即反例，硬门后仍为现金。</li>
    <li><b>失效条件 ①（Floor 过严）</b>：连续 4 个季度「有候选但分数都不足 Eligibility Floor」→ 按 V1-SPEC 第 6 节走变更，不当场下调。</li>
    <li><b>失效条件 ②（硬门长期否决）</b>：连续 4 个季度「硬门把候选压到 ≤1 只」且现金占比持续上升（>45%），
      说明问题不在评分而在菜单/门槛结构——此时应复核 60% 风格组上限与 QDII 溢价容忍度，<b>而不是继续调评分</b>。
      本季现金 __CASHPCT__%，注入后 __CASHNEW__%，距离该阈值尚有余量但方向不利。
      <b>注：两个失效条件在不买路径上会同时触发</b>——持续不买时现金占比依次 35.7% → 39.4% → 42.6% → 45.3%，
      第 4 个季度正好越过 45%，与「连续 4 季候选 ≤1 只」同期发生。这是设计上的冗余，不是两个独立警报；
      实际读法是「4 个季度不买就重检门槛」，不是「先看哪个先响」。</li>
  </ul>
</div>

<div class="card">
  <h2>十一、变更记录</h2>
  <table>
    <thead><tr><th>版本</th><th>日期</th><th>变更</th></tr></thead>
    <tbody>
      <tr><td>v14.1</td><td class="nw">2026-10-22</td><td class="l"><b>证据与口径</b>（不改判定）：
        证据基础改为 V1 自身并补三段分段 IC；投出率标注为「未扣硬门的上限」；结论改为「硬门否决 4/5」；复评节点 2027Q4 → 2027Q3；Div / 溢价 / 回撤口径入局限。<br>
        <b>澄清性修订</b>（不改变任何历史判定，只是把已执行的行为写进条文）：
        ① Candidate Band 的 max 明确为「硬门通过者最高」；② 锁定（规则 L）本来就是 <code>plan_state</code> 里的既有事实、v14 代码也一直在执行；
        ③ 资金分配顺序（逐个尝试、不足顺延、不拆分）——政策层模拟的 5 个决策点里无一次触发顺延。<br>
        <b>行为变更</b>（会让结果更严，需说明为何不走 §6）：
        ④ 回撤改双口径取更深者——<b>总资产口径历史上从未触发 15% 门槛；持仓口径没有历史序列（本次才建基线），无法回溯</b>。
        能保证的只有一件：取两者中更深的那个，<b>只会更早暂停、不会放宽</b>。<br>
        ⑤ 数据质量作废（规则 6）——历史上从未触发（报价与 K 线一直完整），属把既有报错行为写成条文。<br>
        <span class="muted">上述 ④⑤ 都不改变权重、评分公式或阈值数值，且方向只有「更早不出结论」，因此按 V1-SPEC §6b 的判据（能否让「以前不买、现在买」）不需走 §6 的 8 个决策点流程；
        它们改变的是「什么情况下不出结论」，而不是「出什么结论」。若日后要放宽（例如把回撤门改回单口径），则必须走 §6。</span></td></tr>
      <tr><td>v14</td><td class="nw">2026-10-22</td><td class="l">架构切换：T0-T8 状态门 → 硬门 + V1 连续评分（30/30/20/20）；Eligibility Floor 60 ＋ Candidate Band 5；T 码降为描述性特征</td></tr>
      <tr><td>v13</td><td class="nw">2026-10-21</td><td class="l">规则分级 A/B/C；删自相矛盾表述；规模补口径</td></tr>
      <tr><td>v12</td><td class="nw">2026-10-21</td><td class="l">新增双口径 NAV（执行 vs 影子）</td></tr>
    </tbody>
  </table>
</div>

<div class="foot">数据：westock-data（报价 / etf detail / 500 日 K 线）+ review.py --json 快照 ｜ 规格：.workbuddy/skills/etf-quarterly-plan-review/v1_spec.json
 ｜ 证据：reports/research/{T-State-Validation,Gate-Redesign}-20261022.html ｜ 非投资建议</div>
</div>

<script>
var DATA = __DATA__;
var CLR = {red:'#c0392b', green:'#27ae60', blue:'#2c5c8f', grey:'#95a5a6', ink:'#2c3e50', grid:'#eef1f4'};
var base = {textStyle:{fontFamily:'-apple-system,PingFang SC,sans-serif'}, tooltip:{trigger:'axis'},
            grid:{left:52,right:40,top:36,bottom:46}};
function ax(o){ return Object.assign({}, base, o); }

echarts.init(document.getElementById('c1')).setOption(ax({
  legend:{data:['Trend','Momentum','Risk','Diversification'], top:4, textStyle:{fontSize:11}},
  xAxis:{type:'category', data:DATA.names, axisLabel:{fontSize:11}},
  yAxis:{type:'value', max:100, name:'分', splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {name:'Trend', type:'bar', stack:'s', data:DATA.trend, itemStyle:{color:'#2c5c8f'}},
    {name:'Momentum', type:'bar', stack:'s', data:DATA.mom, itemStyle:{color:'#e67e22'}},
    {name:'Risk', type:'bar', stack:'s', data:DATA.risk, itemStyle:{color:'#27ae60'}},
    {name:'Diversification', type:'bar', stack:'s', data:DATA.div, itemStyle:{color:'#95a5a6'},
     markLine:{silent:true, symbol:'none', lineStyle:{color:'#c0392b', type:'dashed'},
               data:[{yAxis:__FLOOR__, label:{formatter:'下限 __FLOOR__', fontSize:11,
                                             position:'insideStartTop', color:'#c0392b'}}]}}
  ]
}));

echarts.init(document.getElementById('c2')).setOption(ax({
  xAxis:{type:'category', data:DATA.floor, axisLabel:{fontSize:11}},
  yAxis:{type:'value', name:'有候选的交易日 %', max:100, splitLine:{lineStyle:{color:CLR.grid}}},
  series:[{type:'bar', data:DATA.pass.map(function(v,i){
      return {value:v, itemStyle:{color:(DATA.floor[i]===__FLOOR__ ? CLR.red : '#c9d6e3')}};}),
    label:{show:true, position:'top', fontSize:11, formatter:'{c}%'}}]
}));

echarts.init(document.getElementById('c3')).setOption(ax({
  xAxis:{type:'category', data:DATA.dec_dates, axisLabel:{fontSize:10, rotate:20}},
  yAxis:{type:'value', name:'最高分', min:40, max:90, splitLine:{lineStyle:{color:CLR.grid}}},
  series:[
    {type:'bar', data:DATA.dec_best.map(function(v){return {value:v, itemStyle:{color:(v>=__FLOOR__?'#e8a5a0':'#b3bec9')}};}),
     label:{show:true, position:'top', fontSize:11}},
    {type:'line', data:DATA.dec_floor, symbol:'none', lineStyle:{color:CLR.red, type:'dashed', width:1.5},
     tooltip:{show:false}}
  ]
}));
</script>
</body></html>
"""

    div_sat = all((sc[c] or {}).get("div", 0) >= spec["score"]["diversification"]["points"]
                  for c in codes if c != "sh510050")
    divnote = ("Div 全部取满 20 分：现金占比 %s%% 时，任何非上证50 的买入都能把 RC50 拉低 1.7~2.3pp，"
               "远超规格阈值 −0.15。这意味着 <b>Div 在本季不区分标的</b>（只是一个常数），"
               "阈值 %d 因此实际等价于核心分 ≥40。" % (n(S["cash_pct"], 1), floor)) if div_sat else \
              "Div 有区分度：ΔRC50 在候选之间存在差异，排序部分依赖分散效果。"

    acts = []
    if buying:
        acts.append("%s %s 份 × %.3f = %s 元（缺口 %s 元）" % (
            act.get("name"), "{:,}".format(act.get("shares")), act.get("px") or 0,
            "{:,.2f}".format(act.get("cost") or 0), "{:,.0f}".format(act.get("gap") or 0)))
        actline = "买入 " + acts[0]
        actdetail = "该标的分数 %s，通过全部硬门，缺口足够。下单后请更新 plan_state.json 的 shares / cash 并跑 --mark-executed。" % n(act.get("score"), 1)
    else:
        actline = ("本季不买，3,000 元并入现金。" if S.get("is_decision_day")
                   else "当前观察：若今日为决策日 → 不买（3,000 元留现金）。")
        actdetail = ("选择原因：<b>%s</b>。硬门通过者中没有一只达到 Eligibility Floor %d。"
                     "注意这不是「等某个形态出现」——下季重新计算，分数够了就买。" % (S.get("selection", ""), floor))

    style_note = ("<b>已超 60% 上限</b>，<b>组内标的（红利低波 ＋ 上证50）本季禁买</b>（低相关腿不受此限）。" if style_over
                  else "未超 60%，红利类未受额外限制。")

    rep = {
        "__ECHARTS__": JS, "__DATA__": json.dumps(chart, ensure_ascii=False),
        "__DATE__": S["date"], "__TIME__": dt.datetime.now().strftime("%H:%M"),
        "__HEADLINE__": actline,
        "__DTOQ__": str(S.get("days_to_qe", "—")),
        "__DDT__": n(S.get("drawdown_total"), 1), "__DDH__": n(S.get("drawdown_holdings"), 1),
        "__DDHTXT__": ("0.0%（基线日，无可比历史）" if S.get("drawdown_holdings") is None
                       else ("%s%%" % n(S.get("drawdown_holdings"), 1))),
        "__DDHNOTE__": ("（持仓口径本次仅建立基线，下期起才有读数）" if S.get("drawdown_holdings") is None else ""),
        "__DDBOX__": ("总资产 %s%%<br><span class=\"muted\" style=\"font-size:11px\">持仓口径 0.0%%（基线日，下期起有读数）</span>"
                      % n(S.get("drawdown_total"), 1)) if S.get("drawdown_holdings") is None
                     else ("总资产 %s%% / 持仓 %s%%" % (n(S.get("drawdown_total"), 1), n(S.get("drawdown_holdings"), 1))),
        "__PEAKH__": "{:,.0f}".format(S.get("peak_holdings") or 0),
        "__PREM_NDX__": ("%s%%" % n(pr.get("sz159941") if (pr := S.get("premium")) else None, 2, True)),
        "__PREM_SPX__": ("%s%%" % n(pr.get("sh513500") if (pr := S.get("premium")) else None, 2, True)),
        "__CASHNEW__": n((S["cash"] + 3000) / (S["total"] + 3000) * 100, 1),
        "__GAPMAX__": n(max([(v or {}).get("total", 0) for v in sc.values()]) - (S.get("score_max") or 0), 1),
        "__DEC0930__": n(next((d["best"] for d in dec if d["d"] == "2026-09-30"), None), 1),
        "__EXC_NORISK__": n(gr_variants.get("V2", {}).get("all", {}).get("exc"), 2, True),
        "__EXC_V1__": n(V1.get("all", {}).get("exc"), 2, True),
        "__COST__": n(abs((gr_variants.get("V2", {}).get("all", {}).get("exc") or 0) - (V1.get("all", {}).get("exc") or 0)), 2),
        "__POOL__": "{:,}".format(GR.get("signal", {}).get("n", 0)),
        "__ICTREND__": n(GR.get("signal", {}).get("ic", {}).get("trend", {}).get("mean"), 3, True),
        "__SEGROWS__": seg_rows(),
        "__ICN0__": str(SEG["全样本"]["total"]["n"]), "__ICN1__": str(SEG["剔除2025Q3"]["total"]["n"]),
        "__ICN2__": str(SEG["2026"]["total"]["n"]),
        "__ICTOTAL_S__": n(SEG["全样本"]["total"]["mean"], 3, True),
        "__ICTOTT__": n(SEG["全样本"]["total"]["tstat"], 2, True),
        "__ICNWT__": n(SEG["全样本"]["total"]["nw_tstat"], 2, True),
        "__ICNWEX__": n(SEG["剔除2025Q3"]["total"]["nw_tstat"], 2, True),
        "__ICNW26__": n(SEG["2026"]["total"]["nw_tstat"], 2, True),
        "__ICNWT2__": n(SEG["全样本"]["trend"]["nw_tstat"], 2, True),
        "__GAP0__": n(SEG["全样本"]["total"]["avg_gap"], 1),
        "__NWLAG__": str(SEG["全样本"]["total"]["nw_lag"]),
        "__ICTTOTEX__": n(SEG["剔除2025Q3"]["total"]["mean"], 3, True),
        "__ICTOTEXT__": n(SEG["剔除2025Q3"]["total"]["tstat"], 2, True),
        "__ICTTOT26__": n(SEG["2026"]["total"]["mean"], 3, True),
        "__ICTOT26T__": n(SEG["2026"]["total"]["tstat"], 2, True),
        "__SDAY0__": str(SEG["全样本"]["_dates"]), "__SDAY1__": str(SEG["剔除2025Q3"]["_dates"]),
        "__SDAY2__": str(SEG["2026"]["_dates"]),
        "__ICMOM__": n(SEG["全样本"]["mom"]["mean"], 3, True),
        "__ICMOMT__": n(SEG["全样本"]["mom"]["tstat"], 2, True),
        "__ICMOMNW__": n(SEG["全样本"]["mom"]["nw_tstat"], 2, True),
        "__ICTOTAL__": n(GR.get("signal", {}).get("ic", {}).get("total", {}).get("mean"), 3, True),
        "__PASS60__": n((TH.get("pass_rate") or {}).get("60"), 1),
        "__RC50A__": n(GR.get("policy", {}).get("models", {}).get("M0", {}).get("rc50_end"), 1),
        "__RC50B__": n(GR.get("policy", {}).get("models", {}).get("M2", {}).get("rc50_end"), 1), "__BAR__": S["bar_date"], "__SPECV__": str(S.get("spec_version")),
        "__HERO__": hero_title, "__HEROSUB__": hero_sub,
        "__TOTAL__": "{:,.0f}".format(S["total"]), "__CASHPCT__": n(S["cash_pct"], 1),
        "__SMAX__": n(S["score_max"], 1), "__FLOOR__": str(floor), "__BAND__": str(band),
        "__RC__": n(rcl, 1), "__RCABS__": n(rcabs, 2),
        "__STYLE__": "%s%% / %s%%" % (n(style2, 1), n(style1, 1)),
        "__STYLE2__": n(style2, 1), "__STYLE1__": n(style1, 1), "__STYLENOTE__": style_note,
        "__SD__": n(S["sd"], 2), "__DD__": n(S["drawdown"], 1),
        "__PEAK__": "{:,.0f}".format(S["peak"]),
        "__ICRISK__": n(GR.get("signal", {}).get("ic", {}).get("risk", {}).get("mean"), 3, True),
        "__SDT__": n(gr_variants.get("V2", {}).get("all", {}).get("sd"), 2),
        "__SD1__": n(V1.get("all", {}).get("sd"), 2),
        "__CVT__": n(gr_variants.get("V2", {}).get("all", {}).get("cvar"), 2),
        "__CV1__": n(V1.get("all", {}).get("cvar"), 2),
        "__CSDAYS__": n(tv_dec.get("cs_on_signal_days"), 2),
        "__CSEX__": n(tv_dec.get("excess_cs"), 2),
        "__TOPQS__": n(tv_conc.get("top_quarter_share"), 1),
        "__EXQ__": n(tv_exq.get("excess_cs"), 2, True), "__EXQW__": n(tv_exq.get("winrate"), 1),
        "__OOS26__": n(V6.get("y2026", {}).get("exc"), 2, True) if V6 else n(TV.get("holdout", {}).get("states", [{}])[0].get("test_excess"), 2, True),
        "__M0T__": str(GR.get("policy", {}).get("models", {}).get("M0", {}).get("trades", "—")),
        "__SCOREROWS__": score_rows(), "__GATEROWS__": gate_rows(),
        "__THRROWS__": thr_rows(), "__DECROWS__": dec_rows(),
        "__THN__": str(TH.get("n_days", "—")),
        "__DIVNOTE__": divnote, "__ACTLINE__": actline, "__ACTDETAIL__": actdetail,
    }
    html = HTML
    for k, v in rep.items():
        html = html.replace(k, v)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(html)
    print("written", OUT, os.path.getsize(OUT))


if __name__ == "__main__":
    main()
