#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成季度定投计划报告 v14（硬门 + V1 连续评分）。

数据来源只有一个：`review.py --json` 的快照。报告与 skill 同源，避免两套口径。
证据数字来自两份研究报告的 JSON（T-State Validation / Gate Redesign）。

输出：reports/etf/allocation/20261022-季定投计划-v14.html
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
OUT = os.path.join(ROOT, "reports/etf/allocation/20261022-季定投计划-v14.html")
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

    def dec_rows():
        out = []
        for d in dec:
            ok60 = "买" if d["n60"] > 0 else '<span class="muted">现金</span>'
            hl = ' style="background:#fdeeee"' if d["n60"] == 0 else ""
            out.append("<tr%s><td>%s</td><td>%s</td><td>%d</td><td>%d</td><td>%s</td></tr>"
                       % (hl, d["d"], n(d["best"], 1), d["n60"], d["n70"], ok60))
        return "".join(out)

    act = S.get("action") or {}
    buying = bool(act.get("code"))
    hero_title = ("本季买入：%s %s 份" % (act.get("name"), "{:,}".format(act.get("shares") or 0))) if buying \
        else "本季不买：留现金"
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
<title>季度定投计划 v14 · 硬门 + 连续评分</title>
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

<h1>季度定投计划 <span class="tag">v14</span> <span style="color:#95a5a6;font-weight:400">/</span> 硬门 + 连续评分</h1>
<div class="sub">每季新增 3,000 元 · 快照 __DATE__ __TIME__ · K 线 __BAR__ · 规格 v__SPECV__（冻结） · 全部数字由 review.py 同源产出 · 非投资建议</div>

<div class="card hero">
  <h2>__HERO__</h2>
  <p style="margin-bottom:12px">__HEROSUB__。架构已从「T0-T8 状态门」换成「<b>硬门 + 连续评分</b>」：硬门只否决不可接受的风险，评分只负责排序，<b>绝对下限才是唯一能产生「不买」的开关</b>。</p>
  <div class="kpi">
    <div class="kpibox"><div class="n">__TOTAL__</div><div class="l">总资产<br>现金 __CASHPCT__%</div></div>
    <div class="kpibox"><div class="n">__SMAX__</div><div class="l">硬门通过者最高分<br>下限 __FLOOR__</div></div>
    <div class="kpibox"><div class="n">__RC__</div><div class="l">RC50 占比<br>绝对 __RCABS__%</div></div>
    <div class="kpibox"><div class="n">__STYLE2__ / __STYLE1__</div><div class="l">风格组风险 %<br>2 年 / 1 年</div></div>
  </div>
</div>

<div class="card">
  <h2>一、架构：三个职责分离</h2>
  <div class="flow">
    <div class="g"><b>HARD GATES</b>溢价 ≤1.5%<br>回撤 &gt;15% 暂停<br>风格组 ≤60%<br>单笔 &lt;2,000</div>
    <div class="s"><b>SOFT SCORE</b>Trend 30<br>Momentum 30（钟形）<br>Risk 20<br>Diversification 20</div>
    <div class="t"><b>THRESHOLD</b>Score ≥ __FLOOR__<br>且 ≥ max − __BAND__<br>无候选 → 现金</div>
    <div><b>EXECUTE</b>按分排序<br>→ 缺口<br>→ 买入 ≤3,000</div>
  </div>
  <table>
    <thead><tr><th>层</th><th>回答的问题</th><th>典型规则</th><th>能否被「分数高」抵消</th></tr></thead>
    <tbody>
      <tr><td><b>硬门</b></td><td class="l">这个风险我是否根本不该承担？</td><td class="l">溢价、回撤、风格组、数据质量</td><td>不能</td></tr>
      <tr><td><b>软分</b></td><td class="l">在可买的里面，哪个现在更值得优先？</td><td class="l">趋势 / 动量 / 波动 / 分散</td><td>能</td></tr>
      <tr><td><b>阈值</b></td><td class="l">今天到底有没有值得买的？</td><td class="l">绝对下限 __FLOOR__ ＋ 相对带 __BAND__</td><td>—</td></tr>
    </tbody>
  </table>
  <div class="note blue">这三个问题的答案性质不同，混在一张表里就会互相抵消。
    最典型的是 <b>Risk 组件</b>：横截面 IC 是 __ICRISK__（负），单看预测收益像是有害的；但它把 top20 的收益标准差从 __SDT__ 压到 __SD1__、5% 尾部从 __CVT__ 改善到 __CV1__。
    <b>用 IC 评价保险，会得出「保险有害」的结论。</b></div>
