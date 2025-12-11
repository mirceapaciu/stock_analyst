"""
Stock Valuation Module using Discounted Cash Flow (DCF) Analysis
"""
import numpy as np
import pandas as pd
from typing import Optional, Dict, List
import sys
import os
import logging

# Add parent directory to path to import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logger = logging.getLogger(__name__)

from fin_config import (
    RISK_FREE_RATE,
    MARKET_RISK_PREMIUM,
    COST_OF_DEBT,
    CORPORATE_TAX_RATE,
    DEFAULT_TERMINAL_GROWTH_RATE,
    MIN_WACC,
    MAX_WACC,
    DEFAULT_WACC,
    MIN_HISTORICAL_GROWTH,
    MAX_HISTORICAL_GROWTH,
    DEFAULT_MIN_GROWTH,
    MIN_STARTING_GROWTH,
    MAX_STARTING_GROWTH,
    MIN_BASELINE_GROWTH,
    FALLBACK_BASELINE_GROWTH,
    MIN_PROJECTED_GROWTH,
    GROWTH_DECLINE_FACTOR,
    DEFAULT_BETA,
    DEFAULT_CONSERVATIVE_FACTOR,
    DEFAULT_FORECAST_YEARS,
    DEFAULT_HISTORICAL_BASE_RATE,
    DEFAULT_HISTORICAL_YEARS,
    FCF_HISTORICAL_WINDOW,
)
from services.financial import get_financial_statements, get_or_create_stock_info, get_historical_fcf
from services.currency import get_financial_currency, convert_currency
from repositories.stocks_db import StockRepository


def get_dcf_valuation(
    ticker: str,
    forecast_years: int = DEFAULT_FORECAST_YEARS,
    terminal_growth_rate: float = DEFAULT_TERMINAL_GROWTH_RATE,
    discount_rate: Optional[float] = None,
    fcf_growth_rates: Optional[List[float]] = None,
    conservative_factor: float = DEFAULT_CONSERVATIVE_FACTOR
) -> Dict:
    """
    Perform DCF valuation and cache the result in the database.
    
    This is a wrapper around do_dcf_valuation that saves the valuation results
    to the dcf_valuation table for historical tracking and analysis.
    
    Args:
        ticker (str): Stock ticker symbol (e.g., 'AAPL')
        forecast_years (int): Number of years to forecast FCF (default: 5)
        terminal_growth_rate (float): Perpetual growth rate after forecast period (default: 0.025)
        discount_rate (float, optional): WACC/discount rate. If None, will be estimated.
        fcf_growth_rates (List[float], optional): Custom FCF growth rates for each year.
            If None, will be estimated based on historical data.
        conservative_factor (float): Factor to apply for conservative valuation (default: 0.9)
    
    Returns:
        Dictionary containing all valuation results and input parameters
    """
    # Perform the DCF valuation
    result = do_dcf_valuation(
        ticker=ticker,
        forecast_years=forecast_years,
        terminal_growth_rate=terminal_growth_rate,
        discount_rate=discount_rate,
        fcf_growth_rates=fcf_growth_rates,
        conservative_factor=conservative_factor
    )
    
    # Save to database
    try:
        from services.financial import get_or_create_stock_id
        
        with StockRepository() as repo:
            # Get stock_id from database
            stock_id = get_or_create_stock_id(ticker)
            
            # Save valuation result
            repo.save_dcf_valuation(stock_id, result)
    except Exception as e:
        logger.warning(f"Warning: Failed to cache DCF valuation in database: {e}")
        # Continue and return result even if caching fails
    
    return result


