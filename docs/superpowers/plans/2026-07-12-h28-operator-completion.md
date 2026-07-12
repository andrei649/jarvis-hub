# H28 Governed Desktop Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete H28.4-H28.6 with a real, default-off accessibility-first Windows desktop rail and machine-verifiable governance.

**Architecture:** A dependency-lazy `WindowsDesktopDriver` implements the existing driver protocol. A new `desktop.step` capability and `DesktopActionExecutor` mediate host execution through the Action Kernel, while ToolRPC only proposes gated work. Reality cases graduate the three wave-1 modules from the park policy.

**Tech Stack:** Python 3.12, optional pywinauto/Pillow host dependencies, FastAPI/Pydantic, existing Action Kernel/CapabilityActionAPI, pytest, React/OpenAPI parity gates.

## Global Constraints

- Default-off: host actuation requires `JARVIS_DESKTOP_HOST=1` and `JARVIS_DESKTOP_ISOLATED=1`.
- Accessibility tree is always attempted before local screen grounding.
- Mutating execution always crosses `desktop.step` at execution time; approval alone is not authorization.
- No arbitrary paths, shell strings, coordinate-only clicks, cloud VLM, ambient credentials, or raw host errors.
- New HTTP routes live in `agents/core/routers/multimodal.py`; no inline `agents/web.py` routes.
- User-facing endpoint changes update OpenAPI, route/auth snapshots, HUD punch-list, and mobile parity in the same PR.
- Use TDD for every production behavior: red test, observed failure, minimal green implementation, focused regression run.
- PR body declarations: `unpark: wave-1` and `unpark: park-policy`.

---

### Task 1: Optional accessibility-first Windows host driver

**Files:**
- Create: `agents/core/desktop_host.py`
- Create: `tests/test_h28_desktop_host.py`
- Modify: `docs/PLAYWRIGHT_OPERATOR.md`

**Interfaces:**
- Produces: `WindowsDesktopDriver.from_env(...)`, `perform(action: str, args: dict) -> dict`, `requires_kernel = True`.
- Consumes: injected `backend_factory`, `screenshotter`, `local_vlm_locator`, and canonical `app_launchers: Mapping[str, Sequence[str]]`.

- [ ] **Step 1: Write failing host-gate and accessibility-first tests**

```python
def test_from_env_requires_host_and_isolated_flags(monkeypatch):
    monkeypatch.delenv("JARVIS_DESKTOP_HOST", raising=False)
    with pytest.raises(DesktopHostDisabled):
        WindowsDesktopDriver.from_env()

async def test_locate_uses_accessibility_before_local_vlm(driver, local_vlm):
    result = await driver.perform("locate", {"query": "Save"})
    assert result["source"] == "accessibility"
    assert local_vlm.calls == []
```

- [ ] **Step 2: Run the new tests and verify they fail because the module is absent**

Run: `python -m pytest tests/test_h28_desktop_host.py -q`

Expected: collection failure for missing `agents.core.desktop_host`.

- [ ] **Step 3: Implement the bounded dependency-lazy driver**

```python
class WindowsDesktopDriver:
    requires_kernel = True

    @classmethod
    def from_env(cls, **kwargs):
        if not env_flag("JARVIS_DESKTOP_HOST") or not env_flag("JARVIS_DESKTOP_ISOLATED"):
            raise DesktopHostDisabled("isolated desktop host actuation is disabled")
        return cls(host_enabled=True, isolated=True, **kwargs)

    async def perform(self, action: str, args: dict) -> dict:
        if action in {"observe", "read", "locate", "screenshot"}:
            return await self._observe(action, args)
        return await self._mutate(action, args)
```

Normalize and cap accessibility elements, require a named element for click/type, require local fallback provenance, sanitize launcher keys, use argv with `shell=False`, cap screenshots before base64 encoding, and redact dependency/host exceptions.

- [ ] **Step 4: Run host-driver and adjacent desktop tests**

Run: `python -m pytest tests/test_h28_desktop_host.py tests/test_desktop_operator_h15_3.py tests/test_desktop_control.py -q`

Expected: all pass.

- [ ] **Step 5: Commit the driver slice**

```bash
git add agents/core/desktop_host.py tests/test_h28_desktop_host.py docs/PLAYWRIGHT_OPERATOR.md
git commit -m "feat(desktop): add isolated accessibility host driver"
```

### Task 2: Kernel-mediated desktop execution

**Files:**
- Modify: `agents/core/kernel/registry.py`
- Modify: `agents/core/capability_manifests.py`
- Modify: `agents/core/desktop_operator.py`
- Modify: `tests/_snapshots/action_auth.json`
- Modify: `tests/test_action_auth_matrix.py`
- Modify: `tests/test_h27_capability_manifests.py`
- Modify: `tests/test_desktop_operator_h15_3.py`

