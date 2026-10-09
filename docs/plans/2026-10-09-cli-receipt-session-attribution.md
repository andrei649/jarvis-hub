# CLI receipt distinguishes requested and observed session

- Generated: 2026-10-09 UTC.
- Base / HEAD before edits: 17712e196ec540c0ba8c75114e11b7692e61078d.
- Branch/worktree: codex/cli-receipt-session-attribution-20261009,
  /workspace/jarvis-hub-cli-receipt-session.
- Goal: record the session actually returned by POST /chat without presenting
  request intent as confirmed execution metadata.
- Scope: autonomous LOCAL CLI/receipt work; no publication or live providers.
- Next action: local receipt unit verified; retain broader H002 outcome/usage
  gaps and continue separately scoped software work.

## Receipt contract

POST /chat already returns the selected session_id, including after /new. The
CLI's finish closure currently ignores it and copies --session into session_id.
Use receipt-local observed_session_id initialized to None. Only a decoded normal
POST /chat response dict may populate it, and only from a nonempty string whose
entire value matches ASCII letters/digits/underscore/hyphen, at most 128 chars.
Preserve the value exactly: no trimming, coercion, inference or requested-ID
fallback. Use a stdlib fullmatch, keeping startup lightweight. The intended
shared ID alphabet/length is documented in core/validation.py; its current
match-with-dollar also accepts a final newline, which this receipt must reject.
Do not expand this unit into changing the shared validator or all route callers.

Set receipt session_id to that observed value. Add requested_session_id to
nerva.chat.usage.v1 with the previous caller-echo value (explicit --session or
None) on every receipt. This preserves request correlation and makes the intent/
observation distinction explicit. The existing session_id type remains nullable
string; document its corrected meaning and the additive request field. No data
migration. An older or malformed hub response has unknown actual session, even
when an ID was requested; retain that intent only in requested_session_id.

Capture a valid returned session for answered, refused, empty or queued chat
responses: outcome and session attribution are separate. Keep session_id None
for pre-request usage errors, authentication/HTTP/no-hub errors, interruption
without a decoded response and vision calls (which use another endpoint). Vision
still refuses --session as before. Interactive output/JSON and exit behavior,
one-shot classification, pending approvals, request bodies and number of calls
stay unchanged. Nothing resumes or creates another session from the receipt.
All usage/cost fields retain their current unavailable values.

## Ownership and verification

- auth_audit (gpt-6-sol/high): agents/cli/nerva.py and
  tests/test_nerva_oneshot.py. RED missing/requested-vs-returned IDs through actual
  cmd_chat plus persisted receipt before code. Test requested correlation when no
  response; success/refusal/queued and interactive cases; invalid/missing/nonstring/
  empty/too-long/path/whitespace IDs incl final newline; valid128boundary.
- mobile_session_transport (gpt-6-sol/high): independent frozen code/test review
  and existing/new vision receipt coverage in tests/test_nerva_chat_image.py only
  if useful. Coordinate source freeze before running shared integration; no
  overlapping writes. Server returned-ID behavior already has test_chat_http.py.
- wall_contracts (gpt-6-luna/medium): read-only affected-pin/current-coordinate
  inventory. Root owns plan/proof/README or CLI docs, metadata, claim review,
  integration and git. Max4active including root; no nested delegation.

Run all one-shot/CLI/send/image/import suites and relevant chat HTTP/approval
transport coverage plus stdlib help launch. Use meaningful RED/GREEN, exact
source hashes and canonical collected counts. Broaden only for a concrete
concern; preserve prior full-backend/client evidence without relabeling it.
Refresh only previously-current pins after named review, leave preexisting stale
pins, and keep H002 partial for the independent outcome/usage gaps.

Rollback receipt capture, additive field, tests and documentation together. No
HTTP schema, server session selection, credentials, billing or authority change.

## Completed evidence

The writer's selected receipt cases were RED 21/21; the independent vision
writer's two affected cases were RED 2/2. Frozen CLI/HTTP union: 297 passed and
one gated live-import skip, 298 total in 5.420 seconds. Root's disjoint producer/
approval/image-retry union: 38/38 in 2.157 seconds. Combined: 336 distinct cases,
335 passed and one skipped, zero failures/errors. All 76 one-shot and 31 vision
cases pass. No live import/model/provider was enabled.

Independent review found no Critical/Important issue. Root AST verification
confirms only _usage_report and cmd_chat change; 77 other top-level functions/
classes and all remaining module statements are identical. Ruff, whitespace and
site-packages-disabled CLI help checks pass. This narrow receipt delta is covered
by the relevant CLI and HTTP suites; prior full-backend/client evidence is kept
with its prior source SHA and is not reported as a new run.

Canonical collection: 21,300 backend (+22), 2,009 frontend/native and 306 mobile
cases; 555 routes. Hermes and generated-status checks pass. Named reviews support
20 current pin refreshes plus the new public receipt-guide pin; 35 previously
stale pins remain stale. H002/H586 test counts and H586 coordinates are updated;
only H002's receipt claim/remaining scope changes semantically. All statuses and
other claims are retained. docs/cli-chat-receipts.md documents historical v1
caller echoes versus new observed/requested fields; HERMES_SPRINT gains a dated
follow-up without rewriting old run counts. Integration details and tested
source hashes are in docs/project-cli-receipt-session-20261009.md.
