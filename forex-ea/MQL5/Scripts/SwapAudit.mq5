//+------------------------------------------------------------------+
//| SwapAudit.mq5                                                    |
//| Measures your broker's overnight-swap markup, per symbol.        |
//|                                                                  |
//| A fair swap is roughly symmetric: what a long position pays, a   |
//| short position receives (the interest-rate differential). The    |
//| part that both sides pay is the broker's markup:                 |
//|      markup  ~=  -(long % p.a. + short % p.a.) / 2               |
//| The research in forex-ea/ assumed ~1% p.a. per side on G10 FX    |
//| and ~2% on emerging-market pairs. Run this on your XM account to |
//| replace those guesses with your real numbers.                    |
//|                                                                  |
//| Output: the Experts journal + MQL5/Files/SwapAudit.csv           |
//+------------------------------------------------------------------+
#property copyright   "HonestEdge"
#property version     "1.00"
#property script_show_inputs

input bool InpOnlyMarketWatch = true;   // false = every symbol the broker offers (slow)

//--- money value (account currency) of the swap for 1 lot held one night
bool SwapMoneyPerLot(const string sym, const double swap, double &money)
{
   long   mode     = SymbolInfoInteger(sym, SYMBOL_SWAP_MODE);
   double point    = SymbolInfoDouble(sym, SYMBOL_POINT);
   double tickSize = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tickVal  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double contract = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
   double price    = SymbolInfoDouble(sym, SYMBOL_BID);
   if(tickSize <= 0 || tickVal <= 0 || contract <= 0 || price <= 0) return false;
   double perQuoteUnit = tickVal / tickSize / contract;   // account money per 1.0 of quote currency
   switch((int)mode)
   {
      case SYMBOL_SWAP_MODE_POINTS:           money = swap * point / tickSize * tickVal;          return true;
      case SYMBOL_SWAP_MODE_CURRENCY_SYMBOL:  money = swap * price * perQuoteUnit;               return true;
      case SYMBOL_SWAP_MODE_CURRENCY_MARGIN:  money = swap * price * perQuoteUnit;               return true;
      case SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT: money = swap;                                      return true;
      case SYMBOL_SWAP_MODE_CURRENCY_PROFIT:  money = swap * perQuoteUnit;                       return true;
      case SYMBOL_SWAP_MODE_INTEREST_CURRENT:
      case SYMBOL_SWAP_MODE_INTEREST_OPEN:    money = swap / 100.0 / 360.0 * price / tickSize * tickVal; return true;
   }
   return false;   // disabled or re-open modes: not comparable
}

void OnStart()
{
   int total = SymbolsTotal(InpOnlyMarketWatch);
   int fh = FileOpen("SwapAudit.csv", FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(fh != INVALID_HANDLE)
      FileWrite(fh, "symbol", "swap_mode", "swap_long", "swap_short", "triple_day",
                "long_pct_pa", "short_pct_pa", "implied_markup_pct_pa");
   PrintFormat("SwapAudit: %s, account currency %s, %d symbols", AccountInfoString(ACCOUNT_COMPANY),
               AccountInfoString(ACCOUNT_CURRENCY), total);
   PrintFormat("%-14s %10s %10s %13s", "symbol", "long %pa", "short %pa", "markup %pa");
   for(int i = 0; i < total; i++)
   {
      string sym = SymbolName(i, InpOnlyMarketWatch);
      double sl  = SymbolInfoDouble(sym, SYMBOL_SWAP_LONG);
      double ss  = SymbolInfoDouble(sym, SYMBOL_SWAP_SHORT);
      double ml, ms;
      if(!SwapMoneyPerLot(sym, sl, ml) || !SwapMoneyPerLot(sym, ss, ms)) continue;
      // notional value of 1 lot in account currency
      double notional = SymbolInfoDouble(sym, SYMBOL_BID) / SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE)
                        * SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
      if(notional <= 0) continue;
      // swaps are charged 7 nights a week in effect (triple swap on one weekday) -> 365 nights
      double lp = ml * 365.0 / notional * 100.0;
      double sp = ms * 365.0 / notional * 100.0;
      double markup = -(lp + sp) / 2.0;
      long triple = SymbolInfoInteger(sym, SYMBOL_SWAP_ROLLOVER3DAYS);
      PrintFormat("%-14s %+10.2f %+10.2f %+13.2f", sym, lp, sp, markup);
      if(fh != INVALID_HANDLE)
         FileWrite(fh, sym, (int)SymbolInfoInteger(sym, SYMBOL_SWAP_MODE), sl, ss, triple,
                   DoubleToString(lp, 3), DoubleToString(sp, 3), DoubleToString(markup, 3));
   }
   if(fh != INVALID_HANDLE)
   {
      FileClose(fh);
      Print("SwapAudit: saved MQL5/Files/SwapAudit.csv. A markup above ~1% p.a. makes any strategy that holds positions overnight much harder to profit from.");
   }
}
//+------------------------------------------------------------------+
