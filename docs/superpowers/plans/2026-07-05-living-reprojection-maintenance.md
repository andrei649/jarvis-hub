# LivingMemory Re-projection Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire LivingMemory stale-record re-projection into nightly maintenance as a default-off, explicitly supplied embedder hook.

**Architecture:** Keep `reproject()` as the algorithm leaf. Add a persistence method on `TieredMemory`, a module method on `LivingMemory`, and a best-effort scheduler call that reports but does not require a live embedder.

**Tech Stack:** Python 3.12, pytest, existing `JsonStore` tier persistence.

## Global Constraints

- No live embedder selection in this PR.
- No new settings key or HTTP route.
- No automatic deletion; maintenance may only update stale records when an embedder is supplied.
- Scheduler failures in this hook must not break consolidation or decay inspection.

---

### Task 1: Red Test Persistent Stale Re-projection

**Files:**
- Modify: `tests/test_living_memory_h21_3.py`

**Interfaces:**
- Consumes: `LivingMemory(embed_version=..., tiers_path=...)`
- Produces: `LivingMemory.reproject_stale(embedder=...) -> dict`

- [x] **Step 1: Seed one stale and one current tier record**

```python
lm = LivingMemory(embed_version=2, tiers_path=path)
lm.tiers.add("old", "abc", activation=1.0, embed_version=1)
lm.tiers.add("fresh", "abcd", activation=1.0, embed_version=2)
```

- [x] **Step 2: Assert re-projection persists only the stale record**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_living_memory_h21_3.py::test_living_memory_reproject_stale_persists_updates -q
```

Expected before implementation: `AttributeError: 'LivingMemory' object has no attribute 'reproject_stale'`.

### Task 2: Red Test Scheduler Hook

**Files:**
- Modify: `tests/test_o26_p2_memory_consolidation.py`

**Interfaces:**
- Consumes: `SchedulerService.run_memory_maintenance()`
- Produces: `result["reprojection"]`

- [x] **Step 1: Add a fake LivingMemory with `reproject_stale()`**

```python
async def reproject_stale(self):
    self.reprojected = True
    return {"available": True, "checked": 1, "reprojected": 1, "version": 2}
```

- [x] **Step 2: Assert nightly maintenance calls and reports it**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_o26_p2_memory_consolidation.py::test_memory_maintenance_runs_reprojection_hook -q
```

Expected before implementation: fake hook is not called and `result["reprojection"]` is absent.

### Task 3: Implement Minimal Hook

**Files:**
- Modify: `agents/core/cognition/memory.py`
- Modify: `agents/core/scheduler_service.py`

**Interfaces:**
- Produces: `TieredMemory.update_records(records) -> int`
- Produces: `LivingMemory.reproject_stale(embedder=None, current_version=None, limit=100) -> dict`

- [x] **Step 1: Persist updated tier records by id**

```python
def update_records(self, records):
    with self._lock:
        ...
        self._save()
```

- [x] **Step 2: Reuse the existing `reproject()` helper on stale copies**

```python
stale = [dict(r) for r in records if needs_reprojection(r, target_version)]
result = await reproject(stale, current_version=target_version, embedder=embedder)
updated = self.tiers.update_records(changed)
```

- [x] **Step 3: Add scheduler reporting**

```python
reprojection = await living.reproject_stale()
result["reprojection"] = reprojection
```

### Task 4: Docs And Verification

**Files:**
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `docs/COGNITION.md`
- Modify: `docs/SPRINT.md`
- Create: `docs/superpowers/specs/2026-07-05-living-reprojection-maintenance-design.md`
- Create: `docs/superpowers/plans/2026-07-05-living-reprojection-maintenance.md`

**Interfaces:**
- Produces: handoff docs that mark #558 merged and this branch in progress.

- [x] **Step 1: Run focused verification**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_living_memory_h21_3.py tests\test_o26_p2_memory_consolidation.py -q
.venv\Scripts\python.exe -m py_compile agents\core\cognition\memory.py agents\core\scheduler_service.py tests\test_living_memory_h21_3.py tests\test_o26_p2_memory_consolidation.py
.venv\Scripts\python.exe -m ruff check agents\core\cognition\memory.py agents\core\scheduler_service.py tests\test_living_memory_h21_3.py tests\test_o26_p2_memory_consolidation.py
```

Expected after implementation: all commands pass.
