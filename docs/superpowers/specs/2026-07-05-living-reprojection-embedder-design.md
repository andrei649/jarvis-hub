# LivingMemory Re-projection Embedder Wiring — Design

## Goal

Make the H21.3 stale-record re-projection hook useful during nightly maintenance by passing the existing local `MemoryManager.embed` seam into `LivingMemory.reproject_stale()` when it is available.

## Non-goals

- Do not introduce a new embedding backend or model selector.
- Do not force re-projection when no embedder exists.
- Do not auto-delete, compact, or rewrite non-stale memory records.
- Do not add a live-model requirement to tests.

## Design

- `SchedulerService.run_memory_maintenance()` keeps the existing default-off fallback.
- If `orch.memory.embed` is callable, the scheduler passes it as `embedder=...` to `living.reproject_stale()`.
- `LivingMemory.reproject()` normalizes structured record content into deterministic JSON text before embedding, because live turn records store metadata dictionaries rather than raw transcript strings.

## Risks

- Embedding failures must remain best-effort and must not break maintenance.
- Structured content serialization must stay deterministic so re-projection is reproducible.
- The maintenance result may still report `embedder_unavailable` in tests or custom orchestrators without `memory.embed`; that is intentional.

## Tests

- Red/green scheduler test proves `run_memory_maintenance()` passes `orch.memory.embed` into re-projection.
- Red/green cognition test proves structured tier record content is serialized before it reaches an embedder.
- Focused LivingMemory + maintenance suites guard the fallback path.

