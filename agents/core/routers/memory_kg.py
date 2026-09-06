"""Memory + Knowledge-Graph endpoints — extracted from web.py (CLN-3).

Covers the long-term memory and knowledge-graph surface across two address
spaces:

* `/api/memory/*` — sleep-time consolidation (H14.3), fused recall / search
  (H5.14), the named-entity store (H8.1b), the LLM-callable search_memory tool
  (H8.3b), decay-based forgetting (H14.4), the memory-eval corpus + harness
  (H14.2), remember/recall, and the machine-facing tool-spec/search-tool.
* `/api/kg/*` — the knowledge-graph editor (H12.3), bi-temporal facts (H14.1),
  and incremental triple ingest (H12.6).

Excludes the data-space surface (`/api/memory/profile`,
`/api/memory/spaces...`), which lives in `routers/data_spaces.py`, and the
non-`/api`-prefixed `/memory/stats`, which stays in web.py.

Orchestrator-only: every handler reads its subsystem off the live orchestrator
(`orch.memory` / `orch.entities` / `orch.decay` / `orch.bitemporal` /
`orch.kg_updater` / `orch.consolidation`) via `get_orch()`, with no web-module
globals. The `_kg()` and `_structured_recall()` helpers were used only by this
domain and are moved here verbatim (they now resolve the orchestrator through
`get_orch()` instead of the web module global).
"""

import asyncio
import contextlib
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse

from agents.core.action_origin import bind_action_origin, current_action_origin, reset_action_origin
from agents.core.automation_contracts import ContractTemplate, contract_denial, predicate
from agents.core.memory.consolidation import (
    ADD, DELETE, UPDATE, ListStore, existing_from_hits, validate_plan,
)
from agents.core.routers._deps import user_guard
from agents.core.routers._component import require_component
from agents.core.security import quarantine, taint
from agents.core.security.rag_guard import REDACTION, provenance_from_hit
from agents.core.security.recall_taint import mark_turn_recall_tainted

from agents.core.web_helpers import nocache_json, error_json
from agents.core.app_state import get_orch
from agents.core.validation import is_safe_kg_label, is_safe_kg_rel_type


router = APIRouter(tags=["memory"])
logger = logging.getLogger("jarvis.memory_kg")

KG_WRITE_CONTRACT_KIND = "kg.write"
_KG_WRITE_OPS = frozenset({
    "add_entity",
    "delete_entity",
    "add_relation",
    "delete_relation",
    "add_fact",
    "ingest",
})


def _kg_write_contract_template() -> ContractTemplate:
    """Contract form of the external KG-write admissibility gate."""

    def kg_write_kind(view, now):
        return view.get("kind") == KG_WRITE_CONTRACT_KIND

    def known_operation(view, now):
        return view.get("op") in _KG_WRITE_OPS

    return ContractTemplate(kind=KG_WRITE_CONTRACT_KIND, constraints=(
        predicate("kg_write_kind", kg_write_kind, reason="invalid_kind"),
        predicate("known_kg_operation", known_operation, reason="unknown_operation"),
    ), requires_approval=False, description="Admissibility for external knowledge-graph writes.")


KG_WRITE_CONTRACT = _kg_write_contract_template()


def _kg_contract_denial(payload: dict) -> str | None:
    """Return a stable contract denial for an external KG write, or None."""
    contract_payload = {"kind": KG_WRITE_CONTRACT_KIND, **(payload or {})}
    try:
        decision = KG_WRITE_CONTRACT.evaluate(contract_payload, now=time.time())
    except Exception:
        logger.warning("KG write contract evaluation failed", exc_info=True)
        return "contract_error"
    return contract_denial(decision)


