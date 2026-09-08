"""
rag_tool.py — H8.3b Agentic RAG Tool (extends H8.3).

Recall stops being a fixed top-k injection and becomes an LLM-callable tool:
``search_memory(query, top_k)``. The model decides *when* and *how* to search and
may **retry with a different query** if the first results are weak. This module
provides the tool wrapper, its function-calling spec, and an agentic loop driven
by an injected planner (the LLM in production, a scripted fake in tests).

Hermes absorption 5a — the same tool is registered on the ToolRPC seam
(:func:`register_search_memory`) so the model can call it from the tool loop, over the
fused recall of the live memory manager. The tool result carries an explicit
``"tainted"`` key rather than relying on the turn-scoped taint mark alone: the tool
loop runs every handler in a child asyncio Task, which gets a *copy* of the turn's
context, so a ContextVar raised inside the handler never reaches the turn that reads
the result. The loop fences the result and marks the turn itself when it sees
``"tainted": True``. That fence is escalate-only — a tainted hit can raise the turn's
action origin to the untrusted-recall label, never lower a more specific one — and a
per-hit redaction already applied here is never undone downstream.

On this seam a hit is shipped once, bounded, and stripped to what the verdict needs:
the body lives only in the hit's text field (capped at ``MAX_HIT_TEXT_CHARS``), so a
redaction cannot be defeated by the same body riding along under ``metadata``; and the
metadata forwarded to the model is an allowlist (``FORWARDED_METADATA_KEYS``) — the taint
mark, its source, the timestamp and the type — so an arbitrary store field can neither
carry instructions the scanner never saw nor bulk that pushes the result past the
loop's byte envelope.
"""

from __future__ import annotations

import inspect
import logging
import math
from typing import Any, Callable

from ..security import quarantine, taint
from ..security.rag_guard import DEFAULT_SNIPPET_CAP, REDACTION, provenance_from_hit
from ..security.recall_taint import mark_turn_recall_tainted
from ..tool_rpc import ToolRPCValidationError

logger = logging.getLogger("jarvis.rag_tool")

# Hermes absorption 5a — the ToolRPC face of search_memory.
TOOL_NAME = "search_memory"
CAPABILITY_ID = "tool:search_memory"
MAX_QUERY_CHARS = 512
DEFAULT_TOP_K = 5
MAX_TOP_K = 50          # the clamp MemorySearchTool.search has always applied
DEFAULT_SOURCE = "memory"
# Per-hit text cap on the tool seam — the same bound the prompt-string recall path
# applies per snippet, so one oversized record cannot crowd out every other hit.
MAX_HIT_TEXT_CHARS = DEFAULT_SNIPPET_CAP
# The only metadata keys a flattened hit carries to the model: what the taint verdict
# and provenance need. Text-bearing keys are deliberately absent (the body is shipped
# once, in the text field, where it is scanned and redacted).
FORWARDED_METADATA_KEYS = frozenset({taint.TAINT_KEY, "taint_source", "created_at", "type", "source"})
# The fields a hit's body may sit under; both are scanned, never one guessed.
_TEXT_FIELDS = ("text", "name")
# The dicts a hit's taint mark may sit under.
_MARK_FIELDS = ("metadata", "properties")

# Function-calling schema exposed to the model.
TOOL_SPEC = {
    "name": "search_memory",
    "description": (
        "Search the user's long-term memory (facts, entities, knowledge graph). "
        "Call this when you need information you weren't given. You may call it "
        "multiple times with refined queries if the first results are insufficient."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look up."},
            "top_k": {"type": "integer", "description": "Max results (default 5)."},
        },
        "required": ["query"],
    },
}

# recall_fn(query, top_k) -> list[dict] (each hit: {"text"/"name", "score", ...})
RecallFn = Callable[[str, int], list]
# planner(query, history) -> {"action": "search"|"answer", "query"?: str, "answer"?: str}
PlannerFn = Callable[[str, list], dict]


