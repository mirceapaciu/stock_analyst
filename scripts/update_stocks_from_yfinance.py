"""
Update all existing stock entries in the database with latest data from yfinance.
"""
import sys
from pathlib import Path
import time

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb
from config import DB_PATH
from services.financial import get_or_create_stock_info


def get_all_tickers(db_path: str = DB_PATH) -> list[str]:
    """Get all ticker symbols from the stock table."""
    conn = duckdb.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT DISTINCT ticker FROM stock ORDER BY ticker")
    rows = cursor.fetchall()
    tickers = [row[0] for row in rows]
    
    conn.close()
    return tickers


def update_all_stocks(db_path: str = DB_PATH, delay: float = 0.5) -> None:
    """
    Update all stock entries in the database with latest data from yfinance.
    
    Args:
        db_path: Path to the database file
        delay: Delay in seconds between API calls to avoid rate limiting
    """
    print(f"Fetching all tickers from database: {db_path}")
    tickers = get_all_tickers(db_path)
    
    if not tickers:
        print("No stocks found in database.")
        return
    
    total = len(tickers)
    print(f"\nFound {total} stock(s) to update.")
    print("=" * 80)
    
    successful = 0
    failed = 0
    failed_tickers = []
    
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{total}] Updating {ticker}...", end=" ", flush=True)
        
        try:
            stock_info = get_or_create_stock_info(ticker,force_fetch=True)
            print(f"✓ Success (stock_id: {stock_info.get('id')})")
            successful += 1
        except Exception as e:
            print(f"✗ Failed: {str(e)}")
            failed += 1
            failed_tickers.append((ticker, str(e)))
        
        # Add delay to avoid rate limiting (except for last item)
        if i < total:
            time.sleep(delay)
    
    print("\n" + "=" * 80)
    print(f"Update complete!")
    print(f"  Successful: {successful}/{total}")
    print(f"  Failed: {failed}/{total}")
    
    if failed_tickers:
        print("\nFailed tickers:")
        for ticker, error in failed_tickers:
            print(f"  - {ticker}: {error}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Update all stock entries with latest data from yfinance"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between API calls (default: 0.5)"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=DB_PATH,
        help=f"Path to database file (default: {DB_PATH})"
    )
    
    args = parser.parse_args()
    
    update_all_stocks(db_path=args.db_path, delay=args.delay)