def do_dcf_valuation(
    ticker: str,
    forecast_years: int = DEFAULT_FORECAST_YEARS,
    terminal_growth_rate: float = DEFAULT_TERMINAL_GROWTH_RATE,
    discount_rate: Optional[float] = None,
    fcf_growth_rates: Optional[List[float]] = None,
    conservative_factor: float = DEFAULT_CONSERVATIVE_FACTOR
) -> Dict[str, float]:
    """
    Calculate the fair value of a stock using Discounted Cash Flow (DCF) Analysis.
    
    Steps:
    1. Estimate future free cash flows (FCF) for 5–10 years
    2. Choose a discount rate (WACC) — the required return
    3. Compute the terminal value (value beyond forecast period)
    4. Discount all those cash flows to the present
    5. Divide by number of shares → fair value per share
    
    Formula:
    Fair Value = (∑t[FCF_t / (1+r)^t] + Terminal Value / (1+r)^n) / Shares Outstanding
    
    Args:
        ticker (str): Stock ticker symbol
        forecast_years (int): Number of years to forecast (5-10 recommended)
        terminal_growth_rate (float): Long-term growth rate for terminal value
        discount_rate (float, optional): WACC/required return rate. If None, will estimate
        fcf_growth_rates (List[float], optional): Custom growth rates for each year
        conservative_factor (float): Factor to apply for conservative valuation

    Returns:
        Dict containing valuation results and key metrics
    """
    
    # Get stock data from financial service
    info = get_or_create_stock_info(ticker)
    statements = get_financial_statements(ticker, statement_type='cashflow')
    cash_flow = statements.get('cashflow')
    
    if cash_flow is None or cash_flow.empty:
        error_msg = (
            f"Unable to retrieve cash flow data for {ticker}. "
            f"This may occur if:\n"
            f"1. The ticker symbol is invalid or the company doesn't exist\n"
            f"2. Cash flow data is not available from the data source\n"
            f"3. The data needs to be refreshed - try running the stock update script\n"
            f"Please verify the ticker symbol and ensure the company has published cash flow statements."
        )
        raise ValueError(error_msg)
    
    # Extract key financial data
    current_fcf = _get_current_fcf(cash_flow)
    shares_outstanding = info.get('sharesOutstanding', 0)
    current_price = info.get('currentPrice', 0)
    
    if current_fcf is None or shares_outstanding == 0:
        raise ValueError(f"Unable to retrieve required financial data for {ticker}")
    
    # Step 1: Estimate future free cash flows
    fcf_growth_notes = []
    if fcf_growth_rates is None:
        # Use historical data to project growth rates
        fcf_growth_rates, fcf_growth_notes = project_fcf_growth_from_historical(
            ticker,
            forecast_years=forecast_years,
            adjustment_factor=1.0
        )
    
    projected_fcfs = _project_fcf(current_fcf, fcf_growth_rates)
    
    # Validate that projected_fcfs and fcf_growth_rates have the same length
    if len(projected_fcfs) != len(fcf_growth_rates):
        logger.warning(
            f"Mismatch in lengths: projected_fcfs has {len(projected_fcfs)} elements, "
            f"fcf_growth_rates has {len(fcf_growth_rates)} elements. "
            f"Truncating to match forecast_years={forecast_years}."
        )
        # Ensure both lists have exactly forecast_years elements
        projected_fcfs = projected_fcfs[:forecast_years]
        fcf_growth_rates = fcf_growth_rates[:forecast_years]
    
    # Step 2: Determine discount rate (WACC)
    if discount_rate is None:
        discount_rate = _estimate_wacc(info, ticker)
    
    # Step 3: Calculate terminal value
    terminal_fcf = projected_fcfs[-1] * (1 + terminal_growth_rate)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth_rate)
    
    # Step 4: Discount all cash flows to present value
    pv_fcfs = []
    for year, fcf in enumerate(projected_fcfs, 1):
        pv_fcf = fcf / (1 + discount_rate) ** year
        pv_fcfs.append(pv_fcf)
    
    pv_terminal_value = terminal_value / (1 + discount_rate) ** forecast_years
    
    # Step 5: Calculate fair value per share
    total_enterprise_value = sum(pv_fcfs) + pv_terminal_value
    
    # Adjust for net debt to get equity value
    net_debt = _get_net_debt(info)
    equity_value = total_enterprise_value - net_debt
    
    fair_value_per_share = equity_value / shares_outstanding
    conservative_fair_value = fair_value_per_share * conservative_factor
    
    # Get currencies for conversion
    trading_currency = info.get('currency') # Trading currency for current price
    financial_currency = info.get('financialCurrency') # Financial currency for valuation numbers
    
    fair_value_in_trading_currency = convert_currency(fair_value_per_share, financial_currency, trading_currency)
    conservative_fair_value_in_trading_currency = convert_currency(conservative_fair_value, financial_currency, trading_currency)

    # Calculate additional metrics
    upside_potential = (fair_value_in_trading_currency - current_price) / current_price if current_price > 0 else 0
    conservative_upside = (conservative_fair_value_in_trading_currency - current_price) / current_price if current_price > 0 else 0
    
    return {
        'ticker': ticker,
        # Input parameters (prefixed with in_) - actual values used
        'in_forecast_years': forecast_years,
        'in_terminal_growth_rate': terminal_growth_rate,
        'in_discount_rate': discount_rate,
        'in_fcf_growth_rates': fcf_growth_rates,
        'in_conservative_factor': conservative_factor,
        # Output results
        'current_price': current_price,
        'fair_value_per_share': fair_value_in_trading_currency,
        'conservative_fair_value': conservative_fair_value_in_trading_currency,
        'upside_potential_pct': upside_potential * 100,
        'conservative_upside_pct': conservative_upside * 100,
        'current_fcf': current_fcf,
        'terminal_value': terminal_value,
        'total_enterprise_value': total_enterprise_value,
        'equity_value': equity_value,
        'shares_outstanding': shares_outstanding,
        'projected_fcfs': projected_fcfs,
        'pv_fcfs': pv_fcfs,
        'pv_terminal_value': pv_terminal_value,
        'net_debt': net_debt,
        'fcf_growth_notes': fcf_growth_notes
    }


