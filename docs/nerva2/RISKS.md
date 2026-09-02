# Nerva 2.0 E0.3a — verified program risk register

> **Snapshot:** `main@8b8e64d599262f15334ce547b7adfa3c042a7a78` on 2026-08-02.  
> **Program:** #757 · **Epic:** #758 · **Slice:** E0.3a.  
> This register is grounded in the merged E0 baseline/contracts and current implementation
> evidence. It does **not** close E0: ORIZONT 27–33, `BACKLOG.md`, `STATUS.md`, #757 and the first
> executable child slices still require a separate reconciliation review.

This document complements [`DEPENDENCIES.md`](DEPENDENCIES.md). That file defines ownership and
allowed authority; this file records ways the program can still fail even when individual
components or tests appear healthy.

## 1. Scoring and status rules

- **Likelihood:** `LOW`, `MEDIUM`, `HIGH`.
- **Impact:** `MODERATE`, `HIGH`, `CRITICAL`.
- **Status:**
  - `OPEN` — no sufficient mitigation has been demonstrated;
  - `MITIGATING` — a control or design exists, but closure evidence is incomplete;
  - `ACCEPTED` — explicitly outside the current threat/product boundary and disclosed;
  - `CLOSED` — the failure mode has a load-bearing automated test and, where needed, real-run
    evidence. A green document assertion alone cannot close a risk.

Status is not evidence of closure. The cited implementation, test and owner/live artifacts are.
No risk below is marked `CLOSED` in this architecture slice.

## 2. Canonical risk register

