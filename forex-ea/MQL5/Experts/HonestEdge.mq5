//+------------------------------------------------------------------+
//| HonestEdge.mq5                                                   |
//| Two rule-based modules + a strict risk manager, for MetaTrader 5.|
//|                                                                  |
//| Module A (ON by default): US index pullback. Long only. Buy when |
//|   daily RSI(2) < 10 while price is above its 200-day SMA; exit   |
//|   on a close above the 5-day SMA or after 10 bars; 3*ATR stop.   |
//| Module B (OFF by default): slow Donchian trend (200/100 bars),   |
//|   5*ATR initial stop, trailing opposite channel. Weak evidence.  |
//|                                                                  |
//| Read forex-ea/README.md before running this on real money.       |
//+------------------------------------------------------------------+
#property copyright   "HonestEdge"
#property version     "1.00"
#property description "A: US index pullback (RSI2 dip-buy). B: slow Donchian trend (off by default)."
#property description "Risk manager: min-lot feasibility check, open-risk cap, spread filter, drawdown kill switch."

#include <Trade\Trade.mqh>

#define HE_PULLBACK 0
#define HE_TREND    1

//--- inputs ---------------------------------------------------------
input group "=== Symbols (use the exact names in your XM Market Watch) ==="
input string          InpPullbackSymbols = "US500Cash";
input string          InpTrendSymbols    = "EURUSD,USDJPY,AUDUSD,GOLD,US500Cash,GER40Cash,JP225Cash";
input string          InpSymbolSuffix    = "";          // e.g. "micro" or "#" depending on account type
input ENUM_TIMEFRAMES InpTimeframe       = PERIOD_D1;   // research was done on D1 only
input long            InpMagicBase       = 26092400;    // module A = base, module B = base+1

input group "=== Module A: index pullback ==="
input bool   InpUsePullback  = true;
input double InpPbRiskPct    = 2.0;    // % of equity lost if the 3*ATR stop is hit
input int    InpPbRsiPeriod  = 2;
input double InpPbRsiBuy     = 10.0;
input int    InpPbTrendSma   = 200;
input int    InpPbExitSma    = 5;
input int    InpPbMaxBars    = 10;
input double InpPbStopAtr    = 3.0;

input group "=== Module B: slow trend (weak edge, off by default) ==="
input bool   InpUseTrend     = false;
input double InpTrRiskPct    = 0.5;
input int    InpTrEntryBars  = 200;
input int    InpTrExitBars   = 100;
input double InpTrStopAtr    = 5.0;

input group "=== Risk manager ==="
input int    InpAtrPeriod          = 20;
input double InpMaxOpenRiskPct     = 6.0;   // total money-at-risk cap across all positions
input double InpMinLotTolerance    = 1.5;   // skip if the minimum lot risks more than this x the target
input double InpMaxMarginUsePct    = 50.0;  // a new trade may use at most this % of free margin
input double InpMaxSpreadAtrFrac   = 0.10;  // wait while spread > this fraction of daily ATR
input int    InpEntryWindowMinutes = 360;   // signals older than this after the bar opens are dropped
input double InpMaxDrawdownPct     = 20.0;  // kill switch: stop opening trades below peak*(1-x%)
input bool   InpCloseOnKill        = false; // also flatten everything when the kill switch trips
input bool   InpResetKillSwitch    = false; // set true once to re-arm after a trip, then back to false
input int    InpSlippagePoints     = 50;

//--- state ----------------------------------------------------------
struct SMarket
{
   string   symbol;
   int      module;
   long     magic;
   int      hAtr;
   int      hRsi;
   int      hSmaTrend;
   int      hSmaExit;
   datetime lastBar;
   int      pendingDir;       // +1 buy, -1 sell, 0 none
   double   pendingStopDist;
   double   pendingAtr;
   datetime pendingExpiry;
   bool     pendingExit;
   datetime pendingExitSince;
   datetime nextTry;          // throttles retries after a failed order
   bool     waitLogged;
   bool     reported;         // feasibility report printed
};

