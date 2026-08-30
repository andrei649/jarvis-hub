"""
transforms.py — H10.3 Workflow Transform Nodes.

Deterministic, offline transform steps that reshape a step's output before it
flows downstream — no LLM call. Used by the engine for ``kind == "transform"``
steps via a ``transform`` config:

    {"op": "formatter",    "mode": "upper|lower|title|strip|json_pretty"}
    {"op": "validator",    "check": "non_empty|json|regex|min_length|max_length|contains", "value": ...}
    {"op": "json_extract", "field": "user.name", "default": ""}
    {"op": "summarize",    "max_sentences": 3, "max_chars": 400}

A validator that fails returns an ``[error:...]`` string so the engine's normal
error/termination handling applies.
"""

from __future__ import annotations

import json
import re

try:
    from .structured import extract_json
except Exception:  # pragma: no cover
    def extract_json(text):
        try:
            return json.loads(text)
        except Exception:
            return None


def _formatter(text: str, cfg: dict) -> str:
    mode = (cfg.get("mode") or "strip").lower()
    if mode == "upper":
        return text.upper()
    if mode == "lower":
        return text.lower()
    if mode == "title":
        return text.title()
    if mode == "strip":
        return text.strip()
    if mode == "json_pretty":
        data = extract_json(text)
        if data is None:
            return "[error:formatter: input is not valid JSON]"
        return json.dumps(data, ensure_ascii=False, indent=2)
    return f"[error:formatter: unknown mode '{mode}']"


def _validator(text: str, cfg: dict) -> str:
    check = (cfg.get("check") or "non_empty").lower()
    value = cfg.get("value")
    ok, reason = True, ""
    if check == "non_empty":
        ok = bool(text.strip()); reason = "empty output"
    elif check == "json":
        ok = extract_json(text) is not None; reason = "not valid JSON"
    elif check == "regex":
        # WFL-113 — same caller-supplied-pattern vector WFL-112 closed in the
        # engine: a validator regex is user data too. Imported lazily, mirroring
        # engine's own `from .transforms import apply_transform`, so the sibling
        # modules stay import-order independent.
        from .engine import _safe_regex_search

        try:
            ok = _safe_regex_search(str(value), text)
        except re.error:
            ok = False
        reason = f"does not match /{value}/"
    elif check == "min_length":
        ok = len(text) >= int(value or 0); reason = f"shorter than {value}"
    elif check == "max_length":
        ok = len(text) <= int(value or 0); reason = f"longer than {value}"
    elif check == "contains":
        ok = str(value) in text; reason = f"missing '{value}'"
    else:
        return f"[error:validator: unknown check '{check}']"
    return text if ok else f"[error:validation failed: {reason}]"


def _json_extract(text: str, cfg: dict) -> str:
    data = extract_json(text)
    field = cfg.get("field", "")
    default = cfg.get("default", "")
    if data is None:
        return f"[error:json_extract: input is not valid JSON]"
    cur = data
    for part in str(field).split(".") if field else []:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return str(default)
    if isinstance(cur, (dict, list)):
        return json.dumps(cur, ensure_ascii=False)
    return "" if cur is None else str(cur)


def _summarize(text: str, cfg: dict) -> str:
    max_sentences = int(cfg.get("max_sentences", 3) or 3)
    max_chars = int(cfg.get("max_chars", 400) or 400)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    summary = " ".join(s for s in sentences[:max_sentences] if s).strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "…"
    return summary


_OPS = {
    "formatter": _formatter,
    "validator": _validator,
    "json_extract": _json_extract,
    "summarize": _summarize,
}


def apply_transform(config: dict, text: str) -> str:
    """Apply a transform config to *text*. Unknown ops → an error string."""
    op = (config or {}).get("op", "")
    fn = _OPS.get(op)
    if fn is None:
        return f"[error:transform: unknown op '{op}']"
    try:
        return fn(text or "", config or {})
    except Exception as e:  # pragma: no cover - defensive
        return f"[error:transform: {e}]"
