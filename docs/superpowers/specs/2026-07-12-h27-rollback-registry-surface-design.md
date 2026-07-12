# H27 rollback contracts and registry surface — design

## Goal

Deliver H27.6 and H27.8 as one coherent read-surface wave: every registry record exposes a
validated, machine-readable rollback contract; queued governed actions carry that contract into
the approval experience; and the capability inventory has a canonical user-guarded API plus HUD
columns for risk, supports, and confidence.

## Non-goals

- Do not mark H27.5 complete or fabricate verification cases for the remaining 70 records.
- Do not implement earned autonomy or modify approval tiers (H27.7).
- Do not execute rollback automatically. This wave describes rollback and may point to an existing
  handler; it does not create a second action/undo dispatcher.
- Do not remove or change the compatibility contract of `/api/metrics/capabilities`.

## Design

### Machine-readable rollback

Add a frozen `RollbackContract` value to the existing capability manifest/record. It contains a
bounded `mode`, a human-readable `description`, whether automatic rollback is supported, and
optional `handler_ref`/`limitations`. Validation rejects unknown modes, blank descriptions,
automatic contracts without a handler, and contradictory `mode=none` contracts.

Action manifests declare explicit contracts. Plugin/component/skill/tool records derive conservative
contracts from their existing lifecycle: disable/restart or no-op where appropriate. The registry
serializes the dataclass as JSON; no parallel rollback registry is introduced.

### Approval projection

The autonomy router resolves `task.kind` through `manifest_for_action`, including wildcard action
kinds, and attaches the serialized rollback contract to blocked task rows and `/autonomy/approvals`.
Unknown task kinds expose `rollback: null` rather than inventing a promise. Browser Decision Inbox
and native Approvals display the description when present and an honest unavailable state otherwise.

### Registry read surface

Add `GET /api/capabilities` to the existing analytics router with `user_guard`. It returns the same
live snapshot as the legacy metrics endpoint. The HUD readiness board switches to the canonical path
and renders per-record readiness, risk, supports, and confidence. `/api/metrics/capabilities` remains
available for compatibility and monitoring.

## Files

- `agents/core/capability_manifests.py`
- `agents/core/observability/capability_registry.py`
- `agents/core/routers/autonomy.py`
- `agents/core/routers/analytics.py`
- `frontend/src/gap.tsx` and focused frontend tests
- `mobile/src/api/client.ts`, `mobile/src/screens/ApprovalsScreen.tsx`, focused mobile tests
- route/OpenAPI/auth snapshots, generated OpenAPI types, parity/backlog/status documentation

## Risks and mitigations

- **Schema break:** keep endpoint additions additive, retain the metrics endpoint, and test all record
  sources. The intentional `rollback` string-to-object change is pinned in backend and UI tests.
- **False rollback promise:** `automatic=true` requires a concrete handler; irreversible or provider-
  dependent actions declare limitations and never claim automatic recovery.
- **Auth drift:** add the route under the existing domain router with `user_guard`; reseed and inspect
  route, OpenAPI, and auth snapshots.
- **Client drift:** update browser, native approvals, `mobile/PARITY.md`, and the generated TS schema in
  the same PR. Track the new registry board for mobile through H18.21 rather than implying parity.

## Tests

- Red/green manifest validation and exact rollback coverage for all 12 actions.
- Registry serialization tests across action/plugin/tool/component/skill records.
- API/auth tests for `/api/capabilities` and approval rollback projection, including wildcard and
  unknown task kinds.
- Browser tests for registry columns and rollback story.
- Mobile API/screen tests for rollback rendering.
- Route/OpenAPI parity gates, focused backend/frontend/mobile suites, lint/typecheck/build, then CI.

## Rollback

Revert this PR. The legacy metrics endpoint is unchanged, and the new path/UI projections are
additive. No persistence migration or external side effect is introduced.

