# LivingMemory Recall Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire LivingMemory into live recall ordering and add a deterministic real-recall eval mode.

**Architecture:** Add a small post-fusion recall helper that uses LivingMemory metadata only for temporal re-ranking, then call it from `Orchestrator._recall_block()` before RAG fencing. Add an async eval mode that ingests corpus facts into a real `MemoryManager`, recalls them, and scores answers built from retrieved facts.

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, FastAPI router query param, existing `MemoryManager`, `FusedHit`, `LivingMemory`, `tcm_rerank`, and `rag_guard`.

## Global Constraints

- LivingMemory must not store or render raw user/assistant transcript text.
- Retrieved text must still pass through `agents.core.security.rag_guard`.
- RRF fusion must remain unchanged; this is post-fusion ordering only.
- `/api/memory/eval/run` must keep keyword mode as the default.

---

### Task 1: LivingMemory Recall Re-Rank Helper

**Files:**
- Create: `agents/core/memory/living_recall.py`
- Test: `tests/test_living_memory_recall_eval.py`

**Interfaces:**
- Produces: `rerank_with_living_memory(hits, living_memory, *, context_ts=None, half_life=86400.0, weight=0.3) -> list`
- Consumes: `living_memory.records(prefix="", limit=...)`, `agents.core.cognition.memory.tcm_rerank`, and `agents.core.memory.fusion.FusedHit`

- [ ] Write failing tests for matched temporal re-ordering and unmatched-order preservation.
- [ ] Run the focused tests and confirm they fail because the helper does not exist.
- [ ] Implement the helper with non-private payload annotation only.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Orchestrator Prompt Recall Integration

**Files:**
- Modify: `agents/core/orchestrator.py`
- Test: `tests/test_living_memory_recall_eval.py`

**Interfaces:**
- Consumes: `rerank_with_living_memory(...)`
- Preserves: `_recall_block(text: str) -> str`

- [ ] Write a failing `_recall_block()` test with fake fused hits and a fake cognition module.
- [ ] Run the focused test and confirm the old order is rendered.
- [ ] Call the helper after `self.memory.recall()` and before `wrap_memory(...)`, gated by `cognition.memory_enabled`.
- [ ] Run the focused test and adjacent recall tests.

### Task 3: Real Recall Eval Mode

**Files:**
- Modify: `agents/core/memory/eval.py`
- Modify: `agents/core/routers/memory_kg.py`
- Test: `tests/test_living_memory_recall_eval.py`
- Test: `tests/test_h14_2_memory_eval.py`

**Interfaces:**
- Produces: `async run_recall_eval(corpus=None, top_k=5) -> dict`
- Produces: `POST /api/memory/eval/run?mode=recall`
- Preserves: `POST /api/memory/eval/run` keyword default

- [ ] Write failing tests for `run_recall_eval()` and endpoint `mode=recall`.
- [ ] Run focused eval tests and confirm failures.
- [ ] Implement async real-path ingestion/recall with deterministic hash embeddings.
- [ ] Add router mode dispatch with invalid-mode 400.
- [ ] Run focused eval tests.

### Task 4: Docs, Snapshots, and Verification

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`
- Update generated OpenAPI/TS snapshots if the endpoint schema gate requires it.

- [ ] Update docs with verified work in progress/completed status.
- [ ] Run targeted backend tests.
- [ ] Run OpenAPI/typegen gates if the query parameter changes generated schema.
- [ ] Run ruff/py_compile/diff-check/status-sync.
- [ ] Commit, push, open draft PR, and monitor CI.
