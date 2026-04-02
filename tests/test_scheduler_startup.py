"""Unit tests for scheduler startup behavior."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pandas as pd

SCRIPTS_PATH = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))


class _DummyDb:
    def __init__(self, status):
        self._status = status

    def get_process_status(self, _process_name):
        return self._status


class _SchedulerDbStub:
    def __init__(self, statuses: dict[str, dict] | None = None):
        self._statuses = statuses or {}
        self.end_calls: list[tuple[str, str, str | None]] = []
        self.start_calls: list[tuple[str, str | None]] = []

    def get_process_status(self, process_name):
        return self._statuses.get(process_name)

    def end_process(self, process_name: str, status: str = "COMPLETED", message: str | None = None):
        self.end_calls.append((process_name, status, message))
        self._statuses[process_name] = {
            "status": status,
            "message": message,
        }

    def start_process(self, process_name: str, message: str | None = None):
        self.start_calls.append((process_name, message))
        self._statuses[process_name] = {
            "status": "STARTED",
            "message": message,
        }


def test_is_discovery_overdue_when_no_status(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    monkeypatch.setattr(
        scheduler,
        "RecommendationsDatabase",
        lambda _db_path: _DummyDb(None),
    )

    assert scheduler._is_discovery_overdue() is True


def test_is_discovery_overdue_when_recent_run(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    recent = (pd.Timestamp.now(tz="UTC") - pd.to_timedelta(1, unit="h")).isoformat()
    monkeypatch.setattr(
        scheduler,
        "RecommendationsDatabase",
        lambda _db_path: _DummyDb({"end_timestamp": recent}),
    )
    monkeypatch.setattr(scheduler, "DISCOVERY_INTERVAL_HOURS", 72)

    assert scheduler._is_discovery_overdue() is False


def test_is_discovery_overdue_when_old_run(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    old = (pd.Timestamp.now(tz="UTC") - pd.to_timedelta(80, unit="h")).isoformat()
    monkeypatch.setattr(
        scheduler,
        "RecommendationsDatabase",
        lambda _db_path: _DummyDb({"end_timestamp": old}),
    )
    monkeypatch.setattr(scheduler, "DISCOVERY_INTERVAL_HOURS", 72)

    assert scheduler._is_discovery_overdue() is True


def test_extract_pid_from_json_message():
    scheduler = importlib.import_module("scheduler")

    assert scheduler._extract_pid('{"pid":12345}') == 12345


def test_verify_running_jobs_marks_failed_when_pid_missing(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    db = _SchedulerDbStub(
        statuses={
            "recommendations_workflow": {"status": "STARTED", "message": None},
            "tracked_stock_batch": {"status": "COMPLETED", "message": "ok"},
            "market_price_refresh": {"status": "COMPLETED", "message": "ok"},
        }
    )

    monkeypatch.setattr(scheduler, "RecommendationsDatabase", lambda _db_path: db)

    scheduler._verify_running_jobs_liveness()

    assert db.end_calls
    process_name, status, message = db.end_calls[0]
    assert process_name == "recommendations_workflow"
    assert status == "FAILED"
    assert "missing PID" in str(message)


def test_verify_running_jobs_marks_failed_when_pid_not_alive(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    db = _SchedulerDbStub(
        statuses={
            "recommendations_workflow": {"status": "STARTED", "message": '{"pid":99999}'},
            "tracked_stock_batch": {"status": "COMPLETED", "message": "ok"},
            "market_price_refresh": {"status": "COMPLETED", "message": "ok"},
        }
    )

    monkeypatch.setattr(scheduler, "RecommendationsDatabase", lambda _db_path: db)
    monkeypatch.setattr(scheduler, "_is_pid_alive", lambda _pid: False)

    scheduler._verify_running_jobs_liveness()

    assert db.end_calls
    process_name, status, message = db.end_calls[0]
    assert process_name == "recommendations_workflow"
    assert status == "FAILED"
    assert "dead process PID" in str(message)


def test_launch_job_subprocess_starts_process_with_pid_message(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    class _DummyProc:
        pid = 43210

    db = _SchedulerDbStub(statuses={"recommendations_workflow": None})

    monkeypatch.setattr(scheduler, "RecommendationsDatabase", lambda _db_path: db)
    monkeypatch.setattr(scheduler.subprocess, "Popen", lambda *_args, **_kwargs: _DummyProc())

    scheduler._launch_job_subprocess("discovery_workflow")

    assert db.start_calls
    process_name, message = db.start_calls[0]
    assert process_name == "recommendations_workflow"
    assert message is not None

    payload = json.loads(message)
    assert payload["pid"] == 43210
    assert payload["script"] == "run_recommendations_workflow.py"
