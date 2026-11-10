"""Per-call live kernel binding for owner-reviewed curator operations."""

from __future__ import annotations

from copy import deepcopy

from agents.core.action_origin import current_action_origin
from agents.core.security.taint import is_tainted, is_untrusted_source

_OPERATIONS = frozenset({
    "run", "pause", "resume", "pin", "unpin", "adopt", "restore", "archive",
    "prune", "backup", "rollback", "purge",
})


def curator_authorize(orch):
    """Return a mandatory guard, never an approval or a cached execution grant.

    The operations store binds the owner's exact card separately. A QUEUE result
    remains pending until that check succeeds; this adapter never treats a
    payload's claimed approval as authority. The live hub kernel is rebound for
    every call so a new halt/policy applies before effects.
    """
    def authorize(payload: dict) -> str:
        origin = current_action_origin()
        if is_untrusted_source(origin) or is_tainted(payload):
            return "deny"
        if not isinstance(payload, dict):
            return "error"
        kind, operation, tier = (payload.get(key) for key in ("kind", "operation", "risk_tier"))
        if (type(kind) is not str or kind not in {"skill.install", "skill.generation"}
                or type(operation) is not str or operation not in _OPERATIONS or type(tier) is not int
                or not 1 <= tier <= 3 or (operation == "purge" and tier != 3)):
            return "error"
        try:
            from agents.core.kernel import Action
            from agents.core.kernel.binding import make_action_kernel

            kernel = make_action_kernel(orch)
            if not callable(kernel):
                return "error"
            decision = kernel(Action(kind=kind, agent="operator", title=f"Curator {operation}",
                                     payload=deepcopy(payload), origin=origin))
            verdict = decision.verdict.value
            return verdict if verdict in {"grant", "queue", "deny"} else "error"
        except Exception:
            return "error"

    return authorize
