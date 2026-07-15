# HUD Honesty and H28 Operator Surface Design

**Date:** 2026-07-14
**Scope approved by owner:** make demo/model/Neural Mesh state truthful and close the missing H28
Operator HUD surface without weakening any existing governance rail.

## Outcome

The normal HUD must make only claims supported by current backend evidence. A user opening the
canonical live address must never see demo state because of an old browser preference, an installed
model must not be labelled loaded unless the local runtime reports it resident, and historical queue
rows must not look like work happening now. H28 browser/desktop governance must also be usable from
the V2 Console through an explicit preview-first Operator panel.

This is one product-truth batch with four independently testable units:

1. URL-owned demo mode;
2. configured/available/resident local-model truth;
3. current-work semantics in the Neural Mesh plus serial-test data isolation;
4. a preview-first governed Operator panel over the already-shipped H28 endpoints, with matching
   mobile approval boundaries.

## Baseline evidence

The design is grounded in the live server and the existing parity/test contracts:

- `/status` reported `model_state=no_model`, `model_loaded=false`, and `loaded_model=null` while
  `configured_model=minimax/minimax-m2.7`.
- LM Studio's native `/api/v0/models` reported every installed model `not-loaded`, while
  `/api/models/local` marked the configured Minimax row `active:true` and V2 rendered that as
  `loaded`.
- `/tasks` returned 30 recent rows with zero `running` tasks: 21 `done` and 9 `blocked`. The HUD
  normalized every row to owner `jarvis` because it ignored the queue's real `agent` field.
- Several visible rows are produced by serial HTTP tests (`endpoint_test not responding`,
  `Delete prod db`). `tests/conftest.py` isolates persistent state under xdist, but a serial run
  currently uses the repository's live `memory_logs` root.
- The H28 browser and desktop endpoints are present and parity-classified, but
  `frontend/src/` has no caller for `/api/browser/*` or `/api/desktop/*`.
- Clean isolated-worktree baseline: 58 focused Python tests and 16 focused frontend tests pass.
  Reproduction commands, run from the worktree root unless noted otherwise:

  ```powershell
  C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest `
    tests/test_local_models_api.py tests/test_dashboard.py `
    tests/test_h28_desktop_routes.py tests/test_h28_operator_reality.py `
    tests/test_hud_v2_parity.py -q
  # 58 passed

  Set-Location frontend
  npm.cmd test -- src/test/mesh.test.tsx src/test/mesh-panel.test.tsx `
    src/test/gap-panels.test.tsx
  # 3 files, 16 tests passed
  ```

  The absolute Python path records the environment actually used for the baseline.

## Goals

- Make `http://127.0.0.1:8080/` an unambiguous live/default HUD address.
- Make `http://127.0.0.1:8080/v2/?demo=1` the shareable, visibly versioned demo address.
- Preserve demo convenience while making the URL the sole durable source of demo truth.
- Distinguish model availability, configured routing choice, and actual residency in both API data
  and V2 labels/actions.
- Make the Neural Mesh a current-activity view: no invented models, no historical-task fan, no
  `ready`-means-running animation, and no fake utilization percentage.
- Prevent serial tests from writing runtime artifacts into the owner's live Jarvis data root.
- Let an operator check browser policy, preview browser/desktop plans, and submit desktop plans to
  the existing governed route with distinct proposed/queued/blocked/failed/partial/executed
  outcomes.
- Prevent the native mobile Approvals UI from displaying a server-desktop proposal payload or
  offering/invoking Approve for that task kind.
- Keep browser/mobile parity and the HUD depth ledger accurate.

## Non-goals

- Do not delete, rewrite, or silently reclassify existing autonomy history. Any purge requires a
  separate evidence-backed owner decision.
- Do not add a browser execution endpoint or bypass agent/ToolRPC governance.
- Do not display raw screenshots, full accessibility trees, typed secrets, or base64 image payloads
  in the Operator panel.
- Do not enable desktop actuation, browser automation, cloud routing, or a local model by default.
- Do not change H28 kernel, approval, injection, isolation, or kill-switch semantics.
- Do not add a new route; the panel consumes the existing user-guarded H28 surface.
- Do not add a native-mobile desktop-actuation affordance. This batch does not add client-attested
  provenance, filter the task payload at the API boundary, or claim that an authenticated custom
  client cannot call the existing user-guarded APIs.

