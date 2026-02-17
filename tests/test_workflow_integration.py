"""Integration tests for workflow nodes that interact with external services.

NOTE: These tests make real HTTP requests to external services (Google Custom Search, OpenAI).
They may be slower and could fail due to network issues or rate limiting.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from recommendations.workflow import (
    search_node, 
    filter_duplicate_node, 
    filter_known_bad_node, 
    analyze_search_result, 
    retrieve_nested_pages,
    scrape_node, 
    validate_tickers_node, 
    output_node, 
    WorkflowState,
    create_workflow
)
from utils.logger import setup_logging
import json


# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestSearchAndScrapeWorkflow:
    
    @classmethod
    def setup_class(cls):
        """Setup logging before running tests."""
        setup_logging()
    
    def dump_state_to_file(self, state: dict, filename: str = "workflow_state_dump.json"): 
        """Dump workflow state to JSON file for inspection."""
        import pathlib
        temp_dir = pathlib.Path(__file__).parent.parent / "temp"
        temp_dir.mkdir(exist_ok=True)
        output_file = temp_dir / filename
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, default=str)
        print(f"State dumped to: {output_file}")

    def test_workflow_compilation(self):
        """Test that the workflow compiles successfully."""
        workflow = create_workflow()
        assert workflow is not None
        print("Workflow compiled successfully")

    def test_end_to_end_data_flow(self):
        """Test that data flows correctly through all workflow nodes."""
        # Initialize empty state - workflow will use default query from config
        state = {
            "query": "",
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [],
            "status": "",
            "error": ""
        }
        print()

        # Run the nodes in sequence
        state = search_node(state)
        print(f"After search: {len(state.get('search_results', []))} results")
        
        state = filter_duplicate_node(state)
        print(f"After filter_duplicate: {len(state.get('search_results', []))} results")
        
        state = filter_known_bad_node(state)
        print(f"After filter_known_bad: {len(state.get('filtered_search_results', []))} results")
        
        state = retrieve_nested_pages(state)
        print(f"After retrieve_nested: {len(state.get('expanded_search_results', []))} results")

        state = analyze_search_result(state)
        print(f"After analyze: {len(state.get('filtered_search_results', []))} results")     
        
        state = scrape_node(state)
        print(f"After scrape: {len(state.get('scraped_pages', []))} pages")
        
        state = validate_tickers_node(state)
        print(f"After validate: {len(state.get('scraped_pages', []))} pages")
        
        state = output_node(state)
        print(f"Final status: {state.get('status')}")

        # Dump state to file for inspection
        self.dump_state_to_file(state)
        
        # Basic assertions
        assert "search_results" in state
        assert "status" in state
        print(f"Workflow completed with status: {state.get('status')}")

    # @pytest.mark.skip(reason="Manual test - requires dumped state file from previous run")
    def test_replay_from_dumped_state(self):
        """Replay workflow from previously dumped state.
        
        This test loads workflow_state_dump.json and continues execution
        from the point where the state was saved.
        """
        import pathlib
        
        # Load the dumped state
        # state_file = pathlib.Path(__file__).parent.parent / "logs" / "workflow_state" / "workflow_state_20251117171119.json"
        state_file = pathlib.Path(__file__).parent.parent / "temp" / "workflow_state_doo.json"

        if not state_file.exists():
            pytest.skip(f"State file not found: {state_file}. Run test_end_to_end_data_flow first.")
        
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        print(f"Loaded state from: {state_file}")
        print(f"State status: {state.get('status')}")
        print(f"Filtered search results: {len(state.get('filtered_search_results', []))}")

        # You can comment/uncomment nodes as needed to continue from a specific point

        # Continue workflow from loaded state
        # state = filter_duplicate_node(state)
        # state = filter_known_bad_node(state)
        state = retrieve_nested_pages(state)
        state = analyze_search_result(state)
        state = scrape_node(state)
        state = validate_tickers_node(state)
        
        # Optionally continue to output node
        state = output_node(state)


        self.dump_state_to_file(state, filename="workflow_final_state_dump.json")

        print(f"Final status: {state.get('status')}")
        assert "status" in state

    def test_full_workflow_invoke(self):
        """Test running the complete workflow using LangGraph's invoke method."""
        workflow = create_workflow()
        
        # Run the entire workflow
        result = workflow.invoke({
            "query": "",
            "search_results": [],
            "filtered_search_results": [],
            "expanded_search_results": [],
            "scraped_pages": [],
            "status": "",
            "error": ""
        })
        
        print(f"Workflow result status: {result.get('status')}")
        print(f"Search results: {len(result.get('search_results', []))}")
        print(f"Scraped pages: {len(result.get('scraped_pages', []))}")
        
        # Dump final state
        self.dump_state_to_file(result, filename="workflow_langgraph_invoke.json")
        
        # Verify workflow completed
        assert "status" in result
        assert "search_results" in result

  
        
        