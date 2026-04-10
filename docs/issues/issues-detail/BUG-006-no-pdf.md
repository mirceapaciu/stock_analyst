# BUG-006 The recommendations do not contain the saved PDF

## Metadata
- Type: bug
- Priority: high
- Status: resolved
- Area: recommendation workflow

## Problem Statement
The workflow is not saving a PDF file for the webpage anymore, although it used to do this in the past.

## Scope
In scope:
- Save the PDF for the webpage containing the recommendation.
- Tests covering the above behavior.

Out of scope:
- Major redesign of extraction prompts.

## Root Cause
- The scrape flow defaulted to non-browser HTTP fetch for most domains.
- Non-browser fetch intentionally returns `pdf_bytes=None`.
- `scrape_single_page` only attempted one fetch path, so recommendation pages frequently reached persistence with no `pdf_content`, and no PDF file was written.

## Resolution
- Added a targeted fallback in `scrape_single_page`:
	- If a page produced stock recommendations but has no `pdf_bytes`, trigger one browser fetch solely to capture PDF bytes.
	- Keep existing lightweight non-browser fetch as the primary path.
	- Log a warning (without failing the workflow) if fallback PDF capture fails.

## Test Coverage
- Added regression tests in `tests/test_fetch_webpage_content.py`:
	- Recommendation pages trigger browser fallback and store `pdf_content`.
	- Non-recommendation pages do not trigger extra browser fetch.

## Remaining Risks / Follow-up
- Some pages can still block headless browser PDF generation; in those cases the workflow continues without a PDF, with warning logs for investigation.