## 1. URL-owned demo mode

### Contract

Demo is true only when the current HUD URL has at least one exact query parameter `demo=1`
(`URLSearchParams.getAll('demo').includes('1')`). The HUD must not read or write
`localStorage['hud.demo']`; values such as `demo=10`, `demo=0`, and `notdemo=1` remain live.

- Enabling demo updates the visible URL with `history.replaceState`, preserving unrelated query
  parameters and the hash. It removes duplicate/conflicting `demo` entries before adding one
  canonical `demo=1` value.
- Exiting demo removes only `demo`, also through `replaceState`.
- Refreshing a demo URL stays in demo; refreshing a URL without `demo=1` is always live.
- A stale `hud.demo=1` value is ignored. It may be left untouched for backwards compatibility; it
  cannot influence rendering.
- Browser navigation to another history entry (`popstate`) re-reads the URL and updates mode without
  consulting storage. The HUD's own enable/exit controls use `replaceState`, so those controls do not
  create entries for Back/Forward to revisit.
- The direct share link is `/v2/?demo=1`. `/?demo=1` remains accepted because `/` serves V2, but
  documentation and UI copy use the versioned link.
- The existing visible demo banner remains mandatory. Demo-derived data never carries a LIVE chip.

### Boundary

Add a small pure `frontend/src/demo-mode.ts` helper for URL parsing/updating and a `useDemoMode`
hook (or equivalently small App wrapper) that owns state. Components continue to receive `demo` and
an enable/disable callback; they do not manipulate browser storage themselves.

## 2. Local-model truth contract

### Definitions

- **available**: the provider catalog says the model can be selected or loaded; `null` means the
  catalog could not establish that fact.
- **configured**: Jarvis' router default points at the model. This is a preference, not runtime
  residency.
- **resident**: the provider's resident-model endpoint reports the model currently in memory.
- **unknown**: the provider catalog is reachable but its resident-state endpoint is unavailable.

### API shape

`GET /api/models/local` remains admin-guarded and backwards-compatible. Existing `active` fields
remain deprecated compatibility aliases for `configured`; all in-repository V2 consumers must stop
reading them in this batch. They may be removed only in a separately documented API-version change
after a source-contract test proves no in-repository consumer remains.

```json
{
  "active": "minimax/minimax-m2.7",
  "configured_model": "minimax/minimax-m2.7",
  "resident_models": [],
  "backend": "lm-studio",
  "providers": [
    {
      "name": "lm-studio",
      "online": true,
      "catalog_state": "known",
      "residency_state": "known"
    }
  ],
  "models": [
    {
      "id": "minimax/minimax-m2.7",
      "provider": "lm-studio",
      "available": true,
      "configured": true,
      "active": true,
      "resident": false,
      "controls": {
        "can_configure": true,
        "can_load": true,
        "can_unload": false
      }
    }
  ]
}
```

Resident truth comes from LM Studio `/api/v0/models` (`state=loaded`) and Ollama `/api/ps`, while
the installed/available catalog remains LM Studio `/v1/models` and Ollama `/api/tags`. If a resident
probe is unsupported or fails while the catalog remains online, `residency_state` is `unknown` and
each affected row has `resident:null`; the HUD says `residency unknown` and never guesses loaded.

Provider `online` is true when either native probe succeeds. `catalog_state` and `residency_state`
are independently `known`, `unknown`, or `offline`: success makes that dimension known; failure while
the other probe proves the provider online makes it unknown; failure of both makes both offline.
Rows use `available:null` whenever catalog state is not known and `resident:null` whenever residency
state is not known.

Available, resident, and configured ids are merged as a union per provider. Multiple resident models
are allowed; a resident model temporarily absent from a successfully fetched catalog remains present
with `available:false`. A configured model absent from a known provider catalog remains visible as a
synthetic row with `available:false`; when its provider/catalog cannot be established it instead uses
`available:null`. Its residency is independently false or null by the probe rules, and synthetic
rows expose no lifecycle control unless the normal capability predicates are proven. Failure of one
provider's resident probe cannot erase the other provider's results. `resident_models` is a stable
list of `{provider,id}` pairs sorted by provider then id so identical ids from different providers
remain distinct.

