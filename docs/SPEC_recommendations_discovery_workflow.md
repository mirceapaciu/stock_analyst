# Specification: Recommendations Discovery Workflow
---

## 1. Purpose

The Recommendations Discovery Workflow is an automated LangGraph pipeline that discovers, scrapes, and stores analyst stock recommendations from reputable financial websites. It runs on a scheduled or on-demand basis and populates the `input_stock_recommendation` table in the recommendations SQLite database, which drives the application's "recommended stocks" list.

---

## 2. Entry Points

| Script | Purpose |
|--------|---------|
| `scripts/run_recommendations_workflow.py` | Standalone CLI runner (no Streamlit) |
| `src/ui/` (Streamlit) | Triggered from the UI via background process |

The workflow is built with `create_workflow()` which returns a compiled LangGraph `StateGraph`. It is invoked via `workflow.invoke(initial_state)`.

---

## 3. Configuration

All configuration lives in `src/config.py` and environment variables (`.env` / AWS SSM).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `GOOGLE_API_KEY` | — | Google Custom Search API key |
| `GOOGLE_CSE_ID` | — | Custom Search Engine ID |
| `OPENAI_API_KEY` | — | OpenAI key (GPT-4o-mini) |
| `FMP_API_KEY` | — | Financial Modeling Prep API key |
| `FINNHUB_API_KEY` | — | Finnhub API key |
| `MAX_SEARCH_RESULTS` | `10` | Max results per query (Google CSE cap) |
| `MAX_RESULT_AGE_DAYS` | `20` | Reject pages older than N days |
| `MAX_WORKERS` | `2` | Thread-pool concurrency for scraping |
| `MIN_MARKET_CAP` | `1,000,000,000` | Min market cap ($1B) for recommendations |
| `SEARCH_QUERIES` | see below | Query templates |
| `REPUTABLE_SITES` | see below | Allowed financial domains |

**Search query templates** (rendered per-site, per-run):
```
"undervalued stocks site:{site}"
"best value stocks site:{site}"
"stocks to buy site:{site}"
```

**Reputable sites:**
```
reuters.com, morningstar.com, finance.yahoo.com,
fool.com, zacks.com, seekingalpha.com
```

---

## 4. Workflow State

The LangGraph state object (`WorkflowState`) is a `TypedDict` that threads all data between nodes:

| Field | Type | Description |
|-------|------|-------------|
| `query` | `str` | Unused query string (legacy) |
| `search_results` | `List[Dict]` | Raw results from Google CSE |
| `filtered_search_results` | `List[Dict]` | After duplicate + bad-domain filtering |
| `expanded_search_results` | `List[Dict]` | Filtered + nested links discovered |
| `scraped_pages` | `List[Dict]` | Scraped page data + extracted recommendations |
| `deduplicated_pages` | `List[Dict]` | Pages after cross-page deduplication |
| `skipped_recommendations` | `List[Dict]` | Recommendations dropped during deduplication |
| `status` | `str` | Human-readable status message from last node |
| `error` | `str` | Error message if a node failed |
| `process_name` | `Optional[str]` | DB process name for progress tracking |

---

## 5. Node Pipeline

```
search
  └─► filter_duplicate
        └─► filter_known_bad
              └─► retrieve_nested_pages
                    └─► analyze_search_result
                          └─► scrape
                                └─► validate_tickers
                                      └─► output
                                            └─► END
```

Each node updates `state["status"]` and calls `update_progress_if_available()` to record percentage in the `process` DB table.

---

## 6. Node Specifications

### 6.1 `search_node` (progress: 30%)

**Purpose:** Query Google Custom Search API to collect candidate article URLs.

**Inputs:** None (reads `SEARCH_QUERIES` × `REPUTABLE_SITES` from config)

**Process:**
1. Build a cross-product of every query template × every reputable site.
2. For each combined query, call the Google CSE API (`customsearch.cse().list`) with:
   - `num = min(MAX_SEARCH_RESULTS, 10)`
   - `dateRestrict = "d{MAX_RESULT_AGE_DAYS}"`
   - `sort = "date"`
