"""Bounded model-directed execution over the governed ToolRPC allowlist.

What the model reads is data (Hermes absorption 5a). The tool loop is an ingress: a web
page, a search hit or a recalled memory that a tool returns lands in the transcript the
model answers from, so it is the same category of content as an untrusted recall — and
until now it crossed into the transcript unmarked, and an action built from it reached
the kernel with a clean turn origin. Two mechanisms already existed for exactly this:
the untrusted fence that ``security.quarantine`` puts around external text, and the
recall taint that ``security.recall_taint`` raises on the turn's action origin so the
kernel escalates a grant to approval. Both are applied here, at the one seam every result
crosses (the observation loop in ``run``), for a tool that declared its output untrusted,
for any result the injection scanner flags, and for a result that carries its own
``tainted`` verdict. The mark is raised from the loop body itself, never from inside a
ToolRPC handler: a handler runs in a child task, and a ContextVar written there never
reaches the turn. The loop is itself a child task of ``run`` (the wall-clock deadline), so
``run`` gives it an explicit context copy and, once it returns or times out, carries an
untrusted origin found there into its own context — the context that awaits ``run``. It
reaches no further: a caller that awaits ``run`` from its own child task (a gather of
agents) must read ``current_action_origin`` there, after ``run`` returns, and raise its
own turn's origin itself. The fence follows the tool, not the planning mode: the registry
projection carries the ``untrusted_output`` declaration through, and a fenced result that
is later compacted is folded on its payload and fenced again.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import logging
import math
import re
from collections.abc import Callable, Coroutine, Mapping
from contextlib import suppress
from functools import partial
from typing import Any

from .action_origin import current_action_origin
from .context_compressor import window_for
from .iteration_budget import IterationBudget
from .llm.tokenizer import estimate_messages
from .llm.tool_protocol import MAX_PARSED_TOOL_CALLS, ToolCall, ToolSpec
from .security.quarantine import (
    fence_tool_result,
    injection_flag_names,
    split_fenced_tool_result,
)
from .security.recall_taint import mark_turn_recall_tainted
from .security.taint import TAINTED_RECALL_ORIGIN, is_untrusted_source
from .tool_rpc import ToolRPCServer

logger = logging.getLogger("jarvis.agent_runtime")

ToolEventSink = Callable[[dict[str, Any]], Any]
GapSink = Callable[[dict[str, str]], Any]
# (agent_id, tool metadata rows) -> (rows to offer, a decision object with surface /
# principal / withheld for the event feed). See agents/core/tool_profiles.py.
ToolProfileHook = Callable[[str, list[dict[str, Any]]], tuple[Any, Any]]

_APPROVAL_REPLY = "I paused the tool loop because this action requires approval."
_DEADLINE_REPLY = "I stopped the tool loop because it reached the safety deadline."
_CONTEXT_REPLY = "I stopped the tool loop because its context exceeded the safety budget."
_REPEAT_REPLY = "I stopped the tool loop because it kept repeating the same tool call."
# Hermes absorption 3a — a model that calls the same tool with the same arguments again and
# again is looping, not working; the iteration limit would end it eventually, but only after
# burning every turn and telling the model nothing. The third identical call is refused with
# the reason (the model can change course); a fourth ends the turn with a named reply.
_DEFAULT_REPEAT_LIMIT = 3
_REPEATED_NOTICE = (
    "This exact call (same tool, same arguments) was already made {repeats} times this turn "
    "and was not run again: repeating it will not produce a different answer. Change the "
    "arguments, use another tool, or answer with what you have."
)
# The same tool failing again and again with different arguments is the other loop: the
# model keeps guessing at a path or a query that will not resolve. Five consecutive
# failures of one tool end the turn with a named reply; a success resets the streak.
_FAILURE_REPLY = "I stopped the tool loop because the same tool kept failing."
_DEFAULT_FAILURE_LIMIT = 5
# Hermes absorption 4f — two more guardrails from the same family. A per-tool cap ends a
# turn that leans on one tool without end (0 = off, set from llm.tool_loop_per_tool_cap);
# and a successful result byte-identical to one already in the transcript is replaced by a
# reference stub, so the model is told "same as call N" instead of paying for the payload
# twice. Error results are never stubbed: each fresh failure is seen verbatim.
_DEFAULT_DUPLICATE_STUB_BYTES = 512
_CAP_NOTICE = (
    "This tool was already called {calls} times this turn, which is its limit ({limit}); "
    "use another tool or answer with what you have."
)
_DUPLICATE_NOTICE = (
    "This result is byte-identical to the result of call {call_id} earlier this turn and "
    "was not repeated; refer to that result."
)
# Hermes absorption 3b — the profile (agent × surface × principal) decides what is offered
# before the model sees a tool list; a turn the profile leaves with nothing never enters the
# loop (``can_run`` says no and the agent answers on the plain path).
_NO_TOOLS_REPLY = "I can't use tools on this surface."
_EVENT_WITHHELD_NAMES = 32
# Hermes absorption 0.3 — in-turn compaction. The loop appends an assistant message and one
# tool result per call for up to 32 iterations and never measured the growing list; at the
# end the work was lost to a context overflow nobody had counted. The budget defaults to a
# fraction of the model's window minus the output reserve, older tool results are folded
# into bounded envelopes first, and a transcript that still does not fit stops the loop with
# a named reason instead of a provider error.
_MIN_CONTEXT_BUDGET = 2_048
_CONTEXT_WINDOW_FRACTION = 0.75
_COMPACTED_NOTICE = "TOOL RESULT COMPACTED"
_TRUNCATED_NOTICE = "TOOL RESULT TRUNCATED"
_DEFAULT_ITERATIONS = 8
_MAX_ITERATIONS = 32
_MAX_TOOL_CALLS_PER_TURN = MAX_PARSED_TOOL_CALLS - 1
_EVENT_IDENTITY_BYTES = 256
_EVENT_TIMEOUT_SECONDS = 0.1
_MAX_JSON_DEPTH = 64
_NO_CAPABILITY_REPLY = (
    "I can't use tools for this request because no live registered capability matches."
)
_CAPABILITY_TERM_RE = re.compile(
    r"\b(?:tool|capabilit(?:y|ies)|skill|plugin|integration|automation|"
    r"unealt[ăa]|capabilitat(?:e|i)|integrar[ei]|automatizar[ei])\b",
    re.IGNORECASE,
)
_CAPABILITY_ACTION_RE = re.compile(
    r"\b(?:use|need|create|build|run|install|add|missing|cannot|can't|"
    r"folose(?:ște|ste)|am nevoie|creeaz[ăa]|ruleaz[ăa]|instaleaz[ăa]|lipsește|lipseste)\b",
    re.IGNORECASE,
)


class _OwnedTimeout(Exception):
    """An owned coroutine exceeded its response-time deadline."""

    def __init__(self, task: asyncio.Task[Any]) -> None:
        super().__init__("owned coroutine exceeded its response-time deadline")
        self.task = task


class AgentToolRuntime:
    """Run provider tool turns exclusively through a governed ToolRPC server."""

    def __init__(
        self,
        server: ToolRPCServer,
        *,
        enabled: Callable[[], bool] = lambda: False,
        registry_enabled: Callable[[], bool] = lambda: False,
        capability_snapshot: Callable[[], dict] = lambda: {"capabilities": []},
        max_iterations: Callable[[], int] = lambda: 8,
        max_tool_calls_per_turn: int = 8,
        max_result_bytes: int = 50_000,
        tool_timeout_seconds: float = 30.0,
        max_wall_seconds: float = 120.0,
        gap_callback: GapSink | None = None,
        context_budget_tokens: Callable[[], int] = lambda: 0,
        compaction_keep_recent: int = 2,
        compacted_result_bytes: int = 512,
        repeat_limit: int = _DEFAULT_REPEAT_LIMIT,
        failure_limit: int = _DEFAULT_FAILURE_LIMIT,
        tool_profile: ToolProfileHook | None = None,
        per_tool_limit: int | Callable[[], int] = 0,
        duplicate_stub_bytes: int = _DEFAULT_DUPLICATE_STUB_BYTES,
    ) -> None:
        self._server = server
        self._tool_profile = tool_profile
        self._repeat_limit = _safe_int(repeat_limit, default=_DEFAULT_REPEAT_LIMIT, minimum=0)
        self._failure_limit = _safe_int(failure_limit, default=_DEFAULT_FAILURE_LIMIT, minimum=0)
        self._per_tool_limit = per_tool_limit
        self._duplicate_stub_bytes = _safe_int(
            duplicate_stub_bytes, default=_DEFAULT_DUPLICATE_STUB_BYTES, minimum=64,
        )
        self._context_budget_tokens = context_budget_tokens
        self._compaction_keep_recent = _safe_int(compaction_keep_recent, default=2, minimum=0)
        self._compacted_result_bytes = _safe_int(compacted_result_bytes, default=512, minimum=64)
        self._enabled = enabled
        self._registry_enabled = registry_enabled
        self._capability_snapshot = capability_snapshot
        self._max_iterations = max_iterations
        self._max_tool_calls_per_turn = min(
            _MAX_TOOL_CALLS_PER_TURN,
            _safe_int(max_tool_calls_per_turn, default=0, minimum=0),
        )
        self._max_result_bytes = _safe_int(max_result_bytes, default=50_000, minimum=8)
        self._tool_timeout_seconds = _safe_float(tool_timeout_seconds, default=30.0)
        self._max_wall_seconds = _safe_float(max_wall_seconds, default=120.0)
        self._gap_callback = gap_callback
        self._stragglers: set[asyncio.Task[Any]] = set()
        self._blocked_event_sinks: dict[int, asyncio.Task[Any]] = {}
        self._event_lock = asyncio.Lock()

    def can_run(self, backend: Any, agent_id: str | None = None) -> bool:
        """Fail closed unless the setting, backend, and allowlist are all live — and, when
        the caller names the agent, unless this turn's profile offers it at least one tool."""
        try:
            self._prune_stragglers()
            live = bool(
                not self._stragglers
                and self._enabled()
                and getattr(backend, "supports_tools", False)
                and self._server.tools()
            )
            if not live:
                return False
            if agent_id is None or self._tool_profile is None:
                return True
            offered, _decision = self._profiled(agent_id, self._server.tools())
            return bool(offered)
        except Exception:
            logger.warning("agent tool runtime capability check failed closed")
            return False

    def _profiled(
        self, agent_id: str, metadata: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], Any]:
        """Apply the turn's tool profile; a resolver failure offers nothing."""
        if self._tool_profile is None:
            return metadata, None
        try:
            offered, decision = self._tool_profile(agent_id, metadata)
        except Exception:
            logger.warning("tool profile resolution failed closed", exc_info=True)
            return [], None
        return [dict(tool) for tool in offered], decision

    async def run(
        self,
        *,
        agent_id: str,
        backend: Any,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        event_sink: ToolEventSink | None = None,
    ) -> str:
        """Run one bounded tool-enabled model turn to a final answer.

        Deadlines bound response latency, not in-process coroutine lifetime. A coroutine
        that suppresses cancellation is detached and blocks ``can_run`` until it exits,
        preventing repeated turns from accumulating unbounded orphan work.
        """
        loop = self._run_loop(
            agent_id=agent_id,
            backend=backend,
            model=model,
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            event_sink=event_sink,
        )
        # The loop runs in a child task under the deadline, in this explicit copy of the
        # turn's context; whatever recall taint the loop raised there is carried back into
        # the caller's context below, on a normal return and on a deadline alike
        # (Hermes absorption 5a).
        turn_context = contextvars.copy_context()
        try:
            return await self._await_owned(
                loop, timeout=self._max_wall_seconds, context=turn_context,
            )
        except _OwnedTimeout:
            return _DEADLINE_REPLY
        finally:
            self._carry_turn_taint(turn_context)

    @staticmethod
    def _carry_turn_taint(turn_context: contextvars.Context) -> None:
        """Raise the awaiting context's action origin when the loop's carries an untrusted one.

        Escalate-only through ``mark_turn_recall_tainted``: an inbound origin keeps its own
        label. The mark lands in the context that awaits ``run`` and no further up — a caller
        that itself runs ``run`` in a child task reads the origin there once ``run`` returns. Reading the loop's context cannot collide with a straggler still running after
        a deadline — the event loop is single-threaded, so no task is mid-step here — but a
        read that fails for any reason marks anyway: a false escalation queues an action for
        approval, a missed one would let it auto-execute (Hermes absorption 5a).
        """
        try:
            loop_origin = turn_context.run(current_action_origin)
        except Exception as exc:
            logger.warning("tool loop origin read failed (%s); marking the turn", type(exc).__name__)
            loop_origin = TAINTED_RECALL_ORIGIN
        if is_untrusted_source(loop_origin):
            mark_turn_recall_tainted()

    async def _run_loop(
        self,
        *,
        agent_id: str,
        backend: Any,
        model: str,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
        event_sink: ToolEventSink | None,
    ) -> str:
        registry_mode = self._registry_mode()
        metadata = self._server.tools()
        if registry_mode:
            metadata = self._registry_metadata(metadata)
            if not metadata:
                if _is_explicit_capability_goal(prompt):
                    await self._emit_gap(
                        {
                            "agent_id": _bounded_identity(agent_id),
                            "goal": prompt[:4096],
                            "reason": "no_registered_capability",
                        }
                    )
                return _NO_CAPABILITY_REPLY
        metadata, decision = self._profiled(agent_id, metadata)
        if decision is not None:
            await self._emit(
                event_sink,
                {
                    "event": "tool_profile",
                    "agent_id": _bounded_identity(agent_id),
                    "surface": _bounded_identity(getattr(decision, "surface", "")),
                    "principal": _bounded_identity(getattr(decision, "principal", "")),
                    "offered": len(metadata),
                    "withheld": [
                        _bounded_identity(name)
                        for name in tuple(getattr(decision, "withheld", ()))[:_EVENT_WITHHELD_NAMES]
                    ],
                },
            )
        if not metadata:
            return _NO_TOOLS_REPLY
        tools = [
            ToolSpec(
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema=tool.get("input_schema", {"type": "object", "properties": {}}),
            )
            for tool in metadata
        ]
        gated_tools = {tool["name"]: bool(tool.get("gated")) for tool in metadata}
        untrusted_tools = {
            tool["name"] for tool in metadata if tool.get("untrusted_output") is True
        }
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        limit = self._iteration_limit()
        budget = IterationBudget(limit)
        compacted: set[int] = set()
        seen_calls: dict[tuple[str, str], int] = {}
        failure_streaks: dict[str, int] = {}
        tool_counts: dict[str, int] = {}
        seen_results: dict[str, str] = {}

        while budget.consume():
            if len(messages) > 2 and not await self._compact_context(
                messages,
                compacted,
                model=model,
                max_tokens=max_tokens,
                agent_id=agent_id,
                event_sink=event_sink,
            ):
                return _CONTEXT_REPLY
            turn = await backend.generate_tool_turn(
                model=model,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if not turn.tool_calls:
                return turn.content

            # A provider response is untrusted input. Keep at most the executable
            # fan-out plus one representative overflow call so both scheduling
            # and the next-turn context stay O(configured cap), not O(provider N).
            bounded_calls = turn.tool_calls[: self._max_tool_calls_per_turn + 1]
            repeated, looping = self._note_repeats(bounded_calls, seen_calls)
            if looping is not None:
                await self._emit(
                    event_sink,
                    {
                        **self._event(looping, agent_id, "tool_loop_repeated", "repeated_call"),
                        "repeats": seen_calls[_call_key(looping)],
                        "limit": self._repeat_limit,
                    },
                )
                return _REPEAT_REPLY
            capped = self._note_tool_counts(bounded_calls, tool_counts)
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": [call.as_openai() for call in bounded_calls],
                }
            )
            observations = await self._execute_turn_calls(
                bounded_calls,
                agent_id=agent_id,
                gated_tools=gated_tools,
                event_sink=event_sink,
                repeated=repeated,
                capped=capped,
            )
            for call, (result, raw) in zip(bounded_calls, observations, strict=True):
                # Fenced and marked from the loop's own context (never a child task), so
                # the recall taint lands on the turn. The stub is keyed on the RAW bytes so
                # identical payloads still dedupe; a "same as call N" stub is Nerva's own
                # words and is never fenced. The mark and the event still fire for the
                # repeat — idempotent and escalate-only.
                content = await self._fence_result(
                    call,
                    result,
                    raw,
                    untrusted=call.name in untrusted_tools,
                    agent_id=agent_id,
                    event_sink=event_sink,
                )
                deduped = await self._dedupe_result(
                    call, result, raw, seen_results, agent_id=agent_id, event_sink=event_sink,
                )
                if deduped != raw:
                    content = deduped
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": content,
                    }
                )
            if any(result.get("reason") == "approval_required" for result, _ in observations):
                return _APPROVAL_REPLY
            failing = self._note_failures(bounded_calls, observations, failure_streaks)
            if failing is not None:
                call, result = failing
                await self._emit(
                    event_sink,
                    {
                        **self._event(
                            call, agent_id, "tool_loop_failing", _failure_reason(result),
                        ),
                        "failures": failure_streaks[call.name],
                        "limit": self._failure_limit,
                    },
                )
                return _FAILURE_REPLY

        await self._emit(
            event_sink,
            {
                "event": "tool_loop_exhausted",
                "agent_id": _bounded_identity(agent_id),
                "status": "safety_limit",
                "limit": limit,
            },
        )
        return (
            f"I stopped the tool loop after {limit} model turns because it reached "
            "the safety limit."
        )

    def _context_budget(self, model: str, max_tokens: int) -> int:
        """Tokens the transcript may occupy before the next model turn."""
        try:
            configured = _safe_int(self._context_budget_tokens(), default=0, minimum=0)
        except Exception:
            logger.warning("tool loop context budget setting failed closed to auto")
            configured = 0
        if configured > 0:
            return max(_MIN_CONTEXT_BUDGET, configured)
        reserve = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else 0
        return max(_MIN_CONTEXT_BUDGET, int(window_for(model) * _CONTEXT_WINDOW_FRACTION) - reserve)

    async def _compact_context(
        self,
        messages: list[dict[str, Any]],
        compacted: set[int],
        *,
        model: str,
        max_tokens: int,
        agent_id: str,
        event_sink: ToolEventSink | None,
    ) -> bool:
        """Fold older tool results into bounded envelopes until the transcript fits.

        Messages are never dropped or reordered — every ``tool`` result keeps answering the
        assistant call that made it, which is what every provider validates — only their
        content shrinks. The most recent ``compaction_keep_recent`` iterations are folded last.
        Returns False when the transcript still exceeds the budget with everything folded.
        """
        budget = self._context_budget(model, max_tokens)
        before = estimate_messages(messages)
        if before <= budget:
            return True
        assistant_positions = [
            index for index, message in enumerate(messages) if message.get("role") == "assistant"
        ]
        keep = self._compaction_keep_recent
        protected_from = (
            assistant_positions[-keep]
            if keep and len(assistant_positions) >= keep
            else len(messages)
        )
        candidates = [
            index
            for index, message in enumerate(messages)
            if message.get("role") == "tool" and index not in compacted
        ]
        used = before
        folded = 0
        for positions in (
            [index for index in candidates if index < protected_from],
            [index for index in candidates if index >= protected_from],
        ):
            for index in positions:
                if used <= budget:
                    break
                compacted.add(index)
                message = messages[index]
                content = message.get("content")
                encoded = content if isinstance(content, str) else json.dumps(content, default=str)
                if len(encoded.encode("utf-8")) <= self._compacted_result_bytes:
                    continue
                messages[index] = {**message, "content": self._compacted_content(encoded)}
                folded += 1
                used = estimate_messages(messages)
        exhausted = used > budget
        await self._emit(
            event_sink,
            {
                "event": "tool_context_compacted",
                "agent_id": _bounded_identity(agent_id),
                "status": "exhausted" if exhausted else "compacted",
                "compacted": folded,
                "tokens_before": before,
                "tokens_after": used,
                "budget": budget,
            },
        )
        return not exhausted

    def _compacted_content(self, encoded: str) -> str:
        """Fold one tool message into a bounded envelope; a fenced message stays fenced.

        A fenced result is not JSON as a whole: folding it whole would report the envelope
        as ``ok: false`` with no tool name and leave the fence as escaped text inside the
        preview. So the payload is folded on its own — ``ok`` and ``tool`` come from the real
        envelope — and the folded envelope is fenced again under the same source; the fence
        is a fixed overhead on top of the byte bound (Hermes absorption 5a).
        """
        fenced = split_fenced_tool_result(encoded)
        if fenced is not None:
            source, payload = fenced
            folded, _ = fence_tool_result(self._compacted_content(payload), source=source)
            return folded
        try:
            parsed = json.loads(encoded)
        except ValueError:
            parsed = None
        result = parsed if isinstance(parsed, dict) else {}
        tool = result.get("tool")
        return _bounded_result_envelope(
            encoded,
            tool_name=tool if isinstance(tool, str) else "",
            ok=result.get("ok") is True,
            reason=result.get("reason"),
            max_bytes=self._compacted_result_bytes,
            notice=_COMPACTED_NOTICE,
        )

    def _note_repeats(
        self,
        calls: tuple[ToolCall, ...],
        seen: dict[tuple[str, str], int],
    ) -> tuple[dict[str, int], ToolCall | None]:
        """Count identical (tool, arguments) calls across the turn.

        Returns the calls that just reached the limit (refused with a notice, keyed by
        call id) and the first call past it, which ends the loop. ``repeat_limit=0``
        disables the detector.
        """
        limit = self._repeat_limit
        repeated: dict[str, int] = {}
        if limit <= 0:
            return repeated, None
        for call in calls:
            key = _call_key(call)
            count = seen.get(key, 0) + 1
            seen[key] = count
            if count > limit:
                return repeated, call
            if count == limit:
                repeated[call.id] = count
        return repeated, None

    def _per_tool_cap(self) -> int:
        limit = self._per_tool_limit
        if callable(limit):
            try:
                limit = limit()
            except Exception:
                logger.warning("per-tool cap setting failed closed to off")
                return 0
        return _safe_int(limit, default=0, minimum=0)

    def _note_tool_counts(
        self, calls: tuple[ToolCall, ...], counts: dict[str, int],
    ) -> dict[str, int]:
        """Count calls per tool across the turn; the ids past the cap are refused."""
        limit = self._per_tool_cap()
        capped: dict[str, int] = {}
        for call in calls:
            count = counts.get(call.name, 0) + 1
            counts[call.name] = count
            if limit > 0 and count > limit:
                capped[call.id] = count
        return capped

    async def _fence_result(
        self,
        call: ToolCall,
        result: Mapping[str, Any],
        content: str,
        *,
        untrusted: bool,
        agent_id: str,
        event_sink: ToolEventSink | None,
    ) -> str:
        """Fence an untrusted result as DATA and raise the turn's recall taint.

        Three reasons, any one of which is enough (Hermes absorption 5a): the tool declared
        its output untrusted and the result is a success (a not-ok envelope — a local
        failure, a server refusal — and a handler's own ``ok: false`` refusal are Nerva's
        own words about a fetch that did not happen, and never fenced for this reason);
        the injection scanner flagged the encoded content; or the handler's own dict says
        ``tainted`` (a tool that computed a per-hit verdict in its child task, which cannot
        reach the turn's ContextVar from there). With no reason the content is returned
        byte-identical. The event carries reasons and flag names, never the content.
        """
        reasons: list[str] = []
        if untrusted and result.get("ok") is True and not _is_failed_result(result):
            reasons.append("untrusted_tool")
        fenced, flags = fence_tool_result(content, source=call.name)
        if flags:
            reasons.append("injection_flags")
        if _declares_taint(result):
            reasons.append("declared_taint")
        if not reasons:
            return content
        mark_turn_recall_tainted()
        await self._emit(
            event_sink,
            {
                **self._event(call, agent_id, "tool_result_untrusted", "fenced"),
                "source": _bounded_identity(call.name),
                "reasons": reasons,
                "injection_flags": injection_flag_names(flags),
                "suspicious": bool(flags),
            },
        )
        return fenced

    async def _dedupe_result(
        self,
        call: ToolCall,
        result: Mapping[str, Any],
        content: str,
        seen: dict[str, str],
        *,
        agent_id: str,
        event_sink: ToolEventSink | None,
    ) -> str:
        """A successful result already in the transcript becomes a reference stub."""
        if _is_failed_result(result) or len(content.encode("utf-8")) < self._duplicate_stub_bytes:
            return content
        prior = seen.get(content)
        if prior is None:
            seen[content] = call.id
            return content
        await self._emit(
            event_sink,
            {
                **self._event(call, agent_id, "tool_result_deduplicated", "same_as"),
                "same_as": _bounded_identity(prior),
            },
        )
        return json.dumps(
            {
                "ok": True,
                "tool": call.name,
                "same_as": prior,
                "notice": _DUPLICATE_NOTICE.format(call_id=prior),
            },
            ensure_ascii=False,
        )

    def _note_failures(
        self,
        calls: tuple[ToolCall, ...],
        observations: list[tuple[dict[str, Any], str]],
        streaks: dict[str, int],
    ) -> tuple[ToolCall, dict[str, Any]] | None:
        """Track consecutive failures per tool across the turn; the call that reaches the
        limit ends the loop. ``failure_limit=0`` disables the breaker."""
        limit = self._failure_limit
        for call, (result, _content) in zip(calls, observations, strict=True):
            if not _is_failed_result(result):
                streaks[call.name] = 0
                continue
            streaks[call.name] = streaks.get(call.name, 0) + 1
            if limit > 0 and streaks[call.name] >= limit:
                return call, result
        return None

    async def _execute_turn_calls(
        self,
        calls: tuple[ToolCall, ...],
        *,
        agent_id: str,
        gated_tools: dict[str, bool],
        event_sink: ToolEventSink | None,
        repeated: Mapping[str, int] | None = None,
        capped: Mapping[str, int] | None = None,
    ) -> list[tuple[dict[str, Any], str]]:
        repeated = repeated or {}
        capped = capped or {}
        for call in calls:
            await self._emit(
                event_sink,
                self._event(call, agent_id, "tool_requested", "requested"),
            )

        approval_lock = asyncio.Lock()
        approval_state = {"required": False}
        pending = [
            self._execute_one(
                call,
                overflow=index >= self._max_tool_calls_per_turn,
                gated=gated_tools.get(call.name, False),
                offered=call.name in gated_tools,
                approval_lock=approval_lock,
                approval_state=approval_state,
                agent_id=agent_id,
                event_sink=event_sink,
                repeats=repeated.get(call.id, 0),
                capped_at=capped.get(call.id, 0),
            )
            for index, call in enumerate(calls)
        ]
        return list(await asyncio.gather(*pending))

    def _registry_mode(self) -> bool:
        try:
            return bool(self._registry_enabled())
        except Exception:
            logger.warning("registry planning flag failed closed")
            return True

    async def _emit_gap(self, payload: dict[str, str]) -> None:
        if self._gap_callback is None:
            return
        try:
            if inspect.iscoroutinefunction(self._gap_callback):
                result = self._gap_callback(payload)
            else:
                result = await asyncio.to_thread(self._gap_callback, payload)
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=_EVENT_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("capability gap callback timed out")
        except Exception:
            logger.warning("capability gap callback failed", exc_info=True)

    def _registry_metadata(self, tools: list[dict]) -> list[dict]:
        """Project ToolRPC metadata through the live capability registry."""
        try:
            snapshot = self._capability_snapshot()
            rows = snapshot.get("capabilities") if isinstance(snapshot, dict) else None
            if not isinstance(rows, list):
                return []
            records: dict[str, dict] = {}
            for row in rows:
                if not isinstance(row, dict):
                    return []
                capability_id = row.get("id")
                if not isinstance(capability_id, str) or not capability_id or capability_id in records:
                    return []
                records[capability_id] = row

            projected = []
            for tool in tools:
                capability_id = tool.get("capability_id") if isinstance(tool, dict) else None
                record = records.get(capability_id) if isinstance(capability_id, str) else None
                if record is None or record.get("state") not in {"wired", "verified", "ga"}:
                    continue
                description = record.get("description")
                inputs = record.get("inputs")
                risk = record.get("risk")
                confidence = record.get("confidence")
                if (
                    not isinstance(description, str)
                    or not isinstance(inputs, dict)
                    or inputs.get("type") != "object"
                    or not isinstance(risk, str)
                    or isinstance(confidence, bool)
                    or not isinstance(confidence, (int, float))
                    or not math.isfinite(float(confidence))
                    or not 0.0 <= float(confidence) <= 1.0
                ):
                    continue
                context = (
                    f" [capability={capability_id} risk={risk} "
                    f"readiness={record['state']} confidence={float(confidence):.3f}]"
                )
                projected.append(
                    {
                        "name": tool.get("name", ""),
                        "gated": bool(tool.get("gated")),
                        "description": (description + context)[:1024],
                        "input_schema": inputs,
                        "capability_id": capability_id,
                        # The fence follows the tool, not the planning mode: a declared-
                        # untrusted tool stays declared under the registry projection;
                        # an undeclared row is unchanged (Hermes absorption 5a).
                        **({"untrusted_output": True} if tool.get("untrusted_output") is True else {}),
                    }
                )
            return projected
        except Exception:
            logger.warning("capability registry projection failed closed")
            return []

    async def _execute_one(
        self,
        call: ToolCall,
        *,
        overflow: bool,
        gated: bool,
        offered: bool,
        approval_lock: asyncio.Lock,
        approval_state: dict[str, bool],
        agent_id: str,
        event_sink: ToolEventSink | None,
        repeats: int = 0,
        capped_at: int = 0,
    ) -> tuple[dict[str, Any], str]:
        if overflow:
            return await self._local_failure(
                call,
                agent_id=agent_id,
                reason="too_many_tool_calls",
                event_sink=event_sink,
            )
        if not offered:
            return await self._local_failure(
                call,
                agent_id=agent_id,
                reason="tool_not_allowed",
                event_sink=event_sink,
            )
        if call.parse_error or not isinstance(call.arguments, dict):
            return await self._local_failure(
                call,
                agent_id=agent_id,
                reason="bad_tool_arguments",
                event_sink=event_sink,
            )
        if repeats:
            return await self._local_failure(
                call,
                agent_id=agent_id,
                reason="repeated_call",
                event_sink=event_sink,
                extra={"repeats": repeats, "notice": _REPEATED_NOTICE.format(repeats=repeats)},
            )
        if capped_at:
            limit = self._per_tool_cap()
            return await self._local_failure(
                call,
                agent_id=agent_id,
                reason="tool_cap_reached",
                event_sink=event_sink,
                extra={
                    "calls": capped_at,
                    "limit": limit,
                    "notice": _CAP_NOTICE.format(calls=capped_at - 1, limit=limit),
                },
            )

        if gated:
            async with approval_lock:
                if approval_state["required"]:
                    return await self._local_failure(
                        call,
                        agent_id=agent_id,
                        reason="approval_required",
                        event_sink=event_sink,
                    )
                observation = await self._execute_rpc(
                    call,
                    agent_id=agent_id,
                    event_sink=event_sink,
                )
                if observation[0].get("reason") == "approval_required":
                    approval_state["required"] = True
                return observation

        return await self._execute_rpc(
            call,
            agent_id=agent_id,
            event_sink=event_sink,
        )

    async def _execute_rpc(
        self,
        call: ToolCall,
        *,
        agent_id: str,
        event_sink: ToolEventSink | None,
    ) -> tuple[dict[str, Any], str]:
        await self._emit(
            event_sink,
            self._event(call, agent_id, "tool_started", "running"),
        )
        try:
            raw_result = await self._await_owned(
                self._server.handle(
                    {"tool": call.name, "args": call.arguments},
                    actor=agent_id,
                ),
                timeout=self._tool_timeout_seconds,
            )
        except _OwnedTimeout:
            raw_result = {
                "ok": False,
                "reason": "tool_timeout",
                "tool": call.name,
            }
        except Exception:
            logger.warning("ToolRPC call failed without exposing exception details")
            raw_result = {
                "ok": False,
                "reason": "tool_error",
                "tool": call.name,
            }

        result, content = self._prepare_result(raw_result, call.name)
        await self._emit_result(event_sink, call, agent_id, result)
        return result, content

    async def _local_failure(
        self,
        call: ToolCall,
        *,
        agent_id: str,
        reason: str,
        event_sink: ToolEventSink | None,
        extra: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        result = {"ok": False, "reason": reason, "tool": call.name, **(extra or {})}
        prepared, content = self._prepare_result(result, call.name)
        await self._emit_result(event_sink, call, agent_id, prepared)
        return prepared, content

    def _prepare_result(self, raw_result: Any, tool_name: str) -> tuple[dict[str, Any], str]:
        result = raw_result if _is_strict_json(raw_result) else _non_json(tool_name)
        try:
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            result = _non_json(tool_name)
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) <= self._max_result_bytes:
            return result, encoded
        return result, _bounded_result_envelope(
            encoded,
            tool_name=tool_name,
            ok=isinstance(result, dict) and result.get("ok") is True,
            reason=result.get("reason") if isinstance(result, dict) else None,
            max_bytes=self._max_result_bytes,
        )

    async def _emit_result(
        self,
        event_sink: ToolEventSink | None,
        call: ToolCall,
        agent_id: str,
        result: dict[str, Any],
    ) -> None:
        ok = result.get("ok") is True
        reason = result.get("reason")
        status = "ok" if ok else _bounded_identity(reason if isinstance(reason, str) else "failed")
        await self._emit(
            event_sink,
            self._event(
                call,
                agent_id,
                "tool_result" if ok else "tool_failed",
                status,
            ),
        )

    @staticmethod
    def _event(call: ToolCall, agent_id: str, event: str, status: str) -> dict[str, Any]:
        return {
            "event": event,
            "agent_id": _bounded_identity(agent_id),
            "tool": _bounded_identity(call.name),
            "call_id": _bounded_identity(call.id),
            "status": _bounded_identity(status),
        }

    async def _emit(self, event_sink: ToolEventSink | None, event: dict[str, Any]) -> None:
        if event_sink is None:
            return
        sink_id = id(event_sink)
        async with self._event_lock:
            blocked = self._blocked_event_sinks.get(sink_id)
            if blocked is not None and not blocked.done():
                return
            if blocked is not None:
                self._blocked_event_sinks.pop(sink_id, None)
            try:
                await self._await_owned(
                    self._invoke_event_sink(event_sink, event),
                    timeout=_EVENT_TIMEOUT_SECONDS,
                )
            except _OwnedTimeout as exc:
                self._blocked_event_sinks[sink_id] = exc.task
                exc.task.add_done_callback(partial(self._clear_blocked_sink, sink_id))
                logger.warning("agent tool event sink timed out; continuing")
            except Exception:
                logger.warning("agent tool event sink failed; continuing")

    @staticmethod
    async def _invoke_event_sink(event_sink: ToolEventSink, event: dict[str, Any]) -> None:
        thread_task = asyncio.create_task(asyncio.to_thread(event_sink, dict(event)))
        cancelled = False
        try:
            outcome = await asyncio.shield(thread_task)
        except asyncio.CancelledError:
            cancelled = True
            outcome = await asyncio.shield(thread_task)
        if inspect.isawaitable(outcome):
            await outcome
        if cancelled:
            raise asyncio.CancelledError

    def _clear_blocked_sink(self, sink_id: int, task: asyncio.Task[Any]) -> None:
        if self._blocked_event_sinks.get(sink_id) is task:
            self._blocked_event_sinks.pop(sink_id, None)

    def _iteration_limit(self) -> int:
        try:
            configured = int(self._max_iterations())
        except (TypeError, ValueError, OverflowError):
            configured = _DEFAULT_ITERATIONS
        return max(1, min(_MAX_ITERATIONS, configured))

    async def _await_owned(
        self,
        coroutine: Coroutine[Any, Any, Any],
        *,
        timeout: float,
        context: contextvars.Context | None = None,
    ) -> Any:
        task = asyncio.create_task(coroutine, context=context)
        try:
            done, _ = await asyncio.wait({task}, timeout=timeout)
        except BaseException:
            self._detach(task)
            raise
        if task in done:
            return task.result()
        self._detach(task)
        raise _OwnedTimeout(task)

    def _detach(self, task: asyncio.Task[Any]) -> None:
        if task.done():
            self._drain_straggler(task)
            return
        self._stragglers.add(task)
        task.add_done_callback(self._drain_straggler)
        task.cancel()

    def _prune_stragglers(self) -> None:
        for task in tuple(self._stragglers):
            if task.done():
                self._drain_straggler(task)

    def _drain_straggler(self, task: asyncio.Task[Any]) -> None:
        self._stragglers.discard(task)
        with suppress(BaseException):
            task.exception()


