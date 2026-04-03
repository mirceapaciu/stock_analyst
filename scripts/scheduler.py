"""Schedule discovery and tracked-stock workflows in one process."""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

import pandas as pd
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from config import DISCOVERY_INTERVAL_HOURS, MARKET_PRICE_REFRESH_INTERVAL_HOURS, SCHEDULER_JOBSTORE_URL, TRACKED_BATCH_INTERVAL_HOURS
from config import RECOMMENDATIONS_DB_PATH
from repositories.recommendations_db import RecommendationsDatabase
from utils.logger import setup_logging

setup_logging()

logger = logging.getLogger("workflow_scheduler")

SCHEDULER_HEARTBEAT_PROCESS = "scheduler_heartbeat"
SCHEDULER_HEARTBEAT_INTERVAL_SECONDS = 60
SCHEDULER_NEXT_RUN_PROCESS_BY_JOB_ID = {
    "discovery_workflow": "scheduler_next_run_discovery_workflow",
    "tracked_stock_batch": "scheduler_next_run_tracked_stock_batch",
    "market_price_refresh": "scheduler_next_run_market_price_refresh",
}
SCHEDULER_NEXT_START_REQUEST_PROCESS_BY_JOB_ID = {
    "discovery_workflow": "scheduler_next_start_discovery_workflow",
    "tracked_stock_batch": "scheduler_next_start_tracked_stock_batch",
    "market_price_refresh": "scheduler_next_start_market_price_refresh",
}
JOB_PROCESS_BY_JOB_ID = {
    "discovery_workflow": "recommendations_workflow",
    "tracked_stock_batch": "tracked_stock_batch",
    "market_price_refresh": "market_price_refresh",
}
JOB_SCRIPT_BY_JOB_ID = {
    "discovery_workflow": "run_recommendations_workflow.py",
    "tracked_stock_batch": "run_tracked_stock_batch.py",
    "market_price_refresh": "update_stale_market_prices.py",
}
ACTIVE_SCHEDULER: BlockingScheduler | None = None
ACTIVE_CHILD_PROCESSES: dict[str, subprocess.Popen] = {}
ACTIVE_CHILD_PROCESS_LOG_PATHS: dict[str, Path] = {}
ACTIVE_CHILD_PROCESS_LOG_HANDLES: dict[str, TextIO] = {}
FAILED_LOG_TAIL_MAX_LINES = 80
FAILED_LOG_TAIL_MAX_CHARS = 4000


def _script_path(script_name: str) -> Path:
    return Path(__file__).resolve().parent / script_name


def _repo_root_path() -> Path:
    return Path(__file__).resolve().parent.parent


def _build_process_message(
    pid: int,
    script_name: str,
    command: list[str],
    log_path: str | None = None,
) -> str:
    return json.dumps(
        {
            "pid": pid,
            "script": script_name,
            "command": command,
            "log_path": log_path,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "started_by": "scheduler",
        },
        separators=(",", ":"),
    )


def _extract_process_payload(message: str | None) -> dict | None:
    if not message:
        return None

    raw_message = str(message).strip()
    if not raw_message:
        return None

    try:
        payload = json.loads(raw_message)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def _extract_pid(message: str | None) -> int | None:
    if not message:
        return None

    payload = _extract_process_payload(message)
    if payload is not None:
        pid_value = payload.get("pid")
        try:
            return int(pid_value) if pid_value is not None else None
        except (TypeError, ValueError):
            return None

    raw_message = str(message).strip()
    if not raw_message:
        return None

    try:
        return int(raw_message)
    except ValueError:
        return None


def _extract_command(message: str | None) -> str | None:
    payload = _extract_process_payload(message)
    if payload is None:
        return None

    command = payload.get("command")
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    if isinstance(command, str):
        return command
    return None


def _extract_process_log_path(message: str | None) -> str | None:
    payload = _extract_process_payload(message)
    if payload is None:
        return None

    log_path = payload.get("log_path")
    if isinstance(log_path, str):
        stripped = log_path.strip()
        return stripped or None
    return None


