"""Schedule discovery and tracked-stock workflows in one process."""

import logging
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from config import DISCOVERY_INTERVAL_HOURS, TRACKED_BATCH_INTERVAL_HOURS
from config import RECOMMENDATIONS_DB_PATH
from repositories.recommendations_db import RecommendationsDatabase
from run_recommendations_workflow import run_recommendations_workflow
from run_tracked_stock_batch import run_tracked_stock_batch
from utils.logger import setup_logging

setup_logging()

logger = logging.getLogger("workflow_scheduler")

SCHEDULER_HEARTBEAT_PROCESS = "scheduler_heartbeat"
SCHEDULER_HEARTBEAT_INTERVAL_SECONDS = 60


def _record_scheduler_heartbeat() -> None:
    """Persist a heartbeat so the dashboard can detect that the scheduler is alive."""
    RecommendationsDatabase(RECOMMENDATIONS_DB_PATH).touch_process_heartbeat(
        SCHEDULER_HEARTBEAT_PROCESS
    )


def run_scheduler() -> None:
    """Start blocking scheduler for discovery and tracked batch workflows."""
    scheduler = BlockingScheduler()

    _record_scheduler_heartbeat()

    scheduler.add_job(
        run_recommendations_workflow,
        IntervalTrigger(hours=DISCOVERY_INTERVAL_HOURS),
        id="discovery_workflow",
        name="Discovery workflow",
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    scheduler.add_job(
        run_tracked_stock_batch,
        IntervalTrigger(hours=TRACKED_BATCH_INTERVAL_HOURS),
        id="tracked_stock_batch",
        name="Tracked-stock batch workflow",
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )

    scheduler.add_job(
        _record_scheduler_heartbeat,
        IntervalTrigger(seconds=SCHEDULER_HEARTBEAT_INTERVAL_SECONDS),
        id="scheduler_heartbeat",
        name="Scheduler heartbeat",
        max_instances=1,
        coalesce=True,
    )

    logger.info(
        "Scheduler starting: discovery every %dh, tracked batches every %dh",
        DISCOVERY_INTERVAL_HOURS,
        TRACKED_BATCH_INTERVAL_HOURS,
    )
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
