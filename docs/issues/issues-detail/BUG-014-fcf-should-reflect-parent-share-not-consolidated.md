# BUG-014 FCF input should reflect parent common shareholders' share, not consolidated FCF

## Metadata
- Type: bug
- Priority: high
- Status: resolved
- Area: financial analysis and DCF valuation

## Problem Statement
The DCF valuation uses consolidated free cash flow as the starting point for projections, but for companies with material minority interest, this overstates the cash flow available to parent common shareholders. The valuation adjusts the final equity value for minority interest (BUG-011 fix), but the input FCF should have been minority-interest-adjusted from the start.

Example (IBKR):
- Consolidated FCF: USD 15,744,000,000
- Total Equity (parent + minority): USD 20,472,000,000
- Stockholders Equity (parent only): USD 5,363,000,000
- Minority Interest: USD 15,109,000,000
- Parent ownership %: 5,363 / 20,472 = 26.2%
- Parent-adjusted FCF should be: 15,744,000,000 × 26.2% ≈ USD 4,125,000,000 (not USD 15,744,000,000)

Using consolidated FCF with a 26% parent equity stake means the model compresses 74% of cash flow onto 26% of the equity base, dramatically inflating the per-share value and terminal value projections.

## Verified Evidence
- BUG-011 added minority-interest adjustment to the equity bridge.
- However, the starting current_fcf used in projections remains consolidated FCF.
- For IBKR, the lack of FCF adjustment combined with an 81.5% growth rate produced USD 8,936.97 fair value per share vs. current market price USD 79.62 (11,124% upside).

## Expected Behavior
When calculating DCF for a company with minority interest:
1. Compute or infer the parent common shareholders' ownership percentage.
2. Adjust starting FCF (and potentially growth assumptions) to reflect parent's share.
3. Project adjusted FCF forward with appropriate growth rates.
4. Apply minority-interest adjustment to the final equity value (as done in BUG-011).

## Scope
In scope:
- Add minority-interest ownership % calculation to valuation inputs.
- Adjust starting current_fcf to reflect parent common share (or warn if ownership % cannot be determined).
- Optionally scale growth assumptions proportionally if appropriate.
- Add diagnostics to valuation output explaining FCF adjustment and ownership %.

Out of scope:
- Full redesign of DCF for minority-heavy structures (e.g., REIT-like vehicles).
- New external data providers.

## Acceptance Criteria
- DCF input path computes/extracts parent ownership % and parent FCF amount.
- Valuation output includes ownership % and adjusted FCF diagnostics.
- For IBKR-like scenario (26% parent stake), projected FCF is adjusted proportionally.
- Fair value per share decreases materially when FCF adjustment is applied (relative to unadjusted baseline).
- Tests validate both present and missing ownership % scenarios.
- Existing valuation tests continue to pass.

## Proposed Approach
1. Add ownership % extraction
- Derive from balance sheet: Stockholders Equity / Total Equity (Gross Minority Interest)
- Use stock info fields if available (e.g., `parentOwnershipPct`).
- Default to 100% (no adjustment) if unavailable, with diagnostic note.

2. Adjust FCF
- Multiply current_fcf by ownership % to get parent FCF.
- Optionally apply same ratio to projected growth rates (if desired).

3. Expose diagnostics
- Include parent_ownership_pct in valuation output.
- Include original_consolidated_fcf and adjusted_parent_fcf for transparency.
- Document source of ownership % calculation.

4. Add fallback behavior
- If ownership % is unavailable, proceed with consolidated FCF but emit warning.

## Test Plan
1. Unit tests
- Ownership % calculated correctly from balance sheet.
- FCF adjusted proportionally for various ownership levels (100%, 50%, 26%, etc.).
- Fair value per share is lower when FCF adjustment is applied.
- Missing ownership % triggers diagnostic note and proceeds with full consolidated FCF.

2. Integration tests
- End-to-end DCF for IBKR-like scenario with 26% parent stake produces lower fair value than unadjusted baseline.
- Valuation diagnostics include ownership % and FCF adjustments.

3. Regression checks
- Companies with 100% parent ownership (no minority interest) show no change in valuation.
- Existing valuation test suite passes.

## Risks / Follow-up
- Ownership % determination can be complex for multi-tier or complex capital structures.
- Growth rate adjustment is optional and may require domain judgment; conservatively, only adjust FCF magnitude, not rates.
- Follow-up: per-sector guidelines for capital-structure adjustments and minority-heavy entity handling.

## Resolution

### Root Cause
`do_dcf_valuation` used consolidated FCF as the DCF input without scaling it to the parent's ownership share. The equity bridge (BUG-011) subtracted minority interest at the end, but the projected cash flows were still inflated by the minority-owned portion, overstating the terminal value and all projected FCFs.

### Steps Taken
1. Added `_get_parent_ownership_pct(ticker, info)` helper in `src/services/valuation.py`.
   - Derives ownership % from balance sheet: `Stockholders Equity / Total Equity Gross Minority Interest`.
   - Defaults to `(1.0, 'unavailable', note)` when the required rows are absent.
2. In `do_dcf_valuation`, after extracting `current_fcf`, multiplies it by the ownership % when < 100%.
3. Added five new fields to the return dict: `parent_ownership_pct`, `parent_ownership_pct_source`, `parent_ownership_pct_note`, `original_consolidated_fcf`, `adjusted_parent_fcf`.
4. Updated `print_dcf_analysis` to display FCF adjustment diagnostics.
5. Added `TestDcfParentOwnershipFcfAdjustment` unit test class (3 tests: 26% stake, unavailable data, 100% ownership).

### Remaining Risks / Follow-up
- Growth rate scaling (not just FCF magnitude) was intentionally left out per scope; may be revisited.
- Multi-tier structures with layered minority interests are not handled by this change.
