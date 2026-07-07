# R3-B3 A2A and Escalation Contract Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for behavior changes and superpowers:verification-before-completion before marking this done. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add live automation-contract gates to inbound A2A tasks and autonomy escalation broadcasts.

**Architecture:** Define contract templates in the owning modules, evaluate them after existing auth/allowlist checks but before state mutation or channel send, and preserve current public result shapes.

**Tech Stack:** Python 3.12, pytest, existing `automation_contracts.ContractTemplate`, existing A2A registry and escalation router modules.

## Global Constraints

- Feature branch only; no direct push to main.
- TDD red before production code.
- Do not expose raw A2A task bodies, raw task values, or escalation message text to contract payloads.
- Default contracts must preserve current successful flows.
- Public routes keep their existing auth/status semantics.

---

### Task 1: A2A Inbound Contract Gate

**Files:**
- Modify: `agents/core/a2a.py`
- Test: `tests/test_r3_b3_a2a_escalation_contracts.py`

**Interfaces:**
- Produces: `A2A_INBOUND_CONTRACT`, `_a2a_contract_denial(peer_id: str, payload: dict) -> str | None`
- Consumes: `automation_contracts.ContractTemplate`, `predicate`, `contract_denial`

- [x] Write a failing test that monkeypatches `a2a.A2A_INBOUND_CONTRACT` to deny a valid signed inbound task.
- [x] Run the focused test and confirm the current code still appends to the inbox.
- [x] Add the A2A inbound contract template and helper.
- [x] Call the helper after JSON parse and before appending the pending record.
- [x] Run the focused A2A contract test and confirm pass.

### Task 2: Escalation Broadcast Contract Gate

**Files:**
- Modify: `agents/core/autonomy/escalation.py`
- Test: `tests/test_r3_b3_a2a_escalation_contracts.py`

**Interfaces:**
- Produces: `ESCALATION_CONTRACT`, `_escalation_contract_denial(message: str, targets: list[str], requested: list[str] | None) -> str | None`
- Consumes: `automation_contracts.ContractTemplate`, `predicate`, `contract_denial`

- [x] Write a failing async test that monkeypatches `escalation.ESCALATION_CONTRACT` to deny a valid broadcast.
- [x] Run the focused test and confirm the current code still calls the channel adapters.
- [x] Add the escalation contract template and helper.
- [x] Evaluate the helper once per resolved broadcast before the send loop.
- [x] Run the focused escalation contract test and confirm pass.

### Task 3: Trackers and Verification

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Consumes: `scripts/status_sync.py`

- [x] Update trackers with R3-B3 scope and test count.
- [x] Run focused R3-B3 tests.
- [x] Run adjacent A2A/escalation/contract sweeps.
- [x] Run touched-file ruff and py_compile.
- [x] Run `python scripts/status_sync.py --check`.
- [x] Run `git diff --check`.
- [x] Commit, push, and open draft PR #584.
