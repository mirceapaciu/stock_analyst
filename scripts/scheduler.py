"""Schedule discovery and tracked-stock workflows in one process."""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import pandas as pd
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from config import DISCOVERY_INTERVAL_HOURS, MARKET_PRICE_REFRESH_INTERVAL_HOURS, SCHEDULER_JOBSTORE_URL, TRACKED_BATCH_INTERVAL_HOURS
from config import RECOMMENDATIONS_DB_PATH
from config import SCHEDULER_JOB_GROUPS
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
JOB_ID_BY_PROCESS_NAME = {
    process_name: job_id for job_id, process_name in JOB_PROCESS_BY_JOB_ID.items()
}


def _build_scheduler_group_maps(job_groups: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Validate group configuration and build lookup maps."""
    known_job_ids = set(JOB_SCRIPT_BY_JOB_ID.keys())
    job_group_by_job_id: dict[str, str] = {}
    job_ids_by_group: dict[str, list[str]] = {}
    seen_group_names: set[str] = set()

    if not isinstance(job_groups, list):
        raise ValueError("SCHEDULER_JOB_GROUPS must be a list")

    for index, raw_group in enumerate(job_groups):
        if not isinstance(raw_group, dict):
            raise ValueError(f"SCHEDULER_JOB_GROUPS[{index}] must be an object")

        group_name = str(raw_group.get("job_group") or "").strip()
        if not group_name:
            raise ValueError(f"SCHEDULER_JOB_GROUPS[{index}].job_group must be a non-empty string")
        if group_name in seen_group_names:
            raise ValueError(f"Duplicate scheduler job group name: {group_name}")

        raw_jobs = raw_group.get("jobs")
        if not isinstance(raw_jobs, list) or not raw_jobs:
            raise ValueError(f"SCHEDULER_JOB_GROUPS[{index}].jobs must be a non-empty list")

        normalized_jobs: list[str] = []
        seen_jobs_in_group: set[str] = set()
        for raw_job_id in raw_jobs:
            job_id = str(raw_job_id or "").strip()
            if not job_id:
                raise ValueError(f"SCHEDULER_JOB_GROUPS[{index}] contains an empty job id")
            if job_id in seen_jobs_in_group:
                raise ValueError(f"Job '{job_id}' appears multiple times in group '{group_name}'")
            if job_id not in known_job_ids:
                raise ValueError(f"Unknown scheduler job id in group '{group_name}': {job_id}")
            if job_id in job_group_by_job_id:
                previous_group = job_group_by_job_id[job_id]
                raise ValueError(
                    f"Job '{job_id}' cannot belong to multiple groups: '{previous_group}' and '{group_name}'"
                )

            seen_jobs_in_group.add(job_id)
            normalized_jobs.append(job_id)
            job_group_by_job_id[job_id] = group_name

        seen_group_names.add(group_name)
        job_ids_by_group[group_name] = normalized_jobs

    return job_group_by_job_id, job_ids_by_group


JOB_GROUP_BY_JOB_ID, JOB_IDS_BY_GROUP = _build_scheduler_group_maps(SCHEDULER_JOB_GROUPS)
ACTIVE_SCHEDULER: BlockingScheduler | None = None
ACTIVE_CHILD_PROCESSES: dict[str, subprocess.Popen] = {}
ACTIVE_CHILD_PROCESS_LOG_PATHS: dict[str, Path] = {}
ACTIVE_CHILD_PROCESS_LOG_HANDLES: dict[str, TextIO] = {}
ACTIVE_JOB_GROUP_LOCKS: dict[str, str] = {}
WAITING_JOB_DUE_TIMES_BY_GROUP: dict[str, dict[str, datetime]] = {}
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


def _queue_waiting_job(group_name: str, job_id: str, due_time: datetime) -> None:
    """Store earliest due timestamp for a blocked job in a lock group."""
    waiting_jobs = WAITING_JOB_DUE_TIMES_BY_GROUP.setdefault(group_name, {})
    existing_due_time = waiting_jobs.get(job_id)
    if existing_due_time is None or due_time < existing_due_time:
        waiting_jobs[job_id] = due_time


def _acquire_group_lock_or_queue(job_id: str) -> bool:
    """Attempt to acquire group lock. Queue job when lock is already held."""
    group_name = JOB_GROUP_BY_JOB_ID.get(job_id)
    if not group_name:
        return True

    lock_holder = ACTIVE_JOB_GROUP_LOCKS.get(group_name)
    if lock_holder is None:
        ACTIVE_JOB_GROUP_LOCKS[group_name] = job_id
        logger.info("Acquired group lock '%s' for job '%s'", group_name, job_id)
        return True

    if lock_holder == job_id:
        return True

    due_time = datetime.now(timezone.utc)
    _queue_waiting_job(group_name, job_id, due_time)
    logger.info(
        "Blocked job '%s' in group '%s'; lock held by '%s'; due_at=%s",
        job_id,
        group_name,
        lock_holder,
        due_time.isoformat(),
    )
    return False


def _release_group_lock_for_job(job_id: str, reason: str) -> None:
    """Release group lock held by a job and schedule next waiting job immediately."""
    group_name = JOB_GROUP_BY_JOB_ID.get(job_id)
    if not group_name:
        return

    lock_holder = ACTIVE_JOB_GROUP_LOCKS.get(group_name)
    if lock_holder != job_id:
        return

    ACTIVE_JOB_GROUP_LOCKS.pop(group_name, None)
    logger.info("Released group lock '%s' from job '%s' (reason=%s)", group_name, job_id, reason)

    waiting_jobs = WAITING_JOB_DUE_TIMES_BY_GROUP.get(group_name) or {}
    if not waiting_jobs:
        return

    next_job_id, _due_time = min(waiting_jobs.items(), key=lambda item: (item[1], item[0]))
    waiting_jobs.pop(next_job_id, None)
    if not waiting_jobs:
        WAITING_JOB_DUE_TIMES_BY_GROUP.pop(group_name, None)

    if ACTIVE_SCHEDULER is None:
        logger.warning(
            "Cannot schedule waiting job '%s' immediately: scheduler reference is missing",
            next_job_id,
        )
        return

    next_job = ACTIVE_SCHEDULER.get_job(next_job_id)
    if not next_job:
        logger.warning("Cannot schedule waiting job immediately: scheduler job '%s' not found", next_job_id)
        return

    run_at = datetime.now(timezone.utc)
    next_job.modify(next_run_time=run_at)
    logger.info(
        "Scheduled waiting job '%s' immediately after lock release in group '%s'",
        next_job_id,
        group_name,
    )


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
        job_id = JOB_ID_BY_PROCESS_NAME.get(process_name)
        status = db.get_process_status(process_name)
        if not status or str(status.get("status") or "").strip().upper() != "STARTED":
            _cleanup_child_tracking(process_name)
            if job_id is not None:
                terminal_state = str(status.get("status") or "UNKNOWN").strip().upper() if status else "MISSING"
                _release_group_lock_for_job(job_id, reason=f"terminal_state_{terminal_state}")
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
            if job_id is not None:
                _release_group_lock_for_job(job_id, reason="dead_child_exit")
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
            if job_id is not None:
                _release_group_lock_for_job(job_id, reason="missing_pid")
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
        if job_id is not None:
            _release_group_lock_for_job(job_id, reason="dead_pid")


def _launch_job_subprocess(job_id: str) -> bool:
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
            return False

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
    return True


def _run_job_with_group_lock(job_id: str) -> None:
    """Run one scheduler job under group mutual exclusion rules."""
    if not _acquire_group_lock_or_queue(job_id):
        return

    try:
        launched = _launch_job_subprocess(job_id)
    except Exception:
        _release_group_lock_for_job(job_id, reason="launch_error")
        raise

    if not launched:
        _release_group_lock_for_job(job_id, reason="launch_skipped")


def _run_discovery_workflow_subprocess() -> None:
    _run_job_with_group_lock("discovery_workflow")


def _run_tracked_stock_batch_subprocess() -> None:
    _run_job_with_group_lock("tracked_stock_batch")


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