from agents.core.memory.recall_admission import (
    RecallAdmission,
    admit,
    reject,
    summarise,
)


def _sanitize_hit(hit: dict) -> dict:
    """CDX-7 follow-up: scan a retrieved hit and **redact** it if the injection
    scanner flags it. Retrieved memory is untrusted data — a stored string (or one
    synced from an untrusted feed into the graph) could carry "ignore previous
    instructions…" that the model would otherwise read straight out of the
    ``search_memory`` tool result. The prompt-string recall sites are fenced by
    ``rag_guard.wrap_memory``; this is the dict-shaped tool path it deferred.

    Clean hits pass through unchanged (same object). A flagged hit keeps its score
    and metadata but its text is replaced by the redaction marker and tagged
    ``injection_flagged`` so the model/UI sees *that* something matched without
    reading the injected instructions.

    Hermes absorption 5a: both ``text`` and ``name`` are scanned when present (a hit
    that carries an empty ``text`` next to an injected ``name`` used to slip past by
    the presence of the empty key), a non-string value in either is left alone rather
    than crashing the scanner, and a redaction also blanks the same fields inside the
    hit's ``metadata`` / ``properties`` so the body is not shipped a second time there.
    """
    if not isinstance(hit, dict):
        return hit
    flags: list[str] = []
    flagged: list[str] = []
    for field in _TEXT_FIELDS:
        value = hit.get(field)
        if isinstance(value, str) and value:
            found = quarantine.detect_injection(value)
            if found:
                flags.extend(found)
                flagged.append(field)
    if not flags:
        return hit
    out = dict(hit)
    for field in flagged:
        out[field] = REDACTION
    for mark_field in _MARK_FIELDS:
        md = out.get(mark_field)
        if isinstance(md, dict) and any(f in md for f in _TEXT_FIELDS):
            out[mark_field] = {k: (REDACTION if k in _TEXT_FIELDS else v) for k, v in md.items()}
    out["injection_flagged"] = True
    out["flags"] = flags
    return out


def _hit_tainted(hit) -> bool:
    """SEC-B5: does this hit carry recall taint — an upstream taint mark, an untrusted
    source label, or the injection flag ``_sanitize_hit`` just set?

    This path renders no fenced block, so it cannot read ``WrappedMemory.tainted``; this
    is the same verdict computed on one un-fenced hit. The flat hits this tool receives
    key their provenance as ``source``, while the fused-hit shape ``provenance_from_hit``
    adapts uses ``sources`` — so both are consulted rather than one guessed.
    """
    if not isinstance(hit, dict):
        return False
    if hit.get("injection_flagged") or taint.is_tainted(hit):
        return True
    if any(taint.is_tainted(hit.get(f)) for f in _MARK_FIELDS):
        return True
    source = hit.get("source")
    if source is not None and not isinstance(source, str):
        # a malformed source is no reason to crash the verdict: its rendering is
        # substring-matched like any label, so an untrusted name inside a list or
        # other shape still counts (never guessed "clean")
        source = str(source)
    return taint.is_untrusted_source(source or provenance_from_hit(hit).source)



def _admission_for(hit) -> RecallAdmission:
    """Which admission reason this hit's existing verdicts amount to.

    Order matters and is not arbitrary: a hit that is BOTH tainted and redacted
    is recorded as ``rejected_taint``, because taint is why it was withheld and
    redaction is how. Recording the "how" would say what happened to the text
    while leaving the reason — the part a person acts on — unstated.
    """
    if _hit_tainted(hit):
        return reject(hit, "rejected_taint", "untrusted source or injection flag")
    if isinstance(hit, dict) and hit.get("injection_flagged"):
        # Flagged but not tainted: the text was redacted, and the hit itself is
        # still used. `redacted` says so rather than the reason pretending it was
        # withheld.
        return admit(hit, redacted=True)
    return admit(hit)


