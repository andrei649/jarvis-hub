# H487 trusted model request grouping

Generated 2026-09-27. Base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus preserved local work. Goal: extend existing safe decision-card grouping to
actual generic model ToolRPC requests. Next action: implement owned backend and
independent integration-test slices, then review and verify. H513's preceding
milestone passed 19,194 backend tests/35 skips and 1,822 frontend tests.

## Contract and authority

Only generic ToolRPC's existing gated enqueue branch may mint this provenance.
Reuse its verified live ToolApprovalContext, binding exact principal, session ID,
session instance, tool name, effective actor, raw argument identity and a private
server-created tool-registration epoch. A re-registration changes the epoch.
A new closed model producer context/scope is separate from HTTP owner markers;
model arguments, JSON authority claims and an inherited admin principal cannot
construct it. Closed/expired/copied contexts and specialized intakes opt out.
No new public caller field, route, setting, capability or permission is introduced.

Worker.govern_enqueue finalizes origin/taint, classification, policy, kernel floor
and receipt/evidence first. For a real ASK/BLOCKED task, register grouping before
notification scheduling, using the existing atomic pending-member validation.
Bind the final semantic task fields, effective policy and proven authority category;
verify they match the producer's actor/tool/arguments. Full member snapshots and
independent signed receipts remain intact. Unique task/receipt IDs are membership
identity, not request equality. Namespace separates HTTP and model registrations,
principals, live sessions/instances, registrations and policy/taint. Bound the
serialized material and group size as before. Ambiguous proofs leave independent
cards. Metadata failure must not enqueue a second task, grant permission, drop a
pending ask or misreport a successfully persisted ask as an unpersisted failure.

Reuse existing leader/follower suppression, promotion and snapshot-CAS rejection.
Approval/edit/defer applies only to its selected task; approval never fans out.
This is notification grouping, explicitly not shared event/decision semantics.
The existing UI wording and card shapes remain unchanged; no frontend code slice.

## Ownership

Writer A (Sol High) owns agents/core/autonomy/approval_grouping.py,
agents/core/tool_rpc.py, agents/core/autonomy/worker.py,
agents/core/autonomy/queue.py and new tests/test_h487_model_grouping.py. Preserve
public signatures where possible with a private context scope; coordinator/raw
queue fallback must not infer provenance. Declare any extra fixture need first.

Writer B (Sol High) owns only new
tests/test_h487_model_grouping_integration.py. Exercise existing public
ToolRPC/worker/queue/origin/turn APIs in an offline isolated fixture; do not couple
the integration tests to a particular new helper/class name. No source edits.
Coordinate each new test module's freeze before combined execution. No subagents.

## Acceptance and verification

RED/GREEN tests: actual two generic asks yield one visible card and two distinct
pending task IDs; same normalized semantic request can group, but different
principal/session instance/registration/policy/taint/arguments cannot. Closed
contexts, raw fallback and specialized intake cannot borrow the marker. Finalized
receipts remain independent, invalid or stale receipts cannot group, and approving
one executes only that task. Leader removal promotes a pending follower; stale
edit/expiry/member snapshots cannot authorize neighbors. Metadata fault injection
preserves the individual ask. Restart preserves existing valid groups without
letting a new registration epoch join an old one. Existing owner-HTTP behavior,
chat observations, judge freshness and expiry semantics remain intact.

Focused tests per implementation step; parent runs combined integration, updates
reviewed evidence only and a serial full backend milestone. The unchanged frontend
reuses its preceding passing snapshot. No live providers, publication, paid calls,
global configuration or unrelated changes. Rollback only this slice's hunks.

## Explicit remaining frozen H487 requirements

This increment does not complete session/always/deny adoption (never once-only),
shared decision/event semantics, supported additional surfaces or human-wait budget
accounting. Existing PermissionLedger has no verified ToolRPC approval consumer;
its process-boot session and surface/resource keys cannot be repurposed as exact
chat/tool authority. A separately designed standing-permission integration must
satisfy that original contract. Generic ToolRPC returns approval_required promptly;
an uncalled wait-accounting helper would not satisfy the human-wait requirement.
Ordinary promotion delivery retry is a reliability follow-up, not a replacement
for these explicit gaps. H487 remains partial after this notification slice.

Coordinator GO: the contract above is released for execution.
