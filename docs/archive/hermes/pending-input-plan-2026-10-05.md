# H067 pending input implementation plan

Goal: all697 pinned Hermes capabilities; implement the original H067 clarify,
three-way confirmation, destructive-command confirmation and ephemeral notices.
Generated2026-10-05; base/head a7ffad6676cfb28e7ac374d495b4a5889e5f4646.
Preserve inherited dirty work. No stage, commit, push, merge, deployment, live
provider activation or new paid service. Previous H063 milestone is complete
locally, with23,680 backend passes and1,912 serial frontend passes; this plan
does not reinterpret that dated snapshot as H067 acceptance.

## Design and source

Reference59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e (MIT):
tools/clarify_gateway.py, tools/clarify_tool.py, tools/slash_confirm.py,
gateway/run_inbound.py, gateway/run_busy.py, gateway/platforms/base.py.
Keep donor numeric/label/multi-select/Other/free-text semantics and first-writer
resolution. Adapt its blocking thread events to Nerva's async runtime rather
than adding a worker thread per prompt. State is per orchestrator, ephemeral
across restart, bounded and cancelled on shutdown; no persisted answer bodies.

Pending identity is(channel,stable_route,verified_sender). The route includes
forum/thread identity even when the model context is intentionally shared.
Pairing and origin/principal binding still run before interception. Observed
group messages never answer a pending prompt. Intercept matching replies before
answering-turn leases so a model waiting on clarification can actually resume.
Clarify has FIFO entries per identity; confirmation supersedes only confirmation.
Unrelated slash commands fall through; invalid selections retain the prompt;
unmatched prose cancels a native-choice prompt and proceeds as a new message.
Confirmation recognizes once/always/cancel, command aliases and bang prefixes.

Do not copy Hermes's ungoverned boolean opt-out. Add the narrowly named
session_command permission surface using a64-hex canonical identity digest.
Only an always grant disables future destructive-session prompts. It must be
requested as permission.grant and applied through the existing approved-task
executor; no direct grant insert or fake human task. The new consumer checks
actual grants even when the legacy ledger feature flag is off. Existing callers
keep their flag-off compatibility. A failed grant never promises permanence;
once may still execute the confirmed command and Cancel changes no conversation.
Native owner decisions require current owner identity, exact live prompt token,
revision and pairing; stale/replayed/cross-topic callbacks do nothing.

Before explicit/new/reset/undo context changes, capture the original command
and session generation in a confirm, then recheck both on resolution. Scheduled
idle/daily reset behavior remains H063's accepted opt-in contract. A restarted
gateway cannot resurrect an old in-memory confirm. Existing signed kernel and
reusable terminal consent paths remain the authority for privileged effects.

EphemeralReply is a str-compatible notice with optional TTL. Default TTL0
matches Hermes (disabled). Only exact successfully sent bot-owned messages may
be removed, on transports supporting deletion; others retain the notice.
Deletion tasks are bounded, owned and closed before transports. A deletion
failure is not a successful delete. Notices bypass conversation-memory append.

## Interfaces and single writers

Implementer1(Sol High) owns NEW agents/core/channels/pending_input.py and
tests/test_pending_input.py. Export PendingKey=tuple[str,str,str],
parse_confirmation(text)->str|None; parse_clarify(text,choices,multi_select=False,
awaiting_text=False)->ParseResult(status,value). ParseResult statuses resolved,
invalid_selection,prose,fallthrough; value str|list[str]|None.
PendingInputs(clock=monotonic,max_pending=4096): register_clarify(key,question,
choices=None,multi_select=False,timeout_seconds=3600)->Prompt;
register_confirmation(key,command,question,timeout_seconds=300)->Prompt;
pending(key,kind=None)->Prompt|None; intercept(key,text)->Resolution;
resolve(prompt_id,key,value)->bool; mark_other(prompt_id,key)->bool;
async wait(prompt)->Answer|None; cancel(key)->int; close()->int.
Integration review adds cancel_prompt(prompt_id,key)->bool to retire exactly one
undelivered/cancelled prompt even if its waiter task has not started; neighbours
must remain intact. Tool results strip the Recommended presentation suffix.
Prompt carries id,key,kind,question,choices,multi_select,awaiting_text,command
and deadline; Answer carries value and optional choice; Resolution carries
status(no_pending,consumed,retry,fallthrough),prompt_id and optional answer.
Futures stay private. No callback executes an effect inside this pure module.