class MemorySearchTool:
    """Wraps a recall function as the callable `search_memory` tool."""

    def __init__(self, recall_fn: RecallFn, *, scan: bool = True) -> None:
        self._recall = recall_fn
        # CDX-7 follow-up: scan retrieved hits for injection and redact flagged
        # ones before they reach the model. On by default; off only for callers
        # that have already sanitized upstream.
        self._scan = scan
        self.calls: list[dict] = []

    @property
    def spec(self) -> dict:
        return dict(TOOL_SPEC)

    def search(self, query: str, top_k: int = 5) -> dict:
        query = (query or "").strip()
        top_k = max(1, min(int(top_k or 5), 50))
        if not query:
            return {"query": "", "hits": [], "count": 0}
        try:
            hits = list(self._recall(query, top_k) or [])
        except Exception:
            hits = []
        hits = hits[:top_k]
        if self._scan:
            hits = [_sanitize_hit(h) for h in hits]
        if any(_hit_tainted(h) for h in hits):
            # SEC-B5: the model is about to read untrusted recalled memory — same
            # turn-scoped escalation the prompt-string recall path raises.
            mark_turn_recall_tainted()

        # E3.2 — record WHY each hit was let in or held back. Evaluation-only:
        # this admits nothing that was not already admitted and blocks nothing
        # that was not already blocked; it names the decision the rules above
        # just made. Without it a redacted hit is invisible, and "why did Nerva
        # not use the thing I told it" has no answer at all.
        admissions = [_admission_for(h) for h in hits]
        self.calls.append({"query": query, "count": len(hits)})
        return {
            "query": query,
            "hits": hits,
            "count": len(hits),
            "admissions": [a.as_dict() for a in admissions],
            "admission_summary": summarise(admissions),
        }


def agentic_search(
    query: str,
    tool: MemorySearchTool,
    planner: PlannerFn,
    max_iters: int = 3,
) -> dict:
    """Agentic recall loop: search → let the planner refine or answer.

    The planner sees the running history of (query, hits) and returns either
    {"action": "answer", "answer": ...} to stop, or {"action": "search",
    "query": <refined>} to retry. Capped at *max_iters* searches.
    """
    history: list[dict] = []
    queries: list[str] = []
    all_hits: list = []
    current = query

    for i in range(max(1, max_iters)):
        result = tool.search(current)
        queries.append(result["query"])
        all_hits.extend(result["hits"])
        history.append({"query": result["query"], "hits": result["hits"]})

        decision = planner(current, history) or {}
        if decision.get("action") == "answer":
            return {
                "answer": decision.get("answer", ""),
                "iterations": i + 1,
                "queries": queries,
                "hits": all_hits,
                "stopped": "answered",
            }
        # refine query for the next iteration (fall back to same query)
        current = decision.get("query") or current

    return {
        "answer": "",
        "iterations": max(1, max_iters),
        "queries": queries,
        "hits": all_hits,
        "stopped": "max_iters",
    }


# ── Hermes absorption 5a: the ToolRPC seam ───────────────────────────────────

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_CHARS},
        "top_k": {"type": "integer", "minimum": 1, "maximum": MAX_TOP_K},
    },
    "required": ["query"],
    "additionalProperties": False,
}

# The sentence the model reads must say what the tool does: an untrusted-source hit is
# delivered but marked tainted (and the loop fences the whole result as data); only an
# injection-flagged hit has its text redacted.
DESCRIPTION = (
    TOOL_SPEC["description"]
    + " Hits are the owner's own memory; a hit from an untrusted source is delivered but "
    "marked tainted, a hit the injection scanner flagged is redacted, and the result "
    "says so."
)


def preflight(args: dict) -> dict:
    """Shape check for the ToolRPC seam: a bounded non-empty query and a top_k inside
    the clamp. Unknown keys are dropped so nothing the model invents reaches recall.
    A bool is refused as top_k because it is an int to ``isinstance`` and would read
    as 1 or 0 — a silent shape change rather than a named refusal."""
    query = (args or {}).get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ToolRPCValidationError("bad_args")
    clean: dict[str, Any] = {"query": query.strip(), "top_k": DEFAULT_TOP_K}
    if "top_k" in args:
        top_k = args["top_k"]
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            raise ToolRPCValidationError("bad_args")
        clean["top_k"] = top_k
    return clean