def _kg_kernel_denial(orch, payload: dict, token_id: Optional[str] = None, scope: str = "global"):
    """ORIZONT-24 K1 wave-3/4b (kg.write): mediate an *externally-driven* KG write through
    the Action Kernel (default-off). Returns a deny-reason (caller → HTTP 403) or ``None``
    (allow). **DENY only** — GRANT/QUEUE allow through (an unknown ``kg.write`` kind
    classifies top-tier → policy QUEUE; we honor only a hard DENY: a halted kill-switch,
    a missing capability token, or a *presented* token that lacks ``kg:write``).

    **Boundary (the whole point of this slice):** only the externally-driven ``/api/kg/*``
    HTTP handlers call this. The high-frequency *internal* ingestion path — incremental
    ``IncrementalKGUpdater.ingest`` from ``orchestrator._record_interactions``, ``seed_graph``,
    reflection/worldview promotion — writes ``graph.add_entity``/``add_relation`` DIRECTLY and
    never traverses these handlers, so it pays no per-write kernel cost and a halt never
    freezes per-turn memory. (``POST /api/memory/remember`` is a vector-store write, and
    ``/consolidate`` returns a plan with no mutation, and ``/decay/forget`` is an ACT-R decay
    op — none are KG writes, so they are intentionally out of this ``kg.write`` slice.)

    Payload carries keys/ids only (audit-PII hygiene — never property values).

    wave-4b: a token is now MANDATORY (``kernel.TOKEN_MANDATORY_KINDS``). Every route that
    calls this already sits behind ``user_guard`` — the caller is already proven — so when
    nothing was *presented* via ``x-capability-token`` we mint a short-lived, single-
    capability operator token ourselves rather than presenting an empty one, letting the
    kernel's real capability nucleus run. ``make_action_kernel`` is imported lazily so the
    router stays import-cheap and the matrix exerciser can substitute a spy.
    """
    from agents.core.kernel import kernel_enabled
    if not kernel_enabled():
        return None
    from agents.core.kernel.binding import make_action_kernel
    kernel = make_action_kernel(orch)
    if kernel is None:
        return None
    from agents.core.kernel import Action, Capability, Verdict
    from agents.core.kernel.capabilities import issue_operator_capability
    if not token_id:
        token_id = issue_operator_capability(getattr(orch, "capabilities", None), "kg:write")
    decision = kernel(
        Action(kind="kg.write", agent="external", title=f"kg write {payload.get('op', '')}",
               payload=payload, scope=scope, origin="external"),
        capability=Capability(token_id=token_id or "", name="kg:write"))
    return decision.reason if decision.verdict is Verdict.DENY else None


# ── SEC-B5 / CDX-7: the HTTP recall routes as a designed ingress ──────────────

@contextlib.asynccontextmanager
async def _recall_scope():
    """SEC-B5: bind-on-entry / reset-on-exit around an HTTP recall handler.

    The three recall routes (``/api/memory/search``, ``/api/memory/recall``,
    ``/api/memory/search-tool``) raise the turn's ``action_origin`` to
    ``recall:untrusted`` when they hand back untrusted or injection-flagged
    memory. They have no turn of their own; until now the mark was bounded only
    *incidentally* by asyncio's per-Task context copy (BACKLOG SEC-B5). This
    scopes it by design: the pre-request origin is snapshotted on entry and
    restored on exit — of the **whole handler**, in a ``finally``.

    Polarity, stated because a narrower reset was reviewed and withdrawn as
    fail-open: the reset runs only after the response is fully built, so nothing
    a handler does after the recall (today: nothing; tomorrow: an act) ever sees a
    scrubbed origin. Within the scope the mark is in force and is *reported* in
    the response (``tainted`` / ``action_origin``), so the escalation the kernel
    would apply is inspectable rather than silent. A direct (non-Task) caller —
    a test, an in-process consumer — no longer leaks the mark into its context.
    """
    token = bind_action_origin(current_action_origin())
    try:
        yield
    finally:
        reset_action_origin(token)


def _redact_payload_text(payload: dict) -> dict:
    """Return a copy of a fused-hit payload with every text-bearing field redacted."""
    out = dict(payload or {})
    for k in ("text", "name"):
        if out.get(k):
            out[k] = REDACTION
    for bucket in ("metadata", "properties"):
        md = out.get(bucket)
        if isinstance(md, dict) and md.get("text"):
            md = dict(md)
            md["text"] = REDACTION
            out[bucket] = md
    return out


