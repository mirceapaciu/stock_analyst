"""LangGraph workflow for searching and analyzing undervalued stocks."""

from typing import List, Dict, TypedDict, Optional
from datetime import datetime, date, timedelta
import json
import logging
import asyncio
from urllib.parse import urlparse

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

from config import MAX_RESULT_AGE_DAYS, GOOGLE_API_KEY, GOOGLE_CSE_ID, MAX_SEARCH_RESULTS, SEARCH_QUERIES, MAX_WORKERS, MIN_MARKET_CAP
from repositories.recommendations_db import RecommendationsDatabase
from recommendations.prompts import get_extract_stocks_prompt, get_analyze_search_result_prompt, get_analyze_search_result_with_date_prompt

logger = logging.getLogger(__name__)

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
    search_results: List[Dict]  # Results from Google search
    filtered_search_results: List[Dict]  # After duplicate and bad domain filtering
    expanded_search_results: List[Dict]  # Includes filtered_search_results + nested links from those pages
    scraped_pages: List[Dict]  # Scraped pages with their stock recommendations
    deduplicated_pages: List[Dict]  # Pages after stock recommendation deduplication (pages may be removed if all recs are duplicates)
    skipped_recommendations: List[Dict]  # Stock recommendations skipped during deduplication
    status: str
    error: str
    process_name: Optional[str]  # Process name for progress tracking


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


