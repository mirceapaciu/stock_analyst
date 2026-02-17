# Stock Risk Evaluation Plan

## Goal
Provide a practical, investor-friendly risk evaluation module that uses advanced but feasible methods with public market data and modest compute.

## Risk Methods (advanced yet practical)
1) Volatility and downside risk
   - Annualized volatility from daily returns.
   - Downside deviation (Sortino) using returns below a threshold (e.g., 0 or risk-free).
   - Value at Risk (VaR) and Conditional VaR (CVaR) using historical simulation and/or parametric methods.

2) Systematic risk (beta and factor risk)
   - Market beta vs. benchmark (e.g., S&P 500).
   - Multi-factor exposure (Fama-French 3 or 5 factors) to separate market, size, value (and profitability, investment) risks.

3) Drawdown risk and capital loss profile
   - Max drawdown and average drawdown duration.
   - Recovery time (time to regain previous peak).

4) Financial leverage and liquidity risk
   - Leverage: Debt/Equity, Net debt/EBITDA, Interest coverage.
   - Liquidity: Current ratio, quick ratio.
   - Cash flow stability: FCF volatility and margin stability.

5) Earnings and revenue stability (fundamental volatility)
   - Revenue CAGR vs. volatility over 5-10 years.
   - Operating margin volatility.

6) Valuation sensitivity risk
   - DCF sensitivity grid (WACC x terminal growth) to quantify valuation uncertainty.
   - Scenario-based downside (bear/base/bull) with probability weights.

7) Event and concentration risk (practical proxy)
   - Price gap risk via largest daily drawdowns.
   - Concentration proxy using % revenue from top segment or region if data available, else skip.

## Data Sources (existing and feasible)
- Price data: Yahoo Finance (yfinance) for daily returns and region benchmark index.
- Financial statements: Yahoo Finance (yfinance), already used for DCF.
- Factor data: Ken French Fama-French 5-factor data (monthly, free).

## Outputs
- Risk score (0-100) with sub-scores (market, downside, drawdown, leverage, stability, valuation sensitivity).
- Risk profile label: Low, Moderate, Elevated, High.
- Key metrics table with latest values and percentile vs. a chosen universe (optional).

## Implementation Plan

### Phase 1: Core risk metrics (MVP)
1) Add new service module
   - Create `src/services/risk.py` with an entry point `get_risk_evaluation(ticker)` that selects a regional benchmark.
2) Price-based metrics
   - Fetch historical daily prices for ticker and its regional benchmark (3-5 years).
   - Compute returns, volatility, beta, downside deviation, VaR, CVaR.
   - Compute max drawdown and recovery time.
3) Fundamental risk metrics
   - Use existing financial statement fetchers to compute leverage, coverage, liquidity, and FCF stability.
4) Risk scoring
   - Normalize metrics to 0-100 using percentile ranks or fixed thresholds.
   - Produce an overall weighted score.
5) Unit tests
   - Add tests for metric calculation and stable outputs for a known ticker with mocked data.

### Phase 2: Factor risk and stability improvements
1) Multi-factor regression (optional)
   - Add Fama-French 5-factor download (monthly) and regression for factor exposures.
2) Fundamental volatility
   - Calculate revenue/margin volatility over 5-10 years.
3) Improved scoring
   - Calibrate weights and thresholds using a sample universe.

### Phase 3: Valuation uncertainty and UI integration
1) DCF sensitivity grid
   - Reuse DCF engine to compute a small grid (e.g., WACC 7-12%, g 1-4%).
   - Convert to a downside risk metric (e.g., % of grid below market price).
2) UI
   - Add a Risk section to the DCF page and Favorites page.
   - Provide summary badge and expandable metrics table.
3) Persistence
   - Add table to DuckDB for `risk_evaluation` results keyed by stock_id and timestamp.

## Scoring Model (draft)
- Market risk (beta, volatility): 25%
- Downside risk (VaR/CVaR, downside deviation): 20%
- Drawdown risk (max drawdown, recovery): 15%
- Leverage and liquidity: 20%
- Stability (FCF, revenue/margin): 10%
- Valuation sensitivity: 10%

## Integration Points
- Service layer: new `risk.py` used by UI and favorites.
- Repository: add `save_risk_evaluation()` in `repositories/stocks_db.py`.
- UI: add cards in `src/ui/pages/2_DCF_Valuation.py` and favorites.

## Risks and Limitations
- Factor data availability or format changes; fall back to single-factor beta if needed.
- Short or missing price history for newer tickers.
- Accounting data quality varies by sector.
 - Regional benchmark mapping may be incomplete for some exchanges; fallback to US benchmark when unknown.

## Next Steps
- Lock in Ken French Fama-French 5-factor dataset (monthly).
- Add regional benchmark mapping based on exchange/region.
- Validate metric thresholds with sample tickers.

## Regional Benchmark Mapping (draft)
- US: S&P 500 (`^GSPC`)
- Canada: S&P/TSX (`^GSPTSE`)
- UK: FTSE 100 (`^FTSE`)
- Eurozone: Euro Stoxx 50 (`^STOXX50E`)
- Germany: DAX (`^GDAXI`)
- France: CAC 40 (`^FCHI`)
- Japan: Nikkei 225 (`^N225`)
- Hong Kong: Hang Seng (`^HSI`)
- Australia: ASX 200 (`^AXJO`)
- Default fallback: S&P 500 (`^GSPC`)
