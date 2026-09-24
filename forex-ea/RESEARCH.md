# Round 2: looking for a better forex strategy

You asked me to search wider for a more profitable strategy on any forex pair. This file records everything I tested, including what failed. Every number can be reproduced with the scripts in `research/` (section 7).

## 1. The short answer

**I did not find a forex strategy that reliably makes money after XM's costs.**

- **Scope:** 36 strategy families and roughly 200 variants.
- **Markets:** 37 currency pairs, plus gold and silver.
- **Data:** 26 years of daily data and 23 years of hourly data.

The results fall into four groups:

| | What happened |
|---|---|
| **Classic currency strategies** (carry, momentum, value, trend, mean reversion, calendar effects) | All lose money once XM's overnight swap markup and spreads are paid. |
| **Intraday patterns on the major pairs** | The real ones are about 0.5–1.5 pips per trade. XM's round-trip cost is about 2–2.8 pips (Standard) or 1.1–1.9 pips (Ultra Low). |
| **Machine learning** (walk-forward, 20 features, 7 majors) | No skill since 2019. It lost money in 14 of 14 years at XM Standard costs. |
| **Best signal found: gold (XAUUSD) intraday volatility breakout** | Passed two untouched holdout periods *before costs*, on both long and short trades. *After* costs since 2016, it's about **+$6/yr** on $1,000 at 0.5% risk per trade. That isn't statistically different from zero. |

The gold breakout is now in the EA as **Module C, OFF by default, for demo forward-testing only**. Module A (the US500 dip-buy) is still the only rule in this project with a clearly positive result after costs, and it isn't a forex pair.

## 2. How the testing was kept honest

- **Costs are always included.** Here is the cost model:

  | Cost | Assumption |
  |---|---|
  | Spreads | XM Standard-typical (EURUSD 1.7 pips, GBPUSD 2.2, USDJPY 1.9, crosses 2–4) plus slippage |
  | Overnight swap | The interest-rate differential from FRED 3-month rates, minus a broker markup of 1% a year per side (2% for emerging-market pairs) |
  | Intraday strategies | Always closed before the 21:00 London rollover, so they pay no swap |

  Your real swap markup can be measured with `MQL5/Scripts/SwapAudit.mq5`.
- **Exploration and holdout were kept apart.**
  1. Intraday ideas were explored on 2016–2026 only.
  2. The 2004–2015 hourly data was kept untouched.
  3. Only two candidates, USDJPY and gold, were taken to it, with their rules frozen first.
  4. Silver was used as an independent check of the gold result.
- **Daily ideas** were judged on two halves of the data (2003/06–2014 and 2015–2026). "Robust" means positive in both.
- **Multiple testing.** With about 200 variants, around 10 will look "significant" at the 5% level by pure luck. That's why a single good-looking backtest means nothing, and why the holdout matters.

## 3. Results: daily-frequency strategies

**Currency portfolios, 9 G10 currencies vs USD, 10% volatility target, all costs** (`results/scan_daily_fx.txt`):

| Strategy | Sharpe 2006–14 | Sharpe 2015–26 | Verdict |
|---|---|---|---|
| Carry (long 3 highest yielders, short 3 lowest) | +0.13 | −0.13 | The carry premium is real: Sharpe +0.38/+0.21 with *zero* markup. A 1% markup costs about 3.3% a year at this leverage and wipes it out. |
| Momentum 1, 3, 6, 12 months | −0.07 to −0.17 | −0.55 to −0.75 | Dead |
| Short-term reversal (weekly) | −0.33 | −0.41 | Dead |
| Value (5-year reversal) | −0.14 | −0.48 | Dead |
| Time-series trend, 12 months | −0.28 | −0.21 | Dead |
| Dollar carry | −0.69 | +0.08 | Dead |
| Carry + momentum + value combined | −0.02 | −0.86 | Dead |

**Single-pair rules on 30 G10 pairs and 4 emerging-market pairs:**

| Strategy | Pairs with Sharpe > 0.3 in both halves |
|---|---|
| Carry with a 200-day trend filter (incl. MXN, ZAR, PLN, HUF) | 0 of 34 |
| 20-day z-score mean reversion | 0 of 30 |
| 2-day reversal | 0 of 30 |

