# R3-B5 Channel-Send Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate the generic channel-send transport before adapter I/O.

**Architecture:** `ChannelManager.send()` remains the single generic outbound channel boundary. It evaluates a shape-only `CHANNEL_SEND_CONTRACT` after adapter lookup and before adapter send.

**Tech Stack:** Python 3.12, pytest, existing `agents.core.automation_contracts` primitives.

## Global Constraints

- Preserve the current `False` result for missing/blocked sends.
- Do not include raw message text or keyword values in the contract payload.
- Do not change the existing channel allow surface: `telegram`, `web`, and `voice`.
- Denied contracts must block before the adapter `send()` method is called.

---

### Task 1: Red Tests

**Files:**
- Create: `tests/test_r3_b5_channel_send_contracts.py`

**Interfaces:**
- Consumes: `ChannelManager.send()` and module-level `CHANNEL_SEND_CONTRACT`.
- Produces: tests proving denial blocks the adapter and success evaluation is shape-only.

- [ ] **Step 1: Write denial test**

Patch `CHANNEL_SEND_CONTRACT` with a denying `ContractTemplate`, send through a fake telegram adapter, and assert the manager returns `False` while the adapter sees no calls.

- [ ] **Step 2: Write shape-only payload test**

Patch `CHANNEL_SEND_CONTRACT` with a capturing admissible contract, send a secret message with target kwargs, and assert the captured payload has only channel, message length, and kwarg keys/count.

- [ ] **Step 3: Verify red**

Run: `python -m pytest tests/test_r3_b5_channel_send_contracts.py -q`
Expected: FAIL because `ChannelManager.send()` ignores the patched contract.

### Task 2: Implement Gate

**Files:**
- Modify: `agents/core/channels/manager.py`

**Interfaces:**
- Produces: `CHANNEL_SEND_CONTRACT_KIND`, `CHANNEL_SEND_CONTRACT`, and a fail-closed `_contract_denial()` path.

- [ ] **Step 1: Add shape helpers and contract template**

Use `ContractTemplate`, `contract_denial`, and `predicate` to validate supported channel ids, non-negative message length, and sorted safe kwarg keys.

- [ ] **Step 2: Evaluate before adapter send**

If contract evaluation denies or raises, log and return `False` before calling the adapter.

- [ ] **Step 3: Verify focused green**

Run: `python -m pytest tests/test_r3_b5_channel_send_contracts.py tests/test_safe_comms_channel_inbox.py tests/test_channel_send_rate_limit.py -q`
Expected: PASS.

### Task 3: Trackers and PR

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Consumes: test count from `scripts/status_sync.py`.
- Produces: accurate active R3-B5 status.

- [ ] **Step 1: Run adjacent suites**

Run channel/inbox/cross-channel/escalation tests plus touched-file static checks.

- [ ] **Step 2: Update trackers**

Increment the synced test count and mark R3-B5 active/local green.

- [ ] **Step 3: Commit and open draft PR**

Commit the narrow branch and open a draft PR for CI.
