# LivingMemory Tier Persistence Implementation Plan

**Branch:** `codex-living-tier-persistence`

**Scope:** H21.3 continuation after #556.

## Tasks

1. Add red tests for `TieredMemory(path=...)`, `LivingMemory(tiers_path=...)`, and production Orchestrator use of `JARVIS_HOME/cognition/living_tiers.json`.
2. Make `TieredMemory` optionally JsonStore-backed while preserving in-memory mode.
3. Wire production `LivingMemory` with both core and tier paths.
4. Update BACKLOG/STATUS/SPRINT/COGNITION docs from verified work.
5. Verify LivingMemory, reflection/core prompt, scheduler, route/OpenAPI guards, ruff, py_compile, status sync, and diff hygiene.

## Current Verification

- `tests/test_living_memory_h21_3.py tests/test_o26_p2_memory_consolidation.py`: 29 passed.
- Adjacent backend sweep: 61 passed (`test_living_memory_h21_3`, `test_o26_p2_memory_consolidation`, `test_living_memory_recall_eval`, `test_daily_reflection`, `test_o26_p1_one_turn_pipeline`, OpenAPI/route auth/typegen guards).
- `py_compile` on touched Python files: passed.
- `ruff check` on touched Python files: passed.
- `bandit` on touched backend files: passed.
- `scripts/status_sync.py --check`: `tests=3663`, `routes=367`.
- `git diff --check`: passed.
