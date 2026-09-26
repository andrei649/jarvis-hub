"""H350 — a SKILL.md is checked before any write lands it, and linted on request.

Before this, a malformed SKILL.md fell through to the loader's fallbacks without a
word: a frontmatter block that is not a mapping, or a fence that never closes, read as
the heading dialect, and the skill registered under its folder's name with an empty
description, one more line in the prompt index that says nothing. Hermes blocks such
a write (``_validate_frontmatter``: the fence, a YAML mapping, a name and a
description, the description's length, a body, a size cap). This module does the same
for both dialects the loader reads, and every write path calls it:

- import (``SkillImporter._save_skill``, so the GitHub and manifest imports) and the
  local import and re-import (``_import_local_skill``, before anything is backed up);
- the marketplace (``publish_skill`` and ``install_from_zip``);
- agent generation (``SkillLoader.generate_skill``);
- skill proposals (``skill_propose``, the background review, and the apply).

:func:`validate_skill_md` returns field-level problems (empty when the document is
fine); :func:`require_valid` raises :class:`SkillDocumentInvalid` (a ``ValueError``)
carrying them. :func:`lint_skill_md` adds advisory findings the hard check does not
block (``nerva skills lint``). Everything here reads text; nothing is executed.

The two dialects:

- **frontmatter** (agentskills.io / Hermes): a ``---`` line first, a closing ``---`` at
  column 0, a YAML mapping between them with ``name`` (a folder-safe name, at most 64
  characters) and ``description`` (at most 1,024), and instructions below.
- **headings** (Nerva's own, the code-skill format): ``# Name`` and a ``> description``
  line; instructions are advised, not required, since the commands may live in
  ``main.py``. The loader names the skill after the LAST ``# `` line and describes it
  with the LAST ``> `` line, so a later one (a shell comment in a code block, a
  quotation) silently renames or re-describes the skill: that is refused here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import frontmatter as _fm

#: The largest SKILL.md a write may land: ``skill_view`` serves at most this much of a
#: file (``tools.MAX_FILE_BYTES``), so a larger one is a skill the model cannot read.
MAX_SKILL_MD_BYTES = 64 * 1024
MAX_NAME_LENGTH = _fm.MAX_NAME_LENGTH
MAX_DESCRIPTION_LENGTH = _fm.MAX_DESCRIPTION_LENGTH

# The importer's folder rule (``importer._SLUG_RE``), after its normalisation (lower
# case, a space as ``-``): a declared name must be one the importer can place.
_FOLDER_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BOM = "﻿"

# Advisory (lint) thresholds.
_SHORT_DESCRIPTION = 20
_LONG_BODY_LINES = 500
_KNOWN_KEYS = frozenset({
    "name", "description", "version", "author", "license", "agents", "requires", "commands",
    "homepage", "compatibility", "platforms", "environments", "requires_apps", "triggers",
    "dependencies", "tags", "related_skills", "setup", "prerequisites",
    "required_environment_variables", "required_credential_files", "metadata",
    "allowed-tools", "allowed_tools",
})


@dataclass(frozen=True)
class Problem:
    """One finding: the field it concerns and what is wrong, in plain words."""

    field: str
    message: str
    line: int | None = None

    def as_dict(self) -> dict:
        out = {"field": self.field, "message": self.message}
        if self.line is not None:
            out["line"] = self.line
        return out

    def __str__(self) -> str:
        where = f" (line {self.line})" if self.line is not None else ""
        return f"{self.field}: {self.message}{where}"


class SkillDocumentInvalid(ValueError):
    """A SKILL.md a write path refused; ``problems`` names every reason."""

    def __init__(self, problems: list[Problem]):
        self.problems = list(problems)
        super().__init__("; ".join(str(p) for p in self.problems) or "invalid SKILL.md")

    def as_list(self) -> list[dict]:
        return [p.as_dict() for p in self.problems]


def folder_safe(name: str) -> bool:
    """Whether *name* makes a skill folder, as the importer normalises it."""
    return bool(_FOLDER_NAME.match(name.strip().lower().replace(" ", "-")))


def _decode(document: str | bytes) -> tuple[str | None, list[Problem]]:
    if isinstance(document, bytes):
        size = len(document)
        if size > MAX_SKILL_MD_BYTES:
            return None, [Problem("document", f"{size:,} bytes; at most {MAX_SKILL_MD_BYTES:,}")]
        try:
            text = document.decode("utf-8")
        except UnicodeDecodeError as exc:
            return None, [Problem("document", f"not UTF-8 text (byte {exc.start:,})")]
    elif isinstance(document, str):
        try:
            size = len(document.encode("utf-8"))
        except UnicodeEncodeError:
            return None, [Problem("document", "holds text that cannot be written as UTF-8")]
        if size > MAX_SKILL_MD_BYTES:
            return None, [Problem("document", f"{size:,} bytes; at most {MAX_SKILL_MD_BYTES:,}")]
        text = document
    else:
        return None, [Problem("document", "not text")]
    text = text.removeprefix(_BOM).replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return None, [Problem("document", "empty")]
    if "\x00" in text:
        return None, [Problem("document", "holds a NUL character", text[: text.index("\x00")].count("\n") + 1)]
    return text, []


def _check_name(name: object, line: int | None) -> list[Problem]:
    if name is None or (isinstance(name, str) and not name.strip()):
        return [Problem("name", "missing", line)]
    if not isinstance(name, str):
        return [Problem("name", f"must be text, not {type(name).__name__}", line)]
    if _CONTROL.search(name):
        return [Problem("name", "holds a control character", line)]
    if len(name.strip()) > MAX_NAME_LENGTH:
        return [Problem("name", f"{len(name.strip()):,} characters; at most {MAX_NAME_LENGTH}", line)]
    if not folder_safe(name):
        return [Problem("name", f"{name.strip()!r} cannot name a skill folder: letters, digits, "
                                "spaces, '.', '_' or '-', starting with a letter or digit", line)]
    return []


def _check_description(description: object, line: int | None) -> list[Problem]:
    if description is None or (isinstance(description, str) and not description.strip()):
        return [Problem("description", "missing: say what the skill does and when to use it", line)]
    if not isinstance(description, str):
        return [Problem("description", f"must be text, not {type(description).__name__}", line)]
    if len(description.strip()) > MAX_DESCRIPTION_LENGTH:
        return [Problem("description", f"{len(description.strip()):,} characters; "
                                       f"at most {MAX_DESCRIPTION_LENGTH:,}", line)]
    return []


def _frontmatter_problems(lines: list[str]) -> list[Problem]:
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if close is None:
        return [Problem("frontmatter", "the closing '---' line is missing", 1)]
    block = "\n".join(lines[1:close])
    try:
        import yaml

        data = yaml.safe_load(block)
    except Exception as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 2 if mark is not None else None
        detail = getattr(exc, "problem", None) or type(exc).__name__
        return [Problem("frontmatter", f"not valid YAML: {detail}", line)]
    if not isinstance(data, dict):
        kind = "nothing" if data is None else type(data).__name__
        return [Problem("frontmatter", f"must be a mapping of keys to values, not {kind}", 2)]
    problems: list[Problem] = []
    key_line = {}
    for i in range(1, close):
        match = re.match(r"^([A-Za-z_][\w-]*)\s*:", lines[i])
        if match:
            key_line.setdefault(match.group(1), i + 1)
    problems += _check_name(data.get("name"), key_line.get("name"))
    problems += _check_description(data.get("description"), key_line.get("description"))
    if not "\n".join(lines[close + 1:]).strip():
        problems.append(Problem("body", "empty: the instructions go below the frontmatter", close + 1))
    return problems


def _heading_problems(lines: list[str]) -> list[Problem]:
    headings = [(i + 1, s[2:].strip()) for i, s in enumerate(ln.strip() for ln in lines) if s.startswith("# ")]
    quotes = [(i + 1, s[2:].strip()) for i, s in enumerate(ln.strip() for ln in lines) if s.startswith("> ")]
    problems: list[Problem] = []
    if not headings:
        problems.append(Problem("name", "missing: start with a '---' frontmatter block, or a '# Name' heading"))
    else:
        problems += _check_name(headings[0][1], headings[0][0])
        for line, text in headings[1:]:
            problems.append(Problem("name", f"a second '# ' line ({text[:40]!r}): the loader would name the "
                                            "skill after it; use '## ' for sections", line))
    if not quotes:
        problems.append(Problem("description", "missing: a '> ' line under the heading says what the skill "
                                               "does and when to use it"))
    else:
        problems += _check_description(quotes[0][1], quotes[0][0])
        for line, _text in quotes[1:]:
            problems.append(Problem("description", "a second '> ' line: the loader would use it as the "
                                                   "description", line))
    # No body rule here: the heading dialect is Nerva's code-skill format, whose commands
    # may live in main.py alone. The linter still advises instructions (a '## ' section).
    return problems


def dialect(document: str) -> str:
    """``frontmatter`` or ``headings``: which reading the loader gives *document*."""
    first = document.removeprefix(_BOM).split("\n", 1)[0]
    return "frontmatter" if first.strip() == "---" else "headings"


def validate_skill_md(document: str | bytes) -> list[Problem]:
    """Every reason a write of *document* as a SKILL.md is refused; empty when none."""
    text, problems = _decode(document)
    if text is None:
        return problems
    lines = text.split("\n")
    if dialect(text) == "frontmatter":
        return _frontmatter_problems(lines)
    return _heading_problems(lines)


def require_valid(document: str | bytes) -> None:
    """Raise :class:`SkillDocumentInvalid` unless *document* passes :func:`validate_skill_md`."""
    problems = validate_skill_md(document)
    if problems:
        raise SkillDocumentInvalid(problems)


def lint_skill_md(document: str | bytes, *, folder: str | None = None) -> list[Problem]:
    """Advisory findings beyond the hard check: nothing here blocks a write.

    ``folder`` is the skill's directory name, when the file sits in one.
    """
    text, _ = _decode(document)
    if text is None:
        return []
    lines = text.split("\n")
    findings: list[Problem] = []
    if dialect(text) == "frontmatter":
        data, body = _fm.split_frontmatter(text, lenient=False)
        if not isinstance(data, dict):
            return []
        name, description = data.get("name"), data.get("description")
        for key in data:
            if isinstance(key, str) and key not in _KNOWN_KEYS:
                findings.append(Problem(key, "not a key Nerva or Hermes reads; it is ignored"))
    else:
        body = text
        heads = [ln.strip()[2:].strip() for ln in lines if ln.strip().startswith("# ")]
        quotes = [ln.strip()[2:].strip() for ln in lines if ln.strip().startswith("> ")]
        name = heads[0] if heads else None
        description = quotes[0] if quotes else None
    if isinstance(description, str) and description.strip():
        desc = description.strip()
        if len(desc) < _SHORT_DESCRIPTION:
            findings.append(Problem("description", f"{len(desc)} characters: too short to tell the model "
                                                   "when to use the skill"))
        lowered = desc.lower()
        if not any(cue in lowered for cue in ("use when", "use this", "when ", "for ")):
            findings.append(Problem("description", "does not say when to use the skill ('Use when …')"))
    if isinstance(name, str) and folder and dialect(text) == "frontmatter" \
            and name.strip().lower().replace(" ", "-") != folder.lower():
        findings.append(Problem("name", f"{name.strip()!r} differs from its folder {folder!r}"))
    body_lines = body.split("\n") if isinstance(body, str) else []
    if len(body_lines) > _LONG_BODY_LINES:
        findings.append(Problem("body", f"{len(body_lines):,} lines: move reference material into files "
                                        f"beside SKILL.md (at most {_LONG_BODY_LINES} is easier to follow)"))
    if isinstance(body, str) and body.strip() and not re.search(r"^#{2,} ", body, re.MULTILINE):
        findings.append(Problem("body", "no '## ' section: headings help the model find the steps"))
    trailing = next((i for i, line in enumerate(lines, 1) if line != line.rstrip()), None)
    if trailing is not None:
        findings.append(Problem("document", "trailing whitespace", trailing))
    if sum(1 for line in lines if line.strip().startswith("```")) % 2:
        findings.append(Problem("body", "a code fence (```) is never closed"))
    if re.search(r"(?<![\w/])(/home/|/Users/|[A-Za-z]:\\Users\\)", text):
        findings.append(Problem("body", "names a path inside someone's home folder: it will not exist "
                                        "on another machine"))
    return findings
