"""Service layer for integrating stock recommendations with DCF valuations."""

import logging
import time
from typing import List, Dict, Optional, Iterable, Set
from datetime import date
import re
from repositories.recommendations_db import RecommendationsDatabase
from recommendations.fmp_client import FMPClient
from config import (
    RECOMMENDATIONS_DB_PATH,
    DB_PATH,
    FMP_API_KEY,
    FINNHUB_API_KEY,
    MARKET_PRICE_REFRESH_PROGRESS_BLOCK_SIZE,
)

logger = logging.getLogger(__name__)


def _normalize_ticker_set(tickers: Optional[Iterable[str]]) -> Set[str]:
    """Normalize tickers to uppercase, trimmed symbol set."""
    if tickers is None:
        return set()

    normalized = set()
    for ticker in tickers:
        cleaned = str(ticker or "").strip().upper()
        if cleaned:
            normalized.add(cleaned)
    return normalized


def collect_workflow_recommendation_tickers(workflow_result: Optional[Dict]) -> Set[str]:
    """Extract ticker symbols from workflow output pages.

    The workflow stores extracted recommendations in ``deduplicated_pages``.
    If that collection is empty, this falls back to ``scraped_pages``.
    """
    if not isinstance(workflow_result, dict):
        return set()

    collected: Set[str] = set()

    pages = workflow_result.get("deduplicated_pages") or []
    for page in pages:
        recommendations = (page or {}).get("stock_recommendations") or []
        for recommendation in recommendations:
            ticker = str((recommendation or {}).get("ticker") or "").strip().upper()
            if ticker:
                collected.add(ticker)

    if collected:
        return collected

    fallback_pages = workflow_result.get("scraped_pages") or []
    for page in fallback_pages:
        recommendations = (page or {}).get("stock_recommendations") or []
        for recommendation in recommendations:
            ticker = str((recommendation or {}).get("ticker") or "").strip().upper()
            if ticker:
                collected.add(ticker)

    return collected


def _symbol_base(symbol: str) -> str:
    """Return normalized base ticker, stripping common exchange suffixes."""
    if not symbol:
        return ""
    cleaned = symbol.strip().upper()
    cleaned = re.split(r'[\.:\-]', cleaned, maxsplit=1)[0]
    return cleaned


def _name_similarity(left: str, right: str) -> float:
    """Compute fuzzy similarity score between two company names."""
    if not left or not right:
        return 0.0
    from difflib import SequenceMatcher
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _select_best_match(results: List[Dict], stock_name: str = None) -> Optional[Dict]:
    """Select best matching stock from multiple results.
    
    Args:
        results: List of stock records
        stock_name: Optional stock name for fuzzy matching
        
    Returns:
        Best matching stock record, or None if results is empty
    """
    if not results:
        return None
    
    if len(results) == 1:
        return results[0]
    
    # Multiple matches - use fuzzy matching if stock_name provided
    if stock_name and stock_name != 'N/A':
        from difflib import SequenceMatcher
        
        best_match = results[0]
        best_similarity = 0.0
        
        for result in results:
            result_name = result.get('stock_name', '')
            similarity = SequenceMatcher(None, 
                                        stock_name.lower(), 
                                        result_name.lower()).ratio()
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = result
        
        logger.info(f"Selected best match: {best_match.get('stock_name')} (similarity: {best_similarity:.2f})")
        return best_match
    
    # No stock_name provided - return first match
    logger.info(f"Multiple matches found, returning first: {results[0].get('stock_name')}")
    return results[0]


