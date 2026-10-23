#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐月采样 QDII ETF 的静态溢价（close / nav），用于判断溢价门是否长期不可通过。"""
import json, os, subprocess, time

NODE = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2-6/bin/node"
CLI = "/Users/aldiadmin/.workbuddy/westock-data/scripts/index.js"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "premium_monthly.json")
CODES = ["sz159941", "sh513100", "sh513500", "sh513110", "sz159513", "sz159632", "sh513650"]
DATES = ["2024-09-30", "2024-10-31", "2024-11-29", "2024-12-31", "2025-01-27", "2025-02-28",
         "2025-03-31", "2025-04-30", "2025-05-30", "2025-06-30", "2025-07-31", "2025-08-29",
         "2025-09-30", "2025-10-31", "2025-11-28", "2025-12-31", "2026-01-30", "2026-02-27",
         "2026-03-31", "2026-04-30", "2026-05-29", "2026-06-30", "2026-07-31", "2026-08-31",
         "2026-09-30", "2026-10-22"]


def one(code, dt, tries=6):
    for _ in range(tries):
        try:
            r = subprocess.run([NODE, CLI, "etf", "detail", code, "--date", dt, "--raw"],
                               capture_output=True, text=True, timeout=40)
            s = json.loads(r.stdout)["sections"][0][0]
            cl, nav = s.get("closePrice"), s.get("nav")
            if cl and nav:
                return dict(date=dt, close=cl, nav=nav, prem=round((cl / nav - 1) * 100, 2),
                            status=s.get("purchaseStatus"))
        except Exception:
            pass
        time.sleep(0.8)
    return None


def main():
    out = {}
    for c in CODES:
        rows = []
        for dt in DATES:
            v = one(c, dt)
            if v:
                rows.append(v)
        out[c] = rows
        print(c, len(rows), "of", len(DATES))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("written", OUT)


if __name__ == "__main__":
    main()
