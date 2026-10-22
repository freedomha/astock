#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取 5 只持仓标的 + 沪深300 的 500 日 K 线（统一到同一批次、同一末日）。"""
import json, os, subprocess, time

NODE = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2-6/bin/node"
CLI = "/Users/aldiadmin/.workbuddy/westock-data/scripts/index.js"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.json")
CODES = ["sh510050", "sh513500", "sz159941", "sh512890", "sh518880", "sh510300"]

def fetch(code, tries=10):
    for i in range(tries):
        try:
            r = subprocess.run([NODE, CLI, "kline", code, "--period", "day", "--limit", "500", "--raw"],
                               capture_output=True, text=True, timeout=60)
            d = json.loads(r.stdout)
            if isinstance(d, list) and len(d) > 100:
                return d
        except Exception:
            pass
        time.sleep(1.2)
    return None

def main():
    out = {}
    for c in CODES:
        d = fetch(c)
        print(c, len(d) if d else "FAIL")
        if d:
            out[c] = d
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("written", OUT)

if __name__ == "__main__":
    main()
