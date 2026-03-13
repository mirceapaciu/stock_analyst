"""Unit tests for recommendation filtering in validate_tickers_node."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.workflow import validate_tickers_node


class DummyRecommendationsDatabase:
    """No-op DB used to avoid real database interactions in tests."""

    def __init__(self, existing_stock_ids=None):
        self.existing_stock_ids = set(existing_stock_ids or [])

    def has_recommended_stock(self, stock_id: int) -> bool:
        return stock_id in self.existing_stock_ids


class TestValidateTickersNodeFiltering:
    def test_filters_recommendation_missing_both_prices_before_lookup(self):
        state = {
            "query": "",
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [
                {
                    "url": "https://example.com/article",
                    "stock_recommendations": [
                        {
                            "ticker": "AMD",
                            "exchange": "NASDAQ",
                            "stock_name": "Advanced Micro Devices",
                            "fair_price": "N/A",
                            "target_price": None,
                        }
                    ],
                }
            ],
            "status": "",
            "error": "",
        }

        with patch("recommendations.workflow.RecommendationsDatabase", return_value=DummyRecommendationsDatabase()):
            with patch("services.recommendations.lookup_stock") as mock_lookup_stock:
                with patch("services.financial.get_or_create_stock_info") as mock_market_data:
                    result = validate_tickers_node(state)

        rec = result["scraped_pages"][0]["stock_recommendations"][0]
        assert rec["validation_status"] == "filtered_missing_price"
        assert "fair_price" in rec["validation_error"]
        mock_lookup_stock.assert_not_called()
        mock_market_data.assert_not_called()

    def test_keeps_recommendation_when_fair_or_target_price_exists(self):
        state = {
            "query": "",
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [
                {
                    "url": "https://example.com/article",
                    "stock_recommendations": [
                        {
                            "ticker": "AMD",
                            "exchange": "NASDAQ",
                            "stock_name": "Advanced Micro Devices",
                            "rating": 4,
                            "fair_price": "270",
                            "target_price": "N/A",
                        }
                    ],
                }
            ],
            "status": "",
            "error": "",
        }

        with patch("recommendations.workflow.RecommendationsDatabase", return_value=DummyRecommendationsDatabase()):
            with patch("services.recommendations.lookup_stock") as mock_lookup_stock:
                with patch("services.financial.get_or_create_stock_info") as mock_market_data:
                    mock_lookup_stock.return_value = {
                        "id": 1,
                        "exchange": "NASDAQ",
                        "stock_name": "Advanced Micro Devices, Inc.",
                        "mic": "XNAS",
                        "isin": None,
                    }
                    mock_market_data.return_value = {"marketCap": "1000000000000"}

                    result = validate_tickers_node(state)

        rec = result["scraped_pages"][0]["stock_recommendations"][0]
        assert rec["validation_status"] == "validated"
        assert rec["stock_id"] == 1

    def test_filters_new_stock_with_rating_below_threshold(self):
        state = {
            "query": "",
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [
                {
                    "url": "https://example.com/article",
                    "stock_recommendations": [
                        {
                            "ticker": "AMD",
                            "exchange": "NASDAQ",
                            "stock_name": "Advanced Micro Devices",
                            "rating": 3,
                            "fair_price": "270",
                            "target_price": "N/A",
                        }
                    ],
                }
            ],
            "status": "",
            "error": "",
        }

        with patch("recommendations.workflow.RecommendationsDatabase", return_value=DummyRecommendationsDatabase()):
            with patch("services.recommendations.lookup_stock") as mock_lookup_stock:
                with patch("services.financial.get_or_create_stock_info") as mock_market_data:
                    mock_lookup_stock.return_value = {
                        "id": 11,
                        "exchange": "NASDAQ",
                        "stock_name": "Advanced Micro Devices, Inc.",
                        "mic": "XNAS",
                        "isin": None,
                    }
                    mock_market_data.return_value = {"marketCap": "1000000000000"}

                    result = validate_tickers_node(state)

        rec = result["scraped_pages"][0]["stock_recommendations"][0]
        assert rec["validation_status"] == "filtered_rating"
        assert "below threshold" in rec["validation_error"]

    def test_keeps_existing_stock_even_with_rating_below_threshold(self):
        state = {
            "query": "",
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [
                {
                    "url": "https://example.com/article",
                    "stock_recommendations": [
                        {
                            "ticker": "AMD",
                            "exchange": "NASDAQ",
                            "stock_name": "Advanced Micro Devices",
                            "rating": 3,
                            "fair_price": "270",
                            "target_price": "N/A",
                        }
                    ],
                }
            ],
            "status": "",
            "error": "",
        }

        with patch(
            "recommendations.workflow.RecommendationsDatabase",
            return_value=DummyRecommendationsDatabase(existing_stock_ids={1}),
        ):
            with patch("services.recommendations.lookup_stock") as mock_lookup_stock:
                with patch("services.financial.get_or_create_stock_info") as mock_market_data:
                    mock_lookup_stock.return_value = {
                        "id": 1,
                        "exchange": "NASDAQ",
                        "stock_name": "Advanced Micro Devices, Inc.",
                        "mic": "XNAS",
                        "isin": None,
                    }
                    mock_market_data.return_value = {"marketCap": "1000000000000"}

                    result = validate_tickers_node(state)

        rec = result["scraped_pages"][0]["stock_recommendations"][0]
        assert rec["validation_status"] == "validated"
        assert rec["stock_id"] == 1

    def test_filters_recommendation_when_text_and_rating_conflict(self):
        state = {
            "query": "",
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [
                {
                    "url": "https://example.com/article",
                    "stock_recommendations": [
                        {
                            "ticker": "AAPL",
                            "exchange": "NASDAQ",
                            "stock_name": "Apple Inc.",
                            "rating": 1,
                            "price": "100",
                            "fair_price": "120",
                            "target_price": "N/A",
                            "recommendation_text": "AAPL appears undervalued and offers an attractive discount.",
                        }
                    ],
                }
            ],
            "status": "",
            "error": "",
        }

        with patch("recommendations.workflow.RecommendationsDatabase", return_value=DummyRecommendationsDatabase()):
            with patch("services.recommendations.lookup_stock") as mock_lookup_stock:
                with patch("services.financial.get_or_create_stock_info") as mock_market_data:
                    result = validate_tickers_node(state)

        rec = result["scraped_pages"][0]["stock_recommendations"][0]
        assert rec["validation_status"] == "inconsistent_data"
        assert "undervaluation" in rec["validation_error"]
        mock_lookup_stock.assert_not_called()
        mock_market_data.assert_not_called()

    def test_filters_recommendation_when_price_gap_conflicts_with_sell_rating(self):
        state = {
            "query": "",
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [
                {
                    "url": "https://example.com/article",
                    "stock_recommendations": [
                        {
                            "ticker": "AAPL",
                            "exchange": "NASDAQ",
                            "stock_name": "Apple Inc.",
                            "rating": 1,
                            "price": "264.72",
                            "fair_price": "778",
                            "target_price": "731",
                            "recommendation_text": "AAPL is trading at a 46% premium and appears overvalued.",
                        }
                    ],
                }
            ],
            "status": "",
            "error": "",
        }

        with patch("recommendations.workflow.RecommendationsDatabase", return_value=DummyRecommendationsDatabase()):
            with patch("services.recommendations.lookup_stock") as mock_lookup_stock:
                with patch("services.financial.get_or_create_stock_info") as mock_market_data:
                    result = validate_tickers_node(state)

        rec = result["scraped_pages"][0]["stock_recommendations"][0]
        assert rec["validation_status"] == "inconsistent_data"
        assert "below fair/target value" in rec["validation_error"]
        mock_lookup_stock.assert_not_called()
        mock_market_data.assert_not_called()