Implementer2(Sol High) owns only agents/core/permission_ledger.py and NEW
tests/test_session_command_permission.py. Append session_command to SURFACES;
normalize_key accepts exactly64 lowercase hex characters for this surface.
PERMISSION_GRANT_CONTRACT permits only always scope for session_command.
Add check_required(surface,key,now=None)->allow|ask|deny through the same
fingerprint,never,boot and consumption rules, regardless of enabled flag.
Existing check retains exact flag-off behavior. Existing request/apply_grant
remain the only widening path. No coordinator/queue/kernel edits by this agent.

Coordinator owns existing orchestrator/adapters/commands/runtime registrations,
NEW pending_input_runtime.py and ephemeral.py plus integration tests. Native
cards, typed gateway resolution, model clarify producer, persistent opt-out,
ephemeral delivery and verified human-wait credit are integration work, not
claims earned by the pure modules. No implementer delegation or shared writers.

Ephemeral integration contract: `EphemeralReply(text, ttl_seconds=None)` preserves
the str interface and validates an optional nonnegative integer TTL. None reads
display.ephemeral_system_ttl, default0; malformed configuration disables deletion.
`EphemeralDeletes(max_pending=1024, sleep=asyncio.sleep)` owns bounded tasks;
schedule(ttl_seconds, delete_coroutine_factory) returns scheduling acceptance only,
not deletion success. Positive TTL waits at least1second as in the reference.
aclose(timeout=2) closes admission, cancels owned tasks and returns whether all
terminated within the budget, retaining ownership of cancellation-resistant tasks.
Telegram schedules per successfully acknowledged chunk (including plain fallback)
with exact returned bot-message IDs; ephemeral notices never consume voice marks.
The legacy ordinary-message delivery branch is unchanged.
Review correction: a delete already in flight can resist cancellation. The tracker
retains ownership, reports an incomplete drain, and separately counts late outcomes
as abandoned rather than successful deletions; Telegram logs that incomplete drain
before closing its transport. A request sent before shutdown may still finish at
the remote server; bounded shutdown is not a claim of forcibly stopping remote IO.

Verified gap: there is no conversation `/undo`; existing `/rollback` also restores
files and must not be reused as the command. Add NEW memory/session_undo.py and
tests/test_session_undo.py under the second implementer's exclusive ownership.
`undo_last_exchange(memory, session_id, expected_clock)` reuses the existing
prepare_rollback_rewind/commit_rollback_rewind/discard_rollback_rewind durable
conversation primitives only, removes the last user exchange, never restores a
file checkpoint and releases an unused ticket on failure/cancellation. The caller
must hold the real session lease, recheck generation and verified owner authority,
and intercept `/undo` before appending it. Root owns that command integration.

First runtime integration step: opt-in channels.pending_inputs_enabled (default
false until the complete channel contract is integrated) installs the model's
clarify ToolRPC producer. A request-local binding closes with its original turn;
typed replies enter through the existing Gateway and are intercepted before
session leases. Actual delivery, current pairing and a live exact prompt are
required for native human-wait credit. Pairing loss or shutdown cancels the wait.
This step initially supports direct Telegram prompt delivery; workspace governed
delivery, native cards, poll-lane bypass and destructive commands remain explicit
integration tasks. Do not credit H067 on this intermediate step.

## Tasks and verification

- [ ] Adapt parser/state with regressions for numbers, labels, recommendation
  suffix, comma/space multi-select, free text/Other, invalid retry and slash
  fallthrough; timeout/duplicate/FIFO/supersession/cancel/shutdown/capacity cases.
- [ ] Verify actual permission.grant request, human-approved executor apply,
  restart permanence, revocation, invalid scope/key, never denial and flag-off
  default-ask for the new consumer. Existing permission tests must remain green.
- [ ] Wire typed replies before leases and register the actual model clarify
  producer; test a real waiting model turn, owner/topic isolation, pairing loss,
  invalid retries, delivery failure, timeout and shutdown. Human credit requires
  an actual delivered prompt; queued output alone earns no credit.
- [ ] Wire destructive command once/always/cancel, live generation recheck,
  persistent governed opt-out and native Telegram/Slack/Discord callbacks with
  typed fallbacks elsewhere. Test the existing real kernel/queue paths.
- [ ] Integrate ephemeral notices, TTL/delete ownership and transport shutdown;
  preserve topic and governed workspace output. Record unsupported deletion.
