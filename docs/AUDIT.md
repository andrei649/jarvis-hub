# Code & Architecture Audit — v9.9.9 (pre-1.0 gate)

> **Date:** 2026-06-03 · **Scope:** whole codebase (architecture, bugs, code quality, docs).
> **Purpose:** `9.9.9` is the last version before 1.0. This audit is the gate:
> findings here feed the **human manual-testing** pass (`docs/MANUAL_TESTING.md`)
> and the **fix** pass that follow, before tagging `1.0.0`.
>
> Method: four parallel read-only reviews (architecture, bug-hunt, code-quality,
> docs) cross-checked against the running code. Every finding below was
> **verified against source** — inaccurate agent findings are called out as such
> so they don't waste fix-phase effort.

## Executive summary

The codebase is **functionally complete and well-tested** (1,559 offline tests,
green) with **strong horizontal organization** — `agents/core/` splits cleanly
into `memory/`, `autonomy/`, `workflows/`, `security/`, `observability/`,
`llm/`, `channels/`, `mcp/`, each coherent. The weaknesses are **vertical**:
the HTTP layer (`web.py`) and the composition root (`orchestrator.py`) have
grown into a monolith and a god-object respectively, and a persistence pattern
was copy-pasted ~13 times. None of this is a correctness emergency — it's
**maintainability debt** that's cheap to pay down now and expensive later.

**No release-blocking bugs were found.** The two "critical" security findings in
the automated bug-hunt (secret-broker plaintext leak) were **false positives**
(verified — see §2). The genuine bugs are low-severity hardening items.

**Verdict:** sound foundation; do the **P0 cleanups** (below) during the fix
phase, ship `1.0.0`. The big refactors (router split, service container) are
**P1 — valuable but not blocking**.

---

## 1. Architecture findings

| # | Severity | Finding | Location | Recommendation |
|---|----------|---------|----------|----------------|
| A1 | **High** | `web.py` is a 3,978-line monolith with ~203 route decorators in one file; ~88 `getattr(orch, "X", None)` reach-ins. | `agents/web.py` | Split into `agents/routers/*` `APIRouter`s by feature area (admin, memory, autonomy, observability, security, workflows, arena, collaboration). Mechanical, test-covered, do incrementally. |
| A2 | ✅ **done** | The 14 repetitive optional-component `try/except` blocks now go through a `ComponentRegistry` (`component_registry.py`): one registrar handles lazy-import + construct + status-tracking, sets `orch.<name>` (back-compat unchanged), and a startup **health report** logs `Components: N/N ok` (**A8**) + `GET /api/health/components`. Collapsed ~80 lines → ~20; failures are now visible, not silent. Remaining god-object surface (plugins/skills/channels init) can follow the same pattern later. | `agents/core/orchestrator.py`, `component_registry.py` | — |
| A3 | ✅ **done** | (base shipped: `persistence/json_store.py`; 6 stores migrated — Widget/Room/Notes/ReviewQueue/Webhook/Arena. Memory/security stores can follow the same base later.) ~13 JSON stores re-implemented identical `_load`/`_save`(atomic tmp+replace)/`threading.Lock`/`__init__(path)` boilerplate (~26 `_load`/`_save` pairs). | `widget.py`, `rooms.py`, `notes.py`, `arena.py`, `webhooks.py`, `observability/review_queue.py`, `autonomy/action_approvals.py` (in-mem), `memory/{entity,bitemporal,decay}.py`, `security/{anchor,capability}.py`, `run_history.py`, `soul_versioning.py` | Extract `agents/core/persistence/json_store.py` `JsonStore` base; subclasses keep only their schema. Removes ~200 LOC and the drift risk. |
| A4 | **Medium** | Blocking I/O on the async path: sync `write_text`/`sqlite3` inside `async def` handlers (JSON store saves, `/api/admin/audit` direct sqlite). | `web.py` store endpoints; `agents/web.py` audit route | Wrap blocking calls in `await asyncio.to_thread(...)`. Files are small so impact is moderate today, but it blocks the event loop under load. |
| A5 | **Medium** | Repeated 503-guard preamble (`getattr(orch,...)→503`) in ~50+ endpoints. | `web.py` | Add one FastAPI dependency `require_component("arena")` returning the component or raising 503. Removes ~100 LOC. |
| A6 | — | ✅ **verified safe** — `workflows/engine.py`'s `Orchestrator` import is `TYPE_CHECKING`-guarded (line 19), so there is **no** circular-import risk. (Flagged by the auto-audit; confirmed a non-issue.) | `agents/core/workflows/engine.py:19` | None needed. |
| A7 | ✅ **done** | `ActionApprovalQueue` now inherits `JsonStore` with **opt-in** persistence (orchestrator passes a path; `path=None` stays in-memory for tests); `asyncio.Event`s re-created lazily for reloaded items. | `autonomy/action_approvals.py` | — |

