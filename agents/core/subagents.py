"""
subagents.py — H20.6 Dynamic sub-agent delegation (+ steerable workers).

Extends the author-defined parallelism of the WorkflowEngine (H5.6) to
**agent-initiated** spawning: at runtime an agent can delegate a piece of work to
an **isolated** sub-agent (its own session), **concurrently**, under a
configurable **cap** (the gate — an agent can't fork unbounded work). Each
sub-agent runs through an INJECTABLE runner (the orchestrator's dispatch in
prod; a stub offline), so the governance/isolation layer is offline-testable.

Company-mode additions (co-subagent-steer):

* **steer / stop** — a running child has a per-spawn :class:`SteerChannel`
  inbox. Runners that accept a ``steer`` kwarg receive it (additive contract,
  like ``blocked``); ``stop()`` cancels the child task. Steer messages carry a
  declared *origin* (``user`` from the guarded HTTP surface, ``agent`` for
  inter-agent messages) and are **never** an approval — see :meth:`decide`.
* **typed output** — ``spawn(..., output_schema=...)`` validates the runner's
  result with :func:`validate_output` (type / required / enum only, no new
  dependency); a violation surfaces as a ``failed`` spawn, not a silent pass.
* **cost per delegation** — tokens/cost are attributed per spawn from the
  runner's ``usage`` (exact) or, failing that, from the cost-tracker delta
  around the run (best-effort; concurrent spawns can share a delta).
* **spawn persistence (observability only)** — finished spawn records are
  appended to ``data_path("subagents", "spawns.jsonl")`` when the
  ``JARVIS_SUBAGENT_SPAWN_LOG`` flag is on (default off). Nothing is replayed
  from it: sub-agents remain NOT the company unit — child queue rows are.

Per-child API settings and honest failure (H681):

* **model / provider / overrides** — ``spawn(..., model=, provider=, overrides=)``
  runs the child inside ``selection_scope`` (the job pin's validation and router
  enforcement) and ``request_overrides_scope`` (``max_tokens``, ``temperature``,
  ``extra_body``, bounded). Precedence: an explicit pin, then the injected
  ``selection_defaults`` (``autonomy.subagent_model`` / ``autonomy.subagent_provider``
  in prod), then the parent's own route; the record's ``selection.source`` says which.
  An invalid selection is refused before anything is spent. Runners that accept a
  ``selection`` kwarg receive the resolved selection (additive, like ``steer``).
* **failure honesty** — a runner raising :class:`SubAgentProviderError`, or answering
  a blank ``output``, is recorded ``failed`` with ``error: provider_failed``, never
  ``done``.
* **batch** — :meth:`SubAgentManager.spawn_batch` runs up to ``BATCH_MAX`` children
  within the free slots and returns one ``subagent_model_rejected`` notice when every
  child failed because the provider does not know the model the setting chose.

The one spawn gate (H400). Every child starts in :meth:`SubAgentManager.spawn` — the
owner routes, the batch and the model's ``delegate_task`` tool all end there — and a
spawn is admitted under one lock that also serialises the pause writer:

* **emergency stop / spawn pause** — while the install's ESTOP is engaged, the kill
  switch is halted, or the owner paused spawning (a sentinel file in the data root, so
  a pause survives a restart), no new child starts. Running children are left alone:
  both switches stop *new* work only. A state that cannot be read counts as stopped.
* **caps** — depth and concurrency are checked and the slot is taken in the same
  critical section; a child's depth comes from the spawn it is running in (a context
  variable the manager sets), never from a caller's argument.
* **per-child timeout** — a child that outruns ``child_timeout`` is cancelled, and its
  slot is released only when its task has actually ended.
* **tools** — a child's tool allowlist is the registered tools (or, for a spawn made
  from a model turn, the tools that turn was offered) minus the tools the blocked
  capabilities stand for (:func:`child_tool_allowlist`); it is recorded on the spawn
  and handed to runners that accept a ``tools`` kwarg.
* **batch quality gate** — a batch with a placeholder goal (``todo``, ``task 3``), an
  unexpanded template marker, or (two or more tasks) a goal under ten characters is
  refused before any child starts.
* **typed answer** — ``answer_schema`` validates the JSON in the child's *text* on the
  parent's side; the child's text is data, never instructions.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .env_config import env_flag
from .estop import SPAWN_PAUSE_SENTINEL
from .iteration_budget import IterationBudget
from .tool_rpc import bind_sync_thread_sink, current_tool_turn, reset_sync_thread_sink

logger = logging.getLogger("jarvis.subagents")

# Capabilities a sub-agent must NOT exercise, regardless of what the runner can
# do. Adapted from hermes-agent `DELEGATE_BLOCKED_TOOLS` (Nous Research, MIT):
# no recursive delegation, no writes to shared memory cores, no outbound
# channel sends, no skill authoring, no user clarification round-trips. The
# list is recorded on every spawn and handed to runners that accept a
# `blocked` kwarg; runners that don't are unchanged (additive contract).
DELEGATE_BLOCKED_CAPABILITIES = frozenset({
    "delegate", "memory_write", "channel_send", "skill_manage", "clarify",
})

# H400 — the model-facing tools each blocked capability stands for. The capability list
# above is what a spawn records; this is what enforces it for a runner that reaches
# tools by name (the production runner narrows the child's turn to the allowlist with
# ``job_toolsets.toolset_scope``, which both the offer and ``ToolRPCServer.handle``
# honour). ``cronjob`` sits under ``delegate``: a child that schedules a job starts work
# that outlives it. The board tools are withheld by prefix (Hermes strips ``kanban``
# from every child; ``kanban.runtime.delegate_scope`` withholds them as well).
BLOCKED_CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {
    "delegate": ("delegate_task", "cronjob"),
    "memory_write": ("memory",),
    "channel_send": ("speak",),
    "skill_manage": ("skill_propose",),
    "clarify": ("clarify", "request_secret"),
}
BLOCKED_TOOL_PREFIXES: tuple[str, ...] = ("kanban_",)


def blocked_tool_names(blocked: Iterable[str], names: Iterable[str]) -> frozenset:
    """The tools in *names* a child with the *blocked* capabilities may not call."""
    denied = {tool for capability in blocked for tool in BLOCKED_CAPABILITY_TOOLS.get(capability, ())}
    return frozenset(name for name in names
                     if name in denied or name.startswith(BLOCKED_TOOL_PREFIXES))


def child_tool_allowlist(registered: Iterable[str], parent_offer: Optional[Iterable[str]],
                         blocked: Iterable[str]) -> frozenset:
    """A child's tools: the registered ones its parent holds, minus the blocked ones.

    *parent_offer* is the set a model turn was offered (``None`` for a spawn made
    outside any turn: then the registry is the bound, and the child's own tool profile
    narrows it). The result is a subset of both — a child never gains a tool."""
    names = frozenset(str(name) for name in registered)
    if parent_offer is not None:
        names &= frozenset(str(name) for name in parent_offer)
    return names - blocked_tool_names(blocked, names)


# The spawn the code in flight is running in (set by the manager around a child's run),
# or None. A child's own spawns are attributed to it from here, so depth is counted from
# what is running and not from what a caller says about itself.
_CURRENT_SPAWN: ContextVar[Optional[str]] = ContextVar("nerva_current_spawn", default=None)


def current_spawn_id() -> Optional[str]:
    """The id of the sub-agent spawn this code runs in, or None outside one."""
    return _CURRENT_SPAWN.get()


# H400 review (M2): which delegation the code in flight belongs to — the spawn, the agent
# that delegated, the model turn it delegated from and the goal it was given — so an
# approval a child asks for says, on the card, that a sub-agent asked and for what.
_CURRENT_DELEGATION: ContextVar[Optional[dict]] = ContextVar("nerva_current_delegation", default=None)
DELEGATION_GOAL_CHARS = 80


def current_delegation() -> Optional[dict]:
    """``{"spawn_id", "parent", "turn", "goal"}`` inside a sub-agent, else None. A copy."""
    found = _CURRENT_DELEGATION.get()
    return dict(found) if found else None


def card_safe(text: object) -> str:
    """Text that came from a model (a delegated goal) made safe to sit beside the action an
    approval card names: no control, format, separator, surrogate or private-use character
    (ANSI escapes, bidi overrides, zero-width marks), no bracket that could fake the end of
    the attribution, whitespace collapsed (second H400 review, B-1)."""
    import unicodedata

    kept = []
    for char in str(text or ""):
        if unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp", "Cs", "Co"}:
            kept.append(" ")
        elif char in "[]":
            kept.append("(" if char == "[" else ")")
        else:
            kept.append(char)
    return " ".join("".join(kept).split())


def delegation_label(delegation: Optional[dict]) -> str:
    """One bounded line for an approval card: who asked, on whose behalf, for what. Every
    part is passed through :func:`card_safe`; the card puts it AFTER the action's own
    title, so model-written text can never stand where the action is named."""
    if not delegation:
        return ""
    goal = card_safe(delegation.get("goal"))
    if len(goal) > DELEGATION_GOAL_CHARS:
        goal = goal[: DELEGATION_GOAL_CHARS - 1] + "…"
    spawn = card_safe(delegation.get("spawn_id") or "?")[:80]
    parent = card_safe(delegation.get("parent") or "?")[:64]
    return f"asked by sub-agent {spawn} of {parent}: {goal}"


# Declared provenance of a steer message. `user` = the guarded HTTP surface
# (an operator typing at a running worker); `agent` = another agent / the
# parent talking to its child. Neither is an approval — approvals only ever
# come from a human decision on a queue row (worker.apply_decision).
STEER_ORIGINS = frozenset({"user", "agent"})
STEER_MAX_CHARS = 4000

# Default-off persistence flag (observability only).
SPAWN_LOG_ENV = "JARVIS_SUBAGENT_SPAWN_LOG"

# H486: spawns one tool-loop turn may make (Hermes: 50 delegate_task calls per turn),
# the shipped value of ``llm.tool_loop_subagent_spawn_cap``; and how many finished
# turns' counts are kept before the oldest is dropped.
DEFAULT_TURN_SPAWN_CAP = 50
TURN_SPAWN_HISTORY = 64

# H400 — the per-child wall clock (``autonomy.subagent_timeout_seconds`` in prod). There
# is no "off": an unreadable value is the shipped one and every value is clamped.
DEFAULT_CHILD_TIMEOUT_SECONDS = 300.0
CHILD_TIMEOUT_MIN_SECONDS = 5.0
CHILD_TIMEOUT_MAX_SECONDS = 3600.0
# How long a cancelled child is waited for before its caller is answered. A child that
# has not ended by then keeps its slot until it does (`stopping`, never a freed slot).
UNWIND_GRACE_SECONDS = 5.0

# H400 — the spawn pause: a sentinel file, so a pause outlives a restart. Its body is
# optional JSON; a file that cannot be read still pauses.
PAUSE_SENTINEL = SPAWN_PAUSE_SENTINEL
PAUSE_REASON_MAX = 200
# Why a spawn is refused when new spawns are stopped (as opposed to a cap being full).
HALT_REASONS = frozenset({"estop_engaged", "kill_switch_halted", "halt_state_unknown", "spawn_paused"})

# H400 — the batch quality gate (Hermes ``_validate_batch_tasks``).
_PLACEHOLDER_GOAL = re.compile(r"(todo|task\s*\d+)", re.IGNORECASE)
_TEMPLATE_MARKER = re.compile(
    r"<[A-Za-z][A-Za-z0-9]*(?:[ _-][A-Za-z0-9]+)+>|\{[A-Za-z][A-Za-z0-9]*(?:[ _-][A-Za-z0-9]+)+\}")
MIN_BATCH_GOAL_CHARS = 10

# H400 (B1) — what a record says when its outcome could not be recorded: fixed text,
# never the child's.
ANSWER_UNCHECKED = {"error": "answer_unchecked",
                    "detail": "the sub-agent's answer could not be checked and was discarded"}

# H400 — a typed answer: the schema a child's JSON answer must satisfy, bounded.
ANSWER_SCHEMA_MAX_BYTES = 8192
ANSWER_SCHEMA_MAX_DEPTH = 8
CONTEXT_MAX_CHARS = 8000

# Spawn lifecycle. `stopping` is the window between stop() (or a timeout) and the child
# task unwinding; every other move is a terminal write.
SPAWN_TRANSITIONS: dict[str, frozenset] = {
    "running": frozenset({"done", "failed", "stopping", "stopped"}),
    "stopping": frozenset({"stopped", "failed", "done"}),
    "done": frozenset(),
    "failed": frozenset(),
    "stopped": frozenset(),
}
TERMINAL_STATUSES = frozenset({"done", "failed", "stopped"})

# JSON-schema-ish type names the validator understands (no external dependency).
_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


# H681 — the settings a child's model comes from when its spawn names none.
SUBAGENT_MODEL_SETTING = "autonomy.subagent_model"
SUBAGENT_PROVIDER_SETTING = "autonomy.subagent_provider"
BATCH_MAX = 16
DETAIL_MAX = 500
_BATCH_ITEM_KEYS = frozenset({"task", "agent", "output_schema", "model", "provider", "overrides",
                              "context", "answer_schema"})
# The row's rule for a provider's own words: a model phrase, then the failure.
_MODEL_MISSING_PHRASE = re.compile(r"model.*(not found|does not exist|unknown)", re.IGNORECASE)


class SubAgentProviderError(RuntimeError):
    """The child's model call failed: *detail* is what the turn answered (or why it never
    ran); *failures* are what the backends noted (``ProviderFailure`` or dicts)."""

    def __init__(self, detail: str, failures: Any = ()) -> None:
        super().__init__(str(detail))
        self.detail = str(detail)
        self.failures = list(failures or ())


def _failure_dict(item: Any) -> Optional[dict]:
    if hasattr(item, "as_dict"):
        try:
            return item.as_dict()
        except Exception:
            return None
    return dict(item) if isinstance(item, dict) else None


def _names_model(text: str, model: str) -> bool:
    """*model* appears in *text* as a whole name (``foo`` is not in ``foo-large``)."""
    edge = r"[\w.:/@+-]"
    return re.search(rf"(?<!{edge}){re.escape(model)}(?!{edge})", text) is not None


def _rejected_for(result: Any, model: str) -> bool:
    """Whether a failed child's result says the provider does not know *model*."""
    if not isinstance(result, dict) or result.get("error") != "provider_failed":
        return False
    failures = [f for f in (result.get("failures") or []) if isinstance(f, dict)]
    if failures:
        # A backend may name the model without its vendor prefix (Gemini is asked for
        # "gemini-2.5-pro" when the setting says "google/gemini-2.5-pro").
        names = {model, model.rsplit("/", 1)[-1]}
        return all(f.get("kind") == "model_not_found" and f.get("model") in names for f in failures)
    detail = str(result.get("detail") or "")
    return bool(_MODEL_MISSING_PHRASE.search(detail)) and _names_model(detail, model)


