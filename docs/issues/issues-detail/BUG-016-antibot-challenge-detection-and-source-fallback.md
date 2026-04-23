# BUG-016 Detect anti-bot challenge pages and fallback to alternate sources

## Metadata
- Type: bug
- Priority: high
- Status: resolved
- Area: recommendation workflow (fetch -> extraction -> source selection)

## Problem Statement
Some fetched pages return anti-bot challenge content instead of article text, but the workflow still treats the fetch as successful. This allows challenge pages to enter extraction, can produce noisy low-quality outputs, and in some cases may generate incorrect recommendation artifacts from non-article content.

## Verified Evidence
From `logs/workflow_state/workflow_state_20260423094458.json`:
- A Seeking Alpha page contains challenge text in `page_text`: "Before we continue... Press & Hold to confirm you are a human (and not a bot)."
- The same record reports `fetch_status: "ok"`, meaning challenge content was not classified as blocked.
- Another record with the same challenge text still produced a recommendation candidate (`ticker: "MAA"`), showing that anti-bot pages can leak into downstream extraction.

## Current Behavior
- Challenge pages are not consistently detected as blocked outcomes.
- Fetch status can remain `ok` for anti-bot interstitial content.
- Downstream extraction may continue on challenge text and waste compute or emit low-confidence/incorrect recommendations.

## Expected Behavior
- Detect anti-bot challenge/interstitial text patterns during fetch/parse stage.
- Fail fast for challenge pages and classify the source as blocked for the run.
- Persist blocked-source signal so subsequent attempts skip known blocked sources.
- Automatically continue discovery/extraction using alternate eligible sources.
- Ensure challenge pages do not produce recommendation candidates.

## Scope
In scope:
- Add challenge-text detection guardrail in fetch/normalize pipeline.
- Add blocked classification for challenge pages (not only HTTP status-based failures).
- Update source-selection logic to fallback to alternate sources when blocked.
- Add tests for blocked challenge detection and fallback behavior.

Out of scope:
- Any anti-bot bypass/evasion techniques.
- Source-specific authenticated scraping flows.

## Acceptance Criteria
- Pages containing known anti-bot challenge text are classified as blocked and do not proceed to extraction.
- Workflow records blocked-source outcome and skips repeated attempts for the same blocked source/pattern.
- Workflow automatically attempts alternate sources when one source is blocked.
- No recommendations are persisted from challenge-page content.
- Run summaries/metrics include challenge-page blocked counts.
- Automated tests exist for:
  - challenge-text blocked classification,
  - fail-fast behavior before extraction,
  - alternate-source fallback path,
  - prevention of persistence from challenge-page content.

## Test Plan
1. Unit tests:
- Feed synthetic page text containing anti-bot phrases and assert blocked classification.
- Verify extraction is not called when blocked classification is triggered.

2. Workflow integration tests:
- Provide mixed candidate set (blocked challenge page + valid alternate pages).
- Assert blocked source is skipped and alternate source is processed.
- Assert final recommendations exclude challenge-page-derived outputs.

3. Regression checks:
- Existing blocked-status handling (401/403/404/410) remains intact.
- Existing low-quality filtering and ticker-validation guardrails continue to pass.

## Implementation Notes
- Keep challenge detection pattern-based and centrally configurable to support future phrase updates.
- Reuse existing blocked URL/pattern persistence mechanism where available instead of introducing a parallel store.

## Root Cause
- Fetch policy only classified terminal failures by HTTP status and cached blocked URL patterns.
- Anti-bot interstitial pages could return HTTP 200, so they were treated as successful fetches.
- Because those pages were marked as `fetch_status: ok`, extraction could run on challenge text and sometimes emit noisy candidates.

## Resolution
- Added challenge-page detection in fetch policy via `detect_challenge_page_text` and `_raise_if_challenge_page` in `src/recommendations/workflow.py`.
- Added fail-fast classification path that raises `TerminalFetchFailure` with a dedicated `failure_type` for challenge pages.
- Persisted challenge-blocked URL rules using existing `blocked_url_pattern` storage with reason `challenge_page`.
- Extended blocked metrics to include `blocked_challenge_pages` and surfaced this count in workflow status summaries.
- Ensured cached blocked rules preserve challenge classification when re-matched.
- Added regression tests for:
  - fail-fast challenge detection and extraction skip,
  - automatic continuation with alternate sources when one source is challenge-blocked.

## Verification
- `uv run pytest tests/test_fetch_webpage_content.py -q` (15 passed)

## Remaining Risks / Follow-up
- Challenge text patterns are heuristic and may require updates if source interstitial wording changes significantly.
- Consider moving challenge phrase patterns to config for easier runtime tuning without code changes.
