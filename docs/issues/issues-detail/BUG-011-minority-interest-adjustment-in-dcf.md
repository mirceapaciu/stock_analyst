# BUG-011 Missing minority-interest adjustment in DCF equity value

## Metadata
- Type: bug
- Priority: high
- Status: resolved
- Area: financial analysis and DCF valuation

## Problem Statement
The DCF implementation converts enterprise value to equity value using only net debt, and then divides by parent common shares outstanding. For companies with material non-controlling interest (minority interest), this allocates 100% of consolidated value to parent common shareholders and can materially overstate fair value per share.

## Verified Evidence
Current DCF implementation in valuation flow:
- Enterprise Value = PV(FCFs) + PV(Terminal Value)
- Equity Value = Enterprise Value - Net Debt
- Fair Value / Share = Equity Value / Shares Outstanding

Observed behavior for IBKR data:
- Total Equity Gross Minority Interest: USD 20,472,000,000
- Stockholders Equity (common): USD 5,363,000,000
- Minority Interest: USD 15,109,000,000

Common equity share of total equity:
- 5,363 / 20,472 = 26.2%

Implication:
- If consolidated FCF is used as valuation input, assigning full resulting equity to parent shares overstates parent fair value unless minority interest is explicitly adjusted.

## Expected Behavior
When deriving parent common equity value from enterprise value, the model should account for minority interest so that value attributable to non-controlling shareholders is not assigned to parent common shareholders.

## Scope
In scope:
- Add minority-interest adjustment to DCF equity bridge.
- Expose applied minority-interest amount and data source in valuation outputs/diagnostics.
- Add tests validating adjustment behavior with and without minority interest.

Out of scope:
- Full redesign of valuation approach for financial-sector firms.
- Introducing new data providers.

## Acceptance Criteria
- DCF equity bridge includes minority-interest adjustment when data is available.
- Valuation output contains a diagnostic field indicating minority-interest amount used (or that none was available).
- For a mocked case with minority interest > 0, fair value per share is lower than the unadjusted baseline.
- Existing valuation tests continue to pass.

## Proposed Approach
1. Add a helper that extracts minority-interest-related fields from available financial data.
2. Update equity-value bridge to use:
- Equity Value (parent) = Enterprise Value - Net Debt - Minority Interest
3. Add fallback behavior:
- If minority interest is unavailable, set adjustment to 0 and emit a note/warning in valuation diagnostics.
4. Extend DCF analysis output to include minority-interest line item.

## Test Plan
1. Unit tests
- Minority interest present: adjustment applied correctly.
- Minority interest missing: zero adjustment and diagnostic note present.
- Regression: no change for cases where minority interest is zero.

2. Integration tests
- End-to-end DCF result for a ticker with known minority interest persists the adjustment fields and produces reduced fair value vs unadjusted baseline.

3. Regression checks
- Run valuation-related tests and broader recommendation tests to verify no unintended breakage.

## Risks / Follow-up
- Reported minority-interest fields can vary across data sources and naming conventions.
- For financial institutions, generic FCF-based DCF may remain weak even after this fix.
- Follow-up: add a valuation-suitability warning for sectors where enterprise-DCF assumptions are unreliable.

## Resolution

### Root Cause
- The DCF equity bridge only deducted net debt from enterprise value, even when consolidated financial statements included minority/non-controlling interests.
- This allocated value attributable to non-controlling shareholders to parent common shares, overstating parent fair value per share.

### Fix Implemented
- Added minority-interest extraction in valuation flow with prioritized sources:
- `stock_info` direct fields (`minorityInterest`, related aliases).
- Balance sheet direct minority-interest rows.
- Derived fallback using `Total Equity Gross Minority Interest - Stockholders Equity` when direct minority-interest rows are unavailable.
- Updated equity bridge formula to:
- `Equity Value (parent) = Enterprise Value - Net Debt - Minority Interest`.
- Added valuation diagnostics fields:
- `minority_interest`
- `minority_interest_source`
- `minority_interest_note` (explicit when adjustment defaults to 0)
- Exposed minority-interest bridge details in DCF UI and printed DCF analysis output.
- Added unit tests covering:
- minority interest present and applied
- minority interest missing with zero fallback and diagnostic note

### Remaining Risks / Follow-up Actions
- Source field coverage may still vary for some tickers/providers and may require additional aliases over time.
- Database persistence schema currently stores core DCF fields; minority-interest diagnostics are available in runtime output and UI but are not persisted as dedicated columns.
