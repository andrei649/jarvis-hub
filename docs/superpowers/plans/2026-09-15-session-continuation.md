# Explicit durable conversation continuation

Goal: an owner can create a new session carrying retained context and root birth, then address real text/stream chat to it. Base db347804559a4c6c76017ef1607ca46a268053c6. Generated 2026-09-15. Implementation and independent source review complete; integrated full-suite verification passed.

No global default switch, automatic compaction rotation, copied approvals/kernels, new providers, protected edits or live calls. Frozen H671 requires root birth across real continuation; equivalence remains unclaimed until actual routes and restart work.

## Owned paths

- agents/core/session_continuation.py: strict seed validation, transactional SQLite creation/idempotency/lineage and explicit-session hydration/coordinator.
- agents/core/checkpoint.py and conversation_clock.py: additive session instance identity, inherited birth and generation-aware clock CAS.
- agents/core/memory/manager.py and orchestrator.py: attach the existing checkpoint hook and hydrate committed seed-only children on explicit resume/startup; ordinary resume preserved.
- agents/core/memory/conversation.py and persistence.py: instance-tagged snapshots and bounded strict snapshot loading and timestamp-preserving hydration without switching current session; new seed fallback only.
- agents/core/routers/sessions.py: admin-guarded creation and typed request/response; existing resume stays unchanged.
- agents/web.py: optional validated session_id, correct notes/lease/history routing for explicit text and stream, no default mutation.
- agents/cli/nerva.py: sessions continue SOURCE --request-id UUID; chat --session CHILD. Existing list/chat behavior retained.
- focused tests/test_session_continuation.py plus necessary exact contract tests; this plan. No global counts/evidence/assets.

## Atomic contract

SQLite transaction owns child session, immutable lineage+seed and initial clock. Opaque per-row generation distinguishes reused IDs. Existing rows migrate idempotently; legacy inserts receive a generation. Child physical birth is new; inherited conversation birth/rebuild are captured from parent. Ancestry is validated boundedly, with no cycles/missing/generation substitutions. New UUID child ID cannot overwrite an existing row or snapshot. A unique caller request ID resolves ambiguous commits/retries without duplicate children.

Creation holds source turn lease, then MemoryManager and ConversationMemory locks, and rechecks source generation/clock in the commit. A busy source refuses; no model is called. Seed is bounded retained history preserving original timestamps. Oversize/corrupt/empty context refuses explicitly. Hydration resolves valid newer child snapshot before immutable seed, never writes seed over newer turns, and never changes memory.current_session_id/default. SQLite is authoritative for creation; JSON is derived. No cross-database atomicity is claimed. Cancellation before commit publishes nothing; cancellation/response loss after commit is resolved by the same request ID. Failed writes must not become a successful empty child. Existing forget erases the SQLite seed along with other user content; verify actual erasure.

## TDD units

- [x] Store RED then green: two-generation lineage/clock, migration/reused IDs, one transaction rollback, same/different request IDs, corrupt ancestry and restart.
- [x] Hydration/coordinator RED then green: retained timestamps, newer snapshots, source busy and mutation races, cancellation/ambiguous response, no default mutation.
- [x] Actual guarded route + explicit text/stream + CLI RED then green; generated schema drift remains parent integration responsibility unless focused contract fixtures need synchronization.
- [x] Focused suite, whole Ruff/Bandit1.9.4, scoped Graft freshness, commit source for independent review.

Invocation reasoning overlap: upcoming source332d0f1b adds ChatRequest.reasoning and CLI --reasoning scopes. Do not cherry-pick it; use independent optional session_id/--session and preserve its integration seam. Locks are process-local like existing turn dispatch; no multi-worker shared-memory claim. Rollback source ignores additive SQLite lineage/seed columns/tables; no automatic deletion of user data.

## Final implementation and verification

New snapshots carry their exact session instance ID; in-memory histories have the same tag. A persistent history binding permits untagged legacy history only for rows present at migration. A pre-existing orphan JSON file is not blessed by a later session insert. Delete/recreate with the same ID cannot reuse old cached or disk context. Pre-upgrade incarnation provenance cannot be reconstructed; the documented legacy fallback trusts only the migrated row.

