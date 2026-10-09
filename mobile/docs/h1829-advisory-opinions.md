# H18.29 — native advisory approval opinions

- Goal: show optional H277 task opinions and a read-only model-role configuration view on the native Approvals screen. Keep owner decisions available with no opinion or while one is pending.
- Non-goals: change approval authority or `approvalPolicy`, start a judge, probe model connectivity, call live providers, change the backend, or claim device acceptance. Automatic pending polling is deferred; pull-to-refresh is the bounded user-triggered check.
- Base SHA / head at start: `da7c8a222c2cd0cb658b192c967194bc9c88efa3`.
- Branch: `codex/mobile-advisory-opinions-20261009`. Generated: 2026-10-09 UTC. Local candidate only; no push, merge, or deployment.
- Changed paths: `mobile/src/screens/ApprovalsScreen.tsx` (minimal import/render insertion), new `mobile/src/screens/AdvisoryApproval.tsx` and `mobile/src/api/advisory.ts`, focused `frontend/native-tests` and `mobile/src/api/__tests__/advisory.test.ts` tests, this note, `BACKLOG.md`, `mobile/PARITY.md`, and `docs/design/HUD_V2_REMAINING.md`. Avoid changing `mobile/src/api/client.ts` because H526 pins its evidence hash.
- Dependencies: `GET /autonomy/approvals` is admin gated and already uses the task judge projection, exposing optional `judge` and `judge_pending` per pending task. Its `pending`, `reversible`, `irreversible`, and `counts` buckets feed the existing cards. `GET /api/llm/roles` is user gated and returns configuration plus `reachable: null`; no connectivity probe occurs. The existing owner decision POST remains the authority boundary. The opaque `chatScope` rotates with URL or credentials and fences stale callbacks.
- Tests: focused regressions failed before the component existed for opinion/pending/missing data and read-only roles/connectivity wording. They then cover roles stale across a changed hub and ensure an opinion never changes the owner POST. Run native host tests and mobile TypeScript checks. The parent integrator owns serialized full suites and generated counts. Poll deadlines are not applicable because there is no automatic polling.
- Rollback: revert this local native presentation/API/tests/docs slice. No server state, role selection, or decision contract changes are planned.

## Acceptance left open

Physical Android/iOS review and a real hub with an opt-in H277 judge remain open. No provider call is required for this local candidate.

The focused hardening regressions first failed on the omitted admin header, malformed roles presented as empty, missing timeout/pre-abort handling, invalid opinion children, and missing loading/retry states. After the fixes, `frontend/native-tests/approvals-advisory.test.tsx` passed 9/9, the three targeted mobile Jest suites passed 10/10, and mobile `tsc --noEmit` passed. These are local simulated transport/React-host checks, not physical-device or provider acceptance.

Open draft #1233 owns native consent/reason controls, the decision controller, and loading/connection epoch fencing. This local slice does not edit those flows and must integrate with that draft before its broader decision-lifecycle behavior can be claimed here. H18.30/#1247 supplies the opaque `chatScope` used by the roles view to reject old-connection results; the roles view never derives identity from credentials.

Integrator verification (2026-10-09): complete mobile Jest suite **177/177 passed**, complete native React host suite **54/54 passed**, and mobile `tsc --noEmit` passed. Independent read-only review found no Important or Critical issue. The native host suite initially ran from the wrong working directory and found no tests; it was rerun from `frontend/` with the native config. Physical-device and live-judge acceptance remain open.