def _guard_hit(hit) -> dict:
    """CDX-7 on the HTTP recall path: one fused hit → one scanned, provenance-tagged row.

    ``rag_guard.wrap_memory`` fences memory for a *prompt*; these routes answer
    JSON to the HUD, so the same three moves are applied to the row instead of a
    block: the injection scanner runs over the snippet and a flagged hit is
    **redacted** (score and provenance kept, text replaced, ``injection_flagged``
    set), the honest ``source`` provenance rides along, and ``tainted`` says
    whether the hit came from an untrusted source or was flagged. Never raises.
    """
    try:
        snippet = provenance_from_hit(hit)
        payload = getattr(hit, "payload", None)
        if payload is None and isinstance(hit, dict):
            payload = hit.get("payload", {})
        payload = dict(payload or {})
        md = payload.get("metadata") or payload.get("properties") or {}
        flags = quarantine.detect_injection(snippet.text) if snippet.text else []
        untrusted = taint.is_untrusted_source(snippet.source) or taint.is_tainted(md)
        row = {
            "id": getattr(hit, "id", None) if not isinstance(hit, dict) else hit.get("id"),
            "score": round(float(getattr(hit, "score", 0.0) if not isinstance(hit, dict)
                                 else hit.get("score", 0.0) or 0.0), 4),
            "sources": list(getattr(hit, "sources", None) or
                            (hit.get("sources") if isinstance(hit, dict) else None) or []),
            "source": snippet.source,
            "payload": _redact_payload_text(payload) if flags else payload,
            "tainted": bool(flags) or untrusted,
        }
        if flags:
            row["injection_flagged"] = True
            row["flags"] = flags
        return row
    except Exception:
        logger.warning("recall hit guard failed; row dropped", exc_info=True)
        return {"id": None, "score": 0.0, "sources": [], "source": "memory",
                "payload": {}, "tainted": True, "dropped": True}


def _guard_store_row(row: dict) -> dict:
    """CDX-7 for ``/api/memory/recall`` rows (``MemoryStore``: key/value/category).

    These are the user's own stored facts, so the source is trusted by default;
    only an injection-flagged value taints (and is redacted)."""
    out = dict(row or {})
    value = out.get("value")
    flags = quarantine.detect_injection(value) if isinstance(value, str) and value else []
    out["tainted"] = bool(flags)
    if flags:
        out["value"] = REDACTION
        out["injection_flagged"] = True
        out["flags"] = flags
    return out


def _mark_if_tainted(rows) -> bool:
    """Raise the scoped origin when any guarded row is tainted; return the verdict."""
    tainted = any(bool(r.get("tainted")) for r in rows if isinstance(r, dict))
    if tainted:
        mark_turn_recall_tainted()
    return tainted


# ── H14.3 Sleep-time memory consolidation ─────────────────────────────────────