3. For each result, attempt to extract a normalized publication date from OpenGraph / meta tags in this priority order:
   `og:article:published_time` → `article:published_time` → `sailthru.date` → `og:article:modified_time` → `parsely-pub-date` → `datePublished` → `publishdate` → `date` → `last-modified` → `dc.date` → `pubdate` → `article:published`
4. Normalize date to `YYYY-MM-DD`.

**Outputs:** `state["search_results"]` — list of dicts:
```python
{
  "title": str,
  "href": str,       # page URL
  "body": str,       # search snippet
  "date": str|None,  # normalized YYYY-MM-DD or None
  "pagemap": dict
}
```

**Error handling:** Individual query failures are caught and logged; the node always returns the accumulated results.

---

### 6.2 `filter_duplicate_node` (progress: 35%)

**Purpose:** Skip URLs already present in the `webpage` table (same URL + date combination).

**Process:**
1. For each result in `search_results`, call `db.webpage_exists(url, date)`.
2. Drop the result if it already exists.

**Outputs:** Updates `state["search_results"]` in place (reduces the list).

---

### 6.3 `filter_known_bad_node` (progress: 40%)

**Purpose:** Remove URLs from domains marked as unusable in the `website` table (`is_usable = 0`).

**Process:**
1. Fetch all unusable domains via `db.get_unusable_domains()`.
2. For each result, extract the domain (`netloc`, strip `www.`).
3. Drop results whose domain ends-with any unusable domain.

**Outputs:** `state["filtered_search_results"]`

---

### 6.4 `retrieve_nested_pages` (progress: 45%)

**Purpose:** Expand the candidate list by following links from the top-level pages to individual stock-specific subpages.

**Process:**
1. Fetch each URL in `filtered_search_results` (respects `needs_browser_rendering` flag per domain).
2. Extract all `<a href>` links with anchor text ≥ 10 characters.
3. Keep only links whose anchor text contains any of: `stock`, `quote`, `analysis`, `fair value`, `undervalued`, `recommendation`, `buy`, `sell`, `target price`, `estimate`.
4. Skip duplicates (already in the expanded list or equal to the parent URL).
5. Each new link is stored as:
   ```python
   {
     "title": link_text,
     "href": absolute_url,
     "body": "",
     "date": None,
     "expanded_from_url": parent_url,
     "pagemap": {}
   }
   ```

**Outputs:** `state["expanded_search_results"]` = original filtered results + nested links

---

### 6.5 `analyze_search_result` (progress: 55%)

**Purpose:** Use an LLM to triage which pages actually contain stock picks, saving scraping time for irrelevant pages. Also extract a publication date when absent.

**Model:** `gpt-4o-mini`, temperature 0

**Process:** For every item in `expanded_search_results` (run in parallel via `asyncio.gather`):

- **If `date` is already known:** Send a single-key JSON prompt asking only `contains_stocks` (true/false).
- **If `date` is unknown:** Send a two-key JSON prompt asking `contains_stocks` and `excerpt_date`.
  - Date extraction rules (in priority order):
    1. Complete date → use verbatim (YYYY-MM-DD).
    2. Month + year only → use last day of the month.
    3. Quarter + year → use last day of the quarter.
    4. Year only → use December 31 of that year.
    5. No date → `null`.

**Fallback** (LLM parse failure): Checks title + snippet for keywords (`undervalued`, `cheap stocks`, `value picks`).

**Outputs:** Each result gains two new fields:
- `contains_stocks: bool`
- `excerpt_date: str|None` (YYYY-MM-DD)

---

### 6.6 `scrape_node` (progress: 65%)

**Purpose:** Fetch and extract full article content, then run LLM extraction of stock recommendations for each page flagged as `contains_stocks = True`.

**Pre-filtering (before scraping):**
- Skip pages where `contains_stocks = False`.
- Skip pages where `excerpt_date` is missing or fails to parse.
- Skip pages where `excerpt_date < now - MAX_RESULT_AGE_DAYS`.
- Limit to first 100 results.

**Parallel execution:** Uses `ThreadPoolExecutor(max_workers=MAX_WORKERS)`.

**Per-page scraping (`scrape_single_page`):**