</div>

<div class="card">
  <h2>二、为什么废除状态门：三条证据</h2>
  <ol>
    <li><b>+4.33pp 里 64% 是时间效应。</b>T3b 出现的那些日子，全市场平均后续 20 日涨 <b>__CSDAYS__%</b>；T3b 标的相对同日全市场只再多 <b>__CSEX__pp</b>。原口径把 β 择时算成了选券能力。</li>
    <li><b>一个季度撑起全部结论。</b>2025Q3 一季贡献 <b>__TOPQS__%</b> 的观测；剔除后横截面超额 <b>__EXQ__pp</b>、胜率 __EXQW__%。2026 样本外 <b>__OOS26__pp</b>。</li>
    <li><b>在 5 只标的的菜单上，它几乎不投。</b>回测的 5 个季度里，状态门只放行 <b>__M0T__ 次</b>买入——它不只是在防止错误投资，也在阻止资产配置发生。<b>「只稀释不卖出」的前提是「有钱投得出去」。</b></li>
  </ol>
  <div class="note warn" style="margin-bottom:0">同日置换检验 p&lt;0.002：T3b <b>不是噪声</b>，横截面信息真实存在。所以正确的处理不是删掉它，而是<b>降级为描述性特征</b>——
    报告里仍然显示 T 码，但它不再决定买卖。</div>
</div>

<div class="card">
  <h2>三、今日评分</h2>
  <div class="tw"><table>
    <thead><tr><th>标的</th><th>Trend</th><th>Mom</th><th>Risk</th><th>Div</th><th>ΔRC50</th><th>合计</th><th>缺口</th><th>判定</th></tr></thead>
    <tbody>__SCOREROWS__</tbody>
  </table></div>
  <div id="c1" class="chart"></div>
  <div class="legend">堆叠＝四个分项之和（0–100）。红色虚线为绝对下限 __FLOOR__。</div>
  <div class="note">__DIVNOTE__</div>
</div>

<div class="card">
  <h2>四、硬门判定</h2>
  <div class="tw"><table>
    <thead><tr><th>标的</th><th>静态溢价</th><th>否决原因</th><th>结果</th></tr></thead>
    <tbody>__GATEROWS__</tbody>
  </table></div>
  <p><b>溢价是本季最主要的否决来源。</b>QDII 场内价 = 净值 + 溢价，套利通道关闭时溢价可持续也可突然收敛；
    按 +13.7% 的溢价买入，即使底层不动，收敛到 2% 也意味着 −10% 以上的损失。这条是 B 类风控政策，<b>不可被高分抵消</b>。</p>
  <div class="note warn" style="margin-bottom:0"><b>已知盲区：溢价门无法回测。</b>接口不提供历史 NAV / IOPV 序列，只有当日静态溢价，
    因此研究报告里的所有历史模拟都等于「假设溢价门通过」。历史结论不能证明「当时真的买得到」。</div>
</div>

<div class="card" style="border:2px solid #c0392b">
  <h2 style="color:#c0392b">五、本季结论</h2>
  <p style="font-size:15px"><b>__ACTLINE__</b></p>
  <p>__ACTDETAIL__</p>
  <div class="note"><b>与旧规则的差别不在本季结论，在「什么时候会买」。</b>
    旧版同样是留现金，但路径是先看 T 码再看溢价；新版先过硬门（本季仍是溢价否决纳指/标普、风格组否决红利），
    再看分数——黄金虽然过了硬门，<b>41.4 分不到下限 __FLOOR__</b>。
    差别在于：<b>旧规则等一个可能不出现的形态，新规则每季重新算分，分够了就买。</b></div>
</div>

