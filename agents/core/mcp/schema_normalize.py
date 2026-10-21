"""schema_normalize.py — provider-agnostic repair of a third-party MCP tool schema (H557).

An MCP server hands us ``inputSchema`` in whatever dialect its framework emits —
Pydantic v1 ``definitions``, nullable unions, ``required`` naming undeclared fields,
nodes with no ``type``, bare ``{"type": "object"}``. Five provider serializers
(Anthropic, OpenAI Chat via ``ToolSpec.as_openai``, OpenAI Responses, xAI Responses,
Gemini) each have their own tolerance for those quirks, and before this module only
the Gemini path repaired any of them.

:func:`normalize_mcp_input_schema` runs once, at registration (``MCPTool``), ahead of
every serializer, so all five ship the same repaired schema:

1. the root ``definitions`` is promoted to ``$defs`` and every ``#/definitions/...``
   reference, under any subschema keyword (``if``/``then``/``else``, ``dependencies`` and
   ``additionalItems`` included), is rewritten to ``#/$defs/...``; a name both blocks
   define differently keeps both shapes (the legacy one moves to ``<name>__definitions``
   and only its own references follow it); a nested ``definitions`` block is kept
   (normalized in place), so a pointer into it still resolves;
2. a nullable union — ``anyOf``/``oneOf`` with exactly one non-null branch next to
   ``{"type": "null"}`` — collapses to that branch, and a ``default: null`` goes with it.
   A property its object lists in ``required`` (Pydantic ``Optional[X]`` with no default)
   stays nullable: a typed branch becomes ``"type": [X, "null"]`` and an untyped one
   (a ``$ref``) keeps its union, so the model can still send an explicit null;
   a one-element ``allOf`` (Pydantic's ``allOf: [{"$ref": ...}]`` next to a ``default``)
   is merged into its siblings with ``properties`` and ``required`` unioned, and left as
   it is whenever merging would lose a constraint, so no serializer loses a shape;
3. ``required`` is pruned to the names ``properties`` actually declares;
4. a node with no ``type`` gets one inferred from its shape (``properties`` → object,
   ``items`` → array, homogeneous ``enum``/``const`` → its scalar type);
5. every object carries an explicit ``properties`` map, and the root is always one.

The function is pure (it never mutates its input), idempotent and depth-bounded.

:func:`mcp_provider_name` turns ``server`` + ``tool`` into the model-facing function
name ``mcp__<server>__<tool>``: only ``[A-Za-z0-9_]`` survives, the result fits the
64-character limit Anthropic and OpenAI enforce (an over-long name is cut and suffixed
with a digest of the original pair, so it stays deterministic and distinct), and the
``mcp__`` prefix keeps a third-party tool out of the built-in tool namespace.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

PROVIDER_NAME_PREFIX = "mcp__"
PROVIDER_NAME_MAX = 64
#: Nesting deeper than this is replaced by an unconstrained ``{}`` node.
MAX_SCHEMA_DEPTH = 32
#: Wrapper collapses (nullable unions, one-element ``allOf``) one node may unwrap; a
#: chain longer than this is degenerate and becomes ``{}`` instead of recursing.
MAX_COLLAPSES = 256

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_]")
_LEGACY_REF = "#/definitions/"
_DEFS_REF = "#/$defs/"
_DIGEST_CHARS = 10
_SCHEMA_LIST_KEYS = ("anyOf", "oneOf", "allOf", "prefixItems")
_SCHEMA_MAP_KEYS = (
    "properties", "patternProperties", "$defs", "definitions", "dependentSchemas",
)
#: Every keyword whose value is one subschema (or, for ``items``/``additionalItems`` in
#: draft-07, a list of them): each is walked, so no ``#/definitions/...`` reference under
#: it is left pointing at the removed root ``definitions``.
_SCHEMA_KEYS = (
    "items", "additionalProperties", "not", "contains", "if", "then", "else",
    "additionalItems", "propertyNames", "unevaluatedItems", "unevaluatedProperties",
    "contentSchema",
)
#: Keywords that only annotate a schema: when a one-element ``allOf`` is merged into its
#: node and both carry one of these, the node's own value wins without losing a constraint.
_ANNOTATION_KEYS = frozenset({
    "title", "description", "default", "examples", "deprecated", "readOnly", "writeOnly",
    "$comment",
})
_UNSET = object()


def _empty_object() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


def _is_null_branch(variant: Any) -> bool:
    return isinstance(variant, dict) and variant.get("type") == "null" and len(variant) == 1


def _scalar_type(values: list[Any]) -> str | None:
    if not values:
        return None
    if all(isinstance(v, str) for v in values):
        return "string"
    if all(isinstance(v, bool) for v in values):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return "integer"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return "number"
    return None


def _infer_type(node: dict[str, Any]) -> str | None:
    """The ``type`` a node's shape implies (``properties`` → object, ``items`` → array,
    a homogeneous ``enum``/``const`` → its scalar type), or None."""
    if isinstance(node.get("properties"), dict):
        return "object"
    if "items" in node or "prefixItems" in node:
        return "array"
    if isinstance(node.get("enum"), list):
        return _scalar_type(node["enum"])
    if "const" in node:
        return _scalar_type([node["const"]])
    return None


def _collapse_nullable(node: dict[str, Any], keep_null: bool = False) -> dict[str, Any] | None:
    """The single non-null branch merged with *node*'s siblings, or None.

    ``keep_null`` (the property is ``required``) keeps the null admissible: a branch
    with a plain ``type`` (given, or inferred from its shape) gains ``"null"`` in it and
    an ``enum`` gains ``None``; any other branch is left as a union.
    """
    for key in ("anyOf", "oneOf"):
        variants = node.get(key)
        if not isinstance(variants, list) or len(variants) < 2:
            continue
        rest = [v for v in variants if not _is_null_branch(v)]
        if len(rest) != 1 or len(rest) == len(variants) or not isinstance(rest[0], dict):
            continue
        siblings = {k: v for k, v in node.items() if k != key}
        branch = dict(rest[0])
        if keep_null:
            if "const" in branch:
                return None  # a const cannot also admit null without staying a union
            kind = branch.get("type")
            if kind is None and "$ref" not in branch and not any(
                k in branch for k in ("anyOf", "oneOf", "allOf")
            ):
                # Inferred here rather than on a second pass, so one pass already
                # reaches the fixed point (the normalizer is idempotent).
                kind = _infer_type(branch)
            if isinstance(kind, str):
                branch["type"] = [kind, "null"] if kind != "null" else kind
            elif isinstance(kind, list) and all(isinstance(k, str) for k in kind):
                branch["type"] = kind if "null" in kind else [*kind, "null"]
            else:
                return None
            enum = branch.get("enum")
            if isinstance(enum, list) and None not in enum:
                # An enum restricts the value too: without None it would still refuse
                # the null the type now admits.
                branch["enum"] = [*enum, None]
        elif siblings.get("default", _UNSET) is None:
            del siblings["default"]
        return {**branch, **siblings}
    return None


def _merge_required(left: Any, right: Any) -> list[Any] | None:
    if not isinstance(left, list) or not isinstance(right, list):
        return None
    merged: list[Any] = []
    for name in [*left, *right]:
        if name not in merged:
            merged.append(name)
    return merged


def _collapse_all_of(node: dict[str, Any]) -> dict[str, Any] | None:
    """A one-element ``allOf`` merged into its siblings, or None when that would lose
    a constraint.

    ``properties`` and ``required`` are unioned; any keyword both sides carry must agree,
    except an annotation (``title``, ``description``, ``default`` …), where the node's own
    value wins. Whatever cannot be merged without loss (two references, two different
    definitions of one property, conflicting ``type`` or validation keywords) keeps the
    ``allOf`` as it is, which every provider path accepts.
    """
    branches = node.get("allOf")
    if not isinstance(branches, list) or len(branches) != 1 or not isinstance(branches[0], dict):
        return None
    siblings = {k: v for k, v in node.items() if k != "allOf"}
    merged = dict(branches[0])
    for key, value in siblings.items():
        if key not in merged or merged[key] == value or key in _ANNOTATION_KEYS:
            merged[key] = value
        elif key == "properties":
            mine = merged[key]
            if not isinstance(mine, dict) or not isinstance(value, dict):
                return None
            if any(name in mine and mine[name] != sub for name, sub in value.items()):
                return None
            merged[key] = {**mine, **value}
        elif key == "required":
            union = _merge_required(merged[key], value)
            if union is None:
                return None
            merged[key] = union
        else:
            return None  # two references, or two different values of one constraint
    return merged


def _unwrap(node: dict[str, Any], keep_null: bool) -> dict[str, Any] | None:
    """Collapse wrapper nodes iteratively (never by recursion); None past the cap."""
    for _ in range(MAX_COLLAPSES):
        collapsed = _collapse_nullable(node, keep_null)
        if collapsed is None:
            collapsed = _collapse_all_of(node)
        if collapsed is None:
            return node
        node = collapsed
    return None


def _rewrite_legacy_ref(ref: str, renamed: dict[str, str]) -> str:
    """``#/definitions/<name>/…`` → ``#/$defs/<name, or its renamed key>/…``."""
    rest = ref[len(_LEGACY_REF):]
    segment, sep, tail = rest.partition("/")
    name = segment.replace("~1", "/").replace("~0", "~")
    if name in renamed:
        segment = renamed[name].replace("~", "~0").replace("/", "~1")
    return _DEFS_REF + segment + sep + tail