**Calendar effects:**

| Effect | Result |
|---|---|
| Month-end equity-rebalancing flow | −1.6 bp/month (t −0.4), then +3.5 bp/month (t 1.1) |
| Day-of-week | All below 4 bp |
| Turn-of-month | All below 4 bp |

## 4. Results: intraday strategies (hourly data, 7 majors)

These are gross pips per trade *before* costs (`results/scan_intraday_fx.txt`). Compare them with XM's roughly 2–2.8 pip round trip.

| Strategy | 2010–15 | 2016–20 | 2021–26 | Verdict |
|---|---|---|---|---|
| Hour-of-day seasonality | best hours about 1 bp | about 1 bp | about 1 bp | Real but smaller than the spread |
| Gotobi / Tokyo fix (USDJPY) | +3.0 | +1.5 | +1.9 | Faded. In 2021–26, non-gotobi days rose more (+2.5) |
| Fade 4-sigma hourly spikes (6h hold) | −1.1 | +1.9 | −3.4 | Noise |
| London breakout of the Asian range | +0.8 | +1.5 | +1.1 | Below cost |
| London breakout, USDJPY only | +4.6 | +2.5 | +4.0 | Failed its 2004–09 holdout: −0.9 pips after cost |
| Intraday momentum (morning → afternoon) | 0.0 | +0.1 | +0.4 | Nothing |
| Currency-ranking reversal (4–24h, synchronous) | +0.4–0.8 bp | +0.4–1.0 bp | +0.1–1.3 bp | Below cost |
| Month-end 4pm London fix hour | −2.4 bp | −3.7 bp | −1.5 bp | Too small and too rare |
| Daily volatility breakout (k = 0.8) | +1.2 | +0.8 | +1.2 | Below cost, except USDJPY (below) |
| Asian-session Bollinger fade ("night scalper") | +0.6 | +0.2 | −0.9 | Dead, and night spreads are wider |
| Friday-afternoon fade of the week's move | −2.6 | 0.0 | +1.6 | Noise |
| Weekend-gap fade | +3.3 | +0.7 | +12.5 | **Fake**: see section 6 |

**Machine learning** (`results/ml_walkforward.txt`):

- **Setup:** LightGBM predicting the next 4 hours from 20 features. Trained on the previous 3 years, retrained every 6 months, tested only on the following 6 months, 2013–2026.
- **Skill:** its rank correlation with actual returns was +0.03 to +0.05 in 2013–2016, then about 0 from 2019 onwards. Its direction calls were right 50.2% of the time.
- **Trading:** it lost money in every threshold and cost scenario. At XM Standard costs, 0 of 14 years were profitable.

**Grid / martingale EA**, a typical commercial design, on EURUSD (`results/grid_martingale_demo.txt`). A fresh $1,000 account was started every month from 2016 to 2025 and run for 12 months:

- **85% of accounts blew up within 12 months.**
- **The average account ended at $787.**
- **The survivors' median end balance was $4,400.** That is the equity curve sellers show you.
- **Every closed basket is a "win".** The losses only show up as the blow-up.

## 5. The pre-registered candidates

The rule was frozen before the holdout years were loaded (`volbreak.py`):

1. Each day at 22:00 London, place a buy-stop at the day's open + 0.8 × yesterday's range and a sell-stop at the open − 0.8 × range.
2. Take the first one that triggers.
3. Close before the 21:00 London rollover.

Net figures below use conservative costs: 2.4 pips on USDJPY, $0.65/oz on gold and $0.05/oz on silver, spread plus slippage (`results/holdout_tests.txt`).

