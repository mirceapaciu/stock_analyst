"""Unit tests for tracked sweep and CSE usage persistence helpers."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from repositories.recommendations_db import RecommendationsDatabase


class TestBatchSchedulerDatabase:
    @staticmethod
    def _seed_recommended_stock(db: RecommendationsDatabase, ticker: str, rating: float, last_analysis_date: str) -> int:
        stock_id = db.upsert_stock(
            isin=None,
            ticker=ticker,
            exchange="NASDAQ",
            stock_name=f"{ticker} Corp",
            mic=None,
        )

        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO recommended_stock (stock_id, rating, last_analysis_date, entry_date)
            VALUES (?, ?, ?, ?)
            """,
            (stock_id, rating, last_analysis_date, last_analysis_date),
        )
        conn.commit()
        conn.close()

        return stock_id

    def test_get_tracked_tickers_by_min_rating_orders_by_staleness(self, tmp_path):
        db = RecommendationsDatabase(str(tmp_path / "batch_scheduler_tickers.duckdb"))

        self._seed_recommended_stock(db, "AAPL", 4.5, "2026-01-10")
        self._seed_recommended_stock(db, "MSFT", 4.2, "2025-12-31")
        self._seed_recommended_stock(db, "GOOG", 3.5, "2025-12-01")

        tickers = db.get_tracked_tickers_by_min_rating(min_rating=4.0)

        assert tickers == ["MSFT", "AAPL"]

    def test_get_or_start_sweep_creates_new_schedule_when_missing(self, tmp_path):
        db = RecommendationsDatabase(str(tmp_path / "batch_scheduler_new_sweep.duckdb"))

        self._seed_recommended_stock(db, "TSLA", 4.6, "2026-01-01")
        self._seed_recommended_stock(db, "AMZN", 4.1, "2026-01-03")

        sweep = db.get_or_start_sweep(
            workflow_type="tracked_stock",
            min_rating=4.0,
            stale_days=14,
        )

        assert sweep.workflow_type == "tracked_stock"
        assert sweep.batch_index == 0
        assert sweep.total_batches >= 1
        assert sweep.ticker_list == ["TSLA", "AMZN"]

    def test_get_or_start_sweep_refreshes_stale_schedule(self, tmp_path):
        db = RecommendationsDatabase(str(tmp_path / "batch_scheduler_stale_sweep.duckdb"))

        self._seed_recommended_stock(db, "NVDA", 4.8, "2026-01-02")

        stale_start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO batch_schedule (
                workflow_type, ticker_list, batch_index, total_batches,
                sweep_started_at, last_batch_at, last_batch_status, sweep_completed_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)
            """,
            ("tracked_stock", '["OLD"]', 0, 1, stale_start),
        )
        conn.commit()
        conn.close()

        sweep = db.get_or_start_sweep(
            workflow_type="tracked_stock",
            min_rating=4.0,
            stale_days=14,
        )

        assert "OLD" not in sweep.ticker_list
        assert sweep.ticker_list == ["NVDA"]
        assert sweep.batch_index == 0

    def test_advance_sweep_moves_cursor_and_marks_completion(self, tmp_path):
        db = RecommendationsDatabase(str(tmp_path / "batch_scheduler_advance.duckdb"))

        self._seed_recommended_stock(db, "AAPL", 4.5, "2026-01-01")
        self._seed_recommended_stock(db, "MSFT", 4.6, "2026-01-02")
        self._seed_recommended_stock(db, "NFLX", 4.7, "2026-01-03")

        sweep = db.get_or_start_sweep("tracked_stock", min_rating=4.0, stale_days=14)

        first_batch = sweep.next_batch(batch_size=2)
        db.advance_sweep("tracked_stock", processed_tickers=first_batch, status="COMPLETED")

        conn = db._get_connection()
        conn.row_factory = None
        cursor = conn.cursor()
        cursor.execute(
            "SELECT batch_index, last_batch_status, sweep_completed_at FROM batch_schedule WHERE workflow_type = ?",
            ("tracked_stock",),
        )
        batch_index, last_batch_status, sweep_completed_at = cursor.fetchone()
        conn.close()

        assert batch_index == 2
        assert last_batch_status == "COMPLETED"
        assert sweep_completed_at is None

        follow_up_sweep = db.get_or_start_sweep("tracked_stock", min_rating=4.0, stale_days=14)
        second_batch = follow_up_sweep.next_batch(batch_size=2)
        db.advance_sweep("tracked_stock", processed_tickers=second_batch, status="COMPLETED")

        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT batch_index, sweep_completed_at FROM batch_schedule WHERE workflow_type = ?",
            ("tracked_stock",),
        )
        completed_batch_index, completed_at = cursor.fetchone()
        conn.close()

        assert completed_batch_index == 3
        assert completed_at is not None

    def test_cse_usage_log_totals_calls_for_today(self, tmp_path):
        db = RecommendationsDatabase(str(tmp_path / "batch_scheduler_cse_usage.duckdb"))

        db.log_cse_usage("discovery", 18)
        db.log_cse_usage("tracked_stock", 5)

        assert db.get_cse_calls_today() == 23

    def test_advance_sweep_skips_batch_after_three_failures(self, tmp_path):
        db = RecommendationsDatabase(str(tmp_path / "batch_scheduler_failures.duckdb"))

        self._seed_recommended_stock(db, "AAPL", 4.5, "2026-01-01")
        self._seed_recommended_stock(db, "MSFT", 4.6, "2026-01-02")
        self._seed_recommended_stock(db, "NVDA", 4.7, "2026-01-03")

        db.get_or_start_sweep("tracked_stock", min_rating=4.0, stale_days=14)

        db.advance_sweep("tracked_stock", processed_tickers=[], status="FAILED")
        db.advance_sweep("tracked_stock", processed_tickers=[], status="FAILED")
        db.advance_sweep("tracked_stock", processed_tickers=[], status="FAILED")

        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT batch_index, last_batch_status, consecutive_failures, sweep_completed_at
            FROM batch_schedule
            WHERE workflow_type = ?
            """,
            ("tracked_stock",),
        )
        batch_index, last_status, consecutive_failures, sweep_completed_at = cursor.fetchone()
        conn.close()

        assert batch_index > 0
        assert last_status == "FAILED_SKIPPED"
        assert consecutive_failures == 0
        assert sweep_completed_at is not None