SMarket g_mk[];
CTrade  g_trade;
double  g_peak   = 0.0;
bool    g_halted = false;
bool    g_hedging = true;
string  g_gvPeak, g_gvHalt;

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpPbRiskPct <= 0 || InpPbRiskPct > 3.0 || InpTrRiskPct <= 0 || InpTrRiskPct > 3.0)
   {
      Print("HonestEdge: risk per trade must be >0 and <=3%. Above that a normal losing streak can gut a small account.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(InpTimeframe != PERIOD_D1)
      Print("HonestEdge: WARNING - the research behind these rules used D1 only. Other timeframes are untested and costs matter far more there.");

   g_hedging = (AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
   if(!g_hedging)
      Print("HonestEdge: netting account detected - only one position per symbol will be held across both modules.");

   ArrayResize(g_mk, 0);
   if(InpUsePullback && !AddMarkets(InpPullbackSymbols, HE_PULLBACK)) return INIT_FAILED;
   if(InpUseTrend    && !AddMarkets(InpTrendSymbols,    HE_TREND))    return INIT_FAILED;
   if(ArraySize(g_mk) == 0)
   {
      Print("HonestEdge: no tradable symbols. Check the symbol names/suffix against Market Watch.");
      return INIT_FAILED;
   }

   g_trade.SetDeviationInPoints(InpSlippagePoints);
   LoadKillSwitch();

   PrintFormat("HonestEdge: started on %d market(s). Account %s, equity %.2f %s, leverage 1:%d.",
               ArraySize(g_mk), g_hedging ? "hedging" : "netting",
               AccountInfoDouble(ACCOUNT_EQUITY), AccountInfoString(ACCOUNT_CURRENCY),
               (int)AccountInfoInteger(ACCOUNT_LEVERAGE));
   EventSetTimer(15);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   for(int i = 0; i < ArraySize(g_mk); i++)
   {
      if(g_mk[i].hAtr      != INVALID_HANDLE) IndicatorRelease(g_mk[i].hAtr);
      if(g_mk[i].hRsi      != INVALID_HANDLE) IndicatorRelease(g_mk[i].hRsi);
      if(g_mk[i].hSmaTrend != INVALID_HANDLE) IndicatorRelease(g_mk[i].hSmaTrend);
      if(g_mk[i].hSmaExit  != INVALID_HANDLE) IndicatorRelease(g_mk[i].hSmaExit);
   }
   Comment("");
}

void OnTick()  { Run(); }
void OnTimer() { Run(); }   // OnTick only fires for the chart symbol; the timer covers the rest

//+------------------------------------------------------------------+
void Run()
{
   static bool busy = false;
   if(busy) return;
   busy = true;
   UpdateKillSwitch();
   for(int i = 0; i < ArraySize(g_mk); i++)
      ProcessMarket(g_mk[i]);
   DrawStatus();
   busy = false;
}

//+------------------------------------------------------------------+
bool AddMarkets(const string list, const int module)
{
   string parts[];
   int n = StringSplit(list, ',', parts);
   for(int i = 0; i < n; i++)
   {
      string s = parts[i];
      StringTrimLeft(s);
      StringTrimRight(s);
      if(s == "") continue;
      s += InpSymbolSuffix;
      if(!SymbolSelect(s, true))
      {
         PrintFormat("HonestEdge: symbol '%s' not found at this broker - skipped. Check Market Watch names and the suffix input.", s);
         continue;
      }
      int k = ArraySize(g_mk);
      ArrayResize(g_mk, k + 1);
      g_mk[k].symbol          = s;
      g_mk[k].module          = module;
      g_mk[k].magic           = InpMagicBase + module;
      g_mk[k].hAtr            = iATR(s, InpTimeframe, InpAtrPeriod);
      g_mk[k].hRsi            = INVALID_HANDLE;
      g_mk[k].hSmaTrend       = INVALID_HANDLE;
      g_mk[k].hSmaExit        = INVALID_HANDLE;
      g_mk[k].lastBar         = 0;
      g_mk[k].pendingDir      = 0;
      g_mk[k].pendingStopDist = 0;
      g_mk[k].pendingAtr      = 0;
      g_mk[k].pendingExpiry   = 0;
      g_mk[k].pendingExit     = false;
      g_mk[k].pendingExitSince= 0;
      g_mk[k].nextTry         = 0;
      g_mk[k].waitLogged      = false;
      g_mk[k].reported        = false;
      if(module == HE_PULLBACK)
      {
         g_mk[k].hRsi      = iRSI(s, InpTimeframe, InpPbRsiPeriod, PRICE_CLOSE);
         g_mk[k].hSmaTrend = iMA(s, InpTimeframe, InpPbTrendSma, 0, MODE_SMA, PRICE_CLOSE);
         g_mk[k].hSmaExit  = iMA(s, InpTimeframe, InpPbExitSma, 0, MODE_SMA, PRICE_CLOSE);
         if(g_mk[k].hRsi == INVALID_HANDLE || g_mk[k].hSmaTrend == INVALID_HANDLE || g_mk[k].hSmaExit == INVALID_HANDLE)
         {
            PrintFormat("HonestEdge: failed to create indicators for %s", s);
            return false;
         }
      }
      if(g_mk[k].hAtr == INVALID_HANDLE)
      {
         PrintFormat("HonestEdge: failed to create ATR for %s", s);
         return false;
      }
   }
   return true;
}

//+------------------------------------------------------------------+
void ProcessMarket(SMarket &m)
{
   datetime bar0 = iTime(m.symbol, InpTimeframe, 0);
   if(bar0 == 0) return;                        // history not loaded yet
   if(bar0 != m.lastBar && OnNewBar(m, bar0))   // retried until the data is ready
      m.lastBar = bar0;
   if(m.pendingExit)    TryExit(m);
   if(m.pendingDir != 0) TryEntry(m);
}

//+------------------------------------------------------------------+
bool OnNewBar(SMarket &m, const datetime bar0)
{
   double atr;
   if(!GetBuf(m.hAtr, 0, 1, atr) || atr <= 0) return false;
   if(!m.reported) ReportFeasibility(m, atr);
   ulong ticket = FindPosition(m.symbol, m.magic);
   if(m.module == HE_PULLBACK) return PullbackBar(m, bar0, atr, ticket);
   return TrendBar(m, bar0, atr, ticket);
}

//+------------------------------------------------------------------+
//| Module A: evaluated once per closed daily bar                    |
//+------------------------------------------------------------------+
bool PullbackBar(SMarket &m, const datetime bar0, const double atr, const ulong ticket)
{
   double rsi, smaT, smaX;
   if(!GetBuf(m.hRsi, 0, 1, rsi) || !GetBuf(m.hSmaTrend, 0, 1, smaT) || !GetBuf(m.hSmaExit, 0, 1, smaX))
      return false;
   double close1 = iClose(m.symbol, InpTimeframe, 1);
   if(close1 <= 0) return false;

   if(ticket > 0)
   {
      if(!PositionSelectByTicket(ticket)) return false;
      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      int held = iBarShift(m.symbol, InpTimeframe, opened, false) - 1;   // closed bars since the entry bar
      if(close1 > smaX || held >= InpPbMaxBars)
      {
         m.pendingExit      = true;
         m.pendingExitSince = TimeCurrent();
         m.waitLogged       = false;
         PrintFormat("HonestEdge: %s pullback exit signal (%s).", m.symbol,
                     close1 > smaX ? "close above SMA" : "max bars reached");
      }
      return true;
   }

   if(close1 > smaT && rsi < InpPbRsiBuy)
      Arm(m, +1, InpPbStopAtr * atr, atr, bar0);
   return true;
}

//+------------------------------------------------------------------+
//| Module B: evaluated once per closed daily bar                    |
//+------------------------------------------------------------------+
bool TrendBar(SMarket &m, const datetime bar0, const double atr, const ulong ticket)
{
   if(Bars(m.symbol, InpTimeframe) < InpTrEntryBars + 3) return false;
   double close1 = iClose(m.symbol, InpTimeframe, 1);
   if(close1 <= 0) return false;

   if(ticket > 0)
   {
      TrailTrend(m, ticket);
      return true;
   }

   int hi = iHighest(m.symbol, InpTimeframe, MODE_HIGH, InpTrEntryBars, 2);
   int lo = iLowest(m.symbol, InpTimeframe, MODE_LOW, InpTrEntryBars, 2);
   if(hi < 0 || lo < 0) return false;
   double hh = iHigh(m.symbol, InpTimeframe, hi);
   double ll = iLow(m.symbol, InpTimeframe, lo);
   if(close1 > hh)      Arm(m, +1, InpTrStopAtr * atr, atr, bar0);
   else if(close1 < ll) Arm(m, -1, InpTrStopAtr * atr, atr, bar0);
   return true;
}

//+------------------------------------------------------------------+
//| Stop only ever tightens, to the opposite N-bar channel.          |
//+------------------------------------------------------------------+
void TrailTrend(SMarket &m, const ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return;
   long   type   = PositionGetInteger(POSITION_TYPE);
   double sl     = PositionGetDouble(POSITION_SL);
   double tp     = PositionGetDouble(POSITION_TP);
   double point  = SymbolInfoDouble(m.symbol, SYMBOL_POINT);
   int    digits = (int)SymbolInfoInteger(m.symbol, SYMBOL_DIGITS);
   double minGap = SymbolInfoInteger(m.symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   MqlTick tk;
   if(!SymbolInfoTick(m.symbol, tk)) return;

   double newSl = 0;
   if(type == POSITION_TYPE_BUY)
   {
      int idx = iLowest(m.symbol, InpTimeframe, MODE_LOW, InpTrExitBars, 1);
      if(idx < 0) return;
      double lvl = NormalizeDouble(iLow(m.symbol, InpTimeframe, idx), digits);
      if(lvl <= sl + point) return;
      if(lvl >= tk.bid - minGap) { ClosePosition(m, ticket, "channel already breached"); return; }
      newSl = lvl;
   }
   else
   {
      int idx = iHighest(m.symbol, InpTimeframe, MODE_HIGH, InpTrExitBars, 1);
      if(idx < 0) return;
      double lvl = NormalizeDouble(iHigh(m.symbol, InpTimeframe, idx) + (tk.ask - tk.bid), digits);
      if(sl > 0 && lvl >= sl - point) return;
      if(lvl <= tk.ask + minGap) { ClosePosition(m, ticket, "channel already breached"); return; }
      newSl = lvl;
   }
   g_trade.SetExpertMagicNumber(m.magic);
   if(!g_trade.PositionModify(ticket, newSl, tp))
      PrintFormat("HonestEdge: %s trail to %.5f failed, retcode %u", m.symbol, newSl, g_trade.ResultRetcode());
}

//+------------------------------------------------------------------+
void Arm(SMarket &m, const int dir, const double stopDist, const double atr, const datetime bar0)
{
   m.pendingDir      = dir;
   m.pendingStopDist = stopDist;
   m.pendingAtr      = atr;
   m.pendingExpiry   = bar0 + InpEntryWindowMinutes * 60;
   m.waitLogged      = false;
   PrintFormat("HonestEdge: %s %s signal (%s module).", m.symbol, dir > 0 ? "BUY" : "SELL",
               m.module == HE_PULLBACK ? "pullback" : "trend");
}

//+------------------------------------------------------------------+
//| Entry is retried until the spread is sane (the daily bar opens at|
//| rollover, exactly when spreads are worst) or the window expires. |
//+------------------------------------------------------------------+
void TryEntry(SMarket &m)
{
   if(TimeCurrent() > m.pendingExpiry)
   {
      PrintFormat("HonestEdge: %s signal expired without a fill (spread/market closed). Skipped.", m.symbol);
      m.pendingDir = 0;
      return;
   }
   if(g_halted)                               { m.pendingDir = 0; return; }
   if(FindPosition(m.symbol, m.magic) > 0)    { m.pendingDir = 0; return; }
   if(!g_hedging && PositionSelect(m.symbol)) { m.pendingDir = 0; return; }
   if(TimeCurrent() < m.nextTry)              return;
   if(!TradingAllowed(m.symbol, m.pendingDir)) return;

   MqlTick tk;
   if(!SymbolInfoTick(m.symbol, tk) || tk.bid <= 0) return;
   if(tk.ask - tk.bid > InpMaxSpreadAtrFrac * m.pendingAtr)
   {
      if(!m.waitLogged)
         PrintFormat("HonestEdge: %s spread %.5f too wide vs ATR %.5f - waiting.", m.symbol, tk.ask - tk.bid, m.pendingAtr);
      m.waitLogged = true;
      return;
   }

   int    dir    = m.pendingDir;
   int    digits = (int)SymbolInfoInteger(m.symbol, SYMBOL_DIGITS);
   double price  = dir > 0 ? tk.ask : tk.bid;
   double sl     = NormalizeDouble(dir > 0 ? price - m.pendingStopDist : price + m.pendingStopDist, digits);
   double minGap = SymbolInfoInteger(m.symbol, SYMBOL_TRADE_STOPS_LEVEL) * SymbolInfoDouble(m.symbol, SYMBOL_POINT);
   if(m.pendingStopDist <= minGap) { m.pendingDir = 0; return; }

   double equity    = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskPct   = m.module == HE_PULLBACK ? InpPbRiskPct : InpTrRiskPct;
   double riskMoney = equity * riskPct / 100.0;
   double lots, actualRisk;
   if(!SizePosition(m.symbol, dir, price, sl, riskMoney, lots, actualRisk)) { m.pendingDir = 0; return; }

   double openRisk = OpenRiskMoney();
   if(openRisk + actualRisk > equity * InpMaxOpenRiskPct / 100.0)
   {
      PrintFormat("HonestEdge: %s skipped - open risk %.2f + %.2f would exceed the %.1f%% cap.",
                  m.symbol, openRisk, actualRisk, InpMaxOpenRiskPct);
      m.pendingDir = 0;
      return;
   }

   ENUM_ORDER_TYPE otype = dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double margin = 0;
   if(!OrderCalcMargin(otype, m.symbol, lots, price, margin) ||
      margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE) * InpMaxMarginUsePct / 100.0)
   {
      PrintFormat("HonestEdge: %s skipped - margin %.2f too large for free margin.", m.symbol, margin);
      m.pendingDir = 0;
      return;
   }

   g_trade.SetExpertMagicNumber(m.magic);
   g_trade.SetTypeFilling(Filling(m.symbol));
   string cmt = m.module == HE_PULLBACK ? "HE pullback" : "HE trend";
   bool sent = dir > 0 ? g_trade.Buy(lots, m.symbol, 0, sl, 0, cmt)
                       : g_trade.Sell(lots, m.symbol, 0, sl, 0, cmt);
   uint rc = g_trade.ResultRetcode();
   if(sent && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_DONE_PARTIAL || rc == TRADE_RETCODE_PLACED))
   {
      PrintFormat("HonestEdge: %s %s %.2f lots, SL %.5f, risk %.2f %s (%.2f%%).", m.symbol,
                  dir > 0 ? "bought" : "sold", lots, sl, actualRisk,
                  AccountInfoString(ACCOUNT_CURRENCY), actualRisk / equity * 100.0);
      m.pendingDir = 0;
      return;
   }
   if(IsTransient(rc))
   {
      m.nextTry = TimeCurrent() + 60;   // market closed, requote, etc. - try again shortly
      return;
   }
   PrintFormat("HonestEdge: %s order rejected (retcode %u) - signal dropped.", m.symbol, rc);
   m.pendingDir = 0;
}

//+------------------------------------------------------------------+
void TryExit(SMarket &m)
{
   ulong ticket = FindPosition(m.symbol, m.magic);
   if(ticket == 0) { m.pendingExit = false; return; }
   if(TimeCurrent() < m.nextTry) return;

   // Prefer a sane spread, but never wait longer than the entry window to get out.
   double atr;
   MqlTick tk;
   if(GetBuf(m.hAtr, 0, 1, atr) && SymbolInfoTick(m.symbol, tk) &&
      tk.ask - tk.bid > InpMaxSpreadAtrFrac * atr &&
      TimeCurrent() - m.pendingExitSince < InpEntryWindowMinutes * 60)
      return;

   ClosePosition(m, ticket, "exit rule");
}

//+------------------------------------------------------------------+
void ClosePosition(SMarket &m, const ulong ticket, const string why)
{
   g_trade.SetExpertMagicNumber(m.magic);
   g_trade.SetTypeFilling(Filling(m.symbol));
   bool ok = g_trade.PositionClose(ticket, InpSlippagePoints);
   uint rc = g_trade.ResultRetcode();
   if(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_DONE_PARTIAL))
   {
      PrintFormat("HonestEdge: %s closed (%s).", m.symbol, why);
      m.pendingExit = false;
      return;
   }
   m.pendingExit      = true;   // keep trying; an open position must eventually be closed
   m.pendingExitSince = (m.pendingExitSince == 0 ? TimeCurrent() : m.pendingExitSince);
   m.nextTry          = TimeCurrent() + 60;
   PrintFormat("HonestEdge: %s close failed (retcode %u), will retry.", m.symbol, rc);
}

