# Nerva 2.0 — reuse, integrate, build, refactor, retire

> **Snapshot:** `main@616f4d3e348675d56f0f600cca2d622b58ded804` on 2026-08-02.  
> **Program:** #757 · **Epic:** #758 · **Slice:** E0.1.  
> Runtime evidence is in [`BASELINE.md`](BASELINE.md). This document records migration intent,
> not current readiness.

## 1. Decision vocabulary

| Decision | Meaning |
|---|---|
| `REUSE` | Keep the implementation and public behavior; add adapters or metadata only where needed. |
| `INTEGRATE` | Depend on a maintained external engine/service through a narrow Nerva adapter rather than reproducing it. |
| `BUILD` | Create Nerva-specific product logic that does not exist adequately in the repository or a maintained dependency. |
| `REFACTOR` | Preserve proven behavior/data while introducing a clearer contract or ownership boundary. |
| `RETIRE` | Remove only after callers/data are migrated and replacement behavior is proven. |

A row may contain more than one decision because migration is usually staged. `RETIRE` never means
immediate deletion.

## 2. Core decisions

| Subsystem | Decision | Keep / use | Change / build | Retirement condition |
|---|---|---|---|---|
| Orchestrator, router and specialist agents | `REUSE` + `REFACTOR` | Existing chat lifecycle, specialist expertise, backend selection and completion seams. | Add Cortex contracts above them. Treat agent/model/capability as candidate types with a common score/evidence interface. | Retire only duplicated routing branches made unreachable by Cortex and protected by replay tests. |
| AgentToolRuntime | `REUSE` | Bounded iterations, tool-call cap, deadlines, ToolRPC-only execution and approval pause. | Cortex policy decides whether the loop is proportionate and records the route. | No retirement planned; it becomes one execution strategy rather than the default symbol of agency. |
| Action Kernel / Ultron | `REUSE` | Grant/deny/queue, capability tokens, taint, budgets, loop breaker, kill switch and audit. | Complete privileged-path migration and attach durable decision evidence to Nerva work records. | Retire compatibility bypasses only after action-auth and reality-harness coverage prove zero bypasses. |
| Autonomy queue, policy and worker | `REUSE` + `REFACTOR` | Durable task states, approval lifecycle, worker recovery and policy enforcement. | Add goal ID, opportunity evidence, workspace/checkpoint, verification receipt and parent work-run fields through migrations. | Retire parallel ad-hoc background job ledgers after all autonomous work uses the shared state machine. |
| Observer, missions and scheduler | `REUSE` | Debounced signals, mission primitives and recurring execution. | Standardize observation/event envelopes and goal-scoped opportunity generation. | Retire bespoke schedulers only when equivalent cadence, recovery and observability are demonstrated. |
| Capability Registry and Verification Fabric | `REUSE` + `REFACTOR` | Runtime honesty lifecycle, derived records, reality harness and demotion controls. | Make Synapse manifests the stable input; add durable verification receipts and implementation-level telemetry. | Retire hand-maintained capability-status tables after generated views cover their owner use cases. |
| ToolRPC and execution environments | `REUSE` | Governed allowlist, bounded outputs and host/container/remote seams. | Add versioned environment compatibility, permission declarations and reliability/cost observations. | Retire direct tool invocation paths after all privileged implementations cross ToolRPC or a documented kernel-equivalent adapter. |
| Bi-temporal KG | `REUSE` + `REFACTOR` | Valid/transaction time, contradiction history, local deterministic persistence and existing API behavior. | Atlas entity identity, provenance, confidence, privacy and projection contracts around the store. | Do not replace storage in the first Atlas phase. A later database change requires dual-read migration and deletion/export parity. |
| LivingMemory and recall fusion | `REUSE` + `REFACTOR` | Tiering, activation, re-projection, temporal re-rank, current vector/graph retrieval and explicit deletion. | Episodes become the semantic unit above existing records; add source links and lifecycle operations without duplicating raw transcripts. | Retire duplicate raw copies and legacy projections only after backfill, recall comparison and purge tests pass. |
| Background review and reflection seeds | `REUSE` + `REFACTOR` | Structured single-call review, anti-capture rules, governed fact/correction/skill routing. | Add expectation/outcome comparison, lesson hypotheses, held-out evaluation and reversible promotion. | Retire direct durable-fact promotion paths that cannot show evidence and confidence. |
| Acquisition pipeline | `REUSE` + `REFACTOR` | Reuse-first resolution, research, quarantine, signing, promotion, rollback concepts and existing stores. | Synapse SDK manifest, conformance kit, dependency solver, maintained-integration preference and operational telemetry. | Retire placeholder skill bodies and fixture-only synthesis lanes once real generated/integrated capabilities pass the same SDK gates. |
| Offline eval and reality harness | `REUSE` + `REFACTOR` | Offline runners, nightly store, rail verification and existing task packs. | Research Lab schema separates task, route, model, host, provider, latency, cost, reliability and privacy result dimensions. | Retire unversioned benchmark fixtures and prose-only model recommendations after reproducible reports replace them. |
| HUD, mobile and channels | `REUSE` + `REFACTOR` | Existing communication surfaces, approval queue, tasks, status, memory and capability views. | E10 composes goals, active work, evidence, corrections, cost and measured value into one owner-facing model. | Retire duplicate panels only after essential desktop/mobile parity and owner workflow checks. |
| WorldView, Signal Layer, house, cameras and ambient | `REUSE` + `INTEGRATE` + `REFACTOR` | Existing domain adapters, provenance work, event ingestion and reality harnesses. | All domains project entities/events/state into Atlas contracts instead of defining parallel identity models. | Retire domain-local duplicate identity/state stores after Atlas projection and rollback are proven. |
| Browser, desktop and media drivers | `REUSE` + `INTEGRATE` | Existing governance, Playwright/host/device adapters, driver registries and verification seams. | Synapse selects the lowest-risk verified implementation; every effect has a postcondition or an honest unverifiable result. | Retire null/deferred responses that look successful; keep explicit unavailable seams for safe degradation. |

