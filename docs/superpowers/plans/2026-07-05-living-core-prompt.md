# LivingMemory Core Prompt Implementation Plan

**Branch:** `codex-living-core-prompt-injection`

**Scope:** H21.3 continuation after #554.

## Tasks

1. Add red tests proving `living.core` facts are absent today, then appear in prompt text only when cognition memory is enabled.
2. Add the gated core-memory renderer in `Orchestrator`.
3. Insert it into `_build_agent_turn_text()`, the shared plain/stream prompt path.
4. Update BACKLOG/STATUS/SPRINT/COGNITION docs from verified work.
5. Verify LivingMemory, reflection, one-turn prompt parity, route/OpenAPI guards, ruff, py_compile, status sync, and diff hygiene.

## Current Verification

- `tests/test_living_memory_recall_eval.py`: 8 passed.
- Adjacent backend sweep: 39 passed (`test_living_memory_recall_eval`, `test_daily_reflection`, `test_o26_p1_one_turn_pipeline`, `test_o26_p2_memory_consolidation`, OpenAPI/route auth/typegen guards).
- `py_compile` on touched Python files: passed.
- `ruff check` on touched Python files: passed.
- `bandit` on touched backend file: passed.
- `scripts/status_sync.py --check`: `tests=3657`, `routes=367`.
- `git diff --check`: passed.
