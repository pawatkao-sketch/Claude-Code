"""
fxlab: small research toolkit for daily-frequency FX strategy tests.

Data: Yahoo Finance daily closes (<PAIR>_d.json) and FRED 3-month interbank rates
(IR3_<CC>.csv). All results are net of an explicit XM-style cost model:
  - spread + slippage paid on every change in position (as % of price)
  - overnight swap = interest differential -/+ a broker markup (per side, % p.a.)
"""
import json
import math
import os

import numpy as np
import pandas as pd

# currency -> (Yahoo pair, True if quoted as USDxxx, FRED country code)
CCY = {
    "EUR": ("EURUSD", False, "EZ"), "GBP": ("GBPUSD", False, "GB"),
    "JPY": ("USDJPY", True, "JP"),  "CHF": ("USDCHF", True, "CH"),
    "CAD": ("USDCAD", True, "CA"),  "AUD": ("AUDUSD", False, "AU"),
    "NZD": ("NZDUSD", False, "NZ"), "NOK": ("USDNOK", True, "NO"),
    "SEK": ("USDSEK", True, "SE"),
}
# Typical XM Standard/Micro spread as % of price, incl. ~0.2 pip slippage.
SPREAD_PCT = {
    "EURUSD": 0.017, "GBPUSD": 0.019, "USDJPY": 0.015, "USDCHF": 0.024,
    "USDCAD": 0.019, "AUDUSD": 0.030, "NZDUSD": 0.042, "USDNOK": 0.045,
    "USDSEK": 0.050, "EURGBP": 0.026, "EURJPY": 0.018, "GBPJPY": 0.020,
    "EURCHF": 0.029, "AUDJPY": 0.029, "EURAUD": 0.019, "EURCAD": 0.020,
    "GBPCHF": 0.032, "AUDNZD": 0.034, "AUDCAD": 0.031, "CADJPY": 0.027,
    "NZDJPY": 0.037, "GBPAUD": 0.019, "CHFJPY": 0.019, "EURNZD": 0.024,
    "GBPCAD": 0.023, "AUDCHF": 0.048, "CADCHF": 0.045, "NZDCAD": 0.042,
    "GBPNZD": 0.026, "NZDCHF": 0.060,
}
SWAP_MARKUP = 0.010   # 1.0% p.a. per side kept by the broker (base case)


def load_close(folder, pair):
    with open(os.path.join(folder, f"{pair}_d.json")) as f:
        r = json.load(f)["chart"]["result"][0]
    c = pd.Series(r["indicators"]["quote"][0]["close"],
                  index=pd.to_datetime(r["timestamp"], unit="s").normalize(), dtype=float)
    c = c[~c.index.duplicated(keep="last")].dropna()
    c = c[c > 0]
    c = c[c.index.dayofweek < 5]
    # remove isolated bad prints: huge move that fully reverses the next day
    lr = np.log(c).diff()
    sd = lr.rolling(60, min_periods=20).std().shift(1)
    bad = (lr.abs() > 8 * sd) & (np.sign(lr) != np.sign(lr.shift(-1))) & \
          (lr.shift(-1).abs() > 0.6 * lr.abs())
    c[bad] = np.nan
    return c.ffill()


def load_rates(folder):
    out = {}
    for cc in ["US"] + [v[2] for v in CCY.values()]:
        s = pd.read_csv(os.path.join(folder, f"IR3_{cc}.csv"))
        s.columns = ["date", "rate"]
        s["date"] = pd.to_datetime(s["date"])
        s["rate"] = pd.to_numeric(s["rate"], errors="coerce")
        # monthly average published for month M is only known after M ends: lag 1 month
        out[cc] = s.set_index("date")["rate"].shift(1) / 100.0
    return pd.DataFrame(out)


def currency_panel(ydir, fdir, start="2001-01-01"):
    """Daily returns of holding each currency vs USD, plus annual rate differential."""
    px = {}
    for c, (pair, inv, _) in CCY.items():
        s = load_close(ydir, pair)
        px[c] = 1.0 / s if inv else s
    px = pd.DataFrame(px).loc[start:].ffill().dropna()
    ret = px.pct_change().fillna(0.0)
    rates = load_rates(fdir).reindex(px.index, method="ffill").ffill()
    diff = pd.DataFrame({c: rates[CCY[c][2]] - rates["US"] for c in CCY}, index=px.index)
    spread = pd.Series({c: SPREAD_PCT[CCY[c][0]] / 100.0 for c in CCY})
    return px, ret, diff, spread


