# Nerva 2.0 — Dependency DAG and interface contracts

Parent: #758 · Program: #757

## Delivery DAG

```text
E0 Baseline
 ├─> E1 Cortex ──────────────────────────────┐
 ├─> E2 Atlas ──> E3 Episodes ──────────────┤
 ├─> E8 Synapse Skills SDK ─────────────────┤
 └─> E9 Research Lab ────────────────────────┤
                                             ├─> E5 Night Shift ──> E10 Experience
E3 Episodes ──> E6 Reflection ───────────────┤
E3 Episodes ──> E4 Howard ──────────────────┘
E2 Atlas + E3 Episodes + E4 Howard + E1 Cortex ──> E7 World Model
All streams ─────────────────────────────────────> E11 Proof & release
```

Parallel implementation is allowed only behind versioned contracts. A downstream epic may prototype against fixtures, but it cannot claim completion until the upstream live contract and migration path are verified.

## Canonical contracts

### 1. Observation event

Minimum fields:

- stable event ID;
- source and source record reference;
- observed time and ingestion time;
- event type and typed payload;
- privacy classification and subject scope;
- confidence and integrity metadata;
- correlation/causation references;
- retention and deletion lineage.

Observation producers do not write directly into Howard or Episodes. They publish evidence for Atlas ingestion.

### 2. Atlas entity/fact/state

Atlas owns:

- canonical entity identity;
- aliases and connector identities;
- facts with source, confidence, valid time and system time;
- current state as a derived view, not destructive overwrite;
- relationships and domain scopes;
- contradiction and resolution status;
- export/deletion lineage.

Consumers receive immutable snapshots or bounded queries. They do not mutate storage directly.

### 3. Episode

An Episode contains:

- identity, title and lifecycle state;
- participants and Atlas entity references;
- timeline/event references;
- goals, decisions, actions and outcomes;
- evidence-linked summaries at allowed privacy levels;
- lessons as hypotheses, never silent facts;
- merge/split/supersede history.

Episodes reference raw records rather than duplicating them.

### 4. Cortex decision

A `DecisionRequest` provides outcome, context references, constraints, authority, budget and deadline. Cortex returns a replayable `DecisionRecord` containing:

- candidates considered;
- hard constraints and rejected candidates;
- quality/risk/privacy/latency/cost estimates;
- chosen route and fallback bounds;
- evidence/version fingerprints;
- required verification and approval class.

Cortex chooses a route; it does not grant authority. External actions still cross Ultron.

### 5. Capability manifest

Synapse owns a versioned manifest with:

- capability ID and semantic version;
- description and typed input/output schemas;
- implementations and runtime requirements;
- permissions, risk, privacy and reversibility;
- health, reliability, latency and cost evidence;
- test/benchmark compatibility;
- provenance, signature and promotion state.

Cortex discovers candidates only through this registry or an explicitly quarantined acquisition path.

### 6. Action request and result

The existing Action Kernel remains authoritative. Nerva additions must map capability execution into existing action contracts and produce:

- authorization decision;
- approval reference where required;
- execution ID and bounded environment;
- result and side effects;
- verification evidence;
- rollback status;
- audit references.

### 7. Verification evidence

Every material completion claim should resolve to a typed evidence record:

- claim;
- target and expected state;
- verification method;
- observed result;
- timestamp and environment;
- confidence and limitations;
- source artifacts such as tests, logs, snapshots or external reads.

### 8. Reflection outcome

Reflection consumes expected versus observed outcomes and may propose:

- a lesson hypothesis;
- confidence and evidence references;
- scope, expiry and contradiction links;
- destination proposal: discard, episode note, Howard preference, Atlas fact correction, skill improvement or human review.

Reflection never rewrites source evidence and cannot self-approve sensitive learning.

### 9. Howard prediction

Howard returns:

- predicted preference/choice;
- context scope;
- confidence and calibration band;
- supporting evidence categories;
- alternatives and uncertainty;
- explicit statement that prediction is not consent.

### 10. Scenario

World Model simulations use immutable Atlas snapshots and explicit assumptions. Results include uncertainty, sensitivities and provenance. Scenario output has no direct action authority.

## Ownership boundaries

| Domain | Owner | Forbidden shortcut |
|---|---|---|
| Authority and external action | Ultron / Action Kernel | model or agent self-authorization |
| Capability inventory/lifecycle | Synapse | bespoke hidden tool wiring |
| Route selection | Cortex | free-form agent voting without replay |
| Canonical personal reality | Atlas | connector-specific truth silos |
| Experience memory | Episodes | raw transcript duplication as the model |
| Preference prediction | Howard | treating prediction as approval |
| Learning/consolidation | Reflection | modifying source evidence |
| Simulation | World Model | mutating live Atlas state |
| Owner-facing truth | Experience/Evidence model | demo state represented as live |

## Compatibility rules

- contracts are versioned and changes require migration notes;
- stored personal data changes require forward migration, backup and rollback tests;
- APIs must expose unavailable/default-off/stubbed states honestly;
- downstream modules accept references and snapshots rather than private database handles;
- all privilege-bearing capabilities remain deny-by-default;
- every autonomous loop has budget, deadline, stop condition and loop-breaker integration.
