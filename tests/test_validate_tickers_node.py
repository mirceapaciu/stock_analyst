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
