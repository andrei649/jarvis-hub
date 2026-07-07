# LivingMemory Core Prompt Design

**Goal:** Make the bounded `LivingMemory.core` facts actually usable by agents by injecting them into the shared prompt ingredient path when cognition memory is enabled.

**Non-goals:** No new storage backend, no raw transcript replay, no endpoint changes, and no dependency on `memory.recall_enabled`.

**Design:**

- Add `Orchestrator._living_core_memory_block()`.
- Gate it on `cognition.memory_enabled`, matching the LivingMemory encode/recall seams.
- Read `living.core.list()` and render a compact `[core memory]` block.
- Normalize whitespace and cap each fact at 300 characters before prompt insertion.
- Label the block as background facts, not instructions.
- Insert the block in `_build_agent_turn_text()`, the shared prompt path used by both plain and streaming turns.

**Risk:** Core memory is trusted internal state, but it can still contain derived text from user conversations. The prompt label and line normalization reduce instruction confusion; the cognition memory flag remains the owner-facing gate.

**Rollback:** Remove `_living_core_memory_block()` and the two-line call in `_build_agent_turn_text()`.
