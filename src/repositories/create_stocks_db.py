import duckdb
import sys
import os
import logging

# Add parent directory to path to import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import DB_PATH

logger = logging.getLogger(__name__)


def create_stock_table(conn: duckdb.DuckDBPyConnection, drop_if_exists: bool = False):
    """Create stock table for basic stock information."""
    cursor = conn.cursor()
    
    if drop_if_exists:
        cursor.execute("DROP TABLE IF EXISTS stock CASCADE")
        cursor.execute("DROP SEQUENCE IF EXISTS stock_id_seq")
    
    cursor.execute("""
    CREATE SEQUENCE IF NOT EXISTS stock_id_seq START 1
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock (
        id INTEGER PRIMARY KEY DEFAULT nextval('stock_id_seq'),
        ticker TEXT,
        short_name TEXT,
        long_name TEXT,
        sector TEXT,
        industry TEXT,
        country TEXT,
        currency TEXT,
        financial_currency TEXT,
        exchange TEXT,
        shares_outstanding BIGINT,
        market_cap BIGINT,
        current_price DOUBLE,
        beta DOUBLE,
        dividend_rate DOUBLE,
        dividend_yield DOUBLE,
        payout_ratio DOUBLE,
        updated_at TEXT
    )
    """)
    
    # Add financial_currency column if it doesn't exist (for existing databases)
    try:
        cursor.execute("ALTER TABLE stock ADD COLUMN financial_currency TEXT")
    except Exception:
        # Column already exists, ignore
        pass
    
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_ticker ON stock(ticker)")
    conn.commit()


def create_fin_statement_item_table(conn: duckdb.DuckDBPyConnection, drop_if_exists: bool = False):
    """Create financial statement item definitions table."""
    cursor = conn.cursor()
    
    if drop_if_exists:
        cursor.execute("DROP TABLE IF EXISTS fin_statement_item CASCADE")
        cursor.execute("DROP SEQUENCE IF EXISTS fin_statement_item_id_seq")
    
    cursor.execute("""
    CREATE SEQUENCE IF NOT EXISTS fin_statement_item_id_seq START 1
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fin_statement_item (
        id INTEGER PRIMARY KEY DEFAULT nextval('fin_statement_item_id_seq'),
        item_name TEXT NOT NULL,
        statement_type TEXT CHECK(statement_type IN ('income', 'balance', 'cashflow')) NOT NULL,
        description TEXT,
        UNIQUE(item_name, statement_type)
    )
    """)
    
    conn.commit()


def create_stock_fin_statement_table(conn: duckdb.DuckDBPyConnection, drop_if_exists: bool = False):
    """Create financial statement values table."""
    cursor = conn.cursor()
    
    if drop_if_exists:
        cursor.execute("DROP TABLE IF EXISTS stock_fin_statement CASCADE")
        cursor.execute("DROP SEQUENCE IF EXISTS stock_fin_statement_id_seq")
    
    cursor.execute("""
    CREATE SEQUENCE IF NOT EXISTS stock_fin_statement_id_seq START 1
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_fin_statement (
        id INTEGER PRIMARY KEY DEFAULT nextval('stock_fin_statement_id_seq'),
        stock_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        fiscal_date TEXT NOT NULL,
        value DOUBLE,
        FOREIGN KEY (stock_id) REFERENCES stock(id),
        FOREIGN KEY (item_id) REFERENCES fin_statement_item(id),
        UNIQUE(stock_id, item_id, fiscal_date)
    )
    """)
    
    conn.commit()


def create_key_ratio_table(conn: duckdb.DuckDBPyConnection, drop_if_exists: bool = False):
    """Create key ratios table."""
    cursor = conn.cursor()
    
    if drop_if_exists:
        cursor.execute("DROP TABLE IF EXISTS key_ratio CASCADE")
        cursor.execute("DROP SEQUENCE IF EXISTS key_ratio_id_seq")
    
    cursor.execute("""
    CREATE SEQUENCE IF NOT EXISTS key_ratio_id_seq START 1
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS key_ratio (
        id INTEGER PRIMARY KEY DEFAULT nextval('key_ratio_id_seq'),
        stock_id INTEGER,
        fiscal_date TEXT,
        pe_ratio DOUBLE,
        pb_ratio DOUBLE,
        roe DOUBLE,
        roa DOUBLE,
        profit_margin DOUBLE,
        operating_margin DOUBLE,
        FOREIGN KEY (stock_id) REFERENCES stock(id)
    )
    """)
    
    conn.commit()


