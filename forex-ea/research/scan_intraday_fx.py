"""
Round-2 intraday FX scan on Dukascopy hourly BID candles, 7 USD majors.

Exploration used 2016-2026 only; 2010-2015 was held back and first opened for the
pre-registered candidates in holdout_tests.py. The 2010-2015 column below was
computed afterwards, for completeness. All numbers are GROSS pips per trade
unless marked; compare them with XM's round-trip cost (Standard ~2.0-2.8 pips,
Ultra Low ~1.1-1.9 pips including slippage).

Usage: python3 scan_intraday_fx.py <data-folder>
"""
import os
import sys

import numpy as np
import pandas as pd

import duka
import volbreak as vb

ROOT = os.path.join(sys.argv[1], "dukascopy")
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"]
INV = {"USDJPY", "USDCHF", "USDCAD"}
COST_STD = {"EURUSD": 2.0, "GBPUSD": 2.5, "USDJPY": 2.2, "USDCHF": 2.4, "USDCAD": 2.6, "AUDUSD": 2.2, "NZDUSD": 2.8}
BLOCKS = [(2010, 2015), (2016, 2020), (2021, 2026)]
pip = lambda p: 0.01 if p.endswith("JPY") else 0.0001

DATA = {}
for _p in PAIRS:
    _h = duka.load_hourly(ROOT, _p).loc["2010":"2026"]
    _h.index = _h.index.tz_localize("UTC").tz_convert("Europe/London")
    DATA[_p] = _h


def section(t):
    print(f"\n{'=' * 100}\n{t}\n{'=' * 100}")


def blocks(s, unit="pips"):
    out = []
    for a, b in BLOCKS:
        x = s[(s.index.year >= a) & (s.index.year <= b)].dropna()
        if len(x) < 10:
            out.append(f"{a}-{b % 100:02d}: n/a")
            continue
        out.append(f"{a}-{b % 100:02d}: {x.mean():+6.2f} {unit} (t={x.mean()/x.std()*np.sqrt(len(x)):+5.2f}, n={len(x)})")
    return " | ".join(out)


def pooled(trades):
    return pd.concat([t for t in trades.values() if len(t)]).sort_index()


def hour_of_day():
    section("1. Hour-of-day seasonality: currency vs USD, London hour, bp (cells with |t|>2.5)")
    rets = {}
    for p, h in DATA.items():
        r = np.log(h.close).diff()
        r = r[h.index.to_series().diff() == pd.Timedelta(hours=1)]
        rets[p[:3] if p not in INV else p[3:]] = -r if p in INV else r
    R = pd.DataFrame(rets)
    for a, b in BLOCKS:
        X = R[(R.index.year >= a) & (R.index.year <= b)]
        g = X.groupby(X.index.hour)
        mu, t = g.mean() * 1e4, g.mean() / g.std() * np.sqrt(g.count())
        cells = [f"{c}@{hr}h:{mu.loc[hr, c]:+.1f}" for hr in mu.index for c in mu.columns
                 if abs(t.loc[hr, c]) > 2.5 and hr not in (21, 22, 23)]
        roll = [f"{c}@{hr}h:{mu.loc[hr, c]:+.1f}" for hr in (21, 23) for c in mu.columns if abs(t.loc[hr, c]) > 2.5]
        print(f"{a}-{b}: tradable hours {' '.join(cells) or 'none'}\n"
              f"           rollover-hour artefacts (bid moves as spreads widen, NOT tradable): {' '.join(roll)}")


def gotobi():
    section("2. Gotobi / Tokyo-fix: USDJPY 07:00->10:00 JST on gotobi days (pips)")
    h = DATA["USDJPY"]
    ut = h.index.tz_convert("UTC")
    o = pd.Series(h.open.values, index=ut)
    days = pd.DatetimeIndex(sorted(set((ut + pd.Timedelta(hours=9)).normalize().tz_localize(None))))
    days = days[days.dayofweek < 5]
    res_g, res_o = {}, {}
    for d in days:
        targets = []
        for k in (5, 10, 15, 20, 25):
            t = pd.Timestamp(d.year, d.month, k)
            while t.dayofweek >= 5:
                t -= pd.Timedelta(days=1)
            targets.append(t)
        targets.append(d + pd.offsets.BMonthEnd(0))
        t0 = (d + pd.Timedelta(hours=7 - 9)).tz_localize("UTC")
        t1 = (d + pd.Timedelta(hours=10 - 9)).tz_localize("UTC")
        if t0 in o.index and t1 in o.index:
            v = (o[t1] - o[t0]) * 100
            (res_g if d in targets else res_o)[d] = v
    print("gotobi days: " + blocks(pd.Series(res_g)))
    print("other days : " + blocks(pd.Series(res_o)))


