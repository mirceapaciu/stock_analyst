# BUG-001 Handle blocked pages more gracefully

## Metadata
- Type: bug
- Priority: high
- Status: open
- Area: recommendation workflow (fetch -> parse -> extraction -> filtering)

## Problem Statement
The workflow currently processes many pages that are blocked (401/403) and this contributes to noisy logs, unnecessary scraping of pages that fail.

## Verified Evidence
From `logs/app/app_20260328.log`:

Repeated blocked-source fetch failures (should be classified early):
	- Reuters 401 examples: lines 13-22
	- Zacks 403 examples: lines 31-32
	- Seeking Alpha 403 examples: lines 33-41


## Current Behavior
- Blocked pages are retried/attempted during nested link expansion and logged as warnings repeatedly.

For example:
"https://www.reuters.com/markets/companies/CNNE.P/profile/"

Note that all pages of this URL pattern are blocked:
"https://www.reuters.com/markets/companies/.*/profile/"

## Expected Behavior
- Blocked pages are identified, categorized, and skipped early with bounded retries.
- URL patterns of blocked pages are saved in DB so taht they can be skipped in a later run as well.

## Scope
In scope:
- Fetch and retry policy for blocked responses (401/403/404 and similar terminal failures).
- Tests covering the above behavior.

Out of scope:
- Major redesign of extraction prompts.
- Source-specific scraping bypasses that require authentication or anti-bot evasion.

## Acceptance Criteria
- Blocked pages are classified as terminal failures and skipped without noisy repeated retries.
- Recommendation candidates from thin/low-information pages are not persisted unless they pass quality threshold checks.
- Hallucinated tickers are counted and reported in run summary metrics/log output.
- Workflow still completes successfully when a large portion of pages are blocked.
- Automated tests exist for:
  - blocked fetch classification and retry behavior,

## Test Plan
1. Unit tests:
	- Mock HTTP 401/403/404 responses and assert terminal classification + bounded retry.

2. Integration check:
	- Run workflow with a mixed URL set (valid + blocked pages) and verify:
	  - no retry storm in logs,
	  - expected recommendation count reduction,
	  - summary metrics include blocked pages counters.

## Notes for Implementation
- Reuse existing low-quality recommendation warnings as a guardrail, but move rejection earlier where possible to reduce wasted processing.
- Keep source handling generic (status-based) to avoid hardcoding provider-specific logic.

## Root Cause
- The workflow only had coarse website-level memory and a special-case 403 retry path in scraping, so terminal fetch failures were either retried too late or remembered too broadly.
- Nested link expansion fetched parent pages without consulting any persisted blocked URL memory, so the same blocked structures were re-requested on later runs.
- Low-quality extraction results were warned about but still allowed to flow toward validation and persistence.
- Hallucinated ticker skips were logged one-by-one but not surfaced as run summary metrics.

## Resolution
- Added a repository-backed `blocked_url_pattern` table to persist exact blocked URLs plus coarse wildcard URL patterns for terminal HTTP failures.
- Introduced shared fetch policy logic that:
	- checks persisted blocked URL rules before any fetch,
	- treats `401/403/404/410` as terminal,
	- bounds `403` retries to a single browser-render attempt,
	- records blocked URL rules instead of marking the whole domain unusable.
- Wired blocked-rule checks into both `filter_known_bad_node` and nested link expansion so previously blocked URLs are skipped early on later runs.
- Filtered low-quality recommendations before they reach persistence and added workflow metrics for:
	- blocked pages,
	- low-quality filtered candidates,
	- hallucinated tickers skipped.
- Added regression tests for terminal blocked-page classification, cached blocked-rule skipping, and extraction metrics/filtering.

## Verification
- `uv run pytest tests/test_fetch_webpage_content.py tests/test_extract_stock_recommendations.py -q`
- `uv run pytest tests/test_validate_tickers_node.py tests/test_save_stock_recommendation_to_db.py -q`

## Remaining Risks / Follow-up
- The wildcard URL patterning is intentionally conservative and heuristic-based; additional blocked URL shapes may still need tuning if future sources use very different path conventions.
- Existing historical blocked pages are not backfilled into the new table; the cache improves as new runs observe terminal failures.