def run_weights(w, ret, diff, spread, markup=SWAP_MARKUP, target_vol=None):
    """
    w: DataFrame of target weights (fraction of equity per currency vs USD), decided
       at the close of day t and held over day t+1. Returns net daily P&L series.
    """
    w = w.reindex(ret.index).ffill().fillna(0.0)
    if target_vol:
        gross = (w.shift(1) * ret).sum(axis=1)
        vol = gross.rolling(60, min_periods=40).std().shift(1) * math.sqrt(252)
        scale = (target_vol / vol).clip(upper=5.0).fillna(0.0)
        w = w.mul(scale, axis=0)
    held = w.shift(1).fillna(0.0)
    days = pd.Series(ret.index, index=ret.index).diff().dt.days.fillna(1).clip(lower=1)
    pnl = (held * ret).sum(axis=1)
    carry = (held * diff).sum(axis=1) * days / 365.0
    swap_cost = held.abs().sum(axis=1) * markup * days / 365.0
    turnover = (w - w.shift(1).fillna(0.0)).abs()
    trade_cost = (turnover * spread / 2.0).sum(axis=1)
    net = pnl + carry - swap_cost - trade_cost
    return pd.DataFrame({"net": net, "price": pnl, "carry": carry,
                         "swap_markup": -swap_cost, "trading": -trade_cost,
                         "gross_exposure": held.abs().sum(axis=1)})


def perf(daily, label=""):
    d = daily.dropna()
    if len(d) < 50 or d.std() == 0:
        return f"{label:<34} n/a"
    yrs = len(d) / 252.0
    eq = (1 + d).cumprod()
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = d.std() * math.sqrt(252)
    sharpe = d.mean() / d.std() * math.sqrt(252)
    dd = (eq / eq.cummax() - 1).min()
    return f"{label:<34} CAGR {cagr*100:6.2f}%  vol {vol*100:5.1f}%  Sharpe {sharpe:5.2f}  MaxDD {dd*100:6.1f}%"


def sharpe(daily):
    d = daily.dropna()
    return d.mean() / d.std() * math.sqrt(252) if d.std() > 0 else 0.0


def month_ends(index):
    s = pd.Series(index, index=index)
    return s.groupby([index.year, index.month]).max().values


def rank_weights(signal, n_long=3, n_short=3, rebalance_dates=None):
    """Equal-weight long top-n / short bottom-n of the signal (per row). +1/-1 per side total."""
    rows = signal.index if rebalance_dates is None else rebalance_dates
    out = pd.DataFrame(np.nan, index=signal.index, columns=signal.columns)
    for t in rows:
        s = signal.loc[t].dropna()
        if len(s) < n_long + n_short:
            continue
        r = s.rank()
        w = pd.Series(0.0, index=signal.columns)
        w[r.nlargest(n_long).index] = 1.0 / n_long
        w[r.nsmallest(n_short).index] = -1.0 / n_short
        out.loc[t] = w
    return out.ffill().fillna(0.0)


PAIR_CCY = lambda p: (p[:3], p[3:])


def pair_rate_diff(pair, rates, index):
    """Annual rate differential earned by holding one unit LONG of the pair (base - quote)."""
    code = {c: v[2] for c, v in CCY.items()}
    code["USD"] = "US"
    b, q = PAIR_CCY(pair)
    r = rates.reindex(index, method="ffill").ffill()
    return r[code[b]] - r[code[q]]


def run_positions(pos, close, diff, spread_pct, markup=SWAP_MARKUP):
    """pos decided at close t (in units of notional, sign = direction), held over t+1."""
    pos = pos.reindex(close.index).fillna(0.0)
    ret = close.pct_change().fillna(0.0)
    held = pos.shift(1).fillna(0.0)
    days = pd.Series(close.index, index=close.index).diff().dt.days.fillna(1).clip(lower=1)
    net = held * ret + held * diff * days / 365.0 - held.abs() * markup * days / 365.0 \
          - (pos - pos.shift(1).fillna(0.0)).abs() * spread_pct / 100.0 / 2.0
    return net, held