//+------------------------------------------------------------------+
//| Position size from money-at-risk. Refuses the trade when the     |
//| broker's minimum lot would risk far more than intended - the     |
//| single most common way small accounts get blown up.              |
//+------------------------------------------------------------------+
bool SizePosition(const string sym, const int dir, const double price, const double sl,
                  const double riskMoney, double &lots, double &actualRisk)
{
   double lossPerLot = LossPerLot(sym, dir, price, sl);
   if(lossPerLot <= 0) { PrintFormat("HonestEdge: %s - cannot value the stop distance.", sym); return false; }

   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = vmin;

   lots = MathFloor(riskMoney / lossPerLot / step + 1e-9) * step;
   if(lots < vmin) lots = vmin;
   if(lots > vmax) lots = vmax;
   lots = NormalizeDouble(lots, VolumeDigits(step));
   actualRisk = lots * lossPerLot;

   if(actualRisk > riskMoney * InpMinLotTolerance)
   {
      PrintFormat("HonestEdge: %s skipped - the smallest position (%.2f lots) risks %.2f, %.1fx the intended %.2f. "
                  "Account is too small for this market on this account type.",
                  sym, lots, actualRisk, actualRisk / riskMoney, riskMoney);
      return false;
   }
   return true;
}

double LossPerLot(const string sym, const int dir, const double price, const double sl)
{
   double pnl = 0;
   ENUM_ORDER_TYPE t = dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(OrderCalcProfit(t, sym, 1.0, price, sl, pnl) && pnl < 0)
      return -pnl;
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tv <= 0) tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tv <= 0 || ts <= 0) return 0;
   return MathAbs(price - sl) / ts * tv;
}