@router.post("/api/memory/consolidate", dependencies=[Depends(user_guard)])
async def memory_consolidate(req: Request):
    """Plan Mem0-style consolidation ops (ADD/UPDATE/DELETE/NOOP) for candidates
    against existing memories. Returns a reversible plan (no mutation)."""
    _, eng, err = require_component("consolidation", "consolidation not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    candidates = (body or {}).get("candidates") or []
    if not candidates:
        return JSONResponse({"error": "candidates required"}, status_code=400)
    # plan() is O(candidates x existing) similarity over caller-supplied text —
    # keep that CPU off the event loop.
    existing = (body or {}).get("existing") or []

    def _plan():
        p = eng.plan(candidates, existing)
        return p, eng.summarize(p)

    plan, summary = await _kg_call(_plan)
    return nocache_json({"plan": plan, "summary": summary})


async def _fused_recall(memory, q: str, top_k: int):
    """Embed *q* (when the manager can) and run fused recall; the vector arm
    degrades to keyword/graph-only when embedding fails or is absent."""
    embedding = await memory.embed(q) if q and hasattr(memory, "embed") else None
    return await memory.hybrid_search(embedding=embedding, keyword=q or None, top_k=top_k)


@router.get("/api/memory/consolidate/preview", dependencies=[Depends(user_guard)])
async def memory_consolidate_preview(q: str = "", top_k: int = Query(20, ge=1, le=50)):
    """DRA-27: the ``existing`` memories a consolidation plan should run against.

    Answers the design question that kept ``/api/memory/consolidate`` unwired:
    where ``existing`` comes from. It is fused recall over the live store, adapted
    to the planner's ``{id, key, text}`` shape (``existing_from_hits``), scanned
    like every other recall (CDX-7) and taint-scoped like one (SEC-B5).
    ``available:false`` with a ``reason`` when there is no memory manager — an
    empty list under a green chip would be the degenerate planner in disguise.
    """
    orch = get_orch()
    memory = getattr(orch, "memory", None) if orch else None
    if memory is None or not hasattr(memory, "hybrid_search"):
        return nocache_json({"available": False, "reason": "memory_unavailable",
                             "existing": [], "total": 0, "query": q, "tainted": False})
    async with _recall_scope():
        try:
            hits = await _fused_recall(memory, q, top_k)
        except Exception as e:
            return error_json(e, 200, "memory recall failed", extra={
                "available": True, "existing": [], "total": 0, "query": q, "tainted": False})
        guarded = [_guard_hit(h) for h in hits]
        tainted = _mark_if_tainted(guarded)
        existing = []
        for row, hit in zip(guarded, hits, strict=False):
            adapted = existing_from_hits([hit])
            if not adapted:
                continue
            entry = adapted[0]
            if row.get("injection_flagged"):
                entry["text"] = REDACTION
                entry["injection_flagged"] = True
            entry["tainted"] = bool(row.get("tainted"))
            existing.append(entry)
        return nocache_json({"available": True, "existing": existing, "total": len(existing),
                             "query": q, "tainted": tainted,
                             "action_origin": current_action_origin()})


async def _vector_remove(memory, record_id: str) -> bool:
    """Remove one vector record through the manager's lock (off-loop: Qdrant is httpx)."""
    vectors = getattr(memory, "vectors", None)
    if vectors is None or not hasattr(vectors, "remove"):
        return False
    lock = getattr(memory, "_lock", None)
    if isinstance(lock, asyncio.Lock):
        async with lock:
            await asyncio.to_thread(vectors.remove, record_id)
    else:
        await asyncio.to_thread(vectors.remove, record_id)
    return True


async def _persist_consolidation(memory, plan: list[dict], existing: list[dict]) -> dict:
    """Write an applied plan back to the live vector store, honestly.

    ADD → ``remember``; UPDATE → remove + ``remember`` under the same id (a plain
    re-add would leave the stale vector behind); DELETE → remove. Rows the preview
    marked non-persistable (graph-only) are *skipped with a reason*, as is an ADD
    the manager could not embed — never counted as persisted.
    """
    persisted = {ADD: 0, UPDATE: 0, DELETE: 0}
    skipped: list[dict] = []
    by_id = {str(e.get("id")): e for e in existing if isinstance(e, dict) and e.get("id")}
    if memory is None or not hasattr(memory, "remember"):
        return {"persisted": persisted, "skipped": [{"reason": "memory_unavailable"}],
                "persistence": "memory_unavailable"}
    for idx, op in enumerate(plan):
        kind = op.get("op")
        target = str(op.get("target_id") or "")
        meta = {"key": op.get("key"), "source": "consolidation"}
        try:
            if kind == ADD:
                rid = await memory.remember(op.get("text", ""), metadata=meta)
                if rid is None:
                    skipped.append({"index": idx, "op": kind, "reason": "no_embedding"})
                else:
                    persisted[ADD] += 1
            elif kind in (UPDATE, DELETE):
                if not by_id.get(target, {}).get("persistable", False):
                    skipped.append({"index": idx, "op": kind, "reason": "not_vector_backed"})
                    continue
                if not await _vector_remove(memory, target):
                    skipped.append({"index": idx, "op": kind, "reason": "no_vector_store"})
                    continue
                if kind == DELETE:
                    persisted[DELETE] += 1
                    continue
                rid = await memory.remember(op.get("text", ""), record_id=target, metadata=meta)
                if rid is None:
                    skipped.append({"index": idx, "op": kind, "reason": "no_embedding"})
                else:
                    persisted[UPDATE] += 1
        except Exception:
            logger.warning("consolidation persist op %s failed", idx, exc_info=True)
            skipped.append({"index": idx, "op": kind, "reason": "store_error"})
    return {"persisted": persisted, "skipped": skipped, "persistence": "vector_store"}


@router.post("/api/memory/consolidate/apply", dependencies=[Depends(user_guard)])
async def memory_consolidate_apply(req: Request):
    """DRA-27: apply (or dry-run) a consolidation plan. Body ``{plan, existing, dry_run?}``.

    Refuses a degenerate call with **422** and a machine-readable ``reason``:
    ``existing: []`` (a plan against nothing), a missing/empty plan, an unknown
    op, an UPDATE/DELETE whose target is not in ``existing``, an ADD/UPDATE with
    no text. The plan is applied to a ``ListStore`` snapshot of ``existing`` (the
    merged result comes back for inspection) and, unless ``dry_run``, written to
    the live vector store with a per-op ``persisted`` / ``skipped`` report.
    """
    orch, eng, err = require_component("consolidation", "consolidation not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    plan = body.get("plan")
    existing = body.get("existing")
    dry_run = bool(body.get("dry_run", False))
    reasons = validate_plan(plan, existing)
    if reasons:
        return JSONResponse({"error": "plan not admissible", "reason": reasons[0],
                             "reasons": reasons}, status_code=422)
    store = ListStore(existing)
    report = await _kg_call(eng.apply_report, plan, store, dry_run=dry_run)
    out = {"ok": not report["errors"], "dry_run": dry_run, "counts": report["counts"],
           "errors": report["errors"], "memories": store.memories}
    if dry_run:
        out.update({"persisted": {ADD: 0, UPDATE: 0, DELETE: 0}, "skipped": [],
                    "persistence": "dry_run"})
    else:
        out.update(await _persist_consolidation(getattr(orch, "memory", None), plan, existing))
    return nocache_json(out)


@router.get("/api/memory/search", dependencies=[Depends(user_guard)])
async def memory_search(q: str = "", top_k: int = 10):
    """Fused recall via RRF: vector similarity + knowledge-graph (H5.14 Task 4).

    CDX-7: every hit is scanned and a flagged one redacted; SEC-B5: an untrusted
    or flagged hit raises the scoped ``action_origin`` and the response says so.
    """
    orch = get_orch()
    top_k = max(1, min(top_k, 50))
    if not orch or not orch.memory:
        return nocache_json({"results": [], "query": q, "total": 0, "tainted": False})
    async with _recall_scope():
        try:
            hits = await _fused_recall(orch.memory, q, top_k)
        except Exception as e:
            return error_json(e, 200, "memory search failed",
                              extra={"results": [], "query": q, "total": 0, "tainted": False})
        results = [_guard_hit(h) for h in hits]
        tainted = _mark_if_tainted(results)
        return nocache_json({
            "results": results,
            "query": q,
            "total": len(results),
            "tainted": tainted,
            "redacted": sum(1 for r in results if r.get("injection_flagged")),
            "action_origin": current_action_origin(),
        })


@router.get("/api/memory/entities", dependencies=[Depends(user_guard)])
async def memory_entities(q: str = "", type: str = "", limit: int = Query(50, ge=1, le=200)):
    """H8.1b — search/list the named-entity store (+ stats)."""
    orch = get_orch()
    if not orch or not getattr(orch, "entities", None):
        return nocache_json({"entities": [], "stats": {}, "error": "entity store not available"})
    return nocache_json({
        "entities": orch.entities.search(q, type, limit),
        "stats": orch.entities.stats(),
    })


# ── H8.3b Agentic RAG tool (LLM-callable search_memory over structured stores) ─

def _structured_recall(query: str, top_k: int = 5) -> list:
    """Offline recall over the structured memory stores (entities + KG)."""
    hits: list[dict] = []
    orch = get_orch()
    if not orch:
        return hits
    q = (query or "").strip()
    ents = getattr(orch, "entities", None)
    if ents is not None:
        for e in ents.search(q, limit=top_k):
            hits.append({"source": "entity", "text": e["name"], "type": e.get("type", ""),
                         "score": e.get("mentions", 0)})
    g = getattr(getattr(orch, "memory", None), "graph", None)
    if g is not None:
        try:
            for node in g.search(q)[:top_k]:
                hits.append({"source": "graph", "text": node.get("name", ""),
                             "type": node.get("type", ""), "score": 1})
        except Exception:
            pass  # best-effort recall: a graph-search failure must not break the response
    return hits[:top_k]


@router.get("/api/memory/tool-spec")
async def memory_tool_spec():
    """H8.3b — the search_memory function-calling spec the model can invoke."""
    from agents.core.memory.rag_tool import TOOL_SPEC
    return nocache_json(TOOL_SPEC)


@router.post("/api/memory/search-tool", dependencies=[Depends(user_guard)])
async def memory_search_tool(req: Request):
    """H8.3b — a single search_memory tool call. Body: {query, top_k?}."""
    from agents.core.memory.rag_tool import MemorySearchTool
    try:
        body = await req.json()
    except Exception:
        body = {}
    query = (body or {}).get("query", "")
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    try:
        top_k = int(body.get("top_k", 5))
    except (TypeError, ValueError):
        top_k = 5
    tool = MemorySearchTool(_structured_recall)
    # SEC-B5: the tool marks the origin itself when a hit is tainted; the scope
    # bounds that mark to this handler by design (see _recall_scope).
    async with _recall_scope():
        # _structured_recall hits the graph (a blocking neo4j call on the neo4j
        # backend) — run the whole sync tool call in a worker thread. The mark is
        # raised inside the worker; to_thread copies the context *into* the worker,
        # so it would not reach this handler — re-derive it here from the hits.
        result = await _kg_call(tool.search, query, top_k)
        hits = result.get("hits") or []
        tainted = any(_hit_is_tainted(h) for h in hits)
        if tainted:
            mark_turn_recall_tainted()
        result["tainted"] = tainted
        result["action_origin"] = current_action_origin()
        return nocache_json(result)


def _hit_is_tainted(hit) -> bool:
    """The search-tool's own taint verdict for one flat hit (``rag_tool._hit_tainted``)."""
    from agents.core.memory.rag_tool import _hit_tainted
    return _hit_tainted(hit)


# ── H14.4 Decay-based forgetting (ACT-R activation + dependency-aware delete) ──

@router.get("/api/memory/decay/ranking", dependencies=[Depends(user_guard)])
async def memory_decay_ranking(limit: int = Query(100, ge=1, le=1000)):
    """Memory items ranked by ACT-R activation (recency + frequency)."""
    orch = get_orch()
    d = getattr(orch, "decay", None) if orch else None
    if d is None:
        return nocache_json({"ranking": []})
    # ranking() takes the store's threading.Lock once per item — off-loop.
    return nocache_json({"ranking": await _kg_call(d.ranking, limit=limit)})


@router.get("/api/memory/decay/candidates", dependencies=[Depends(user_guard)])
async def memory_decay_candidates(threshold: float = 0.0):
    """Items whose activation has decayed below *threshold* (forget candidates)."""
    orch = get_orch()
    d = getattr(orch, "decay", None) if orch else None
    if d is None:
        return nocache_json({"candidates": []})
    # forget_candidates() ranks up to 10k items under the store lock — off-loop.
    candidates = await _kg_call(d.forget_candidates, threshold)
    return nocache_json({"threshold": threshold, "candidates": candidates})


@router.post("/api/memory/decay/forget", dependencies=[Depends(user_guard)])
async def memory_decay_forget(req: Request):
    """Forget an item + its transitive dependents (anti-recontamination)."""
    _, d, err = require_component("decay", "decay memory not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    item_id = (body or {}).get("id", "")
    if not item_id:
        return JSONResponse({"error": "id required"}, status_code=400)
    # forget() deletes + rewrites the decay JSON file under the store lock.
    removed = await _kg_call(d.forget, item_id)
    if not removed:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True, "removed": removed})


# ── H12.3 Knowledge-graph editor (query / edit / delete entities + relations) ─

def _kg():
    """Return the live knowledge graph, or None."""
    orch = get_orch()
    if not orch or not getattr(orch, "memory", None):
        return None
    return getattr(orch.memory, "graph", None)


async def _kg_call(fn, *args, **kwargs):
    """Run a graph call in a worker thread.

    With KNOWLEDGE_GRAPH_BACKEND=neo4j every graph method is a blocking sync
    httpx request (5s probe / 10s query timeouts); inline it froze the whole
    event loop — and with it every other route — for the duration. The default
    in-memory backend is cheap, so the offload is negligible there.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


@router.get("/api/kg/entities", dependencies=[Depends(user_guard)])
async def kg_entities(q: str = "", limit: int = Query(100, ge=1, le=500)):
    """List (or search with ?q=) knowledge-graph entities."""
    g = _kg()
    if g is None:
        return nocache_json({"entities": [], "error": "graph not available"})
    entities = await _kg_call(g.search, q) if q else await _kg_call(g.list_entities, limit)
    return nocache_json({"entities": entities[:limit], "total": len(entities)})


@router.get("/api/kg/entities/{name}", dependencies=[Depends(user_guard)])
async def kg_entity(name: str):
    """Get one entity plus its relations."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    ent = await _kg_call(g.get_entity, name)
    if ent is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"entity": ent, "relations": await _kg_call(g.get_relations, name)})


