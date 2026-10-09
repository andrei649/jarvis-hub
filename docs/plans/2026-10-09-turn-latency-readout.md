# Current-turn latency in chat (H686 first slice)

- Generated: 2026-10-09 UTC.
- Goal: show the measured duration of the current completed turn in both HUD chat surfaces, controlled by the persisted display field selection.
- Base/initial head: 33e542bd474fb25afa8908dd0e99fe0e1d247966.
- Branch/worktree: codex/turn-latency-readout-20261009, /workspace/jarvis-hub-turn-latency-readout.
- Delivery: autonomous local development; no new publication or live inference.
- Tested source: 43fba70bc7d7592d2d4b6646107666b22c7068a0.
- State: local implementation, independent reviews and full verification complete.
- Next action: retain this checkpoint and choose the next verified local gap. No publication follows from this unit.

## Contract and scope

Use one optional `outcome` on ChatResponse and every SSE end event, as critic note 10 of the Hermes build queue requires for H220/H396/H686. This first slice carries only `latency_ms`: finite nonnegative wall time around the public orchestrator handle_input/handle_input_stream invocation, including orchestration and cleanup, excluding HTTP setup and network delivery. A typed refusal or command returned normally can have a duration; duration does not imply model success. Exceptions, cancellation, unavailable/busy paths and test doubles without measurement have `outcome: null`. Preserve reply text, session IDs, notices and approvals.

Open a request-owned collector at /chat and within the SSE runner. The orchestrator publishes once into that collector; nested calls cannot replace the outer measurement. Close/freeze collectors after use, so copied contexts and late tasks cannot alter returned results. No global or per-session last-result cache; concurrent sessions are isolated. Do not infer metrics from prose or reuse per-agent latency as whole-turn latency.

Add display.status_bar_fields, default ['latency'], a distinct bounded list from the fixed vocabulary model, context_pct, cache_hit, latency, tps, compressions, bg_tasks, duration. Empty list hides the readout. Filter metrics server-side using the declared setting, so chat does not need admin access to read display preferences. Only latency is implemented; other allowed fields remain absent, never synthetic zero. The existing generic Admin Settings editor is the mutation surface; no new endpoint or permission. The HUD uses a typed runtime projection and shows only valid present latency, with a label describing turn duration. One shared StatusStrip serves cockpit and focus chat. Clear outcome on send, error, stop, session/agent selection and demo changes; reject stale end callbacks with existing epoch guards.

Non-goals: TPS/first-token instrumentation, context occupancy, model selection display, cache invalidation or ratios, compression counters, costs, H396 exit reasons/accounting, native readout, historical/persisted metrics. H686 remains partial. Future H220/H396 work extends this same outcome, not parallel stats/usage payloads. Existing provider accounting and context anchors are untouched.

## Ownership and tests

- auth_audit (gpt-6-sol/high): new core/turn_outcome.py, public-wrapper instrumentation only in orchestrator.py, web.py outcome collection/projection only, settings_db.py declared selection+validation, client_protocol.py end fields; tests/test_turn_status_readout.py and necessary bounded client descriptor assertions. First tests prove missing payload; test clocks deterministically, both wrappers, normal refusal, exception/cancel, concurrent requests, nested calls, collector closure and settings validation/persistence.
- mobile_session_transport (gpt-6-sol/high): frontend app.tsx/cockpit.tsx/modes3.tsx, new turn-outcome.tsx and mounted/component tests. Own frontend changes except generated schema (root). Runtime-validate finite nonnegative numeric values; never render booleans/null/negative/NaN/infinity. Tests both chat surfaces, no fabricated placeholder, late events, reset/send/stop/session/agent/demo lifecycle. Existing generic settings editor should expose display automatically; confirm with evidence.
- wall_contracts (gpt-6-luna/medium): read-only exact-base evidence inventory.
- Root: shared contract, meaningful RED review, integration, generated OpenAPI/build, docs/parity/status, bounded evidence refresh, git. At most four active, no nested agents.

Source edits begin after reported expected REDs. One writer per file; no changes to unrelated parked worktrees. Test artifacts saved under /workspace/scratch/h686-turn-latency-*. Independently review backend and frontend. Run focused tests then applicable route/session/settings regressions, full frontend/typecheck/build and one serial backend milestone because public wrappers and web contracts change. New routes are not introduced. Check protocol/OpenAPI/lifespan/parity guards. Regenerate types from actual app schema using pinned generator; commit built HUD if repository convention requires. No provider/server accepting external connections/device calls.

Update mobile/PARITY.md with native gap and docs/design/HUD_V2_REMAINING.md with exact HUD scope. Keep H686 partial and record shared-outcome dependencies in H220/H396. Refresh only exact-base-fresh evidence pins whose claims are checked, or explicitly reassess a bounded row; preserve unrelated stale pins and all immutable inventory identities. Sync canonical executed/collected counts truthfully.

Rollback: revert this coherent source/test/docs unit; no database migration (ordinary additive setting seed), no new endpoint or persisted chat state. Default selection may remain as an unused setting row after code rollback.

## Browser finding during integration

The new compiled-HUD regression passed at 1280px but failed at 390px: the duration output had x=-127. The focus-chat column inherited the composer min-content width and could not shrink. This unit also applies the existing cockpit wrapping/input shrink rules to `.chat-col` and gives that column `min-width:0`; no global layout redesign. Root owns this bounded styles.css repair and its real browser regression.

Final verification (2026-10-09T14:24:01.735919+00:00): full backend 21641 passed/37 skipped/21678 total (295.465 s), same 37 skip identities as the prior milestone; full frontend/native 2027/2027; browser 2/2; app/E2E typecheck and production build passed. The initial full run had one old exact-JSON warmup expectation missing outcome:null; only that expectation changed before the successful repeat.