## 3. Nerva-specific components to build

These are the main proprietary/product-value layers. They should be small, typed and independently
measurable rather than new all-knowing agents.

### E1 — Cortex

- `DecisionRequest`: goal, context references, constraints, privacy, authority, deadline and budget.
- `Candidate`: capability/model/agent/workflow implementation with measured attributes.
- `DecisionRecord`: hard constraints, candidate scores, selected route, fallbacks and evidence.
- deterministic replay and bounded replan behavior.

Cortex must consume the Capability Registry, Atlas snapshots, Ultron policy and Research Lab results;
it must not reimplement them.

### E2 — Atlas

- canonical entity identity and alias resolution;
- source/provenance/confidence/privacy envelope;
- event versus entity versus current-state separation;
- projection APIs for existing KG, WorldView, house, device, asset and project domains;
- scoped query/export/delete contracts.

Atlas should start as contracts and projections around existing stores, not as a database migration.

### E3 — Episodes

- episode identity, timeline, participants, goals, evidence, outcomes, significance and lessons;
- `open`, `settled`, `consolidated`, `superseded` lifecycle;
- manual boundaries first, automated boundary proposals later;
- merge/split/correct/delete operations with audit and source preservation.

Episodes reference existing records; they do not become another raw transcript archive.

### E4 — Howard / Digital Twin

- contextual preference and decision-pattern hypotheses;
- evidence categories, confidence, recency and scope;
- prediction with explanation, alternatives and calibration;
- inspect/correct/disable/delete controls;
- strict type separation between `prediction` and `authorization`.

### E5 — Night Shift

- approved goal backlog and scope;
- opportunity record with evidence and expected value;
- bounded work run with deadline, budget, stop reason and checkpoints;
- independent verification pass;
- morning brief generated from receipts, never from unsupported narrative.

### E6 — Reflection and consolidation policy

- expectation/outcome comparison;
- lesson hypothesis, counter-evidence and confidence;
- evaluation and reversible promotion;
- contradiction and staleness repair;
- memory growth, false-lesson and usefulness metrics.

### E7 — World Model

- immutable baseline snapshot plus explicit assumptions;
- domain simulation adapters;
- uncertainty and sensitivity output;
- comparison/backtest contract;
- no direct action authority.