def spike_fade():
    section("3. Fade hourly spikes > 4 sd (London 07-19h)")
    for H in (1, 3, 6):
        tr = {}
        for p, h in DATA.items():
            r = h.close.diff()
            sd = r.rolling(480).std().shift(1)
            ev = (r.abs() > 4 * sd) & (h.index.hour >= 7) & (h.index.hour <= 19)
            tr[p] = ((-np.sign(r) * (h.close.shift(-H) - h.close))[ev] / pip(p))
        print(f"hold {H}h, all pairs: " + blocks(pooled(tr)))
        print(f"          USDJPY  : " + blocks(tr["USDJPY"]))


def weekend_gap():
    section("4. Weekend gap: the 'edge' is the bid dropping while spreads blow out at the Sunday open")
    tr, bias = {}, {}
    for p, h in DATA.items():
        idx = h.index
        starts = idx[idx.to_series().diff() > pd.Timedelta(hours=24)]
        g, fades = {}, {}
        for s in starts:
            i = idx.get_loc(s)
            gap = (h.open.iloc[i] - h.close.iloc[i - 1]) / pip(p)
            g[s] = gap
            if abs(gap) >= 10:
                later = h.loc[s: s + pd.Timedelta(hours=14)]
                fades[s] = -np.sign(gap) * (later.close.iloc[-1] - h.open.iloc[i]) / pip(p)
        tr[p], bias[p] = pd.Series(fades), pd.Series(g)
    allg = pooled(bias)
    print("share of NEGATIVE Sunday-open gaps on BOTH XXXUSD and USDXXX pairs: " +
          " | ".join(f"{a}-{b % 100:02d}: {(allg[(allg.index.year >= a) & (allg.index.year <= b)] < 0).mean():.2f}"
                     for a, b in BLOCKS) + "  (0.50 expected if real)")
    print("naive gap fade (bid-only data): " + blocks(pooled(tr)))


def london_breakout():
    section("5. London breakout of the Asian range (00-07h), stop = other side, exit 16:00")
    tr = {}
    for p, h in DATA.items():
        res = {}
        for day, g in h.groupby(h.index.date):
            asia, sess = g[g.index.hour < 7], g[(g.index.hour >= 7) & (g.index.hour < 16)]
            if len(asia) < 5 or len(sess) < 5:
                continue
            hi, lo = asia.high.max(), asia.low.min()
            pos = 0
            for t, b in sess.iterrows():
                if pos == 0:
                    if t.hour >= 11:
                        break
                    up, dn = b.high > hi, b.low < lo
                    if up and dn:
                        break
                    if up or dn:
                        pos, entry, stop = (1, hi, lo) if up else (-1, lo, hi)
                        if (pos == 1 and b.low <= stop) or (pos == -1 and b.high >= stop):
                            res[t] = -(hi - lo) / pip(p)
                            pos = 9
                            break
                    continue
                if (pos == 1 and b.low <= stop) or (pos == -1 and b.high >= stop):
                    res[t] = -(hi - lo) / pip(p)
                    pos = 9
                    break
            if pos in (1, -1):
                res[sess.index[-1]] = pos * (sess.close.iloc[-1] - entry) / pip(p)
        tr[p] = pd.Series(res)
    print("all pairs: " + blocks(pooled(tr)))
    for p in ("GBPUSD", "USDJPY"):
        print(f"{p}   : " + blocks(tr[p]))


def intraday_momentum():
    section("6. Intraday momentum: sign(07->12h) traded 12->16h")
    tr = {}
    for p, h in DATA.items():
        res = {}
        for day, g in h.groupby(h.index.date):
            try:
                o7 = g.open[g.index.hour == 7].iloc[0]
                o12 = g.open[g.index.hour == 12].iloc[0]
                c15 = g.close[g.index.hour == 15].iloc[0]
            except IndexError:
                continue
            res[g.index[0]] = np.sign(o12 - o7) * (c15 - o12) / pip(p)
        tr[p] = pd.Series(res)
    print("all pairs: " + blocks(pooled(tr)))


