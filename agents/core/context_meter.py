"""The context meter (H412): what fills the model's window for this conversation.

``/context``, ``GET /api/sessions/{id}/context`` and the HUD meter all read this one
function, and it reads the **same policy object the compaction loop uses**
(``Orchestrator._compaction_model`` / ``_compaction_policy``, ``context_compressor``):
the window, the soft tier (images go first) and the hard tier (older text is
summarised). A meter that re-derived its own thresholds would report a state the
compressor does not share.

The next request is split by category, in tokens:

* ``system`` — the routed agent's soul, the shared identity contract, the host facts and
  the per-turn scaffold (``prompt_size``, the same pieces ``nerva prompt-size`` costs);
* ``tools`` — every tool schema the model is offered, one row per tool;
* ``skills`` — the skills index and any skills the session carries;
* ``memory`` — the living core-memory block the next turn would send;
* ``history`` — the conversation's stored turns, costed as the compressor costs them;
* ``attachments`` — images in the history and ``@file`` attachments
  (``--- Attached Context ---`` blocks), which the history figure leaves out.

The categories add up to ``used``; ``free`` is what is left of the window. Every figure
is an estimate from the runtime's own estimator, and the payload says so; the exact size
of a request is the one the provider reports back (H673), shown as ``measured`` when
there is one. Read-only: nothing here compacts, writes or calls a model.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.context_meter")

CATEGORIES = ("system", "tools", "skills", "memory", "history", "attachments")
GRID_CELLS = 100
_SYSTEM = {"identity", "host-detected", "environment-hint", "turn-scaffold"}


class MeterUnavailable(RuntimeError):
    """The meter cannot be computed for this conversation; the message says why."""


def _estimate(text: str) -> int:
    from .llm.tokenizer import estimate_tokens

    return estimate_tokens(text) if text else 0


def _fixed_floor(orch: Any, agent: str) -> dict[str, list[dict]]:
    """The per-call floor by category, from ``prompt_size`` (no backend, no request)."""
    from .prompt_size import (
        environment_hint_component,
        host_detected_component,
        identity_component,
        scaffold_component,
        skills_index_component,
        skills_loaded_component,
        soul_components,
        tool_schema_components,
    )

    root = Path(__file__).resolve().parent.parent          # …/agents
    rows: dict[str, list[dict]] = {name: [] for name in CATEGORIES}
    souls = soul_components(root)
    soul = next((c for c in souls if c.name == f"soul:{agent}"), None)
    if soul is None and souls:
        soul = max(souls, key=lambda c: c.tokens)          # worst realistic case
    pieces = [soul] if soul is not None else []
    pieces += [identity_component(root), host_detected_component(), environment_hint_component(),
               scaffold_component()]
    for piece in pieces:
        if piece is not None and piece.tokens:
            rows["system"].append(piece.as_dict())
    server = getattr(orch, "tool_rpc", None)
    try:
        specs = server.tools() if server is not None else []
    except Exception:  # noqa: BLE001
        specs = []
    rows["tools"] = [c.as_dict() for c in tool_schema_components(specs) if c.tokens]
    loader = getattr(orch, "skills", None)
    index = ""
    try:
        index = loader.prompt_index(agent) if callable(getattr(loader, "prompt_index", None)) else ""
    except Exception:  # noqa: BLE001
        index = ""
    rows["skills"] = [c.as_dict() for c in (skills_index_component(index or ""),
                                            skills_loaded_component("")) if c.tokens]
    return rows


def _history_rows(turns: list[dict]) -> tuple[int, int, int, int]:
    """``(history_tokens, attachment_tokens, images, attached_blocks)``."""
    from .context_compressor import IMAGE_TOKEN_COST, _has_image
    from .context_refs import MARKER

    history = attachments = images = blocks = 0
    for turn in turns:
        content = str(turn.get("content", "") or "")
        if _has_image(turn):
            images += 1
            attachments += IMAGE_TOKEN_COST
            if content.startswith("data:image/"):
                content = ""
        if MARKER in content:
            head, _, attached = content.partition(MARKER)
            blocks += 1
            attachments += _estimate(MARKER + attached)
            content = head
        history += _estimate(content)
    return history, attachments, images, blocks


async def breakdown(orch: Any, session_id: str, *, agent: str = "jarvis") -> dict:
    """The meter for *session_id*: categories, window, tiers and a 100-cell grid."""
    model = orch._compaction_model()
    policy = orch._compaction_policy()
    window = int(policy.window(model))
    floor = await asyncio.to_thread(_fixed_floor, orch, agent)
    memory_text = ""
    block = getattr(orch, "_living_core_memory_block", None)
    if callable(block):
        try:
            memory_text = await asyncio.to_thread(block, freeze=False)
        except Exception:  # noqa: BLE001
            memory_text = ""
    memory = getattr(orch, "memory", None)
    try:
        turns = await memory.get_history(session_id) if memory is not None else []
    except Exception as exc:  # noqa: BLE001 — e.g. UnverifiedRewind: the history is not readable
        from .memory.conversation import UnverifiedRewind
        from .memory.manager import RewindRefused

        if isinstance(exc, (UnverifiedRewind, RewindRefused)):
            raise MeterUnavailable("this conversation's history cannot be verified, so it is not measured") from exc
        raise
    turns = [t for t in (turns or []) if isinstance(t, dict)]
    history, attachments, images, blocks = _history_rows(turns)
    tokens = {
        "system": sum(r["tokens"] for r in floor["system"]),
        "tools": sum(r["tokens"] for r in floor["tools"]),
        "skills": sum(r["tokens"] for r in floor["skills"]),
        "memory": _estimate(memory_text),
        "history": history,
        "attachments": attachments,
    }
    used = sum(tokens.values())
    free = max(0, window - used)
    soft, hard = int(policy.soft * window), int(min(0.85, policy.hard) * window)
    tier = policy.tier(history + attachments, model)
    categories = []
    for name in CATEGORIES:
        detail = floor.get(name) or []
        row = {"name": name, "tokens": tokens[name],
               "share": round(tokens[name] / window, 4) if window else 0.0}
        if detail:
            row["items"] = sorted(detail, key=lambda r: (-r["tokens"], r["name"]))
        categories.append(row)
    categories[CATEGORIES.index("history")]["turns"] = len(turns)
    categories[CATEGORIES.index("attachments")]["images"] = images
    categories[CATEGORIES.index("attachments")]["attached_blocks"] = blocks
    # The provider's own count of this conversation's last request (H673), when one
    # reported it and no turn has been dropped from under it since.
    measured = None
    row = (getattr(orch, "__dict__", {}).get("_context_measured_by_session") or {}).get(str(session_id))
    if isinstance(row, tuple) and len(row) == 2 and int(row[1]) <= len(turns):
        measured = int(row[0])
    return {
        "session_id": session_id,
        "model": model,
        "window": window,
        "used": used,
        "free": free,
        "percent": round(100.0 * used / window, 1) if window else 0.0,
        "categories": categories,
        "thresholds": {"soft": soft, "hard": hard, "soft_ratio": policy.soft,
                       "hard_ratio": min(0.85, policy.hard)},
        "compaction_tier": tier,
        "grid": grid(tokens, window),
        "measured": measured if isinstance(measured, int) and measured > 0 else None,
        "estimated": True,
        "note": ("Estimates from the runtime's own token estimator; the provider's own count of "
                 "the last request is 'measured' when it reported one."),
    }


def grid(tokens: dict[str, int], window: int, cells: int = GRID_CELLS) -> list[str]:
    """*cells* cells, each the category that fills it (``free`` for the rest). Every
    category with any tokens gets at least one cell, largest remainders first, so the
    grid always sums to *cells*."""
    if window <= 0:
        return ["free"] * cells
    shares = {name: tokens.get(name, 0) * cells / window for name in CATEGORIES}
    counts = {name: int(share) for name, share in shares.items()}
    for name in CATEGORIES:
        if tokens.get(name, 0) > 0 and counts[name] == 0:
            counts[name] = 1
    total = sum(counts.values())
    if total > cells:                                   # over the window: scale down
        scale = cells / total
        counts = {name: max(1 if tokens.get(name, 0) else 0, int(c * scale)) for name, c in counts.items()}
        while sum(counts.values()) > cells:
            biggest = max(counts, key=lambda n: counts[n])
            counts[biggest] -= 1
    else:
        spare = min(cells - total, int(round(sum(shares.values()))) - total)
        for name in sorted(CATEGORIES, key=lambda n: -(shares[n] - int(shares[n]))):
            if spare <= 0:
                break
            if tokens.get(name, 0):
                counts[name] += 1
                spare -= 1
    out: list[str] = []
    for name in CATEGORIES:
        out.extend([name] * counts[name])
    return (out + ["free"] * cells)[:cells]


_GLYPH = {"system": "S", "tools": "T", "skills": "K", "memory": "M", "history": "H",
          "attachments": "A", "free": "·"}


def render(meter: dict, *, expand: bool = False) -> str:
    """The ``/context`` text: a 10×10 glyph grid and a usage table."""
    rows = meter["grid"]
    lines = [f"Context: {meter['used']:,} of {meter['window']:,} tokens ({meter['percent']}%) "
             f"— model {meter['model'] or 'default'}, estimated"]
    for start in range(0, len(rows), 10):
        lines.append("  " + " ".join(_GLYPH.get(c, "?") for c in rows[start:start + 10]))
    lines.append("  S system · T tools · K skills · M memory · H history · A attachments · · free")
    lines.append("")
    lines.append(f"{'category':<12}{'tokens':>10}{'of window':>11}")
    for row in meter["categories"]:
        extra = ""
        if row["name"] == "history":
            extra = f"  ({row.get('turns', 0)} turns)"
        elif row["name"] == "attachments" and (row.get("images") or row.get("attached_blocks")):
            extra = f"  ({row.get('images', 0)} images, {row.get('attached_blocks', 0)} @file blocks)"
        lines.append(f"{row['name']:<12}{row['tokens']:>10,}{row['share'] * 100:>10.1f}%{extra}")
        if expand and row.get("items"):
            for item in row["items"][:15]:
                lines.append(f"    {item['name'][:36]:<36}{item['tokens']:>8,}")
    lines.append(f"{'free':<12}{meter['free']:>10,}")
    t = meter["thresholds"]
    lines.append("")
    lines.append(f"Compaction: images go at {t['soft']:,} tokens ({t['soft_ratio']:.0%}), older text is "
                 f"summarised at {t['hard']:,} ({t['hard_ratio']:.0%}); this conversation is at tier "
                 f"'{meter['compaction_tier']}'.")
    if meter.get("measured"):
        lines.append(f"The provider measured the last request at {meter['measured']:,} tokens.")
    if not expand:
        lines.append("/context all lists every tool and skill row.")
    return "\n".join(lines)


def compress_report(meter: dict) -> str:
    """``/compress``: what compaction does for this conversation now — never a rewrite.

    Nerva compacts on the turn, inside the request it builds (the policy above), and
    never edits the stored conversation. So a manual ``/compress`` reports, from the
    same policy, which of the three outcomes the next turn will take: nothing (below the
    soft tier), drop images (soft), or summarise older text (hard)."""
    tier = meter["compaction_tier"]
    t = meter["thresholds"]
    history = next(r for r in meter["categories"] if r["name"] == "history")["tokens"]
    attachments = next(r for r in meter["categories"] if r["name"] == "attachments")["tokens"]
    load = history + attachments
    head = f"History and attachments: {load:,} tokens of a {meter['window']:,}-token window."
    if tier == "none":
        return (f"{head}\nNo-op: below the soft tier ({t['soft']:,} tokens), so nothing is dropped or "
                "summarised; the next request sends this conversation unchanged. The stored "
                "conversation was not changed.")
    if tier == "images":
        return (f"{head}\nAbove the soft tier ({t['soft']:,}): the next request drops images from older "
                "turns first (the text that described them stays); no text is summarised yet. The "
                "stored conversation was not changed.")
    return (f"{head}\nAbove the hard tier ({t['hard']:,}): the next request drops older images and "
            "summarises the older text, keeping the first and the latest turns verbatim; if the "
            "summariser fails it falls back to a deterministic digest. The stored conversation "
            "was not changed.")