| ID | Failure mode | Likelihood | Impact | Status | Current evidence / trigger | Required mitigation and closure evidence | Owner |
|---|---|---:|---:|---|---|---|---|
| `SEC-01` | A privileged effect bypasses Ultron or executes without attributable mediation. | MEDIUM | CRITICAL | OPEN | `agents/core/kernel/`, action-auth matrix; the withdrawn live counter design in `docs/superpowers/plans/2026-08-02-qa4-ungoverned-counter-park.md` proves current live measurement is insufficient. | Persist the kernel decision on each queued task, validate it at the execution seam, count real governed/refused/ungoverned events, and prove a planted bypass turns the gate red on restart-safe evidence. | E1/E5/E8/E11 |
| `SEC-02` | Advisory output acquires hidden authority: Cortex route choice, Howard preference, E12 belief or World Model simulation becomes authorization. | MEDIUM | CRITICAL | MITIGATING | `docs/nerva2/DEPENDENCIES.md`, `CONTRACT_REGISTRY.json`, `HYBRID_COGNITION_BOUNDARY.md`. | Typed authority fields, negative tests at every consumer and one sole `privileged_action` contract; owner/live action evidence still crosses Ultron. | E1/E4/E7/E12 |
| `SEC-03` | A generated or installed capability receives excessive permissions, escapes quarantine or runs outside the declared executor. | MEDIUM | CRITICAL | MITIGATING | `agents/core/acquisition/`, `agents/core/capability_manifests.py`, sandbox and signing/quarantine tests. | Deny-by-default manifest, typed permissions/privacy, conformance tests, sandbox proof, reviewed promotion and rollback. Three migrated capabilities must pass without bespoke bypass wiring. | E8/E11 |
| `SEC-04` | Security posture displayed to the owner differs from live runtime behavior. | MEDIUM | CRITICAL | MITIGATING | `docs/THREAT_MODEL.md`; recent guardrails live-resync work demonstrates this class is real. | Settings-to-runtime parity tests for every safety control, fail-closed unknown values and evidence-linked owner surfaces. | E10/E11 |
| `SEC-05` | External or ingested data carries prompt/tool instructions across trust boundaries. | HIGH | CRITICAL | MITIGATING | `docs/THREAT_MODEL.md` identifies taint as a flag rather than full data-flow analysis; channels, web and WorldView are untrusted inputs. | Typed origin/taint propagation through memory, retrieval, planning and action; adversarial cross-channel tests; tainted data cannot lower approval floors. | E2/E3/E8/E11 |
| `SEC-06` | Audit evidence is valid-looking but not tamper-evident or omits the action that matters. | MEDIUM | CRITICAL | MITIGATING | `agents/core/security/audit.py`, `agents/core/autonomy/audit_sink.py`, `docs/THREAT_MODEL.md`. | Keyed-chain posture must be explicit; action/decision/execution receipts share correlation IDs; full-table downgrade and missing-event probes remain red-capable. | E5/E11 |
| `SEC-07` | A compromised host or operating system defeats local controls. | LOW | CRITICAL | ACCEPTED | `docs/THREAT_MODEL.md` explicitly trusts the host. | Keep this boundary disclosed; reduce blast radius through least privilege, isolation, encrypted exports and recoverable backups. Do not market host compromise resistance as implemented. | E0/E11 |
| `PRIV-01` | Personal data is duplicated across Atlas, Episodes, embeddings, summaries and cognitive workspaces so export/delete misses derivatives. | HIGH | CRITICAL | OPEN | `agents/core/data_purge.py`, `agents/core/memory/bitemporal.py`, `agents/core/cognition/memory.py`, `docs/PRIVACY.md`. | Canonical source references, deletion lineage and tombstones; export→forget→scan and remote-store failure tests cover every derivative. | E2/E3/E6/E12/E11 |
| `PRIV-02` | Household, person, room or relationship data leaks into the wrong user-facing context, agent or delivery surface. | MEDIUM | CRITICAL | OPEN | Current system is single-user but carries family/home domains; `docs/THREAT_MODEL.md` lists no per-user isolation. | Subject/relationship/room privacy scopes at ingestion and query time, strict local defaults, cross-person leakage fixtures and inspect/delete controls. | E2/E3/E4/E10 |
| `PRIV-03` | Cognitive workspace, belief and trace retention grows into an unbounded sensitive transcript. | HIGH | HIGH | OPEN | E12 candidate workspace is intentionally deferred; current memory is already `MIXED` in `BASELINE.md`. | Typed bounded snapshots, retention class, expiry, compaction, deletion lineage and tests proving no hidden free-form transcript store. | E3/E6/E12 |
| `PRIV-04` | Cloud routing sends private context farther than the owner intended. | MEDIUM | CRITICAL | MITIGATING | `docs/PRIVACY.md`, strict-local agents, plugin network policy and egress monitor. | Per-request privacy constraints in Cortex, route evidence, cloud redaction/minimization, provider disclosure and negative strict-local tests. | E1/E8/E10 |
| `DATA-01` | Connector identity resolution duplicates one real entity or merges different people/assets incorrectly. | HIGH | HIGH | OPEN | `agents/core/memory/bitemporal.py`; Atlas identity service does not yet exist. | Stable source IDs, reversible merge/split, confidence and contradiction records, owner correction and three-domain identity tests. | E2 |
| `DATA-02` | A probability, inference, summary or model statement is promoted to an Atlas fact without adequate provenance. | HIGH | CRITICAL | MITIGATING | `HYBRID_COGNITION_BOUNDARY.md`; current fact/memory substrates are separate but no full admission contract exists. | Observation/fact/belief types, writer ownership, promotion gates, expiry and tests that high confidence never implies facthood. | E2/E3/E12 |
| `DATA-03` | Correlated sources are treated as independent evidence, causing false confidence. | HIGH | HIGH | OPEN | E12 risk named in the merged boundary; no source-dependence model is implemented. | Source lineage/dependence metadata, conservative aggregation, calibration suites and adversarial duplicated-source fixtures. | E2/E9/E12 |
| `DATA-04` | Temporal corrections are flattened, so stale facts or superseded beliefs reappear as current truth. | MEDIUM | HIGH | MITIGATING | `agents/core/memory/bitemporal.py` preserves valid/system time; consumers are not yet unified through Atlas/Episodes. | Canonical temporal query rules, supersession links, correction propagation and “what was true then?” evaluation. | E2/E3/E6 |
| `MEM-01` | Reflection creates self-confirming false lessons and then uses them as evidence for future decisions. | HIGH | CRITICAL | OPEN | `agents/core/learning/background_review.py`, `agents/core/autonomy/reflection.py`; current review is gated and does not prove downstream benefit. | Lesson proposals remain non-authoritative, cite counter-evidence, use held-out evaluation and require destination-owned promotion/demotion. | E6/E9 |
| `MEM-02` | Memory and index growth degrades latency, cost and retrieval quality indefinitely. | HIGH | HIGH | OPEN | `agents/core/cognition/memory.py`; consolidation/decay exist but long-running Nerva growth is unproven. | Storage/latency budgets, compaction/forgetting policy, growth simulation, restore and deletion parity. | E3/E6/E11 |
| `MEM-03` | Similarity-only retrieval admits irrelevant, stale, private or instruction-bearing memory. | HIGH | CRITICAL | OPEN | Current fused recall is `MIXED`; Continuity Core #731 identifies the missing trust/admission gate. | Admission decision with subject, time, provenance, contradiction, privacy, taint and abstention reason; cross-topic/person tests. Owner decision 2026-09-01: the narrow line "every production-recall admission decision records a taint/provenance reason" is proposed into #761's acceptance (comment for the epic owner); the approval-floor half stays with the kernel / SEC-05 owners. | E3/E6/E12 |
| `AUTO-01` | Night Shift invents work outside an approved goal or expands scope while running. | MEDIUM | CRITICAL | OPEN | `agents/core/autonomy/observer.py`, scheduler/missions and queue exist; approved goal/opportunity contracts do not. | Immutable GoalSpec, allowed domains/capabilities, time/budget ceiling, child-task lineage and scope-escape tests. | E5 |
| `AUTO-02` | Deliberation, retries, search or tool loops consume unbounded time, money or compute. | HIGH | HIGH | MITIGATING | Kernel budgets and circuit breakers exist; E12 may add deeper reasoning and curiosity. | Hard token/cost/time/step limits, EVC shadow telemetry, loop breakers, cancellation and worst-case tests. | E1/E5/E12 |
| `AUTO-03` | Partial, queued, null, mocked or failed work is reported as complete. | HIGH | CRITICAL | MITIGATING | `agents/core/observability/capability_registry.py`, `reality_harness.py`; baseline identifies plumbing-as-capability as dominant risk. | EvidenceReceipt required for completion, independent postcondition verification, explicit partial/checkpoint states and UI provenance labels. | E5/E10/E11 |
| `AUTO-04` | Restart/resume duplicates an external effect or loses an in-progress task. | MEDIUM | CRITICAL | OPEN | Durable queue and stuck-running reaper exist, but Night Shift checkpoint/idempotency contract is not defined. | Idempotency keys, persisted checkpoints, effect receipts, replay-safe compensation and crash-at-each-transition tests. | E5/E11 |
| `AUTO-05` | An irreversible action has no independent verification or workable rollback/compensation. | MEDIUM | CRITICAL | OPEN | Ultron can authorize/queue, but capability-level verifier and rollback are not universal. | Capability manifest requires verifier, reversibility and compensation; irreversible actions keep explicit human approval and observed-state evidence. | E8/E11 |
| `AUTO-06` | Proactivity creates interruption burden or optimizes activity instead of owner value. | HIGH | HIGH | OPEN | #757 defines time returned as the north star; no verified time-ROI loop exists. | Expected-value/time-ROI scoring, interruption budget, quiet hours and measured actual time saved/burden after execution. | E5/E10/E11 |
| `RES-01` | Benchmarks overfit hand-picked prompts, leak test data or reward the metric instead of real outcomes. | HIGH | HIGH | OPEN | `agents/core/observability/eval.py`, `reality_harness.py`; Research Lab contract is proposed only. | Versioned held-out suites, provenance, negative results, anti-leak review and owner-workflow outcome metrics. | E9/E12 |
| `RES-02` | Model quality is confused with routing, provider, hardware or infrastructure effects. | HIGH | HIGH | OPEN | Existing eval harness does not fully separate these dimensions, per `BASELINE.md`. | Record model/route/provider/host/version/cost/latency separately and reproduce comparisons across profiles. | E9 |
| `RES-03` | Causal or counterfactual narratives are accepted without intervention evidence or sensitivity analysis. | HIGH | HIGH | OPEN | World Model and E12 are not implemented; simulation boundary is architecture-only. | Facts/assumptions/interventions/estimates remain distinct; sensitivity, backtests and unsupported-causality warnings are mandatory. | E7/E12 |
| `RES-04` | An advanced method is adopted because it sounds sophisticated, despite no measurable advantage. | HIGH | HIGH | MITIGATING | `HYBRID_COGNITION_BOUNDARY.md` requires simple baselines, calibration and ablations. | Every promoted method beats a strong simpler baseline on a versioned suite with ablation, robustness and operational-value evidence. | E9/E12 |
| `RES-05` | Confidence appears precise but is uncalibrated or collapses under missing/out-of-distribution evidence. | HIGH | HIGH | OPEN | No production belief/calibration layer exists. | Brier/log loss, reliability buckets, OOD/missing-data tests, abstention quality and widening uncertainty under weaker evidence. | E9/E12 |
| `OPS-01` | Schema or backend migration loses personal data or cannot roll back. | MEDIUM | CRITICAL | OPEN | Existing stores and export/forget paths are diverse; Nerva adds cross-store references. | Versioned migrations, backup, forward/rollback fixtures, export/import reconstruction and index rebuild proof. | E0/E2/E3/E11 |
| `OPS-02` | Connector, provider or device API drift silently breaks a capability or changes semantics. | HIGH | HIGH | OPEN | ToolRPC/adapters are host/provider dependent and capability state is `MIXED`. | Version/health/compatibility metadata, contract tests, staged rollout, degradation reasons and rollback to previous implementation. | E8/E9/E11 |
| `OPS-03` | CI or hermetic tests are represented as owner-hardware proof. | HIGH | HIGH | MITIGATING | `DEPENDENCIES.md` separates CI and owner-hardware evidence; owner/live gates remain open. | EvidenceReceipt records environment; hardware-required cases fail/degrade honestly; E11 requires real-run artifacts. | E9/E11 |
| `OPS-04` | Missing model, network, DB, credential or hardware dependency produces a misleading success. | HIGH | HIGH | MITIGATING | Capability Registry/reality harness already model missing/seam/wired/verified states. | Fail-closed prerequisite checks, explicit degraded reason/needs, no default success and chaos/failure-injection coverage. | E8/E9/E10/E11 |
| `OPS-05` | Backup, restore, export or forget works in unit scope but fails across the complete live installation. | MEDIUM | CRITICAL | OPEN | `docs/PRIVACY.md` describes controls; E11 drills are not complete. | Destructive throwaway-host drills, remote-store failure evidence, integrity hashes and documented recovery time/data loss. | E11 |
| `PROD-01` | Existing components are renamed and rebuilt, increasing complexity without owner value. | HIGH | HIGH | MITIGATING | `BASELINE.md`, `REUSE_BUILD_RETIRE.md` and E0 drift guard. | Every new subsystem names reused code and explains why integration is insufficient; duplicate framework/database/scheduler additions are stop-review. | E0/all |
| `PROD-02` | Demo, seed, stub or null state is shown as live reality. | MEDIUM | CRITICAL | MITIGATING | Capability truth and recent honesty fixes; baseline states remain `LIVE/GATED/SEAM/STUB/MIXED`. | Provenance/state labels at API and UI, fixture isolation and tests that normal live mode cannot render demo success. | E10/E11 |
| `PROD-03` | Parallel PRs and manually maintained ledgers create contradictory dependencies, statuses or claims. | HIGH | HIGH | MITIGATING | The E0.2 review found and corrected dependency drift; #757 is the master ledger. | Small slices, builder/integrator separation, machine-readable program manifest, cycle/orphan/drift checker and same-movement ledger updates. | E0/#757 |
| `PROD-04` | Nerva becomes an AI research toy rather than returning useful time. | HIGH | CRITICAL | OPEN | #757 exit gate requires three recurring workflows and measured time saved. | Prioritize real recurring workflows, verified net hours returned, interruption burden and non-owner design-partner evidence. | E5/E10/E11 |
| `PROD-05` | Claims of consciousness, emotion or human equivalence obscure actual capability limits. | LOW | HIGH | MITIGATING | E12 and Continuity Core explicitly reject anthropomorphic claims. | Keep identity/personality as declared computational behavior, disclose uncertainty and reject unsupported sentience claims in product copy. | E4/E12 |
| `SUP-01` | Dependency, generated code or CI supply-chain compromise reaches the host. | MEDIUM | CRITICAL | MITIGATING | Hash-pinned locks, action pins, sandbox, SAST and secret scanning in `docs/THREAT_MODEL.md`. | Maintain lock/action integrity gates, provenance/signatures, quarantine and dependency-CVE response; generated code never bypasses review. | E8/E11 |

