# H487 action registration grouping — bounded implementation plan

Approved scope: action queue, new approval_grouping helper, actions router and
new focused tests only. No task/UI/browser/auth changes, full suite or publication.

## Trusted producer and semantics

Only HTTP /api/actions/request registrations whose existing lazy web principal
is a verified owner are eligible. Reuse _deps._web()._web_principal(request) after
user_guard; do not invent an execution session from orchestrator.session_id.
Ordinary user registrations, direct queue/browser callers, task-bound requests,
and requests claiming principal/session/policy/authority/binding context opt out.
A fixed server context names owner + http_actions_registration + registration_only,
with a private random queue namespace retained in persisted grouping metadata.
No token or token hash is retained or exposed. Grouping confers no authorization.

Fingerprint the complete canonical request plus server context and independently
computed taint, even when the judge is off. Invalid/noncanonical semantics opt
out; JSON NaN/Infinity, malformed tool/args/agent/summary/risk values cannot group.
Every request still creates its own id/item/event. Private metadata holds the
fingerprint and random group/snapshot identities outside public action objects.

GET actions and pending retains the complete legacy actions array. Only when
multiple pending eligible members exist, add groups with random opaque id,
leader_id, count, member_ids, and random snapshot token. Parent renders one card
per group. Approval and individual rejection continue to affect only their own
row; the next oldest pending member becomes leader. No approval fanout.

POST /api/actions/groups/{group_id}/reject is admin guarded and requires an exact
snapshot token and member_ids. Under the queue lock, compare the complete pending
membership and token, reject all or none, persist once, then wake each waiter and
clear each advisory pending marker. Include optional normalized human reason in
existing per-item decision audit records. Membership addition, settlement or expiry
rotates the opaque snapshot token. Stale request returns conflict with no mutation.
H659 replay/reservation remains before queue request/context creation.

## Verification

RED then GREEN focused tests cover actual owner route production of two rows/one
group; direct/user/authority-claim opt-out; complete semantics and taint isolation;
queue namespace separation and persistence/restart; private metadata exclusion;
once approval and remaining follower; explicit atomic rejection/reason/waiter
wake-up; stale additions/decisions/expiry; concurrent reject vs decision; H659
replay without extra row/group member. Run existing action/H277/H659 regressions,
lint and diff checks. Existing JsonStore is a single-process store; do not claim
cross-process transaction protection. Durable task deadlines are outside H487.