The inventory key is the pair `(provider, exact provider id)`. Ids are trimmed at their outer
whitespace boundary but are not lower-cased, basename-folded, or compared across providers. When the
router supplies a provider, configuration matches that exact pair. Without a provider, an exact id
match is configured only when it resolves to one provider; an ambiguous or absent id becomes the
synthetic `provider:"unknown"` row rather than falsely configuring multiple rows.

The inventory exposes lifecycle capability explicitly on every model row:

- LM Studio rows may set `can_load`/`can_unload` only when the controller is enabled and residency is
  known; availability and residency select which one is enabled.
- Ollama rows always set `can_load:false` and `can_unload:false` because the existing lifecycle
  endpoints are LM Studio-only. They may still set `can_configure:true` and use the separate router
  switch action.
- Unknown residency disables both lifecycle actions regardless of provider. No frontend code infers
  provider capabilities from a name or sends an Ollama id to `/api/llm/load|unload`.

### Shared `/status` invariant

One shared local-inventory helper owns catalog and residency probes plus the short cache. Both
`GET /api/models/local` and `/status` consume that helper; `_llm_ready()` becomes a compatibility
projection rather than a second LM Studio-only truth source. `/status` adds
`residency_state:known|unknown|offline` and the same ordered `resident_models` pairs while retaining
legacy `model_state`, `model_loaded`, and `loaded_model` fields.

The aggregate `residency_state` is `offline` when no provider is online, `unknown` when any online
provider has an unknown resident probe, and `known` otherwise. It can therefore be `unknown` while
`model_state` is `ready` if one provider proves a resident and another provider's probe is unknown;
the provider rows preserve that distinction.

`model_state` is derived as follows:

1. `ready` when at least one provider reports at least one resident model;
2. `unknown` when no residency is proven and at least one online provider's residency probe is
   unknown;
3. `no_model` when at least one provider is online, every online provider has known residency, and
   none reports a resident model;
4. `offline` when no provider is online.

For compatibility, `loaded_model` remains a string id: it is the configured model id when its
`{provider,id}` pair is resident; otherwise it is the `id` from the first pair in the stable
`resident_models` order; otherwise it is `null`.
`model_loaded` is true exactly when `resident_models` is non-empty. The V2 loader retains all pairs,
and the Neural Mesh may therefore draw more than one genuinely resident local model. Tests assert
that `/status` and `/api/models/local` agree for zero, one, multiple, Ollama-only, and unknown
residency cases.

### HUD behavior

`LMStudioPanel` and the live Admin data adapter render residency as the primary state:

1. `resident:true` — green `loaded` label;
2. `resident:null` — amber `residency unknown` label;
3. `resident:false && available:true` — muted `ready` label;
4. `resident:false && available:null` — amber `availability unknown` label;
5. otherwise — muted `unavailable` label.

`configured` is an independent neutral/accent badge, so a configured model can simultaneously say
`residency unknown`. Buttons come only from the row's `controls` object; unknown residency and Ollama
never receive LM Studio lifecycle controls.

Loading/unloading refreshes the catalog. Switching the configured model remains a separate router
choice and must not be described as loading it.

## 3. Neural Mesh current-work semantics

### Models

- In demo mode only, retain the cinematic Gemma/Claude/Gemini constellation.
- In live mode, `deriveMeshModels` returns every resident local model in the current `/status`
  snapshot and only cloud lanes backed by a successful `/api/trust/status` response from the current
  loader cycle.
- `claude_available === true` adds one `claude` lane. Otherwise,
  `cloud_available === true` adds one generic `cloud` lane. If both are true, Claude wins and the
  generic lane is not duplicated. The loader sets `sources.trust=true` only on a successful current
  response and clears prior trust evidence at the start of each cycle; missing, failed, stale, or
  merely generic server-up signals add no cloud node.
- Each local node is keyed by `provider:id` and sorted in the `/status` order; there is no single-model
  selection or fallback. Tests cover two simultaneous residents and prove both labels come from the
  response rather than the demo constants.
- An empty `resident_models` list produces zero local nodes for `no_model`, offline, or unknown; the
  aggregate residency flag never hides a model proven resident by another provider. Independently
  qualified cloud lanes may still render under the exact trust rules above; local state never creates
  or suppresses a cloud lane.