## 3. Stop-ship invariants

Any violation below blocks integration or release regardless of feature value:

1. **Ultron is the sole privileged-action authority.** No model, agent, UI, scheduler, Howard,
   E12 or World Model output can self-authorize.
2. **Prediction is not consent.** A likely owner preference cannot approve an action.
3. **Belief is not fact.** Probability or model confidence cannot write Atlas truth directly.
4. **Simulation is not mutation.** Scenario or causal output cannot change live state.
5. **Reflection cannot rewrite source evidence or approve its own lesson.**
6. **Every autonomous loop has an approved scope, budget, deadline, stop condition and loop breaker.**
7. **Every material completion claim has environment-appropriate verification evidence.**
8. **Deletion/export covers derived state and names anything it could not reach.**
9. **Demo, seed, stub, null and hardware-gated states remain visibly distinct from live.**
10. **A release is not declared from feature count, CI count or narrative plausibility.**

## 4. Risk acceptance and closure protocol

- The originating epic owns mitigation; E11 owns final consolidated evidence, not silent transfer
  of responsibility.
- A risk can move to `CLOSED` only with a test that can still fail. For hardware, connectors,
  privacy deletion, restore, migration and recurring autonomy, attach real-run evidence as well.
- A risk accepted as out of scope remains documented in owner-facing limits and cannot be described
  as solved.
