# FEAT-009 Add DB-backed company-name pre-LLM validation

## Metadata
- Type: feature
- Priority: medium
- Status: new
- Area: recommendation workflow (pre-LLM candidate gating)

## Problem Statement
Pre-LLM gating currently relies mainly on ticker-like patterns and heuristic recommendation terms from title/snippet/metadata. This can miss useful evidence from known company names already present in the local `stock` table and can also send weak candidates to LLM unnecessarily.

## Expected Behavior
Before LLM analysis, the workflow should check whether page text/title/snippet contains company names from the local stock universe and use that signal to improve gating decisions.

## Scope
In scope:
- Add DB-backed company-name matching as a pre-LLM signal.
- Integrate this signal into discovery scoring/gating logic.
- Keep current noise filters and ticker-based checks.
- Add tests for positive and negative scenarios.

Out of scope:
- Replacing existing extraction prompts.
- Full NER model deployment.
- Schema migrations unless strictly needed.

## Acceptance Criteria
- Pre-LLM gating uses DB company-name match as a weighted signal (not strict hard requirement by default).
- Candidates with strong recommendation language plus DB-name matches are retained even without ticker patterns.
- Generic pages without DB-name matches and without recommendation intent remain filtered.
- Matching is normalized (case/spacing/punctuation/suffix handling).
- Unit tests cover:
  - positive DB-name hit retention,
  - negative generic page rejection,
  - ambiguous names with low-confidence handling.
- Existing search/extraction tests continue to pass.

## Proposed Approach
1. Build normalized company-name cache from DB
- Load stock names from `stock` table once per workflow run.
- Normalize tokens (casefold, punctuation stripping, suffix normalization like Inc/Corp/PLC).

2. Add pre-LLM DB-name evidence helper
- Evaluate title + snippet (+ selected metadata) for company-name matches.
- Return evidence score and matched names.

3. Integrate into discovery gate
- Gate logic becomes hybrid score:
  - ticker-like evidence
  - recommendation-intent language
  - DB-name evidence
  - negative/noise penalties
- Keep threshold configurable.

4. Add observability
- Track metrics such as `db_name_matches`, `db_name_helped_pass`, `db_name_low_confidence_skips`.

## Test Plan
1. Unit tests
- DB-name match + recommendation terms -> candidate passes pre-LLM gate.
- No DB-name match + weak intent -> candidate filtered.
- Name normalization works (`Meta Platforms, Inc.` vs `Meta`).

2. Integration checks
- Run discovery workflow on mixed dataset and compare:
  - pre-LLM pass rate,
  - recommendation yield,
  - false-positive rate.

3. Regression checks
- Run existing tests for search mode behavior and extraction quality.

## Risks / Follow-up
- Risk: common-word company names can increase false positives.
- Mitigation: require recommendation-intent co-signal and confidence thresholds.
- Follow-up: maintain alias table for frequent abbreviations and brand/legal-name mappings.
