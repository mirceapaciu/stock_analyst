# BUG-010 IBKR DCF valuation produces implausible fair value outlier

## Metadata
- Type: bug
- Priority: high
- Status: new
- Area: financial analysis and DCF valuation

## Problem Statement
The DCF valuation output for IBKR is producing an extreme fair value per share (USD 8,936.97) and upside signal (+11,124.5%) that is not plausible relative to the current market price (USD 79.62). The projection appears to be driven by compounding an exceptionally high free cash flow growth rate (81.5% CAGR for 5 years), resulting in a terminal value that dominates the valuation and creates a misleading STRONG BUY recommendation.

## Verified Evidence
From the provided DCF analysis for IBKR:

### Current market context
- Current Price: USD 79.62
- Shares Outstanding: 445,616,477

### Valuation inputs
- Forecast Years: 5
- Current FCF: USD 15,744,000,000
- Discount Rate (WACC): 8.5%
- Terminal Growth Rate: 2.5%
- Conservative Factor: 90.0%
- Net Debt: USD 0

### Projected free cash flows (81.5% growth each year)
- Year 1: USD 28,573,318,271
- Year 2: USD 51,856,867,188
- Year 3: USD 94,113,488,992
- Year 4: USD 170,803,777,602
- Year 5: USD 309,986,706,002

### Valuation outputs
- Terminal Value: USD 5,280,835,286,021
- Present Value of FCFs: USD 473,182,545,890
- Present Value of Terminal: USD 3,509,280,465,202
- Total Enterprise Value: USD 3,982,463,011,093
- Equity Value: USD 3,982,463,011,093

### Fair value and recommendation
- Fair Value per Share: USD 8,936.97
- Conservative Fair Value: USD 8,043.28
- Upside Potential: 11,124.5%
- Conservative Upside: 10,002.1%
- Recommendation: STRONG BUY

## Expected Behavior
DCF outputs should be bounded by realistic assumptions and validation checks so that:
- Growth assumptions do not produce runaway multi-trillion terminal values without warning.
- Fair value outputs that imply extreme upside are flagged as low-confidence or rejected.
- The recommendation engine does not emit high-conviction signals from evidently unstable valuation inputs.

## Scope
In scope:
- Validate and constrain growth-related assumptions used in DCF projections.
- Add guardrails for outlier fair value/upside outputs.
- Add diagnostics to explain which assumptions caused outlier valuations.
- Add tests for extreme-growth scenarios and recommendation safety.

Out of scope:
- Replacing DCF with a different valuation framework.
- Introducing new external data sources unless needed for validation thresholds.

## Acceptance Criteria
- DCF projection logic applies explicit guardrails for extreme FCF growth trajectories (for example capped growth, tapering, or outlier rejection).
- Valuation output includes an outlier check; when triggered, recommendation is downgraded or withheld with a clear warning.
- Terminal value contribution ratio is evaluated; unusually dominant terminal values trigger a safety warning.
- The IBKR input evidence above no longer produces an unconditional STRONG BUY without an outlier warning/override.
- Existing valuation and recommendation tests continue to pass.

## Proposed Approach
1. Add input and projection guardrails
- Validate current FCF and derived growth assumptions.
- Apply configurable max-growth/tapering logic across forecast years.

2. Add output sanity checks
- Compute diagnostic ratios (for example PV terminal / enterprise value, implied CAGR vs thresholds).
- Mark valuation as outlier when diagnostics exceed configured bounds.

3. Integrate recommendation safety
- If outlier flag is set, force recommendation confidence downgrade or emit NEEDS_REVIEW.
- Persist outlier diagnostics for observability and review.

4. Improve transparency
- Expose key valuation diagnostics in logs/UI to aid analyst review.

## Test Plan
1. Unit tests
- Extreme-growth scenario reproducing current IBKR pattern triggers outlier flag.
- Reasonable-growth scenario remains unflagged.
- Recommendation downgrade/hold behavior activates when outlier flag is set.

2. Integration tests
- End-to-end valuation flow with IBKR-like inputs does not emit unqualified STRONG BUY from outlier assumptions.
- Workflow output includes diagnostic explanation for the outlier decision.

3. Regression checks
- Run existing valuation and recommendation test suites to ensure no regressions in normal cases.

## Risks / Follow-up
- Overly strict thresholds may suppress valid high-growth opportunities.
- Mitigation: keep thresholds configurable and calibrate with historical backtests.
- Follow-up: consider per-sector growth bounds and confidence scoring based on data quality.
