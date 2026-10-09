# Hermes Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. The coordinator integrates shared interfaces.

**Goal:** Reuse the complete pinned Hermes runtime through authenticated Jarvis session/control interfaces and obligatory authorization, continuing PR #1233.

**Architecture:** Ship a versioned source/runtime manager outside the Hub interpreter. A Jarvis RPC adapter owns sessions and events; an obligatory worker bridge mediates effects through existing Kernel/task primitives. HUD/CLI use the same services.

**Tech Stack:** Jarvis Python 3.12/FastAPI, Hermes managed Python 3.14, JSON-RPC/WebSocket, existing React HUD and Kernel.

**Spec:** `docs/superpowers/specs/2026-10-06-hermes-runtime-design.md`.

## Global Constraints

- Work on `codex/hermes-parity-handover-20261006`; preserve all previous commits. User authorized publication to PR #1233, not merge/deploy.
- Pin donor SHA `0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7`, retain provenance/MIT license and complete source; no dynamic `main` installation.
- At most two implementation agents (`gpt-6-sol`, High), no child agents. Root owns shared routes/HUD/authorization/integration. No paid/live provider probes.
- Runtime disabled until explicitly configured; credentials and private profile state are not imported. No new general shell/proxy surface and no weakening of CI gates.

## Review Focus

- Source/path/executable substitution: reject any launch whose verified source/runtime identity differs.
- Runtime disconnect after an accepted operation: reconnect without retrying the operation.
- Cross-session or old-generation request: deny before dispatch, including server-request responses.
- Broker error or unclassified operation: fail closed with no worker effect.
- Shutdown/cancellation while tools or child processes run: stop owned work and report its real state.

### Task 1: Pin, provision and supervise complete source/runtime

**Files:** `agents/core/hermes_runtime/{__init__,distribution,process}.py`, `runtime/hermes/upstream.lock.json`, `scripts/hermes_runtime.py`, `tests/test_hermes_runtime_distribution.py`, `tests/test_hermes_runtime_process.py`.

**Interfaces:** `load_pin() -> dict`; `verify_source(source: Path) -> dict`; `prepare_source(destination: Path) -> Path`; `RuntimeProcess(source: Path, home: Path, python: Path)` with async `start(*, bridge_url: str, bridge_token: str) -> dict`, `stop() -> dict` and `status() -> dict`. Root owns RPC/client and worker bridge. Coordinate any signature change before integration.

- [x] Add and run failing regressions for pinned source identity, unsafe archives/paths, isolated environment, unsupported interpreter, bind/readiness failure and process cleanup.
- [x] Implement pinned full source preparation and upstream-PM setup, with private profile/runtime data and no inherited operator credentials.
- [x] Implement owned process lifecycle with validated launcher, bounded readiness, one process generation and cleanup; no launches through arbitrary shell strings.
- [x] Run focused tests and report exact setup/real-runtime results to root. Do not commit shared work.

### Task 2: Authenticated control/RPC plus obligatory worker authorization

**Files:** root-owned `agents/core/hermes_runtime/{client,service,policy,worker,bridge}.py`, `agents/core/routers/hermes_runtime.py`, `agents/web.py`, applicable settings/CLI bindings, `tests/test_hermes_runtime_{client,service,policy,routes,bridge}.py`.

**Interfaces:** `HermesRuntimeService` owns process, single-owner profile/session transport, catalog and events. Runtime control and RPC are explicit methods, not a caller-selected origin or arbitrary executable. Bind bridge decisions to the generation/session/method/tool/arguments and existing Action Kernel authorization.

- [x] Write/run failing tests for forged identity, unknown methods, disabled runtime, broker loss, replay, direct mutation authorization and safe reconnect/server-request delivery.
- [x] Load the upstream OpenRPC catalog with provenance; implement single-owner sessions and bounded RPC/events.
- [x] Implement mandatory worker-side authorization at actual dispatch/control boundaries; keep unverified paths denied and disclose availability.
- [x] Add guarded routes and lifecycle cleanup; verify them with real FastAPI and pinned-worker/offline model tests.

### Task 3: Existing CI failures and operator availability

**Files:** CI-repair agent owns the three existing failing `docs/` runner scripts and `agents/core/security/secret_sources/` + `agents/cli/secrets.py`, targeted regressions. Root owns new HUD runtime panel/API client/tests and regenerated frontend assets/status/schema/parity documentation.

- [x] Reproduce Ruff/Bandit/Semgrep findings on the base; correct code or narrow source-level scanner false positives with explicit rationale, retaining gate configurations.
- [x] Add operator runtime status, setup/session/control flow and real error/pending states; commands and HUD call the same services.
- [x] Verify failure boundaries and real RPC/event behavior; keep all 697 contracts in scope and distinguish runtime-backed availability from native equivalence.
- [x] Run one relevant backend union and frontend build/test milestone, security/lint and generated contract/status checks. Fix concrete failures, independently review and publish a fast-forward update to the same PR with truthful validation.

## Execution ledger

2026-10-06: Ruling: proceed under the user's implementation/publication request and AGENTS.md standing autonomous-local authorization; no redundant design approval gate. The accepted direction is captured above. No merge/deployment is authorized.

2026-10-06 integrated milestone: pinned full source extracted via shared archive_safe; upstream PM installed 3.14.7 and default browser/device dependencies. Focused union: 265 pass + 2 opt-in skips; installed-runtime tests: 2 pass including offline prompt/events, sessions, refusal and replay. Frontend 1,980 pass, typecheck/build pass. Ruff/Bandit/Semgrep/gitleaks and route/OpenAPI/status checks pass. Aggregate backend attempt incomplete with inherited failures and xdist worker/scheduler error, explicitly retained in evidence. Publish same draft branch; 151 operations remain at an approval floor, not marked complete. Next action: read report.json and implement action-bound durable queue execution for these remaining families.
