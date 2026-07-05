# Cognition Forget Purge Design

## Goal

Keep the explicit user-forget contract complete after LivingMemory gained durable core and tier stores.

## Problem

#556 and #557 moved cognition memory from process-local state into:

- `memory_logs/cognition/core_memory.json`
- `memory_logs/cognition/living_tiers.json`

The existing AUD-2 purge path knew how to erase legacy memory stores (`bitemporal_kg.json`, `entities.json`, `decay.json`, `embedding_cache`, and session transcripts), but it did not yet know about these two cognition files. The live clear path also cleared `orch.memory`, `orch.entities`, and `orch.decay`, but not the registered `LivingMemory` module. That means a running process could keep old facts in memory and re-save them after the files were deleted.

## Non-Goals

- Do not change retention semantics. Automatic maintenance still demotes and never deletes.
- Do not broaden purge to a blanket `cognition/` directory delete.
- Do not add new admin routes or change `/api/admin/forget` shape.
- Do not export cognition stores in the portable export path.

## Design

Add exact-path cognition files to the existing `PURGE_MEMORY_FILES` allow-list in `agents/core/data_purge.py`.

Add explicit clear seams to:

- `CoreMemory.clear()`
- `TieredMemory.clear()`
- `LivingMemory.clear()`

Then extend `clear_live_memory(orch)` to defensively look up `orch.cognition.module("memory")` and call `clear()` when present.

The clear methods persist empty state when the stores are file-backed. This prevents the running process from resurrecting forgotten facts later if another write occurs after the at-rest purge.

## Tests

- Extend `tests/test_data_purge_memory.py` so `purge_data(memory=True)` removes both cognition files.
- Extend live clear coverage so `clear_live_memory()` empties a real `LivingMemory` instance.
- Re-run adjacent LivingMemory/consolidation tests to prove the new `clear()` methods do not disturb normal add/access/maintain/persistence behavior.

## Risk

Low. The purge file list is exact-path, not globbed; non-memory files still survive. The live clear call is defensive and best-effort like the existing memory/entity/decay clears.

## Rollback

Revert the `PURGE_MEMORY_FILES` additions, `clear_live_memory()` cognition branch, and the three `clear()` methods. The tests added in this slice will fail again, correctly showing the privacy gap.
