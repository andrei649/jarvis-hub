"""
dry_run.py — H12.5 Preview / dry-run for autonomy (extends H6.2).

Before you approve an autonomous action (or its pattern), show exactly what it
*would* do — target, concrete effects, reversibility, and whether approval is
required — without executing anything. Closes the observability gap: no blind
actions. Reuses the H17.1 irreversibility classification.
"""

from __future__ import annotations

from typing import Union

try:
    from ..security.quarantine import QuarantinePolicy
    _POLICY = QuarantinePolicy()
except Exception:  # pragma: no cover - security module always present
    _POLICY = None

# payload keys that describe a concrete, observable effect
_EFFECT_KEYS = ("target", "url", "to", "recipient", "amount", "command",
                "path", "file", "channel", "query", "body")

# kind/title tokens that imply an irreversible side effect
_IRREVERSIBLE_TOKENS = ("send", "post", "publish", "delete", "remove", "transfer",
                        "pay", "payment", "buy", "deploy", "email", "message", "exec")


def _as_dict(task: Union[dict, object]) -> dict:
    if isinstance(task, dict):
        return task
    if hasattr(task, "to_dict"):
        return task.to_dict()
    return dict(getattr(task, "__dict__", {}))


def _is_irreversible(kind: str, title: str) -> bool:
    blob = f"{kind} {title}".lower()
    if _POLICY is not None and _POLICY.is_irreversible(kind.lower()):
        return True
    return any(tok in blob for tok in _IRREVERSIBLE_TOKENS)


def preview_task(task: Union[dict, object]) -> dict:
    """Return a non-executing preview of what *task* would do."""
    t = _as_dict(task)
    kind = str(t.get("kind", ""))
    title = str(t.get("title", ""))
    payload = t.get("payload") or {}
    tier = int(t.get("risk_tier", 3) or 3)

    target = (payload.get("target") or payload.get("url") or payload.get("to")
              or payload.get("recipient") or "")
    effects = [{"field": k, "value": payload[k]} for k in _EFFECT_KEYS if payload.get(k)]
    irreversible = _is_irreversible(kind, title)
    # Approval required when irreversible or medium/high risk (tier 1 = lowest here).
    requires_approval = irreversible or tier <= 2

    summary = (
        f"Would run '{kind or 'task'}'"
        + (f" → {target}" if target else "")
        + f"; {'IRREVERSIBLE' if irreversible else 'reversible'}"
        + f"; {'approval required' if requires_approval else 'auto-approvable'}."
    )
    return {
        "kind": kind,
        "title": title,
        "target": target,
        "effects": effects,
        "irreversible": irreversible,
        "risk_tier": tier,
        "requires_approval": requires_approval,
        "summary": summary,
        "would_execute": False,
    }