- [ ] Run focused/affected tests after each step, scoped Ruff/Bandit/strict scan,
  explicitly refreshed local Graft and metadata/count/doc gates. Run frozen
  backend and serial frontend once the integrated contract reaches acceptance.
- [ ] Credit H067 only after all original requirements have behavior evidence.
  Preserve partial gaps and stale unrelated pins; never globally restamp.

Rollback: use preserved dirty preimages under /tmp/nerva-h067-baseline-20261005
for manual localized reverse diffs. Do not restore whole files over inherited
work. New stores/prompt state have no private history import or external service.
Next action: implement pure pending state and governed opt-out in parallel,
then integrate exact gateway/transport/kernel bindings and verify end to end.

## Polling and rate ingress follow-up (2026-10-05)

Root coordinator owns gateway.py, telegram.py, orchestrator.py, web.py and
tests/test_pending_input_ingress.py. Add an explicitly wired pending-only gateway
hook and Telegram transport hook. The hook cannot start a model turn. It checks
fresh pairing and binds the channel origin/principal before exact delivered-prompt
resolution. A consumed reply bypasses model-message rate and chat lanes; unmatched
input retains ordinary rate/batching/order. Edited, forwarded and attachment input
never enter this path. Group policy still runs before it; observed/dropped messages
cannot resolve. Shutdown/default-off/detached bindings cannot resolve.

Acceptance: reproduce the real polling/lane deadlock and saturated shared rate
before the fix; then verify two polling pages resume the exact ToolRPC waiter,
invalid retry remains out of the model and batching, unrelated sender/topic and
revoked pairing cannot answer, and normal/observed traffic retains its policies.
No native-card or destructive-command completion credit in this follow-up.
Rollback uses localized reverse diffs against the ingress preimages in /tmp;
no restore, stage, publication or changes to provider credentials.

## Native cards and destructive command integration (2026-10-05)

Full697 objective unchanged. Root owns existing runtime, Telegram, lifecycle,
orchestrator/web wiring and integration tests. Two Sol High implementers do not
delegate and own disjoint new modules/tests:
1. pending_input_cards.py: NativePromptCards(inputs, eligible). register(prompt)
returns CardOffer(token,prompt_id,markup); bind(token,chat_id,message_id,thread_id=None)
accepts exact successful bot-message receipt. handle(callback) returns CardResult
(applied,status,prompt_id,markup). discard(token), close(). Random bounded tokens,
revision fencing, fresh sender/chat/topic/eligibility before mutations, choices,
Other, multi-select toggle/Submit, once/always/cancel. No network or effect execution.
2. session_command_consent.py: SessionCommandConsent(ledger,govern_enqueue).
check(key,command)->allow|ask|deny; request_always(key,command,requested_by)->taskid.
Canonical digest includes verified pending identity plus normalized reset/undo
operation; no plaintext command in the selector. Only ledger.check_required and
ledger.request, never apply_grant/direct insert/synthetic production tasks.
Tests must use real governed worker intake, real queue human decision and approved
executor for persistence/revoke; no SimpleNamespace human-task substitute.

Root will add a strict-ack Telegram card send returning the exact final message ID,
wire callbacks outside chat lanes with origin/principal and fresh pairing, bind
only acknowledged cards, and retire offers after finish/timeout/shutdown.
Destructive commands capture source/base/generation/actual session and clock
before prompting, release leases while awaiting human input, recheck owner/
pairing/generation/memory clock under base+actual session leases before effects.
The command itself never enters model/history. Cancel/no-delivery/expired/replay
changes no conversation. Reset prepares memory before route rotation; undo uses
existing durable rewind. Always requests a real governed permission task and
clearly says permanence remains pending until that task is approved/executed;
confirmed once may proceed when that request fails, with no permanence promise.
TTL0/default-off preview retained while other channels/CLI/HUD remain unfinished.

Focused RED/GREEN tests per step, integrated authority/lifecycle/RPC checks after
merge of disjoint work, local source/security scans, truthful partial records.
Rollback localized reverse diffs against native-command preimages; no publication.

### Native transport integration checkpoint scope

