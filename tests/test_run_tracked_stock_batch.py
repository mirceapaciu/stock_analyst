"""Unit tests for tracked batch runner script behavior."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# Add project root and scripts folder to import standalone scripts
project_root = Path(__file__).parent.parent
scripts_path = project_root / "scripts"
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(scripts_path))

import run_tracked_stock_batch


class DummyDatabase:
    def __init__(self, process_status):
        self._process_status = process_status
        self.start_process_calls = 0

    def get_process_status(self, process_name: str):
        return self._process_status

    def start_process(self, process_name: str) -> None:
        self.start_process_calls += 1


class TestRunTrackedStockBatch:
    def test_batch_concurrency_guard_skips_when_process_is_running(self):
        process_status = {
            "status": "STARTED",
            "start_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        db = DummyDatabase(process_status=process_status)

        with patch("run_tracked_stock_batch.RecommendationsDatabase", return_value=db):
            with patch("run_tracked_stock_batch.create_workflow") as mock_create_workflow:
                result = run_tracked_stock_batch.run_tracked_stock_batch()

        assert result == 0
        assert db.start_process_calls == 0
        mock_create_workflow.assert_not_called()
