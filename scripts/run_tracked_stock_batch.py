"""Run one tracked-stock batch using persisted sweep cursor and CSE quota guards."""

import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from config import (
    RECOMMENDATIONS_DB_PATH,
    CSE_DAILY_QUOTA,
    TRACKED_BATCH_SIZE,
    TRACKED_BATCH_MIN_RATING,
    TRACKED_BATCH_SEARCH_QUERIES,
    SWEEP_STALE_DAYS,
)
from recommendations.workflow import create_workflow
from repositories.recommendations_db import RecommendationsDatabase
from services.recommendations import update_market_data_for_recommended_stocks
from utils.logger import setup_logging, save_workflow_state_to_json

setup_logging()

PROCESS_NAME = "tracked_stock_batch"
WORKFLOW_TYPE = "tracked_stock"
PROCESS_STALE_HOURS = max(1, int(os.getenv("TRACKED_BATCH_PROCESS_STALE_HOURS", "4")))


logger = logging.getLogger("run_tracked_stock_batch")


def _parse_sqlite_timestamp(timestamp_value: Optional[str]) -> Optional[datetime]:
    """Parse SQLite timestamp strings into datetime objects."""
    if not timestamp_value:
        return None

    raw_value = str(timestamp_value).strip()
    if not raw_value:
        return None

    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw_value, fmt)
        except ValueError:
            continue

    return None


def _is_started_process_stale(status: dict, stale_hours: int) -> bool:
    """Return True when a STARTED process is older than stale_hours."""
    if not status or status.get("status") != "STARTED":
        return False

    started_at = _parse_sqlite_timestamp(status.get("start_timestamp"))
    if not started_at:
        return True

    return datetime.now() - started_at > timedelta(hours=stale_hours)


def _get_batch_stock_names(db: RecommendationsDatabase, batch_tickers: list[str]) -> dict[str, str]:
    """Load stock names for the current tracked ticker batch."""
    if not batch_tickers:
        return {}

    ticker_set = {str(ticker or "").strip().upper() for ticker in batch_tickers if str(ticker or "").strip()}
    stock_names: dict[str, str] = {}

    try:
        for stock in db.get_all_recommended_stocks():
            ticker = str(stock.get("ticker") or "").strip().upper()
            if not ticker or ticker not in ticker_set or ticker in stock_names:
                continue

            stock_name = str(stock.get("stock_name") or "").strip()
            if stock_name:
                stock_names[ticker] = stock_name
    except Exception as stock_name_error:
        logger.warning(f"Failed to load stock names for tracked batch queries: {stock_name_error}")

    return stock_names


def run_tracked_stock_batch() -> int:
    """Run one tracked-stock batch workflow invocation."""
    logger.info(f"Using database: {RECOMMENDATIONS_DB_PATH}")

    db = RecommendationsDatabase()
    batch_tickers: list[str] = []

    logger.info("=" * 80)
    logger.info("Starting tracked-stock batch workflow")
    logger.info("=" * 80)

    existing_status = db.get_process_status(PROCESS_NAME)
    if existing_status and existing_status.get("status") == "STARTED":
        if not _is_started_process_stale(existing_status, PROCESS_STALE_HOURS):
            logger.warning("Previous tracked batch still running, skipping this invocation")
            return 0
        logger.warning(
            f"Found stale STARTED process older than {PROCESS_STALE_HOURS}h. "
            "Proceeding with a new batch invocation."
        )

    db.start_process(PROCESS_NAME)

    try:
        workflow = create_workflow()
        db.update_process_progress(PROCESS_NAME, 10)

        sweep = db.get_or_start_sweep(
            workflow_type=WORKFLOW_TYPE,
            min_rating=TRACKED_BATCH_MIN_RATING,
            stale_days=SWEEP_STALE_DAYS,
        )

        calls_per_ticker = max(1, len(TRACKED_BATCH_SEARCH_QUERIES))
        calls_used_today = db.get_cse_calls_today()
        remaining_calls = max(0, CSE_DAILY_QUOTA - calls_used_today)

        if remaining_calls < calls_per_ticker:
            logger.info(
                f"Skipping tracked batch: quota exhausted (used={calls_used_today}, "
                f"quota={CSE_DAILY_QUOTA})"
            )
            db.end_process(PROCESS_NAME, "COMPLETED")
            return 0

        max_tickers_by_quota = remaining_calls // calls_per_ticker
        effective_batch_size = min(TRACKED_BATCH_SIZE, max_tickers_by_quota)
        batch_tickers = sweep.next_batch(batch_size=effective_batch_size)

        if not batch_tickers:
            logger.info("No tracked tickers to process in this invocation")
            db.end_process(PROCESS_NAME, "COMPLETED")
            return 0

        logger.info(
            f"Processing tracked batch #{sweep.next_batch_number(TRACKED_BATCH_SIZE)} "
            f"(size={len(batch_tickers)}, remaining_quota={remaining_calls})"
        )
        logger.info(f"Tickers: {', '.join(batch_tickers)}")

        batch_stock_names = _get_batch_stock_names(db, batch_tickers)

        initial_state = {
            "query": "",
            "executed_queries": [],
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [],
            "deduplicated_pages": [],
            "skipped_recommendations": [],
            "status": "Starting tracked-stock batch",
            "error": "",
            "process_name": PROCESS_NAME,
            "workflow_mode": "tracked",
            "batch_tickers": batch_tickers,
            "batch_stock_names": batch_stock_names,
        }

        result = workflow.invoke(initial_state)
        db.update_process_progress(PROCESS_NAME, 90)

        db.advance_sweep(
            workflow_type=WORKFLOW_TYPE,
            processed_tickers=batch_tickers,
            status="COMPLETED",
        )

        state_file = save_workflow_state_to_json(result)
        logger.info(f"Tracked batch workflow state saved to: {state_file}")

        try:
            logger.info("Updating market data for recommended stocks...")
            update_result = update_market_data_for_recommended_stocks()
            logger.info(
                f"Market data update result: updated={update_result['updated']}, "
                f"failed={update_result['failed']}, skipped={update_result['skipped']}"
            )
        except Exception as market_error:
            logger.warning(f"Market data update failed after batch run: {market_error}")

        logger.info("Tracked batch completed successfully")
        db.end_process(PROCESS_NAME, "COMPLETED")
        return 0

    except KeyboardInterrupt:
        logger.warning("Tracked batch interrupted by user")
        db.advance_sweep(
            workflow_type=WORKFLOW_TYPE,
            processed_tickers=[],
            status="FAILED",
        )
        db.end_process(PROCESS_NAME, "FAILED")
        return 1
    except Exception as error:
        logger.error(f"Tracked batch failed: {error}", exc_info=True)
        db.advance_sweep(
            workflow_type=WORKFLOW_TYPE,
            processed_tickers=[],
            status="FAILED",
        )
        db.end_process(PROCESS_NAME, "FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_tracked_stock_batch())
