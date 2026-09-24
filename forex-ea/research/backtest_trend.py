"""
Independent sanity-check backtest of the TrendEdge EA rules on daily data.

This is NOT a substitute for the MT5 Strategy Tester on XM's own data. It uses
free Yahoo Finance daily bars (imperfect: bad ticks, no real spreads) and a
deliberately pessimistic cost model, with textbook parameters that were NOT
optimised on this data. Its only job is to answer: "is there anything here
at all after realistic retail costs?"

Usage:
    python3 backtest_trend.py <dir-with-yahoo-json-files>

The JSON files are raw responses from
https://query1.finance.yahoo.com/v8/finance/chart/<SYMBOL>?period1=...&interval=1d
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

# --- Strategy parameters (same defaults as the EA; chosen a priori, not fitted) ---
ENTRY_N = 55          # Donchian breakout lookback
EXIT_N = 20           # Donchian exit lookback
ATR_N = 20
STOP_ATR = 3.0        # initial stop distance in ATR
RISK_PCT = 0.005      # 0.5% of equity risked per trade
MAX_OPEN_RISK = 0.04  # never more than 4% of equity at initial risk in total
START_EQUITY = 1000.0

# --- Pessimistic cost model -----------------------------------------------------
# symbol: (spread in price units, annual swap drag as fraction of notional)
MARKETS = {
    "EURUSD=X": (0.00017, 0.015), "GBPUSD=X": (0.00023, 0.015),
    "USDJPY=X": (0.020, 0.015),   "AUDUSD=X": (0.00019, 0.015),
    "USDCAD=X": (0.00025, 0.015), "USDCHF=X": (0.00022, 0.015),
    "NZDUSD=X": (0.00026, 0.015), "EURJPY=X": (0.028, 0.015),
    "GBPJPY=X": (0.040, 0.015),   "EURGBP=X": (0.00020, 0.015),
    "GC=F": (0.35, 0.04),         "^GSPC": (0.6, 0.05),
    "^GDAXI": (1.5, 0.05),        "^N225": (10.0, 0.05),
    "CL=F": (0.05, 0.05),
}
SLIPPAGE_ATR = 0.02   # extra slippage per side, as a fraction of ATR

# Standard-account reality check: minimum position value is ~1,000 units for FX
# (0.01 std lot) and ~1 oz gold. We record how often min-lot risk > 1.5x target.
STD_MIN_UNITS = {"GC=F": 1.0, "^GSPC": 1.0, "^GDAXI": 1.0, "^N225": 1.0, "CL=F": 10.0}


def load(path):
    with open(path) as f:
        js = json.load(f)
    r = js["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"],
                       "close": q["close"]},
                      index=pd.to_datetime(r["timestamp"], unit="s").normalize())
    df = df.dropna()
    df = df[(df > 0).all(axis=1)]
    df = df[~df.index.duplicated(keep="last")]
    # repair obviously broken highs/lows (common in Yahoo FX data)
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    return df


def prep(df):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_N).mean()
    df["hh_entry"] = df["high"].rolling(ENTRY_N).max().shift(1)
    df["ll_entry"] = df["low"].rolling(ENTRY_N).min().shift(1)
    df["hh_exit"] = df["high"].rolling(EXIT_N).max()
    df["ll_exit"] = df["low"].rolling(EXIT_N).min()
    return df


def usd_value_of_one_unit_move(sym, price):
    """Rough USD P&L of a 1.0 price move on 1 unit (for the min-lot check only)."""
    if sym.startswith("USD") and sym.endswith("=X"):
        return 1.0 / price
    if sym.endswith("JPY=X"):
        return 1.0 / 150.0
    if sym == "EURGBP=X":
        return 1.27
    return 1.0


def run(data):
    dates = sorted(set().union(*[d.index for d in data.values()]))
    equity = START_EQUITY
    open_pos = {}            # sym -> dict
    pending = {}             # sym -> direction to open at next open
    trades = []
    curve = []
    std_skips = 0
    std_checks = 0

    for day in dates:
        mtm = 0.0
        for sym, df in data.items():
            if day not in df.index:
                if sym in open_pos:
                    p = open_pos[sym]
                    mtm += p["risk_usd"] * p["dir"] * (p["last"] - p["entry"]) / p["stop_dist"]
                continue
            bar = df.loc[day]
            spread, swap = MARKETS[sym]

            # 1) fill pending entries at today's open
            if sym in pending and sym not in open_pos:
                d = pending.pop(sym)
                atr = bar["atr_prev"]
                stop_dist = STOP_ATR * atr
                open_risk = sum(p["risk_usd"] for p in open_pos.values())
                risk_usd = equity * RISK_PCT
                if stop_dist > 0 and open_risk + risk_usd <= equity * MAX_OPEN_RISK:
                    cost = spread / 2 + SLIPPAGE_ATR * atr
                    entry = bar["open"] + d * cost
                    open_pos[sym] = dict(dir=d, entry=entry, stop_dist=stop_dist,
                                         stop=entry - d * stop_dist, risk_usd=risk_usd,
                                         opened=day, last=entry)
                    # standard-account feasibility check
                    std_checks += 1
                    min_units = STD_MIN_UNITS.get(sym, 1000.0)
                    min_risk = min_units * stop_dist * usd_value_of_one_unit_move(sym, entry)
                    if min_risk > 1.5 * risk_usd:
                        std_skips += 1
            pending.pop(sym, None)

            # 2) manage open position: stop hit intrabar (gap -> fill at open)
            if sym in open_pos:
                p = open_pos[sym]
                hit = (p["dir"] == 1 and bar["low"] <= p["stop"]) or \
                      (p["dir"] == -1 and bar["high"] >= p["stop"])
                if hit:
                    raw = p["stop"]
                    if (p["dir"] == 1 and bar["open"] < p["stop"]) or \
                       (p["dir"] == -1 and bar["open"] > p["stop"]):
                        raw = bar["open"]
                    exit_px = raw - p["dir"] * (spread / 2 + SLIPPAGE_ATR * bar["atr"])
                    days = (day - p["opened"]).days
                    r_mult = p["dir"] * (exit_px - p["entry"]) / p["stop_dist"]
                    r_mult -= swap * days / 365.0 * p["entry"] / p["stop_dist"]
                    pnl = r_mult * p["risk_usd"]
                    equity += pnl
                    trades.append(dict(sym=sym, open=p["opened"], close=day, dir=p["dir"],
                                       r=r_mult, pnl=pnl, days=days))
                    del open_pos[sym]
                else:
                    # trail: stop only ever tightens, to the opposite 20-bar channel
                    if p["dir"] == 1:
                        p["stop"] = max(p["stop"], bar["ll_exit"])
                    else:
                        p["stop"] = min(p["stop"], bar["hh_exit"])
                    p["last"] = bar["close"]
                    mtm += p["risk_usd"] * p["dir"] * (bar["close"] - p["entry"]) / p["stop_dist"]

            # 3) signal on today's close -> enter tomorrow's open
            if sym not in open_pos and not math.isnan(bar["hh_entry"]):
                if bar["close"] > bar["hh_entry"]:
                    pending[sym] = 1
                elif bar["close"] < bar["ll_entry"]:
                    pending[sym] = -1
        curve.append((day, equity + mtm))

    eq = pd.Series(dict(curve))
    return eq, pd.DataFrame(trades), std_skips, std_checks


def stats(eq, tr, label):
    if len(eq) < 2 or tr.empty:
        return f"{label}: no trades"
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    daily = eq.resample("D").last().ffill().pct_change().dropna()
    sharpe = daily.mean() / daily.std() * math.sqrt(365) if daily.std() > 0 else 0
    wins = tr[tr.pnl > 0]
    losses = tr[tr.pnl <= 0]
    pf = wins.pnl.sum() / -losses.pnl.sum() if len(losses) and losses.pnl.sum() != 0 else float("inf")
    return (f"{label:<22} CAGR {cagr*100:6.2f}%  MaxDD {dd*100:6.1f}%  Sharpe {sharpe:5.2f}  "
            f"PF {pf:4.2f}  trades {len(tr):4d}  win {len(wins)/len(tr)*100:4.1f}%  "
            f"avgR {tr.r.mean():5.2f}")


def main():
    folder = sys.argv[1]
    data = {}
    for sym in MARKETS:
        path = os.path.join(folder, f"{sym}.json")
        if os.path.exists(path):
            df = prep(load(path))
            df["atr_prev"] = df["atr"].shift(1)
            data[sym] = df.dropna(subset=["atr_prev", "hh_entry"])
    eq, tr, skips, checks = run(data)
    print(f"Markets: {len(data)}   Period: {eq.index[0].date()} -> {eq.index[-1].date()}")
    print(f"Start ${START_EQUITY:.0f} -> end ${eq.iloc[-1]:.0f}")
    print(stats(eq, tr, "FULL PERIOD"))
    for a, b in [("2001", "2007"), ("2008", "2012"), ("2013", "2019"), ("2020", "2026")]:
        e = eq[a:b]
        t = tr[(tr.close >= a) & (tr.close <= f"{b}-12-31")]
        print(stats(e, t, f"  {a}-{b}"))
    print("\nPer-market total R (after costs):")
    print(tr.groupby("sym").r.agg(["count", "sum", "mean"]).round(2).sort_values("sum").to_string())
    print(f"\nStandard account @ $1000: {skips}/{checks} entries "
          f"({skips/checks*100:.0f}%) would need >1.5x the intended risk at 0.01 lot.")
    yearly = eq.resample("YE").last().pct_change().dropna()
    print("\nCalendar-year returns:")
    print(" ".join(f"{d.year}:{v*100:+.1f}%" for d, v in yearly.items()))


if __name__ == "__main__":
    main()