- `build()` must support an empty model list without falling back to demo data.
- Model tooltips describe `local model · loaded` or `cloud lane`; the current hard-coded `cost * 100`
  “load” claim is removed. Visual node size remains decorative and is not labelled utilization.

### Agents

- Only `busy` and `active` mean currently executing. `ready` means available and remains visually
  static.
- Live random agent firing/cascades are removed. Decorative core rotation may remain, but task/model
  flow particles occur only for actual `busy`/`active` agents or running tasks.
- Demo mode may retain cinematic choreography because the DEMO banner and URL provenance are visible.
- Cinema mode receives the same `llm`, `trust`, `demo`, tasks, and live-source inputs as the cockpit;
  it cannot silently re-enter a demo constellation.

### Tasks

- Keep unqualified `/tasks` backwards-compatible for one migration window (`view:'legacy'`), but add
  the explicit enum query `view=running|history`. `view=running` returns only
  `state/status == running` with no history fallback; `view=history` returns the recent bounded
  non-running rows and never includes a running row. Any other query value returns FastAPI's bounded
  HTTP 422 validation response instead of silently selecting a view. The response also carries
  `view`, `source:'autonomy_queue'`, `history_included`, and an ISO-8601 UTC `as_of` so consumers
  know what they saw. `history_included` is true only for explicit history or the legacy no-running
  fallback.
- Explicit views derive effective state from the first non-empty value of `state`, then `status`,
  normalized with trim + lowercase; if both disagree, `state` wins. Only exact `running` is live.
  The legacy no-query path deliberately preserves today's algorithm for compatibility: select rows
  where raw `status == "running"` OR raw `state == "running"`; if none match, return all recent 30
  rows. Its existing case sensitivity and fallback remain until that migration window is removed.
- Fix normalization precedence to `owner || agent_id || agent || 'jarvis'`.
- The V2 live loader requests `/tasks?view=running` and defensively re-filters for running before
  supplying tasks to either mesh implementation. This batch proves only that proposed, blocked,
  completed, and failed rows are excluded from Mesh; it does not claim that Decision Inbox or Today
  provides exhaustive history, and it does not change those surfaces. The frontend filter uses the
  same effective-state precedence and normalization as the explicit backend views.
- `NeuralMesh` also filters non-running input defensively so a fixture or future caller cannot make
  terminal history look live.
- Draw at most five running task dots per owner. When focused, show at most three short labels plus
  one `+N more` summary; never render twelve labels into one fixed arc.
- This bounded-label cleanup is in scope because the reported Neural Mesh failure includes the
  overlapping task text shown in the supplied screenshot; it is not a general visual redesign.
- The legend says `N running task(s)` and reports `demo`, `live telemetry`, or `no live activity`
  from explicit props. It never unconditionally says `live`.

### Test-data isolation

`tests/conftest.py` unconditionally creates a per-process temporary `JARVIS_HOME` and
`JARVIS_KEY_DIR` for serial as well as xdist runs before any Jarvis store module is imported,
overriding ambient operator values inside the pytest process. Tests may still override those paths
inside a test. No test run may default to repository `memory_logs` or the owner's configured live
root.

This prevents new fixture rows from reaching a real autonomy database. Existing live rows are left
intact and simply stop appearing as active mesh work.

## 4. H28 Operator panel

### Placement and boundary

Create `frontend/src/operator-panel.tsx` and register `OperatorPanel` in Console → Build. Keeping the
panel outside the already-large `gap.tsx` limits collision risk; `gap.tsx` receives only the import
and section registration.

The panel uses existing user-token API helpers only. It never requests or stores an admin token.

### Browser preview

- Inputs: URL, explicit domain allowlist, and a small structured plan builder limited to
  `navigate(url)`, `extract(selector)`, `click(selector)`, `type(selector,text)`, and
  `submit(selector)`. Screenshot, download, upload, and script execution are absent.
- The panel caps the allowlist and plan at 20 entries each, below the server maximum, and never
  performs a check or preview automatically on mount. URL is capped at 2,000 characters, each domain
  at 253, each selector at 512, and `type` text at 4,000. The backend validates allowed action names,
  exact per-action keys, string types, and those same caps so malformed dictionary entries return a
  bounded 422 rather than reaching `GovernedBrowser.preview()`.
