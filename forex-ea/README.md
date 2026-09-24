# HonestEdge: an MT5 EA for a $1,000 XM account (Thailand)

This folder contains:

- **`MQL5/Experts/HonestEdge.mq5`**: the EA.
- **`MQL5/Scripts/SwapAudit.mq5`**: measures XM's real overnight-swap markup on your account.
- **`RESEARCH.md`**: round 2, the wide search for a better forex strategy (36 strategy families, 37 pairs, gold and silver).
- **`research/`**: Python scripts behind every number, with saved outputs in `research/results/`. You can re-run them yourself.

You asked for brutal honesty, so the verdict comes first.

> **Round 2 update: searching wider for a better forex strategy.**
>
> - **Scope:** 36 strategy families and about 200 variants across 37 currency pairs, gold and silver. Data: 26 years daily, 23 years hourly.
> - **Tested:** carry, momentum, value, mean reversion, calendar and flow effects, session breakouts, the "night scalper", machine learning and grid/martingale.
> - **Result: none of them reliably makes money on a forex pair after XM's costs.**
> - **Best signal:** a gold (XAUUSD) intraday volatility breakout. It passed two untouched holdout periods before costs. After costs since 2016, it's about +$6 a year on $1,000.
> - **The EA:** that signal is now Module C, **off by default, for demo testing only**. Module A (the US500 dip-buy) is still the best thing in this EA.
>
> Full details and all the traps that create fake edges are in [RESEARCH.md](RESEARCH.md).

---

## 1. The verdict

1. **This EA will not make you meaningful money on $1,000.** The best rule set I found adds roughly **$10–25 per year** at sensible risk. That is about 1–2.5% a year. Over the same period, holding the S&P 500 made **6.5% a year** from price alone, before dividends.
2. **Most "edges" in forex are not there once you pay retail costs.** The standard trend-following system (55/20 Donchian, the "Turtle" rules) *lost money* on 15 markets from 2000 to 2026. It was slightly negative even with **zero costs**. XM's overnight swap charges then made it clearly negative.
3. **Only one pattern survived both halves of the data:** buying short-term dips in the US stock index (S&P 500) while it is in a long-term uptrend. That is Module A of this EA. It is well known, it is small, and much of it is simply the stock market's own long-term upward drift.
4. **No EA "finds edges in any market" by itself.** An EA that re-optimises itself to find what works will find whatever worked *by chance* in the past. That is curve-fitting, and it is the main way retail EAs lose money. This EA runs fixed rules that were picked *before* testing, with textbook parameters.
5. **I could not compile or run this EA in MetaTrader.** This environment has no MT5. The MQL5 code was written carefully against the MT5 API, but you must compile it in MetaEditor. Test it on a **demo account** before any real money goes near it.

Is it *possible* to be profitable? Yes, barely, in one narrow place. Is it possible to turn $1,000 into an income? **No.** Anyone selling you an EA that claims otherwise is selling you the EA, not the returns.

---

## 2. What I tested, and the numbers

Data: free Yahoo Finance daily bars, 2000 to Sept 2026. Markets: 10 FX pairs, gold, oil, S&P 500, DAX and Nikkei.

The cost model is deliberately pessimistic:

- XM Standard-like spreads.
- Slippage of 2% of the daily ATR on each side of every trade.
- Swap charged at 1.5% a year of the position value on FX, and 4–5% a year on gold, indices and oil.

Parameters were **not optimised**.

### Trend following: dead at retail

55/20 Donchian breakout, 3×ATR stop, 0.5% risk per trade, 15 markets:

| Cost scenario             | CAGR   | Max DD | Profit factor | Trades |
|---------------------------|--------|--------|---------------|--------|
| Gross (zero costs)        | −0.3%  | −20%   | 0.97          | 1,200  |
| Spread + slippage only    | −0.8%  | −24%   | 0.93          | 1,201  |
| Swap only                 | −2.3%  | −47%   | 0.80          | 1,195  |
| **All costs**             | **−2.8%** | **−53%** | **0.75** | 1,198  |
| 200/100 slow, all costs   | +0.6%  | −19%   | 1.18          | 264    |

Every sub-period lost money: 2001–07, 2008–12, 2013–19 and 2020–26. **Swap is the biggest killer, not spread.** Trend trades are held for weeks, and XM's swap charges are paid every night. The slow 200/100 version is barely positive, so it ships as **Module B, OFF by default**.

### Dip-buying: works on the US index only

Rules: RSI(2) below 10, price above its 200-day SMA, exit on a close above the 5-day SMA or after 10 bars, 3×ATR emergency stop, long only.