def _normalize_node(
    node: Any, depth: int, keep_null: bool = False, renamed: dict[str, str] | None = None,
) -> Any:
    if not isinstance(node, dict):
        return node if isinstance(node, bool) else {}
    if depth > MAX_SCHEMA_DEPTH:
        return {}
    unwrapped = _unwrap(node, keep_null)
    if unwrapped is None:
        return {}
    node = unwrapped
    raw_required = node.get("required")
    required_names = (
        {name for name in raw_required if isinstance(name, str)}
        if isinstance(raw_required, list) else set()
    )

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "$ref" and isinstance(value, str) and value.startswith(_LEGACY_REF):
            out[key] = _rewrite_legacy_ref(value, renamed or {})
        elif key in _SCHEMA_MAP_KEYS and isinstance(value, dict):
            out[key] = {
                str(name): _normalize_node(
                    sub, depth + 1, keep_null=key == "properties" and name in required_names,
                    renamed=renamed)
                for name, sub in value.items()
            }
        elif key == "dependencies" and isinstance(value, dict):
            # draft-07: each entry is a subschema or a list of property names.
            out[key] = {
                str(name): (_normalize_node(sub, depth + 1, renamed=renamed)
                            if isinstance(sub, dict) else copy.deepcopy(sub))
                for name, sub in value.items()
            }
        elif key in _SCHEMA_LIST_KEYS and isinstance(value, list):
            out[key] = [_normalize_node(sub, depth + 1, renamed=renamed) for sub in value]
        elif key in _SCHEMA_KEYS and isinstance(value, (dict, list)):
            out[key] = (
                [_normalize_node(sub, depth + 1, renamed=renamed) for sub in value]
                if isinstance(value, list)
                else _normalize_node(value, depth + 1, renamed=renamed)
            )
        else:
            # Leaf values (enum, default, examples …) are copied so the result never
            # aliases the server's own objects; one too deep to copy is dropped.
            try:
                out[key] = copy.deepcopy(value)
            except RecursionError:
                continue

    if "type" not in out and "$ref" not in out and not any(
        k in out for k in ("anyOf", "oneOf", "allOf")
    ):
        inferred = _infer_type(out)
        if inferred:
            out["type"] = inferred

    kind = out.get("type")
    if kind == "object" or (isinstance(kind, list) and "object" in kind):
        properties = out.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        out["properties"] = properties
    required = out.get("required")
    if "required" in out:
        declared = out.get("properties") if isinstance(out.get("properties"), dict) else {}
        kept: list[str] = []
        for name in required if isinstance(required, list) else []:
            if isinstance(name, str) and name in declared and name not in kept:
                kept.append(name)
        if kept:
            out["required"] = kept
        else:
            del out["required"]
    return out