Root also owns channels/manager.py and channels/gateway.py for the existing
send-contract gate and pending-only callback admission. Immediate preimages are
kept in /tmp/nerva-h067-native-transport-baseline-20261005; no inherited source
is reset. Native send requires positive exact integer Bot API receipts and
plain UTF-16-safe final-part keyboard placement; callback tasks are bounded and
drained before transport shutdown. Transport generation fences old native cards.
Other instructions use the existing gated ephemeral text send. This checkpoint
will keep H067 partial and will not claim Slack/Discord/CLI/HUD parity or fresh
full suites/H277 mutations. Native transport tests use local MockTransport and
actual channel/gateway/RPC implementations, with a synthetic model.

Review correction: undo forwards an optional synchronous authorize guard into
MemoryManager.commit_rollback_rewind; it runs after both async memory locks and
before writes, outside the checkpoint non-reentrant lock. Existing callers that
omit the guard retain their previous API behavior. The second conversation fence
pins the real conversation instance/revision because compaction clock revisions
do not advance on every ordinary turn. New append/rewind during human waiting
therefore invalidates the old command request. Safe-mode numeric inventory now
explicitly reviews display.ephemeral_system_ttl as notice retention (TTL0 for
pending prompts), without changing authority budgets or durable audit retention.
One deferred UI minor: if both Other keyboard editing and the instruction send
fail, callback acknowledgement still says Applied while typed answers remain usable.

## Persisted undo, signed consent and workspace transport continuation

Goal all697, base/head a7ffad6676cfb28e7ac374d495b4a5889e5f4646, local-only.
Previous native checkpoint delivered2394 affected +195 metadata passes; no
blocking condition. This continuation owns cold-start command history resume
(runtime + existing tests) through one Sol High implementer, and physical signed
kernel consent acceptance in a disjoint new test module through a second Sol
High implementer. No child delegation. Root owns shared modules and review.

Before snapshot/prompt, a persisted cold transcript must be resumed without
creating or erasing absent/corrupt history. Capture/revalidate route and owner
across resume awaits, preserve shared and topic identity, and test cancellation
against real persisted bytes. Signed consent must use actual coordinator/queue/
physical enforce-mode kernel/registered executor; no fabricated human tasks.

Root investigates native workspace delivery through the existing governed
channel.reply path. Slack/Discord cannot gain generic direct-send access. Native
prompts need exact verified outbound receipts before callback binding or human
wait credit, with fresh inbound owner/sender/topic checks. Extend existing
transport seams locally only after tests reproduce any missing behavior.
Rollback uses external immediate preimages and localized diffs; no staging,
commit, push, merge, deploy or paid/live-provider activation. Source freezes and
focused tests per implementation, integrated checks at a coherent milestone.


## Governed workspace native clarification continuation

Goal: all697 pinned Hermes capabilities; H067 remains partial until all producers and acceptance cases are integrated. Base/head a7ffad6676cfb28e7ac374d495b4a5889e5f4646; local only, generation2026-10-05. Previous turn is verified progress: persisted cold-start undo and physical signed permanent consent,419 integration plus195 metadata cases.

Plan before code: retain generic direct-send denial for Slack/Discord; queue canonical native prompts through existing channel.reply intake. Keep an in-process delivery waiter bound to the exact approved payload, inbound message and active prompt. A strict final bot-message receipt is necessary before button binding or human-wait credit; no approval-pending credit. Reject expired/cancelled/edited/restarted requests and recheck pairing, sender, target, workspace, thread and transport generation before applying answers. Native interaction updates only edit the exact delivered bot keyboard; ordinary typed answers use pending-only ingress ahead of blocked batching/model lanes.

Two SolHigh implementers own only Slack adapter plus a new Slack-native test file, and Discord adapter plus a new Discord-native test file. Root owns manager, reply broker, pure cards, pending runtime, gateway/orchestrator/web wiring and cross-component integration tests. No child delegation. Shared adapter API: send_pending_card(message,reply_markup=canonical_inline_keyboard,**trusted_target) returns None or dict with channel,target,message_id,thread_id,team_id; all IDs strings, optional values None. Callback hook receives that receipt shape plus verified sender and data; send receipt channel is slack/discord, Slack sender is team:user, Discord sender is decimal ID. pending_reply_handler is pending-only, pending_callback_handler never starts a model turn. _pending_callback_generation changes at stop/start. discard_pending_card(receipt) does local keyboard/view cleanup only.

