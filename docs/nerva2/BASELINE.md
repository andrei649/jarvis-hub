# Nerva 2.0 E0 baseline — core substrate

> **Snapshot:** `main@616f4d3e348675d56f0f600cca2d622b58ded804` on 2026-08-02.  
> **Program:** #757 · **Epic:** #758 · **Slice:** E0.1.  
> This is the first code-evidenced pass. It does **not** close E0: physical adapters, every
> route, the full dependency DAG and the risk register remain follow-up slices. Open PRs are
> excluded from the snapshot; in particular, #756 is not treated as merged behavior.

## 1. Method

Prior vision and audit documents were used only as indexes. Runtime claims below were checked
against implementation modules and tests on the pinned commit.

Runtime state and strategic disposition are deliberately separate:

| Runtime state | Meaning |
|---|---|
| `LIVE` | Used by the normal runtime and produces durable state or a real effect without a replacement implementation. |
| `GATED` | Real implementation exists, but a feature flag, credential, dependency, host or explicit posture is required. |
| `SEAM` | Contract and wiring exist, but the default implementation is null/deferred or an owner-supplied adapter is still required. |
| `STUB` | Fixture, canned response, placeholder logic or documentation with no adequate implementation. |
| `MIXED` | The subsystem contains more than one of the above states and must not be summarized as simply “done”. |

The migration decision for each subsystem is recorded separately in
[`REUSE_BUILD_RETIRE.md`](REUSE_BUILD_RETIRE.md).

## 2. Executive verdict

Nerva 2.0 is an **evolution, not a rewrite**. The repository already contains unusually strong
substrates for governed execution, auditability, bounded autonomy, memory experiments,
capability truth and multiple user surfaces.

The principal missing value is not another agent framework. It is a small set of stable,
Nerva-owned contracts that join the existing parts:

1. a replayable Cortex decision record above models, agents and capabilities;
2. an Atlas identity/provenance model spanning the currently separate graphs and domains;
3. an Episode object above turns, facts and events;
4. an explainable Howard preference-hypothesis model that is never authorization;
5. a bounded Night Shift goal/opportunity loop;
6. governed lesson promotion and scenario simulation;
7. a benchmark and owner-facing evidence layer that measures real value.

The dominant product risk remains **plumbing presented as capability**. The canonical capability
registry has already started correcting this, but “wired” is not the same as a verified outcome.

## 3. Component baseline