def normalize_mcp_input_schema(schema: Any) -> dict[str, Any]:
    """A repaired copy of *schema* every provider serializer accepts (see module doc)."""
    if not isinstance(schema, dict):
        return _empty_object()
    root = dict(schema)
    legacy = root.pop("definitions", None)
    renamed: dict[str, str] = {}
    if isinstance(legacy, dict):
        existing = root.get("$defs")
        defs = dict(existing) if isinstance(existing, dict) else {}
        for raw_name, sub in legacy.items():
            name = str(raw_name)
            if name not in defs or defs[name] == sub:
                defs[name] = sub
                continue
            # Both blocks define this name differently: the legacy entry moves to a fresh
            # key and only ``#/definitions/<name>`` references follow it, so neither
            # shape replaces the other.
            fresh, n = f"{name}__definitions", 2
            while fresh in defs or fresh in legacy:
                fresh, n = f"{name}__definitions{n}", n + 1
            defs[fresh] = sub
            renamed[name] = fresh
        root["$defs"] = defs
    if "type" not in root and "properties" not in root:
        root["type"] = "object"
    out = _normalize_node(root, 0, renamed=renamed)
    if not isinstance(out, dict) or out.get("type") != "object":
        return _empty_object()
    return out


def _sanitize(part: Any) -> str:
    return _UNSAFE_NAME_CHARS.sub("_", str(part or "")) or "_"


def _digest(server: str, tool: str) -> str:
    raw = json.dumps([str(server), str(tool)], ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def mcp_provider_name(server: Any, tool: Any, *, hashed: bool = False) -> str:
    """``mcp__<server>__<tool>`` in ``[A-Za-z0-9_]{1,64}``.

    ``hashed=True`` (or an over-long name) appends a digest of the original pair, so two
    pairs that sanitize to the same text still get distinct, stable names.
    """
    name = f"{PROVIDER_NAME_PREFIX}{_sanitize(server)}__{_sanitize(tool)}"
    if not hashed and len(name) <= PROVIDER_NAME_MAX:
        return name
    suffix = "_" + _digest(str(server or ""), str(tool or ""))
    return name[: PROVIDER_NAME_MAX - len(suffix)] + suffix