def _get_current_fcf(cash_flow: pd.DataFrame) -> Optional[float]:
    """Extract the most recent free cash flow from cash flow statement."""
    try:
        if cash_flow.empty:
            return None
        
        # Look for Free Cash Flow first
        if 'Free Cash Flow' in cash_flow.index:
            return float(cash_flow.loc['Free Cash Flow'].iloc[0])
        
        # Calculate FCF = Operating Cash Flow - Capital Expenditures
        operating_cf = cash_flow.loc['Operating Cash Flow'].iloc[0] if 'Operating Cash Flow' in cash_flow.index else 0
        capex = cash_flow.loc['Capital Expenditures'].iloc[0] if 'Capital Expenditures' in cash_flow.index else 0
        
        # Capital expenditures are usually negative, so we add them
        return float(operating_cf + capex)
    
    except (KeyError, IndexError, TypeError):
        return None


def _determine_best_growth_method(historical: Dict[str, any]) -> str:
    """
    Determine the best growth method based on historical FCF growth volatility.
    
    Returns 'median' if growth is volatile, 'cagr' if stable.
    
    Growth is considered volatile if:
    - Year-to-year changes swing by >10 percentage points, OR
    - There is a mix of high positive growth and near-zero/negative growth
    
    Args:
        historical (Dict): Historical growth data from calculate_historical_fcf_growth_rates()
            Must contain 'growth_rates' key with list of year-over-year growth rates
    
    Returns:
        str: 'median' if volatile, 'cagr' if stable
    """
    growth_rates = historical.get('growth_rates', [])
    
    if len(growth_rates) < 2:
        # Not enough data to determine volatility, default to cagr
        return 'cagr'
    
    # Check 1: Year-to-year changes swing by >10 percentage points
    for i in range(len(growth_rates) - 1):
        change = abs(growth_rates[i + 1] - growth_rates[i])
        if change > 0.10:  # 10 percentage points
            return 'median'
    
    # Check 2: Mix of high positive growth and near-zero/negative growth
    # Define thresholds: high positive = >10%, near-zero/negative = <=5%
    has_high_positive = any(rate > 0.10 for rate in growth_rates)
    has_low_or_negative = any(rate <= 0.05 for rate in growth_rates)
    
    if has_high_positive and has_low_or_negative:
        return 'median'
    
    # Growth is stable, use cagr
    return 'cagr'


