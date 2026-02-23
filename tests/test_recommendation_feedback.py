"""Tests for invalid recommendation feedback flow."""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from repositories.recommendations_db import RecommendationsDatabase


class TestRecommendationFeedback:
    def test_get_input_recommendations_exposes_currency_code(self, tmp_path):
        db_path = tmp_path / "test_currency_code_query.duckdb"
        db = RecommendationsDatabase(str(db_path))

        stock_id = db.upsert_stock(
            isin=None,
            ticker="SAP",
            exchange="XETRA",
            stock_name="SAP SE",
            mic=None,
        )

        db.insert_stock_recommendation(
            {
                "ticker": "SAP",
                "exchange": "XETRA",
                "currency_code": "EUR",
                "stock_id": stock_id,
                "isin": None,
                "stock_name": "SAP SE",
                "rating_id": 4,
                "analysis_date": "2026-02-01",
                "price": 180.0,
                "fair_price": 220.0,
                "target_price": 230.0,
                "price_growth_forecast_pct": 12.0,
                "pe": 20.0,
                "recommendation_text": "rec",
                "quality_score": 80,
                "quality_description_words": 140,
                "quality_has_rating": True,
                "quality_reasoning_level": 3,
                "webpage_id": None,
                "entry_date": "2026-02-01",
            }
        )

        rows = db.get_input_recommendations_for_stock(stock_id)

        assert len(rows) == 1
        assert rows[0]["currency_code"] == "EUR"

    def test_mark_invalid_sets_flag_and_creates_feedback(self, tmp_path):
        db_path = tmp_path / "test_feedback.duckdb"
        db = RecommendationsDatabase(str(db_path))

        stock_id = db.upsert_stock(
            isin=None,
            ticker="AMD",
            exchange="NASDAQ",
            stock_name="Advanced Micro Devices, Inc.",
            mic=None,
        )

        rec_id = db.insert_stock_recommendation(
            {
                "ticker": "AMD",
                "exchange": "NASDAQ",
                "stock_id": stock_id,
                "isin": None,
                "stock_name": "Advanced Micro Devices, Inc.",
                "rating_id": 4,
                "analysis_date": "2026-02-01",
                "price": 100.0,
                "fair_price": 120.0,
                "target_price": 130.0,
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

        returned_stock_id = db.mark_recommendation_invalid(
            recommendation_id=rec_id,
            feedback_text="Price is hallucinated",
            invalid_fields=["fair_price", "target_price"],
        )

        assert returned_stock_id == stock_id

        conn = db._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT is_invalid FROM input_stock_recommendation WHERE id = ?", (rec_id,))
        assert cursor.fetchone()[0] == 1

        cursor.execute(
            "SELECT id, recommendation_id, stock_id, feedback_text FROM recommendation_feedback WHERE recommendation_id = ?",
            (rec_id,),
        )
        feedback_row = cursor.fetchone()

        assert feedback_row is not None
        feedback_id = feedback_row[0]
        assert feedback_row[1] == rec_id
        assert feedback_row[2] == stock_id
        assert feedback_row[3] == "Price is hallucinated"

        cursor.execute(
            "SELECT field_name FROM recommendation_feedback_invalid_fields WHERE feedback_id = ? ORDER BY field_name",
            (feedback_id,),
        )
        invalid_fields = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert invalid_fields == ["fair_price", "target_price"]

    def test_invalid_recommendation_excluded_from_summary_and_upsert(self, tmp_path):
        db_path = tmp_path / "test_feedback_exclusion.duckdb"
        db = RecommendationsDatabase(str(db_path))

        stock_id = db.upsert_stock(
            isin=None,
            ticker="MSFT",
            exchange="NASDAQ",
            stock_name="Microsoft Corporation",
            mic=None,
        )

        rec_id = db.insert_stock_recommendation(
            {
                "ticker": "MSFT",
                "exchange": "NASDAQ",
                "stock_id": stock_id,
                "isin": None,
                "stock_name": "Microsoft Corporation",
                "rating_id": 5,
                "analysis_date": "2026-02-01",
                "price": 300.0,
                "fair_price": 400.0,
                "target_price": 450.0,
                "price_growth_forecast_pct": 12.0,
                "pe": 25.0,
                "recommendation_text": "rec",
                "quality_score": 80,
                "quality_description_words": 140,
                "quality_has_rating": True,
                "quality_reasoning_level": 3,
                "webpage_id": None,
                "entry_date": "2026-02-01",
            }
        )

        db.mark_recommendation_invalid(
            recommendation_id=rec_id,
            feedback_text="Incorrect recommendation text",
            invalid_fields=["recommendation_text"],
        )

        summary = db.get_input_recommendations_summary_for_stock(stock_id)
        assert summary["total_count"] == 0
        assert summary["average_rating"] is None

        upserted = db.upsert_recommended_stock_from_input(stock_id=stock_id)
        assert upserted == 0

        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM recommended_stock WHERE stock_id = ?", (stock_id,))
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 0

    def test_upsert_deletes_recommended_stock_when_no_valid_inputs_for_stock(self, tmp_path):
        db_path = tmp_path / "test_feedback_delete_recommended.duckdb"
        db = RecommendationsDatabase(str(db_path))

        stock_id = db.upsert_stock(
            isin=None,
            ticker="NVDA",
            exchange="NASDAQ",
            stock_name="NVIDIA Corporation",
            mic=None,
        )

        rec_id = db.insert_stock_recommendation(
            {
                "ticker": "NVDA",
                "exchange": "NASDAQ",
                "stock_id": stock_id,
                "isin": None,
                "stock_name": "NVIDIA Corporation",
                "rating_id": 5,
                "analysis_date": "2026-02-01",
                "price": 700.0,
                "fair_price": 900.0,
                "target_price": 950.0,
                "price_growth_forecast_pct": 20.0,
                "pe": 35.0,
                "recommendation_text": "rec",
                "quality_score": 85,
                "quality_description_words": 150,
                "quality_has_rating": True,
                "quality_reasoning_level": 3,
                "webpage_id": None,
                "entry_date": "2026-02-01",
            }
        )

        # First create/update recommended_stock row from valid input
        upserted_before = db.upsert_recommended_stock_from_input(stock_id=stock_id)
        assert upserted_before == 1

        # Mark the only input recommendation as invalid
        db.mark_recommendation_invalid(
            recommendation_id=rec_id,
            feedback_text="Hallucinated values",
            invalid_fields=["fair_price", "target_price"],
        )

        # Re-upsert should delete stale recommended_stock row
        changed_rows = db.upsert_recommended_stock_from_input(stock_id=stock_id)
        assert changed_rows == 1

        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM recommended_stock WHERE stock_id = ?", (stock_id,))
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 0
