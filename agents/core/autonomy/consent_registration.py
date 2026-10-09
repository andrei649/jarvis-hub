"""Stable, fail-closed provenance for an explicit ToolRPC registrar contract.

This digest describes registered code and declarations. It grants no permission.
Closure cells, instance state, remote targets and policy remain separate scope.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import sys
from pathlib import Path
from types import CodeType, FunctionType, MethodType

_CALLBACKS = (
    "handler", "preflight", "classifier", "gated_intake", "gated_review",
    "schema_overrides",
)
_STATIC = (
    "consent_revision", "description", "input_schema", "capability_id",
    "gated", "trusted_execution", "untrusted_output", "max_result_bytes",
)
_INTERNAL = frozenset({"_grouping_epoch", "_consent_registration_key", "active_tasks"})
_MAX_SOURCE = 2_000_000
_MAX_PAYLOAD = 131_072


def _constant(value, depth=0):
    if depth > 32:
        raise ValueError("code constant nesting")
    if isinstance(value, CodeType):
        return {"code": _code(value, depth + 1)}
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return {"float": value.hex()}
    if type(value) is bytes:
        return {"bytes": value.hex()}
    if type(value) is complex and math.isfinite(value.real) and math.isfinite(value.imag):
        return {"complex": [value.real.hex(), value.imag.hex()]}
    if type(value) in (tuple, frozenset):
        values = [_constant(item, depth + 1) for item in value]
        if type(value) is frozenset:
            values.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return {"tuple" if type(value) is tuple else "frozenset": values}
    raise ValueError("opaque code constant")


def _code(value: CodeType, depth=0):
    if depth > 32:
        raise ValueError("code nesting")
    return {
        "argcount": value.co_argcount,
        "posonlyargcount": value.co_posonlyargcount,
        "kwonlyargcount": value.co_kwonlyargcount,
        "nlocals": value.co_nlocals,
        "stacksize": value.co_stacksize,
        "flags": value.co_flags,
        "code": value.co_code.hex(),
        "consts": [_constant(item, depth + 1) for item in value.co_consts],
        "names": value.co_names,
        "varnames": value.co_varnames,
        "freevars": value.co_freevars,
        "cellvars": value.co_cellvars,
        "exceptiontable": value.co_exceptiontable.hex(),
    }


def _callback(value):
    if value is None:
        return None
    if isinstance(value, MethodType):
        function = value.__func__
    elif isinstance(value, FunctionType):
        function = value
    elif callable(value) and not inspect.isclass(value):
        function = type(value).__call__
        if not isinstance(function, FunctionType):
            raise ValueError("opaque callable instance")
    else:
        raise ValueError("opaque callback")
    module = sys.modules.get(function.__module__)
    source = getattr(module, "__file__", None)
    code_source = inspect.getsourcefile(function)
    if not isinstance(source, str) or not code_source:
        raise ValueError("unreadable implementation module")
    source_path = Path(source).resolve(strict=True)
    if source_path != Path(code_source).resolve(strict=True):
        raise ValueError("unmatched implementation module")
    if not source_path.is_file() or source_path.stat().st_size > _MAX_SOURCE:
        raise ValueError("oversized implementation module")
    module_bytes = source_path.read_bytes()
    if len(module_bytes) > _MAX_SOURCE:
        raise ValueError("oversized implementation module")
    return {"module_sha256": hashlib.sha256(module_bytes).hexdigest(),
            "code": _code(function.__code__)}


def _valid_static(value, depth=0):
    if depth > 24:
        return False
    if type(value) is dict:
        return all(type(key) is str and _valid_static(child, depth + 1)
                   for key, child in value.items())
    if type(value) is list:
        return all(_valid_static(child, depth + 1) for child in value)
    if type(value) is float:
        return math.isfinite(value)
    return value is None or type(value) in (str, int, bool)


def trusted_registration_key(name: str, spec: dict) -> str | None:
    """Hash a readable explicit declaration; refuse unknown or malformed state."""
    try:
        if not isinstance(name, str) or not name or len(name) > 128 or type(spec) is not dict:
            return None
        revision = spec.get("consent_revision")
        if (type(revision) is not str or not revision or len(revision) > 128
                or not all(char.isascii() and (char.isalnum() or char in "._:-")
                           for char in revision)):
            return None
        if any(key not in spec for key in (*_STATIC, *_CALLBACKS)):
            return None
        if any(key not in (*_STATIC, *_CALLBACKS) and key not in _INTERNAL
               for key in spec):
            return None
        static = {key: spec[key] for key in _STATIC}
        if not _valid_static(static):
            return None
        if (type(static["description"]) is not str
                or type(static["input_schema"]) is not dict
                or (static["capability_id"] is not None
                    and type(static["capability_id"]) is not str)
                or (static["max_result_bytes"] is not None
                    and (type(static["max_result_bytes"]) is not int
                         or static["max_result_bytes"] <= 0))):
            return None
        if any(type(static[key]) is not bool for key in
               ("gated", "trusted_execution", "untrusted_output")):
            return None
        callbacks = {key: _callback(spec[key]) for key in _CALLBACKS}
        if callbacks["handler"] is None:
            return None
        payload = json.dumps({"version": 1, "name": name, "static": static,
                              "callbacks": callbacks}, sort_keys=True,
                             ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        if len(payload) > _MAX_PAYLOAD:
            return None
        return hashlib.sha256(payload).hexdigest()
    except (OSError, TypeError, ValueError, RecursionError, UnicodeError, OverflowError):
        return None