class NullRunner:
    """Offline default — echoes the task without a real agent."""

    async def __call__(self, task: str, session_id: str, agent: str) -> dict:
        return {"output": f"[stub:{agent or 'sub'}] {task}", "session_id": session_id}


def _runner_accepts(runner, name: str) -> bool:
    """Whether the injected runner declares kwarg *name* (additive opt-in)."""
    try:
        if inspect.isfunction(runner) or inspect.ismethod(runner):
            target = runner
        elif callable(runner):
            target = runner.__call__
        else:
            target = runner
        params = inspect.signature(target).parameters
        return name in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        return False


def _runner_accepts_blocked(runner) -> bool:
    """Whether the injected runner declares a `blocked` kwarg (additive opt-in)."""
    return _runner_accepts(runner, "blocked")


@dataclass(frozen=True)
class SteerMessage:
    """One steer delivered to a running child. Immutable, origin-validated."""

    spawn_id: str
    text: str
    origin: str = "user"
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.spawn_id, str) or not self.spawn_id:
            raise ValueError("steer requires a spawn_id")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("steer text must be a non-empty string")
        if len(self.text) > STEER_MAX_CHARS:
            raise ValueError(f"steer text exceeds {STEER_MAX_CHARS} chars")
        if self.origin not in STEER_ORIGINS:
            raise ValueError(f"steer origin must be one of {sorted(STEER_ORIGINS)}")

    def to_dict(self) -> dict:
        # `can_approve` is a hard-coded False on purpose: a runner reading its
        # inbox can never mistake a steer for a human decision.
        return {"spawn_id": self.spawn_id, "text": self.text, "origin": self.origin,
                "ts": self.ts, "can_approve": False}


class SteerChannel:
    """Per-spawn inbox handed to runners that accept a ``steer`` kwarg.

    A runner drains it with :meth:`poll` (non-blocking) between its own steps,
    or awaits :meth:`get` when it wants to block for guidance. ``stop_requested``
    flips when the manager begins cancelling the child, so a cooperative runner
    can wind down before the CancelledError lands."""

    def __init__(self, spawn_id: str) -> None:
        from collections import deque

        self.spawn_id = spawn_id
        self._q: asyncio.Queue = asyncio.Queue()
        self._pending = deque()
        self.stop_requested = False
        self.delivered: list[dict] = []

    def push(self, msg: SteerMessage) -> None:
        item = msg.to_dict()
        self._pending.append(item)
        self._q.put_nowait(item)

    def peek(self, *, max_messages: int = 32) -> list[dict]:
        """Read the FIFO prefix without acknowledging model delivery."""
        from itertools import islice

        if type(max_messages) is not int or max_messages < 1:
            raise ValueError("max_messages must be a positive integer")
        return [dict(item) for item in islice(self._pending, max_messages)]

    def poll(self, *, max_messages: int | None = None) -> list[dict]:
        if max_messages is not None and (type(max_messages) is not int or max_messages < 1):
            raise ValueError("max_messages must be a positive integer")
        out: list[dict] = []
        while max_messages is None or len(out) < max_messages:
            try:
                item = self._q.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._pending.popleft()
            self.delivered.append(item)
            out.append(item)
        return out

    async def get(self, timeout: Optional[float] = None) -> Optional[dict]:
        try:
            if timeout is None:
                item = await self._q.get()
            else:
                item = await asyncio.wait_for(self._q.get(), timeout)
        except TimeoutError:
            return None
        self._pending.popleft()
        self.delivered.append(item)
        return item

    @property
    def pending(self) -> int:
        return self._q.qsize()


#: H400 — bounds on checking a child's answer (B1): a check can never raise, never
#: recurse without bound and never report without bound.
VALIDATE_MAX_DEPTH = 32
VALIDATE_MAX_VIOLATIONS = 50
SCHEMA_UNUSABLE = "$: the output schema could not be applied"


def _shown(value: Any, limit: int = 80) -> str:
    """A bounded ``repr`` for a violation line."""
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001 — a repr that fails is not worth failing for
        text = f"<{type(value).__name__}>"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def validate_output(value: Any, schema: Any, path: str = "$") -> list[str]:
    """Validate *value* against a minimal schema: ``type`` / ``required`` / ``enum``
    (plus nested ``properties`` and ``items``). Returns a list of violations —
    empty means valid. Unknown keywords are ignored; a non-dict schema is a
    single violation rather than an exception.

    H400 (B1): it never raises, whatever JSON the schema and the value are — a
    ``required`` member that is not a property name, an unhashable one, a schema nested
    past ``VALIDATE_MAX_DEPTH``, a value too deep to compare — each is a violation, and
    at most ``VALIDATE_MAX_VIOLATIONS`` are reported."""
    out: list[str] = []
    try:
        _validate(value, schema, path, out, 0)
    except Exception:  # noqa: BLE001 — RecursionError, a comparison that fails, …
        logger.warning("an output schema could not be applied", exc_info=True)
        return [SCHEMA_UNUSABLE]
    return out[:VALIDATE_MAX_VIOLATIONS]


def _validate(value: Any, schema: Any, path: str, out: list, depth: int) -> None:
    if len(out) >= VALIDATE_MAX_VIOLATIONS:
        return
    if depth > VALIDATE_MAX_DEPTH:
        out.append(f"{path}: the schema nests deeper than {VALIDATE_MAX_DEPTH} levels")
        return
    if not isinstance(schema, dict):
        out.append(f"{path}: schema must be an object")
        return
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        checks = [_TYPE_CHECKS.get(t) if isinstance(t, str) else None for t in types]
        if not checks or any(c is None for c in checks):
            out.append(f"{path}: unknown type {_shown(expected)}")
        elif not any(c(value) for c in checks if c is not None):
            out.append(f"{path}: expected type {_shown(expected)}, got {type(value).__name__}")
            return
    enum = schema.get("enum")
    if "enum" in schema:
        if not isinstance(enum, list):
            out.append(f"{path}: enum must be a list")
        elif value not in enum:
            out.append(f"{path}: value {_shown(value)} not in enum {_shown(enum)}")
    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
            out.append(f"{path}: required must be a list of property names")
        elif isinstance(value, dict):
            for key in required:
                if key not in value:
                    out.append(f"{path}: missing required property {_shown(key)}")
        else:
            out.append(f"{path}: required properties on non-object")
    props = schema.get("properties")
    if isinstance(props, dict) and isinstance(value, dict):
        for key, sub in props.items():
            if isinstance(key, str) and key in value:
                _validate(value[key], sub, f"{path}.{key}", out, depth + 1)
    items = schema.get("items")
    if isinstance(items, dict) and isinstance(value, list):
        for i, item in enumerate(value):
            if len(out) >= VALIDATE_MAX_VIOLATIONS:
                return
            _validate(item, items, f"{path}[{i}]", out, depth + 1)


def schema_problem(schema: Any, _depth: int = 0) -> Optional[str]:
    """Why *schema* cannot be used as an output schema, or None. Never raises."""
    try:
        return _schema_problem(schema, _depth)
    except Exception:  # noqa: BLE001 — RecursionError on a hostile shape, …
        return "the schema could not be read"


def _schema_problem(schema: Any, _depth: int = 0) -> Optional[str]:
    """Why *schema* cannot be used as an ``answer_schema``, or None. Checked before a
    child is spent on: an object of bounded size and depth whose ``type`` names are
    ones :func:`validate_output` knows and whose ``required`` / ``enum`` /
    ``properties`` / ``items`` have the shapes it reads."""
    if not isinstance(schema, dict):
        return "a schema is a JSON object"
    if _depth == 0:
        try:
            size = len(json.dumps(schema, allow_nan=False))
        except (TypeError, ValueError):
            return "a schema is plain JSON"
        if size > ANSWER_SCHEMA_MAX_BYTES:
            return f"a schema is at most {ANSWER_SCHEMA_MAX_BYTES} bytes"
    if _depth > ANSWER_SCHEMA_MAX_DEPTH:
        return f"a schema nests at most {ANSWER_SCHEMA_MAX_DEPTH} levels"
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not types or any(not isinstance(t, str) or t not in _TYPE_CHECKS for t in types):
            return f"unknown type {expected!r}"
    required = schema.get("required")
    if required is not None and (not isinstance(required, list)
                                 or any(not isinstance(key, str) for key in required)):
        return "required is a list of property names"
    if "enum" in schema and not isinstance(schema["enum"], list):
        return "enum is a list"
    props = schema.get("properties")
    if props is not None:
        if not isinstance(props, dict):
            return "properties is an object"
        for sub in props.values():
            problem = _schema_problem(sub, _depth + 1)
            if problem:
                return problem
    if "items" in schema:
        return _schema_problem(schema["items"], _depth + 1)
    return None


#: H400 (B1): the longest answer whose JSON is looked for, and how deep that JSON may nest.
ANSWER_JSON_MAX_CHARS = 200_000
ANSWER_JSON_MAX_DEPTH = 32


