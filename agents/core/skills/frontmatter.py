"""The SKILL.md frontmatter contract (H327), shared by the loader and the importer.

agentskills.io / Hermes write a YAML block between ``---`` fences at the top of a
SKILL.md. Hermes parses it defensively (``agent/skill_utils.parse_frontmatter``): a
leading UTF-8 byte-order mark is dropped before the fence check, the closing fence
sits at the start of a line, and a block that is not valid YAML falls back to
``key: value`` lines instead of losing the file. The listing caps a name at 64
characters and a description at 1024 (``tools/skills_tool_plugin.py``). This module
does the same, and turns the keys Hermes recognises into one normalised shape so the
gating, setup and disclosure rows read typed values instead of raw YAML.

Everything here is metadata. A declared environment-variable NAME is recorded; no
value is ever read, and any capture of one belongs to the secret broker in the setup
rows. Imported frontmatter is third-party text, so every list and string is bounded,
every nested value is bounded in total size as well as depth and width (YAML aliases
expand a 2 KB file into billions of nodes), and every value is reduced to plain,
finite JSON types (a YAML date, a NaN or a hex integer past Python's ``str()`` limit
would otherwise break discovery or the routes that serialise a skill).
"""
from __future__ import annotations

import datetime
import itertools
import math
import re
from typing import Any

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_LIST_ITEMS = 64
MAX_FIELD_CHARS = 1024
MAX_NODES = 2048
_MAX_DEPTH = 6
_MAX_INT_BITS = 64
_BOM = "\ufeff"

# Hermes' PLATFORM_MAP: a declared platform matches the host whose sys.platform starts
# with the mapped value. Nerva stores the OS under its human name.
_HERMES_PLATFORM_MAP = {"macos": "darwin", "linux": "linux", "windows": "win32"}
_SYS_PLATFORM_NAMES = (("darwin", "macos"), ("linux", "linux"), ("win32", "windows"))
_ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HERMES_LIST_KEYS = ("supersedes", "session_platforms", "requires_toolsets", "requires_tools",
                     "fallback_for_toolsets", "fallback_for_tools")
_CONTAINERS = (dict, list, tuple, set)


def split_frontmatter(content: str, *, lenient: bool = True) -> tuple[dict | None, str]:
    """``(frontmatter, body)``, or ``(None, content)`` when there is no fenced block.

    A block that parses to something other than a mapping is not frontmatter
    either, so the caller keeps its own fallback for such files. With ``lenient``
    (the loader's reading), a block that is not valid YAML is read line by line as
    ``key: value``, as Hermes does; identity decisions pass ``lenient=False`` so a
    name only that fallback can find never decides one.
    """
    content = content.removeprefix(_BOM)
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, content
    for i in range(1, len(lines)):
        # Column 0 only, as Hermes' ``\n---\s*\n`` requires: an indented ``---``
        # inside a block scalar is content, not the end of the block.
        if lines[i].rstrip() != "---":
            continue
        block = "\n".join(lines[1:i])
        body = "\n".join(lines[i + 1:])
        try:
            import yaml

            data = yaml.safe_load(block)
        except Exception:
            if not lenient:
                return None, content
            data = _naive_key_values(block)
            # Neither a name nor a description: this was never YAML frontmatter
            # (a heading-dialect file framed by fences), so the heading parser reads it.
            if not (data.get("name") or data.get("description")):
                return None, content
        return (data, body) if isinstance(data, dict) else (None, content)
    return None, content


def _naive_key_values(block: str) -> dict:
    """Hermes' ``key: value`` fallback, kept to top-level keys.

    Hermes splits every line on its first colon. Only column-0 keys count here, so an
    indented ``name:`` under ``metadata:`` cannot replace the skill's own, and a value
    wrapped in matching quotes loses them, as YAML would have read it.
    """
    out: dict = {}
    for line in block.split("\n"):
        if not line or line[0].isspace() or line[0] in "#-" or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return value.bit_length() <= _MAX_INT_BITS
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _scalar_text(value: Any) -> str:
    """``str(value)``, or ``""`` when there is no honest one.

    A hex or octal YAML integer escapes Python's 4,300-digit parse limit and then
    ``str()`` raises; a NaN or an infinity has no JSON form.
    """
    if isinstance(value, (int, float)) and not _finite_number(value):
        return ""
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return ""


def json_safe(value: Any) -> Any:
    """Plain, finite JSON types, bounded in depth, width, string length and total nodes."""
    return _json_safe(value, 0, [MAX_NODES])


