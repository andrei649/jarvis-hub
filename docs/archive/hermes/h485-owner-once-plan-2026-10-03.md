# H485 context-bound owner-once continuation implementation plan

> For agentic workers: execute red-first, one writer per file, no child delegation. Root owns shared interfaces and integration. Full mission remains all 697 Hermes capabilities.

Goal: match pinned Hermes interactive smart-DENY once/deny behavior and unattended definitive refusal, returning actual named-worker completion in the originating invocation.
Architecture: a trusted live Telegram reply capability and exact SQLite offer bind one human reply to one current task/turn. A separate signed owner receipt authorizes one worker claim/dispatch; separate signed DONE evidence proves execution. Ordinary manual/ESCALATE and smart APPROVE behavior retain their existing paths.
Tech stack: existing Python 3.12, asyncio, SQLite, detached signer, HTTPX tests; no new dependency or paid provider.
Spec: Hermes tools/approval.py at 59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e, especially _smart_gate/_human_decision; current terminal_review.py and actual Telegram ChatLanes.
Generated: 2026-10-03T14:56:37.759544+00:00
Base/head: ee1dc146c413a09c353fc560226db0ba104545ec; codex/h277-provider-discovery-20261002; /Users/andrei649/Projects/nerva-pr-worktrees/integration.
Current milestone: owner-identity checkpoint sealed locally at ee1dc146c413a09c353fc560226db0ba104545ec; full backend terminal result21790 passed/34 skipped/one xfailed; case count21825 and frozen2806 sources match. No publication. This plan starts a separate rollback unit.

## Decisions and acceptance boundaries

- Admin identity alone is not an answerable owner channel. Mint a reply capability only inside a currently running, authenticated Telegram owner turn with live registered channel/poller/callback generation. Web admin/cron/batch and copied stale turn contexts receive definitive DENY unless an actual bidirectional transport is implemented and proved.
- A successful card response must include Telegram JSON ok:true and a positive message ID. Bind that ID, destination, owner sender and generation to the offer before accepting a response. Raw nonce is not task/model data.
- Namespace aut1:<32hex nonce>:a|r offers exactly once/reject. Only an exact registered prompt and fresh owner binding can bypass the waiting chat lane; ordinary aut: cards, guest chat and reason replies keep ordering. Track bounded fast callbacks; revoke before channel stop/drain.
- Bind one offer to task birth, exact command/target/args and mediation/intake digest, current canonical DENY, session instance, principal, originating turn, nonce and finite deadline (no later than existing approval deadline, maximum120s). No session/pattern/permanent grant.
- Off mode retains signed owner-once claim support with no B7 provenance. Enforce composes owner CAS with B7 claim/event transaction. Hold refuses execution. Missing signer/store fails closed; do not force enforce on existing off-mode users.
- A current exact smart DENY cannot be bypassed by generic accept/edit. Reject/withdrawal/timeout/no-channel settles refusal without a contradictory pending generic card. ESCALATE and ordinary manual decisions retain their established controls.
- Scheduler cannot claim owner-once rows. Only a live, server-created private permit may run that named task, once, without retries. Check current owner, turn/cancellation, registration, deadline, policy, payload and target at claim and at the actual transport dispatch boundary.
- Cancellation before dispatch revokes the permit and prevents later dispatch, including cancellation-resistant waits. After dispatch has begun, cancel transport and never claim that physical effects were undone. Separate accepted, executing and verified DONE outcomes.
- Preserve kernel e-stop/capability/budget/loop/taint, target/hardline/backend flags, trusted owner denies and local/SSH argv/cwd rules. Owner reply never bypasses these floors.
- Guardian DENY is counted once even after owner-once acceptance, matching Hermes. Do not manufacture a second count for human reject or reset via the generic accept path.
- Owner proof uses separate approval/completion purposes and result key. Actual durable DONE plus exact result-body signature is required; smart proof, unsigned human metadata or synthetic statuses cannot prove owner-once completion.

## Ownership and red-first tasks