def flatten_hit(hit: Any) -> dict | None:
    """Adapt one recall hit — a ``fusion.FusedHit``, any object with ``payload`` /
    ``score`` / ``sources``, or an already-flat dict — to the flat dict
    :class:`MemorySearchTool` scans and the model reads.

    The text and source rules are those of ``rag_guard.provenance_from_hit`` so the
    prompt-string recall path and this tool path agree on what a hit says and where
    it came from; in particular ``taint_source`` wins as the source when the metadata
    is tainted, so an untrusted origin is never hidden behind the store it landed in.
    The taint mark survives flattening — from ``metadata``, ``properties`` or the payload
    itself, whichever carries it — so ``_hit_tainted`` can see it; the rest of the
    metadata is reduced to ``FORWARDED_METADATA_KEYS`` and the body is shipped once, in
    the text field, capped at ``MAX_HIT_TEXT_CHARS``. A cut is scanned on the *full*
    text first so a body whose instructions sit past the cap is still redacted and
    declared, never silently trimmed to clean. A non-finite score becomes None (one
    NaN would void the whole tool result downstream). Returns None for a hit with no
    text or a malformed input; never raises.
    """
    try:
        if isinstance(hit, dict) and "payload" not in hit and not hasattr(hit, "payload"):
            return _flatten_flat_dict(hit)
        payload = getattr(hit, "payload", None)
        if payload is None and isinstance(hit, dict):
            payload = hit.get("payload")
        if not isinstance(payload, dict):
            return None
        md = payload.get("metadata") or payload.get("properties") or {}
        if not isinstance(md, dict):
            md = {}
        text = payload.get("text") or md.get("text") or payload.get("name") or md.get("name")
        if not isinstance(text, str) or not text:
            return None
        sources = getattr(hit, "sources", None)
        if sources is None and isinstance(hit, dict):
            sources = hit.get("sources")
        sources = [str(x) for x in sources if x] if isinstance(sources, (list, tuple)) else []
        source = sources[0] if sources else DEFAULT_SOURCE
        # a mark on any of the dicts a hit is made of counts; the merged view is what
        # the model sees, so the mark is carried rather than dropped by the pick above
        marks = [d for d in (md, payload.get("properties"), payload.get("metadata"), payload)
                 if taint.is_tainted(d)]
        md_out = _forwarded_metadata(md)
        if marks:
            taint_source = next((str(d["taint_source"]) for d in marks if d.get("taint_source")), None)
            md_out = taint.mark(md_out, source=taint_source)
            if taint_source:
                source = taint_source
        score = getattr(hit, "score", None)
        if score is None and isinstance(hit, dict):
            score = hit.get("score")
        hit_id = getattr(hit, "id", None)
        if hit_id is None and isinstance(hit, dict):
            hit_id = hit.get("id")
        out: dict[str, Any] = {
            "id": str(hit_id) if hit_id is not None else None,
            "text": text,
            "score": _finite_score(score),
            "source": source,
            "sources": sources,
            "metadata": md_out,
        }
        kind = payload.get("type") or md.get("type")
        if kind is not None:
            out["type"] = kind
        _cap_text(out, "text")
        return out
    except Exception:
        return None