- `check policy` calls `POST /api/browser/check` and shows allowed/blocked plus the bounded reason.
- `preview plan` calls `POST /api/browser/plan/preview` and renders each step as run/approval/block.
- There is no browser Run button because no browser execution route is part of this scope.
- Empty allowlists fail closed and the UI explains that behavior.
- Because the endpoint evaluates the allowlist supplied in that same request, the result is labelled
  `policy dry run`, never browser readiness or current server configuration.
- Browser type text is kept only in component memory for the request lifetime. The preview list says
  `type · N characters` and never echoes the text; the backend preview response remains limited to
  index, action, kind, decision, and a reason capped at 240 characters.

### Desktop preview and governed submission

The structured builder exposes only this safe subset of the route's validated actions:

- read-only: `read(query)`, `locate(query)`;
- mutating: `click(name)`, `type(name,text)`, `launch(app)`.

Raw screenshot, full accessibility observation, and unrestricted JSON actions are deliberately
absent. The builder enforces the required field shape before network submission and never persists
input text. The UI caps a plan at 20 steps and submitted type text at 4,000 characters; stricter
server limits remain authoritative.

`POST /api/desktop/preview` must use `validate_desktop_run_args()` before classifying a plan. Today it
labels unsupported actions such as `wait` or `teleport` runnable/approvable even though `/run` rejects
them. Preview and run must accept the same step/argument schema; an invalid preview returns the same
bounded `{ok:false, reason}` family and cannot unlock submission. The shared validator also rejects
an empty plan with `empty_steps`, closing the current `all([]) == true` false-success path.

Flow:

1. Build a bounded, non-empty step list.
2. The client canonicalizes it with the same rules as the server validator: ordered steps, lower-case
   action names, trimmed non-text arguments, unmodified `type.text`, and fixed per-action key order.
   It stores a deep-cloned canonical object plus a stable JSON signature in component memory only.
3. `preview` sends that snapshot to `POST /api/desktop/preview` and renders every step as
   proposed/read-only or proposed/approval-required.
4. Any edit rebuilds the current signature; a mismatch clears the preview and disables submission.
5. `submit governed plan` sends the stored preview snapshot, not the mutable form state, to
   `POST /api/desktop/run`. The backend validates and normalizes it again before any decision.
6. Mutating steps continue through ToolRPC/Decision Inbox; the panel cannot send caller approval
   fields and cannot approve its own task.

### Outcome language

- **proposed**: returned by preview only; nothing executed.
- **queued**: a durable approval task exists; show task id and point to Decision Inbox.
- **blocked**: disabled host/kernel, injection, policy denial, approval requirement without a queued
  task, or another fail-closed governance reason.
- **failed**: a permitted attempt failed or returned an invalid/unverified result.
- **partial**: at least one step has `status=ran`, but any part of the exact executed predicate fails,
  including `ok:false`, a count mismatch, a missing step, or another step status.
- **executed**: the submitted plan is non-empty, returned step count equals submitted step count,
  `ok:true`, and every returned step has `status=ran`.

Never derive success from HTTP 200 alone. Never label a queued or unverified response executed.
The plan-level reducer is deterministic: preview is `proposed`; a top-level
`approval_required + task_id` with no ran step is `queued`; the exact non-empty/count-matched all-ran
case is `executed`; any other result containing at least one ran step is `partial`; with no ran step,
a governance refusal is `blocked` and every other unsuccessful response is `failed`. Each returned
step is shown separately with action and status. A partial result carries `Do not retry the whole
plan: some steps already ran` because replay could duplicate effects.

Result rendering is allowlisted and capped: action 64 characters, reason 240, task id 128, source 64,
read result text 1,000, numeric element count, truncation flag, and at most 10 matched elements with
role/name capped at 120 characters each. It omits screenshot/base64 data, full accessibility arrays,
submitted browser/desktop `type` text, paths, and raw JSON dumps. Type rows display only a character
count.

### Mobile approval boundary

The existing native Approvals screen sees generic autonomy tasks and currently renders every task
payload with an Approve button. A `toolrpc.desktop_run` task contains desktop targets and typed text,
so this contradicts the parity rule that a phone must not control the server's desktop.

For `task.kind == "toolrpc.desktop_run"`, the mobile card must:

- hide the payload entirely;
- show `Approval unavailable in mobile app · continue in Owner HUD`;
- omit/disable **Approve**;
- retain Reject and Defer so the owner can stop or postpone a proposal without causing execution.

