# H063 session lifecycle implementation plan

Goal: all original 697 pinned Hermes capabilities; implement the complete accepted
H063 reset, expiry/index-age and stall contract without deleting transcripts.
Generated: 2026-10-05. Base/head: a7ffad6676cfb28e7ac374d495b4a5889e5f4646.
Existing dirty work is preserved. No commit, stage, push, merge, deployment,
live provider activation or new paid service.

## Design and reference reconciliation

Pinned reference: Hermes 59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e.
`gateway/config.py` declares SessionResetPolicy inert; `session_lifecycle.py`
does not replace sessions on time alone. The original accepted H063 inventory
also requires opt-in idle/daily policies. Preserve the current reference default
(`none`) while implementing those accepted options; do not shrink the row.

Use the existing session identity, shared pairing and delivery boundaries.
Keep current generation-zero keys for backward-compatible transcript resume.
A local SQLite route index (stdlib, as in existing Nerva stores) persists the
generation, activity, normalized channel and dm/group/thread kind. Transactions
and retired generation fences prevent reuse of old transcripts after pruning.
Pruning removes active routing metadata, not transcripts or generation fences.
The store refuses corruption/capacity/write errors rather than falling back to
generation zero. Scope is the existing single-orchestrator turn-lease model;
SQLite counters do not invent a distributed turn lock.

Hold a stable base-route lease while selecting/rotating a generation and running
an answering turn, plus the existing actual-session lease. Context-only observed
messages keep the pre-existing no-turn-lease contract. Watchers skip active routes
and externally leased actual sessions. Observe-only turns cannot reset or reply.
`/new` and `/reset` (configurable exact texts) rotate before the model and deliver
a short acknowledgement through the normal router. Slack/Discord/ntfy keep
their existing persisted-Inbox approval path. Identityless/shared channel turns
stay unchanged by default; configured resets of intentionally shared context
apply to that same shared context, not a newly invented isolated conversation.

Reset settings: sessions.reset_mode none|idle|daily|both (none), idle_minutes1440,
daily_hour4, reset_by_type{}, reset_by_channel{}, reset_triggers['/new','/reset'].
Policy precedence: global < type < channel < channel's nested types[kind].
Daily boundaries use general.timezone (Europe/Bucharest existing default), with
aware UTC timestamps, DST tests and no reset on backward/invalid clocks.
Index-age: sessions.store_max_age_days90; zero disables it; active routes exempt.

Stalls use real processing-start/token/tool/completion activity as the sole
progress clock. Inbound marks only pending eligibility, never progress. Unknown
progress cannot trigger a notice. Each pending turn has its own episode token;
success latches once, send failure retries, progress/drain rearms, and a fresh
check precedes delivery. Notice has no inbound text/sender data. Use the existing
owner-configured outbound destination/safe-mode/audit path with bounded sends.
sessions.stall_seconds300 (zero off); sessions.stall_channel='telegram'.
Run the lightweight stall check every30s and route expiry/pruning every300s on
the existing scheduler, default reset policy none; no new daemon.

## Interfaces and single writers

- Sol High implementer1 owns only NEW channels/session_reset.py and
  tests/test_session_reset_policy.py. ResetPolicy(mode,idle_minutes,daily_hour,
  timezone); resolve_policy(get_setting,channel,kind); should_reset(last_activity,
  now,policy); generation_key(base,generation). SessionResetStore(path):
  state(base), touch(base,now,channel,kind), rotate(base,now,channel,kind),
  entries(), retire(base). Immutable RouteState(base,generation,last_activity,
  channel,kind,active). Retire increments the generation and clears active
  metadata; touch revives without decrementing it. Cap10000 total fences.
- Sol High implementer2 owns only NEW channels/session_stall.py and
  tests/test_stall_watcher.py. StallWatcher(clock=monotonic): begin(key) returns
  an episode token; progress(key,token); finish(key,token); async check(timeout,
  notify) returns sent count. notify receives(key,token,idle_seconds). Progress
  requires exact active token, and old completion cannot drain a newer episode.
  Recheck before each callback, bounded10s, no latch on false/error/timeout;
  serialize overlapping checks. begin does not update progress.
- Coordinator owns all existing files and integration tests: channels/session.py,
  orchestrator.py, scheduler_service.py, settings_db.py, agent_runtime.py,
  channel adapter metadata, NEW channels/session_lifecycle.py and its tests.
  No implementer delegation or shared-file edits.

## Tasks and verification

- [x] RED then GREEN policy precedence, idle/daily/both, invalid config/clock,
  DST, restart persistence, atomic failed writes, pruning fences/capacity.
- [x] RED then GREEN stall exact-token pending/progress, no inbound fallback,
  once/rearm, failed/bounded sends, recovery during sibling send, cancellation.
- [x] Integrate stable-route serialization, generation selection, reset-trigger
  acknowledgement and transcript preservation; restart and concurrent-turn tests.
- [x] Normalize adapter dm/group/thread metadata without changing existing keys
  except explicit Telegram forum topics, which must be isolated from the room.
- [x] Wire real token/tool progress and scheduled expiry/index/stall checks;
  test active-turn and direct-session lease exemptions, pruning and shared mode.
- [x] Run focused and affected suites after each step, then serial full suites on
  a frozen milestone. Scoped Ruff/Bandit/strict secret scan, fresh local Graft,
  count/report/doc gates. Record skips and inherited evidence drift separately.
