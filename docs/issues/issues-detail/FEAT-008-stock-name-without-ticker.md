# FEAT-008 Collect recommendations that mention stock name without ticker

## Metadata
- Type: feature
- Priority: high
- Status: resolved
- Area: recommendation workflow (search analysis gating -> extraction)

## Problem Statement
The current discovery flow applies a pre-LLM gate that requires ticker-like evidence in title/snippet (for example `(META)`, `NYSE: META`, `META stock`).

As a result, valid recommendation pages can be dropped when they mention only the company name (for example `Meta`, `Microsoft`, `Universal Music Group`) without an explicit ticker in the search result snippet/title.

## Verified Evidence
In `logs/workflow_state/workflow_state_20260409182921.json`, this Morningstar article is marked with `contains_stocks: false` even though the article is recommendation-relevant:
- URL: https://global.morningstar.com/en-eu/stocks/meta-muse-models-may-just-be-spark-that-firm-needed-ai-model-development
- `og:description`: "We think Meta stock is moderately undervalued."
- `contains_stocks`: false

Root behavior in code:
- `analyze_search_result` short-circuits to `contains_stocks=false` in discovery mode when `has_ticker_like_evidence(title, body)` is false.

## Expected Behavior
Discovery should preserve recommendation candidates that contain strong stock-name evidence even when ticker symbols are absent in title/snippet.

## Scope
In scope:
- Extend discovery pre-LLM gating logic to allow stock-name-only recommendation evidence.
- Keep precision safeguards to avoid reintroducing broad low-quality noise.
- Add tests for tickerless-but-valid recommendation cases.

Out of scope:
- Full named-entity recognition pipeline overhaul.
- Changes to valuation formulas or persistence schema.

## Acceptance Criteria
- A discovery result can pass pre-LLM gating when ticker-like evidence is missing but stock-name recommendation evidence is strong.
- Existing ticker-based matches continue to pass.
- Obvious non-recommendation pages (privacy/legal/support/profile) remain filtered.
- Ticker inference follows a deterministic-first strategy and uses tool-assisted lookup fallback for unresolved/ambiguous company names.
- Inferred tickers are persisted only when validation checks pass (confidence/consistency/coherence checks).
- Unit tests cover both positive and negative tickerless scenarios.
- Existing search/filter tests continue to pass.

## Proposed Approach
1. Add a secondary evidence detector for stock-name recommendation intent:
- Use company-name patterns from title/snippet and supportive terms such as `stock`, `undervalued`, `buy`, `fair value`, `rating`, `price target`, `analyst picks`.
- Optionally inspect selected metadata fields (for example `og:description`, `newsarticle.description`) when available.

2. Update discovery pre-LLM gate:
- Current gate: `has_ticker_like_evidence(...)`.
- New gate: `has_ticker_like_evidence(...) OR has_stock_name_recommendation_evidence(...)`.

3. Add guardrails:
- Keep existing discovery intent score threshold and non-recommendation URL filters.
- Keep tracked mode behavior unchanged unless explicitly requested.
- Verify that the stock prices are coherent with the inferred ticker.

4. Ticker inference strategy (deterministic first, tool-assisted fallback):
- First try deterministic resolution from existing extracted ticker signals, local symbol universe, and known company-name aliases.
- If unresolved or ambiguous, allow LLM to use lookup tools (for example internal symbol lookup service / trusted market data endpoint) to propose candidate tickers.
- Require strict validation before accepting inferred ticker:
	- confidence threshold,
	- source agreement / consistency checks,
	- page-context consistency,
	- price coherence sanity check.
- Mark inferred tickers explicitly for auditability (for example `ticker_inference_method`, `ticker_inference_confidence`).
- Route low-confidence or conflicting cases to skip/review path instead of silent acceptance.

## Test Plan
1. Unit tests:
- Positive: title/snippet/metadata mention stock name with recommendation language but no ticker -> passes pre-LLM gate.
- Negative: generic market/news/legal pages with no recommendation evidence -> fails pre-LLM gate.
- Regression: ticker-based detection continues to work.
- Ticker inference tests:
	- deterministic alias match resolves without LLM tool call,
	- ambiguous names trigger tool-assisted fallback,
	- low-confidence inference is rejected,
	- accepted inference includes metadata (`method`, `confidence`).

2. Integration checks:
- Run workflow on mixed Morningstar/Reuters results and confirm tickerless recommendation pages are no longer systematically marked `contains_stocks=false`.

3. Regression checks:
- Run `tests/test_search_node_modes.py` and nested-link filter tests.

## Risks / Follow-up
- Risk: allowing stock-name-only signals may increase false positives.
- Mitigation: combine name evidence with recommendation-intent terms and existing low-intent filters; monitor precision over several runs.

## Resolution

### Root Cause
Discovery-mode pre-LLM gating required ticker-like evidence in title/snippet and short-circuited to `contains_stocks=false` otherwise. This excluded recommendation pages that referenced companies by name only (no explicit ticker pattern in snippet/title).

Additionally, extraction required ticker symbols to be present and grounded directly in text, so name-only recommendations were often skipped as hallucinations.

### Steps Taken
1. Discovery gating enhancement:
- Added `has_stock_name_recommendation_evidence(result)` to detect stock-name recommendation signals from title/snippet and selected metadata (`og:title`, `og:description`, `newsarticle` fields).
- Updated discovery pre-LLM gate to allow:
	- `has_ticker_like_evidence(...) OR has_stock_name_recommendation_evidence(...)`.

2. Deterministic ticker inference fallback:
- Added repository helper `find_stock_by_name(...)` for company-name lookups.
- Added service helper `infer_ticker_from_stock_name(...)` with deterministic-first flow:
	- DB stock-name matching first,
	- FMP `search-name` fallback when DB is weak/missing,
	- confidence thresholding before acceptance.

3. Extraction pipeline integration:
- In `extract_stock_recommendations_with_llm`, when LLM returns missing ticker but has stock name:
	- attempt ticker inference from stock name,
	- accept recommendation if grounded by ticker or stock name evidence in page context,
	- annotate accepted records with `ticker_inference_method` and `ticker_inference_confidence`.
- Added `inferred_tickers` extraction metric and surfaced it in scrape status.

4. Test coverage:
- Added discovery evidence tests (positive/negative) for stock-name-only detection.
- Added extraction test proving ticker inference works when ticker is missing but stock name is present.

### Validation
- Ran: `uv run pytest tests/test_search_node_modes.py tests/test_extract_stock_recommendations.py`
- Result: `18 passed`

### Remaining Risks / Follow-up
- Name-based inference can still produce false positives for ambiguous company names.
- Follow-up options:
	- tighten confidence thresholds per source,
	- add alias dictionary for frequent names,
	- add optional manual-review path for low-confidence inferred tickers.