def _scheduler_job_log_dir() -> Path:
    log_dir = _repo_root_path() / "logs" / "app" / "scheduler_jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _build_job_log_path(process_name: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_process_name = process_name.replace("/", "_").replace("\\", "_")
    return _scheduler_job_log_dir() / f"{safe_process_name}_{timestamp}.log"


def _read_log_tail(log_path: str | Path | None) -> str | None:
    if not log_path:
        return None

    try:
        candidate = Path(log_path)
    except Exception:
        return None

    if not candidate.exists() or not candidate.is_file():
        return None

    try:
        lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    if not lines:
        return None

    tail = "\n".join(lines[-FAILED_LOG_TAIL_MAX_LINES:]).strip()
    if not tail:
        return None

    if len(tail) > FAILED_LOG_TAIL_MAX_CHARS:
        tail = tail[-FAILED_LOG_TAIL_MAX_CHARS:]
    return tail


def _cleanup_child_tracking(process_name: str) -> None:
    log_handle = ACTIVE_CHILD_PROCESS_LOG_HANDLES.pop(process_name, None)
    if log_handle is not None:
        try:
            log_handle.flush()
            log_handle.close()
        except Exception:
            pass

    ACTIVE_CHILD_PROCESS_LOG_PATHS.pop(process_name, None)
    ACTIVE_CHILD_PROCESSES.pop(process_name, None)


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _verify_running_jobs_liveness() -> None:
    db = RecommendationsDatabase(RECOMMENDATIONS_DB_PATH)

    for process_name in JOB_PROCESS_BY_JOB_ID.values():
        status = db.get_process_status(process_name)
        if not status or str(status.get("status") or "").strip().upper() != "STARTED":
            _cleanup_child_tracking(process_name)
            continue

        raw_message = status.get("message")
        pid = _extract_pid(raw_message)
        command_text = _extract_command(raw_message) or "unknown"
        persisted_log_path = _extract_process_log_path(raw_message)
        child_process = ACTIVE_CHILD_PROCESSES.get(process_name)

        if child_process is not None:
            exit_code = child_process.poll()
            if exit_code is None:
                continue

            live_log_path = ACTIVE_CHILD_PROCESS_LOG_PATHS.get(process_name)
            log_tail = _read_log_tail(live_log_path)

            active_pid = child_process.pid
            failure_message = (
                f"Scheduler detected dead process PID {active_pid}; "
                f"exit_code={exit_code}; command={command_text}"
            )
            logger.error("%s for process '%s'", failure_message, process_name)
            db.end_process(
                process_name,
                "FAILED",
                failure_message,
                exit_code=exit_code,
                failure_log_tail=log_tail,
            )
            _cleanup_child_tracking(process_name)
            continue

        if pid is None:
            failure_message = "Scheduler could not verify running job: missing PID metadata"
            failure_log_tail = _read_log_tail(persisted_log_path)
            logger.error("%s for process '%s'", failure_message, process_name)
            db.end_process(
                process_name,
                "FAILED",
                failure_message,
                exit_code=None,
                failure_log_tail=failure_log_tail,
            )
            _cleanup_child_tracking(process_name)
            continue

        if _is_pid_alive(pid):
            continue

        failure_message = (
            f"Scheduler detected dead process PID {pid}; "
            f"exit_code=unknown; command={command_text}"
        )
        failure_log_tail = _read_log_tail(persisted_log_path)
        logger.error("%s for process '%s'", failure_message, process_name)
        db.end_process(
            process_name,
            "FAILED",
            failure_message,
            exit_code=None,
            failure_log_tail=failure_log_tail,
        )
        _cleanup_child_tracking(process_name)


