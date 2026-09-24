"""
Why "95% win-rate" grid / martingale EAs look great and then blow up.

A typical commercial design, simulated on real EURUSD hourly data:
  - open a 0.01-lot (1,000 unit) BUY; every 20 pips against the basket add a new
    BUY at 1.5x the previous size (up to 12 levels);
  - close the whole basket when it is +10 pips from its average price;
  - $1,000 account; the broker stops you out when equity falls to 20% of margin
    (1:500 leverage), or when all 12 levels are used and price keeps going.
  - costs: 1.7 pip spread per position, no swap (flattering to the EA).
We start a fresh $1,000 account on the first day of every month 2016-2025 and run
it for 12 months, alternating BUY-only and SELL-only versions.

Usage: python3 grid_martingale_demo.py <data-folder>      (layout: see download_data.py)
"""
import os
import sys

import numpy as np
import pandas as pd

import duka

STEP, TP, MULT, LEVELS = 20, 10, 1.5, 12
LOT0, SPREAD, LEV, STOPOUT = 1000.0, 1.7, 500.0, 0.2
PIP = 0.0001


def run(h, start, side):
    """Walk each hourly bar along a plausible path (open-low-high-close for up bars,
    open-high-low-close for down bars) so fills and take-profits happen in order."""
    eq0 = bal = 1000.0
    g = h.loc[start: start + pd.DateOffset(months=12)]
    basket = []           # list of (fill price incl. spread, units)
    cycles = 0
    worst_dd = 0.0

    def state(price):
        units = sum(u for _, u in basket)
        avg = sum(p * u for p, u in basket) / units
        return units, avg, side * (price - avg) * units

    for t, b in g.iterrows():
        path = [b.open, b.low, b.high, b.close] if b.close >= b.open else [b.open, b.high, b.low, b.close]
        if not basket:
            basket.append((b.open + side * SPREAD * PIP, LOT0))
        prev = path[0]
        for target in path[1:]:
            price = prev
            step = PIP * 0.5 * (1 if target > prev else -1)
            n = int(abs(target - prev) / abs(step)) if step else 0
            for _ in range(n + 1):
                if not basket:
                    basket.append((price + side * SPREAD * PIP, LOT0))
                last_fill = basket[-1][0] - side * SPREAD * PIP
                if len(basket) < LEVELS and side * (price - last_fill) <= -STEP * PIP:
                    basket.append((price + side * SPREAD * PIP, basket[-1][1] * MULT))
                units, avg, floating = state(price)
                margin = units * price / LEV
                worst_dd = min(worst_dd, (bal + floating) / eq0 - 1)
                if bal + floating <= STOPOUT * margin or bal + floating <= 0:
                    return dict(start=start, side=side, blown=True, end=max(bal + floating, 0.0),
                                cycles=cycles, wins=cycles, worst_dd=-1.0, when=t)
                if side * (price - avg) >= TP * PIP:
                    bal += floating
                    cycles += 1
                    basket = []
                price = min(price + step, target) if step > 0 else max(price + step, target)
            prev = target
    if basket:
        units, avg, floating = state(g.close.iloc[-1])
        bal += floating
    return dict(start=start, side=side, blown=False, end=bal, cycles=cycles, wins=cycles,
                worst_dd=worst_dd, when=None)


def main(folder):
    h = duka.load_hourly(folder, "EURUSD").loc["2016":"2026"]
    res = []
    for i, start in enumerate(pd.date_range("2016-01-01", "2025-09-01", freq="MS")):
        res.append(run(h, start, 1 if i % 2 == 0 else -1))
    r = pd.DataFrame(res)
    surv = r[~r.blown]
    print(f"Accounts started: {len(r)}")
    print(f"Blown up within 12 months: {r.blown.sum()} ({r.blown.mean()*100:.0f}%)")
    print(f"Survivors: median end balance ${surv.end.median():.0f}, "
          f"worst intra-year drawdown among survivors {surv.worst_dd.min()*100:.0f}%")
    print(f"Basket win rate before ruin: {r.wins.sum() / max(r.cycles.sum(), 1) * 100:.1f}% "
          f"(every closed basket is a 'win' - losses only appear as a blow-up)")
    avg_all = r.end.mean()
    print(f"Average ending balance across ALL starts (incl. blow-ups): ${avg_all:.0f} from $1000")


if __name__ == "__main__":
    main(os.path.join(sys.argv[1], "dukascopy"))
