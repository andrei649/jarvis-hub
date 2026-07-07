# DailyReflector LivingMemory Implementation Plan

**Branch:** `codex-living-memory-daily-reflector`

**Scope:** H21.3 continuation after #553.

## Tasks

1. Add red tests for durable same-day skip after restart, manual force rerun, LivingMemory lesson encoding without raw transcript content, and default-off gating.
2. Add `ReflectionRunStore` and wire `DailyReflector.run(..., force=False)` through durable idempotency.
3. Add optional LivingMemory lesson handoff and production provider gating in `Orchestrator.load_agents()`.
4. Update `/api/reflection/run` to call `force=True`.
5. Update BACKLOG/STATUS/SPRINT/COGNITION docs from verified work.
6. Verify reflection, LivingMemory, scheduler, route/auth/OpenAPI guard, ruff, py_compile, status sync, and diff hygiene.

## Current Verification

- `tests/test_daily_reflection.py`: 14 passed.
- Adjacent backend sweep: 34 passed (`test_daily_reflection`, `test_o26_p2_memory_consolidation`, `test_living_memory_recall_eval`, OpenAPI/route auth/typegen guards).
- `py_compile` on touched Python files: passed.
- `ruff check` on touched Python files: passed.
- `bandit` on touched backend files: passed.
- `scripts/status_sync.py --check`: `tests=3655`, `routes=367`.
- `git diff --check`: passed.