def _is_failed_result(result: Mapping[str, Any]) -> bool:
    """A refusal by the server (``ok`` not true) or by the handler itself — an inline tool's
    own ``{"ok": false, "reason": ...}`` arrives wrapped under ``result``."""
    if result.get("ok") is not True:
        return True
    inner = result.get("result")
    return isinstance(inner, dict) and inner.get("ok") is False


def _declares_taint(result: Any) -> bool:
    """A handler's own dict, wrapped under ``result``, says its content is tainted."""
    inner = result.get("result") if isinstance(result, Mapping) else None
    return isinstance(inner, Mapping) and inner.get("tainted") is True


def _failure_reason(result: Mapping[str, Any]) -> str:
    """The named reason of a failed result — the server's, or the handler's own."""
    reason = result.get("reason")
    if not isinstance(reason, str):
        inner = result.get("result")
        reason = inner.get("reason") if isinstance(inner, dict) else None
    return reason if isinstance(reason, str) and reason else "failed"


def _call_key(call: ToolCall) -> tuple[str, str]:
    """Identity of a call for the repeat detector: the tool plus its arguments in
    canonical JSON (key order does not make a different call)."""
    if isinstance(call.arguments, dict):
        try:
            encoded = json.dumps(
                call.arguments, sort_keys=True, default=str, separators=(",", ":"),
            )
        except (TypeError, ValueError):
            encoded = str(call.raw_arguments)
    else:
        encoded = str(call.raw_arguments)
    return (str(call.name), encoded)