---

## 2. Bug findings (verified)

| # | Severity | Status | Finding | Location |
|---|----------|--------|---------|----------|
| B1 | **Low** | ✅ **fixed** | `await_decision` reads `self._items[action_id]["status"]` **after** the `await`, unguarded → `KeyError` if `clear()` races. | `autonomy/action_approvals.py` (`await_decision`) → use `self._items.get(action_id, {}).get("status", "unknown")` |
| B2 | **Low** | ✅ **fixed** | Intentional best-effort `except Exception: pass` swallows preview errors with no trace. | `autonomy/escalation.py` `render_escalation` → log at `debug`. |
| B3 | — | ❌ **false positive** | "SecretBroker.redact/has TOCTOU returns plaintext." **Not true** — actual `redact()` snapshots names under lock then skips any deleted secret (`get()→None`); no plaintext path. `has()` lock-free read is harmless. | `security/secret_broker.py` (verified) |
| B4 | — | ❌ **false positive** | "`asyncio.Event()`/`asyncio.Lock()` built in `__init__` crash." **Not true on Python ≥3.10** — they no longer bind a loop at construction; async tests pass. | `action_approvals.py`, `memory/manager.py` |
| B5 | **Low** | ⚠️ acceptable | `time.sleep` backoff in the embedder runs **inside a thread-pool worker** (already off the event loop), so it's tolerable; convert to async only if that path moves on-loop. | `ingestion/embedder.py` |
| B6 | **Low** | ✅ **fixed** | Fire-and-forget `asyncio.create_task`/`ensure_future` without a done-callback can swallow exceptions (voice wake-word, gemini cache warm). | `voice/pipeline.py`, `orchestrator.py` → attach `add_done_callback` that logs `t.exception()`. |

**Security posture:** the quarantine (H17.1), capability/kill-switch (H17.3),
secret broker (H15.4), and audit-anchor (H17.4) modules were reviewed — **no
bypass found**. Admin-guarded endpoints are consistently gated. The lethal-trifecta
defenses hold.

---

## 3. Code-quality findings

| # | Severity | Finding | Recommendation |
|---|----------|---------|----------------|
| Q1 | High | Same as A3 (store duplication). | `JsonStore` base. |
| Q2 | High | Same as A5 (getattr/503 boilerplate, ~88×). | `require_component` dependency. |
| Q3 | ✅ **mostly done** | The systemic catch-all already returns a generic 500 (no leak); the explicit `str(e)`-on-500 handlers (TTS, notes-rewrite, skills/marketplace, MCP probe, review-dataset) now log the detail and return a generic `{"error": "internal error", "code": 500}`. 400/404 validation messages kept (user-facing). | `agents/web.py` (handlers exist at lines ~180–201). Full `require_component` boilerplate dedup (A5) deferred — see note. |
| Q4 | ✅ **partly done** | The named limits (`NOTES_MAX_LEN`, `ROOM_HISTORY_CAP`, `RUN_HISTORY_MAX_PER_AGENT`) + `MEMORY_DIR` + `data_path()` now live in `agents/core/config.py`; the three modules alias them (back-compat). Migrating every store's `DEFAULT_PATH` to `data_path()` left as an optional follow-up. | `agents/core/config.py` | — |
| Q5 | Low | ~50+ public methods/classes lack docstrings/return-type hints (e.g. `agent.py`, `cost_tracker.py`, `resilience.py`). | Sweep; add `mypy`/`ruff` docstring lint (non-blocking) to CI. |
| Q6 | Low | Atomic tmp+replace write used by stores but **not** in `ingestion/watcher.py`, `memory/conversation.py`, `plugins/oracle_bridge.py`. | Once `JsonStore` exists, route these through it. |
| Q7 | ✅ **done** | `tests/README.md` added — run commands, the `test_hXX_*`→backlog naming convention, an area-coverage table, conventions, and the `apscheduler` note. | `tests/README.md` | — |

---

## 4. Documentation findings — **fixed in this PR**

