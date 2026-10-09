"""
vlm.py — H13.1 Vision-Language model adapter (integration layer).

A strict-local VLM (Qwen3-VL etc.) for screen/document/receipt/PDF understanding
serves over an **OpenAI-vision-compatible** API. This module is the integration
layer — image preprocessing (base64 data-URI, optional downscale to respect the
KV-cache budget) + the vision message format + the backend — all offline-testable
with an injectable client, exactly like the OpenRouter adapter (H20.2).

The model weights + GGUF build + 24GB GPU are the **host deployment seam**:
LM Studio (``http://localhost:1234/v1``, load a ``vlm``-type model), vLLM and
llama.cpp all serve the same OpenAI-vision contract, and this adapter drives any
of them. Select with ``JARVIS_VLM_BACKEND`` (``lmstudio`` | ``custom``; unset =
off) — ``resolve_vlm_config`` is the single config reader, and it never guesses:
no backend means "not configured", and ``lmstudio`` without a pinned
``JARVIS_VLM_MODEL`` refuses rather than inventing a model name (the
companion-eval precedent). ``generate_vision`` feeds the Howard pipeline;
text-only ``generate`` keeps the LLMBackend contract.

``JARVIS_VLM_PRESET`` (optional) names one of the pinned open grounders in
``VLM_PRESETS`` so the screen locator knows which **coordinate convention** the
model emits (OS-Atlas-style 0–1000 vs. UI-TARS-style absolute-on-resized) — a
preset annotates and validates, it never substitutes for the ``JARVIS_VLM_MODEL``
pin, because the served model name is the host's fact, not ours.
"""

from __future__ import annotations

import base64
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional

from ..screen_grounding import (
    CONVENTION_ABSOLUTE,
    CONVENTION_ABSOLUTE_RESIZED,
    CONVENTION_RELATIVE_1000,
    CONVENTIONS,
)
from . import model_roles
from .base import LLMBackend
from .egress import llm_async_client
from .model_roles import LMSTUDIO_VLM_BASE, _is_loopback_base  # noqa: F401 — re-exported by name
from .native_response import compatible_empty_success, compatible_vision_answer
from .vision_retry import current_vision_retry

logger = logging.getLogger("jarvis.llm.vlm")

DEFAULT_VLM_BASE = "http://localhost:8000/v1"
# LM Studio's OpenAI-compatible server default (``LMSTUDIO_VLM_BASE``) and the loopback
# label ``_is_loopback_base`` live in the H277 role table now and keep their names here;
# Ollama serves the same contract on 11434/v1 (same constant the companion-eval lane documents).
_FMT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "JPG": "image/jpeg",
             "GIF": "image/gif", "WEBP": "image/webp"}
MAX_VISION_RESPONSE_BYTES = 512_000
VISION_GENERATION_TIMEOUT = 180


def _mime(fmt: str) -> str:
    return _FMT_MIME.get((fmt or "PNG").upper(), "image/png")


