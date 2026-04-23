# FEAT-015 Add Residual Income valuation tab with DB caching

## Metadata
- Type: feature
- Priority: high
- Status: new
- Area: valuation services, valuation persistence, Streamlit UI

## Problem Statement
The platform currently offers DCF valuation only. For companies where equity-based valuation is more informative, users need a Residual Income (RI) valuation option. Today there is no RI calculation flow, no RI-specific UI tab, and no RI valuation cache in DuckDB.

## Expected Behavior
- Users can manually valuate a stock with the Residual Income model from a dedicated UI tab.
- RI valuation logic lives in a dedicated service file: `src/services/ri_valuation.py`.
- RI valuation results are cached in DuckDB similarly to DCF (same operational behavior: write-through on compute, stable retrieval semantics for latest result).
- Existing stock metadata and repository patterns are reused where practical.

## Basic Design Decisions
1. Service separation
- Add a new module: `src/services/ri_valuation.py`.
- Keep RI model logic isolated from DCF logic for maintainability and easier testing.
- Reuse shared data access helpers from `services.financial` and currency/risk utilities where relevant.

2. UI integration as a new valuation tab
- Rename `src/ui/pages/2_DCF_Valuation.py` → `2_Valuation.py` and introduce `st.tabs(["💰 DCF", "📐 Residual Income"])`.
- Both tabs serve manual single-stock valuation; keeping them on one page lets users compare results without sidebar navigation.
- Extract each tab's rendering into a private function (`_render_dcf_tab()`, `_render_ri_tab()`) to keep the page file maintainable.
- Keep input/output layout aligned with the existing DCF tab (ticker input, model assumptions, key metrics, expandable diagnostics).
- Reuse existing auth/session/page conventions used by the current DCF page.

3. Persistence approach
- Prefer a dedicated `ri_valuation` DuckDB table rather than overloading `dcf_valuation`, because RI uses different model assumptions and output fields.
- Reuse `stock_id` foreign key and date/versioning/upsert patterns from DCF persistence.
- Reuse JSON-serialization approach for list/diagnostic fields where needed.

4. Code reuse and extension
- Reuse existing `StockRepository` lifecycle and DB initialization flow.
- Extend repository with RI-specific methods (for example save/get latest) and extract small shared helper(s) if DCF/RI SQL serialization logic would otherwise be duplicated.
- Avoid introducing a generic mega-table unless both valuation models can be represented cleanly without sparse/null-heavy schema.

5. RI mapping thresholds — proposed initial bands :

| Label | Upside condition | Rationale |
|---|---|---|
| `STRONG BUY` | upside > 30% | RI is a stricter intrinsic model; a higher bar reduces false positives from book-value noise |
| `BUY` | upside > 15% | Meaningful margin of safety above RI fair value |
| `HOLD` | -15% ≤ upside ≤ 15% | Within noise band of model precision |
| `SELL` | upside < -15% | Price materially above RI intrinsic value |
| `NEEDS_REVIEW` | triggered by guardrail / missing data | Mirrors DCF guardrail pattern; suppresses recommendation when model inputs are unreliable |

  These thresholds should be defined in `fin_config.py` under a clearly separated RI section (for example `RI_STRONG_BUY_THRESHOLD`, `RI_BUY_THRESHOLD`, etc.) and consumed by `ri_valuation.py`.


6. Recommendation label UX (RI-specific)
- RI uses its own upside-to-recommendation mapping with thresholds tuned for RI model behavior.
- Implement RI mapping in `src/services/ri_valuation.py` (or a RI-specific helper module) instead of reusing DCF thresholds.
- Surface RI threshold definitions in the RI tab help text for transparency.

## Proposed Scope
In scope:
- New RI valuation service module in `src/services/ri_valuation.py`.
- RI valuation UI tab with inputs, outputs, and diagnostics similar to DCF UX.
- DuckDB schema/repository changes for RI result caching.
- Tests for RI calculation, persistence, and UI-triggered service behavior.

Out of scope:
- Replacing existing DCF workflow.
- Refactoring all valuation code into a unified valuation framework in this issue.
- New external data providers.
- Any writes to recommendations metadata (for example `fair_price_dcf`-style fields).

## Acceptance Criteria
- RI valuation can be executed from UI and returns fair value style outputs.
- RI logic is implemented in `src/services/ri_valuation.py` (not mixed into DCF module).
- RI results are persisted and can be retrieved from DuckDB for the same stock/assumption set and valuation date.
- Existing `stock` table and financial statement retrieval paths are reused.
- Repository changes are minimal and maintainable; duplicated DCF patterns are either reused or cleanly abstracted.
- New tests cover:
  - RI core model calculations
  - RI persistence upsert/read behavior
  - UI-to-service integration sanity path
- Existing valuation and repository tests continue to pass.

## Suggested Implementation Notes
1. Data model
- RI inputs should include (at minimum): cost of equity, forecast horizon, terminal assumptions, and starting book value / earnings-derived residual income components.
- RI outputs should include: intrinsic value per share, current price, upside/downside %, recommendation bucket, and model diagnostics.

2. DB schema candidate
- New table `ri_valuation` with:
  - `stock_id`, `valuation_date`
  - input columns (`in_*` pattern, mirroring DCF naming convention)
  - output columns (fair value, upside, core bridge values)
  - optional JSON text columns for projection vectors/diagnostics
  - unique constraint comparable to DCF assumption uniqueness.

3. Maintainability guardrail
- If duplication appears between DCF and RI repository methods, create small internal helpers in `StockRepository` for common JSON field normalization and upsert execution patterns.

## Test Plan
1. Unit tests
- RI formula correctness on deterministic mocked financial inputs.
- Edge cases: missing required financial fields, non-positive book value handling, and invalid terminal assumptions.

2. Repository tests
- Insert/update conflict path in `ri_valuation` unique key.
- Latest RI valuation retrieval for a stock.

3. Integration/regression
- UI invocation triggers RI service and shows key metrics.
- Existing DCF, risk, and stock repository tests remain green.

## Risks / Follow-up
- Financial-sector companies may require RI-specific guardrails or stricter assumption bounds.
- Data availability for book value and clean-surplus assumptions can vary by ticker/source.
- Follow-up candidate: shared valuation summary interface to compare DCF vs RI outputs side by side.
