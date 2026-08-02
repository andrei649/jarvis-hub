# Nerva 2.0 E0.2 — dependency and interface ownership

> **Snapshot:** `main@a2766a98d16be40389ca587c6677c9e5e5d6e270` on 2026-08-02.  
> **Program:** #757 · **Epic:** #758 · **Slice:** E0.2.  
> E0.1 established runtime truth and migration intent. This slice names the contracts and
> ownership boundaries required before E1–E3, E8–E9 and E12 can build safely in parallel.

The machine-readable companion is [`CONTRACT_REGISTRY.json`](CONTRACT_REGISTRY.json). It is a
planning and integrity artifact, not a second runtime capability registry. It records the acyclic
delivery prerequisites separately from runtime feedback edges. E12's provisional schemas remain
outside the canonical contract list until E12.1 exercises typed fixtures and calibration tests;
its dependency and authority boundary are canonical now.

## 1. Dependency rule

Nerva's core flow is:

```text
Evidence
  ↓
Atlas state / Episodes / capability evidence
  ↓
Cortex decision
  ↓
Ultron authorization
  ↓
Synapse implementation + bounded execution
  ↓
Verification receipt
  ↓
Reflection proposal / Research Lab result
```

The arrows are data and authority boundaries, not permission to import every upstream package.
No model, agent, preference predictor, simulator, metacognitive controller, UI or scheduler may
bypass Ultron for a privileged effect.

## 2. Delivery prerequisite DAG — acyclic

Only build-time prerequisites belong in this graph. A runtime consumer or feedback edge never
becomes a delivery blocker merely because it may improve an already working capability.

```text
E0 baseline and contracts
 ├─> E1 Cortex
 ├─> E2 Atlas ──> E3 Episodes ──┬─> E4 Howard
 │                              └─> E6 Reflection
 ├─> E8 Synapse Skills SDK
 └─> E9 Research Lab

E0 + E1 + E2 + E3 + E6 ─────────────> E5 Night Shift
E1 + E2 + E3 + E4 ──────────────────> E7 World Model
E1 + E2 + E3 + E6 + E9 ─────────────> E12 Hybrid Cognition
E1 + E2 + E5 + E6 ──────────────────> E10 Experience
All mandatory production bars ──────> E11 Proof and release
```

The exact direct blockers for the first bounded E5 Night Shift are:

```text
E0 Baseline + E1 Cortex + E2 Atlas + E3 Episodes + E6 Reflection
```

E4 Howard, E8 Synapse Skills SDK, E9 Research Lab and E12 Hybrid Cognition may improve later Night
Shift versions, but they are not direct prerequisites for its first bounded implementation. The
first version may reuse current capability manifests, ToolRPC, the Action Kernel, scheduler,
queue/worker and verification substrate while those streams mature independently.

A downstream epic may prototype against versioned fixtures, but it cannot claim completion until
its upstream live contract, migration path and deletion/export behavior are verified. E12 may run
shadow-mode experiments early; it cannot become production routing, live-state mutation or action
authority before its declared dependencies are real and tested.

### 2.1 Runtime cognitive feedback graph — cycles expected

Runtime feedback is deliberately separate from delivery order:

```text
Observe → Atlas → Cortex → Ultron → Synapse / Executors → Verification
   ↑                                                       ↓
   └──────── Episodes ← Outcomes / Evidence ←──────────────┘
                  ↓
              Reflection ──advisory──> Atlas / Cortex

Howard ──preference prediction only──> Cortex
E12 ──belief / metacognition only────> Cortex / World Model / Research Lab
```

These feedback edges may be cyclic because the system learns from outcomes. They never grant
authority, never mutate live state by themselves and are not delivery prerequisites. Every
privileged effect still crosses Ultron.

## 3. Contract ownership summary

| Contract | Owner | Existing substrate reused | Primary consumers | Authority |
|---|---|---|---|---|
| `nerva.observation.v1` | Atlas | `autonomy/observer.py`, scheduler and domain adapters | Atlas, Episodes, Night Shift | Evidence only |
| `nerva.atlas.snapshot.v1` | Atlas | `memory/bitemporal.py`, memory KG routes | Cortex, Episodes, Howard, World Model, E12 | Read-only snapshot/query |
| `nerva.capability.v1` | Synapse | capability manifests + Capability Registry | Cortex, Research Lab, Experience | Describes; does not execute |
| `nerva.decision.v1` | Cortex | orchestrator, router and bounded agent runtime | Night Shift, interactive runtime, Experience, E12 | Chooses route; does not authorize |
| `nerva.action.v1` | Ultron | Action Kernel, policy, queue, worker and audit | Every privileged implementation | Sole privileged-action authority |
| `nerva.episode.v1` | Episodes | LivingMemory, turn/fact stores, reflection inputs | Cortex, Howard, Reflection, World Model, E12 | Memory record only |
| `nerva.lesson.v1` | Reflection | BackgroundReviewer and DailyReflector | Episodes, Howard, Synapse, E12, human review | Proposal until promoted |
| `nerva.preference.v1` | Howard | persona/cognition, feedback and approved history | Cortex, Experience, World Model | Prediction; never consent |
| `nerva.work-run.v1` | Night Shift | missions, scheduler, task queue and worker | Experience, Reflection, Research Lab | Delegates actions to Ultron |
| `nerva.scenario.v1` | World Model | Atlas snapshots and decision constraints | Owner/Cortex advisory use | Simulation only; no mutation |
| `nerva.benchmark.v1` | Research Lab | offline eval + reality harness | Cortex, Synapse and E12 evidence | Evaluation only |
| `nerva.evidence.v1` | Verification Fabric | reality harness, audit and capability readiness | All completion claims, including E12 | Proves/limits a claim; no authority |

