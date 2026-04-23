"""LangGraph workflow for searching and analyzing undervalued stocks."""

from typing import List, Dict, TypedDict, Optional
from datetime import datetime, date, timedelta
import json
import logging
import asyncio
from urllib.parse import urlparse
from dataclasses import dataclass

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from googleapiclient.discovery import build
import requests
from bs4 import BeautifulSoup

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from config import (
    MAX_RESULT_AGE_DAYS,
    GOOGLE_API_KEY,
    GOOGLE_CSE_ID,
    MAX_SEARCH_RESULTS,
    SEARCH_QUERIES,
    TRACKED_BATCH_SEARCH_QUERIES,
    TRACKED_BATCH_SITES,
    TRACKED_RESULT_AGE_DAYS,
    MAX_WORKERS,
    MIN_MARKET_CAP,
    MIN_RATING_NEW_STOCK,
    REPUTABLE_SITES,
    BROWSER_FETCH_TIMEOUT_SECONDS,
    build_tracked_query,
)
from services.recommendations import infer_ticker_from_stock_name
from repositories.recommendations_db import RecommendationsDatabase
from recommendations.prompts import (
    get_extract_stocks_prompt,
    get_extract_stocks_prompt_tracked,
    get_analyze_search_result_prompt,
    get_analyze_search_result_with_date_prompt,
)

logger = logging.getLogger(__name__)

LOW_QUALITY_RECOMMENDATION_THRESHOLD = 40
TERMINAL_HTTP_STATUS_CODES = {401, 403, 404, 410}
CHALLENGE_PAGE_REASON = 'challenge_page'

DISCOVERY_INTENT_PHRASES = (
    "undervalued stocks",
    "best value stocks",
    "stocks to buy",
)
DISCOVERY_QUERY_OR_TERMS = '"buy rating" "top picks" "analyst picks" "price target" "stock recommendations"'
DISCOVERY_QUERY_EXCLUDE_TERMS = 'video podcast transcript "company profile"'
DISCOVERY_MIN_INTENT_SCORE = 2

DISCOVERY_POSITIVE_TERMS = (
    "undervalued stocks",
    "best value stocks",
    "stocks to buy",
    "buy rating",
    "top picks",
    "analyst picks",
    "price target",
    "recommendation",
    "recommended stocks",
    "value stock",
)

DISCOVERY_NEGATIVE_TERMS = (
    "company profile",
    "market talk",
    "video",
    "podcast",
    "transcript",
    "live blog",
    "stock quote",
)

DISCOVERY_DOMAIN_PATH_DENYLIST = {
    "reuters.com": (
        "/company/",
        "/video/",
        "/graphics/",
        "/pictures/",
    ),
}


@dataclass
class TerminalFetchFailure(Exception):
    """Raised when a URL is blocked by a cached rule or terminal HTTP/challenge failure."""

    url: str
    reason: str
    status_code: Optional[int] = None
    matched_pattern: Optional[str] = None
    cached: bool = False
    failure_type: str = 'terminal_http'

    def metrics(self) -> Dict[str, int]:
        metrics = {'blocked_cached_skips': 1} if self.cached else {'blocked_terminal_failures': 1}
        if self.failure_type == CHALLENGE_PAGE_REASON:
            metrics['blocked_challenge_pages'] = 1
        return metrics

# Pydantic models for LLM response validation
class RecommendationQuality(BaseModel):
    """Quality assessment of a stock recommendation."""
    description_word_count: int = Field(default=0, description="Number of words in stock description")
    has_explicit_rating: bool = Field(default=False, description="Whether text contains explicit rating (Buy/Sell/Hold or stars)")
    reasoning_detail_level: int = Field(default=0, description="Level of reasoning detail: 0=none, 1=brief, 2=moderate, 3=detailed")


class StockRecommendation(BaseModel):
    """Single stock recommendation from LLM."""
    ticker: str
    exchange: str = "N/A"
    currency: str = "N/A"
    stock_name: str = ""
    rating: int | str = 3  # 1-5 scale: 1=Strong Sell, 2=Sell, 3=Hold, 4=Buy, 5=Strong Buy
    price: Optional[str | float | int] = "N/A"
    fair_price: Optional[str | float | int] = "N/A"
    target_price: Optional[str | float | int] = "N/A"
    price_growth_forecast_pct: Optional[str | float | int] = "N/A"
    pe: Optional[str | float | int] = "N/A"
    recommendation_text: str = ""
    quality: RecommendationQuality = Field(default_factory=RecommendationQuality)
    
    def model_post_init(self, __context):
        """Convert numeric fields to strings and normalize rating to numeric 1-5 after validation."""
        currency_value = (self.currency or '').strip().upper()
        self.currency = currency_value if currency_value else 'N/A'

        # Convert numeric fields to strings
        for field in ['price', 'fair_price', 'target_price', 'price_growth_forecast_pct', 'pe']:
            value = getattr(self, field)
            if value is not None and not isinstance(value, str):
                setattr(self, field, str(value))
        
        # Convert star symbols and text ratings to numeric 1-5
        star_to_rating = {
            '★★★★★': 5,
            '★★★★': 4,
            '★★★': 3,
            '★★': 2,
            '★': 1,
            '\u2605\u2605\u2605\u2605\u2605': 5,
            '\u2605\u2605\u2605\u2605': 4,
            '\u2605\u2605\u2605': 3,
            '\u2605\u2605': 2,
            '\u2605': 1,
        }
        
        text_to_rating = {
            'Strong Buy': 5, 'strong buy': 5,
            'Buy': 4, 'buy': 4,
            'Hold': 3, 'hold': 3,
            'Sell': 2, 'sell': 2,
            'Strong Sell': 1, 'strong sell': 1,
            'N/A': 3,  # Default to Hold
        }
        
        # Convert string rating to numeric if needed
        if isinstance(self.rating, str):
            if self.rating in star_to_rating:
                self.rating = star_to_rating[self.rating]
            elif self.rating in text_to_rating:
                self.rating = text_to_rating[self.rating]
            else:
                # Try to parse as integer
                try:
                    rating_num = int(self.rating)
                    if 1 <= rating_num <= 5:
                        self.rating = rating_num
                    else:
                        self.rating = 3  # Default to Hold
                except ValueError:
                    self.rating = 3  # Default to Hold if invalid
        
        # Ensure rating is within valid range
        if not isinstance(self.rating, int) or not (1 <= self.rating <= 5):
            self.rating = 3  # Default to Hold


class StockRecommendationsResponse(BaseModel):
    """LLM response containing analysis date and list of stock recommendations."""
    analysis_date: str = "N/A"
    tickers: List[StockRecommendation] = Field(default_factory=list)

class WorkflowState(TypedDict):
    """State for the stock search workflow."""
    query: str
    executed_queries: List[str]  # Queries executed by search node
    search_results: List[Dict]  # Results from Google search
    filtered_search_results: List[Dict]  # After duplicate and bad domain filtering
    expanded_search_results: List[Dict]  # Includes filtered_search_results + nested links from those pages
    scraped_pages: List[Dict]  # Scraped pages with their stock recommendations
    deduplicated_pages: List[Dict]  # Pages after stock recommendation deduplication (pages may be removed if all recs are duplicates)
    skipped_recommendations: List[Dict]  # Stock recommendations skipped during deduplication
    status: str
    error: str
    process_name: Optional[str]  # Process name for progress tracking
    workflow_mode: Optional[str]  # discovery (default) | tracked
    batch_tickers: Optional[List[str]]  # Tickers processed in tracked mode
    batch_stock_names: Optional[Dict[str, str]]  # Optional ticker->stock name mapping
    fetch_metrics: Optional[Dict[str, int]]
    extraction_metrics: Optional[Dict[str, int]]


def merge_count_maps(*maps: Optional[Dict[str, int]]) -> Dict[str, int]:
    """Combine sparse integer metric maps."""
    merged: Dict[str, int] = {}
    for current in maps:
        for key, value in (current or {}).items():
            merged[key] = merged.get(key, 0) + int(value or 0)
    return merged


def is_obvious_non_stock_url(url: str) -> bool:
    """Return True when URL path strongly suggests non-stock detail content."""
    from urllib.parse import urlparse
    import re

    parsed = urlparse(str(url or ""))
    path = (parsed.path or "").lower()

    blocked_segments = [
        "fund",
        "funds",
        "etf",
        "etfs",
        "category",
        "categories",
    ]

    for segment in blocked_segments:
        if re.search(rf"(^|/)({re.escape(segment)})(/|$)", path):
            return True

    return False


def is_obvious_non_recommendation_link(url: str, link_text: str = "") -> bool:
    """Return True when URL or anchor text clearly points to legal/privacy/support content."""
    parsed = urlparse(str(url or ""))
    path = (parsed.path or "").lower()
    text = str(link_text or "").strip().lower()

    blocked_path_fragments = (
        "/privacy-policy",
        "/do-not-sell",
        "/cookie-policy",
        "/cookies",
        "/terms-of-use",
        "/terms-and-conditions",
        "/legal",
        "/contact-us",
        "/help",
        "/support",
    )

    blocked_text_fragments = (
        "privacy policy",
        "do not sell or share",
        "your privacy choices",
        "cookie policy",
        "terms of use",
        "terms and conditions",
        "contact us",
        "help center",
        "support",
    )

    if any(fragment in path for fragment in blocked_path_fragments):
        return True

    if any(fragment in text for fragment in blocked_text_fragments):
        return True

    return False


