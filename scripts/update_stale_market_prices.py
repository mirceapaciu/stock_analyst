"""Refresh stale market prices for all recommended stocks."""

import logging
import sys
from pathlib import Path

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from services.recommendations import update_market_data_for_recommended_stocks
from utils.logger import setup_logging

setup_logging()
logger = logging.getLogger("update_stale_market_prices")


def main() -> int:
    """Refresh stale market prices across all recommended stocks."""
    logger.info("Starting stale market price refresh for all recommended stocks")

    try:
        result = update_market_data_for_recommended_stocks()
        logger.info(
            "Stale market price refresh completed: "
            f"updated={result['updated']}, failed={result['failed']}, skipped={result['skipped']}"
        )
        return 0
    except Exception as error:
        logger.error(f"Stale market price refresh failed: {error}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
