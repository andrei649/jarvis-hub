"""Turn-local, result-aware decisions for a stalled model tool loop.

The observer sees completed calls in assistant order, never executes a tool or changes
authority. It retains only a digest of the prior result, not its payload.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_FAILED_STATUSES = frozenset({"error", "failed", "failure", "refused", "denied", "timeout"})
_FAILED_REASONS = frozenset({"bad_args", "bad_tool_arguments", "validation_failed",
                            "contract_error", "not_found", "approval_required",
                            "guardian_denied", "kernel_denied", "tool_not_allowed",
                            "rate_limited", "rate_limit", "timeout"})
_SECRET_PARTS = ("secret", "token", "password", "credential", "apikey", "privatekey",
                 "authorization", "cookie", "sessionkey")
_OPAQUE_KEYS = frozenset({"command", "shell", "script", "headers", "header", "env"})
_EMBEDDED_CREDENTIAL = re.compile(
    r"(?:\b(?:bearer|basic)\s+\S+|://[^\s/@]+:[^\s/@]+@|"
    r"\b(?:token|password|secret|api[_-]?key|cookie)\s*[:=]\s*\S+)", re.I,
)


def is_poller(tool: str) -> bool:
    return tool == "process" or tool.endswith(("_poll", "_get_result"))


def classify_failure(result: Mapping[str, Any]) -> bool:
    """Respect explicit success/failure, then classify legacy envelopes without ok."""
    if result.get("ok") is False:
        return True
    inner = result.get("result")
    if isinstance(inner, Mapping) and inner.get("ok") is False:
        return True
    if isinstance(inner, Mapping) and inner.get("ok") is not True and classify_failure(inner):
        return True
    if result.get("ok") is True:
        return False
    if isinstance(inner, Mapping) and inner.get("ok") is True:
        return False
    if result.get("error"):
        return True
    status = result.get("status")
    if str(status).lower() in _FAILED_STATUSES:
        return True
    if (type(status) is int and status >= 400) or (
        isinstance(status, str) and status.isdecimal() and int(status) >= 400
    ):
        return True
    reason = result.get("reason")
    if not isinstance(reason, str):
        return False
    code = reason.strip().lower()
    return code in _FAILED_REASONS or code.endswith(
        ("_error", "_failed", "_refused", "_denied", "_timeout", "_unavailable", "_not_found")
    )


def recovery_hint(result: Mapping[str, Any]) -> str:
    """Finite guidance chosen from trusted reason codes; never quote tool content."""
    reason = result.get("reason")
    if not isinstance(reason, str):
        inner = result.get("result")
        reason = inner.get("reason") if isinstance(inner, Mapping) else None
    if reason in {"bad_args", "bad_tool_arguments", "validation_failed", "contract_error"}:
        return "Check the tool's argument schema and correct the arguments before retrying."
    if reason in {"not_found", "file_not_found", "missing"}:
        return "Verify the path or query once, then use another source if it is absent."
    if reason in {"tool_timeout", "timeout", "rate_limited", "rate_limit"}:
        return "Wait for the condition to change or use another available tool."
    if reason in {"approval_required", "guardian_denied", "kernel_denied", "tool_not_allowed"}:
        return "Use the permission path or choose an authorized action; do not retry unchanged."
    return "Change the arguments or tool, or answer with the evidence already available."


def _scrub_args(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if str(key).lower() in _OPAQUE_KEYS or any(
                part in re.sub(r"[^a-z0-9]", "", str(key).lower()) for part in _SECRET_PARTS
            )
            else _scrub_args(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_scrub_args(item) for item in value]
    return value


def safe_args_preview(args: Mapping[str, Any]) -> str:
    """A bounded JSON preview; known credential keys never reveal values."""
    try:
        encoded_raw = json.dumps(args, ensure_ascii=False, default=str)
        if _EMBEDDED_CREDENTIAL.search(encoded_raw) or any(
            str(key).lower() in _OPAQUE_KEYS for key in args
        ):
            return "[arguments withheld]"
        return json.dumps(_scrub_args(args), sort_keys=True, ensure_ascii=False,
                          default=str, separators=(",", ":"))[:120]
    except (TypeError, ValueError):
        return ""


def _signature(tool: str, args: Mapping[str, Any], result: Mapping[str, Any]) -> tuple[str, str, str]:
    try:
        encoded_args = json.dumps(args, sort_keys=True, ensure_ascii=False,
                                  default=str, separators=(",", ":"))
        encoded_result = json.dumps(result, sort_keys=True, ensure_ascii=False,
                                    default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        encoded_args = repr(args)
        encoded_result = repr(result)
    return (tool, hashlib.sha256(encoded_args.encode("utf-8")).hexdigest(),
            hashlib.sha256(encoded_result.encode("utf-8")).hexdigest())


@dataclass(frozen=True, slots=True)
class StallDecision:
    notices: tuple[str, ...] = ()
    halt: str | None = None
    count: int = 0


class StallObserver:
    """Classify consecutive observations within one run, not across concurrent turns."""

    def __init__(self, *, halt_enabled: bool = False, repeat_warn: int = 3,
                 same_tool_halt: int = 8, track_repeats: bool = True,
                 track_failures: bool = True) -> None:
        self.halt_enabled = halt_enabled
        self.repeat_warn = repeat_warn
        self.same_tool_halt = same_tool_halt
        self.track_repeats = track_repeats
        self.track_failures = track_failures
        self._last: tuple[str, str, str] | None = None
        self._last_failed = False
        self._identical = 0
        self._exact_failure = 0
        self._same_tool_failure = 0
        self._no_progress = 0

    def observe(self, tool: str, args: Mapping[str, Any], result: Mapping[str, Any]) -> StallDecision:
        signature = _signature(tool, args, result)
        failed = classify_failure(result)
        if is_poller(tool):
            self._last = None
            self._last_failed = False
            return StallDecision()
        same = signature == self._last
        same_failed_tool = self._last is not None and self._last[0] == tool and self._last_failed
        self._identical = self._identical + 1 if same else 1
        self._exact_failure = self._exact_failure + 1 if failed and same and self._last_failed else (1 if failed else 0)
        self._same_tool_failure = self._same_tool_failure + 1 if failed and same_failed_tool else (1 if failed else 0)
        self._no_progress = self._no_progress + 1 if not failed and same else (0 if failed else 1)
        self._last = signature
        self._last_failed = failed
        notices: list[str] = []
        if self.track_repeats and self._identical >= self.repeat_warn:
            notices.append("identical_call")
        if self.track_failures and failed and self._exact_failure >= 2:
            notices.append("exact_failure")
        if self.track_failures and failed and self._same_tool_failure >= 3:
            notices.append("same_tool_failure")
        if self.track_repeats and not failed and self._no_progress >= 2:
            notices.append("no_progress")
        halt = None
        count = 0
        if self.halt_enabled:
            if self.track_failures and self._exact_failure >= 5:
                halt, count = "exact_failure", self._exact_failure
            elif self.track_failures and self._same_tool_failure >= self.same_tool_halt:
                halt, count = "same_tool_failure", self._same_tool_failure
            elif self.track_repeats and self._no_progress >= 5:
                halt, count = "no_progress", self._no_progress
        return StallDecision(tuple(notices), halt, count)
