# HUD Honesty and H28 Operator Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make live HUD state evidence-backed, isolate test data from the owner's runtime, and expose the already-governed H28 browser/desktop surface in Console without creating an execution bypass.

**Architecture:** Introduce one URL-owned demo hook, one shared local-provider inventory projection, explicit current/history task views, pure frontend truth/reducer helpers, and a standalone Operator panel. Preserve legacy response aliases and routes while moving every V2 consumer to explicit configured/resident/source-aware fields. Desktop preview and run share the same validator; mobile retains only reject/defer for server-desktop proposals.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, httpx, pytest/pytest-xdist, React 19, TypeScript, Vitest/Testing Library, React Native/Jest, Vite.

## Global Constraints

- Work only on `codex/hud-honesty-operator-surface` in the isolated worktree.
- Keep every production change behind an observed failing test.
- Do not add routes, weaken guards, enable flags, mutate live history, or lower existing server-side plan maxima.
- Keep `active` as a deprecated model-configuration alias, but do not read it from V2 code.
- Never persist or render browser/desktop typed text, raw screenshots, full accessibility trees, paths, base64 data, or raw result JSON.
- Keep browser preview-only; desktop submission must continue through the existing ToolRPC, approval, and Action Kernel path.
- Use one independently reviewable commit per task. Run the stated focused checks before each commit.
- Before each task commit, generate the task diff package, run a fresh spec-compliance review, then a separate code-quality review; remediate findings and rerun every affected test before staging.
- Update generated artifacts only after source contracts are green; stage removed hashed bundles with `git add -A agents/web/v2`.

---

## Task 1: Make demo mode URL-owned

**Files:**

- Create: `frontend/src/demo-mode.ts`
- Create: `frontend/src/test/demo-mode.test.tsx`
- Modify: `frontend/src/app.tsx`

**Interfaces:** `readDemoMode(search: string): boolean`; `replaceDemoMode(enabled: boolean,
href?: string): string`; `useDemoMode(): [boolean, (enabled: boolean) => void]`. `App` remains the
single owner and passes the existing `demo` boolean plus setter to descendants.

- [ ] **Step 1: Write failing URL and hook tests**

Test the pure contract and a small hook harness:

```tsx
expect(readDemoMode('?demo=1')).toBe(true)
expect(readDemoMode('?demo=10&notdemo=1')).toBe(false)

const next = replaceDemoMode(true, 'http://jarvis/v2/?theme=dark&demo=0#mesh')
expect(next).toBe('/v2/?theme=dark&demo=1#mesh')

localStorage.setItem('hud.demo', '1')
window.history.replaceState({}, '', '/v2/')
render(<DemoHarness />)
expect(screen.getByTestId('mode')).toHaveTextContent('live')

act(() => {
  window.history.pushState({}, '', '/v2/?demo=1')
  window.dispatchEvent(new PopStateEvent('popstate'))
})
expect(screen.getByTestId('mode')).toHaveTextContent('demo')
```

Also cover duplicate/conflicting `demo` parameters, disabling demo while preserving unrelated query/hash state, `replaceState` rather than `pushState`, and visible demo-banner copy containing the canonical share path `/v2/?demo=1`.

- [ ] **Step 2: Run the focused test and observe RED**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/test/demo-mode.test.tsx
```

Expected: FAIL because `demo-mode.ts` does not exist and App still consults `hud.demo`.

- [ ] **Step 3: Implement the pure URL helpers and hook**

Use exact query semantics and a canonical visible URL:

```ts
export function readDemoMode(search: string): boolean {
  return new URLSearchParams(search).getAll('demo').includes('1')
}

export function replaceDemoMode(enabled: boolean, href = window.location.href): string {
  const url = new URL(href, window.location.origin)
  url.searchParams.delete('demo')
  if (enabled) url.searchParams.append('demo', '1')
  return `${url.pathname}${url.search}${url.hash}`
}

export function useDemoMode(): [boolean, (enabled: boolean) => void] {
  const [demo, setDemoState] = useState(() => readDemoMode(window.location.search))
  useEffect(() => {
    const sync = () => setDemoState(readDemoMode(window.location.search))
    window.addEventListener('popstate', sync)
    return () => window.removeEventListener('popstate', sync)
  }, [])
  const setDemo = useCallback((enabled: boolean) => {
    window.history.replaceState(window.history.state, '', replaceDemoMode(enabled))
    setDemoState(enabled)
  }, [])
  return [demo, setDemo]
}
```

Replace only App's demo initializer/effect with `useDemoMode()`. Keep the existing callbacks passed to banner, top bar, first-run, and empty state. Add `/v2/?demo=1` to the visible DemoBanner provenance line so copied screenshots and links identify the demo address.

- [ ] **Step 4: Run focused and frontend safety checks**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/test/demo-mode.test.tsx src/test/first-run-gate.test.tsx
npm.cmd run typecheck
```

Expected: all selected tests pass and TypeScript exits 0.

- [ ] **Step 5: Review and commit**