def search_node(state: WorkflowState) -> WorkflowState:
    """Search for undervalued stocks using Google Custom Search API."""
    update_progress_if_available(state, 30)
    try:
        if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
            return {
                **state,
                "search_results": [],
                "status": "Search failed: GOOGLE_API_KEY or GOOGLE_CSE_ID not set",
                "error": "Missing Google API credentials"
            }
        
        service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
        all_results = []
        date_restrict = f"d{MAX_RESULT_AGE_DAYS}"
        
        for query in SEARCH_QUERIES[:1]:
            try:
                result = service.cse().list(
                    q=query,
                    cx=GOOGLE_CSE_ID,
                    num=min(MAX_SEARCH_RESULTS, 10),
                    dateRestrict=date_restrict,
                    sort='date'
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
        
        return {
            **state,
            "search_results": all_results,
            "status": f"Found {len(all_results)} results (filtered by {MAX_RESULT_AGE_DAYS} days)",
            "error": ""
        }

    except Exception as e:
        return {
            **state,
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
    
    for result in search_results:
        url = result.get('href', '')
        try:
            domain = urlparse(url).netloc.replace('www.', '')
            is_unusable = any(domain.endswith(unusable) for unusable in unusable_domains)
            if not is_unusable:
                filtered.append(result)
            else:
                bad_removed += 1
        except Exception:
            filtered.append(result)
    
    return {
        **state,
        "filtered_search_results": filtered,
        "status": f"Removed {bad_removed} from unusable domains, {len(filtered)} results remaining"
    }


def analyze_search_result(state: WorkflowState) -> WorkflowState:
    """Analyze each search result with an LLM to detect if it contains stock picks."""
    update_progress_if_available(state, 55)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    async def analyze_single_result(r: Dict) -> Dict:
        """Analyze a single search result asynchronously."""
        title = r.get("title", "")
        href = r.get("href", "")
        body = r.get("body", "")
        existing_date = r.get("date", "")
        
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
                contains = any(w.lower() in (title + " " + body).lower() for w in ["undervalued", "undervalued stocks", "cheap stocks", "value picks"]) 
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
        updated["contains_stocks"] = contains
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


def fetch_webpage_content(url: str, headers: Dict, use_browser: bool = False) -> tuple[str, BeautifulSoup]:
    """Fetch webpage and return HTML content and parsed soup."""
    if use_browser:
        from playwright.async_api import async_playwright
        
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
                
                try:
                    # Navigate and wait for network to be mostly idle
                    await page.goto(url, wait_until='networkidle', timeout=45000)
                    
                    # Additional wait for dynamic content
                    await page.wait_for_timeout(5000)
                    
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
                    
                    await page.wait_for_timeout(2000)
                    html_content = await page.content()
                    return html_content
                finally:
                    await browser.close()
        
        # Run async Playwright
        html_content = asyncio.run(run_playwright_async())
        
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
        
        soup = BeautifulSoup(response.content, 'html.parser')
    
    for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
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
    
    return page_text, soup

def validate_ticker_in_text(ticker: str, text: str) -> bool:
    """Verify that ticker symbol actually appears in the text."""
    import re
    pattern = r'\b' + re.escape(ticker.upper()) + r'\b'
    return bool(re.search(pattern, text.upper()))


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
    page_date: datetime
) -> List[Dict]:
    """Extract stock recommendations from page content using LLM."""
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    structured_llm = llm.with_structured_output(StockRecommendationsResponse)
    
    extraction_prompt = get_extract_stocks_prompt(url, title, page_text)

    try:
        llm_response = structured_llm.invoke([HumanMessage(content=extraction_prompt)])
    except Exception as e:
        logger.error(f"Error extracting recommendations from {url}: {e}")
        return []
    
    analysis_date = llm_response.analysis_date
    if not analysis_date or analysis_date == "N/A":
        analysis_date = page_date.strftime('%Y-%m-%d')
    
    if analysis_date > datetime.now().strftime('%Y-%m-%d'):
        analysis_date = datetime.now().strftime('%Y-%m-%d')
   
    if not llm_response.tickers:
        return []
    
    recommendations = []
    for ticker_obj in llm_response.tickers:
        if not ticker_obj.ticker or ticker_obj.ticker == 'N/A':
            continue

        if validate_ticker_in_text(ticker_obj.ticker, page_text):
            # Calculate quality score from LLM-extracted quality indicators
            quality_score = calculate_recommendation_quality_score(ticker_obj.quality)
            
            recommendation = {
                'ticker': ticker_obj.ticker,
                'exchange': ticker_obj.exchange,
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
            
            if quality_score < 40:
                logger.warning(f"Low quality recommendation for {ticker_obj.ticker}: score={quality_score}")
            
            recommendations.append(recommendation)
        else:
            logger.warning(f"Hallucinated ticker {ticker_obj.ticker} not found in text, skipping")
            
    return recommendations

def scrape_single_page(search_result: Dict, headers: Dict, db: RecommendationsDatabase) -> Dict:
    """Scrape a single web page and extract stock recommendation information using LLM."""
    url = search_result.get("href", "")
    if not url:
        return None
    
    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    # use_browser = db.needs_browser_rendering(domain)
    use_browser = True
    
    try:
        page_text, soup = fetch_webpage_content(url, headers, use_browser=use_browser)
    except requests.RequestException as e:
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 403:
            if not use_browser:
                logger.warning(f"403 Forbidden for {url}, retrying with browser rendering")
                try:
                    page_text, soup = fetch_webpage_content(url, headers, use_browser=True)
                    logger.info(f"Browser rendering successful for {domain}, updating database")
                    db.upsert_website(domain, is_usable=1, requires_browser=1)
                except Exception as browser_error:
                    logger.error(f"Browser rendering also failed for {url}: {browser_error}")
                    logger.warning(f"Marking domain {domain} as unusable")
                    db.upsert_website(domain, is_usable=0)
                    return None
            else:
                logger.warning(f"403 Forbidden even with browser for {url}, marking domain {domain} as unusable")
                db.upsert_website(domain, is_usable=0)
                return None
        else:
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

        stock_recommendations = extract_stock_recommendations_with_llm(
            url=url,
            title=webpage_title,
            page_text=page_text,
            page_date=page_date
        )

        result = {
            'url': url,
            'webpage_title': webpage_title,
            'webpage_date': webpage_date,
            'page_text': page_text,
            'stock_recommendations': stock_recommendations
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
            'stock_recommendations': []
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
            'stock_recommendations': []
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
                page_text, soup = fetch_webpage_content(parent_url, headers, use_browser=use_browser)
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
                    nested_result = {
                        'title': link_text,
                        'href': nested_url,
                        'body': '',
                        'date': None,
                        'expanded_from_url': parent_url,
                        'pagemap': {}
                    }
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
        'Accept-Encoding': 'gzip, deflate, br',
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
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_page = {
            executor.submit(scrape_with_error_handling, page): page 
            for page in pages_to_scrape
        }
        
        for future in concurrent.futures.as_completed(future_to_page):
            page_data = future.result()
            if page_data:
                scraped_pages.append(page_data)
    
    scraped_count = len(scraped_pages)
    total_recommendations = sum(len(page.get('stock_recommendations', [])) for page in scraped_pages)
    
    status_msg = f"Scraped {scraped_count} pages with {total_recommendations} recommendations"
    if skipped_count > 0:
        status_msg += f" (skipped {skipped_count} old/invalid results)"
    
    return {
        **state,
        "skipped_from_scraping": skipped_from_scraping,  # Include modified results
        "scraped_pages": scraped_pages,
        "status": status_msg
    }

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

        recommendation_data = {
            'ticker': rec.get('ticker'),
            'exchange': rec.get('exchange', 'NASDAQ'),
            'stock_id': stock_id,
            'isin': None,
            'stock_name': rec.get('stock_name', ''),
            'rating_id': rating,
            'analysis_date': rec.get('analysis_date', str(date.today())),
            'price': float(rec.get('price', 0)) if rec.get('price') and rec.get('price') != 'N/A' else None,
            'fair_price': float(rec.get('fair_price', 0)) if rec.get('fair_price') and rec.get('fair_price') != 'N/A' else None,
            'target_price': float(rec.get('target_price', 0)) if rec.get('target_price') and rec.get('target_price') != 'N/A' else None,
            'price_growth_forecast_pct': float(rec.get('price_growth_forecast_pct', 0)) if rec.get('price_growth_forecast_pct') and rec.get('price_growth_forecast_pct') != 'N/A' else None,
            'pe': float(rec.get('pe', 0)) if rec.get('pe') and rec.get('pe') != 'N/A' else None,
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
    
    validated_count = 0
    enriched_count = 0
    invalid_count = 0
    
    for page in state.get("scraped_pages", []):
        for rec in page.get('stock_recommendations', []):
            ticker = rec.get('ticker', '').strip()
            exchange = rec.get('exchange', '').strip()
            
            if not ticker or ticker == 'N/A':
                rec['validation_status'] = 'invalid'
                rec['validation_error'] = 'Missing ticker'
                invalid_count += 1
                continue
            
            try:
                if exchange and exchange != 'N/A':
                    lookup_results = lookup_stock(ticker, exchange)
                else:
                    lookup_results = lookup_stock(ticker)
                
                if not lookup_results:
                    rec['validation_status'] = 'not_found'
                    rec['validation_error'] = f'Ticker {ticker} not found in database or FMP API'
                    invalid_count += 1
                    continue
                
                original_stock_name = rec.get('stock_name', 'N/A')
                
                if len(lookup_results) == 1:
                    stock_info = lookup_results[0]
                else:
                    from difflib import SequenceMatcher
                    
                    best_match = lookup_results[0]
                    best_similarity = 0.0
                    
                    if original_stock_name and original_stock_name != 'N/A':
                        for result in lookup_results:
                            result_name = result.get('stock_name', '')
                            similarity = SequenceMatcher(None, 
                                                        original_stock_name.lower(), 
                                                        result_name.lower()).ratio()
                            if similarity > best_similarity:
                                best_similarity = similarity
                                best_match = result
                    
                    stock_info = best_match
                
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
    
    status_msg = f"Saved {saved_count} deduplicated stock recommendations"
    if skipped_count > 0:
        status_msg += f" (skipped {skipped_count} duplicate recommendations)"
    
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