def _safe_cagr(start_value: float, end_value: float, years: int) -> Optional[float]:
    """Safely compute CAGR, returning None when the math is undefined."""
    if years <= 0 or start_value == 0:
        return None

    ratio = end_value / start_value
    if ratio <= 0:
        return None

    try:
        return ratio ** (1 / years) - 1
    except (ZeroDivisionError, OverflowError, ValueError):
        return None


def _append_cagr_note(notes: List[str], start_value: float, end_value: float, years: int) -> float:
    """Append a CAGR note and return the numeric value (or 0 when unavailable)."""
    if years <= 0:
        notes.append("  CAGR (N/A): N/A (needs >=2 data points)")
        return 0

    cagr_value = _safe_cagr(start_value, end_value, years)
    if cagr_value is None:
        notes.append(
            f"  CAGR ({years} years): N/A (requires non-zero starting FCF and consistent sign)"
        )
        return 0

    notes.append(f"  CAGR ({years} years): {cagr_value:.1%}")
    return cagr_value


def project_fcf_growth_from_historical(
    ticker: str,
    forecast_years: int = DEFAULT_FORECAST_YEARS,
    method: str = 'auto',
    adjustment_factor: float = 1.0
) -> tuple[List[float], List[str]]:
    """
    Project future FCF growth rates based on historical performance.
    
    Args:
        ticker (str): Stock ticker symbol
        forecast_years (int): Number of years to forecast
        method (str): Projection method - 'declining', 'constant', or 'cagr'
            - 'declining': Start with historical average, decline over time
            - 'constant': Use historical average for all years
            - 'cagr': Use historical CAGR for all years (best for stable stocks)
            - 'median': Use historical median growth rate for all years (best for volatile stocks)
            - 'auto': Determine the best growth method based on historical data (default)
        adjustment_factor (float): Multiply historical rates by this factor
            Use >1.0 for optimistic, <1.0 for conservative
    
    Returns:
        Tuple of (list of projected growth rates, list of FCF growth notes)
    """
    years_of_history = DEFAULT_HISTORICAL_YEARS
    fcf_dates, fcf_values = get_historical_fcf(ticker, years_of_history)
    historical_fcf_growth_rates = calculate_historical_fcf_growth_rates(fcf_dates, fcf_values)
    fcf_growth_notes = historical_fcf_growth_rates.get('fcf_growth_notes', [])
    
    if method == 'auto':
        method = _determine_best_growth_method(historical_fcf_growth_rates)

    if method == 'cagr':
        base_rate = historical_fcf_growth_rates['cagr'] * adjustment_factor
        return [base_rate] * forecast_years, fcf_growth_notes
    
    elif method == 'median':
        base_rate = historical_fcf_growth_rates['median_growth'] * adjustment_factor
        return [base_rate] * forecast_years, fcf_growth_notes
    
    elif method == 'constant':
        base_rate = historical_fcf_growth_rates['average_growth'] * adjustment_factor
        return [base_rate] * forecast_years, fcf_growth_notes
    
    else:  # 'declining' (default)
        base_rate = historical_fcf_growth_rates['average_growth'] * adjustment_factor
        # Cap the starting rate
        base_rate = max(MIN_STARTING_GROWTH, min(MAX_STARTING_GROWTH, base_rate))
        
        # If historical growth is negative or very low, use a minimum baseline
        if base_rate < MIN_BASELINE_GROWTH:
            base_rate = FALLBACK_BASELINE_GROWTH  # Use 5% as minimum for declining projection
        
        # Create declining growth rates
        projected_rates = []
        for year in range(forecast_years):
            decline_factor = GROWTH_DECLINE_FACTOR ** year  # Decline by 10% each year
            rate = base_rate * decline_factor
            projected_rates.append(max(MIN_PROJECTED_GROWTH, rate))  # Minimum 2% growth
        
        return projected_rates, fcf_growth_notes