Check `rg "hud\.demo|localStorage" frontend/src/app.tsx frontend/src/demo-mode.ts` proves neither file reads or writes `hud.demo`, then commit:

```powershell
git add frontend/src/demo-mode.ts frontend/src/test/demo-mode.test.tsx frontend/src/app.tsx
git commit -m "fix: make HUD demo mode URL-owned"
```

---

## Task 2: Establish shared configured/available/resident model truth

**Files:**

- Create: `agents/core/llm/local_model_inventory.py`
- Create: `tests/test_local_model_inventory.py`
- Create: `tests/test_local_model_status.py`
- Modify: `agents/web.py`
- Modify: `agents/core/routers/models_llm.py`
- Modify: `agents/core/routers/status.py`
- Modify: `tests/test_local_models_api.py`

**Interfaces:** async `get_local_model_inventory(*, router=None, controller=None,
force_refresh=False) -> dict[str, Any]`; `project_llm_status(inventory) -> dict[str, Any]`;
`invalidate_local_model_inventory_cache() -> None`. `LocalInventory` retains legacy top-level and
row `active` aliases while adding `configured_model`, `resident_models: list[{provider,id}]`,
`providers`, per-row `available/configured/resident`, and explicit lifecycle `controls`. `/status`
adds the same `resident_models` and aggregate `residency_state` while retaining
`model_state/model_loaded/loaded_model`.

- [ ] **Step 1: Write failing inventory matrix tests**

Cover LM Studio catalog `/v1/models`, LM Studio native residency `/api/v0/models`, Ollama catalog `/api/tags`, Ollama residency `/api/ps`, and these cases: zero/one/multiple residents, Ollama-only resident, identical ids under two providers, configured id absent from catalog, resident absent from catalog, exact case-sensitive ids, outer whitespace trimming, provider probe failure, cache reuse/expiry/invalidation, and controller disabled. Include an ambiguous configured id with no configured provider and assert exactly one synthetic `{provider: "unknown", id: "alpha"}` row is configured while neither real-provider row is configured.

Assert the stable pair identity and explicit controls:

```py
assert inventory["resident_models"] == [
    {"provider": "lm-studio", "id": "alpha"},
    {"provider": "ollama", "id": "alpha"},
]
assert lm_row["configured"] is True
assert lm_row["active"] is True
assert lm_row["resident"] is False
assert lm_row["controls"] == {
    "can_configure": True,
    "can_load": True,
    "can_unload": False,
}
assert ollama_row["controls"]["can_load"] is False
assert ollama_row["controls"]["can_unload"] is False
```

- [ ] **Step 2: Write failing endpoint agreement tests**

Monkeypatch the shared helper and assert `/status` and `/api/models/local` agree. Preserve the late-bound `models_llm._web()` seam used by existing tests.

```py
assert status["model_loaded"] == bool(models["resident_models"])
assert status["resident_models"] == models["resident_models"]
assert status["residency_state"] == models["residency_state"]
```

Exercise precedence `ready > unknown > no_model > offline`, including `ready` with aggregate residency `unknown`, and configured-resident preference for `loaded_model`.

- [ ] **Step 3: Run focused backend tests and observe RED**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_local_model_inventory.py tests/test_local_model_status.py tests/test_local_models_api.py -q
```

Expected: FAIL because the shared inventory and new fields do not exist.

- [ ] **Step 4: Implement the shared inventory**

Expose exactly three public call seams: `get_local_model_inventory(*, router=None,
controller=None, force_refresh=False) -> dict[str, Any]` as an async function,
`project_llm_status(inventory: dict[str, Any]) -> dict[str, Any]`, and
`invalidate_local_model_inventory_cache() -> None`.

The implementation must:

- probe provider URLs from `router.lm_studio_url` and `router.ollama_url`;
- use `router._backend_name` as provider identity, never parse composite `router.name`;
- cache only raw probe results, then recompute configured/active/control projections on every call;
- merge by `(provider, trimmed exact id)` and sort provider then id;
- assign independent `catalog_state` and `residency_state` values;
- synthesize configured/resident-only rows without inventing lifecycle capability;
- derive lifecycle capability only from LM Studio controller enablement plus known availability/residency.

Use these exact aggregation rules:

```py
provider["online"] = catalog_ok or residency_ok
provider["catalog_state"] = "known" if catalog_ok else ("unknown" if residency_ok else "offline")
provider["residency_state"] = "known" if residency_ok else ("unknown" if catalog_ok else "offline")