def _json_safe(value: Any, depth: int, budget: list[int]) -> Any:
    budget[0] -= 1
    if budget[0] < 0:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if _finite_number(value) else None
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS]
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if depth >= _MAX_DEPTH:
        return None
    if isinstance(value, dict):
        out: dict = {}
        for key, item in itertools.islice(value.items(), MAX_LIST_ITEMS):
            if budget[0] <= 0:
                break
            out[_scalar_text(key)[:MAX_FIELD_CHARS]] = _json_safe(item, depth + 1, budget)
        return out
    if isinstance(value, (list, tuple, set)):
        items: list = []
        for item in itertools.islice(value, MAX_LIST_ITEMS):
            if budget[0] <= 0:
                break
            items.append(_json_safe(item, depth + 1, budget))
        return items
    return _scalar_text(value)[:MAX_FIELD_CHARS]


def text(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    """A scalar as a stripped string; a list, mapping or null reads as empty."""
    if value is None or isinstance(value, _CONTAINERS):
        return ""
    return _scalar_text(value).strip()[:limit].strip()


def joined(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    """A scalar as text; a list (``author: [a, b]``) as its items joined with ``, ``."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str_list(value))[:limit].strip()
    return text(value, limit)


def _items(value: Any) -> list:
    """Hermes' ``value if isinstance(value, list) else [value]``, bounded, empties dropped."""
    if not value:
        return []
    return list(itertools.islice(value, MAX_LIST_ITEMS)) if isinstance(value, list) else [value]


def str_list(value: Any) -> list[str]:
    """A list, a ``[a, b]`` string or an ``a, b`` string, as non-empty strings (Hermes' _parse_tags)."""
    if value is None or isinstance(value, dict) or (isinstance(value, str) and not value):
        return []
    if isinstance(value, (list, tuple, set)):
        parts = (text(v) for v in value if v is not None and not isinstance(v, _CONTAINERS))
    else:
        raw = text(value)
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        parts = (part.strip().strip("\"'") for part in raw.split(","))
    return list(itertools.islice((part for part in parts if part), MAX_LIST_ITEMS))


def _one_or_many(value: Any) -> list[str]:
    """A list, or one string as ONE item (Hermes never splits these on commas)."""
    return [item for item in (text(v) for v in _items(value) if not isinstance(v, _CONTAINERS)) if item]


def normalize_platforms(value: Any) -> list[str]:
    """``platforms:`` as Hermes matches it, stored under Nerva's OS names.

    A list, or one string as one name (``"macos, linux"`` is a single name that
    matches no host). A name maps through Hermes' PLATFORM_MAP and matches the host
    whose ``sys.platform`` starts with it (so ``darwin`` and ``win`` count, ``osx``
    and ``win64`` do not); an unmatched name is kept, lowercased, so a platform gate
    refuses it on every host, as Hermes hides it.
    """
    out: list[str] = []
    for item in _one_or_many(value):
        declared = item.lower()
        mapped = _HERMES_PLATFORM_MAP.get(declared, declared)
        name = next((nerva for sys_platform, nerva in _SYS_PLATFORM_NAMES if sys_platform.startswith(mapped)),
                    declared)
        if name not in out:
            out.append(name)
    return out


def normalize_environments(value: Any) -> list[str]:
    """``environments:`` tags, lowercased; a string is one tag (Hermes' skill_matches_environment)."""
    out: list[str] = []
    for item in _one_or_many(value):
        tag = item.lower()
        if tag not in out:
            out.append(tag)
    return out


def requires_apps(value: Any) -> list[str]:
    """``requires_apps:`` names, a list or one name (Hermes' _requires_apps_list)."""
    return _one_or_many(value)


def first_body_line(body: str) -> str:
    """The first non-empty, non-heading body line: Hermes' listing description when none is declared."""
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _dict_list(raw: Any) -> list:
    return [raw] if isinstance(raw, dict) else list(itertools.islice(raw, MAX_LIST_ITEMS)) if isinstance(raw, list) else []


def _clean(value: Any) -> str | None:
    return value.strip()[:MAX_FIELD_CHARS] if isinstance(value, str) and value.strip() else None


def required_environment_variables(fm: dict) -> list[dict]:
    """Hermes' ``_get_required_environment_variables``: one deduped list, first entry wins.

    Sources, in order: ``required_environment_variables`` (names or mappings),
    ``setup.collect_secrets`` and the legacy ``prerequisites.env_vars``. A name that
    is not an environment-variable name is dropped. ``optional`` is read for truth,
    as Hermes reads it.
    """
    setup = fm.get("setup") if isinstance(fm.get("setup"), dict) else {}
    setup_help = _clean(setup.get("help"))
    prereqs = fm.get("prerequisites")
    legacy = (prereqs.get("env_vars") if isinstance(prereqs, dict) else None) or []
    legacy = [legacy] if isinstance(legacy, str) else legacy if isinstance(legacy, list) else []
    entries = [{"name": item} if isinstance(item, str) else item
               for item in _dict_list(fm.get("required_environment_variables"))
               if isinstance(item, (str, dict))]
    entries += [{"name": item.get("env_var"), "prompt": item.get("prompt"),
                 "url": text(item.get("provider_url") or item.get("url")) or None}
                for item in _dict_list(setup.get("collect_secrets")) if isinstance(item, dict)]
    entries += [{"name": name} for name in (text(v) for v in legacy[:MAX_LIST_ITEMS]) if name]
    required: dict[str, dict] = {}
    for entry in entries:
        name = text(entry.get("name") or entry.get("env_var"))
        if not name or name in required or len(name) > 128 or not _ENV_VAR_NAME.match(name):
            continue
        normalized: dict = {"name": name,
                            "prompt": text(entry.get("prompt")) or f"Enter value for {name}"}
        help_text = _clean(entry.get("help") or entry.get("provider_url") or entry.get("url") or setup_help)
        if help_text:
            normalized["help"] = help_text
        required_for = _clean(entry.get("required_for"))
        if required_for:
            normalized["required_for"] = required_for
        if entry.get("optional"):
            normalized["optional"] = True
        required[name] = normalized
        if len(required) >= MAX_LIST_ITEMS:
            break
    return list(required.values())


def credential_files(value: Any) -> list[dict]:
    """``required_credential_files`` entries (a path string or a mapping with ``path``)."""
    out: list[dict] = []
    for entry in value[:MAX_LIST_ITEMS] if isinstance(value, list) else []:
        if isinstance(entry, dict):
            path = text(entry.get("path") or entry.get("name"))
            item = {"path": path}
            description = text(entry.get("description"))
            if description:
                item["description"] = description
        elif isinstance(entry, str):
            path = text(entry)
            item = {"path": path}
        else:
            continue
        if path:
            out.append(item)
    return out


def config_vars(raw: Any) -> list[dict]:
    """``metadata.hermes.config``: entries need a key and a description; first key wins."""
    result: dict[str, dict] = {}
    for item in _dict_list(raw):
        if not isinstance(item, dict):
            continue
        key, desc = text(item.get("key")), text(item.get("description"))
        if not key or key in result or not desc:
            continue
        entry: dict = {"key": key, "description": desc}
        if item.get("default") is not None:
            entry["default"] = json_safe(item["default"])
        entry["prompt"] = text(item.get("prompt")) or desc
        result[key] = entry
    return list(result.values())


def _raw_hermes(fm: dict) -> dict:
    metadata = fm.get("metadata")
    raw = metadata.get("hermes") if isinstance(metadata, dict) else None
    return raw if isinstance(raw, dict) else {}


def hermes_metadata(fm: dict) -> dict:
    """``metadata.hermes`` normalised; every key present, empty when absent or malformed."""
    raw = _raw_hermes(fm)
    out: dict = {"tags": str_list(raw.get("tags")), "category": text(raw.get("category")),
                 "upstream_skill": text(raw.get("upstream_skill"))}
    for key in _HERMES_LIST_KEYS:
        out[key] = str_list(raw.get(key))
    out["config"] = config_vars(raw.get("config"))
    return out


def cap_description(value: Any) -> str:
    """Hermes' listing cap: past 1024 characters, 1021 of them and ``...``. Quotes stay."""
    desc = text(value, limit=MAX_DESCRIPTION_LENGTH + 1)
    if len(desc) > MAX_DESCRIPTION_LENGTH:
        return desc[: MAX_DESCRIPTION_LENGTH - 3] + "..."
    return desc


def contract_fields(fm: dict) -> dict:
    """Every recognised key beyond the loader's original eight, normalised."""
    hermes = hermes_metadata(fm)
    raw_hermes = _raw_hermes(fm)
    setup = fm.get("setup")
    prereqs = fm.get("prerequisites")
    return {
        "homepage": text(fm.get("homepage")),
        "compatibility": text(fm.get("compatibility")),
        "platforms": normalize_platforms(fm.get("platforms")),
        "environments": normalize_environments(fm.get("environments")),
        "requires_apps": requires_apps(fm.get("requires_apps")),
        "triggers": str_list(fm.get("triggers")),
        "dependencies": str_list(fm.get("dependencies")),
        # A declared metadata.hermes.* value wins over the top-level key, as in Hermes'
        # skill_view (``hermes_meta.get(k) or frontmatter.get(k)``, parsed after).
        "tags": str_list(raw_hermes.get("tags") or fm.get("tags")),
        "related_skills": str_list(raw_hermes.get("related_skills") or fm.get("related_skills")),
        "setup": json_safe(setup) if isinstance(setup, dict) else {},
        "prerequisites": json_safe(prereqs) if isinstance(prereqs, dict) else {},
        "required_environment_variables": required_environment_variables(fm),
        "required_credential_files": credential_files(fm.get("required_credential_files")),
        "hermes": hermes,
    }
