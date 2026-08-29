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
"""

from __future__ import annotations

import base64
import ipaddress
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

import httpx

from ..env_config import env_str
from .base import LLMBackend, strip_thinking

logger = logging.getLogger("jarvis.llm.vlm")

DEFAULT_VLM_BASE = "http://localhost:8000/v1"
# LM Studio's OpenAI-compatible server default; Ollama serves the same
# contract on 11434/v1 (same constant the companion-eval lane documents).
LMSTUDIO_VLM_BASE = "http://localhost:1234/v1"
_FMT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "JPG": "image/jpeg",
             "GIF": "image/gif", "WEBP": "image/webp"}


def _mime(fmt: str) -> str:
    return _FMT_MIME.get((fmt or "PNG").upper(), "image/png")


class VLMNotConfigured(RuntimeError):
    """No VLM backend is configured; carries the stable refusal reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _is_loopback_base(url: str) -> bool:
    """Best-effort loopback check for provenance labeling (never raises).

    This is a boolean *label*, not a gate — the consent-scoped camera path
    keeps its own strict fail-closed validator (cameras/vlm._local_endpoint),
    which cannot be imported here without a package cycle.
    """
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class VLMConfig:
    """Resolved VLM configuration (the only shape callers should consume)."""

    backend: str  # "lmstudio" | "custom"
    base_url: str
    model: str
    api_key: str
    is_local: bool


def resolve_vlm_config(env=None) -> VLMConfig:
    """Resolve the VLM deployment from the environment, refusing to guess.

    Raises VLMNotConfigured with a stable reason instead of returning a
    half-configured backend:
    - ``vlm_disabled`` — JARVIS_VLM_BACKEND unset/off and no legacy
      JARVIS_VLM_URL either.
    - ``vlm_model_unset`` — lmstudio selected but no JARVIS_VLM_MODEL pinned
      (a guessed model would make every downstream record meaningless).
    - ``vlm_url_unset`` — custom selected without JARVIS_VLM_URL.

    Legacy compatibility: a bare JARVIS_VLM_URL with no backend selector keeps
    working as ``custom`` (with the historical qwen2-vl model default), so
    existing owner hosts do not regress.
    """

    def _get(name: str, default: str = "") -> str:
        if env is not None:
            return str(env.get(name, default) or default)
        return env_str(name, default)

    backend = _get("JARVIS_VLM_BACKEND").strip().lower()
    url = _get("JARVIS_VLM_URL").strip()
    model = _get("JARVIS_VLM_MODEL").strip()
    api_key = _get("JARVIS_VLM_KEY")
    if backend in {"", "off"}:
        if backend == "" and url:
            # Legacy path: URL-only configuration predates the selector.
            return VLMConfig(
                backend="custom",
                base_url=url,
                model=model or "qwen2-vl",
                api_key=api_key,
                is_local=_is_loopback_base(url),
            )
        raise VLMNotConfigured("vlm_disabled")
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
        )
    if backend == "custom":
        if not url:
            raise VLMNotConfigured("vlm_url_unset")
        return VLMConfig(
            backend="custom",
            base_url=url,
            model=model or "qwen2-vl",
            api_key=api_key,
            is_local=_is_loopback_base(url),
        )
    # An unknown selector is a config typo, not a reason to guess.
    raise VLMNotConfigured("vlm_backend_unknown")


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


class VLMBackend(LLMBackend):
    """OpenAI-vision-compatible VLM backend (host server is the deployment seam)."""

    def __init__(self, base_url: str = DEFAULT_VLM_BASE, api_key: str = "",
                 client=None, max_image_dim: int = 1024) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.max_image_dim = max_image_dim
        # Provenance label consumed by proven-local gates (e.g. the H28
        # desktop fallback); a remote base is honestly not local.
        self.is_local = _is_loopback_base(base_url)
        self.client = client or httpx.AsyncClient(base_url=base_url, timeout=180.0)

    @classmethod
    def from_env(cls, *, client=None, max_image_dim: int = 1024) -> "VLMBackend":
        """Build from resolve_vlm_config; raises VLMNotConfigured when off."""
        config = resolve_vlm_config()
        backend = cls(
            base_url=config.base_url,
            api_key=config.api_key,
            client=client,
            max_image_dim=max_image_dim,
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
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def generate_vision(self, model: str, prompt: str, images=None, system: str = "",
                              max_tokens: int = 1024, temperature: float = 0.2) -> str:
        messages = build_vision_messages(prompt, images, system, self.max_image_dim)
        payload = {"model": model, "messages": messages,
                   "max_tokens": max_tokens, "temperature": temperature, "stream": False}
        try:
            resp = await self.client.post("/chat/completions", json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            content = (data["choices"][0]["message"].get("content", "") or "")
            return strip_thinking(content)
        except Exception as e:
            logger.warning("VLM generate failed: %s", e)
            return "[VLM error]"

    async def generate(self, model: str, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> str:
        # Text-only path keeps the LLMBackend contract.
        return await self.generate_vision(model, prompt, images=[], system=system,
                                          max_tokens=max_tokens, temperature=temperature)