aggregate_residency = (
    "offline" if not any(p["online"] for p in providers)
    else "unknown" if any(p["online"] and p["residency_state"] == "unknown" for p in providers)
    else "known"
)
```

Build each provider independently before unioning rows so one provider failure cannot erase the
other's evidence. If router provider is present, configure only that exact pair. If it is absent,
configure the sole exact-id pair only when unambiguous; otherwise append the one unknown-provider
synthetic row. The switch endpoint resolves only rows where `available is True`; an ambiguous id
returns a bounded client error rather than selecting a provider arbitrarily.

- [ ] **Step 5: Wire compatibility projections and cache invalidation**

Keep `web._list_local_models()` and `web._llm_ready()` callable as thin projections. Make `/status` await the same inventory and add `resident_models` plus `residency_state`. Reject model switch unless `available is True`. On successful LM Studio load/unload, invalidate the inventory cache before returning.

Do not expose raw probe exception strings from the unguarded status route.

- [ ] **Step 6: Run focused tests and static checks**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_local_model_inventory.py tests/test_local_model_status.py tests/test_local_models_api.py tests/test_llm_status_api.py -q
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m ruff check agents/core/llm/local_model_inventory.py agents/web.py agents/core/routers/models_llm.py agents/core/routers/status.py tests/test_local_model_inventory.py tests/test_local_model_status.py tests/test_local_models_api.py
```

Expected: all selected tests pass; Ruff exits 0.

- [ ] **Step 7: Review and commit**

Verify `active` equals `configured`, provider failures remain bounded, and no route/guard changed. Commit:

```powershell
git add agents/core/llm/local_model_inventory.py agents/web.py agents/core/routers/models_llm.py agents/core/routers/status.py tests/test_local_model_inventory.py tests/test_local_model_status.py tests/test_local_models_api.py
git commit -m "feat: expose truthful local model residency"
```

---

## Task 3: Split running/history task truth and isolate pytest data

**Files:**

- Modify: `agents/core/routers/dashboard.py`
- Modify: `tests/test_dashboard.py`
- Modify: `tests/conftest.py`
- Create: `tests/support/pytest_data_root_probe.py`
- Create: `tests/test_pytest_data_isolation.py`
- Modify if required by isolation regression: `tests/test_jarvis_home.py`

**Interfaces:** existing `GET /tasks` gains `view: Literal["running", "history"] | None` and a
declared response model containing `tasks`, `view: "legacy"|"running"|"history"`,
`source: "autonomy_queue"`, `history_included: bool`, and UTC `as_of: datetime`. The no-query
selection remains legacy-compatible. Pytest sets process-local `JARVIS_HOME` and `JARVIS_KEY_DIR`
before any Jarvis module import; individual tests may still override them.

Define and bind the response model exactly at the existing route:

```py
class TasksResponse(BaseModel):
    tasks: list[dict[str, Any]]
    view: Literal["legacy", "running", "history"]
    source: Literal["autonomy_queue"] = "autonomy_queue"
    history_included: bool
    as_of: datetime


@router.get("/tasks", response_model=TasksResponse)
async def get_tasks(
    view: Literal["running", "history"] | None = Query(default=None),
) -> TasksResponse:
```

- [ ] **Step 1: Write failing task-view contract tests**

Test `view=running`, `view=history`, invalid view 422, and the untouched no-query migration behavior. Explicit views derive the state as:

```py
def _effective_task_state(task: dict[str, Any]) -> str:
    state = task.get("state")
    value = state if isinstance(state, str) and state.strip() else task.get("status")
    return value.strip().lower() if isinstance(value, str) else ""
```

Assert `state` wins conflicts; only exact normalized `running` is live; explicit running never falls back; history excludes running; legacy remains raw case-sensitive OR plus 30-row fallback. Assert owner precedence `owner`, `agent_id`, `agent`, `jarvis` and response metadata `view`, `source`, `history_included`, UTC `as_of`.

- [ ] **Step 2: Write the failing subprocess isolation proof**

The parent test creates an operator sentinel directory and launches an explicit child probe with ambient `JARVIS_HOME`/`JARVIS_KEY_DIR` pointing at it. The child imports Jarvis only after conftest has run, then proves:

```py
assert Path(data_root()).is_relative_to(Path(os.environ["JARVIS_HOME"]))
assert Path(TaskQueue.DEFAULT_DB).is_relative_to(Path(os.environ["JARVIS_HOME"]))
```

It enters full `TestClient(web.app)` lifespan and submits an autonomy task. The parent fingerprints the sentinel before/after and asserts no file or database changed.

- [ ] **Step 3: Run the focused tests and observe RED**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_dashboard.py tests/test_pytest_data_isolation.py -q
```

Expected: FAIL because task views/metadata and unconditional serial isolation do not exist.

- [ ] **Step 4: Implement explicit task views without breaking legacy**

Implement the typed query/response model declared in the Interfaces block. Keep the no-query
selection algorithm unchanged. Explicit running uses the normalized helper and returns no history
fallback. Explicit history returns only non-running recent rows. Normalize ownership with
`owner or agent_id or agent or "jarvis"`. Return timezone-aware UTC `as_of` and truthful metadata.

- [ ] **Step 5: Create per-process pytest roots before Jarvis imports**

At the top of `tests/conftest.py`, create one temporary root per process and assign both variables, never `setdefault`:

```py
_PYTEST_DATA_ROOT = tempfile.mkdtemp(prefix="jarvis-pytest-")
os.environ["JARVIS_HOME"] = _PYTEST_DATA_ROOT
os.environ["JARVIS_KEY_DIR"] = str(Path(_PYTEST_DATA_ROOT) / "keys")
atexit.register(shutil.rmtree, _PYTEST_DATA_ROOT, ignore_errors=True)
```

Tests may still monkeypatch these values later. Ensure module reload tests restore the temporary test root rather than repository `memory_logs`.

- [ ] **Step 6: Run serial and xdist isolation checks**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_dashboard.py tests/test_pytest_data_isolation.py tests/test_jarvis_home.py -q
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_pytest_data_isolation.py -n 2 --dist loadfile -q
```

