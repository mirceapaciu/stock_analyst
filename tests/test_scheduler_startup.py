"""Unit tests for scheduler startup behavior."""

from __future__ import annotations

import importlib
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