@router.post("/api/kg/entities", dependencies=[Depends(user_guard)])
async def kg_upsert_entity(req: Request):
    """Create or update an entity (upsert). Body: {name, type, properties}."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = (body or {}).get("name", "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    entity_type = body.get("type") or "unknown"
    # AUD-12 (F11): the label is interpolated into Cypher — reject a non-identifier
    # type outright rather than let the graph coerce it (strict API contract).
    if not is_safe_kg_label(entity_type):
        return JSONResponse({"error": "invalid entity type"}, status_code=400)
    payload = {"op": "add_entity", "name": name, "type": entity_type}
    denied = _kg_contract_denial(payload)
    if denied is not None:
        return JSONResponse({"error": f"contract denied: {denied}"}, status_code=403)
    denied = _kg_kernel_denial(get_orch(), payload, req.headers.get("x-capability-token", ""))
    if denied is not None:
        return JSONResponse({"error": f"kernel denied: {denied}"}, status_code=403)
    ok = await _kg_call(g.add_entity, name, entity_type, body.get("properties") or {})
    return nocache_json({"ok": bool(ok), "entity": await _kg_call(g.get_entity, name)})


@router.delete("/api/kg/entities/{name}", dependencies=[Depends(user_guard)])
async def kg_delete_entity(name: str, req: Request = None):
    """Delete an entity and any relations that touch it."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    # req is None only for a direct (non-HTTP) call, e.g. a test — the kernel
    # helper mints its own operator token when none is presented (wave-4b).
    # Deny precedes the existence lookup so a halt doesn't leak whether the entity exists.
    token_id = req.headers.get("x-capability-token", "") if req is not None else ""
    payload = {"op": "delete_entity", "name": name}
    denied = _kg_contract_denial(payload)
    if denied is not None:
        return JSONResponse({"error": f"contract denied: {denied}"}, status_code=403)
    denied = _kg_kernel_denial(get_orch(), payload, token_id)
    if denied is not None:
        return JSONResponse({"error": f"kernel denied: {denied}"}, status_code=403)
    if not await _kg_call(g.delete_entity, name):
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True, "deleted": name})