Expected: all selected tests pass in serial and xdist; the sentinel fingerprint is unchanged.

- [ ] **Step 7: Review and commit**

Verify the subprocess invokes only the tracked support probe, never the full suite recursively. Commit:

```powershell
git add agents/core/routers/dashboard.py tests/test_dashboard.py tests/conftest.py tests/support/pytest_data_root_probe.py tests/test_pytest_data_isolation.py tests/test_jarvis_home.py
git commit -m "fix: isolate test data and expose current task views"
```

---

## Task 4: Make the model panel, live loader, Mesh, and Cinema truthful

**Files:**

- Create: `frontend/src/task-state.ts`
- Create: `frontend/src/test/local-models.test.tsx`
- Create: `frontend/src/test/loaders.test.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/live.ts`
- Modify: `frontend/src/api/loaders.ts`
- Modify: `frontend/src/app.tsx`
- Modify: `frontend/src/gap.tsx`
- Modify: `frontend/src/mesh.tsx`
- Modify: `frontend/src/shell.tsx`
- Modify: `frontend/src/test/mesh.test.tsx`
- Modify: `frontend/src/test/cinema.test.tsx`
- Modify: `frontend/src/test/gap-panels.test.tsx`

**Interfaces:** `LocalModelRef = {provider: string; id: string}`;
`LlmLiveState = {state: ModelState; model: string|null; residents: LocalModelRef[]}`;
`LiveSources` gains `tasks: boolean` and `trust: boolean`; `effectiveTaskState(task): string` and
`runningTasks(tasks): Task[]` are the shared defensive filter. `NeuralMesh` and `CinemaMesh` both
receive identical `llm`, `trust`, `sources`, `tasks`, and `demo` props. `deriveMeshModels` returns
stable nodes keyed by provider/id or `cloud:claude|cloud:generic`.

- [ ] **Step 1: Write failing adapter and model-panel tests**

Define `LocalModelRef` as `{ provider: string; id: string }`. Make the loader retain every `/status.resident_models` pair and request `/tasks?view=running`. Prove it re-filters terminal rows, clears trust evidence at each cycle, and sets `sources.trust=true` only after a successful current trust response.

Test panel precedence: resident → `loaded`; `null` → `residency unknown`; available → `ready`; available null → `availability unknown`; else unavailable. Test the independent configured badge and assert lifecycle buttons come only from `controls`. Assert no free-form load/unload form exists and an Ollama row never calls `/api/llm/load|unload`.

- [ ] **Step 2: Write failing Mesh/Cinema truth tests**

Export pure helpers and assert:

```ts
expect(deriveMeshModels({ demo: false, residents: [], trustEvidence: false, trust: null })).toEqual([])
expect(deriveMeshModels({
  demo: false,
  residents: [{ provider: 'lm-studio', id: 'a' }, { provider: 'ollama', id: 'b' }],
  trustEvidence: true,
  trust: { claude_available: true, cloud_available: true },
}).map(model => model.key)).toEqual(['lm-studio:a', 'ollama:b', 'cloud:claude'])
```

Test `busy|active` only, no live random cascades, terminal-task defensive filtering, five dots per owner, three text labels plus `+N more`, truthful tooltip copy, and legend states `demo`, `live telemetry`, or `no live activity`. Assert Cinema receives the same truth props and does not count `ready` agents as executing.

- [ ] **Step 3: Run focused frontend tests and observe RED**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/test/local-models.test.tsx src/test/loaders.test.ts src/test/mesh.test.tsx src/test/cinema.test.tsx src/test/gap-panels.test.tsx
```

Expected: FAIL on missing resident/source-aware fields and current fallback/demo behavior.

- [ ] **Step 4: Implement shared task and live-source normalization**

Use the same precedence as the explicit backend view:

```ts
export function effectiveTaskState(task: Task): string {
  const state = typeof task.state === 'string' && task.state.trim() ? task.state : task.status
  return typeof state === 'string' ? state.trim().toLowerCase() : ''
}

export const runningTasks = (tasks: Task[]) =>
  tasks.filter(task => effectiveTaskState(task) === 'running')
```

Initialize a fresh `sources` object every load cycle. Request `/tasks?view=running`, re-filter, retain all resident pairs, and pass the same data from App into cockpit and Cinema.

- [ ] **Step 5: Implement model-panel and Mesh truth**

Move all V2 reads from `active` to `configured`/`resident`/`controls`. Remove free-form lifecycle submission; row lifecycle and separate configure actions are the only controls.

In live Mesh, demo constants are forbidden. Build nodes from all resident pairs plus a current-evidence cloud lane; support an empty list. Gate flow animation on actual running tasks or agents whose normalized status is `busy`/`active`. Demo can retain choreography. Sanitize label volume and copy exactly as specified.

- [ ] **Step 6: Run focused, typecheck, and full frontend tests**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/test/local-models.test.tsx src/test/loaders.test.ts src/test/mesh.test.tsx src/test/cinema.test.tsx src/test/gap-panels.test.tsx
npm.cmd run typecheck
npm.cmd test
```