Receipt replay and hydration share bounded SHA256/schema validation. Present corrupt newer JSON refuses instead of replaying an older seed. Child seed/clock/session creation is one SQLite commit, but subsequent normal turn JSON persistence retains its existing best-effort behavior; it is not a transactional post-creation turn store. Default startup may catch resume errors, so continued-session preparation also guards text/stream before add_turn and the shared prompt-history path before internal process calls. Invalid continued context produces a safe refusal (or the existing empty internal completion), without overwriting the file or calling a provider.

Operator flow: `nerva sessions continue SOURCE --request-id 00000000-0000-4000-8000-000000000001` returns a new ID. Use `nerva chat --session CHILD "next question"`, or POST `/chat`/`/chat/stream` with `session_id`. Repeat creation with the same UUID to resolve response loss. Creation is admin guarded and respects the server prefix; chat keeps existing guards. No shared session switch occurs. Only role/content/agent label/token estimate/original timestamp are carried, not executable checkpoints or approvals. Missing ancestors block new descendants; an existing child retains its immutable root birth.

RED logs: `/tmp/nerva-continuation-store-red.log`, `-hydrate-red.log`, `-route-red.log`, `-resume-red.log`, `-review-red.log`, `-startup-red.log` (four real default-dispatch failures), and `-process-red.log` (two internal-completion failures). Final guarded focused result: 358 passed, zero skipped/errors/failures; 45 new collected cases. `/tmp/nerva-continuation-focused.xml` and `.log`. Actual owner route to real Orchestrator/Agent text and stream runs both directly and after restart/two generations, using a fixture backend. No live model call. Tests also cover leases, ambiguous commit recovery, seed erasure, generation reuse/orphans, and newer snapshot precedence.

Run from this worktree with the existing pytest configuration:

```sh
TMPDIR=/private/tmp /usr/bin/python3 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_session_continuation.py tests/test_chat_http.py tests/test_nerva_cli.py tests/test_compaction_clock.py tests/test_session_persistence.py tests/test_session_birth_persistence.py tests/test_orchestrator_bindings.py tests/test_concurrent_session_isolation.py tests/test_turn_lease.py tests/test_session_traversal.py tests/test_data_purge.py tests/test_data_purge_memory.py tests/test_memory_endpoints.py tests/test_agent_session_start.py tests/test_aud7_sse_hotpath.py tests/test_agent_runtime_v2.py tests/test_tool_loop_compaction.py tests/test_r3_b2_memory_forget_contracts.py --junitxml=/tmp/nerva-continuation-focused.xml -q
```

Whole Ruff and baseline Bandit1.9.4: `/tmp/nerva-continuation-ruff.log`, `/tmp/nerva-continuation-bandit.log`. Existing Starlette/httpx deprecation and Bandit comment-parser warnings only. Scoped ten-file Graft wiring cache rebuilt and checked in `/tmp/nerva-continuation-scoped-graft`; logs `/tmp/nerva-continuation-scoped-graft-build.log` and `/tmp/nerva-continuation-scoped-graft-check.log`. No semantic/paid indexing. Global counts/evidence, +1 guarded route schema snapshots, invocation-reasoning additive integration and publication remain parent-owned.

Independent review follow-up: actual observe-only channel dispatch reproduced two RED cases after failed resume. Common MemoryManager.add_turn now validates/hydrates continued history before any append, including ID identity and seed-only context. The valid unhydrated-seed observation test preserves both earlier history and instance-tagged persistence. RED `/tmp/nerva-continuation-observe-red.log`; final focused log above includes all three added cases.


## Integrated H671 contract reassessment

Final source base: `01f26553c1425de5e109a440285526bf50165c75`, integrated onto actual main `5a8efc9`. Whole-row H671 is equivalent to the frozen behavior: the birth line resolves the durable lineage root across explicit continuation/restart, the second date reflects only accepted compaction, same-day prefixes remain stable, and production renders a known IANA zone with its historical abbreviation/offset. No automatic rotation is invented or required. Unknown birth remains omitted; unavailable or invalid zone discovery retains a truthful local offset rather than inventing an IANA name. Subsequent ordinary JSON persistence remains best effort and turn leases remain process-local; no broader transactional transcript guarantee is claimed.

