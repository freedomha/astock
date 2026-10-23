#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取 QDII ETF 的收盘价与净值历史，用于计算「静态溢价」的时间序列。"""
import json, os, subprocess, time

NODE = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2-6/bin/node"
CLI = "/Users/aldiadmin/.workbuddy/westock-data/scripts/index.js"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "premium_raw.json")
CODES = {"sz159941": "纳指ETF(广发)", "sh513100": "纳指ETF(国泰)",
         "sh513110": "纳指ETF(华安)", "sh513500": "标普500ETF(博时)"}
START, END = "2024-09-01", "2026-10-22"


def run(args, tries=8):
    for i in range(tries):
        try:
            r = subprocess.run([NODE, CLI] + args, capture_output=True, text=True, timeout=60)
            d = json.loads(r.stdout)
            if isinstance(d, list) and d:
                return d
        except Exception:
            pass
        time.sleep(1.2)
    return None


def main():
    out = {}
    for c in CODES:
        nav = run(["etf", "nav", c, "--start", START, "--end", END, "--raw"])
        kl = run(["kline", c, "--period", "day", "--start", START, "--end", END, "--raw"])
        print(c, "nav", len(nav) if nav else 0, "kline", len(kl) if kl else 0)
        if nav and kl:
            out[c] = {"name": CODES[c], "nav": nav,
                      "close": [{"date": b["date"], "close": b["last"]} for b in kl]}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("written", OUT)


if __name__ == "__main__":
    main()