def _non_json(tool_name: str) -> dict[str, Any]:
    return {"ok": False, "reason": "non_json_result", "tool": _bounded_identity(tool_name)}


def _bounded_result_envelope(
    encoded: str,
    *,
    tool_name: str,
    ok: bool,
    reason: Any,
    max_bytes: int,
    notice: str = _TRUNCATED_NOTICE,
) -> str:
    """Return a complete JSON truncation envelope within ``max_bytes``."""
    raw = encoded.encode("utf-8")
    envelope: dict[str, Any] = {
        "ok": ok,
        "tool": _bounded_identity(tool_name),
        "truncated": True,
        "notice": notice,
        "original_bytes": len(raw),
    }
    if not ok and isinstance(reason, str):
        envelope["reason"] = _bounded_identity(reason)

    def render(kept_bytes: int | None = None) -> str:
        payload = dict(envelope)
        if kept_bytes is not None:
            head_bytes = kept_bytes // 2
            tail_bytes = kept_bytes - head_bytes
            payload["preview"] = {
                "head": raw[:head_bytes].decode("utf-8", errors="ignore"),
                "tail": raw[-tail_bytes:].decode("utf-8", errors="ignore") if tail_bytes else "",
            }
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )

    base = render()
    if len(base.encode("utf-8")) > max_bytes:
        for fallback in (
            '{"truncated":true,"notice":"TOOL RESULT TRUNCATED"}',
            '{"truncated":true}',
            "null",
        ):
            if len(fallback.encode("utf-8")) <= max_bytes:
                return fallback
        return "null"[:max_bytes]

    best = base
    low = 0
    high = min(len(raw), max_bytes)
    while low <= high:
        kept = (low + high) // 2
        candidate = render(kept)
        if len(candidate.encode("utf-8")) <= max_bytes:
            best = candidate
            low = kept + 1
        else:
            high = kept - 1
    return best