def xs_reversal_hourly():
    section("7. Cross-sectional reversal with synchronous hourly closes (bp per unit, before ~1.5-2bp cost)")
    close = pd.DataFrame({p: DATA[p].close for p in PAIRS}).ffill()
    ccy = np.log(pd.DataFrame({p: (1 / close[p] if p in INV else close[p]) for p in PAIRS}))
    for H in (4, 8, 24):
        lb, fwd = ccy.diff(H), ccy.shift(-H) - ccy
        snaps = ccy.index[ccy.index.hour == 15]
        vals = {}
        for t in snaps:
            s, f = lb.loc[t], fwd.loc[t]
            if s.isna().any() or f.isna().any():
                continue
            r = s.rank()
            vals[t] = (f[r.nsmallest(2).index].mean() - f[r.nlargest(2).index].mean()) / 2 * 1e4
        print(f"lookback/hold {H:2d}h @15:00: " + blocks(pd.Series(vals), "bp"))


def month_end_fix():
    section("8. Month-end London 4pm fix: USD basket during the 15:00-16:00 hour of the last business day (bp, + = USD down)")
    close = pd.DataFrame({p: DATA[p].close for p in PAIRS}).ffill()
    ccy = np.log(pd.DataFrame({p: (1 / close[p] if p in INV else close[p]) for p in PAIRS}))
    step = (ccy.shift(-1) - ccy).mean(axis=1) * 1e4
    vals = {}
    for (y, m), g in step.groupby([step.index.year, step.index.month]):
        last = sorted(set(g.index.date))[-1]
        gl = g[(g.index.date == last) & (g.index.hour == 15)]
        if len(gl):
            vals[gl.index[0]] = gl.iloc[0]
    print("fix hour: " + blocks(pd.Series(vals), "bp"))


def vol_breakout():
    section("9. Daily volatility breakout k=0.8 (see volbreak.py), exit before rollover")
    tr = {p: vb.backtest(h, 0.8, None, 20, pip=pip(p)).pips for p, h in DATA.items()}
    print("all pairs: " + blocks(pooled(tr)))
    for p in PAIRS:
        print(f"{p}   : " + blocks(tr[p]))


def asian_fade():
    section("10. Asian-session Bollinger fade ('night scalper'), 23-05h entries, TP = mean, exit 07:00")
    tr = {}
    for p, h in DATA.items():
        c = h.close
        m, s = c.rolling(20).mean(), c.rolling(20).std()
        z = ((c - m) / s).values
        cv, mv, sv, hi, lo, hrs = c.values, m.values, s.values, h.high.values, h.low.values, h.index.hour
        out, i, n = {}, 0, len(h)
        while i < n - 1:
            if hrs[i] in (23, 0, 1, 2, 3, 4) and not np.isnan(z[i]) and abs(z[i]) > 2.0:
                d = -np.sign(z[i])
                entry, tp, sl = cv[i], mv[i], cv[i] - d * 3 * sv[i]
                j, res = i + 1, None
                while j < n:
                    if (d > 0 and lo[j] <= sl) or (d < 0 and hi[j] >= sl):
                        res = (sl - entry) * d
                        break
                    if (d > 0 and hi[j] >= tp) or (d < 0 and lo[j] <= tp):
                        res = (tp - entry) * d
                        break
                    if hrs[j] == 7:
                        res = (cv[j] - entry) * d
                        break
                    j += 1
                if res is not None:
                    out[h.index[i]] = res / pip(p)
                i = j + 1
            else:
                i += 1
        tr[p] = pd.Series(out)
    print("all pairs: " + blocks(pooled(tr)) + "   (night spreads at XM are wider than daytime)")


def friday_fade():
    section("11. Friday-afternoon fade of the week's move (12:00 -> 20:00 Friday)")
    tr = {}
    for p, h in DATA.items():
        iso = h.index.isocalendar()
        res = {}
        for _, g in h.groupby([iso.year.values, iso.week.values]):
            mon, fri = g[g.index.dayofweek == 0], g[g.index.dayofweek == 4]
            f12, f20 = fri[fri.index.hour == 12], fri[fri.index.hour == 20]
            if len(mon) < 5 or len(f12) == 0 or len(f20) == 0:
                continue
            wk = f12.open.iloc[0] - mon.open.iloc[0]
            res[f12.index[0]] = -np.sign(wk) * (f20.open.iloc[0] - f12.open.iloc[0]) / pip(p)
        tr[p] = pd.Series(res)
    print("all pairs: " + blocks(pooled(tr)))


if __name__ == "__main__":
    for f in (hour_of_day, gotobi, spike_fade, weekend_gap, london_breakout, intraday_momentum,
              xs_reversal_hourly, month_end_fix, vol_breakout, asian_fade, friday_fade):
        f()