@router.post("/api/kg/relations", dependencies=[Depends(user_guard)])
async def kg_add_relation(req: Request):
    """Create a relation. Body: {source, relation, target, properties}."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    source = (body or {}).get("source", "").strip()
    relation = (body or {}).get("relation", "").strip()
    target = (body or {}).get("target", "").strip()
    if not (source and relation and target):
        return JSONResponse({"error": "source, relation, target required"}, status_code=400)
    # AUD-12 (F11): the relationship type is interpolated into Cypher — reject a
    # non-identifier value outright (strict API contract).
    if not is_safe_kg_rel_type(relation):
        return JSONResponse({"error": "invalid relation type"}, status_code=400)
    payload = {"op": "add_relation", "source": source, "relation": relation, "target": target}
    denied = _kg_contract_denial(payload)
    if denied is not None:
        return JSONResponse({"error": f"contract denied: {denied}"}, status_code=403)
    denied = _kg_kernel_denial(get_orch(), payload, req.headers.get("x-capability-token", ""))
    if denied is not None:
        return JSONResponse({"error": f"kernel denied: {denied}"}, status_code=403)
    ok = await _kg_call(g.add_relation, source, relation, target, body.get("properties") or {})
    return nocache_json({"ok": bool(ok)})


@router.delete("/api/kg/relations", dependencies=[Depends(user_guard)])
async def kg_delete_relation(source: str, relation: str, target: str, req: Request = None):
    """Delete a specific relation (by source/relation/target)."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    # AUD-12 (F11): the relationship type is interpolated into Cypher (strict
    # API contract — reject rather than coerce a delete).
    if not is_safe_kg_rel_type(relation):
        return JSONResponse({"error": "invalid relation type"}, status_code=400)
    # req is None only for a direct (non-HTTP) call — see kg_delete_entity above.
    # Deny precedes the lookup so a halt doesn't leak whether the relation exists.
    token_id = req.headers.get("x-capability-token", "") if req is not None else ""
    payload = {"op": "delete_relation", "source": source, "relation": relation, "target": target}
    denied = _kg_contract_denial(payload)
    if denied is not None:
        return JSONResponse({"error": f"contract denied: {denied}"}, status_code=403)
    denied = _kg_kernel_denial(get_orch(), payload, token_id)
    if denied is not None:
        return JSONResponse({"error": f"kernel denied: {denied}"}, status_code=403)
    if not await _kg_call(g.delete_relation, source, relation, target):
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True})


