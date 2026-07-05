# R3-B2 Memory and Forget Contract Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add live automation-contract gates to external KG writes and irreversible data purge.

**Architecture:** Define contract templates at the mutation-owner modules, run them immediately before mutation, and keep the existing Action Kernel/admin guards intact. Denials are controlled 403 responses at HTTP seams and `PurgeError` at the function seam.

**Tech Stack:** Python 3.12, FastAPI routers, existing `automation_contracts.ContractTemplate`, pytest monkeypatch-based red/green tests.

## Global Constraints

- Feature branch only; no direct push to main.
- TDD red before production code.
- Do not change existing kernel/capability behavior for KG writes.
- Do not include raw KG property values, raw memory text, or user content in contract payloads.
- Default contracts must preserve current successful flows.

---

### Task 1: KG Write Contract Gate

**Files:**
- Modify: `agents/core/routers/memory_kg.py`
- Test: `tests/test_r3_b2_memory_forget_contracts.py`

**Interfaces:**
- Produces: `KG_WRITE_CONTRACT`, `_kg_contract_denial(payload: dict) -> str | None`
- Consumes: `automation_contracts.ContractTemplate`, `predicate`, `contract_denial`

- [x] Write failing tests that monkeypatch `memory_kg.KG_WRITE_CONTRACT` to deny `kg_upsert_entity`, `kg_add_relation`, `kg_add_fact`, and `kg_ingest`.
- [x] Run the focused tests and confirm the handlers currently mutate state despite the denied contract.
- [x] Add the KG write contract template and helper.
- [x] Call the helper before `_kg_kernel_denial()` and before each KG mutation.
- [x] Run the focused KG contract tests and confirm pass.

### Task 2: Data Purge Contract Gate

**Files:**
- Modify: `agents/core/data_purge.py`
- Modify: `agents/core/routers/backup.py`
- Test: `tests/test_r3_b2_memory_forget_contracts.py`

**Interfaces:**
- Produces: `DATA_PURGE_CONTRACT`, `purge_contract_denial(...) -> str | None`
- Consumes: `automation_contracts.ContractTemplate`, `predicate`, `contract_denial`

- [x] Write failing tests that monkeypatch `data_purge.DATA_PURGE_CONTRACT` to deny direct `purge_data(...)`.
- [x] Write failing route test proving `/api/admin/forget` returns 403 before `clear_live_memory`.
- [x] Run the focused tests and confirm purge currently proceeds despite the denied contract.
- [x] Add the data purge contract template and helper.
- [x] Enforce the helper at the start of `purge_data(...)`.
- [x] Enforce the helper in `forget_data(...)` before live memory clear.
- [x] Run the focused purge contract tests and confirm pass.

### Task 3: Trackers and Verification

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Consumes: `scripts/status_sync.py`

- [x] Update trackers with R3-B2 scope and test count.
- [x] Run focused R3-B2 tests.
- [x] Run adjacent KG/data-purge/contract sweeps.
- [x] Run touched-file ruff and py_compile.
- [x] Run `python scripts/status_sync.py --check`.
- [x] Run `git diff --check`.
- [x] Commit, push, and open draft PR #582.
- [ ] Wait for CI, mark ready, then merge when green.
