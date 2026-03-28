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