def get_fcf_outliers(
    fcf_dates: List[str], fcf_values: List[float], iqr_multiplier: float = 2.0
) -> List[str]:
    """
    Identify outliers in historical FCF data using the IQR method.
    
    Args:
        fcf_dates: List of dates corresponding to historical FCF values
        fcf_values: List of historical Free Cash Flow values
        iqr_multiplier: Multiplier for IQR to define outlier bounds (default: 2.0)
            - 1.5 is more aggressive (standard)
            - 2.0 is moderate (recommended for financial data)
            - 2.5+ is more conservative
    
    Returns:
        List of dates where FCF values are considered outliers
    """
    if len(fcf_values) < 3:
        # Not enough data to detect outliers
        return []
    
    # Calculate IQR (Interquartile Range)
    q1 = np.percentile(fcf_values, 25)
    q3 = np.percentile(fcf_values, 75)
    iqr = q3 - q1
    
    # Define outlier bounds
    lower_bound = q1 - iqr_multiplier * iqr
    upper_bound = q3 + iqr_multiplier * iqr
    
    # Identify outliers
    outlier_dates = []
    for i, (date, value) in enumerate(zip(fcf_dates, fcf_values)):
        if value < lower_bound or value > upper_bound:
            outlier_dates.append(date)
            logger.info(
                f"FCF outlier detected at {date}: {value:,.0f} "
                f"(bounds: {lower_bound:,.0f} to {upper_bound:,.0f})"
            )
    
    return outlier_dates


