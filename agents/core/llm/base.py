"""
base.py — Abstract LLM backend interface with streaming support.
Supports LM Studio (OpenAI-compatible API) and Ollama.
"""

import asyncio
import inspect
import json
import re
from abc import ABC, abstractmethod
from typing import Callable, Optional

import httpx


# ── Post-processing filter (used on non-stream responses) ─────────────────────

def strip_thinking(text: str) -> str:
    """Remove chain-of-thought reasoning from a complete LLM response.

    Handles formats emitted by thinking-capable models (qwen3, deepseek-r1, etc.):
      1. <think>...</think> XML-style tags
      2. "Here's a thinking process..." prose blocks with numbered steps
      3. Leading numbered-step sections before the actual answer
    """
    if not text:
        return text

    # 1. <think>…</think> blocks
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 2. "Here's a thinking process…" / "**Thinking…**" narrative blocks
    cleaned = re.sub(
        r"(?:Here['\u2019]?s a thinking process.*?\n|\*{0,2}Thinking.*?\*{0,2}\n)"
        r"(?:.*?\n)*?(?=\n[A-Z\u0102\u00ce\u0218\u021a\u00c2]|\Z)",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # 3. Leading numbered-step blocks (stop at first blank line after steps)
    cleaned = re.sub(
        r"^(?:\d+\.\s+.+\n)+\n",
        "",
        cleaned,
        flags=re.MULTILINE,
    )

    return cleaned.strip()


# ── Real-time streaming filter ────────────────────────────────────────────────

class ThinkingStreamFilter:
    """Filters <think>...</think> blocks from a streamed sequence of chunks.

    Feed chunks one by one via .feed(chunk); each call returns the text that
    is safe to emit right now (may be empty if we are inside a think block).
    Call .flush() at the end of the stream to get any remaining buffered text.
    """

    _OPEN_TAG = "<think>"
    _CLOSE_TAG = "</think>"

    def __init__(self):
        self._in_think: bool = False
        self._buf: str = ""

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out_parts = []

        while self._buf:
            if self._in_think:
                end = self._buf.find(self._CLOSE_TAG)
                if end >= 0:
                    self._in_think = False
                    self._buf = self._buf[end + len(self._CLOSE_TAG):]
                else:
                    # Still inside thinking — discard all but a tail guard
                    # (keep enough chars to detect a split </think> tag)
                    guard = len(self._CLOSE_TAG) - 1
                    self._buf = self._buf[-guard:] if len(self._buf) > guard else self._buf
                    break
            else:
                start = self._buf.find(self._OPEN_TAG)
                if start >= 0:
                    # Emit everything before <think>
                    if start > 0:
                        out_parts.append(self._buf[:start])
                    self._in_think = True
                    self._buf = self._buf[start + len(self._OPEN_TAG):]
                else:
                    # No opening tag yet — emit safely (keep a tail guard for
                    # a potential partial <think> split across chunks)
                    guard = len(self._OPEN_TAG) - 1
                    safe_len = max(0, len(self._buf) - guard)
                    if safe_len > 0:
                        out_parts.append(self._buf[:safe_len])
                        self._buf = self._buf[safe_len:]
                    break

        return "".join(out_parts)

    def flush(self) -> str:
        """Return any remaining buffer after stream ends (skip if in think block)."""
        if self._in_think:
            return ""
        remainder = self._buf
        self._buf = ""
        return remainder


# ── Async-safe token emitter ──────────────────────────────────────────────────

async def _emit(on_token: Callable, text: str) -> None:
    """Call on_token whether it is a coroutine function or a plain callable."""
    if not text:
        return
    if inspect.iscoroutinefunction(on_token):
        await on_token(text)
    else:
        on_token(text)


# ── Abstract base ─────────────────────────────────────────────────────────────

class LLMBackend(ABC):
    @abstractmethod
    async def generate(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        ...

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        full = await self.generate(model, prompt, system, max_tokens, temperature)
        if on_token:
            await _emit(on_token, full)
        return full


# ── LM Studio ─────────────────────────────────────────────────────────────────

class LMStudioBackend(LLMBackend):
    """LM Studio local server (GPU-accelerated on Windows)."""

    def __init__(self, base_url: str = "http://localhost:1234"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=300.0)

    async def generate(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        try:
            resp = await self.client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content", "")
            if not content:
                # Fallback for models that put everything in reasoning_content
                content = msg.get("reasoning_content", "")
            return strip_thinking(content)
        except Exception as e:
            return f"[LM Studio error: {e}]"

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        full = ""
        reasoning_full = ""
        sf = ThinkingStreamFilter()
        try:
            async with self.client.stream("POST", "/v1/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(chunk)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            reasoning = delta.get("reasoning_content", "")
                            if content:
                                safe = sf.feed(content)
                                full += content
                                if on_token and safe:
                                    await _emit(on_token, safe)
                            if reasoning:
                                reasoning_full += reasoning
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            err = f"[LM Studio stream error: {e}]"
            full = err
            if on_token:
                await _emit(on_token, err)
            return full

        # Flush any remaining buffered text
        remainder = sf.flush()
        if on_token and remainder:
            await _emit(on_token, remainder)

        # Fall back to reasoning_full if content was completely empty (for models
        # that put all thinking and final answers in reasoning_content)
        text_to_clean = full if full else reasoning_full
        return strip_thinking(text_to_clean)


# ── Ollama ────────────────────────────────────────────────────────────────────

class OllamaBackend(LLMBackend):
    """Ollama local server."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=120.0)

    async def generate(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7
    ) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        try:
            resp = await self.client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return strip_thinking(data.get("response", ""))
        except Exception as e:
            return f"[Ollama error: {e}]"

    async def generate_stream(
        self, model: str, prompt: str, system: str = "",
        max_tokens: int = 1024, temperature: float = 0.7,
        on_token: Callable[[str], None] = None,
    ) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        full = ""
        reasoning_full = ""
        sf = ThinkingStreamFilter()
        try:
            async with self.client.stream("POST", "/api/generate", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            content = data.get("response", "")
                            reasoning = data.get("reasoning_content", "")
                            if content:
                                safe = sf.feed(content)
                                full += content
                                if on_token and safe:
                                    await _emit(on_token, safe)
                            if reasoning:
                                reasoning_full += reasoning
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            err = f"[Ollama stream error: {e}]"
            full = err
            if on_token:
                await _emit(on_token, err)
            return full

        remainder = sf.flush()
        if on_token and remainder:
            await _emit(on_token, remainder)

        text_to_clean = full if full else reasoning_full
        return strip_thinking(text_to_clean)