The doc audit found pervasive stale numbers. **Corrected here** (verified against
code): version `0.9.x` → **9.9.9** everywhere; agent count `15` → **16** (JARVIS.md
×4); test count (`846`/`909`/`1184`/`1474`) → **1,559** (1,568 collected, 9 skipped; verified 2026-06-04); endpoint count
(`17`/`19`/`88`) → **~203**; model `gemma-4-26b` → `gemma-4-31b` (JARVIS.md self-conflict);
ARCHITECTURE port typo `8000` → `8080`; ARCHITECTURE module index gained the
`observability/` entries (`quality`, `review_queue`, `datasets`); BACKLOG/MOONSHOT/
VALUATION/STATUS refreshed; a `9.9.9` row added to the version roadmap.

**Corrected agent error:** the doc audit claimed `LICENSE`/`CONTRIBUTING.md` were
missing — **they exist** (shipped under H7.9). No action taken.

**Still open (low):** JARVIS.md vs docs/ARCHITECTURE.md overlap — consider making
ARCHITECTURE.md the single source for the module index and trimming JARVIS.md to
a high-level overview (deferred; not blocking).

---

## 5. Prioritized remediation roadmap

**P0 — do during the fix phase, before 1.0 (low risk, high signal):**
1. `JsonStore` base class; migrate the ~13 stores (A3/Q1). Big duplication win, all test-covered.
2. `require_component` dependency + one `ErrorResponse` model/handler (A5/Q2/Q3). Kills boilerplate, standardizes the API surface.
3. Wrap blocking store/sqlite writes in `asyncio.to_thread` (A4).
4. The two real micro-bugs: `await_decision` `.get` guard (B1) and `create_task` done-callbacks (B6); demote `except:pass` to `debug` (B2).
5. Persist `ActionApprovalQueue` (A7).

**P1 — valuable, not blocking (schedule post-1.0 or during if time allows):**
6. Split `web.py` into feature `APIRouter`s (A1).
7. Component registry + startup health report on the Orchestrator (A2).
8. Centralize config/paths/limits (Q4).

**P2 — polish:**
9. Docstring/type-hint sweep + CI lint (Q5); `tests/README.md` (Q7); JARVIS.md/ARCHITECTURE.md de-duplication.

---

## 6. Actioned in this PR
- Version bumped to **9.9.9** (single source `agents/__init__.py`; propagates to `/version` + `/status`).
- All stale doc numbers synced (§4).
- This audit report added.

Code refactors (P0–P2) are intentionally **not** applied here — they belong to
the post-manual-testing fix phase so audit findings and fixes stay reviewable
and the `9.9.9` snapshot stays a clean, behavior-frozen baseline for human testing.

## 7. Fix-phase progress (post-audit)

Applied (each its own PR, behavior-preserving, full-suite green):
- **B1/B2/B6** micro-bug hardening (#113).
- **A3/Q1** `JsonStore` base + **all 13 stores migrated** (#114 + follow-up: Widget,
  Room, Notes, Review, Webhook, Arena, ActionApprovalQueue, BiTemporalKG, EntityStore,
  SoulVersionStore, DecayMemory, KillSwitch, RunHistory, IntentLog, TransparencyAnchor).
  The duplicated `_load`/`_save`/lock boilerplate now exists once, in the base.
- **A7** `ActionApprovalQueue` persistence (opt-in) + `JsonStore` in-memory mode.
- **Q3** `str(e)`-on-500 leaks hardened to generic messages (detail still logged).
- **A3** completed — all 13 stores on the `JsonStore` base (#116).
- **Q4** named limits + `MEMORY_DIR`/`data_path` centralized in `core/config.py`.
- **Q7** `tests/README.md` test index added.
- **A2 + A8** `ComponentRegistry` — the 14 god-object `try/except` init blocks
  collapsed to a registrar with a startup health report (`GET /api/health/components`).

**Deferred to post-manual-testing (mechanical, behavior-neutral, higher churn):**
- **A5/Q2** the `require_component` FastAPI dependency to dedupe the ~88 `getattr(orch,…)→503`
  guards — best done in one consistent sweep *after* manual testing has exercised
  the real degradation paths, since many endpoints intentionally degrade gracefully
  (return empty) rather than 503, and a blanket migration would change that.
- **A1** `web.py` router split, **A2** orchestrator component registry, **A4** blocking-I/O
  offload, **Q4** config centralization — P1/P2, scheduled for after the test gate.
