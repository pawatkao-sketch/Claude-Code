"""
Sanity-check backtest of the EA's Module A (index pullback / RSI(2) dip-buy).

Rules (Connors-style, textbook parameters, not optimised here):
  - Long only. Regime: close > SMA(200).
  - Entry: RSI(2) < 10 on the daily close -> buy next open.
  - Exit: close > SMA(5) -> sell next open, or after 10 bars, or 3*ATR(20) stop.
Costs: spread + 0.02*ATR slippage per side + CFD financing (swap) per day held.

Usage: python3 backtest_pullback.py <dir-with-yahoo-json-files>
"""
import math
import os
import sys

import pandas as pd

from backtest_trend import MARKETS, load

RSI_N, RSI_BUY, SMA_TREND, SMA_EXIT, MAX_BARS, STOP_ATR, ATR_N = 2, 10, 200, 5, 10, 3.0, 20
SLIPPAGE_ATR = 0.02


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def trades_for(df, spread, swap):
    c = df["close"]
    sma_t, sma_x, r = c.rolling(SMA_TREND).mean(), c.rolling(SMA_EXIT).mean(), rsi(c, RSI_N)
    tr = pd.concat([df.high - df.low, (df.high - c.shift()).abs(),
                    (df.low - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_N).mean()
    o, l, cl = df.open.values, df.low.values, c.values
    out, pos, n = [], None, len(df)
    for i in range(SMA_TREND + 1, n - 1):
        if pos is None:
            if cl[i] > sma_t.iloc[i] and r.iloc[i] < RSI_BUY:
                a = atr.iloc[i]
                pos = (i + 1, o[i + 1] + spread / 2 + SLIPPAGE_ATR * a, a)
            continue
        j, e, a = pos
        stop = e - STOP_ATR * a
        if l[i] <= stop:
            x, when = min(o[i], stop), i
        elif cl[i] > sma_x.iloc[i] or i - j >= MAX_BARS:
            x, when = o[i + 1], i + 1
        else:
            continue
        x -= spread / 2 + SLIPPAGE_ATR * a
        days = (df.index[when] - df.index[j]).days
        out.append(dict(open=df.index[j], close=df.index[when],
                        ret=(x - e) / e - swap * days / 365,          # return on notional
                        r=((x - e) - swap * days / 365 * e) / (STOP_ATR * a)))  # in R
        pos = None
    return pd.DataFrame(out)


def equity_curve(t, risk_pct, start=1000.0):
    eq, pts = start, []
    for when, r in t["r"].items():
        eq += eq * risk_pct * r
        pts.append((when, eq))
    return pd.Series(dict(pts))


def main():
    folder = sys.argv[1]
    for sym in ["^GSPC", "^GDAXI", "^N225", "GC=F", "EURUSD=X", "USDJPY=X", "AUDUSD=X"]:
        spread, swap = MARKETS[sym]
        t = trades_for(load(os.path.join(folder, f"{sym}.json")), spread, swap)
        t = t.set_index("close")
        for a, b in [("2001", "2012"), ("2013", "2026")]:
            s = t[a:b]
            pf = s.r[s.r > 0].sum() / -s.r[s.r <= 0].sum()
            print(f"{sym:<9} {a}-{b} trades {len(s):3d}  win {(s.r > 0).mean()*100:4.1f}%  "
                  f"PF {pf:4.2f}  avgR {s.r.mean():+.3f}")
    # sizing table for the one market that holds up
    spread, swap = MARKETS["^GSPC"]
    df = load(os.path.join(folder, "^GSPC.json"))
    t = trades_for(df, spread, swap).set_index("close")
    yrs = (t.index[-1] - t.index[0]).days / 365.25
    print(f"\nUS500 pullback, $1000 start, {t.index[0].year}-{t.index[-1].year}:")
    for risk in [0.005, 0.01, 0.02, 0.03]:
        eq = equity_curve(t, risk)
        cagr = (eq.iloc[-1] / 1000) ** (1 / yrs) - 1
        dd = (eq / eq.cummax() - 1).min()
        print(f"  risk {risk*100:.1f}%/trade -> end ${eq.iloc[-1]:7.0f}  CAGR {cagr*100:5.2f}%  "
              f"MaxDD(closed) {dd*100:6.1f}%  ${1000*cagr:.0f}/yr on $1000")
    c = df.close
    bh = (c.iloc[-1] / c.iloc[0]) ** (365.25 / (c.index[-1] - c.index[0]).days) - 1
    print(f"  Buy-and-hold S&P 500 index (price only, no dividends): CAGR {bh*100:.2f}%")


if __name__ == "__main__":
    main()
