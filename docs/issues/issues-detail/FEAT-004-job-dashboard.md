# FEAT-004 Job dashboard

## Metadata
- Type: feature
- Priority: high
- Status: resolved
- Area: recommendation workflow, market price refresh

## Current Behavior
The workflow is currently running in a schedule. The user cannot see when the workflow has run.

## Desired Behavior

Add a new **Job Dashboard** UI tab that displays the status and schedule information for all scheduled jobs.

### Dashboard Features

#### UI Tab
- Add a new tab in the Streamlit UI labeled "Job Dashboard"
- Located alongside existing tabs (Recommendations, Favorites, Valuation)

#### Job Types Tracked
The dashboard must display status for three job types:
1. **Stock Recommendation Discovery** — periodic search and analysis for new stock recommendations
2. **Tracked Stock Recommendation** — batch processing of tracked/monitored stocks
3. **Market Price Refresh** — periodic update of market data for tracked stocks

#### Information Displayed Per Job
For each job type, display:
- **Last Run Timestamp** — when the job most recently executed (format: YYYY-MM-DD HH:MM:SS)
- **Completion Status** — current state of the job:
  - Running (in progress)
  - Completed (last run succeeded)
  - Failed (last run encountered error)
  - Pending (scheduled but never run)
- **Schedule Frequency** — how often the job is scheduled to run (in days, e.g., "Every 1 day", "Every 8 days")

#### Data Source

##### SQLite `recommendations.db` Tables

**`process` table** — tracks Stock Recommendation Discovery job
| Column | Type | Description |
|--------|------|-------------|
| `process_name` | VARCHAR(50) | Identifier: `"recommendations_workflow"` |
| `start_timestamp` | TIMESTAMP | When job started |
| `end_timestamp` | TIMESTAMP | When job completed (NULL if running) |
| `progress_pct` | INTEGER | Progress percentage (0–100) |
| `status` | VARCHAR(20) | Status: `STARTED`, `COMPLETED`, or `FAILED` |

**`batch_schedule` table** — tracks Tracked Stock Recommendation and Market Price Refresh jobs
| Column | Type | Description |
|--------|------|-------------|
| `workflow_type` | VARCHAR(50) | Job identifier (e.g., `"tracked_stock_recommendation"`, `"market_price_refresh"`) |
| `sweep_started_at` | TIMESTAMP | When this sweep/batch started |
| `last_batch_at` | TIMESTAMP | When last batch executed |
| `last_batch_status` | VARCHAR(20) | Status of last batch: `COMPLETED` or `FAILED` |
| `consecutive_failures` | INTEGER | Count of consecutive failures |
| `sweep_completed_at` | TIMESTAMP | When sweep completed (NULL if in progress) |

##### Environment Variables (Configuration)

Schedule frequency is stored in environment variables:
- `DISCOVERY_INTERVAL_HOURS` — Stock Recommendation Discovery frequency (hours)
- `TRACKED_BATCH_INTERVAL_HOURS` — Tracked Stock Recommendation frequency (hours)
- `SWEEP_STALE_DAYS` — Market Price Refresh frequency (days)

##### Query Methods

All data is queryable via `RecommendationsDatabase` class:
- `db.get_process_status(process_name)` — returns process table row as dict
- `db.is_process_running(process_name)` — returns True if status is 'STARTED'
- Direct SQL query on `batch_schedule` table by `workflow_type`

### Acceptance Criteria
1. Dashboard tab is accessible and renders without errors
2. All three job types are displayed with their current status
3. Last run timestamps are accurate and update after each job execution
4. Completion status correctly reflects job state
5. Schedule frequency is clearly displayed in human-readable format
6. Dashboard auto-refreshes or user can manually refresh to see latest status

## Resolution Summary
- Added a new Streamlit page: `src/ui/pages/4_Job_Dashboard.py`
- Dashboard displays three job types with:
  - last run timestamp
  - completion status
  - schedule frequency in days
- Dashboard also shows a scheduler heartbeat status banner based on a persisted heartbeat row
- Data source implemented via:
  - `process` table (`recommendations_workflow`, `tracked_stock_batch`, `market_price_refresh`)
  - `process` table heartbeat row (`scheduler_heartbeat`)
  - `batch_schedule` table fallback for tracked stock last batch metadata
- Added repository method `get_batch_schedule_status(workflow_type)`
- Added repository method `touch_process_heartbeat(process_name)`
- Added process tracking for market refresh runs by extending
  `update_market_data_for_recommended_stocks(..., process_name=...)`
- Wired market refresh process tracking from:
  - `scripts/update_stale_market_prices.py`
  - `scripts/run_recommendations_workflow.py`
  - `scripts/run_tracked_stock_batch.py`
  - UI buttons in Favorites and Recommendations pages
- Wired scheduler heartbeat writes from `scripts/scheduler.py` on startup and every minute

## Validation
- Unit tests passed:
  - `tests/test_batch_scheduler_db.py`
  - `tests/test_market_data_refresh_scope.py`

## Remaining Risks / Follow-up
- Dashboard shows latest persisted process status per job, not full historical run history.
- If two market refresh triggers overlap, the `market_price_refresh` process row reflects the latest run state only.

