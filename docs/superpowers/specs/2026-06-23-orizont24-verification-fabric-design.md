# ORIZONT 24 · Track V — Verification Fabric (design)

> Spec for the fabric that makes fleet-scale breadth *safe*: every capability proven
> against reality before it may claim "done", with a queryable readiness state and CI
> gates that N parallel agents cannot silently break.
> Owner: Andrei · Tracks V1–V4 · ~21 SP · Priority: P0–P1 · Phase B (after Phase-A AUD-\*).
> Direction: [BACKLOG.md → ORIZONT 24](../../../BACKLOG.md) · sibling spec: Track K (Action Kernel).
> **Build-on-not-reinvent:** this spec extends the existing snapshot-introspection gates and the
> plugin/component registries; it does not add a parallel system.

## Today (what exists, grounded)

Readiness is **implicit and scattered** — "is this capability real?" is answered per-caller by
**API-key presence**, with no central state:

- `agents/core/plugins/cloud_llm.py:29` returns `"[Cloud LLM unavailable: no API key configured]"`
  when no key — a **SEAM**. `n8n.py`, `websearch.py` (Tavily→DuckDuckGo fallback) do the same ad hoc.
- `agents/core/plugin_gate.py:BUILTIN_PLUGINS` — **the closest thing to a registry**: 24 `PluginManifest`
  entries (`id, version, network_access ∈ {NONE,LAN,RESTRICTED,FULL}, data_scope, allowed_domains,
  agents_served, enabled`). **Static/declarative only** — no readiness state, used for the egress
  boundary (SEC-5), not operational readiness.
- `agents/core/component_registry.py` — tracks component init `status: dict[str,str]` (`"ok"|"failed"`).
  The natural anchor for per-capability state, but today it's boot-status, not a readiness lifecycle.
