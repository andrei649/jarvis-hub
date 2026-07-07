# LivingMemory Core Persistence Design

**Goal:** Make `LivingMemory.core` survive process restarts so DailyReflector lessons and manually pinned core facts remain available for the prompt injection path.

**Non-goals:** No tier-store persistence, no vector-store migration, no endpoint changes, and no change to the `cognition.memory_enabled` runtime gate.

**Design:**

- Keep `CoreMemory` as the small bounded ring API, but back it with `JsonStore` when a path is provided.
- Preserve `CoreMemory(path=None)` as in-memory mode for unit tests and pure algorithm use.
- Persist only the bounded fact list under `{"facts": [...]}`.
- Preserve de-duplication and cap behavior during load and write.
- Let `LivingMemory(core_path=...)` pass persistence through without changing encode/tier behavior.
- Register production LivingMemory with `data_path("cognition", "core_memory.json")`.

**Risk:** Core facts are persistent user memory. The production path is still inert unless the cognition subsystem is enabled, and prompt injection remains gated by `cognition.memory_enabled`.

**Rollback:** Remove `core_path` wiring; existing in-memory behavior remains compatible.