1. Sol High A: queue/schema/exact offer/owner receipt/claim/completion primitives in agents/core/autonomy/queue.py (extract a focused adjacent helper only if it avoids unrelated rewrites), tests/test_h485_owner_once_queue.py and tests/test_h485_owner_once_completion.py. Root freezes interface signatures before delegation.
   - [ ] Red: nonce replay, wrong birth/digest/session/turn/principal, duplicate decision and expiry/edit/revoke races; real two-connection CAS where meaningful.
   - [ ] Implement exact offer/delivery/decision lifecycle and distinct signed receipts, bounded retention; off/enforce/hold matrix.
   - [ ] Red: generic smart-DENY accept/edit bypass, scheduler/forged permit, fake/tampered DONE. Preserve manual/ESCALATE and smart APPROVE tests.
2. Sol High B: pure card/parser and Telegram reply source/receipt/fast-callback lifecycle in agents/core/autonomy/inbox.py, agents/core/channels/telegram.py, tests/test_h485_owner_once_telegram.py. Root owns coordinator wiring and shared capability types.
   - [ ] Red: actual same-chat poll-loop deadlock; genuine owner nonce reply resolves while ordinary turns stay queued. Guest, wrong message ID, revoked owner and stale generation cannot bypass.
   - [ ] Implement only reserved bounded reply dispatch; HTTP200 ok:false/missing/bool message ID refuses; stop revokes and drains within existing shutdown budget.
3. Root: agents/core/autonomy/worker.py, terminal_review.py, autonomy_coordinator.py, environments/execution.py and actual local/SSH/Docker dispatch adapters as required.
   - [ ] Formalize trusted runtime capability outside request payload; enroll before judge/notification race can expose a generic card.
   - [ ] Red: same ToolRPC invocation receives one actual kernel/transport execution and separate signed DONE; unattended DENY never executes later.
   - [ ] Red: pause before physical dispatch, request cancellation/revocation and use cancellation-resistant transport; no late spawn. Test post-dispatch cancellation truthfully.
   - [ ] Keep all policy floors, no private-token inference from IDs, no retry after owner-once claim, no success merely from accepted/running.
4. Root integrates the actual queue/judge/worker/kernel/MockTransport paths, reviews critical races, runs focused tests after each implementation step, rebuilds Graft and syncs truthful records.
   - [ ] Mutation checks target each new authority/receipt/liveness guard; validate baseline and restored source, not process exits alone.
   - [ ] Final frontend/mobile checks only if changed; guarded full backend serially at integrated milestone, exact staged secret scan, frozen hashes/counts and coherent local commit.
   - [ ] Keep H277/H485 partial until all their remaining requirements are actually met; no push/merge/deploy/paid calls/activation.

## Detailed source contracts to incorporate before implementation

- [Queue contract](h485-owner-once-queue-contract-2026-10-03.md) (corrected mode matrix)
- [Transport contract](h485-owner-once-transport-contract-2026-10-03.md)

Rollback: separate local continuation commit after the owner-identity prerequisite commit. New offer records are inert without the live runtime permit; revert source while preserving ordinary queue/task history. No unrelated file rewrite or dependency/global-policy change.
Next action: finalize the shared capability/offer interface from these contracts, then write failing real continuation regressions before implementing queue/transport/worker integration. Keep the full goal active; H277/H485 remain partial.

## Physical-boundary kernel revalidation refinement

Integration established that the context-free judge needs a bounded process-local
registration of the live originating invocation before it can settle unattended
DENY. This registration suppresses premature closure only; it grants no execution
authority. Releasing the invocation also settles any remaining canonical DENY,
including cancellation before prompt creation.

A paused built-in transport must observe current kernel floors after its initial
GRANT. Repeating normal authorization would record the loop event twice and disturb
the pending B7 decision handoff. Add a non-consuming, fail-closed revalidator of
the exact `terminal.exec` Action, capability and approval aperture: current
kill-switch, budget, loop breaker, policy mode, taint and receipt, without a new
loop event or pending handoff. Owner physical scopes require its GRANT immediately
before dispatch CAS; unsupported or awaitable revalidators refuse execution.
Ordinary smart/manual authorization remains unchanged. Root integrates; implementer
A owns kernel/binding/worker and focused kernel tests; B owns the runner's trusted
revalidation callback and physical pause tests. Final evidence must include these
sources and the integrated tests, rather than reusing the earlier 647-case freeze.
