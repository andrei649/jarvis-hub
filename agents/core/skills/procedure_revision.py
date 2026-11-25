"""Read the narrow, approved owner-taught procedure format for step revisions."""

from __future__ import annotations

import re
from pathlib import Path

from agents.core.skill_drift import manifest_hash

from .loader import _writable_skills_dir
from .usage import WRITE_REVIEWED_REPLY

_FOLDER = re.compile(r"procedure_([0-9a-f]{32})\Z")
_STEP = re.compile(r"([1-9][0-9]*)\. (.+)\Z")


def candidate(loader, skill, agent: str) -> bool:
    """Cheap hint for the command catalog; GET/POST perform the source check."""
    # shortcut: a catalog hint can outlive a filesystem change, recheck the source on GET/POST.
    try:
        path = Path(skill.path)
        usage = getattr(loader, "_usage", None)
        return bool(agent != "all" and _FOLDER.fullmatch(path.name) and skill.agents == [agent]
                    and skill.external and not skill.sandboxed and skill.trusted
                    and skill.module is None and not skill.commands_meta
                    and usage is not None
                    and (usage.get(skill.name) or {}).get("write_origin") == WRITE_REVIEWED_REPLY)
    except (TypeError, AttributeError):
        return False


def read(loader, skill, agent: str) -> dict | None:
    """Return the current revision surface, or refuse an uncertain skill or filesystem."""
    try:
        path = Path(skill.path)
        root = _writable_skills_dir()
        match = _FOLDER.fullmatch(path.name)
        if (not candidate(loader, skill, agent) or not match or path.is_symlink() or root.is_symlink()
                or path.resolve().parent != root.resolve()
                or loader.catalog_gate(skill, agent)):
            return None
        files = list(path.iterdir())
        if ({item.name for item in files} != {"SKILL.md", "SKILL.sig", "PROCEDURE_REQUEST"}
                or any(item.is_symlink() or not item.is_file() for item in files)):
            return None
        standing = loader.owner_standing(skill)
        if (standing.get("unreadable") or standing.get("bundled")
                or not standing.get("approved") or not standing.get("signed")):
            return None
        snapshot = standing.get("snapshot")
        if snapshot is None or {item.relative_path for item in snapshot.files} != {"SKILL.md", "PROCEDURE_REQUEST"}:
            return None
        raw = snapshot.read_bytes("SKILL.md")
        receipt = snapshot.read_bytes("PROCEDURE_REQUEST")
        receipt_lines = receipt.decode("ascii").splitlines() if receipt is not None else []
        if (raw is None or len(receipt_lines) != 2 or receipt_lines[0] != match.group(1)
                or re.fullmatch(r"[0-9a-f]{64}", receipt_lines[1]) is None):
            return None
        current = raw.decode("utf-8")
        headings = list(re.finditer(r"^## Steps\r?\n", current, re.MULTILINE))
        if len(headings) != 1:
            return None
        prefix = current[:headings[0].end()]
        steps = current[headings[0].end():].splitlines()
        if not 1 <= len(steps) <= 20:
            return None
        parsed = []
        for index, line in enumerate(steps, 1):
            step = _STEP.fullmatch(line)
            if step is None or int(step.group(1)) != index:
                return None
            parsed.append(step.group(2))
        return {"skill": skill.name, "steps": parsed, "base_hash": manifest_hash(current),
                "prefix": prefix, "newline": "\r\n" if prefix.endswith("\r\n") else "\n",
                "current": current}
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return None
