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

Scoping — stated precisely, because the boundaries differ:

* **Chat/tool turns** (``Orchestrator.handle_input`` and its prepared path) bind a
  turn origin and reset it in ``finally``. The mark is set without keeping its own
  reset token, so that reset restores the pre-turn value.
* **One-shot ``Orchestrator.process``** delegates to ``process_detailed``. That method
  binds the entry origin around media-history inspection and agent execution, then
  resets in ``finally``. A recalled untrusted hit is therefore visible while the
  internal call runs, and an inherited untrusted origin is retained. The current
  scope also restores a clean entry origin before returned text reaches its caller;
  whether that is the intended boundary for callers that may act on the returned text
  is a separate authority decision, not settled by this helper.
* **HTTP memory routes** use ``routers/memory_kg.py``'s ``_recall_scope`` async
  context manager. It binds on handler entry and resets in ``finally`` after the
  response is built. This explicit boundary also works when a test awaits the route
  directly, without relying on asyncio Task-context isolation.

These scopes belong to their callers; this module's marker remains escalate-only and
does not own a reset token. See the orchestrator and route regressions for the
boundaries currently enforced.
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