- [x] Only verified full H063 earns equivalence. Preserve partial gaps elsewhere;
  never globally restamp stale records. Next action: frozen full backend, then
  serial frontend and bounded evidence/collateral review.

## Local checkpoint, 2026-10-05

Owned implementation: the modules above plus `agents/core/agent.py`,
`agents/core/channels/telegram.py`, `agents/core/channels/discord.py`, and focused
metadata expectations in `tests/test_telegram_group_gate.py` and
`tests/test_h117_message_batching.py`. Two Sol High implementers completed the
policy store (26 tests) and watcher (20 tests); neither delegated or published.

Final affected suite: 536 cases, 535 passed, one existing optional-adapter skip,
zero failures/errors. This is scoped verification, not the full-suite result.
Reset leases cover the current and next generation before rotation, and the
returned memory session during the turn. Shared busy requests cannot replace
the active stall episode; persisted shared generation-zero routes remain tracked
after a policy change and restart. Failed create/resume leaves the old route.
Rewind refusal returns a controlled unavailable reply. Expiry does not retain
temporary locks for inactive routes. Tokens are observed independently of reply
publication. Watcher close runs before transport shutdown; a coroutine ignoring
cancellation is bounded, reported, and retained until it settles, never described
as forcibly stopped. Forum text/HTML fallback/voice/audio and transcript echoes
keep the topic, including batches; closed reply scopes cannot leak to late tasks.

Remaining verification: frozen full suites, metadata gates and final acceptance.
Inherited conversation snapshot persistence is best effort outside verified rewind
writes; H063 does not claim to make all memory writes transactional. Main HUD/API
turns that bypass channel_handler retain their existing lifecycle; this capability
is the accepted gateway/channel contract. No live Telegram/Discord/provider probe,
fresh mobile run, GitHub CI, commit, push, merge or deployment was performed.

## Full-suite round 2

First full backend: 23,711 cases, 23,669 passed, seven failures, 34 ordinary skips,
one existing xfail, zero errors; all 4,771 frozen inputs unchanged. The seven
failures are retained as red evidence rather than hidden by focused results.

Fixes: context-only observation no longer waits on an active answering lease;
the lifecycle cache is declared in Orchestrator initialization; two exact external
writer coordinates are refreshed after scheduler insertion; Discord identity
assertions include the added private/group/thread metadata while still checking
the author ID and no direct sends; the origin fixture supplies a valid session and
typed setting defaults instead of returning False for every setting. The four
new numeric settings are reviewed housekeeping/owner-alert cadences, with an
integration test proving that due stall notices still obey safe-mode egress.

Round-2 focused verification: 317 passed, zero failures/errors/skips. The source
plan now also owns `agents/core/orchestrator_bindings.py` and the narrow expectations
in `tests/test_default_deny_front_door.py`, `tests/test_h490_safe_mode_posture.py`,
and `tests/test_m12_origin_threading.py`. Existing turn-lease regressions are pinned
as evidence. Next: fresh frozen full backend, then serial frontend and final
acceptance. H063 remains partial until those checks finish.

Final provider-emitter regression: the real `llm.base._emit` awaits coroutine
functions, rather than returned awaitables. The activity wrapper is now async and
awaits both coroutine sinks and awaitable-returning callable sinks. Red reproduced
the dropped async sink; async/sync/no-sink variants now pass with the actual emitter.
Final expanded affected suite: 403 passed, no failures/errors/skips. Integration
tests now total 40; collected backend count is 23,715. Full retry remains pending.

Second full backend: 23,715 cases, 23,679 passed, one failure in the inherited
H487 native approval wall-budget test, 34 ordinary skips and one existing xfail;
zero errors or drift in 4,416 primary inputs plus 370 unchanged supplementary
inputs retained from the first freeze. The eight approval test variants pass
alone. Their assumed 250ms budget included real disk-backed execution, making
human-credit verification sensitive to suite load. Only the test accounting
clocks are now controlled, advancing 500ms after a real native window opens;
asyncio, consent routing, effects and receipt checks remain real. Production
budgets are unchanged. A disposable credit-disabled control fails by assertion;
133 affected runtime/lifecycle tests pass. Own the additional localized test
`tests/test_h487_native_runtime_human_wait.py`. Preserve both full red reports;
next: third frozen backend attempt, then serial frontend and final records.

Rollback: revert only this unit's localized diffs and new modules/tests/settings;
leave the generated route index intact. Generation transcripts remain ordinary
stored sessions and can be resumed explicitly. Original transcripts are never
removed by reset/index pruning; normal separately governed retention is unchanged.

## Final local acceptance, 2026-10-05

Third frozen backend: 23,715 cases; 23,680 passed, 34 ordinary skips and one
existing xfail, zero failures/errors. Serial frontend: 1,912/1,912 passed. All
4,807 regular source/test/metadata inputs match at both terminal checks, before
these final records were written. The accepted H063 gateway contract is complete
locally; earlier pending/red sections remain dated checkpoints. Global697 parity,
live transports/providers, native devices and publication remain unfinished.
The test-only clock correction retains a valid credit-disabled assertion failure.
Inherited ordinary snapshot durability and the public-setting secret-scan false
positive remain separate follow-ups; no scan exception or production deadline
change was introduced. Next gateway audit: H067 pending-input interception.