int VolumeDigits(const double step)
{
   int d = (int)MathRound(-MathLog10(step));
   return d < 0 ? 0 : d;
}

//+------------------------------------------------------------------+
//| Money still at risk: loss from the current price to each SL.     |
//+------------------------------------------------------------------+
double OpenRiskMoney()
{
   double total = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      long magic = PositionGetInteger(POSITION_MAGIC);
      if(magic != InpMagicBase + HE_PULLBACK && magic != InpMagicBase + HE_TREND) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      double sl  = PositionGetDouble(POSITION_SL);
      double vol = PositionGetDouble(POSITION_VOLUME);
      bool   buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      if(sl == 0) return AccountInfoDouble(ACCOUNT_EQUITY);   // unprotected position: block new risk
      double cur = PositionGetDouble(POSITION_PRICE_CURRENT);
      double pnl = 0;
      if(OrderCalcProfit(buy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, vol, cur, sl, pnl) && pnl < 0)
         total += -pnl;
   }
   return total;
}

//+------------------------------------------------------------------+
void ReportFeasibility(SMarket &m, const double atr)
{
   m.reported = true;
   double stopMult = m.module == HE_PULLBACK ? InpPbStopAtr : InpTrStopAtr;
   double riskPct  = m.module == HE_PULLBACK ? InpPbRiskPct : InpTrRiskPct;
   double price    = SymbolInfoDouble(m.symbol, SYMBOL_BID);
   if(price <= 0) { m.reported = false; return; }
   double loss   = LossPerLot(m.symbol, +1, price, price - stopMult * atr);
   double vmin   = SymbolInfoDouble(m.symbol, SYMBOL_VOLUME_MIN);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(loss <= 0 || equity <= 0) return;
   double minPct = vmin * loss / equity * 100.0;
   PrintFormat("HonestEdge: feasibility %s [%s]: min lot %.2f risks %.2f%% of equity on a %.1f*ATR stop; target %.2f%% -> %s",
               m.symbol, m.module == HE_PULLBACK ? "pullback" : "trend", vmin, minPct, stopMult, riskPct,
               minPct <= riskPct * InpMinLotTolerance ? "OK" : "TOO SMALL - every signal will be skipped");
}

