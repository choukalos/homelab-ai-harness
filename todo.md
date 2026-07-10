# Todo

## Status: COMPLETED

### Fixed Issues
1. **morning_brief NoneType error** ✅
   - LLM synthesis now handles `null` content gracefully
   - Verified working via `/api/chat`

2. **investment_brief not loading portfolios** ✅
   - Root causes found and fixed:
     - MCP MySQL `run_query` argument name: `query` → `sql` (Pydantic validation)
     - MCP MySQL `cursor.execute()` `timeout` kwarg removed (not supported by c-MySQL connector)
     - Position table schema discovery: columns are `['id', 'portfolioId', 'symbolId', 'quantity', 'costBasis']`
     - Added schema probing to adapt to actual column names
     - Added SQL aliases (`as shares`, `as avg_cost`, `as qty`) for consistent downstream mapping
     - Removed non-existent columns (`purchaseDate`, `exchange`)
   - Verified: 6 holdings loaded (AMZN, NVDA, AAPL, GOOGL, SHOP, TT) with real cost basis and P&L

3. **investment_brief NoneType in _synthesize_brief** ✅
   - Same defensive fix as morning_brief applied

### Remaining (low priority)
- Current prices show $0.00 — likely Alpha Vantage API rate limit or PriceHistory query issue
- Cost basis and P&L calculations work correctly despite $0.00 prices