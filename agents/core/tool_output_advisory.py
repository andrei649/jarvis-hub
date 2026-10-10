"""Host-owned, advisory observations of external tool output (H398).

These observations cannot authorize a tool or reduce the existing turn taint.
They never become fields in a provider message or copies of attacker text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from .security.quarantine import detect_injection_normalized, injection_flag_names

COMPLETENESS_NOTICE = (
    "[Nerva note: this external result indicates omitted data. "
    "It is INCOMPLETE; fetch the remainder before treating an enumeration as complete.]\n"
)
_RAW_MIN = 1000
_RAW_MAX = 65536
_RAW_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\.\.\.\s*\d+\s+more\s+items?",
    r'"has_more"\s*:\s*true',
    r"saved to sandbox",
    r"data_preview",
))
_TRUNCATED_TOOLS = frozenset({
    "file_read", "file_list", "file_search", "kanban_list", "execute_code", "web_extract",
})
_CODE_NO_DATA_REASONS = frozenset({
    "code_execution_disabled", "sandbox_unavailable", "sandbox_not_isolated", "authority_unavailable",
})


@dataclass(frozen=True, slots=True)
class ToolOutputRisk:
    external_untrusted: bool = False
    risk: Literal["high", "low"] | None = None
    findings: tuple[str, ...] = ()
    redacted: Literal[False] | None = None
    declared_taint: bool = False
    upstream_elided: bool = False
    context_elided: bool = False
    typed_marker: str | None = None
    raw_marker: bool = False
    scanner_unavailable: bool = False

    def with_context_elided(self) -> ToolOutputRisk:
        return replace(self, context_elided=True)


def raw_elision_marker(text: str) -> bool:
    """The frozen upstream four-marker scan, bounded to 1,000–65,536 characters."""
    if len(text) < _RAW_MIN:
        return False
    head = text[:_RAW_MAX]
    return any(pattern.search(head) for pattern in _RAW_PATTERNS)


def _source_texts(value: Any) -> tuple[str, ...]:
    """Strings actually carried by a ToolRPC handler, before host display replacement."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(
            part["text"] for part in value
            if isinstance(part, Mapping) and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
    if isinstance(value, Mapping):
        # Native tools return dictionaries. Their JSON is what the model would
        # read, while direct string values retain literal quoted JSON markers.
        texts = [field for field in value.values() if isinstance(field, str)]
        content = value.get("content")
        if isinstance(content, list):
            texts.extend(_source_texts(content))
        texts.append(json.dumps(value, ensure_ascii=False, allow_nan=False))
        return tuple(texts)
    return ()


def _typed_marker(tool: str, envelope: Mapping[str, Any]) -> str | None:
    if envelope.get("ok") is not True or envelope.get("tool") != tool:
        return None
    result = envelope.get("result")
    if not isinstance(result, Mapping):
        return None
    if tool in _TRUNCATED_TOOLS and result.get("truncated") is True:
        return "truncated"
    if tool == "skills_list":
        offset, next_offset = result.get("offset"), result.get("next_offset")
        if type(offset) is int and offset >= 0 and type(next_offset) is int and next_offset > offset:
            return "next_offset"
    return None


def is_local_refusal(envelope: Mapping[str, Any], tool: str) -> bool:
    """Recognize host refusals and exact native no-data handler replies only.

    An arbitrary handler's ``ok: false`` is not provenance: it may contain
    attacker-controlled error text read before the handler failed.
    """
    if envelope.get("ok") is not True:
        return True  # ToolRPC's outer refusal, before a handler result is wrapped.
    inner = envelope.get("result")
    if not isinstance(inner, Mapping) or inner.get("ok") is not False:
        return False
    reason = inner.get("reason")
    if not isinstance(reason, str):
        return False
    keys = set(inner)
    if tool == "execute_code":
        return reason in _CODE_NO_DATA_REASONS and keys == {"ok", "reason"}
    if tool not in {"web_search", "web_extract"}:
        return False
    if reason == "websearch_unavailable":
        if not keys <= {"ok", "reason", "available", "missing"}:
            return False
        if "available" in inner and inner["available"] is not False:
            return False
        return "missing" not in inner or inner["missing"] == "beautifulsoup4"
    if tool == "web_search" and reason in {"secret_in_query", "tainted_turn"}:
        return keys == {"available", "ok", "reason"} and inner["available"] is True
    if tool == "web_extract" and reason in {"secret_in_url", "tainted_turn", "url_refused"}:
        url = inner.get("url")
        return (keys == {"available", "ok", "reason", "url"} and inner["available"] is True
                and isinstance(url, str) and len(url) <= 2048)
    return False


def classify_output(tool: str, envelope: Mapping[str, Any], *, untrusted: bool) -> ToolOutputRisk:
    """Classify one original ToolRPC envelope without trusting handler labels.

    The risk IDs adapt the native normalized injection scanner. A scanner error
    is recorded as unknown; it never means a clean or trusted result.
    """
    inner = envelope.get("result")
    if not untrusted or is_local_refusal(envelope, tool):
        return ToolOutputRisk()
    texts = _source_texts(inner)
    typed = _typed_marker(tool, envelope)
    raw = any(raw_elision_marker(text) for text in texts)
    if not texts:
        return ToolOutputRisk(
            external_untrusted=True,
            declared_taint=isinstance(inner, Mapping) and inner.get("tainted") is True,
            upstream_elided=bool(typed), typed_marker=typed,
        )
    flags: list[str] = []
    try:
        for source in texts:
            # The 65,536-character cap belongs to the completeness marker scan,
            # not to risk findings: a late hostile instruction still matters.
            flags.extend(detect_injection_normalized(source))
        findings = tuple(injection_flag_names(flags))
    except Exception:
        return ToolOutputRisk(
            external_untrusted=True, declared_taint=isinstance(inner, Mapping) and inner.get("tainted") is True,
            upstream_elided=bool(typed or raw), typed_marker=typed, raw_marker=raw,
            scanner_unavailable=True,
        )
    return ToolOutputRisk(
        external_untrusted=True, risk="high" if findings else "low", findings=findings,
        redacted=False, declared_taint=isinstance(inner, Mapping) and inner.get("tainted") is True,
        upstream_elided=bool(typed or raw), typed_marker=typed, raw_marker=raw,
    )
