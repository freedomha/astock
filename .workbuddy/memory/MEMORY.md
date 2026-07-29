# 项目长期记忆（astock）

## westock-data 使用规范（关键）
- **必须加 `dangerouslyDisableSandbox: true`**：沙箱会屏蔽网络，所有 westock-data 命令（quote/kline/finance/consensus/rating/report/macro）不加此参数会返回"数据为空"或 `[]`。
- **数据源高概率瞬时失败**：quote 批量常整批 `SKILL_004 未找到匹配数据`；kline/consensus/finance 偶发 `[]` 或 `null`（注意 `null` 不是空数组，需单独拒绝）。务必用重试循环（参考 /tmp/fetch_westock.py：最多10次，拒绝 `success:false`、空数组、`^null$`）。
- **概念板块代码不可直接取 K 线**（如 pt02GN2324 电信运营返回 `[]`），改用其成分股 K 线自建等权/市值加权指数；申万行业代码（如 pt01801770 通信）可正常取 K 线。
- 重试时 `WD` / `NODE` 环境变量不跨 Bash 调用持久，须用绝对路径：`WD=/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data`，`NODE=/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node`。

## 板块深度分析（sector-deep-analysis）产出规律
- 报告命名：`<板块名>板块深度分析-YYYYMMDD.html`，存项目根目录。
- 概念板块（聚源产业）成分少且含跨子赛道（运营商/广电/卫星），须分赛道分析，不能整体判断。
- consensus 的 `institutionCnt` 在本环境常返回 0（数据未返回的局限），不代表真实无覆盖。

## 碗底扫描（bowl-bottom-sector-scanner）经验
- 830 概念板块 K 线瞬时失败率约 5%，两轮重试即可 100% 覆盖。
- 8 并发下偶发整批失败，降低并发或串行补拉；大 json.dump 易 OOM(137)，拆分 fetch 与 re-analyze 两步。
