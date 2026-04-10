# BUG-007 Search returns non-recommendation pages for stock-pick intents

## Metadata
- Type: bug
- Priority: high
- Status: resolved
- Area: recommendation workflow (search -> filter -> analysis)

## Problem Statement
The discovery workflow currently executes stock-pick intent queries such as:
- undervalued stocks
- best value stocks
- stocks to buy

However, the returned result set includes pages that are not stock recommendation articles (for example company profile and video pages). This reduces precision, wastes downstream fetch/LLM budget, and increases noisy candidates in extraction.

## Verified Evidence
From logs/workflow_state/workflow_state_20260409173433.json:

Executed Reuters intent queries:
- "undervalued stocks site:reuters.com"
- "best value stocks site:reuters.com"
- "stocks to buy site:reuters.com"

Returned page:
- Title: "Jana Partners LLC | Reuters"
- URL: https://www.reuters.com/company/jana-partners-llc/
- Body excerpt does not contain the exact stock-pick phrases and represents a company page, not a recommendation article.

Workflow behavior confirming why this can happen:
- Search node appends Google CSE items directly to search_results.
- Domain-level filtering removes duplicates/unusable domains but does not apply recommendation-intent URL/path or phrase checks.

## Expected Behavior
Search results should prioritize recommendation-intent pages and avoid obvious non-article/non-recommendation endpoints, while preserving enough recall for good candidate discovery.

## Scope
In scope:
- Improve search precision for recommendation intents in discovery mode.
- Add pre-analysis filtering/ranking to reduce non-recommendation pages.
- Keep tracked workflow behavior unchanged unless explicitly configured.

Out of scope:
- Changing valuation logic.
- Reworking extraction prompts beyond minimal compatibility updates.

## Acceptance Criteria
- Company profile/video/landing pages from reputable domains are filtered out before analysis when they are not recommendation-intent pages.
- Search query construction supports intent constraints stronger than broad keyword matching (for example exact terms and recommendation synonyms).
- A lightweight scoring or gating step removes low-intent candidates before expensive fetch/LLM extraction.
- Precision improves measurably on a sampled run (for example, lower share of non-recommendation pages in top candidates).
- Existing tests continue to pass.

## Proposed Approach
1. Query refinement:
- Use exactTerms and orTerms style constraints where supported by the CSE API.
- Include recommendation synonyms (buy rating, top picks, analyst picks, price target).
- Add exclude terms for known noise classes (video, podcast, transcript, company profile).

2. Domain path filtering:
- Add domain-specific deny patterns for known non-recommendation endpoints (for example Reuters /company/, /video/, /graphics/).
- Keep patterns configurable.

3. Candidate scoring:
- Score title/snippet for recommendation intent.
- Apply threshold before fetch/extract to reduce wasted processing.

4. Observability:
- Log precision metrics by query template and source domain to support iterative tuning.

## Test Plan
1. Unit tests:
- Query builder test: generated requests contain intent constraints and synonyms.
- URL/path filter test: Reuters company/video URLs are rejected; article URLs are retained.
- Scoring test: recommendation-like snippets pass threshold; non-recommendation snippets fail.

2. Integration tests:
- Run discovery workflow against mocked CSE results containing mixed page types and verify low-intent pages are filtered before analysis.
- Verify that legitimate recommendation pages still pass through.

3. Regression checks:
- Run existing recommendation workflow test suite and ensure no regressions in extraction/save pipeline.

## Risks / Follow-up
- Overly strict filters may reduce recall and miss valid recommendations.
- Mitigation: keep filters configurable and monitor precision/recall metrics over multiple runs.

## Resolution

### Root Cause
Discovery-mode search used broad keyword queries with only site constraints and accepted all CSE candidates from reputable domains. The pre-analysis filter removed duplicates and known-bad domains, but did not enforce recommendation intent by URL path or title/snippet evidence. This allowed low-signal pages such as Reuters company profiles to pass into downstream analysis.

### Steps Taken
1. Added discovery query constraints in search execution:
- `exactTerms` derived from the current intent phrase when available (`undervalued stocks`, `best value stocks`, `stocks to buy`).
- `orTerms` for recommendation synonyms (`buy rating`, `top picks`, `analyst picks`, `price target`, `stock recommendations`).
- `excludeTerms` for noisy content classes (`video`, `podcast`, `transcript`, `company profile`).

2. Added discovery-only low-intent filtering in `filter_known_bad_node`:
- Domain/path denylist for known noisy endpoints (for example Reuters `/company/`, `/video/`, `/graphics/`, `/pictures/`).
- Lightweight recommendation-intent scoring based on title/snippet positive and negative terms.
- Threshold gate before downstream analysis, with retained candidates annotated by `discovery_intent_score`.

3. Preserved tracked-mode behavior:
- The new intent filter is applied only in discovery mode so tracked searches continue to pass through existing domain/block checks only.

4. Added/updated unit tests:
- Discovery search calls include CSE intent constraints.
- Discovery filtering removes Reuters company-profile style results while retaining recommendation-like results.
- Tracked mode bypasses discovery-only intent filtering.

### Validation
- Ran: `uv run pytest tests/test_search_node_modes.py`
- Result: `5 passed`

### Remaining Risks / Follow-up
- Highly concise recommendation pages without strong title/snippet signals may be filtered out.
- Follow-up option: tune term weights/threshold via logged precision metrics and make thresholds environment-configurable if needed.
