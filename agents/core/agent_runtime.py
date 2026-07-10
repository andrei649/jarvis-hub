"""Bounded model-directed execution over the governed ToolRPC allowlist."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable
from typing import Any

from .environments.output_limits import truncate_text
from .iteration_budget import IterationBudget
from .llm.tool_protocol import ToolCall, ToolSpec
from .tool_rpc import ToolRPCServer

logger = logging.getLogger("jarvis.agent_runtime")

ToolEventSink = Callable[[dict[str, Any]], Any]

_APPROVAL_REPLY = "I paused the tool loop because this action requires approval."
_DEADLINE_REPLY = "I stopped the tool loop because it reached the safety deadline."
_DEFAULT_ITERATIONS = 8
_MAX_ITERATIONS = 32
_EVENT_IDENTITY_BYTES = 256


class AgentToolRuntime:
    """Run provider tool turns exclusively through a governed ToolRPC server."""

    def __init__(
        self,
        server: ToolRPCServer,
        *,
        enabled: Callable[[], bool] = lambda: False,
        max_iterations: Callable[[], int] = lambda: 8,
        max_tool_calls_per_turn: int = 8,
        max_result_bytes: int = 50_000,
        tool_timeout_seconds: float = 30.0,
        max_wall_seconds: float = 120.0,
    ) -> None:
        self._server = server
        self._enabled = enabled
        self._max_iterations = max_iterations
        self._max_tool_calls_per_turn = _safe_int(max_tool_calls_per_turn, default=0, minimum=0)
        self._max_result_bytes = _safe_int(max_result_bytes, default=50_000, minimum=8)
        self._tool_timeout_seconds = _safe_float(tool_timeout_seconds, default=30.0)
        self._max_wall_seconds = _safe_float(max_wall_seconds, default=120.0)

    def can_run(self, backend: Any) -> bool:
        """Fail closed unless the setting, backend, and allowlist are all live."""
        try:
            return bool(
                self._enabled()
                and getattr(backend, "supports_tools", False)
                and self._server.tools()
            )
        except Exception:
            logger.warning("agent tool runtime capability check failed closed")
            return False

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
        """Run one bounded tool-enabled model turn to a final answer."""
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
        try:
            return await asyncio.wait_for(loop, timeout=self._max_wall_seconds)
        except TimeoutError:
            return _DEADLINE_REPLY

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
        metadata = self._server.tools()
        tools = [
            ToolSpec(
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema=tool.get("input_schema", {"type": "object", "properties": {}}),
            )
            for tool in metadata
        ]
        gated_tools = {tool["name"]: bool(tool.get("gated")) for tool in metadata}
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        limit = self._iteration_limit()
        budget = IterationBudget(limit)

        while budget.consume():
            turn = await backend.generate_tool_turn(
                model=model,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if not turn.tool_calls:
                return turn.content

            messages.append(turn.as_assistant_message())
            observations = await self._execute_turn_calls(
                turn.tool_calls,
                agent_id=agent_id,
                gated_tools=gated_tools,
                event_sink=event_sink,
            )
            for call, (_result, content) in zip(turn.tool_calls, observations, strict=True):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": content,
                    }
                )
            if any(result.get("reason") == "approval_required" for result, _ in observations):
                return _APPROVAL_REPLY

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

    async def _execute_turn_calls(
        self,
        calls: tuple[ToolCall, ...],
        *,
        agent_id: str,
        gated_tools: dict[str, bool],
        event_sink: ToolEventSink | None,
    ) -> list[tuple[dict[str, Any], str]]:
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
                approval_lock=approval_lock,
                approval_state=approval_state,
                agent_id=agent_id,
                event_sink=event_sink,
            )
            for index, call in enumerate(calls)
        ]
        return list(await asyncio.gather(*pending))

    async def _execute_one(
        self,
        call: ToolCall,
        *,
        overflow: bool,
        gated: bool,
        approval_lock: asyncio.Lock,
        approval_state: dict[str, bool],
        agent_id: str,
        event_sink: ToolEventSink | None,
    ) -> tuple[dict[str, Any], str]:
        if overflow:
            return await self._local_failure(
                call,
                agent_id=agent_id,
                reason="too_many_tool_calls",
                event_sink=event_sink,
            )
        if call.parse_error or not isinstance(call.arguments, dict):
            return await self._local_failure(
                call,
                agent_id=agent_id,
                reason="bad_tool_arguments",
                event_sink=event_sink,
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
            raw_result = await asyncio.wait_for(
                self._server.handle(
                    {"tool": call.name, "args": call.arguments},
                    actor=agent_id,
                ),
                timeout=self._tool_timeout_seconds,
            )
        except TimeoutError:
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
    ) -> tuple[dict[str, Any], str]:
        result = {"ok": False, "reason": reason, "tool": call.name}
        prepared, content = self._prepare_result(result, call.name)
        await self._emit_result(event_sink, call, agent_id, prepared)
        return prepared, content

    def _prepare_result(self, raw_result: Any, tool_name: str) -> tuple[dict[str, Any], str]:
        result = raw_result if isinstance(raw_result, dict) else _non_json(tool_name)
        try:
            encoded = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            result = _non_json(tool_name)
            encoded = json.dumps(result, ensure_ascii=False)
        bounded = truncate_text(
            encoded,
            max_content_bytes=self._max_result_bytes,
            label="TOOL RESULT",
        )
        return result, bounded.text

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

    @staticmethod
    async def _emit(event_sink: ToolEventSink | None, event: dict[str, Any]) -> None:
        if event_sink is None:
            return
        try:
            outcome = event_sink(dict(event))
            if inspect.isawaitable(outcome):
                await outcome
        except Exception:
            logger.warning("agent tool event sink failed; continuing")

    def _iteration_limit(self) -> int:
        try:
            configured = int(self._max_iterations())
        except (TypeError, ValueError, OverflowError):
            configured = _DEFAULT_ITERATIONS
        return max(1, min(_MAX_ITERATIONS, configured))


def _non_json(tool_name: str) -> dict[str, Any]:
    return {"ok": False, "reason": "non_json_result", "tool": tool_name}


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
    return parsed if parsed > 0 else default


def _bounded_identity(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    raw = value.encode("utf-8")
    if len(raw) <= _EVENT_IDENTITY_BYTES:
        return value
    return raw[:_EVENT_IDENTITY_BYTES].decode("utf-8", errors="ignore") + "..."


__all__ = ["AgentToolRuntime", "ToolEventSink"]
