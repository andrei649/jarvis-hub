# Nerva 2.0 E0.2a — Hybrid Cognition boundary and adoption gate

> **Snapshot:** `main@a2766a98d16be40389ca587c6677c9e5e5d6e270` on 2026-08-02.  
> **Program:** #757 · **E0:** #758 · **Research epic:** #773  
> **Status:** architecture boundary only; no runtime implementation is claimed.  
> E12 was approved after the original E0.2 snapshot. Its dependency position and advisory-only
> authority are now pinned in `DEPENDENCIES.md` and `CONTRACT_REGISTRY.json`; its candidate schemas
> remain deferred until E12.1 produces typed fixtures and calibration evidence.

## 1. Purpose

E12 explores a hybrid cognitive architecture combining deterministic software, probabilistic
beliefs, retrieval, learned models, symbolic constraints, search, simulation and metacognitive
control. Its purpose is better decisions under uncertainty — not a larger collection of agents,
not anthropomorphic claims and not a second action authority.

The central rule is:

> Hybrid cognition may improve what Nerva believes, considers and recommends. It never changes
> what Nerva is authorized to do.

Ultron and `nerva.action.v1` remain the sole privileged-action boundary.

## 2. Dependency position

```text
E0 baseline + ownership contracts
 ├─> E1 Cortex decision records ───────────────┐
 ├─> E2 Atlas facts/provenance ─> E3 Episodes ├─> E12 Hybrid Cognition
 ├─> E6 Reflection proposals ─────────────────┤
 └─> E9 Research Lab benchmark evidence ──────┘

E12 advisory outputs ─> Cortex / World Model / Research Lab
Any external effect ──> Ultron / Action Kernel
```

E12 may prototype against versioned fixtures, but it cannot claim integration until the relevant
live contracts exist. In particular:

- Atlas owns observations, canonical facts, time and provenance;
- Episodes owns experience lifecycle;
- Reflection owns lesson proposals, never source evidence;
- Research Lab owns benchmark evidence;
- Cortex owns route selection and DecisionRecords;
- Ultron owns authorization and privileged execution;
- E12 owns only advisory belief and metacognitive records once those schemas are proven.

## 3. State separation

Hybrid cognition must preserve four different kinds of state:

| State | Example | Writer | Mutation rule |
|---|---|---|---|
| Observation | “Sensor A reported 24.3°C at 10:12” | Atlas ingestion | Immutable source reference |
| Fact projection | “Living room temperature was 24.3°C” | Atlas | Bi-temporal, provenance-rich, correctable |
| Belief | “The room is probably occupied, p=0.72” | Future E12 belief layer | Advisory, calibrated, expires/revises |
| Authorization | “May turn the AC on” | Ultron | Deterministic policy/approval boundary |

A probability is never promoted to fact by notation alone. A high-confidence preference is never
consent. A simulation result is never a command.

## 4. Provisional E12 contract candidates

These are candidates for **E12.1**, not additions to the canonical contract list yet. They must be
exercised against fixtures and reviewed before registry promotion.

### 4.1 `nerva.belief.v1` — BeliefState / Hypothesis

Minimum fields:

- stable belief and hypothesis IDs;
- proposition in typed, machine-readable form;
- Atlas/Episode evidence references;
- prior and posterior probabilities;
- update method and model/version;
- supporting and contradicting evidence;
- calibration cohort and reliability metadata;
- valid time, expiry and supersession links;
- privacy class and deletion lineage;
- explicit limitations.

Authority: `advisory_belief_only`.

### 4.2 `nerva.metacognition.v1` — CognitiveDecision

Records why Nerva selected a reasoning mode and when it stopped. Minimum fields:

- request and decision-record references;
- detected uncertainty, novelty, conflict and stakes;
- candidate reasoning modes;
- expected benefit, compute cost, latency cost and reasoning risk;
- selected mode and stop condition;
- verification or clarification requirement;
- budget consumed and bounded fallback;
- replay fingerprint.

Authority: `reasoning_control_only`; it cannot authorize tools or actions.

### 4.3 `nerva.cognitive-workspace.v1` — BlackboardSnapshot

A typed, immutable snapshot containing goals, observations, hypotheses, contradictions, candidate
plans, unresolved questions and evidence links. It must not become an unbounded free-form transcript
or a hidden shared mutable database.

Authority: `workspace_only`.

## 5. Initial reasoning-mode taxonomy

