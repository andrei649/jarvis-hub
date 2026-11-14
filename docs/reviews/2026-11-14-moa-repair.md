# MoA and stacked-branch repair review

Generated 2026-11-14 UTC. Owner requested review and merge of eligible PRs. Source: PR #1366 at `155c9150eeb42c279ec1c3ddcecaa86cc57752e5`, combined with parent #1365 at `17eaceaa2c89872c58528dfc3e36a33b151aeb38`. Main reconciliation brings the reviewed BACKLOG/INSTALL documentation; cumulative features are preserved.

## Repairs and evidence

- Cloud aggregation supplies optional activity callbacks only when accepted by the real adapter signature; no duplicate-call retry.
- Active preset edits enforce the managed selection pin under the store lock, for HTTP and offline CLI.
- MoA storage honors HOME aliases. Run endpoint uses the shared component guard, preserving validation order and 503 behavior.
- Optional context-window failures log only exception type. A B404-only subprocess import rationale documents argument-list/no-shell calls; no installer behavior changes.

The cloud signatures, active-pin edits and both CI contract failures reproduced red before repair. Combined focused MoA, managed-scope, environment, component and bootstrap-contract suites plus status verification: **194 passed**. Independent review ran unchanged Bandit baseline gate: exit 0. Ruff and whitespace pass. No real provider, macOS TCC, installation, deployment or previously blocked update/restart action was run.

Expected Linux JUnit count: **36723**, not a claim that 36723 tests passed. Authentic #1365 CI job 132452588220 recorded 36700. Successful paired canonical collection yielded 36709 for the documentation-only reconciled parent and 36732 for this candidate. All 23 additions are 16 MoA and 7 macOS node IDs; none removed. Locked dependencies, pytest config and conftest unchanged. The optional local Discord SDK contributes a constant 9-entry offset, canceled by the paired delta. Existing status renderer preserves frontend/mobile counts and source stamp. Exact candidate CI must confirm the expected count.

## Remaining hold

The macOS library-staging rollback-journal defect remains unresolved. Cumulative update/restart adversarial review was previously blocked by the platform and was not retried or circumvented. Functional CI and Bandit do not clear those findings. Keep draft until valid resolution. Reverse this repair commit to roll it back while retaining its parents.

Prior H079 CI timeout did not reproduce: the isolated test passed, and its fixture suite plus startup test passed (10 tests). No assertion or timeout was changed; exact-head CI remains the next evidence.