def json_depth_exceeds(value: Any, limit: int) -> bool:
    """Whether *value* nests containers deeper than *limit* (iterative: never recurses)."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, (dict, list)):
            if depth > limit:
                return True
            children = item.values() if isinstance(item, dict) else item
            stack.extend((child, depth + 1) for child in children)
    return False


def extract_json_candidate(text: Any) -> tuple[bool, Any]:
    """``(found, value)``: the JSON a child answered with. The whole text, the body of a
    leading code fence, or the outermost ``{...}`` / ``[...]`` span is tried in turn.

    H400 (B1): it never raises. An answer over ``ANSWER_JSON_MAX_CHARS`` is not parsed,
    a parse that recurses too deep is no JSON, and a value nesting deeper than
    ``ANSWER_JSON_MAX_DEPTH`` is not returned (the caller checks, renders and logs it,
    and each of those walks it)."""
    if not isinstance(text, str) or len(text) > ANSWER_JSON_MAX_CHARS:
        return False, None
    body = text.strip()
    fence = re.match(r"```[A-Za-z0-9_-]*[ \t]*\r?\n(.*?)\r?\n?```", body, re.DOTALL)
    candidates = [body] + ([fence.group(1).strip()] if fence else [])
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = body.find(opener), body.rfind(closer)
        if 0 <= start < end:
            candidates.append(body[start:end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError, RecursionError):
            continue
        if json_depth_exceeds(value, ANSWER_JSON_MAX_DEPTH):
            return False, None
        return True, value
    return False, None


def goal_problem(goal: str, *, batch_size: int) -> Optional[str]:
    """The batch quality gate for one goal (Hermes ``_validate_batch_tasks``), or None.

    A placeholder (``todo``, ``task 3``), an unexpanded template marker (a multi-word
    name in ``<...>`` or ``{...}``; ``Vec<T>``, ``<div>`` and ``{"k": 1}`` are not one),
    or, in a batch of two or more, a goal under ten characters. Duplicate goals are
    allowed on purpose (best-of-N)."""
    normalized = " ".join(str(goal).split())
    shown = normalized[:60]
    if _PLACEHOLDER_GOAL.fullmatch(normalized):
        return (f"placeholder goal ('{shown}'): replace it with a specific, self-contained "
                "description of what the sub-agent should accomplish")
    marker = _TEMPLATE_MARKER.search(normalized)
    if marker:
        return (f"unexpanded template marker ('{marker.group(0)[:60]}'): substitute the real "
                "value, a sub-agent cannot resolve placeholders")
    if batch_size >= 2 and len(normalized) < MIN_BATCH_GOAL_CHARS:
        return (f"goal too short ('{shown}'): write a specific, self-contained goal of at "
                f"least {MIN_BATCH_GOAL_CHARS} characters")
    return None


def build_child_prompt(task: str, context: Optional[str] = None,
                       answer_schema: Optional[dict] = None) -> str:
    """The focused brief a delegated child is given instead of its parent's history."""
    parts = [
        "You are a sub-agent working on one delegated task for another agent. You cannot "
        "see its conversation: everything you are given is below.",
        "Work only on this task with the tools you are offered. You cannot ask the user a "
        "question, write long-term memory, propose skills, send messages, use the board or "
        "delegate further. Your whole final reply is handed back to the agent that "
        "delegated the task, as data: report what you did and what you found, concisely.",
        f"TASK:\n{task}",
    ]
    if context and context.strip():
        parts.append(f"CONTEXT:\n{context.strip()}")
    if answer_schema is not None:
        parts.append(
            "OUTPUT CONTRACT (machine-validated):\nYour final reply must be a single JSON value "
            "that validates against this schema. No prose before or after it; a ```json code "
            "fence is acceptable.\n" + json.dumps(answer_schema, indent=2, sort_keys=True))
    return "\n\n".join(parts)


# ── the spawn pause (H400): one sentinel file is the truth ───────────────────

def default_pause_path() -> Path:
    from .paths import data_path

    return data_path("subagents", PAUSE_SENTINEL)


