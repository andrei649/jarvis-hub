# H485 owner-once continuation: local integration checkpoint

Goal remains full functional parity across the pinned 697 Hermes capabilities.
This checkpoint advances the existing [implementation plan](../h485-owner-once-plan-2026-10-03.md);
it does not complete H485 or H277 and does not grant new equivalence credit.

Base/head: `aec4348cf96f92d2b384dbba4b8e3a5b7e438a11`.
Branch: `codex/h277-provider-discovery-20261002`.
Generated: 2026-10-03. Source changes are uncommitted. No publication, merge,
deployment, paid provider calls, or runtime activation was performed.

## Implemented and verified locally

- Exact delivered-owner offer, reply, signed acceptance, private queue claim,
  one-use dispatch CAS and separate signed completion primitives. Off mode keeps
  signed owner grants; hold refuses claims; enforce composes with B7 events.
- Generic accept/edit cannot bypass an intact smart DENY. Unattended DENY is
  rejected independently of notifier presence or interrupt mode. ESCALATE keeps
  its established manual approval controls.
- Notification-first closure remains observable by the originating invocation,
  including closure before the observer starts. Definitive refusals do not
  consume generic decision delivery or its attention budget.
- Exact DENY history/count/breaker survives machine rejection, owner acceptance,
  owner rejection and withdrawal before dispatch. Historical owner acceptance
  observations do not confer execution authority or completion proof.
- Separate once/deny Telegram cards preserve valid 4,000-character commands.
  Plain-text parts stay within 4,096 UTF-16 units; only the final confirmed part
  carries controls. HTTP `ok:true`, positive message ID and live generation are
  required for every part.
- Bounded reply registry binds the live origin, canonical owner, exact delivered
  message, generation and deadline. It checks fresh ownership/registration,
  requested cancellation and the live request loop before queue decision CAS.
  The waiter must confirm receipt before a successful callback acknowledgment.
  Channel stop revokes grants and releases generation registry capacity.
- Real Telegram ChatLanes plus the real signed queue demonstrate that the exact
  registered callback resolves a waiting turn. Closed origins cannot authorize
  later execution. Cross-loop tests reject a stopped request loop.

## Verification boundary

The guarded focused command covering H277 smart tests, H485 tests, Telegram tests
and orchestrator bindings completed with **647 passed, zero failures/errors**.
The restored prompt suite has 12 cases. Ruff and diff checks passed; Bandit against
the repository baseline reported zero new findings/errors. Gitleaks scanned the
exact 19 changed source/test files and reported zero findings.

Three targeted mutations removed fresh-owner checking, active-request-loop
checking and confirmed waiter delivery. Each failed its named behavioral
regression; the source was restored byte-for-byte. The compact
[verification record](h485-owner-once-progress-2026-10-03.json) pins changed sources.

The earlier full-backend result of 21,790 passed belongs to the preceding identity
checkpoint, not this change set. No full-backend, frontend, live Telegram, paid
provider or remote CI acceptance is claimed here. Existing default pytest socket
and timeout guards remained enabled.

## Next integration work

1. Wire `OwnerOncePrompts` in the real coordinator before judge/notification
   scheduling. It is currently exercised in tests and **not wired in production**.
2. Continue an accepted claim in its originating ToolRPC invocation through the
   private named worker path, without scheduler authority or retry. Preserve
   e-stop, B7, kernel capability/budget/loop/taint and target/hardline floors.
3. Carry fresh owner/turn/registration checks to the actual local, SSH and Docker
   physical dispatch boundaries. Prove no late spawn under cancellation-resistant
   waits; distinguish cancellation after dispatch from undoing physical effects.
4. Seal/read the separate owner DONE proof before reporting successful execution;
   release runtime grants on every settled/failed/held/cancelled path. Reconcile
   crash/expired grants without replaying a previously approved operation.
5. Run integrated scenarios, remaining mutations and the guarded full suite at
   that milestone; sync test counts and reread affected evidence before restamping.
   Keep H277/H485 partial until their complete contracts pass, then continue the
   remaining Hermes queue. All 697 rows remain in scope.

Rollback remains the plan's separate local continuation unit after the committed
identity prerequisite. Preserve existing task history; unsigned/model metadata
and restarted-process rows never recreate a live owner permit.
