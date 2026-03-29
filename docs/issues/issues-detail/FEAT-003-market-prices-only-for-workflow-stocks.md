# FEAT-003 Market prices only for workflow stocks

## Metadata
- Type: feature
- Priority: high
- Status: resolved
- Area: recommendation workflow

## Current Behavior
The workflow is currently retrieving the market prices for all the stocks registered in DB. This is slowing down the workflow.

## Expected Behavior
- The workflow should get the market prices only for the stocks from the recommentations collected in this workflow
- There must be a script that is retrieving the market prices for all stocks with stale prices.

## Scope
In scope:
- reduce the number of market prices retrieved within the workflow 
- create a script that retrieves the market price for all stocks with stale prices. Use the  same logic that was used until now in the workflow for refreshing the market prices.

Out of scope:
- Major redesign.

## Test Plan
1. Integration check:
	- Run workflow and verify :
	  - The market prices of the workflows were retrieved.
	  - No market prices were retrieved for stocks that were not in new recommendations of the workflow.

## Root Cause
- Workflow runner scripts refreshed stale market prices using all rows from `recommended_stock`, without constraining refreshes to tickers produced by the current workflow execution.
- The broad refresh logic existed only in workflow post-processing, so there was no dedicated script to run the stale-price sweep independently.

## Resolution
- Added workflow-ticker scoping support in the market data refresh service:
	- `update_market_data_for_recommended_stocks(..., workflow_tickers=...)`
	- refresh applies only to tickers collected during the current workflow run when provided.
- Added helper `collect_workflow_recommendation_tickers(workflow_result)` to extract tickers from workflow output (`deduplicated_pages`, with fallback to `scraped_pages`).
- Updated both workflow runner scripts to pass current-run tickers into market refresh:
	- `scripts/run_recommendations_workflow.py`
	- `scripts/run_tracked_stock_batch.py`
- Added standalone stale sweep script using the original stale-refresh logic:
	- `scripts/update_stale_market_prices.py`

## Validation
- Added unit tests in `tests/test_market_data_refresh_scope.py` for:
	- ticker extraction from workflow state
	- fallback extraction path
	- market refresh constrained to workflow tickers
	- empty workflow ticker list producing no updates

## Remaining Risks / Follow-up
- End-to-end integration execution against a live recommendations DB and API keys is still needed to validate runtime behavior in production-like conditions.