Expected: focused and full Vitest pass and typecheck exits 0. The production bundle build is
deliberately deferred to Task 7 so this source commit leaves no generated working-tree changes.

- [ ] **Step 7: Review and commit source changes**

Commit source/tests with a clean generated-output tree:

```powershell
git add frontend/src/task-state.ts frontend/src/api/types.ts frontend/src/api/live.ts frontend/src/api/loaders.ts frontend/src/app.tsx frontend/src/gap.tsx frontend/src/mesh.tsx frontend/src/shell.tsx frontend/src/test/local-models.test.tsx frontend/src/test/loaders.test.ts frontend/src/test/mesh.test.tsx frontend/src/test/cinema.test.tsx frontend/src/test/gap-panels.test.tsx
git commit -m "fix: ground HUD model and activity state in evidence"
```

---

## Task 5: Enforce browser and desktop preview/run validation parity

**Files:**

- Modify: `agents/core/routers/browser.py`
- Modify: `agents/core/desktop_operator.py`
- Modify: `agents/core/routers/multimodal.py`
- Modify: `tests/test_h15_1_browser_agent.py`
- Modify: `tests/test_desktop_operator_h15_3.py`
- Modify: `tests/test_h28_desktop_routes.py`
- Modify: `tests/test_h28_operator_reality.py`

**Interfaces:** `BrowserCheckBody(url<=2000, allowlist<=100 with each domain<=253)`;
`BrowserPreviewBody(plan<=200, allowlist<=100)` with a discriminated union of exact
`navigate(url)`, `extract(selector)`, `click(selector)`, `type(selector,text)`, and
`submit(selector)` step shapes and `extra="forbid"`. Preview returns only
`{index,action,kind,decision,reason}` projections. `validate_desktop_run_args(raw) ->
{"steps": normalized_steps}` or raises `DesktopProposalError(reason)`; both desktop routes call it
before any host/runtime/ToolRPC seam.

- [ ] **Step 1: Write failing strict browser request tests**

Use a table of invalid actions/shapes: unknown action, extra/missing keys, non-string values, URL > 2,000, domain > 253, selector > 512, type text > 4,000. Assert HTTP 422 is bounded and `GovernedBrowser.preview()` is not called. Keep existing server allowlist maximum 100 and plan maximum 200; UI caps will be 20.

Assert preview projection contains only `index`, `action`, `kind`, `decision`, and reason capped to 240; type text never appears.

Use explicit accepted/rejected boundary pairs at 2,000/2,001 URL characters, 253/254 domain
characters, 512/513 selector characters, and 4,000/4,001 type-text characters. Assert check reasons
are also capped at 240.

- [ ] **Step 2: Write failing desktop parity tests**

Table-drive empty, `wait`, `teleport`, malformed `read/locate/click/type/launch`, extra keys, and text limits through both `/api/desktop/preview` and `/api/desktop/run`. Assert identical `{ok:false, reason}` families and zero ToolRPC/driver calls. Assert validation occurs before the host-enabled check. Keep `ungoverned_actions == 0` in the reality harness.

- [ ] **Step 3: Run focused backend tests and observe RED**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_h15_1_browser_agent.py tests/test_desktop_operator_h15_3.py tests/test_h28_desktop_routes.py tests/test_h28_operator_reality.py -q
```

Expected: FAIL because browser dictionaries are permissive, preview accepts invalid desktop steps, and empty plans can pass `all([])`.

- [ ] **Step 4: Implement typed browser validation and bounded projection**

Accept only:

```text
navigate(url)
extract(selector)
click(selector)
type(selector, text)
submit(selector)
```

Implement action-specific Pydantic models using `Literal` action fields and `ConfigDict(extra="forbid")`, then validate exact keys/types/caps before `GovernedBrowser.preview()`. Keep domain/SSRF decisions in the governed browser. Map every internal preview entry through a bounded projection rather than returning arbitrary internal plan objects.

- [ ] **Step 5: Share desktop validation and normalization**

Update `validate_desktop_run_args()` to reject empty steps with `empty_steps` and return normalized steps. Both preview and run call it first; preview classifies those normalized steps, and run checks host flags only after validation. Preserve type text while lower-casing actions, trimming non-text arguments, and using fixed action-key order.

- [ ] **Step 6: Run focused tests and reality gate**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_h15_1_browser_agent.py tests/test_desktop_operator_h15_3.py tests/test_h28_desktop_routes.py tests/test_h28_operator_reality.py -q
```

Expected: all selected tests pass and the reality report still records zero ungoverned actions.

- [ ] **Step 7: Review and commit**

