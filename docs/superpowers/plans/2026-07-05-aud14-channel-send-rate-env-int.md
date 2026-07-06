# AUD-14 Channel Send-Rate Env-Int Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the global outbound channel send-rate cap through the shared `env_config.env_int()` parser.

**Architecture:** Add one private helper in `agents/core/channels/send_rate_limit.py` for the global cap and reuse it from both read paths. Keep per-channel override parsing as-is so this PR only closes the global numeric env seam.

**Tech Stack:** Python 3.12, pytest, existing `agents.core.env_config.env_int`.

## Global Constraints

- Default behavior stays unlimited when the env var is unset, zero, malformed, or negative.
- Per-channel overrides in `JARVIS_CHANNEL_SEND_RATES` continue to beat the global cap.
- No repo-wide env cleanup in this PR.
- TDD: red tests before implementation.

---

### Task 1: Red Tests

**Files:**
- Modify: `tests/test_channel_send_rate_limit.py`

**Interfaces:**
- Consumes: `agents.core.channels.send_rate_limit.limit_for()`, `configured_rates()`, `status_snapshot()`.
- Produces: regression coverage that malformed and negative `JARVIS_CHANNEL_SEND_RATE` resolve to unlimited, plus a static ratchet that the global cap uses `env_int`.

- [x] **Step 1: Add malformed global cap test**

Add a test that sets `JARVIS_CHANNEL_SEND_RATE=banana` and asserts:

```python
assert limit_for("whatsapp") == 0
assert srl.configured_rates()[0] == 0
assert srl.status_snapshot()["enabled"] is False
```

- [x] **Step 2: Add negative global cap test**

Add a test that sets `JARVIS_CHANNEL_SEND_RATE=-4` and asserts the same unlimited behavior.

- [x] **Step 3: Add env-int static ratchet**

Add a test that reads `agents/core/channels/send_rate_limit.py` and asserts:

```python
assert 'env_int("JARVIS_CHANNEL_SEND_RATE"' in src
assert 'int(os.environ.get("JARVIS_CHANNEL_SEND_RATE"' not in src
```

- [x] **Step 4: Verify red**

Run:

```bash
python -m pytest tests/test_channel_send_rate_limit.py::test_global_channel_send_rate_uses_env_int -q
```

Expected: FAIL because `send_rate_limit.py` still parses `JARVIS_CHANNEL_SEND_RATE` directly.

### Task 2: Implement Shared Env-Int Read

**Files:**
- Modify: `agents/core/channels/send_rate_limit.py`

**Interfaces:**
- Produces: `_global_cap() -> int`.

- [x] **Step 1: Import `env_int`**

Add:

```python
from agents.core.env_config import env_int
```

- [x] **Step 2: Add helper**

Add:

```python
def _global_cap() -> int:
    return env_int("JARVIS_CHANNEL_SEND_RATE", 0, minimum=0)
```

- [x] **Step 3: Reuse helper**

Replace both direct global cap parses in `limit_for()` and `configured_rates()` with `_global_cap()`.

- [x] **Step 4: Verify focused green**

Run:

```bash
python -m pytest tests/test_channel_send_rate_limit.py -q
```

Expected: PASS.

### Task 3: Trackers and PR

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`

**Interfaces:**
- Consumes: local verification results.
- Produces: active/local-green AUD-14 status for this narrow slice.

- [x] **Step 1: Run adjacent AUD-14 checks**

Run:

```bash
python -m pytest tests/test_o26_p2_env_config.py tests/test_channel_send_rate_limit.py -q
```

- [x] **Step 2: Run static checks**

Run:

```bash
python -m ruff check agents/core/channels/send_rate_limit.py tests/test_channel_send_rate_limit.py
python -m py_compile agents/core/channels/send_rate_limit.py
PYTHONIOENCODING=utf-8 python scripts/status_sync.py --check
git diff --check
```

- [x] **Step 3: Commit and open draft PR**

Commit:

```bash
git commit -m "fix: parse channel send rate env with env_int"
```