//+------------------------------------------------------------------+
//| Drawdown kill switch. Persists across restarts (terminal GVs).   |
//+------------------------------------------------------------------+
void LoadKillSwitch()
{
   string key = StringFormat("%I64d_%I64d", AccountInfoInteger(ACCOUNT_LOGIN), InpMagicBase);
   g_gvPeak = "HE_peak_" + key;
   g_gvHalt = "HE_halt_" + key;
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(InpResetKillSwitch || tester || !GlobalVariableCheck(g_gvPeak))
   {
      g_peak = eq;
      g_halted = false;
      if(!tester)
      {
         GlobalVariableSet(g_gvPeak, g_peak);
         GlobalVariableSet(g_gvHalt, 0);
      }
      return;
   }
   g_peak   = MathMax(GlobalVariableGet(g_gvPeak), eq);
   g_halted = GlobalVariableCheck(g_gvHalt) && GlobalVariableGet(g_gvHalt) > 0;
   if(g_halted)
      Print("HonestEdge: kill switch is TRIPPED from a previous session - no new trades. Review, then set InpResetKillSwitch=true once.");
}

void UpdateKillSwitch()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(eq > g_peak)
   {
      g_peak = eq;
      if(!tester) GlobalVariableSet(g_gvPeak, g_peak);
   }
   if(g_halted || InpMaxDrawdownPct <= 0) return;
   if(eq < g_peak * (1.0 - InpMaxDrawdownPct / 100.0))
   {
      g_halted = true;
      if(!tester) GlobalVariableSet(g_gvHalt, 1);
      PrintFormat("HonestEdge: KILL SWITCH - equity %.2f is %.1f%% below peak %.2f. No new trades until reset.",
                  eq, (1.0 - eq / g_peak) * 100.0, g_peak);
      if(InpCloseOnKill) CloseAll();
   }
}