Verify routes, auth guards, ToolRPC, approval, and default-off gates are unchanged. Commit:

```powershell
git add agents/core/routers/browser.py agents/core/desktop_operator.py agents/core/routers/multimodal.py tests/test_h15_1_browser_agent.py tests/test_desktop_operator_h15_3.py tests/test_h28_desktop_routes.py tests/test_h28_operator_reality.py
git commit -m "fix: align governed browser and desktop validation"
```

---

## Task 6: Add the preview-first Operator panel and exact result reducer

**Files:**

- Create: `frontend/src/operator-contract.ts`
- Create: `frontend/src/operator-panel.tsx`
- Create: `frontend/src/test/operator-contract.test.ts`
- Create: `frontend/src/test/operator-panel.test.tsx`
- Modify: `frontend/src/gap.tsx`
- Modify: `frontend/src/test/gap-panels.test.tsx`
- Modify: `tests/test_hud_v2_parity.py`

**Interfaces:** `canonicalizeDesktopSteps(steps): CanonicalDesktopStep[]`;
`desktopPlanSignature(steps): string`; `reduceDesktopOutcome(context, result, submittedCount):
'proposed'|'queued'|'blocked'|'failed'|'partial'|'executed'`;
`sanitizeDesktopResult(result): SafeDesktopResult`. `OperatorPanel` calls the existing user-token
`apiPost` helper for exactly four endpoints and exposes no admin-token or caller-approval field.

- [ ] **Step 1: Write failing pure contract tests**

Test `canonicalizeDesktopSteps`, `desktopPlanSignature`, `reduceDesktopOutcome`, and `sanitizeDesktopResult`. Canonicalization lower-cases actions, trims non-text fields, preserves `type.text`, fixes key order, deep clones, and rejects unsupported/empty/oversized data.

Use the exact reducer order:

```ts
if (context === 'preview') return 'proposed'
if (ranCount === 0 && result.approval_required && boundedTaskId) return 'queued'
if (submittedCount > 0 && result.ok === true && returnedCount === submittedCount && ranCount === submittedCount) return 'executed'
if (ranCount > 0) return 'partial'
if (isGovernanceRefusal(result)) return 'blocked'
return 'failed'
```

Test action 64, reason 240, task id 128, source 64, read result 1,000, at most ten elements, role/name 120, numeric count, truncation marker; forbid type text, screenshots, base64, paths, raw arrays/objects.

- [ ] **Step 2: Write failing panel interaction tests**

Assert no network calls on mount; structured browser/desktop safe subsets only; browser check/preview exact payloads; empty allowlist fail-closed copy; type rows display `N characters`; no browser Run button. Exercise UI caps at 20/21 allowlist entries, 20/21 browser steps, 20/21 desktop steps, and exact/one-past URL 2,000, domain 253, selector 512, and type text 4,000.

For desktop: preview stores a deep canonical snapshot; edit invalidates preview; submit sends the snapshot; payload has no approval fields; requests are disabled in flight. Test proposed, queued, blocked, failed, partial, executed, per-step rendering, Decision Inbox pointer, and exact partial warning `Do not retry the whole plan: some steps already ran`. Reject each of the four endpoint calls in separate tests and require a visible bounded error without stale success state. Cap browser-check and preview reasons at 240 in rendered output.

- [ ] **Step 3: Strengthen the failing HUD parity gate**

Require a real `OperatorPanel` caller for all four existing endpoints:

```text
/api/browser/check
/api/browser/plan/preview
/api/desktop/preview
/api/desktop/run
```

The gate must not pass merely because Console → Build exists.

- [ ] **Step 4: Run focused tests and observe RED**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/test/operator-contract.test.ts src/test/operator-panel.test.tsx src/test/gap-panels.test.tsx
Set-Location ..
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_hud_v2_parity.py -q
```

Expected: FAIL because the Operator source and callers do not exist.

- [ ] **Step 5: Implement the pure contract and standalone panel**

Use the existing user-token `apiPost` helper. Keep transient secrets only in component state; render only sanitized projections. Cap browser allowlist/steps and desktop steps at 20. Do not export raw state or persist inputs. Label browser results `policy dry run`.

- [ ] **Step 6: Register Console → Build and pass parity**

Import `OperatorPanel` into `gap.tsx` and add a Build section entry without moving unrelated panels. Ensure panel source contains the endpoint calls so the strengthened parity test can trace them.

- [ ] **Step 7: Run focused and full frontend checks**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/test/operator-contract.test.ts src/test/operator-panel.test.tsx src/test/gap-panels.test.tsx
npm.cmd run typecheck
npm.cmd test
Set-Location ..
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_hud_v2_parity.py -q
```

Expected: focused/full frontend and HUD parity pass.

- [ ] **Step 8: Review and commit**

Search for forbidden surfaces and caller approval fields, then commit:

```powershell
git add frontend/src/operator-contract.ts frontend/src/operator-panel.tsx frontend/src/test/operator-contract.test.ts frontend/src/test/operator-panel.test.tsx frontend/src/gap.tsx frontend/src/test/gap-panels.test.tsx tests/test_hud_v2_parity.py
git commit -m "feat: add governed Operator HUD surface"
```

