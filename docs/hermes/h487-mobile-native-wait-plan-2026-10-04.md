# H487 native mobile consent and live human-wait integration

Generated: 2026-10-04. Goal: full local functional parity with all697 pinned
Hermes capabilities. Base/head:87b2a1b86bb4f5d0580118623b5c3f43156c7371.
Previous Telegram/CLI milestone:22,292 backend passes,34 skips and1 existing
expected failure, zero failures;2,884 frozen paths unchanged before records.
This plan adds no equivalent credit by itself. Local only; no publication,
activation, paid services or real process/device effects.

## Grounded design

The existing mobile screen lacks `consent_offer`, human reasons and positive
decision confirmation. Keep its admin authentication and desktop approval
boundary. Render session/always/deny only from a bounded validated server offer;
permanent consent additionally requires every category to support permanence.
Send the exact displayed revision, never substitute a fetched one after409.
Optional reasons have the backend's280 Unicode-code-point limit. A synchronous
controller lock prevents double submissions before React renders its busy state.
Refresh only after a confirmed response; errors retain the displayed snapshot.

The real AgentToolRuntime currently gives tool handlers30 seconds and the whole
run120 seconds while a verified owner card may wait120 seconds. Pinned Hermes
tools/approval_human_wait.py credits the union of actual human waits, not gate
residency; agent/tool_executor.py consumes a baseline delta. Adapt that principle
to runtime-issued per-run context and exact native prompt registrations. Track
monotonic bounded intervals only after verified delivery, stop at prompt expiry
or authority/lifecycle loss, and keep unrelated hangs on their original clocks.
Timing credit never grants execution permission. Durable Company wait credit is
already present and is not the missing live tool/runtime integration.

## Tasks, interfaces and single writers

1. Mobile API implementer (Sol High): mobile/src/api/client.ts and API tests.
   Export ApprovalConsentChoice=session|always|deny, ApprovalConsentOffer and
   validatedConsentOffer(value:unknown):ApprovalConsentOffer|null; add optional
   consent_offer to ApprovalTask. Export decideApprovalConsent(config,taskId,
   choice,revision,reason?) using existing authenticated consent route. Validate
   positive safe integer task IDs, exact lowercase64hex revision, supported
   choices and <=280-code-point reasons before fetch. Require ok===true and a
   nonempty valid tasks array containing selected ID. Ordinary decideApproval
   adds optional reason while keeping omitted-reason body exactly{action}.
2. Root: mobile/src/screens/ApprovalsScreen.tsx, approvalPolicy.ts, new pure
   approvalDecision.ts and functional controller tests. Preserve desktop policy,
   avoid forged authority fields, test actual dispatch/revision/reason/errors,
   synchronous busy exclusion and success-only refresh. No dependency changes.
3. Runtime implementer (Sol High): agents/core/agent_runtime.py, new
   agents/core/native_human_wait.py and pure timer/runtime tests. Root first
   demonstrates a delayed genuine owner reply outliving an injected tool budget.
   Exact proposed interface: runtime_human_wait_scope() context manager establishes
   a fresh per-run scope; current_human_wait_scope() returns it or None; scope
   seconds() reads union credit. native_human_wait_window(deadline=monotonic,
   current=zero-argument live predicate) opens only in a current run, finite
   deadline, current native request task; closes in finally. Runtime wall/tool
   consumers capture their baseline and extend only those owned deadlines using
   credited delta. Event-sink budgets must not extend. Preserve cancellation and
   straggler quarantine; cap per window at declared native wait plus60 seconds,
   with no credit beyond actual expiry/loss. Tests: overlap, bounded reads/close,
   current invalidation, unrelated scopes, ordinary hangs, prebaseline exclusion,
   wall and tool deadlines, nested/parallel calls and cancellation.
4. Root: consent_prompts.py, owner_once_prompts.py, real native runtime integration
   tests; open the timing window only around waiting for a delivered exact prompt,
   never sending/queue locks/arbitrary handler code. Register and check actual
   source/parent/task/offer/transport binding. Remaining inline timeout and denial
   reason outcomes are separate follow-up work, not claimed by timing support.
5. Root: review each unit, run focused suites after each change, all mobile Jest
   and tsc, appropriate docs/status/routes/scans, rebuild Graft after source edits.
   Run expensive backend suite serially once at a frozen integrated milestone.
   Re-read collateral claims rather than blindly rehashing; no fresh live or
   mutation acceptance from historical evidence. Update backlog and evidence.

## Review and rollback

| Pair/task | Shared contract | Ruling |
|---|---|---|
| API/root mobile | validated offer and strict dispatch | Agreed interfaces above; distinct files |
| Runtime/root prompts | current per-run timing scope | Exact trusted native window; no model-controlled flags |
| Mobile/runtime | No shared source | Independent work; tests may run independently |
| Mobile task | TDD, exact revision, auth, desktop boundary | Existing APIs retained; no dependencies |
| Runtime task | TDD, hard expiry, ordinary timeouts | No blanket timeout increase or gate residency credit |

Ruling: owner-authorized autonomous local development permits implementation
without renewed design approval. The pinned Hermes source and existing Nerva
authority constraints control the design; this plan is provisional where real
regressions reveal a stronger requirement. Each unit remains independently
reviewable and revertible; retain the Telegram/CLI commit. Next action: dispatch
mobile API task, establish real runtime RED, then finalize timer interface.

## Delivered milestone and next action

Mobile is independently committed as ce96e6ae. Native timing passes133 connected
regressions and the broader2,811-pass/1-skip selection. The terminal full backend
run passes22,312 with34 skips and1 existing expected failure, zero failures/errors;
all2,982 frozen paths remain unchanged before the final records. The separate
`docs/hermes/evidence/h487-native-wait-full-2026-10-04.json` preserves this result
without rewriting the earlier focused receipt. H487 remains partial and all697
remain the accepted goal. Next action: source-bound cross-surface inline decisions,
explicit timeout/withdrawal outcomes and denial reason handback, with RED/GREEN.