void CloseAll()
{
   for(int i = 0; i < ArraySize(g_mk); i++)
   {
      ulong t = FindPosition(g_mk[i].symbol, g_mk[i].magic);
      if(t > 0) ClosePosition(g_mk[i], t, "kill switch");
   }
}

//+------------------------------------------------------------------+
//| helpers                                                          |
//+------------------------------------------------------------------+
bool GetBuf(const int handle, const int buffer, const int shift, double &val)
{
   double b[1];
   if(handle == INVALID_HANDLE) return false;
   if(CopyBuffer(handle, buffer, shift, 1, b) != 1) return false;
   val = b[0];
   return val != EMPTY_VALUE;
}

ulong FindPosition(const string sym, const long magic)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == sym && PositionGetInteger(POSITION_MAGIC) == magic)
         return t;
   }
   return 0;
}

bool TradingAllowed(const string sym, const int dir)
{
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED)) return false;
   long mode = SymbolInfoInteger(sym, SYMBOL_TRADE_MODE);
   if(mode == SYMBOL_TRADE_MODE_DISABLED || mode == SYMBOL_TRADE_MODE_CLOSEONLY) return false;
   if(dir > 0 && mode == SYMBOL_TRADE_MODE_SHORTONLY) return false;
   if(dir < 0 && mode == SYMBOL_TRADE_MODE_LONGONLY)  return false;
   return true;
}

