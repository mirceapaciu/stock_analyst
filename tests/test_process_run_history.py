"""Tests for process run history persistence."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from repositories.recommendations_db import RecommendationsDatabase


def test_process_run_history_records_completed_run(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_S3_SYNC", "false")
    db_path = tmp_path / "process_run_history_1.duckdb"
    db = RecommendationsDatabase(str(db_path))

    db.start_process("recommendations_workflow", message="started")
    db.update_process_progress("recommendations_workflow", 55)
    db.end_process("recommendations_workflow", status="COMPLETED", message="done")

    history = db.get_process_run_history("recommendations_workflow", limit=10)

    assert len(history) == 1
    run = history[0]
    assert run["process_name"] == "recommendations_workflow"
    assert run["status"] == "COMPLETED"
    assert run["message"] == "done"
    assert run["progress_pct"] == 100
    assert run["start_timestamp"] is not None
    assert run["end_timestamp"] is not None


def test_process_run_history_returns_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_S3_SYNC", "false")
    db_path = tmp_path / "process_run_history_2.duckdb"
    db = RecommendationsDatabase(str(db_path))

    db.start_process("tracked_stock_batch", message="run1")
    db.end_process("tracked_stock_batch", status="FAILED", message="failed")

    db.start_process("tracked_stock_batch", message="run2")
    db.end_process("tracked_stock_batch", status="COMPLETED", message="ok")

    history = db.get_process_run_history("tracked_stock_batch", limit=10)

    assert len(history) == 2
    assert history[0]["message"] == "ok"
    assert history[0]["status"] == "COMPLETED"
    assert history[1]["message"] == "failed"
    assert history[1]["status"] == "FAILED"


def test_snapshot_only_start_does_not_create_extra_run(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_S3_SYNC", "false")
    db_path = tmp_path / "process_run_history_3.duckdb"
    db = RecommendationsDatabase(str(db_path))

    # Scheduler-style snapshot update should not write to process_run.
    db.start_process(
        "market_price_refresh",
        message='{"pid": 1234}',
        track_run_history=False,
    )

    # Worker-style start/end owns the run history row.
    db.start_process("market_price_refresh", message="worker-start")
    db.end_process("market_price_refresh", status="COMPLETED", message="worker-done")

    history = db.get_process_run_history("market_price_refresh", limit=10)

    assert len(history) == 1
    assert history[0]["status"] == "COMPLETED"
    assert history[0]["message"] == "worker-done"


def test_init_auto_closes_preexisting_stale_started_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_S3_SYNC", "false")
    db_path = tmp_path / "process_run_history_4.duckdb"

    db = RecommendationsDatabase(str(db_path))
    db.start_process("market_price_refresh", message="legacy-start-1")
    db.start_process("market_price_refresh", message="legacy-start-2")
    db.end_process("market_price_refresh", status="COMPLETED", message="latest-completed")

    before_reopen = db.get_process_run_history("market_price_refresh", limit=10)
    open_before = [row for row in before_reopen if row["status"] == "STARTED" and row["end_timestamp"] is None]
    assert len(open_before) == 1

    reopened = RecommendationsDatabase(str(db_path))
    history = reopened.get_process_run_history("market_price_refresh", limit=10)

    stale_rows = [
        row for row in history
        if row["message"] and "Auto-closed stale STARTED run" in row["message"]
    ]
    assert len(stale_rows) == 1
    assert stale_rows[0]["status"] == "FAILED"
    assert stale_rows[0]["end_timestamp"] is not None
