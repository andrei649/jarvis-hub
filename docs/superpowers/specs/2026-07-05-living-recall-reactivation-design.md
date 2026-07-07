# LivingMemory Recall Reactivation — Design

## Goal

When an already-retrieved recall hit matches a LivingMemory turn reference, make recall reinforce that trace instead of only using it as a ranking hint.

## Non-goals

- Do not generate new recall snippets or bypass the existing `rag_guard` fence.
- Do not auto-delete, compact, or demote any memory on read.
- Do not change unmatched recall hit ordering.
- Do not require a live LLM or embedding backend.

## Design

- `LivingMemory.access(mem_id)` delegates to `TieredMemory.access(mem_id)` so a matched recall can increment access count, raise activation, and re-tier the trace.
- `rerank_with_living_memory(...)` keeps its current post-fusion re-rank behavior, but for each matched LivingMemory record it best-effort records one access.
- The helper accepts an optional `decay_memory` and calls `decay_memory.access(mem_id)` for the same matched id, keeping the H14 ACT-R access ledger warm too.
- `Orchestrator._living_memory_rerank_hits()` passes its live `self.decay` store into the helper.

## Risks

- Access recording must never break recall or prompt construction.
- Duplicate hits for the same memory id should not inflate access count in one recall pass.
- The behavior must remain gated by existing cognition memory settings because the orchestrator only invokes the helper when `cognition.memory_enabled` is active.

## Tests

- Red/green unit test proves matched recall records reactivate LivingMemory and call the decay access seam.
- Red/green orchestrator test proves the live decay store is passed into the recall helper.
- Focused LivingMemory/decay/consolidation sweep guards existing ranking, persistence, and maintenance behavior.

