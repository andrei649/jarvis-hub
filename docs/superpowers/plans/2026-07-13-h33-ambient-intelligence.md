# H33 Ambient Intelligence Implementation Plan

> Execute after H30.1/H30.2 and H31's typed producer sink merge. Use strict TDD, additive ambient
> modules, fresh review per task, and serialize autonomy/orchestrator/shared-snapshot edits.

**Master setting:** `ambient.enabled`, default false; Product Posture cannot enable it.

**Goal:** declarative durable monitors plus the six-rung ignore/remember/monitor/act-silently/
ask/interrupt ladder, with one persistent <=4/day attention budget and transparent surfaces.

## Task 1 — H33.1 bounded contracts, durable monitor registry, and engine

**Create:** `agents/core/ambient/contracts.py`, `store.py`, `registry.py`, `engine.py`, adapters and
focused tests.

- [ ] Red tests for default-off master flag, bounded schema, no eval/callables, SQLite restart/
  migration/corruption, source idempotency, event/observed time, debounce/hold/hysteresis/cooldown,
  backpressure, per-source health, and decision journal.
- [ ] Define allowlisted `AmbientEvent`/`MonitorDefinition`/`AmbientDecision` contracts with
  structured provenance, taint, privacy, consent, correlation, and bounded attributes.
- [ ] Monitor definitions are admin-created, versioned, audited and hash-bound; create/update/delete
  routes are excluded from ToolRPC/MCP/agent tools. Events can select only a predeclared rule
  branch and can never supply capability ids, action kinds, targets, templates, or parameters.
- [ ] Predicate DSL is limited to typed eq/ne/lt/lte/gt/gte/in/changed/age operators: at most 200
  monitors, 20 predicates/monitor, 32 attributes/event, 512 chars/string, 16 KiB encoded event,
  7-day hold/cooldown and 24-hour source-event age. No regex/eval/custom code.
- [ ] Persist only opaque source/target ids and non-sensitive rule fields as plaintext monitor
  config; private names, room/camera mappings, recipients, and schedules remain in H30/H31 owner
  stores or an encrypted private definition. Event/decision state stores only stable fingerprints,
  opaque owner-store references, and schema-specific anonymous aggregates;
  private H30/H31 values remain in their encrypted stores. Cap ambient state at 100,000 rows/64
  MiB with 30-day journal, 7-day health, and monitor-bounded dedupe/cooldown TTLs.
- [ ] Bind derived rows to consent generation and source event id. Purge removes journal, memory,
  dedupe/correlation/cooldown rows and writes replay-suppression tombstones. Corruption disables
  evaluation/actuation and surfaces degraded health; never recreate an empty safety database.
- [ ] Bound queues to 256/source and 2,048 global, concurrency to 8 and work to 100 events/tick.
  Coalesce state updates by dedupe key; a critical transition is durably held/backpressured and
  surfaced degraded, never silently discarded.
- [ ] Adapt H30 HouseEvent, H31 CameraEvent, and existing digital probes without producers
  importing H33. No raw frames/audio/email bodies/arbitrary source payloads.
- [ ] Define an ownership table for ProactiveObserver resource/service probes and EventWatcher
  email/calendar/finance/health/WorldView sources. Cut over in two phases: health-check/import the
  cursor/debounce watermark, atomically claim source ownership, then disable that exact legacy
  producer. Failure leaves legacy active; rollback resumes from the shared watermark without
  replaying a fresh transition.
- [ ] Give each digital adapter an allowlisted projection. Never persist raw `Signal.detail`, host,
  calendar title, sender, finance/health detail, or WorldView payload in ambient state, tasks,
  journal, KG, or API.
- [ ] Run observer/watcher/store/contract tests, review, and commit.

## Task 2 — H33.2 six-rung policy and persistent global K3 attention budget

**Create:** `agents/core/ambient/policy.py`, durable `AttentionLedger` and
`AttentionDeliveryBroker`; modify narrow autonomy
worker/policy/queue seams and focused tests.