1. **Browser mode** (`use_browser=True`, currently hardcoded):
   - Launches headless Chromium via Playwright.
   - Applies anti-bot mitigations: removes `navigator.webdriver`, spoofs `navigator.plugins`, `navigator.languages`, `window.chrome`.
   - Waits 8 seconds for dynamic content.
   - Handles cookie consent banners (multi-language selectors).
   - Clicks "read more / show more / expand" controls (up to 5 rounds, max 12 elements per pattern).
   - Hides fixed/sticky ad overlays and high-z-index elements.
   - Switches to print media mode.
   - Generates a PDF (`A4`, print background, 20px margins).
   - Falls back to simple `requests.get` if browser mode is disabled.

2. **Content extraction:**
   - Removes `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>`, `<aside>` tags.
   - Prefers `<main>`, `<article>` or common `class` / `id` content selectors.
   - Appends up to 50 relevant `<a href>` links with anchor text as a `RELATED LINKS` section.
   - Truncates to 10,000 characters (9,000 + links section).

3. **Date resolution** (per page): Meta tags → search result date → `excerpt_date` → `datetime.now()`.

4. **LLM extraction** (`extract_stock_recommendations_with_llm`):
   - Model: `gpt-4o-mini`, temperature 0, structured output via `StockRecommendationsResponse` Pydantic schema.
   - Prompt: `get_extract_stocks_prompt(url, title, page_text)`.
   - **Rating extraction priority:**
     1. Morningstar star symbols (★★★★★ → 5, …, ★ → 1) — highest priority.
     2. Explicit text rating ("Strong Buy" → 5, "Buy" → 4, "Hold" → 3, "Sell" → 2, "Strong Sell" → 1).
     3. Sentiment inference (fallback, default 3).
   - **Anti-hallucination guard:** Each extracted ticker must appear as a whole word in the raw page text (`\bTICKER\b` regex). Tickers failing this check are discarded.
   - **Quality scoring** (0–100 points):
     | Component | Scoring |
     |-----------|---------|
     | Description word count | +10 pts per 50 words, max 30 pts |
     | Explicit rating present | +25 pts |
     | Reasoning detail level (0–3) | level × 10 pts, max 30 pts |
   - Recommendations with `quality_score < 40` are logged as warnings but not discarded.
   - `analysis_date` capped at `datetime.now()` if the LLM returns a future date.

5. **403 handling:** If simple HTTP returns 403 and browser mode was off, retries with browser. Marks domain as `is_usable=1` + `requires_browser=1` on success, or `is_usable=0` on failure.

**Per-page output dict:**
```python
{
  "url": str,
  "webpage_title": str,
  "webpage_date": str,          # YYYY-MM-DD
  "page_text": str,
  "pdf_content": bytes|None,
  "stock_recommendations": List[Dict],
  "expanded_from_url": str      # optional, for nested pages
}
```

**Per-recommendation dict fields:**

| Field | Type | Notes |
|-------|------|-------|
| `ticker` | str | Validated against page text |
| `exchange` | str | "N/A" if not found |
| `currency` | str | "N/A" if not found |
| `stock_name` | str | |
| `rating` | int | 1–5 |
| `analysis_date` | str | YYYY-MM-DD |
| `price` | str | Numeric string or "N/A" |
| `fair_price` | str | Numeric string or "N/A" |
| `target_price` | str | Numeric string or "N/A" |
| `price_growth_forecast_pct` | str | Numeric string or "N/A" |
| `pe` | str | Numeric string or "N/A" |
| `recommendation_text` | str | ≤ 500 chars |
| `quality_score` | int | 0–100 |
| `quality_description_words` | int | |
| `quality_has_rating` | bool | |
| `quality_reasoning_level` | int | 0–3 |

---

### 6.7 `validate_tickers_node`

**Purpose:** Validate each extracted ticker against a known stock database, enrich metadata, and apply business filters.

**Validation checks (in order):**

1. **Valuation data required:** Both `fair_price` and `target_price` must be absent to filter — i.e., at least one must be present. If both are missing → `filtered_missing_price`.

2. **Ticker present:** Non-empty, non-"N/A" ticker symbol required.

