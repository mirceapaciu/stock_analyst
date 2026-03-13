# Plan: Batch Scheduler for Tracked-Stock and Discovery Workflows

## Overview

Scale the recommendation pipeline from ~20 tracked tickers to **320+** (and growing)
by splitting the workload into two independently-scheduled workflows:

| Workflow | Purpose | Schedule |
|----------|---------|----------|
| **Discovery** | Find new undervalued stocks via generic queries | Daily |
| **Tracked-stock** | Refresh ratings for existing stocks (avg rating ≥ threshold) in batches | Every 8 hours (3×/day) |

---

## 1. Problem Analysis

### 1.1 Query volume at scale — free CSE tier constraint

Google CSE free tier allows **100 queries/day**. This is the hard budget.

- **Discovery workflow**: 3 templates × 6 sites = **18 CSE calls/day**.
- **Remaining daily budget for tracked-stock batches**: 100 − 18 = **82 calls/day**.

Sites can be **grouped into a single CSE query** using `OR` in the query string
(e.g. `"AAPL stock analysis (site:reuters.com OR site:fool.com OR site:zacks.com)"`).
This counts as **1 CSE call** and returns the top 10 results across all listed
sites. Trade-off: some sites may be absent from results if others rank higher,
but every ticker still gets a dedicated query.

| Templates | Site groups | Calls/ticker | Tickers/day (82 budget) | Sweep for 320 tickers |
|----------:|------------:|-------------:|------------------------:|----------------------:|
| 1         | 1 (6 sites OR'd)  | 1     | 82                      | ~4 days               |
| 1         | 2 (3 sites each)   | 2     | 41                      | ~8 days               |
| 2         | 1 (6 sites OR'd)  | 2     | 41                      | ~8 days               |
| 2         | 2 (3 sites each)   | 4     | 20                      | ~16 days              |

**Chosen approach**: **1 template × 1 site-group (all 6 sites OR'd) = 1 CSE call/ticker**
→ 82 tickers/day → full sweep of 320 tickers in **~4 days**.

The current approach of running all tracked queries inside a single `search_node`
invocation **does not scale** beyond ~20 tickers because:
- A single workflow run becomes very long (API calls + scraping + LLM extraction).
- A failure partway through wastes all work done so far.
- The `MAX_TRACKED_STOCK_SEARCHES = 20` cap silently drops most tickers.
- The free quota would be exhausted in the first batch.

### 1.2 Free-tier budget split

```
Google CSE free tier: 100 calls/day
 ├─ Discovery workflow (daily):    18 calls  (3 templates × 6 sites)
 └─ Tracked-stock batches:         82 calls  remaining
     └─ At 1 call/ticker (site-grouped) → 82 tickers/day
        → full 320-ticker sweep in ~4 days
```

Site-grouping (combining multiple `site:` filters with `OR` in one query) is
the key optimization. Instead of issuing separate CSE calls per site, each
ticker gets a single query that searches all 6 reputable sites at once:

```
{ticker} stock analysis (site:reuters.com OR site:fool.com OR site:zacks.com
  OR site:morningstar.com OR site:seekingalpha.com OR site:finance.yahoo.com)
```

This reduces calls/ticker from 3–6 down to **1**, making a ~4-day sweep cycle
feasible on the free tier.

### 1.3 Two concerns, two cadences

- **Discovery** (new undervalued stocks): 18 CSE calls, fast, run once daily.
- **Tracked-stock refresh**: thousands of CSE calls, should be spread over
  hours/days in small batches.

Mixing them in one workflow forces a lowest-common-denominator schedule.

### 1.4 Upstream pipeline bias (unchanged from previous analysis)

The discovery pipeline is biased toward positive/undervalued content at three
layers (search queries, analysis fallback keywords, LLM extraction prompt).
Tracked-stock searches use sentiment-neutral queries and a broader extraction
prompt. This separation already exists in the codebase and the two workflow
modes naturally leverage it.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Scheduler Layer                       │
│  Option A: APScheduler service (in-process / container)  │
│  Option B: External (cron / ECS Scheduled Task / Airflow)│
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌────────────────────┐    ┌───────────────────────────┐ │
│  │ Discovery Workflow │    │ Tracked-Stock Batch       │ │
│  │                    │    │                           │ │
│  │ Schedule: daily    │    │ Schedule: every N hours   │ │
│  │ Queries: SEARCH_   │    │ Queries: TRACKED_STOCK_   │ │
│  │   QUERIES × sites  │    │   SEARCH_QUERIES × sites  │ │
│  │ Tickers: none      │    │ Tickers: next batch from  │ │
│  │   (generic search) │    │   sweep cursor            │ │
│  │ Prompt: discovery  │    │ Prompt: tracked (neutral) │ │
│  │ Rating filter: ≥ 4 │    │ Rating filter: accept all │ │
│  │   for new stocks   │    │   (already in DB)         │ │
│  └─────────┬──────────┘    └────────────┬──────────────┘ │
│            │                            │                │
│            └──────────┬─────────────────┘                │
│                       ▼                                  │
│           ┌───────────────────────────┐                  │
│           │   Same 8-node pipeline    │                  │
│           │   (search → filter →      │                  │
│           │    analyze → scrape →     │                  │
│           │    validate → output)     │                  │
│           └───────────────────────────┘                  │
│                       │                                  │
│                       ▼                                  │
│           ┌───────────────────────────┐                  │
│           │  recommendations.db       │                  │
│           │  (input_stock_rec +       │                  │
│           │   recommended_stock)      │                  │
│           └───────────────────────────┘                  │
└──────────────────────────────────────────────────────────┘
```

Both workflows reuse the **same 8-node LangGraph pipeline** (`create_workflow()`).
The difference is controlled entirely by the initial `WorkflowState`:
- `workflow_mode`: `"discovery"` or `"tracked"`
- `batch_tickers`: list of tickers for this batch (tracked mode only)

