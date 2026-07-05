# LivingMemory Duplicate Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject exact duplicate completed-turn digests at the LivingMemory encoding seam.

**Architecture:** Keep the existing metadata-only turn record format. Add a bounded digest lookup to `LivingMemory`, then let the orchestrator map a repeated digest to zero surprise so the existing encoding gate handles the skip.

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, existing `LivingMemory`, golden-loop orchestrator harness, H14 decay store.

## Global Constraints

- No raw user or assistant transcript text is stored in LivingMemory.
- No endpoint, OpenAPI, HUD, or mobile parity change.
- Exact user-forget remains the only deletion path; this gate only skips new duplicate writes.
- Keep the PR small and include the #561 merged-status doc correction.

---

### Task 1: Red Tests

**Files:**
- Modify: `tests/test_living_memory_h21_3.py`
- Modify: `tests/test_o26_p2_memory_consolidation.py`

**Interfaces:**
- Consumes: `LivingMemory.encode()`, `LivingMemory.records()`, golden-loop `make_golden_orchestrator()`.
- Produces: Expected `LivingMemory.has_text_digest(text_sha256, prefix="turn:") -> bool` and orchestrator duplicate-skip behavior.

- [x] Add a pure test that a metadata record with `text_sha256="abc"` can be found and a missing digest is false.
- [x] Run the pure test and confirm it fails because `has_text_digest` does not exist yet.
- [x] Add a golden-loop test that two identical turns create only one LivingMemory record and one decay record.
- [x] Run the golden-loop test and confirm it fails because duplicate skipping does not exist yet.

### Task 2: Minimal Implementation

**Files:**
- Modify: `agents/core/cognition/memory.py`
- Modify: `agents/core/orchestrator.py`

**Interfaces:**
- Produces: `LivingMemory.has_text_digest(text_sha256: str, prefix: str = "turn:", limit: int = 1000) -> bool`.
- Produces: `_record_living_memory_after_turn()` sets `surprise=0.0` and `novelty=0.0` for duplicate digests, records `reason="duplicate_turn_digest"`, and skips decay add when not encoded.

- [x] Implement bounded digest lookup over existing tier records.
- [x] Use the lookup in the turn seam without changing the content shape.
- [x] Run the focused tests and confirm they pass.

### Task 3: Docs and Verification

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`
- Modify: `docs/COGNITION.md`

**Interfaces:**
- Produces: Honest status for #561 as merged and this duplicate-gate PR as current WIP.

- [x] Update status docs to mark #561 merged and describe the duplicate gate.
- [x] Run focused cognition/memory suites, py_compile, ruff, bandit, status sync, and diff check.
- [x] Commit, push, and open draft PR #562.
- [x] Monitor CI and merge #562 after full GitHub Actions passed.