3. **Rating/data consistency checks:**
   - If recommendation text explicitly states an N-star rating (e.g., "3-star") that differs from the extracted rating → `inconsistent_data`.
   - If text contains "overvalued" / "premium" but rating ≥ 4 (Buy/Strong Buy) → `inconsistent_data`.
   - If text contains "undervalued" / "discount" but rating ≤ 2 (Sell/Strong Sell) → `inconsistent_data`.
   - If price is ≥ 20% above fair/target value but rating ≥ 4 → `inconsistent_data`.
   - If price is ≥ 20% below fair/target value but rating ≤ 2 → `inconsistent_data`.

4. **Stock lookup** (`services.recommendations.lookup_stock`):
   - Looks up the ticker in the `stock` table of the recommendations DB.
   - If not found, calls the Financial Modeling Prep (FMP) API (`search-symbol` endpoint).
   - When the extracted `exchange` is missing ("N/A"), infers exchange hints from `currency`:
     - `GBP/GBX` → LSE, `EUR` → PAR/XETRA/AMS…, `JPY` → TYO, etc.
   - If the resolved stock name differs significantly (fuzzy similarity < 0.45) or the resolved exchange conflicts with currency-inferred exchange hints, retries with alternative lookups and selects the best candidate.
   - If still not found → `not_found`.

5. **Market data** (`services.financial.get_or_create_stock_info`):
   - Fetches market data from yfinance (cached in `stocks.duckdb`).
   - If `marketCap` is missing → `invalid`.
   - If `marketCap < MIN_MARKET_CAP` ($1B) → `filtered_market_cap`.

6. **Enrichment on success:** Updates `rec` in place with:
   - `exchange`, `stock_name`, `mic`, `isin`, `stock_id`, `marketCap`, `validation_status = "validated"`

**Validation statuses:**

| Status | Meaning |
|--------|---------|
| `validated` | Passed all checks, enriched with DB/market data |
| `filtered_missing_price` | Both fair_price and target_price are absent |
| `invalid` | Missing ticker or missing marketCap |
| `not_found` | Ticker unknown in DB and FMP API |
| `filtered_market_cap` | Market cap below $1B threshold |
| `inconsistent_data` | Rating/text/valuation contradiction detected |
| `error` | Unexpected exception during lookup |

---

### 6.8 `output_node`

**Purpose:** Deduplicate validated recommendations across all pages and persist to the database.

**Deduplication logic (`deduplicate_stock_recommendations`):**

- Deduplication key: `(ticker, exchange, main_url)` where `main_url` is the parent URL for nested pages, or the page URL itself.
- Selection priority (tie-breaking):
  1. Higher `quality_score` wins.
  2. Tie → nested page beats the parent page.
  3. Still tied → first occurrence wins.
- Losing entries are recorded in `skipped_recommendations` with reason.

**Persistence (`load_webpage_to_db` per page):**

1. Upsert `website` record (domain → `is_usable=2`).
2. Upsert `webpage` record (URL + date, stores `page_text`, marks `is_stock_recommendation=1`).
3. Save PDF to `data/db/webpage/{webpage_id}/{webpage_id}.pdf`.
4. Save metadata JSON to `data/db/webpage/{webpage_id}/metadata.json`.
5. For each validated recommendation:
   - Upsert `stock` record (ticker, exchange, name, MIC).
   - Insert `input_stock_recommendation` record (all valuation fields, quality fields, `webpage_id`, `entry_date`).
   - Call `upsert_recommended_stock_from_input(stock_id)` to update the aggregated `recommended_stock` view.
   - On failure: write error JSON to `data/stock_recommendation/error/`.

**Outputs:** `state["deduplicated_pages"]`, `state["skipped_recommendations"]`, updated `state["status"]`.

---

## 7. Database Schema (Recommendations DB — SQLite)

### Core tables relevant to this workflow

```
market          – ISO MIC exchange codes and currency
website         – tracked domains; is_usable={0=bad,1=ok,2=active}, requires_browser flag
webpage         – scraped page record; UNIQUE(url, date)
stock           – ticker + exchange; UNIQUE(ticker, exchange)
ref_stock_rating– reference 1–5 ratings (Strong Sell → Strong Buy)
input_stock_recommendation – one row per ticker × webpage
recommended_stock – aggregated view per stock (updated after each insert)
process         – workflow progress tracking
recommendation_feedback – user feedback on recommendations
```

### `input_stock_recommendation` key fields

