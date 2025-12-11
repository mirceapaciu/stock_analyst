"""
Currency and exchange rate service for currency conversion and exchange rate management.
"""
from typing import Optional
import yfinance as yf
import logging
from datetime import date
from repositories.stocks_db import StockRepository
from services.financial import get_or_create_stock_info

logger = logging.getLogger(__name__)


def get_financial_currency(ticker: str) -> Optional[str]:
    """
    Get the currency used in financial statements for a stock.
    
    In yfinance, financial statements may be in a different currency than
    the trading currency. This function returns the 'financialCurrency' field
    from the stock info, which indicates the currency of financial statements.
    
    Args:
        ticker (str): Stock ticker symbol
    
    Returns:
        str: Currency code (e.g., 'USD', 'EUR', 'GBP') or None if not available
    """
    stock_info = get_or_create_stock_info(ticker)
    if stock_info:
        # financialCurrency is the currency used in financial statements
        # If not available, fall back to currency (trading currency)
        return stock_info.get('financialCurrency') or stock_info.get('currency')
    return None


def is_financial_currency_usd(ticker: str) -> bool:
    """
    Check if a stock's financial data is reported in USD.
    
    Args:
        ticker (str): Stock ticker symbol
    
    Returns:
        bool: True if financial currency is USD, False otherwise
    """
    currency = get_financial_currency(ticker)
    return currency is not None and currency.upper() == 'USD'


def get_exchange_rate(source_currency: str, target_currency: str) -> Optional[float]:
    """
    Get exchange rate for a currency pair.
    
    First tries to get the last cached rate from the database.
    If no cached rate is found, fetches the latest rate from yfinance
    and saves it to the database.
    
    Args:
        source_currency: Source currency code (e.g., 'EUR', 'USD')
        target_currency: Target currency code (e.g., 'USD', 'EUR')
    
    Returns:
        Exchange rate (float) or None if not found
    """
    # Normalize currency codes
    source_currency = source_currency.upper() if source_currency else None
    target_currency = target_currency.upper() if target_currency else None
    
    if not source_currency or not target_currency:
        return None
    
    # If currencies are the same, return 1.0
    if source_currency == target_currency:
        return 1.0
    
    # Try to get last cached rate from database
    with StockRepository() as repo:
        result = repo.get_last_exchange_rate(source_currency, target_currency)
        
        if result:
            rate, rate_date = result
            return rate
        
        # No cached rate found, fetch from yfinance
        try:
            # yfinance uses format "FROMTO=X" for currency pairs (e.g., "EURUSD=X")
            logger.debug(f"Retrieving the exchange rate {source_currency}/{target_currency} from yfinance")
            ticker_symbol = f"{source_currency}{target_currency}=X"
            ticker = yf.Ticker(ticker_symbol)
            
            # Get the latest price (exchange rate)
            hist = ticker.history(period="1d")
            if not hist.empty:
                # Use the close price as the exchange rate
                rate = float(hist['Close'].iloc[-1])
            else:
                # Try to get from info if history is empty
                info = ticker.info
                if info and 'regularMarketPrice' in info:
                    rate = float(info['regularMarketPrice'])
                elif info and 'previousClose' in info:
                    rate = float(info['previousClose'])
                else:
                    logger.warning(f"Could not fetch exchange rate for {source_currency} to {target_currency}")
                    return None
            
            # Save the rate to database (for today's date)
            today = date.today()
            repo.save_exchange_rate(source_currency, target_currency, rate, today)
            logger.info(f"Fetched and cached exchange rate {source_currency}/{target_currency} = {rate} for {today}")
            return rate
        
        except Exception as e:
            logger.error(f"Error fetching exchange rate from yfinance: {e}")
            return None


def convert_currency(amount: float, source_currency: str, target_currency: str) -> float:
    """
    Convert an amount from one currency to another using exchange rates.
    
    Uses get_exchange_rate() to retrieve rates from cache or yfinance.
    If currencies are the same, returns the amount unchanged.
    If either currency is unknown ('n/a'), returns the amount unchanged without conversion.
    
    Args:
        amount: Amount to convert
        source_currency: Source currency code (e.g., 'EUR', 'USD')
        target_currency: Target currency code (e.g., 'USD', 'EUR')
    
    Returns:
        Converted amount in target currency
    """
    # Check if either currency is unknown - if so, don't convert
    if not source_currency or not target_currency:
        return amount
    
    # Normalize currency codes for comparison
    source_currency_upper = source_currency.upper()
    target_currency_upper = target_currency.upper()
    
    # If currency is unknown ('n/a'), don't convert
    if source_currency_upper == 'N/A' or target_currency_upper == 'N/A':
        return amount
    
    # Normalize currency codes
    source_currency = source_currency_upper
    target_currency = target_currency_upper
    
    # If currencies are the same, no conversion needed
    if source_currency == target_currency:
        return amount
    
    # Get exchange rate
    rate = get_exchange_rate(source_currency, target_currency)
    
    if rate is None:
        logger.warning(f"Could not get exchange rate for {source_currency} to {target_currency}, returning amount unchanged")
        return amount
    
    # Convert the amount
    converted_amount = amount * rate
    return converted_amount