def has_ticker_like_evidence(title: str, snippet: str) -> bool:
    """Detect ticker-like evidence from title/snippet text."""
    import re

    text = f"{title or ''} {snippet or ''}"
    patterns = [
        r"\(([A-Z]{1,6}(?:\.[A-Z]{1,4})?)\)",
        r"\b(?:NYSE|NASDAQ|AMEX|TSX|LSE|XNAS|XNYS)\s*[:\-]\s*[A-Z]{1,6}(?:\.[A-Z]{1,4})?\b",
        r"\b[A-Z]{1,6}(?:\.[A-Z]{1,4})?\s+stock\b",
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def has_stock_name_recommendation_evidence(result: Dict) -> bool:
    """Detect recommendation-like content that references stock/company name without ticker symbols."""
    import re

    title = str(result.get("title") or "")
    body = str(result.get("body") or "")
    pagemap = result.get("pagemap") or {}
    metatags = pagemap.get("metatags") or []
    news_articles = pagemap.get("newsarticle") or []

    extra_parts = []
    if metatags:
        meta = metatags[0] or {}
        extra_parts.extend(
            [
                str(meta.get("og:title") or ""),
                str(meta.get("og:description") or ""),
                str(meta.get("parsely-title") or ""),
            ]
        )
    if news_articles:
        article = news_articles[0] or {}
        extra_parts.extend(
            [
                str(article.get("name") or ""),
                str(article.get("description") or ""),
                str(article.get("headline") or ""),
            ]
        )

    combined = " ".join([title, body, *extra_parts]).lower()
    recommendation_terms = (
        "undervalued",
        "fair value",
        "top picks",
        "analyst picks",
        "rating",
        "price target",
        "stocks to buy",
        "stock is",
        "we think",
    )

    has_recommendation_language = any(term in combined for term in recommendation_terms)
    if not has_recommendation_language:
        return False

    # Company-style mention patterns, e.g. "Meta: ..." or "Meta stock ..."
    company_like_patterns = [
        r"\b[A-Z][A-Za-z0-9&\.-]{1,40}\s+stock\b",
        r"^[A-Z][A-Za-z0-9&\.'\-\s]{2,60}:",
    ]
    title_has_company_pattern = any(
        re.search(pattern, title, re.IGNORECASE)
        for pattern in company_like_patterns
    )

    # Heuristic: article URL path already under /stocks/ tends to be relevant.
    href = str(result.get("href") or "").lower()
    path_suggests_stock_article = "/stocks/" in href

    return title_has_company_pattern or path_suggests_stock_article


def _get_discovery_intent_phrase_for_query(query: str) -> str:
    normalized = str(query or "").lower()
    for phrase in DISCOVERY_INTENT_PHRASES:
        if phrase in normalized:
            return phrase
    return ""


def get_discovery_cse_constraints(query: str) -> Dict[str, str]:
    """Return additional CSE constraints to improve recommendation intent precision."""
    constraints: Dict[str, str] = {
        "orTerms": DISCOVERY_QUERY_OR_TERMS,
        "excludeTerms": DISCOVERY_QUERY_EXCLUDE_TERMS,
    }
    intent_phrase = _get_discovery_intent_phrase_for_query(query)
    if intent_phrase:
        constraints["exactTerms"] = intent_phrase
    return constraints


def _domain_matches(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def is_discovery_noise_url(url: str) -> bool:
    """Return True when URL path is known to be low-signal for recommendation intents."""
    try:
        parsed = urlparse(str(url or ""))
        host = (parsed.netloc or "").lower().replace("www.", "")
        path = (parsed.path or "").lower()

        for domain, denied_prefixes in DISCOVERY_DOMAIN_PATH_DENYLIST.items():
            if _domain_matches(host, domain) and any(path.startswith(prefix) for prefix in denied_prefixes):
                return True
    except Exception:
        return False

    return False


def score_discovery_recommendation_intent(result: Dict) -> int:
    """Heuristic score for recommendation intent based on title/snippet evidence."""
    title = str(result.get("title") or "")
    snippet = str(result.get("body") or "")
    combined = f"{title} {snippet}".lower()

    score = 0
    score += sum(3 for phrase in DISCOVERY_INTENT_PHRASES if phrase in combined)
    score += min(4, sum(1 for term in DISCOVERY_POSITIVE_TERMS if term in combined))
    score -= min(4, sum(2 for term in DISCOVERY_NEGATIVE_TERMS if term in combined))

    if has_ticker_like_evidence(title, snippet):
        score += 1

    return score


def update_progress_if_available(state: WorkflowState, progress: int):
    """Update progress in database if process name is available.
    
    Creates a new database connection for each update to avoid storing
    non-serializable connection objects in workflow state.
    """
    process_name = state.get('process_name')
    if process_name:
        try:
            from repositories.recommendations_db import RecommendationsDatabase
            db = RecommendationsDatabase()
            db.update_process_progress(process_name, progress)
        except Exception as e:
            logger.warning(f"Failed to update progress: {e}")

def get_search_queries() -> List[str]:
    """Generate search queries based on templates"""
    queries: List[str] = []

    current_year = date.today().year
    current_month = date.today().month

    for q in SEARCH_QUERIES:
        for site in REPUTABLE_SITES:
            new_query = q.format(year=current_year, month=current_month, site=site)
            if new_query not in queries:
                queries.append(new_query)

    return queries


def get_tracked_batch_query_specs(
    batch_tickers: List[str],
    batch_stock_names: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """Generate grouped tracked-mode query specs for provided batch tickers."""
    query_specs: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    normalized_stock_names: Dict[str, str] = {}

    for ticker, stock_name in (batch_stock_names or {}).items():
        normalized_ticker = str(ticker or "").strip().upper()
        normalized_name = str(stock_name or "").strip()
        if normalized_ticker and normalized_name:
            normalized_stock_names[normalized_ticker] = normalized_name

    for ticker in batch_tickers:
        normalized_ticker = (ticker or '').strip().upper()
        if not normalized_ticker:
            continue

        stock_name = normalized_stock_names.get(normalized_ticker, "")

        for template in TRACKED_BATCH_SEARCH_QUERIES:
            query = build_tracked_query(
                normalized_ticker,
                stock_name,
                template,
                TRACKED_BATCH_SITES,
            )
            dedupe_key = (query, normalized_ticker)
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            query_specs.append({
                "query": query,
                "tracked_ticker": normalized_ticker,
            })

    return query_specs


def search_node(state: WorkflowState) -> WorkflowState:
    """Search for stock recommendations using Google Custom Search API."""
    update_progress_if_available(state, 30)
    executed_queries: List[str] = list(state.get("executed_queries") or [])

    try:
        if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
            return {
                **state,
                "query": executed_queries[-1] if executed_queries else state.get("query", ""),
                "executed_queries": executed_queries,
                "search_results": [],
                "status": "Search failed: GOOGLE_API_KEY or GOOGLE_CSE_ID not set",
                "error": "Missing Google API credentials"
            }

        workflow_mode = str(state.get("workflow_mode") or "discovery").strip().lower()
        if workflow_mode not in {"discovery", "tracked"}:
            workflow_mode = "discovery"

        service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
        all_results = []

        if workflow_mode == "tracked":
            result_index: dict[tuple[str, Optional[str]], int] = {}
            cse_calls_made = 0
            batch_tickers = []
            seen_tickers = set()
            for ticker in state.get("batch_tickers") or []:
                normalized_ticker = str(ticker or "").strip().upper()
                if not normalized_ticker or normalized_ticker in seen_tickers:
                    continue
                seen_tickers.add(normalized_ticker)
                batch_tickers.append(normalized_ticker)

            raw_batch_stock_names = state.get("batch_stock_names") or {}
            batch_stock_names: Dict[str, str] = {}
            if isinstance(raw_batch_stock_names, dict):
                for ticker, stock_name in raw_batch_stock_names.items():
                    normalized_ticker = str(ticker or "").strip().upper()
                    normalized_name = str(stock_name or "").strip()
                    if normalized_ticker and normalized_name:
                        batch_stock_names[normalized_ticker] = normalized_name

            query_specs: List[Dict[str, Optional[str]]] = [
                {"query": spec["query"], "tracked_ticker": spec["tracked_ticker"]}
                for spec in get_tracked_batch_query_specs(
                    batch_tickers,
                    batch_stock_names=batch_stock_names,
                )
            ]
            date_restrict = f"d{TRACKED_RESULT_AGE_DAYS}"

            def _upsert_result(item: Dict, tracked_ticker: Optional[str] = None):
                date_value = None
                pagemap = item.get('pagemap', {})
                metatags = pagemap.get('metatags', [])
                if metatags and len(metatags) > 0:
                    meta = metatags[0]
                    date_value = (
                        meta.get('og:article:published_time') or
                        meta.get('article:published_time') or
                        meta.get('sailthru.date') or
                        meta.get('og:article:modified_time') or
                        meta.get('parsely-pub-date') or
                        meta.get('datePublished') or
                        meta.get('publishdate') or
                        meta.get('date') or
                        meta.get('last-modified') or
                        meta.get('dc.date') or
                        meta.get('pubdate') or
                        meta.get('article:published')
                    )

                    if date_value:
                        date_value = date_value.rstrip(';').strip()

                normalized_date = None
                if date_value:
                    try:
                        date_str = date_value.replace('Z', '').split('T')[0]
                        date_obj = datetime.fromisoformat(date_str)
                        normalized_date = date_obj.strftime('%Y-%m-%d')
                    except Exception:
                        try:
                            from email.utils import parsedate_to_datetime
                            date_obj = parsedate_to_datetime(date_value)
                            normalized_date = date_obj.strftime('%Y-%m-%d')
                        except Exception:
                            try:
                                date_obj = datetime.strptime(date_value, '%a, %d %b %Y %H:%M:%S')
                                normalized_date = date_obj.strftime('%Y-%m-%d')
                            except Exception:
                                pass

                href = item.get('link', '')
                result_key = (href, normalized_date)

                if result_key in result_index:
                    existing = all_results[result_index[result_key]]
                    if tracked_ticker:
                        existing['is_tracked_stock_search'] = True
                        existing_tickers = existing.setdefault('tracked_tickers', [])
                        if tracked_ticker not in existing_tickers:
                            existing_tickers.append(tracked_ticker)
                            existing['tracked_ticker'] = existing_tickers[0]
                    return

                tracked_tickers = [tracked_ticker] if tracked_ticker else []
                all_results.append({
                    'title': item.get('title', ''),
                    'href': href,
                    'body': item.get('snippet', ''),
                    'date': normalized_date,
                    'pagemap': pagemap,
                    'is_tracked_stock_search': bool(tracked_ticker),
                    'tracked_ticker': tracked_ticker,
                    'tracked_tickers': tracked_tickers,
                })
                result_index[result_key] = len(all_results) - 1

            for query_spec in query_specs:
                query = query_spec['query']
                tracked_ticker = query_spec['tracked_ticker']
                executed_queries.append(query)
                try:
                    cse_calls_made += 1
                    result = service.cse().list(
                        q=query,
                        cx=GOOGLE_CSE_ID,
                        num=min(MAX_SEARCH_RESULTS, 10),
                        dateRestrict=date_restrict,
                        sort='date'
                    ).execute()

                    if 'items' in result:
                        for item in result['items']:
                            _upsert_result(item, tracked_ticker=tracked_ticker)
                except Exception as e:
                    logger.error(f"Search query '{query}' failed: {e}")
                    continue

            if cse_calls_made > 0:
                try:
                    usage_db = RecommendationsDatabase()
                    usage_db.log_cse_usage(
                        workflow_type="tracked_stock",
                        queries_count=cse_calls_made,
                    )
                except Exception as usage_error:
                    logger.warning(f"Failed to log CSE usage: {usage_error}")

            tracked_results_count = sum(1 for r in all_results if r.get('is_tracked_stock_search'))
            status = (
                f"Tracked mode: found {len(all_results)} results from {len(query_specs)} queries "
                f"for {len(batch_tickers)} tickers (age <= {TRACKED_RESULT_AGE_DAYS} days, "
                f"tracked results={tracked_results_count})"
            )
            if not query_specs:
                status = "Tracked mode: no tickers provided for this batch"
        else:
            date_restrict = f"d{MAX_RESULT_AGE_DAYS}"
            discovery_calls_made = 0

            for query in get_search_queries():
                executed_queries.append(query)
                try:
                    discovery_calls_made += 1
                    discovery_constraints = get_discovery_cse_constraints(query)
                    result = service.cse().list(
                        q=query,
                        cx=GOOGLE_CSE_ID,
                        num=min(MAX_SEARCH_RESULTS, 10),
                        dateRestrict=date_restrict,
                        sort='date',
                        **discovery_constraints,
                    ).execute()

                    if 'items' in result:
                        for item in result['items']:
                            date_value = None
                            pagemap = item.get('pagemap', {})
                            metatags = pagemap.get('metatags', [])
                            if metatags and len(metatags) > 0:
                                meta = metatags[0]
                                date_value = (
                                    meta.get('og:article:published_time') or
                                    meta.get('article:published_time') or
                                    meta.get('sailthru.date') or
                                    meta.get('og:article:modified_time') or
                                    meta.get('parsely-pub-date') or
                                    meta.get('datePublished') or
                                    meta.get('publishdate') or
                                    meta.get('date') or
                                    meta.get('last-modified') or
                                    meta.get('dc.date') or
                                    meta.get('pubdate') or
                                    meta.get('article:published')
                                )

                                if date_value:
                                    date_value = date_value.rstrip(';').strip()

                            normalized_date = None
                            if date_value:
                                try:
                                    date_str = date_value.replace('Z', '').split('T')[0]
                                    date_obj = datetime.fromisoformat(date_str)
                                    normalized_date = date_obj.strftime('%Y-%m-%d')
                                except Exception:
                                    try:
                                        from email.utils import parsedate_to_datetime
                                        date_obj = parsedate_to_datetime(date_value)
                                        normalized_date = date_obj.strftime('%Y-%m-%d')
                                    except Exception:
                                        try:
                                            date_obj = datetime.strptime(date_value, '%a, %d %b %Y %H:%M:%S')
                                            normalized_date = date_obj.strftime('%Y-%m-%d')
                                        except Exception:
                                            pass

                            all_results.append({
                                'title': item.get('title', ''),
                                'href': item.get('link', ''),
                                'body': item.get('snippet', ''),
                                'date': normalized_date,
                                'pagemap': pagemap,
                            })
                except Exception as e:
                    logger.error(f"Search query '{query}' failed: {e}")
                    continue

            try:
                usage_db = RecommendationsDatabase()
                usage_db.log_cse_usage(
                    workflow_type="discovery",
                    queries_count=discovery_calls_made,
                )
            except Exception as usage_error:
                logger.warning(f"Failed to log CSE usage: {usage_error}")

            status = f"Found {len(all_results)} results (filtered by {MAX_RESULT_AGE_DAYS} days)"

        return {
            **state,
            "query": executed_queries[-1] if executed_queries else state.get("query", ""),
            "executed_queries": executed_queries,
            "search_results": all_results,
            "status": status,
            "error": ""
        }

    except Exception as e:
        return {
            **state,
            "query": executed_queries[-1] if executed_queries else state.get("query", ""),
            "executed_queries": executed_queries,
            "search_results": [],
            "status": f"Search failed: {str(e)}",
            "error": str(e)
        }


def filter_duplicate_node(state: WorkflowState) -> WorkflowState:
    """Remove search results that already exist in webpage table (same URL, date)."""
    update_progress_if_available(state, 35)
    db = RecommendationsDatabase()
    search_results = state.get("search_results", [])
    
    filtered = []
    duplicates_removed = 0
    
    for result in search_results:
        url = result.get('href', '')
        date = result.get('date')
        if not db.webpage_exists(url, date):
            filtered.append(result)
        else:
            duplicates_removed += 1

    return {
        **state,
        "search_results": filtered,
        "status": f"Removed {duplicates_removed} duplicates, {len(filtered)} results remaining"
    }


def filter_known_bad_node(state: WorkflowState) -> WorkflowState:
    """Remove search results from domains marked as unusable (is_usable=0)."""
    update_progress_if_available(state, 40)
    db = RecommendationsDatabase()
    unusable_domains = db.get_unusable_domains()
    
    search_results = state.get("search_results", [])
    filtered = []
    bad_removed = 0
    blocked_removed = 0
    intent_removed = 0
    fetch_metrics = merge_count_maps(state.get('fetch_metrics'))
    workflow_mode = str(state.get("workflow_mode") or "discovery").strip().lower()
    if workflow_mode not in {"discovery", "tracked"}:
        workflow_mode = "discovery"
    
    for result in search_results:
        url = result.get('href', '')
        try:
            domain = urlparse(url).netloc.replace('www.', '')
            is_unusable = any(domain.endswith(unusable) for unusable in unusable_domains)
            blocked_match = db.get_blocked_url_match(url)
            if blocked_match:
                blocked_removed += 1
                fetch_metrics = merge_count_maps(fetch_metrics, {'blocked_cached_skips': 1})
            elif not is_unusable:
                if workflow_mode == "discovery":
                    if is_discovery_noise_url(url):
                        intent_removed += 1
                        continue

                    intent_score = score_discovery_recommendation_intent(result)
                    if intent_score < DISCOVERY_MIN_INTENT_SCORE:
                        intent_removed += 1
                        continue

                    enriched_result = {**result, "discovery_intent_score": intent_score}
                    filtered.append(enriched_result)
                else:
                    filtered.append(result)
            else:
                bad_removed += 1
        except Exception:
            filtered.append(result)
    
    return {
        **state,
        "filtered_search_results": filtered,
        "fetch_metrics": fetch_metrics,
        "status": (
            f"Removed {bad_removed} from unusable domains, {blocked_removed} from blocked URL rules, "
            f"{intent_removed} from low-intent discovery results, {len(filtered)} results remaining"
        ),
    }


def analyze_search_result(state: WorkflowState) -> WorkflowState:
    """Analyze each search result with an LLM to detect if it contains stock picks."""
    update_progress_if_available(state, 55)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    workflow_mode = str(state.get("workflow_mode") or "discovery").strip().lower()
    if workflow_mode not in {"discovery", "tracked"}:
        workflow_mode = "discovery"

    async def analyze_single_result(r: Dict) -> Dict:
        """Analyze a single search result asynchronously."""
        title = r.get("title", "")
        href = r.get("href", "")
        body = r.get("body", "")
        existing_date = r.get("date", "")

        # Pre-filter obvious non-stock URL categories before LLM calls.
        if is_obvious_non_stock_url(href):
            updated = dict(r)
            updated["contains_stocks"] = False
            updated["excerpt_date"] = existing_date or None
            return updated

        # In discovery mode, require either ticker-like evidence or strong stock-name evidence.
        if workflow_mode == "discovery" and not (
            has_ticker_like_evidence(title, body)
            or has_stock_name_recommendation_evidence(r)
        ):
            updated = dict(r)
            updated["contains_stocks"] = False
            updated["excerpt_date"] = existing_date or None
            return updated
        
        if existing_date:
            prompt_text = get_analyze_search_result_prompt(title, href, body)
            ex_date = existing_date
        else:
            prompt_text = get_analyze_search_result_with_date_prompt(title, href, body)
            ex_date = None

        try:
            resp = await llm.ainvoke([HumanMessage(content=prompt_text)])
            content = resp.content.strip()
            try:
                import json as _json
                parsed = _json.loads(content)
                contains = bool(parsed.get("contains_stocks"))
                if not existing_date:
                    ex_date = parsed.get("excerpt_date")
            except Exception:
                fallback_keywords = ["undervalued", "undervalued stocks", "cheap stocks", "value picks"]
                if workflow_mode == "tracked":
                    fallback_keywords = fallback_keywords + ["stock analysis", "stock rating", "stock forecast"]
                contains = any(w.lower() in (title + " " + body).lower() for w in fallback_keywords)
                if not existing_date:
                    ex_date = None
        except Exception:
            contains = False
            if not existing_date:
                ex_date = None

        if ex_date:
            try:
                pub_date_obj = datetime.fromisoformat(ex_date.split('T')[0])
                ex_date = pub_date_obj.strftime('%Y-%m-%d')
            except Exception:
                ex_date = None

        updated = dict(r)
        updated["contains_stocks"] = contains or (
            workflow_mode == "tracked" and bool(r.get("is_tracked_stock_search"))
        )
        updated["excerpt_date"] = ex_date
        return updated

    async def analyze_all():
        """Analyze all results in parallel."""
        tasks = [analyze_single_result(r) for r in state.get("expanded_search_results", [])]
        return await asyncio.gather(*tasks)

    # Run async analysis
    results = asyncio.run(analyze_all())

    return {
        **state,
        "expanded_search_results": results,
        "status": f"Analyzed {len(results)} search results",
    }

def extract_date_from_webpage(search_result: Dict, soup: BeautifulSoup) -> datetime:
    """Try to extract publication date from meta tags or content."""
    page_date = None
        
    date_meta_tags = [
        soup.find('meta', {'property': 'article:published_time'}),
        soup.find('meta', {'name': 'publish-date'}),
        soup.find('meta', {'name': 'date'}),
        soup.find('time', {'datetime': True})
    ]
    
    for tag in date_meta_tags:
        if tag:
            date_value = tag.get('content') or tag.get('datetime')
            if date_value:
                try:
                    page_date = datetime.fromisoformat(date_value.split('T')[0])
                    break
                except Exception:
                    pass
    
    if not page_date and search_result.get('date'):
        page_date = datetime.strptime(search_result['date'], '%Y-%m-%d')
    return page_date


def _get_request_status_code(error: Exception) -> Optional[int]:
    response = getattr(error, 'response', None)
    if response is None:
        return None
    return getattr(response, 'status_code', None)


def detect_challenge_page_text(page_text: str, original_html: str = '') -> Optional[str]:
    """Return matching anti-bot challenge marker when interstitial content is detected."""
    normalized_text = " ".join(str(page_text or '').lower().split())
    normalized_html = " ".join(str(original_html or '').lower().split())
    haystack = f"{normalized_text} {normalized_html}".strip()

    if not haystack:
        return None

    if "press & hold to confirm you are a human" in haystack:
        return "press & hold to confirm you are a human"

    if "press and hold to confirm you are a human" in haystack:
        return "press and hold to confirm you are a human"

    if "captcha" in haystack and "verify you are a human" in haystack:
        return "captcha verify you are a human"

    if "checking if the site connection is secure" in haystack and "cloudflare" in haystack:
        return "cloudflare checking if the site connection is secure"

    if "reference id" in haystack and "confirm you are a human" in haystack:
        return "reference id confirm you are a human"

    return None


def _raise_if_challenge_page(
    url: str,
    page_text: str,
    original_html: str,
    db: RecommendationsDatabase,
) -> None:
    """Persist blocked URL rules and raise terminal failure for challenge/interstitial pages."""
    marker = detect_challenge_page_text(page_text, original_html)
    if not marker:
        return

    patterns = db.record_blocked_url(url, reason=CHALLENGE_PAGE_REASON)
    logger.info(f"Persisted challenge blocked URL rules for {url}: {patterns}")
    raise TerminalFetchFailure(
        url=url,
        reason=f"Anti-bot challenge detected: {marker}",
        failure_type=CHALLENGE_PAGE_REASON,
    )


def _build_blocked_page_result(
    search_result: Dict,
    reason: str,
    fetch_status: str,
    fetch_metrics: Dict[str, int],
    status_code: Optional[int] = None,
    matched_pattern: Optional[str] = None,
) -> Dict:
    result = {
        'url': search_result.get('href', ''),
        'webpage_title': search_result.get('title', ''),
        'webpage_date': search_result.get('excerpt_date') or search_result.get('date') or datetime.now().strftime('%Y-%m-%d'),
        'page_text': '',
        'pdf_content': None,
        'stock_recommendations': [],
        'fetch_status': fetch_status,
        'fetch_error': reason,
        'fetch_metrics': fetch_metrics,
        'extraction_metrics': {},
        'is_tracked_stock_search': bool(search_result.get('is_tracked_stock_search')),
        'tracked_tickers': list(search_result.get('tracked_tickers') or []),
    }
    if status_code is not None:
        result['fetch_status_code'] = status_code
    if matched_pattern:
        result['matched_blocked_pattern'] = matched_pattern
    if 'expanded_from_url' in search_result:
        result['expanded_from_url'] = search_result['expanded_from_url']
    return result


def fetch_webpage_content_with_policy(
    url: str,
    headers: Dict,
    db: RecommendationsDatabase,
    use_browser: Optional[bool] = None,
) -> tuple[str, BeautifulSoup, str, Optional[bytes]]:
    """Fetch webpage with blocked-URL caching and bounded browser fallback for terminal failures."""
    blocked_match = db.get_blocked_url_match(url)
    if blocked_match:
        failure_type = CHALLENGE_PAGE_REASON if blocked_match.get('reason') == CHALLENGE_PAGE_REASON else 'terminal_http'
        raise TerminalFetchFailure(
            url=url,
            reason=f"Blocked URL rule matched: {blocked_match['pattern']}",
            status_code=blocked_match.get('status_code'),
            matched_pattern=blocked_match['pattern'],
            cached=True,
            failure_type=failure_type,
        )

    domain = urlparse(url).netloc
    browser_mode = db.needs_browser_rendering(domain) if use_browser is None else use_browser

    try:
        page_text, soup, original_html, pdf_bytes = fetch_webpage_content(url, headers, use_browser=browser_mode)
        _raise_if_challenge_page(url, page_text, original_html, db)
        return page_text, soup, original_html, pdf_bytes
    except ValueError as error:
        error_text = str(error)
        if "Brotli-compressed" in error_text and not browser_mode:
            logger.warning(f"Brotli encoding issue for {url}, retrying with browser rendering")
            page_text, soup, original_html, pdf_bytes = fetch_webpage_content(url, headers, use_browser=True)
            _raise_if_challenge_page(url, page_text, original_html, db)
            logger.info(f"Browser rendering successful for {domain}, updating database")
            db.upsert_website(domain, is_usable=1, requires_browser=1)
            return page_text, soup, original_html, pdf_bytes
        raise
    except requests.RequestException as error:
        status_code = _get_request_status_code(error)

        if status_code == 403 and not browser_mode:
            logger.warning(f"403 Forbidden for {url}, retrying once with browser rendering")
            try:
                page_text, soup, original_html, pdf_bytes = fetch_webpage_content(url, headers, use_browser=True)
                _raise_if_challenge_page(url, page_text, original_html, db)
                logger.info(f"Browser rendering successful for {domain}, updating database")
                db.upsert_website(domain, is_usable=1, requires_browser=1)
                return page_text, soup, original_html, pdf_bytes
            except requests.RequestException as browser_error:
                browser_status_code = _get_request_status_code(browser_error)
                if browser_status_code in TERMINAL_HTTP_STATUS_CODES:
                    patterns = db.record_blocked_url(url, status_code=browser_status_code, reason='terminal_http_status')
                    logger.info(f"Persisted blocked URL rules for {url}: {patterns}")
                    raise TerminalFetchFailure(
                        url=url,
                        reason=f"Terminal HTTP {browser_status_code} after browser retry",
                        status_code=browser_status_code,
                    ) from browser_error
                raise

        if status_code in TERMINAL_HTTP_STATUS_CODES:
            patterns = db.record_blocked_url(url, status_code=status_code, reason='terminal_http_status')
            logger.info(f"Persisted blocked URL rules for {url}: {patterns}")
            raise TerminalFetchFailure(
                url=url,
                reason=f"Terminal HTTP {status_code}",
                status_code=status_code,
            ) from error

        raise


def fetch_webpage_content(
    url: str,
    headers: Dict,
    use_browser: bool = False,
    browser_timeout_seconds: int = BROWSER_FETCH_TIMEOUT_SECONDS,
) -> tuple[str, BeautifulSoup, str, Optional[bytes]]:
    """Fetch webpage and return (page_text, parsed_soup, original_html, pdf_bytes)."""
    if use_browser:
        from playwright.async_api import async_playwright
        import re
        
        async def run_playwright_async():
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                    ]
                )
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                    timezone_id='America/New_York',
                    java_script_enabled=True,
                    has_touch=False,
                    is_mobile=False,
                    device_scale_factor=1,
                )
                
                # Remove webdriver detection and other bot indicators
                page = await context.new_page()
                await page.add_init_script("""
                    // Remove webdriver property
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    
                    // Override the plugins property
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    
                    // Override the languages property
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                    
                    // Override chrome property
                    window.chrome = {
                        runtime: {}
                    };
                    
                    // Override permissions
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                """)

                async def _expand_collapsed_content() -> int:
                    """Expand article text by clicking common 'read more/show more' controls."""
                    expansion_patterns = [
                        r"read\\s+more",
                        r"show\\s+more",
                        r"see\\s+more",
                        r"view\\s+more",
                        r"continue\\s+reading",
                        r"continue",
                        r"expand",
                        r"read\\s+full",
                        r"full\\s+(article|story|text|content)",
                        r"load\\s+more",
                    ]
                    expand_regex = re.compile("|".join(expansion_patterns), re.IGNORECASE)

                    async def _click_in_frame(frame) -> int:
                        clicked_count = 0

                        # Site-specific expand controls (known problematic patterns)
                        try:
                            site_specific_locators = [
                                frame.locator("span.show_article"),
                                frame.locator(".archive_collapse"),
                            ]
                            for locator in site_specific_locators:
                                count = min(await locator.count(), 5)
                                for index in range(count):
                                    try:
                                        candidate = locator.nth(index)
                                        if await candidate.is_visible() and await candidate.is_enabled():
                                            await candidate.scroll_into_view_if_needed(timeout=1000)
                                            await candidate.click(timeout=1500, force=True)
                                            clicked_count += 1
                                            await page.wait_for_timeout(500)
                                    except Exception:
                                        continue
                        except Exception:
                            pass

                        role_locators = [
                            frame.get_by_role("button", name=expand_regex),
                            frame.get_by_role("link", name=expand_regex),
                        ]
                        css_locators = [
                            frame.locator("button, [role='button'], summary"),
                            frame.locator("a[href^='#'], a[href^='javascript:']"),
                            frame.locator("[aria-expanded='false']"),
                            frame.locator("[class*='read-more'], [id*='read-more']"),
                            frame.locator("[class*='show-more'], [id*='show-more']"),
                            frame.locator("[class*='expand'], [id*='expand']"),
                            frame.locator("[class*='continue'], [id*='continue']"),
                        ]

                        for locator in role_locators + css_locators:
                            try:
                                count = await locator.count()
                            except Exception:
                                continue

                            count = min(count, 12)
                            for index in range(count):
                                try:
                                    candidate = locator.nth(index)
                                    text_blob = (
                                        ((await candidate.inner_text(timeout=500)) or "") + " " +
                                        ((await candidate.get_attribute("aria-label")) or "") + " " +
                                        ((await candidate.get_attribute("title")) or "") + " " +
                                        ((await candidate.get_attribute("class")) or "") + " " +
                                        ((await candidate.get_attribute("id")) or "")
                                    )

                                    if not expand_regex.search(text_blob):
                                        continue

                                    if not await candidate.is_visible() or not await candidate.is_enabled():
                                        continue

                                    tag_name = await candidate.evaluate("el => (el.tagName || '').toLowerCase()")
                                    if tag_name == 'a':
                                        href = (await candidate.get_attribute('href') or '').strip().lower()
                                        if href and not (href.startswith('#') or href.startswith('javascript:')):
                                            continue

                                    await candidate.scroll_into_view_if_needed(timeout=1000)
                                    await candidate.click(timeout=1500, force=True)
                                    clicked_count += 1
                                    await page.wait_for_timeout(600)
                                except Exception:
                                    continue

                        # Fallback JavaScript click pass for non-standard controls
                        try:
                            js_clicked = await frame.evaluate(
                                """
                                () => {
                                    const regex = /read\\s+more|show\\s+more|see\\s+more|view\\s+more|continue\\s+reading|read\\s+full|full\\s+(article|story|text|content)|expand|load\\s+more/i;
                                    const nodes = Array.from(document.querySelectorAll('button, a, [role="button"], summary, [aria-expanded]'));
                                    let clicked = 0;

                                    const isVisible = (el) => {
                                        const style = window.getComputedStyle(el);
                                        const rect = el.getBoundingClientRect();
                                        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                                    };

                                    for (const el of nodes.slice(0, 200)) {
                                        try {
                                            if (el.dataset.copilotExpandedClicked === '1') continue;

                                            const text = `${el.innerText || ''} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''} ${el.className || ''} ${el.id || ''}`;
                                            if (!regex.test(text)) continue;
                                            if (!isVisible(el) || el.disabled) continue;

                                            if (el.tagName.toLowerCase() === 'a') {
                                                const href = (el.getAttribute('href') || '').trim().toLowerCase();
                                                if (href && !(href.startsWith('#') || href.startsWith('javascript:'))) continue;
                                            }

                                            el.dataset.copilotExpandedClicked = '1';
                                            el.click();
                                            clicked += 1;
                                        } catch {
                                            // Ignore element-level failures
                                        }
                                    }

                                    return clicked;
                                }
                                """
                            )
                            if isinstance(js_clicked, int):
                                clicked_count += js_clicked
                        except Exception:
                            pass

                        return clicked_count

                    total_clicked = 0

                    # Scroll to trigger lazy-loaded sections first
                    try:
                        for _ in range(4):
                            await page.mouse.wheel(0, 1800)
                            await page.wait_for_timeout(450)
                        await page.evaluate("window.scrollTo(0, 0)")
                        await page.wait_for_timeout(500)
                    except Exception:
                        pass

                    for _ in range(5):
                        round_clicks = 0
                        for frame in page.frames:
                            try:
                                round_clicks += await _click_in_frame(frame)
                            except Exception:
                                continue

                        total_clicked += round_clicks
                        if round_clicks == 0:
                            break

                        await page.wait_for_timeout(1200)

                    return total_clicked
                
                try:
                    # Navigate and wait for DOM to be ready (more reliable than networkidle for ad-heavy sites)
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    
                    # Wait for dynamic content to load (longer wait since we're not using networkidle)
                    await page.wait_for_timeout(8000)
                    
                    # Handle cookie consent banners
                    cookie_consent_selectors = [
                        'button:has-text("Alle akzeptieren")',  # German: Accept all
                        'button:has-text("Accept all")',
                        'button:has-text("Accept All")',
                        'button:has-text("I Accept")',
                        'button:has-text("I agree")',
                        'button:has-text("Agree")',
                        'button:has-text("Alle ablehnen")',  # German: Reject all (fallback)
                        'button:has-text("Reject all")',
                        '[class*="accept"][class*="cookie"]',
                        '[class*="consent"][class*="accept"]',
                        '[id*="accept"][id*="cookie"]',
                    ]
                    
                    for selector in cookie_consent_selectors:
                        try:
                            if await page.locator(selector).count() > 0:
                                await page.locator(selector).first.click(timeout=2000)
                                logger.info(f"Clicked cookie consent button: {selector}")
                                await page.wait_for_timeout(1000)
                                break
                        except Exception:
                            continue

                    # Expand collapsed article content prior to extracting text/PDF
                    expanded_clicks = await _expand_collapsed_content()
                    if expanded_clicks > 0:
                        logger.info(f"Expanded collapsed content with {expanded_clicks} click(s) for {url}")
                    else:
                        logger.debug(f"No expandable controls detected for {url}")
                    
                    await page.wait_for_timeout(2000)
                    
                    # Hide advertisement overlays and sticky elements before PDF generation
                    await page.evaluate("""
                        // Remove fixed/sticky position ads and overlays that cover content
                        const selectorsToHide = [
                            '[class*="ad-"][class*="overlay"]',
                            '[class*="sticky-ad"]',
                            '[id*="ad-overlay"]',
                            '[class*="adhesion"]',
                            '[class*="floating-ad"]',
                            '[class*="notification-bar"]',
                            '[class*="newsletter-popup"]',
                            '[data-ad-type]',
                            'iframe[src*="doubleclick"]',
                            'iframe[src*="googlesyndication"]',
                            '[class*="modal-backdrop"]',
                            '[class*="overlay"]',
                            '.archive_collapse',
                            '.show_article'
                        ];
                        
                        selectorsToHide.forEach(selector => {
                            try {
                                document.querySelectorAll(selector).forEach(el => {
                                    const style = window.getComputedStyle(el);
                                    const position = style.position;
                                    const zIndex = style.zIndex;
                                    
                                    // Hide if it's a fixed/sticky element with high z-index
                                    if ((position === 'fixed' || position === 'sticky') && 
                                        (zIndex === 'auto' || parseInt(zIndex) > 100)) {
                                        el.style.display = 'none';
                                    }
                                });
                            } catch (e) {
                                // Ignore selector errors
                            }
                        });
                        
                        // Also hide any element with very high z-index (likely ads/overlays)
                        document.querySelectorAll('*').forEach(el => {
                            try {
                                const style = window.getComputedStyle(el);
                                const zIndex = parseInt(style.zIndex);
                                const position = style.position;
                                
                                // Hide fixed elements with z-index > 1000
                                if ((position === 'fixed' || position === 'sticky') && zIndex > 1000) {
                                    el.style.display = 'none';
                                }
                            } catch (e) {
                                // Ignore errors
                            }
                        });
                    """)
                    
                    # Switch to print media mode (often hides ads automatically)
                    await page.emulate_media(media='print')
                    
                    html_content = await page.content()
                    
                    # Generate PDF
                    pdf_bytes = await page.pdf(
                        format='A4',
                        print_background=True,
                        margin={'top': '20px', 'right': '20px', 'bottom': '20px', 'left': '20px'}
                    )
                    
                    return html_content, pdf_bytes
                finally:
                    await browser.close()
        
        # Run async Playwright with a hard timeout to prevent indefinite hangs.
        try:
            html_content, pdf_bytes = asyncio.run(
                asyncio.wait_for(run_playwright_async(), timeout=browser_timeout_seconds)
            )
        except asyncio.TimeoutError as timeout_error:
            raise TimeoutError(
                f"Browser fetch timed out after {browser_timeout_seconds}s for {url}"
            ) from timeout_error
        
        soup = BeautifulSoup(html_content, 'html.parser')
    else:
        session = requests.Session()
        session.headers.update(headers)
        
        response = session.get(
            url, 
            timeout=10,
            allow_redirects=True,
            verify=True
        )
        response.raise_for_status()

        content_encoding = response.headers.get('Content-Encoding', '')
        if 'br' in content_encoding:
            raise ValueError(
                f"Server returned Brotli-compressed content for {url}. "
                "Remove 'br' from Accept-Encoding headers or install the 'brotli' package."
            )

        html_content = response.content
        soup = BeautifulSoup(html_content, 'html.parser')
    
    for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
        element.decompose()

    # Remove known "expand/read more" controls from extracted text
    for element in soup.select('.archive_collapse, .show_article'):
        element.decompose()
    
    main_content = None
    content_selectors = [
        soup.find('main'),
        soup.find('article'),
        soup.find('div', {'class': ['content', 'main-content', 'article-content', 'post-content', 'entry-content']}),
        soup.find('div', {'id': ['content', 'main-content', 'article', 'post']}),
    ]
    
    for selector in content_selectors:
        if selector:
            main_content = selector
            break
    
    if main_content:
        page_text = main_content.get_text(separator=' ', strip=True)
        links_section = main_content
    else:
        body = soup.find('body')
        page_text = body.get_text(separator=' ', strip=True) if body else soup.get_text(separator=' ', strip=True)
        links_section = body if body else soup
    
    # Extract links with their anchor text to preserve context
    links_info = []
    if links_section:
        for link in links_section.find_all('a', href=True):
            link_text = link.get_text(strip=True)
            link_href = link.get('href')
            if link_text and link_href and len(link_text) > 5:  # Filter out short/empty links
                # Make relative URLs absolute
                from urllib.parse import urljoin
                absolute_url = urljoin(url, link_href)
                links_info.append(f"{link_text} [{absolute_url}]")
    
    # Append links section to page text if we found any relevant links
    if links_info:
        links_text = "\n\nRELATED LINKS:\n" + "\n".join(links_info[:50])  # Limit to 50 links
        page_text = page_text[:9000] + links_text  # Leave room for links
    else:
        page_text = page_text[:10000]
    
    return page_text, soup, html_content, pdf_bytes if use_browser else None