**Interfaces:**
- Produces: action kind `desktop.step`, capability id `action:desktop.step`, and `DesktopActionExecutor.perform(step, context) -> PerformResult`.
- Consumes: `CapabilityActionAPI`, `PerformContext`, and a driver implementing `perform`.

- [ ] **Step 1: Write failing manifest, kernel-invocation, and host-bypass tests**

```python
async def test_real_driver_refuses_without_action_executor():
    driver = FakeHostDriver(requires_kernel=True)
    result = await GovernedDesktop(driver=driver).run([{"action": "click", "args": {"query": "OK"}}], approver=allow)
    assert result["ran"][0]["reason"] == "kernel_required"
    assert driver.calls == []
```

Add `desktop.step` to the action-auth exerciser and assert an engaged spy/kill switch is reached before the driver.

- [ ] **Step 2: Run focused tests and observe missing registry/manifest/executor failures**

Run: `python -m pytest tests/test_desktop_operator_h15_3.py tests/test_h27_capability_manifests.py tests/test_action_auth_matrix.py -q`

Expected: failures naming the absent `desktop.step` capability and executor.

- [ ] **Step 3: Implement the manifest and executor**

```python
class DesktopActionExecutor:
    def __init__(self, driver, *, authorizer):
        self.driver = driver
        self.api = CapabilityActionAPI(authorizer=authorizer)
        self.api.register("action:desktop.step", self._execute)

    async def perform(self, step, context=None):
        return await self.api.perform("action:desktop.step", step, context)
```

The handler validates `action` and `args`, then calls the driver. `GovernedDesktop` uses the executor for `requires_kernel` drivers and never falls back to direct execution.

- [ ] **Step 4: Reseed action-auth snapshot and run focused tests**

Run: `python tests/test_action_auth_matrix.py --update`

Run: `python -m pytest tests/test_desktop_operator_h15_3.py tests/test_h27_capability_manifests.py tests/test_action_auth_matrix.py tests/test_h27_capability_actions.py -q`

Expected: all pass.

- [ ] **Step 5: Commit the governance slice**

```bash
git add agents/core/kernel/registry.py agents/core/capability_manifests.py agents/core/desktop_operator.py tests/_snapshots/action_auth.json tests/test_action_auth_matrix.py tests/test_h27_capability_manifests.py tests/test_desktop_operator_h15_3.py
git commit -m "feat(desktop): mediate host steps through action kernel"
```

### Task 3: Route and agent proposal wiring

**Files:**
- Modify: `agents/core/routers/multimodal.py`
- Modify: `agents/core/autonomy_coordinator.py`
- Create: `tests/test_h28_desktop_routes.py`
- Modify: `tests/test_agent_runtime_v2.py`
- Modify: `tests/_snapshots/route_surface.json`
- Modify: `tests/_snapshots/openapi_surface.json`
- Modify: `tests/_snapshots/route_auth.json`
- Modify: `frontend/src/api/schema.gen.ts`
- Modify: `docs/design/HUD_V2_REMAINING.md`
- Modify: `mobile/PARITY.md`

**Interfaces:**
- Produces: `POST /api/desktop/run` and gated ToolRPC tool `desktop_run`.
- Consumes: the live orchestrator kernel binding, `WindowsDesktopDriver.from_env`, and `DesktopActionExecutor`.

- [ ] **Step 1: Write failing route and ToolRPC registration tests**

```python
def test_desktop_run_is_user_guarded_and_default_off(client):
    response = client.post("/api/desktop/run", json={"steps": []})
    assert response.status_code == 200
    assert response.json()["reason"] == "desktop_host_disabled"

def test_desktop_tool_is_gated(runtime):
    spec = next(tool for tool in runtime.server.tools() if tool["name"] == "desktop_run")
    assert spec["gated"] is True
```

- [ ] **Step 2: Run the tests and verify route/tool absence**

Run: `python -m pytest tests/test_h28_desktop_routes.py tests/test_agent_runtime_v2.py -q`

Expected: 404 or missing-tool failures.

- [ ] **Step 3: Implement default-off route and gated proposal tool**

```python
@router.post("/api/desktop/run", dependencies=[Depends(user_guard)])
async def desktop_run(body: DesktopStepsBody):
    if not desktop_host_enabled():
        return nocache_json({"ok": False, "reason": "desktop_host_disabled"})
    return nocache_json(await build_desktop_runtime(get_orch()).run(body.steps))
```

Register `desktop_run` as `gated=True` with a bounded steps schema. Do not execute desktop work inside ToolRPC.

