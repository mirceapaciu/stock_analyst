"""
Financial data service for retrieving and caching stock financial statements.
"""
from typing import Dict, Optional
import yfinance as yf
import pandas as pd
import logging
from repositories.stocks_db import StockRepository
from config import DB_PATH

logger = logging.getLogger(__name__)

def save_financial_statements( 
    ticker: str,
    statement_type: str,
    df: pd.DataFrame
):
    # Don't save empty DataFrames
    if df is None or df.empty:
        logger.warning(f"Skipping save of empty {statement_type} statement for {ticker}")
        return

    # Make sure the stock exists in the database
    stock_info = get_or_create_stock_info(ticker)
    if stock_info is None:
        raise ValueError(f"Stock info not found for ticker: {ticker}")
    
    stock_id = stock_info.get('id')
    if stock_id is None:
        raise ValueError(f"Stock id not found for ticker: {ticker}")

    # Save the financial statements to the database
    repo = StockRepository()
    repo.save_financial_statements_to_db(ticker, stock_id, statement_type, df)

def get_financial_statements(
    ticker: str,
    statement_type: str = 'all',
    db_path: str = DB_PATH
) -> Dict[str, pd.DataFrame]:
    """
    Retrieve financial statements for a stock from DB or yfinance API.
    
    Args:
        ticker (str): Stock ticker symbol (e.g., 'MSFT')
        statement_type (str): Type of statement to retrieve:
            - 'income': Income statement
            - 'balance': Balance sheet
            - 'cashflow': Cash flow statement
            - 'all': All three statements (default)
        db_path (str): Path to SQLite database file
    
    Returns:
        Dict[str, pd.DataFrame]: Dictionary with statement types as keys and DataFrames as values
            Example: {'income': df_income, 'balance': df_balance, 'cashflow': df_cashflow}
    """
    # Validate statement_type
    valid_types = ['income', 'balance', 'cashflow', 'all']
    if statement_type not in valid_types:
        raise ValueError(f"Invalid statement_type. Must be one of {valid_types}")
    
    # Determine which statements to retrieve
    if statement_type == 'all':
        statement_types = ['income', 'balance', 'cashflow']
    else:
        statement_types = [statement_type]
    
    # Initialize repository
    repo = StockRepository(db_path)
    result = {}
    
    for stmt_type in statement_types:
        # Try to get from database first
        df = repo.get_financial_statements(ticker, stmt_type)
        
        if df is None or df.empty:
            # Not in cache - fetch from yfinance and save to DB
            df = _fetch_from_yfinance(ticker, stmt_type)
            if df is not None and not df.empty:
                save_financial_statements(ticker, stmt_type, df)
        
        # Only add to result if df is not None and not empty
        if df is not None and not df.empty:
            result[stmt_type] = df
    
    return result

def get_historical_fcf(ticker: str, years_of_history: int = 5) -> (list, list):
    """
    Retrieve historical Free Cash Flow (FCF) data for a stock.
    """
    
    statements = get_financial_statements(ticker, statement_type='cashflow')
    cash_flow = statements.get('cashflow')
    
    if cash_flow is None or cash_flow.empty:
        raise ValueError(f"No cash flow data available for {ticker}")
    
    # Extract historical FCF values (excluding NaN values)
    # Collect as pairs to maintain date-FCF correspondence
    fcf_pairs = []
    
    for i in range(min(len(cash_flow.columns), years_of_history)):
        date = cash_flow.columns[i]
        if 'Free Cash Flow' in cash_flow.index:
            fcf = cash_flow.loc['Free Cash Flow'].iloc[i]
        else:
            operating_cf = cash_flow.loc['Operating Cash Flow'].iloc[i] if 'Operating Cash Flow' in cash_flow.index else 0
            capex = cash_flow.loc['Capital Expenditure'].iloc[i] if 'Capital Expenditure' in cash_flow.index else 0
            fcf = operating_cf + capex
        
        # Skip NaN values
        if pd.notna(fcf):
            fcf_pairs.append((date, float(fcf)))
    
    # Sort by date chronologically (oldest to newest)
    fcf_pairs.sort(key=lambda x: pd.to_datetime(x[0]))
    
    # Extract sorted values and dates
    fcf_dates = [pair[0] for pair in fcf_pairs]
    fcf_values = [pair[1] for pair in fcf_pairs]  
    return fcf_dates, fcf_values


def get_or_create_stock_info(ticker: str, force_fetch: bool = False) -> Dict:
    """
    Get or create stock record and return stock information dictionary.
    
    If stock doesn't exist in database, retrieves stock data from yfinance
    and upserts it using StockRepository.upsert_stock().
    
    Args:
        ticker (str): Stock ticker symbol
        force_fetch: If True, will fetch stock data from yfinance even if it already exists in the database
    
    Returns:
        Dict: Dictionary containing stock information including 'id', 'shortName', 'longName',
              'sector', 'industry', 'country', 'currency', 'financialCurrency', 'exchange',
              'sharesOutstanding', 'marketCap', 'currentPrice', 'beta', 'dividendRate',
              'dividendYield', 'payoutRatio', and other fields from yfinance.
              Returns empty dict {} if stock not found and cannot be fetched.
    """
    repo = StockRepository()
    
    stock_info = None
    if not force_fetch:
        # Try to get stock info from database
        stock_info = repo.get_stock_info(ticker)
    
    if stock_info is None or force_fetch:
        # Stock not found - fetch from yfinance and upsert
        stock_info = _fetch_stock_info_from_yfinance(ticker)
        if stock_info:
            stock_id = repo.upsert_stock(ticker, stock_info)
            stock_info['id'] = stock_id
        else:
            raise ValueError(f"Could not retrieve stock data for ticker: {ticker}")
    
    return stock_info if stock_info else {}


# In src/services/financial.py
def get_or_create_stock_id(ticker: str) -> int:
    """
    Get or create stock record and return stock_id.
    
    Args:
        ticker (str): Stock ticker symbol
    
    Returns:
        int: Stock ID from database (guaranteed to exist after this call)
    """
    stock_info = get_or_create_stock_info(ticker)    
    return stock_info.get('id')

def _fetch_stock_info_from_yfinance(ticker: str) -> Optional[Dict]:
    """
    Fetch stock information from yfinance API.
    
    Returns:
        Dict or None if error
    """
    try:
        stock = yf.Ticker(ticker)
        return stock.info
    except Exception:
        return None


def _fetch_from_yfinance(ticker: str, statement_type: str) -> Optional[pd.DataFrame]:
    """
    Fetch financial statement data from yfinance API.
    
    Returns:
        pd.DataFrame or None if error or empty
    """
    try:
        stock = yf.Ticker(ticker)
        
        # Map statement type to yfinance attribute
        if statement_type == 'income':
            df = stock.financials
        elif statement_type == 'balance':
            df = stock.balance_sheet
        elif statement_type == 'cashflow':
            df = stock.cashflow
        else:
            logger.warning(f"Unknown statement type: {statement_type}")
            return None
        
        if df is None or df.empty:
            logger.warning(f"Empty {statement_type} statement returned from yfinance for {ticker}")
            return None
        
        return df
    
    except Exception as e:
        logger.warning(f"Error fetching {statement_type} statement from yfinance for {ticker}: {e}")
        return None