The router should choose the cheapest sufficient mode:

1. **Deterministic** — parsing, validation, lookup, arithmetic, policy and direct capability calls.
2. **Retrieve-and-adapt** — use an existing Episode, procedure or verified pattern.
3. **Fast model proposal** — generate candidates or summarize low-stakes material.
4. **Probabilistic update** — combine uncertain or contradictory evidence.
5. **Constraint solve** — satisfy explicit hard constraints and optimize soft objectives.
6. **Causal analysis** — distinguish observation from intervention and counterfactuals.
7. **Bounded search/simulation** — compare plans when stakes justify the cost.
8. **Clarify/escalate** — ask for missing authority or decisive information.
9. **Defer/refuse** — stop when evidence, authority or safe capability is absent.

The taxonomy is not a fixed claim that every mode needs a new subsystem. Existing deterministic
code, retrieval, model routing, evaluation and simulation substrates should be reused first.

## 6. Mathematical adoption protocol

No technique is accepted because it sounds advanced. Each candidate must pass all gates below.

### Gate A — hypothesis

Define the exact failure mode it is expected to improve and the simpler baseline it must beat.
Examples:

- Bayesian source reliability versus a deterministic source-priority rule;
- expected value of computation versus a fixed depth/step limit;
- MCTS versus bounded beam search or a single planner pass;
- active inference versus explicit expected-information-gain scheduling.

### Gate B — versioned task suite

Use privacy-safe fixtures and real Nerva task classes. Separate factual uncertainty, route
selection, planning quality, calibration, safety/constraint compliance, latency, cost and resource
use.

### Gate C — metrics

At minimum:

- task success and verification rate;
- Brier score and/or log loss for probabilistic outputs;
- reliability diagrams or confidence buckets;
- hard-constraint violation rate;
- tool/model calls, wall time and cost;
- abstention/clarification quality;
- worst-case and tail behavior, not only averages.

### Gate D — ablation

Remove each component independently. The claimed improvement must disappear or materially weaken.
If the full system performs no better than the simple baseline, the simple baseline wins.

### Gate E — robustness

Evaluate missing data, stale data, adversarial evidence, source correlation, model/provider outage,
out-of-distribution cases and contradictory observations. Uncertainty must widen rather than become
more confident under missing evidence.

### Gate F — operational value

A technique must demonstrate one or more of better verified outcomes, fewer unjustified actions,
improved calibration, fewer unnecessary calls, lower latency/cost at equivalent quality, or clearer
owner-facing explanations. Novelty without measurable owner value is a negative result and should
be documented as such.

## 7. Expected Value of Computation boundary

A future controller may estimate:

```text
EVC = expected decision improvement
      - compute cost
      - latency cost
      - risk introduced by further reasoning
```

This is a decision aid, not a universal law. The first implementation should be conservative and
observable:

- start as shadow/no-action telemetry;
- compare against fixed-budget baselines;
- use hard ceilings for steps, tokens, money and wall time;
- record why deeper reasoning was selected or skipped;
- preserve Ultron approvals and loop breakers;
- fall back to clarification/defer when EVC is uncertain in high-stakes contexts.

## 8. Safety invariants

- E12 has no privileged-action authority.
- Beliefs remain labeled probabilities with provenance and expiry.
- Hard policies and permissions remain deterministic and non-negotiable.
- Howard preference predictions remain separate from consent.
- World Model and causal analysis cannot mutate Atlas.
- Curiosity operates only inside approved goals, privacy scopes and budgets.
- No recursive self-modification outside normal reviewed software changes.
- No claims of consciousness, sentience, emotion or human equivalence.
- Every autonomous loop has a budget, deadline, stop condition and loop-breaker path.
- Negative results and failed hypotheses are retained as research evidence.

## 9. E0 reconciliation impact

E0.3 must add E12-specific risks to the program risk register:

- false precision and uncalibrated probability;
- correlated sources treated as independent evidence;
- hidden authority leakage from advisory output to action;
- runaway deliberation and compute spend;
- benchmark overfitting and metric gaming;
- causal claims unsupported by interventions;
- curiosity escaping approved goals;
- cognitive-workspace privacy and retention growth.

E12 remains `DISCOVERY`. The next executable E12 slice is E12.1: typed fixtures for belief,
hypothesis, evidence, candidate plan and metacognitive decision, followed by calibration tests. It
must not begin as production routing or autonomous action logic.
