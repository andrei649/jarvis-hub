## Anchored Summary (updated)

**Branch:** `feat/context-cache`
**Test count:** 538 passed, 8 skipped (+29 from 509)

### Goal
Finish H4 Platform. H4.11 Context Caching + Hybrid Routing Metrics is the last H4 story before H5. Four subsystems: cost estimator, route tracking, context caching, dashboard UI.

### Constraints & Preferences
All tests must continue to pass. Vanilla React (createElement, no JSX). Local-first. Cloud opt-in per-agent.

### Progress
- **Tasks 1-4: DONE** (committed)
  - Task 1: Cost estimator module (8 tests)
  - Task 2: route_name on InteractionRecord + orchestrator wiring (4 tests)
  - Task 3: route_usage + cost_estimates in admin stats endpoint (2 tests)
  - Task 4: Gemini context cache module with persistence (12 tests, up from 6 after code review fixes)
- **Tasks 5-8: PENDING**
  - Task 5: Wire caching into GeminiBackend + orchestrator
  - Task 6: Track tokens + cache info in interaction records
  - Task 7: Dashboard UI — route distribution + cost cards
  - Task 8: Final verification + BACKLOG update

### Key Decisions
- Cost estimator uses MODELS dict with pricing per 1M tokens; local models cost zero
- route_name field on InteractionRecord defaults to empty string
- cache_key() is a @staticmethod — returns SHA-256[:16] of system_instruction + model
- Persistence uses direct INSERT OR REPLACE SQL (put_category is update-only, won't insert new rows)
- On extend failure, stale entry is evicted from _cache_map and create is retried
- ContextCache uses httpx.AsyncClient with 30s timeout

### Next Steps (Tasks 5-8)
1. Wire ContextCache into GeminiBackend._build_payload + orchestrator handle_input_stream
2. Add token estimates and cache metadata to interaction records
3. Dashboard UI: route bar chart + cost cards in ChartsPage
4. Final verification + BACKLOG.md update

### Critical Context
- Commits: 2edc0e9 (cost), f8190f7 (fix cost), 30f5866 (route tracking), 7160273 (admin stats), fd31be5 (fix admin), bc4fe1f (cache module)
- Code review for Task 4 caught: persistence broken (put_category skips unknown keys), unmocked test making real HTTP calls, no stale-entry fallback — all fixed in bc4fe1f
- Fixed issues in gemini_cache.py: direct SQL INSERT OR REPLACE instead of put_category, stale entry eviction + retry, mock patching for delete test, renamed count_active→count_entries
- All 538 tests pass with 8 skipped

### Relevant Files
- `agents/core/llm/cost_estimator.py` — MODELS pricing table + estimate_cost/estimate_monthly
- `tests/test_cost_estimator.py` — 8 tests
- `agents/core/learning/loop.py` — InteractionRecord with route_name field + get_route_counts()
- `tests/test_learning_live.py` — route tracking tests (4 new)
- `agents/web.py` — route_usage + cost_estimates in `/api/admin/stats`
- `tests/test_admin_charts.py` — 7 tests (2 new for stats fields)
- `agents/core/llm/gemini_cache.py` — ContextCache with REST API + SQLite persistence
- `tests/test_gemini_cache.py` — 12 tests (cache key, create, extend, fallback, delete, persistence)
- `agents/core/orchestrator.py` — route_name passed to _record_interactions (pending Task 5-6 wiring)
