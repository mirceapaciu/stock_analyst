"""Run recommendation workflow from an existing webpage PDF."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, TypedDict

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from langgraph.graph import END, StateGraph

from repositories.recommendations_db import RecommendationsDatabase
from recommendations.workflow import (
    extract_stock_recommendations_with_llm,
    output_node,
    update_progress_if_available,
    validate_tickers_node,
)
from utils.logger import save_workflow_state_to_json, setup_logging

logger = logging.getLogger(__name__)


class PdfWorkflowState(TypedDict):
    """State for recommendation workflow based on an existing webpage PDF."""

    webpage_id: int
    pdf_file_path: Optional[str]
    query: str
    search_results: List[Dict]
    filtered_search_results: List[Dict]
    expanded_search_results: List[Dict]
    scraped_pages: List[Dict]
    deduplicated_pages: List[Dict]
    skipped_recommendations: List[Dict]
    status: str
    error: str
    process_name: Optional[str]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_pdf_path(webpage_id: int) -> Path:
    return _project_root() / "data" / "db" / "webpage" / str(webpage_id) / f"{webpage_id}.pdf"


def _read_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from PDF bytes."""
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                "PDF parsing library not found. Install 'pypdf' in the environment."
            ) from exc

    reader = PdfReader(BytesIO(pdf_bytes))
    parts: List[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text.strip())

    text = "\n".join(parts).strip()
    return text[:10000]


def scrape_pdf_node(state: PdfWorkflowState) -> PdfWorkflowState:
    """Load a saved webpage PDF by webpage.id and extract stock recommendations."""
    update_progress_if_available(state, 65)
    db = RecommendationsDatabase()

    webpage_id = state.get("webpage_id")
    if not webpage_id:
        return {
            **state,
            "scraped_pages": [],
            "status": "PDF scrape failed: missing webpage_id",
            "error": "Missing webpage_id",
        }

    webpage = db.get_webpage_by_id(int(webpage_id))
    if not webpage:
        return {
            **state,
            "scraped_pages": [],
            "status": f"PDF scrape failed: webpage.id {webpage_id} not found",
            "error": "Webpage not found",
        }

    configured_pdf_path = state.get("pdf_file_path")
    pdf_path = Path(configured_pdf_path) if configured_pdf_path else _default_pdf_path(int(webpage_id))
    if not pdf_path.is_absolute():
        pdf_path = (_project_root() / pdf_path).resolve()

    if not pdf_path.exists():
        return {
            **state,
            "scraped_pages": [],
            "status": f"PDF scrape failed: PDF file not found for webpage.id {webpage_id}",
            "error": f"Missing PDF: {pdf_path}",
        }

    try:
        pdf_bytes = pdf_path.read_bytes()
        page_text = _read_pdf_text(pdf_bytes)
        if not page_text:
            raise ValueError("Extracted empty text from PDF")

        webpage_date_raw = webpage.get("date") or datetime.now().strftime("%Y-%m-%d")
        try:
            page_date = datetime.strptime(str(webpage_date_raw), "%Y-%m-%d")
        except ValueError:
            page_date = datetime.now()

        recommendations = extract_stock_recommendations_with_llm(
            url=webpage.get("url", ""),
            title=webpage.get("title", ""),
            page_text=page_text,
            page_date=page_date,
        )

        scraped_page = {
            "url": webpage.get("url", ""),
            "webpage_title": webpage.get("title", ""),
            "webpage_date": page_date.strftime("%Y-%m-%d"),
            "page_text": page_text,
            "pdf_content": pdf_bytes,
            "stock_recommendations": recommendations,
            "source_webpage_id": int(webpage_id),
            "source_pdf_path": str(pdf_path),
        }

        return {
            **state,
            "scraped_pages": [scraped_page],
            "status": (
                f"Scraped PDF for webpage.id {webpage_id}: "
                f"{len(recommendations)} recommendations extracted"
            ),
            "error": "",
        }
    except Exception as exc:
        logger.error(f"Failed PDF scrape for webpage.id={webpage_id}: {exc}", exc_info=True)
        return {
            **state,
            "scraped_pages": [],
            "status": f"PDF scrape failed for webpage.id {webpage_id}",
            "error": str(exc),
        }


def create_pdf_workflow():
    """Create workflow that starts from a saved PDF instead of web scraping."""
    def route_after_scrape(state: PdfWorkflowState) -> str:
        if state.get("error") or not state.get("scraped_pages"):
            return "end"
        return "validate"

    workflow = StateGraph(PdfWorkflowState)
    workflow.add_node("scrape_pdf", scrape_pdf_node)
    workflow.add_node("validate_tickers", validate_tickers_node)
    workflow.add_node("output", output_node)

    workflow.set_entry_point("scrape_pdf")
    workflow.add_conditional_edges(
        "scrape_pdf",
        route_after_scrape,
        {
            "validate": "validate_tickers",
            "end": END,
        },
    )
    workflow.add_edge("validate_tickers", "output")
    workflow.add_edge("output", END)

    return workflow.compile()


def run_pdf_workflow_for_webpage_id(
    webpage_id: int,
    pdf_file_path: str | None = None,
    process_name: str | None = None,
) -> Dict:
    """Run PDF-based workflow for a single existing webpage.id."""
    workflow = create_pdf_workflow()

    initial_state: PdfWorkflowState = {
        "webpage_id": int(webpage_id),
        "pdf_file_path": pdf_file_path,
        "query": f"existing_webpage_pdf:{webpage_id}",
        "search_results": [],
        "filtered_search_results": [],
        "expanded_search_results": [],
        "scraped_pages": [],
        "deduplicated_pages": [],
        "skipped_recommendations": [],
        "status": "Starting PDF workflow",
        "error": "",
        "process_name": process_name,
    }

    return workflow.invoke(initial_state)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run recommendation workflow for an existing webpage.id using saved PDF"
    )
    parser.add_argument("webpage_id", type=int, help="Existing webpage.id in database")
    parser.add_argument(
        "--pdf-path",
        default=None,
        help="Optional PDF path override (default: data/db/webpage/{id}/{id}.pdf)",
    )
    parser.add_argument(
        "--process-name",
        default=None,
        help="Optional process name used for progress updates",
    )
    return parser.parse_args()


def main() -> int:
    setup_logging()
    args = _parse_args()

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
