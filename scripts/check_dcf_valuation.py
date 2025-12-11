"""
Check DCF valuation records in the database.
"""
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb
from config import DB_PATH

def check_dcf_records():
    """Check DCF valuation records."""
    conn = duckdb.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get count
    cursor.execute('SELECT COUNT(*) FROM dcf_valuation')
    count = cursor.fetchone()[0]
    print(f"\nTotal DCF valuation records: {count}")
    
    # Get recent records
    cursor.execute('''
        SELECT 
            s.ticker,
            d.valuation_date,
            d.in_forecast_years,
            d.in_terminal_growth_rate,
            d.in_discount_rate,
            d.fair_value_per_share,
            d.conservative_fair_value,
            d.current_price
        FROM dcf_valuation d
        JOIN stock s ON d.stock_id = s.id
        ORDER BY d.valuation_date DESC, d.id DESC
        LIMIT 5
    ''')
    
    rows = cursor.fetchall()
    
    if rows:
        print("\nRecent DCF Valuation Records:")
        print("-" * 120)
        print(f"{'Ticker':<10} {'Date':<12} {'Years':<7} {'Term.Gr%':<10} {'Disc.%':<8} {'Fair Val':<12} {'Conserv.':<12} {'Curr.Price':<12}")
        print("-" * 120)
        
        for row in rows:
            ticker, entry_date, years, term_gr, disc_rate, fair_val, conserv, curr_price = row
            print(f"{ticker:<10} {entry_date!s:<12} {years:<7} {term_gr*100:<10.2f} {disc_rate*100:<8.2f} ${fair_val:<11.2f} ${conserv:<11.2f} ${curr_price:<11.2f}")
    else:
        print("\nNo records found.")
    
    conn.close()

if __name__ == "__main__":
    check_dcf_records()
