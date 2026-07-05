# LivingMemory Tier Persistence Design

**Goal:** Preserve LivingMemory tier metadata across process restarts so turn/reflection records remain available for temporal recall hints and nightly maintenance.

**Non-goals:** No vector payload migration, no raw transcript storage, no endpoint changes, and no user-forget behavior change.

**Design:**

- Make `TieredMemory` optionally `JsonStore`-backed through `path=...`.
- Keep `TieredMemory(path=None)` as pure in-memory mode.
- Persist the record map under `{"items": {...}}`.
- Save on `add`, `access`, `maintain`, and explicit `forget`.
- Preserve the no-auto-delete rule: maintenance only decays activation and re-tiers.
- Add `LivingMemory(tiers_path=...)` and wire production Orchestrator to `data_path("cognition", "living_tiers.json")`.

**Risk:** The tier store persists whatever callers pass to `LivingMemory.encode`. Production turn/reflection callers store metadata/digests, not raw transcript text; tests pin that path.

**Rollback:** Remove the `tiers_path` constructor wiring; in-memory algorithm behavior remains compatible.