---

## Task 7: Enforce mobile boundary, synchronize ledgers, generate artifacts, and verify the batch

**Files:**

- Create: `mobile/src/screens/approvalPolicy.ts`
- Create: `mobile/src/screens/__tests__/approvalsDesktopBoundary.test.ts`
- Modify: `mobile/src/screens/ApprovalsScreen.tsx`
- Modify: `mobile/PARITY.md`
- Modify: `docs/design/HUD_V2_REMAINING.md`
- Modify: `BACKLOG.md`
- Modify: `STATUS.md`
- Modify: `tests/test_openapi_ts_typegen_gate.py`
- Modify generated: `frontend/src/api/schema.gen.ts`
- Modify generated: `agents/web/v2/`
- Regenerate if changed: `tests/_snapshots/openapi_surface.json`

**Interfaces:** `approvalPolicy(task): {showPayload,canApprove,canReject,canDefer}` is a pure native
UI policy; it changes no server/API authorization. The generated schema must represent the
`view=running|history` query and declared `TasksResponse`. The production V2 bundle must be generated
from the exact committed frontend source.

- [ ] **Step 1: Write the failing mobile boundary test**

Use a pure policy helper and a source-contract test. For `toolrpc.desktop_run`, assert:

```ts
expect(approvalPolicy(task)).toEqual({
  showPayload: false,
  canApprove: false,
  canReject: true,
  canDefer: true,
})
```

The rendered card must contain `Approval unavailable in mobile app · continue in Owner HUD`, omit the payload, omit the Approve control/callback, and retain Reject/Defer.

- [ ] **Step 2: Run focused mobile tests and observe RED**

Run:

```powershell
Set-Location mobile
npm.cmd test -- --runInBand src/screens/__tests__/approvalsDesktopBoundary.test.ts
```

Expected: FAIL because Approvals renders every payload and Approve action.

- [ ] **Step 3: Implement the native UI-only policy boundary**

Apply `approvalPolicy(task)` before rendering payload/actions. Do not change the generic task API, server guards, or responsive browser HUD. Preserve reject/defer dispatch exactly.

- [ ] **Step 4: Run focused and full mobile checks**

Run:

```powershell
Set-Location mobile
npm.cmd test -- --runInBand src/screens/__tests__/approvalsDesktopBoundary.test.ts
npm.cmd test -- --runInBand
npx.cmd tsc --noEmit
```

Expected: focused/full Jest and TypeScript pass.

- [ ] **Step 5: Regenerate OpenAPI TypeScript schema**

