"""The SKILL.md frontmatter contract (H327), shared by the loader and the importer.

agentskills.io / Hermes write a YAML block between ``---`` fences at the top of a
SKILL.md. Hermes parses it defensively (``agent/skill_utils.parse_frontmatter``): a
leading UTF-8 byte-order mark is dropped before the fence check, and a block that is
not valid YAML falls back to ``key: value`` lines instead of losing the file. The
listing caps a name at 64 characters and a description at 1024
(``tools/skills_tool_plugin.py``). This module does the same, and turns the keys
Hermes recognises into one normalised shape so the gating, setup and disclosure rows
read typed values instead of raw YAML.

Everything here is metadata. A declared environment-variable NAME is recorded; no
value is ever read, and any capture of one belongs to the secret broker in the setup
rows. Imported frontmatter is third-party text, so every list and string is bounded
and every value is reduced to plain JSON types (a YAML date would otherwise break the
routes that serialise a skill).
"""
from __future__ import annotations

import datetime
import re
from typing import Any

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_LIST_ITEMS = 64
MAX_FIELD_CHARS = 1024
_MAX_DEPTH = 6
_BOM = "﻿"

# One vocabulary for the host OS: Hermes maps these to sys.platform prefixes
# (macos→darwin, windows→win32); Nerva stores the human name and maps aliases in.
_PLATFORM_ALIASES = {
    "macos": "macos", "mac": "macos", "osx": "macos", "darwin": "macos",
    "linux": "linux",
    "windows": "windows", "win": "windows", "win32": "windows", "win64": "windows",
}
_ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HERMES_LIST_KEYS = ("supersedes", "session_platforms", "requires_toolsets", "requires_tools",
                     "fallback_for_toolsets", "fallback_for_tools")


def split_frontmatter(content: str) -> tuple[dict | None, str]:
    """``(frontmatter, body)``, or ``(None, content)`` when there is no fenced block.

    A block that parses to something other than a mapping is not frontmatter
    either, so the caller keeps its own fallback for such files. A block that is
    not valid YAML is read line by line as ``key: value``, as Hermes does.
    """
    content = content.removeprefix(_BOM)
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, content
    for i in range(1, len(lines)):
        if lines[i].strip() != "---":
            continue
        block = "\n".join(lines[1:i])
        body = "\n".join(lines[i + 1:])
        try:
            import yaml

            data = yaml.safe_load(block)
        except Exception:
            data = _naive_key_values(block)
        return (data, body) if isinstance(data, dict) else (None, content)
    return None, content


def _naive_key_values(block: str) -> dict:
    out: dict = {}
    for line in block.strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip():
                out[key.strip()] = value.strip()
    return out


def json_safe(value: Any, depth: int = 0) -> Any:
    """Plain JSON types only, bounded in depth, length and item count."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS]
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if depth >= _MAX_DEPTH:
        return None
    if isinstance(value, dict):
        return {str(k)[:MAX_FIELD_CHARS]: json_safe(v, depth + 1)
                for k, v in list(value.items())[:MAX_LIST_ITEMS]}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v, depth + 1) for v in list(value)[:MAX_LIST_ITEMS]]
    return str(value)[:MAX_FIELD_CHARS]


def text(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    """A scalar as a stripped string; a list, mapping or null reads as empty."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        value = value.isoformat()
    return str(value).strip()[:limit]


def str_list(value: Any) -> list[str]:
    """A list, a ``[a, b]`` string or an ``a, b`` string, as non-empty strings (Hermes' _parse_tags)."""
    if value is None or value == "" or isinstance(value, dict):
        return []
    if isinstance(value, (list, tuple, set)):
        items = [text(v) for v in list(value) if v is not None and not isinstance(v, (dict, list))]
    else:
        raw = text(value)
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        items = [part.strip().strip("\"'") for part in raw.split(",")]
    return [item for item in items if item][:MAX_LIST_ITEMS]


def normalize_platforms(value: Any) -> list[str]:
    out: list[str] = []
    for item in str_list(value):
        name = _PLATFORM_ALIASES.get(item.lower(), item.lower())
        if name not in out:
            out.append(name)
    return out


def _dict_list(raw: Any) -> list:
    return [raw] if isinstance(raw, dict) else list(raw)[:MAX_LIST_ITEMS] if isinstance(raw, list) else []


def _clean(value: Any) -> str | None:
    return value.strip()[:MAX_FIELD_CHARS] if isinstance(value, str) and value.strip() else None


def required_environment_variables(fm: dict) -> list[dict]:
    """Hermes' ``_get_required_environment_variables``: one deduped list, first entry wins.

    Sources, in order: ``required_environment_variables`` (names or mappings),
    ``setup.collect_secrets`` and the legacy ``prerequisites.env_vars``. A name that
    is not an environment-variable name is dropped.
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
                 "url": str(item.get("provider_url") or item.get("url") or "").strip() or None}
                for item in _dict_list(setup.get("collect_secrets")) if isinstance(item, dict)]
    entries += [{"name": str(v)} for v in legacy[:MAX_LIST_ITEMS] if str(v).strip()]
    required: dict[str, dict] = {}
    for entry in entries:
        name = str(entry.get("name") or entry.get("env_var") or "").strip()
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
        if entry.get("optional") is True:
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
            path = entry.strip()[:MAX_FIELD_CHARS]
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
    desc = text(value, limit=10 * MAX_DESCRIPTION_LENGTH).strip("'\"")
    if len(desc) > MAX_DESCRIPTION_LENGTH:
        return desc[: MAX_DESCRIPTION_LENGTH - 3] + "..."
    return desc


def contract_fields(fm: dict) -> dict:
    """Every recognised key beyond the loader's original eight, normalised."""
    hermes = hermes_metadata(fm)
    setup = fm.get("setup")
    prereqs = fm.get("prerequisites")
    return {
        "homepage": text(fm.get("homepage")),
        "compatibility": text(fm.get("compatibility")),
        "platforms": normalize_platforms(fm.get("platforms")),
        "environments": [env.lower() for env in str_list(fm.get("environments"))],
        "triggers": str_list(fm.get("triggers")),
        "dependencies": str_list(fm.get("dependencies")),
        # metadata.hermes.* wins over the top-level key (Hermes' skill_view order).
        "tags": hermes["tags"] or str_list(fm.get("tags")),
        "related_skills": str_list(_raw_hermes(fm).get("related_skills")) or str_list(fm.get("related_skills")),
        "setup": json_safe(setup) if isinstance(setup, dict) else {},
        "prerequisites": json_safe(prereqs) if isinstance(prereqs, dict) else {},
        "required_environment_variables": required_environment_variables(fm),
        "required_credential_files": credential_files(fm.get("required_credential_files")),
        "hermes": hermes,
    }
