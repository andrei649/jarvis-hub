"""
grammar.py — H13.2 Constrained decoding (GBNF grammar generation).

Generates a llama.cpp **GBNF** grammar from a JSON schema (e.g. a tool's
parameter spec). Feeding the grammar to a grammar-capable backend constrains
decoding so the model can *only* emit JSON that matches the schema — tool-args
are valid by construction, eliminating validation-retry round-trips ($0 cost,
big reliability win).

Pure-Python and offline: this module produces the grammar string (and a light
`validate_args` fallback for backends without grammar support). The actual
enforcement is the backend's job (pass `grammar=` to llama.cpp / use XGrammar).
"""

from __future__ import annotations

import json
from typing import Optional

# GBNF primitive rules shared by every generated grammar.
_PRIMITIVES = {
    "ws": r"[ \t\n]*",
    "string": r'"\"" ( [^"\\] | "\\" . )* "\""',
    "integer": r'"-"? [0-9]+',
    "number": r'"-"? [0-9]+ ( "." [0-9]+ )?',
    "boolean": r'"true" | "false"',
    "null": r'"null"',
    # permissive any-JSON value, used when a property has no declared type
    "value": r'string | number | boolean | null | object | array',
    "object": r'"{" ws ( string ws ":" ws value ( ws "," ws string ws ":" ws value )* )? ws "}"',
    "array": r'"[" ws ( value ( ws "," ws value )* )? ws "]"',
}


class _Builder:
    def __init__(self) -> None:
        self.rules: dict[str, str] = {}
        self._n = 0

    def _fresh(self, base: str) -> str:
        self._n += 1
        return f"{base}{self._n}"

    def _need(self, name: str) -> None:
        if name not in _PRIMITIVES or name in self.rules:
            return
        self.rules[name] = _PRIMITIVES[name]
        # value/object/array form a mutually-recursive cluster over the scalars —
        # pull the whole permissive closure so no reference is left dangling.
        if name in ("value", "object", "array"):
            for dep in ("ws", "string", "number", "boolean", "null", "value", "object", "array"):
                self._need(dep)

    def ref(self, schema: dict) -> str:
        """Return a rule reference (token) for *schema*, emitting rules as needed."""
        if not isinstance(schema, dict):
            self._need("value")
            return "value"
        if "enum" in schema:
            return self._enum_rule(schema["enum"])
        t = schema.get("type")
        if t in ("string", "integer", "number", "boolean", "null"):
            self._need(t)
            return t
        if t == "array":
            return self._array_rule(schema.get("items", {}))
        if t == "object":
            return self._object_rule(schema)
        self._need("value")
        return "value"

    def _enum_rule(self, values: list) -> str:
        alts = " | ".join(_quote(v) for v in values) or '"\\"\\""'
        name = self._fresh("enum")
        self.rules[name] = alts
        return name

    def _array_rule(self, items: dict) -> str:
        self._need("ws")
        item_ref = self.ref(items) if items else self._any_value()
        name = self._fresh("array")
        self.rules[name] = f'"[" ws ( {item_ref} ( ws "," ws {item_ref} )* )? ws "]"'
        return name

    def _any_value(self) -> str:
        self._need("value")
        return "value"

    def _object_rule(self, schema: dict) -> str:
        self._need("ws")
        props: dict = schema.get("properties", {}) or {}
        # Emit ALL declared properties in declared order (required ones first to
        # keep a stable key order). The grammar fixes key order and presence; the
        # `required` distinction is enforced by validate_args, since GBNF for
        # arbitrarily-ordered optional keys is impractical.
        required = list(schema.get("required") or [])
        rest = [k for k in props if k not in required]
        keys = [k for k in required if k in props] + rest
        if not keys:
            self._need("object")
            return "object"
        segments = []
        for k in keys:
            child = self.ref(props[k])
            segments.append(f'"\\"{k}\\"" ws ":" ws {child}')
        body = '"{" ws ' + ' ws "," ws '.join(segments) + ' ws "}"'
        name = self._fresh("obj")
        self.rules[name] = body
        return name


def _quote(v) -> str:
    """A GBNF literal matching the JSON encoding of *v*."""
    return '"' + json.dumps(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def json_schema_to_gbnf(schema: dict, root_name: str = "root") -> str:
    """Convert a JSON schema into a GBNF grammar string (root rule first)."""
    b = _Builder()
    top = b.ref(schema or {})
    lines = [f"{root_name} ::= {top}"]
    for name, body in b.rules.items():
        lines.append(f"{name} ::= {body}")
    return "\n".join(lines)


def tool_to_gbnf(tool: dict) -> str:
    """GBNF for a tool's arguments object.

    Accepts the common shapes: ``{"parameters": <schema>}`` (OpenAI-style) or
    ``{"input_schema": <schema>}`` (Anthropic-style), or a bare schema.
    """
    schema = (tool or {}).get("parameters") or (tool or {}).get("input_schema") or tool or {}
    return json_schema_to_gbnf(schema)


def validate_args(obj, schema: dict) -> dict:
    """Light fallback validator (backends without grammar support).

    Returns {ok, errors}. Checks types, required keys, and enums — not a full
    JSON-Schema implementation, just the shapes tool-calling needs.
    """
    errors: list[str] = []
    _validate(obj, schema or {}, "$", errors)
    return {"ok": not errors, "errors": errors}


_TYPE_CHECK = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _validate(value, schema: dict, path: str, errors: list) -> None:
    if not isinstance(schema, dict):
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']}")
        return
    t = schema.get("type")
    if t and t in _TYPE_CHECK and not _TYPE_CHECK[t](value):
        errors.append(f"{path}: expected {t}, got {type(value).__name__}")
        return
    if t == "object":
        props = schema.get("properties", {}) or {}
        for req in schema.get("required", []):
            if not isinstance(value, dict) or req not in value:
                errors.append(f"{path}.{req}: required")
        if isinstance(value, dict):
            for k, v in value.items():
                if k in props:
                    _validate(v, props[k], f"{path}.{k}", errors)
    elif t == "array" and isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{i}]", errors)
