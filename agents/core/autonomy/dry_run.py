"""
dry_run.py — H12.5 Preview / dry-run for autonomy (extends H6.2).

Before you approve an autonomous action (or its pattern), show exactly what it
*would* do — target, concrete effects, reversibility, and whether approval is
required — without executing anything. Closes the observability gap: no blind
actions. Reuses the H17.1 irreversibility classification.
"""

from __future__ import annotations

import re
from typing import Union

try:
    from ..security.quarantine import QuarantinePolicy
    _POLICY = QuarantinePolicy()
except Exception:  # pragma: no cover - security module always present
    _POLICY = None

# payload keys that describe a concrete, observable effect
_EFFECT_KEYS = ("target", "url", "to", "recipient", "amount", "command",
                "path", "file", "channel", "query", "body")


def _irreversible_tokens() -> tuple[str, ...]:
    """Kind/title tokens that imply an external or irreversible side effect.

    Derived from the policy's canonical classification sets (GOV-038 gap 2:
    a preview narrower than the policy told the human "reversible" about a
    purchase/booking the policy itself tiers as money) plus "exec", which the
    policy handles through sandbox kinds rather than a token."""
    from .policy import _EXTERNAL, _MONEY_OR_IRREVERSIBLE

    return tuple(dict.fromkeys((*_MONEY_OR_IRREVERSIBLE, *_EXTERNAL, "exec")))


_IRREVERSIBLE_TOKENS = _irreversible_tokens()


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
    # Word-token membership, the policy's own matching semantics — a substring
    # test over the broader token set would flag "design" (sign) or "facebook"
    # (book) as irreversible. Compound tokens (submit_order) are split away by
    # the tokenizer, so those few match as literal substrings instead.
    words = set(re.split(r"[^a-z0-9]+", blob))
    return any(tok in blob if "_" in tok else tok in words for tok in _IRREVERSIBLE_TOKENS)


def preview_task(task: Union[dict, object], *, autonomy_level: str | None = None) -> dict:
    """Return a non-executing preview of what *task* would do.

    ``autonomy_level`` lets a pipeline that decides its own approval floor
    (e.g. house intake: "ask" until autonomy is earned) stamp the preview with
    what will actually happen — anything but "act" forces approval, on top of
    (never instead of) the tier/irreversibility floor."""
    t = _as_dict(task)
    kind = str(t.get("kind", ""))
    title = str(t.get("title", ""))
    payload = t.get("payload") or {}
    tier = int(t.get("risk_tier", 3) or 3)

    target = (payload.get("target") or payload.get("url") or payload.get("to")
              or payload.get("recipient") or "")
    effects = [{"field": k, "value": payload[k]} for k in _EFFECT_KEYS if payload.get(k)]
    irreversible = _is_irreversible(kind, title)
    # RiskTier scale: 0=READ_ONLY, 1=REVERSIBLE, 2=EXTERNAL, 3=IRREVERSIBLE_OR_MONEY —
    # approval is required from EXTERNAL up. GOV-038: this comparison used to be
    # inverted (`tier <= 2`), so a tier-3 money task previewed as "auto-approvable"
    # while a tier-0 read required approval; the unknown-tier default (3) now fails
    # closed instead of open.
    requires_approval = irreversible or tier >= 2
    if autonomy_level is not None and autonomy_level != "act":
        requires_approval = True

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
        # PNB-055: this was hard-coded False, so the Decision Inbox chip read
        # "would queue" forever. A preview never executes anything; the field
        # says what submission WOULD do — run without approval, or queue for it.
        "would_execute": not requires_approval,
    }