def validate_ticker_in_text(ticker: str, text: str) -> bool:
    """Verify that ticker symbol actually appears in the text."""
    import re
    pattern = r'\b' + re.escape(ticker.upper()) + r'\b'
    return bool(re.search(pattern, text.upper()))


def validate_stock_name_in_text(stock_name: str, text: str) -> bool:
    """Verify that the stock/company name appears in the text (case-insensitive)."""
    normalized_name = " ".join(str(stock_name or "").split())
    if len(normalized_name) < 3:
        return False
    return normalized_name.lower() in str(text or "").lower()


def extract_explicit_rating_from_text(text: str) -> Optional[int]:
    """Extract explicit star or text rating from source text when present."""
    import re

    normalized = " ".join(str(text or "").split())
    if not normalized:
        return None

    star_match = re.search(r"Morningstar\s+Rating\s*:\s*([★\u2605]{1,5})", normalized, re.IGNORECASE)
    if star_match:
        return len(star_match.group(1))

    text_ratings = {
        'strong buy': 5,
        'buy': 4,
        'hold': 3,
        'sell': 2,
        'strong sell': 1,
    }
    for rating_text, rating_value in text_ratings.items():
        if re.search(rf"\b{re.escape(rating_text)}\b", normalized, re.IGNORECASE):
            return rating_value

    return None


