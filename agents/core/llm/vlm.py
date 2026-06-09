"""
vlm.py — H13.1 Vision-Language model adapter (integration layer).

A strict-local VLM (Qwen3-VL etc.) for screen/document/receipt/PDF understanding
serves over an **OpenAI-vision-compatible** API. This module is the integration
layer — image preprocessing (base64 data-URI, optional downscale to respect the
KV-cache budget) + the vision message format + the backend — all offline-testable
with an injectable client, exactly like the OpenRouter adapter (H20.2).

The model weights + GGUF build + 24GB GPU are the **host deployment seam**: point
``JARVIS_VLM_URL`` at a local vision server (vLLM / llama.cpp) and this adapter
drives it. ``generate_vision`` feeds the Howard pipeline; text-only ``generate``
keeps the LLMBackend contract.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import httpx

from .base import LLMBackend, strip_thinking

logger = logging.getLogger("jarvis.llm.vlm")

DEFAULT_VLM_BASE = "http://localhost:8000/v1"
_FMT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "JPG": "image/jpeg",
             "GIF": "image/gif", "WEBP": "image/webp"}


def _mime(fmt: str) -> str:
    return _FMT_MIME.get((fmt or "PNG").upper(), "image/png")


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


def encode_image_block(source, max_dim: int = 1024,
                       allow_local_files: bool = True) -> Optional[dict]:
    """Turn bytes / file-path / URL / data-URI into an OpenAI image_url content block.

    ``allow_local_files`` must be **False** for untrusted (e.g. HTTP request)
    input — otherwise a caller could read arbitrary host files by passing a path
    (path injection). Internal callers (on-disk screenshots) may pass True.
    """
    if isinstance(source, (bytes, bytearray)):
        data, fmt = _downscale(bytes(source), max_dim)
        return {"type": "image_url", "image_url": {"url": to_data_uri(data, _mime(fmt))}}
    s = str(source)
    if s.startswith(("data:", "http://", "https://")):
        return {"type": "image_url", "image_url": {"url": s}}
    if not allow_local_files:
        logger.warning("VLM: rejected non-URL image source from untrusted input")
        return None
    try:
        with open(s, "rb") as f:
            raw = f.read()
        data, fmt = _downscale(raw, max_dim)
        return {"type": "image_url", "image_url": {"url": to_data_uri(data, _mime(fmt))}}
    except Exception:
        logger.warning("VLM: could not read image source %r", s)
        return None


def build_vision_messages(prompt: str, images=None, system: str = "",
                          max_dim: int = 1024, allow_local_files: bool = True) -> list:
    """Build OpenAI vision `messages` (text + image blocks)."""
    content = [{"type": "text", "text": prompt}]
    for img in (images or []):
        block = encode_image_block(img, max_dim, allow_local_files=allow_local_files)
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
        self.client = client or httpx.AsyncClient(base_url=base_url, timeout=180.0)

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
                              max_tokens: int = 1024, temperature: float = 0.2,
                              allow_local_files: bool = True) -> str:
        messages = build_vision_messages(prompt, images, system, self.max_image_dim,
                                         allow_local_files=allow_local_files)
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
            return f"[VLM error: {e}]"

    async def generate(self, model: str, prompt: str, system: str = "",
                       max_tokens: int = 1024, temperature: float = 0.7) -> str:
        # Text-only path keeps the LLMBackend contract.
        return await self.generate_vision(model, prompt, images=[], system=system,
                                          max_tokens=max_tokens, temperature=temperature)
