"""
base.py — Abstract LLM backend interface with streaming support.
Supports LM Studio (OpenAI-compatible API) and Ollama.
"""

import inspect
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Callable

import httpx

logger = logging.getLogger("jarvis.llm.base")


# ── Output-budget ("max tokens") resolution ───────────────────────────────────
# A single dial, not two. `max_tokens <= 0` (or falsy) means **auto**: let the
# model answer using its full loaded context — i.e. whatever you sized in LM
# Studio / Ollama — instead of a second, smaller Jarvis-side cap that silently
# truncates reasoning models mid-thought. Local servers express "use the whole
# context" natively (LM Studio: omit the field; Ollama: num_predict = -1). Cloud
# APIs can't — they require a concrete positive ceiling — so for them auto falls
# back to CLOUD_AUTO_MAX_TOKENS.
CLOUD_AUTO_MAX_TOKENS = 8192


def is_auto_max_tokens(max_tokens: int) -> bool:
    """True when the caller wants the model's full context (auto), not a hard cap."""
    return not max_tokens or max_tokens <= 0


def cloud_cap(max_tokens: int) -> int:
    """Concrete output ceiling for cloud backends (auto -> CLOUD_AUTO_MAX_TOKENS)."""
    return max_tokens if (max_tokens and max_tokens > 0) else CLOUD_AUTO_MAX_TOKENS


# ── Post-processing filter (used on non-stream responses) ─────────────────────

def strip_thinking(text: str) -> str:
    """Remove chain-of-thought reasoning from a complete LLM response.

    Handles formats emitted by thinking-capable models (qwen3, deepseek-r1,
    gemma, etc.):
      1a. <think>...</think> XML-style tags (closed)
      1b. <think> with no closing tag — reasoning that never reached an answer
          (e.g. generation truncated at max_tokens mid-thought). Drop to end.
      2. "Here's a thinking process..." prose blocks with numbered steps
      3. Leading numbered-step sections before the actual answer
    """
    if not text:
        return text

    # 1a. Closed <think>…</think> blocks
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 1b. Unterminated <think> (no closing tag): the model was still reasoning
    # when the stream ended/was truncated, so everything from the tag onward is
    # chain-of-thought, not an answer. Without this, a truncated think block
    # leaks verbatim because the closed-tag regex above never matches it.
    cleaned = re.sub(r"<think>.*\Z", "", cleaned, flags=re.DOTALL | re.IGNORECASE)

    # 2. "Here's a thinking process…" / "**Thinking…**" narrative blocks
    cleaned = re.sub(
        r"(?:Here['\u2019]?s a thinking process.*?\n|\*{0,2}Thinking.*?\*{0,2}\n)"
        r"(?:.*?\n)*?(?=\n[A-Z\u0102\u00ce\u0218\u021a\u00c2]|\Z)",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # 3. Leading numbered-step blocks (stop at first blank line after steps).
    # Each step line is newline-bounded ([ \t] then [^\n]*) so the pattern stays
    # linear — the old `\d+\.\s+.+` let `\s+` span newlines and overlap `.+`,
    # which CodeQL flagged as a super-linear (ReDoS-prone) regex (#1).
    cleaned = re.sub(
        r"^(?:\d+\.[ \t][^\n]*\n)+\n",
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

    async def warm_up(self, model: str) -> bool:
        """Preload *model* with a minimal generation so the first real request
        doesn't pay the cold-load cost (model weights swapped into VRAM).

        Best-effort: returns True on a clean response, False on any failure, and
        never raises — warm-up must not break startup. Backends with a native
        preload path (e.g. Ollama) override this."""
        try:
            out = await self.generate(model, ".", max_tokens=1, temperature=0.0)
            # generate() reports failures as a "[backend error: …]" string, not
            # an exception — treat those as a failed warm-up.
            return not (isinstance(out, str) and out.startswith("["))
        except Exception:
            return False

    @staticmethod
    def _finalize_stream(emitted: str, reasoning_full: str, finish, model: str) -> str:
        """Decide the value a streamed generation returns.

        `emitted` is the already-filtered text the user saw. Prefer it. If it is
        empty, the answer was either (a) placed entirely in reasoning_content by
        the model — surface it only when generation finished cleanly — or (b)
        truncated at max_tokens mid-thought (finish == "length"), in which case
        there is no answer, only chain-of-thought, and we must not leak it.
        """
        answer = strip_thinking(emitted)
        if answer:
            return answer
        if finish == "length":
            # FP: "max_tokens" is a context-size note; only the model name is logged, no secret.
            # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
            logger.warning(
                "Stream truncated at max_tokens before an answer (model=%s); "
                "the model filled its context before answering — load a larger-context "
                "model in LM Studio (or, if llm.max_tokens is set to a manual cap, raise it)",
                model,
            )
            return ""
        return strip_thinking(reasoning_full)

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

    async def aclose(self):
        """Close the HTTP client's connection pool (BUG-7)."""
        await self.client.aclose()

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
            "temperature": temperature,
            "stream": False,
        }
        # Auto (max_tokens <= 0): omit the cap so LM Studio answers up to the
        # loaded model's full context — the single dial sized in LM Studio.
        if not is_auto_max_tokens(max_tokens):
            payload["max_tokens"] = max_tokens
        try:
            resp = await self.client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            msg = choice.get("message", {})
            finish = choice.get("finish_reason")
            answer = strip_thinking(msg.get("content", "") or "")
            if answer:
                return answer
            # No answer in `content`. This happens two ways:
            #  - The model puts its whole reply in `reasoning_content` (legit) —
            #    surface it only when generation actually finished.
            #  - Generation was truncated at max_tokens mid-thought (finish ==
            #    "length"): there is no answer yet, only chain-of-thought. Never
            #    surface that — it is exactly the leak we are guarding against.
            if finish == "length":
                # FP: "max_tokens" is a context-size note; only the model name is logged, no secret.
                # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
                logger.warning(
                    "LM Studio truncated at max_tokens before an answer (model=%s); "
                    "the model filled its context before answering — load a larger-context "
                "model in LM Studio (or, if llm.max_tokens is set to a manual cap, raise it)",
                    model,
                )
                return ""
            return strip_thinking(msg.get("reasoning_content", "") or "")
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
            "temperature": temperature,
            "stream": True,
        }
        # Auto (max_tokens <= 0): omit the cap so LM Studio answers up to the
        # loaded model's full context — the single dial sized in LM Studio.
        if not is_auto_max_tokens(max_tokens):
            payload["max_tokens"] = max_tokens
        emitted = ""          # filtered text actually streamed to the user
        reasoning_full = ""   # accumulated reasoning_content (never emitted live)
        finish = None
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
                            choice = data.get("choices", [{}])[0]
                            if choice.get("finish_reason"):
                                finish = choice["finish_reason"]
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            reasoning = delta.get("reasoning_content", "")
                            if content:
                                safe = sf.feed(content)
                                if safe:
                                    emitted += safe
                                    if on_token:
                                        await _emit(on_token, safe)
                            if reasoning:
                                reasoning_full += reasoning
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            err = f"[LM Studio stream error: {e}]"
            if on_token:
                await _emit(on_token, err)
            return err

        # Flush any remaining buffered text (drops an unterminated think block)
        remainder = sf.flush()
        if remainder:
            emitted += remainder
            if on_token:
                await _emit(on_token, remainder)

        # Return what was actually streamed, not the raw buffer — otherwise a
        # truncated <think> / reasoning_content trace would overwrite the clean
        # bubble and poison conversation memory.
        return self._finalize_stream(emitted, reasoning_full, finish, model)


