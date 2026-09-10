"""
anthropic.py — Anthropic Claude API backend with streaming support.
Uses Anthropic Messages API directly via httpx (no SDK dependency).
"""

import json
from typing import Any, Callable

import httpx

from .auth_rotation import is_rotatable_status
from .base import LLMBackend, _emit, cloud_cap
from .egress import llm_async_client
from .model_config import DEFAULT_CLAUDE_MODEL
from .reasoning_effort import apply_anthropic, parse_overrides
from .tool_dialects import (
    ANTHROPIC_FINISH_REASONS,
    anthropic_messages,
    anthropic_text,
    anthropic_tool_calls,
    anthropic_tools,
    anthropic_usage,
    cache_marked_system,
    cache_marked_tools,
    normalize_finish_reason,
)
from .tool_protocol import ToolSpec, ToolTurn, parse_openai_tool_calls

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeBackend(LLMBackend):
    # Tool calls travel as tool_use / tool_result blocks; the translation lives in
    # tool_dialects (Hermes absorption, wave 0.1).
    supports_tools = True

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_CLAUDE_MODEL,
        auth_pool=None,
        reasoning_effort: str = "",
        effort_overrides=None,
    ):
        self.api_key = api_key
        self.model = model
        # H364 — one ladder rung for this install, clamped per model at send time.
        # Empty means "ask for nothing", which is what every install did before.
        # The override map is the escape hatch for a family whose contract moves
        # under us: it can widen or, by naming an empty list, silence a model.
        self.reasoning_effort = str(reasoning_effort or "")
        self.effort_overrides = parse_overrides(effort_overrides)
        # H12.20 — optional multi-key auth pool. When set, the active key is drawn
        # from the pool and a rotatable error (401/403/429) fails over to the next
        # healthy key. None → single-key behavior, unchanged.
        self.auth_pool = auth_pool
        self.client = llm_async_client("anthropic", timeout=120.0)

    def _active_key(self) -> str:
        if self.auth_pool is not None:
            return self.auth_pool.current_key() or self.api_key
        return self.api_key

    def _headers(self) -> dict:
        return {
            "x-api-key": self._active_key(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _fit_to_wire(self, payload: dict, model: str):
        """Add what this model accepts and remove what it rejects (H364).

        Runs on every request, not only the ones that ask to think harder: the
        sampling parameters return a 400 on the 4.7 generation and later whether
        or not an effort was requested, so `temperature` has to come off there
        even on a default install that never touches the ladder.
        """
        return apply_anthropic(
            payload,
            model or self.model,
            self.reasoning_effort,
            overrides=self.effort_overrides,
        )

    def _build_messages(self, prompt: str, system: str = "") -> list[dict]:
        return [{"role": "user", "content": prompt}]

    async def _post_messages(self, payload: dict) -> tuple[dict | None, str]:
        """POST /messages once per healthy auth profile, failing over on rotatable errors (H12.20).

        Returns ``(data, "")`` on success or ``(None, error_text)``; never raises.
        """
        attempts = self.auth_pool.size if self.auth_pool else 1
        last_err = ""
        for _ in range(max(1, attempts)):
            key = self._active_key()
            try:
                resp = await self.client.post(
                    f"{ANTHROPIC_API_BASE}/messages",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise ValueError("response body is not an object")
            except httpx.HTTPStatusError as e:
                last_err = str(e)
                status = e.response.status_code
                if self.auth_pool is not None and is_rotatable_status(status) and self.auth_pool.size > 1:
                    self.auth_pool.report_failure(key)
                    continue   # fail over to the next key
                return None, f"[Claude API error: {e}]"
            except Exception as e:
                return None, f"[Claude API error: {e}]"
            if self.auth_pool is not None:
                self.auth_pool.report_success(key)
            return data, ""
        return None, f"[Claude API error: all auth profiles exhausted: {last_err}]"

    async def generate(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        model = model or self.model
        payload = {
            "model": model,
            "max_tokens": cloud_cap(max_tokens),
            "temperature": temperature,
            "system": system,
            "messages": self._build_messages(prompt, system),
        }
        self._fit_to_wire(payload, model)
        data, error = await self._post_messages(payload)
        if data is None:
            return error
        if data.get("content"):
            return self._finalize_cloud(anthropic_text(data["content"]))
        return ""

    async def generate_tool_turn(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> ToolTurn:
        """One tool-enabled turn; every tool_use block crosses `parse_openai_tool_calls`."""
        system, converted = anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": cloud_cap(max_tokens),
            "temperature": temperature,
            "messages": converted,
        }
        if system:
            payload["system"] = cache_marked_system(system)
        if tools:
            # The breakpoint goes on the LAST tool because a `cache_control` mark
            # covers everything *before* it: one mark caches the whole tool array,
            # and the array plus the system prompt are the two things that do not
            # change between the turns of one session. Marking each tool instead
            # would spend the four-breakpoint budget on a prefix already covered.
            payload["tools"] = cache_marked_tools(anthropic_tools(tools))
            payload["tool_choice"] = {"type": "auto"}
        self._fit_to_wire(payload, payload["model"])
        data, error = await self._post_messages(payload)
        if data is None:
            return ToolTurn(content=error)
        blocks = data.get("content") or []
        return ToolTurn(
            content=self._finalize_cloud(anthropic_text(blocks)),
            tool_calls=parse_openai_tool_calls(anthropic_tool_calls(blocks)),
            finish_reason=normalize_finish_reason(ANTHROPIC_FINISH_REASONS, data.get("stop_reason")),
            usage=anthropic_usage(data),
        )

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        model = model or self.model
        payload = {
            "model": model,
            "max_tokens": cloud_cap(max_tokens),
            "temperature": temperature,
            "system": system,
            "messages": self._build_messages(prompt, system),
            "stream": True,
        }
        self._fit_to_wire(payload, model)
        full = ""
        stream_key = self._active_key()
        try:
            async with self.client.stream(
                "POST",
                f"{ANTHROPIC_API_BASE}/messages",
                headers=self._headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                            event_type = data.get("type", "")
                            if event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                # Only the answer's own deltas. H364 makes thinking
                                # reachable on this stream for the first time, and a
                                # reasoning delta must never be concatenated into the
                                # reply — so the block type decides, not the presence
                                # of a `text` key.
                                text = (
                                    delta.get("text", "")
                                    if delta.get("type") == "text_delta"
                                    else ""
                                )
                                if text:
                                    full += text
                                    if on_token:
                                        await _emit(on_token, text)
                            elif event_type == "message_stop":
                                break
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPStatusError as e:
            # Rotatable error → cool this key down so the next call fails over (H12.20).
            if self.auth_pool is not None and is_rotatable_status(e.response.status_code):
                self.auth_pool.report_failure(stream_key)
            full = f"[Claude API stream error: {e}]"
        except Exception as e:
            full = f"[Claude API stream error: {e}]"
        return self._finalize_cloud(full)

    async def aclose(self):
        """Close the pooled httpx client (BUG-7)."""
        await self.client.aclose()
