# Nerva 2.0 E0.3b1 — ORIZONT 27–33 reconciliation and executable slices

> **Snapshot:** `main@ab177c5501eeea379b66d9d33a1ed895a322e934` on 2026-08-02.  
> **Program:** #757 · **Epic:** #758 · **Slice:** E0.3b1.  
> **Machine-readable companion:** [`ROADMAP_RECONCILIATION.json`](ROADMAP_RECONCILIATION.json).  
> This slice reconciles scope and creates bounded child issues. It **does not close E0** and it does
> not claim that legacy ORIZONT completion equals Nerva runtime or release completion.

## 1. Why this reconciliation exists

`NERVA_VISION.md` maps Programs A–G to ORIZONT 27–33, while Nerva 2.0 now has explicit epics,
contract ownership, a delivery DAG and a risk register. Both planning systems contain useful work,
but they answer different questions:

- ORIZONT 27–33 organized capability delivery and existing implementation waves;
- Nerva E0–E12 owns current dependency order, authority, product truth and acceptance evidence;
- `BACKLOG.md` remains the delivery roadmap and `STATUS.md` remains the implementation snapshot;
- #757 remains the owner-facing cross-epic ledger.

The reconciliation rule is:

> Reuse accepted ORIZONT substrate and evidence. Do not rename it and rebuild it. Do not treat
> code-complete, wired, default-off, reference-driver or hermetic evidence as Nerva `DONE`.

## 2. Source hierarchy

| Question | Canonical source |
|---|---|
| Product destination and Programs A–G | `NERVA_VISION.md` |
| Current prioritized delivery history/roadmap | `BACKLOG.md` |
| Current generated implementation snapshot | `STATUS.md` |
| Runtime and migration truth | `BASELINE.md`, `REUSE_BUILD_RETIRE.md` |
| Delivery dependencies and authority | `DEPENDENCIES.md`, `CONTRACT_REGISTRY.json` |
| Security, privacy, autonomy and product-truth risk | `RISKS.md` |
| Cross-epic status and order | #757 and child epics |

A future PR that changes scope or status must update the stale source in the same movement. The
machine-readable companion to this document prevents the mapping itself from silently losing a
horizon or first executable slice.

## 3. ORIZONT 27–33 → Nerva ownership

| Legacy horizon | Accepted substrate to reuse | Nerva destinations | What still has to be earned |
|---|---|---|---|
| **O27 / Program A — Foundations** | Capability Registry, manifests, automation contracts, Action Kernel, agent runtime and existing `perform()`/unified-action seams | **E1 Cortex**, **E8 Synapse**, **E11 Proof** | Replayable typed decisions; universal SDK conformance; task-level live Ultron mediation evidence; release proof. Existing code-complete/default-off surfaces are not completion. |
| **O28 / Program B — Computer operator** | H15 governance, ToolRPC, local/Docker/SSH environments and host-driver seams | **E8 Synapse**, **E10 Experience**, **E11 Proof** | Real structured browser/desktop implementations, honest degradation, verifier/rollback contracts and owner-hardware evidence. Visual control remains fallback. |
| **O29 / Program C — Media and surfaces** | Media Director, local reference driver, media catalog, Spotify and interrupt budgets | **E8 Synapse**, **E10 Experience**, **E11 Proof** | Versioned presentation capability, additional real device classes, evidence-linked delivery and coherent owner controls. A reference driver does not prove audible/visible output. |
| **O30 / Program D — Atlas house model** | Bi-temporal KG, memory-KG routes, Homebridge/Tuya seams, Wyoming and WorldView/Signal Layer inputs | **E2 Atlas**, **E10 Experience**, **E11 Proof** | Canonical identity/provenance/privacy snapshots over real room/device/occupant state, governed actuation and live deletion/export/restore proof. |
| **O31 / Program E — Vision and surveillance** | VLM adapter, Atlas/evidence boundaries and reality-harness patterns | **E2 Atlas**, **E8 Synapse**, **E11 Proof** | Privacy-first camera event adapters, retention/deletion, Atlas observations, capability conformance and owner-hardware evidence. Missing or gated adapters remain explicit. |
| **O32 / Program F — Synapse self-extension** | Acquisition runtime, strict-local synthesis, reuse check, sandbox/quarantine, promotion broker and eval substrate | **E8 Synapse**, **E9 Research Lab**, **E11 Proof** | Universal manifest/conformance contract, benchmark evidence, staged promotion, rollback and measured reuse-before-generation reliability. |
| **O33 / Program G — Ambient cognition** | Observer, scheduler, missions, queue/worker, policy, background review and run history | **E5 Night Shift**, **E6 Reflection**, **E10 Experience**, **E11 Proof** | Approved goals, bounded discovery, independent verification, reflection, restart-safe zero-bypass measurement and multi-night positive net value. |