def lookup_stock(ticker: str, exchange: str = None, stock_name: str = None, db_path: str = RECOMMENDATIONS_DB_PATH) -> Optional[Dict]:
    """Look up stock in database, or fetch from FMP API if not found.
    
    This is the service layer function that orchestrates database lookups
    and external API calls.
    
    When multiple matches are found, selects the best match based on:
    1. If stock_name provided: highest similarity to stock_name using fuzzy matching
    2. Otherwise: returns first match
    
    Args:
        ticker: Stock ticker symbol to search for
        exchange: Optional exchange to filter results
        stock_name: Optional stock name for best-match selection when multiple results exist
        db_path: Path to recommendations database
        
    Returns:
        Single matching stock record (from DB or newly created from API), or None if not found
        
    Raises:
        Exception: If FMP API fails and stock is not in database
    """
    # Normalize ticker and exchange
    ticker = ticker.strip().upper() if ticker else ticker
    exchange = exchange.strip() if exchange else exchange
    
    with RecommendationsDatabase(db_path) as db:
        # First, try to find the stock in the database
        results = db.find_stock_in_db(ticker, exchange)
        
        if results:
            logger.info(f"Found {ticker} in database: {len(results)} result(s)")
            best_match = _select_best_match(results, stock_name)

            # For ambiguous symbols, do not trust exchange-filtered DB hit if the stock name
            # provided by extraction clearly conflicts with the matched company name.
            if exchange and stock_name and stock_name != 'N/A':
                similarity = _name_similarity(stock_name, best_match.get('stock_name', ''))
                if similarity < 0.45:
                    logger.info(
                        f"DB match name mismatch for {ticker} on {exchange}: "
                        f"input='{stock_name}' db='{best_match.get('stock_name', '')}' similarity={similarity:.2f}. "
                        "Continuing with fallback resolution."
                    )
                else:
                    return best_match
            else:
                return best_match

        # If exchange was specified and nothing found, retry DB lookup without exchange
        # to handle cases where extracted exchange is incorrect.
        if exchange:
            fallback_results = db.find_stock_in_db(ticker)
            if fallback_results:
                logger.info(
                    f"Found {ticker} in database with exchange mismatch (requested={exchange}). "
                    f"Using best ticker-only match from {len(fallback_results)} result(s)."
                )
                fallback_best_match = _select_best_match(fallback_results, stock_name)
                if stock_name and stock_name != 'N/A':
                    similarity = _name_similarity(stock_name, fallback_best_match.get('stock_name', ''))
                    if similarity < 0.45:
                        logger.info(
                            f"Ticker-only DB match name mismatch for {ticker}: "
                            f"input='{stock_name}' db='{fallback_best_match.get('stock_name', '')}' similarity={similarity:.2f}. "
                            "Continuing with FMP fallback resolution."
                        )
                    else:
                        return fallback_best_match
                else:
                    logger.info(
                        f"Ignoring ticker-only DB fallback for {ticker} because no stock_name hint was provided "
                        f"(requested exchange={exchange})."
                    )
        
        # Not found in database - query FMP API
        logger.info(f"Stock {ticker} not found in DB, querying FMP API...")
        
        if not FMP_API_KEY:
            raise ValueError("FMP_API_KEY not configured in environment")
        
        try:
            fmp = FMPClient()
            fmp_results = fmp.search_symbol(ticker)
            
            # Insert all results into the stock table
            inserted_stocks = []
            exact_symbol_candidates = []
            base_symbol_candidates = []
            ticker_base = _symbol_base(ticker)
            for result in fmp_results:
                symbol = result.get('symbol', '')
                name = result.get('name', '')
                exchange_name = result.get('exchange', 'N/A')
                
                # Skip if no symbol
                if not symbol:
                    continue
                
                symbol_upper = symbol.upper()
                symbol_base = _symbol_base(symbol_upper)

                # Keep exact symbol matches and exchange-suffixed variants with same base.
                if symbol_upper != ticker.upper() and symbol_base != ticker_base:
                    continue

                if symbol_upper == ticker.upper():
                    exact_symbol_candidates.append(result)
                base_symbol_candidates.append(result)
                
                # Skip non-matching exchanges if exchange was specified
                # Use flexible matching: check if requested exchange is in FMP exchange name
                if exchange:
                    exchange_upper = exchange.upper()
                    exchange_name_upper = exchange_name.upper()
                    # Accept if exact match or if requested exchange is contained in FMP exchange
                    if exchange_upper != exchange_name_upper and exchange_upper not in exchange_name_upper:
                        logger.debug(f"Skipping {symbol} on {exchange_name} (requested {exchange})")
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

            if inserted_stocks:
                selected = _select_best_match(inserted_stocks, stock_name)
                if stock_name and stock_name != 'N/A':
                    similarity = _name_similarity(stock_name, selected.get('stock_name', ''))
                    if similarity < 0.45:
                        logger.info(
                            f"Exchange-filtered FMP match name mismatch for {ticker}: "
                            f"input='{stock_name}' selected='{selected.get('stock_name', '')}' similarity={similarity:.2f}. "
                            "Continuing with fallback resolution."
                        )
                    else:
                        return selected
                else:
                    return selected

            # If we found ticker-base variants (e.g. BA and BA.L) but exchange filtered them out,
            # retry without exchange filter using best stock_name similarity.
            if exchange and base_symbol_candidates and stock_name and stock_name != 'N/A':
                logger.info(
                    f"Found {ticker} base-symbol candidates in FMP with exchange conflict "
                    f"(requested={exchange}). Retrying without exchange filter."
                )

                from difflib import SequenceMatcher

                fallback_candidate = max(
                    base_symbol_candidates,
                    key=lambda candidate: SequenceMatcher(
                        None,
                        stock_name.lower(),
                        (candidate.get('name') or '').lower()
                    ).ratio()
                )

                fallback_symbol = fallback_candidate.get('symbol', '')
                fallback_name = fallback_candidate.get('name', '')
                fallback_exchange = fallback_candidate.get('exchange', 'N/A')
                fallback_mic = db.get_mic_by_exchange(fallback_exchange)

                try:
                    db.upsert_stock(
                        isin=None,
                        ticker=fallback_symbol,
                        exchange=fallback_exchange,
                        stock_name=fallback_name,
                        mic=fallback_mic
                    )
                except Exception as e:
                    logger.error(f"Error inserting fallback base-symbol stock {fallback_symbol}: {e}")
                    return None

                fallback_inserted = db.find_stock_in_db(fallback_symbol, fallback_exchange)
                if fallback_inserted:
                    selected = _select_best_match(fallback_inserted, stock_name)
                    similarity = _name_similarity(stock_name, selected.get('stock_name', ''))
                    if similarity < 0.45:
                        logger.info(
                            f"Base-symbol fallback name mismatch for {ticker}: "
                            f"input='{stock_name}' selected='{selected.get('stock_name', '')}' similarity={similarity:.2f}. "
                            "Continuing with name-based fallback."
                        )
                    else:
                        return selected

            # Name-based fallback for ambiguous symbols (e.g. BA -> Boeing vs BAE Systems).
            if stock_name and stock_name != 'N/A':
                name_queries = [stock_name.strip()]
                normalized_tokens = [
                    token for token in re.split(r'[^A-Za-z0-9]+', stock_name.strip())
                    if token
                ]

                uppercase_tokens = [token for token in normalized_tokens if token.isupper() and len(token) >= 3]
                if uppercase_tokens:
                    name_queries.extend(uppercase_tokens)

                if normalized_tokens:
                    name_queries.append(normalized_tokens[0])

                seen_queries = set()
                deduped_queries = []
                for query in name_queries:
                    query_key = query.lower()
                    if query_key and query_key not in seen_queries:
                        seen_queries.add(query_key)
                        deduped_queries.append(query)

                name_results = []
                for query in deduped_queries:
                    try:
                        query_results = fmp.search_name(query)
                        if query_results:
                            name_results.extend(query_results)
                    except Exception as name_search_error:
                        logger.warning(f"FMP name search failed for query '{query}': {name_search_error}")
                        continue

                name_candidates = []
                for candidate in name_results:
                    candidate_symbol = (candidate.get('symbol') or '').upper()
                    if not candidate_symbol:
                        continue
                    candidate_base = _symbol_base(candidate_symbol)
                    if candidate_base == ticker_base or ticker_base in candidate_base:
                        name_candidates.append(candidate)

                if name_candidates:
                    from difflib import SequenceMatcher

                    if exchange:
                        exchange_upper = exchange.upper()
                        exchange_filtered = []
                        for candidate in name_candidates:
                            candidate_exchange = (candidate.get('exchange') or '').upper()
                            candidate_exchange_full = (candidate.get('exchangeFullName') or '').upper()
                            if (
                                exchange_upper == candidate_exchange
                                or exchange_upper in candidate_exchange
                                or exchange_upper in candidate_exchange_full
                            ):
                                exchange_filtered.append(candidate)
                        if exchange_filtered:
                            name_candidates = exchange_filtered

                    best_name_candidate = max(
                        name_candidates,
                        key=lambda candidate: SequenceMatcher(
                            None,
                            stock_name.lower(),
                            (candidate.get('name') or '').lower()
                        ).ratio()
                    )

                    name_symbol = best_name_candidate.get('symbol', '')
                    name_exchange = best_name_candidate.get('exchange', 'N/A')
                    name_company = best_name_candidate.get('name', '')
                    name_mic = db.get_mic_by_exchange(name_exchange)

                    try:
                        db.upsert_stock(
                            isin=None,
                            ticker=name_symbol,
                            exchange=name_exchange,
                            stock_name=name_company,
                            mic=name_mic
                        )
                    except Exception as e:
                        logger.error(f"Error inserting name-fallback stock {name_symbol}: {e}")
                        return None

                    name_inserted = db.find_stock_in_db(name_symbol, name_exchange)
                    if name_inserted:
                        return _select_best_match(name_inserted, stock_name)

            # Fallback: symbol exists in FMP but exchange did not match requested one.
            # Retry without exchange filtering and choose best approximate name match.
            if exchange and exact_symbol_candidates and stock_name and stock_name != 'N/A':
                logger.info(
                    f"Found {ticker} in FMP with exchange conflict (requested={exchange}). "
                    "Retrying without exchange filter."
                )

                from difflib import SequenceMatcher

                fallback_candidate = max(
                    exact_symbol_candidates,
                    key=lambda candidate: SequenceMatcher(
                        None,
                        stock_name.lower(),
                        (candidate.get('name') or '').lower()
                    ).ratio()
                )

                fallback_symbol = fallback_candidate.get('symbol', '')
                fallback_name = fallback_candidate.get('name', '')
                fallback_exchange = fallback_candidate.get('exchange', 'N/A')
                fallback_mic = db.get_mic_by_exchange(fallback_exchange)

                try:
                    db.upsert_stock(
                        isin=None,
                        ticker=fallback_symbol,
                        exchange=fallback_exchange,
                        stock_name=fallback_name,
                        mic=fallback_mic
                    )
                except Exception as e:
                    logger.error(f"Error inserting fallback stock {fallback_symbol}: {e}")
                    return None

                fallback_inserted = db.find_stock_in_db(fallback_symbol, fallback_exchange)
                if fallback_inserted:
                    selected = _select_best_match(fallback_inserted, stock_name)
                    similarity = _name_similarity(stock_name, selected.get('stock_name', ''))
                    if similarity < 0.45:
                        logger.info(
                            f"Exact-symbol fallback name mismatch for {ticker}: "
                            f"input='{stock_name}' selected='{selected.get('stock_name', '')}' similarity={similarity:.2f}. "
                            "Continuing with name-based fallback."
                        )
                    else:
                        return selected
            
            return None
            
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


