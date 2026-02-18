"""Unit tests for save_stock_recommendation_to_db mapping behavior."""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.workflow import save_stock_recommendation_to_db


class DummyRecommendationsDatabase:
    def __init__(self):
        self.inserted_payload = None

    def get_mic_by_exchange(self, exchange):
        return "XNAS"

    def upsert_stock(self, isin, ticker, exchange, stock_name, mic):
        return 123

    def insert_stock_recommendation(self, payload):
        self.inserted_payload = payload

    def upsert_recommended_stock_from_input(self, stock_id):
        return None


class TestSaveStockRecommendationToDb:
    def test_uses_target_price_when_fair_price_missing(self):
        db = DummyRecommendationsDatabase()

        recommendation = {
            "ticker": "AMD",
            "exchange": "NASDAQ",
            "stock_name": "Advanced Micro Devices, Inc.",
            "rating": 4,
            "analysis_date": "2026-02-18",
            "price": "120.5",
            "fair_price": "N/A",
            "target_price": "150",
            "price_growth_forecast_pct": "10",
            "pe": "30",
            "recommendation_text": "Test recommendation",
        }

        success, error = save_stock_recommendation_to_db(db, recommendation, webpage_id=1)

        assert success is True
        assert error is None
        assert db.inserted_payload is not None
        assert db.inserted_payload["target_price"] == 150.0
        assert db.inserted_payload["fair_price"] == 150.0

    def test_keeps_fair_price_when_both_prices_present(self):
        db = DummyRecommendationsDatabase()

        recommendation = {
            "ticker": "AMD",
            "exchange": "NASDAQ",
            "stock_name": "Advanced Micro Devices, Inc.",
            "rating": 4,
            "analysis_date": "2026-02-18",
            "fair_price": "145",
            "target_price": "150",
        }

        success, error = save_stock_recommendation_to_db(db, recommendation, webpage_id=1)

        assert success is True
        assert error is None
        assert db.inserted_payload["fair_price"] == 145.0
        assert db.inserted_payload["target_price"] == 150.0