def calculate_historical_fcf_growth_rates(
    fcf_dates: List[str], fcf_values: List[float]
) -> Dict[str, any]:
    """
    Calculate FCF growth rates based on historical data.
    
    Args:
        fcf_dates: List of dates corresponding to historical FCF values
        fcf_values: List of historical Free Cash Flow values
    
    Returns:
        Dict containing:
            - growth_rates: List of year-over-year growth rates
            - average_growth: Average historical growth rate
            - median_growth: Median historical growth rate
            - cagr: Compound Annual Growth Rate
    """

    outliers_dates = get_fcf_outliers(fcf_dates, fcf_values)
    fcf_growth_notes = []
    
    # Document historical FCF data
    fcf_growth_notes.append("Historical FCF Data:")
    for date, value in zip(fcf_dates, fcf_values):
        is_outlier = " (OUTLIER)" if date in outliers_dates else ""
        fcf_growth_notes.append(f"  {date}: {value:,.0f}{is_outlier}")

    if outliers_dates:
        fcf_growth_notes.append(f"\nOutlier Detection: {len(outliers_dates)} outlier(s) detected using IQR method")
        logger.info(f"Outliers detected at {outliers_dates} - will use filtered data for aggregate metrics")
    
    # Calculate year-over-year growth rates using ALL data (including outliers)
    # to preserve temporal sequence integrity
    fcf_growth_notes.append("\nYear-over-Year Growth Rates (calculated from all data):")
    growth_rates = []
    for i in range(len(fcf_values) - 1):
        older_fcf = fcf_values[i]      # Older (earlier date)
        newer_fcf = fcf_values[i + 1]  # Newer (later date)
        older_date = fcf_dates[i]
        newer_date = fcf_dates[i + 1]
        
        if older_fcf != 0:
            growth = (newer_fcf - older_fcf) / abs(older_fcf)
            growth_rates.append(growth)
            fcf_growth_notes.append(f"  {older_date} → {newer_date}: {growth:.1%}")
    
    # Calculate metrics (filter out any NaN/inf values)
    valid_growth_rates = [g for g in growth_rates if np.isfinite(g)]
    
    # For aggregate metrics (avg, median, CAGR), use filtered data if outliers exist
    if outliers_dates:
        fcf_growth_notes.append("\nAggregate Metrics Calculation:")
        fcf_growth_notes.append("  Method: Calculated from non-outlier data only")
        
        # Filter out outlier data points for aggregate calculations
        outlier_dates_set = set(outliers_dates)
        filtered_fcf = [(date, value) for date, value in zip(fcf_dates, fcf_values) 
                        if date not in outlier_dates_set]
        
        if len(filtered_fcf) >= 2:
            filtered_dates, filtered_values = zip(*filtered_fcf)
            
            fcf_growth_notes.append(f"  Data points used: {len(filtered_values)} (excluded {len(outliers_dates)} outliers)")
            fcf_growth_notes.append(f"  Date range: {filtered_dates[0]} to {filtered_dates[-1]}")
            
            # Recalculate growth rates on filtered data for aggregate metrics
            filtered_growth_rates = []
            for i in range(len(filtered_values) - 1):
                older = filtered_values[i]
                newer = filtered_values[i + 1]
                if older != 0:
                    growth = (newer - older) / abs(older)
                    if np.isfinite(growth):
                        filtered_growth_rates.append(growth)
            
            # Use filtered data for aggregate metrics
            avg_growth = np.mean(filtered_growth_rates) if filtered_growth_rates else 0
            median_growth = np.median(filtered_growth_rates) if filtered_growth_rates else 0
            years = len(filtered_values) - 1

            fcf_growth_notes.append(f"  Average Growth: {avg_growth:.1%}")
            fcf_growth_notes.append(f"  Median Growth: {median_growth:.1%}")
            cagr = _append_cagr_note(fcf_growth_notes, filtered_values[0], filtered_values[-1], years)
        else:
            fcf_growth_notes.append("  Warning: Not enough non-outlier data, using all data instead")
            
            # Not enough filtered data, fallback to all data
            avg_growth = np.mean(valid_growth_rates) if valid_growth_rates else 0
            median_growth = np.median(valid_growth_rates) if valid_growth_rates else 0
            years = len(fcf_values) - 1 if len(fcf_values) >= 2 else 0
            start_value = fcf_values[0] if fcf_values else 0
            end_value = fcf_values[-1] if fcf_values else 0

            fcf_growth_notes.append(f"  Average Growth: {avg_growth:.1%}")
            fcf_growth_notes.append(f"  Median Growth: {median_growth:.1%}")
            cagr = _append_cagr_note(fcf_growth_notes, start_value, end_value, years)
    else:
        fcf_growth_notes.append("\nAggregate Metrics Calculation:")
        fcf_growth_notes.append("  Method: Calculated from all data (no outliers detected)")
        
        # No outliers, use all data
        avg_growth = np.mean(valid_growth_rates) if valid_growth_rates else 0
        median_growth = np.median(valid_growth_rates) if valid_growth_rates else 0
        years = len(fcf_values) - 1 if len(fcf_values) >= 2 else 0
        start_value = fcf_values[0] if fcf_values else 0
        end_value = fcf_values[-1] if fcf_values else 0

        fcf_growth_notes.append(f"  Data points used: {len(fcf_values)}")
        fcf_growth_notes.append(f"  Date range: {fcf_dates[0]} to {fcf_dates[-1]}")
        fcf_growth_notes.append(f"  Average Growth: {avg_growth:.1%}")
        fcf_growth_notes.append(f"  Median Growth: {median_growth:.1%}")
        cagr = _append_cagr_note(fcf_growth_notes, start_value, end_value, years)
    
    return {
        'growth_rates': valid_growth_rates,
        'average_growth': avg_growth,
        'median_growth': median_growth,
        'cagr': cagr,
        'fcf_growth_notes': fcf_growth_notes
    }


