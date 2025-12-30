"""
Stock data repository for database operations using DuckDB.
"""
import duckdb
from datetime import datetime, date
from typing import Optional, List, Tuple
import pandas as pd
import sys
import os
import logging

logger = logging.getLogger(__name__)

# Add parent directory to path to import config
_parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
from config import DB_PATH
# Import s3_storage lazily to avoid circular import issues


class StockRepository:
    """Repository for stock financial data database operations using DuckDB."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn = None
        
        # Try to download database from S3 on initialization (only if S3 is configured and not using EFS)
        # EFS provides persistent storage, so S3 sync is optional/for backup
        use_s3_sync = os.getenv("USE_S3_SYNC", "true").lower() == "true"
        if use_s3_sync:
            from utils.s3_storage import get_s3_storage
            s3 = get_s3_storage()
            if s3.s3_client:
                logger.info(f"Checking S3 for existing database: {os.path.basename(db_path)}")
                s3.sync_database_from_s3(db_path)
        
        # FIXME: This is needed only at the start of the application
        # self._ensure_tables_exist()
    
    def _ensure_tables_exist(self):
        """Ensure all required tables exist in the database."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Check if main tables exist
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_schema = 'main' 
                AND table_name IN ('stock', 'fin_statement_item', 'stock_fin_statement', 
                                  'dcf_valuation', 'exchange_rate')
            """)
            result = cursor.fetchone()
            
            # Only create tables if they don't all exist
            if result[0] < 5:  # We expect 5 tables
                from pathlib import Path
                
                # Ensure we're using an absolute path
                db_path = Path(self.db_path).resolve()
                self.db_path = str(db_path)
                
                # Ensure parent directory exists
                db_dir = db_path.parent
                db_dir.mkdir(parents=True, exist_ok=True)
                
                # Import and run table creation
                from repositories.create_stocks_db import create_stocks_db
                # Create tables if they don't exist (won't drop existing data)
                create_stocks_db(self.db_path, drop_if_exists=False)
                
                logger.info(f"Database tables created/verified at {self.db_path}")
            else:
                logger.debug(f"All required tables already exist in database")
                
        except Exception as e:
            logger.warning(f"Could not ensure tables exist: {e}")
    
    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = duckdb.connect(self.db_path)
        return self._conn
    
    def close(self):
        """Close database connection and sync to S3 (optional backup)."""
        if self._conn:
            self._conn.close()
            self._conn = None
            # Sync to S3 after closing (only if enabled, EFS provides primary persistence)
            use_s3_sync = os.getenv("USE_S3_SYNC", "true").lower() == "true"
            if use_s3_sync:
                self._sync_to_s3()
    
    def _sync_to_s3(self):
        """Sync database to S3 after changes (optional backup)."""
        from utils.s3_storage import get_s3_storage
        s3 = get_s3_storage()
        if s3.s3_client:
            s3.sync_database_to_s3(self.db_path)
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection and sync."""
        self.close()
    
    def get_stock_id(self, ticker: str) -> Optional[int]:
        """Get stock_id from ticker symbol."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM stock WHERE ticker = $1", (ticker,))
        row = cursor.fetchone()
        return row[0] if row else None
    
    
    def get_or_create_item(self, item_name: str, statement_type: str) -> int:
        """Get or create financial statement item and return item_id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Try to get existing item
        cursor.execute("""
        SELECT id FROM fin_statement_item WHERE item_name = $1 AND statement_type = $2
        """, (item_name, statement_type))
        
        row = cursor.fetchone()
        
        if row:
            return row[0]
        
        # Create new item
        cursor.execute("""
        INSERT INTO fin_statement_item (item_name, statement_type)
        VALUES ($1, $2)
        RETURNING id
        """, (item_name, statement_type))
        
        item_id = cursor.fetchone()[0]
        conn.commit()
        return item_id
    
    def get_financial_statements(
        self, 
        ticker: str, 
        statement_type: str
    ) -> Optional[pd.DataFrame]:
        """
        Retrieve financial statement data from database.
        
        Args:
            ticker: Stock ticker symbol
            statement_type: 'income', 'balance', or 'cashflow'
        
        Returns:
            DataFrame with items as rows and dates as columns, or None if not found
        """
        try:
            conn = self._get_connection()
            # Get stock_id
            stock_id = self.get_stock_id(ticker)
            if stock_id is None:
                return None
            
            # Query financial statement data
            query = """
            SELECT 
                fsi.item_name,
                sfs.fiscal_date,
                sfs.value
            FROM stock_fin_statement sfs
            JOIN fin_statement_item fsi ON sfs.item_id = fsi.id
            WHERE sfs.stock_id = $1 AND fsi.statement_type = $2
            ORDER BY sfs.fiscal_date DESC, fsi.item_name
            """
            
            cursor = conn.cursor()
            cursor.execute(query, (stock_id, statement_type))
            rows = cursor.fetchall()
            
            if not rows:
                return None
            
            # Convert to DataFrame (pivot format: items as rows, dates as columns)
            data = {}
            for item_name, fiscal_date, value in rows:
                if item_name not in data:
                    data[item_name] = {}
                data[item_name][fiscal_date] = value
            
            df = pd.DataFrame(data).T
            return df
        
        except Exception:
            return None
    
    def save_financial_statements_to_db(
        self, 
        ticker: str, 
        stock_id: int,
        statement_type: str, 
        df: pd.DataFrame
    ) -> None:
        """
        Save financial statement data to database.
        
        Args:
            ticker: Stock ticker symbol
            statement_type: 'income', 'balance', or 'cashflow'
            df: DataFrame with items as rows and dates as columns
        """
        try:            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Insert financial statement items and values
            for item_name in df.index:
                # Get or create item_id
                item_id = self.get_or_create_item(item_name, statement_type)
                
                # Insert values for each fiscal date
                for fiscal_date in df.columns:
                    value = df.loc[item_name, fiscal_date]
                    
                    # Skip NaN values
                    if pd.isna(value):
                        continue
                    
                    # Convert date to string format
                    date_str = (fiscal_date.strftime('%Y-%m-%d') 
                               if hasattr(fiscal_date, 'strftime') 
                               else str(fiscal_date))
                    
                    # Insert or update financial statement value
                    cursor.execute("""
                    INSERT INTO stock_fin_statement 
                    (stock_id, item_id, fiscal_date, value)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (stock_id, item_id, fiscal_date)
                    DO UPDATE SET value = $4
                    """, (stock_id, item_id, date_str, float(value)))
            
            conn.commit()
        
        except Exception as e:
            logger.error(f"Database error: {e}")
            raise e
    
    def get_stock_info(self, ticker: str) -> Optional[dict]:
        """
        Retrieve stock info from database.
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            Dict containing stock information, or None if not found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stock WHERE ticker = $1", (ticker,))
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            # Get column names from cursor description
            columns = [desc[0] for desc in cursor.description]
            db_data = dict(zip(columns, row))
            return {
                'id': db_data.get('id'),
                'shortName': db_data.get('short_name'),
                'longName': db_data.get('long_name'),
                'sector': db_data.get('sector'),
                'industry': db_data.get('industry'),
                'country': db_data.get('country'),
                'currency': db_data.get('currency'),
                'financialCurrency': db_data.get('financial_currency'),
                'exchange': db_data.get('exchange'),
                'sharesOutstanding': db_data.get('shares_outstanding'),
                'marketCap': db_data.get('market_cap'),
                'currentPrice': db_data.get('current_price'),
                'beta': db_data.get('beta'),
                'dividendRate': db_data.get('dividend_rate'),
                'dividendYield': db_data.get('dividend_yield'),
                'payoutRatio': db_data.get('payout_ratio'),
            }
        
        except Exception:
            return None
    
    def upsert_stock(self, ticker: str, info: dict) -> int:
        """
        Upsert stock info to database (insert if not exists, update if exists).
        
        Args:
            ticker: Stock ticker symbol
            info: Dictionary containing stock information from yfinance
        
        Returns:
            int: The stock_id (existing or newly created)
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Check if stock exists
            stock_id = self.get_stock_id(ticker)
            
            if stock_id is None:
                # Insert new stock
                cursor.execute("""
                INSERT INTO stock (
                    ticker, short_name, long_name, sector, industry, 
                    country, currency, financial_currency, exchange, shares_outstanding, 
                    market_cap, current_price, beta, dividend_rate, 
                    dividend_yield, payout_ratio, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
                RETURNING id
                """, (
                    ticker,
                    info.get('shortName'),
                    info.get('longName'),
                    info.get('sector'),
                    info.get('industry'),
                    info.get('country'),
                    info.get('currency'),
                    info.get('financialCurrency'),
                    info.get('exchange'),
                    info.get('sharesOutstanding'),
                    info.get('marketCap'),
                    info.get('currentPrice'),
                    info.get('beta'),
                    info.get('dividendRate'),
                    info.get('dividendYield'),
                    info.get('payoutRatio'),
                    datetime.now().isoformat()
                ))
                stock_id = cursor.fetchone()[0]
            else:
                # Update existing stock
                cursor.execute("""
                UPDATE stock SET
                    short_name = $1,
                    long_name = $2,
                    sector = $3,
                    industry = $4,
                    country = $5,
                    currency = $6,
                    financial_currency = $7,
                    exchange = $8,
                    shares_outstanding = $9,
                    market_cap = $10,
                    current_price = $11,
                    beta = $12,
                    dividend_rate = $13,
                    dividend_yield = $14,
                    payout_ratio = $15,
                    updated_at = $16
                WHERE ticker = $17
                """, (
                    info.get('shortName'),
                    info.get('longName'),
                    info.get('sector'),
                    info.get('industry'),
                    info.get('country'),
                    info.get('currency'),
                    info.get('financialCurrency'),
                    info.get('exchange'),
                    info.get('sharesOutstanding'),
                    info.get('marketCap'),
                    info.get('currentPrice'),
                    info.get('beta'),
                    info.get('dividendRate'),
                    info.get('dividendYield'),
                    info.get('payoutRatio'),
                    datetime.now().isoformat(),
                    ticker
                ))
            
            conn.commit()
            return stock_id
        
        except Exception as e:
            logger.error(f"Database error: {e}")
            raise e
    
    def save_stock_info(self, ticker: str, info: dict) -> None:
        """
        Save stock info to database.
        
        Args:
            ticker: Stock ticker symbol
            info: Dictionary containing stock information from yfinance
        """
        self.upsert_stock(ticker, info)
    
    def save_dcf_valuation(self, stock_id: int, valuation_result: dict) -> None:
        """
        Save DCF valuation results to database.
        
        Args:
            stock_id: Stock ID from the stock table
            valuation_result: Dictionary containing valuation results from do_dcf_valuation
        """
        import json
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Convert list fields to JSON strings
            in_fcf_growth_rates_json = json.dumps(valuation_result.get('in_fcf_growth_rates'))
            projected_fcfs_json = json.dumps(valuation_result.get('projected_fcfs'))
            pv_fcfs_json = json.dumps(valuation_result.get('pv_fcfs'))
            
            # Insert valuation result
            cursor.execute("""
            INSERT INTO dcf_valuation (
                stock_id,
                in_forecast_years,
                in_terminal_growth_rate,
                in_discount_rate,
                in_fcf_growth_rates,
                in_conservative_factor,
                current_price,
                fair_value_per_share,
                conservative_fair_value,
                upside_potential_pct,
                conservative_upside_pct,
                current_fcf,
                terminal_value,
                total_enterprise_value,
                equity_value,
                shares_outstanding,
                net_debt,
                projected_fcfs,
                pv_fcfs,
                pv_terminal_value
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16, $17, $18, $19, $20
            )
            ON CONFLICT (stock_id, valuation_date, in_forecast_years, in_terminal_growth_rate, 
                        in_discount_rate, in_fcf_growth_rates, in_conservative_factor)
            DO UPDATE SET
                current_price = $7,
                fair_value_per_share = $8,
                conservative_fair_value = $9,
                upside_potential_pct = $10,
                conservative_upside_pct = $11,
                current_fcf = $12,
                terminal_value = $13,
                total_enterprise_value = $14,
                equity_value = $15,
                shares_outstanding = $16,
                net_debt = $17,
                projected_fcfs = $18,
                pv_fcfs = $19,
                pv_terminal_value = $20
            """, (
                stock_id,
                valuation_result.get('in_forecast_years'),
                valuation_result.get('in_terminal_growth_rate'),
                valuation_result.get('in_discount_rate'),
                in_fcf_growth_rates_json,
                valuation_result.get('in_conservative_factor'),
                valuation_result.get('current_price'),
                valuation_result.get('fair_value_per_share'),
                valuation_result.get('conservative_fair_value'),
                valuation_result.get('upside_potential_pct'),
                valuation_result.get('conservative_upside_pct'),
                valuation_result.get('current_fcf'),
                valuation_result.get('terminal_value'),
                valuation_result.get('total_enterprise_value'),
                valuation_result.get('equity_value'),
                valuation_result.get('shares_outstanding'),
                valuation_result.get('net_debt'),
                projected_fcfs_json,
                pv_fcfs_json,
                valuation_result.get('pv_terminal_value')
            ))
            
            conn.commit()
        
        except Exception as e:
            logger.error(f"Database error saving DCF valuation: {e}")
            raise e

    def get_exchange_rate(
        self, 
        source_currency: str, 
        target_currency: str, 
        rate_date: Optional[datetime] = None
    ) -> Optional[float]:
        """
        Get exchange rate from database for a specific date.
        
        Args:
            source_currency: Source currency code (e.g., 'EUR')
            target_currency: Target currency code (e.g., 'USD')
            rate_date: Date for the exchange rate (defaults to today)
        
        Returns:
            Exchange rate (float) or None if not found
        """
        if rate_date is None:
            rate_date = datetime.now()
        
        # Normalize date to just the date part (no time)
        if isinstance(rate_date, datetime):
            rate_date_str = rate_date.date().isoformat()
        else:
            rate_date_str = str(rate_date)
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
            SELECT rate FROM exchange_rate
            WHERE source_currency = $1 AND target_currency = $2 AND rate_date = $3
            """, (source_currency.upper(), target_currency.upper(), rate_date_str))
            
            row = cursor.fetchone()
            return float(row[0]) if row else None
        
        except Exception as e:
            logger.error(f"Database error getting exchange rate: {e}")
            return None
    
    def get_last_exchange_rate(
        self, 
        source_currency: str, 
        target_currency: str
    ) -> Optional[Tuple[float, date]]:
        """
        Get the most recent exchange rate from database for a currency pair.
        
        Args:
            source_currency: Source currency code (e.g., 'EUR')
            target_currency: Target currency code (e.g., 'USD')
        
        Returns:
            Tuple of (exchange_rate, rate_date) or None if not found
            The rate_date is the date when this rate was cached
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
            SELECT rate, rate_date FROM exchange_rate
            WHERE source_currency = $1 AND target_currency = $2
            ORDER BY rate_date DESC
            LIMIT 1
            """, (source_currency.upper(), target_currency.upper()))
            
            row = cursor.fetchone()
            if row:
                rate = float(row[0])
                rate_date = row[1]
                # Convert rate_date to date object if needed
                if isinstance(rate_date, str):
                    rate_date = datetime.fromisoformat(rate_date).date()
                elif isinstance(rate_date, datetime):
                    rate_date = rate_date.date()
                elif not isinstance(rate_date, date):
                    # If it's not already a date, try to parse it
                    try:
                        rate_date = datetime.fromisoformat(str(rate_date)).date()
                    except (ValueError, AttributeError):
                        logger.warning(f"Could not parse rate_date: {rate_date}")
                        return None
                return (rate, rate_date)
            return None
        
        except Exception as e:
            logger.error(f"Database error getting last exchange rate: {e}")
            return None
    
    def save_exchange_rate(
        self, 
        source_currency: str, 
        target_currency: str, 
        rate: float, 
        rate_date: Optional[datetime] = None
    ) -> None:
        """
        Save exchange rate to database for a specific date.
        
        Args:
            source_currency: Source currency code (e.g., 'EUR')
            target_currency: Target currency code (e.g., 'USD')
            rate: Exchange rate value
            rate_date: Date for the exchange rate (defaults to today)
        """
        if rate_date is None:
            rate_date = datetime.now()
        
        # Normalize date to just the date part (no time)
        if isinstance(rate_date, datetime):
            rate_date_str = rate_date.date().isoformat()
        else:
            rate_date_str = str(rate_date)
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO exchange_rate (source_currency, target_currency, rate_date, rate)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (source_currency, target_currency, rate_date)
            DO UPDATE SET rate = $4
            """, (source_currency.upper(), target_currency.upper(), rate_date_str, float(rate)))
            
            conn.commit()
        
        except Exception as e:
            logger.error(f"Database error saving exchange rate: {e}")
            raise e