This is intentionally a native-Approvals-UI boundary, not a server security boundary. The generic
task/API payload and user-token routes remain unchanged, the responsive browser HUD may still be
opened on a phone, and no client provenance is asserted. Desktop execution still requires ToolRPC,
human approval, fresh validation, and the Action Kernel.

## Error handling and security

- All new frontend calls surface a visible error/outcome instead of swallowing `.catch()` results.
- URL parsing fails live/off; malformed `demo` values do not enable demo.
- Model resident-probe failures degrade to unknown; availability never upgrades residency.
- Provider errors remain bounded and do not expose exception strings beyond the existing admin
  provider-status contract.
- Operator edits cannot reuse an old preview. Submission is disabled while a request is in flight.
- Desktop preview and run share the exact validator; a preview cannot bless an unexecutable action.
- Desktop default-off and isolated-host double opt-in remain unchanged.
- Browser allowlist/SSRF decisions remain server authoritative.
- Kernel, ToolRPC, approval queue, accessibility-first observation, injection classification,
  cleanup, and zero-ungoverned-action proofs remain unchanged and are regression-tested.

## Files expected to change

- `frontend/src/demo-mode.ts` — URL-only demo parsing/updating.
- `frontend/src/app.tsx` — use URL-owned demo state and pass truthful mesh/cinema inputs.
- `frontend/src/shell.tsx` — cinema/live agent semantics.
- `frontend/src/mesh.tsx` — model/task/activity truth and bounded labels.
- `frontend/src/api/live.ts` and `frontend/src/api/loaders.ts` — explicit model fields and running
  task selection.
- `frontend/src/gap.tsx` — LM Studio labels plus Operator registration.
- `frontend/src/operator-panel.tsx` — safe H28 control surface.
- `agents/core/llm/local_model_inventory.py` — shared cached provider catalog/residency truth.
- `agents/web.py`, `agents/core/routers/models_llm.py`, and `agents/core/routers/status.py` — expose the
  shared inventory and compatibility projections.
- `agents/core/routers/browser.py` — strict bounded browser-preview request models.
- `agents/core/routers/dashboard.py` — correct task owner normalization.
- `agents/core/desktop_operator.py` and `agents/core/routers/multimodal.py` — non-empty shared desktop
  validation plus preview/run parity.
- `tests/conftest.py` — serial and xdist runtime-data isolation.
- `mobile/src/screens/ApprovalsScreen.tsx` — desktop-task payload/approval boundary.
- Focused Python/frontend tests, generated `agents/web/v2/` bundle, HUD depth docs, mobile parity
  ledger, `BACKLOG.md`, and `STATUS.md` truth notes.

No route-surface reseed is expected because no route is added or removed. The new `/tasks` query and
response metadata intentionally change OpenAPI, so regenerate the TypeScript schema and reseed the
OpenAPI snapshot in the same PR; route/auth snapshots should remain unchanged.

This remains one batch-build draft PR, with independently reviewable commits for URL/demo truth,
model inventory/status truth, Mesh/tasks/test isolation, and Operator/mobile/docs. A failed unit can
therefore be reverted without discarding the rest of the batch.

## Verification strategy

TDD is required per unit:

1. Red tests prove localStorage can no longer enable demo and URL toggle/exit preserves unrelated URL
   state.
2. Red API/UI tests prove configured Minimax is not loaded, native resident state is reflected,
   configured-but-unknown keeps the configured badge while disabling lifecycle controls, offline
   configured rows remain visible, Ollama never gets LM Studio controls, both inventory endpoints
   agree, multiple residents all reach Mesh, and resident-probe failure renders unknown.
3. Red dashboard/mesh/loader tests prove `view=running` never falls back to history, no-model
   produces no model nodes, terminal tasks do not render, ownership uses `agent`, `ready` does not
   animate as running, labels remain bounded, and cinema receives live truth.
4. A red subprocess isolation test proves serial pytest resolves `data_root()` and
   `TaskQueue.DEFAULT_DB` beneath the temporary test home, and a full-app mutation cannot alter a
   sentinel operator database.
