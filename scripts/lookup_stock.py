from pathlib import Path
import sys

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from repositories.recommendations_db import RecommendationsDatabase
from services.financial import get_or_create_stock_info

db = RecommendationsDatabase()

recommended_stocks = db.get_all_recommended_stocks()

for stock in recommended_stocks:
    ticker = stock.get('ticker')
    stock_id = stock.get('stock_id')

    if ticker is None or stock_id is None:
        print(f"Skipping invalid stock entry: {stock}")
        continue

    stock_info = get_or_create_stock_info(ticker)

    print(f"Ticker: {ticker}")
    if stock_info is None:
        print("  No stock info found!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
        market_cap = stock_info.get('marketCap')
        if market_cap is None:
            print("  No market cap found!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            db.delete_recommended_stock(stock_id)
            db.delete_stock_recommendation(stock_id)
            print("  Deleted recommendation.")
        else:
            if market_cap < 1_000_000_000:
                print(f"  Market Cap {market_cap} is less than 1B!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                db.delete_recommended_stock(stock_id)
                db.delete_stock_recommendation(stock_id)
                print(f"  Deleted recommendations for stock_id = {stock_id}.")
