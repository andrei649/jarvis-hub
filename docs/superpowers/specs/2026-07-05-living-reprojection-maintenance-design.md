# LivingMemory Re-projection Maintenance Design

## Goal

Make the documented LivingMemory re-projection story real enough to run in nightly maintenance without requiring a production embedder yet.

## Problem

`agents/core/cognition/memory.py` already had the pure `reproject(records, current_version, embedder)` helper, but there was no module-level method that:

- selects stale tier records,
- re-embeds them through an explicitly supplied embedder,
- persists the updated `vector` and `embed_version` fields back to `memory_logs/cognition/living_tiers.json`,
- reports the work from the nightly `SchedulerService.run_memory_maintenance()` path.

That left `docs/COGNITION.md` overstating re-projection: the algorithm existed, but the nightly maintenance seam did not.

## Non-Goals

- Do not choose or instantiate a live embedder in this PR.
- Do not add a new route or settings key.
- Do not auto-delete, compact, or migrate tier records.
- Do not alter NREM/REM maintenance semantics.

## Design

Add `TieredMemory.update_records(records)` as a narrow persistence primitive keyed by record `id`.

Add `LivingMemory.reproject_stale(embedder=..., current_version=None, limit=100)`:

- target version defaults to `self.embed_version`,
- no embedder returns a structured default-off report,
- stale records are copied out, passed through the existing `reproject()` helper, and only successfully upgraded records are written back,
- the return payload includes `available`, `checked`, `reprojected`, `updated`, and `version`.

Extend `SchedulerService.run_memory_maintenance()`:

- after NREM/REM consolidation, call `living.reproject_stale()` when available,
- include a `reprojection` section in the result,
- contain hook failures with `reason="reprojection_failed"` and keep decay inspection independent.

## Tests

- `tests/test_living_memory_h21_3.py` proves stale records are re-embedded and persisted while current records remain untouched.
- `tests/test_o26_p2_memory_consolidation.py` proves nightly maintenance calls and reports the re-projection hook.
- Existing maintenance tests prove disabled cognition remains a no-op.

## Risk

Low. Without an embedder, production returns `embedder_unavailable` and does not mutate tier records. The scheduler hook is best-effort and isolated from consolidation/decay.

## Rollback

Revert `LivingMemory.reproject_stale`, `TieredMemory.update_records`, the scheduler `reprojection` section, and the two regression tests. The pure `reproject()` helper can remain if desired.
