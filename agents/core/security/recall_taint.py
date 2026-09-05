"""recall_taint.py — SEC-B5: carry a tainted RECALL into the turn's action provenance.

Recall is an **ingress**. A snippet pulled from an untrusted source — or one the
injection scanner flagged — becomes part of the prompt the model answers from, so an
action that turn emits is derived from untrusted material even when the turn's own
channel is trusted. Until now ``rag_guard.WrappedMemory.tainted`` was computed and
then dropped, so such an action reached the kernel with a clean "generated" origin.

Taint still cannot be traced *through* the model (it launders content — see
``taint.py`` and the kernel's step-3b note); what is carried here is the honest, coarse
fact that **this turn read untrusted memory**. The vehicle is the existing per-turn
``action_origin`` ContextVar: every kernel-mediated broker already tags
``Action.origin`` from it, and the kernel escalates an untrusted origin from GRANT to
QUEUE. So a recall-tainted turn's actions land in the approval inbox instead of
auto-executing — fail safe, never a DENY, never a weakened gate.

Scoping — stated precisely, because two different mechanisms are doing the work and
only one of them is a turn:

* **Chat/tool turns** (``Orchestrator.handle_input``, orchestrator.py:1167 and :1324)
  bind a turn origin and reset it in a ``finally``. The mark is set *without* keeping
  its own reset token, so that reset restores the pre-turn value. Here the mark is
  genuinely turn-scoped.
* **The HTTP recall route** (``routers/memory_kg.py`` builds a ``MemorySearchTool``)
  has no turn at all. What bounds the mark there is asyncio's per-task context copy:
  the handler runs in its own Task, so a ``ContextVar`` set inside it never propagates
  back to the parent context and dies with the request.

The second is real isolation but it is incidental, not designed — it holds because of
how Tasks copy context, not because anything in this module arranges it. A synchronous
caller reaching the marking path outside a Task would leak the mark for the life of its
context. No production caller does that today (the only two are listed above), and the
autouse fixture in ``tests/conftest.py`` restores the binding around every test so a
pytest worker running many files in one context cannot carry a mark across a file.

That residual is now closed by ``bounded_recall_taint`` below, which the HTTP route wraps
its search in. Read its docstring for what it does and does not buy: it is deliberately a
no-op under today's implementation, and the whole point is that it stays correct under the
refactor that would otherwise break the incidental isolation.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from ..action_origin import (
    bind_action_origin,
    current_action_origin,
    reset_action_origin,
)
from .taint import TAINTED_RECALL_ORIGIN, is_untrusted_source


@contextmanager
def bounded_recall_taint() -> Iterator[None]:
    """Confine any recall taint mark raised inside this block to the block.

    For callers that recall memory **outside a turn** — today only the HTTP route
    ``POST /api/memory/search-tool`` — there is no turn ``finally`` to restore the
    ambient origin, so without this the mark's lifetime is whatever the caller's context
    happens to be.

    What it buys, stated precisely so nobody reads more into it. **Today it changes
    nothing**, and that is measurable: the route dispatches the sync tool through
    ``asyncio.to_thread``, which runs it in a *copy* of the context, so a mark raised in
    the worker thread is discarded when the copy dies and never reaches the request
    handler at all. Verified by probe: through ``to_thread`` the caller's origin is
    unchanged; called inline the caller's origin becomes ``recall:untrusted`` and stays
    that way.

    That second line is the point. The current safety is a property of the *dispatch
    mechanism*, not of this module — delete the offload (an easy call to make, since the
    default in-memory backend is cheap) and the mark starts escaping into the caller's
    context. This block makes the confinement a property of the code that recalls, so it
    survives that refactor. It binds the origin already in force, then resets to it on
    exit, discarding any escalation raised inside — including on an exception path.

    It is deliberately NOT used on the turn paths (``Orchestrator.handle_input``): there
    the mark is *supposed* to outlive the recall and reach ``kernel.authorize`` so the
    turn's actions escalate to QUEUE. Wrapping those would silently defeat SEC-B5's whole
    purpose. This is for recall with no action downstream of it.
    """
    token = bind_action_origin(current_action_origin())
    try:
        yield
    finally:
        reset_action_origin(token)


def mark_turn_recall_tainted() -> str:
    """Raise this turn's action origin to the tainted-recall label; return the origin in force.

    Escalate-only: an already-untrusted origin (an inbound channel, a worldview feed)
    keeps its more specific label rather than being overwritten by this coarser one.
    """
    origin = current_action_origin()
    if is_untrusted_source(origin):
        return origin
    bind_action_origin(TAINTED_RECALL_ORIGIN)   # token dropped: the turn's own reset scopes it
    return TAINTED_RECALL_ORIGIN
