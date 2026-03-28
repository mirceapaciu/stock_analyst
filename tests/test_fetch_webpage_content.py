"""Unit tests for fetch_webpage_content – Brotli compression handling (BUG-002)."""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.workflow import fetch_webpage_content


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
