# LivingMemory Recall Reactivation — Plan

1. Sync `main` and create `codex-living-recall-reactivation`.
2. Add a failing test that a matched LivingMemory recall hit increments tier access, raises activation, updates the hit annotation, and records decay access once.
3. Add a failing orchestrator test that `_living_memory_rerank_hits()` passes `self.decay` to the recall helper.
4. Implement `LivingMemory.access()` as a small delegate to `TieredMemory.access()`.
5. Update `rerank_with_living_memory()` to best-effort access matched records and optional decay entries without affecting unmatched hits.
6. Update docs/status for #560 merged and this active branch.
7. Verify focused tests, compile/lint/security checks, status sync, diff hygiene, then open a draft PR.