- [ ] Red tests for all rung semantics, hard-floor precedence, confidence/taint downgrade,
  ask-without-push, interrupt-with-push, exhaustion downgrade to ask, quiet hours, concurrency,
  restart/day rollover, clock rollback, and atomic <=4/day across every unsolicited channel.
- [ ] `ignore` counts without content; `remember` stores sanitized fact; `monitor` updates state;
  `act_silently` permits only reversible allowlisted verified/rollbackable actions; `ask` creates a
  Decision Inbox/digest item without push; `interrupt` adds an immediate budgeted push.
- [ ] Make the delivery broker the only unsolicited-delivery choke point for Telegram,
  CallBroker, legacy/autonomy pushes, and ambient interrupts. Persist unique delivery ids and
  `reserved -> dispatching -> delivered | failed` transactions under SQLite concurrency.
  Reservation immediately debits admission. Only failure proven before dispatch may release it;
  crash/timeout after dispatch begins conservatively stays spent unless a provider idempotency key
  and status reconciliation proves non-delivery. Ledger unavailable/corrupt downgrades to ask.
  Remove independent `consume()` paths.
- [ ] AttentionLedger stores only opaque delivery/task id, channel class, state, reservation/
  dispatch/delivery timestamps, day/window id and bounded failure category; never body, recipient,
  phone/chat id, event attributes, room/camera label, or provider payload. At-rest scan tests prove
  absence; HUD resolves safe labels through privacy-filtered owner projections.
- [ ] Persist task `attention_mode = none | digest | interrupt`: ask creates a blocked Inbox/digest
  task without reserving delivery; only interrupt calls the broker. Critical alerts never bypass
  an exhausted budget and downgrade to ask.
- [ ] Use owner IANA timezone plus monotonic persisted day sequence; handle ambiguous/nonexistent
  DST time and prevent clock rollback/restart from reopening an earlier allowance.
- [ ] Test crash before dispatch, crash after provider acceptance before commit, ambiguous timeout,
  duplicate retry, provider reconciliation, restart, and concurrent processes; actual/ambiguous
  interruptions can never exceed four admissions per persisted day.
- [ ] H30 security, money, irreversible, low-confidence, and tainted actions can never silently
  actuate. Every side effect re-enters CapabilityActionAPI/kernel at execution.
- [ ] AmbientEngine only emits a canonical governed TaskQueue proposal with monitor/rung/event
  provenance; it never calls a broker/driver. The registered TaskExecutor revalidates monitor
  version, current event/state, consent, kill-switch, capability binding and policy, then invokes
  Action API/kernel.
- [ ] Every task carries immutable ambient generation and monitor-version hash. Disabling ambient
  atomically advances/revokes the generation and source ownership, stops intake, and makes pending/
  approved tasks non-runnable. TaskExecutor rechecks `ambient.enabled`, generation, monitor hash,
  source ownership, and current policy immediately before Action API and again before mutation.
  Compensation remains allowed/audited after disable.
- [ ] Test disable after queue, after approval, during handler, restart with approved task, final
  pre-mutation revocation, and compensation after disable.
- [ ] Silent eligibility uses a static capability allowlist and requires bound postcondition
  verification plus automatic rollback/restore handler. Missing proof downgrades to ask. Exclude
  media, calls, messages, visible displays, and all attention-producing actions. Partial failure
  runs verified compensation or records `manual_recovery_required`, never transport-only success.
- [ ] Run worker/policy/K3/concurrency tests, review, and commit.

## Task 3 — H33.3 privacy-safe situation memory with provenance and decay

**Create:** `agents/core/ambient/memory.py`, focused tests; reuse private house/camera projections,
bi-temporal KG for non-sensitive facts, and DecayMemory.

- [ ] Red tests for temporal correlation, source provenance, valid/observed time, privacy filters,
  consent purge, decay, contradiction, restart, and no raw/private payload leakage.