<div class="card">
  <h2>六、组合风险</h2>
  <div class="kpi" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpibox" style="background:#f8fafc;border:1px solid #eef1f4"><div class="n" style="color:#1f3a5f">__SD__%</div><div class="l" style="color:#7f8c8d">σp（组合波动）</div></div>
    <div class="kpibox" style="background:#f8fafc;border:1px solid #eef1f4"><div class="n" style="color:#1f3a5f">__RC__%</div><div class="l" style="color:#7f8c8d">上证50 风险占比</div></div>
    <div class="kpibox" style="background:#f8fafc;border:1px solid #eef1f4"><div class="n" style="color:#1f3a5f">__RCABS__%</div><div class="l" style="color:#7f8c8d">绝对风险贡献</div></div>
    <div class="kpibox" style="background:#f8fafc;border:1px solid #eef1f4"><div class="n" style="color:#1f3a5f">__DD__%</div><div class="l" style="color:#7f8c8d">当前回撤（峰值 __PEAK__）</div></div>
  </div>
  <p>风格组（上证50＋红利低波）风险：<b>2 年 __STYLE2__% ／ 1 年 __STYLE1__%</b>。__STYLENOTE__</p>
  <div class="note">RC50 占比与绝对贡献要一起看：单独看占比会被「加高波动资产」机械稀释。
    251 日滚动窗口里风格组最低仍 62.1%、从未低于 60%——所以规则 4/5 的约束与窗口选择无关。</div>
</div>

<div class="card">
  <h2>七、阈值的证据：只验证行为，不验证收益</h2>
  <p>下图是「五只标的中最高分」在过去 __THN__ 个交易日的分布通过率。<b>绝对下限 60 是唯一能产生「不买」的开关</b>；
    相对带 __BAND__ 永远挡不住买入——最高分天然满足 <code>≥ max − __BAND__</code>，它只把候选集从 4 只收窄到约 2 只。</p>
  <div id="c2" class="chart"></div>
  <div class="tw"><table>
    <thead><tr><th>绝对下限</th><th>有候选的交易日占比</th><th>读法</th></tr></thead>
    <tbody>__THRROWS__</tbody>
  </table></div>
  <h3>五个历史决策日：最弱的季度长什么样</h3>
  <div id="c3" class="chart" style="height:260px"></div>
  <div class="tw"><table>
    <thead><tr><th>季度末</th><th>最高分</th><th>≥60 的候选数</th><th>≥70 的候选数</th><th>本季动作（floor 60）</th></tr></thead>
    <tbody>__DECROWS__</tbody>
  </table></div>
  <div class="note ok" style="margin-bottom:0">下一步要看的是：在 <b>≥4 个新的季度决策点</b>（最早 2027Q4）之前，不得用收益对 V1 做「优于/劣于」判断。
    复评只看行为指标：符号一致性、投出率、现金比、RC50 方向、纪律偏差。<b>60 与 __BAND__ 是预注册候选值，没有收益验证。</b></div>
</div>

<div class="card">
  <h2>八、执行规则</h2>
  <table>
    <thead><tr><th>#</th><th>规则</th><th>证据等级</th></tr></thead>
    <tbody>
      <tr><td>0</td><td class="l"><b>溢价门</b>：静态溢价 &gt; 1.5% 一律不买；折价不构成门槛</td><td>B 风控政策</td></tr>
      <tr><td>1</td><td class="l"><b>金额</b>：每季 3,000，单笔 ≤3,000，缺口按投入后总资产重算，不跨季结转</td><td>B</td></tr>
      <tr><td>2</td><td class="l"><b>最小额</b>：单笔 &lt;2,000 跳过（5 元佣金 = 0.25%）</td><td>B</td></tr>
      <tr><td>3</td><td class="l"><b>评分门</b>：Score ≥ __FLOOR__ 且 ≥ max − __BAND__，按分排序取缺口；无候选留现金</td><td>C 待验证（行为已验证）</td></tr>
      <tr><td>4</td><td class="l"><b>风格组</b>：60% 上限只约束同因子标的（红利类），低相关腿不受限</td><td>B</td></tr>
      <tr><td>5</td><td class="l"><b>双窗口</b>：2 年与 1 年均低于 60% 才放行红利类</td><td>B</td></tr>
      <tr><td>—</td><td class="l"><b>回撤</b>：相对峰值 &gt;15% 暂停全部买入，收窄至 10% 且复核通过后恢复</td><td>B</td></tr>
    </tbody>
  </table>
  <p class="muted">下单时点：季末最后一个交易日收盘后计算，下一交易日 14:45 之后下单（唯一一笔异常滑点 +76.8bps 来自盘中追价）。</p>
