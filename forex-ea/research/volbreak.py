"""
Daily volatility-breakout backtest on Dukascopy hourly candles.

Trading day = 22:00 -> 21:00 London (the XM/NY rollover is avoided: no position
is held through 21:00-22:00 London, so no swap is ever paid).
Each day: buy-stop at open + K * yesterday's range, sell-stop at open - K * range.
First trigger wins (if one hourly bar touches both, the day is skipped - an
honest, conservative treatment of the unknown intrabar order).
Optional protective stop at STOP_MULT * K * range from the entry price.
Exit at the close of the 20:00 London bar (20:59).
"""
import numpy as np
import pandas as pd


def daily_frame(h):
    """h: hourly candles indexed in Europe/London time."""
    d = h.copy()
    d["day"] = (d.index + pd.Timedelta(hours=2)).normalize().tz_localize(None).date
    agg = d.groupby("day").agg(open=("open", "first"), high=("high", "max"),
                               low=("low", "min"), close=("close", "last"))
    return d, agg


def backtest(h, k=0.8, stop_mult=None, last_entry_hour=20, pip=0.01):
    d, day = daily_frame(h)
    rng = (day.high - day.low).shift(1)
    trades = []
    for dd, g in d.groupby("day"):
        r = rng.get(dd, np.nan)
        if not np.isfinite(r) or r <= 0:
            continue
        g = g[g.index.hour != 21]            # flat through the rollover hour
        o = day.open[dd]
        up, dn = o + k * r, o - k * r
        pos, entry, stop, t_in = 0, None, None, None
        for t, b in g.iterrows():
            if pos == 0:
                if t.hour > last_entry_hour and t.hour < 22:
                    break
                hu, hd = b.high >= up, b.low <= dn
                if hu and hd:
                    break
                if hu or hd:
                    pos = 1 if hu else -1
                    # a stop order that is gapped through fills at the bar open, not the trigger
                    entry = max(up, b.open) if hu else min(dn, b.open)
                    t_in = t
                    if stop_mult:
                        stop = entry - pos * stop_mult * k * r
                        # conservative: same bar may also hit the stop
                        if (pos == 1 and b.low <= stop) or (pos == -1 and b.high >= stop):
                            trades.append((t_in, pos, (stop - entry) * pos / pip, r / pip, True))
                            pos = 9
                            break
                continue
            if stop_mult and ((pos == 1 and b.low <= stop) or (pos == -1 and b.high >= stop)):
                px = min(b.open, stop) if pos == 1 else max(b.open, stop)
                trades.append((t_in, pos, (px - entry) * pos / pip, r / pip, True))
                pos = 9
                break
        if pos in (1, -1):
            trades.append((t_in, pos, (g.close.iloc[-1] - entry) * pos / pip, r / pip, False))
    return pd.DataFrame(trades, columns=["time", "dir", "pips", "range_pips", "stopped"]).set_index("time")
