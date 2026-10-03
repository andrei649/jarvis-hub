# H487 Telegram reusable consent implementation plan

> Agentic execution: subagent-driven-development, two Sol High implementers;
> root owns shared integration and review. No child delegation.

Generated: 2026-10-04. Goal: all697 pinned Hermes capabilities, not only H487.
Base/head at start:42840e3d409449cb1382417c8e88999fdd14ed26.
Terminal milestone is locally committed; full22210 run had six collateral
failures, corrected with52 focused passes and90 final record/route gates.
A fresh full run is required at the next frozen integrated milestone.

## Design and boundaries

Extend the existing terminal approval path with the pinned Hermes choices
session/always/deny. The global authenticated Telegram owner can decide a
web-origin offer; its grant remains scoped to the captured request principal,
surface, session, reviewed registration, policy and target. Never manufacture a
web principal from a Telegram callback. Owner authority is current transport
state, not model payload or callback data. Local edits only, no runtime activation,
remote publication, real process/device effects or provider spend.

A separate bounded ConsentPrompts registry binds random32hex callback nonces,
exact task birth/offer revision/member set, verified native message ID, channel
instance/generation/hook identity and expiry. Use autc:nonce:s|a|d, never ordinary
aut or owner-once aut1. Reusable callbacks bypass an occupied originating chat
lane in a separate bounded32 lane; stale, replayed and overflowing reserved
callbacks are acknowledged promptly without entering that blocked lane.
Persist the decision before success acknowledgment. Failed send, changed owner,
channel replacement, stopped poller, deadline expiry or stale offer cannot grant.

Source and decider are distinct. A server-only authority minted from actual
Bot API user/chat IDs and a registry-bound current predicate permits cross-surface
owner decisions. Its recorded decider key is canonical ['telegram',user,chat].
It is an in-process trusted boundary, not a Python object sandbox. Existing web
actors and same-origin legacy actors retain their validated semantics. For new
attributed Telegram grants, a strict version2 signed ledger decision and task
proof bind the real decider; version1 existing records remain verifiable without
silent upgrade. Denials retain ordinary durable human attribution and create no
execution/grant proof; do not claim cryptographic denial audit from that row.

## Interfaces and ownership

A owns autonomy/consent_types.py, consent_authority.py(new), consent_ledger.py,
queue.py and test_h487_telegram_consent_authority.py(new). Interface:
make_telegram_consent_actor(*,user_id:int,chat_id:int,current:Callable[[],bool])
-> OwnerConsentActor|None in consent_authority.py. Reject bool/noninteger IDs,
nonpositive user and zero chat; bind actual event key and live issuer identity.
Queue checks that exact issued authority plus actor/current before granting and
for every member. Preserve captured grant context and all current proof/receipt
checks. Add optional signed decider metadata without changing grant identity,
head namespace/version or accepting unsupported signed schema versions.

B owns autonomy/inbox.py, consent_prompts.py(new), channels/telegram.py and
new test_h487_telegram_consent_prompts.py/test_h487_telegram_consent_transport.py.
ConsentPrompts(coordinator) supports install(channel), register_invocation(id,
check=...), reply_available(id), release_invocation(id), request(id,check=...)
-> committed result|None, notify(task,channel,chat_id)->bool, pending(callback),
async callback(nonce,choice,*,chat_id,user_id,message_id), stop(generation).
Stable hooks consent_pending/on_consent_callback/on_consent_stop. Capture real
OwnerReplySource and ApprovalTurnContext synchronously at terminal intake for
same-chat request/wait; unsolicited owner inbox cards use current coordinator,
worker/queue/channel identity and actual callback owner auth, not a fake turn.
Verified send_consent_card may delegate existing multipart verified send logic;
last part contains command remainder, member count and choices. Old revisions
must refuse without adopting new followers; a fresh card can refresh with a new
nonce. Registry locks never enclose queue transactions or network awaits.

Root owns coordinator.py, terminal_review.py, worker.py as needed, literal AST
binding inventory, real registered-producer integration tests, plans/evidence/
BACKLOG, parity and generated status. Wire registry before intake and retain hooks
across harmless wire(); stop old registry on actual lifecycle replacement.
Ordinary notifier uses consent card for a fresh offer and preserves ordinary
cards otherwise. Join bounded prompt waiting even when Smart judge is absent;
a Smart DENY only uses existing explicit owner-once path and can never be
changed to a reusable grant. Once committed, actual worker tick executes through
the existing private physical proof path; verify durable result, not a button.

## RED/GREEN tasks