### 3.1 E12 ownership boundary

E12 / Hybrid Cognition Lab owns only future **advisory** belief, hypothesis and metacognitive
records once E12.1 proves their schemas. It may rank reasoning modes, represent competing
hypotheses and recommend verification. It may not:

- write Atlas facts or Episode history;
- convert probabilities into facts or Howard predictions into consent;
- authorize tools, actions or autonomous work;
- mutate live state from a causal or simulation result;
- change production routing without the normal reviewed Cortex/Synapse path.

The detailed boundary and adoption gate live in
[`HYBRID_COGNITION_BOUNDARY.md`](HYBRID_COGNITION_BOUNDARY.md).

## 4. Interface contracts

### 4.1 `nerva.observation.v1` — ObservationEnvelope

**Owned by Atlas.** Producers include host observers, channels, WorldView/Signal Layer, house,
camera, media and future vehicle adapters.

Minimum fields include stable event/version IDs, source identity and immutable record reference,
observed and ingestion time, typed payload, subject/privacy scope, source confidence, integrity,
correlation/causation references, retention class and deletion lineage. Producers publish evidence;
they do not write directly into Howard, Episodes or a private Atlas store.

### 4.2 `nerva.atlas.snapshot.v1` — AtlasQuery / AtlasSnapshot

**Owned by Atlas.** The current bi-temporal KG supplies valid time, ingest time and contradiction
history; Atlas adds identity, provenance, confidence, privacy and domain projection. Consumers
receive immutable snapshots or bounded query results. Cortex, Howard, Episodes, World Model and E12
must not receive Atlas's database handle or mutate facts through read APIs.

### 4.3 `nerva.capability.v1` — CapabilityDescriptor

**Owned by Synapse.** It evolves existing capability manifests and `CapabilityRecord`; it does not
replace the Capability Registry. It carries typed I/O, implementation/environment requirements,
permissions, privacy, risk, reversibility, readiness, health/reliability/cost evidence and
promotion/rollback metadata. A descriptor never grants permission to run.

### 4.4 `nerva.decision.v1` — DecisionRequest / Candidate / DecisionRecord

**Owned by Cortex.** The first implementation wraps current router/orchestrator evidence in
no-action shadow records. A DecisionRecord captures candidates, hard-constraint rejections,
quality/risk/privacy/latency/cost estimates, route/fallbacks, confidence, limitations, required
approval/verification and a replay fingerprint. Cortex chooses a route; it cannot authorize,
mark work complete or treat a belief as fact.

### 4.5 `nerva.action.v1` — ActionRequest / ActionDecision / ActionReceipt

**Owned by Ultron.** Existing `Action`, `Capability`, `Budget`, `Decision`, task queue and worker
remain the live authority and execution state machine. Every privileged capability crosses this
boundary and produces authorization, approval/task reference, execution identity, observed result,
verification, rollback and audit evidence. New Nerva contracts compose this boundary; they never
replace it with model reasoning.

### 4.6 `nerva.episode.v1` — EpisodeRecord

**Owned by Episodes.** An Episode is a coherent experience above turns, events and facts. It stores
identity, lifecycle, participants, Atlas references, goals, decisions, actions, outcomes,
significance, evidence-linked summaries and merge/split/supersede history. It references source
records rather than duplicating raw transcripts.

### 4.7 `nerva.lesson.v1` — OutcomeObservation / LessonProposal

**Owned by Reflection.** Reflection compares expected and observed outcomes and may propose a lesson
with evidence, confidence, counter-evidence, scope, expiry and contradiction links. Destinations own
promotion. Reflection cannot rewrite evidence or self-approve sensitive learning.

### 4.8 `nerva.preference.v1` — PreferenceHypothesis / PreferencePrediction

**Owned by Howard.** Predictions carry context, evidence categories, confidence, calibration band,
recency, alternatives and uncertainty. They must state that they are not consent. Howard may advise
ranking; it may not authorize or silently promote a weak hypothesis to fact.

### 4.9 `nerva.work-run.v1` — Goal / Opportunity / WorkRun

**Owned by Night Shift**, built on missions, scheduler, task queue and worker. A run includes approved
goal/scope, opportunity evidence, expected value, budget, deadline, workspace/checkpoint, stop
conditions, child action references and independent verification receipts. Every external effect
still crosses Ultron.

### 4.10 `nerva.scenario.v1` — ScenarioRequest / ScenarioResult

