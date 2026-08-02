# Nerva 2.0 — Program risk register

Parent: #758 · Program: #757

## Risk scoring

- Likelihood: Low / Medium / High
- Impact: Moderate / High / Critical
- Status: Open / Mitigating / Accepted / Closed

| ID | Risk | Likelihood | Impact | Primary mitigation | Owner epic |
|---|---|---:|---:|---|---|
| R1 | Feature breadth hides that core workflows are not dependable | High | Critical | release gates based on real workflows, evidence and soak tests rather than counts | E11 |
| R2 | New Nerva names duplicate existing subsystems | High | High | E0 decision register; every epic names reuse paths and migration contracts | E0/all |
| R3 | Autonomous loops generate work outside approved goals | Medium | Critical | approved goal scopes, budgets, deadlines, stop conditions and independent review | E5 |
| R4 | Agent/model output bypasses Action Kernel | Medium | Critical | one privileged-action boundary; contract and call-site ratchets | E1/E5/E8/E11 |
| R5 | Digital Twin prediction is mistaken for owner consent | Medium | Critical | typed separation of preference prediction and authorization; UI warnings; policy tests | E4 |
| R6 | Reflection creates self-confirming false memories | High | Critical | evidence-linked hypotheses, promotion gates, held-out evals and contradiction visibility | E6 |
| R7 | Personal data is duplicated across Atlas, Episodes and embeddings | High | Critical | references/lineage over duplication; export/delete propagation tests | E2/E3/E6 |
| R8 | Connector identities create duplicate or wrongly merged people/assets | High | High | canonical identity service, confidence, reversible merge/split and owner correction | E2 |
| R9 | Scenario narratives appear precise despite weak assumptions | High | High | explicit facts/assumptions/estimates, ranges, sensitivities and calibration backtests | E7 |
| R10 | Night Shift reports partial work as complete | Medium | Critical | evidence contract, checkpoint states, independent verification and honest brief schema | E5/E10 |
| R11 | Skills generated or installed with excessive permissions | Medium | Critical | deny-by-default manifests, quarantine, signing, kernel enforcement and conformance tests | E8 |
| R12 | External integrations become unmaintainable or compromise local-first posture | Medium | High | replaceable adapters, health/version reporting, local mode and exit plan | E0/E8 |
| R13 | Too many parallel PRs create conflicts and stale roadmap claims | High | High | smallest slices, explicit dependencies, one master ledger and independent integrator | #757 |
| R14 | Existing user data cannot migrate or roll back safely | Medium | Critical | migration fixtures, backups, restore drills, forward/backward compatibility | E0/E11 |
| R15 | Demo/seed/mock state is shown as live | Medium | High | mandatory provenance labels and tests across API/UI | E10/E11 |
| R16 | Costs grow silently through background cloud inference | Medium | High | per-route accounting, budgets, local-first policy and owner-visible cost reports | E1/E5/E9/E10 |
| R17 | Local hardware absence produces misleading green tests | High | High | hardware capability detection, explicit skipped/blocked states and real-run evidence | E9/E11 |
| R18 | Memory growth degrades latency and storage indefinitely | High | High | bounded consolidation/forgetting, growth simulations and operational metrics | E3/E6 |
| R19 | Model/provider changes regress behavior without detection | High | High | versioned real-task suites, reproducible reports and quarantined migrations | E9 |
| R20 | Security controls exist in UI but differ from live runtime behavior | Medium | Critical | live posture/runtime consistency tests and fail-closed settings propagation | E11 |
| R21 | Family/household context leaks across users or rooms | Medium | Critical | subject/room privacy scopes, household roles and private delivery policy | E2/E10 |
| R22 | Project becomes an AI research toy instead of saving owner time | High | Critical | prioritize three recurring owner workflows and measure verified time saved | #757/E10/E11 |

## Program invariants

The following are stop-ship invariants:

1. No privileged operation bypasses Ultron/Action Kernel.
2. Prediction never equals consent.
3. Simulation never mutates live reality state.
4. Reflection never rewrites source evidence.
5. Memory deletion/export covers derived state and indexes.
6. Autonomous work remains within approved goals, budgets and stop conditions.
7. Completion claims link to verification evidence.
8. Demo or stub state is never represented as live.
9. A release is not declared from feature count alone.

## Drift indicators

The integrator should flag the program when any of these appear:

- a new agent, database, scheduler, plugin framework or approval system without an E0 reuse justification;
- PRs that modify several epics without a tested shared contract;
- status documents updated before code/evidence exists;
- benchmark improvements based only on hand-picked prompts;
- memory summaries promoted without provenance;
- background jobs without explicit cost and termination bounds;
- external writes verified only by tool return text rather than observed state;
- UI cards backed by static fixtures in normal live mode;
- repeated emergency fixes around the same boundary without a contract-level ratchet.

## Review cadence

Each epic update must state new risks, changed likelihood/impact and the next mitigation slice. E11 owns the final consolidated risk review, but risks remain open in their originating epic until evidence closes them.
