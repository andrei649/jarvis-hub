# H18.30 — mobile conversation continuity

- Goal: History resumes the exact selected conversation and subsequent messages stay on it, including after an app restart.
- Base SHA / HEAD at start: `304ae4babf1c1a91777c5b780d80ac172c32077e`.
- Branch: `codex/mobile-session-continuity-20261008`; publication authorized by the owner on 2026-10-09 (Europe/Bucharest).
- Generated: 2026-10-08 UTC.
- Changed paths: `mobile/src/api/{client,sse}.ts`, `mobile/src/chat/conversation.ts`, `mobile/src/screens/ChatScreen.tsx`, `mobile/src/components/SessionsModal.tsx`, `mobile/src/storage/{chat,settings}.ts`, `mobile/src/context/ServerContext.tsx`, their unit tests, `frontend/native-tests/conversation.test.tsx` and its native host mock; backlog/parity and generated test-count documentation.

## Behavior and boundaries

Previously, the native screen discarded the ID returned by History and sent only message/agent with the following turn. It also cleared only local messages when New was pressed. The screen now owns a connection-scoped conversation controller: selected and returned IDs travel with every subsequent request, and the ID plus bounded settled transcript are written as one serialized AsyncStorage record.

An opaque cache scope lives with the existing connection settings, persists across restarts, and rotates on any URL/user/admin credential change. It contains no token or token-derived hash and grants no authority. The old unscoped local history key is retained, but is not automatically assigned to a connection; saved server conversations remain accessible through History. Storage remains best-effort, with no cross-key/process atomicity claim.

New sends the existing `/new` owner command. New/reset clear the visible old transcript only when the server confirms a different concrete ID. Undo fetches the exact returned session, and its delayed fetch cannot replace a newer turn. A refused command preserves the previous topic. Chat and History pass already configured owner credentials; all server permission checks remain unchanged. Invalid selected IDs fail before a request instead of silently selecting the hub's current session.

Hydration does not save an empty thread over the cache. Disposal, Stop, topic selection and connection changes revoke stale callbacks; changing hub/credentials clears the visible prior thread. History refuses unsuccessful/mismatched resume responses and ignores responses after the modal closes or changes connections.

Non-goals: backend session policy, image review/history parity, command discovery, Hermes runtime integration, deployment and physical-device acceptance. Existing APIs and dependencies are reused. Revert the mobile source and related test changes to roll back; server transcripts are unchanged and the legacy local cache remains on disk.

## Verification

Transport regressions failed before the implementation: selected ID omitted, end ID dropped, late callbacks delivered, configured owner header absent and invalid IDs silently dropped. The History admin-only regressions failed before the header fix. Storage regressions failed on the missing session-aware API; scope regressions failed on the absent persisted identity. The conversation controller is covered through request-boundary tests and mounted native-screen tests.

- `cd mobile && npm test -- --runInBand --json --outputFile=/workspace/scratch/mobile-tests-final.json`: **173/173 passed** in 39 suites (31 new tests).
- `cd mobile && npx --no-install tsc --noEmit`: passed.
- `cd frontend && npx --no-install vitest run --config vitest.native.config.ts --reporter=dot`: **45/45 passed**, including six new mounted conversation tests. The host shim still emits its pre-existing nested-DOM-button warning for native Pressable nesting.
- `cd frontend && npm test -- --reporter=json --outputFile=/workspace/scratch/frontend-tests-final.json`: **1,864 passed, 1 failed**, 1,865 collected. The failure was a 5-second timeout in unchanged `src/test/selection-guard.test.tsx` → `a guarded settings choice names the price and is sent again with the flag once the model is typed`.
- Isolated diagnostic rerun, `npx --no-install vitest run src/test/selection-guard.test.tsx --reporter=verbose`: **5/5 passed**; the previously timed-out case took 160 ms. This rerun does not turn the full-suite result into a green run; the full-suite timing failure remains recorded, with no change to that test or its timeout.
- Frontend `npm run typecheck` and `npm run typecheck:e2e`: passed.
- `python scripts/status_sync.py --reuse-test-counts`, both frontend/mobile `--verify-test-count` checks, and `--check --reuse-test-counts`: passed. Frontend 1,865 and mobile 173 come from the actual JSON results; backend 20,985 is explicitly reused, not executed in this mobile-only change.
- Trusted unchanged `scripts/selfdev_policy.py classify` reports `autonomous_local_development: true` for the implementation; `git diff --check` passes.

Native host tests use React DOM plus the repository's React Native/service mocks; they do not constitute Android/iOS device or real-Hub/LLM evidence. No complete backend suite, native package build or provider-backed acceptance was run.

## Review and continuation

Implementation split: coordinator owned conversation/storage/UI; `gpt-6-sol` at high effort owned transport and its regressions. A separate `gpt-6-sol` at high effort reviewed the diff and identified the History admin-only credential gap, now covered by regression tests. Its final pass found no remaining Important or Critical findings. No subagent delegated or performed a remote mutation.

Next action: run the mobile app against an owner-configured hub, resume a saved topic, send a follow-up, restart, then exercise New/reset/undo and switching connections. H063 overall equivalence and selected-image controls remain partial. The initial implementation was kept local; the owner subsequently requested a GitHub PR. Merge, deployment and paid-provider activation are outside that publication request.
