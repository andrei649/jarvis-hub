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
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse

from agents.core.automation_contracts import ContractTemplate, contract_denial, predicate
from agents.core.routers._deps import user_guard

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


# ── H14.3 Sleep-time memory consolidation ─────────────────────────────────────

@router.post("/api/memory/consolidate", dependencies=[Depends(user_guard)])
async def memory_consolidate(req: Request):
    """Plan Mem0-style consolidation ops (ADD/UPDATE/DELETE/NOOP) for candidates
    against existing memories. Returns a reversible plan (no mutation)."""
    orch = get_orch()
    eng = getattr(orch, "consolidation", None) if orch else None
    if eng is None:
        return JSONResponse({"error": "consolidation not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    candidates = (body or {}).get("candidates") or []
    if not candidates:
        return JSONResponse({"error": "candidates required"}, status_code=400)

    # plan() is O(candidates × existing) similarity over caller-supplied text —
    # keep that CPU off the event loop.
    existing = (body or {}).get("existing") or []

    def _plan():
        p = eng.plan(candidates, existing)
        return p, eng.summarize(p)

    plan, summary = await asyncio.to_thread(_plan)
    return nocache_json({"plan": plan, "summary": summary})


@router.get("/api/memory/search", dependencies=[Depends(user_guard)])
async def memory_search(q: str = "", top_k: int = 10):
    """Fused recall via RRF: vector similarity + knowledge-graph (H5.14 Task 4)."""
    orch = get_orch()
    top_k = max(1, min(top_k, 50))
    if not orch or not orch.memory:
        return nocache_json({"results": [], "query": q, "total": 0})
    try:
        # Real semantic recall: embed the query so the vector arm of fused recall
        # actually contributes (degrades to keyword/graph-only if embedding fails).
        embedding = await orch.memory.embed(q) if q and hasattr(orch.memory, "embed") else None
        hits = await orch.memory.hybrid_search(
            embedding=embedding, keyword=q or None, top_k=top_k
        )
        return nocache_json({
            "results": [
                {
                    "id": h.id,
                    "score": round(h.score, 4),
                    "sources": h.sources,
                    "payload": h.payload,
                }
                for h in hits
            ],
            "query": q,
            "total": len(hits),
        })
    except Exception as e:
        return error_json(e, 200, "memory search failed", extra={"results": [], "query": q, "total": 0})


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
    # search() runs _structured_recall, which hits the live graph — sync HTTP
    # under the Neo4j backend — so it must not run on the loop.
    return nocache_json(await asyncio.to_thread(tool.search, query, top_k))


# ── H14.4 Decay-based forgetting (ACT-R activation + dependency-aware delete) ──

@router.get("/api/memory/decay/ranking", dependencies=[Depends(user_guard)])
async def memory_decay_ranking(limit: int = Query(100, ge=1, le=1000)):
    """Memory items ranked by ACT-R activation (recency + frequency)."""
    orch = get_orch()
    d = getattr(orch, "decay", None) if orch else None
    if d is None:
        return nocache_json({"ranking": []})
    # ranking() takes the store's threading.Lock once per item — off-loop.
    return nocache_json({"ranking": await asyncio.to_thread(d.ranking, limit=limit)})


@router.get("/api/memory/decay/candidates", dependencies=[Depends(user_guard)])
async def memory_decay_candidates(threshold: float = 0.0):
    """Items whose activation has decayed below *threshold* (forget candidates)."""
    orch = get_orch()
    d = getattr(orch, "decay", None) if orch else None
    if d is None:
        return nocache_json({"candidates": []})
    # forget_candidates() ranks up to 10k items under the store lock — off-loop.
    candidates = await asyncio.to_thread(d.forget_candidates, threshold)
    return nocache_json({"threshold": threshold, "candidates": candidates})


@router.post("/api/memory/decay/forget", dependencies=[Depends(user_guard)])
async def memory_decay_forget(req: Request):
    """Forget an item + its transitive dependents (anti-recontamination)."""
    orch = get_orch()
    d = getattr(orch, "decay", None) if orch else None
    if d is None:
        return JSONResponse({"error": "decay memory not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    item_id = (body or {}).get("id", "")
    if not item_id:
        return JSONResponse({"error": "id required"}, status_code=400)
    # forget() deletes + rewrites the decay JSON file under the store lock.
    removed = await asyncio.to_thread(d.forget, item_id)
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


@router.get("/api/kg/entities", dependencies=[Depends(user_guard)])
async def kg_entities(q: str = "", limit: int = Query(100, ge=1, le=500)):
    """List (or search with ?q=) knowledge-graph entities."""
    g = _kg()
    if g is None:
        return nocache_json({"entities": [], "error": "graph not available"})
    # The graph may be Neo4jGraph: every op is a blocking HTTP transaction
    # (httpx.Client, 5–10s timeouts) that must stay off the event loop.
    if q:
        entities = await asyncio.to_thread(g.search, q)
    else:
        entities = await asyncio.to_thread(g.list_entities, limit)
    return nocache_json({"entities": entities[:limit], "total": len(entities)})


@router.get("/api/kg/entities/{name}", dependencies=[Depends(user_guard)])
async def kg_entity(name: str):
    """Get one entity plus its relations."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    ent = await asyncio.to_thread(g.get_entity, name)
    if ent is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"entity": ent,
                         "relations": await asyncio.to_thread(g.get_relations, name)})


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
    ok = await asyncio.to_thread(g.add_entity, name, entity_type, body.get("properties") or {})
    return nocache_json({"ok": bool(ok), "entity": await asyncio.to_thread(g.get_entity, name)})


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
    if not await asyncio.to_thread(g.delete_entity, name):
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
    ok = await asyncio.to_thread(
        g.add_relation, source, relation, target, body.get("properties") or {})
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
    if not await asyncio.to_thread(g.delete_relation, source, relation, target):
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True})


# ── H14.1 Bi-temporal KG (valid-time + ingested-at; as-of recall) ─────────────

@router.post("/api/kg/facts", dependencies=[Depends(user_guard)])
async def kg_add_fact(req: Request):
    """Add a bi-temporal fact. Body: {subject, predicate, object, valid_from?,
    ingested_at?, multi?}. Single-valued predicates invalidate (not delete) a
    contradicting prior fact."""
    orch = get_orch()
    bt = getattr(orch, "bitemporal", None) if orch else None
    if bt is None:
        return JSONResponse({"error": "bi-temporal KG not available"}, status_code=503)
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
    fact = await asyncio.to_thread(
        bt.add_fact,
        body["subject"], body["predicate"], body["object"],
        valid_from=body.get("valid_from"), ingested_at=body.get("ingested_at"),
        multi=bool(body.get("multi", False)),
    )
    return nocache_json({"ok": True, "fact": fact})


@router.get("/api/kg/facts/as-of", dependencies=[Depends(user_guard)])
async def kg_facts_as_of(at: Optional[float] = None, subject: str = "", predicate: str = ""):
    """Valid-time recall: facts true in the world at time `at` (default now)."""
    orch = get_orch()
    bt = getattr(orch, "bitemporal", None) if orch else None
    if bt is None:
        return JSONResponse({"error": "bi-temporal KG not available"}, status_code=503)
    # Store reads share the writer's threading.Lock — keep the wait off the loop.
    return nocache_json({"at": at, "facts": await asyncio.to_thread(bt.as_of, at, subject, predicate)})


@router.get("/api/kg/facts/history", dependencies=[Depends(user_guard)])
async def kg_facts_history(subject: str, predicate: str = ""):
    """All versions (incl. invalidated) for a subject, oldest first."""
    orch = get_orch()
    bt = getattr(orch, "bitemporal", None) if orch else None
    if bt is None:
        return JSONResponse({"error": "bi-temporal KG not available"}, status_code=503)
    return nocache_json({"subject": subject,
                         "history": await asyncio.to_thread(bt.history, subject, predicate)})


@router.post("/api/kg/ingest", dependencies=[Depends(user_guard)])
async def kg_ingest(req: Request):
    """H12.6 — extract triples from text and write them to the KG immediately."""
    orch = get_orch()
    updater = getattr(orch, "kg_updater", None) if orch else None
    if updater is None:
        return JSONResponse({"error": "incremental KG not available"}, status_code=503)
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
    # ingest() extracts triples, then writes the graph (blocking HTTP under
    # Neo4j) and bi-temporal facts (file rewrite per fact) — off-loop.
    count = await asyncio.to_thread(updater.ingest, text)
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
    """Search memory store by query string."""
    from agents.core.memory.store import MemoryStore
    store = MemoryStore()
    if not q:
        return {"results": []}
    results = await store.search(q, limit=20)
    return {"results": results, "query": q}