**Owned by World Model.** A scenario uses an immutable Atlas snapshot, explicit assumptions,
constraints and preference advice. Results separate facts, assumptions and estimates and include
uncertainty, sensitivity and provenance. Simulation never mutates live Atlas and has no action
authority.

### 4.11 `nerva.benchmark.v1` — BenchmarkCase / BenchmarkRun / BenchmarkResult

**Owned by Research Lab.** It extends offline eval and the reality harness with separate task, route,
model, provider, host/hardware, latency, cost, reliability and privacy dimensions. Research Lab may
recommend a migration; it may not change production routing automatically.

### 4.12 `nerva.evidence.v1` — EvidenceReceipt

**Owned by the Verification Fabric.** Material completion claims resolve to typed receipts containing
claim, target, expected state, method, observed state, environment, timestamp, confidence,
limitations and source artifacts. CI proof must not be represented as owner-hardware proof.

### 4.13 E12 provisional records — schema deferred to E12.1

`nerva.belief.v1`, `nerva.metacognition.v1` and a typed cognitive workspace remain candidates, not
canonical contracts. E12.1 must first provide privacy-safe fixtures, calibration tests, simpler
baselines, ablations and shadow-mode evidence. Until promotion, the canonical rule is only:
**advisory belief/reasoning records, no authorization and no live-state mutation**.

## 5. Write ownership and forbidden shortcuts

| Data/decision | Sole writer or authority | Forbidden shortcut |
|---|---|---|
| Canonical entity/fact/state projection | Atlas | connector or probabilistic belief becoming global truth directly |
| Episode lifecycle | Episodes | a reflector or cognitive workspace silently creating settled history |
| Capability lifecycle and implementation metadata | Synapse | hidden tool wiring invisible to the registry |
| Route decision record | Cortex | free-form agent voting or metacognition changing production routing directly |
| Privileged authorization | Ultron / Action Kernel | model, agent, E12, Howard, Night Shift or UI self-authorization |
| Lesson promotion | destination owner plus policy/human gate | Reflection promoting its own proposal as fact |
| Preference hypothesis | Howard | prediction stored or used as owner consent |
| Belief / metacognitive advice | E12 after schema promotion | probability becoming Atlas fact or authorization |
| Scenario result | World Model | simulation writing to live Atlas or scheduling an action |
| Benchmark evidence | Research Lab | benchmark directly changing production routing |
| Completion status | Verification/evidence view | queued, wired, mock or null result presented as success |

## 6. Layering and import rules

1. Contract values are plain typed data and cannot import HTTP routers, HUD code or provider SDKs.
2. Atlas and Episodes expose queries/references; consumers do not receive private database handles.
3. Cortex may read Synapse, Atlas, Howard, Research Lab and future E12 views, but writes only
   DecisionRecords.
4. Ultron remains lower-level than Cortex/Night Shift/Howard/E12 and must not depend on their policy.
5. Synapse implementations invoke ToolRPC/adapters only after any required Ultron decision.
6. Reflection reads outcomes/evidence and writes proposals; destination modules own promotion.
7. World Model, Research Lab and E12 experiments run against snapshots/fixtures and cannot mutate
   live state.
8. Experience/HUD/mobile are consumers and correction surfaces, not hidden sources of authority.

## 7. Migration order

The first child slices are contract-first and behavior-preserving:

1. **E1:** no-action decision records over current candidate/routing data.
2. **E2:** Atlas identity/provenance envelopes and a projection around `BiTemporalKG`; no new DB.
3. **E3:** Episode schema and deterministic manual boundaries linked to existing records.
4. **E8:** validate a versioned Synapse manifest against three existing capabilities.
5. **E9:** persist versioned benchmark cases/results with route/model/host dimensions separated.
6. **E12.1:** only after E0.3 and upstream fixture ownership are clear, add typed belief and
   metacognitive fixtures plus calibration tests in shadow mode.

Only after these schemas are exercised should Night Shift, Howard learning, World Model or Hybrid
Cognition depend on them operationally.

## 8. Compatibility and evidence rules

- contracts are versioned; breaking changes require migration notes and compatibility tests;
- personal stored-data changes require backup, forward migration, rollback and purge/export tests;
- references remain resolvable or carry an explicit tombstone after deletion;
- unavailable/default-off/stubbed state remains explicit at every boundary;
- every autonomous or deliberative loop has budget, deadline, stop condition and loop-breaker;
- all privileged capabilities are deny-by-default;
- probabilities remain labeled beliefs with provenance, calibration and expiry;
- no completion claim exists without an EvidenceReceipt appropriate to the environment;
- E0.2 changes no runtime behavior and does not close #758.

## 9. Next E0 slice

E0.3 should add `RISKS.md`, including false precision, correlated evidence, authority leakage,
runaway deliberation, benchmark overfitting, unsupported causal claims, curiosity scope escape and
cognitive-workspace privacy growth. It must then reconcile E0 against ORIZONT 27–33, `BACKLOG.md`
and `STATUS.md`. Only after that review should the first executable child issues be split from
#759, #760, #761, #766, #767 and #773.