- New Nerva PRs state which risk IDs they reduce, introduce or leave unchanged.
- If a mitigation adds another scheduler, database, agent framework, approval rail or capability
  registry, it must first pass the E0 reuse/duplication test.

## 5. Immediate risk burn-down order

The highest-leverage sequence is:

1. `SEC-01` — task-persisted Ultron mediation evidence at the execution seam;
2. `PRIV-01` / `MEM-03` — canonical lineage and trusted memory admission contracts;
3. `AUTO-03` / `OPS-03` — universal evidence receipts and environment truth;
4. `PROD-03` — machine-readable program manifest and drift checker;
5. `RES-01` / `RES-02` / `RES-05` — Research Lab benchmark and calibration substrate;
6. `AUTO-01` / `AUTO-04` / `AUTO-06` — bounded Night Shift goals, resume semantics and value;
7. `OPS-01` / `OPS-05` — continuity migration, restore and deletion drills.

## 6. Next E0 slice

E0.3b must reconcile ORIZONT 27–33, `BACKLOG.md`, `STATUS.md`, #757, #758 and the blocker
burn-down plan #778 against the merged dependency contracts and this risk register. It should then
create only the smallest executable issues for E1, E2, E3, E8 and E9. Until that reconciliation is
reviewed, E0 remains `BUILDING` and downstream implementation claims remain gated.
