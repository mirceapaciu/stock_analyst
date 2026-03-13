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
from run_recommendations_workflow import run_recommendations_workflow
from run_tracked_stock_batch import run_tracked_stock_batch
from utils.logger import setup_logging

setup_logging()

logger = logging.getLogger("workflow_scheduler")


def run_scheduler() -> None:
    """Start blocking scheduler for discovery and tracked batch workflows."""
    scheduler = BlockingScheduler()

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

    logger.info(
        "Scheduler starting: discovery every %dh, tracked batches every %dh",
        DISCOVERY_INTERVAL_HOURS,
        TRACKED_BATCH_INTERVAL_HOURS,
    )
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
