# H18.33 native current-turn duration

- Generated: 2026-10-09 UTC.
- Goal: show the server-selected duration of the current native chat turn, with no stale or persisted metric.
- Base/initial head: ecc50430a62fd91e87585a4dfda09cfca112ce1a.
- Branch/worktree: codex/native-turn-duration-20261009, /workspace/jarvis-hub-native-turn-duration.
- State: implemented and verified locally. Next action: checkpoint the clean commit; device/live-Hub acceptance and broader project work remain open.
- Delivery: autonomous local development; no new publication, live provider or device access.

## Contract

Consume the existing H686 outcome, which is null or an object containing nonnegative integer latency_ms. Add an optional third normalized outcome argument to native streamChat.onDone. Preserve the existing first two arguments and TWO-argument invocation when no valid outcome exists, including EOF without explicit end. Only explicit end frames can supply a metric. Admit an own latency_ms property that is a finite nonnegative safe integer, including zero; drop other fields. Missing, null, boolean, string, fractional, negative and unsafe/exponent-overflow values are unavailable. Do not change SSE framing, response/session semantics, credentials, timeout or cancellation behavior.

Use one ephemeral ConversationState.turnOutcome: TurnOutcome | null, separate from ChatMessage and SavedConversation. Initialize and hydrate null; clear on accepted send, selected-image start, stop, resume, error and disposal. A first ordinary end acquiring a concrete server session can carry duration. An actual /new, /reset or /undo rollover clears it, while a refused command in the same session can have duration. Preserve existing partial-text/EOF settlement: no invented timing and no transport semantic rewrite. Save only an explicit {sessionId, messages} projection and prove actual stored bytes and remount contain no metric.

Agent selection currently permits an in-flight old reply to finish. Preserve that behavior. Add clearTurnOutcome() with a metric-specific generation: it clears immediately and prevents the already-running turn from republishing duration, including A-to-B-to-A changes. Existing conversation epoch still controls reply/session/cancellation; do not abort text merely to hide the metric. Call the method synchronously on agent change, including a changed asynchronously restored preference. Bind the visible screen snapshot to the current connection scope/epoch so a reconnection cannot show a prior metric while controller replacement awaits an effect.

ChatScreen renders one small themed accessible strip between the transcript and composer, labelled Turn duration. Show only valid current state when not sending. Use the same whole-turn meaning as HUD, not model speed or proof of execution success. No MessageBubble metric field, native preference API, per-session accumulator or stored historical duration. Existing selected-image, voice, dictation, command, session and hub gates remain intact.

## Ownership and meaningful regressions

- auth_audit (gpt-6-sol/high): mobile/src/api/client.ts streaming section, api/sse.ts type-only optional outcome field if necessary, new chat/turnOutcome.ts pure normalized type/helper if useful, chat/conversation.ts; own API streamChat Jest and conversation Jest tests. Own no screen or native mounted test files. Demonstrate actual callbacks/replies before missing outcome assertions; no RED consisting only of missing module imports. Prove two-argument compatibility, strict number projection, explicit end, late frames, ephemeral state, all lifecycle clears, metric-only generation and explicit persistence projection.
- mobile_session_transport (gpt-6-sol/high): mobile/src/screens/ChatScreen.tsx, optional new presentation component, new frontend/native-tests/turn-duration.test.tsx. Own no API/controller files. Expected state is turnOutcome and controller method clearTurnOutcome(). Mounted real ChatScreen/ServerProvider/XHR tests for current metric, zero, no-data/malformed, new send/stop/error/session/reset, selected-image start, pending agent switch away-and-back preserving text but suppressing duration, hub replacement/reconnection and remount/storage omission.
- Root: contract, base-hash/RED review and release, source review/integration, docs/parity/backlog/evidence/counts, git. wall_contracts (gpt-6-luna/medium) read-only inventory. Maximum four active, no nested agents.

No production edits until root has inspected the expected RED failures and exact base hashes. One writer per file. Final independent reviews cross backend-client/state and native UI. No new dependency is required; reuse existing frontend/native and mobile test environments via local symlinks without changing targets.

## Verification and remaining work

Focused API/controller and mounted regressions, then full mobile Jest and full frontend/native suites serially, mobile/app/E2E TypeScript, and Android/iOS export using existing installed dependencies where available. Backend production is unchanged: reuse the latest full backend 21641 passed/37 JUnit-skipped on 43fba70, run applicable parity/status guards and report reused counts accurately. Full backend repetition requires a new backend change or failure. Record native device/live-hub validation as unrun with specific scope, never infer it from host tests.

Update H18.33 and mobile/PARITY.md to exact local implemented scope and remaining device acceptance; H686 remains partial with its other metrics open. Update HUD remaining only as needed for native gap status. Refresh only base-fresh claim pins after bounded review; stale pins remain stale unless explicitly reassessed. Current project baseline counts 21678 backend,2027 frontend/native,306 mobile,555 routes,18 agents. Whole-project inventory remains 36 open checkbox rows plus horizon tasks and 569 Hermes rows not currently equivalent; this unit does not close the whole project.

The separate skipped-test inventory is in /workspace/scratch/post-h686-skipped-tests-audit.md. It distinguishes 36 guarded skips from one source-integration xfail. Missing optional dependencies and opt-in local verification are actionable research, not blanket blockers; they are separate from this feature's implementation/rollback unit.

Rollback: revert this native API/state/UI/test/docs unit. No persisted schema, backend endpoint or authority change; old callbacks continue accepting the first two arguments and existing history bytes remain compatible.

## Final local result

Root inspected core RED (6 missing-feature failures/22 controls) and native RED
(5 failures/2 controls), then verified all six existing production hashes before
release. Final focused API/controller tests pass 31/31; mounted native tests pass
12/12. Cross-review identified a static accessible label that hid the number;
an explicit label regression failed before the dynamic-label fix and passed after.
The final native suite also checks a real XHR error and the first connection-epoch
commit before passive controller recreation. No open Critical/Important finding.

Full suites ran serially: mobile 316/316 and frontend/native 2039/2039
(1862 HUD +177 native), no failures/skips. Mobile/app/E2E TypeScript and offline
Android/iOS Metro/Hermes exports pass. Backend source is unchanged: prior full
21641 passed/37 JUnit-skipped is reused; 109 targeted parity/protocol/status cases
pass freshly. A separate clean-base cached-image Docker opt-in run passed 11/11,
including nine previously guarded cases; it does not replace that prior full run.

Evidence: `mobile/docs/h1833-turn-duration.md`; eight frozen source/test hashes
and exact-base pin review under `/workspace/scratch/h1833-*`. One fresh H526
client pin refreshed after named unchanged-TTS review, nine native H686 pins
added, preexisting stale H135 pin retained. All 226 review status/identity values
and immutable inventory hash unchanged; H686 stays partial. Generated project
counts now 21678/2039/316 tests, 555 routes/18 agents. No backend/schema/dependency
change, live provider/device use, new push, merge or deployment.