1. A: real web-origin terminal source + truthful Telegram actor fails before
extension, then grants captured web scope; next web request reuses, Telegram
source does not. Wrong event/issuer/current owner, forged principal, per-member
revocation, modified signed decider/human metadata and unsupported versions
refuse. Existing consent ledger/queue/source/physical tests remain green.
2. B: strict parser/card and real MockTransport Bot API receipt tests fail before
implementation. Same-chat occupied lane must receive its consent callback.
Missing/false receipt, wrong sender/chat/message, revoked owner, hook/generation
changes, expiry/cancellation, replay/races and32-cap refuse without blocking.
Ordinary callbacks, owner-once and reason lanes retain their semantics.
3. Root: real registered tool RPC + live owner Telegram scope and mocked Bot API,
mediation off/enforce, all three choices, actual dispatch effect mocked. Web-origin
notification decided by actual owner preserves scope. Future matching requests
reuse with no fake human record. Identical followers settle their own receipts;
stale card refuses and fresh card shows current count. Smart DENY never offers
reusable controls. Refresh AST coordinates, run full owner/consent/Telegram suites.
4. Source-review changed collateral capability claims; run route/doc/status,
Ruff and actual CI-scope Bandit/gitleaks. Update truthful partial H487 record,
collect actual test counts, freeze source, then run full backend serially.
No live acceptance claim or equivalent credit until all H487 requirements close.

Review focus: stale callback while sender HTTP receipt is unresolved; await
holding occupied chat lane; changed followers/revision; exact signed decider
version migration; native deny isolation. Each is owned above. Rollback is this
coherent diff atop42840e3d; preserve task/chat history and external anchors.

## Task5 — native CLI owner choices

After A finishes, a second Sol High implementer owns agents/cli/nerva.py,
tests/test_nerva_cli.py (only expected command-tree addition), and new
 tests/test_h487_consent_cli.py. Root owns the existing GET/autonomy/approvals
projection so list returns the same bounded consent_offer as HUD tasks.

Add `nerva approvals consent <positive-id> --choice session|always|deny
--revision <64 lowercase hex> [--reason <=280] [--json]` using the existing
HubClient and POST/autonomy/tasks/{id}/consent. Require an explicit revision;
never silently fetch a new revision and substitute it into a previous choice.
Validate ID/revision/reason before sending; no --payload, actor, principal or
source metadata. List shows valid offer revision/count/categories and copyable
command guidance, preserving ordinary task buckets and legacy decision verbs.
Malformed offer projections stay ordinary and are not shown as reusable choices.
CLI acceptance uses the existing authenticated route and never writes queue,
proof or grant directly. Native JSON result requires `ok is True` and an actual
nonempty task list; report refusal/error with existing nonzero conventions.

RED/GREEN tests cover parser/discovery, exact body/path and all3choices,
explicit/missing/malformed revision, nonpositive ID, long reason, malformed
success/error response, unauthorized/no-hub/stale409, no POST on local validation
failure, list/human output and all ordinary CLI/completion regressions. Root
adds real API list/decision coverage; no new routes or runtime activation.

## Integration checkpoint — 2026-10-04

Tasks1–3 and5 are locally implemented, uncommitted atop42840e3d. The native
Telegram implementation passed190 focused cases, including real registered
terminal dispatch, all choices, cross-surface decisions, actual model-runtime
child calls, changed followers and private receipts. CLI135 and owner API44
focused cases pass separately; these suites overlap. Ruff passes. Backend
collection refreshed to22,327; frontend/mobile source is unchanged from the
prior verified milestone (1889/142 collected cases, not fresh live evidence).

Ruling: bind registration and reply to the exact current terminal RPC task,
while retaining the actual live parent OwnerReplySource and ApprovalTurnContext.
AgentToolRuntime runs tools in gathered/owned child tasks. Requiring the parent
task itself rejected a legitimate production path; allowing arbitrary copied
context to consume a registration would transfer authority. A failing real
runtime regression demonstrated the gap before the localized registry fix.
Copied-context siblings, parent cancellation/close, request cancellation and
expiry are covered by focused regressions. This supports in-process child-task
execution on the native source event loop; it does not claim cross-loop transport.

Task4 verification is complete: collateral claims were reviewed, security and
freshness gates passed, and the corrected frozen full backend run completed
22,327 cases:22,292 passed,34 skipped and1 existing expected failure, with no
failures or errors. All2,884 frozen paths matched before recording this result.
Mobile baseline:142 tests and TypeScript pass with unchanged mobile source;
no-cache Jest was used after an initial Node SIGSEGV. These results do not
establish new mobile consent controls or live transport/device acceptance.
No additional equivalent credit is claimed. Remaining H487 scope includes other
accepted producers, mobile controls, native deadline authoring, longer explicit
human waits, legacy markerless recovery and live acceptance.