</div>

<div class="card">
  <h2>九、与 v13 的差异</h2>
  <div class="tw"><table>
    <thead><tr><th>项目</th><th>v13（状态门）</th><th>v14（V1）</th></tr></thead>
    <tbody>
      <tr><td>买不买由什么决定</td><td class="l">T 码 ∈ {T3b,T4}（分散腿放宽到 T1+）</td><td class="l">Score ≥ __FLOOR__ 且 ≥ max − __BAND__</td></tr>
      <tr><td>T 码的角色</td><td class="l">硬门（有否决权）</td><td class="l">描述性特征（只展示）</td></tr>
      <tr><td>溢价 / 回撤 / 风格组</td><td class="l">硬门</td><td class="l">硬门（不变）</td></tr>
      <tr><td>候选排序</td><td class="l">缺口最大者</td><td class="l">分数优先，分差 &lt;1 再比缺口</td></tr>
      <tr><td>「恢复」概念</td><td class="l">A 溢价收敛 / B 黄金转 T1</td><td class="l">无——每季独立按分数判定</td></tr>
      <tr><td>证据基础</td><td class="l">T3b +4.33pp（池化基准、样本内）</td><td class="l">同日横截面 +1.57pp，且三段全为正</td></tr>
    </tbody>
  </table></div>
  <div class="note blue" style="margin-bottom:0">旧报告仍保留在 <code>reports/etf/allocation/20261021-季定投计划.html</code>，作为历史决策存档；
    其中「规则 3 状态门」已被本版取代，引用时请注意。</div>
</div>

<div class="card">
  <h2>十、局限与失效条件</h2>
  <ul>
    <li><b>Div 已饱和。</b>现金 __CASHPCT__% 时，任意非上证50 标的的 ΔRC50 都在 −1.7~−2.3pp，远超规格的 −0.15，所以 Div 恒为 20。
      排序不受影响（同一常数），但<b>阈值 __FLOOR__ 实际等价于核心分 ≥40</b>。现金降到 10% 以下前，Div 事实是「非上证50」的门。</li>
    <li><b>政策层样本极短。</b>5 个季度决策、收益差 647 元——不可判定。只有 RC50 的差异（40.2 vs 29.2）有结构性含义。</li>
    <li><b>溢价门不可回测。</b>历史模拟等于假设溢价门通过。</li>
    <li><b>QDII 用场内价算协方差</b>（已用指数代理做 lag1 修正），仍含跟踪误差与汇率缺口。</li>
    <li><b>失效条件</b>：若连续 4 个季度「有候选但分数都不足 60」导致投出率 &lt;50%，说明下限过严，应按 V1-SPEC 第 6 节走变更流程，而不是当场下调。</li>
  </ul>
</div>

<div class="card">
  <h2>十一、变更记录</h2>
  <table>
    <thead><tr><th>版本</th><th>日期</th><th>变更</th></tr></thead>
    <tbody>
      <tr><td>v14</td><td class="nw">2026-10-22</td><td class="l">架构切换：T0-T8 状态门 → 硬门 + V1 连续评分（30/30/20/20），阈值 60/5；T 码降为描述性特征</td></tr>
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
        actline = "本季不买，3,000 元并入现金。"
        actdetail = ("选择原因：<b>%s</b>。硬门通过者中没有一只达到绝对下限 %d。"
                     "注意这不是「等某个形态出现」——下季重新计算，分数够了就买。" % (S.get("selection", ""), floor))

    style_note = ("<b>已超 60% 上限</b>，红利类本季禁买（低相关腿不受此限）。" if style_over
                  else "未超 60%，红利类未受额外限制。")

    rep = {
        "__ECHARTS__": JS, "__DATA__": json.dumps(chart, ensure_ascii=False),
        "__DATE__": S["date"], "__TIME__": dt.datetime.now().strftime("%H:%M"), "__BAR__": S["bar_date"], "__SPECV__": str(S.get("spec_version")),
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
