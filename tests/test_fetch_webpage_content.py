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

from recommendations.workflow import fetch_webpage_content, scrape_single_page
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
