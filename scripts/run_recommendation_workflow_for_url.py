"""Run recommendation extraction workflow for a single URL."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from repositories.recommendations_db import RecommendationsDatabase
from recommendations.workflow import (
    scrape_single_page,
    validate_tickers_node,
    output_node,
    save_pdf_to_file,
    save_metadata_to_file,
)
from utils.logger import setup_logging, save_workflow_state_to_json

setup_logging()
logger = logging.getLogger("run_recommendation_workflow_for_url")


def _persist_scraped_page_artifacts(db: RecommendationsDatabase, page_data: dict) -> int:
    """Persist webpage + page_text + PDF/metadata even when no recommendations survive validation."""
    page_url = page_data.get("url")
    if not page_url:
        raise ValueError("Cannot persist scraped page: missing URL")

    parsed = urlparse(page_url)
    domain = parsed.netloc
    website_id = db.upsert_website(domain, is_usable=2)

    webpage_date = page_data.get("webpage_date") or datetime.now().strftime("%Y-%m-%d")
    webpage_title = page_data.get("webpage_title", "")
    has_recommendations = bool(page_data.get("stock_recommendations"))

    webpage_id = db.upsert_webpage(
        url=page_url,
        date=webpage_date,
        title=webpage_title,
        excerpt="",
        last_seen_date=datetime.now().strftime("%Y-%m-%d"),
        website_id=website_id,
        is_stock_recommendation=1 if has_recommendations else 0,
        page_text=page_data.get("page_text", ""),
    )

    pdf_content = page_data.get("pdf_content")
    if pdf_content:
        save_pdf_to_file(webpage_id, pdf_content)
    else:
        logger.warning("No PDF content available for scraped page")

    save_metadata_to_file(
        webpage_id=webpage_id,
        url=page_url,
        webpage_title=webpage_title,
        webpage_date=webpage_date,
    )

    return webpage_id


def _build_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def run_for_url(url: str, title: str | None = None, excerpt_date: str | None = None) -> int:
    db = RecommendationsDatabase()

    logger.info("=" * 80)
    logger.info("Starting single-URL recommendation workflow")
    logger.info(f"URL: {url}")
    logger.info("=" * 80)

    if not excerpt_date:
        excerpt_date = datetime.now().strftime("%Y-%m-%d")

    search_result = {
        "title": title or "",
        "href": url,
        "body": "",
        "date": excerpt_date,
        "contains_stocks": True,
        "excerpt_date": excerpt_date,
        "pagemap": {},
    }

    page_data = scrape_single_page(search_result, _build_headers(), db)
    if not page_data:
        logger.error("Failed to scrape page or extract recommendations")
        return 1

    webpage_id = _persist_scraped_page_artifacts(db, page_data)
    logger.info(f"Saved scraped page artifacts for webpage_id={webpage_id}")

    state = {
        "query": f"direct_url:{url}",
        "executed_queries": [f"direct_url:{url}"],
        "search_results": [search_result],
        "filtered_search_results": [search_result],
        "expanded_search_results": [search_result],
        "scraped_pages": [page_data],
        "deduplicated_pages": [],
        "skipped_recommendations": [],
        "fetch_metrics": page_data.get("fetch_metrics", {}),
        "extraction_metrics": page_data.get("extraction_metrics", {}),
        "status": "scraped",
        "error": "",
        "process_name": None,
    }

    state = validate_tickers_node(state)
    state = output_node(state)

    state_file = save_workflow_state_to_json(state)
    logger.info(f"State dumped to: {state_file}")

    saved_recommendations = sum(
        len(page.get("stock_recommendations", []))
        for page in state.get("deduplicated_pages", [])
    )
    logger.info(f"Final status: {state.get('status', 'N/A')}")
    logger.info(f"Scraped pages: {len(state.get('scraped_pages', []))}")
    logger.info(f"Saved recommendations (deduplicated): {saved_recommendations}")
    logger.info(f"Saved webpage_id: {webpage_id}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run recommendation workflow on a single webpage URL"
    )
    parser.add_argument("url", help="Page URL to scrape and analyze")
    parser.add_argument(
        "--title",
        help="Optional page title override (otherwise extracted from page metadata/workflow defaults)",
        default=None,
    )
    parser.add_argument(
        "--excerpt-date",
        help="Optional YYYY-MM-DD date used as excerpt_date/date in pipeline (default: today)",
        default=None,
    )

    args = parser.parse_args()

    try:
        return run_for_url(args.url, args.title, args.excerpt_date)
    except KeyboardInterrupt:
        logger.warning("Workflow interrupted by user")
        return 1
    except Exception as exc:
        logger.error(f"Workflow failed: {exc}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
