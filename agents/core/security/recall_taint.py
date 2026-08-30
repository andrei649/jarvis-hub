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

Turn-scoped by construction: the mark is set *without* keeping a reset token, so the
turn's own ``reset_action_origin`` (bound in ``Orchestrator.handle_input``) restores
the pre-turn value. The mark can never outlive the turn that raised it.
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
