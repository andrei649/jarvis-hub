# Reviewed local follow-ups

Generated 2026-10-09 UTC. Branch `codex/project-followups-20261009`, base
`a7d00151cd4d1c2757b938e051cbde19212a29fd`, integrated source `6507cc4`.
The [global baseline evidence](project-integration-20261009.md) remains the
record of the full backend/frontend runs. This branch adds two independent
local units without changing their reviewed runtime source:

- Exact research mediation: `c745e2e` → `10e829f`, with metadata correction
  `53261a6` → `6f50037`. Governed research obtains kernel authority and durable
  evidence; unknown task kinds stay refused. See the
  [scope and remaining work](plans/2026-10-09-research-task-mediation.md).
- Admin accessibility readiness: `0c9c8f6` → `6507cc4`. The mode scan waits for
  the pause card's settled state and preserves explicit empty-state reporting.
  See the [six-test browser proof](plans/2026-10-09-admin-estop-readiness.md).

Only generated status files conflicted. They were regenerated with backend
21,012, frontend 1,962 and mobile 284, preserving both units' test additions.
Backlog and reviewed evidence changes merged without overlap. The five
research registry rows and Admin's H277 row exactly match their reviewed source
candidates; all prior statuses, remaining limits and unrelated stale pins stay
unchanged.

On the combined source, the research regression, action-auth matrix,
task-mediation evidence, web-tools wiring, status and Hermes suites passed
**248/248** in 14.951 seconds. Report:
`/workspace/scratch/project-followups-focused.xml`. Generated status, Hermes
freshness and whitespace checks passed. Source comparisons confirm the research
runtime/tests match `53261a6`, all frontend source/tests/assets match `0c9c8f6`,
and mobile runtime/manifests/native host files match `8cb474f`; the only later
mobile-tree changes are parity documentation.

The Admin unit's 8 component tests, TypeScript/build and 6 Chromium checks apply
unchanged. Full baseline backend (20,966 passed, 37 skipped), frontend (1,959
passed), mobile (284 passed), native exports and permission evidence are reused
with those version limits. The follow-up inventory adds nine backend and three
frontend cases; no full-suite execution of the expanded totals is claimed here.

No push, merge, deployment or live-model acceptance is included. PR #1247
remains the separately published draft. DRA-59 and broader mode readiness remain
open; the project backlog is not complete. Either follow-up can be reverted
independently, with the fully verified baseline preserved.