Tests: adapter RED/GREEN, then real inbox/coordinator/kernel/queue/worker/approved-delivery/RPC tests with actual SDK response/view classes and local synthetic transports. Wrong receipt/workspace/user/thread, replay, stale revisions/generation, timeout/cancel/restart/revocation and edited queued payload refuse effects and wait credit. Existing Telegram and ordinary workspace reply tests must remain green. Scoped source/security and evidence checks after freeze; full backend/frontend and H277 original49 remain milestone requirements. Rollback: narrow diffs from /tmp/nerva-h067-workspace-native-baseline-20261005, preserve inherited changes; do not stage, commit, push, merge or deploy.

## Completion batch — 2026-10-05

Plan before source edits. Retain the pinned gateway H067 contract: pending
clarification, three-way confirmation, reset/undo persistent consent, ephemeral
notices. CLI/HUD enhancements are separate capability contracts, not extra gates
added to this gateway row. Live account probes are labelled separately.
1. Extend existing SessionCommandRuntime to governed Slack/Discord native
confirmation using exact explicit channels.owner_senders and current pairing.
No paired-user implicit admin, no direct workspace-send bypass. Reuse real
queue/kernel and durable memory fixtures for cancel/once/always and revocation.
2. Recreate closed pending runtime on same-instance restart; re-register clarify
handler when needed, ensuring retired requests cannot gain authority.
3. Preserve ephemeral metadata across durable workspace reply intake and extend
owned best-effort deletion in supported transports, with failure/shutdown tests.
Root owns localized pending runtime, session commands, orchestrator wiring,
channel reply, Slack/Discord output and focused completion tests. Source preimages
are external under /tmp/nerva-h067-completion-baseline-20261005. Test affected
modules once, then integrated milestone; never soften kernel envelopes or credit
full H067 before all pinned behavior has a witness. No publication.

Completion addition: copy donor clarify_tool pure choice normalization and batch validation; adapt its legacy per-question callback loop to awaited gateway prompts. Prevalidate the full batch before any send, preserve answered questions on timeout and label delivery failures. No new UI subsystem.

Completion checkpoint: workspace three-way confirmations, explicit paired owner identities, copied batch protocol, signed ephemeral TTL and transport-owned deletion, restart and Other fallback are implemented. Integration1277 passed; final Telegram transport probes passed separately. H067 stays partial for larger signed-content references and other producers. No publication.

## Large signed prompts (local continuation 2026-10-05)

Problem: native questions allow80,000 characters and25 button labels, while
mediation deliberately permits16,384 characters per string and65,536 bytes.
Keep those global bounds. For oversized prompts only, store canonical UTF-8
text and packed buttons on the existing ephemeral delivery entry; sign their
SHA256, byte length and a1,024-character preview in the durable task. Both
content and the exact inbound/task binding must remain live at execution.
No file lookup, disk persistence, replay after restart or alternate executor.
Bound a single blob to2MiB and aggregate live reference content to32MiB.

Expose complete live content through the existing admin-only task preview and
render text plus all labels safely in Decision Inbox. Lost/expired bindings
show unavailable; approval cannot revive them. Short prompt wire format stays
unchanged. Preserve all inherited edits using new external preimages.

Steps: write failing physical queue/kernel and owner-preview tests; implement
the conditional reference and strict hydration; test tamper/cancel/restart and
Unicode byte bounds; verify HUD rendering plus build; run affected suites once,
record exact inputs, refresh only affected H067 pins and rebuild local Graft.
This closes the large-prompt gap, not all remaining H067 producers or697 parity.

## Typed ntfy producer and ingress continuation

Observed blocker: the subscription awaits the full model turn, preventing it
from reading the next answer while clarify waits. Reuse the existing Slack-style
serial dispatch pattern: one bounded128-item queue and dispatcher, with the
existing pending-only gateway hook before enqueue. Unconfigured hook preserves
legacy synchronous behavior. Stop cancels both owned lanes; queued metadata
is fenced to the subscription context. No per-message unbounded tasks.

Add a strict text-only prompt variant on the existing channel.reply task, only
for ntfy initially. Exact inbound/topic/configuration, live prompt and current
canonical content remain required. The existing HTTP guard rechecks the live
prompt after DNS/policy waits and before each chunk. Successful delivery means
all HTTP chunks accepted, not a native button receipt. Reuse large-content
digest binding and protected full preview; no new store or bypass executor.

Extend existing runtime typed interception and reset/undo confirmation to ntfy.
Only explicitly configured owner_senders plus current pairing authorize history
changes; the topic is the adapter-established identity, never event sender/title.
Recheck configuration, transport generation, consent and conversation head
before effects. Ephemeral notices on ntfy remain visible because it cannot delete.