def _launch_job_subprocess(job_id: str) -> None:
    process_name = JOB_PROCESS_BY_JOB_ID[job_id]
    script_name = JOB_SCRIPT_BY_JOB_ID[job_id]
    db = RecommendationsDatabase(RECOMMENDATIONS_DB_PATH)

    existing_status = db.get_process_status(process_name)
    if existing_status and str(existing_status.get("status") or "").strip().upper() == "STARTED":
        existing_pid = _extract_pid(existing_status.get("message"))
        if existing_pid and _is_pid_alive(existing_pid):
            logger.warning(
                "Skipping launch for '%s': PID %s is still running",
                process_name,
                existing_pid,
            )
            return

        stale_message = (
            f"Scheduler recovered stale STARTED status before relaunch; previous PID={existing_pid}"
        )
        logger.warning("%s for process '%s'", stale_message, process_name)
        db.end_process(process_name, "FAILED", stale_message, exit_code=None, failure_log_tail=None)

    _cleanup_child_tracking(process_name)

    script_path = _script_path(script_name)
    log_path = _build_job_log_path(process_name)
    log_handle = open(log_path, "a", encoding="utf-8", errors="replace")
    try:
        process = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=str(_repo_root_path()),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception:
        log_handle.close()
        raise
    command = [sys.executable, str(script_path)]
    ACTIVE_CHILD_PROCESSES[process_name] = process
    ACTIVE_CHILD_PROCESS_LOG_PATHS[process_name] = log_path
    ACTIVE_CHILD_PROCESS_LOG_HANDLES[process_name] = log_handle
    db.start_process(
        process_name,
        message=_build_process_message(process.pid, script_name, command, str(log_path)),
        track_run_history=False,
    )
    logger.info("Launched '%s' as PID %s (logs: %s)", process_name, process.pid, log_path)


def _run_discovery_workflow_subprocess() -> None:
    _launch_job_subprocess("discovery_workflow")


def _run_tracked_stock_batch_subprocess() -> None:
    _launch_job_subprocess("tracked_stock_batch")


def _run_market_price_refresh_subprocess() -> None:
    _launch_job_subprocess("market_price_refresh")


def _record_scheduler_heartbeat() -> None:
    """Persist a heartbeat so the dashboard can detect that the scheduler is alive."""
    RecommendationsDatabase(RECOMMENDATIONS_DB_PATH).touch_process_heartbeat(
        SCHEDULER_HEARTBEAT_PROCESS
    )


def _resolve_job_next_run_time(job, now_utc: datetime) -> datetime | None:
    """Resolve a job next run time, including tentative jobs before scheduler.start()."""
    if not job:
        return None

    explicit_next_run = getattr(job, "next_run_time", None)
    if explicit_next_run is not None:
        return explicit_next_run

    trigger = getattr(job, "trigger", None)
    if trigger is None:
        return None

    get_next_fire_time = getattr(trigger, "get_next_fire_time", None)
    if not callable(get_next_fire_time):
        return None

    try:
        return get_next_fire_time(None, now_utc)
    except Exception:
        return None


def _record_scheduler_next_run_times(scheduler: BlockingScheduler) -> None:
    """Persist each job's next run timestamp for dashboard visibility."""
    db = RecommendationsDatabase(RECOMMENDATIONS_DB_PATH)
    now_utc = datetime.now(timezone.utc)

    for job_id, process_name in SCHEDULER_NEXT_RUN_PROCESS_BY_JOB_ID.items():
        job = scheduler.get_job(job_id)
        next_run_attr = _resolve_job_next_run_time(job, now_utc)
        next_run_time = next_run_attr.isoformat() if next_run_attr else "N/A"
        db.touch_process_heartbeat(
            process_name,
            status="SCHEDULED",
            message=next_run_time,
        )


