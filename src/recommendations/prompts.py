"""Prompt templates for LLM interactions in the stock analysis workflow."""


def get_extract_stocks_prompt(url: str, title: str, page_text: str) -> str:
    return f"""Extract stock recommendations from this article.
IMPORTANT RULES:
- ONLY extract stocks that are EXPLICITLY mentioned in the content
- If NO stocks are mentioned, return an empty tickers array
- DO NOT invent or hallucinate any stock information
- Extract only stocks that are explicitly recommended as undervalued or good buys
- Do not extract stocks that are merely mentioned without a clear recommendation
- Extract only values that are explicitly stated in the content

RATING EXTRACTION RULES (PRIORITY ORDER):
1. FIRST PRIORITY - Look for "Morningstar Rating" field with star symbols (★ or \u2605):
   * Count the stars EXACTLY - this is the official rating
   * Return the count as a NUMBER: 5 stars = 5, 4 stars = 4, 3 stars = 3, 2 stars = 2, 1 star = 1
   * IMPORTANT: Use this numeric rating even if other language in the article sounds positive or negative

2. SECOND PRIORITY - If no Morningstar stars found, look for explicit rating text:
   * Convert text to numbers: "Strong Buy" = 5, "Buy" = 4, "Hold" = 3, "Sell" = 2, "Strong Sell" = 1

3. FALLBACK ONLY - If neither stars nor explicit rating found, infer from sentiment:
   * 5 - Very positive language, words like "excellent opportunity", "highly undervalued"
   * 4 - Positive language, words like "undervalued", "attractive", "good opportunity"
   * 3 - Neutral or mixed signals, or when only factual information is provided
   * 2 - Negative language, concerns about valuation or performance
   * 1 - Very negative language
   * Default to 3 if sentiment is unclear

CRITICAL: Always use the Morningstar star count if present, regardless of other positive/negative language in the article.

URL: {url}
Title: {title}
Content: {page_text}

Extract these fields:
- analysis_date: Date of analysis (YYYY-MM-DD format). If not found in content, return "N/A".
- tickers: Array of stock recommendations, where each item contains:
    - ticker: Stock ticker symbol (e.g., AAPL)
    - exchange: Exchange code (e.g., NASDAQ, NYSE, or "N/A" if unknown)
    - stock_name: Company name
    - rating: Recommendation rating as a NUMBER from 1 to 5, where 1=Strong Sell, 2=Sell, 3=Hold, 4=Buy, 5=Strong Buy. Follow priority order above.
    - price: Current stock price (number only, or "N/A")
    - fair_price: Fair/intrinsic value estimate (number only, or "N/A")
    - target_price: Price target (number only, or "N/A")
    - price_growth_forecast_pct: Expected growth percentage (number only, or "N/A")
    - pe: P/E ratio (number only, or "N/A")
    - recommendation_text: Brief summary of why this stock is recommended (max 500 chars)
    - quality: Quality assessment object containing:
        * description_word_count: Count the words in the stock description/analysis text (integer)
        * has_explicit_rating: Does the text contain an explicit rating (Strong Buy/Buy/Hold/Sell/Strong Sell or star rating)? (true/false)
        * reasoning_detail_level: How detailed is the reasoning? Use integer 0-3:
            - 0: No reasoning provided
            - 1: Brief (1-2 sentence explanation)
            - 2: Moderate (multiple points or a paragraph)
            - 3: Detailed (comprehensive analysis with multiple arguments)"""


def get_analyze_search_result_prompt(title: str, href: str, body: str) -> str:
    """Prompt for analyzing if search result contains stock recommendations."""
    return f"""Examine this search result and answer in JSON with key 'contains_stocks' (true/false).

Title: {title}
URL: {href}
Snippet: {body}

Return ONLY a valid JSON object with no additional text. Example: {{"contains_stocks": true}}"""


def get_analyze_search_result_with_date_prompt(title: str, href: str, body: str) -> str:
    """Prompt for analyzing search result and extracting date."""
    return f"""Examine this search result and answer in JSON with keys 'contains_stocks' (true/false) and 'excerpt_date' (YYYY-MM-DD string or null).

Date extraction rules:
1. If you find a complete date (e.g., 'March 15, 2025'), use that exact date in YYYY-MM-DD format.
2. If you find only a month and year (e.g., 'March 2025', 'For March 2025'), use the last day of that month (2025-03-31).
3. If you find a quarter and year (e.g., 'Q2 2025', '2nd quarter 2025'), use the last day of that quarter (2025-06-30):
   - Q1: March 31 (YYYY-03-31)
   - Q2: June 30 (YYYY-06-30)
   - Q3: September 30 (YYYY-09-30)
   - Q4: December 31 (YYYY-12-31)
4. If you find only the year without month/day, return the last day of that year (YYYY-12-31).
5. If no date is found, return null.

Title: {title}
URL: {href}
Snippet: {body}

Return ONLY a valid JSON object with no additional text. Example: {{"contains_stocks": true, "excerpt_date": "2025-03-01"}}"""
