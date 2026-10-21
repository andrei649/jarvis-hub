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
3. ``required`` is pruned to the names ``properties`` actually declares — only on a node
   that has a ``properties`` map; a required-only subschema (``anyOf: [{"required":
   ["url"]}, {"required": ["path"]}]``, ``not: {"required": [...]}``) constrains its
   parent's instance and is left as it is;
4. a node with no ``type`` gets one inferred from its shape (``properties`` → object,
   ``items`` → array, homogeneous ``enum``/``const`` → its scalar type);
5. every object carries an explicit ``properties`` map (except a nested object that only
   lists ``required`` names), and the root is always one: a root ``type`` list holding
   ``"object"`` becomes ``"object"``, and the root is flattened so it carries no
   ``anyOf``/``oneOf``/``allOf``/``$ref``/``enum``/``not`` (Anthropic rejects a top-level
   combinator): a ``$ref`` is inlined, an ``allOf`` merged, and an ``anyOf``/``oneOf`` of
   objects becomes one object whose properties are the union of the branches', whose
   ``required`` is their intersection and whose description spells out the alternatives.

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
    required = out.get("required")
    if "required" in out and not isinstance(required, list):
        del out["required"]
        required = None
    is_object = kind == "object" or (isinstance(kind, list) and "object" in kind)
    # A nested object that only lists ``required`` names is a constraint on its parent's
    # instance (``anyOf: [{"type": "object", "required": ["url"]}, …]``): it keeps them
    # and gets no ``properties`` map, which would make the pruning below erase them.
    if is_object and not isinstance(out.get("properties"), dict) and (
        depth == 0 or not required
    ):
        out["properties"] = {}
    if isinstance(required, list) and isinstance(out.get("properties"), dict):
        # Pruned only against a ``properties`` map the node itself declares; a
        # subschema without one (``{"required": ["a"]}``) is left as it is.
        declared = out["properties"]
        kept: list[str] = []
        for name in required:
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
    if not isinstance(out, dict):
        return _empty_object()
    kind = out.get("type")
    if isinstance(kind, list) and "object" in kind:
        # ``["object", "null"]``: the arguments are always an object.
        out["type"] = "object"
    if any(key in out for key in _ROOT_FORBIDDEN):
        out = _normalize_node(_flatten_root(out, out, frozenset(), 0), 0)
    if not isinstance(out, dict) or out.get("type") != "object":
        return _empty_object()
    return out


# ── root flattening ──────────────────────────────────────────────────────────────

#: Keywords a provider refuses (or reads unreliably) at the top level of a tool's
#: parameters: Anthropic rejects a top-level ``anyOf``/``oneOf``/``allOf``, and a root
#: ``$ref`` beside empty ``properties`` shows the model no parameters at all.
_ROOT_FORBIDDEN = ("anyOf", "oneOf", "allOf", "$ref", "enum", "not")