| Market   | 2003–2012 PF | 2013–2026 PF | Verdict |
|----------|--------------|--------------|---------|
| S&P 500  | 2.16         | 1.58         | **Holds up in both halves** |
| DAX      | 1.01         | 1.15         | Break-even: noise |
| Nikkei   | 0.73         | 1.35         | Unstable |
| Gold     | 0.90         | 0.89         | No edge |
| EURUSD   | 1.17         | 0.62         | No edge |
| USDJPY   | 0.58         | 1.02         | No edge |
| AUDUSD   | 1.25         | 0.58         | No edge |

Note that the S&P 500 edge has weakened: profit factor fell from 2.16 to 1.58 between the two halves.

### What the S&P 500 dip-buy is worth on $1,000 (2003–2026)

| Risk per trade (to the 3×ATR stop) | End value | CAGR  | Max DD (closed trades) | $/year |
|------------------------------------|-----------|-------|------------------------|--------|
| 0.5%                               | $1,105    | 0.4%  | −1.8%                  | ~$4    |
| 1.0%                               | $1,219    | 0.9%  | −3.6%                  | ~$9    |
| **2.0% (EA default)**              | $1,481    | 1.7%  | −7.1%                  | ~$17   |
| 3.0% (EA hard maximum)             | $1,790    | 2.5%  | −10.6%                 | ~$25   |
| *Buy and hold S&P 500 (price only)* |          | *6.5%* |                       | ~$65   |

Why it's so small: the strategy is only in the market about 10% of the time. It averages about 9 trades a year. It wins about 70% of trades, but 19 of 199 trades hit the full stop. One stop wipes out roughly 8–10 average winners. The drawdown shown only counts closed trades, so the real mark-to-market drawdown is larger.

Re-run everything yourself:

```bash
pip install numpy pandas
# download Yahoo JSON for each symbol into ./data (see the script docstrings for the URL)
python3 research/backtest_trend.py ./data
python3 research/backtest_pullback.py ./data
```

---

## 3. What the EA does

**Module A: index pullback (ON).** Runs on the daily chart, long only, on `US500Cash` by default.

- **Entry:** when yesterday's close is above the 200-day SMA and RSI(2) is below 10, it buys.
- **Exit:** a close above the 5-day SMA, 10 bars held, or a server-side stop at 3×ATR(20).

**Module B: slow trend (OFF).** 200-bar Donchian breakout, long or short, with a 5×ATR initial stop. The stop trails to the opposite 100-bar channel. Its evidence is weak, and it is included only so you can test it yourself.

**Module C: gold intraday breakout (OFF, demo only).** Runs on `GOLD` (XAUUSD).

- **Entry:** each server day it places a buy-stop at the day's open + 0.8 × yesterday's range and a sell-stop at the open − 0.8 × range. The first fill cancels the other.
- **Stop:** 2 × 0.8 × range from the entry.
- **Exit:** everything is closed by 23:00 server time (21:00 London), before the rollover, so it never pays swap. At most one trade a day.
- **Why it's off:** before costs, this was the most robust signal in round 2. After costs it's roughly break-even (see RESEARCH.md section 5). It's here so you can measure real XM fills and costs on a demo account, not to earn money.

**Risk manager.** This is the part that actually protects you:

| Guard | What it prevents |
|---|---|
| **Min-lot feasibility check** | On a $1,000 **Standard** account, 0.01 lot of EURUSD with a daily-ATR stop risks about 2% instead of 0.5%. The backtest found this true for **99% of trend entries**. The EA *refuses* a trade whenever the smallest lot would risk more than 1.5× the target, and prints a feasibility line for each symbol at startup. |
| Hard cap of 3% risk per trade | The EA will not start with a higher setting. |
| Open-risk cap (default 6%) | Correlated positions stacking up, for example five USD trades that all lose at once. |
| Margin cap (50% of free margin) | XM's 1:1000 leverage letting you over-size. Sizing here is by risk, so high leverage is irrelevant, not an advantage. |
| Spread filter plus a 6-hour entry window | The daily bar opens at **rollover**, when spreads are worst. The EA waits until the spread is below 10% of the daily ATR. If that doesn't happen in time, it skips the trade. |
| Drawdown kill switch (default 20% from peak) | It stops opening trades and survives restarts. You re-arm it by hand with `InpResetKillSwitch`. |
| Server-side stop loss on every position | Losses stay limited even if your PC or VPS dies. |
| `OnTester` score | During optimisation, it scores runs with fewer than 30 trades or a net loss as zero. |

---

## 4. Setup on XM MT5