def _flatten_flat_dict(hit: dict) -> dict | None:
    """The already-flat shape: a copy that keeps its keys, with the body field
    normalised so the scanner reads what the model will read. A non-string body is
    malformed (None); a non-string source is stringified rather than crashing the
    taint verdict; ``metadata`` / ``properties`` are reduced to the forwarded keys with
    any taint mark kept; the body is capped like every other hit."""
    field = next((f for f in _TEXT_FIELDS if hit.get(f)), None)
    if field is None or not isinstance(hit.get(field), str):
        return None
    out = dict(hit)
    if field == "name" and "text" in out:
        # an empty/None "text" next to the real body under "name" — drop the decoy so
        # the body is the field that gets scanned, redacted and capped
        out.pop("text")
    src = out.get("source")
    if src is not None and not isinstance(src, str):
        out["source"] = str(src)
    for mark_field in _MARK_FIELDS:
        md = out.get(mark_field)
        if isinstance(md, dict):
            out[mark_field] = _forwarded_metadata(md)
            # the same rule as the fused path: a taint source names where the body
            # came from, and it wins over a store label that would hide the origin
            if taint.is_tainted(md) and md.get("taint_source"):
                out["source"] = str(md["taint_source"])
    if "score" in out and isinstance(out["score"], float) and not math.isfinite(out["score"]):
        out["score"] = None
    _cap_text(out, field)
    return out


def _forwarded_metadata(md: dict) -> dict:
    """Only the allowlisted keys reach the model; a taint mark is never dropped."""
    out = {k: v for k, v in md.items() if k in FORWARDED_METADATA_KEYS}
    if taint.is_tainted(md):
        out = taint.mark(out, source=md.get("taint_source"))
    return out


def _finite_score(score: Any) -> float | None:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    value = float(score)
    return value if math.isfinite(value) else None


def _cap_text(out: dict, field: str) -> None:
    """Bound the body in place. The full text is scanned before the cut so a flag that
    sits past the cap still redacts and declares the hit — escalate-only: a cut can
    shorten a clean body, never launder a flagged one."""
    text = out.get(field)
    if not isinstance(text, str) or len(text) <= MAX_HIT_TEXT_CHARS:
        return
    flags = quarantine.detect_injection(text)
    out[field] = text[:MAX_HIT_TEXT_CHARS]
    out["truncated"] = True
    if flags:
        out[field] = REDACTION
        out["injection_flagged"] = True
        out["flags"] = flags


def register_search_memory(server: Any, recall_getter: Callable[[], Any], *, scan: bool = True) -> str:
    """Expose ``search_memory`` on a ToolRPC server, over whatever recall the getter
    returns at call time (the live memory manager's fused recall, sync or async).

    Ungated: it reads what the owner already can. Not declared ``untrusted_output``
    either — memory is the owner's own data; what is untrusted is one *hit*, and that
    verdict is per hit and declared through ``"tainted"`` on the result. The handler
    never raises: no recall, or a recall that fails, is a short named reason.
    """

    async def _handle(args: dict) -> dict:
        query = str(args.get("query") or "")
        top_k = int(args.get("top_k") or DEFAULT_TOP_K)
        try:
            recall = recall_getter()
        except Exception as exc:
            logger.warning("search_memory recall getter failed: %s", type(exc).__name__)
            recall = None
        if not callable(recall):
            return {"ok": False, "reason": "recall_unavailable"}
        try:
            raw = recall(query, top_k)
            if inspect.isawaitable(raw):
                raw = await raw
            raw = list(raw or [])[:top_k]
        except Exception as exc:
            logger.warning("search_memory recall failed: %s", type(exc).__name__)
            return {"ok": False, "reason": "recall_failed"}
        hits = [h for h in (flatten_hit(x) for x in raw) if h]
        tool = MemorySearchTool(lambda _q, _k: hits, scan=scan)
        try:
            result = tool.search(query, top_k)
            result["tainted"] = any(_hit_tainted(h) for h in result.get("hits") or [])
        except Exception as exc:
            # the scan/verdict never leaks a traceback to the model: a named refusal,
            # and nothing from the hits is delivered
            logger.warning("search_memory scan failed: %s", type(exc).__name__)
            return {"ok": False, "reason": "scan_failed"}
        return result

    server.register_tool(
        TOOL_NAME,
        _handle,
        gated=False,
        description=DESCRIPTION,
        input_schema=INPUT_SCHEMA,
        capability_id=CAPABILITY_ID,
        preflight=preflight,
    )
    return TOOL_NAME
