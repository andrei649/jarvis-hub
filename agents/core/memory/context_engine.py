"""Pluggable ContextEngine interface, loader, request-only selection, and switch guard (H434).

Provides:
1. :class:`ContextEngine` ABC with :class:`DefaultCompressorContextEngine`
   wrapping :class:`agents.core.context_compressor.ContextCompressor` as the
   default engine, plus :func:`register_context_engine` and
   :func:`load_context_engine`.
2. Request-only context selection (:meth:`ContextEngine.select_for_request`):
   constructs a bounded per-request view of conversation turns (preserving
   protected head + tail turns and selecting highest-relevance middle turns
   within budget) **without** mutating the session transcript or any turn dict.
3. Context-switch guard (:func:`check_context_switch_guard`): emits a structured
   warning (and per-turn notice ``context_switch_window_reduced``) when a
   session switches to a model with a smaller context window or when existing
   transcript pressure approaches/exceeds the target model's window.
"""

from __future__ import annotations

import copy
import importlib
import inspect
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..context_compressor import CompactionPolicy, ContextCompressor, window_for
from ..turn_notices import record_compaction_status, record_turn_notice

_MODULE_SPEC_RE = re.compile(r"^(agents(?:\.[A-Za-z_][A-Za-z0-9_]*)+):([A-Za-z_][A-Za-z0-9_]*)$")
_WORD_RE = re.compile(r"[a-z0-9_]{3,}")

_ENGINE_REGISTRY: dict[str, Callable[..., "ContextEngine"]] = {}


def _query_terms(query: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall((query or "").lower()))


def _turn_token_estimate(turn: Mapping[str, Any]) -> int:
    text = str(turn.get("content", "") or "")
    cost = ContextCompressor.estimate_tokens(text)
    if turn.get("image") or turn.get("images"):
        cost += 1024
    return cost


def _score_middle_turn(turn: Mapping[str, Any], terms: frozenset[str], index: int, total: int) -> float:
    content = str(turn.get("content", "") or "")
    lowered = content.lower()
    overlap = 0.0
    if terms:
        turn_words = set(_WORD_RE.findall(lowered))
        matched = len(terms & turn_words)
        overlap = matched / max(1, len(terms))
    length_score = min(1.0, len(content) / 400.0) * 0.25
    question_bonus = 0.2 if "?" in content else 0.0
    role_bonus = 0.1 if turn.get("role") == "user" else 0.0
    recency_bonus = (index / max(1, total)) * 0.15
    return overlap * 2.0 + length_score + question_bonus + role_bonus + recency_bonus


def select_turns_for_request(
    turns: Sequence[Mapping[str, Any]],
    *,
    query: str = "",
    max_tokens: int | None = None,
    protect_first: int = 1,
    protect_last: int = 4,
) -> list[dict[str, Any]]:
    """Select turns for a single request without mutating input ``turns``.

    Always deep-copies chosen turns so caller mutations to the returned list
    never leak back into session history, and never rewrites/summarizes turn
    text in-place.
    """
    rows = list(turns or ())
    if not rows:
        return []
    if max_tokens is None or max_tokens <= 0:
        return [copy.deepcopy(dict(row)) for row in rows]

    budget = int(max_tokens)
    total_cost = sum(_turn_token_estimate(row) for row in rows)
    if total_cost <= budget:
        return [copy.deepcopy(dict(row)) for row in rows]

    n = len(rows)
    head_n = max(0, min(int(protect_first), n))
    tail_n = max(0, min(int(protect_last), n - head_n))

    tail_indices = list(range(n - tail_n, n)) if tail_n > 0 else []
    head_indices = list(range(0, head_n))
    middle_indices = list(range(head_n, n - tail_n))

    selected_indices: set[int] = set()
    used = 0

    # Priority 1: most recent tail turns (newest-first if budget is tighter than tail)
    for idx in reversed(tail_indices):
        cost = _turn_token_estimate(rows[idx])
        if used + cost <= budget or not selected_indices:
            selected_indices.add(idx)
            used += cost

    # Priority 2: protected head turns (original user goal / anchor)
    for idx in head_indices:
        cost = _turn_token_estimate(rows[idx])
        if used + cost <= budget:
            selected_indices.add(idx)
            used += cost

    # Priority 3: highest-relevance middle turns for this specific request query
    if middle_indices and used < budget:
        terms = _query_terms(query)
        ranked = sorted(
            middle_indices,
            key=lambda i: (_score_middle_turn(rows[i], terms, i, n), i),
            reverse=True,
        )
        for idx in ranked:
            cost = _turn_token_estimate(rows[idx])
            if used + cost <= budget:
                selected_indices.add(idx)
                used += cost

    ordered = sorted(selected_indices)
    return [copy.deepcopy(dict(rows[idx])) for idx in ordered]