def create_price_history_table(conn: duckdb.DuckDBPyConnection, drop_if_exists: bool = False):
    """Create price history table."""
    cursor = conn.cursor()
    
    if drop_if_exists:
        cursor.execute("DROP TABLE IF EXISTS price_history CASCADE")
        cursor.execute("DROP SEQUENCE IF EXISTS price_history_id_seq")
    
    cursor.execute("""
    CREATE SEQUENCE IF NOT EXISTS price_history_id_seq START 1
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY DEFAULT nextval('price_history_id_seq'),
        stock_id INTEGER,
        date TEXT,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,
        volume BIGINT,
        FOREIGN KEY (stock_id) REFERENCES stock(id)
    )
    """)
    
    conn.commit()


def create_dcf_valuation_table(conn: duckdb.DuckDBPyConnection, drop_if_exists: bool = False):
    """Create DCF valuation results table."""
    cursor = conn.cursor()
    
    if drop_if_exists:
        cursor.execute("DROP TABLE IF EXISTS dcf_valuation CASCADE")
        cursor.execute("DROP SEQUENCE IF EXISTS dcf_valuation_id_seq")
    
    cursor.execute("""
    CREATE SEQUENCE IF NOT EXISTS dcf_valuation_id_seq START 1
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dcf_valuation (
        id INTEGER PRIMARY KEY DEFAULT nextval('dcf_valuation_id_seq'),
        stock_id INTEGER NOT NULL,
        valuation_date DATE DEFAULT CURRENT_DATE,
        in_forecast_years INTEGER NOT NULL,
        in_terminal_growth_rate DOUBLE NOT NULL,
        in_discount_rate DOUBLE NOT NULL,
        in_fcf_growth_rates TEXT NOT NULL,
        in_conservative_factor DOUBLE,
        current_price DOUBLE,
        fair_value_per_share DOUBLE,
        conservative_fair_value DOUBLE,
        upside_potential_pct DOUBLE,
        conservative_upside_pct DOUBLE,
        current_fcf DOUBLE,
        terminal_value DOUBLE,
        total_enterprise_value DOUBLE,
        equity_value DOUBLE,
        shares_outstanding BIGINT,
        net_debt DOUBLE,
        projected_fcfs TEXT,
        pv_fcfs TEXT,
        pv_terminal_value DOUBLE,
        FOREIGN KEY (stock_id) REFERENCES stock(id),
        UNIQUE(stock_id, valuation_date, in_forecast_years, in_terminal_growth_rate, in_discount_rate, in_fcf_growth_rates, in_conservative_factor)
    )
    """)
    
    conn.commit()


def create_exchange_rate_table(conn: duckdb.DuckDBPyConnection, drop_if_exists: bool = False):
    """Create exchange rate table for caching currency conversion rates."""
    cursor = conn.cursor()
    
    if drop_if_exists:
        cursor.execute("DROP TABLE IF EXISTS exchange_rate CASCADE")
        cursor.execute("DROP SEQUENCE IF EXISTS exchange_rate_id_seq")
    
    cursor.execute("""
    CREATE SEQUENCE IF NOT EXISTS exchange_rate_id_seq START 1
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS exchange_rate (
        id INTEGER PRIMARY KEY DEFAULT nextval('exchange_rate_id_seq'),
        source_currency TEXT NOT NULL,
        target_currency TEXT NOT NULL,
        rate_date DATE NOT NULL,
        rate DOUBLE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_currency, target_currency, rate_date)
    )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exchange_rate_lookup ON exchange_rate(source_currency, target_currency, rate_date)")
    conn.commit()


def create_stocks_db(db_path=DB_PATH, drop_if_exists: bool = False):
    """
    Creates all DuckDB tables for stock fundamental data.
    
    Args:
        db_path: Path to the database file
        drop_if_exists: If True, drop existing tables before creating new ones
    """
    conn = duckdb.connect(db_path)
    
    try:
        # Create tables in order (parent tables first)
        create_stock_table(conn, drop_if_exists)
        create_fin_statement_item_table(conn, drop_if_exists)
        create_stock_fin_statement_table(conn, drop_if_exists)
        create_key_ratio_table(conn, drop_if_exists)
        create_price_history_table(conn, drop_if_exists)
        create_dcf_valuation_table(conn, drop_if_exists)
        create_exchange_rate_table(conn, drop_if_exists)
        
        logger.info("All tables created successfully!")
    finally:
        conn.close()


if __name__ == "__main__":
    # Create the database when running this file directly
    create_stocks_db()

