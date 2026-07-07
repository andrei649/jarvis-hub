# LivingMemory Re-projection Embedder Wiring — Plan

1. Sync `main` and create `codex-living-reprojection-embedder`.
2. Add a failing scheduler test that expects `run_memory_maintenance()` to pass the existing `memory.embed` function into `reproject_stale()`.
3. Add a failing LivingMemory re-projection test for structured tier-record content.
4. Implement only the minimal scheduler wiring and deterministic content normalization.
5. Update `BACKLOG.md`, `STATUS.md`, `docs/SPRINT.md`, and `docs/COGNITION.md` to distinguish #559's hook from this embedder wiring follow-up.
6. Verify focused tests, compile/lint/security checks, status sync, diff hygiene, then open a draft PR.