5. Red Operator tests prove bounded/redacted browser checks/previews, shared non-empty desktop
   preview/run validation, preview invalidation, canonical snapshot submission, exact desktop
   payloads, queued/blocked/failed/partial/executed reduction, per-step outcomes, retry warning, no
   caller approval fields, no unsafe screenshot/observe action, and no raw-result rendering.
6. Strengthen HUD parity so `/api/browser/*` and `/api/desktop/*` require a real `OperatorPanel`
   caller rather than merely matching the broad Build prefix.
7. A mobile source/Jest contract proves `toolrpc.desktop_run` hides payloads and cannot render or
   invoke Approve while Reject/Defer remain available.

Required final evidence:

- focused Python suites for local models, dashboard, H28 routes/reality, parity, and test isolation;
- focused frontend suites for demo, model panel, mesh/cinema, Operator, and Console registration;
- focused and full mobile Jest plus mobile TypeScript typecheck;
- full frontend Vitest, TypeScript typecheck, production build, and committed bundle diff;
- route/OpenAPI/HUD parity gates and generated-schema diff check;
- full Python suite, with any environment-only failure reproduced on clean `origin/main`;
- touched-file code-health checks;
- manual local smoke at `/`, `/v2/`, and `/v2/?demo=1`, including LM Studio with zero loaded models.

## Documentation and parity

- Mark the H28 Operator depth item complete in `docs/design/HUD_V2_REMAINING.md` only after the
  real panel and tests land.
- Update `mobile/PARITY.md` with separate browser policy-preview and server-desktop rows, both mobile
  `➖`; the latter records the payload-hidden/no-approve rule.
- Update TASK-2/H28 truth in `BACKLOG.md` within the feature PR; do not mark owner-hardware proof
  complete.
- Keep the canonical address documented as `/`, the explicit stable V2 alias as `/v2/`, and the
  shareable demo address as `/v2/?demo=1`.

## Rollback

The batch is additive or presentation-only except for corrected response fields, stricter preview
validation, removal of one native-mobile approval affordance, and test isolation. Rollback is a
normal per-unit commit revert:

- compatibility `active` fields keep older model clients working;
- no database migration or runtime-history mutation occurs;
- no flags are enabled;
- reverting the Operator unit restores the old permissive preview and native approval UI together;
  removing only `OperatorPanel` still leaves the existing H28 run governance rails untouched;
- URL demo mode reverts without changing stored user/runtime data.

## Acceptance criteria

The work is complete only when all of the following are true:

- A plain live URL cannot show demo data because of browser storage.
- Demo enable/exit is visible in the URL and `/v2/?demo=1` is reliably shareable.
- A configured-but-not-resident LM Studio model is labelled configured/ready, never loaded, and has
  a load action only when the LM Studio controller is enabled; a disabled controller exposes no
  lifecycle action. Configured + unknown remains visibly configured with both lifecycle actions
  disabled.
- An offline configured model remains visible, Ollama rows never call LM Studio lifecycle routes,
  and `/status` agrees with `/api/models/local` for zero, one, multiple, unknown, and Ollama-only
  residents.
- Cloud mesh nodes require a successful current trust response and exact qualifying booleans; failed,
  missing, stale, and generic server-up evidence cannot invent them.
- Live `no_model` renders no invented model constellation or fake load percentage.
- Zero running tasks means zero mesh task fan even when history contains done/blocked/test rows.
- Steve/Gecko running tasks attach to Steve/Gecko, not Jarvis.
- `ready` agents are available but not counted or animated as executing.
- Serial and parallel pytest runs cannot write to the live Jarvis data root by default.
- Console → Build contains a usable Operator panel for browser policy/plan preview and desktop
  preview/governed submission.
- Desktop preview rejects every action/argument shape that desktop run would reject.
- Empty desktop plans cannot execute successfully; exact non-empty all-ran/count-matched results are
  the only executed outcome, while mixed results are partial with per-step detail and a retry warning.
- The panel distinguishes proposed, queued, blocked, failed, partial, and executed without claiming
  success from an HTTP status or leaking typed text/raw desktop data.
- The native mobile Approvals UI hides `toolrpc.desktop_run` payloads and exposes no code path that
  renders or invokes Approve for them; Reject and Defer remain. No server/client-provenance guarantee
  is claimed by this UI-only rule.
- H28 reality tests still prove `ungoverned_actions == 0` and all relevant CI checks pass.