def _resolve_pointer(ref: str, doc: dict[str, Any]) -> Any:
    """The node a local JSON pointer (``#`` or ``#/…``) names in *doc*, or None."""
    if ref == "#":
        return doc
    if not ref.startswith("#/"):
        return None
    node: Any = doc
    for raw in ref[2:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def _merge_schemas(own: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Both *own* and *other* apply (``allOf`` semantics), as one node.

    ``properties`` and ``required`` are unioned; a property both define differently
    becomes ``allOf`` of the two (legal below the root on every path, and Gemini merges
    it), and nested ``allOf`` lists are concatenated, so no shape is lost. For any other
    keyword *own*'s value wins.
    """
    merged = dict(own)
    for key, value in other.items():
        if key == "properties" and isinstance(value, dict):
            mine = merged.get("properties")
            props = dict(mine) if isinstance(mine, dict) else {}
            for name, sub in value.items():
                if name in props and props[name] != sub:
                    props[name] = {"allOf": [props[name], sub]}
                else:
                    props.setdefault(name, sub)
            merged["properties"] = props
        elif key == "required" and isinstance(value, list):
            merged["required"] = _merge_required(merged.get("required", []), value) or []
        elif key == "allOf" and isinstance(value, list) and isinstance(merged.get("allOf"), list):
            merged["allOf"] = [*merged["allOf"], *value]
        else:
            merged.setdefault(key, value)
    return merged


def _deref(
    node: dict[str, Any], doc: dict[str, Any], seen: frozenset[str],
) -> tuple[dict[str, Any], frozenset[str]]:
    """*node* with its ``$ref`` chain inlined (bounded; a cycle drops the reference)."""
    for _ in range(MAX_COLLAPSES):
        if "$ref" not in node:
            return node, seen
        ref = node.get("$ref")
        rest = {k: v for k, v in node.items() if k != "$ref"}
        target = _resolve_pointer(ref, doc) if isinstance(ref, str) and ref not in seen else None
        if isinstance(target, dict):
            node, seen = _merge_schemas(rest, target), seen | {ref}
        else:
            node = rest
    return {k: v for k, v in node.items() if k != "$ref"}, seen


def _is_object_branch(branch: dict[str, Any]) -> bool:
    kind = branch.get("type")
    if kind is None:
        return True  # ``{"required": [...]}``, ``{"properties": …}``: constrains an object
    return kind == "object" or (isinstance(kind, list) and "object" in kind)


def _discriminators(branch: dict[str, Any]) -> list[tuple[str, Any]]:
    """The properties a branch pins to one value (``const`` or a one-value ``enum``)."""
    pinned: list[tuple[str, Any]] = []
    props = branch.get("properties")
    for name, sub in (props.items() if isinstance(props, dict) else []):
        if not isinstance(sub, dict):
            continue
        if "const" in sub:
            pinned.append((name, sub["const"]))
        elif isinstance(sub.get("enum"), list) and len(sub["enum"]) == 1:
            pinned.append((name, sub["enum"][0]))
    return pinned


def _union_property(variants: list[Any]) -> Any:
    """One schema for a property several alternatives define."""
    distinct: list[Any] = []
    for sub in variants:
        if sub not in distinct:
            distinct.append(sub)
    if len(distinct) == 1:
        return distinct[0]
    values: list[Any] = []
    for sub in distinct:
        if not isinstance(sub, dict):
            break
        if "const" in sub:
            values.append(sub["const"])
        elif isinstance(sub.get("enum"), list):
            values.extend(sub["enum"])
        else:
            break
    else:
        kind = _scalar_type(values)
        if kind is not None:
            merged: dict[str, Any] = {"type": kind, "enum": []}
            for value in values:
                if value not in merged["enum"]:
                    merged["enum"].append(value)
            return merged
    return {"anyOf": distinct}


def _alternatives_text(key: str, branches: list[dict[str, Any]], common: list[str]) -> str:
    shapes: list[str] = []
    for index, branch in enumerate(branches, 1):
        pinned = _discriminators(branch)
        parts = [f"{name}={json.dumps(value, ensure_ascii=False)}" for name, value in pinned]
        pinned_names = {name for name, _ in pinned}
        req = branch.get("required")
        needs = [n for n in (req if isinstance(req, list) else [])
                 if isinstance(n, str) and n not in common and n not in pinned_names]
        if needs:
            parts.append("requires " + ", ".join(needs))
        if not parts:
            label = branch.get("title") or branch.get("description")
            props = branch.get("properties")
            if label:
                parts.append(str(label))
            elif isinstance(props, dict) and props:
                parts.append("with " + ", ".join(str(name) for name in props))
            else:
                parts.append("no further requirement")
        shapes.append(f"({index}) " + ", ".join(parts))
    lead = "exactly one" if key == "oneOf" else "at least one"
    return f"Arguments must match {lead} of these shapes: " + "; ".join(shapes) + "."


def _union_root(
    base: dict[str, Any], key: str, branches: Any, doc: dict[str, Any],
    seen: frozenset[str], depth: int,
) -> dict[str, Any]:
    """A root ``anyOf``/``oneOf`` of objects as one object: properties unioned, the
    ``required`` names every alternative shares, and the alternatives spelled out in the
    description (a provider-legal root cannot carry the union itself)."""
    objects: list[dict[str, Any]] = []
    for branch in branches if isinstance(branches, list) else []:
        if not isinstance(branch, dict) or _is_null_branch(branch):
            continue
        flat = _flatten_root(branch, doc, seen, depth + 1)
        if _is_object_branch(flat):
            objects.append(flat)
    if not objects:
        return base
    names: dict[str, list[Any]] = {}
    for branch in objects:
        props = branch.get("properties")
        for name, sub in (props.items() if isinstance(props, dict) else []):
            names.setdefault(name, []).append(sub)
    common: list[str] = []
    for index, branch in enumerate(objects):
        req = branch.get("required")
        req_names = [n for n in (req if isinstance(req, list) else []) if isinstance(n, str)]
        common = req_names if index == 0 else [n for n in common if n in req_names]
    text = _alternatives_text(key, objects, common)
    own = base.get("description")
    merged = _merge_schemas(base, {
        "properties": {name: _union_property(subs) for name, subs in names.items()},
        "required": common,
    })
    merged["description"] = f"{own} {text}" if isinstance(own, str) and own else text
    return merged


def _not_text(schema: Any) -> str | None:
    if isinstance(schema, dict) and set(schema) == {"required"}:
        names = [n for n in schema["required"] if isinstance(n, str)] if isinstance(
            schema["required"], list) else []
        if names:
            return "Do not provide all of: " + ", ".join(names) + "."
    return None


def _flatten_root(
    node: dict[str, Any], doc: dict[str, Any], seen: frozenset[str], depth: int,
) -> dict[str, Any]:
    """*node* rewritten so it carries none of :data:`_ROOT_FORBIDDEN`: a ``$ref`` is
    inlined, an ``allOf`` merged (references resolved), an ``anyOf``/``oneOf`` of objects
    unioned (:func:`_union_root`); ``enum`` and ``not`` are dropped (a required-only
    ``not`` is stated in the description). Bounded in steps and depth."""
    if depth > MAX_SCHEMA_DEPTH:
        return {}
    for _ in range(MAX_COLLAPSES):
        if "$ref" in node:
            node, seen = _deref(node, doc, seen)
            continue
        if "allOf" in node:
            branches = node["allOf"]
            merged = {k: v for k, v in node.items() if k != "allOf"}
            followed = seen
            for branch in branches if isinstance(branches, list) else []:
                if not isinstance(branch, dict):
                    continue
                branch, branch_seen = _deref(branch, doc, seen)
                followed = followed | branch_seen
                merged = _merge_schemas(merged, branch)
            node, seen = merged, followed
            continue
        key = next((k for k in ("anyOf", "oneOf") if k in node), None)
        if key is None:
            break
        rest = {k: v for k, v in node.items() if k != key}
        node = _union_root(rest, key, node[key], doc, seen, depth)
    note = _not_text(node.get("not"))
    node = {k: v for k, v in node.items() if k not in _ROOT_FORBIDDEN}
    if note:
        own = node.get("description")
        node["description"] = f"{own} {note}" if isinstance(own, str) and own else note
    return node


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