def update_market_data_for_recommended_stocks(
    force: bool = False,
    only_favorite_stocks: bool = False,
    workflow_tickers: Optional[Iterable[str]] = None,
    db_path: str = RECOMMENDATIONS_DB_PATH,
    process_name: Optional[str] = None,
    progress_update_block_size: int = MARKET_PRICE_REFRESH_PROGRESS_BLOCK_SIZE,
) -> Dict[str, int]:
    """Update market data for recommended stocks with stale market_date.
    
    This service layer function orchestrates:
    1. Querying stocks needing refresh from database
    2. Fetching current prices from Finnhub API
    3. Updating database with new market data
    
    Args:
        force: If True, refresh all stocks. If False, only refresh stale data (>1 day old)
        only_favorite_stocks: If True, only update stocks that are in favorites
        workflow_tickers: Optional iterable of tickers to limit updates to workflow stocks only
        db_path: Path to recommendations database
        process_name: Optional process name to track status in the process table
        progress_update_block_size: Update process progress every N processed tickers
        
    Returns:
        Dictionary with counts: {'updated': int, 'failed': int, 'skipped': int}
        
    Raises:
        ValueError: If FINNHUB_API_KEY is not configured
    """
    if not FINNHUB_API_KEY:
        raise ValueError("FINNHUB_API_KEY not configured in environment")
    
    import finnhub
    
    with RecommendationsDatabase(db_path) as db:
        if process_name:
            db.start_process(process_name)

        try:
            # Get stocks needing refresh
            stocks_to_update = db.get_stocks_needing_market_data_refresh(force=force)

            # Filter to only favorite stocks if requested
            if only_favorite_stocks:
                favorite_stock_ids = db.get_favorite_stock_ids()
                stocks_to_update = [
                    stock for stock in stocks_to_update
                    if stock['stock_id'] in favorite_stock_ids
                ]

            # Optionally scope updates to tickers produced in the current workflow run.
            if workflow_tickers is not None:
                workflow_ticker_set = _normalize_ticker_set(workflow_tickers)
                stocks_to_update = [
                    stock for stock in stocks_to_update
                    if str(stock.get('ticker') or '').strip().upper() in workflow_ticker_set
                ]

            if not stocks_to_update:
                result = {'updated': 0, 'failed': 0, 'skipped': 0}
                if process_name:
                    db.end_process(
                        process_name,
                        'COMPLETED',
                        "Market refresh completed: updated=0, failed=0, skipped=0",
                    )
                return result

            # Initialize Finnhub client
            finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
            total_stocks = len(stocks_to_update)
            safe_progress_block_size = max(1, int(progress_update_block_size or 1))

            updated_count = 0
            failed_count = 0
            skipped_count = 0

            for index, stock in enumerate(stocks_to_update, start=1):
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
                finally:
                    if process_name and (
                        index % safe_progress_block_size == 0 or index == total_stocks
                    ):
                        progress_pct = int((index / total_stocks) * 100)
                        db.update_process_progress(process_name, progress_pct)

            result = {
                'updated': updated_count,
                'failed': failed_count,
                'skipped': skipped_count
            }
            if process_name:
                db.end_process(
                    process_name,
                    'COMPLETED',
                    (
                        f"Market refresh completed: updated={updated_count}, "
                        f"failed={failed_count}, skipped={skipped_count}"
                    ),
                )
            return result
        except Exception:
            if process_name:
                try:
                    db.end_process(process_name, 'FAILED', 'Market refresh failed')
                except Exception as process_error:
                    logger.warning(f"Failed to mark process '{process_name}' as FAILED: {process_error}")
            raise
