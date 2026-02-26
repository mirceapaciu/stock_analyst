"""Run recommendation workflow for an existing webpage.id using saved PDF content."""

import argparse
import logging
import sys
from pathlib import Path

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.pdf_workflow import run_pdf_workflow_for_webpage_id
from utils.logger import save_workflow_state_to_json, setup_logging

setup_logging()
logger = logging.getLogger("run_recommendation_workflow_for_webpage_pdf")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run recommendation workflow from saved PDF for existing webpage.id"
    )
    parser.add_argument("webpage_id", type=int, help="Existing webpage.id")
    parser.add_argument(
        "--pdf-path",
        default=None,
        help="Optional PDF path override (default: data/db/webpage/{id}/{id}.pdf)",
    )
    parser.add_argument(
        "--process-name",
        default=None,
        help="Optional process name for progress tracking",
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("Starting PDF-based recommendation workflow")
    logger.info(f"webpage_id={args.webpage_id}")
    if args.pdf_path:
        logger.info(f"pdf_path={args.pdf_path}")
    logger.info("=" * 80)

    result = run_pdf_workflow_for_webpage_id(
        webpage_id=args.webpage_id,
        pdf_file_path=args.pdf_path,
        process_name=args.process_name,
    )

    state_file = save_workflow_state_to_json(result)
    logger.info(f"Workflow state dumped to: {state_file}")
    logger.info(f"Final status: {result.get('status', 'N/A')}")

    if result.get("error"):
        logger.error(result["error"])
        return 1

    saved_recommendations = sum(
        len(page.get("stock_recommendations", []))
        for page in result.get("deduplicated_pages", [])
    )
    logger.info(f"Saved recommendations (deduplicated): {saved_recommendations}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
