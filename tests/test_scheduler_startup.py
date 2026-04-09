"""Unit tests for scheduler startup behavior."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
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
        self.end_calls: list[dict] = []
        self.start_calls: list[tuple[str, str | None]] = []

    def get_process_status(self, process_name):
        return self._statuses.get(process_name)

    def end_process(
        self,
        process_name: str,
        status: str = "COMPLETED",
        message: str | None = None,
        exit_code: int | None = None,
        failure_log_tail: str | None = None,
    ):
        self.end_calls.append(
            {
                "process_name": process_name,
                "status": status,
                "message": message,
                "exit_code": exit_code,
                "failure_log_tail": failure_log_tail,
            }
        )
        self._statuses[process_name] = {
            "status": status,
            "message": message,
            "exit_code": exit_code,
            "failure_log_tail": failure_log_tail,
        }

    def start_process(
        self,
        process_name: str,
        message: str | None = None,
        track_run_history: bool = True,
    ):
        self.start_calls.append((process_name, message))
        self._statuses[process_name] = {
            "status": "STARTED",
            "message": message,
        }

    def touch_process_heartbeat(self, process_name: str, status: str = "HEARTBEAT", message: str | None = None):
        self._statuses[process_name] = {
            "status": status,
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
    call = db.end_calls[0]
    assert call["process_name"] == "recommendations_workflow"
    assert call["status"] == "FAILED"
    assert "missing PID" in str(call["message"])
    assert call["exit_code"] is None


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
    call = db.end_calls[0]
    assert call["process_name"] == "recommendations_workflow"
    assert call["status"] == "FAILED"
    assert "dead process PID" in str(call["message"])
    assert call["exit_code"] is None


def test_verify_running_jobs_persists_exit_code_and_command(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    db = _SchedulerDbStub(
        statuses={
            "recommendations_workflow": {
                "status": "STARTED",
                "message": '{"pid":43210,"command":["python","run_recommendations_workflow.py"]}',
            },
            "tracked_stock_batch": {"status": "COMPLETED", "message": "ok"},
            "market_price_refresh": {"status": "COMPLETED", "message": "ok"},
        }
    )

    class _ExitedProc:
        pid = 43210

        def poll(self):
            return 1

    monkeypatch.setattr(scheduler, "RecommendationsDatabase", lambda _db_path: db)
    monkeypatch.setattr(
        scheduler,
        "ACTIVE_CHILD_PROCESSES",
        {"recommendations_workflow": _ExitedProc()},
    )

    scheduler._verify_running_jobs_liveness()

    assert db.end_calls
    call = db.end_calls[0]
    assert call["process_name"] == "recommendations_workflow"
    assert call["status"] == "FAILED"
    assert "exit_code=1" in str(call["message"])
    assert "run_recommendations_workflow.py" in str(call["message"])
    assert call["exit_code"] == 1


def test_verify_running_jobs_captures_failure_log_tail(monkeypatch, tmp_path):
    scheduler = importlib.import_module("scheduler")

    log_path = tmp_path / "scheduler_job_failure.log"
    log_path.write_text("line 1\nline 2\nfatal error happened\n", encoding="utf-8")

    db = _SchedulerDbStub(
        statuses={
            "recommendations_workflow": {
                "status": "STARTED",
                "message": json.dumps(
                    {
                        "pid": 54321,
                        "command": ["python", "run_recommendations_workflow.py"],
                        "log_path": str(log_path),
                    }
                ),
            },
            "tracked_stock_batch": {"status": "COMPLETED", "message": "ok"},
            "market_price_refresh": {"status": "COMPLETED", "message": "ok"},
        }
    )

    class _ExitedProc:
        pid = 54321

        def poll(self):
            return 2

    monkeypatch.setattr(scheduler, "RecommendationsDatabase", lambda _db_path: db)
    monkeypatch.setattr(
        scheduler,
        "ACTIVE_CHILD_PROCESSES",
        {"recommendations_workflow": _ExitedProc()},
    )
    monkeypatch.setattr(
        scheduler,
        "ACTIVE_CHILD_PROCESS_LOG_PATHS",
        {"recommendations_workflow": log_path},
    )
    monkeypatch.setattr(
        scheduler,
        "ACTIVE_CHILD_PROCESS_LOG_HANDLES",
        {},
    )

    scheduler._verify_running_jobs_liveness()

    assert db.end_calls
    call = db.end_calls[0]
    assert call["exit_code"] == 2
    assert "fatal error happened" in str(call["failure_log_tail"])


def test_launch_job_subprocess_starts_process_with_pid_message(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    class _DummyProc:
        pid = 43210

    popen_calls: list[dict] = []

    def _fake_popen(*args, **kwargs):
        popen_calls.append({"args": args, "kwargs": kwargs})
        return _DummyProc()

    db = _SchedulerDbStub(statuses={"recommendations_workflow": None})

    monkeypatch.setattr(scheduler, "RecommendationsDatabase", lambda _db_path: db)
    monkeypatch.setattr(scheduler.subprocess, "Popen", _fake_popen)

    scheduler._launch_job_subprocess("discovery_workflow")

    assert popen_calls
    expected_cwd = str(Path(scheduler.__file__).resolve().parent.parent)
    assert popen_calls[0]["kwargs"].get("cwd") == expected_cwd
    assert popen_calls[0]["kwargs"].get("stdout") is not None
    assert popen_calls[0]["kwargs"].get("stderr") == scheduler.subprocess.STDOUT
    assert popen_calls[0]["kwargs"].get("text") is True

    assert db.start_calls
    process_name, message = db.start_calls[0]
    assert process_name == "recommendations_workflow"
    assert message is not None

    payload = json.loads(message)
    assert payload["pid"] == 43210
    assert payload["script"] == "run_recommendations_workflow.py"
    assert payload["log_path"] is not None
    assert "run_recommendations_workflow.py" in " ".join(payload["command"])


def test_record_scheduler_next_run_times_uses_trigger_fallback(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    class _DummyTrigger:
        def __init__(self, next_fire_time: datetime):
            self._next_fire_time = next_fire_time

        def get_next_fire_time(self, _previous_fire_time, _now):
            return self._next_fire_time

    class _DummyJob:
        def __init__(self, trigger):
            self.next_run_time = None
            self.trigger = trigger

    class _DummyScheduler:
        def __init__(self, jobs: dict[str, object]):
            self._jobs = jobs

        def get_job(self, job_id: str):
            return self._jobs.get(job_id)

    expected_next_run = datetime(2099, 1, 1, 0, 0, tzinfo=timezone.utc)
    dummy_scheduler = _DummyScheduler(
        {
            "discovery_workflow": _DummyJob(_DummyTrigger(expected_next_run)),
            "tracked_stock_batch": _DummyJob(_DummyTrigger(expected_next_run)),
            "market_price_refresh": _DummyJob(_DummyTrigger(expected_next_run)),
        }
    )

    db = _SchedulerDbStub()
    monkeypatch.setattr(scheduler, "RecommendationsDatabase", lambda _db_path: db)

    scheduler._record_scheduler_next_run_times(dummy_scheduler)

    discovery_status = db.get_process_status("scheduler_next_run_discovery_workflow")
    tracked_status = db.get_process_status("scheduler_next_run_tracked_stock_batch")
    market_status = db.get_process_status("scheduler_next_run_market_price_refresh")

    assert discovery_status is not None
    assert tracked_status is not None
    assert market_status is not None

    assert discovery_status["message"] == expected_next_run.isoformat()
    assert tracked_status["message"] == expected_next_run.isoformat()
    assert market_status["message"] == expected_next_run.isoformat()


def test_apply_requested_starts_consumes_request_and_updates_job(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    requested_time = datetime.now(timezone.utc).isoformat()
    db = _SchedulerDbStub(
        statuses={
            "scheduler_next_start_discovery_workflow": {
                "status": "REQUESTED",
                "message": requested_time,
            }
        }
    )

    class _DummyJob:
        def __init__(self):
            self.next_run_time = None
            self.modified_next_run_time = None

        def modify(self, next_run_time=None):
            self.modified_next_run_time = next_run_time

    class _DummyScheduler:
        def __init__(self, job):
            self._job = job

        def get_job(self, job_id: str):
            if job_id == "discovery_workflow":
                return self._job
            return None

    job = _DummyJob()
    dummy_scheduler = _DummyScheduler(job)

    monkeypatch.setattr(scheduler, "RecommendationsDatabase", lambda _db_path: db)

    scheduler._apply_requested_starts(dummy_scheduler)

    request_status = db.get_process_status("scheduler_next_start_discovery_workflow")
    assert request_status is not None
    assert request_status["status"] == "CONSUMED"
    assert request_status["message"] is not None
    assert job.modified_next_run_time is not None


def test_run_job_with_group_lock_queues_when_other_job_holds_lock(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    monkeypatch.setattr(
        scheduler,
        "JOB_GROUP_BY_JOB_ID",
        {
            "discovery_workflow": "recommendations_workflows",
            "tracked_stock_batch": "recommendations_workflows",
        },
    )
    monkeypatch.setattr(
        scheduler,
        "ACTIVE_JOB_GROUP_LOCKS",
        {"recommendations_workflows": "discovery_workflow"},
    )
    monkeypatch.setattr(scheduler, "WAITING_JOB_DUE_TIMES_BY_GROUP", {})

    launch_calls: list[str] = []
    monkeypatch.setattr(
        scheduler,
        "_launch_job_subprocess",
        lambda job_id: launch_calls.append(job_id) or True,
    )

    scheduler._run_job_with_group_lock("tracked_stock_batch")

    assert not launch_calls
    waiting = scheduler.WAITING_JOB_DUE_TIMES_BY_GROUP.get("recommendations_workflows")
    assert waiting is not None
    assert "tracked_stock_batch" in waiting


def test_release_group_lock_starts_waiting_job_by_earliest_due_time(monkeypatch):
    scheduler = importlib.import_module("scheduler")

    class _DummyJob:
        def __init__(self):
            self.modified_next_run_time = None

        def modify(self, next_run_time=None):
            self.modified_next_run_time = next_run_time

    class _DummyScheduler:
        def __init__(self):
            self.jobs = {
                "discovery_workflow": _DummyJob(),
                "tracked_stock_batch": _DummyJob(),
            }

        def get_job(self, job_id: str):
            return self.jobs.get(job_id)

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        scheduler,
        "JOB_GROUP_BY_JOB_ID",
        {
            "discovery_workflow": "recommendations_workflows",
            "tracked_stock_batch": "recommendations_workflows",
        },
    )
    monkeypatch.setattr(
        scheduler,
        "ACTIVE_JOB_GROUP_LOCKS",
        {"recommendations_workflows": "discovery_workflow"},
    )
    monkeypatch.setattr(
        scheduler,
        "WAITING_JOB_DUE_TIMES_BY_GROUP",
        {
            "recommendations_workflows": {
                "tracked_stock_batch": now,
            }
        },
    )

    dummy_scheduler = _DummyScheduler()
    monkeypatch.setattr(scheduler, "ACTIVE_SCHEDULER", dummy_scheduler)

    scheduler._release_group_lock_for_job("discovery_workflow", reason="completed")

    assert "recommendations_workflows" not in scheduler.ACTIVE_JOB_GROUP_LOCKS
    assert "recommendations_workflows" not in scheduler.WAITING_JOB_DUE_TIMES_BY_GROUP
    assert dummy_scheduler.jobs["tracked_stock_batch"].modified_next_run_time is not None


def test_build_scheduler_group_maps_rejects_unknown_job_id():
    scheduler = importlib.import_module("scheduler")

    try:
        scheduler._build_scheduler_group_maps(
            [
                {
                    "job_group": "recommendations_workflows",
                    "jobs": ["discovery_workflow", "unknown_job"],
                }
            ]
        )
    except ValueError as error:
        assert "Unknown scheduler job id" in str(error)
    else:
        raise AssertionError("Expected ValueError for unknown scheduler job id")
