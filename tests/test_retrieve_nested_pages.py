"""Unit tests for nested link expansion filtering."""

import sys
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.workflow import retrieve_nested_pages


class DummyDb:
    @staticmethod
    def needs_browser_rendering(_domain):
        return False


def _base_state():
    return {
        "query": "",
        "executed_queries": [],
        "search_results": [],
        "filtered_search_results": [],
        "expanded_search_results": [],
        "scraped_pages": [],
        "deduplicated_pages": [],
        "skipped_recommendations": [],
        "status": "",
        "error": "",
        "process_name": None,
        "workflow_mode": "discovery",
        "batch_tickers": [],
    }


def test_retrieve_nested_pages_skips_privacy_links_but_keeps_recommendation_links():
    parent_url = "https://www.morningstar.com/markets/q1-2026-review-q2-market-outlook"

    html = """
    <html>
      <body>
        <a href="/company/privacy-policy/do-not-sell-or-share">Do Not Sell or Share My Personal Information</a>
        <a href="/stocks/33-undervalued-stocks-buy-volatile-market">33 Undervalued Stocks to Buy in a Volatile Market</a>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")

    state = {
        **_base_state(),
        "filtered_search_results": [
            {
                "title": "Q1 review",
                "href": parent_url,
                "body": "",
                "date": None,
                "pagemap": {},
            }
        ],
    }

    with patch("recommendations.workflow.RecommendationsDatabase", return_value=DummyDb()), patch(
        "recommendations.workflow.fetch_webpage_content_with_policy",
        return_value=("page text", soup, html, None),
    ):
        result = retrieve_nested_pages(state)

    hrefs = [item.get("href") for item in result.get("expanded_search_results", [])]

    assert "https://www.morningstar.com/company/privacy-policy/do-not-sell-or-share" not in hrefs
    assert "https://www.morningstar.com/stocks/33-undervalued-stocks-buy-volatile-market" in hrefs