class ContextEngine(ABC):
    """Pluggable context engine contract (H434)."""

    max_tokens: int = 2000

    @property
    @abstractmethod
    def engine_id(self) -> str:
        """Stable identifier for this context engine."""

    def select_for_request(
        self,
        turns: Sequence[Mapping[str, Any]],
        *,
        query: str = "",
        max_tokens: int | None = None,
        protect_first: int = 1,
        protect_last: int = 4,
    ) -> list[dict[str, Any]]:
        """Return a non-mutating request-scoped view of ``turns``."""
        effective_budget = self.max_tokens if max_tokens is None else max_tokens
        return select_turns_for_request(
            turns,
            query=query,
            max_tokens=effective_budget,
            protect_first=protect_first,
            protect_last=protect_last,
        )

    def estimate_used_tokens(self, turns: list[dict[str, Any]], anchor: Any = None) -> int:
        """Estimate transcript token occupancy."""
        return sum(_turn_token_estimate(t) for t in (turns or ()))

    def _used(self, rows: list[dict[str, Any]], anchor: Any = None, **kwargs: Any) -> int:
        return self.estimate_used_tokens(rows, anchor=anchor)

    @abstractmethod
    async def compact(
        self,
        turns: list[dict[str, Any]],
        *,
        model: str | None = None,
        policy: CompactionPolicy | None = None,
        session_id: str = "",
        prior: dict[str, Any] | None = None,
        sink: Callable[[dict[str, Any]], Any] | None = None,
        anchor: Any = None,
        force_target_tokens: int | None = None,
        emit_status: bool = False,
    ) -> dict[str, Any]:
        """Compact ``turns`` to fit ``model`` / ``policy`` budget."""


class DefaultCompressorContextEngine(ContextEngine):
    """Default :class:`ContextEngine` backed by :class:`ContextCompressor`."""

    def __init__(self, compressor: ContextCompressor | None = None, **kwargs: Any) -> None:
        self.compressor = compressor if compressor is not None else ContextCompressor(**kwargs)
        self.max_tokens = self.compressor.max_tokens

    @property
    def engine_id(self) -> str:
        return "default"

    def estimate_used_tokens(self, turns: list[dict[str, Any]], anchor: Any = None) -> int:
        return self.compressor._used(turns, anchor)

    def _used(self, rows: list[dict[str, Any]], anchor: Any = None, **kwargs: Any) -> int:
        return self.compressor._used(rows, anchor, **kwargs)

    async def compact(
        self,
        turns: list[dict[str, Any]],
        *,
        model: str | None = None,
        policy: CompactionPolicy | None = None,
        session_id: str = "",
        prior: dict[str, Any] | None = None,
        sink: Callable[[dict[str, Any]], Any] | None = None,
        anchor: Any = None,
        force_target_tokens: int | None = None,
        emit_status: bool = False,
    ) -> dict[str, Any]:
        self.compressor.max_tokens = self.max_tokens
        result = await self.compressor.compact(
            turns,
            model=model,
            policy=policy,
            session_id=session_id,
            prior=prior,
            sink=sink,
            anchor=anchor,
            force_target_tokens=force_target_tokens,
        )
        if emit_status and result.get("compressed"):
            evicted = int(result.get("evicted", 0) or 0)
            dropped = int(result.get("images_dropped", 0) or 0)
            parts: list[str] = []
            if evicted:
                parts.append(f"{evicted} earlier turn(s) summarized")
            if dropped:
                parts.append(f"{dropped} older image(s) stripped")
            detail = ", ".join(parts) if parts else f"tier={result.get('tier', 'compact')}"
            record_compaction_status(f"Context compacted ({detail}).")
        return result


def register_context_engine(name: str, factory: Callable[..., ContextEngine]) -> None:
    """Register a named :class:`ContextEngine` factory."""
    key = (name or "").strip().lower()
    if not key or key in {"default", "compressor", "builtin"}:
        raise ValueError(f"Reserved or empty context engine name: {name!r}")
    if not callable(factory):
        raise TypeError("ContextEngine factory must be callable")
    _ENGINE_REGISTRY[key] = factory


def unregister_context_engine(name: str) -> None:
    """Remove a previously registered context engine factory."""
    key = (name or "").strip().lower()
    _ENGINE_REGISTRY.pop(key, None)