- [ ] **Step 4: Reseed route/OpenAPI/auth/type artifacts and update parity ledgers**

Run: `python tests/test_route_parity_guard.py --update`

Run: `python tests/test_openapi_parity_guard.py --update`

Run the repository's action/auth snapshot update command, then OpenAPI type generation. Add the HUD punch-list row and mark the mobile surface intentionally desktop-only.

- [ ] **Step 5: Run route, runtime, parity, and type gates**

Run: `python -m pytest tests/test_h28_desktop_routes.py tests/test_agent_runtime_v2.py tests/test_route_parity_guard.py tests/test_openapi_parity_guard.py tests/test_route_auth_matrix.py tests/test_openapi_ts_typegen_gate.py tests/test_hud_v2_parity.py -q`

Expected: all pass.

- [ ] **Step 6: Commit the integration slice**

```bash
git add agents/core/routers/multimodal.py agents/core/autonomy_coordinator.py tests/test_h28_desktop_routes.py tests/test_agent_runtime_v2.py tests/_snapshots frontend/src/api/schema.gen.ts docs/design/HUD_V2_REMAINING.md mobile/PARITY.md
git commit -m "feat(desktop): expose governed host execution proposal rail"
```

### Task 4: Operator reality benchmark and wave-1 graduation

**Files:**
- Modify: `agents/core/observability/reality_harness.py`
- Create: `tests/test_h28_operator_reality.py`
- Modify: `scripts/park_guard.py`
- Modify: `tests/test_park_guard.py`
- Modify: `BACKLOG.md`
- Modify: `project-status.json`
- Modify: `README.md`
- Modify: `JARVIS.md`
- Modify: `GO_LIVE_PLAN.md`
- Modify: `STATUS.md`

**Interfaces:**
- Produces: `OPERATOR_CAPABILITY_CASES` and permanent wave-1 unpark state.
- Consumes: `WindowsDesktopDriver`, `DesktopActionExecutor`, and the real kill-switch/kernel rail.

- [ ] **Step 1: Write failing reality and park-graduation tests**

```python
async def test_operator_reality_pack_has_zero_ungoverned_actions():
    result = await run_reality(OPERATOR_CAPABILITY_CASES, promote=False)
    assert result["passed"] == result["total"]
    assert all(case.metadata.get("ungoverned_actions") == 0 for case in OPERATOR_CAPABILITY_CASES)

def test_wave_one_modules_are_no_longer_parked():
    assert not {"browser_agent", "desktop_operator", "screen_grounding"} & set(guard.PARK_POLICY)
```

- [ ] **Step 2: Run tests and observe missing cases plus still-parked modules**

Run: `python -m pytest tests/test_h28_operator_reality.py tests/test_park_guard.py -q`

Expected: failures for missing `OPERATOR_CAPABILITY_CASES` and existing park entries.

- [ ] **Step 3: Add hermetic cases and graduate wave 1**

Add accessibility-first, fallback, kernel-halt, and zero-ungoverned-action cases to the canonical reality list. Remove only the three wave-1 entries from `PARK_POLICY`; keep wave 2, wave 3, training, rust, and self-protection unchanged.

- [ ] **Step 4: Update backlog and generated status once implementation tests are green**

Mark H28.4, H28.5, and H28.6 complete with exact evidence. Run:

`python scripts/status_sync.py --reuse-js-counts`

- [ ] **Step 5: Run the complete H28 verification set**

Run: `python -m pytest tests/test_h28_desktop_host.py tests/test_h28_desktop_routes.py tests/test_h28_operator_reality.py tests/test_h28_action_hierarchy_router.py tests/test_h28_playwright_driver.py tests/test_h28_terminal_targets.py tests/test_desktop_operator_h15_3.py tests/test_desktop_control.py tests/test_h15_1_browser_agent.py tests/test_h27_capability_actions.py tests/test_h27_capability_manifests.py tests/test_action_auth_matrix.py tests/test_park_guard.py tests/test_release_gate.py tests/test_status_sync.py -q`

Run: `ruff check` on every touched Python file, `bandit -q` on touched production Python, `git diff --check`, and `python scripts/status_sync.py --check --reuse-js-counts`.

Expected: all pass; the opt-in live desktop/Playwright tests may skip with explicit reasons.

- [ ] **Step 6: Commit the graduation and truth sync**

```bash
git add agents/core/observability/reality_harness.py tests/test_h28_operator_reality.py scripts/park_guard.py tests/test_park_guard.py BACKLOG.md project-status.json README.md JARVIS.md GO_LIVE_PLAN.md STATUS.md
git commit -m "feat(operator): complete H28 governed desktop reality rail"
```
