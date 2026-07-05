# R2 Taint Propagation Teeth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve inbound taint through autonomy queue intake, edit decisions, embedded memory metadata, and recall provenance.

**Architecture:** Add small helper methods in `AutonomyWorker` to derive effective origin, mark payloads, and force ASK for tainted/untrusted tasks. Extend `MemoryManager.add_turn()` with optional channel metadata for user-turn embeddings, and teach `rag_guard.provenance_from_hit()` to prefer taint provenance.

**Tech Stack:** Python 3.12, pytest, existing `action_origin`, `security.taint`, `AutonomyWorker`, `MemoryManager`, and `rag_guard`.

## Global Constraints

- Feature branch only; do not push direct to main.
- TDD red before production code.
- No schema migration; `Task.origin` remains a string.
- Kernel default stays off.
- Existing callers of `MemoryManager.add_turn()` stay compatible.

---

### Task 1: Queue Intake Taint Teeth

**Files:**
- Modify: `agents/core/autonomy/worker.py`
- Modify: `agents/core/autonomy/queue.py`
- Test: `tests/test_r2_taint_propagation.py`

**Interfaces:**
- Produces: `AutonomyWorker._effective_origin(origin) -> str`, `_mark_payload_for_origin(payload, origin) -> tuple[dict, bool]`, `_force_ask_for_taint(level, tainted) -> str`
- Consumes: `agents.core.action_origin.current_action_origin`, `agents.core.security.taint`

- [x] Write failing tests for inbound `govern_enqueue()` and `submit()` forcing ASK and persisting taint.
- [x] Run the two tests and confirm they fail because tasks auto-approve or payloads are untainted.
- [x] Add the worker helpers and call them from both intake paths.
- [x] Update the `Task.origin` comment to include `inbound`.
- [x] Run the focused queue tests and confirm pass.

### Task 2: Edit Decision Re-Marking

**Files:**
- Modify: `agents/core/autonomy/worker.py`
- Test: `tests/test_r2_taint_propagation.py`

**Interfaces:**
- Consumes: Task 1 worker helpers.
- Produces: edited inbound task payloads remain tainted before policy re-evaluation.

- [x] Write a failing edit-decision test where a blocked inbound task is edited into a policy-ACT payload.
- [x] Run the test and confirm it incorrectly approves before the fix.
- [x] Re-mark edited payloads with the task origin before `policy.decide()`.
- [x] Force ASK when the edited payload is tainted.
- [x] Run the focused edit test and confirm pass.

### Task 3: Memory Taint Metadata + Recall Provenance

**Files:**
- Modify: `agents/core/memory/manager.py`
- Modify: `agents/core/orchestrator.py`
- Modify: `agents/core/security/rag_guard.py`
- Test: `tests/test_r2_taint_propagation.py`

**Interfaces:**
- Produces: `MemoryManager.add_turn(..., channel: str | None = None)` remains backward-compatible.
- Consumes: `action_origin.origin_for_channel`, `security.taint.mark`.

- [x] Write failing tests for inbound user-turn embedding metadata and tainted recall provenance.
- [x] Run the tests and confirm metadata/provenance are missing.
- [x] Add optional `channel` to `MemoryManager.add_turn()` and mark inbound user-turn embedding metadata.
- [x] Pass `channel=channel` from orchestrator user-turn writes.
- [x] Prefer `metadata.taint_source` in `rag_guard.provenance_from_hit()` when metadata is tainted.
- [x] Run the focused memory/provenance tests and confirm pass.

### Task 4: Trackers and Verification

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Produces: backlog/status evidence for R2.
- Consumes: `scripts/status_sync.py`.

- [x] Update trackers with R2 scope and verification.
- [x] Run `python -m pytest tests/test_r2_taint_propagation.py tests/test_taint_flag.py tests/test_task3_taint_ingestion.py tests/test_cdx7_action_origin_taint.py tests/test_m12_origin_threading.py tests/test_h17_origin_by_construction.py -q`.
- [x] Run touched-file ruff and py_compile.
- [x] Run `python scripts/status_sync.py --check`.
- [x] Run `git diff --check`.
- [x] Commit, push, and open draft PR #580.
- [ ] Wait for CI, mark ready, then merge when green.