# ── Ollama ────────────────────────────────────────────────────────────────────

class OllamaBackend(LLMBackend):
    """Ollama local server."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=120.0)

    async def aclose(self):
        """Close the HTTP client's connection pool (BUG-7)."""
        await self.client.aclose()

    async def warm_up(self, model: str) -> bool:
        """Preload via Ollama's load path (empty prompt loads weights without
        generating) and pin the model resident with keep_alive=-1 so it doesn't
        unload between turns. Best-effort, never raises."""
        try:
            resp = await self.client.post("/api/generate", json={
                "model": model,
                "prompt": "",
                "keep_alive": -1,
                "stream": False,
            })
            resp.raise_for_status()
            return True
        except Exception:
            return False

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
                # Auto (max_tokens <= 0) -> -1: generate until the loaded model's
                # context is full (Ollama's "infinite"), matching the single dial.
                "num_predict": max_tokens if not is_auto_max_tokens(max_tokens) else -1,
                "temperature": temperature,
            },
        }
        try:
            resp = await self.client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            answer = strip_thinking(data.get("response", "") or "")
            if not answer and data.get("done_reason") == "length":
                logger.warning(
                    "Ollama truncated at num_predict before an answer (model=%s); "
                    "the model filled its context before answering — load a larger-context "
                "model in LM Studio (or, if llm.max_tokens is set to a manual cap, raise it)",
                    model,
                )
            return answer
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
                # Auto (max_tokens <= 0) -> -1: generate until the loaded model's
                # context is full (Ollama's "infinite"), matching the single dial.
                "num_predict": max_tokens if not is_auto_max_tokens(max_tokens) else -1,
                "temperature": temperature,
            },
        }
        emitted = ""
        reasoning_full = ""
        finish = None
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
                                if safe:
                                    emitted += safe
                                    if on_token:
                                        await _emit(on_token, safe)
                            if reasoning:
                                reasoning_full += reasoning
                            if data.get("done", False):
                                finish = data.get("done_reason") or finish
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            err = f"[Ollama stream error: {e}]"
            if on_token:
                await _emit(on_token, err)
            return err

        remainder = sf.flush()
        if remainder:
            emitted += remainder
            if on_token:
                await _emit(on_token, remainder)

        return self._finalize_stream(emitted, reasoning_full, finish, model)
