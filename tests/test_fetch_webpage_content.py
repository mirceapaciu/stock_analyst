"""Unit tests for fetch_webpage_content – Brotli compression handling (BUG-002)."""

import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch
import requests

from bs4 import BeautifulSoup

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.workflow import fetch_webpage_content, scrape_single_page, scrape_node
from repositories.recommendations_db import RecommendationsDatabase


def _make_mock_response(content: bytes, content_encoding: str = "", status_code: int = 200):
    """Return a minimal mock of requests.Response."""
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_resp.status_code = status_code
    mock_resp.headers = {"Content-Encoding": content_encoding} if content_encoding else {}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


HEADERS = {"User-Agent": "test-agent", "Accept-Encoding": "gzip, deflate"}


class TestFetchWebpageContentBrotli:
    """BUG-002: Server returns Content-Encoding: br — must not silently pass garbage to caller."""

    def test_brotli_response_raises_value_error(self):
        """A response with Content-Encoding: br should raise ValueError with a clear message."""
        fake_brotli_bytes = b"\x1b\x00\x00\x00\x00\xf0\x13\x00\x00\x00\xff"
        mock_resp = _make_mock_response(fake_brotli_bytes, content_encoding="br")

        with patch("recommendations.workflow.requests.Session") as mock_session_cls:
            mock_session_cls.return_value.get.return_value = mock_resp

            with pytest.raises(ValueError, match="Brotli"):
                fetch_webpage_content(
                    "https://www.fool.com/investing/2026/03/28/example/",
                    HEADERS,
                    use_browser=False,
                )

    def test_brotli_error_message_includes_url(self):
        """The Brotli ValueError message should reference the offending URL."""
        url = "https://www.fool.com/investing/2026/03/28/example/"
        mock_resp = _make_mock_response(b"\x1b\xff", content_encoding="br")

        with patch("recommendations.workflow.requests.Session") as mock_session_cls:
            mock_session_cls.return_value.get.return_value = mock_resp

            with pytest.raises(ValueError, match=url):
                fetch_webpage_content(url, HEADERS, use_browser=False)

    def test_gzip_response_returns_readable_text(self):
        """A normal HTML response (no Brotli) should parse to non-empty readable text."""
        html = (
            b"<html><body><main>"
            b"<p>Buy Acme Corp stock. Ticker: ACM. Analyst rates it a strong buy.</p>"
            b"</main></body></html>"
        )
        mock_resp = _make_mock_response(html, content_encoding="gzip")

        with patch("recommendations.workflow.requests.Session") as mock_session_cls:
            mock_session_cls.return_value.get.return_value = mock_resp

            page_text, soup, html_content, pdf_bytes = fetch_webpage_content(
                "https://example.com/article", HEADERS, use_browser=False
            )

        assert "Acme" in page_text, "Expected readable article text in page_text"
        assert pdf_bytes is None  # non-browser path never returns PDF bytes

    def test_no_content_encoding_header_works_fine(self):
        """Response with no Content-Encoding header should parse normally."""
        html = b"<html><body><p>Some article text about AAPL stock.</p></body></html>"
        mock_resp = _make_mock_response(html)  # no content_encoding

        with patch("recommendations.workflow.requests.Session") as mock_session_cls:
            mock_session_cls.return_value.get.return_value = mock_resp

            page_text, _, _, _ = fetch_webpage_content(
                "https://example.com/no-encoding", HEADERS, use_browser=False
            )

        assert "AAPL" in page_text or "article" in page_text


class TestAcceptEncodingHeaders:
    """BUG-002: Ensure scrape node headers no longer advertise Brotli support."""

    def test_scrape_pages_node_does_not_advertise_brotli(self):
        """scrape_node's Accept-Encoding must not include 'br'."""
        import inspect
        from recommendations.workflow import scrape_node

        source = inspect.getsource(scrape_node)
        # The headers dict must not contain 'br' as an encoding token
        assert "'Accept-Encoding': 'gzip, deflate'" in source, (
            "scrape_node must not include 'br' in Accept-Encoding"
        )
        assert "gzip, deflate, br" not in source, (
            "scrape_node must not advertise Brotli support"
        )

    def test_single_url_runner_headers_do_not_advertise_brotli(self):
        """Single URL runner must not include 'br' in Accept-Encoding."""
        runner_file = Path(__file__).parent.parent / "scripts" / "run_recommendation_workflow_for_url.py"
        source = runner_file.read_text(encoding="utf-8")
        assert '"Accept-Encoding": "gzip, deflate"' in source
        assert '"Accept-Encoding": "gzip, deflate, br"' not in source

    def test_rescrape_runner_headers_do_not_advertise_brotli(self):
        """Rescrape script must not include 'br' in Accept-Encoding."""
        runner_file = Path(__file__).parent.parent / "scripts" / "rescrape_webpage_to_pdf.py"
        source = runner_file.read_text(encoding="utf-8")
        assert "'Accept-Encoding': 'gzip, deflate'" in source
        assert "'Accept-Encoding': 'gzip, deflate, br'" not in source