| Nerva area | Runtime state | Existing implementation evidence | Honest finding | Nerva 2.0 contract still needed |
|---|---|---|---|---|
| **Interactive orchestration** | `LIVE` | `agents/core/orchestrator.py`, `agents/core/router.py`, `scripts/install_smoke.py` | The central orchestrator, specialist routing, chat completion and persistent completion seams are real. Seventeen named roles are useful specialists, but agent identity is currently a stronger architecture boundary than Nerva 2.0 needs. | Cortex request/candidate/decision contracts; explicit fast path for simple tasks; agents become candidates, not the operating system. |
| **Model-directed tool loop** | `GATED` | `agents/core/agent_runtime.py`, `agents/core/tool_rpc.py`, `agents/core/tool_rpc_runtime.py`, `tests/test_agent_runtime_v2.py` | `AgentToolRuntime` is bounded, fail-closed and approval-aware, but its constructor defaults to disabled and it depends on a tool-capable backend plus a non-empty allowlist. | Cortex must decide when the loop is justified, record why, and compare it with API/CLI/non-agent alternatives. |
| **Ultron / Action Kernel** | `MIXED` | `agents/core/kernel/__init__.py`, `agents/core/kernel/budget.py`, `agents/core/kernel/syscalls.py`, `tests/test_kernel_syscalls.py`, `tests/test_kernel_budget.py` | The grant/deny/queue facade, kill switch, capability checks, taint escalation, budgets and audit behavior are substantive. The kernel facade is still explicitly default-off for compatibility, while individual action families have been migrated in waves. | Preserve one mandatory privileged-action boundary; finish migration coverage and expose per-decision evidence rather than replacing the kernel. |
| **Approval queue and autonomous worker** | `LIVE` | `agents/core/autonomy/queue.py`, `agents/core/autonomy/worker.py`, `agents/core/autonomy/policy.py`, `agents/core/routers/autonomy.py` | Durable task state, policy decisions, approval handling, worker ticks, hold/retry behavior and kill-switch interaction are real. Downstream effects may still terminate in null clients. | Night Shift should reuse this state machine and add approved goals, opportunity provenance, checkpoints and independent verification. |
| **Observation and scheduling** | `LIVE` | `agents/core/autonomy/observer.py`, `agents/core/scheduler_service.py`, `agents/core/autonomy/missions.py`, `tests/test_autonomy_observer.py` | Host observations, state-change debouncing, recurring jobs and mission primitives exist. They are sources and schedulers, not a general autonomous work-discovery system. | Typed observation/event envelope; goal-scoped opportunity discovery; budget/deadline/stop contract shared with Night Shift. |
| **Capability truth / Verification Fabric** | `MIXED` | `agents/core/observability/capability_registry.py`, `agents/core/observability/reality_harness.py`, `tests/test_h27_registry_planning.py`, `tests/test_action_auth_matrix.py` | The registry derives `missing → seam → wired → verified → ga` records from existing systems and exposes runtime honesty. It is a catalog and evidence layer, not an executor. In-process verification state resets on boot unless a durable snapshot path is used. | Synapse SDK manifest as the authoritative capability contract; durable evidence receipts; Cortex candidate discovery over verified implementations. |
| **ToolRPC and execution plane** | `GATED` | `agents/core/tool_rpc.py`, `agents/core/tool_rpc_runtime.py`, `agents/core/execution/`, `tests/test_tool_rpc_h20_1.py`, `tests/test_tool_rpc_runtime.py` | The governed RPC spine, bounded output and local/container/remote execution concepts already exist. Availability and risk vary by host and configured implementation. | Versioned implementation descriptors, environment compatibility, permission declarations and reliability telemetry in Synapse. |
| **Bi-temporal knowledge** | `LIVE` | `agents/core/memory/bitemporal.py`, `agents/core/routers/memory_kg.py`, `tests/test_data_purge_memory.py` | Facts preserve valid time, ingest time and contradiction history. Persistence is deterministic and local. This is a strong primitive, but it is not yet a cross-domain Atlas ontology or identity service. | Canonical entity identity, provenance/confidence/privacy fields, source linkage, domain namespaces and scoped derived-data deletion. |
| **LivingMemory and recall** | `MIXED` | `agents/core/cognition/memory.py`, `agents/core/memory/`, `agents/core/data_purge.py`, `tests/test_living_memory_recall_eval.py` | Tiering, activation, selective encoding, re-projection and recall re-ranking are implemented, while cognition posture controls whether they participate in the live turn path. Existing stores remain record/turn/fact oriented. | Episode lifecycle and links, correction/merge/split semantics, situation/outcome/lesson retrieval and bounded consolidation metrics. |
| **Memory maintenance** | `GATED` | `agents/core/scheduler_service.py`, `agents/core/cognition/memory.py`, `tests/test_o26_p2_memory_consolidation.py` | NREM/REM-style maintenance and decay inspection are scheduled through existing services, with explicit-user deletion semantics. This is useful machinery, not yet an evidence-gated learning policy. | Reflection proposal and promotion contracts; contradiction repair; reversible consolidation; false-lesson and growth measurements. |
| **Per-turn learning / reflection seeds** | `GATED` | `agents/core/learning/background_review.py`, `agents/core/autonomy/reflection.py`, `tests/test_background_review.py` | The background reviewer performs one structured review, then code routes facts, corrections and skill proposals through governance. It is default-off and does not prove that a proposed lesson improved a later outcome. | Outcome-versus-expectation record, evidence-linked lesson hypothesis, held-out evaluation and explicit promotion/demotion. |
| **Synapse acquisition seeds** | `MIXED` | `agents/core/acquisition/runtime.py`, `agents/core/acquisition/resolver.py`, `agents/core/acquisition/research.py`, `agents/core/acquisition/llm_synth.py`, `agents/core/acquisition/quarantine.py`, `agents/core/acquisition/promotion.py`, `tests/test_h32_synthesis_pipeline.py` | Request, reuse-first resolution, research, synthesis, quarantine, signing and promotion components exist. The 2026-07-18 audit found that the end-to-end production caller and generated implementation quality were not yet equivalent to a dependable SDK. | Stable manifest/I-O schema, conformance kit, dependency resolution, staged telemetry, maintained-integration preference and rollback evidence. |
| **Atlas external and physical domains** | `MIXED` | `worldview/`, `agents/core/memory/bitemporal.py`, `agents/core/house/`, `agents/core/cameras/`, `agents/core/ambient/` | WorldView, provenance UI/API, house, camera and ambient modules now exist, but they do not yet share one canonical entity/state/event model. Most physical adapters require LAN services, credentials, consent or flags. | Atlas ontology and identity resolution first; adapters project into Atlas rather than each owning a parallel world model. |
| **Browser/desktop/media actuation** | `MIXED` | `agents/core/browser_agent.py`, `agents/core/media_director.py`, `agents/core/observability/operator_reality.py`, `agents/core/observability/media_reality.py`, `tests/test_h28_playwright_driver.py` | Governance rails and several real drivers exist, but host dependencies, flags and device configuration determine whether a real effect occurs. Null/deferred seams remain valid fallback states and must be visible. | Synapse implementation selection by risk/reliability; postcondition verification; no “success” card for a null/deferred outcome. |
| **Offline evaluation** | `LIVE` | `agents/core/observability/eval.py`, `.github/workflows/eval-nightly.yml`, `agents/core/observability/reality_harness.py` | Reproducible case execution, scoring and nightly/reality rails exist. The generic harness does not by itself separate model quality from routing, hardware, provider and infrastructure effects. | Research Lab task-suite versioning, hardware/provider profiles, cost/latency/reliability dimensions and evidence-based migration recommendations. |
| **HUD, mobile and channels** | `LIVE` | `frontend/`, `mobile/`, `agents/core/channels/`, `agents/core/web.py` | Multiple owner surfaces, approvals, tasks, status, memory and capability views exist. Product truth is spread across status, ticker, task, audit and specialized panels. | E10 coherent goals/work/evidence view; inspect-and-correct Atlas/Episodes/Howard; verified time-saved metric. |
| **Proof and release evidence** | `MIXED` | `agents/core/observability/reality_harness.py`, `docs/MANUAL_TESTING.md`, `docs/AUDIT.md`, `GO_LIVE_PLAN.md` | Unit/CI coverage and reality-harness rails are extensive, but feature count and rail verification are not substitutes for restart recovery, restore drills, multi-day autonomy and recurring owner workflows. | E11 evidence bundle: soak, failure injection, restore/export/delete, adversarial tests, design-partner use and measured owner value. |

