"""Read-only project records from a compact vault index."""

import json
import re

INDEX_PATH = "Projects/index.json"
REGISTER_DIR = "Projects/Register"
SCHEMA = "project-index/v1"
MAX_BYTES = 1 << 20
_FIELDS = ("id", "n", "fr", "st", "rec", "bl", "ai", "sc", "mc", "par", "pas")
_LABELS = {
    "fr": "Front", "st": "Stadiu (0–5)", "rec": "Recomandare", "bl": "Blocaj",
    "ai": "Autonomie agent", "sc": "Scor de finalizare (0–100)", "mc": "Mission Control în registru",
    "par": "Proiect părinte", "pas": "Pas următor",
}
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_ID = re.compile(r"(?:PRJ-[0-9]{3}|WS-[a-z0-9]+(?:-[a-z0-9]+)*)")
_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", re.I)


def settings(cfg: dict) -> tuple[str, str, str]:
    """Validate private, vault-relative index settings before opening any file."""
    paths = []
    for key, default in (("projectIndexPath", INDEX_PATH), ("projectRegisterDir", REGISTER_DIR)):
        value = cfg.get(key, default)
        if not isinstance(value, str) or not value or value != value.strip() or "\\" in value:
            raise ValueError("invalid project path")
        parts = value.split("/")
        if any(part in ("", ".", "..") or part != part.strip() or part.startswith(".") or part.endswith(".")
               or _BAD_NAME.search(part) or _DEVICE.fullmatch(part) for part in parts):
            raise ValueError("invalid project path")
        paths.append(value)
    if not paths[0].lower().endswith(".json"):
        raise ValueError("invalid project index filename")
    schema = cfg.get("projectIndexSchema", SCHEMA)
    if not isinstance(schema, str) or not schema or len(schema) > 128 or any(ord(c) < 32 for c in schema):
        raise ValueError("invalid project schema")
    return paths[0], paths[1], schema


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("invalid JSON number")


def _text(value, limit=4096):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("invalid project text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("invalid project text") from exc
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("control character in project text")
    return value


def project_records(data: bytes, *, index_path: str = INDEX_PATH, schema: str = SCHEMA) -> list[dict]:
    """Validate a bounded index and return searchable, source-labelled metadata."""
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError("invalid project index size")
    try:
        root = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_keys,
                          parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid project index JSON") from exc
    if not isinstance(root, dict) or root.get("schema") != schema:
        raise ValueError("unsupported project index schema")
    items = root.get("items")
    if not isinstance(items, list) or len(items) > 1000:
        raise ValueError("invalid project item count")

    records = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid project item")
        project_id = _text(item.get("id"), 80)
        name = _text(item.get("n"), 255)
        if not _ID.fullmatch(project_id) or project_id in seen:
            raise ValueError("invalid or duplicate project ID")
        if (not name.lower().endswith(".md") or not name[:-3].strip()
                or name != name.strip() or _BAD_NAME.search(name)
                or _DEVICE.fullmatch(name) or name[:-3].endswith(".")):
            raise ValueError("invalid project filename")
        seen.add(project_id)

        values = {}
        for field in _FIELDS[2:]:
            value = item.get(field)
            if value is None:
                continue
            if field in ("st", "sc"):
                upper = 5 if field == "st" else 100
                if type(value) is not int or not 0 <= value <= upper:
                    raise ValueError("invalid project number")
            else:
                value = _text(value)
            values[field] = value

        details = [f"{name[:-3]} · {project_id}"]
        details.extend(f"{_LABELS[field]}: {value}" for field, value in values.items() if value != "")
        records.append({
            "projectId": project_id,
            "title": name[:-3],
            "noteFile": name,
            "relPath": f"{index_path}#{project_id}",
            "body": "\n".join(details),
            "tags": ["proiect", project_id],
        })
    return records
