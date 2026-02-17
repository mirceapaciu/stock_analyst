"""
Stock risk evaluation module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from fin_config import (
    RISK_LOOKBACK_YEARS,
    RISK_VAR_ALPHA,
    RISK_VOLATILITY_LOW,
    RISK_VOLATILITY_HIGH,
    RISK_DOWNSIDE_DEV_LOW,
    RISK_DOWNSIDE_DEV_HIGH,
    RISK_VAR_LOW,
    RISK_VAR_HIGH,
    RISK_CVAR_LOW,
    RISK_CVAR_HIGH,
    RISK_BETA_LOW,
    RISK_BETA_HIGH,
    RISK_MAX_DRAWDOWN_LOW,
    RISK_MAX_DRAWDOWN_HIGH,
    RISK_DRAWDOWN_DAYS_LOW,
    RISK_DRAWDOWN_DAYS_HIGH,
    RISK_DEBT_EQUITY_LOW,
    RISK_DEBT_EQUITY_HIGH,
    RISK_NET_DEBT_EBITDA_LOW,
    RISK_NET_DEBT_EBITDA_HIGH,
    RISK_INTEREST_COVERAGE_LOW,
    RISK_INTEREST_COVERAGE_HIGH,
    RISK_CURRENT_RATIO_LOW,
    RISK_CURRENT_RATIO_HIGH,
    RISK_QUICK_RATIO_LOW,
    RISK_QUICK_RATIO_HIGH,
    RISK_FCF_VOLATILITY_LOW,
    RISK_FCF_VOLATILITY_HIGH,
    RISK_REVENUE_VOLATILITY_LOW,
    RISK_REVENUE_VOLATILITY_HIGH,
    RISK_MARGIN_VOLATILITY_LOW,
    RISK_MARGIN_VOLATILITY_HIGH,
    RISK_SCORE_WEIGHTS,
    RISK_CACHE_DAYS,
    RISK_DCF_DISCOUNT_GRID,
    RISK_DCF_TERMINAL_GROWTH_GRID,
)
from services.financial import get_financial_statements, get_or_create_stock_info, get_historical_fcf
from services.currency import convert_currency
from services.valuation import do_dcf_valuation
from repositories.stocks_db import StockRepository


REGIONAL_BENCHMARKS = {
    "US": "^GSPC",
    "Canada": "^GSPTSE",
    "UK": "^FTSE",
    "Eurozone": "^STOXX50E",
    "Germany": "^GDAXI",
    "France": "^FCHI",
    "Japan": "^N225",
    "Hong Kong": "^HSI",
    "Australia": "^AXJO",
}

EXCHANGE_REGION_MAP = {
    "NYQ": "US",
    "NMS": "US",
    "NAS": "US",
    "ASE": "US",
    "TSX": "Canada",
    "TOR": "Canada",
    "LSE": "UK",
    "FRA": "Germany",
    "GER": "Germany",
    "PAR": "France",
    "PA": "France",
    "JPX": "Japan",
    "TSE": "Japan",
    "HKG": "Hong Kong",
    "ASX": "Australia",
}

COUNTRY_REGION_MAP = {
    "United States": "US",
    "USA": "US",
    "Canada": "Canada",
    "United Kingdom": "UK",
    "UK": "UK",
    "Germany": "Germany",
    "France": "France",
    "Japan": "Japan",
    "Hong Kong": "Hong Kong",
    "Australia": "Australia",
}


@dataclass
class PriceSeries:
    close: pd.Series
    returns: pd.Series


def get_risk_evaluation(
    ticker: str,
    benchmark: Optional[str] = None,
    lookback_years: int = RISK_LOOKBACK_YEARS,
    use_cache_days: int = RISK_CACHE_DAYS,
    force_refresh: bool = False,
    include_valuation_sensitivity: bool = True,
) -> Dict:
    """
    Compute risk evaluation metrics and store them in the database.
    """
    stock_info = get_or_create_stock_info(ticker)
    stock_id = stock_info.get("id")
    if stock_id is None:
        raise ValueError(f"Stock id not found for ticker: {ticker}")

    with StockRepository() as repo:
        if not force_refresh and use_cache_days > 0:
            cached = repo.get_latest_risk_evaluation(stock_id)
            if cached:
                last_date = cached.get("evaluation_date")
                if last_date and _is_within_days(last_date, use_cache_days):
                    return cached

    benchmark_symbol = benchmark or _select_regional_benchmark(stock_info)

    price_series = _get_price_series(ticker, lookback_years)
    benchmark_series = _get_price_series(benchmark_symbol, lookback_years)

    aligned = price_series.returns.to_frame("stock").join(
        benchmark_series.returns.to_frame("benchmark"),
        how="inner",
    )

    metrics = _calculate_price_metrics(aligned["stock"], aligned["benchmark"])
    metrics.update(_calculate_drawdown_metrics(price_series.close))
    metrics.update(_calculate_fundamental_metrics(ticker))

    valuation_sensitivity = None
    if include_valuation_sensitivity:
        valuation_sensitivity = _calculate_valuation_sensitivity(ticker, stock_info)

    sub_scores = _calculate_sub_scores(metrics, valuation_sensitivity)
    overall_score = _weighted_score(sub_scores)
    risk_label = _label_from_score(overall_score)

    result = {
        "ticker": ticker,
        "benchmark": benchmark_symbol,
        "lookback_years": lookback_years,
        "risk_score": overall_score,
        "risk_label": risk_label,
        "sub_scores": sub_scores,
        "metrics": metrics,
        "valuation_sensitivity": valuation_sensitivity,
    }

    with StockRepository() as repo:
        repo.save_risk_evaluation(stock_id, result)

    return result


def _is_within_days(date_value: str, days: int) -> bool:
    try:
        date_obj = datetime.fromisoformat(str(date_value)).date()
    except ValueError:
        return False
    return date_obj >= (datetime.utcnow().date() - timedelta(days=days))


def _select_regional_benchmark(stock_info: Dict) -> str:
    exchange = (stock_info.get("exchange") or "").upper()
    country = stock_info.get("country") or ""

    region = EXCHANGE_REGION_MAP.get(exchange)
    if region is None:
        region = COUNTRY_REGION_MAP.get(country)

    if region is None:
        return REGIONAL_BENCHMARKS["US"]

    return REGIONAL_BENCHMARKS.get(region, REGIONAL_BENCHMARKS["US"])


def _get_price_series(symbol: str, years: int) -> PriceSeries:
    period = f"{years}y"
    history = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
    if history is None or history.empty:
        raise ValueError(f"No price history for {symbol}")

    close = history["Close"].dropna()
    returns = close.pct_change().dropna()

    if returns.empty:
        raise ValueError(f"Not enough price history for {symbol}")

    return PriceSeries(close=close, returns=returns)


def _calculate_price_metrics(stock_returns: pd.Series, benchmark_returns: pd.Series) -> Dict:
    metrics: Dict[str, Optional[float]] = {}

    volatility = stock_returns.std() * np.sqrt(252)
    downside_dev = stock_returns[stock_returns < 0].std() * np.sqrt(252)
    var_95, cvar_95 = _calculate_var_cvar(stock_returns, RISK_VAR_ALPHA)
    beta = _calculate_beta(stock_returns, benchmark_returns)

    metrics["volatility"] = _safe_float(volatility)
    metrics["downside_deviation"] = _safe_float(downside_dev)
    metrics["var_95"] = _safe_float(var_95)
    metrics["cvar_95"] = _safe_float(cvar_95)
    metrics["beta"] = _safe_float(beta)
    metrics["observations"] = int(stock_returns.shape[0])

    return metrics


def _calculate_var_cvar(returns: pd.Series, alpha: float) -> Tuple[Optional[float], Optional[float]]:
    if returns.empty:
        return None, None

    var_threshold = np.quantile(returns, alpha)
    tail = returns[returns <= var_threshold]

    var_value = -float(var_threshold)
    cvar_value = -float(tail.mean()) if not tail.empty else None

    return var_value, cvar_value


def _calculate_beta(stock_returns: pd.Series, benchmark_returns: pd.Series) -> Optional[float]:
    if stock_returns.empty or benchmark_returns.empty:
        return None

    covariance = np.cov(stock_returns, benchmark_returns)[0, 1]
    variance = np.var(benchmark_returns)

    if variance == 0:
        return None

    return float(covariance / variance)


def _calculate_drawdown_metrics(prices: pd.Series) -> Dict:
    if prices.empty:
        return {"max_drawdown": None, "max_drawdown_days": None, "recovery_days": None}

    cumulative = (1 + prices.pct_change().fillna(0)).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative / running_max) - 1

    max_drawdown = float(drawdown.min())
    max_drawdown_pct = -max_drawdown if max_drawdown < 0 else 0

    durations = _drawdown_durations(drawdown)
    max_duration = max(durations) if durations else 0

    recovery_days = _recovery_days(drawdown)

    return {
        "max_drawdown": max_drawdown_pct,
        "max_drawdown_days": int(max_duration) if max_duration else None,
        "recovery_days": recovery_days,
    }


def _drawdown_durations(drawdown: pd.Series) -> List[int]:
    durations: List[int] = []
    current = 0
    for value in drawdown:
        if value < 0:
            current += 1
        else:
            if current > 0:
                durations.append(current)
                current = 0
    if current > 0:
        durations.append(current)
    return durations


def _recovery_days(drawdown: pd.Series) -> Optional[int]:
    min_idx = drawdown.idxmin()
    if drawdown.loc[min_idx] == 0:
        return 0

    post = drawdown.loc[min_idx:]
    recovered = post[post >= 0]
    if recovered.empty:
        return None

    recovery_idx = recovered.index[0]
    delta = recovery_idx - min_idx
    try:
        return int(delta.days)
    except AttributeError:
        return None


def _calculate_fundamental_metrics(ticker: str) -> Dict:
    statements = get_financial_statements(ticker, statement_type="all")
    balance = statements.get("balance")
    income = statements.get("income")

    metrics: Dict[str, Optional[float]] = {}

    total_debt = _get_latest_value(balance, [
        "Total Debt",
        "Long Term Debt",
        "Long Term Debt And Capital Lease Obligation",
        "Short Long Term Debt",
        "Short Long Term Debt Total",
        "Total Liab",
    ])
    total_equity = _get_latest_value(balance, [
        "Total Stockholder Equity",
        "Total Equity Gross Minority Interest",
        "Stockholders Equity",
    ])
    total_cash = _get_latest_value(balance, [
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Short Term Investments",
    ])
    current_assets = _get_latest_value(balance, ["Current Assets"])
    current_liabilities = _get_latest_value(balance, ["Current Liabilities"])
    inventory = _get_latest_value(balance, ["Inventory"]) or 0

    debt_equity = _safe_divide(total_debt, total_equity)
    net_debt_ebitda = _safe_divide(_safe_subtract(total_debt, total_cash), _get_latest_value(income, ["EBITDA"]))

    ebit = _get_latest_value(income, ["EBIT", "Ebit", "Operating Income", "Operating Income or Loss"])
    interest_expense = _get_latest_value(income, ["Interest Expense", "Interest Expense Non Operating"])
    interest_coverage = _safe_divide(ebit, abs(interest_expense) if interest_expense else None)

    current_ratio = _safe_divide(current_assets, current_liabilities)
    quick_ratio = _safe_divide(_safe_subtract(current_assets, inventory), current_liabilities)

    metrics["debt_to_equity"] = debt_equity
    metrics["net_debt_to_ebitda"] = net_debt_ebitda
    metrics["interest_coverage"] = interest_coverage
    metrics["current_ratio"] = current_ratio
    metrics["quick_ratio"] = quick_ratio

    metrics.update(_calculate_cashflow_stability(ticker))
    metrics.update(_calculate_revenue_stability(income))

    return metrics


def _calculate_cashflow_stability(ticker: str) -> Dict:
    metrics: Dict[str, Optional[float]] = {"fcf_volatility": None}
    try:
        _, fcf_values = get_historical_fcf(ticker, years_of_history=5)
    except Exception:
        return metrics

    if len(fcf_values) < 2:
        return metrics

    mean_value = float(np.mean(fcf_values))
    std_value = float(np.std(fcf_values))

    if mean_value == 0:
        return metrics

    metrics["fcf_volatility"] = abs(std_value / mean_value)
    return metrics


def _calculate_revenue_stability(income: Optional[pd.DataFrame]) -> Dict:
    metrics: Dict[str, Optional[float]] = {
        "revenue_cagr": None,
        "revenue_volatility": None,
        "operating_margin_volatility": None,
    }

    if income is None or income.empty:
        return metrics

    revenue_series = _get_series(income, ["Total Revenue"])
    operating_income_series = _get_series(income, ["Operating Income", "Operating Income or Loss"])

    if revenue_series is None or revenue_series.empty:
        return metrics

    revenue_values = revenue_series.values
    if len(revenue_values) >= 2:
        start_value = revenue_values[0]
        end_value = revenue_values[-1]
        years = len(revenue_values) - 1
        if start_value and years > 0:
            metrics["revenue_cagr"] = (end_value / start_value) ** (1 / years) - 1

        revenue_growth = pd.Series(revenue_values).pct_change().dropna()
        if not revenue_growth.empty:
            metrics["revenue_volatility"] = float(revenue_growth.std())

    if operating_income_series is not None and not operating_income_series.empty:
        aligned = revenue_series.align(operating_income_series, join="inner")
        revenue_aligned = aligned[0]
        operating_aligned = aligned[1]
        margins = operating_aligned / revenue_aligned
        if not margins.empty:
            metrics["operating_margin_volatility"] = float(margins.std())

    return metrics


def _calculate_valuation_sensitivity(ticker: str, stock_info: Dict) -> Optional[Dict]:
    try:
        base = do_dcf_valuation(ticker=ticker)
    except Exception:
        return None

    projected_fcfs = base.get("projected_fcfs")
    shares_outstanding = base.get("shares_outstanding")
    net_debt = base.get("net_debt")
    current_price = base.get("current_price")

    if not projected_fcfs or not shares_outstanding:
        return None

    financial_currency = stock_info.get("financialCurrency") or stock_info.get("currency")
    trading_currency = stock_info.get("currency")

    grid: List[Dict[str, float]] = []

    for discount_rate in RISK_DCF_DISCOUNT_GRID:
        for terminal_growth in RISK_DCF_TERMINAL_GROWTH_GRID:
            if discount_rate <= terminal_growth:
                continue
            fair_value = _compute_fair_value_per_share(
                projected_fcfs,
                discount_rate,
                terminal_growth,
                net_debt,
                shares_outstanding,
                financial_currency,
                trading_currency,
            )
            if fair_value is None:
                continue
            grid.append({
                "discount_rate": discount_rate,
                "terminal_growth_rate": terminal_growth,
                "fair_value_per_share": fair_value,
            })

    if not grid or current_price is None:
        return None

    below_market = [item for item in grid if item["fair_value_per_share"] < current_price]
    pct_below = len(below_market) / len(grid)

    return {
        "grid": grid,
        "percent_below_market": pct_below,
    }


def _compute_fair_value_per_share(
    projected_fcfs: List[float],
    discount_rate: float,
    terminal_growth_rate: float,
    net_debt: float,
    shares_outstanding: float,
    financial_currency: Optional[str],
    trading_currency: Optional[str],
) -> Optional[float]:
    if not projected_fcfs:
        return None

    pv_fcfs = []
    for year, fcf in enumerate(projected_fcfs, 1):
        pv_fcfs.append(fcf / (1 + discount_rate) ** year)

    terminal_fcf = projected_fcfs[-1] * (1 + terminal_growth_rate)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth_rate)
    pv_terminal_value = terminal_value / (1 + discount_rate) ** len(projected_fcfs)

    total_enterprise_value = sum(pv_fcfs) + pv_terminal_value
    equity_value = total_enterprise_value - (net_debt or 0)
    fair_value = equity_value / shares_outstanding

    if financial_currency and trading_currency:
        return convert_currency(fair_value, financial_currency, trading_currency)

    return fair_value


def _calculate_sub_scores(metrics: Dict, valuation_sensitivity: Optional[Dict]) -> Dict:
    market_risk = _average_scores([
        _score_from_range(metrics.get("volatility"), RISK_VOLATILITY_LOW, RISK_VOLATILITY_HIGH),
        _score_from_range(metrics.get("beta"), RISK_BETA_LOW, RISK_BETA_HIGH),
    ])

    downside_risk = _average_scores([
        _score_from_range(metrics.get("downside_deviation"), RISK_DOWNSIDE_DEV_LOW, RISK_DOWNSIDE_DEV_HIGH),
        _score_from_range(metrics.get("var_95"), RISK_VAR_LOW, RISK_VAR_HIGH),
        _score_from_range(metrics.get("cvar_95"), RISK_CVAR_LOW, RISK_CVAR_HIGH),
    ])

    drawdown_risk = _average_scores([
        _score_from_range(metrics.get("max_drawdown"), RISK_MAX_DRAWDOWN_LOW, RISK_MAX_DRAWDOWN_HIGH),
        _score_from_range(metrics.get("max_drawdown_days"), RISK_DRAWDOWN_DAYS_LOW, RISK_DRAWDOWN_DAYS_HIGH),
    ])

    leverage_risk = _average_scores([
        _score_from_range(metrics.get("debt_to_equity"), RISK_DEBT_EQUITY_LOW, RISK_DEBT_EQUITY_HIGH),
        _score_from_range(metrics.get("net_debt_to_ebitda"), RISK_NET_DEBT_EBITDA_LOW, RISK_NET_DEBT_EBITDA_HIGH),
        _score_from_range(metrics.get("interest_coverage"), RISK_INTEREST_COVERAGE_LOW, RISK_INTEREST_COVERAGE_HIGH, higher_is_risk=False),
        _score_from_range(metrics.get("current_ratio"), RISK_CURRENT_RATIO_LOW, RISK_CURRENT_RATIO_HIGH, higher_is_risk=False),
        _score_from_range(metrics.get("quick_ratio"), RISK_QUICK_RATIO_LOW, RISK_QUICK_RATIO_HIGH, higher_is_risk=False),
    ])

    stability_risk = _average_scores([
        _score_from_range(metrics.get("fcf_volatility"), RISK_FCF_VOLATILITY_LOW, RISK_FCF_VOLATILITY_HIGH),
        _score_from_range(metrics.get("revenue_volatility"), RISK_REVENUE_VOLATILITY_LOW, RISK_REVENUE_VOLATILITY_HIGH),
        _score_from_range(metrics.get("operating_margin_volatility"), RISK_MARGIN_VOLATILITY_LOW, RISK_MARGIN_VOLATILITY_HIGH),
    ])

    valuation_risk = None
    if valuation_sensitivity and valuation_sensitivity.get("percent_below_market") is not None:
        valuation_risk = float(valuation_sensitivity["percent_below_market"] * 100)

    return {
        "market": market_risk,
        "downside": downside_risk,
        "drawdown": drawdown_risk,
        "leverage": leverage_risk,
        "stability": stability_risk,
        "valuation": valuation_risk,
    }


def _weighted_score(sub_scores: Dict) -> float:
    total = 0.0
    weight_sum = 0.0
    for key, weight in RISK_SCORE_WEIGHTS.items():
        score = sub_scores.get(key)
        if score is None:
            continue
        total += score * weight
        weight_sum += weight

    if weight_sum == 0:
        return 0.0

    return total / weight_sum


def _label_from_score(score: float) -> str:
    if score < 25:
        return "Low"
    if score < 50:
        return "Moderate"
    if score < 75:
        return "Elevated"
    return "High"


def _score_from_range(
    value: Optional[float],
    low: float,
    high: float,
    higher_is_risk: bool = True,
) -> Optional[float]:
    if value is None:
        return None

    if higher_is_risk:
        if value <= low:
            return 0.0
        if value >= high:
            return 100.0
        return float((value - low) / (high - low) * 100)

    if value >= high:
        return 0.0
    if value <= low:
        return 100.0
    return float((high - value) / (high - low) * 100)


def _average_scores(scores: List[Optional[float]]) -> Optional[float]:
    valid = [score for score in scores if score is not None]
    if not valid:
        return None
    return float(sum(valid) / len(valid))


def _get_latest_value(df: Optional[pd.DataFrame], keys: List[str]) -> Optional[float]:
    if df is None or df.empty:
        return None

    for key in keys:
        if key in df.index:
            value = df.loc[key].iloc[0]
            if pd.notna(value):
                return float(value)
    return None


def _get_series(df: pd.DataFrame, keys: List[str]) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None

    for key in keys:
        if key in df.index:
            series = df.loc[key].dropna()
            if series.empty:
                return None
            try:
                series.index = pd.to_datetime(series.index)
                series = series.sort_index()
            except Exception:
                series = series.sort_index()
            return series.astype(float)
    return None


def _safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _safe_subtract(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None and b is None:
        return None
    return (a or 0.0) - (b or 0.0)


def _safe_float(value: Optional[float]) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return float(value)
