# LivingMemory Core Persistence Implementation Plan

**Branch:** `codex-living-core-persistence`

**Scope:** H21.3 continuation after #555.

## Tasks

1. Add red tests for `CoreMemory(path=...)`, `LivingMemory(core_path=...)`, and production Orchestrator use of `JARVIS_HOME/cognition/core_memory.json`.
2. Make `CoreMemory` a JsonStore-backed bounded ring when a path is supplied.
3. Add `core_path` to `LivingMemory` and wire the Orchestrator registration.
4. Update BACKLOG/STATUS/SPRINT/COGNITION docs from verified work.
5. Verify LivingMemory, reflection/core prompt, scheduler, route/OpenAPI guards, ruff, py_compile, status sync, and diff hygiene.

## Current Verification

- `tests/test_living_memory_h21_3.py tests/test_o26_p2_memory_consolidation.py`: 26 passed.
- Adjacent backend sweep: 58 passed (`test_living_memory_h21_3`, `test_o26_p2_memory_consolidation`, `test_living_memory_recall_eval`, `test_daily_reflection`, `test_o26_p1_one_turn_pipeline`, OpenAPI/route auth/typegen guards).
- `py_compile` on touched Python files: passed.
- `ruff check` on touched Python files: passed.
- `bandit` on touched backend files: passed.
- `scripts/status_sync.py --check`: `tests=3660`, `routes=367`.
- `git diff --check`: passed.
