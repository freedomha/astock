#!/usr/bin/env python3
"""
全市场概念板块枚举 + 最新K线拉取
1. sector list 枚举 concept_list_industry / concept_list_style / concept_list_area（分页至取完）
2. 对全部概念板块拉取 250 日日K线（4次重试，容忍瞬时空返回）
3. 输出:
   - all_concept_sectors.json  全概念板块清单
   - concept_kline_data.json   K线数据 {code: [kline...]}
"""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK_BIN = "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/westock-data/scripts/index.js"
NODE_BIN = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
OUT_DIR = "/Users/aldiadmin/Documents/vscodeworkspace/astock"
KLINE_DAYS = 250
MAX_WORKERS = 6
SLEEP = 0.2

SCOPES = [
    ("concept_list_industry", "聚源产业概念"),
    ("concept_list_style", "聚源风格概念"),
    ("concept_list_area", "聚源地域概念"),
]

def run_westock(args, retries=4, timeout=30):
    cmd = [NODE_BIN, WESTOCK_BIN] + args + ["--raw"]
    for _ in range(retries):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = r.stdout.strip()
            if r.returncode == 0 and out:
                data = json.loads(out)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            pass
        time.sleep(SLEEP)
    return None

def enumerate_concepts():
    sectors = []
    seen = set()
    for scope, stype in SCOPES:
        offset = 0
        page = 200
        total_scope = 0
        while True:
            data = run_westock(["sector", "list", scope, "--limit", str(page), "--offset", str(offset)])
            if not data:
                break
            for s in data:
                code = s.get("code")
                if code and code not in seen:
                    seen.add(code)
                    sectors.append({"code": code, "name": s.get("name"), "type": stype,
                                    "sectorCode": s.get("sectorCode")})
            total_scope += len(data)
            if len(data) < page:
                break
            offset += page
        print(f"{scope}: {total_scope} 个")
    return sectors

def fetch_kline(code):
    return code, run_westock(["kline", code, "--period", "day", "--limit", str(KLINE_DAYS)])

def main():
    print("Step 1: 枚举全市场概念板块...")
    sectors = enumerate_concepts()
    print(f"共 {len(sectors)} 个概念板块")
    with open(f"{OUT_DIR}/all_concept_sectors.json", "w") as f:
        json.dump(sectors, f, ensure_ascii=False, indent=1)

    # 旧数据兜底
    old = {}
    for p in [f"{OUT_DIR}/concept_kline_data.json", f"{OUT_DIR}/sector_kline_data.json"]:
        try:
            with open(p) as f:
                for k, v in json.load(f).items():
                    if v and k not in old:
                        old[k] = v
        except Exception:
            pass
    print(f"载入 {len(old)} 条旧K线作兜底")

    print("Step 2: 并行拉取K线...")
    kline = {}
    failed = []
    codes = [s["code"] for s in sectors]
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_kline, c): c for c in codes}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                _, data = fut.result()
            except Exception:
                data = None
            if data:
                kline[c] = data
            elif c in old:
                kline[c] = old[c]
                failed.append(c + "(keep-old)")
            else:
                failed.append(c)
            done += 1
            if done % 30 == 0 or done == len(codes):
                print(f"  进度 {done}/{len(codes)}  fresh={len(kline) - sum(1 for x in failed if 'keep-old' in x)}")

    with open(f"{OUT_DIR}/concept_kline_data.json", "w") as f:
        json.dump(kline, f, ensure_ascii=False)

    fresh = len(kline) - sum(1 for x in failed if "keep-old" in x)
    print(f"\nDONE 总数={len(codes)} 获取K线={len(kline)} (全新={fresh}, 兜底={len(kline)-fresh}, 完全失败={len(codes)-len(kline)})")
    if failed:
        print("失败/兜底列表:", failed[:30])
    # 最新日期分布
    from collections import Counter
    c = Counter(max(x["date"] for x in v) for v in kline.values() if v)
    print("最新日期分布:", dict(c.most_common(5)))

if __name__ == "__main__":
    main()
