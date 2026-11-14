"""H079: resolve up to five installed skills for an owner's slash invocation.

Resolution only names an installed skill. The shared bundle turn loader performs the
actual read, gate, taint, environment and ledger work for each model prompt.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import bundles

_SLASH = re.compile(r"/([A-Za-z][A-Za-z0-9_-]{0,63})(?:@\w+)?(?:\s+(.*))?", re.DOTALL)
_NEXT = re.compile(r"/([A-Za-z][A-Za-z0-9_-]{0,63})(?:@\w+)?(?=\s|$)")
MAX_STACK = 5
_REFUSAL = "The skill could not be loaded; nothing was sent to the model."


@dataclass(frozen=True)
class Invocation:
    skill_names: tuple[str, ...]
    instruction: str
    problem: str = ""

    @property
    def skill_name(self) -> str:
        """The first skill, for the single-skill command catalog."""
        return self.skill_names[0] if self.skill_names else ""

    @property
    def ambiguous(self) -> bool:
        return self.problem == "ambiguous"


def _matches(word: str, pool: list[Any]) -> list[Any]:
    wanted = bundles.slugify(word)
    hits = {}
    for skill in pool:
        path = getattr(skill, "path", None)
        folder = getattr(path, "name", "") if path is not None else ""
        if wanted in (bundles.slugify(getattr(skill, "name", "")), bundles.slugify(folder)):
            hits[id(skill)] = skill
    return list(hits.values())


def resolve(text: Any, loader: Any, *, taken: Callable[[str], bool] | None = None) -> Invocation | None:
    """Resolve leading skill tokens, refusing an invalid stack after a known first skill.

    The command namespace owns its words. A skill can be named by its display name
    or folder using the same slug normalization as a bundle. Multiple installed
    skills with one slug are refused, rather than selecting an arbitrary skill.
    A slash path such as ``/tmp/file`` does not form a skill token and stays in the
    instruction. A command, quick command or bundle after the first skill refuses
    the stack; it cannot be smuggled through as a skill or an instruction.
    """
    if not isinstance(text, str):
        return None
    match = _SLASH.fullmatch(text.strip())
    if match is None:
        return None
    word = match.group(1)
    if callable(taken) and taken(word.lower()):
        return None
    pool = list((getattr(loader, "skills", None) or {}).values())
    hits = _matches(word, pool)
    if not hits:
        return None
    if len(hits) != 1:
        return Invocation((), "", problem="ambiguous")
    names = [hits[0].name]
    rest = (match.group(2) or "").strip()
    while rest.startswith("/"):
        next_token = _NEXT.match(rest)
        if next_token is None:
            break
        if len(names) >= MAX_STACK:
            return Invocation(tuple(names), "", problem="too_many")
        word = next_token.group(1)
        if (callable(taken) and taken(word.lower())) or bundles.get(word) is not None:
            return Invocation(tuple(names), "", problem="namespace")
        hits = _matches(word, pool)
        if len(hits) != 1:
            return Invocation(tuple(names), "", problem="ambiguous" if hits else "unknown")
        names.append(hits[0].name)
        rest = rest[next_token.end():].strip()
    return Invocation(tuple(names), rest[:bundles._MAX_INSTRUCTION_TYPED])


def begin_load(inv: Invocation, loader: Any, *, owner: bool, session: str,
               template_vars: Any = None) -> str | None:
    """Bind one owner-requested skill, or return a no-model refusal."""
    if owner is not True or inv.problem or not inv.skill_names:
        return _REFUSAL
    if len(inv.skill_names) == 1:
        return bundles.begin_skill_load(inv.skill_name, inv.instruction, loader,
                                        session=session, template_vars=template_vars)
    return bundles.begin_skill_stack_load(inv.skill_names, inv.instruction, loader,
                                          session=session, template_vars=template_vars)