def _estimate_fcf_growth_rates(cash_flow: pd.DataFrame, forecast_years: int) -> List[float]:
    """Estimate FCF growth rates based on historical data."""
    try:
        if cash_flow.empty or len(cash_flow.columns) < 2:
            # Default conservative growth rates
            return [DEFAULT_MIN_GROWTH] * forecast_years
        
        # Calculate historical FCF growth
        fcf_values = []
        for i in range(min(len(cash_flow.columns), FCF_HISTORICAL_WINDOW)):
            if 'Free Cash Flow' in cash_flow.index:
                fcf = cash_flow.loc['Free Cash Flow'].iloc[i]
            else:
                operating_cf = cash_flow.loc['Operating Cash Flow'].iloc[i] if 'Operating Cash Flow' in cash_flow.index else 0
                capex = cash_flow.loc['Capital Expenditure'].iloc[i] if 'Capital Expenditure' in cash_flow.index else 0
                fcf = operating_cf + capex
            
            fcf_values.append(float(fcf))
        
        # Calculate year-over-year growth rates
        growth_rates = []
        for i in range(len(fcf_values) - 1):
            newer_fcf = fcf_values[i]      # More recent
            older_fcf = fcf_values[i + 1]  # Less recent
            
            if older_fcf != 0:
                growth = (newer_fcf - older_fcf) / abs(older_fcf)
                growth_rates.append(growth)
        
        if growth_rates:
            avg_growth = np.mean(growth_rates)
            # Cap growth rates
            avg_growth = max(MIN_HISTORICAL_GROWTH, min(MAX_HISTORICAL_GROWTH, avg_growth))
            
            # Create declining growth rates over forecast period
            # Start with reasonable growth (max 10%) and decline gradually
            starting_growth = min(MAX_STARTING_GROWTH, avg_growth) if avg_growth > 0 else DEFAULT_MIN_GROWTH
            declining_rates = []
            for year in range(forecast_years):
                decline_factor = GROWTH_DECLINE_FACTOR ** year
                rate = starting_growth * decline_factor
                declining_rates.append(max(MIN_PROJECTED_GROWTH, rate))
            
            return declining_rates
        
    except (KeyError, IndexError, TypeError):
        pass
    
    # Default conservative declining growth rates
    return [DEFAULT_HISTORICAL_BASE_RATE * (GROWTH_DECLINE_FACTOR ** year) for year in range(forecast_years)]


def _project_fcf(current_fcf: float, growth_rates: List[float]) -> List[float]:
    """Project future free cash flows based on growth rates."""
    projected_fcfs = []
    fcf = current_fcf
    
    for growth_rate in growth_rates:
        fcf = fcf * (1 + growth_rate)
        projected_fcfs.append(fcf)
    
    return projected_fcfs


def _estimate_wacc(info: Dict, ticker: str) -> float:
    """Estimate Weighted Average Cost of Capital (WACC).

    WACC = (E/V × Re) + (D/V × Rd × (1-T))
    Where:
        E = Market value of equity (market cap)
        D = Market value of debt (net debt)
        V = E + D (total firm value)
        Re = Cost of equity (from CAPM)
        Rd = Cost of debt
        T = Corporate tax rate

    Cost of Equity (CAPM):
    Re = Rf + β × (Rm - Rf)
    Where:
        Rf = Risk-free rate
        β = Beta (available in info['beta'])
        Rm - Rf = Market risk premium
    """
    try:
        # Get beta for cost of equity calculation
        beta = info.get('beta', DEFAULT_BETA)
        
        # Cost of equity using CAPM: Re = Rf + β(Rm - Rf)
        cost_of_equity = RISK_FREE_RATE + beta * MARKET_RISK_PREMIUM
        
        # Get debt information
        total_debt = info.get('totalDebt', 0)
        market_cap = info.get('marketCap', 0)
        total_cash = info.get('totalCash', 0)
        
        # FIXED: Use gross debt for WACC, not net debt
        if total_debt > 0 and market_cap > 0:
            # Calculate weights using GROSS debt
            total_value = market_cap + total_debt
            weight_equity = market_cap / total_value
            weight_debt = total_debt / total_value
            
            # WACC = (E/V * Re) + (D/V * Rd * (1-T))
            wacc = (weight_equity * cost_of_equity) + (weight_debt * COST_OF_DEBT * (1 - CORPORATE_TAX_RATE))
        else:
            # If no debt information, use cost of equity
            wacc = cost_of_equity
        
        # Ensure WACC is reasonable
        return max(MIN_WACC, min(MAX_WACC, wacc))
    
    except (KeyError, TypeError):
        # Default WACC for technology companies
        return DEFAULT_WACC


