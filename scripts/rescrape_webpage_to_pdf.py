"""Script to rescrape a webpage by webpage_id and save as PDF."""

import sys
import os
import argparse
import logging

# Add src directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
src_dir = os.path.join(project_root, 'src')
sys.path.insert(0, src_dir)

from repositories.recommendations_db import RecommendationsDatabase
from recommendations.workflow import scrape_single_page, save_pdf_to_file, save_html_to_file

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def rescrape_webpage_to_pdf(webpage_id: int) -> bool:
    """
    Rescrape a webpage by its ID and save as PDF.
    
    Args:
        webpage_id: The database ID of the webpage to rescrape
        
    Returns:
        bool: True if successful, False otherwise
    """
    db = RecommendationsDatabase()
    
    # Get webpage URL from database
    try:
        webpage = db.get_webpage_by_id(webpage_id)
        if not webpage:
            logger.error(f"Webpage with ID {webpage_id} not found in database")
            return False
        
        url = webpage.get('url')
        title = webpage.get('title', '')
        date = webpage.get('date', '')
        
        logger.info(f"Rescaping webpage {webpage_id}: {url}")
        logger.info(f"Title: {title}")
        logger.info(f"Date: {date}")
        
    except Exception as e:
        logger.error(f"Failed to retrieve webpage {webpage_id} from database: {e}")
        return False
    
    # Prepare search_result dict for scrape_single_page
    search_result = {
        'href': url,
        'title': title,
        'date': date,
        'body': '',
        'contains_stocks': True,
        'excerpt_date': date
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0'
    }
    
    # Scrape the page
    try:
        logger.info(f"Starting scrape of {url}...")
        page_data = scrape_single_page(search_result, headers, db)
        
        if not page_data:
            logger.error(f"Failed to scrape webpage {webpage_id}")
            return False
        
        logger.info(f"Successfully scraped {url}")
        
        # Save HTML if available
        html_content = page_data.get('html_content')
        if html_content:
            html_path = save_html_to_file(webpage_id, html_content)
            if html_path:
                logger.info(f"HTML saved: {html_path}")
        
        # Save PDF if available
        pdf_content = page_data.get('pdf_content')
        if pdf_content:
            pdf_path = save_pdf_to_file(webpage_id, pdf_content)
            if pdf_path:
                logger.info(f"PDF saved: {pdf_path}")
                return True
            else:
                logger.error("Failed to save PDF")
                return False
        else:
            logger.warning("No PDF content generated (page may not have used browser rendering)")
            return False
            
    except Exception as e:
        logger.error(f"Error during scraping: {e}", exc_info=True)
        return False


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Rescrape a webpage by ID and save as PDF'
    )
    parser.add_argument(
        'webpage_id',
        type=int,
        help='The database ID of the webpage to rescrape'
    )
    
    args = parser.parse_args()
    
    logger.info(f"Starting rescrape for webpage ID: {args.webpage_id}")
    
    success = rescrape_webpage_to_pdf(args.webpage_id)
    
    if success:
        logger.info("✓ Rescrape completed successfully")
        sys.exit(0)
    else:
        logger.error("✗ Rescrape failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
