"""
Round-2 daily-frequency FX strategy scan (Yahoo daily closes + FRED rates).

Every result is net of an XM-style cost model (see fxlab.py): spread on every
trade, plus overnight swap = interest differential -/+ a 1% p.a. broker markup
per side (2% for emerging-market currencies). Splits: 2006-2014 vs 2015-2026.

Usage: python3 scan_daily_fx.py <data-folder>      (layout: see download_data.py)
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

import fxlab as fx

ROOT = sys.argv[1]
YD, FD = os.path.join(ROOT, "yahoo"), os.path.join(ROOT, "fred")
IS, OOS = ("2003", "2014"), ("2015", "2026")


def section(t):
    print(f"\n{'=' * 100}\n{t}\n{'=' * 100}")


def xs_strategies():
    section("A. Cross-sectional currency strategies, 9 G10 currencies vs USD, 10% vol target")
    px, ret, diff, spread = fx.currency_panel(YD, FD)
    me = fx.month_ends(px.index)
    fri = px.index[px.index.dayofweek == 4]
    res = {}

    def report(name, w, markup=fx.SWAP_MARKUP, tv=0.10):
        r = fx.run_weights(w, ret, diff, spread, markup=markup, target_vol=tv).loc["2003":]
        parts = r[["price", "carry", "swap_markup", "trading"]].sum() / (len(r) / 252) * 100
        print(f"{name:<34} IS Sh {fx.sharpe(r.net[IS[0]:IS[1]]):5.2f} | OOS Sh {fx.sharpe(r.net[OOS[0]:OOS[1]]):5.2f} | "
              f"{fx.perf(r.net, '')[35:]} | %/yr: price {parts.price:+5.2f} carry {parts.carry:+5.2f} "
              f"markup {parts.swap_markup:+5.2f} trading {parts.trading:+6.2f}")
        return r

    print(f"panel {px.index[0].date()} -> {px.index[-1].date()}")
    res["carry"] = report("Carry: long top-3 / short bottom-3", fx.rank_weights(diff, 3, 3, me))
    for mk in (0.0, 0.005, 0.02):
        report(f"  carry with markup {mk*100:.1f}%", fx.rank_weights(diff, 3, 3, me), markup=mk)
    for lb in (21, 63, 126, 252):
        res[f"mom{lb}"] = report(f"Momentum {lb}d, 3/3 monthly", fx.rank_weights(px.pct_change(lb), 3, 3, me))
    res["rev5"] = report("Reversal 5d, 3/3 weekly", fx.rank_weights(-px.pct_change(5), 3, 3, fri))
    report("Reversal 1d, 3/3 daily (see note)", fx.rank_weights(-px.pct_change(1), 3, 3))
    res["val"] = report("Value proxy (-5y return), monthly", fx.rank_weights(-px.pct_change(1260), 3, 3, me))
    vol = ret.rolling(63).std() * math.sqrt(252)
    w = (np.sign(px.pct_change(252)) * (0.10 / vol) / len(fx.CCY)).loc[me].reindex(px.index).ffill()
    report("TSMOM 12m per currency vs USD", w, tv=None)
    avgd = diff.mean(axis=1)
    w = pd.DataFrame(np.sign(avgd).values[:, None] * np.ones((1, len(fx.CCY))) / len(fx.CCY),
                     index=px.index, columns=px.columns).loc[me].reindex(px.index).ffill()
    report("Dollar carry", w)
    combo = (res["carry"].net + res["mom63"].net + res["val"].net) / 3
    print(f"{'Combo carry+momentum+value':<34} IS Sh {fx.sharpe(combo[IS[0]:IS[1]]):5.2f} | "
          f"OOS Sh {fx.sharpe(combo[OOS[0]:OOS[1]]):5.2f} | {fx.perf(combo, '')[35:]}")
    print("Note: the 1-day reversal's large gross 'price' profit is an artefact of Yahoo's non-synchronous\n"
          "daily closes; with synchronous hourly data (scan_intraday_fx.py) it shrinks to ~1bp/day.")


def load_rates_ext():
    rates = fx.load_rates(FD)
    for cc in ("MX", "ZA", "PL", "HU"):
        s = pd.read_csv(os.path.join(FD, f"IR3_{cc}.csv"))
        s.columns = ["date", "rate"]
        s["date"] = pd.to_datetime(s["date"])
        s["rate"] = pd.to_numeric(s["rate"], errors="coerce")
        rates[cc] = s.set_index("date")["rate"].shift(1).reindex(rates.index) / 100.0
    return rates


def per_pair_strategies():
    section("B. Single-pair daily strategies on 30 G10 pairs + 4 EM pairs (Sharpe on notional)")
    rates = load_rates_ext()
    code = {c: v[2] for c, v in fx.CCY.items()}
    code.update(USD="US", MXN="MX", ZAR="ZA", PLN="PL", HUF="HU")
    em_spread = {"USDMXN": 0.035, "USDZAR": 0.06, "USDPLN": 0.08, "USDHUF": 0.09}

    def rdiff(pair, idx):
        r = rates.reindex(idx, method="ffill").ffill()
        return r[code[pair[:3]]] - r[code[pair[3:]]]

    def sh(x):
        x = x.dropna()
        return x.mean() / x.std() * math.sqrt(252) if x.std() > 0 else 0.0

    rows, ct_nets = [], {}
    for p in list(fx.SPREAD_PCT) + list(em_spread):
        c = fx.load_close(YD, p).loc["2004":]
        d = rdiff(p, c.index)
        em = p in em_spread
        spread = em_spread.get(p, fx.SPREAD_PCT.get(p))
        markup = 0.02 if em else 0.01
        row = dict(pair=p)
        # carry + 200-day trend filter
        sma = c.rolling(200).mean()
        pos = pd.Series(0.0, index=c.index)
        pos[(d > 0.005) & (c > sma)] = 1.0
        pos[(d < -0.005) & (c < sma)] = -1.0
        net, _ = fx.run_positions(pos, c, d, spread, markup=markup)
        vol = c.pct_change().rolling(63).std() * math.sqrt(252)
        ct_nets[p] = net * (0.10 / vol.shift(1)).clip(upper=5)
        row.update(carry_trend_IS=sh(net[:"2014"]), carry_trend_OOS=sh(net["2015":]))
        if not em:
            lr = np.log(c)
            z = ((lr - lr.rolling(20).mean()) / lr.rolling(20).std()).values
            posz = np.zeros(len(c))
            cur = age = 0
            for i in range(len(c)):
                if cur != 0:
                    age += 1
                    if (cur > 0 and z[i] >= 0) or (cur < 0 and z[i] <= 0) or age >= 10:
                        cur = 0
                if cur == 0 and not np.isnan(z[i]):
                    cur, age = (1, 0) if z[i] < -2 else ((-1, 0) if z[i] > 2 else (0, 0))
                posz[i] = cur
            netz, _ = fx.run_positions(pd.Series(posz, index=c.index), c, d, spread)
            r2 = lr.diff(2)
            sig = (-np.sign(r2) * (r2.abs() > r2.rolling(100).std())).fillna(0)
            netr, _ = fx.run_positions(sig.rolling(2).mean().clip(-1, 1), c, d, spread)
            row.update(zscore_IS=sh(netz[:"2014"]), zscore_OOS=sh(netz["2015":]),
                       rev2d_IS=sh(netr[:"2014"]), rev2d_OOS=sh(netr["2015":]))
        rows.append(row)
    df = pd.DataFrame(rows).set_index("pair").round(2)
    print(df.to_string())
    for col in ("carry_trend", "zscore", "rev2d"):
        both = ((df[f"{col}_IS"] > 0.3) & (df[f"{col}_OOS"] > 0.3)).sum()
        print(f"{col:<12}: positive IS {int((df[f'{col}_IS'] > 0).sum())}, positive OOS "
              f"{int((df[f'{col}_OOS'] > 0).sum())}, Sharpe > 0.3 in BOTH halves: {both} of {df[f'{col}_IS'].notna().sum()}")
    port = pd.DataFrame(ct_nets).loc["2006":].fillna(0)
    for name, cols in (("carry+trend G10 portfolio", [c for c in port if c not in em_spread]),
                       ("carry+trend EM portfolio", list(em_spread))):
        x = port[cols].mean(axis=1)
        print(f"{name:<28} IS Sh {sh(x[:'2014']):5.2f} | OOS Sh {sh(x['2015':]):5.2f} | {fx.perf(x, '')[35:]}")


def calendar():
    section("C. Calendar and flow effects (USD vs 6-currency basket, bp)")
    px, ret, diff, spread = fx.currency_panel(YD, FD, start="2001-01-01")
    basket = ret[["EUR", "GBP", "JPY", "CHF", "CAD", "AUD"]].mean(axis=1)

    def idx(sym):
        r = json.load(open(os.path.join(YD, f"IDX_{sym}.json")))["chart"]["result"][0]
        s = pd.Series(r["indicators"]["quote"][0]["close"],
                      index=pd.to_datetime(r["timestamp"], unit="s").normalize()).dropna()
        return s[~s.index.duplicated(keep="last")]

    eq = pd.DataFrame({k: idx(k) for k in ("^GSPC", "^STOXX50E", "^FTSE", "^N225", "^AXJO", "^GSPTSE")}
                      ).reindex(px.index).ffill()
    dates = px.index
    ym = pd.Series(dates.year * 100 + dates.month, index=dates)
    rows, tom = [], pd.Series(False, index=dates)
    for _, g in pd.Series(dates, index=dates).groupby(ym.values):
        d = list(g.values)
        tom.loc[d[:2]] = True
        if len(d) < 10:
            continue
        start = dates[max(dates.get_loc(d[0]) - 1, 0)]
        us = eq["^GSPC"].loc[d[-2]] / eq["^GSPC"].loc[start] - 1
        fo = (eq.drop(columns="^GSPC").loc[d[-2]] / eq.drop(columns="^GSPC").loc[start] - 1).mean()
        rows.append(dict(month=pd.Timestamp(d[-1]), rel=us - fo, last_day=basket.loc[d[-1]]))
    m = pd.DataFrame(rows).set_index("month")
    for a, b in (("2001", "2014"), ("2015", "2026")):
        x = m.loc[a:b]
        s = np.sign(x.rel) * x.last_day
        print(f"Month-end equity-rebalancing flow {a}-{b}: {s.mean()*1e4:+.1f} bp/month, "
              f"t={s.mean()/s.std()*math.sqrt(len(s)):+.2f}, n={len(s)}")
        bb = basket.loc[a:b]
        g = bb.groupby(bb.index.dayofweek).agg(["mean", "std", "count"])
        t = g["mean"] / g["std"] * np.sqrt(g["count"])
        print(f"  day-of-week {a}-{b}: " + " ".join(f"{'MTWTF'[i]}:{mu*1e4:+.1f}(t={tt:+.1f})"
                                                   for i, mu, tt in zip(g.index, g["mean"], t)))
        tt_ = tom.loc[a:b]
        print(f"  turn-of-month (first 2 days) {a}-{b}: {bb[tt_].mean()*1e4:+.2f} bp vs other days {bb[~tt_].mean()*1e4:+.2f} bp")


if __name__ == "__main__":
    xs_strategies()
    per_pair_strategies()
    calendar()