def calculate_recommendation_quality_score(quality: RecommendationQuality) -> int:
    """
    Calculate total quality score from LLM-extracted components.
    
    Scoring:
    - Description length: 0-30 points (10 points per 50 words, max 150 words)
    - Explicit rating: 25 points if present
    - Reasoning detail: 0-45 points (level * 15, where level is 0-3)
    
    Total possible: 100 points
    """
    score = 0
    
    # Description length (0-30 points)
    description_score = min(30, (quality.description_word_count // 50) * 10)
    score += description_score
    
    # Explicit rating (25 points)
    if quality.has_explicit_rating:
        score += 25
    
    # Reasoning detail (0-30 points): 0=0pts, 1=10pts, 2=20pts, 3=30pts
    score += quality.reasoning_detail_level * 10
    
    return score

def extract_stock_recommendations_with_llm(
    url: str,
    title: str,
    page_text: str,
    page_date: datetime,
    tracked_tickers: Optional[List[str]] = None,
    return_metrics: bool = False,
) -> List[Dict] | tuple[List[Dict], Dict[str, int]]:
    """Extract stock recommendations from page content using LLM."""
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    structured_llm = llm.with_structured_output(StockRecommendationsResponse)
    extraction_metrics = {
        'hallucinated_tickers': 0,
        'low_quality_filtered': 0,
        'inferred_tickers': 0,
    }

    if tracked_tickers:
        extraction_prompt = get_extract_stocks_prompt_tracked(url, title, page_text, tracked_tickers)
    else:
        extraction_prompt = get_extract_stocks_prompt(url, title, page_text)

    try:
        llm_response = structured_llm.invoke([HumanMessage(content=extraction_prompt)])
    except Exception as e:
        logger.error(f"Error extracting recommendations from {url}: {e}")
        return ([], extraction_metrics) if return_metrics else []
    
    analysis_date = llm_response.analysis_date
    if not analysis_date or analysis_date == "N/A":
        analysis_date = page_date.strftime('%Y-%m-%d')
    
    if analysis_date > datetime.now().strftime('%Y-%m-%d'):
        analysis_date = datetime.now().strftime('%Y-%m-%d')
   
    if not llm_response.tickers:
        return ([], extraction_metrics) if return_metrics else []
    
    recommendations = []
    for ticker_obj in llm_response.tickers:
        inferred_ticker_info = None
        normalized_ticker = str(ticker_obj.ticker or '').strip().upper()
        if not normalized_ticker or normalized_ticker == 'N/A':
            inferred_ticker_info = infer_ticker_from_stock_name(
                ticker_obj.stock_name,
                exchange=ticker_obj.exchange,
                currency=ticker_obj.currency,
            )

            if not inferred_ticker_info:
                extraction_metrics['hallucinated_tickers'] += 1
                logger.warning(
                    f"Could not infer ticker for stock_name '{ticker_obj.stock_name}' from {url}; skipping"
                )
                continue

            ticker_obj.ticker = inferred_ticker_info['ticker']
            normalized_ticker = str(ticker_obj.ticker or '').strip().upper()
            if not ticker_obj.exchange or ticker_obj.exchange == 'N/A':
                ticker_obj.exchange = inferred_ticker_info.get('exchange', ticker_obj.exchange)
            if not ticker_obj.stock_name or ticker_obj.stock_name == 'N/A':
                ticker_obj.stock_name = inferred_ticker_info.get('stock_name', ticker_obj.stock_name)
            extraction_metrics['inferred_tickers'] += 1

        reference_text = f"{title}\n{page_text}"
        ticker_present = validate_ticker_in_text(normalized_ticker, reference_text)
        stock_name_present = validate_stock_name_in_text(ticker_obj.stock_name, reference_text)

        if ticker_present or stock_name_present:
            explicit_rating = extract_explicit_rating_from_text(f"{title}\n{page_text}")
            if explicit_rating is not None:
                ticker_obj.rating = explicit_rating
                ticker_obj.quality.has_explicit_rating = True

            # Calculate quality score from LLM-extracted quality indicators
            quality_score = calculate_recommendation_quality_score(ticker_obj.quality)
            if quality_score < LOW_QUALITY_RECOMMENDATION_THRESHOLD:
                extraction_metrics['low_quality_filtered'] += 1
                logger.info(
                    f"Filtered low quality recommendation for {ticker_obj.ticker}: score={quality_score}"
                )
                continue
            
            recommendation = {
                'ticker': normalized_ticker,
                'exchange': (ticker_obj.exchange or 'N/A').strip() or 'N/A',
                'currency': ticker_obj.currency,
                'stock_name': ticker_obj.stock_name,
                'rating': ticker_obj.rating,
                'analysis_date': analysis_date,
                'price': ticker_obj.price,
                'fair_price': ticker_obj.fair_price,
                'target_price': ticker_obj.target_price,
                'price_growth_forecast_pct': ticker_obj.price_growth_forecast_pct,
                'pe': ticker_obj.pe,
                'recommendation_text': ticker_obj.recommendation_text,
                'quality_score': quality_score,
                'quality_description_words': ticker_obj.quality.description_word_count,
                'quality_has_rating': ticker_obj.quality.has_explicit_rating,
                'quality_reasoning_level': ticker_obj.quality.reasoning_detail_level
            }

            if inferred_ticker_info:
                recommendation['ticker_inference_method'] = inferred_ticker_info.get('method', 'name_inference')
                recommendation['ticker_inference_confidence'] = inferred_ticker_info.get('confidence', 0.0)

            recommendations.append(recommendation)
        else:
            extraction_metrics['hallucinated_tickers'] += 1
            logger.warning(
                f"Hallucinated/unsupported recommendation ({normalized_ticker}) not grounded in page text by ticker or stock_name, skipping"
            )

    if return_metrics:
        return recommendations, extraction_metrics
    return recommendations

def scrape_single_page(search_result: Dict, headers: Dict, db: RecommendationsDatabase) -> Dict:
    """Scrape a single web page and extract stock recommendation information using LLM."""
    url = search_result.get("href", "")
    if not url:
        return None
    
    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    use_browser = db.needs_browser_rendering(domain)

    logger.info(f"Scraping page: {url} (browser={use_browser})")
    
    try:
        page_text, soup, original_html, pdf_bytes = fetch_webpage_content_with_policy(
            url,
            headers,
            db,
            use_browser=use_browser,
        )
    except TerminalFetchFailure as blocked_error:
        logger.info(f"Skipping blocked page {url}: {blocked_error.reason}")
        return _build_blocked_page_result(
            search_result,
            reason=blocked_error.reason,
            fetch_status='blocked_cached' if blocked_error.cached else 'blocked_terminal',
            fetch_metrics=blocked_error.metrics(),
            status_code=blocked_error.status_code,
            matched_pattern=blocked_error.matched_pattern,
        )
    except ValueError as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None
    
    try:
        page_date = extract_date_from_webpage(search_result, soup)
        if not page_date:
            date_now = datetime.now()
            excerpt_date = search_result.get('excerpt_date')
            if excerpt_date:
                if isinstance(excerpt_date, str):
                    page_date = datetime.strptime(excerpt_date, '%Y-%m-%d')
                else:
                    page_date = excerpt_date
            else:
                page_date = date_now

            if page_date > date_now:
                page_date = date_now
        
        if not isinstance(page_date, datetime):
            page_date = datetime.now()

        webpage_title = search_result.get('title', '')
        webpage_date = page_date.strftime('%Y-%m-%d')

        tracked_tickers = search_result.get('tracked_tickers') or []
        if not tracked_tickers:
            tracked_ticker = search_result.get('tracked_ticker')
            if tracked_ticker:
                tracked_tickers = [tracked_ticker]

        stock_recommendations, extraction_metrics = extract_stock_recommendations_with_llm(
            url=url,
            title=webpage_title,
            page_text=page_text,
            page_date=page_date,
            tracked_tickers=tracked_tickers,
            return_metrics=True,
        )

        # Keep lightweight HTTP fetch by default, but ensure recommendation pages
        # still get a PDF artifact for downstream UI links and auditing.
        if not pdf_bytes and stock_recommendations:
            try:
                _, _, _, fallback_pdf_bytes = fetch_webpage_content(
                    url,
                    headers,
                    use_browser=True,
                )
                if fallback_pdf_bytes:
                    pdf_bytes = fallback_pdf_bytes
                    logger.info(f"Captured fallback PDF for recommendation page: {url}")
            except Exception as fallback_error:
                logger.warning(
                    f"Failed fallback PDF capture for recommendation page {url}: {fallback_error}"
                )

        result = {
            'url': url,
            'webpage_title': webpage_title,
            'webpage_date': webpage_date,
            'page_text': page_text,
            'pdf_content': pdf_bytes if 'pdf_bytes' in locals() else None,
            'stock_recommendations': stock_recommendations,
            'fetch_status': 'ok',
            'fetch_metrics': {},
            'extraction_metrics': extraction_metrics,
            'is_tracked_stock_search': bool(search_result.get('is_tracked_stock_search')),
            'tracked_tickers': tracked_tickers,
        }
        
        # Propagate expanded_from_url if present in search_result
        if 'expanded_from_url' in search_result:
            result['expanded_from_url'] = search_result['expanded_from_url']
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response for {url}: {e}")
        result = {
            'url': url,
            'webpage_title': search_result.get('title', ''),
            'webpage_date': datetime.now().strftime('%Y-%m-%d'),
            'page_text': page_text,
            'pdf_content': pdf_bytes if 'pdf_bytes' in locals() else None,
            'stock_recommendations': [],
            'fetch_status': 'ok',
            'fetch_metrics': {},
            'extraction_metrics': {},
        }
        if 'expanded_from_url' in search_result:
            result['expanded_from_url'] = search_result['expanded_from_url']
        return result
    except Exception as e:
        logger.error(f"Scraping failed for {url}: {e}")
        result = {
            'url': url,
            'webpage_title': search_result.get('title', ''),
            'webpage_date': datetime.now().strftime('%Y-%m-%d'),
            'page_text': page_text if 'page_text' in locals() else '',
            'pdf_content': pdf_bytes if 'pdf_bytes' in locals() else None,
            'stock_recommendations': [],
            'fetch_status': 'ok',
            'fetch_metrics': {},
            'extraction_metrics': {},
        }
        if 'expanded_from_url' in search_result:
            result['expanded_from_url'] = search_result['expanded_from_url']
        return result

def retrieve_nested_pages(state: WorkflowState) -> WorkflowState:
    """Extract nested links from filtered search results and expand the list."""
    update_progress_if_available(state, 45)
    from urllib.parse import urljoin, urlparse
    import requests
    from bs4 import BeautifulSoup
    
    filtered_results = state.get('filtered_search_results', [])
    expanded_results = list(filtered_results)  # Start with all filtered results
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    db = RecommendationsDatabase()
    nested_links_found = 0
    nested_fetch_metrics = merge_count_maps(state.get('fetch_metrics'))
    
    logger.info(f"Retrieving nested links from {len(filtered_results)} pages...")
    
    for parent_result in filtered_results:
        parent_url = parent_result.get('href', '')
        if not parent_url:
            continue
        
        try:
            # Fetch the parent page
            parsed_url = urlparse(parent_url)
            domain = parsed_url.netloc
            use_browser = db.needs_browser_rendering(domain)
            
            try:
                _, soup, _, _ = fetch_webpage_content_with_policy(parent_url, headers, db, use_browser=use_browser)
            except TerminalFetchFailure as blocked_error:
                nested_fetch_metrics = merge_count_maps(nested_fetch_metrics, blocked_error.metrics())
                logger.info(f"Skipping nested link extraction for blocked page {parent_url}: {blocked_error.reason}")
                continue
            except Exception as e:
                logger.warning(f"Failed to fetch {parent_url} for nested link extraction: {e}")
                continue
            
            # Extract all links from the page
            links_found = set()
            for link in soup.find_all('a', href=True):
                link_href = link.get('href')
                link_text = link.get_text(strip=True)
                
                # Skip empty or very short links
                if not link_text or len(link_text) < 10:
                    continue
                
                # Make relative URLs absolute
                absolute_url = urljoin(parent_url, link_href)

                if is_obvious_non_recommendation_link(absolute_url, link_text):
                    continue
                
                # Skip if same domain and already in our results
                if absolute_url == parent_url:
                    continue
                    
                # Check if URL looks like a stock analysis page based on link text
                stock_keywords = ['stock', 'quote', 'analysis', 'fair value', 'undervalued', 
                                'recommendation', 'buy', 'sell', 'target price', 'estimate']
                if any(keyword in link_text.lower() for keyword in stock_keywords):
                    links_found.add((absolute_url, link_text))
            
            # Add unique nested links to expanded results
            existing_urls = {r.get('href') for r in expanded_results}
            
            for nested_url, link_text in links_found:
                if nested_url not in existing_urls:
                    if is_obvious_non_stock_url(nested_url):
                        continue

                    nested_result = {
                        'title': link_text,
                        'href': nested_url,
                        'body': '',
                        'date': None,
                        'expanded_from_url': parent_url,
                        'pagemap': {}
                    }
                    if parent_result.get('is_tracked_stock_search'):
                        nested_result['is_tracked_stock_search'] = True
                    if parent_result.get('tracked_tickers'):
                        nested_result['tracked_tickers'] = list(parent_result.get('tracked_tickers', []))
                    elif parent_result.get('tracked_ticker'):
                        nested_result['tracked_ticker'] = parent_result['tracked_ticker']
                        nested_result['tracked_tickers'] = [parent_result['tracked_ticker']]
                    expanded_results.append(nested_result)
                    existing_urls.add(nested_url)
                    nested_links_found += 1
        
        except Exception as e:
            logger.error(f"Error extracting nested links from {parent_url}: {e}")
            continue
    
    status_msg = f"Expanded {len(filtered_results)} pages to {len(expanded_results)} pages ({nested_links_found} nested links found)"
    logger.info(status_msg)
    
    return {
        **state,
        "expanded_search_results": expanded_results,
        "fetch_metrics": nested_fetch_metrics,
        "status": status_msg
    }

def scrape_node(state: WorkflowState) -> WorkflowState:
    """Scrape stock recommendations from expanded search results."""
    update_progress_if_available(state, 65)
    db = RecommendationsDatabase()
    
    cutoff_date = datetime.now() - timedelta(days=MAX_RESULT_AGE_DAYS)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0'
    }
    
    pages_to_scrape = []
    skipped_count = 0
    skipped_from_scraping = []
    
    # Use expanded_search_results if available, otherwise fall back to filtered_search_results
    search_results_to_use = state.get("expanded_search_results", state.get("filtered_search_results", []))
    
    for search_result in search_results_to_use[:100]:  # Limit to first 100 results
        if not search_result.get('contains_stocks', False):
            skipped_count += 1
            continue
        
        excerpt_date_str = search_result.get('excerpt_date')
        if excerpt_date_str:
            try:
                excerpt_date = datetime.strptime(excerpt_date_str, '%Y-%m-%d')
                if excerpt_date < cutoff_date:
                    skipped_count += 1
                    search_result['skipped_scraping_reason'] = 'Old excerpt date'
                    skipped_from_scraping.append(search_result)
                    continue
            except ValueError:
                skipped_count += 1
                search_result['skipped_scraping_reason'] = 'Error parsing excerpt date'
                skipped_from_scraping.append(search_result)
                continue
        else:
            skipped_count += 1
            search_result['skipped_scraping_reason'] = 'No excerpt date'
            skipped_from_scraping.append(search_result)
            continue
        
        pages_to_scrape.append(search_result)
    
    import concurrent.futures
    
    def scrape_with_error_handling(search_result):
        """Wrapper to handle errors in parallel execution."""
        try:
            return scrape_single_page(search_result, headers, db)
        except Exception as e:
            logger.error(f"Error scraping {search_result.get('href', 'unknown')}: {e}")
            return None
    
    scraped_pages = []
    total_pages = len(pages_to_scrape)
    logger.info(f"Scraping {total_pages} page(s) with max_workers={MAX_WORKERS}")
    completed_pages = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_page = {
            executor.submit(scrape_with_error_handling, page): page 
            for page in pages_to_scrape
        }
        
        for future in concurrent.futures.as_completed(future_to_page):
            completed_pages += 1
            page_data = future.result()
            if page_data:
                scraped_pages.append(page_data)
            if completed_pages == total_pages or completed_pages % 5 == 0:
                logger.info(f"Scrape progress: {completed_pages}/{total_pages} page(s) completed")
    
    fetch_metrics = merge_count_maps(
        state.get('fetch_metrics'),
        *[page.get('fetch_metrics') for page in scraped_pages],
    )
    extraction_metrics = merge_count_maps(
        state.get('extraction_metrics'),
        *[page.get('extraction_metrics') for page in scraped_pages],
    )
    scraped_count = sum(1 for page in scraped_pages if page.get('fetch_status') == 'ok')
    total_recommendations = sum(
        len(page.get('stock_recommendations', []))
        for page in scraped_pages
        if page.get('fetch_status') == 'ok'
    )

    status_msg = f"Scraped {scraped_count} pages with {total_recommendations} recommendations"
    if skipped_count > 0:
        status_msg += f" (skipped {skipped_count} old/invalid results)"
    blocked_pages = fetch_metrics.get('blocked_terminal_failures', 0) + fetch_metrics.get('blocked_cached_skips', 0)
    if blocked_pages > 0:
        status_msg += f", {blocked_pages} blocked pages"
    if fetch_metrics.get('blocked_challenge_pages', 0) > 0:
        status_msg += f", {fetch_metrics['blocked_challenge_pages']} challenge pages"
    if extraction_metrics.get('low_quality_filtered', 0) > 0:
        status_msg += f", {extraction_metrics['low_quality_filtered']} low-quality filtered"
    if extraction_metrics.get('hallucinated_tickers', 0) > 0:
        status_msg += f", {extraction_metrics['hallucinated_tickers']} hallucinated skipped"
    if extraction_metrics.get('inferred_tickers', 0) > 0:
        status_msg += f", {extraction_metrics['inferred_tickers']} ticker inferred by stock name"
    
    return {
        **state,
        "skipped_from_scraping": skipped_from_scraping,  # Include modified results
        "scraped_pages": scraped_pages,
        "fetch_metrics": fetch_metrics,
        "extraction_metrics": extraction_metrics,
        "status": status_msg
    }

def save_pdf_to_file(webpage_id: int, pdf_bytes: bytes) -> Optional[str]:
    """Save PDF content to file using webpage_id and return the filepath."""
    import os
    
    # Create directory structure: data/db/webpage/{webpage_id}/
    webpage_dir = os.path.join('data', 'db', 'webpage', str(webpage_id))
    os.makedirs(webpage_dir, exist_ok=True)
    
    # Create filename
    filename = f"{webpage_id}.pdf"
    filepath = os.path.join(webpage_dir, filename)
    
    try:
        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)
        
        logger.info(f"Saved PDF to: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Failed to save PDF for webpage_id {webpage_id}: {e}")
        return None

