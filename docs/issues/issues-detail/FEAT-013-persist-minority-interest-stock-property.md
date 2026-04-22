# FEAT-013 Persist minority interest as stock-level property

## Metadata
- Type: feature
- Priority: medium
- Status: new
- Area: financial data persistence and valuation diagnostics

## Problem Statement
Minority interest is currently computed/loaded during valuation execution and returned in runtime diagnostics, but it is not persisted as a stock-level property in the database. This prevents consistent reuse across analyses, limits observability of source/value history, and can trigger repeated extraction logic on each valuation run.

## Verified Evidence
- BUG-011 added minority-interest adjustment in the DCF equity bridge and exposed runtime fields:
  - minority_interest
  - minority_interest_source
  - minority_interest_note
- Existing persistence stores core DCF valuation outputs and stock info fields, but minority-interest diagnostics are not persisted as dedicated stock properties.

## Expected Behavior
Minority interest should be persisted in the database as stock-level financial property data, with source metadata and update semantics that allow valuation and downstream analytics to reuse it deterministically.

## Scope
In scope:
- Add stock-level minority-interest persistence in DB schema/repository flow.
- Store amount and source metadata (including derived-source indicator when applicable).
- Ensure valuation reads persisted value when available, with fallback refresh behavior.
- Add tests for persistence, retrieval, and valuation reuse behavior.

Out of scope:
- Historical time-series warehousing of minority interest by filing period.
- New external data provider integrations.

## Acceptance Criteria
- DB schema includes stock-level fields for minority-interest amount and source metadata.
- Data ingestion/retrieval path persists and updates minority-interest values without breaking existing stock records.
- Valuation path consumes persisted minority-interest property when present.
- Tests validate:
  - persistence for available minority-interest input
  - retrieval/use in valuation bridge
  - fallback behavior when field is unavailable
- Existing valuation and repository tests continue to pass.

## Proposed Approach
1. Schema and repository updates
- Extend stock table (or equivalent stock metadata storage) with minority-interest columns.
- Update upsert/get methods to include minority-interest amount and source.

2. Data extraction and write path
- Reuse BUG-011 extraction logic to populate stock-level fields.
- Persist source classification (stock info direct, balance sheet direct, derived, unavailable).

3. Valuation read path
- Prefer persisted stock-level minority-interest value.
- If missing/stale, compute from current financials, then persist refreshed value.

4. Observability
- Keep runtime valuation diagnostics aligned with persisted fields.
- Log when fallback recomputation occurs due to missing persisted data.

## Test Plan
1. Unit tests
- Repository upsert/get includes minority-interest fields.
- Extraction result is written correctly for direct and derived sources.

2. Integration tests
- End-to-end valuation for a mocked ticker uses persisted minority-interest value when present.
- Missing persisted value triggers fallback extraction and persists the refreshed value.

3. Regression checks
- Run repository and valuation tests to ensure no breaking changes.

## Risks / Follow-up
- Field naming across data sources can vary; alias mapping may need expansion.
- Potential staleness if persisted value is not refreshed with new filings.
- Follow-up: define freshness policy tied to financial statement update cadence.
