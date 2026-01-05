"""Logging configuration for the stock tracking application."""

import logging
from pathlib import Path
from datetime import datetime
import json

# Base directory - use resolve() to ensure absolute path
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Logging settings
LOG_DIR = BASE_DIR / "logs"

APP_LOG_DIR = LOG_DIR / "app"
APP_LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = APP_LOG_DIR / f"app_{datetime.now().strftime('%Y%m%d')}.log"

WORKFLOW_STATE_DIR = LOG_DIR / "workflow_state"
WORKFLOW_STATE_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging():
    """Configure logging to write to both console and file."""

    # Create logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Create formatters
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

def save_workflow_state_to_json(final_state)->str:
    """Save workflow state to a JSON file in the logs directory.
    
    Excludes pdf_content field to reduce file size.
    This field is already saved to disk and doesn't need to be in state.
    
    Args:
        final_state: The final state from the workflow execution

    Returns:
        Path to the saved JSON file
    """
    logger = logging.getLogger(__name__)
    try:
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"workflow_state_{timestamp}.json"
        filepath = WORKFLOW_STATE_DIR / filename
        
        # Deep copy state and remove large content fields
        import copy
        state_to_save = copy.deepcopy(final_state)
        
        # Remove pdf_content from scraped pages and deduplicated pages
        for key in ['scraped_pages', 'deduplicated_pages']:
            if key in state_to_save:
                for page in state_to_save[key]:
                    page.pop('pdf_content', None)
        
        # Save to JSON file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(state_to_save, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Workflow state saved to: {filepath}")
        return str(filepath)

    except Exception as e:
        logger.error(f"Failed to save workflow state to JSON: {e}")
        # Don't raise exception - this is non-critical functionality