| Column | Type | Notes |
|--------|------|-------|
| `ticker` | VARCHAR(10) | |
| `exchange` | VARCHAR(20) | |
| `currency_code` | VARCHAR(10) | |
| `stock_id` | FK → stock | |
| `rating_id` | FK → ref_stock_rating | 1–5 |
| `analysis_date` | DATE | From article |
| `price` | DECIMAL(10,2) | Current price at analysis time |
| `fair_price` | DECIMAL(10,2) | Intrinsic/fair value from article |
| `target_price` | DECIMAL(10,2) | Analyst price target |
| `price_growth_forecast_pct` | DECIMAL(10,2) | Expected growth % |
| `pe` | DECIMAL(6,2) | P/E ratio |
| `quality_score` | INTEGER | 0–100 |
| `quality_description_words` | INTEGER | |
| `quality_has_rating` | INTEGER | 0/1 |
| `quality_reasoning_level` | INTEGER | 0–3 |
| `webpage_id` | FK → webpage | |
| `entry_date` | DATE | Row insertion date |
| UNIQUE | (stock_id, webpage_id) | One rec per stock per page |

---

## 8. External Dependencies

| Service | Usage | API |
|---------|-------|-----|
| Google Custom Search | Article discovery | REST (`customsearch.cse().list`) |
| OpenAI GPT-4o-mini | Triaging + extraction | LangChain `ChatOpenAI` |
| Playwright / Chromium | JavaScript-heavy page rendering | Async Playwright |
| BeautifulSoup + requests | Simple page fetching + HTML parsing | — |
| Financial Modeling Prep (FMP) | Ticker symbol validation | `/stable/search-symbol`, `/stable/search-name` |
| Yahoo Finance (yfinance) | Market cap + stock quote data | yfinance Python lib |
| SQLite | Recommendations persistence | `sqlite3` (WAL mode) |
| DuckDB | Stock market data cache | `duckdb` |
| AWS S3 (optional) | Database backup/sync | boto3 |

---

## 9. Progress Tracking

The workflow records its progress percent in the `process` table under `process_name = "recommendations_workflow"`:

| Stage | Progress % |
|-------|-----------|
| Workflow created | 10% |
| `search_node` | 30% |
| `filter_duplicate_node` | 35% |
| `filter_known_bad_node` | 40% |
| `retrieve_nested_pages` | 45% |
| `analyze_search_result` | 55% |
| `scrape_node` | 65% |
| Post `workflow.invoke` | 90% |

Progress updates are written via a fresh DB connection per node (state is not used to hold connections).

---

## 10. File Outputs

| Path | Content |
|------|---------|
| `data/db/webpage/{id}/{id}.pdf` | PDF snapshot of scraped page |
| `data/db/webpage/{id}/metadata.json` | `{url, webpage_title, webpage_date}` |
| `data/stock_recommendation/error/error_{ts}_{ticker}.json` | Failed recommendation + error details |
| `logs/workflow_state/` | Final workflow state JSON (via `save_workflow_state_to_json`) |

---

## 11. Key Design Decisions

1. **Browser-first scraping:** `use_browser` is currently hardcoded to `True` for all pages. The `needs_browser_rendering` DB flag exists but is currently bypassed (commented out).

2. **Anti-hallucination guard:** Every ticker extracted by the LLM is validated against a `\bTICKER\b` regex applied to the raw page text. This is a lightweight but effective guard against LLM fabrication.

3. **Quality gating:** Recommendations are not hard-filtered by quality score; a low score (`< 40`) only generates a warning. Filtering is done by valuation data presence (both `fair_price` and `target_price` absent → drop).

4. **Deduplication scope:** Deduplication is cross-page but respects the parent/nested page hierarchy. The same stock appearing on two completely different root pages is **not** deduplicated — deduplication is per `(ticker, exchange, main_url)`.

5. **Currency-to-exchange inference:** When an article states a price in GBP/GBX but doesn't name the exchange, the validator infers LSE as the exchange hint. This improves lookup accuracy for international stocks.

6. **Stateless progress updates:** DB progress calls inside nodes create fresh connections rather than storing a connection in the workflow state. This avoids serialization issues with LangGraph's state checkpointing.
