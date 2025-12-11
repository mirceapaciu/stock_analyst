"""Service layer for integrating stock recommendations with DCF valuations."""

import logging
import time
from typing import List, Dict, Optional
from datetime import date
from repositories.recommendations_db import RecommendationsDatabase
from recommendations.fmp_client import FMPClient
from config import RECOMMENDATIONS_DB_PATH, DB_PATH, FMP_API_KEY, FINNHUB_API_KEY

logger = logging.getLogger(__name__)


def lookup_stock(ticker: str, exchange: str = None, db_path: str = RECOMMENDATIONS_DB_PATH) -> List[Dict]:
    """Look up stock in database, or fetch from FMP API if not found.
    
    This is the service layer function that orchestrates database lookups
    and external API calls.
    
    Args:
        ticker: Stock ticker symbol to search for
        exchange: Optional exchange to filter results
        db_path: Path to recommendations database
        
    Returns:
        List of matching stock records (from DB or newly created from API)
        
    Raises:
        Exception: If FMP API fails and stock is not in database
    """
    with RecommendationsDatabase(db_path) as db:
        # First, try to find the stock in the database
        results = db.find_stock_in_db(ticker, exchange)
        
        if results:
            logger.info(f"Found {ticker} in database: {len(results)} result(s)")
            return results
        
        # Not found in database - query FMP API
        logger.info(f"Stock {ticker} not found in DB, querying FMP API...")
        
        if not FMP_API_KEY:
            raise ValueError("FMP_API_KEY not configured in environment")
        
        try:
            fmp = FMPClient()
            fmp_results = fmp.search_symbol(ticker)
            
            # Insert all results into the stock table
            inserted_stocks = []
            for result in fmp_results:
                symbol = result.get('symbol', '')
                name = result.get('name', '')
                exchange_name = result.get('exchange', 'N/A')
                
                # Skip if no symbol
                if not symbol:
                    continue
                
                # Skip non-matching symbols
                if symbol.upper() != ticker.upper():
                    continue
                
                # Get MIC for the exchange
                mic = db.get_mic_by_exchange(exchange_name)
                
                # Insert the stock (upsert will handle duplicates)
                try:
                    stock_id = db.upsert_stock(
                        isin=None,  # FMP search doesn't return ISIN
                        ticker=symbol,
                        exchange=exchange_name,
                        stock_name=name,
                        mic=mic
                    )
                    
                    # Fetch the inserted record from DB
                    inserted = db.find_stock_in_db(symbol, exchange_name)
                    if inserted:
                        inserted_stocks.extend(inserted)
                        logger.info(f"Inserted stock {symbol} from FMP API")
                        
                except Exception as e:
                    logger.error(f"Error inserting stock {symbol}: {e}")
                    continue
            
            return inserted_stocks
            
        except Exception as e:
            logger.error(f"Error fetching from FMP API for {ticker}: {e}")
            raise Exception(f"Error fetching from FMP API: {e}")

def get_recommendation_summary() -> Dict:
    """Get summary statistics for recommendations.
    
    Returns:
        Dictionary containing:
            - total_recommendations: Total number of recommended stocks
            - avg_rating: Average rating across all recommendations
            - by_rating: Count of stocks by rating bucket (Strong Buy, Buy, etc.)
    """
    with RecommendationsDatabase(RECOMMENDATIONS_DB_PATH) as db:
        recommendations = db.get_all_recommended_stocks()
    
    if not recommendations:
        return {
            'total_recommendations': 0,
            'avg_rating': None,
            'by_rating': {}
        }
    
    # Calculate statistics
    ratings = [rec['rating'] for rec in recommendations if rec.get('rating') is not None]
    avg_rating = sum(ratings) / len(ratings) if ratings else None
    
    # Count by rating buckets
    rating_buckets = {
        'Strong Buy': 0,
        'Buy': 0,
        'Hold': 0,
        'Sell': 0,
        'Strong Sell': 0
    }
    
    for rating in ratings:
        if rating >= 4.5:
            rating_buckets['Strong Buy'] += 1
        elif rating >= 3.5:
            rating_buckets['Buy'] += 1
        elif rating >= 2.5:
            rating_buckets['Hold'] += 1
        elif rating >= 1.5:
            rating_buckets['Sell'] += 1
        else:
            rating_buckets['Strong Sell'] += 1
    
    return {
        'total_recommendations': len(recommendations),
        'avg_rating': avg_rating,
        'by_rating': rating_buckets
    }


def update_market_data_for_recommended_stocks(force: bool = False, only_favorite_stocks: bool = False, db_path: str = RECOMMENDATIONS_DB_PATH) -> Dict[str, int]:
    """Update market data for recommended stocks with stale market_date.
    
    This service layer function orchestrates:
    1. Querying stocks needing refresh from database
    2. Fetching current prices from Finnhub API
    3. Updating database with new market data
    
    Args:
        force: If True, refresh all stocks. If False, only refresh stale data (>1 day old)
        only_favorite_stocks: If True, only update stocks that are in favorites
        db_path: Path to recommendations database
        
    Returns:
        Dictionary with counts: {'updated': int, 'failed': int, 'skipped': int}
        
    Raises:
        ValueError: If FINNHUB_API_KEY is not configured
    """
    if not FINNHUB_API_KEY:
        raise ValueError("FINNHUB_API_KEY not configured in environment")
    
    import finnhub
    
    with RecommendationsDatabase(db_path) as db:
        # Get stocks needing refresh
        stocks_to_update = db.get_stocks_needing_market_data_refresh(force=force)
        
        # Filter to only favorite stocks if requested
        if only_favorite_stocks:
            favorite_stock_ids = db.get_favorite_stock_ids()
            stocks_to_update = [
                stock for stock in stocks_to_update 
                if stock['stock_id'] in favorite_stock_ids
            ]
        
        if not stocks_to_update:
            return {'updated': 0, 'failed': 0, 'skipped': 0}
        
        # Initialize Finnhub client
        finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
        
        updated_count = 0
        failed_count = 0
        skipped_count = 0
        
        for stock in stocks_to_update:
            stock_id = stock['stock_id']
            ticker = stock['ticker']
            exchange = stock['exchange']
            
            # Finnhub quote works only with US stocks
            if exchange not in ['NASDAQ', 'NYSE', 'AMEX', 'N/A']:
                logger.info(f"Skipping {ticker} ({exchange}) - non-US exchange")
                skipped_count += 1
                continue
            
            try:
                # Get quote from Finnhub with retry logic
                quote_data = None
                for attempt in range(2):
                    try:
                        quote_data = finnhub_client.quote(ticker)
                        break
                    except Exception as api_error:
                        if attempt == 0:
                            logger.warning(f"Finnhub API call failed for {ticker}, retrying in 60 seconds...")
                            time.sleep(60)
                        else:
                            raise api_error
                
                if quote_data is None:
                    logger.warning(f"Failed to get quote data for {ticker}")
                    failed_count += 1
                    continue
                
                # Extract current price ('c' key)
                current_price = quote_data.get('c')
                
                if current_price is None or current_price == 0:
                    logger.warning(f"No valid price data for {ticker}")
                    failed_count += 1
                    continue
                
                # Update the database via repository method
                today = date.today().strftime('%Y-%m-%d')
                db.update_stock_market_data(stock_id, current_price, today)
                
                updated_count += 1
                logger.info(f"Updated {ticker}: ${current_price}")
                
            except Exception as e:
                logger.error(f"Error updating {ticker}: {e}")
                failed_count += 1
                continue
        
        return {
            'updated': updated_count,
            'failed': failed_count,
            'skipped': skipped_count
        }