class TestScrapeSinglePageBrotliFallback:
    """Regression tests for BUG-002 ValueError handling in scrape_single_page."""

    def test_brotli_value_error_retries_with_browser(self):
        """On Brotli ValueError in plain fetch, scrape_single_page should retry with browser."""
        search_result = {
            "href": "https://www.fool.com/investing/2026/03/28/example/",
            "title": "Example title",
            "excerpt_date": "2026-03-28",
            "is_tracked_stock_search": False,
        }
        headers = {"User-Agent": "test-agent", "Accept-Encoding": "gzip, deflate"}

        db = MagicMock()
        db.needs_browser_rendering.return_value = False
        db.get_blocked_url_match.return_value = None

        html = "<html><body><article><p>Readable stock article text</p></article></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        with patch(
            "recommendations.workflow.fetch_webpage_content",
            side_effect=[
                ValueError("Server returned Brotli-compressed content for https://www.fool.com/investing/2026/03/28/example/"),
                ("Readable stock article text", soup, html, b"%PDF-1.4"),
            ],
        ) as mock_fetch, patch(
            "recommendations.workflow.extract_date_from_webpage",
            return_value=datetime(2026, 3, 28),
        ), patch(
            "recommendations.workflow.extract_stock_recommendations_with_llm",
            return_value=[],
        ):
            result = scrape_single_page(search_result, headers, db)

        assert result is not None
        assert result["page_text"] == "Readable stock article text"
        assert result["stock_recommendations"] == []
        assert mock_fetch.call_count == 2
        db.upsert_website.assert_called_with("www.fool.com", is_usable=1, requires_browser=1)

    def test_brotli_value_error_does_not_crash_when_browser_retry_fails(self):
        """If browser retry fails too, scrape_single_page should return None (not raise)."""
        search_result = {
            "href": "https://www.fool.com/investing/2026/03/28/example/",
            "title": "Example title",
            "excerpt_date": "2026-03-28",
        }
        headers = {"User-Agent": "test-agent", "Accept-Encoding": "gzip, deflate"}

        db = MagicMock()
        db.needs_browser_rendering.return_value = False
        db.get_blocked_url_match.return_value = None

        with patch(
            "recommendations.workflow.fetch_webpage_content",
            side_effect=[
                ValueError("Server returned Brotli-compressed content for https://www.fool.com/investing/2026/03/28/example/"),
                RuntimeError("playwright failed"),
            ],
        ):
            result = scrape_single_page(search_result, headers, db)

        assert result is None