- `agents/core/skills/loader.py:SkillLoader.discover()` — enumerates `skills/<name>/SKILL.md`. (Note:
  `skills/marketplace.py` referenced in some docs does **not** exist; don't depend on it.)

The verification *machinery* exists but is **ungated for capabilities**:

- **Eval harness** — `agents/core/observability/eval.py` (`EvalHarness`, `EvalCase`) + dataset
  versioning/regression (`tests/test_h9_3b_dataset_regression.py`) + `POST /api/eval/datasets/run`
  (`routers/eval.py`). Tested in CI, but **not a blocking gate** (H23.4).
- **North-star + counter-metrics** — `agents/core/observability/north_star.py` →
  `GET /api/metrics/north-star` (`accepted_per_active_user`, `interrupt_rate_per_day`, `reject_rate`,
  `local_pct`, `p95_latency_ms`). Computed correctly; **informational only**.
- **The snapshot-introspection gate pattern (the model to generalize)** —
  `tests/_route_introspect.py:iter_effective_routes(app)` flattens FastAPI routing;
  `test_route_auth_matrix.py` snapshots `route_auth.json` and fails CI on any *unclassified open
  mutator* (with explicit `INTENTIONALLY_OPEN` / `PENDING_GUARD` escape sets);
  `test_route_parity_guard.py` snapshots `route_surface.json`; `test_hud_v2_parity.py` maps every
  route to a HUD home. These are **blocking** in `.github/workflows/ci.yml`.
- **Test isolation** — `tests/conftest.py` sets `JARVIS_TESTING=1` to gate external pollers/egress.

**The gap in one line:** capabilities have no readiness state, so "looks done, isn't wired" is
invisible — exactly the ambiguity the 2026-06-23 audit kept hitting.

## Approach

Four pieces, each extending an existing seam.

```
                        capability registry (V2)
  plugin_gate.BUILTIN_PLUGINS ─┐     state ∈ {SEAM, WIRED, VERIFIED, GA}
  component_registry.status   ─┼──►  CapabilityRecord{ id, kind, owner_agent,
  skills/loader.discover()    ─┘        contract_ref, state, last_verified, harness_id }
                                              │
                 ┌────────────────────────────┼────────────────────────────┐
                 ▼                            ▼                             ▼
        reality harness (V1)        readiness/eval gates (V3,V4)     /api/metrics + HUD board
   each capability: a contract +    snapshot-introspection (like     queryable readiness;
   a live-or-real-protocol test     route_auth matrix) — a cap       "looks done isn't wired"
   run on a CI schedule  ──────────►  cannot reach VERIFIED without   becomes a visible state
   updates state SEAM→VERIFIED       a green harness; eval + north-
                                     star regressions block merge
```

### V1 — Reality harness

- A capability **declares a contract**: the minimal end-to-end behavior that proves the *rail* works
  (not the mock). Co-locate with the capability, e.g. a `reality/` test marked `@pytest.mark.reality`.
- Two run modes so unit speed is preserved: **null clients stay** for the default suite; the harness
  runs the **live** path (real API key) *or* a **hermetic-but-real-protocol** path (a spun-up local
  service / real SQLite / real HTTP loopback against a fake-but-protocol-correct server) — never a
  Python mock standing in for the protocol.
- Runs on a **CI schedule** (nightly + on-demand), gated by `JARVIS_TESTING`-style env so PR unit runs
  stay offline and fast. A green reality run is what **promotes** a capability's state (V2).
- Reuse `observability/eval.py` as the scoring substrate (a reality case is an `EvalCase` whose runner
  hits the real rail and whose scorer asserts the contract).

### V2 — Capability readiness registry

- Add a single source of truth: `CapabilityRecord{ id, kind (plugin|agent|skill|route-cluster),
  owner_agent, contract_ref, state ∈ {SEAM,WIRED,VERIFIED,GA}, last_verified_ts, harness_id }`.
- **Derive, don't duplicate**: seed records from `plugin_gate.BUILTIN_PLUGINS` + `component_registry`
  + `skills/loader`. State transitions: `SEAM` (declared, null-only) → `WIRED` (live path runs, manual)
  → `VERIFIED` (green reality-harness in CI) → `GA` (VERIFIED + on the supported matrix).
- Expose read-only at `GET /api/metrics/capabilities` (sibling of `/api/metrics/north-star`) and a HUD
  **readiness board** (reuses the LIVE/SEED-indicator intent from theme 0.16 / TASK-2).
- State is **set by the harness, not by hand** — a human can demote, but only a green harness promotes
  to VERIFIED.

### V3 — Fleet-coordination CI gates

Generalize the `test_route_auth_matrix.py` pattern from "every mutator is guarded" to "every capability
is honestly stated":

- `tests/test_capability_readiness_matrix.py` — snapshot `_snapshots/capability_readiness.json`;
  **fail CI** if a capability claims `VERIFIED`/`GA` without a passing `harness_id`, or if a
  **user-facing** capability is still `SEAM`. Mirror the honest-escape-set design:
  `INTENTIONALLY_SEAM` (by-design stubs) and `PENDING_VERIFY` (shrinking backlog), so the gate is
  truthful as it fills in — exactly how `PENDING_GUARD` shrank to empty in SEC-3.
- **Interface-contract drift**: extend the parity-snapshot idea to the cross-agent interfaces (A2A /
  subagent / kernel action schema) so one agent renaming a field fails CI instead of silently breaking
  another — the multiplier risk when the fleet edits in parallel.

### V4 — Eval + north-star as required gates

- Promote the eval harness (H23.4) to a **required** job in `.github/workflows/ci.yml`: run the golden
  dataset (`routers/eval.py` path, offline), **block merge** on a score regression beyond a baseline
  delta (the dataset-regression machinery in `test_h9_3b_dataset_regression.py` already computes
  `regressed`/`score_delta` — wire it to a non-zero exit).
- Add the **counter-metric guardrails** from `north_star.py` as merge checks (reject-rate, %-local, p95
  must not regress past thresholds). The north-star itself isn't a unit-CI number (it needs real usage),
  so gate the **counter-metrics** (which *are* computable offline) and track the north-star on the live
  board — matching MOONSHOT §6's "guardrails against gaming the north-star".

### Gating & safety

- Reality-harness scheduled jobs are **additive** — they never block the fast PR unit run; only V3/V4
  matrix + eval checks are on the PR critical path, and those are offline/deterministic.
- `JARVIS_REALITY_HARNESS=1` opt-in for the live (keyed) mode; default off in PR CI.
- The readiness matrix ships with `INTENTIONALLY_SEAM`/`PENDING_VERIFY` populated to **today's truth**
  so it's green on landing, then tightens (no big-bang).

## Acceptance

1. `GET /api/metrics/capabilities` returns a readiness state for every enumerated capability; the HUD
   board renders it.
2. A capability marked `VERIFIED` without a passing `harness_id` **fails** `test_capability_readiness_matrix`.
3. A user-facing capability left `SEAM` (and not in `INTENTIONALLY_SEAM`) **fails** CI.
4. A golden-dataset eval regression beyond the baseline delta **blocks merge** (V4 job red).
5. A counter-metric regression (reject-rate / %-local / p95 past threshold) **blocks merge**.
6. Renaming a cross-agent interface field without updating consumers **fails** the contract-drift gate.

## Phasing / why staged

V1 + V2 are the substrate (you can't gate readiness you don't track); land them first, seeded to
today's truth so CI stays green. V3 (the matrix) and V4 (eval/north-star gates) turn the registry into
*enforcement* — add them once the registry is honest, then drive `PENDING_VERIFY` toward empty exactly
as SEC-3 drove `PENDING_GUARD` to empty. Track P packs cannot reach VERIFIED until this fabric is live —
that ordering is the whole point.
