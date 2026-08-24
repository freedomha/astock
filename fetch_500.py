#!/usr/bin/env python3
"""
拉取ETF 500日K线数据，用于碗底算法回测
"""
import json
import subprocess
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK_BIN = "/Users/aldiadmin/.workbuddy/westock-data/scripts/index.js"
NODE_BIN = "/Users/aldiadmin/.workbuddy/binaries/node/versions/22.22.2/bin/node"
KLINE_DAYS = 500
MAX_WORKERS = 8

def run_westock(*args):
    cmd = [NODE_BIN, WESTOCK_BIN] + list(args) + ["--raw"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        if isinstance(data, dict) and data.get("success") is False:
            return None
        return data
    except Exception as e:
        return None

def fetch_kline(code, retries=4):
    for attempt in range(retries):
        data = run_westock("kline", code, "--period", "day", "--limit", str(KLINE_DAYS))
        if data:
            return code, data
        if attempt < retries - 1:
            time.sleep(0.3)
    return code, None

def main():
    # Load ETF codes from existing kline data (we know these are fetchable)
    existing_file = os.path.join(os.getcwd(), "etf_kline_data.json")
    if not os.path.exists(existing_file):
        print("no existing data")
        return
    
    with open(existing_file) as f:
        existing = json.load(f)
    
    codes = list(existing.keys())
    print(f"Feteching 500-day K-line for {len(codes)} ETFs...")
    
    kline_data = {}
    done = 0
    total = len(codes)
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_kline, code): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                c, data = future.result()
                if data:
                    kline_data[c] = data
                done += 1
                if done % 50 == 0 or done == total:
                    print(f"  {done}/{total} ({len(kline_data)} ok)")
            except:
                done += 1
    
    # Retry missing
    missing = [c for c in codes if c not in kline_data]
    if missing:
        print(f"Retrying {len(missing)} failed...")
        for c in missing:
            _, d = fetch_kline(c, retries=6)
            if d:
                kline_data[c] = d
        still_missing = [c for c in codes if c not in kline_data]
        print(f"  After retry: {len(kline_data)}/{total} ok, {len(still_missing)} missing")
    
    # Save
    output_file = os.path.join(os.getcwd(), "etf_kline_data_500.json")
    with open(output_file, "w") as f:
        json.dump(kline_data, f, ensure_ascii=False)
    
    # Stats
    sizes = [len(v) for v in kline_data.values()]
    if sizes:
        print(f"\nSaved: {output_file}")
        print(f"Records per ETF: min={min(sizes)}, max={max(sizes)}, avg={sum(sizes)/len(sizes):.0f}")
        # Date range for first ETF
        first = kline_data[list(kline_data.keys())[0]]
        if first:
            dates = [k["date"] for k in first if "date" in k]
            print(f"Date range: {dates[-1] if dates else '?'} ~ {dates[0] if dates else '?'}")

if __name__ == "__main__":
    main()