def _is_strict_json(
    value: Any,
    *,
    _depth: int = 0,
    _active: set[int] | None = None,
) -> bool:
    """Accept only finite, recursively JSON-native values without cycles."""
    if _depth > _MAX_JSON_DEPTH:
        return False
    value_type = type(value)
    if value is None or value_type in {bool, int}:
        return True
    if value_type is str:
        return _is_valid_unicode(value)
    if value_type is float:
        return math.isfinite(value)
    if value_type not in {list, dict}:
        return False

    active = _active if _active is not None else set()
    identity = id(value)
    if identity in active:
        return False
    active.add(identity)
    try:
        if value_type is list:
            return all(_is_strict_json(item, _depth=_depth + 1, _active=active) for item in value)
        return all(
            type(key) is str
            and _is_valid_unicode(key)
            and _is_strict_json(item, _depth=_depth + 1, _active=active)
            for key, item in value.items()
        )
    finally:
        active.remove(identity)


def _safe_int(value: Any, *, default: int, minimum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, parsed)


def _safe_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0 else default


def _bounded_identity(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= _EVENT_IDENTITY_BYTES:
        return raw.decode("utf-8")
    return raw[:_EVENT_IDENTITY_BYTES].decode("utf-8", errors="ignore") + "..."


def _is_valid_unicode(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_explicit_capability_goal(prompt: Any) -> bool:
    """Conservative trigger: ordinary unanswered chat never becomes acquisition work."""
    if not isinstance(prompt, str) or not prompt:
        return False
    candidate = prompt
    marker = "User said:"
    if marker in candidate:
        candidate = candidate.rsplit(marker, 1)[-1].split("\nRespond as", 1)[0]
    candidate = candidate[:4096]
    return bool(_CAPABILITY_TERM_RE.search(candidate) and _CAPABILITY_ACTION_RE.search(candidate))


__all__ = ["AgentToolRuntime", "GapSink", "ToolEventSink", "ToolProfileHook"]
