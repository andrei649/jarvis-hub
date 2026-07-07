# Cognition Forget Purge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure explicit user-forget clears durable LivingMemory core and tier stores live and at rest.

**Architecture:** Reuse the existing AUD-2 `data_purge` seam. Add exact-path purge coverage for the two cognition JSON stores and add clear methods to the live cognition memory module so a running process cannot re-save forgotten state.

**Tech Stack:** Python 3.12, pytest, existing `JsonStore` persistence base.

## Global Constraints

- Local-first; no cloud dependency.
- Do not add a new route or change `/api/admin/forget` request/response shape.
- Purge only exact known cognition memory files; do not delete the whole `cognition/` directory.
- Preserve the "maintenance never deletes; only user-forget deletes" invariant.

---

### Task 1: Red Test For Cognition Store Purge

**Files:**
- Modify: `tests/test_data_purge_memory.py`

**Interfaces:**
- Consumes: `agents.core.data_purge.purge_data(source_root, backup_first, memory, session_ids)`
- Produces: regression coverage for `cognition/core_memory.json` and `cognition/living_tiers.json`

- [x] **Step 1: Seed cognition files in the memory purge fixture**

```python
(root / "cognition" / "core_memory.json").write_text(
    '{"facts": ["Alice lives in Bucharest"]}',
    encoding="utf-8",
)
(root / "cognition" / "living_tiers.json").write_text(
    '{"items": {"turn:1": {"content": "Alice secret", "activation": 1.0}}}',
    encoding="utf-8",
)
```

- [x] **Step 2: Assert the files are deleted and reported**

Run: `.venv\Scripts\python.exe -m pytest tests\test_data_purge_memory.py -q`

Expected before implementation: fail because `core_memory.json` still exists.

### Task 2: Red Test For Live Cognition Clear

**Files:**
- Modify: `tests/test_data_purge_memory.py`

**Interfaces:**
- Consumes: `agents.core.data_purge.clear_live_memory(orch)`
- Produces: regression coverage for clearing a live `LivingMemory`

- [x] **Step 1: Add a fake cognition facade returning real `LivingMemory`**

```python
class _FakeCognition:
    def __init__(self, living_memory):
        self._living_memory = living_memory

    def module(self, name):
        return self._living_memory if name == "memory" else None
```

- [x] **Step 2: Assert core facts and tier records are emptied**

Run: `.venv\Scripts\python.exe -m pytest tests\test_data_purge_memory.py -q`

Expected before implementation: fail because `living.core.list()` still contains the fact.

### Task 3: Implement Minimal Purge Coverage

**Files:**
- Modify: `agents/core/data_purge.py`
- Modify: `agents/core/cognition/memory.py`

**Interfaces:**
- Produces: `CoreMemory.clear() -> int`
- Produces: `TieredMemory.clear() -> int`
- Produces: `LivingMemory.clear() -> dict`

- [x] **Step 1: Add exact-path cognition files to `PURGE_MEMORY_FILES`**

```python
PURGE_MEMORY_FILES = (
    "bitemporal_kg.json",
    "entities.json",
    "decay.json",
    "cognition/core_memory.json",
    "cognition/living_tiers.json",
)
```

- [x] **Step 2: Add clear methods to core/tier/living memory**

```python
def clear(self) -> int:
    with self._lock:
        count = len(self._items)
        self._items = {}
        self._save()
        return count
```

- [x] **Step 3: Call the live cognition module from `clear_live_memory()`**

```python
cognition = getattr(orch, "cognition", None)
living = cognition.module("memory") if cognition is not None else None
if living is not None and hasattr(living, "clear"):
    living.clear()
```

- [x] **Step 4: Verify focused and adjacent tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_data_purge_memory.py -q
.venv\Scripts\python.exe -m pytest tests\test_living_memory_h21_3.py tests\test_o26_p2_memory_consolidation.py -q
```

Expected after implementation: both commands pass.

### Task 4: Documentation And Handoff

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/SPRINT.md`
- Modify: `docs/COGNITION.md`
- Create: `docs/superpowers/specs/2026-07-05-cognition-forget-purge-design.md`
- Create: `docs/superpowers/plans/2026-07-05-cognition-forget-purge.md`

**Interfaces:**
- Produces: docs that mark #557 merged and the forget-purge follow-up verified locally.

- [x] **Step 1: Update status docs with verified scope**

Record that #557 is merged and this slice covers explicit user-forget for cognition stores.

- [x] **Step 2: Add diagnostic note to `docs/COGNITION.md`**

Record that only explicit user-forget truly erases cognition memory and that new durable stores must be added to AUD-2 purge coverage.