class TestScrapeSinglePageBlockedPages:
    def test_terminal_http_status_records_block_rule(self, tmp_path):
        """401/403/404 terminal failures should be persisted as blocked URL rules without retry storms."""
        search_result = {
            "href": "https://www.reuters.com/markets/companies/CNNE.P/profile/",
            "title": "Reuters profile",
            "excerpt_date": "2026-03-28",
        }
        headers = {"User-Agent": "test-agent", "Accept-Encoding": "gzip, deflate"}
        db = RecommendationsDatabase(str(tmp_path / "blocked_pages.duckdb"))

        http_error = requests.HTTPError("401 Unauthorized")
        http_error.response = MagicMock(status_code=401)

        with patch(
            "recommendations.workflow.fetch_webpage_content",
            side_effect=http_error,
        ) as mock_fetch:
            result = scrape_single_page(search_result, headers, db)

        assert result is not None
        assert result["fetch_status"] == "blocked_terminal"
        assert result["fetch_status_code"] == 401
        assert result["fetch_metrics"]["blocked_terminal_failures"] == 1
        assert mock_fetch.call_count == 1

        blocked_match = db.get_blocked_url_match(search_result["href"])
        assert blocked_match is not None
        assert blocked_match["status_code"] == 401
        assert any("/markets/companies/*/profile/" in pattern for pattern in db.get_blocked_url_patterns())

    def test_cached_block_rule_skips_future_fetches(self, tmp_path):
        """Persisted blocked URL patterns should short-circuit later runs before network fetch."""
        search_result = {
            "href": "https://www.reuters.com/markets/companies/CNNE.P/profile/",
            "title": "Reuters profile",
            "excerpt_date": "2026-03-28",
        }
        headers = {"User-Agent": "test-agent", "Accept-Encoding": "gzip, deflate"}
        db = RecommendationsDatabase(str(tmp_path / "blocked_pages_cache.duckdb"))
        db.record_blocked_url(search_result["href"], status_code=403, reason="terminal_http_status")

        with patch("recommendations.workflow.fetch_webpage_content") as mock_fetch:
            result = scrape_single_page(search_result, headers, db)

        assert result is not None
        assert result["fetch_status"] == "blocked_cached"
        assert result["fetch_metrics"]["blocked_cached_skips"] == 1
        assert result["matched_blocked_pattern"] in db.get_blocked_url_patterns()
        mock_fetch.assert_not_called()


class TestScrapeSinglePagePdfFallback:
    def test_recommendation_page_uses_browser_fallback_to_capture_pdf(self):
        """When initial fetch has no PDF bytes, recommendation pages should trigger browser PDF capture."""
        search_result = {
            "href": "https://example.com/article",
            "title": "Example title",
            "excerpt_date": "2026-03-28",
            "is_tracked_stock_search": False,
        }
        headers = {"User-Agent": "test-agent", "Accept-Encoding": "gzip, deflate"}

        db = MagicMock()
        db.needs_browser_rendering.return_value = False
        db.get_blocked_url_match.return_value = None

        html = "<html><body><article><p>Readable stock article text about AAPL</p></article></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        with patch(
            "recommendations.workflow.fetch_webpage_content_with_policy",
            return_value=("Readable stock article text about AAPL", soup, html, None),
        ), patch(
            "recommendations.workflow.fetch_webpage_content",
            return_value=("Readable stock article text about AAPL", soup, html, b"%PDF-1.4-fallback"),
        ) as mock_fetch_fallback, patch(
            "recommendations.workflow.extract_date_from_webpage",
            return_value=datetime(2026, 3, 28),
        ), patch(
            "recommendations.workflow.extract_stock_recommendations_with_llm",
            return_value=([
                {
                    "ticker": "AAPL",
                    "validation_status": "validated",
                    "quality_score": 80,
                }
            ], {"hallucinated_tickers": 0, "low_quality_filtered": 0}),
        ):
            result = scrape_single_page(search_result, headers, db)

        assert result is not None
        assert result["pdf_content"] == b"%PDF-1.4-fallback"
        mock_fetch_fallback.assert_called_once_with(
            search_result["href"],
            headers,
            use_browser=True,
        )

    def test_non_recommendation_page_does_not_trigger_pdf_fallback(self):
        """Pages without recommendations should not do an extra browser fetch just to capture PDF."""
        search_result = {
            "href": "https://example.com/no-rec-article",
            "title": "No recommendation title",
            "excerpt_date": "2026-03-28",
            "is_tracked_stock_search": False,
        }
        headers = {"User-Agent": "test-agent", "Accept-Encoding": "gzip, deflate"}

        db = MagicMock()
        db.needs_browser_rendering.return_value = False
        db.get_blocked_url_match.return_value = None

        html = "<html><body><article><p>Readable article text</p></article></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        with patch(
            "recommendations.workflow.fetch_webpage_content_with_policy",
            return_value=("Readable article text", soup, html, None),
        ), patch(
            "recommendations.workflow.fetch_webpage_content",
        ) as mock_fetch_fallback, patch(
            "recommendations.workflow.extract_date_from_webpage",
            return_value=datetime(2026, 3, 28),
        ), patch(
            "recommendations.workflow.extract_stock_recommendations_with_llm",
            return_value=([], {"hallucinated_tickers": 0, "low_quality_filtered": 0}),
        ):
            result = scrape_single_page(search_result, headers, db)

        assert result is not None
        assert result["pdf_content"] is None
        mock_fetch_fallback.assert_not_called()