def save_metadata_to_file(webpage_id: int, url: str, webpage_title: str, webpage_date: str) -> Optional[str]:
    """Save metadata to JSON file using webpage_id and return the filepath."""
    import os
    import json
    
    # Create directory structure: data/db/webpage/{webpage_id}/
    webpage_dir = os.path.join('data', 'db', 'webpage', str(webpage_id))
    os.makedirs(webpage_dir, exist_ok=True)
    
    # Create filename
    filename = "metadata.json"
    filepath = os.path.join(webpage_dir, filename)
    
    metadata = {
        'url': url,
        'webpage_title': webpage_title,
        'webpage_date': webpage_date
    }
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved metadata to: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Failed to save metadata for webpage_id {webpage_id}: {e}")
        return None

def save_failed_recommendation_to_file(recommendation: dict, webpage_id: int, error: Exception) -> None:
    """Save a failed recommendation to a JSON error file."""
    import os
    
    error_dir = os.path.join('data', 'stock_recommendation', 'error')
    os.makedirs(error_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    ticker = recommendation.get('ticker', 'unknown').replace('/', '_')
    filename = f"error_{timestamp}_{ticker}.json"
    filepath = os.path.join(error_dir, filename)
    
    error_data = {
        'error': str(error),
        'error_type': type(error).__name__,
        'timestamp': datetime.now().isoformat(),
        'webpage_id': webpage_id,
        'recommendation': recommendation
    }
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(error_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved error details to: {filepath}")
    except Exception as save_error:
        logger.error(f"Failed to save error file: {save_error}")

def save_stock_recommendation_to_db(db: RecommendationsDatabase, recommendation: dict, webpage_id: int) -> tuple[bool, Optional[str]]:
    """Load a single stock recommendation into the database."""
    rec = recommendation
    try:
        def _parse_optional_float(value) -> Optional[float]:
            if value is None:
                return None
            if isinstance(value, str):
                cleaned = value.strip()
                if not cleaned or cleaned.upper() == 'N/A':
                    return None
                cleaned = cleaned.replace(',', '')
                try:
                    return float(cleaned)
                except ValueError:
                    return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        exchange = rec.get('exchange', 'NASDAQ')
        mic = db.get_mic_by_exchange(exchange)

        stock_id = db.upsert_stock(
            isin=None,
            ticker=rec.get('ticker'),
            exchange=exchange,
            stock_name=rec.get('stock_name', ''),
            mic=mic
        )

        # Rating is already numeric 1-5 from LLM/model validation
        rating = rec.get('rating', 3)  # Default to Hold (3)
        # Ensure rating is valid integer 1-5
        if isinstance(rating, str):
            try:
                rating = int(rating)
            except ValueError:
                rating = 3  # Default to Hold if invalid
        if not (1 <= rating <= 5):
            rating = 3  # Default to Hold if out of range

        parsed_price = _parse_optional_float(rec.get('price'))
        parsed_target_price = _parse_optional_float(rec.get('target_price'))
        parsed_fair_price = _parse_optional_float(rec.get('fair_price'))
        if parsed_fair_price is None and parsed_target_price is not None:
            parsed_fair_price = parsed_target_price

        currency_code = (rec.get('currency') or '').strip().upper()
        if not currency_code:
            currency_code = None

        parsed_price_growth_forecast_pct = _parse_optional_float(rec.get('price_growth_forecast_pct'))
        parsed_pe = _parse_optional_float(rec.get('pe'))

        recommendation_data = {
            'ticker': rec.get('ticker'),
            'exchange': rec.get('exchange', 'NASDAQ'),
            'currency_code': currency_code,
            'stock_id': stock_id,
            'isin': None,
            'stock_name': rec.get('stock_name', ''),
            'rating_id': rating,
            'analysis_date': rec.get('analysis_date', str(date.today())),
            'price': parsed_price,
            'fair_price': parsed_fair_price,
            'target_price': parsed_target_price,
            'price_growth_forecast_pct': parsed_price_growth_forecast_pct,
            'pe': parsed_pe,
            'recommendation_text': rec.get('recommendation_text', ''),
            'quality_score': rec.get('quality_score'),
            'quality_description_words': rec.get('quality_description_words'),
            'quality_has_rating': rec.get('quality_has_rating'),
            'quality_reasoning_level': rec.get('quality_reasoning_level'),
            'webpage_id': webpage_id,
            'entry_date': str(date.today())
        }

        db.insert_stock_recommendation(recommendation_data)
        db.upsert_recommended_stock_from_input(stock_id)
        return True, None
    except Exception as e:
        logger.error(f"Failed to save recommendation for {rec.get('ticker', 'unknown')}: {e}")
        save_failed_recommendation_to_file(rec, webpage_id, e)
        return False, str(e)

def load_webpage_to_db(db: RecommendationsDatabase, page: Dict) -> int:
    """Load a single scraped webpage and its stock recommendations into the database."""
    saved_recommendations_count = 0
    try:
        parsed_url = urlparse(page['url'])
        domain = parsed_url.netloc

        website_id = db.upsert_website(domain, is_usable=2)

        webpage_id = db.upsert_webpage(
            url=page['url'],
            date=page.get('webpage_date', str(date.today())),
            title=page.get('webpage_title', ''),
            excerpt=page.get('webpage_excerpt', ''),
            last_seen_date=str(date.today()),
            website_id=website_id,
            is_stock_recommendation=1,
            page_text=page.get('page_text', '')
        )

        # Save PDF content to file system using webpage_id
        pdf_content = page.get('pdf_content')
        if pdf_content:
            save_pdf_to_file(webpage_id, pdf_content)
        
        # Save metadata to file system using webpage_id
        save_metadata_to_file(
            webpage_id=webpage_id,
            url=page['url'],
            webpage_title=page.get('webpage_title', ''),
            webpage_date=page.get('webpage_date', str(date.today()))
        )

        for rec in page.get('stock_recommendations', []):
            success, error_message = save_stock_recommendation_to_db(db, rec, webpage_id)
            rec['db_load_status'] = "OK" if success else "error"
            if not success:
                rec['error_message'] = error_message
            saved_recommendations_count += 1 if success else 0

        return saved_recommendations_count

    except Exception as e:
        logger.error(f"Failed to process page {page.get('url', 'unknown')}: {e}")
        return saved_recommendations_count

def validate_tickers_node(state: WorkflowState) -> WorkflowState:
    """Validate and enrich stock ticker information using lookup_stock()."""
    from services.recommendations import lookup_stock
    from services.financial import get_or_create_stock_info

    db = RecommendationsDatabase()

    def _name_similarity(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        from difflib import SequenceMatcher
        return SequenceMatcher(None, left.lower(), right.lower()).ratio()

    def _exchange_matches_hint(exchange_value: str, exchange_hints: List[str]) -> bool:
        if not exchange_hints:
            return True
        if not exchange_value:
            return False
        exchange_upper = exchange_value.strip().upper()
        for exchange_hint in exchange_hints:
            hint_upper = exchange_hint.strip().upper()
            if exchange_upper == hint_upper or hint_upper in exchange_upper or exchange_upper in hint_upper:
                return True
        return False

    def _infer_exchange_from_currency(currency_code: str) -> List[str]:
        if not currency_code:
            return []

        currency_upper = currency_code.strip().upper()
        currency_to_exchanges = {
            'GBP': ['LSE'],
            'GBX': ['LSE'],
            'EUR': ['PAR', 'XETRA', 'AMS', 'BRU', 'MIL', 'MCE', 'LIS', 'VIE'],
            'DKK': ['CPH'],
            'SEK': ['STO'],
            'NOK': ['OSL'],
            'CHF': ['SIX'],
            'JPY': ['TYO'],
            'HKD': ['HKSE'],
            'AUD': ['ASX'],
            'CAD': ['TSX'],
            'NZD': ['NZX'],
        }
        return currency_to_exchanges.get(currency_upper, [])

    def _normalize_market_cap(raw_value) -> Optional[float]:
        if raw_value is None:
            return None
        try:
            if isinstance(raw_value, str):
                cleaned = raw_value.replace(',', '').strip()
                if not cleaned:
                    return None
                return float(cleaned)
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    def _has_valuation_value(raw_value) -> bool:
        if raw_value is None:
            return False
        if isinstance(raw_value, str):
            normalized = raw_value.strip()
            if not normalized:
                return False
            try:
                float(normalized.replace(',', ''))
                return True
            except ValueError:
                return False
        if isinstance(raw_value, (int, float)):
            return True
        try:
            float(raw_value)
            return True
        except (TypeError, ValueError):
            return False

    def _parse_valuation_float(raw_value) -> Optional[float]:
        if raw_value is None:
            return None
        if isinstance(raw_value, str):
            normalized = raw_value.strip()
            if not normalized:
                return None
            upper_normalized = normalized.upper()
            if upper_normalized in {'N/A', 'NA', 'NULL', 'NONE'}:
                return None
            normalized = normalized.replace(',', '').replace('$', '').replace('%', '')
            try:
                return float(normalized)
            except ValueError:
                return None
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    def _detect_rating_data_inconsistency(rec: Dict) -> Optional[str]:
        recommendation_text = (rec.get('recommendation_text') or '').strip()
        text_lower = recommendation_text.lower()

        rating_raw = rec.get('rating')
        try:
            rating_value = int(rating_raw)
        except (TypeError, ValueError):
            rating_value = None

        if rating_value is not None and 1 <= rating_value <= 5 and recommendation_text:
            import re
            star_match = re.search(r'\b([1-5])\s*[- ]?\s*star\b', recommendation_text, flags=re.IGNORECASE)
            if star_match:
                explicit_star_rating = int(star_match.group(1))
                if explicit_star_rating != rating_value:
                    return (
                        f"Explicit star rating ({explicit_star_rating}) conflicts with extracted rating ({rating_value})"
                    )

        price_value = _parse_valuation_float(rec.get('price'))
        fair_value = _parse_valuation_float(rec.get('fair_price'))
        target_value = _parse_valuation_float(rec.get('target_price'))
        reference_value = fair_value if fair_value is not None else target_value

        has_overvalued_cue = any(keyword in text_lower for keyword in ('overvalued', 'premium'))
        has_undervalued_cue = any(keyword in text_lower for keyword in ('undervalued', 'discount'))

        if rating_value is not None and 1 <= rating_value <= 5:
            if has_overvalued_cue and rating_value >= 4:
                return "Text indicates overvaluation/premium but rating is Buy/Strong Buy"
            if has_undervalued_cue and rating_value <= 2:
                return "Text indicates undervaluation/discount but rating is Sell/Strong Sell"

        if (
            rating_value is not None
            and 1 <= rating_value <= 5
            and price_value is not None
            and reference_value is not None
            and reference_value > 0
        ):
            mispricing = (price_value - reference_value) / reference_value
            if mispricing >= 0.20 and rating_value >= 4:
                return (
                    f"Price is {mispricing * 100:.1f}% above fair/target value but rating is Buy/Strong Buy"
                )
            if mispricing <= -0.20 and rating_value <= 2:
                return (
                    f"Price is {abs(mispricing) * 100:.1f}% below fair/target value but rating is Sell/Strong Sell"
                )

            if has_overvalued_cue and mispricing <= -0.10:
                return (
                    f"Text indicates overvaluation/premium but valuation implies {abs(mispricing) * 100:.1f}% discount"
                )
            if has_undervalued_cue and mispricing >= 0.10:
                return (
                    f"Text indicates undervaluation/discount but valuation implies {mispricing * 100:.1f}% premium"
                )

        return None

    def _is_existing_stock(stock_id: int) -> bool:
        has_recommended_stock = getattr(db, 'has_recommended_stock', None)
        if not callable(has_recommended_stock):
            return False
        try:
            return bool(has_recommended_stock(stock_id))
        except Exception as e:
            logger.warning(f"Unable to determine whether stock {stock_id} already exists in recommended_stock: {e}")
            return False
    
    validated_count = 0
    enriched_count = 0
    invalid_count = 0
    filtered_rating_count = 0
    
    for page in state.get("scraped_pages", []):
        for rec in page.get('stock_recommendations', []):
            ticker = rec.get('ticker', '').strip()
            exchange = rec.get('exchange', '').strip()
            currency = (rec.get('currency', '') or '').strip().upper()

            has_fair_price = _has_valuation_value(rec.get('fair_price'))
            has_target_price = _has_valuation_value(rec.get('target_price'))
            if not has_fair_price and not has_target_price:
                rec['validation_status'] = 'filtered_missing_price'
                rec['validation_error'] = 'Missing both fair_price and target_price'
                invalid_count += 1
                logger.info(f"Filtered {ticker or 'unknown'}: missing both fair_price and target_price")
                continue
            
            if not ticker or ticker == 'N/A':
                rec['validation_status'] = 'invalid'
                rec['validation_error'] = 'Missing ticker'
                invalid_count += 1
                continue

            inconsistency_error = _detect_rating_data_inconsistency(rec)
            if inconsistency_error:
                rec['validation_status'] = 'inconsistent_data'
                rec['validation_error'] = inconsistency_error
                invalid_count += 1
                logger.info(f"Filtered {ticker}: {inconsistency_error}")
                continue
            
            try:
                original_stock_name = rec.get('stock_name', 'N/A')
                exchange_hints = _infer_exchange_from_currency(currency)
                
                if exchange and exchange != 'N/A':
                    stock_info = lookup_stock(ticker, exchange, original_stock_name)
                else:
                    if exchange_hints:
                        stock_info = None
                        for exchange_hint in exchange_hints:
                            stock_info = lookup_stock(ticker, exchange_hint, original_stock_name)
                            if stock_info:
                                break
                        if not stock_info:
                            stock_info = lookup_stock(ticker, stock_name=original_stock_name)
                    else:
                        stock_info = lookup_stock(ticker, stock_name=original_stock_name)

                # Consistency checks: treat provided exchange as a soft hint and retry when
                # resolved stock conflicts with stock_name or currency-inferred exchange.
                if stock_info:
                    resolved_exchange = (stock_info.get('exchange') or '').strip()
                    resolved_name = stock_info.get('stock_name', '')
                    name_similarity = (
                        _name_similarity(original_stock_name, resolved_name)
                        if original_stock_name and original_stock_name != 'N/A'
                        else 1.0
                    )
                    has_name_conflict = (
                        bool(original_stock_name and original_stock_name != 'N/A')
                        and name_similarity < 0.45
                    )
                    has_exchange_conflict = not _exchange_matches_hint(resolved_exchange, exchange_hints)

                    if has_name_conflict or has_exchange_conflict:
                        currency_hint_display = ','.join(exchange_hints) if exchange_hints else 'N/A'
                        logger.info(
                            f"Retrying lookup for {ticker} due to consistency conflict "
                            f"(name_similarity={name_similarity:.2f}, resolved_exchange={resolved_exchange}, "
                            f"currency_hint={currency_hint_display})"
                        )

                        retry_candidates = []
                        if exchange_hints:
                            for exchange_hint in exchange_hints:
                                hinted = lookup_stock(ticker, exchange_hint, original_stock_name)
                                if hinted:
                                    retry_candidates.append(hinted)

                        generic = lookup_stock(ticker, stock_name=original_stock_name)
                        if generic:
                            retry_candidates.append(generic)

                        if retry_candidates:
                            def _candidate_score(candidate: Dict) -> tuple[float, float]:
                                candidate_name = candidate.get('stock_name', '')
                                candidate_exchange = candidate.get('exchange', '')
                                similarity_score = (
                                    _name_similarity(original_stock_name, candidate_name)
                                    if original_stock_name and original_stock_name != 'N/A'
                                    else 1.0
                                )
                                exchange_score = 1.0 if _exchange_matches_hint(candidate_exchange, exchange_hints) else 0.0
                                return (similarity_score, exchange_score)

                            stock_info = max(retry_candidates, key=_candidate_score)
                
                if not stock_info:
                    rec['validation_status'] = 'not_found'
                    rec['validation_error'] = f'Ticker {ticker} not found in database or FMP API'
                    invalid_count += 1
                    continue
                
                original_exchange = rec.get('exchange', 'N/A')

                ticker_upper = ticker.upper()
                try:
                    market_data = get_or_create_stock_info(ticker_upper)
                except Exception as market_error:
                    rec['validation_status'] = 'error'
                    rec['validation_error'] = f"Market data lookup failed: {market_error}"
                    invalid_count += 1
                    logger.error(f"Market data lookup failed for {ticker_upper}: {market_error}")
                    continue
                
                market_cap = _normalize_market_cap(market_data.get('marketCap') if market_data else None)

                if market_cap is None:
                    rec['validation_status'] = 'invalid'
                    rec['validation_error'] = 'Missing marketCap data'
                    invalid_count += 1
                    logger.info(f"Skipping {ticker_upper}: missing marketCap")
                    continue

                if market_cap < MIN_MARKET_CAP:
                    rec['validation_status'] = 'filtered_market_cap'
                    rec['validation_error'] = f"marketCap {market_cap:.0f} below threshold {MIN_MARKET_CAP}"
                    invalid_count += 1
                    logger.info(f"Filtered {ticker_upper}: marketCap {market_cap} < {MIN_MARKET_CAP}")
                    continue

                
                rec['exchange'] = stock_info['exchange']
                rec['stock_name'] = stock_info['stock_name']
                rec['mic'] = stock_info.get('mic')
                rec['isin'] = stock_info.get('isin')
                rec['stock_id'] = stock_info['id']
                rec['marketCap'] = market_cap
                rec['validation_status'] = 'validated'

                rating_raw = rec.get('rating', 3)
                try:
                    rating_value = int(rating_raw)
                except (TypeError, ValueError):
                    rating_value = 3

                is_existing_stock = _is_existing_stock(stock_info['id'])
                if not is_existing_stock and rating_value < MIN_RATING_NEW_STOCK:
                    rec['validation_status'] = 'filtered_rating'
                    rec['validation_error'] = (
                        f"Rating {rating_value} below threshold {MIN_RATING_NEW_STOCK} "
                        "for new stock"
                    )
                    filtered_rating_count += 1
                    invalid_count += 1
                    logger.info(
                        f"Filtered {ticker_upper}: rating {rating_value} < {MIN_RATING_NEW_STOCK} "
                        "for new stock"
                    )
                    continue

                if original_exchange != stock_info['exchange'] or original_stock_name != stock_info['stock_name']:
                    enriched_count += 1

                validated_count += 1
                
            except Exception as e:
                rec['validation_status'] = 'error'
                rec['validation_error'] = str(e)
                invalid_count += 1
                logger.error(f"Error validating ticker {ticker}: {e}")
    
    status_msg = f"Validated {validated_count} tickers"
    if enriched_count > 0:
        status_msg += f", enriched {enriched_count}"
    if filtered_rating_count > 0:
        status_msg += f", {filtered_rating_count} filtered by rating"
    if invalid_count > 0:
        status_msg += f", {invalid_count} invalid/not found"

    return {
        **state,
        "status": status_msg
    }

def deduplicate_stock_recommendations(scraped_pages: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    """
    Deduplicate stock recommendations across all pages by ticker, keeping highest quality version.
    
    Priority for selecting which recommendation to keep:
    1. Higher quality_score wins
    2. If tied, nested page (expanded from parent) wins over parent
    3. If still tied, keep first occurrence
    
    Returns:
        Tuple of (pages_with_deduplicated_recommendations, skipped_recommendations)
        - Pages with only winning recommendations (pages with no winners are excluded)
        - List of skipped recommendations with metadata about why they were skipped
    """
    if not scraped_pages:
        return [], []
    
    ticker_to_best = {}
    skipped_recommendations = []
    
    # Collect all recommendations with their source info
    for page in scraped_pages:
        page_url = page.get('url', '')
        # A page is nested if it has expanded_from_url field
        is_nested = bool(page.get('expanded_from_url'))
        # Main URL is the parent URL if nested, otherwise the current page URL
        main_url = page.get('expanded_from_url', page_url) if is_nested else page_url
        
        for rec in page.get('stock_recommendations', []):
            # Only consider validated recommendations
            if rec.get('validation_status') != 'validated':
                continue
                
            ticker = rec.get('ticker', '').upper().strip()
            if not ticker or ticker == 'N/A':
                continue
                
            exchange = rec.get('exchange', 'NASDAQ').strip()
            quality_score = rec.get('quality_score', 0)
            
            # Create unique key for each ticker+exchange+main_url combination
            # This ensures same ticker from same main page (parent or non-nested) is deduplicated
            key = (ticker, exchange, main_url)
            
            candidate = {
                'recommendation': rec,
                'page': page,
                'quality_score': quality_score,
                'is_nested': is_nested,
                'page_url': page_url
            }
            
            if key not in ticker_to_best:
                ticker_to_best[key] = candidate
            else:
                current = ticker_to_best[key]
                should_replace = False
                replaced_item = None
                
                # Priority 1: Higher quality score wins
                if quality_score > current['quality_score']:
                    should_replace = True
                    replaced_item = current
                    replacement_reason = f"Higher quality score ({quality_score} > {current['quality_score']})"
                elif quality_score == current['quality_score']:
                    # Priority 2: If tied, prefer nested (detailed) page over parent
                    if is_nested and not current['is_nested']:
                        should_replace = True
                        replaced_item = current
                        replacement_reason = f"Nested page preferred (same quality={quality_score})"
                    # Priority 3: If still tied, keep first occurrence (no replacement)
                    else:
                        # Current candidate loses to existing
                        skipped_recommendations.append({
                            **rec,
                            'skipped_reason': f"Lower priority (quality={quality_score}, nested={is_nested} vs existing nested={current['is_nested']})",
                            'skipped_from_url': page_url,
                            'kept_url': current['page_url']
                        })
                        logger.info(f"Skipping {ticker} from {page_url}: same quality, first occurrence wins")
                        continue
                else:
                    # Current candidate has lower quality
                    skipped_recommendations.append({
                        **rec,
                        'skipped_reason': f"Lower quality score ({quality_score} < {current['quality_score']})",
                        'skipped_from_url': page_url,
                        'kept_url': current['page_url']
                    })
                    logger.info(f"Skipping {ticker} from {page_url}: lower quality {quality_score} < {current['quality_score']}")
                    continue
                
                if should_replace:
                    # Add the previously best item to skipped list
                    skipped_recommendations.append({
                        **replaced_item['recommendation'],
                        'skipped_reason': replacement_reason,
                        'skipped_from_url': replaced_item['page_url'],
                        'kept_url': page_url
                    })
                    logger.info(f"Replacing {ticker} recommendation: {replacement_reason}")
                    ticker_to_best[key] = candidate
    
    # Build set of winning recommendations for filtering
    winning_combinations = set()
    for best_item in ticker_to_best.values():
        page_url = best_item['page_url']
        ticker = best_item['recommendation'].get('ticker', '').upper().strip()
        winning_combinations.add((page_url, ticker))
    
    # Rebuild pages with only the winning recommendations
    result_pages = []
    total_removed = 0
    
    for page in scraped_pages:
        page_url = page.get('url', '')
        filtered_recs = []
        
        for rec in page.get('stock_recommendations', []):
            if rec.get('validation_status') != 'validated':
                continue
                
            ticker = rec.get('ticker', '').upper().strip()
            if not ticker or ticker == 'N/A':
                continue
            
            # Check if this specific recommendation is a winner
            rec_key = (page_url, ticker)
            if rec_key in winning_combinations:
                filtered_recs.append(rec)
            else:
                # Log the skipped recommendation
                quality_score = rec.get('quality_score', 0)
                logger.info(f"Skipped duplicate {ticker} from {page_url} "
                           f"(quality={quality_score})")
                total_removed += 1
        
        # Only include pages that have remaining recommendations
        if filtered_recs:
            result_pages.append({**page, 'stock_recommendations': filtered_recs})
    
    total_kept = sum(len(page.get('stock_recommendations', [])) for page in result_pages)
    logger.info(f"Stock recommendation deduplication complete: kept {total_kept} recommendations, removed {len(skipped_recommendations)} duplicates")
    
    return result_pages, skipped_recommendations

def output_node(state: WorkflowState) -> WorkflowState:
    """Write stock recommendations to database with deduplication by quality."""
    db = RecommendationsDatabase()
    
    # Deduplicate stock recommendations across all pages by ticker quality
    deduplicated_pages, skipped_recommendations = deduplicate_stock_recommendations(
        state.get("scraped_pages", [])
    )
    
    saved_count = 0
    
    for page in deduplicated_pages:
        valid_recommendations = [
            rec for rec in page.get('stock_recommendations', [])
            if rec.get('validation_status') == 'validated'
        ]
        
        if valid_recommendations:
            page_copy = {**page, 'stock_recommendations': valid_recommendations}
            saved_count += load_webpage_to_db(db, page_copy)

    skipped_count = len(skipped_recommendations)
    fetch_metrics = state.get('fetch_metrics') or {}
    extraction_metrics = state.get('extraction_metrics') or {}
    
    status_msg = f"Saved {saved_count} deduplicated stock recommendations"
    if skipped_count > 0:
        status_msg += f" (skipped {skipped_count} duplicate recommendations)"
    blocked_pages = fetch_metrics.get('blocked_terminal_failures', 0) + fetch_metrics.get('blocked_cached_skips', 0)
    if blocked_pages > 0:
        status_msg += f", {blocked_pages} blocked pages"
    if fetch_metrics.get('blocked_challenge_pages', 0) > 0:
        status_msg += f", {fetch_metrics['blocked_challenge_pages']} challenge pages"
    if extraction_metrics.get('low_quality_filtered', 0) > 0:
        status_msg += f", {extraction_metrics['low_quality_filtered']} low-quality filtered"
    if extraction_metrics.get('hallucinated_tickers', 0) > 0:
        status_msg += f", {extraction_metrics['hallucinated_tickers']} hallucinated skipped"
    
    return {
        **state,
        "deduplicated_pages": deduplicated_pages,
        "skipped_recommendations": skipped_recommendations,
        "status": status_msg
    }

def create_workflow():
    """Create and compile the stock search workflow."""
    workflow = StateGraph(WorkflowState)
    
    workflow.add_node("search", search_node)
    workflow.add_node("filter_duplicate", filter_duplicate_node)
    workflow.add_node("filter_known_bad", filter_known_bad_node)
    workflow.add_node("retrieve_nested_pages", retrieve_nested_pages)
    workflow.add_node("analyze_search_result", analyze_search_result)
    workflow.add_node("scrape", scrape_node)
    workflow.add_node("validate_tickers", validate_tickers_node)
    workflow.add_node("output", output_node)
    
    workflow.set_entry_point("search")
    workflow.add_edge("search", "filter_duplicate")
    workflow.add_edge("filter_duplicate", "filter_known_bad")
    workflow.add_edge("filter_known_bad", "retrieve_nested_pages")
    workflow.add_edge("retrieve_nested_pages", "analyze_search_result")
    workflow.add_edge("analyze_search_result", "scrape")
    workflow.add_edge("scrape", "validate_tickers")
    workflow.add_edge("validate_tickers", "output")
    workflow.add_edge("output", END)
    
    return workflow.compile()
