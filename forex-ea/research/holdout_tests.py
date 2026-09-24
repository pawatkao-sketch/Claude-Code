"""
Pre-registered holdout tests for the only intraday candidates that looked promising
in the 2016-2026 exploration data. The rule was frozen BEFORE the holdout years
(2004-2015) were loaded:

  daily volatility breakout, K = 0.8 x yesterday's range, first trigger wins,
  exit at 20:59 London (never held through the rollover, so no swap).

Candidates: USDJPY (recurring intraday trend in exploration), XAUUSD (gold), and
XAGUSD (silver) as an independent sister-market check of the gold result.

Usage: python3 holdout_tests.py <data-folder>
"""
import os
import sys

import numpy as np
import pandas as pd

import duka
import volbreak as vb

ROOT = os.path.join(sys.argv[1], "dukascopy")
BLOCKS = [("2004", "2009", "HOLDOUT"), ("2010", "2015", "HOLDOUT"), ("2016", "2021", "explore"), ("2022", "2026", "explore")]
# symbol: (price units per "pip" used by volbreak, round-trip cost in price units =
#          XM spread + slippage on the stop entry, conservative)
CANDIDATES = {"USDJPY": (0.01, 0.024), "XAUUSD": (1.0, 0.65), "XAGUSD": (1.0, 0.05)}


def load(sym):
    h = duka.load_hourly(ROOT, sym)
    h.index = h.index.tz_localize("UTC").tz_convert("Europe/London")
    return h


def to_bp(t, h, pip, cost):
    px = h.close.reindex(t.index, method="ffill")
    return t.assign(gross_bp=t.pips * pip / px * 1e4, net_bp=(t.pips * pip - cost) / px * 1e4)


def report(t):
    for a, b, tag in BLOCKS:
        x = t.loc[a:b]
        if len(x) < 30:
            continue
        tg = x.gross_bp.mean() / x.gross_bp.std() * np.sqrt(len(x))
        tn = x.net_bp.mean() / x.net_bp.std() * np.sqrt(len(x))
        print(f"  {a}-{b} [{tag:7}] n={len(x):4d} gross {x.gross_bp.mean():+6.1f}bp (t={tg:+5.2f})  "
              f"net {x.net_bp.mean():+6.1f}bp (t={tn:+5.2f})  long {x[x.dir > 0].gross_bp.mean():+6.1f} "
              f"short {x[x.dir < 0].gross_bp.mean():+6.1f}")
    trimmed = t.net_bp.sort_values().iloc[:-max(int(len(t) * 0.01), 1)]
    print(f"  ALL: net {t.net_bp.mean():+.1f}bp/trade; without the best 1% of trades {trimmed.mean():+.1f}bp; "
          f"median {t.net_bp.median():+.1f}bp; win rate {(t.net_bp > 0).mean():.2f}")


def main():
    for sym, (pip, cost) in CANDIDATES.items():
        h = load(sym)
        print(f"\n### {sym} volatility breakout k=0.8 (round-trip cost {cost} price units)")
        report(to_bp(vb.backtest(h, 0.8, None, 20, pip=pip), h, pip, cost))
    h = load("XAUUSD")
    pip, cost = CANDIDATES["XAUUSD"]
    print("\n### Gold robustness (whole sample; net bp per trade by block)")
    for label, k, sm, leh in (("k=0.6", 0.6, None, 20), ("k=0.7", 0.7, None, 20), ("k=0.9", 0.9, None, 20),
                              ("k=1.0", 1.0, None, 20), ("stop 1x k*range", 0.8, 1.0, 20),
                              ("stop 2x k*range (EA)", 0.8, 2.0, 20), ("entries until 16:00", 0.8, None, 16)):
        t = to_bp(vb.backtest(h, k, sm, leh, pip=pip), h, pip, cost)
        print(f"  {label:<22} " + " ".join(f"{a[2:]}-{b[2:]}:{t.net_bp.loc[a:b].mean():+5.1f}" for a, b, _ in BLOCKS))
    t = to_bp(vb.backtest(h, 0.8, 2.0, 20, pip=pip), h, pip, cost)
    print("  EA default, net bp/trade by year: " +
          " ".join(f"{y}:{v:+.0f}" for y, v in t.net_bp.groupby(t.index.year).mean().items()))
    print("  NOTE: XAGUSD 2004-2009 Dukascopy data is sparse and unreliable (few trades, extreme values).")

    print("\n### What EA module C (gold, k=0.8, stop 2x) would have made on $1,000, compounded, after costs")
    t = vb.backtest(h, 0.8, 2.0, 20, pip=pip)
    t["R"] = (t.pips * pip - cost) / (2.0 * 0.8 * t.range_pips * pip)     # result in units of the stop distance
    for start in ("2010", "2016"):
        x = t.loc[start:]
        yrs = (x.index[-1] - x.index[0]).days / 365.25
        for risk in (0.005, 0.01, 0.03):
            eq = 1000 * (1 + risk * x.R).cumprod()
            cagr = (eq.iloc[-1] / 1000) ** (1 / yrs) - 1
            print(f"  from {start}, risk {risk*100:.1f}%/trade: end ${eq.iloc[-1]:5.0f}, CAGR {cagr*100:+5.2f}%, "
                  f"max drawdown {(eq / eq.cummax() - 1).min()*100:6.1f}%, ~${1000*cagr:+.0f}/yr")


if __name__ == "__main__":
    main()
