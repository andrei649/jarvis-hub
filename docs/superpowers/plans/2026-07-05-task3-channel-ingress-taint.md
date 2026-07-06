# TASK-3 Channel Ingress Taint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make inbound channel messages carry explicit taint metadata at the gateway boundary without changing handler text semantics.

**Architecture:** `Gateway.route()` creates shape-only taint metadata for untrusted origins. `ChannelInboxStore` persists safe taint fields. `Orchestrator.channel_handler()` consumes private gateway metadata before outbound sends.

**Tech Stack:** Python 3.12, pytest, existing `security.taint` and `security.quarantine` primitives.

## Global Constraints

- Handler text remains a plain `str`.
- Trusted `web` and `voice` turns are not marked tainted.
- Private metadata must not be forwarded to outbound channel adapters.
- Inbox persistence stores only public taint fields and injection pattern ids, not raw hidden metadata values.

---

### Task 1: Red Tests

**Files:**
- Create: `tests/test_task3_channel_ingress_taint.py`

**Interfaces:**
- Consumes: `Gateway.route()`, `ChannelInboxStore.messages()`, and `taint.is_tainted()`.
- Produces: regression tests for handler metadata, inbox persistence, and trusted web behavior.

- [x] **Step 1: Write untrusted telegram test**

Route injection-looking telegram text through a gateway with an inbox store and assert the handler receives `_inbound_meta` with taint and injection flags while `text` remains a string.

- [x] **Step 2: Write inbox persistence assertion**

Assert the inbox message carries `tainted`, `taint_source`, and `injection_flags`.

- [x] **Step 3: Write trusted web regression**

Route the same text via `web` and assert `_inbound_meta` is absent or untainted.

- [x] **Step 4: Verify red**

Run: `python -m pytest tests/test_task3_channel_ingress_taint.py -q`
Expected: FAIL because gateway/inbox do not yet preserve taint metadata.

### Task 2: Implement Gateway and Inbox Taint

**Files:**
- Modify: `agents/core/channels/gateway.py`
- Modify: `agents/core/channel_inbox.py`
- Modify: `agents/core/orchestrator.py`

**Interfaces:**
- Produces: private `_inbound_meta` handler kwarg and public inbox taint fields.

- [x] **Step 1: Add gateway metadata helper**

For `origin_for_channel(channel) == "inbound"`, mark metadata with `taint.mark(..., source=f"inbound:{channel}")` and attach `quarantine.detect_injection(text)` as `injection_flags`.

- [x] **Step 2: Persist public inbox fields**

Extend `ChannelInboxStore._record()` and `_public()` to carry `tainted`, `taint_source`, and `injection_flags`.

- [x] **Step 3: Prevent outbound leakage**

Pop `_inbound_meta` in `Orchestrator.channel_handler()` before the reply send.

- [x] **Step 4: Verify focused green**

Run: `python -m pytest tests/test_task3_channel_ingress_taint.py tests/test_safe_comms_channel_inbox.py -q`
Expected: PASS.

### Task 3: Trackers and PR

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Consumes: test count from `scripts/status_sync.py`.
- Produces: active/local-green TASK-3 status.

- [x] **Step 1: Run adjacent channel/security tests**

Run pairing, cross-channel, memory taint, action-origin taint, and Safe Comms tests.

- [x] **Step 2: Run static checks**

Run ruff, py_compile, status sync, and diff check.

- [x] **Step 3: Commit and open draft PR**

Commit the narrow branch and open a draft PR for CI.
