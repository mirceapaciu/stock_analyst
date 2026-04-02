"""Tests for the Streamlit job dashboard page."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


PAGE_PATH = Path(__file__).resolve().parent.parent / "src" / "ui" / "pages" / "4_Job_Dashboard.py"


class _Sidebar:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def header(self, *_args, **_kwargs):
        return None


class _Column:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def metric(self, *_args, **_kwargs):
        return None


class _CacheData:
    def __call__(self, *_args, **_kwargs):
        def decorator(func):
            return func

        return decorator

    def clear(self):
        return None


class _StreamlitStub(ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.cache_data = _CacheData()
        self.sidebar = _Sidebar()

    def set_page_config(self, *_args, **_kwargs):
        return None

    def stop(self):
        raise RuntimeError("stop should not be called in test")

    def title(self, *_args, **_kwargs):
        return None

    def markdown(self, *_args, **_kwargs):
        return None

    def header(self, *_args, **_kwargs):
        return None

    def button(self, *_args, **_kwargs):
        return False

    def rerun(self):
        return None

    def success(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None

    def columns(self, count):
        return [_Column() for _ in range(count)]

    def metric(self, *_args, **_kwargs):
        return None

    def dataframe(self, *_args, **_kwargs):
        return None


class _RecommendationsDbStub:
    def __init__(self, _db_path):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def get_process_status(self, process_name):
        if process_name == "scheduler_heartbeat":
            return {"status": "HEARTBEAT", "end_timestamp": "2099-01-01T00:00:00Z"}
        if process_name == "scheduler_next_run_discovery_workflow":
            return {"status": "SCHEDULED", "message": "2099-01-03T00:00:00+00:00"}
        if process_name == "scheduler_next_run_tracked_stock_batch":
            return {"status": "SCHEDULED", "message": "2099-01-03T00:00:00+00:00"}
        if process_name == "scheduler_next_run_market_price_refresh":
            return {"status": "SCHEDULED", "message": "2099-01-02T00:00:00+00:00"}
        return {"status": "COMPLETED", "end_timestamp": "2099-01-01T00:00:00Z", "message": "ok"}

    def get_batch_schedule_status(self, _workflow_type):
        return None


class _RecommendationsDbStubWithPid(_RecommendationsDbStub):
    def get_process_status(self, process_name):
        if process_name == "recommendations_workflow":
            return {
                "status": "STARTED",
                "start_timestamp": "2099-01-01T00:00:00Z",
                "message": '{"pid": 12345, "script": "run_recommendations_workflow.py"}',
            }
        return super().get_process_status(process_name)


def _load_dashboard_module(monkeypatch, market_refresh_hours: int = 24):
    streamlit_stub = _StreamlitStub()
    monkeypatch.setitem(sys.modules, "streamlit", streamlit_stub)

    auth_module = ModuleType("utils.auth")
    auth_module.check_password = lambda: True
    monkeypatch.setitem(sys.modules, "utils.auth", auth_module)

    config_module = ModuleType("config")
    config_module.DISCOVERY_INTERVAL_HOURS = 72
    config_module.TRACKED_BATCH_INTERVAL_HOURS = 72
    config_module.MARKET_PRICE_REFRESH_INTERVAL_HOURS = market_refresh_hours
    config_module.RECOMMENDATIONS_DB_PATH = ":memory:"
    monkeypatch.setitem(sys.modules, "config", config_module)

    repo_module = ModuleType("repositories.recommendations_db")
    repo_module.RecommendationsDatabase = _RecommendationsDbStub
    monkeypatch.setitem(sys.modules, "repositories.recommendations_db", repo_module)

    spec = importlib.util.spec_from_file_location("job_dashboard_page_test", PAGE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_dashboard_module_with_repo_stub(
    monkeypatch,
    repo_stub_cls,
    market_refresh_hours: int = 24,
):
    streamlit_stub = _StreamlitStub()
    monkeypatch.setitem(sys.modules, "streamlit", streamlit_stub)

    auth_module = ModuleType("utils.auth")
    auth_module.check_password = lambda: True
    monkeypatch.setitem(sys.modules, "utils.auth", auth_module)

    config_module = ModuleType("config")
    config_module.DISCOVERY_INTERVAL_HOURS = 72
    config_module.TRACKED_BATCH_INTERVAL_HOURS = 72
    config_module.MARKET_PRICE_REFRESH_INTERVAL_HOURS = market_refresh_hours
    config_module.RECOMMENDATIONS_DB_PATH = ":memory:"
    monkeypatch.setitem(sys.modules, "config", config_module)

    repo_module = ModuleType("repositories.recommendations_db")
    repo_module.RecommendationsDatabase = repo_stub_cls
    monkeypatch.setitem(sys.modules, "repositories.recommendations_db", repo_module)

    spec = importlib.util.spec_from_file_location("job_dashboard_page_test", PAGE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_market_price_refresh_frequency_uses_market_refresh_interval(monkeypatch):
    module = _load_dashboard_module(monkeypatch, market_refresh_hours=24)

    rows, _heartbeat = module.load_job_dashboard_rows()
    market_row = next(row for row in rows if row["Job Type"] == "Market price refresh")

    assert market_row["Schedule Frequency (days)"] == "Every 1 day(s)"
    assert market_row["Next Scheduled Run"] == "2099-01-02T00:00:00+00:00"
    assert market_row["Job PID"] == "N/A"
    assert "Due" not in market_row


def test_dashboard_extracts_job_pid_from_process_message(monkeypatch):
    module = _load_dashboard_module_with_repo_stub(monkeypatch, _RecommendationsDbStubWithPid)

    rows, _heartbeat = module.load_job_dashboard_rows()
    discovery_row = next(row for row in rows if row["Job Type"] == "Stock recommendation discovery")

    assert discovery_row["Status"] == "Running"
    assert discovery_row["Job PID"] == "12345"


def test_request_job_start_now_skips_when_job_is_running(monkeypatch):
    module = _load_dashboard_module(monkeypatch)

    class _DbStub:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def get_process_status(self, _process_name):
            return {
                "status": "STARTED",
                "message": '{"pid":12345,"script":"run_recommendations_workflow.py"}',
            }

        def touch_process_heartbeat(self, *_args, **_kwargs):
            raise AssertionError("touch_process_heartbeat should not be called for running process")

    monkeypatch.setattr(module, "RecommendationsDatabase", lambda _db_path: _DbStub())

    started, message = module._request_job_start_now("Stock recommendation discovery")

    assert started is False
    assert "already running" in message


def test_request_job_start_now_persists_requested_timestamp(monkeypatch):
    module = _load_dashboard_module(monkeypatch)

    class _DbStub:
        def __init__(self):
            self.request_calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def get_process_status(self, _process_name):
            return None

        def touch_process_heartbeat(self, process_name, status="HEARTBEAT", message=None):
            self.request_calls.append((process_name, status, message))

    db = _DbStub()
    monkeypatch.setattr(module, "RecommendationsDatabase", lambda _db_path: db)

    started, message = module._request_job_start_now("Stock recommendation discovery")

    assert started is True
    assert "Queued" in message
    assert len(db.request_calls) == 1
    process_name, status, payload = db.request_calls[0]
    assert process_name == "scheduler_next_start_discovery_workflow"
    assert status == "REQUESTED"
    assert payload is not None
