# H277 automatic vision selection verification plan

Generated 2026-10-02. Base and head: `aa3e20676bfa4ecc99855c5953896a74b621e8cf`.
Pinned Hermes: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.

## Goal and boundary

Verify the newly added automatic image-route selection against independently
mutated behavior. This increment changes only `docs/hermes/` evidence and the
mutation runner; it does not change provider runtime, credentials, the selected
chat route, or Hermes equivalence counts. Mutations run on an exact-commit archive
in `/tmp`, not in the live checkout. Rollback is removal of this plan, runner,
and report; no product state or database migration is involved.

## Checks

1. Freeze the full source commit and pass the existing 16 resolver and HTTP
   consumer tests as a baseline.
2. Probe the explicit route, selected main route, model override, provider
   scope, malformed policy, candidate order and priority recheck. A mutant is
   killed only by an assertion failure; collection and infrastructure errors
   are invalid.
3. Restore the archive after each case, rerun the baseline, verify every
   tracked source hash, then record survivors and limits without inflating the
   175/697 Hermes equivalence count.

If a mutation survives because the tests exercise only a preselected model,
add a behavioral HTTP regression for the missing discovery path before
freezing the source again. The regression must prove status prepares a scoped
catalog and POST uses only the prepared selection.

Dependencies: repository's Python 3.12 environment, the existing focused tests,
and the existing isolated mutation harness. The separate main-chat context
integration needs the orchestrator's actual per-turn selected route and a
capability/provider adapter contract; the composer currently has neither, so
this campaign does not claim Hermes's main-first automatic route.