def read_pause(path: Path) -> Optional[dict]:
    """``{"reason", "paused_at", "by"}`` when spawning is paused, else None. Blocking.

    Fail safe: a sentinel that cannot be stat'ed or read still pauses (all fields None)."""
    try:
        if not path.exists():
            return None
    except OSError:
        return {"reason": None, "paused_at": None, "by": None}
    state = {"reason": None, "paused_at": None, "by": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key in state:
                value = raw.get(key)
                state[key] = value if isinstance(value, (str, int, float)) and value != "" else None
    except (OSError, ValueError):
        pass
    return state


def write_pause(path: Path, paused: bool, *, reason: str = "", actor: str = "") -> None:
    """Create or remove the sentinel. Blocking; raises ``OSError`` when it could not."""
    if not paused:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    body = json.dumps({"reason": str(reason or "")[:PAUSE_REASON_MAX] or None,
                       "paused_at": time.time(), "by": str(actor or "")[:80] or None})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(body + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):      # already moved into place, or never written
            tmp.unlink()


def _estop_halt() -> Optional[str]:
    """The default halt probe: the install's emergency stop. Blocking (one stat)."""
    from . import estop

    return "estop_engaged" if estop.is_engaged() else None


def _default_cost_probe() -> dict:
    """Read the live cost tracker (best-effort; empty when unavailable)."""
    try:
        from . import cost_tracker
        return cost_tracker.get_summary()
    except Exception:
        logger.debug("cost probe unavailable", exc_info=True)
        return {}


def _cost_totals(summary: Any) -> Optional[dict]:
    agents = summary.get("agents") if isinstance(summary, dict) else None
    if not isinstance(agents, dict):
        return None
    tot = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for data in agents.values():
        if not isinstance(data, dict):
            continue
        for k in ("input_tokens", "output_tokens"):
            try:
                tot[k] += int(data.get(k, 0) or 0)
            except (TypeError, ValueError):
                continue
        try:
            tot["cost_usd"] += float(data.get("cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
    return tot


def _usage_from_result(result: Any) -> Optional[dict]:
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(usage, dict):
        return None
    try:
        return {"input_tokens": int(usage.get("input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
                "cost_usd": round(float(usage.get("cost_usd", 0.0) or 0.0), 6),
                "source": "runner_usage"}
    except (TypeError, ValueError):
        return None


def _compact_for_log(rec: dict, limit: int = 2000) -> dict:
    """Bound the persisted line: long outputs are previewed, not stored whole."""
    out = {k: v for k, v in rec.items() if k != "result"}
    result = rec.get("result")
    if isinstance(result, dict):
        preview = dict(result)
        for k, v in list(preview.items()):
            if isinstance(v, str) and len(v) > limit:
                preview[k] = v[:limit] + "…"
        out["result"] = preview
    elif isinstance(result, str):
        out["result"] = result[:limit]
    else:
        out["result"] = result
    return out


# G18 (H404) — the only tools a read-only reviewer may be given: reads of files in the
# folder it reviews. Everything networked (web, A2A, MCP), and every search over the
# owner's sessions or memory, is out: the reviewer reads private code and untrusted text,
# so it must have no channel that could carry either out.
REVIEWER_TOOLS = frozenset({"file_read", "file_list", "file_search"})

# ── G18 (H401): live transcripts, tool trace, timeout dumps ─────────────────────

#: How often a running child's durable row is touched, and how long a child may go
#: without any activity (a tool event, a steer) before it is marked stalled.
HEARTBEAT_SECONDS = 10.0
DEFAULT_STALL_SECONDS = 120.0
STALL_MIN_SECONDS = 10.0
STALL_MAX_SECONDS = 3600.0
#: A transcript's bounds: events kept on disk, bytes on disk, events kept for a dump.
TRANSCRIPT_MAX_EVENTS = 2000
TRANSCRIPT_MAX_BYTES = 2_000_000
TRANSCRIPT_RECENT = 40
TRANSCRIPT_TEXT_CHARS = 2000
DUMP_STACK_FRAMES = 25
#: Transcripts and dumps kept on disk (the newest; pruned at each start).
STATE_FILES_KEPT = 500

_TRACE: ContextVar[Optional["Transcript"]] = ContextVar("nerva_subagent_trace", default=None)


class Transcript:
    """One child's live transcript: an append-only JSONL file the owner can tail.

    What goes in is bounded and never a tool's arguments or result: the start (goal,
    agent, tool count, worktree), the tool loop's own events for this child (tool name,
    status, call id, sizes and timings as ``observability.tool_events`` already bounds
    them — the ``tool_trace``), steer messages, a stall, and the end (status, error,
    an output preview). Past :data:`TRANSCRIPT_MAX_EVENTS` events or
    :data:`TRANSCRIPT_MAX_BYTES` bytes one ``truncated`` marker is written and the rest
    is dropped. Writes never raise into the child."""

    def __init__(self, path: Optional[Path], on_activity: Optional[Callable[[float], None]] = None) -> None:
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._count = 0
        self._bytes = 0
        self._truncated = False
        self.recent: list[dict] = []
        self.tool_calls = 0
        self._on_activity = on_activity

    def append(self, kind: str, **fields: Any) -> None:
        now = time.time()
        row = {"seq": 0, "at": round(now, 3), "type": str(kind)[:40]}
        for key, value in list(fields.items())[:16]:
            if isinstance(value, str):
                value = value[:TRANSCRIPT_TEXT_CHARS]
            elif not (value is None or isinstance(value, (bool, int, float))):
                try:
                    value = json.loads(json.dumps(value, default=str))
                except (TypeError, ValueError):
                    value = type(value).__name__
            row[str(key)[:40]] = value
        try:
            with self._lock:
                self._count += 1
                row["seq"] = self._count
                self.recent.append(row)
                del self.recent[:-TRANSCRIPT_RECENT]
                if kind == "tool" and row.get("event") in {"tool_result", "tool_failed"}:
                    self.tool_calls += 1
                if self.path is None or self._truncated:
                    pass
                else:
                    line = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
                    if self._count > TRANSCRIPT_MAX_EVENTS or self._bytes + len(line) > TRANSCRIPT_MAX_BYTES:
                        self._truncated = True
                        line = json.dumps({"seq": self._count, "at": row["at"], "type": "truncated"}) + "\n"
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as stream:
                        stream.write(line)
                    self._bytes += len(line)
        except Exception:  # noqa: BLE001 — observability never breaks the child
            logger.debug("sub-agent transcript write failed", exc_info=True)
        if self._on_activity is not None:
            with contextlib.suppress(Exception):
                self._on_activity(now)


def trace_tool_event(row: Any) -> None:
    """Called by ``observability.tool_events`` for every tool-loop event: when the code
    in flight belongs to a sub-agent, the (already bounded) event joins its transcript."""
    transcript = _TRACE.get()
    if transcript is None or not isinstance(row, dict):
        return
    transcript.append("tool", **{k: v for k, v in row.items() if k not in {"at", "seq"}})


def read_transcript(path: Path, *, after: int = 0, limit: int = 200) -> list[dict]:
    """Events of a transcript file with ``seq`` > *after* (at most *limit*)."""
    bound = max(1, min(int(limit or 1), 1000))
    out: list[dict] = []
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and int(row.get("seq") or 0) > after:
                    out.append(row)
                    if len(out) >= bound:
                        break
    except FileNotFoundError:
        return []
    return out


def _parent_session() -> Optional[str]:
    """The conversation the spawn is made from (its results are delivered back to it)."""
    try:
        from .kernel.plan_mode import current_session

        return current_session()
    except Exception:  # noqa: BLE001
        return None


def _worktree_view(report: Optional[dict]) -> Optional[dict]:
    """What the parent is told about a child's tree: its branch, whether it was kept, the
    commits and files it changed, and the stale-file reminder (H401) when it changed any."""
    if not isinstance(report, dict):
        return None
    view = {key: report[key] for key in ("branch", "path", "kept", "reason", "commits",
                                          "changed_files", "changed_files_total", "archive")
            if key in report}
    if report.get("changed_files"):
        view["stale_files_notice"] = (
            "The sub-agent changed these files on its own branch. Any copy of them you read "
            "earlier is stale: re-read them (or review the branch) before relying on or editing them.")
    return view


def _stack_of(task: Optional[asyncio.Future]) -> list[str]:
    """Where a hung child's coroutine waits (file:line function), outermost first: the
    task's coroutine and every coroutine it is awaiting, down to the innermost."""
    get_coro = getattr(task, "get_coro", None)
    coro = get_coro() if callable(get_coro) else None
    frames: list[str] = []
    with contextlib.suppress(Exception):
        while coro is not None and len(frames) < DUMP_STACK_FRAMES:
            frame = getattr(coro, "cr_frame", None) or getattr(coro, "gi_frame", None)
            if frame is None:
                break
            code = frame.f_code
            frames.append(f"{code.co_filename}:{frame.f_lineno} {code.co_name}")
            coro = getattr(coro, "cr_await", None) or getattr(coro, "gi_yieldfrom", None)
    return frames


class SubAgentManager:
    """Gated, isolated, concurrent, steerable sub-agent spawning."""

    def __init__(self, runner: Optional[Callable[..., Awaitable[dict]]] = None,
                 max_concurrent: int = 3, parent_agent: str = "jarvis",
                 max_depth: Optional[int] = 8,
                 budget: Optional["IterationBudget"] = None,
                 blocked: Optional[frozenset] = None,
                 cost_probe: Optional[Callable[[], dict]] = None,
                 spawn_log: Optional[Path] = None,
                 persist: Optional[bool] = None,
                 decision_hook: Optional[Callable[..., Awaitable[Any]]] = None,
                 selection_defaults: Optional[Callable[[], dict]] = None,
                 fallback_probe: Optional[Callable[[str], Optional[str]]] = None,
                 turn_cap: Any = DEFAULT_TURN_SPAWN_CAP,
                 child_timeout: Any = DEFAULT_CHILD_TIMEOUT_SECONDS,
                 halt_probe: Optional[Callable[[], Optional[str]]] = None,
                 pause_path: Optional[Path] = None,
                 tool_registry: Optional[Callable[[], Iterable[str]]] = None,
                 store: Any = None,
                 worktree_provider: Optional[Callable[[str], Any]] = None,
                 read_only_probe: Optional[Callable[[str], bool]] = None,
                 stall_seconds: Any = DEFAULT_STALL_SECONDS,
                 heartbeat_seconds: float = HEARTBEAT_SECONDS,
                 state_dir: Optional[Path] = None,
                 admission_runtime: Any = None) -> None:
        self._runner = runner or NullRunner()
        # G18 (H401) — the durable delegation rows (the autonomy queue in prod: a
        # ``TaskQueue`` or a reader returning one), this boot's id, the per-child live
        # transcripts and timeout dumps under ``state_dir``, and the stall monitor.
        self._store = store
        self.boot_id = uuid.uuid4().hex[:16]
        self._state_dir = Path(state_dir) if state_dir is not None else None
        self._stall_seconds = stall_seconds
        self.heartbeat_seconds = max(0.05, float(heartbeat_seconds))
        self._background: set = set()
        self._pruned = False
        self._transcripts: dict[str, Transcript] = {}
        # G18 (H402) — a child's own git worktree (``autonomy.subagent_worktrees`` in
        # prod): called on a worker thread with the spawn id, it answers a
        # ``worktrees.ChildTree`` or None (no isolation for this child), or raises
        # ``WorktreeRefused`` (the spawn then fails, never runs unisolated).
        self._worktree_provider = worktree_provider
        # G18 (H404) — which registered tools only read (ToolRPC's declared effect in
        # prod); a read-only child (the /review reviewer) is given those and no others.
        self._read_only_probe = read_only_probe
        # H400 — the spawn gate. `halt_probe` answers why no new child may start (the
        # emergency stop by default; prod adds the kill switch), `pause_path` is the
        # owner's pause sentinel, and `_gate_lock` is held by every admission and by the
        # pause writer, so a pause that has been answered is in force for every spawn
        # admitted after it. Both reads block, so they run on a worker thread.
        self._halt_probe = halt_probe or _estop_halt
        self._pause_path = Path(pause_path) if pause_path is not None else None
        self._gate_lock = asyncio.Lock()
        # A restart drain owns this ephemeral gate in production. Standalone managers
        # retain their existing behavior when no runtime was supplied.
        self._admission_runtime = admission_runtime
        self._admission_leases: dict[str, Any] = {}
        self._admission_slots_done: set[str] = set()
        self._admission_settled: set[str] = set()
        self._settlement_tasks: dict[str, asyncio.Task] = {}
        # H400 — the per-child wall clock: a number or a reader (the setting in prod).
        self._child_timeout = child_timeout
        # H400 — the registered tool names (ToolRPC in prod). With it a spawn records
        # and hands its runner the child's allowlist; without it there is none to give.
        self._tool_registry = tool_registry
        self._runner_takes_tools = _runner_accepts(self._runner, "tools")
        self._settling: set = set()
        # H400 — the spawns holding a slot, and the sync tool threads each child started
        # (ToolRPC adds them through ``bind_sync_thread_sink``): a slot is given back only
        # when its child's task has ended AND its last tool thread has returned.
        self._held: set[str] = set()
        self._threads: dict[str, set] = {}
        # H681: where a child's model comes from when its spawn names none (the
        # autonomy.subagent_* settings in prod), and what it would run on without it.
        self._selection_defaults = selection_defaults
        self._fallback_probe = fallback_probe
        self._runner_takes_selection = _runner_accepts(self._runner, "selection")
        self.max_concurrent = max(1, int(max_concurrent))
        self.parent_agent = parent_agent
        # H20.6 hardening: total-spawn budget (refundable IterationBudget) on top
        # of the concurrency cap — None keeps today's unbounded-total behavior.
        self.budget = budget
        # H486: how many spawns one tool-loop turn may make (Hermes caps delegate_task at
        # 50 per turn). Read at each spawn (a setting reader in prod); 0 = no ceiling, an
        # unreadable value = the shipped ceiling. Keyed on the tool loop's own turn token,
        # so a spawn outside any turn (the HTTP routes) is left to the per-boot budget; the
        # model's delegate_task tool (H400) spawns inside one and is counted.
        self._turn_cap = turn_cap
        self._turn_spawns: dict[str, int] = {}
        # Capability scoping for children (hermes DELEGATE_BLOCKED_TOOLS analog).
        self.blocked = frozenset(blocked) if blocked is not None else DELEGATE_BLOCKED_CAPABILITIES
        self._runner_takes_blocked = _runner_accepts_blocked(self._runner)
        self._runner_takes_steer = _runner_accepts(self._runner, "steer")
        # K3 (OWASP unbounded-consumption): cap the recursion DEPTH of agent-initiated
        # delegation — an agent spawning sub-agents that spawn sub-agents can't tower up
        # forever. None = unbounded. Depth is inferred from the recorded parent-chain, so
        # it needs no runner cooperation (the spawning sub-agent just passes its own id as
        # `parent`, which it already does to attribute the spawn).
        self.max_depth = max_depth if (max_depth is None or max_depth > 0) else None
        # Per-delegation cost: tracker snapshot around the run (injectable for tests).
        self._cost_probe = cost_probe or _default_cost_probe
        # Observability-only persistence (default off; env flag or explicit `persist`).
        self.persist = env_flag(SPAWN_LOG_ENV) if persist is None else bool(persist)
        self._spawn_log = Path(spawn_log) if spawn_log is not None else None
        self._log_lock = threading.Lock()
        # The only path from a spawn context to an approval decision. In prod the
        # integrator wires worker.apply_decision; `decide()` refuses agent-origin
        # requests before this hook is ever consulted.
        self._decision_hook = decision_hook
        self._spawns: dict[str, dict] = {}
        self._channels: dict[str, SteerChannel] = {}
        self._tasks: dict[str, asyncio.Future] = {}
        self._active = 0
        self._counter = 0

    # ── the per-turn ceiling (H486) ──────────────────────────────
    def turn_cap(self) -> int:
        """The spawns one tool-loop turn may make: a whole number, 0 = no ceiling; an
        unreadable or failing reader is the shipped ceiling, never "off"."""
        raw = self._turn_cap
        if callable(raw):
            try:
                raw = raw()
            except Exception:
                logger.warning("sub-agent turn ceiling unreadable; the shipped ceiling applies")
                return DEFAULT_TURN_SPAWN_CAP
        if isinstance(raw, bool):
            return DEFAULT_TURN_SPAWN_CAP
        try:
            return max(0, int(raw))
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_TURN_SPAWN_CAP

    def _note_turn_spawn(self, turn: str) -> None:
        # Re-insert so the table is ordered by recency of the last spawn.
        self._turn_spawns[turn] = self._turn_spawns.pop(turn, 0) + 1
        # Turn tokens are fresh per run; keep only the most recent few so a long-lived
        # process does not grow a table of finished turns.
        while len(self._turn_spawns) > TURN_SPAWN_HISTORY:
            del self._turn_spawns[next(iter(self._turn_spawns))]

    # ── the spawn gate: emergency stop, pause, timeout (H400) ────
    def child_timeout(self) -> float:
        """Seconds one child may run: the configured value clamped into
        ``CHILD_TIMEOUT_MIN_SECONDS``..``CHILD_TIMEOUT_MAX_SECONDS``; an unreadable,
        non-numeric, non-finite or non-positive one is the shipped default, never "off"."""
        raw = self._child_timeout
        if callable(raw):
            try:
                raw = raw()
            except Exception:
                logger.warning("sub-agent timeout unreadable; the shipped timeout applies")
                return DEFAULT_CHILD_TIMEOUT_SECONDS
        if isinstance(raw, bool):
            return DEFAULT_CHILD_TIMEOUT_SECONDS
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_CHILD_TIMEOUT_SECONDS
        if value != value or value in (float("inf"), float("-inf")) or value <= 0:
            return DEFAULT_CHILD_TIMEOUT_SECONDS
        return min(max(CHILD_TIMEOUT_MIN_SECONDS, value), CHILD_TIMEOUT_MAX_SECONDS)

    def pause_path(self) -> Path:
        if self._pause_path is None:
            self._pause_path = default_pause_path()
        return self._pause_path

    def _halt_state(self) -> dict:
        """What stops new spawns right now. Blocking: call it on a worker thread.

        Fail closed: a probe or a sentinel that cannot be read stops spawning."""
        try:
            halted = self._halt_probe()
        except Exception:
            logger.warning("sub-agent halt probe failed; new spawns are refused", exc_info=True)
            halted = "halt_state_unknown"
        if halted is not None and (not isinstance(halted, str) or halted not in HALT_REASONS):
            halted = "halt_state_unknown"
        try:
            pause = read_pause(self.pause_path())
        except Exception:
            logger.warning("sub-agent pause state unreadable; new spawns are refused", exc_info=True)
            pause = {"reason": None, "paused_at": None, "by": None}
        return {"halted": halted, "paused": pause is not None, "pause": pause}

    @staticmethod
    def _halt_refusal(state: dict) -> Optional[dict]:
        if state["halted"]:
            return {"ok": False, "reason": state["halted"],
                    "detail": "new sub-agents are stopped; running ones are not affected"}
        if state["paused"]:
            return {"ok": False, "reason": "spawn_paused", "pause": state["pause"],
                    "detail": "sub-agent spawning is paused; running ones are not affected"}
        return None

    async def gate_state(self) -> dict:
        """``{"halted", "paused", "pause", "accepting"}`` — read under the gate lock, so
        it is the state the next admitted spawn sees."""
        async with self._gate_lock:
            state = await asyncio.to_thread(self._halt_state)
        return {**state, "accepting": self._halt_refusal(state) is None}

    async def set_paused(self, paused: bool, *, reason: str = "", actor: str = "") -> dict:
        """Pause or resume NEW spawns and answer the state read back from the sentinel.

        Holds the gate lock, so no spawn is admitted between the write and the answer.
        Running children are not touched. A resume that could not remove the sentinel,
        or a pause that could not write it, raises ``OSError`` with nothing claimed."""
        async with self._gate_lock:
            await asyncio.to_thread(write_pause, self.pause_path(), bool(paused),
                                    reason=reason, actor=actor)
            state = await asyncio.to_thread(self._halt_state)
        logger.info("sub-agent spawning %s by %s", "paused" if state["paused"] else "resumed",
                    str(actor or "?")[:80])
        return {**state, "accepting": self._halt_refusal(state) is None}

    def _child_tools(self, parent_offer: Optional[Iterable[str]], agent: str = "") -> Optional[frozenset]:
        """The child's allowlist, or None when no registry was given to draw it from.
        A registry that cannot be read gives the child no tools at all."""
        if self._tool_registry is None:
            if parent_offer is None:
                return None
            return child_tool_allowlist(parent_offer, parent_offer, self.blocked)
        try:
            # H400 (minor 4): the registry reader is asked for what THIS child would be
            # offered (in prod: the tool profile for its agent, principal and surface),
            # so the record says what the child really gets.
            registered = list(self._tool_registry(agent))
        except Exception:
            logger.warning("tool registry unreadable; the sub-agent gets no tools", exc_info=True)
            return frozenset()
        return child_tool_allowlist(registered, parent_offer, self.blocked)

    # ── introspection ────────────────────────────────────────────
    def _active_count(self) -> int:
        return self._active

    def _depth_of(self, parent: str) -> int:
        """How deep a spawn under *parent* would sit (0 = top-level, i.e. parent is the
        root agent, not a recorded sub-agent). Walks the recorded parent links; the `seen`
        guard makes a malformed cycle terminate instead of spinning."""
        depth, cur, seen = 0, parent, set()
        while cur in self._spawns and cur not in seen:
            seen.add(cur)
            depth += 1
            cur = self._spawns[cur].get("parent", "")
        return depth

    def _set_status(self, rec: dict, new: str) -> None:
        cur = rec["status"]
        if new not in SPAWN_TRANSITIONS.get(cur, frozenset()):
            raise ValueError(f"illegal spawn transition {cur} -> {new}")
        rec["status"] = new

    # ── spawn ────────────────────────────────────────────────────
    def _read_defaults(self) -> dict:
        """The setting-chosen model and provider (empty when unset or unreadable)."""
        if self._selection_defaults is None:
            return {}
        try:
            got = self._selection_defaults()
        except Exception:
            logger.warning("could not read %s / %s; the child runs on the parent's model",
                           SUBAGENT_MODEL_SETTING, SUBAGENT_PROVIDER_SETTING, exc_info=True)
            return {}
        return got if isinstance(got, dict) else {}

    def _resolve_selection(self, model: Any, provider: Any, overrides: Any):
        """``(selection, overrides)`` for one child, or ValueError naming what is wrong.
        An explicit model or provider is taken as a pair; otherwise the setting's pair;
        otherwise none (the parent's route)."""
        from .llm.job_selection import validate_pins
        from .llm.request_context import validate_overrides

        ov = validate_overrides(overrides)
        pins = {k: v for k, v in (("model", model), ("provider", provider)) if v is not None and v != ""}
        if pins:
            validate_pins(pins)
            source = "explicit"
        else:
            defaults = self._read_defaults()
            pins = {k: defaults[k] for k in ("model", "provider") if defaults.get(k)}
            if pins:
                try:
                    validate_pins(pins)
                except ValueError as exc:
                    raise ValueError(f"{SUBAGENT_MODEL_SETTING} / {SUBAGENT_PROVIDER_SETTING}: {exc}") from exc
                source = "setting"
            else:
                source = "parent"
        selection = {"model": pins.get("model"), "provider": pins.get("provider"),
                     "overrides": ov.as_dict() if ov is not None else None, "source": source}
        return selection, ov

    async def spawn(self, task: str, agent: str = "", parent: str = "",
                    output_schema: Optional[dict] = None, *, model: Optional[str] = None,
                    provider: Optional[str] = None, overrides: Optional[dict] = None,
                    tools: Optional[Iterable[str]] = None, context: Optional[str] = None,
                    answer_schema: Optional[dict] = None, focused: bool = False,
                    read_only: bool = False, kind: str = "delegate", background: bool = False,
                    confine: Optional[str] = None,
                    _admitted: Optional[asyncio.Future] = None) -> dict:
        """Spawn an isolated sub-agent for `task` — the one place a child starts.

        G18: every spawn has a durable row (``delegation_id``), a live transcript and a
        stall monitor; one past its timeout leaves a diagnostic dump. With the worktree
        provider on, it runs confined to its own git worktree (H402). `read_only`
        (H404, the /review reviewer) gives it only the tools that declared themselves
        read-only and runs it under the kernel's read-only floor. `background` marks a
        spawn whose result nobody waits for: it is delivered once, later, by a claim.

        Refused while new spawns are stopped (the emergency stop, the kill switch, the
        owner's pause: ``estop_engaged`` / ``kill_switch_halted`` / ``spawn_paused``, or
        ``halt_state_unknown`` when that cannot be read), when the concurrency cap is
        reached, the total-spawn budget is spent, or the parent-chain is already
        `max_depth` deep (recursion guard). The checks and the slot are taken under one
        lock. A child that outruns :meth:`child_timeout` is cancelled and recorded
        ``failed`` with ``error: timeout``.

        With `output_schema`, the runner's result must validate or the spawn is recorded
        as failed. With `answer_schema` (H400), the JSON in the child's ``output`` text
        must validate, and the parsed value is added as ``structured``. With `model` /
        `provider` / `overrides` (H681), the child runs pinned; an invalid one is refused
        (``invalid_selection``) before any budget is spent. `tools` is the set of tools
        the spawning model turn was offered (None outside a turn): the child's allowlist
        is drawn from it. `focused` gives the runner the brief built from `task`,
        `context` and `answer_schema` (:func:`build_child_prompt`) instead of the bare task.

        A spawn made from inside a running child is attributed to that child whatever
        `parent` says, so its depth cannot be understated."""
        parent = _CURRENT_SPAWN.get() or parent or self.parent_agent
        # H400 (B1): both schemas are checked before anything is spent, on every caller
        # (the routes, the batch, the tool): one the validator cannot apply is refused here.
        for schema in (output_schema, answer_schema):
            if isinstance(schema, dict):
                problem = schema_problem(schema)
                if problem:
                    return {"ok": False, "reason": "invalid_output_schema",
                            "detail": problem[:DETAIL_MAX]}
        if context is not None and (not isinstance(context, str) or len(context) > CONTEXT_MAX_CHARS):
            return {"ok": False, "reason": "invalid_context",
                    "detail": f"context is text of at most {CONTEXT_MAX_CHARS} characters"}
        timeout = self.child_timeout()
        # Built before a slot is taken: nothing between the reservation and the child's
        # task can fail and strand the slot.
        prompt = build_child_prompt(task, context, answer_schema) if focused else task
        caller_turn = current_tool_turn()
        async with self._gate_lock:
            # Blocking reads (a stat each), off the loop; the lock keeps this admission
            # and the pause writer from interleaving.
            refusal = self._halt_refusal(await asyncio.to_thread(self._halt_state))
            if refusal is not None:
                return refusal
            depth = self._depth_of(parent)
            if self.max_depth is not None and depth >= self.max_depth:
                return {"ok": False, "reason": "recursion_depth_cap",
                        "depth": depth, "max_depth": self.max_depth}
            if self._active >= self.max_concurrent:
                return {"ok": False, "reason": "concurrency_cap",
                        "active": self._active, "cap": self.max_concurrent}
            if output_schema is not None and not isinstance(output_schema, dict):
                return {"ok": False, "reason": "invalid_output_schema"}
            try:
                selection, ov = self._resolve_selection(model, provider, overrides)
            except ValueError as exc:
                return {"ok": False, "reason": "invalid_selection", "detail": str(exc)[:DETAIL_MAX]}
            turn, cap = current_tool_turn(), self.turn_cap()
            if turn is not None and cap > 0 and self._turn_spawns.get(turn, 0) >= cap:
                return {"ok": False, "reason": "turn_spawn_cap",
                        "spawned": self._turn_spawns[turn], "cap": cap}
            allowed = self._child_tools(tools, agent)
            if read_only:
                # G18 review: the reviewer reads files in the folder it reviews and
                # nothing else — no network, no session or memory search — so nothing it
                # read can leave the box. Without a folder to confine it to, no tools.
                allowed = (self._read_only_tools(allowed) & REVIEWER_TOOLS) if confine else frozenset()
            # The halt read awaited above; close_admission can run while it waits.
            # Acquire synchronously under this gate immediately before consuming any
            # budget, slot or durable record. A live parent's ContextVar cannot admit a
            # new child during drain: child spawns are never reentrant.
            lease = None
            if self._admission_runtime is not None:
                try:
                    lease = self._admission_runtime.acquire("subagent", allow_reentrant=False)
                except Exception:
                    logger.warning("sub-agent restart admission could not be checked", exc_info=True)
                    return {"ok": False, "reason": "restart_admission_unavailable"}
                if lease is None:
                    return {"ok": False, "reason": "restart_draining"}
            registered = False
            try:
                if self.budget is not None and not self.budget.consume():
                    return {"ok": False, "reason": "spawn_budget_exhausted",
                            "used": self.budget.used, "max_total": self.budget.max_total}
                if turn is not None:
                    self._note_turn_spawn(turn)
                self._counter += 1
                # The boot id makes a spawn id unique across restarts: a counter alone would
                # repeat, and a repeated id would reuse an old child's tree, branch and record.
                spawn_id = f"sub-{parent}-{self._counter}-{self.boot_id[:6]}"
                session_id = f"session::{spawn_id}"   # isolated session
                delegation_id = uuid.uuid4().hex[:20]
                now = time.time()
                rec = {"id": spawn_id, "parent": parent, "agent": agent or "sub",
                   "task": task, "session_id": session_id, "status": "running",
                   "created_at": now, "finished_at": None, "result": None,
                   "blocked": sorted(self.blocked), "output_schema": output_schema,
                   "steers": [], "steerable": self._runner_takes_steer,
                   "stop_reason": None, "cost": None, "selection": selection,
                   "tools": sorted(allowed) if allowed is not None else None,
                   "timeout_seconds": timeout,
                   # G18
                   "delegation_id": delegation_id, "kind": str(kind or "delegate")[:20],
                   "read_only": bool(read_only), "background": bool(background),
                   "parent_session": _parent_session(), "activity_at": now, "stalled": False,
                   "worktree": None, "transcript": None}
                self._spawns[spawn_id] = rec
                chan = SteerChannel(spawn_id)
                self._channels[spawn_id] = chan
                self._active += 1
                self._held.add(spawn_id)
                if lease is not None:
                    self._admission_leases[spawn_id] = lease
                registered = True
            finally:
                if lease is not None and not registered:
                    lease.release()
        # H400 (B1): from here on the slot is taken. Whatever goes wrong below — the
        # answer's check, the accounting, the log — the record ends terminal and the
        # slot is released exactly once (``_close_on_error``); nothing escapes with a
        # record left running.
        child: Optional[asyncio.Future] = None
        before: Optional[dict] = None
        monitor: Optional[asyncio.Future] = None
        try:
            before = _cost_totals(self._safe_probe())
            transcript = self._open_transcript(rec)
            tree = None
            if not read_only and self._worktree_provider is not None:
                try:
                    tree = await asyncio.to_thread(self._worktree_provider, spawn_id)
                except Exception as exc:  # noqa: BLE001 — refused isolation never runs unisolated
                    detail = str(exc)[:DETAIL_MAX] or type(exc).__name__
                    self._set_status(rec, "failed")
                    rec["result"] = {"error": "worktree_unavailable", "detail": detail}
                    transcript.append("end", status="failed", error="worktree_unavailable", detail=detail)
                if tree is not None:
                    rec["worktree"] = tree.to_dict() if hasattr(tree, "to_dict") else dict(tree)
            await self._durable_start(rec, task)
            if rec["status"] != "running":
                self._finish(rec, before, None)
                await self._persist(rec)
                await self._settle_owned(rec, child)
                return await self._answer(rec, selection, child)
            transcript.append("start", goal=task, agent=rec["agent"], read_only=bool(read_only),
                              tools=len(allowed) if allowed is not None else None,
                              worktree=(rec["worktree"] or {}).get("path"), background=bool(background))
            if _admitted is not None and not _admitted.done():
                _admitted.set_result(rec)
            child = asyncio.ensure_future(
                self._run(prompt, session_id, agent or "sub", chan, selection, ov, spawn_id, allowed,
                      {"spawn_id": spawn_id, "parent": parent, "turn": caller_turn,
                       "goal": task[:DELEGATION_GOAL_CHARS * 4]},
                      isolation={"tree": (rec["worktree"] or {}).get("path") or (confine if read_only else None),
                                 "read_only": bool(read_only), "tools": allowed, "transcript": transcript}))
            self._tasks[spawn_id] = child
            monitor = asyncio.ensure_future(self._monitor(rec, transcript))
            try:
                finished, _pending = await asyncio.wait({child}, timeout=timeout)
            except asyncio.CancelledError:
                # The *parent* was cancelled (the awaiting task went away): stop the child,
                # record it honestly and let the cancellation keep propagating upward.
                rec["stop_reason"] = rec.get("stop_reason") or "parent_cancelled"
                await self._end_cancelled(rec, child, chan, before, final="stopped",
                                          result={"error": "stopped", "reason": rec["stop_reason"]})
                self._settle_later(rec, child, monitor)
                raise
            if not finished:
                # The wall clock ran out: cancel the child's work, not just the wait for it.
                rec["stop_reason"] = "timeout"
                payload = {"error": "timeout", "timeout_seconds": timeout,
                           "detail": f"the sub-agent did not finish within {timeout:g} s and was cancelled"}
                # G18 (H401): what the hung child was doing, written before it is cancelled.
                dump = await self._timeout_dump(rec, child, transcript)
                if dump is not None:
                    payload["dump"] = dump
                    rec["dump"] = dump
                if not await self._end_cancelled(rec, child, chan, before, final="failed", result=payload):
                    logger.warning("sub-agent %s timed out and has not ended yet; its slot stays taken",
                                   spawn_id)
            else:
                try:
                    result = self._record_outcome(rec, child, output_schema, answer_schema)
                except Exception:  # noqa: BLE001 — fail closed with a fixed message
                    logger.warning("sub-agent %s: its answer could not be checked", spawn_id,
                                   exc_info=True)
                    self._mark_unchecked(rec)
                    result = None
                if ov is not None:
                    rec["overrides_applied"] = sorted(ov.taken())
                    rec["overrides_ignored"] = sorted(ov.requested() - ov.taken())
                self._finish(rec, before, result)
        except asyncio.CancelledError:
            # A child still unwinding is closed by the callback _end_cancelled attached.
            if rec.get("finished_at") is None and (child is None or child.done()):
                self._close_on_error(rec, child, before)
            self._settle_later(rec, child, monitor)
            raise
        except Exception:  # noqa: BLE001 — the slot must never be stranded
            logger.warning("sub-agent %s: the spawn failed after its slot was taken", spawn_id,
                           exc_info=True)
            self._close_on_error(rec, child, before)
        if monitor is not None:
            monitor.cancel()
        if rec["status"] in TERMINAL_STATUSES:      # a child still unwinding is logged when it ends
            await self._persist(rec)
            await self._settle_owned(rec, child)
        return await self._answer(rec, selection, child)

    async def _answer(self, rec: dict, selection: Optional[dict], child: Optional[asyncio.Future]) -> dict:
        out = {"ok": rec["status"] == "done", "id": rec["id"],
               "session_id": rec["session_id"], "status": rec["status"],
               "result": rec["result"], "cost": rec["cost"], "selection": selection,
               "delegation_id": rec.get("delegation_id")}
        if rec.get("worktree"):
            out["worktree"] = rec["worktree"]
        if "overrides_applied" in rec:
            out["overrides_applied"] = rec["overrides_applied"]
            out["overrides_ignored"] = rec["overrides_ignored"]
        return out

    # ── G18: durability, the stall monitor, worktrees, transcripts ───────────
    def stall_seconds(self) -> float:
        """How long a running child may show no activity before it is marked stalled:
        the configured value clamped into 10..3600 s; unreadable is the shipped 120 s."""
        raw = self._stall_seconds
        if callable(raw):
            try:
                raw = raw()
            except Exception:
                return DEFAULT_STALL_SECONDS
        if isinstance(raw, bool):
            return DEFAULT_STALL_SECONDS
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_STALL_SECONDS
        if value != value or value <= 0 or value == float("inf"):
            return DEFAULT_STALL_SECONDS
        return min(max(STALL_MIN_SECONDS, value), STALL_MAX_SECONDS)

    def _get_store(self) -> Any:
        store = self._store
        if store is None:
            return None
        if hasattr(store, "delegation_start"):
            return store
        if callable(store):
            try:
                found = store()
            except Exception:
                return None
            return found if hasattr(found, "delegation_start") else None
        return None

    async def _store_call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        store = self._get_store()
        method = getattr(store, name, None) if store is not None else None
        if not callable(method):
            return None
        try:
            return await asyncio.to_thread(method, *args, **kwargs)
        except Exception:  # noqa: BLE001 — logged; the child's own outcome stands
            logger.warning("sub-agent delegation store: %s failed", name, exc_info=True)
            return None

    def state_dir(self) -> Path:
        if self._state_dir is None:
            from .paths import data_path

            self._state_dir = data_path("subagents")
        return self._state_dir

    def transcript_path(self, rec: dict) -> Path:
        return self.state_dir() / "transcripts" / f"{rec['delegation_id']}.jsonl"

    def _open_transcript(self, rec: dict) -> Transcript:
        def activity(ts: float) -> None:
            rec["activity_at"] = ts
            if rec.get("stalled"):
                rec["stalled"] = False
        path = self.transcript_path(rec)
        transcript = Transcript(path, on_activity=activity)
        rec["transcript"] = str(path)
        self._transcripts[rec["id"]] = transcript
        return transcript

    def transcript(self, spawn_id: str, *, after: int = 0, limit: int = 200) -> Optional[dict]:
        """A child's live transcript (H401): ``{"id", "status", "events", "next"}``, read
        from its file — a running child's as far as it has got. None when unknown here;
        a past boot's child is found through its durable row."""
        rec = self._spawns.get(spawn_id)
        path: Optional[str] = rec.get("transcript") if rec else None
        status = rec.get("status") if rec else None
        if path is None:
            row = None
            store = self._get_store()
            if store is not None:
                with contextlib.suppress(Exception):
                    row = store.delegation_get(spawn_id) or store.delegation_by_spawn(spawn_id)
            if not row or not row.get("transcript_path"):
                return None
            path, status = row["transcript_path"], row.get("status")
        events = read_transcript(Path(path), after=after, limit=limit)
        return {"id": spawn_id, "status": status, "events": events,
                "next": events[-1]["seq"] if events else after}

    async def _durable_start(self, rec: dict, task: str) -> None:
        await self._store_call("delegation_start", {
            "delegation_id": rec["delegation_id"], "spawn_id": rec["id"], "boot_id": self.boot_id,
            "kind": rec["kind"], "parent": rec["parent"], "agent": rec["agent"],
            "parent_session": rec.get("parent_session"), "child_session": rec["session_id"],
            "goal": task, "background": rec["background"], "created_at": rec["created_at"],
            "worktree": rec.get("worktree"), "transcript_path": rec.get("transcript")})

    async def _monitor(self, rec: dict, transcript: Transcript) -> None:
        """Heartbeat the durable row and mark a child that has shown no activity for
        :meth:`stall_seconds` as ``stalled`` (it is not stopped: its timeout does that)."""
        while rec["status"] in ("running", "stopping"):
            await asyncio.sleep(self.heartbeat_seconds)
            now = time.time()
            activity = float(rec.get("activity_at") or rec["created_at"])
            stalled_at = None
            if not rec.get("stalled") and now - activity > self.stall_seconds():
                rec["stalled"] = True
                rec["stalled_at"] = stalled_at = now
                logger.warning("sub-agent %s shows no activity for %.0f s: stalled", rec["id"], now - activity)
                on_activity, transcript._on_activity = transcript._on_activity, None
                transcript.append("stalled", idle_seconds=round(now - activity, 1))
                transcript._on_activity = on_activity
            await self._store_call("delegation_touch", rec["delegation_id"], heartbeat_at=now,
                                   activity_at=activity, stalled_at=stalled_at)

    async def _timeout_dump(self, rec: dict, child: asyncio.Future, transcript: Transcript) -> Optional[str]:
        """Write what a timed-out child was doing — where its coroutine waits, its last
        transcript events, its steers and tool-thread count — before it is cancelled."""
        body = {"delegation_id": rec["delegation_id"], "spawn_id": rec["id"], "goal": rec["task"][:2000],
                "timeout_seconds": rec.get("timeout_seconds"), "started_at": rec["created_at"],
                "dumped_at": time.time(), "stack": _stack_of(child),
                "recent_events": list(transcript.recent), "tool_calls": transcript.tool_calls,
                "steers": list(rec.get("steers") or [])[-10:],
                "threads_running": sum(1 for f in self._threads.get(rec["id"], set()) if not f.done()),
                "worktree": (rec.get("worktree") or {}).get("path")}
        path = self.state_dir() / "dumps" / f"{rec['delegation_id']}.json"

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(body, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

        try:
            await asyncio.to_thread(write)
        except Exception:  # noqa: BLE001
            logger.warning("sub-agent %s: timeout dump not written", rec["id"], exc_info=True)
            return None
        transcript.append("timeout_dump", path=str(path))
        return str(path)

    def _settle_later(self, rec: dict, child: Optional[asyncio.Future],
                      monitor: Optional[asyncio.Future]) -> None:
        if monitor is not None:
            monitor.cancel()
        try:
            task = asyncio.ensure_future(self._settle_owned(rec, child))
        except RuntimeError:
            return
        self._settling.add(task)
        task.add_done_callback(self._settling.discard)

    def _maybe_release_admission(self, spawn_id: str) -> None:
        if spawn_id not in self._admission_slots_done or spawn_id not in self._admission_settled:
            return
        lease = self._admission_leases.pop(spawn_id, None)
        self._admission_slots_done.discard(spawn_id)
        self._admission_settled.discard(spawn_id)
        if lease is not None:
            lease.release()

    async def _settle_owned(self, rec: dict, child: Optional[asyncio.Future]) -> None:
        """Keep admission live through the actual durable/worktree settlement task."""
        if rec["status"] not in TERMINAL_STATUSES:
            return
        spawn_id = rec["id"]
        task = self._settlement_tasks.get(spawn_id)
        if task is None:
            task = asyncio.create_task(self._settle(rec, child))
            self._settlement_tasks[spawn_id] = task

            def completed(done: asyncio.Task) -> None:
                try:
                    done.result()
                except BaseException:
                    # Keep the failed task and its admission lease: a later caller must
                    # not mistake _settle's early marker for completed durable cleanup.
                    logger.warning("sub-agent %s settlement did not finish", spawn_id, exc_info=True)
                    return
                self._settlement_tasks.pop(spawn_id, None)
                if rec.get("settled") and spawn_id in self._admission_leases:
                    self._admission_settled.add(spawn_id)
                    self._maybe_release_admission(spawn_id)

            task.add_done_callback(completed)
        await asyncio.shield(task)

    async def _settle(self, rec: dict, child: Optional[asyncio.Future]) -> None:
        """Once per spawn, after it ends: close the transcript, reclaim or keep its
        worktree (the kept branch is the reviewable artefact; its changed files are the
        stale-file reminder), and close the durable row — delivered in line unless the
        spawn ran in the background."""
        if rec.get("settled") or rec["status"] not in TERMINAL_STATUSES:
            return
        rec["settled"] = True
        transcript = self._transcripts.pop(rec["id"], None)
        tree = rec.get("worktree")
        if tree and tree.get("path") and self._worktree_provider is not None:
            if child is not None and not child.done() or rec.get("threads_running"):
                rec["worktree"] = {**tree, "kept": True, "reason": "child_still_running"}
            else:
                from . import worktrees

                try:
                    report = await asyncio.to_thread(worktrees.finish_child_tree, worktrees.ChildTree(
                        repo=tree["repo"], path=tree["path"], branch=tree["branch"], base=tree["base"]))
                except Exception as exc:  # noqa: BLE001
                    report = {**tree, "kept": True, "reason": f"finish_failed: {type(exc).__name__}"}
                rec["worktree"] = {**tree, **report}
            if isinstance(rec.get("result"), dict):
                rec["result"] = {**rec["result"], "worktree": _worktree_view(rec["worktree"])}
        result = rec.get("result")
        if transcript is not None:
            preview = result.get("output") if isinstance(result, dict) else None
            transcript.append("end", status=rec["status"],
                              error=result.get("error") if isinstance(result, dict) else None,
                              output=preview if isinstance(preview, str) else None)
        await self._store_call("delegation_finish", rec["delegation_id"], rec["status"], result,
                               worktree=rec.get("worktree"), dump_path=rec.get("dump"),
                               delivered_to=None if rec.get("background") else "inline")

    def _read_only_tools(self, allowed: Optional[frozenset]) -> frozenset:
        """The tools of *allowed* that declared themselves read-only; none without a probe."""
        if not allowed or self._read_only_probe is None:
            return frozenset()
        kept = set()
        for name in allowed:
            try:
                read_only = self._read_only_probe(name) is True
            except Exception:  # noqa: BLE001 — an unreadable tool is not read-only
                read_only = False
            if read_only:
                kept.add(name)
        return frozenset(kept)

    def recover(self, *, now: Optional[float] = None) -> list[dict]:
        """At start and on every autonomy tick (blocking): close as ``lost`` each durable
        row another boot left running whose heartbeat has gone stale — its process died;
        it is reported once, never re-run. A live second process keeps heartbeating and is
        left alone."""
        if not self._pruned:
            self._pruned = True
            self._prune_state()
        store = self._get_store()
        if store is None:
            return []
        try:
            kwargs = {"now": now} if now is not None else {}
            lost = store.delegation_recover(self.boot_id, **kwargs)
        except Exception:  # noqa: BLE001
            logger.warning("sub-agent recovery failed", exc_info=True)
            return []
        if lost:
            logger.warning("%d sub-agent(s) stopped with their process; reported as lost", len(lost))
        return lost

    def _prune_state(self, keep: int = STATE_FILES_KEPT) -> None:
        """Keep the newest *keep* transcripts and dumps; older files are removed (they
        are observability, not the record: the durable row and the audit log are)."""
        for folder in ("transcripts", "dumps"):
            directory = self.state_dir() / folder
            try:
                files = sorted((p for p in directory.iterdir() if p.is_file() and not p.is_symlink()),
                               key=lambda p: p.stat().st_mtime, reverse=True)
            except OSError:
                continue
            for stale in files[keep:]:
                with contextlib.suppress(OSError):
                    stale.unlink()

    async def claim_completions(self, consumer: str, *, parent_session: Optional[str] = None,
                                limit: int = 20) -> list[dict]:
        """Finished results nobody has received yet, each handed to exactly one consumer."""
        rows = await self._store_call("delegation_claim", consumer, parent_session=parent_session, limit=limit)
        return list(rows or [])

    async def spawn_background(self, task: str, **kwargs: Any) -> dict:
        """Start a child and answer as soon as it is admitted (H401 background fan-out):
        ``{"ok": True, "id", "delegation_id", "status": "running", "background": True}``,
        or the refusal. Its result is delivered once, later, by :meth:`claim_completions`."""
        loop = asyncio.get_running_loop()
        admitted: asyncio.Future = loop.create_future()
        runner = asyncio.ensure_future(self.spawn(task, background=True, _admitted=admitted, **kwargs))
        self._background.add(runner)
        runner.add_done_callback(self._background.discard)
        await asyncio.wait({admitted, runner}, return_when=asyncio.FIRST_COMPLETED)
        if admitted.done():
            rec = admitted.result()
            return {"ok": True, "id": rec["id"], "delegation_id": rec["delegation_id"],
                    "session_id": rec["session_id"], "status": "running", "background": True}
        admitted.cancel()
        out = runner.result()
        return {**out, "background": True} if isinstance(out, dict) else out

    @staticmethod
    def _mark_unchecked(rec: dict) -> None:
        """Fail a record whose outcome could not be recorded. Assigned, not transitioned:
        whatever state the failed step left, the record ends ``failed`` with a fixed
        message that carries none of the child's text."""
        rec["status"] = "failed"
        rec["result"] = dict(ANSWER_UNCHECKED)

    def _close_on_error(self, rec: dict, child: Optional[asyncio.Future],
                        before: Optional[dict]) -> None:
        """The fail-closed end of a spawn whose normal path raised (B1): the record is
        terminal and the slot released once — now, or when the child's task ends."""
        if rec.get("finished_at") is not None:
            return
        if rec.get("status") not in TERMINAL_STATUSES:
            self._mark_unchecked(rec)
        if child is not None and not child.done():
            child.cancel()
            child.add_done_callback(lambda _fut: self._finish(rec, before, None))
            return
        self._finish(rec, before, None)

    def _record_outcome(self, rec: dict, child: asyncio.Future, output_schema: Optional[dict],
                        answer_schema: Optional[dict]) -> Any:
        """Write a finished child's status and result onto its record; returns what the
        runner answered (None when it did not)."""
        spawn_id = rec["id"]
        try:
            result = child.result()
        except asyncio.CancelledError:
            if rec["status"] != "stopping":           # cancelled by something other than stop()
                rec["stop_reason"] = rec.get("stop_reason") or "cancelled"
                self._set_status(rec, "stopping")
            self._set_status(rec, "stopped")
            rec["result"] = {"error": "stopped", "reason": rec.get("stop_reason")}
            return None
        except SubAgentProviderError as exc:
            logger.warning("sub-agent %s: its model call failed: %s", spawn_id, exc.detail[:200])
            self._set_status(rec, "failed")
            rec["result"] = {"error": "provider_failed", "detail": exc.detail[:DETAIL_MAX]}
            failures = [d for d in (_failure_dict(f) for f in exc.failures) if d is not None]
            if failures:
                rec["result"]["failures"] = failures
            return None
        except Exception:
            logger.warning("sub-agent run failed", exc_info=True)
            self._set_status(rec, "failed")
            rec["result"] = {"error": "run failed"}
            return None
        violations = (validate_output(result, output_schema)
                      if output_schema is not None else [])
        blank = (isinstance(result, dict) and isinstance(result.get("output"), str)
                 and not result["output"].strip())
        structured: Any = None
        if not blank and not violations and answer_schema is not None:
            answer = result.get("output") if isinstance(result, dict) else result
            found, structured = extract_json_candidate(answer)
            if found:
                violations = validate_output(structured, answer_schema)[:10]
            elif isinstance(answer, str) and len(answer) > ANSWER_JSON_MAX_CHARS:
                violations = [f"$: the answer is longer than {ANSWER_JSON_MAX_CHARS} characters"]
            else:
                violations = [f"$: the answer is not JSON (or nests deeper than "
                              f"{ANSWER_JSON_MAX_DEPTH} levels)"]
        if blank:
            # A turn that answered nothing is not a child that finished its task.
            self._set_status(rec, "failed")
            rec["result"] = {"error": "provider_failed", "detail": "empty output"}
        elif violations:
            self._set_status(rec, "failed")
            rec["result"] = {"error": "output_schema_violation",
                             "violations": violations, "output": result}
        else:
            self._set_status(rec, "done")
            rec["result"] = ({**result, "structured": structured}
                             if answer_schema is not None and isinstance(result, dict) else result)
        return result

    async def _end_cancelled(self, rec: dict, child: asyncio.Future, chan: SteerChannel,
                             before: Optional[dict], *, final: str, result: dict) -> bool:
        """Cancel a child and close its record as *final* once its task has ended.

        The child is waited for (``UNWIND_GRACE_SECONDS``). If it has ended, the record
        is closed and the slot released now. If it has not — its code is holding the
        cancellation off — the record stays ``stopping`` and keeps its slot, and a
        done-callback closes it when the task does end: the count of taken slots never
        drops below the tasks that are still running. Returns whether it has ended."""
        if rec["status"] == "running":
            self._set_status(rec, "stopping")
        chan.stop_requested = True
        rec["result"] = dict(result)

        def close(_fut: Any = None) -> None:
            if not child.cancelled():
                with contextlib.suppress(BaseException):
                    child.exception()         # retrieved, so the loop does not log it
            if rec["status"] == "stopping":
                self._set_status(rec, final)
            self._finish(rec, before, None)

        recancelled = False
        if not child.done():
            child.cancel()
            try:
                await asyncio.wait({child}, timeout=UNWIND_GRACE_SECONDS)
            except asyncio.CancelledError:
                recancelled = True
        if child.done():
            close()
        else:
            rec["result"]["unwound"] = False

            def later(fut: Any) -> None:
                rec["result"].pop("unwound", None)
                close(fut)
                try:
                    task = asyncio.ensure_future(self._persist(rec))
                    settle = asyncio.ensure_future(self._settle_owned(rec, child))
                except RuntimeError:
                    return
                for pending in (task, settle):
                    self._settling.add(pending)
                    pending.add_done_callback(self._settling.discard)

            child.add_done_callback(later)
        if recancelled:
            raise asyncio.CancelledError
        return child.done()

    async def _run(self, task: str, session_id: str, agent: str, chan: SteerChannel,
                   selection: Optional[dict] = None, ov: Any = None,
                   spawn_id: Optional[str] = None, tools: Optional[frozenset] = None,
                   delegation: Optional[dict] = None, isolation: Optional[dict] = None):
        from .llm.job_selection import selection_scope
        from .llm.request_context import request_overrides_scope

        kwargs: dict[str, Any] = {}
        if self._runner_takes_blocked:
            kwargs["blocked"] = self.blocked
        if self._runner_takes_steer:
            kwargs["steer"] = chan
        if self._runner_takes_selection:
            kwargs["selection"] = selection
        if self._runner_takes_tools:
            kwargs["tools"] = tools
        pins = {k: selection[k] for k in ("model", "provider") if selection and selection.get(k)}
        # This coroutine is the child's own task: what it binds here is the child's.
        marker = _CURRENT_SPAWN.set(spawn_id)
        delegated = _CURRENT_DELEGATION.set(dict(delegation) if delegation else None)
        sink = bind_sync_thread_sink(self._threads.setdefault(spawn_id, set()) if spawn_id else None)
        isolation = isolation or {}
        trace = _TRACE.set(isolation.get("transcript"))
        try:
            with contextlib.ExitStack() as stack:
                lease = self._admission_leases.get(spawn_id) if spawn_id else None
                if lease is not None:
                    stack.enter_context(lease.bind())
                # G18 (H402): a child with its own worktree has its file tools confined
                # to it (and the tree is held in use, so no reclaim takes it meanwhile).
                if isolation.get("tree"):
                    from .worktrees import tree_scope

                    stack.enter_context(tree_scope(isolation["tree"]))
                # G18 (H404): the reviewer runs under the kernel's read-only floor.
                if isolation.get("read_only"):
                    from .kernel.plan_mode import read_only_floor

                    stack.enter_context(read_only_floor("review", allowed=isolation.get("tools") or frozenset()))
                stack.enter_context(selection_scope(pins))
                stack.enter_context(request_overrides_scope(ov))
                return await self._runner(task, session_id, agent, **kwargs)
        finally:
            _TRACE.reset(trace)
            reset_sync_thread_sink(sink)
            _CURRENT_DELEGATION.reset(delegated)
            _CURRENT_SPAWN.reset(marker)

    # ── batch (H681) ─────────────────────────────────────────────
    async def spawn_batch(self, tasks: Any, parent: str = "", *,
                          tools: Optional[Iterable[str]] = None, model_authored: bool = False,
                          queue: bool = True, background: bool = False) -> dict:
        """Run up to ``BATCH_MAX`` children, at most as many at once as there are free
        slots, and report each. Every item is validated before any runs: its shape, its
        schemas and its selection. A batch a model wrote (``model_authored``: the
        ``delegate_task`` tool, the only way a model reaches this) also passes the batch
        quality gate (:func:`goal_problem`, H400): a placeholder goal, an unexpanded
        template marker or, with two or more tasks, a goal under ten characters refuses
        the whole batch as ``invalid_goal``, and each child is given the focused brief
        (:func:`build_child_prompt`). The owner's own batch (the HTTP route) is the
        owner's words and is not judged. A batch
        is refused whole while new spawns are stopped. With ``queue=False`` a batch that
        does not fit the free slots right now is refused (``concurrency_cap``) instead
        of waiting for them. The result's ``notice`` is one ``subagent_model_rejected``
        when every child failed because the provider does not know the model
        ``autonomy.subagent_model`` chose."""
        if not isinstance(tasks, list):
            return {"ok": False, "reason": "invalid_batch", "detail": "tasks must be a list"}
        if not tasks:
            return {"ok": False, "reason": "empty_batch"}
        if len(tasks) > BATCH_MAX:
            return {"ok": False, "reason": "batch_too_large", "max": BATCH_MAX}
        for i, item in enumerate(tasks):
            if (not isinstance(item, dict) or not isinstance(item.get("task"), str)
                    or not item["task"].strip() or set(item) - _BATCH_ITEM_KEYS):
                return {"ok": False, "reason": "invalid_batch", "index": i,
                        "detail": f"each task is an object with a non-empty 'task' and only {sorted(_BATCH_ITEM_KEYS)}"}
            if item.get("output_schema") is not None and not isinstance(item["output_schema"], dict):
                return {"ok": False, "reason": "invalid_output_schema", "index": i}
            if isinstance(item.get("output_schema"), dict):
                problem = schema_problem(item["output_schema"])
                if problem:
                    return {"ok": False, "reason": "invalid_output_schema", "index": i,
                            "detail": problem[:DETAIL_MAX]}
            if item.get("answer_schema") is not None:
                problem = schema_problem(item["answer_schema"])
                if problem:
                    return {"ok": False, "reason": "invalid_output_schema", "index": i,
                            "detail": problem[:DETAIL_MAX]}
            context = item.get("context")
            if context is not None and (not isinstance(context, str) or len(context) > CONTEXT_MAX_CHARS):
                return {"ok": False, "reason": "invalid_context", "index": i,
                        "detail": f"context is text of at most {CONTEXT_MAX_CHARS} characters"}
            problem = goal_problem(item["task"], batch_size=len(tasks)) if model_authored else None
            if problem:
                return {"ok": False, "reason": "invalid_goal", "index": i,
                        "detail": f"task {i}: {problem}"[:DETAIL_MAX]}
            try:
                self._resolve_selection(item.get("model"), item.get("provider"), item.get("overrides"))
            except ValueError as exc:
                return {"ok": False, "reason": "invalid_selection", "index": i, "detail": str(exc)[:DETAIL_MAX]}
        state = await self.gate_state()
        refusal = self._halt_refusal(state)
        if refusal is not None:
            return refusal
        free = self.max_concurrent - self._active
        if (background or not queue) and len(tasks) > free:
            return {"ok": False, "reason": "concurrency_cap", "active": self._active,
                    "cap": self.max_concurrent, "requested": len(tasks)}
        gate = asyncio.Semaphore(max(1, free))

        async def one(item: dict) -> dict:
            async with gate:
                return await self.spawn(item["task"], agent=str(item.get("agent") or ""), parent=parent,
                                        output_schema=item.get("output_schema"), model=item.get("model"),
                                        provider=item.get("provider"), overrides=item.get("overrides"),
                                        tools=tools, context=item.get("context"),
                                        answer_schema=item.get("answer_schema"), focused=model_authored)

        if background:
            # G18 (H401): every child is admitted now and runs on; nobody waits. Each
            # result is delivered exactly once, later (claim_completions).
            started = []
            for item in tasks:
                started.append(await self.spawn_background(
                    item["task"], agent=str(item.get("agent") or ""), parent=parent,
                    output_schema=item.get("output_schema"), model=item.get("model"),
                    provider=item.get("provider"), overrides=item.get("overrides"), tools=tools,
                    context=item.get("context"), answer_schema=item.get("answer_schema"),
                    focused=model_authored))
            dispatched = sum(1 for c in started if c.get("status") == "running")
            return {"ok": dispatched == len(started), "background": True, "children": started,
                    "summary": {"total": len(started), "dispatched": dispatched,
                                "failed": sum(1 for c in started if c.get("status") in ("failed", "stopped")),
                                "refused": sum(1 for c in started if "status" not in c)}}
        children = list(await asyncio.gather(*(one(item) for item in tasks)))
        summary = {"total": len(children),
                   "done": sum(1 for c in children if c.get("status") == "done"),
                   "failed": sum(1 for c in children if c.get("status") in ("failed", "stopped", "stopping")),
                   "refused": sum(1 for c in children if "status" not in c)}
        return {"ok": summary["done"] == summary["total"], "children": children, "summary": summary,
                "notice": self._batch_notice(children)}

    def _batch_notice(self, children: list) -> Optional[dict]:
        if not children or any(c.get("status") != "failed" for c in children):
            return None
        defaults = self._read_defaults()
        model = defaults.get("model") if isinstance(defaults.get("model"), str) else ""
        if not model:
            return None
        for child in children:
            selection = child.get("selection") or {}
            if selection.get("source") != "setting" or selection.get("model") != model:
                return None
            if not _rejected_for(child.get("result"), model):
                return None
        provider = defaults.get("provider") or next(
            (f.get("provider") for c in children for f in (c["result"].get("failures") or [])
             if isinstance(f, dict) and f.get("provider")), None)
        fallback_model = None
        if self._fallback_probe is not None:
            try:
                candidate = self._fallback_probe(model)
            except Exception:
                logger.debug("no fallback model could be named", exc_info=True)
                candidate = None
            if isinstance(candidate, str) and candidate and candidate != model:
                fallback_model = candidate
        who = provider or "the provider"
        message = (f"Every sub-agent in this batch failed: {who} does not know the model '{model}' "
                   f"that {SUBAGENT_MODEL_SETTING} chooses. ")
        message += (f"Clear the setting to run them on '{fallback_model}', or choose another model."
                    if fallback_model else "There is no other model to fall back to: choose another model.")
        return {"kind": "subagent_model_rejected", "model": model, "provider": provider,
                "setting": SUBAGENT_MODEL_SETTING, "fallback": fallback_model is not None,
                "fallback_model": fallback_model, "children": len(children), "message": message}

    def _safe_probe(self) -> dict:
        try:
            return self._cost_probe() or {}
        except Exception:
            logger.debug("cost probe failed", exc_info=True)
            return {}

    def _finish(self, rec: dict, before: Optional[dict], result: Any) -> None:
        """Close the record, close the channel, attribute cost — exactly once — and
        release the slot when the child's last tool thread has returned."""
        if rec.get("finished_at") is not None:
            return
        rec["finished_at"] = time.time()
        self._channels.pop(rec["id"], None)
        self._tasks.pop(rec["id"], None)
        try:
            cost = _usage_from_result(result)
            if cost is None and before is not None:
                after = _cost_totals(self._safe_probe())
                if after is not None:
                    cost = {"input_tokens": max(0, after["input_tokens"] - before["input_tokens"]),
                            "output_tokens": max(0, after["output_tokens"] - before["output_tokens"]),
                            "cost_usd": round(max(0.0, after["cost_usd"] - before["cost_usd"]), 6),
                            "source": "tracker_delta"}
        except Exception:  # noqa: BLE001 — accounting never strands a slot
            logger.warning("sub-agent %s: its cost could not be attributed", rec["id"], exc_info=True)
            cost = None
        rec["cost"] = cost
        self._release_after_threads(rec)

    def _release(self, spawn_id: str) -> None:
        """Give back one slot — once per spawn, whoever calls."""
        if spawn_id in self._held:
            self._held.discard(spawn_id)
            self._active -= 1
            if spawn_id in self._admission_leases:
                self._admission_slots_done.add(spawn_id)
                self._maybe_release_admission(spawn_id)

    def _release_after_threads(self, rec: dict) -> None:
        """Release *rec*'s slot now, or — when a sync tool handler the child started is
        still running on its worker thread (ToolRPC cannot interrupt one) — when the last
        such thread returns. Until then the slot stays taken and the record says how
        many threads are still running, so real concurrency never exceeds the cap."""
        spawn_id = rec["id"]
        threads = self._threads.pop(spawn_id, set())
        live = {future for future in threads if not future.done()}
        if not live:
            self._release(spawn_id)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._release(spawn_id)
            return
        rec["threads_running"] = len(live)

        def check() -> None:
            remaining = sum(1 for future in live if not future.done())
            if remaining:
                rec["threads_running"] = remaining
                return
            rec.pop("threads_running", None)
            self._release(spawn_id)

        for future in live:
            # A concurrent future calls back on its worker thread: hop to the loop.
            future.add_done_callback(lambda _f: loop.call_soon_threadsafe(check))

    # ── persistence (observability only) ─────────────────────────
    def spawn_log_path(self) -> Path:
        if self._spawn_log is None:
            from .paths import data_path
            self._spawn_log = data_path("subagents", "spawns.jsonl")
        return self._spawn_log

    def _append_log(self, line: str) -> None:
        path = self.spawn_log_path()
        with self._log_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    async def _persist(self, rec: dict) -> None:
        if not self.persist:
            return
        try:
            line = json.dumps(_compact_for_log(rec), ensure_ascii=False, sort_keys=True,
                              default=str)
            await asyncio.to_thread(self._append_log, line)
        except Exception:
            logger.debug("spawn record not persisted", exc_info=True)

    # ── steer / stop ─────────────────────────────────────────────
    def steer(self, spawn_id: str, message: str, origin: str = "user") -> dict:
        """Deliver a steer message to a running child. Returns `delivered=False`
        (still ok) when the runner never opted into the `steer` kwarg — the
        message is recorded on the spawn either way."""
        rec = self._spawns.get(spawn_id)
        if rec is None:
            return {"ok": False, "reason": "unknown_spawn", "id": spawn_id}
        if rec["status"] != "running":
            return {"ok": False, "reason": "not_running", "id": spawn_id,
                    "status": rec["status"]}
        try:
            msg = SteerMessage(spawn_id=spawn_id, text=message, origin=origin)
        except ValueError as e:
            return {"ok": False, "reason": "invalid_steer", "detail": str(e), "id": spawn_id}
        rec["steers"].append(msg.to_dict())
        transcript = self._transcripts.get(spawn_id)
        if transcript is not None:
            transcript.append("steer", origin=origin, text=msg.text)
        chan = self._channels.get(spawn_id)
        delivered = chan is not None and self._runner_takes_steer
        if chan is not None:
            chan.push(msg)
        return {"ok": True, "id": spawn_id, "delivered": delivered,
                "origin": origin, "pending": chan.pending if chan else 0}

    def stop(self, spawn_id: str, reason: str = "operator") -> dict:
        """Cancel a running child. The status is `stopping` until the child task
        unwinds (its awaiting `spawn()` records `stopped`)."""
        rec = self._spawns.get(spawn_id)
        if rec is None:
            return {"ok": False, "reason": "unknown_spawn", "id": spawn_id}
        if rec["status"] != "running":
            return {"ok": False, "reason": "not_running", "id": spawn_id,
                    "status": rec["status"]}
        rec["stop_reason"] = str(reason or "operator")[:80]
        self._set_status(rec, "stopping")
        chan = self._channels.get(spawn_id)
        if chan is not None:
            chan.stop_requested = True
        fut = self._tasks.get(spawn_id)
        if fut is not None and not fut.done():
            fut.cancel()
        return {"ok": True, "id": spawn_id, "status": rec["status"]}

    # ── approval seam ────────────────────────────────────────────
    async def decide(self, spawn_id: str, task_id: int, action: str,
                     origin: str = "agent") -> dict:
        """The ONLY route from a spawn context to a queue decision. Agent-origin
        requests (inter-agent steers, a child's own output) are refused before the
        injected `decision_hook` is consulted: a sub-agent can never approve, and a
        message from another agent can never stand in for the human. `user`-origin
        requests are forwarded to the hook, which in prod is the worker's
        `apply_decision` — the same human-decision path the inbox uses."""
        if origin != "user":
            return {"ok": False, "reason": "agent_origin_cannot_approve",
                    "origin": origin, "task_id": task_id, "action": action}
        if self._decision_hook is None:
            return {"ok": False, "reason": "decision_hook_unavailable",
                    "task_id": task_id, "action": action}
        if spawn_id not in self._spawns:
            return {"ok": False, "reason": "unknown_spawn", "id": spawn_id}
        try:
            out = await self._decision_hook(task_id, action,
                                            decided_by=f"user:via-subagent:{spawn_id}")
        except Exception as e:
            logger.warning("decision hook failed", exc_info=True)
            return {"ok": False, "reason": "decision_failed", "detail": str(e)[:200]}
        return {"ok": True, "task_id": task_id, "action": action,
                "status": getattr(out, "status", None)}

    # ── read model ───────────────────────────────────────────────
    def list(self) -> "list[dict]":
        """Every spawn without its result, plus a failed child's reason (H681)."""
        out = []
        for r in self._spawns.values():
            row = {k: v for k, v in r.items() if k != "result"}
            result = r.get("result")
            if r.get("status") == "failed" and isinstance(result, dict):
                row["failure"] = {"error": str(result.get("error") or "failed"),
                                  "detail": str(result.get("detail") or "")[:200]}
            out.append(row)
        return out

    def get(self, spawn_id: str) -> Optional[dict]:
        r = self._spawns.get(spawn_id)
        return dict(r) if r else None

    def stats(self) -> dict:
        by_status: dict[str, int] = {}
        cost_usd = 0.0
        for r in self._spawns.values():
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            if isinstance(r.get("cost"), dict):
                cost_usd += float(r["cost"].get("cost_usd", 0.0) or 0.0)
        out = {"total": len(self._spawns), "active": self._active,
               "cap": self.max_concurrent, "max_depth": self.max_depth,
               "blocked": sorted(self.blocked), "by_status": by_status,
               "steerable": self._runner_takes_steer, "persist": self.persist,
               "cost_usd": round(cost_usd, 6), "timeout_seconds": self.child_timeout()}
        if self.budget is not None:
            out["budget"] = self.budget.status()
        turn = current_tool_turn()
        out["turn_cap"] = {"cap": self.turn_cap(),
                           "spawned_this_turn": self._turn_spawns.get(turn, 0) if turn else 0}
        return out


__all__ = [
    "BATCH_MAX", "BLOCKED_CAPABILITY_TOOLS", "CHILD_TIMEOUT_MAX_SECONDS", "CHILD_TIMEOUT_MIN_SECONDS",
    "DEFAULT_CHILD_TIMEOUT_SECONDS", "DELEGATE_BLOCKED_CAPABILITIES", "HALT_REASONS", "NullRunner",
    "STEER_ORIGINS", "SPAWN_LOG_ENV", "SPAWN_TRANSITIONS", "SUBAGENT_MODEL_SETTING",
    "SUBAGENT_PROVIDER_SETTING", "SteerChannel", "SteerMessage", "SubAgentManager",
    "SubAgentProviderError", "blocked_tool_names", "build_child_prompt", "child_tool_allowlist",
    "current_delegation", "current_spawn_id", "delegation_label", "extract_json_candidate", "goal_problem", "read_pause", "schema_problem",
    "DEFAULT_STALL_SECONDS", "Transcript", "read_transcript", "trace_tool_event",
    "validate_output", "write_pause",
]