### E8 — Synapse Skills SDK

- versioned manifest and typed inputs/outputs;
- permissions, privacy, risk, dependencies and environment compatibility;
- conformance tests and benchmark interface;
- staged lifecycle, telemetry, rollback and provenance;
- reuse/integration preference before synthesis.

### E9 — Research Lab

- versioned real-task suites with sanitized/local-only fixtures;
- route/model/host/provider separation;
- quality, latency, cost, reliability and privacy scoring;
- reproducible migration recommendation with confidence and rollback plan.

### E10 — Owner experience

- goals and active-work model;
- evidence-linked completion/failure;
- unified decision/approval inbox;
- Atlas/Episodes/Howard inspect-and-correct surfaces;
- measured cost, reliability and verified time saved.

## 4. Integrate rather than build

Nerva should use maintained engines behind governed adapters. Existing repository adapters remain the
starting point.

| Need | Integration direction | Nerva ownership |
|---|---|---|
| LLM inference | Existing local and cloud provider adapters | privacy/risk routing, budgets, evidence and fallback policy |
| Browser automation | Playwright and structured accessibility paths | action hierarchy, policy, verification and rollback |
| Desktop automation | OS-native/host drivers | authorization, isolation, postconditions and honest availability |
| Smart home | Home Assistant/Homebridge/Tuya adapters | Atlas model, household authority, routines and cross-domain reasoning |
| Cameras/NVR | Frigate/ONVIF adapters | consent, event correlation, retention, privacy zones and governed actions |
| Voice STT/TTS | Installed local engines or configured providers | identity, privacy, delivery policy and experience continuity |
| Search/news/market data | Existing provider/plugin adapters | source provenance, trust, caching, synthesis and action gating |
| Vector/embedding/model storage | Existing repository backends and provider adapters | episode semantics, deletion, versioning and retrieval policy |

No Nerva epic should begin by building a new foundation engine unless the E0 map documents a
measured deficiency that an adapter cannot close.

## 5. Retirement candidates

The following are candidates, not immediate deletions:

1. **Quiet mock/deferred success.** A null or mock path may remain, but its result must be typed as
   unavailable/deferred and must never produce a success claim.
2. **Manual status prose as runtime truth.** `STATUS.md` remains the owner snapshot; generated
   capability/evidence data should replace hand-maintained readiness claims where possible.
3. **Agent-to-agent chatter as default orchestration.** Multi-agent work remains available when a
   measured task needs it; simple tasks take the smallest adequate route.
4. **Parallel capability catalogs.** Plugin, skill, component and action metadata should project
   into Synapse/Capability Registry contracts rather than diverge.
5. **Parallel identity graphs.** House, device, WorldView, project, person and asset identities
   should converge through Atlas aliases and projections.
6. **Duplicate raw memory.** Episodes link to source records; they do not copy every message, fact,
   vector and summary into another store.
7. **Direct privileged action paths.** Compatibility paths retire after kernel coverage and
   reality-harness evidence prove the replacement.
8. **Fixture-only generated skills as product capability.** Fixtures remain tests; production
   readiness requires SDK conformance and real outcome verification.

## 6. Migration invariants

Every Nerva 2.0 migration must preserve:

- fail-closed governance and explicit authority;
- local-first/privacy posture and strict-local operation where declared;
- data provenance, contradiction history and explicit deletion;
- current owner workflows until replacement parity is verified;
- rollback or a documented irreversible migration approval;
- honest state labels (`missing`, `seam`, `wired`, `verified`, `ga`);
- no automatic implication that a preference prediction is consent;
- no claim of completion without test or real-run evidence.

## 7. Next E0 decisions

The next slice should create `DEPENDENCIES.md` and settle interface ownership for:

- Cortex ↔ Capability Registry/Synapse;
- Cortex ↔ Atlas snapshot;
- Cortex/Night Shift ↔ Ultron and autonomy queue;
- Episodes ↔ source records/LivingMemory/Atlas;
- Reflection ↔ Episodes and lesson promotion;
- Research Lab ↔ decision telemetry and capability evidence.

Only after those interfaces are named should the first E1–E3/E8–E9 implementation issues be
created.