### 3.1 What is deliberately not mapped to a duplicate subsystem

- O27 does not create another Capability Registry; E8 evolves the existing registry and manifests.
- O28 does not create a second action authority; operator implementations still cross Ultron.
- O30/O31 do not create connector-owned truth databases; adapters publish observations to Atlas.
- O32 does not create an unconstrained self-modification loop; generated work stays quarantined.
- O33 does not create unrestricted autonomy; Night Shift works only inside approved goals and
  bounded delegated scopes.

## 4. First bounded executable slices

The E0 acceptance criteria require issue-level work that can begin without architecture ambiguity.
Five bounded issues now exist; all remain blocked until E0 is independently accepted:

| Epic | Issue | Smallest slice | Authority / behavior posture |
|---|---:|---|---|
| E1 Cortex | **#780** | Shadow `DecisionRecord` over existing routing | No-action; cannot change routing or authorize |
| E2 Atlas | **#781** | Identity/provenance envelope plus read-only snapshot around the current bi-temporal store | Read-only consumer contract; no new DB |
| E3 Episodes | **#782** | Episode schema and deterministic manual boundaries | Memory record only; depends on #781 |
| E8 Synapse | **#783** | Versioned manifest conformance on three existing capabilities | Describes capability; does not grant permission |
| E9 Research Lab | **#784** | Versioned benchmark contract and privacy-safe task suite | Evaluation only; cannot change production routing |

These issues intentionally start with typed fixtures, compatibility and shadow/read-only behavior.
Night Shift, Howard, World Model and Hybrid Cognition are not pulled forward around their declared
prerequisites.

## 5. Parallelism after E0

Once E0 is accepted, the safe first wave is:

```text
#780 E1 Cortex shadow records ──────────────┐
#781 E2 Atlas read-only snapshot ───────────┼─ parallel
#783 E8 Synapse conformance ────────────────┤
#784 E9 benchmark contract ─────────────────┘

#781 minimum Atlas contract ──> #782 E3 Episodes
```

No first-wave slice performs a privileged external effect. This allows contract and evidence work
to progress in parallel while preserving Ultron as the sole privileged-action authority.

## 6. Legacy status interpretation

The following words are not interchangeable:

- **legacy delivered/code-complete** — an ORIZONT implementation or control exists;
- **wired/default-off/reference-driver** — a route exists but may not produce a real external
  effect in a normal install;
- **hermetic verified** — controlled tests prove software behavior, not owner hardware;
- **live verified** — the real adapter/effect was exercised with appropriate evidence;
- **Nerva epic done** — the epic acceptance criteria, documentation, security boundaries and
  real-world evidence are all satisfied.

This mapping therefore uses `INTEGRATE` or `BUILD_ON_EXISTING_BOUNDARIES`, never a blanket
`DONE`, for O27–O33.

## 7. Risks and drift controlled by this slice

- **Duplicate rebuild risk:** every horizon names concrete existing modules to reuse.
- **Authority drift:** O28/O29/O30/O31/O32/O33 effects still require Ultron.
- **Product-truth drift:** mixed/default-off/reference-driver states remain explicit.
- **Planning drift:** all seven horizons and five first slices are machine-readable and checked.
- **Premature parallelism:** #782 explicitly waits for the minimum Atlas contract; downstream
  autonomy and cognition retain their canonical blockers.
- **Private-data leakage:** Atlas, Episodes and Research Lab slices include privacy/deletion/local-
  only acceptance criteria before production use.

## 8. What remains before E0 can close

This slice intentionally stops before editing the large current-delivery ledgers from an unreviewed
mapping. After independent review of this reconciliation:

1. update the durable Nerva sections in `BACKLOG.md` and `STATUS.md` to point to this mapping and
   #780–#784 without rewriting historical ORIZONT delivery records;
2. update #757, #758 and #778 durable status sections so their issue bodies—not only comments—agree;
3. run the normal status generator/checks and full required CI;
4. close E0 only when those sources agree and the integrator accepts the evidence.

The next smallest slice is therefore **E0.3b2 — direct ledger reconciliation**, not implementation
of #780–#784 ahead of the E0 gate.
