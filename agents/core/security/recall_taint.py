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

Residual, recorded rather than papered over: making the second path scope the mark
explicitly — binding and resetting around the search instead of relying on Task
isolation — is the remaining hardening. It is not done here.
"""

from __future__ import annotations

from ..action_origin import bind_action_origin, current_action_origin
from .taint import TAINTED_RECALL_ORIGIN, is_untrusted_source


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