ENUM_ORDER_TYPE_FILLING Filling(const string sym)
{
   long fm = SymbolInfoInteger(sym, SYMBOL_FILLING_MODE);
   if((fm & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK) return ORDER_FILLING_FOK;
   if((fm & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

bool IsTransient(const uint rc)
{
   return rc == TRADE_RETCODE_MARKET_CLOSED || rc == TRADE_RETCODE_REQUOTE ||
          rc == TRADE_RETCODE_PRICE_OFF     || rc == TRADE_RETCODE_PRICE_CHANGED ||
          rc == TRADE_RETCODE_TIMEOUT       || rc == TRADE_RETCODE_CONNECTION ||
          rc == TRADE_RETCODE_TRADE_DISABLED || rc == TRADE_RETCODE_TOO_MANY_REQUESTS ||
          rc == 0;
}

void DrawStatus()
{
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return;
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   string s = StringFormat("HonestEdge v1.00  |  %s\nEquity %.2f  Peak %.2f  DD %.1f%% (kill at %.1f%%)\nOpen risk %.2f (cap %.1f%%)  Markets %d",
                           g_halted ? "HALTED - kill switch tripped" : "running",
                           eq, g_peak, g_peak > 0 ? (1.0 - eq / g_peak) * 100.0 : 0.0, InpMaxDrawdownPct,
                           OpenRiskMoney(), InpMaxOpenRiskPct, ArraySize(g_mk));
   for(int i = 0; i < ArraySize(g_mk); i++)
      if(g_mk[i].pendingDir != 0 || g_mk[i].pendingExit)
         s += StringFormat("\n  %s: %s", g_mk[i].symbol, g_mk[i].pendingExit ? "exit pending" : "entry pending");
   Comment(s);
}

//+------------------------------------------------------------------+
//| Custom optimisation score. Returns 0 for tiny samples and losing |
//| runs so the optimiser can't fall in love with 12 lucky trades.   |
//| Optimising at all is the fastest way to fool yourself - see the  |
//| README before using it.                                          |
//+------------------------------------------------------------------+
double OnTester()
{
   double trades = TesterStatistics(STAT_TRADES);
   double profit = TesterStatistics(STAT_PROFIT);
   double pf     = TesterStatistics(STAT_PROFIT_FACTOR);
   double dd     = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   if(trades < 30 || profit <= 0) return 0.0;
   return pf * MathSqrt(trades) / (1.0 + dd / 10.0);
}
//+------------------------------------------------------------------+
