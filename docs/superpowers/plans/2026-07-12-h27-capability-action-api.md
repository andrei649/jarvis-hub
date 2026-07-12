# H27.1-H27.3 Capability Registry and Unified Action API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enrich the existing readiness registry, manifest every kernel action and governed plugin, and add a default-off unified `perform()` facade.

**Architecture:** A focused manifest module owns descriptive action metadata; the existing capability registry derives records from it and current plugin/component/skill sources; an injected async facade mediates new handlers itself or delegates to already-mediated brokers/ToolRPC without double authorization.

**Tech Stack:** Python 3.12, dataclasses, FastAPI's existing metrics route, pytest, Ruff, Bandit.

**Design:** `docs/superpowers/specs/2026-07-12-h27-capability-action-api-design.md`

## File map

- Create `agents/core/capability_manifests.py`: schema, validation, action manifests, plugin metadata derivation.
- Modify `agents/core/observability/capability_registry.py`: additive v1 fields and action derivation.
- Create `agents/core/capability_actions.py`: default-off perform facade and adapters.
- Create `tests/test_h27_capability_manifests.py`: H27.1/H27.2 schema and drift contract.
- Create `tests/test_h27_capability_actions.py`: H27.3 red/green behavior.
- Modify `tests/test_capability_registry.py`: enriched endpoint/compatibility assertions.
- Modify `BACKLOG.md`: complete H27.1-H27.3 with exact evidence.

## Task 1: Manifest schema and action coverage

- [ ] Add failing tests asserting a frozen `CapabilityManifest`, confidence/risk validation, all required v1 fields, wildcard resolution, and exact equality between `ACTION_REGISTRY` and action manifests.
- [ ] Run `python -m pytest tests/test_h27_capability_manifests.py -q` and confirm import/behavior failures are caused by the missing feature.
- [ ] Implement `CapabilityManifest`, `ACTION_CAPABILITY_MANIFESTS`, `manifest_for_action()`, and `validate_manifest()` in `agents/core/capability_manifests.py`.
- [ ] Give every current action-auth kind an explicit description, bounded input schema, conservative risk, kernel requirement, supports list, verification reference, rollback text, confidence, implementation reference, and contract reference where one exists.
- [ ] Re-run the focused test and `tests/test_action_auth_matrix.py`; both must pass.
- [ ] Commit `feat(h27): manifest kernel action capabilities`.

## Task 2: Governed plugin metadata and registry v1

- [ ] Add failing tests asserting every built-in plugin derives complete v1 metadata and that plugin risk/confidence/rollback defaults are conservative.
- [ ] Extend `tests/test_capability_registry.py` with failing assertions for new fields and `action:<kind>` records while retaining existing readiness behavior.
- [ ] Run both test files and confirm expected missing-field/action failures.
- [ ] Implement `plugin_capability_manifest()` and extend `CapabilityRecord` with:
  `description`, `inputs`, `risk`, `requires`, `supports`, `verification`, `rollback`, `confidence`, and `implementation`.
- [ ] Derive action records from `ACTION_CAPABILITY_MANIFESTS`; enrich plugin records; assign explicit conservative defaults to component and skill records.
- [ ] Re-run the focused registry/manifest tests and endpoint test; confirm additive serialization.
- [ ] Commit `feat(h27): extend capability registry schema v1`.

## Task 3: Default-off perform facade

- [ ] Add failing tests for `PerformContext`, `PerformResult`, disabled behavior, unknown capability, non-mapping params, required inputs, missing binding, and redacted handler failures.
- [ ] Add failing tests proving facade mediation calls the kernel exactly once, never executes on DENY/QUEUE, and executes on GRANT.
- [ ] Run `python -m pytest tests/test_h27_capability_actions.py -q` and confirm the module/API is missing.
- [ ] Implement `CapabilityActionAPI`, binding validation, sync/async handler normalization, required-key validation, Action construction, stable statuses, and the `JARVIS_UNIFIED_ACTION_API` opt-in.
- [ ] Re-run the focused tests and keep output warning-free.
- [ ] Commit `feat(h27): add unified capability perform facade`.

## Task 4: Broker and ToolRPC delegation adapters

- [ ] Add failing tests that reject delegated bindings for non-kernel kinds, accept current action kinds, invoke a broker callback once without facade authorization, and route ToolRPC through `server.handle()` without double authorization.
- [ ] Verify RED against the missing adapter methods.
- [ ] Implement `register_broker()` and `register_tool_rpc()` as thin wrappers around delegated registration; require `kernel.registry.classify(action_kind) is KERNEL`.
- [ ] Run H27 tests plus `tests/test_tool_rpc_kernel_wave.py`, `tests/test_tool_rpc_h20_1.py`, and `tests/test_action_auth_matrix.py`.
- [ ] Commit `feat(h27): bridge brokers and tool rpc into perform`.

## Task 5: Documentation, backlog, and release verification

- [ ] Update H27.1-H27.3 in `BACKLOG.md` in the same feature commit, recording the runtime count reconciliation (12 action patterns), default-off posture, files, and exact tests.
- [ ] Run focused H27 tests, adjacent registry/kernel/ToolRPC suites, route/OpenAPI/auth parity, lifespan smoke, Ruff, Bandit, and `scripts/status_sync.py --check --reuse-js-counts`.
- [ ] Run the complete test suite through CI on Ubuntu and Windows; treat CI as authoritative for the host-sensitive monolithic suite.
- [ ] Review `git diff origin/main...HEAD` against every design requirement, fix Critical/Important findings with regression tests, and rerun affected verification.
- [ ] Push the branch and open a draft PR with goal, non-goals, risks, rollback, parity statement, and exact evidence.
- [ ] Watch CI, repair failures, update the PR evidence, and leave an explicit final integration status.
