"""H672 — the compaction commit is the one safe migration point for a live session.

Nerva's whole autonomy story is sessions that do not end. Today, enabling a
plugin, importing a skill or approving a capability has no effect on a
conversation already running: the owner enables something, nothing changes, and
the only fix is a restart — the exact opposite of an always-on house brain.

The boundary already exists. `ContextCompressor.compact()` commits and emits a
lineage row; it simply was not used as a migration point. Mid-turn is the wrong
place (a tool set that shifts under a turn makes the model's own plan invalid),
and a restart is no place at all. The compaction commit is the moment the
context is already being rebuilt, so nothing extra is disturbed.

Two refreshes, and they fail in OPPOSITE directions on purpose.

**The prompt fails open.** A plugin that throws while rendering its section must
not take the conversation's system prompt down with it, so a failed rebuild
keeps the last-good bytes. The worst case is a stale section, which is what the
owner already had.

**The tools fail closed.** The mirror-image choice, and the one that matters for
safety: this refresh must be able to REMOVE. A capability revoked mid-session —
an allowlist edit, a withdrawn consent, a disabled plugin — has to disappear at
the boundary, or "pick up changes without a restart" would mean picking up only
the additions and holding revocations live in every running conversation, which
is strictly worse than today's "nothing changes until restart". A resolver that
cannot answer therefore offers nothing, matching `_profiled`'s existing posture.

The keep-prompt fast path is gated on **byte equality of the builder's output**,
never on a dirty flag. A flag is a claim about the world that drifts from it;
the bytes are the world. Anything that forgets to set a flag silently pins a
session to a stale prompt forever, and that failure is invisible.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromptRefresh:
    """What the system prompt should be after a boundary, and whether it moved."""

    text: str
    changed: bool
    reason: str          # "identical" | "rebuilt" | "failed-open"

    @property
    def kept(self) -> bool:
        return not self.changed


@dataclass(frozen=True)
class ToolRefresh:
    """The offered tool set after a boundary, with what joined and what left."""

    tools: tuple[Mapping[str, Any], ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    reason: str = "identical"   # "identical" | "rebuilt" | "failed-closed"
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


def _names(tools: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(t.get("name") or "") for t in tools or () if t.get("name")]


def refresh_prompt(
    build: Callable[[], str],
    in_force: str,
    *,
    last_good: str | None = None,
) -> PromptRefresh:
    """Rebuild the system prompt from the LIVE builder, or keep what works.

    ``in_force`` is what the session is currently sending. The comparison is on
    the builder's actual output — byte equality — so a prompt that did not move
    is reported as kept even though it was fully rebuilt to find that out. That
    cost is the point: it is what makes the answer trustworthy.
    """
    fallback = in_force if last_good is None else last_good
    try:
        rebuilt = build()
    except Exception:
        # A broken plugin section must not break the conversation's prompt.
        logger.warning("system prompt rebuild failed; keeping last-good bytes",
                       exc_info=True)
        return PromptRefresh(text=fallback, changed=False, reason="failed-open")
    text = "" if rebuilt is None else str(rebuilt)
    if text == in_force:
        return PromptRefresh(text=in_force, changed=False, reason="identical")
    return PromptRefresh(text=text, changed=True, reason="rebuilt")


def refresh_tools(
    resolve: Callable[[], Sequence[Mapping[str, Any]]],
    in_force: Sequence[Mapping[str, Any]],
) -> ToolRefresh:
    """Re-resolve the offered tool set, so a revocation actually lands.

    Fails **closed**: a resolver that raises offers nothing, because the
    alternative is holding a possibly-revoked capability open for the life of a
    session that never ends. Refusing everything is recoverable at the next
    boundary; a silently retained capability is not.
    """
    before = _names(in_force)
    try:
        resolved = list(resolve() or ())
    except Exception:
        logger.warning("tool re-resolution failed; offering nothing until the next "
                       "boundary", exc_info=True)
        return ToolRefresh(
            tools=(), added=(), removed=tuple(before), reason="failed-closed",
            notes=("resolver raised; every tool is withdrawn rather than assumed still granted",),
        )
    after = _names(resolved)
    before_set, after_set = set(before), set(after)
    return ToolRefresh(
        tools=tuple(dict(t) for t in resolved),
        added=tuple(n for n in after if n not in before_set),
        removed=tuple(n for n in before if n not in after_set),
        reason="rebuilt" if before_set != after_set else "identical",
    )


def boundary_note(prompt: PromptRefresh, tools: ToolRefresh) -> str:
    """One line for the lineage row, or "" when nothing migrated.

    Silence when nothing changed matters: a boundary note on every compaction
    would train a reader to skip it, and this line only exists to be read on the
    day a capability vanished and somebody asks when.
    """
    parts: list[str] = []
    if prompt.changed:
        parts.append("prompt rebuilt")
    elif prompt.reason == "failed-open":
        parts.append("prompt kept (rebuild failed)")
    if tools.added:
        parts.append(f"tools added: {', '.join(tools.added)}")
    if tools.removed:
        parts.append(f"tools removed: {', '.join(tools.removed)}")
    if tools.reason == "failed-closed":
        parts.append("tool resolver failed closed")
    return "; ".join(parts)


__all__ = [
    "PromptRefresh",
    "ToolRefresh",
    "boundary_note",
    "refresh_prompt",
    "refresh_tools",
]