def _apply_requested_starts(scheduler: BlockingScheduler) -> None:
    """Apply dashboard manual start requests by setting job next_run_time."""
    db = RecommendationsDatabase(RECOMMENDATIONS_DB_PATH)
    now_utc = datetime.now(timezone.utc)

    for job_id, request_process in SCHEDULER_NEXT_START_REQUEST_PROCESS_BY_JOB_ID.items():
        request_status = db.get_process_status(request_process)
        if not request_status:
            continue

        request_state = str(request_status.get("status") or "").strip().upper()
        if request_state != "REQUESTED":
            continue

        requested_timestamp = str(request_status.get("message") or "").strip()
        requested_start = pd.to_datetime(requested_timestamp, errors="coerce", utc=True)
        if pd.isna(requested_start):
            db.touch_process_heartbeat(
                request_process,
                status="FAILED",
                message=f"Invalid next_start_timestamp: {requested_timestamp}",
            )
            continue

        job = scheduler.get_job(job_id)
        if not job:
            db.touch_process_heartbeat(
                request_process,
                status="FAILED",
                message=f"Scheduler job not found for request: {job_id}",
            )
            continue

        requested_datetime = requested_start.to_pydatetime()
        effective_start = now_utc if requested_datetime <= now_utc else requested_datetime
        job.modify(next_run_time=effective_start)

        db.touch_process_heartbeat(
            request_process,
            status="CONSUMED",
            message=effective_start.isoformat(),
        )
        logger.info(
            "Applied manual next_start_timestamp for '%s': %s",
            job_id,
            effective_start.isoformat(),
        )


def _record_scheduler_runtime_state(scheduler: BlockingScheduler) -> None:
    """Persist scheduler heartbeat and next-run metadata in one call."""
    _record_scheduler_heartbeat()
    _apply_requested_starts(scheduler)
    _record_scheduler_next_run_times(scheduler)
    _verify_running_jobs_liveness()


def _record_scheduler_runtime_state_job() -> None:
    """Job entrypoint for recording scheduler runtime state."""
    if ACTIVE_SCHEDULER is None:
        _record_scheduler_heartbeat()
        return
    _record_scheduler_runtime_state(ACTIVE_SCHEDULER)


def _is_discovery_overdue() -> bool:
    """Return True when discovery last run is older than its configured interval."""
    status = RecommendationsDatabase(RECOMMENDATIONS_DB_PATH).get_process_status("recommendations_workflow")
    if not status:
        return True

    last_run_timestamp = status.get("end_timestamp") or status.get("start_timestamp")
    parsed_last_run = pd.to_datetime(last_run_timestamp, errors="coerce", utc=True)
    if pd.isna(parsed_last_run):
        return True

    threshold = pd.Timestamp.now(tz="UTC") - pd.to_timedelta(DISCOVERY_INTERVAL_HOURS, unit="h")
    return parsed_last_run <= threshold


def run_scheduler() -> None:
    """Start blocking scheduler for discovery and tracked batch workflows."""
    global ACTIVE_SCHEDULER
    scheduler = BlockingScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=SCHEDULER_JOBSTORE_URL)},
        timezone="UTC",
    )
    ACTIVE_SCHEDULER = scheduler

    discovery_next_run_time = datetime.now(timezone.utc) if _is_discovery_overdue() else None

    scheduler.add_job(
        _run_discovery_workflow_subprocess,
        IntervalTrigger(hours=DISCOVERY_INTERVAL_HOURS),
        id="discovery_workflow",
        name="Discovery workflow",
        next_run_time=discovery_next_run_time,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.add_job(
        _run_tracked_stock_batch_subprocess,
        IntervalTrigger(hours=TRACKED_BATCH_INTERVAL_HOURS),
        id="tracked_stock_batch",
        name="Tracked-stock batch workflow",
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.add_job(
        _run_market_price_refresh_subprocess,
        IntervalTrigger(hours=MARKET_PRICE_REFRESH_INTERVAL_HOURS),
        id="market_price_refresh",
        name="Market price refresh",
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.add_job(
        _record_scheduler_runtime_state_job,
        IntervalTrigger(seconds=SCHEDULER_HEARTBEAT_INTERVAL_SECONDS),
        id="scheduler_heartbeat",
        name="Scheduler heartbeat",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    _record_scheduler_runtime_state(scheduler)

    logger.info(
        "Scheduler starting: discovery every %dh, tracked batches every %dh, market price refresh every %dh",
        DISCOVERY_INTERVAL_HOURS,
        TRACKED_BATCH_INTERVAL_HOURS,
        MARKET_PRICE_REFRESH_INTERVAL_HOURS,
    )
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
