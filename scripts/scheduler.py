"""Schedule discovery and tracked-stock workflows in one process."""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def _script_path(script_name: str) -> Path:
    return Path(__file__).resolve().parent / script_name


def _build_process_message(pid: int, script_name: str) -> str:
    return json.dumps(
        {
            "pid": pid,
            "script": script_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "started_by": "scheduler",
        },
        separators=(",", ":"),
    )


def _extract_pid(message: str | None) -> int | None:
    if not message:
        return None

    raw_message = str(message).strip()
    if not raw_message:
        return None

    try:
        parsed = json.loads(raw_message)
        pid_value = parsed.get("pid") if isinstance(parsed, dict) else None
        return int(pid_value) if pid_value is not None else None
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    try:
        return int(raw_message)
    except ValueError:
        return None


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
            continue

        pid = _extract_pid(status.get("message"))
        if pid is None:
            failure_message = "Scheduler could not verify running job: missing PID metadata"
            logger.error("%s for process '%s'", failure_message, process_name)
            db.end_process(process_name, "FAILED", failure_message)
            continue

        if _is_pid_alive(pid):
            continue

        failure_message = f"Scheduler detected dead process PID {pid}"
        logger.error("%s for process '%s'", failure_message, process_name)
        db.end_process(process_name, "FAILED", failure_message)


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
        db.end_process(process_name, "FAILED", stale_message)

    script_path = _script_path(script_name)
    process = subprocess.Popen(
        [sys.executable, str(script_path)],
        cwd=str(Path(__file__).resolve().parent),
    )
    db.start_process(process_name, message=_build_process_message(process.pid, script_name))
    logger.info("Launched '%s' as PID %s", process_name, process.pid)


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


def _record_scheduler_runtime_state(scheduler: BlockingScheduler) -> None:
    """Persist scheduler heartbeat and next-run metadata in one call."""
    _record_scheduler_heartbeat()
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