The bounded IANA repair was planned before implementation: resolve explicit TZ with existing env_config and ZoneInfo, otherwise use the already-installed cross-platform tzlocal discovery; pass that zone through production rendering for both birth and rebuild dates. No new dependency, timezone setting mutation or abbreviation inference. Two actual production-render cases failed first (`/tmp/nerva-clock-iana-red.log`); four added cases cover explicit Bucharest, historical/current DST, unset discovery, invalid/unavailable fallback and repeated/same-day rendering. Focused 168 passed (`/tmp/nerva-clock-iana-green.xml`, `.log`); independent 168 passed (`/tmp/nerva-clock-iana-independent.xml`, `.log`). Scoped Ruff/Bandit passed.

Continuation source author verification: 358 guarded passes. Independent exact-source review: 360 passes including external actual process and observe-only regressions (`/tmp/nerva-continuation-independent-final.xml`, `.log`). Integration preserved invocation reasoning and session request isolation; independent 151 combined cases and root 242 guarded cases passed. Five new integration cases plus four IANA cases give 54 new backend cases overall. Actual guarded collection: 800 modules, 11885 tests (`/tmp/nerva-continuation-collect.log`). Frontend 1326/mobile 140 remain unchanged; route count is 502 with regenerated guarded API snapshots/types. Three TypeScript checks passed. Integrated whole Ruff and Bandit1.9.4 passed (`/tmp/nerva-continuation-integrated-ruff.log`, `-bandit.log`). All provider calls in proofs are mocked; no live service or billing claim.

Full integrated backend outcome: passed on the frozen repaired source/metadata; actual evidence is recorded below. Previously stale evidence rows are preserved verbatim; other evidence refreshes require every prior row hash to match actual main.


## First integrated full run and verification repair

The first guarded full run collected 11885: 11855 passed, 23 skipped, one expected failure, six failures and no errors in 253.327 seconds (`/tmp/nerva-continuation-full-first.xml`, `.log`). Four failures came from the omitted generated API sweep update; one from the HUD caller inventory missing the explicitly CLI-only continuation creation route; one existing dispatch test's second runner still consulted production quiet hours, while its first runner already used a non-quiet injected clock. The latter was independently reproduced on actual main (`/tmp/nerva-job-baseline.xml`).

Source/test repair `01f26553c1425de5e109a440285526bf50165c75` regenerates the API sweep, declares the actual `nerva sessions continue` CLI consumer in the existing machine-facing inventory, and gives both test runners the same explicit non-quiet callback. It does not change production quiet hours or loosen pending-reservation/replay assertions. The separate quiet-hours regression still verifies delayed delivery followed by exactly one send when quiet hours end. Root repair suite: 50 passed (`/tmp/nerva-continuation-repair.xml`); independent repair review exercises these assertions and HUD parity (`/tmp/nerva-continuation-repair-review.xml`, `.log`). No runtime change or new test case; count remains 11885. The full rerun passed on this frozen repaired source/metadata, as recorded below.


## Final integrated result

The complete guarded rerun passed: 11885 collected, 11861 passed, 23 skipped, one expected failure, zero failures/errors in 256.227 seconds (`/tmp/nerva-continuation-full.xml`, `.log`). The first failed run remains preserved separately above. Root verified tracked files were unchanged throughout the successful run. Exact product command retained pytest.ini guards and used `/tmp/nerva-run-isolated.py`, `/usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0`, `PATH=/tmp/nerva-fish-runtime/fish/4.9.3/bin:/Users/andrei649/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin`, and `/Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest --junitxml=/tmp/nerva-continuation-full.xml`. No live providers or external channels were used. Independent repair review passed 15 cases. Final metadata/count verification uses the actual full XML; 81 metadata checks are recorded in `/tmp/nerva-continuation-metadata.xml` and `.log`. Assessment source remains `01f26553c1425de5e109a440285526bf50165c75`; only documentation/evidence changes follow the successful full run.
