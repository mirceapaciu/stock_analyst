"""Unit tests for search_node mode branching and CSE usage logging."""

import sys
from pathlib import Path
from unittest.mock import patch

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from config import MAX_RESULT_AGE_DAYS, TRACKED_RESULT_AGE_DAYS
from recommendations.workflow import (
    search_node,
    get_tracked_batch_query_specs,
    filter_known_bad_node,
    has_stock_name_recommendation_evidence,
)


class DummyUsageDatabase:
    def __init__(self):
        self.logged = []

    def log_cse_usage(self, workflow_type: str, queries_count: int) -> None:
        self.logged.append((workflow_type, queries_count))


class FakeCseClient:
    def __init__(self, responses, query_log):
        self.responses = responses
        self.query_log = query_log
        self._last_query = ""

    def list(self, q, cx, num, dateRestrict, sort, **kwargs):
        self._last_query = q
        self.query_log.append({"query": q, "dateRestrict": dateRestrict, **kwargs})
        return self

    def execute(self):
        return self.responses.get(self._last_query, {"items": []})


class FakeGoogleService:
    def __init__(self, responses, query_log):
        self._cse_client = FakeCseClient(responses=responses, query_log=query_log)

    def cse(self):
        return self._cse_client


class TestSearchNodeModes:
    @staticmethod
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
            "batch_tickers": [],
        }

    def test_search_node_discovery_mode_uses_discovery_queries_only(self):
        query_log = []
        usage_db = DummyUsageDatabase()
        discovery_queries = [
            "undervalued stocks site:example.com",
            "best value stocks site:example.com",
        ]

        responses = {
            "undervalued stocks site:example.com": {
                "items": [
                    {
                        "title": "Value pick 1",
                        "link": "https://example.com/value-1",
                        "snippet": "Undervalued stock coverage",
                    }
                ]
            },
            "best value stocks site:example.com": {
                "items": [
                    {
                        "title": "Value pick 2",
                        "link": "https://example.com/value-2",
                        "snippet": "Best value stocks",
                    }
                ]
            },
        }

        state = {
            **self._base_state(),
            "workflow_mode": "discovery",
            "batch_tickers": ["AAPL", "MSFT"],
        }

        with patch("recommendations.workflow.GOOGLE_API_KEY", "test-key"):
            with patch("recommendations.workflow.GOOGLE_CSE_ID", "test-cse-id"):
                with patch("recommendations.workflow.get_search_queries", return_value=discovery_queries):
                    with patch(
                        "recommendations.workflow.build",
                        return_value=FakeGoogleService(responses=responses, query_log=query_log),
                    ):
                        with patch("recommendations.workflow.RecommendationsDatabase", return_value=usage_db):
                            result = search_node(state)

        assert [entry["query"] for entry in query_log] == discovery_queries
        assert all(entry["dateRestrict"] == f"d{MAX_RESULT_AGE_DAYS}" for entry in query_log)
        assert all(entry.get("orTerms") for entry in query_log)
        assert all(entry.get("excludeTerms") for entry in query_log)
        assert all(entry.get("exactTerms") for entry in query_log)
        assert usage_db.logged == [("discovery", 2)]
        assert result["executed_queries"] == discovery_queries
        assert len(result["search_results"]) == 2
        assert all(not item.get("is_tracked_stock_search") for item in result["search_results"])

    def test_search_node_tracked_mode_uses_batch_tickers_only(self):
        usage_db = DummyUsageDatabase()
        query_log = []

        batch_tickers = ["AAPL", "MSFT"]
        batch_stock_names = {
            "AAPL": "Apple Inc",
            "MSFT": "Microsoft Corporation",
        }
        query_specs = get_tracked_batch_query_specs(
            batch_tickers,
            batch_stock_names=batch_stock_names,
        )

        for spec in query_specs:
            expected_name = batch_stock_names[spec["tracked_ticker"]]
            assert spec["tracked_ticker"] in spec["query"]
            assert f'"{expected_name}"' in spec["query"]

        responses = {}
        for index, spec in enumerate(query_specs, start=1):
            ticker = spec["tracked_ticker"]
            query = spec["query"]
            responses[query] = {
                "items": [
                    {
                        "title": f"{ticker} rating update",
                        "link": f"https://example.com/{ticker.lower()}-{index}",
                        "snippet": f"{ticker} stock analysis",
                    }
                ]
            }

        state = {
            **self._base_state(),
            "workflow_mode": "tracked",
            "batch_tickers": batch_tickers,
            "batch_stock_names": batch_stock_names,
        }

        with patch("recommendations.workflow.GOOGLE_API_KEY", "test-key"):
            with patch("recommendations.workflow.GOOGLE_CSE_ID", "test-cse-id"):
                with patch(
                    "recommendations.workflow.build",
                    return_value=FakeGoogleService(responses=responses, query_log=query_log),
                ):
                    with patch("recommendations.workflow.RecommendationsDatabase", return_value=usage_db):
                        result = search_node(state)

        expected_queries = [spec["query"] for spec in query_specs]
        assert [entry["query"] for entry in query_log] == expected_queries
        assert all(entry["dateRestrict"] == f"d{TRACKED_RESULT_AGE_DAYS}" for entry in query_log)
        assert usage_db.logged == [("tracked_stock", len(expected_queries))]
        assert result["executed_queries"] == expected_queries
        assert len(result["search_results"]) == len(expected_queries)
        assert all(item.get("is_tracked_stock_search") for item in result["search_results"])
        assert {item.get("tracked_ticker") for item in result["search_results"]} == {"AAPL", "MSFT"}

    def test_tracked_query_specs_include_stock_name_when_template_uses_only_ticker(self):
        with patch(
            "recommendations.workflow.TRACKED_BATCH_SEARCH_QUERIES",
            ["{ticker} stock analysis"],
        ):
            specs = get_tracked_batch_query_specs(
                ["AAPL"],
                batch_stock_names={"AAPL": "Apple Inc"},
            )

        assert len(specs) == 1
        assert "AAPL" in specs[0]["query"]
        assert '"Apple Inc"' in specs[0]["query"]

    def test_filter_known_bad_discovery_mode_removes_low_intent_or_profile_urls(self):
        class DummyFilterDatabase:
            @staticmethod
            def get_unusable_domains():
                return []

            @staticmethod
            def get_blocked_url_match(_url):
                return None

        state = {
            **self._base_state(),
            "workflow_mode": "discovery",
            "search_results": [
                {
                    "title": "Jana Partners LLC | Reuters",
                    "href": "https://www.reuters.com/company/jana-partners-llc/",
                    "body": "Stocks · U.S. Markets · Wealth",
                    "date": None,
                    "pagemap": {},
                },
                {
                    "title": "10 Undervalued Stocks to Buy in 2026",
                    "href": "https://www.reuters.com/markets/stocks/undervalued-stocks-to-buy-2026-04-01/",
                    "body": "Top picks with buy rating and price target updates",
                    "date": "2026-04-01",
                    "pagemap": {},
                },
            ],
        }

        with patch("recommendations.workflow.RecommendationsDatabase", return_value=DummyFilterDatabase()):
            result = filter_known_bad_node(state)

        assert len(result["filtered_search_results"]) == 1
        assert result["filtered_search_results"][0]["href"].endswith("/undervalued-stocks-to-buy-2026-04-01/")
        assert result["filtered_search_results"][0].get("discovery_intent_score", 0) >= 2

    def test_filter_known_bad_tracked_mode_does_not_apply_discovery_intent_filter(self):
        class DummyFilterDatabase:
            @staticmethod
            def get_unusable_domains():
                return []

            @staticmethod
            def get_blocked_url_match(_url):
                return None

        state = {
            **self._base_state(),
            "workflow_mode": "tracked",
            "search_results": [
                {
                    "title": "Jana Partners LLC | Reuters",
                    "href": "https://www.reuters.com/company/jana-partners-llc/",
                    "body": "Stocks · U.S. Markets · Wealth",
                    "date": None,
                    "pagemap": {},
                }
            ],
        }

        with patch("recommendations.workflow.RecommendationsDatabase", return_value=DummyFilterDatabase()):
            result = filter_known_bad_node(state)

        assert len(result["filtered_search_results"]) == 1
        assert result["filtered_search_results"][0]["href"].endswith("/company/jana-partners-llc/")

    def test_has_stock_name_recommendation_evidence_detects_name_only_stock_articles(self):
        result = {
            "title": "Meta: Muse Models May Just Be the Spark That the Firm Needed in AI Model Development",
            "href": "https://global.morningstar.com/en-eu/stocks/meta-muse-models-may-just-be-spark",
            "body": "We think Meta stock is moderately undervalued.",
            "pagemap": {
                "metatags": [
                    {
                        "og:description": "We think Meta stock is moderately undervalued.",
                    }
                ]
            },
        }

        assert has_stock_name_recommendation_evidence(result) is True

    def test_has_stock_name_recommendation_evidence_rejects_generic_news(self):
        result = {
            "title": "Global Markets Open Mixed Amid Macro Uncertainty",
            "href": "https://www.example.com/news/global-markets-open-mixed",
            "body": "Macro developments and rate expectations moved broad indexes.",
            "pagemap": {},
        }

        assert has_stock_name_recommendation_evidence(result) is False
