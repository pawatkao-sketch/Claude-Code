"""
Walk-forward machine-learning test: can a model find a tradable intraday FX edge?

Every day at 07:00, 11:00 and 15:00 London, predict each major pair's next-4-hour
return from 20 standard technical/calendar/cross-currency features. LightGBM,
pooled across 7 pairs, trained on the previous 3 years, retrained every 6 months,
tested only on the following 6 months (never on data it was trained on).
A trade is taken only when the predicted move exceeds the round-trip cost.

Usage: python3 ml_walkforward.py <data-folder>      (layout: see download_data.py)
"""
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import duka

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"]
INV = {"USDJPY", "USDCHF", "USDCAD"}
COST_STD = {"EURUSD": 2.0, "GBPUSD": 2.5, "USDJPY": 2.2, "USDCHF": 2.4, "USDCAD": 2.6, "AUDUSD": 2.2, "NZDUSD": 2.8}
COST_ULTRA = {"EURUSD": 1.1, "GBPUSD": 1.5, "USDJPY": 1.3, "USDCHF": 1.6, "USDCAD": 1.6, "AUDUSD": 1.4, "NZDUSD": 1.9}
H = 4
HOURS = (7, 11, 15)


def features(folder):
    closes, frames = {}, {}
    for p in PAIRS:
        h = duka.load_hourly(folder, p)
        h.index = h.index.tz_localize("UTC").tz_convert("Europe/London")
        frames[p] = h
        closes[p] = h.close
    C = pd.DataFrame(closes).ffill().dropna()
    L = np.log(C)
    ccy = pd.DataFrame({p: (-L[p] if p in INV else L[p]) for p in PAIRS})   # currency vs USD
    usd24 = -ccy.diff(24).mean(axis=1)
    rows = []
    for p in PAIRS:
        l = L[p]
        r1 = l.diff()
        vol = r1.rolling(480).std()                       # ~20 trading days of hours
        f = pd.DataFrame(index=L.index)
        for k in (1, 4, 12, 24, 72, 120):
            f[f"ret{k}"] = l.diff(k) / (vol * np.sqrt(k))
        f["volratio"] = r1.rolling(24).std() / vol
        f["z100"] = (l - l.rolling(100).mean()) / (vol * 10)
        f["z480"] = (l - l.rolling(480).mean()) / (vol * 22)
        up = r1.clip(lower=0).rolling(14).mean(); dn = (-r1.clip(upper=0)).rolling(14).mean()
        f["rsi14"] = 100 - 100 / (1 + up / dn)
        cr = ccy.diff(24).rank(axis=1)
        f["xs_rank24"] = cr[p] if p not in INV else 8 - cr[p]
        f["usd24"] = usd24 / (vol * np.sqrt(24))
        f["hour"] = L.index.hour
        f["dow"] = L.index.dayofweek
        f["month_end"] = (L.index + pd.offsets.BDay(1)).month != L.index.month
        f["pair"] = PAIRS.index(p)
        f["target"] = (l.shift(-H) - l) / (vol * np.sqrt(H))
        f["fwd_pips"] = (C[p].shift(-H) - C[p]) / (0.01 if p.endswith("JPY") else 0.0001)
        f["vol_pips"] = vol * C[p] / (0.01 if p.endswith("JPY") else 0.0001)
        f["p"] = p
        rows.append(f[f.index.hour.isin(HOURS)])
    X = pd.concat(rows).dropna()
    return X.sort_index()


def main(folder):
    X = features(folder)
    feats = [c for c in X.columns if c not in ("target", "fwd_pips", "vol_pips", "p")]
    X["ym"] = X.index.year * 2 + (X.index.month > 6)
    periods = sorted(X.ym.unique())
    out = []
    for i, per in enumerate(periods):
        tr = X[(X.ym >= per - 6) & (X.ym < per)]
        te = X[X.ym == per]
        if tr.ym.nunique() < 6 or len(te) == 0:
            continue
        m = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=8, max_depth=3,
                              min_child_samples=300, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.8, reg_lambda=5.0, verbose=-1)
        m.fit(tr[feats], tr["target"].clip(-4, 4))
        te = te.copy()
        te["pred"] = m.predict(te[feats])
        out.append(te)
    R = pd.concat(out)
    R["pred_pips"] = R.pred * R.vol_pips * np.sqrt(H)
    ic = R.groupby(R.index.year).apply(lambda g: g.pred.corr(g.target, method="spearman"))
    print("Out-of-sample rank IC by year (0 = no skill):")
    print(" ".join(f"{y}:{v:+.3f}" for y, v in ic.items()))
    print(f"Pooled OOS IC {R.pred.corr(R.target, method='spearman'):+.4f}, "
          f"sign hit-rate {(np.sign(R.pred) == np.sign(R.target)).mean():.4f}, n={len(R)}")
    for mult in (0.0, 1.0, 2.0):
        for name, cost in (("XM Standard", COST_STD), ("XM Ultra Low", COST_ULTRA)):
            c = R.p.map(cost)
            take = R.pred_pips.abs() > mult * c
            pnl = (np.sign(R.pred) * R.fwd_pips - c)[take]
            yrs = pnl.groupby(pnl.index.year).sum()
            print(f"trade if |pred| > {mult:.0f}x cost, {name:12}: trades {take.sum():6d}, "
                  f"net {pnl.mean():+.2f} pips/trade, t={pnl.mean()/pnl.std()*np.sqrt(len(pnl)):+.2f}, "
                  f"years positive {(yrs > 0).sum()}/{len(yrs)}")


if __name__ == "__main__":
    main(os.path.join(sys.argv[1], "dukascopy"))
