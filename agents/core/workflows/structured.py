"""
structured.py — H10.10 Structured Agent Outputs (Pydantic).

Lets a workflow step declare an expected output schema; the engine then extracts
JSON from the agent's reply, validates/coerces it against a dynamically-built
Pydantic model, and exposes the typed fields to downstream steps (so a template
can reference ``{step.field}``).

Schema format (intentionally small)::

    {"fields": {
        "sentiment": {"type": "str", "required": true},
        "score":     {"type": "float", "required": false, "default": 0.0}
    }}
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel, ValidationError, create_model

_PY_TYPES: dict[str, Any] = {
    "str": str, "string": str,
    "int": int, "integer": int,
    "float": float, "number": float,
    "bool": bool, "boolean": bool,
    "list": list, "array": list,
    "dict": dict, "object": dict,
}

# ```json ... ``` fenced block, or the first bare {...} object.
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> Optional[dict]:
    """Pull a JSON object out of a free-form agent reply (fenced or bare)."""
    if not text:
        return None
    for pat in (_FENCE, _BARE):
        m = pat.search(text)
        if m:
            candidate = m.group(1) if pat is _FENCE else m.group(0)
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def build_model(schema: dict) -> type[BaseModel]:
    """Build a Pydantic model from a small field schema. Raises ValueError on bad schema."""
    fields = (schema or {}).get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ValueError("schema must contain a non-empty 'fields' object")
    definitions: dict[str, tuple] = {}
    for name, spec in fields.items():
        spec = spec or {}
        py_type = _PY_TYPES.get(str(spec.get("type", "str")).lower(), str)
        required = spec.get("required", True)
        default = ... if required else spec.get("default", None)
        if not required and default is None:
            definitions[name] = (Optional[py_type], None)
        else:
            definitions[name] = (py_type, default)
    return create_model("StructuredOutput", **definitions)


def validate_output(text: str, schema: dict) -> dict:
    """Return {"ok", "data", "error"} from validating *text* against *schema*."""
    try:
        model = build_model(schema)
    except ValueError as e:
        return {"ok": False, "data": None, "error": f"bad schema: {e}"}

    raw = extract_json(text)
    if raw is None:
        return {"ok": False, "data": None, "error": "no JSON object found in output"}

    try:
        obj = model(**raw)
    except ValidationError as e:
        return {"ok": False, "data": None, "error": str(e)}
    return {"ok": True, "data": obj.model_dump(), "error": ""}
