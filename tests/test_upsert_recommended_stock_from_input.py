"""Unit tests for upsert_recommended_stock_from_input fallback behavior."""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from repositories.recommendations_db import RecommendationsDatabase


class TestUpsertRecommendedStockFromInput:
    def test_uses_avg_target_price_when_avg_fair_price_is_null(self, tmp_path):
        db_path = tmp_path / "test_recommendations.duckdb"
        db = RecommendationsDatabase(str(db_path))

        stock_id = db.upsert_stock(
            isin=None,
            ticker="AMD",
            exchange="NASDAQ",
            stock_name="Advanced Micro Devices, Inc.",
            mic=None,
        )

        db.insert_stock_recommendation(
            {
                "ticker": "AMD",
                "exchange": "NASDAQ",
                "stock_id": stock_id,
                "isin": None,
                "stock_name": "Advanced Micro Devices, Inc.",
                "rating_id": 4,
                "analysis_date": "2026-02-01",
                "price": 100.0,
                "fair_price": None,
                "target_price": 150.0,
                "price_growth_forecast_pct": 10.0,
                "pe": 20.0,
                "recommendation_text": "rec1",
                "quality_score": 70,
                "quality_description_words": 120,
                "quality_has_rating": True,
                "quality_reasoning_level": 2,
                "webpage_id": None,
                "entry_date": "2026-02-01",
            }
        )

        db.insert_stock_recommendation(
            {
                "ticker": "AMD",
                "exchange": "NASDAQ",
                "stock_id": stock_id,
                "isin": None,
                "stock_name": "Advanced Micro Devices, Inc.",
                "rating_id": 5,
                "analysis_date": "2026-02-02",
                "price": 105.0,
                "fair_price": None,
                "target_price": 250.0,
                "price_growth_forecast_pct": 15.0,
                "pe": 22.0,
                "recommendation_text": "rec2",
                "quality_score": 80,
                "quality_description_words": 150,
                "quality_has_rating": True,
                "quality_reasoning_level": 3,
                "webpage_id": None,
                "entry_date": "2026-02-02",
            }
        )

        db.upsert_recommended_stock_from_input(stock_id=stock_id)

        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT fair_price, target_price FROM recommended_stock WHERE stock_id = ?",
            (stock_id,),
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        fair_price, target_price = row
        assert fair_price == 200.0
        assert target_price == 200.0

    def test_prefers_avg_fair_price_when_present(self, tmp_path):
        db_path = tmp_path / "test_recommendations_with_fair.duckdb"
        db = RecommendationsDatabase(str(db_path))

        stock_id = db.upsert_stock(
            isin=None,
            ticker="MSFT",
            exchange="NASDAQ",
            stock_name="Microsoft Corporation",
            mic=None,
        )

        db.insert_stock_recommendation(
            {
                "ticker": "MSFT",
                "exchange": "NASDAQ",
                "stock_id": stock_id,
                "isin": None,
                "stock_name": "Microsoft Corporation",
                "rating_id": 4,
                "analysis_date": "2026-02-01",
                "price": 300.0,
                "fair_price": 410.0,
                "target_price": 500.0,
                "price_growth_forecast_pct": 8.0,
                "pe": 25.0,
                "recommendation_text": "rec",
                "quality_score": 75,
                "quality_description_words": 140,
                "quality_has_rating": True,
                "quality_reasoning_level": 2,
                "webpage_id": None,
                "entry_date": "2026-02-01",
            }
        )

        db.upsert_recommended_stock_from_input(stock_id=stock_id)

        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT fair_price, target_price FROM recommended_stock WHERE stock_id = ?",
            (stock_id,),
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        fair_price, target_price = row
        assert fair_price == 410.0
        assert target_price == 500.0