- [ ] Project only schema-allowlisted sanitized situations. Sensitive house facts stay in H30's
  private store; camera facts remain anonymous metadata.
- [ ] Answer repeated-observation queries without claiming anonymous person events are the same
  individual. Re-identification remains absent.
- [ ] Link decay and deletion across derived relations so purge/revocation cannot resurrect facts.
- [ ] Run KG/private-store/decay/privacy tests, review, and commit.

## Task 4 — H33.4 core reality pack, scale, and counter-metrics

- [ ] Hermetic 1/10/100-monitor scenarios prove bounded memory/latency/queues, idempotency,
  hysteresis, durable debounce, persistent <=4 interrupts, ask/interrupt separation, taint
  containment, kill-switch, and zero action bypass.
- [ ] Gate 1/10/100 scenarios at <=64 MiB incremental memory, <=100 ms p95 decision latency for
  bounded local fixtures, zero dropped critical transitions, and queue depth within configured
  caps at 10 events/second/source. Report environment and raw measurements.
- [ ] Record per-rung decisions, true pushes, verified actions, rollback, rejects, and downgrades.
  Do not infer pushes from a boolean task field or general `updated_at`.
- [ ] Preserve north-star interrupt/reject guardrails as monitors multiply and surface confidence
  intervals/sample sizes honestly.
- [ ] Replace north-star push reads with committed AttentionLedger delivery timestamps; retain
  TaskQueue only for accepted/rejected action outcomes. Report pushes, calls, failures, released
  reservations, downgraded interrupts, and ambient action results separately.
- [ ] Run reality/north-star/load/soak gates, review, and commit.

## Task 5 — H33.5 night-shift v2 and quiet-hours behavior

- [ ] Red tests use the configured owner IANA timezone for night boundaries/DST, critical vs
  noncritical interrupts, budget exhaustion,
  silent reversible verified work, no-op exclusion, failure/rollback, and restart.
- [ ] Ambiguous/nonexistent DST times execute once under the persisted window id; a backward clock
  shift cannot replenish budget or repeat a night action.
- [ ] Count ambient work by rung and verified result. Noncritical interrupt becomes ask during quiet
  hours; critical still consumes the one global budget. Security hard floors remain unchanged.
- [ ] Report the night split without counting ignored/monitor/no-op activity as completed work.
- [ ] Run scheduler/night/north-star tests, review, and commit.

## Task 6 — H33.6 transparency API, HUD/mobile parity, truth sync, and PR

**Create:** `agents/core/routers/ambient.py`, separate frontend component and native read surface;
update route/OpenAPI/auth/type/parity artifacts.

- [ ] Red tests for disabled/empty/degraded/live monitor list, source health, last event/decision,
  rung counts, global budget, privacy redaction, bounds, and guarded mutations.
- [ ] Add `GET /api/ambient/monitors` and narrow owner controls. Fix or retire legacy consumers
  expecting incompatible observer shapes rather than returning multiple undocumented schemas.
- [ ] HUD/mobile show what is watched, why the last rung was chosen, health, and remaining
  attention budget without exposing private event content.
- [ ] Prove H30/H31 feed consumption, then close H31.6. Graduate only wave-3 modules actually
  exercised by the real hermetic seam; keep training/rust owner-only.
- [ ] Update H33.3 backlog wording from “same unknown person” to repeated anonymous observations;
  no re-identification claim.
- [ ] Run all H33 plus H30/H31/autonomy/K3/KG/reality/parity, full backend/frontend/mobile,
  Ruff/Bandit/diff-check/status-sync; fresh final review, truth sync, draft PR, CI, merge.

## Rollback

Disable the ambient master flag, detach producer adapters, and restore legacy observers only where
no equivalent monitor is active. Durable decisions remain auditable; sensitive situation data can
be purged through its owning H30/H31 privacy lifecycle.
