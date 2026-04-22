# BUG-012 Add financial-sector guardrail for generic DCF

## Metadata
- Type: bug
- Priority: high
- Status: new
- Area: financial analysis and DCF valuation

## Problem Statement
The current generic DCF implementation is applied uniformly across sectors, including financial-sector tickers (for example brokers, banks, insurers). For these sectors, enterprise-style FCF-based DCF assumptions are often not comparable to non-financial operating businesses, which can produce unstable or misleading fair value and recommendation outputs.

## Verified Evidence
- IBKR valuation in BUG-010 produced implausible upside and recommendation confidence under generic DCF assumptions.
- Existing DCF flow does not include a sector suitability gate before valuation/recommendation output.
- Existing outlier controls (growth/terminal diagnostics) do not guarantee sector-appropriateness.

## Expected Behavior
When a ticker is identified as financial-sector (or another configured excluded sector), the system should either:
- Exclude generic DCF valuation from recommendation scoring, or
- Produce valuation with a clear low-confidence warning and downgrade/override recommendation behavior.

The behavior must be explicit, deterministic, and visible in outputs.

## Scope
In scope:
- Add sector guardrail policy for generic DCF.
- Add configurable mode: `exclude` or `warn` for guarded sectors.
- Add explicit diagnostics in valuation/recommendation outputs indicating guardrail trigger and reason.
- Add tests for financial-sector guardrail behavior.

Out of scope:
- Building a full sector-specific valuation model for financial institutions.
- Replacing the existing DCF engine for all sectors.

## Acceptance Criteria
- Guardrail is applied for financial-sector tickers based on available stock metadata (for example `sector`/`industry`).
- In `exclude` mode: valuation result is suppressed from recommendation scoring and output includes structured reason.
- In `warn` mode: valuation remains available but output includes a high-visibility warning and recommendation confidence is reduced/overridden.
- Guardrail decision and reason are persisted in valuation diagnostics.
- Existing non-financial ticker flows are unaffected.
- Tests cover both guarded and unguarded paths.

## Proposed Approach
1. Define guardrail policy
- Add configuration for guarded sectors and behavior mode (`exclude` vs `warn`).

2. Implement sector detection
- Use stock metadata from existing stock-info source (`sector`, `industry`), with safe fallback when missing.

3. Integrate into valuation/recommendation path
- Apply guardrail before recommendation decisioning that consumes DCF outputs.
- Emit deterministic diagnostic fields, for example:
  - `dcf_guardrail_triggered`
  - `dcf_guardrail_reason`
  - `dcf_guardrail_mode`

4. Surface transparency
- Show guardrail status in UI/log output and persisted valuation records where applicable.

## Test Plan
1. Unit tests
- Financial-sector ticker with `exclude` mode: DCF excluded from scoring, reason emitted.
- Financial-sector ticker with `warn` mode: warning emitted and recommendation downgraded/overridden.
- Non-financial ticker: guardrail not triggered.
- Missing sector metadata: deterministic fallback behavior documented and tested.

2. Integration tests
- End-to-end recommendation flow confirms guarded ticker does not produce unqualified high-conviction signal from generic DCF.

3. Regression checks
- Run valuation and recommendation suites to ensure no regressions for non-financial sectors.

## Risks / Follow-up
- Sector labels from providers may be inconsistent or missing; fallback logic must be conservative and transparent.
- Some diversified firms can be hard to classify; consider allowlist/override support.
- Follow-up: evaluate sector-specific valuation alternatives for financial firms.

## Resolution Summary

### Root Cause
- `do_dcf_valuation` applied a generic enterprise-style FCF DCF model uniformly, without checking whether ticker sector/industry was suitable for that model.
- Recommendation output derived directly from DCF upside had no sector guardrail override path.

### Fix Implemented
- Added configurable DCF guardrail policy in `fin_config.py`:
  - `DCF_GUARDRAIL_MODE` with supported values: `exclude` (default) or `warn`.
  - `DCF_GUARDED_SECTOR_KEYWORDS` as configurable keyword list for sector/industry matching.
- Added deterministic sector suitability evaluation in `services/valuation.py` using stock metadata (`sector`, `industry`).
- Added structured diagnostics to valuation outputs:
  - `dcf_guardrail_triggered`
  - `dcf_guardrail_mode`
  - `dcf_guardrail_reason`
  - `dcf_guardrail_warning`
  - `dcf_guardrail_matched_keyword`
  - `dcf_guardrail_sector`
  - `dcf_guardrail_industry`
- Implemented policy behavior:
  - `exclude`: suppresses valuation outputs (`fair_value_per_share` and related valuation fields become `None`) and emits explicit guardrail reason.
  - `warn`: keeps valuation outputs but overrides recommendation to `HOLD` with reduced confidence.
- Added recommendation diagnostics in valuation output:
  - `dcf_recommendation`
  - `dcf_recommendation_confidence`
- Surfaced guardrail behavior in UI:
  - DCF page shows guardrail warnings/reasons and stops excluded valuation display.
  - Recommendations batch valuation treats excluded cases as skipped, with explicit reason.

### Test Coverage Added
- Financial-sector ticker in `exclude` mode: valuation suppressed + reason emitted.
- Financial-sector ticker in `warn` mode: valuation retained + recommendation downgraded.
- Non-financial ticker: no guardrail trigger.
- Missing sector metadata: deterministic non-trigger fallback reason.

### Remaining Risks / Follow-up
- Provider sector/industry labels can vary; keyword policy may need periodic tuning.
- Diversified firms may need explicit allowlist/override handling in future.
