"""
Download every dataset the research scripts use into one folder:

  <data>/yahoo/<PAIR>_d.json      daily FX closes (Yahoo Finance), 2000 -> today
  <data>/yahoo/IDX_<SYM>.json     daily equity indices (for the month-end flow test)
  <data>/fred/IR3_<CC>.csv        3-month interbank rates (FRED / OECD)
  <data>/dukascopy/<PAIR>/*.bi5   hourly BID candles (Dukascopy), 2004 -> today

Dukascopy rate-limits aggressively; the downloader backs off and resumes, and
already-downloaded months are skipped. A full run can take several hours.

Usage: python3 download_data.py <data-folder> [--skip-hourly]
"""
import os
import random
import sys
import threading
import time
import queue

import requests

YAHOO_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURGBP", "EURJPY",
               "GBPJPY", "EURCHF", "AUDJPY", "EURAUD", "EURCAD", "GBPCHF", "AUDNZD", "AUDCAD", "CADJPY",
               "NZDJPY", "GBPAUD", "CHFJPY", "EURNZD", "GBPCAD", "AUDCHF", "CADCHF", "NZDCAD", "GBPNZD",
               "NZDCHF", "USDSGD", "USDMXN", "USDZAR", "USDTRY", "USDNOK", "USDSEK", "USDPLN", "USDHUF"]
INDICES = ["^GSPC", "^STOXX50E", "^FTSE", "^N225", "^AXJO", "^GSPTSE", "^SSMI"]
FRED = ["US", "EZ", "JP", "GB", "CH", "CA", "AU", "NZ", "NO", "SE", "ZA", "MX", "PL", "HU"]
HOURLY = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "XAUUSD", "XAGUSD"]
UA = {"User-Agent": "Mozilla/5.0"}


def get(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    for attempt in range(8):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 200:
                with open(path, "wb") as f:
                    f.write(r.content)
                return
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    print("FAILED", url)


def dukascopy(folder, pairs, y0, y1, last=(time.gmtime().tm_year, time.gmtime().tm_mon - 2)):
    q = queue.Queue()
    for y in range(y1, y0 - 1, -1):
        for m in range(12):
            if (y, m) <= last:
                for p in pairs:
                    q.put((p, y, m))

    def worker():
        s = requests.Session()
        s.headers.update(UA)
        while True:
            try:
                p, y, m = q.get_nowait()
            except queue.Empty:
                return
            path = os.path.join(folder, p, f"{y}_{m:02d}_BID.bi5")
            if os.path.exists(path):
                continue
            url = f"https://datafeed.dukascopy.com/datafeed/{p}/{y}/{m:02d}/BID_candles_hour_1.bi5"
            for _ in range(20):
                try:
                    r = s.get(url, timeout=60)
                    if r.status_code == 200 and r.content[:1] != b"{":
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "wb") as f:
                            f.write(r.content)
                        break
                    if r.status_code == 404:
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        open(path, "wb").close()
                        break
                    time.sleep(20 + random.random() * 20)      # rate limited
                except requests.RequestException:
                    s = requests.Session()
                    s.headers.update(UA)
                    time.sleep(5)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]


def main():
    root = sys.argv[1]
    for sub in ("yahoo", "fred", "dukascopy"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    end = int(time.time())
    for p in YAHOO_PAIRS:
        get(f"https://query1.finance.yahoo.com/v8/finance/chart/{p}=X?period1=946684800&period2={end}&interval=1d",
            os.path.join(root, "yahoo", f"{p}_d.json"))
    for s in INDICES:
        get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1=946684800&period2={end}&interval=1d",
            os.path.join(root, "yahoo", f"IDX_{s}.json"))
    for c in FRED:
        get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=IR3TIB01{c}M156N",
            os.path.join(root, "fred", f"IR3_{c}.csv"))
    if "--skip-hourly" not in sys.argv:
        dukascopy(os.path.join(root, "dukascopy"), HOURLY, 2004, time.gmtime().tm_year)
    print("done")


if __name__ == "__main__":
    main()
