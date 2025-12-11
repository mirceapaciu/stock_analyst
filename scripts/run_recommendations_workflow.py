"""Standalone script to run the stock recommendation workflow without Streamlit."""

import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# Add src directory to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.workflow import create_workflow
from services.recommendations import update_market_data_for_recommended_stocks
from repositories.recommendations_db import RecommendationsDatabase
from utils.logger import setup_logging
from utils.logger import save_workflow_state_to_json

# Configure logging using the standard setup
setup_logging()

PROCESS_NAME = "recommendations_workflow"

def run_recommendations_workflow():
    logger = logging.getLogger("run_recommendation_workflow")
    
    # Import config to log database path
    from config import RECOMMENDATIONS_DB_PATH
    logger.info(f"Using database: {RECOMMENDATIONS_DB_PATH}")
    
    db = RecommendationsDatabase()

    """Run the stock recommendation workflow."""
    logger.info("=" * 80)
    logger.info("Starting Stock Recommendation Workflow")
    logger.info("=" * 80)
    
    # Mark process as started
    db.start_process(PROCESS_NAME)
    
    try:
        # Create workflow
        logger.info("Creating workflow...")
        workflow = create_workflow()
        db.update_process_progress(PROCESS_NAME, 10)
        
        # Initialize state
        initial_state = {
            "search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [],
            "deduplicated_pages": [],
            "skipped_recommendations": [],
            "status": "Starting workflow",
            "process_name": PROCESS_NAME  # Process name for progress tracking (nodes create their own DB connections)
        }
        
        logger.info("\nRunning workflow (this may take several minutes)...")
        logger.info("-" * 80)
        
        # Workflow will update progress internally at each node (30% to 85%)
        result = workflow.invoke(initial_state)
        db.update_process_progress(PROCESS_NAME, 90)
        
        # Save final state to JSON for record-keeping
        state_file = save_workflow_state_to_json(result)
        logger.info(f"Workflow state saved to: {state_file}")

        # Display results
        logger.info("\n" + "=" * 80)
        logger.info("WORKFLOW COMPLETED")
        logger.info("=" * 80)
        logger.info(f"Final Status: {result.get('status', 'Unknown')}")
        logger.info(f"Search Results Found: {len(result.get('search_results', []))}")
        logger.info(f"Expanded Results: {len(result.get('expanded_search_results', []))}")
        logger.info(f"Pages Scraped: {len(result.get('scraped_pages', []))}")
        logger.info(f"Pages Deduplicated: {len(result.get('deduplicated_pages', []))}")
        logger.info(f"Recommendations Skipped: {len(result.get('skipped_recommendations', []))}")
        
        # Count total recommendations
        total_recommendations = sum(
            len(page.get('stock_recommendations', []))
            for page in result.get('deduplicated_pages', [])
        )
        logger.info(f"Total Stock Recommendations: {total_recommendations}")
        
        # Log database path being used
        logger.info(f"Database path: {db.db_path}")
        
        # Verify recommendations were saved
        try:
            saved_stocks = db.get_all_recommended_stocks()
            logger.info(f"Verified: {len(saved_stocks)} stocks in database")
        except Exception as e:
            logger.error(f"Error verifying saved recommendations: {e}")
        
        # Display some sample recommendations
        if total_recommendations > 0:
            logger.info("\n" + "-" * 80)
            logger.info("SAMPLE RECOMMENDATIONS:")
            logger.info("-" * 80)
            
            count = 0
            for page in result.get('deduplicated_pages', []):
                for rec in page.get('stock_recommendations', []):
                    if count >= 5:  # Show first 5
                        break
                    ticker = rec.get('ticker', 'N/A')
                    exchange = rec.get('exchange', 'N/A')
                    description = rec.get('description', 'No description')[:100]
                    quality = rec.get('quality_score', 0)
                    
                    logger.info(f"\n{count + 1}. {ticker} ({exchange}) - Quality: {quality}")
                    logger.info(f"   {description}...")
                    count += 1
                
                if count >= 5:
                    break
        
        # Display skipped recommendations
        skipped = result.get('skipped_recommendations', [])
        if skipped:
            logger.info("\n" + "-" * 80)
            logger.info(f"SKIPPED RECOMMENDATIONS ({len(skipped)} duplicates):")
            logger.info("-" * 80)
            for i, skip in enumerate(skipped[:5], 1):  # Show first 5
                logger.info(f"{i}. {skip.get('ticker')} ({skip.get('exchange')}) - {skip.get('reason')}")
                skipped_url = skip.get('skipped_url')
                kept_url = skip.get('kept_url')
                if skipped_url:
                    logger.info(f"   Skipped URL: {skipped_url[:80]}...")
                if kept_url:
                    logger.info(f"   Kept URL: {kept_url[:80]}...")
        
        logger.info("\n" + "=" * 80)
        
        # Update market data for recommended stocks
        try:
            logger.info("Updating market data for recommended stocks...")
            update_result = update_market_data_for_recommended_stocks()
            logger.info(f"Market data updated: {update_result['updated']} stocks updated, "
                       f"{update_result['failed']} failed, {update_result['skipped']} skipped")
        except Exception as e:
            logger.warning(f"Failed to update market data: {e}")
            # Continue anyway - the recommendations are still saved

        logger.info("Workflow completed successfully!")
        logger.info("=" * 80)
        
        # Mark process as complete
        db.end_process(PROCESS_NAME, 'COMPLETED')
        
        return 0
        
    except KeyboardInterrupt:
        logger.warning("\nWorkflow interrupted by user")
        db.end_process(PROCESS_NAME, 'FAILED')
        return 1
    except Exception as e:
        logger.error(f"\nWorkflow failed with error: {e}", exc_info=True)
        db.end_process(PROCESS_NAME, 'FAILED')
        return 1


if __name__ == "__main__":
    exit_code = run_recommendations_workflow()
    sys.exit(exit_code)