def registered_context_engines() -> tuple[str, ...]:
    """Return sorted registered engine names (including 'default')."""
    return tuple(sorted({"default", *_ENGINE_REGISTRY.keys()}))


def _instantiate_with_supported_kwargs(factory: Callable[..., Any], kwargs: dict[str, Any]) -> ContextEngine:
    try:
        sig = inspect.signature(factory)
    except (TypeError, ValueError):
        instance = factory(**kwargs)
    else:
        accepts_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if accepts_var_kw:
            instance = factory(**kwargs)
        else:
            filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
            instance = factory(**filtered)
    if not isinstance(instance, ContextEngine):
        raise TypeError(f"Loaded object {instance!r} is not a ContextEngine")
    return instance


def load_context_engine(spec: str | None = None, **kwargs: Any) -> ContextEngine:
    """Load a :class:`ContextEngine` by name, ``agents.*:ClassName`` path, or setting."""
    from .. import safe_mode

    if safe_mode.active():
        return DefaultCompressorContextEngine(**kwargs)

    resolved = spec
    if resolved is None or not str(resolved).strip():
        try:
            configured = safe_mode.get_value("memory", "context_engine", "default")
            resolved = str(configured or "default")
        except Exception:
            resolved = "default"

    raw = str(resolved).strip()
    key = raw.lower()
    if key in {"", "default", "compressor", "builtin"}:
        return DefaultCompressorContextEngine(**kwargs)

    if key in _ENGINE_REGISTRY:
        return _instantiate_with_supported_kwargs(_ENGINE_REGISTRY[key], kwargs)

    match = _MODULE_SPEC_RE.match(raw)
    if match:
        mod_name, cls_name = match.group(1), match.group(2)
        module = importlib.import_module(mod_name)
        cls = getattr(module, cls_name, None)
        if not isinstance(cls, type) or not issubclass(cls, ContextEngine):
            raise ValueError(f"Target {raw!r} is not a ContextEngine subclass")
        return _instantiate_with_supported_kwargs(cls, kwargs)

    raise ValueError(f"Unknown context engine: {raw!r}")


def check_context_switch_guard(
    previous_model: str,
    new_model: str,
    *,
    current_tokens: int = 0,
    previous_window: int | None = None,
    new_window: int | None = None,
    emit_notice: bool = True,
) -> dict[str, Any] | None:
    """Warn when switching models shrinks the context window or risks overflow (H434)."""
    prev_m = str(previous_model or "").strip()
    next_m = str(new_model or "").strip()
    if not prev_m or not next_m or prev_m == next_m:
        return None

    old_win = (
        int(previous_window)
        if isinstance(previous_window, int) and previous_window > 0
        else int(window_for(prev_m))
    )
    next_win = (
        int(new_window)
        if isinstance(new_window, int) and new_window > 0
        else int(window_for(next_m))
    )
    tokens = max(0, int(current_tokens or 0))
    window_reduced = next_win < old_win
    soft_limit = max(1, int(next_win * 0.6))
    hard_limit = max(1, int(next_win * 0.85))
    overflow_risk = tokens > hard_limit
    pressure_high = tokens >= soft_limit

    if not window_reduced and not pressure_high:
        return None

    if window_reduced and tokens > 0:
        warning = (
            f"Context-switch guard: model changed from {prev_m} ({old_win:,} tokens) "
            f"to {next_m} ({next_win:,} tokens) with ~{tokens:,} tokens in context"
            + (" (exceeds hard budget; compaction or truncation required)." if overflow_risk else ".")
        )
    elif window_reduced:
        warning = (
            f"Context-switch guard: model changed from {prev_m} ({old_win:,} tokens) "
            f"to {next_m} ({next_win:,} tokens); smaller context window may compact earlier."
        )
    else:
        warning = (
            f"Context-switch guard: switching to {next_m} ({next_win:,} tokens) "
            f"with ~{tokens:,} tokens already above soft threshold ({soft_limit:,})."
        )

    if emit_notice:
        record_turn_notice("context_switch_window_reduced", warning)

    return {
        "code": "context_switch_window_reduced",
        "previous_model": prev_m,
        "new_model": next_m,
        "previous_window": old_win,
        "new_window": next_win,
        "current_tokens": tokens,
        "window_reduced": window_reduced,
        "overflow_risk": overflow_risk,
        "warning": warning,
    }


__all__ = [
    "ContextEngine",
    "DefaultCompressorContextEngine",
    "check_context_switch_guard",
    "load_context_engine",
    "register_context_engine",
    "registered_context_engines",
    "select_turns_for_request",
    "unregister_context_engine",
]
