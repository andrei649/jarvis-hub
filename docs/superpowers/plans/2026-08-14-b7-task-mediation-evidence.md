# B7 task-persisted Ultron mediation evidence plan

**Goal:** implement the bounded, default-off contract in the companion design and
produce exact hostile evidence without broadening Action Kernel authority.

## Task 1 — receipt and event primitives

**Files:** `agents/core/autonomy/mediation.py`,
`tests/test_task_mediation_evidence.py`

- [x] Red tests for deterministic payload/action digests, exact receipt binding,
  expiry/revision/substitution/replay rejection, signed event chaining and tamper.
- [x] Implement frozen v1 receipt/event types and a signer adapter over the existing
  owner-held HMAC primitive.
- [x] Add a fail-closed adapter for a trusted monotonic latest-head CAS store outside
  the rollbackable queue database.
- [x] Prove malformed values and signing failures deny without raising authority.

## Task 2 — atomic queue persistence and migration

**Files:** `agents/core/autonomy/queue.py`,
`tests/test_task_mediation_evidence.py`, adjacent queue tests

- [x] Red tests for atomic task+receipt insertion, unique enqueue identity, raw
  classified enqueue refusal, evidence-write rollback and restart reconstruction.
- [x] Add additive task columns plus the append-only mediation-event table/indexes.
- [x] Implement configured `off|enforce|hold` mediation, atomic mediated enqueue,
  CAS worker claim, verified counters and planted-bypass detection.
- [x] Gate every evidence append/claim on the authenticated external latest head;
  reject valid signed-prefix rollback, global task/event mismatch and anchor outage.
- [x] Serialize additive legacy-schema migration across processes with a database
  write transaction and bounded WAL acquisition retry.
- [x] Quarantine legacy classified proposed/approved/running rows under enforce/hold.
- [x] Make persisted B7 provenance irreversible across mutable kind changes and
  reject event timestamps that regress behind the last verified chain event.

## Task 3 — worker and kernel wiring

**Files:** `agents/core/autonomy/worker.py`,
`agents/core/autonomy/{queue,executor}.py`, `agents/core/autonomy_coordinator.py`,
`agents/core/kernel/binding.py`, `agents/core/security/anchor.py`,
`agents/core/orchestrator.py`, tests

- [x] Red tests for kernel `DENY|QUEUE|GRANT`, missing/disabled/failing authority,
  human approval, edit requiring a new revision, retry, hold and direct execution.
- [x] Bind the existing kernel plus signer to the worker after coordinator startup.
- [x] Route classified `govern_enqueue()`/`submit()` through sealed mediated enqueue.
- [x] Route classified `tick()` through atomic validated claim before executor call.
- [x] Keep mode `off` byte-compatible and preserve policy/taint/kill-switch floors.
- [x] Finalize server taint bytes before the kernel call and sign the actual kernel
  tier separately from the effective policy/task tier; mismatched pending decisions deny.

## Task 4 — canonical authority identity

**Files:** `agents/web.py`, `agents/run.py`, relevant autonomy router imports,
queue/kernel/mediation modules and tests

- [x] Red hostile import-order test proving no distinct queue/kernel/metrics/evidence
  modules or singletons can be created as `core.*` and `agents.core.*`.
- [x] Canonicalize production authority imports to `agents.core.*` and fail closed on
  non-canonical direct imports of the B7 authority modules.
- [x] Update only tests that intentionally exercised the legacy import spelling.

## Task 5 — proof, ledgers and draft delivery

**Files:** `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.{json,md}` only if structural
truth changes; `BACKLOG.md`, `docs/MAX_RUNS.md`, generated status surfaces

- [ ] Run focused hostile tests and adjacent queue/worker/broker/action-auth/startup
  suites on Windows.
- [ ] Run repository Ruff and format check, AI policy, Bandit/Semgrep-compatible
  checks, roadmap/status preflight and `git diff --check`.
- [x] Update B7/#818 as candidate-fixed only; E5/E8 remain blocked until acceptance
  and no release/live-hardware claim moves.
- [ ] Commit in bounded steps, push one draft PR, request fresh exact-head security
  review, and wait for terminal hosted Windows/Linux CI.