class VLMNotConfigured(RuntimeError):
    """No VLM backend is configured; carries the stable refusal reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ── pinned local grounder presets ────────────────────────────────────────────
#
# Open grounders disagree on what a coordinate *means*: OS-Atlas / Qwen3-VL emit
# 0–1000 relative coordinates, UI-TARS / Holo emit absolute pixels on the
# *resized* image the model actually saw. Without a preset the locator can only
# assume absolute-on-original and a relative grounder produces silent mis-clicks
# in the top-left 1000×1000 corner. The table is the difference between a
# working visual route and a plausible-looking wrong one. Conventions are the
# names ``screen_grounding.normalize_coords`` understands.
#
# Honesty: these are pinned from the models' published inference notes, not
# from an owner run — the per-preset convention is delivered-not-proven until a
# real screenshot round-trips on hardware (🔨 in BACKLOG).

# The convention names live in screen_grounding (the module that converts them):
#   absolute         — pixels on the original screenshot
#   absolute_resized — pixels on the resized model input (UI-TARS / Holo)
#   relative_1000    — 0–1000 per axis (OS-Atlas / Qwen3-VL)
#   relative_unit    — 0.0–1.0 per axis
COORDINATE_CONVENTIONS: frozenset[str] = frozenset(CONVENTIONS)


@dataclass(frozen=True)
class VLMPreset:
    """One pinned open grounder: its coordinate convention and a prompt hint."""

    id: str
    family: str
    convention: str
    size_gb: float
    prompt_hint: str
    license: str = "Apache-2.0"

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("preset id is required")
        if self.convention not in COORDINATE_CONVENTIONS:
            raise ValueError(f"unknown coordinate convention: {self.convention!r}")
        if isinstance(self.size_gb, bool) or not isinstance(self.size_gb, (int, float)):
            raise ValueError("size_gb must be a number")
        if not self.size_gb > 0:
            raise ValueError("size_gb must be positive")
        if not isinstance(self.prompt_hint, str):
            raise ValueError("prompt_hint must be text")


_ABSOLUTE_HINT = (
    "Answer with pixel coordinates of the image you were given, as `label at (x, y)`."
)
_RELATIVE_1000_HINT = (
    "Answer with coordinates normalized to a 0-1000 range on each axis, "
    "as `label at (x, y)`."
)

VLM_PRESETS: dict[str, VLMPreset] = {
    preset.id: preset
    for preset in (
        VLMPreset("qwen3-vl-4b", "qwen3-vl", CONVENTION_RELATIVE_1000, 4.5, _RELATIVE_1000_HINT),
        VLMPreset("qwen3-vl-8b", "qwen3-vl", CONVENTION_RELATIVE_1000, 8.9, _RELATIVE_1000_HINT),
        VLMPreset("ui-tars-1.5-7b", "ui-tars", CONVENTION_ABSOLUTE_RESIZED, 8.3, _ABSOLUTE_HINT),
        VLMPreset("holo-3.1-35b-a3b", "holo", CONVENTION_ABSOLUTE_RESIZED, 21.0, _ABSOLUTE_HINT),
        VLMPreset("qwen3.8-27b", "qwen3-vl", CONVENTION_RELATIVE_1000, 16.5, _RELATIVE_1000_HINT),
    )
}


def resolve_vlm_preset(name: str) -> VLMPreset:
    """Look up a pinned preset by id; an unknown id is a config typo, not a guess."""
    key = str(name or "").strip().lower()
    preset = VLM_PRESETS.get(key)
    if preset is None:
        raise VLMNotConfigured("vlm_preset_unknown")
    return preset


@dataclass(frozen=True)
class VLMConfig:
    """Resolved VLM configuration (the only shape callers should consume).

    ``preset`` / ``convention`` annotate which grounder is served (from
    ``JARVIS_VLM_PRESET``); with no preset the convention defaults to absolute
    pixels on the original screenshot, the only convention the free-text
    ``label at (x, y)`` contract ever promised.
    """

    backend: str  # Local, compatible or reviewed native provider id.
    base_url: str
    model: str
    api_key: str
    is_local: bool
    preset: str = ""
    convention: str = CONVENTION_ABSOLUTE
    wire_mode: str = "chat_completions"
    route_source: str = ""
    prompt_cache_retention: str = "in_memory"
    reasoning_effort: str = ""

    def __post_init__(self) -> None:
        if self.wire_mode not in {"chat_completions", "anthropic_messages", "ollama_chat", "gemini_generate_content", "responses", "xai_responses"} or (
                self.wire_mode == "anthropic_messages" and self.backend not in {"nous", "anthropic"}) or (
                self.wire_mode == "ollama_chat" and self.backend != "ollama") or (
                self.wire_mode == "gemini_generate_content" and self.backend != "gemini") or (
                self.wire_mode == "responses" and self.backend != "openai-responses") or (
                self.wire_mode == "xai_responses" and self.backend != "xai") or (
                self.backend == "anthropic" and self.wire_mode != "anthropic_messages") or (
                self.backend == "gemini" and self.wire_mode != "gemini_generate_content") or (
                self.backend == "openai-responses" and self.wire_mode != "responses") or (
                self.backend == "xai" and self.wire_mode != "xai_responses") or (
                self.backend == "ollama" and self.wire_mode != "ollama_chat"):
            raise ValueError("unsupported vision wire mode")
        if self.prompt_cache_retention not in {"in_memory", "24h"}:
            raise ValueError("unsupported Responses retention")
        if self.reasoning_effort not in {"", "low", "medium", "high", "xhigh"}:
            raise ValueError("unsupported image reasoning effort")
        if self.convention not in COORDINATE_CONVENTIONS:
            raise ValueError(f"unknown coordinate convention: {self.convention!r}")


def resolve_vlm_config(env=None) -> VLMConfig:
    """Resolve the VLM deployment from the environment, refusing to guess.

    Raises VLMNotConfigured with a stable reason instead of returning a
    half-configured backend:
    - ``vlm_disabled`` — JARVIS_VLM_BACKEND unset/off and no legacy
      JARVIS_VLM_URL either.
    - ``vlm_model_unset`` — lmstudio selected but no JARVIS_VLM_MODEL pinned
      (a guessed model would make every downstream record meaningless).
    - ``vlm_url_unset`` — custom selected without JARVIS_VLM_URL.
    - ``vlm_preset_unknown`` — JARVIS_VLM_PRESET names no pinned preset.
    - ``vlm_model_unset`` — a preset is set but JARVIS_VLM_MODEL is not: the
      preset annotates the convention, it never stands in for the model pin.

    - ``role_provider_unknown`` / ``role_provider_unsupported`` (H277) —
      ``JARVIS_ROLE_VISION_PROVIDER`` names no provider profile, or one the vision
      path cannot speak to.

    Legacy compatibility: a bare JARVIS_VLM_URL with no backend selector keeps
    working as ``custom`` (with the historical qwen2-vl model default), so
    existing owner hosts do not regress.

    H277: the reads go through the ``vision`` role (``model_roles.vision_env_view``):
    ``JARVIS_ROLE_VISION_PROVIDER`` (``lm-studio`` | ``openai-compatible``) / ``_MODEL`` /
    ``_BASE_URL`` win when set, and ``JARVIS_VLM_*`` are the fallbacks, unchanged.
    """
    if model_roles._reader(env)("JARVIS_ROLE_VISION_PROVIDER").strip().lower() == "openrouter":
        from .vision_openrouter import resolve_config
        return resolve_config(env)
    if model_roles._reader(env)("JARVIS_ROLE_VISION_PROVIDER").strip().lower() == "deepinfra":
        from .vision_deepinfra import resolve_config
        return resolve_config(env)
    if model_roles._reader(env)("JARVIS_ROLE_VISION_PROVIDER").strip().lower() == "nous":
        from .vision_nous import resolve_config
        return resolve_config(env)
    if model_roles._reader(env)("JARVIS_ROLE_VISION_PROVIDER").strip().lower() == "auto":
        from .vision_auto import resolve_config
        return resolve_config(env)
    try:
        backend, url, model, api_key, preset_name = model_roles.vision_env_view(env)
    except model_roles.RoleConfigError as exc:
        raise VLMNotConfigured(exc.reason) from exc
    backend = backend.strip().lower()
    url = url.strip()
    model = model.strip()
    preset_name = preset_name.strip().lower()
    if backend in {"", "off"} and not (backend == "" and url):
        raise VLMNotConfigured("vlm_disabled")
    if backend not in {"", "lmstudio", "custom"}:
        # An unknown selector is a config typo, not a reason to guess.
        raise VLMNotConfigured("vlm_backend_unknown")
    preset_fields: dict = {}
    if preset_name:
        preset = resolve_vlm_preset(preset_name)
        if not model:
            # A preset says which convention the model speaks; it is not a model.
            raise VLMNotConfigured("vlm_model_unset")
        preset_fields = {"preset": preset.id, "convention": preset.convention}
    if backend == "lmstudio":
        if not model:
            raise VLMNotConfigured("vlm_model_unset")
        base = url or LMSTUDIO_VLM_BASE
        return VLMConfig(
            backend="lmstudio",
            base_url=base,
            model=model,
            api_key=api_key,
            is_local=_is_loopback_base(base),
            **preset_fields,
        )
    # ``custom`` — explicit, or the legacy URL-only path that predates the selector.
    if not url:
        raise VLMNotConfigured("vlm_url_unset")
    return VLMConfig(
        backend="custom",
        base_url=url,
        model=model or "qwen2-vl",
        api_key=api_key,
        is_local=_is_loopback_base(url),
        **preset_fields,
    )


def to_data_uri(image_bytes: bytes, mime: str = "image/png") -> str:
    """Base64 a raw image into a data URI (pure, no deps)."""
    b64 = base64.b64encode(bytes(image_bytes)).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _downscale(image_bytes: bytes, max_dim: int) -> "tuple[bytes, str]":
    """Downscale to fit max_dim if Pillow is available; otherwise pass through."""
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        fmt = img.format or "PNG"
        w, h = img.size
        if max(w, h) <= max_dim:
            return image_bytes, fmt
        scale = max_dim / float(max(w, h))
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        out = io.BytesIO()
        img.save(out, format=fmt)
        return out.getvalue(), fmt
    except Exception:
        return image_bytes, "PNG"   # Pillow missing / not an image → pass through


def encode_image_block(source, max_dim: int = 1024) -> Optional[dict]:
    """Turn bytes / URL / data-URI into an OpenAI image_url content block.

    Only in-memory bytes, ``data:`` URIs, and ``http(s)`` URLs are accepted —
    never a filesystem path, so a request-supplied value can never be used to
    read host files (path injection). A caller holding a file on disk reads the
    bytes itself and passes them in.
    """
    if isinstance(source, (bytes, bytearray)):
        data, fmt = _downscale(bytes(source), max_dim)
        return {"type": "image_url", "image_url": {"url": to_data_uri(data, _mime(fmt))}}
    s = str(source)
    if s.startswith(("data:", "http://", "https://")):
        return {"type": "image_url", "image_url": {"url": s}}
    logger.warning("VLM: unsupported image source (expected bytes, a data: URI, or an http(s) URL)")
    return None


def build_vision_messages(prompt: str, images=None, system: str = "",
                          max_dim: int = 1024) -> list:
    """Build OpenAI vision `messages` (text + image blocks)."""
    content = [{"type": "text", "text": prompt}]
    for img in (images or []):
        block = encode_image_block(img, max_dim)
        if block:
            content.append(block)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    return messages


def build_vision_history_messages(prompt: str, images, history, system: str = "",
                                  max_dim: int = 1024) -> list:
    """Replay explicitly selected active image turns as ordered native parts."""
    from .vision_history import ActiveImageTurn

    if type(history) not in (list, tuple) or not 1 <= len(history) <= 8:
        raise ValueError("invalid active image history")
    if type(prompt) is not str or not prompt.strip():
        raise ValueError("invalid active image question")
    if type(images) not in (list, tuple) or len(images) > 8:
        raise ValueError("invalid active image selection")
    messages = [{"role": "system", "content": system}] if system else []
    image_count = len(images)
    for turn in history:
        if isinstance(turn, ActiveImageTurn):
            question, answer, prior_images = turn.question, turn.answer, turn.images
        elif type(turn) is tuple and len(turn) == 3:
            question, answer, prior_images = turn
        else:
            raise ValueError("invalid active image history")
        if (type(question) is not str or not 0 < len(question) <= 4000 or not question.strip()
                or type(answer) is not str or not 0 < len(answer) <= 16000 or not answer.strip()
                or type(prior_images) not in (list, tuple) or not 1 <= len(prior_images) <= 8
                or any(type(image) is not bytes or not image for image in prior_images)):
            raise ValueError("invalid active image history")
        image_count += len(prior_images)
        if image_count > 8:
            raise ValueError("too many active images")
        parts = [{"type": "text", "text": question}]
        parts.extend(encode_image_block(image, max_dim) for image in prior_images)
        messages.extend(({"role": "user", "content": parts},
                         {"role": "assistant", "content": answer}))
    if any(type(image) is not bytes or not image for image in images):
        raise ValueError("invalid active image selection")
    parts = [{"type": "text", "text": prompt}]
    parts.extend(encode_image_block(image, max_dim) for image in images)
    messages.append({"role": "user", "content": parts})
    return messages


class VLMBackend(LLMBackend):
    """OpenAI-vision-compatible VLM backend (host server is the deployment seam)."""

    # Deliberate: a vision backend answers grounding questions, it never drives the
    # tool loop — the operator decides what to do with what it saw.
    supports_tools = False

    def __init__(self, base_url: str = DEFAULT_VLM_BASE, api_key: str = "",
                 client=None, max_image_dim: int = 1024, *, composer_auth: bool = False,
                 provider_id: str = "", wire_mode: str = "chat_completions",
                 prompt_cache_retention: str = "in_memory", reasoning_effort: str = "") -> None:
        if provider_id not in ("", "openrouter", "deepinfra", "nous", "ollama", "anthropic", "gemini", "openai-responses", "xai"):
            raise ValueError("unsupported native vision provider")
        if wire_mode not in {"chat_completions", "anthropic_messages", "ollama_chat", "gemini_generate_content", "responses", "xai_responses"} or (
                wire_mode == "anthropic_messages" and provider_id not in {"nous", "anthropic"}) or (
                wire_mode == "ollama_chat" and provider_id != "ollama") or (
                wire_mode == "gemini_generate_content" and provider_id != "gemini") or (
                wire_mode == "responses" and provider_id != "openai-responses") or (
                wire_mode == "xai_responses" and provider_id != "xai") or (
                provider_id == "anthropic" and wire_mode != "anthropic_messages") or (
                provider_id == "gemini" and wire_mode != "gemini_generate_content") or (
                provider_id == "openai-responses" and wire_mode != "responses") or (
                provider_id == "xai" and wire_mode != "xai_responses") or (
                provider_id == "ollama" and wire_mode != "ollama_chat"):
            raise ValueError("unsupported vision wire mode")
        if prompt_cache_retention not in {"in_memory", "24h"}:
            raise ValueError("unsupported Responses retention")
        if reasoning_effort not in {"", "low", "medium", "high", "xhigh"}:
            raise ValueError("unsupported image reasoning effort")
        self._wire_mode = wire_mode
        self._provider_id = provider_id
        self._prompt_cache_retention = prompt_cache_retention
        self._reasoning_effort = reasoning_effort
        self.base_url = base_url
        self.api_key = api_key
        self.max_image_dim = max_image_dim
        self._composer_auth = composer_auth
        # Provenance label consumed by proven-local gates (e.g. the H28
        # desktop fallback); a remote base is honestly not local.
        self.is_local = _is_loopback_base(base_url)
        options = {}
        if composer_auth:
            import httpx
            # Suppress URL Basic overriding explicit Bearer; _headers resolves both.
            options["auth"] = httpx.Auth()
            options["trust_env"] = False
        self.client = client or llm_async_client(provider_id or "vlm", base_url=base_url, timeout=180.0, **options)

    @classmethod
    def from_env(cls, *, client=None, max_image_dim: int = 1024) -> "VLMBackend":
        """Build from resolve_vlm_config; raises VLMNotConfigured when off."""
        config = resolve_vlm_config()
        backend = cls(
            base_url=config.base_url,
            api_key=config.api_key,
            client=client,
            max_image_dim=max_image_dim,
            **({"provider_id": config.backend} if config.backend in ("openrouter", "deepinfra", "nous", "ollama", "anthropic", "gemini", "openai-responses", "xai") else {}),
            wire_mode=config.wire_mode,
            prompt_cache_retention=config.prompt_cache_retention,
            reasoning_effort=config.reasoning_effort,
        )
        backend.is_local = config.is_local
        return backend

    async def aclose(self):
        try:
            await self.client.aclose()
        except Exception:  # pragma: no cover - best-effort
            pass

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._wire_mode == "anthropic_messages":
            h["anthropic-version"] = "2023-06-01"
        if self._provider_id == "anthropic":
            h["x-api-key"] = self.api_key
        elif self._provider_id == "gemini":
            h["x-goog-api-key"] = self.api_key
        elif self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        elif self._composer_auth:
            from .vision_policy import authorization
            auth = authorization(self.base_url, self.api_key)
            if auth:
                h["Authorization"] = auth
        return h

    async def generate_vision_checked(self, model: str, prompt: str, images=None, system: str = "",
                              max_tokens: int = 1024, temperature: float = 0.2, *,
                              history=None) -> str:
        messages = (build_vision_history_messages(prompt, images or [], history, system,
                                                  self.max_image_dim)
                    if history is not None else
                    build_vision_messages(prompt, images, system, self.max_image_dim))
        payload = {"model": model, "messages": messages,
                   "max_tokens": max_tokens, "temperature": temperature, "stream": False}
        native_messages = self._wire_mode == "anthropic_messages"
        native_ollama = self._wire_mode == "ollama_chat"
        native_gemini = self._wire_mode == "gemini_generate_content"
        native_responses = self._wire_mode == "responses"
        native_xai = self._wire_mode == "xai_responses"
        if native_gemini:
            from .video_native import gemini_request_url
            gemini_request_url(self.base_url, model)
        endpoint = (f"/models/{model}:generateContent" if native_gemini else
                    "/responses" if native_responses or native_xai else
                    "/messages" if native_messages else "/api/chat" if native_ollama else "/chat/completions")
        answer, empty = compatible_vision_answer, compatible_empty_success
        if native_messages:
            from .vision_nous_wire import messages_payload, messages_answer, messages_empty
            payload = messages_payload(payload)
            answer, empty = messages_answer, messages_empty
        if native_ollama:
            from .vision_ollama_wire import chat_payload, chat_answer, chat_empty
            payload = chat_payload(payload)
            answer, empty = chat_answer, chat_empty
        if native_gemini:
            from .vision_gemini_wire import (
                generate_content_answer, generate_content_empty, generate_content_payload,
            )
            payload = generate_content_payload(payload)
            answer, empty = generate_content_answer, generate_content_empty
        if native_responses:
            from .vision_responses_wire import responses_answer, responses_empty, responses_payload
            payload = responses_payload(payload, retention=self._prompt_cache_retention)
            answer, empty = responses_answer, responses_empty
        if native_xai:
            from .vision_xai_wire import xai_answer, xai_empty, xai_payload
            payload = xai_payload(payload, reasoning_effort=self._reasoning_effort)
            answer, empty = xai_answer, xai_empty
        if self._provider_id == "openrouter":
            from .vision_openrouter import current_provider_block
            payload["provider"] = current_provider_block()
        if history is not None and len(json.dumps(
                payload, separators=(",", ":"), ensure_ascii=False).encode()) > 20_000_000:
            raise ValueError("active image request too large")
        scope = current_vision_retry(self, model)
        image_bearing = any(isinstance(part, dict) and part.get("type") == "image_url"
                            for message in messages if isinstance(message.get("content"), list)
                            for part in message["content"])
        recovery = scope if image_bearing else None
        if recovery is not None or history is not None or self._provider_id in {"deepinfra", "nous", "ollama", "anthropic", "gemini", "openai-responses", "xai"}:
            if recovery is not None:
                recovery.begin(payload)
            async with asyncio.timeout(VISION_GENERATION_TIMEOUT):
                attempts = recovery.max_attempts if recovery is not None else 1
                for attempt in range(attempts):
                    attempt_body = recovery.next_attempt() if recovery is not None else payload
                    async with self.client.stream(
                            "POST", endpoint, json=attempt_body,
                            headers=self._headers()) as response:
                        result = bytearray()
                        async for chunk in response.aiter_bytes():
                            if recovery is not None:
                                recovery.check()
                            if len(result) + len(chunk) > MAX_VISION_RESPONSE_BYTES:
                                raise ValueError("vision response too large")
                            result.extend(chunk)
                        if recovery is not None:
                            recovery.check()
                        response.raise_for_status()
                    if recovery is not None:
                        recovery.check()
                    data = json.loads(result)
                    if recovery is not None and attempt + 1 < attempts and empty(data):
                        continue
                    return answer(data)
        resp = await self.client.post(endpoint, json=payload, headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        return answer(data)

    async def generate_vision(self, model: str, prompt: str, images=None, system: str = "",
                              max_tokens: int = 1024, temperature: float = 0.2) -> str:
        # Historical callers retain the sentinel contract; explicit composer turns
        # use the checked method so failed inference cannot look like an answer.
        try:
            return await self.generate_vision_checked(model, prompt, images, system, max_tokens, temperature)
        except Exception as e:
            logger.warning("VLM generate failed: %s", e)
            return "[VLM error]"

    async def generate(self, model: str, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> str:
        # Text-only path keeps the LLMBackend contract.
        return await self.generate_vision(model, prompt, images=[], system=system,
                                          max_tokens=max_tokens, temperature=temperature)
