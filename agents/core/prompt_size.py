"""H048 — what a fresh turn costs before anybody has said anything.

Nerva's stated advantage is running well on a local model with a small context
window. Everything that competes for that window before the first user word —
each agent's soul, the skills index, the tool schemas, the turn scaffolding —
is invisible today, so "why does the local model degrade after four turns" has
no number attached to it. This produces the number.

Read-only and offline: it reads files and a registry's declared specs. It never
constructs a backend, never sends a request, and never needs a running hub.

The figures are ESTIMATES, and the report says so. `estimate_tokens` is the same
function the runtime budget uses, so a number here is directly comparable with a
number there — but the only exact count of a real request is the one the
provider reports back (H673). This measures the fixed floor; that measures the
turn.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm.tokenizer import estimate_tokens

# The literal scaffolding `Agent.build_prompt` appends to every single turn.
# Kept here as the shape it renders rather than a copy of the words: a caller
# wants the cost, and duplicating the sentences would rot the moment they change.
_SCAFFOLD_KEYS = ("user_line", "respond_as", "learn_hint", "handoff_hint")


@dataclass(frozen=True)
class Component:
    """One named contributor to the fixed per-call cost."""

    name: str
    chars: int
    tokens: int
    detail: str = ""

    @classmethod
    def of(cls, name: str, text: str, detail: str = "") -> Component:
        body = text or ""
        return cls(name=name, chars=len(body), tokens=estimate_tokens(body), detail=detail)

    def as_dict(self) -> dict[str, Any]:
        row = {"name": self.name, "chars": self.chars, "tokens": self.tokens}
        if self.detail:
            row["detail"] = self.detail
        return row


@dataclass
class Breakdown:
    """The whole fixed floor, by component, largest first."""

    components: list[Component] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(c.tokens for c in self.components)

    @property
    def total_chars(self) -> int:
        return sum(c.chars for c in self.components)

    def ranked(self) -> list[Component]:
        """Largest first — the point of the report is what to cut."""
        return sorted(self.components, key=lambda c: (-c.tokens, c.name))

    def share(self, component: Component) -> float:
        total = self.total_tokens
        return (component.tokens / total) if total else 0.0

    def shared_components(self) -> list[Component]:
        """Everything every call pays for, whichever agent answers."""
        return [c for c in self.components if not c.name.startswith("soul:")]

    def souls(self) -> list[Component]:
        return [c for c in self.components if c.name.startswith("soul:")]

    def per_call(self, agent: str = "") -> tuple[int, Component | None]:
        """The floor ONE request actually pays: the shared cost plus ONE soul.

        Summing all eighteen personas would be the misleading number this row
        exists to replace — no single request has ever paid it. When no agent is
        named the heaviest soul is used, so the figure is the worst realistic
        case rather than a flattering one.
        """
        shared = sum(c.tokens for c in self.shared_components())
        souls = self.souls()
        if not souls:
            return shared, None
        if agent:
            wanted = f"soul:{agent}".lower()
            picked = next((c for c in souls if c.name.lower() == wanted), None)
            if picked is None:
                return shared, None
        else:
            picked = max(souls, key=lambda c: c.tokens)
        return shared + picked.tokens, picked

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_chars": self.total_chars,
            "total_tokens": self.total_tokens,
            "components": [c.as_dict() for c in self.ranked()],
            "notes": list(self.notes),
        }


def soul_components(root: Path) -> list[Component]:
    """One row per agent persona actually on disk.

    Eighteen personas ship, and only the routed one is sent per call — so this is
    deliberately reported per agent rather than summed into a single figure that
    no single request would ever pay.
    """
    found: list[Component] = []
    for path in sorted(root.glob("*/SOUL.md")):
        agent = path.parent.name
        if agent.startswith("_"):        # _templates is not an agent
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        found.append(Component.of(f"soul:{agent}", text, detail=str(path.relative_to(root.parent))))
    return found


def skills_index_component(skills: Iterable[Mapping[str, Any]]) -> Component:
    """The `Available skills:` block, rendered exactly as `build_prompt` renders it."""
    rows = list(skills or [])
    if not rows:
        return Component(name="skills-index", chars=0, tokens=0, detail="no skills registered")
    body = "\n".join(
        f"  - {row.get('command', '')}: {row.get('description', '')}" for row in rows
    )
    return Component.of("skills-index", f"Available skills:\n{body}\n\n",
                        detail=f"{len(rows)} skill(s)")


def tool_schema_components(specs: Iterable[Mapping[str, Any]]) -> list[Component]:
    """One row per tool, costed as the JSON that actually crosses the wire.

    The schema is what the model is charged for, not the tool's name — a single
    verbose `input_schema` can outweigh a whole persona, and that is exactly the
    kind of thing this report exists to expose.
    """
    rows: list[Component] = []
    for spec in specs or []:
        name = str(spec.get("name") or "?")
        blob = json.dumps(spec, ensure_ascii=False, sort_keys=True)
        gated = " (gated)" if spec.get("gated") else ""
        rows.append(Component.of(f"tool:{name}", blob, detail=f"schema JSON{gated}"))
    return rows


def scaffold_component(agent_name: str = "Jarvis") -> Component:
    """The per-turn boilerplate every request carries, whatever else it carries.

    Small per call and paid on every call, which is the only reason it is worth a
    line of its own: a reader comparing it against a persona learns where the
    money actually is.
    """
    rendered = (
        f"User said: \n"
        f"Respond as {agent_name}.\n\n"
        "IMPORTANT: If this is a complex multi-step task you solved elegantly, "
        "end your response with '[learn: task description | step1,step2,step3 | command_name]' "
        "to save it as a reusable skill. "
        "You can also hand off to another agent with '[handoff:agent_id]'."
    )
    return Component.of("turn-scaffold", rendered, detail=f"{len(_SCAFFOLD_KEYS)} fixed parts")


def breakdown(
    *,
    agents_root: Path,
    tool_specs: Iterable[Mapping[str, Any]] = (),
    skills: Iterable[Mapping[str, Any]] = (),
    agent_name: str = "Jarvis",
) -> Breakdown:
    """Assemble the fixed floor. Pure: every input is passed in, nothing is booted."""
    report = Breakdown()
    report.components.extend(soul_components(agents_root))
    report.components.extend(tool_schema_components(tool_specs))
    report.components.append(skills_index_component(skills))
    report.components.append(scaffold_component(agent_name))
    report.components = [c for c in report.components if c.chars or c.name == "skills-index"]
    report.notes.append(
        "Token figures are estimates from the same function the runtime budget uses. "
        "The exact size of a real request is the one the provider reports back (H673)."
    )
    report.notes.append(
        "Only ONE soul is sent per call — the routed agent's. They are listed "
        "separately rather than summed, because no single request pays for all of them."
    )
    return report


def render(report: Breakdown, *, window: int = 0, agent: str = "") -> str:
    """A plain-text table, largest first, with each row's share of the floor."""
    lines = ["component                                    chars   tokens    share",
             "-" * 74]
    for component in report.ranked():
        lines.append(
            f"{component.name[:42]:<42} {component.chars:>8} {component.tokens:>8}"
            f" {report.share(component) * 100:>7.1f}%"
        )
    lines.append("-" * 74)
    lines.append(f"{'all components listed':<42} {report.total_chars:>8} "
                 f"{report.total_tokens:>8}")

    per_call, soul = report.per_call(agent)
    shared = sum(c.tokens for c in report.shared_components())
    lines.append("")
    lines.append("What ONE request actually pays:")
    lines.append(f"  shared by every call (tools, skills, scaffold): {shared:>8} tokens")
    if soul is not None:
        which = "heaviest" if not agent else "requested"
        lines.append(f"  + one soul ({soul.name.split(':', 1)[1]}, {which}):"
                     f"{'':<14}{soul.tokens:>8} tokens")
    lines.append(f"  = fixed floor per call:{'':<26}{per_call:>8} tokens")
    if window:
        lines.append("")
        lines.append(
            f"Against a {window:,}-token window that floor is "
            f"{per_call / window * 100:.1f}% before the first word."
        )
    for note in report.notes:
        lines.append("")
        lines.append(f"note: {note}")
    return "\n".join(lines)


__all__ = [
    "Breakdown",
    "Component",
    "breakdown",
    "render",
    "scaffold_component",
    "skills_index_component",
    "soul_components",
    "tool_schema_components",
]
