# Nerva 2.0 — Evidence-based baseline

Status: E0 discovery baseline  
Parent: #758  
Program: #757

This document records the starting point for Nerva 2.0. It deliberately separates live capabilities from default-off, stubbed, demo-backed, hardware-gated and documentation-only work. File paths are the evidence anchors; implementation PRs must validate assumptions against code and tests before relying on them.

## Executive baseline

Nerva is not a greenfield project. The repository already contains a broad personal-intelligence platform with mature governance, memory, channels, UI, evaluation and execution substrates. The highest-value Nerva 2.0 work is therefore consolidation and connection—not adding more agents or parallel frameworks.

The strongest existing assets are:

- the Action Kernel, contracts, approvals, budgets, audit and kill switches;
- the Verification Fabric and reality-harness approach;
- memory fusion, LivingMemory, CoreMemory and the bi-temporal knowledge graph;
- the Capability Registry and governed skill lifecycle;
- ToolRPC plus local, Docker and SSH execution environments;
- the scheduler, observer, background review and per-turn learning loop;
- HUD, mobile, voice and multi-channel experience surfaces;
- WorldView, Signal Layer and distributed node foundations.

The largest product gaps are:

- a deterministic Cortex meta-decision layer above existing routing;
- Atlas as one canonical, provenance-rich model of personal reality;
- Episodes as an experience-centric memory layer;
- an explainable Digital Twin that never substitutes prediction for consent;
- Night Shift as a bounded autonomous work loop with independent verification;
- a stable Skills SDK and acquisition loop;
- a governed World Model for what-if simulation;
- a continuous Research Lab tied to real Nerva task suites;
- owner-facing evidence and value reporting across all of the above.

## Component inventory

| Nerva area | Existing substrate | Current posture | E0 conclusion |
|---|---|---|---|
| Observe | `core/autonomy/observer.py`, passive capture, channels, voice, ingestion, heartbeat | Mixed live/default-off; external hardware and connector coverage varies | Reuse event capture, standardize event contracts |
| Understand | memory fusion, LivingMemory, CoreMemory, bi-temporal KG, ingestion provenance | Live foundations, fragmented domain semantics | Reuse stores; build Atlas ontology and Episodes |
| Decide | orchestrator, 17 specialist agents, model routing/fallback, `agent_runtime.py`, autonomy policy | Live but optimized around agents/models rather than capabilities and explicit trade-offs | Refactor behind Cortex decision contracts |
| Act | Action Kernel, automation contracts, brokers, ToolRPC, sandbox, execution environments | Governance mature; some physical/browser drivers remain stubbed or integration-dependent | Reuse Ultron boundary; unify capability invocation |
| Verify | reality harness, capability states, action verification patterns, CI/evals | Strong substrate but uneven adoption | Reuse and make mandatory for Nerva epics |
| Learn | background review, DailyReflector, LivingMemory consolidation/decay, skill curator, feedback | Live/default-off mix; lacks one governed outcome-learning contract | Refactor into Reflection and consolidation pipeline |
| Cortex | orchestrator, router, budgets, eval telemetry | Partial substrate only | Build meta-decision layer, not another agent |
| Atlas | bi-temporal KG, WorldView, Signal Layer, node/device concepts | Substantial pieces, not one canonical reality model | Build ontology, identity, provenance and query contract |
| Episodes | turns, memories, events, daily reflection | No first-class episode lifecycle | Build on existing stores without raw-data duplication |
| Howard | personas, preferences, feedback, owner context | Static/fragmented preference substrate | Build explainable prediction and correction model |
| Night Shift | scheduler, task budgets, approval queue, ToolRPC, run history | Components exist; autonomous work-discovery loop does not | Build bounded loop with independent review |
| Synapse | capability registry, skill lifecycle, signing, quarantine, marketplace | Strong internal substrate; contracts need SDK stabilization | Refactor and productize as Skills SDK |
| Research Lab | eval store, nightly workflows, model telemetry | Existing tests are broad but not yet a continuous migration lab | Build versioned real-task suites and recommendation reports |
| Experience | HUD v3, mobile, approvals, tasks, ticker, audit, status | Broad surfaces; fragmented owner narrative | Reuse UI, add unified executive evidence model |
| World Model | scenario-like reasoning can be prompted ad hoc | No isolated, provenance-bound simulation service | Build after Atlas, Episodes and Howard |

## Existing assets to preserve

### Ultron / governance boundary

The Action Kernel and associated contracts are the non-negotiable authority boundary. Nerva 2.0 must not introduce a second approval, permission or action-dispatch system. Every privileged path remains kernel-mediated, budgeted, audited and kill-switch aware.

Evidence families to inspect in implementation slices:

- action kernel and capability authorization;
- automation contracts;
- approval queue and risk tiers;
- taint/origin propagation;
- audit chain and redaction;
- loop breaker and runtime security posture.

### Memory and knowledge

LivingMemory, CoreMemory, recall fusion and the bi-temporal KG are data assets, not prototypes to discard. Nerva 2.0 should add stronger schemas and lifecycle semantics while preserving export, deletion, provenance and migration compatibility.

### Synapse execution plane

ToolRPC, sandboxing, skill lifecycle and execution environments already provide much of the capability plane. The missing layer is a stable versioned SDK, conformance suite and acquisition policy—not another plugin framework.

### Experience surfaces

HUD and mobile already expose approvals, tasks, memory, graph, skills and status. Nerva 2.0 should avoid a UI rewrite. New work should introduce a shared owner-facing evidence model and progressively adapt existing surfaces.

## Known non-live or incomplete areas

These must never be represented as production reality without fresh evidence:

- real browser/desktop actuation where Null drivers remain in use;
- camera/RTSP/ONVIF/Frigate capabilities not yet integrated;
- complete Home Assistant state, presence and room graph integration;
- full media-device abstraction and cross-room presentation;
- vehicle telemetry beyond connector-specific or planned work;
- autonomous capability acquisition end to end;
- design-partner proof, multi-day soak and restore drills;
- any demo/seed data rendered through HUD surfaces.

## Nerva 2.0 migration principles

1. Preserve current behavior behind explicit adapters before replacing internals.
2. Prefer one canonical contract per concept: decision, event, entity, episode, capability, action, verification and learning outcome.
3. Do not duplicate raw personal data to create higher-level models; store references, provenance and derived summaries.
4. Keep prediction separate from authorization.
5. Keep simulation separate from live state mutation.
6. Make default-off, stubbed, demo and hardware-gated states visible in APIs and UI.
7. Require evidence-linked status updates in #757 and the relevant epic.

## Immediate implementation order

1. Stabilize typed contracts and inventories before broad implementation.
2. Start Cortex, Atlas, Skills SDK and Research Lab as parallel foundations after E0.
3. Build Episodes on Atlas identity/provenance contracts.
4. Build Reflection and Howard on Episodes.
5. Build Night Shift only after Cortex, Atlas, Episodes, Skills and verification contracts are usable.
6. Build the World Model after Atlas, Episodes and Howard.
7. Treat proof and owner value as release work, not post-release polish.

## Open evidence tasks

- verify module paths and live/default-off status against current `main` after active productionization PRs merge;
- generate a machine-readable capability and subsystem inventory;
- identify duplicate routing, memory and task abstractions with call-site evidence;
- record migration compatibility requirements for existing databases and user state;
- establish baseline measurements for routing quality, memory growth, task completion, cost and latency.
