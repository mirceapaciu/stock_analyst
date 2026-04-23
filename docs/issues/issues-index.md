| ID | Type | Priority | Status | Title | Notes |
| --- | --- | ---      | ---    | ---   | --- |
| BUG-001 |	bug | high | resolved |	Handle blocked pages more gracefully |	4xx HTTP errors |
| BUG-002 |	bug | high | resolved |	Garbled page_text for Brotli-compressed responses |	requests doesn't decompress br; fool.com affected |
| FEAT-003 | feature | high | resolved | Market prices only for workflow stocks |  |
| FEAT-004 | feature | high | resolved | Jobs dashboard | UI dashboard that shows when the jobs last ran |
| FEAT-005 | feature | high | resolved | Job group lock | Recommendation discovery and tracked stock jobs should not run at the same time |
| BUG-006 |	bug | high | resolved |	The recommendations do not contain saved PDF|  |
| BUG-007 | bug | high | resolved | Search returns non-recommendation pages for stock-pick intents | Added discovery query constraints and low-intent filtering before analysis |
| FEAT-008 | feature | high | resolved | Collect recommendations that mention stock name without ticker | Added stock-name evidence gating and deterministic ticker inference fallback |
| FEAT-009 | feature | medium | new | Add DB-backed company-name pre-LLM validation | Use stock table names as weighted signal before LLM analysis |
| BUG-010 | bug | high | resolved | DCF valuation produces implausible fair value outlier | Added outlier detection guardrails for extreme growth, terminal value dominance, and upside potential |
| BUG-011 | bug | high | resolved | Missing minority-interest adjustment in DCF equity value | DCF now deducts minority interest in equity bridge and exposes diagnostics |
| BUG-012 | bug | high | resolved | Add financial-sector guardrail for generic DCF | Exclude or warn for financial-sector tickers where generic enterprise DCF is unreliable |
| BUG-014 | bug | high | resolved | FCF should reflect parent common share, not consolidated | Adjust starting FCF by parent ownership % before projection |
| FEAT-013 | feature | medium | resolved | Persist minority interest as stock-level property | Store minority-interest amount/source in DB for deterministic valuation reuse |
| FEAT-015 | feature | high | new | Add Residual Income valuation tab with DB caching | New RI model valuation flow, cached similarly to DCF with reusable repository patterns |
| BUG-016 | bug | high | resolved | Detect anti-bot challenge pages and fallback to alternate sources | Fail fast on challenge text, persist blocked URL rules, and continue with alternate eligible sources |