Write failing synthetic actual-stream/model/queue/HTTP tests first; implement
locally, test typed choices/free text, signed approval, invalid retry, revoke,
restart, bounded ingress and once/always/cancel. Run affected tests once after
corrections. Preserve prior code and evidence; remain local, no publication.
Other typed producers (HUD/web/email/CLI) stay explicit until integrated.

Review correction: a topic name alone is not globally unique. A failing real
Always/grant/executor regression showed a new ntfy server inheriting the old
server's history opt-out. Bind only ntfy consent selectors to URL, receive
topic and publish topic; preserve the previous selectors for other channels.
Exclude random transport epoch and token so consent survives restarts and
credential rotation. Recheck the live original configuration before effects.

Donor fidelity correction: gateway/platforms/base.py send_clarify marks a
non-native numbered prompt for typed capture. tools/clarify_gateway.py maps
valid choices first, then accepts the user's own answer. A real-stream failing
probe exposed a deadlock when unfamiliar prose waited behind its own blocked
model. Apply the donor fallback only to ntfy text prompts, keeping native
choice retry/new-prose semantics unchanged and retaining Nerva answer bounds.
This replaces the newly written ntfy numeric-retry expectation with the actual
pinned donor contract; existing native retry tests remain.

## Explicit clarification cancellation at occupied ingress

Observed: parse_clarify deliberately lets slash/bang commands fall through; the
serial Telegram/Slack/ntfy dispatcher cannot process /cancel while its current
model awaits clarify. Reuse the existing exact-prompt cancel operation for only
/cancel and !cancel (case-insensitive whole text), after the delivered prompt,
identity, pairing, active binding and native generation checks. Consume this
existing-wait action without a new model turn or rate debit. Ordinary prose,
unknown commands and invalid selection retries keep their existing contracts.
A choice actually named Cancel remains selectable through its label/number.

RED: real gateway/RPC and native SDK/ntfy stream probes must demonstrate the
blocked cancel. GREEN: exact cancellation returns the tool's existing cancelled
result, retires its card through current cleanup, and leaves FIFO neighbours and
other senders/topics untouched. No transport rewrite or new store. Run the
affected pending-input suite after this localized step; keep H067 partial.

## Authenticated HUD stream clarification

Goal: reuse ChannelPendingRuntime/PendingInputs, donor normalization and native
human-wait accounting in the actual /chat/stream runner. Add a trusted HTTP
binding carrying a server-derived credential/role fingerprint, session and live
auth callback; client_id or payload identity never grants authority. Emit clarify
SSE with a random prompt ID and bounded question/choices. A separate user-guarded
router accepts validated answer/Other/multiselect/cancel for the exact live prompt
and same currently authorized actor, without acquiring the model's turn lease.
A generator acknowledgement after yielding gates delivered state/credit.
Disconnect, expiry, disabled setting and revoked credentials retire the wait.

HUD consumes the event, offers native choice/multiselect plus Other/free-text
and cancel, posts through the existing same-origin credential client, preserves
the question on rejected/failed submissions and never starts another model turn.
Use existing theme variables and one component; retain Stop/disconnect behavior.
Tests: actual stream/ToolRPC plus real guarded HTTP answers, actor/expiry/revoke/
disconnect and invalid-selection isolation; real App streaming and answer UI;
route/OpenAPI guards, affected channel regressions, typecheck and HUD build.
Non-goals for this slice: email/CLI, nonstream HTTP producer, busy prose routing.
Rollback: restore only this slice from external immediate source preimages;
never discard inherited dirty work. No new dependency, publication or paid API.

## Nonstream HTTP producer/discovery
Reuse the trusted HTTP binding for POST /chat. Put an unacknowledged poll offer
in the existing offered map and hold its private future until a user-guarded
GET /chat/pending response is sent. Discovery filters the same live actor and
optional session; bounded pagination exposes no other credentials' questions.
Response-background acknowledgement precedes delivered state/credit and answers.
The existing answer route/parser resumes the same model. Expiry/auth loss before
poll cannot wedge delivery. Owned request-disconnect watcher and finally cleanup
retire the producer; no new persistent store or alternate model path.
RED actual concurrent POST/poll/answer tests first, then focused and affected
HTTP/native regressions, API/typegen/doc gates, frozen manifests and explicit
Graft refresh. No frontend behavior/dependency change, publication or full-parity
claim. CLI/email and busy prose remain separate unfinished work.