1. **Account type matters more than the strategy.**
   - A Standard account's minimum position (0.01 lot = 1,000 units of FX) is too coarse for $1,000.
   - XM's **Micro** account uses 1 lot = 1,000 units, so 0.01 lot = 10 units, which lets you size correctly.
   - Check that XM currently offers Micro on MT5 in your region. Also check the index CFD contract sizes there.
   - The EA's startup "feasibility" log tells you directly whether each symbol is tradable at your account size.
2. **Symbol names differ by account.** Open Market Watch → Show All.
   - Use the exact names in `InpPullbackSymbols` and `InpTrendSymbols`, and set `InpSymbolSuffix` if your account adds one (for example `micro`).
   - I have not verified XM's current names. `US500Cash`, `GER40Cash`, `JP225Cash` and `GOLD` are XM's usual style.
3. **Install.**
   1. Copy `HonestEdge.mq5` to `MQL5/Experts/` and `SwapAudit.mq5` to `MQL5/Scripts/`.
   2. Open each in MetaEditor and press **F7** to compile. If either fails, paste the errors back to me.
   3. Attach the EA to **one** D1 chart. It trades all listed symbols from that one chart, including `InpGbSymbols` for Module C. "Algo Trading" must be enabled.
4. **Keep it running.** Daily-bar logic doesn't need a VPS, but the terminal must be running around the daily open. XM offers a free VPS above certain balances and volumes. At $1,000 you probably won't qualify, and a paid VPS (about $10–30 a month) would eat all of the expected profit. **Run it on a PC you leave on, or don't bother.**

---

## 5. How to test it properly

Do these in order. Stop at the first failure.

1. **MT5 Strategy Tester on XM's own data.** Use D1 with "Every tick based on real ticks", from 2015 to now. You should see about 9 trades a year on US500 and a profit factor well above 1. If XM's data disagrees with my Yahoo test, **XM's data wins.** XM's swaps, spreads and index contracts are what you would actually trade.
2. **Check the swap.** In the Strategy Tester report, compare gross profit with swap paid. If swap eats more than about 30% of gross, the edge is too thin at XM.
3. **Don't optimise to "improve" it.** If you do anyway:
   - Optimise only on 2010–2018.
   - Then run the chosen settings once, unchanged, on 2019 to now.
   - If out-of-sample performance falls by more than half, you fitted noise.
4. **Demo-trade it for at least 3 months.** Compare every demo fill with what the tester would have done. The gap between them is your real-world friction.
5. **Go live only if all of this holds:** demo profit factor above 1.2, no execution problems, and you accept that the expected gain is about $15 a year.
6. **Module C (gold), if you try it:**
   - Demo only.
   - Test with "Every tick based on real ticks". Don't use "Open prices only": it fills stop orders unrealistically.
   - After a few months, compare the average demo trade with XM's gold spread. If the average trade isn't clearly larger than the round-trip cost, it has no edge at your broker.
7. **Run `SwapAudit.mq5`** (MT5 → Navigator → Scripts, drag it onto any chart).
   - It prints each symbol's long and short swap as a yearly % and the broker's implied markup.
   - The research assumed about 1% a year per side. If your numbers are higher, every strategy that holds positions overnight is worse than shown here.

**Stop it for good** if any of these happen: the kill switch trips; 25 live trades show a profit factor below 1.0; or XM changes US500 swap or spread terms materially.

---

## 6. Thailand-specific notes (not legal or tax advice)

- **Regulation.** XM serves Thai clients through its offshore entity (XM Global, licensed in **Belize**), not through a Thai-regulated broker.
  - The Thai SEC does not license offshore retail forex/CFD brokers, and it has publicly warned about unlicensed offerings. For a Thai resident this is a legal grey zone at best.
  - If there is a dispute or insolvency, your protection is Belize's, not Thailand's.
- **Tax.** Since 1 January 2024, foreign-sourced income that Thai tax residents bring into Thailand is generally taxable in the year it is remitted. Confirm how this applies to you with a Thai tax adviser.
- **Deposits and withdrawals.** Offshore brokers often use local payment agents or e-wallets. Know the fees on both ends. A 1–2% round trip on $1,000 is $10–20, which **is the entire expected annual edge.**

---

## 7. What I would actually do with $1,000

If the goal is to **grow money**, buy a low-cost S&P 500 or world-index ETF through a regulated broker and leave it. On this backtest that beats every strategy here by roughly 3–6× on return, with no work.

If the goal is to **learn algorithmic trading**, this EA is a good, honest learning setup:

- Run it on **demo**.
- Learn the MT5 Strategy Tester.
- Learn why costs and curve-fitting kill most EAs.
- Treat any live money as tuition, not investment.

The skills (testing, risk sizing, not fooling yourself) are worth far more than the $15 a year.