class TestScrapeSinglePageChallengePages:
    def test_challenge_text_is_blocked_and_not_extracted(self, tmp_path):
        """Challenge/interstitial text should fail fast, persist a blocked rule, and skip extraction."""
        search_result = {
            "href": "https://seekingalpha.com/article/4891681-public-storage-we-took-large-position-in-6-6-percent-yielding-preferreds",
            "title": "Seeking Alpha example",
            "excerpt_date": "2026-04-17",
        }
        headers = {"User-Agent": "test-agent", "Accept-Encoding": "gzip, deflate"}
        db = RecommendationsDatabase(str(tmp_path / "challenge_pages.duckdb"))

        challenge_text = (
            "Before we continue... Press & Hold to confirm you are a human (and not a bot). "
            "Reference ID 0f5d6679-3ee8-11f1-a8df-d7e721de136c"
        )
        html = f"<html><body><main><p>{challenge_text}</p></main></body></html>"
        soup = BeautifulSoup(html, "html.parser")

        with patch(
            "recommendations.workflow.fetch_webpage_content",
            return_value=(challenge_text, soup, html, None),
        ), patch("recommendations.workflow.extract_stock_recommendations_with_llm") as mock_extract:
            result = scrape_single_page(search_result, headers, db)

        assert result is not None
        assert result["fetch_status"] == "blocked_terminal"
        assert result["fetch_metrics"]["blocked_terminal_failures"] == 1
        assert result["fetch_metrics"]["blocked_challenge_pages"] == 1
        assert "Anti-bot challenge detected" in result["fetch_error"]
        assert result["stock_recommendations"] == []
        mock_extract.assert_not_called()

        blocked_match = db.get_blocked_url_match(search_result["href"])
        assert blocked_match is not None
        assert blocked_match["reason"] == "challenge_page"


class TestScrapeNodeChallengeFallback:
    def test_scrape_node_continues_with_alternate_sources_when_one_is_challenge_blocked(self):
        """A blocked challenge page should not stop scraping of other eligible sources."""
        state = {
            "query": "",
            "executed_queries": [],
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [
                {
                    "href": "https://blocked.example.com/challenge",
                    "title": "Blocked source",
                    "contains_stocks": True,
                    "excerpt_date": "2026-04-17",
                },
                {
                    "href": "https://open.example.com/analysis",
                    "title": "Open source",
                    "contains_stocks": True,
                    "excerpt_date": "2026-04-17",
                },
            ],
            "scraped_pages": [],
            "status": "",
            "error": "",
            "fetch_metrics": {},
            "extraction_metrics": {},
        }

        blocked_result = {
            "url": "https://blocked.example.com/challenge",
            "webpage_title": "Blocked source",
            "webpage_date": "2026-04-17",
            "page_text": "",
            "pdf_content": None,
            "stock_recommendations": [],
            "fetch_status": "blocked_terminal",
            "fetch_error": "Anti-bot challenge detected",
            "fetch_metrics": {"blocked_terminal_failures": 1, "blocked_challenge_pages": 1},
            "extraction_metrics": {},
        }
        ok_result = {
            "url": "https://open.example.com/analysis",
            "webpage_title": "Open source",
            "webpage_date": "2026-04-17",
            "page_text": "Some valid analysis text",
            "pdf_content": None,
            "stock_recommendations": [{"ticker": "AAPL"}],
            "fetch_status": "ok",
            "fetch_metrics": {},
            "extraction_metrics": {},
        }

        with patch("recommendations.workflow.RecommendationsDatabase", return_value=MagicMock()), patch(
            "recommendations.workflow.scrape_single_page",
            side_effect=[blocked_result, ok_result],
        ), patch("recommendations.workflow.MAX_WORKERS", 1):
            result = scrape_node(state)

        assert len(result["scraped_pages"]) == 2
        assert result["fetch_metrics"]["blocked_terminal_failures"] == 1
        assert result["fetch_metrics"]["blocked_challenge_pages"] == 1
        assert "blocked pages" in result["status"]
        assert "challenge pages" in result["status"]
        assert "Scraped 1 pages with 1 recommendations" in result["status"]