# ── H14.1 Bi-temporal KG (valid-time + ingested-at; as-of recall) ─────────────

@router.post("/api/kg/facts", dependencies=[Depends(user_guard)])
async def kg_add_fact(req: Request):
    """Add a bi-temporal fact. Body: {subject, predicate, object, valid_from?,
    ingested_at?, multi?}. Single-valued predicates invalidate (not delete) a
    contradicting prior fact."""
    orch, bt, err = require_component("bitemporal", "bi-temporal KG not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    for k in ("subject", "predicate", "object"):
        if not (body or {}).get(k):
            return JSONResponse({"error": "subject, predicate, object required"}, status_code=400)
    payload = {"op": "add_fact", "subject": body["subject"], "predicate": body["predicate"]}
    denied = _kg_contract_denial(payload)
    if denied is not None:
        return JSONResponse({"error": f"contract denied: {denied}"}, status_code=403)
    denied = _kg_kernel_denial(orch, payload, req.headers.get("x-capability-token", ""))
    if denied is not None:
        return JSONResponse({"error": f"kernel denied: {denied}"}, status_code=403)
    # add_fact() holds the store lock across an atomic JSON file rewrite — off-loop.
    fact = await _kg_call(
        bt.add_fact,
        body["subject"], body["predicate"], body["object"],
        valid_from=body.get("valid_from"), ingested_at=body.get("ingested_at"),
        multi=bool(body.get("multi", False)),
    )
    return nocache_json({"ok": True, "fact": fact})


@router.get("/api/kg/facts/as-of", dependencies=[Depends(user_guard)])
async def kg_facts_as_of(at: Optional[float] = None, subject: str = "", predicate: str = ""):
    """Valid-time recall: facts true in the world at time `at` (default now)."""
    _, bt, err = require_component("bitemporal", "bi-temporal KG not available")
    if err is not None:
        return err
    # Store reads share the writer's threading.Lock — keep the wait off the loop.
    facts = await _kg_call(bt.as_of, at, subject, predicate)
    return nocache_json({"at": at, "facts": facts})


@router.get("/api/kg/facts/history", dependencies=[Depends(user_guard)])
async def kg_facts_history(subject: str, predicate: str = ""):
    """All versions (incl. invalidated) for a subject, oldest first."""
    _, bt, err = require_component("bitemporal", "bi-temporal KG not available")
    if err is not None:
        return err
    history = await _kg_call(bt.history, subject, predicate)
    return nocache_json({"subject": subject, "history": history})


@router.post("/api/kg/ingest", dependencies=[Depends(user_guard)])
async def kg_ingest(req: Request):
    """H12.6 — extract triples from text and write them to the KG immediately."""
    orch, updater, err = require_component("kg_updater", "incremental KG not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body or {}).get("text", "")
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    payload = {"op": "ingest", "text_len": len(text)}
    denied = _kg_contract_denial(payload)
    if denied is not None:
        return JSONResponse({"error": f"contract denied: {denied}"}, status_code=403)
    denied = _kg_kernel_denial(orch, payload, req.headers.get("x-capability-token", ""))
    if denied is not None:
        return JSONResponse({"error": f"kernel denied: {denied}"}, status_code=403)
    count = await _kg_call(updater.ingest, text)
    return nocache_json({"ok": True, "added": count, "triples": updater.last_added})


@router.get("/api/memory/eval/corpus")
async def memory_eval_corpus():
    """H14.2 — the owned memory-eval corpus (cases across 5 abilities)."""
    from agents.core.memory.eval import DEFAULT_CORPUS, ABILITIES
    return nocache_json({
        "abilities": ABILITIES,
        "cases": [c.to_dict() for c in DEFAULT_CORPUS],
    })


@router.post("/api/memory/eval/run", dependencies=[Depends(user_guard)])
async def memory_eval_run(mode: str = "keyword"):
    """H14.2 — run the memory eval harness."""
    from agents.core.memory.eval import run_eval, keyword_answer, run_recall_eval
    mode = (mode or "keyword").strip().lower()
    if mode == "keyword":
        return nocache_json(run_eval(keyword_answer))
    if mode == "recall":
        return nocache_json(await run_recall_eval())
    return JSONResponse({"error": "mode must be keyword or recall"}, status_code=400)


@router.post("/api/memory/remember", dependencies=[Depends(user_guard)])
async def memory_remember(req: Request):
    """Store a fact in long-term memory with a real embedding, for later recall."""
    orch = get_orch()
    if not orch or not orch.memory:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body or {}).get("text", "")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    metadata = (body or {}).get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    rid = await orch.memory.remember(text, metadata=metadata)
    return nocache_json({"ok": rid is not None, "id": rid})


@router.get("/api/memory/recall", dependencies=[Depends(user_guard)])
async def recall_memory(q: str = ""):
    """Search the structured memory store by query string.

    CDX-7: an injection-flagged value is redacted; SEC-B5: such a row raises the
    scoped ``action_origin`` and the response reports it.
    """
    from agents.core.memory.store import MemoryStore
    if not q:
        return {"results": [], "tainted": False}
    async with _recall_scope():
        store = await asyncio.to_thread(MemoryStore)  # opens SQLite (WAL) — off-loop
        rows = await store.search(q, limit=20)
        results = [_guard_store_row(r) for r in rows]
        tainted = _mark_if_tainted(results)
        return {"results": results, "query": q, "tainted": tainted,
                "action_origin": current_action_origin()}
