# Nerva 2.0 E0.3b1 — ORIZONT 27–33 reconciliation after E0 closure

> **Snapshot:** accepted repository-ledger base `main@0c7f880dea1fe254d590ce8967e45cfe453dc52f`.  
> **Program:** #757 · **Epic:** #758 · **Historical ownership-map slice:** E0.3b1.  
> **Machine-readable companion:** [`ROADMAP_RECONCILIATION.json`](ROADMAP_RECONCILIATION.json).  
> E0 is `DONE`. This ownership map still **does not claim that legacy ORIZONT completion equals Nerva runtime or release completion**.

## 1. Reconciliation rule

Reuse accepted ORIZONT substrate and evidence. Do not rename and rebuild it. Code-complete,
wired/default-off, reference-driver and hermetic states remain distinct from live verification and
from Nerva epic completion.

Canonical source hierarchy remains:

| Question | Source |
|---|---|
| Product destination and Programs A–G | `NERVA_VISION.md` |
| Delivery roadmap and history | `BACKLOG.md` |
| Implementation snapshot | `STATUS.md` |
| Baseline and migration truth | `BASELINE.md`, `REUSE_BUILD_RETIRE.md` |
| Dependencies and authority | `DEPENDENCIES.md`, `CONTRACT_REGISTRY.json` |
| Risk and stop-ship invariants | `RISKS.md` |
| Cross-epic order and state | #757 and child epics |

## 2. ORIZONT 27–33 → Nerva ownership

| Legacy horizon | Existing substrate to reuse | Nerva destinations | Remaining Nerva value |
|---|---|---|---|
| **O27 / Program A — Foundations** | Capability Registry, manifests, automation contracts, Action Kernel and agent runtime | E1, E8, E11 | Typed decisions, universal SDK conformance, task-level Ultron mediation evidence and release proof. |
| **O28 / Program B — Computer operator** | ToolRPC, local/Docker/SSH environments and governed host-driver seams | E8, E10, E11 | Real structured browser/desktop implementations, honest degradation, verifier/rollback and owner-hardware evidence. |
| **O29 / Program C — Media and surfaces** | Media Director, reference driver, catalog and interrupt budgets | E8, E10, E11 | Versioned presentation capabilities, more real targets and evidence-linked delivery. |
| **O30 / Program D — Atlas house model** | Bi-temporal KG, memory-KG routes, Homebridge/Tuya seams, Wyoming and situational inputs | E2, E10, E11 | Canonical identity/provenance/privacy snapshots over real room, device and occupant state. |
| **O31 / Program E — Vision and surveillance** | VLM adapter, evidence boundaries and reality-harness patterns | E2, E8, E11 | Privacy-first camera events, retention/deletion, Atlas observations and owner-hardware proof. |
| **O32 / Program F — Synapse self-extension** | Acquisition runtime, strict-local synthesis, reuse checks, sandbox/quarantine and evals | E8, E9, E11 | SDK conformance, benchmark evidence, staged promotion, rollback and measured reuse-before-generation. |
| **O33 / Program G — Ambient cognition** | Observer, scheduler, missions, queue/worker, policy, review and run history | E5, E6, E10, E11 | Approved goals, bounded discovery, independent verification, reflection and restart-safe zero-bypass proof. |

No horizon creates a second action authority, truth store or unconstrained self-modification loop.
All privileged effects preserve **Ultron as the sole privileged-action authority**.

## 3. First bounded executable slices

E0 is closed, so the E0 blocker is removed from the first wave without changing scope or authority:

| Epic | Issue | Smallest slice | Remaining blocker | Authority / behavior posture |
|---|---:|---|---|---|
| E1 Cortex | **#780** | Shadow `DecisionRecord` over existing routing | none | No action or routing authority |
| E2 Atlas | **#781** | Identity/provenance envelope plus read-only snapshot | none | Read-only consumer contract; no new DB |
| E3 Episodes | **#782** | Episode schema and deterministic manual boundaries | **#781** | Memory record only |
| E8 Synapse | **#783** | Versioned manifest conformance on three existing capabilities | none | Description cannot grant permission |
| E9 Research Lab | **#784** | Versioned benchmark contract and privacy-safe task suite | none | Evaluation cannot change production routing |

#780, #781, #783 and #784 may proceed as separate bounded PRs. #782 still waits for #781.
Issue existence and E0 closure are not implementation evidence.

## 4. Post-E0 parallelism

```text
#780 E1 Cortex shadow records ──────────────┐
#781 E2 Atlas read-only snapshot ───────────┼─ parallel
#783 E8 Synapse conformance ────────────────┤
#784 E9 benchmark contract ─────────────────┘

#781 minimum Atlas contract ──> #782 E3 Episodes
```

The first wave starts with typed fixtures, compatibility, shadow or read-only behavior. Night Shift,
Howard, World Model and Hybrid Cognition retain their declared dependencies.

## 5. Truth and security boundaries

- Legacy delivered/code-complete is not live verified.
- Wired/default-off/reference-driver is not proof of an external effect.
- Hermetic verification is not owner-hardware proof.
- E0 DONE is planning/control completion, not runtime or release completion.
- No first-wave slice changes production authority.
- #782 retains the Atlas prerequisite; no dependency is silently discarded.

## 6. Open work after E0

The ORIZONT mapping is complete, but broader Nerva work remains:

- B2 whole-program manifest, cycle/orphan detection and generated dependency views;
- B3 Continuity Core mapping;
- B4–B10 cognitive ledger, SDK breadth, real actuation, mediation, research, Night Shift and proof;
- all owner-hardware and Nerva 2.0 release gates.

## 7. Next smallest movement

Choose one of **E1.0 / E2.0 / E8.0 / E9.0** as a dedicated, reuse-first PR. Prefer typed contracts,
shadow/read-only behavior and evidence before runtime expansion. #782 still waits for #781.
