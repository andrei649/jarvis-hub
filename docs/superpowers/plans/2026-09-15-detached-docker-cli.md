# Detached Docker CLI Implementation Plan

> **For agentic workers:** Execute inline with superpowers:executing-plans; the parent coordinates independent work.

**Goal:** Run detached session containers with the operator's local Docker CLI/socket without exposing host configuration to the worker.

**Architecture:** Snapshot CLI executable/connection inputs at backend construction. Resolve a local Unix endpoint once using bounded asynchronous Docker context discovery and serialize the first resolution. Execute all operations through that frozen executable/endpoint with an empty private Docker configuration, keeping worker environment and isolation flags unchanged.

**Tech Stack:** Python 3.12 stdlib, asyncio subprocess, Docker CLI, pytest.

**Spec:** Parent-approved bounded design in the current task; this module-scoped note records its implementation contract.

## Constraints and freshness

- Base/head at plan creation: `5e8ff76e35d63849858aa94700c0afa9be13e598`; generated 2026-09-15.
- Paths: `agents/core/detached_kernel.py`, focused `tests/test_detached_kernel.py`, this note.
- No protected kernel/security/coordinator policy changes; no SSH/Modal provisioning; no global report edits.
- Keep `PipeKernelBackend._child_env()` and Docker containment flags unchanged.
- Snapshot only HOME, PATH (executable resolution), DOCKER_CONFIG, DOCKER_CONTEXT, DOCKER_HOST and DOCKER_API_VERSION; no general credentials/proxy environment.
- A context is resolved to a fixed local Unix endpoint before launch; later process/config changes cannot redirect cleanup. Context discovery failure stays failed for this backend.
- Actual Docker operations use a private empty CLI config to prevent automatic proxy variable injection. Retain its TemporaryDirectory for the backend lifetime, including teardown retries.
- Docker image must already be available or publicly pullable; private-registry credential handling is outside this change.
- Rollback: revert this single coherent commit. Dependencies: existing stdlib and Docker, no Python dependencies added.

## Task 1: Regression, implementation, verification

- [x] Run existing detached transport tests as a clean baseline.
- [x] Add a subprocess-boundary test fixture returning the effective CLI arguments/environment; test task-local executable selection and frozen endpoint across environment mutation. Test explicit context precedence, default context discovery, concurrent initialization, unsupported/missing endpoints, and secret/proxy exclusion.
- [x] Run the new tests against the original implementation and record failures.
- [x] Add construction-time snapshots, serialized lazy endpoint resolution, and a private empty CLI config. Keep logical command arrays unchanged for local test doubles; substitute the resolved host prefix only at the actual subprocess boundary.
- [x] Keep existing output/time bounds for discovery and operations. Fail unavailable before container creation if discovery fails; never retry discovery to another daemon during teardown.
- [x] Run focused detached/session suites with isolated canonical data, existing pytest socket and timeout settings. Run lint and diff checks.
- [x] Verify the native macOS CLI against the retained Lima Unix socket with the real seven-test suite and a sentinel proxy/config context case. Stop VM and report evidence.
- [x] Commit only scoped changes; parent handles PRs, global counts, and integration.

## Verification and supported boundary

- Baseline detached tests: 15 passed. Eight initial regressions failed against the original implementation before the fix.
- Final focused detached/session suites: 67 passed; this slice adds 10 collected tests. Host CLI fixture tests require POSIX executable/Unix socket support and skip on Windows. Windows named pipes and remote Docker transports are outside this bounded local Unix implementation.
- Native macOS Python 3.12.14 + task-local Docker 29.8.0 + Lima Docker 29.1.3: unchanged real containment suite 7 passed, 0 skips in 5.58s, preserving pytest.ini socket and 30-second timeout restrictions.
- Separate native runtime verification: 2 passed in 5.17s for implicit current context and explicit context precedence, proxy/host-secret exclusion from actual container Config.Env, configuration mutation after launch, cancellation removal, and fresh reuse with lost-state reporting.
- Docker CLI extracted without system installation from Homebrew's official ARM64 Tahoe Docker 29.8.0 bottle, SHA256 `998293c4bd31551c89a433e216ae890e4e93c9835b5ac6a822455655367bef89`, matching published formula metadata. Docker's static distribution lacked a published .sha256 sidecar; it was not used.
- Real tests left no containers. Local 2GiB VM stopped after verification. Evidence retained outside the repository under `/private/tmp/nerva-h660-runtime/`.
- Empty CLI configuration remains owned by the backend's TemporaryDirectory object until backend disposal; failed teardown does not remove it. Endpoint freezes at first asynchronous discovery before any launch, while environment/executable selection freezes at construction.
- Ruff and git diff --check passed. Parent owns global collection counts, full integration run and PR workflow.