## 4. What is already strong enough to protect

The following are migration invariants, not candidates for a rewrite:

- privileged effects remain mediated by Ultron/Action Kernel;
- approval, budget, taint, kill-switch and audit semantics remain fail-closed;
- local-first and strict-local privacy postures remain enforceable;
- source evidence is never rewritten by reflection or consolidation;
- deletion/export reaches derived stores, not only the chat transcript;
- runtime truth distinguishes unavailable, seam, wired and verified states;
- existing data formats receive explicit migrations before replacement.

## 5. Confirmed gaps that unblock child epics

The first implementation issues under E1–E3 and E8–E9 should target contracts rather than large
features:

1. **E1 / Cortex:** typed, replayable `DecisionRequest`, candidate and `DecisionRecord` with a
   no-action reference implementation over current routing data.
2. **E2 / Atlas:** identity/provenance envelope and projection adapter for the existing
   bi-temporal fact store; no new database in the first slice.
3. **E3 / Episodes:** schema plus deterministic manual episode boundaries linked to existing
   records; automatic boundary detection comes later.
4. **E8 / Synapse:** versioned manifest and conformance validator around three existing
   capabilities; no marketplace rewrite.
5. **E9 / Research Lab:** versioned benchmark case/result schema that records route, model,
   host profile, latency and cost separately.

## 6. Remaining E0 work

- reconcile the full ORIZONT 27–33 backlog against the Nerva 2.0 epic DAG;
- inspect all physical adapters and current default settings on the latest merged commit;
- produce `DEPENDENCIES.md` with explicit interfaces and data ownership;
- produce `RISKS.md` with threat, privacy, autonomy, migration and product-truth risks;
- update `BACKLOG.md` and `STATUS.md` once the complete E0 map is reviewed;
- create the five smallest implementation issues after the interface names are settled.

## 7. Evidence history used as an index

- `NERVA_VISION.md`
- `docs/research/2026-07-18-live-vs-plumbing-capability-audit.md`
- `docs/research/2026-07-25-nerva-vs-hermes-honest-gap-analysis.md`

These documents are valuable context but can become stale. The pinned code paths and tests above
are the authority for this snapshot.