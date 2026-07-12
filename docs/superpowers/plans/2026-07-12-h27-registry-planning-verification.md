# H27.4-H27.5 Registry Planning and Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Filter Agent Runtime tools through live capability records and bind every executable action/tool verification reference to a real V1 case.

**Architecture:** ToolRPC carries optional capability identity; the existing registry derives live tool records; Agent Runtime filters/enriches metadata behind a new default-off setting; reality cases exercise the action facade/kernel and ToolRPC rails hermetically.

**Design:** `docs/superpowers/specs/2026-07-12-h27-registry-planning-verification-design.md`

## Task 1: Tool identity and registry records

- [ ] Write failing tests for optional `capability_id` projection, legacy projection parity, production echo/time ids, and derived `tool:*` registry rows.
- [ ] Run the focused ToolRPC/registry tests and verify RED for missing metadata/records.
- [ ] Extend `ToolRPCServer.register_tool()` and `tools()` without changing output when the id is absent.
- [ ] Declare ids for production echo/time and derive tool records in `capability_registry.py` with conservative risk and confidence 0.0.
- [ ] Run ToolRPC, coordinator wiring, registry endpoint, and readiness suites; commit `feat(h27): register live tool capabilities`.

## Task 2: Registry-aware Agent Runtime

- [ ] Write failing tests for default-off identical ToolSpecs, registry-enriched ToolSpecs, missing/SEAM filtering, malformed snapshot fail-closed, and no-match refusal before provider/RPC calls.
- [ ] Verify RED against the current unfiltered `_server.tools()` path.
- [ ] Add injected `registry_enabled` and `capability_snapshot` callables plus a focused metadata projection helper.
- [ ] Return the stable no-capability reply when registry mode yields no tools; retain existing master flag/provider checks.
- [ ] Wire the default-false `llm.registry_planning_enabled` setting and live snapshot provider in `autonomy_coordinator.py`.
- [ ] Run Agent Runtime v2 and coordinator tests; commit `feat(h27): make tool planning registry aware`.

## Task 3: Action/tool reality cases and verification gate

- [ ] Write failing tests that require a stable `RealityCase.ref`, exact action/tool verification-ref coverage, matching capability ids, and hermetic passing probes.
- [ ] Verify RED for the current `action-auth:*` references and absent tool cases.
- [ ] Add stable case-name/ref helpers, 12 action-plane kill-switch cases through real `CapabilityActionAPI` + kernel, and echo/time ToolRPC cases.
- [ ] Point action manifests and derived tool records to those refs; extend CASES without changing existing cases.
- [ ] Update readiness PENDING_VERIFY and reseed the canonical snapshot for `tool:echo/time`.
- [ ] Run reality/readiness/action-auth suites; commit `test(h27): prove executable capability rails`.

## Task 4: Backlog, generated status, review, and CI

- [ ] Mark H27.4/H27.5 complete in `BACKLOG.md` with exact default-off and verification evidence.
- [ ] Regenerate and check project status with tracked JS counts.
- [ ] Run focused H27/Agent Runtime/ToolRPC/reality/registry suites plus route/OpenAPI/auth/lifespan, Ruff, Bandit, park guard, and release gate.
- [ ] Review the complete diff for fallback bypass, fabricated VERIFIED/confidence, provider calls on empty selection, environment leakage, and snapshot drift; fix Important/Critical findings with red/green tests.
- [ ] Push a draft PR, monitor Ubuntu/Windows CI and CodeQL, repair all failures, then squash-merge and clean the owned worktree.
