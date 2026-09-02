# CLN-2 / CLN-3 — God-Object Decomposition Plan

> Generated: 2026-06-13 · Owner: Andrei · Status: **Superseded — landed in #293/#296** (v0.11.0; owner decision 2026-09-01) · Priority: P3
> Gate: Phase 0 is gate-safe (pure-additive) and shipped. The web.py/orchestrator split itself shipped
> as v0.11.0 (#293/#296) under route-parity guards, so the 2026-06-10 "after the manual-test pass"
> green-light is retired as superseded (2026-09-01); the phase text below is historical.
> Backlog rows: `BACKLOG.md` CLN-2 / CLN-3. Related: `docs/2026-06-08-future-developments-report.md` §4.
>
> Produced from a 4-agent parallel analysis (orchestrator decomposition · route inventory ·
> shared-kernel decoupling · verification harness), all measured against the live code, not grep.

---

## 0. The governing insight (read first)

**The test suite couples to module *namespaces*, not to behavior.** This single fact reframes both
refactors and constrains every step below.

- `orch.*` is referenced **531×** in `agents/web.py`.
- `web.orch` is **monkeypatched 112× across 16 test files** (`monkeypatch.setattr(web, "orch", …)` /
  `web.orch = mock`) and **read via `web.orch.*` 59× across 24 files**.
- Config flags (`ADMIN_TOKEN`, `USER_TOKEN`, `RATE_LIMIT_PER_MIN`, `TRUSTED_PROXY`) are monkeypatched
  **80× across 15 files**; singletons rebound directly (`web._payment_broker`, `web._wf_store_instance`,
  `web._rate_hits.clear()`).
- Four `Orchestrator.__new__(...)` "bare" tests set a *minimal* attribute set and call **one** method
  directly; five full-init tests monkeypatch *bound methods* (`o._call_agents_parallel = fake`).

**Therefore the task is NOT "split the files." It is "extract implementations behind a frozen public
surface."** The canonical names stay put; decoupling happens underneath them via late-binding accessors
and thin facades.

Three hard consequences (all independently confirmed):

1. **The BUG-5 `_active_session` ContextVar core is not extractable.** `session_id`/`_resolve_session`/
   `channel_handler`/`handle_input(_stream)`/`_recall_block`/`_maybe_checkpoint`/`_flush_checkpoint`/
   `_log_session`/`_async_create_cache`/`_update_cognition` must stay on `Orchestrator` — the four bare
   tests call them with only a few attributes set. **There is no `SessionManager`**; this is the
   legitimate residual core.
2. **`orch` stays owned by `web.py`** (it is tied to `lifespan`). Decoupling = a `get_orch()` accessor
   that does `from agents import web; return web.orch` *inside the function* (late binding → monkeypatch
   still observed). This mirrors the already-shipped `agents/core/cognition/api.py:_facade()`.
3. **Request-pipeline entrypoints stay bound methods on the facade** (`handle_input`, `handle_input_stream`,
   `_call_agents_parallel`, `_synthesize`, `_route_candidates`, `_gather_plugin_data`, `_record_interactions`,
   `process`, `promote_bench_agent`) so the bound-method monkeypatch contract holds.

---

## 1. Current surface (authoritative — from the live app)

- **294 routes total**: **255 still inline in `web.py`**, **39 already extracted** (8 routers in
  `core/routers/` + `cognition/api.py`). CLN-3's migration surface is the 255.
- **`orchestrator.py`: 57 methods** (17 public, 39 private), **2,202 LOC**.
- **`web.py`: 5,037 LOC**, 255 inline routes, ~36 module-level helpers, ~10 lazy singletons.
- **Coverage gaps (why blind moves are dangerous):**
  - **83 routes are hard-untested** (no test hits them) — **72 inline**, 11 in already-extracted routers
    (proof the gap bites: extraction created silent blind spots).
  - The scheduler/autonomy/watcher methods CLN-2 relocates are **almost entirely untested at unit level**
    — they only execute inside `lifespan`.
- The existing `tests/test_hud_v2_parity.py` is **text-grep only and blind to mounted routers** — it
  cannot serve as the parity guard.

---

## 2. Phase 0 — Safety net (ZERO behavior risk; safe *before* the gate) — ✅ LANDED 2026-06-13

Pure-additive: new tests + a convention. Nothing in the live surface changes, so it cannot regress the
manual-test gate, and it de-risks everything after. **This is the only phase recommended pre-gate.**

**Status:** shipped. `tests/test_route_parity_guard.py` (snapshot of all **294** routes, in
`tests/_snapshots/route_surface.json`), `tests/test_openapi_parity_guard.py` (294 operations), and
`tests/test_lifespan_smoke.py` (verifies channels start, **20** scheduler jobs register via
`orch.heartbeat_scheduler.scheduler`, `/api/status`→200, clean teardown) are green. A characterization suite (`tests/test_route_guard_contracts.py`, **14 tests**) locks the admin-guard +
validation + safe-behavior contracts of the riskiest previously-untested routes: LLM
(`llm/load`, `llm/auth-profiles`), autonomy (`autonomy/mode`), payments (`payments/{id}/reject`), the
**distributed-mesh / dispatch group** (`nodes` list/register/dispatch/delete, `satellites`
list/register, `subagents/spawn`, `toolrpc/call`, `sync push|pull`, `context/compress`) — the Tier-4
"smoke tests before extraction" the plan prescribes — plus oauth service-routing (`auth-url`/`refresh`
→ 404) and the admin read surface (`audit`/`widgets`/`agents/stats`). The "new routes → per-domain
router" convention is documented in `AGENTS.md` + `docs/ARCHITECTURE.md`. Full suite after Phase 0:
**2,230 passed, 2 skipped**. The remaining ~60 hard-untested routes (lower-risk reads: cognition GETs,
media/vlm/desktop, integrations) are backfilled just-in-time per extracted domain during Phase 3.

> Two spec assumptions were corrected against the live app while implementing: the scheduler is at
> `orch.heartbeat_scheduler.scheduler` (not `orch.scheduler`), and `/api/status` returns
> `{version, agents, status}` (not `{ok, agents, channels}`).

1. **Route-parity guard** — `tests/test_route_parity_guard.py`: snapshot `app.routes` (294 method+path),
   assert zero diff. Catches a router that fails to mount, a wrong `prefix=`, a dropped method, a renamed
   path param. (Test code in Appendix A.)
2. **OpenAPI surface guard** — freeze `app.openapi()["paths"]` + `operationId` (catches handler renames).
   Surface-only — necessary, not sufficient.
3. **Lifespan smoke test** — `with TestClient(web.app)`: assert the orchestrator builds, channels start,
   scheduler jobs register, `/api/status`→200, teardown nulls `orch`. **Highest-leverage CLN-2 guard** —
   the only thing exercising the scheduler/autonomy wiring. (Test code in Appendix A.)
4. **Backfill characterization tests** for the highest-risk hard-untested routes first (state-mutating:
   `llm/load|unload|server/start`, `nodes/dispatch`, `oauth/callback`, `sync/push|pull`,
   `heartbeat/*/start|stop`, `autonomy/mode`, `payments/{id}/reject`), written against current behavior.
   Remainder backfilled just-in-time per extracted domain. (Full 83 in Appendix B.)
5. **Convention:** *new feature routes go in `core/routers/<domain>.py`, never inline in `web.py`.* Caps
   the god-object's growth (it grew +400 LOC / +22 routes in the 5 days before this plan) at zero risk.

---

## 3. Phase 1 — Shared-kernel decoupling (low risk, Phase-0-guarded) — ✅ steps 1–3 LANDED 2026-06-13

**Status:** the shared kernel exists and the 8 extracted routers are fully decoupled from `web`.
`core/web_helpers.py` (pure: `nocache_json`, `mask_secret`; `web.py` re-exports them under
`_nocache_json`/`_mask_secret`) and `core/app_state.py` (`get_orch()`, late-binding to `web.orch` via a
`sys.modules` lookup so it stays a leaf — no static import edge, no cycle) shipped. The routers (a2a/browser/canvas/capture/onboarding/
pairing/webhooks/wyoming) replaced their 52 `web._nocache_json` + 7 `web.orch` + lazy
`from agents import web` with direct `core/` imports — **zero residual `web.*` refs**. Behavior-identical:
route-parity + lifespan guards green, full suite **2,230 passed / 2 skipped**. `orch` stays owned by
`web.py` (lifespan). `cognition/api.py` left as-is (canonical `_facade()`).

**Deferred to Phase 3 (by design):** relocating the remaining stateful helpers + the ~10 lazy singletons
(`_payment_broker`, `_data_spaces`, `_wf_store_instance`, `_mcp_rs`, `_dataset_store`, `_stt_engine`, …).
No extracted router uses them yet, and the plan already moves each singleton *with its domain* during the
Phase 3 route extraction — so relocating them now would be premature churn against the test sites that
rebind `web._payment_broker`/`web._wf_store_instance`. They move when their domain does.

Strict 3-layer topology so routers stop importing `web` (none of layers 0–3 imports `web` at module top;
the only `web` reference is *inside* `get_orch()`/guards, at request time):

```
Layer 0  core/web_helpers.py   pure: nocache_json, _sys_info, _mask_secret, NO_STORE_PATHS …  (no orch)
Layer 1  core/app_state.py     singletons + get_*() accessors; get_orch(): lazy `from agents import web`
Layer 2  core/routers/_deps.py lazy user_guard/admin_guard (routers import get_orch from app_state)
Layer 3  core/routers/*.py     import web_helpers/_deps at TOP; drop `from agents import web`
Layer 4  agents/web.py         owns orch/gateway (lifespan); thin re-export shims; include_router()
```

Migration order (each step independently test-green): pure helpers → singletons behind accessors →
`get_orch()` (convert the 39 already-extracted routes off `from agents import web`) → stateful helpers
(`_enrich_agents`, `_llm_ready`, `_build_mcp_server`, `_list_local_models`, `_kg`, `_structured_recall`,
rate-limiter helpers). `web.py` keeps re-export shims so every monkeypatched name still resolves.

**#1 risk — duplicated singleton.** Each singleton gets exactly one home (`app_state`); `web._x` *aliases
the same object* (not a copy), or the 2 test sites that rebind `web._payment_broker`/`web._wf_store_instance`
are repointed at `app_state`. Never leave two live globals. `get_orch()` must late-bind (read the attribute
each call) — never `from agents.web import orch` (freezes `None`). `lifespan` ordering and the
`_dashboard_lock`/`_rate_hits` object identity must be preserved.

---

## 4. Phase 2 — CLN-2 orchestrator decomposition (facade-preserving) — ✅ COMPLETE (steps 1–4) 2026-06-13/14

**Status (step 1 — `SchedulerService`):** shipped. `core/scheduler_service.py` owns the 5 `schedule_*`
registration methods + 4 job bodies (`run_log_quick/hourly/daily_scan`, `run_daily_digest`); `start_channels`
now calls `self._scheduler.schedule_all()`. Two job bodies deliberately stayed on the Orchestrator because
callers reach them there: `_run_learning_loop` (admin `POST /api/learning/propose`) and
`_run_worldview_kg_sync` (`test_worldview_kg_sync` calls it *unbound* on a `SimpleNamespace`, so it must read
`self.plugins`/`self.memory` directly). The lifespan smoke test asserts the exact 7 job IDs the service wires.

**Status (step 2 — `llm_control`):** shipped. The self-contained NL-detection block (`detect_llm_control`,
its regexes, `_extract_model`, `_is_plausible_model`) moved to `core/llm_control.py`; orchestrator re-exports
`detect_llm_control` (tests import it from `core.orchestrator`; the request lifecycle calls it). Per the
bare-init constraint, the *methods* `_run_llm_control`, `_control_master_enabled`, `_chat_control_enabled`,
`_runtime_state_block` stayed on the facade (`test_llm_control_intent` calls them on a `__new__` orch with
only `lmstudio`/`llm_router`/`_runtime_settings` set). `_env_flag`/`_as_bool` (general helpers, interleaved in
the block) also stayed.

**Status (step 3 — `plugin_gatherer`):** shipped. The plugin-data assembly moved to
`core/plugin_gatherer.py` as module-level free functions (`gather_plugin_data(orch, …)`,
`extract_location`, `format_plugin_data`, `any_agent_can(orch, …)`, `first_target_agent(orch, …)`); the
orchestrator keeps all five as **thin one-line wrappers/delegators** so the public surface is byte-compatible.
`_gather_plugin_data` stays a bound entrypoint (`test_concurrent_session_isolation` replaces it as a bound
method); `_any_agent_can`/`_first_target_agent` stay callable (`test_routing` calls them on a full-init orch);
`_format_plugin_data` stays a wrapper (called via `self.` at two sites). `plugin_gatherer` imports only leaf
modules (`.log`, `.errors`) and takes `orch` as a parameter → no import cycle. (Also removed 3 now-unused
imports orphaned by steps 1/3.)

**Status (step 4 — `autonomy_coordinator`):** shipped. `_wire_autonomy`, `_on_autonomy_callback`,
`_build_autonomy_executor`, `_autonomy_loop` moved to `core/autonomy_coordinator.py` (`wire()`,
`_on_callback()`, `build_executor()`, `loop()`) — all four moved outright (no test calls them directly).
`build_executor()` still sets the 6 broker attributes on the orchestrator via the back-ref
(`writeback`/`social`/`call_broker`/`node_mesh`/`tool_rpc`/`subagents` — all read in web.py) and still wires
`autonomy.policy.calibration_hook`. The 6 plain autonomy attributes stay plain (test_shutdown_cleanup assigns
`autonomy_queue`). `start_channels` task-creation/ordering byte-identical (`asyncio.create_task(self._autonomy.loop())`).
Removed 3 orphaned imports (`TaskExecutor`, `build_decision_card`, `is_night_window`). No import cycle.

orchestrator.py: **2,202 → 1,619 LOC (−583 across steps 1–4)** — Phase 2 complete. Behavior-identical:
route-parity + lifespan guards green, full suite **2,234 passed / 2 skipped** throughout. The residual
orchestrator is the legitimate request-lifecycle core (handle_input/_stream, the BUG-5 session ContextVar,
agent runtime, checkpoint/recall) that the bare-init tests pin to the facade. Next: Phase 3 route extraction.


Four safe manager extractions, ascending risk. Each is a *free-function-body + thin-wrapper* move so bare
tests keep working (the wrapper reads only the orch attributes the bare test sets).

| Order | Manager (`agents/core/…`) | Methods moved | ~LOC | Risk |
|---|---|---|---|---|
| 1 | `scheduler_service.py` | `_schedule_daily_digests/_budget_reset/_learning_loop/_log_scans/_worldview_kg_sync`, `_run_learning_loop/_log_quick|hourly|daily_scan/_daily_digest/_worldview_kg_sync` | ~250 | lowest |
| 2 | `llm_control.py` | `detect_llm_control`+regexes, `_control_master_enabled/_chat_control_enabled/_control_cognition`, `_runtime_state_block`; `_run_llm_control` body→free fn (keep wrapper) | ~220 | low |
| 3 | `plugin_gatherer.py` | `_gather_plugin_data` body, `_extract_location`, `_format_plugin_data`, `_any_agent_can`, `_first_target_agent` | ~120 | low-med |
| 4 | `autonomy_coordinator.py` | `_wire_autonomy`, `_on_autonomy_callback`, `_build_autonomy_executor`, `_autonomy_loop` | ~300 | med |

**Stays on the facade (do NOT move):** the session/ContextVar core (§0.1); the request entrypoints (§0.3);
`start_channels`/`stop_channels`/`aclose` (task ordering + defensive shutdown are byte-sensitive);
`load_agents`; `get_status`/`get_setting`/`load_runtime_settings`. Keep heavily-read attributes
(`memory`, `agents`, `plugins`, `learning`, `bench`, `autonomy*`, `observer`, `llm_router`, `lmstudio`, …)
as **plain attributes** (not properties) — `test_shutdown_cleanup` *assigns* `orch.autonomy_queue`/`mcp`/
`llm_router`, so a read-only property would break it. Managers hold a back-ref (`Mgr(orchestrator)`); no
top-level `from .orchestrator import Orchestrator` (use `TYPE_CHECKING`).

Result: ~2,200 → ~1,300 LOC, residual = the legitimate request-lifecycle core. `AgentRuntime` is an
optional, wrap-only 5th step.

**Bare-test contract (the binding constraint):**

| Test (construction) | Pins on the facade |
|---|---|
| `test_perf_hotpath` (`__new__`) | `_maybe_checkpoint`/`_flush_checkpoint` read `_runtime_settings`/`_turns_since_checkpoint`/`checkpoints` |
| `test_cross_channel_sessions` (`__new__`) | `channel_handler`/`session_id`/`_resolve_session` + module `_active_session` |
| `test_memory_embeddings` (`__new__`) | `_recall_block` reads `_runtime_settings`/`memory` |
| `test_llm_control_intent` (`__new__`) | `_run_llm_control` reads `lmstudio`/`llm_router`; `detect_llm_control` importable from `orchestrator` |
| `test_concurrent_session_isolation` (full) | `handle_input(_stream)` + ContextVar; monkeypatches `_call_agents_parallel`/`_gather_plugin_data`/`_synthesize` as bound methods |
| `test_orchestrator_process_record` (full) | `process`/`_record_interactions`/`_call_agents_parallel` bound |
| `test_routing` (full) | `_route_candidates`/`_any_agent_can`/`_first_target_agent` callable |
| `test_bench_activation` (full) | `promote_bench_agent` callable |
| `test_shutdown_cleanup` (full) | `aclose` defensive; `mcp`/`autonomy_queue`/`llm_router` **assignable** |

---

## 5. Phase 3 — CLN-3 route extraction (incremental, one domain per PR) — 🟡 IN PROGRESS 2026-06-14

**Status:** 18 domains extracted into per-domain routers under `core/routers/` (each its own commit,
route-parity + full suite green throughout): rooms, notes, actions, arena, review, quality, security, skills,
data_spaces, secrets, mesh, autonomy, models_llm, oauth, memory_kg, **admin**, **analytics**, **integrations**.
All use the Phase-1 shared kernel — zero static `from agents import web`. **web.py: 5,037 → 2,388 LOC (−53%)** so far.

**CodeQL cleanup (post-merge, PR #196):** dropped the last cross-cutting `put_category` web-global — the
models_llm router now imports it directly from its leaf (`core.settings_db`) and the local-models test patches
it in the router's namespace, so web.py no longer carries the import purely as a monkeypatch target (cleared the
"unused import" alert). The admin `llm/test` backend probe no longer returns `str(e)` per item; it logs the full
detail server-side and exposes a static reason (CWE-209).

**The 5 blocking alerts (CodeQL, PR #196) — identified by running CodeQL locally.** The agent env can't
enumerate code-scanning alerts via MCP, so the exact set was confirmed by building a CodeQL DB (same
`security-and-quality` suite as `.github/codeql/codeql-config.yml`) and diffing head vs the merge base. CodeQL
reports taint alerts at the **sink**, so they don't appear *in* the four new router files — the routers are the
**source**, the sinks live in shared/leaf modules. The 5 (4 high + 1 medium):
- **4× `py/polynomial-redos` (CWE-1333)** — `integrations.py` transcript-ingest body flows into the three
  line-marker regexes in `autonomy/transcript_watcher.py`. Each had a trailing `\s*`/`\s+` immediately followed
  by `(?P<task>.+)` — both match whitespace, so a long space run backtracks polynomially. Fix: anchor the task
  group as `(?P<task>\S.*)`. The greedy leading `\s*`/`\s+` already eats all whitespace, so this is
  behavior-identical (verified by the H12.25 suite) while removing the ambiguous overlap.
- **1× `py/log-injection` (CWE-117)** — `admin.py` put-category (category + body keys) flows into
  `settings_db.put_category`'s `logger.warning`. Fix: `settings_db._logsafe()` strips CR/LF before logging, and
  the call switched to `%`-style lazy args.

Re-running the local CodeQL DB after the fix: all 5 cleared, **0 new alerts** introduced (the only remaining
alert touching a changed file is a *pre-existing* `py/stack-trace-exposure` from `rooms.py`'s `f"[error:{e}]"`
chat reply → `nocache_json`, which is on `main` and in a different domain, so out of scope here). Locked by
`tests/test_h12_25_transcript.py::test_extraction_is_redos_safe_on_pathological_input` and
`tests/test_settings_db.py::test_logsafe_strips_newlines`.

**Reflected user-input hardening (PR #196 "harden now" item):** independent of the 5 above (CodeQL did *not*
flag these — JSON responses aren't an XSS sink here), the four routers also echoed a user-supplied path/query id
into response bodies. Added `web_helpers.safe_reflect(value)` (truncate → strip to a conservative identifier
charset → `html.escape`) and applied it to the `unknown category` / `agent … not found` / `trace … not found` /
`no webhook channel` messages and the prompt-diff `agent_id` key — defense-in-depth for the reflected-input
class the PR plan called out. No-op for realistic ids, so routes/OpenAPI stay byte-identical; locked by
`tests/test_error_json_sanitizer.py`. Free-text echoes (`q`/`subject`) are left untouched (sanitizing would
corrupt legitimate spaces/text).

**integrations** (batch 6, no test edits): the only HTTP-level test (`test_h12_25_transcript`) monkeypatches
`web.orch`/`web.USER_TOKEN`, both already honored by `get_orch()` + the user guard accessor, so the standard
pattern applied with zero coupling work. Request models modernized to `str | None`.

**Two infra fixes during this work:** (1) pinned `fastapi>=0.136.3,<0.137` in both requirements files — fastapi
0.137.0 regressed `app.include_router` (mounted routers add 0 routes → the app silently loses ~100 routes); CI
(Python 3.12) floated to 0.137.0 and the **route-parity guard caught it** (would have broken production too).
(2) `tests/test_hud_v2_parity.py` `_routes()` now scans `core/routers/*.py` too (not just inline `web.py` @app
routes) — extraction had dropped the inline count below its `>150` floor; the fix restores it and strengthens
the gate (extracted routes are now checked for a v2 home). Also fixed the routers↔web import cycle at the source: `_deps.py`
resolves web via `sys.modules` (leaf module), clearing the CodeQL cyclic-import alerts for every router import.

**Unblock policy for test-coupled domains (established batch 4, zero test edits):** most remaining domains have
test-coupling to `web`. Two sanctioned, behavior-preserving unblocks: **(A)** if a test imports a handler
symbol from `agents.web` (e.g. `from agents.web import audit_verify`), **repoint that test import to the
symbol's new home** (`from agents.core.routers.X import handler`) — a mechanical 1-line import update, no
assertion change. (Re-exporting from `web.py` was the first attempt but CodeQL's unused-import query flags the
re-export, so repointing the import is cleaner.) **(B)** if a handler reads a web.py module-global a
test monkeypatches (`DEV_MODE`, lazily-created singletons), add a request-time `app_state` accessor that reads
`web.X` via `sys.modules` (like `get_orch`/`dev_mode`) so the monkeypatch stays observed. Both keep every test
unchanged and add no static import edge.

**Still to extract:** payments/eval-datasets (cross-domain singleton edges — extract with consumers); MCP
(heavy singletons: `_build_mcp_server`, admin/mcp lifecycle); workflows/pipelines; misc tail
(status/sessions/plugins/learning/bench/agent-templates, vlm/media/desktop/context/digest/schedule, voice/tts,
heartbeat, health/components); dashboard + chat-SSE LAST (hot path / shared `asyncio.Lock`).
`data_spaces`/`secrets` ✅ done (batch 5) — `data_spaces` via unblock B (singleton home stays on `web`, router
reads it via a sys.modules accessor); `secrets` was orchestrator-only (no unblock needed). `integrations`
✅ done (batch 6).

Tiered easiest→hardest; each PR gated by the Phase-0 parity guard + full suite. Mirror the existing
`capture.py`/`pairing.py` pattern; move a domain's owning singleton with it; keep `put_category` in
`web.py` until the end (cross-cutting).

- **Tier 1** (textbook, well-tested, singleton-backed): payments → eval-datasets → data-spaces →
  secrets/widgets → rooms → notes → actions.
- **Tier 2–3**: arena/review/quality → workflows → prompts → analytics/cost/traces → settings/env/audit →
  admin-stats → security → memory/KG → models/LLM → **MCP** (most-coupled non-hot) → autonomy.
- **Tier 4 (untested — add smoke tests *first*)**: distributed mesh (satellites/nodes/sync/toolrpc/
  subagents), heartbeat, media/vlm/desktop.
- **Tier 5 (last)**: dashboard/agents-roster (owns the `asyncio.Lock` + caches), then **chat SSE
  `/chat/stream`** dead last (only `StreamingResponse` + `handle_input_stream`).

Cross-domain edges set sequence: do payments + eval-datasets before MCP (`settle_payment`→`_build_mcp_server`,
`mcp_server_rpc`→`_dataset_store`); do payments before analytics (`clear_traces`→`_payment_broker`).

---

## 6. Sequencing, dependencies, effort

```
Phase 0 ──► Phase 1 ──► Phase 3
   │                 ╲
   └──────────────────► Phase 2   (independent; parallelizable with 1/3)
```

Phase 0 gates everything. Phase 1 precedes heavy Phase 3 (removes the `from agents import web` coupling new
routers would inherit). Phase 2 is independent. **Revised effort ~20–25 SP** (vs backlog 5+8) — the 8 SP
for CLN-3 only ever covered "move bodies," not kernel decoupling or test backfill. Front-loaded with the
zero-risk net.

## 7. Consolidated risk register

1. **Duplicated singleton → divergent state** vs a monkeypatched `web._x`. One home in `app_state`; alias on `web`.
2. **`get_orch()` must late-bind** (`from agents import web; return web.orch` inside the fn).
3. **Lifespan ordering** for scheduler/autonomy/`aclose` — covered only by the new smoke test.
4. **Bare-test attribute contract** — don't convert pinned attributes into manager-delegating properties.
5. **`asyncio.Lock`/`_rate_hits` object identity** — alias the same object, never recreate.
6. **`put_category`/`get_category` import spelling** (`core.settings_db`, sys.path includes `agents/`) — keep lazy in-function imports; `test_mcp_api.py` is the canary.

---

## Appendix A — Verification test code (Phase 0)

`tests/test_route_parity_guard.py` (seed once on baseline: `python tests/test_route_parity_guard.py --update`):

```python
import json
from pathlib import Path
from fastapi.routing import APIRoute

SNAPSHOT = Path(__file__).resolve().parent / "_snapshots" / "route_surface.json"

def _route_surface():
    from agents import web
    sig = set()
    for r in web.app.routes:
        if isinstance(r, APIRoute):
            for m in (r.methods - {"HEAD", "OPTIONS"}):
                sig.add(f"{m} {r.path}")
    return sorted(sig)

def test_route_surface_unchanged():
    assert SNAPSHOT.exists(), "seed with --update"
    cur, exp = set(_route_surface()), set(json.loads(SNAPSHOT.read_text()))
    added, removed = sorted(cur - exp), sorted(exp - cur)
    assert not added and not removed, f"ADDED {added}\nREMOVED {removed}"

def test_route_surface_size_sanity():
    assert len(_route_surface()) >= 290

if __name__ == "__main__":
    import sys
    if "--update" in sys.argv:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(_route_surface(), indent=2) + "\n")
```

`tests/test_lifespan_smoke.py`:

```python
from fastapi.testclient import TestClient

def test_lifespan_starts_and_stops_clean():
    from agents import web
    assert web.orch is None
    with TestClient(web.app) as c:
        assert web.orch is not None
        assert set(web.orch.channels) >= {"web", "voice"}
        assert c.get("/api/status").status_code == 200
        assert web.orch.scheduler.get_jobs()      # _schedule_* registered jobs
    assert web.orch is None
```

Per-step workflow: (0) seed snapshots on `main`, confirm 2,212 green; (a–d) per domain/manager — extract
one (small reversible commit) → run parity + openapi + lifespan guards then full suite (zero diff, count
stays 2,212) → backfill characterization tests for any hard-untested route touched, written against old
behavior first.

## Appendix B — Hard-untested routes (83; backfill these before/with extraction)

Grouped by prefix (representative): **llm** (`POST /api/llm/load`, `/unload`, `/server/start`, `/moe/route`,
`/openrouter`, `GET /api/llm/auth-profiles`); **mesh** (`GET/POST /api/nodes`, `/api/nodes/register`,
`/api/nodes/{id}/dispatch`, `DELETE /api/nodes/{id}`; same for `/api/satellites/*`); **sync/oauth/oracle**
(`POST /api/sync/push|pull`, `/api/oauth/callback|refresh`, `GET /api/oauth/auth-url`, `POST /api/oracle/sync`,
`/api/oracle/conflicts/resolve`); **heartbeat** (`POST /heartbeat/{agent_id}/start|stop|run`,
`GET /heartbeat/status`); **autonomy** (`GET/POST /autonomy/mode`, `POST /api/autonomy/call`,
`GET /api/autonomy/tasks/{id}/preview`); **admin** (`GET /api/admin/audit`, `/widgets`, `/agents/stats`,
`POST /api/admin/llm/test`, `/memory/clear`, `PUT /api/admin/agents/{id}`); **misc** (`GET /api/status`,
`/api/security/kill-switch`, `/api/payments`, `POST /api/payments/{id}/reject`, `/api/context/compress`,
`/api/vlm/describe`, `/api/media/generate`, `/api/subagents/spawn`, `/api/toolrpc/call`). Also the 11
already-extracted-but-untested (cognition `ensemble|honesty|learning|memory|personality|stream`, capture
`status|clear`, a2a `card|peers/{id}`).

## Appendix C — Critical files

`agents/core/orchestrator.py` · `agents/web.py` · `agents/core/routers/{__init__,_deps,capture,pairing}.py` ·
`agents/core/cognition/api.py` (the proven lazy-`_facade()` pattern) · `agents/core/channels/manager.py`
(existing CLN-2 precedent) · `agents/core/component_registry.py` (back-ref pattern) · `tests/conftest.py`
(`make_app`; autouse `_disable_user_guard` overrides both `web._user_guard` and `_deps.user_guard`).
New modules to create when executing: `agents/core/web_helpers.py`, `agents/core/app_state.py`,
`agents/core/scheduler_service.py`, `agents/core/llm_control.py`, `agents/core/plugin_gatherer.py`,
`agents/core/autonomy_coordinator.py`; tests `tests/test_route_parity_guard.py`,
`tests/test_openapi_parity_guard.py`, `tests/test_lifespan_smoke.py`, snapshots under `tests/_snapshots/`.