First extend `tests/test_openapi_ts_typegen_gate.py` with a semantic source assertion that the
generated `/tasks` operation contains `view` and both `running` and `history`, then run it and
observe RED because the committed schema predates that query contract:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_openapi_ts_typegen_gate.py -q
```

Then start an isolated hidden app process, wait for `/openapi.json`, generate, and always stop it:

```powershell
$root = (Get-Location).Path
$python = 'C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe'
$oldHome = $env:JARVIS_HOME
$oldKeyDir = $env:JARVIS_KEY_DIR
$oldTesting = $env:JARVIS_TESTING
$schemaHome = Join-Path ([IO.Path]::GetTempPath()) "jarvis-schema-$PID"
New-Item -ItemType Directory -Path (Join-Path $schemaHome 'keys') -Force | Out-Null
$env:JARVIS_HOME = $schemaHome
$env:JARVIS_KEY_DIR = Join-Path $schemaHome 'keys'
$env:JARVIS_TESTING = '1'
$server = $null
try {
  $server = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','agents.web:app','--host','127.0.0.1','--port','8765') -WorkingDirectory $root -WindowStyle Hidden -PassThru
  $ready = $false
  foreach ($attempt in 1..60) {
    try {
      Invoke-WebRequest 'http://127.0.0.1:8765/openapi.json' -UseBasicParsing | Out-Null
      $ready = $true
      break
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  if (-not $ready) { throw 'OpenAPI server did not become ready on port 8765' }
  Push-Location frontend
  try { npm.cmd run typegen:openapi } finally { Pop-Location }
} finally {
  if ($null -ne $server -and -not $server.HasExited) { Stop-Process -Id $server.Id }
  if ($null -eq $oldHome) { Remove-Item Env:JARVIS_HOME -ErrorAction SilentlyContinue } else { $env:JARVIS_HOME = $oldHome }
  if ($null -eq $oldKeyDir) { Remove-Item Env:JARVIS_KEY_DIR -ErrorAction SilentlyContinue } else { $env:JARVIS_KEY_DIR = $oldKeyDir }
  if ($null -eq $oldTesting) { Remove-Item Env:JARVIS_TESTING -ErrorAction SilentlyContinue } else { $env:JARVIS_TESTING = $oldTesting }
  $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
  $resolvedSchema = [IO.Path]::GetFullPath($schemaHome)
  if (-not $resolvedSchema.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing to remove non-temp schema root' }
  Remove-Item -LiteralPath $resolvedSchema -Recurse -Force -ErrorAction SilentlyContinue
}

& $python tests/test_openapi_parity_guard.py --update
& $python -m pytest tests/test_openapi_parity_guard.py tests/test_openapi_ts_typegen_gate.py -q
```

Expected: both gates pass and the generated schema includes the `/tasks` enum/response. The snapshot
reseed command is mandatory even though its route-only projection may remain byte-identical; route
and auth snapshots must otherwise remain unchanged.

- [ ] **Step 6: Build and stage the V2 bundle**

Run:

```powershell
Set-Location frontend
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
Set-Location ..
git add -A agents/web/v2 frontend/src/api/schema.gen.ts tests/_snapshots/openapi_surface.json
```

Expected: typecheck, all Vitest, and Vite build pass; obsolete hashed assets are staged as deletions.

- [ ] **Step 7: Update truth and parity ledgers from measured results**

Update:

- `docs/design/HUD_V2_REMAINING.md`: H28 Operator depth complete with test evidence;
- `mobile/PARITY.md`: browser policy preview and server-desktop rows are mobile `➖`, with server-desktop payload hidden/no approve;
- `BACKLOG.md`: TASK-2/H28 HUD truth only; retain owner-hardware/live H28 gate as open;
- `STATUS.md`: actual test counts and canonical URLs `/`, `/v2/`, `/v2/?demo=1`.

Run `python scripts/status_sync.py --check` and correct only affected truth lines.

- [ ] **Step 8: Run backend parity and focused batch gates**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_route_parity_guard.py tests/test_route_auth_matrix.py tests/test_openapi_parity_guard.py tests/test_openapi_ts_typegen_gate.py tests/test_hud_v2_parity.py -q
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_local_model_inventory.py tests/test_local_model_status.py tests/test_local_models_api.py tests/test_dashboard.py tests/test_pytest_data_isolation.py tests/test_h15_1_browser_agent.py tests/test_desktop_operator_h15_3.py tests/test_h28_desktop_routes.py tests/test_h28_operator_reality.py -q
```

Expected: every parity and focused test passes, with zero ungoverned actions.

- [ ] **Step 9: Run full verification**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/ -n auto --dist loadfile --timeout=90 -q --tb=short
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe scripts/code_health.py
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe scripts/status_sync.py --check
git diff --check
```

Expected: full Python suite passes; advisory health has no new finding in touched files; status sync and whitespace check exit 0. Any environment-only failure must be reproduced on clean `origin/main` before classification.

- [ ] **Step 10: Run manual local smoke**

Start `serve.py` in the isolated worktree and verify:

- `/` and `/v2/` are live regardless of stale `hud.demo` storage;
- `/v2/?demo=1` visibly shows the demo banner and demo-only constellation;
- enabling/exiting demo changes only the URL query;
- zero resident models render no loaded badge or invented local node;
- Console → Build → Operator performs browser check/preview and desktop preview without auto-running;
- a mutated desktop plan cannot submit until re-previewed.

Record the observed routes/status in the PR body; do not claim owner-hardware execution proof unless it was actually performed.

- [ ] **Step 11: Review, commit, and prepare branch-wide review**

Commit the boundary/docs/generated artifacts:

```powershell
git add mobile/src/screens/approvalPolicy.ts mobile/src/screens/ApprovalsScreen.tsx mobile/src/screens/__tests__/approvalsDesktopBoundary.test.ts mobile/PARITY.md docs/design/HUD_V2_REMAINING.md BACKLOG.md STATUS.md tests/test_openapi_ts_typegen_gate.py frontend/src/api/schema.gen.ts tests/_snapshots/openapi_surface.json
git add -A agents/web/v2
git commit -m "docs: close Operator parity and publish HUD bundle"
```

Then run a whole-branch spec review against `origin/main`, remediate every material finding with tests, rerun the exact affected gates, and create a final review-fix commit when needed.

---

## Batch Completion Gate

- [ ] Every task has an observed red test, green focused test, task-level review, and commit.
- [ ] No placeholder or suppression was introduced:

```powershell
rg -n "TODO|FIXME|NotImplemented|placeholder|eslint-disable|type: ignore|pytest\.skip|test\.skip" agents/core/llm/local_model_inventory.py agents/core/routers/browser.py agents/core/routers/dashboard.py agents/core/desktop_operator.py agents/core/routers/multimodal.py frontend/src/demo-mode.ts frontend/src/task-state.ts frontend/src/operator-contract.ts frontend/src/operator-panel.tsx mobile/src/screens/approvalPolicy.ts
```

- [ ] `git diff origin/main...HEAD --check` is clean and generated files match sources.
- [ ] Independent whole-branch code review reports no unresolved critical/high issue.
- [ ] Final verification is rerun after the last review fix, not before it.
- [ ] Push `codex/hud-honesty-operator-surface` and open one draft PR into `main` with exact commands/results, explicit owner-hardware limitation, rollback notes, and no auto-merge until checks are green.