def _get_net_debt(info: Dict) -> float:
    """Calculate net debt (total debt - cash and cash equivalents)."""
    total_debt = info.get('totalDebt', 0)
    total_cash = info.get('totalCash', 0)
    
    return max(0, total_debt - total_cash)  # Net debt can't be negative for valuation

def get_recomendation_from_upside_potential(upside_potential_pct: float) -> str:
    """Get a recommendation based on the upside potential."""
    if upside_potential_pct > 20:
        return "STRONG BUY"
    elif upside_potential_pct > 10:
        return "BUY"
    elif upside_potential_pct > -10:
        return "HOLD"
    else:
        return "SELL"

def print_dcf_analysis(valuation_result: Dict) -> None:
    """Print a formatted DCF valuation analysis."""
    result = valuation_result
    
    # Get currencies for the ticker
    ticker = result['ticker']
    stock_info = get_or_create_stock_info(ticker)
    trading_currency = stock_info.get('currency') or 'n/a'  # Trading currency for current price
    financial_currency = stock_info.get('financialCurrency') or stock_info.get('currency') or 'n/a'  # Financial currency for valuation numbers
    
    # Helper function to format currency amounts
    def format_currency(amount: float, currency: str, decimals: int = 2) -> str:
        """Format amount with currency code."""
        if decimals == 0:
            return f"{currency} {amount:,.0f}"
        else:
            return f"{currency} {amount:,.{decimals}f}"
    
    print(f"\n{'='*60}")
    print(f"DCF VALUATION ANALYSIS: {result['ticker']}")
    print(f"{'='*60}")
    
    print(f"\nCURRENT MARKET DATA:")
    print(f"Current Price: {format_currency(result['current_price'], trading_currency, 2)}")
    print(f"Shares Outstanding: {result['shares_outstanding']:,.0f}")
    
    print(f"\nVALUATION INPUTS:")
    print(f"Forecast Years: {result['in_forecast_years']}")
    print(f"Current FCF: {format_currency(result['current_fcf'], financial_currency, 0)}")
    print(f"Discount Rate (WACC): {result['in_discount_rate']:.1%}")
    print(f"Terminal Growth Rate: {result['in_terminal_growth_rate']:.1%}")
    print(f"Conservative Factor: {result['in_conservative_factor']:.1%}")
    print(f"Net Debt: {format_currency(result['net_debt'], financial_currency, 0)}")
    
    print(f"\nPROJECTED FREE CASH FLOWS:")
    projected_fcfs = result['projected_fcfs']
    growth_rates = result['in_fcf_growth_rates']
    # Ensure both lists have the same length (use the minimum to avoid mismatches)
    min_length = min(len(projected_fcfs), len(growth_rates))
    for i in range(min_length):
        print(f"Year {i+1}: {format_currency(projected_fcfs[i], financial_currency, 0)} (Growth: {growth_rates[i]:.1%})")
    
    print(f"\nVALUATION RESULTS:")
    print(f"Terminal Value: {format_currency(result['terminal_value'], financial_currency, 0)}")
    print(f"Present Value of FCFs: {format_currency(sum(result['pv_fcfs']), financial_currency, 0)}")
    print(f"Present Value of Terminal: {format_currency(result['pv_terminal_value'], financial_currency, 0)}")
    print(f"Total Enterprise Value: {format_currency(result['total_enterprise_value'], financial_currency, 0)}")
    print(f"Equity Value: {format_currency(result['equity_value'], financial_currency, 0)}")
    
    print(f"\nFAIR VALUE ESTIMATES:")
    print(f"Fair Value per Share: {format_currency(result['fair_value_per_share'], trading_currency, 2)}")
    print(f"Conservative Fair Value: {format_currency(result['conservative_fair_value'], trading_currency, 2)}")
    
    print(f"\nINVESTMENT RECOMMENDATION:")
    recommendation = get_recomendation_from_upside_potential(result['upside_potential_pct'])
    
    print(f"Upside Potential: {result['upside_potential_pct']:.1f}%")
    print(f"Conservative Upside: {result['conservative_upside_pct']:.1f}%")
    print(f"Recommendation: {recommendation}")
    
    print(f"\n{'='*60}")