| Market | 2004–09 holdout | 2010–15 holdout | 2016–21 | 2022–26 | Verdict |
|---|---|---|---|---|---|
| USDJPY gross (bp per trade) | +2.4 (t 1.2) | +4.7 (t 2.7) | +3.7 | +3.8 | |
| USDJPY net | +0.2 | +2.1 | +1.5 | +2.1 | **Fails.** Removing the best 1% of trades makes it negative. It was really just riding yen trends such as Abenomics in 2013. |
| Gold gross | +18.2 (t 4.4) | +7.7 (t 2.2) | +6.0 (t 2.2) | +5.3 (t 1.5) | Real before costs: positive in every block, long *and* short, including the 2011–15 bear market |
| Gold net | +7.5 (t 1.8) | +2.9 (t 0.8) | +1.4 (t 0.5) | +2.6 (t 0.7) | **Break-even after costs.** Decaying, and it depends on a few big trend days: without the best 1% of trades the net is 0. |
| Silver gross | (unreliable data) | +5.5 | +9.7 | +6.2 | Same sign as gold before costs… |
| Silver net | | −17.0 | −18.4 | −10.9 | …but silver's spread (about 15–20 bp) makes it clearly lose |

What gold Module C would have made on $1,000, compounded, after costs:

| Risk per trade | Since 2010 | Since 2016 | Worst drawdown |
|---|---|---|---|
| 0.5% (EA default) | +1.4%/yr (~$14/yr) | +0.6%/yr (~$6/yr) | −11% |
| 1% | +2.8%/yr | +1.2%/yr | −22% |
| 3% (EA hard cap) | +7.2%/yr | +2.7%/yr | −55% |

It wins 49% of trades, and the median trade loses slightly. A handful of large trend days pay for everything else. Parameter sensitivity: net is mildly positive for k = 0.7–1.0 and negative for k = 0.5. A tight stop (1× k × range) turns it negative.

## 6. Traps that make fake edges

These would have given me a "profitable" EA if I hadn't checked:

1. **Yahoo daily FX closes aren't taken at the same moment for every currency.** A 1-day reversal strategy showed +8%/yr gross on Yahoo data. With synchronous hourly data it shrinks to about 1 bp/day, which is below cost.
2. **Bid-only data at the Sunday open and the daily rollover.** Spreads blow out, so the *bid* drops and then recovers. That produces a fake "weekend gap fade" worth +12.5 pips per trade in 2021–26: 63% of Sunday gaps were negative on *both* EURUSD-type and USDCHF-type pairs, which real price moves can't do. It also produces fake 21:00–23:00 hour-of-day effects of up to 3 bp. MT5 backtests using bid bars at rollover show the same illusion.
3. **Unknown order of prices inside a bar.** My first grid/martingale simulation let it buy the bar's low and sell the bar's high even when the high came first. It showed **+214%**. Walking each bar's price path in order gave **−21% and an 85% blow-up rate**. Cheap MT5 tester modes ("Open prices only", or "1 minute OHLC" for M1 scalpers) create the same fantasy.
4. **Survivorship.** Grid EAs that survive look spectacular. You never see the 85% that didn't.
5. **Hindsight trends.** Gold went from $1,070 to $4,450 over 2016–2026, and USDJPY from 103 to 160 over 2021–2024. Any long-biased rule looks brilliant on that period. That's why I checked long and short separately and used the holdouts.

## 7. Reproduce it

```bash
pip install numpy pandas requests lightgbm scikit-learn
python3 research/download_data.py ./data            # Yahoo + FRED + Dukascopy (hourly takes hours: rate-limited)
python3 research/scan_daily_fx.py ./data             # section 3
python3 research/scan_intraday_fx.py ./data          # section 4
python3 research/ml_walkforward.py ./data            # machine learning
python3 research/grid_martingale_demo.py ./data      # grid / martingale
python3 research/holdout_tests.py ./data             # section 5
```

Saved outputs from my run are in `research/results/`. Free data isn't broker data, so XM's own tick data and swaps are what count. Run the EA in the MT5 Strategy Tester ("Every tick based on real ticks") and `SwapAudit.mq5` on your account before trusting any of this.

## 8. What would actually change the answer

- **Lower costs, not a cleverer strategy.** Every intraday effect above is roughly 0.5–2 pips, so costs decide everything. An ECN/raw-spread account (about 0.1–0.3 pip spread plus a commission of about 0.6 pip round trip) would make a few of them borderline. Even then the edges are thin, and larger capital doesn't make an edge bigger.
- **Holding for weeks or months** only works if the swap markup is small. Run `SwapAudit.mq5` and look at the markup column.
- **The dependable way to grow $1,000** is still a low-cost index fund. The honest way to *learn* algo trading is this EA on a demo account.
