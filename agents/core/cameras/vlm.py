"""Strict-local, on-demand camera description adapter for already-masked frames."""

from __future__ import annotations

import inspect
import ipaddress
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .models import CameraEvent, MaskedFrame

_MAX_IMAGE_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_CHARS = 4096
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_FORBIDDEN_OUTPUT = re.compile(
    r"\b(?:biometric|face(?:[ _-]?id)?|identit(?:y|ies)|identified person|"
    r"license[ _-]?plate|plate[ _-]?(?:number|id)|person[ _-]?(?:id|name)|"
    r"sub[ _-]?label|named person)\b",
    re.IGNORECASE,
)
_LIKELY_PLATE = re.compile(r"\b(?=[A-Z0-9-]{4,12}\b)(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9-]+\b")
_LIKELY_NAME_START = re.compile(r"^[A-Z][a-z]{1,31}\b")
_SAFE_SENTENCE_STARTS = frozenset({"a", "an", "anonymous", "someone", "the"})


def _local_endpoint(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("local VLM endpoint must be text")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("local VLM endpoint is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("local VLM endpoint must use an exact HTTP origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("local VLM endpoint must not contain credentials, query, or fragment")
    if parsed.path.rstrip("/") not in {"", "/v1"}:
        raise ValueError("local VLM endpoint path must be /v1")
    host = parsed.hostname.lower()
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("local VLM endpoint must use localhost or a literal loopback IP") from exc
        if not address.is_loopback:
            raise ValueError("local VLM endpoint must stay on this host")
    netloc = parsed.hostname
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path.rstrip("/") or "/v1"
    return urlunsplit((parsed.scheme, netloc, path, "", ""))


@dataclass(frozen=True, slots=True)
class LocalCameraVLMConfig:
    """Default-off configuration for one exact local OpenAI-compatible VLM."""

    endpoint: str
    model: str
    enabled: bool = False
    max_image_bytes: int = _MAX_IMAGE_BYTES

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", _local_endpoint(self.endpoint))
        if not isinstance(self.model, str) or _MODEL_RE.fullmatch(self.model.strip()) is None:
            raise ValueError("local VLM model contains unsafe characters")
        object.__setattr__(self, "model", self.model.strip())
        if not isinstance(self.enabled, bool):
            raise ValueError("local VLM enabled must be a boolean")
        if isinstance(self.max_image_bytes, bool) or not isinstance(self.max_image_bytes, int):
            raise ValueError("local VLM image limit must be an integer")
        if not 1 <= self.max_image_bytes <= _MAX_IMAGE_BYTES:
            raise ValueError("local VLM image limit must be between 1 byte and 2 MiB")


class LocalCameraVLM:
    """Describe a masked PNG without retaining bytes or exposing backend failures."""

    def __init__(
        self,
        config: LocalCameraVLMConfig,
        *,
        generate: Callable[..., Awaitable[str] | str],
    ) -> None:
        if not isinstance(config, LocalCameraVLMConfig):
            raise ValueError("camera VLM config is required")
        if not callable(generate):
            raise ValueError("camera VLM generate callback must be callable")
        self._config = config
        self._generate = generate

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @classmethod
    def from_backend(cls, config: LocalCameraVLMConfig, backend: Any) -> LocalCameraVLM:
        if _local_endpoint(getattr(backend, "base_url", "")) != config.endpoint:
            raise ValueError("camera VLM backend endpoint does not match governed config")
        callback = getattr(backend, "generate_vision", None)
        if not callable(callback):
            raise ValueError("camera VLM backend must provide generate_vision")
        return cls(config, generate=callback)

    async def describe(self, frame: MaskedFrame, event: CameraEvent) -> str | None:
        if not self._config.enabled:
            return None
        if not isinstance(frame, MaskedFrame) or not isinstance(event, CameraEvent):
            return None
        if (
            frame.format.upper() != "PNG"
            or not isinstance(frame.data, bytes)
            or not frame.data
            or len(frame.data) > self._config.max_image_bytes
            or frame.width < 1
            or frame.height < 1
        ):
            return None
        prompt = (
            f"Describe only the visible {event.label} activity in one short sentence. "
            "Use anonymous terms. Never infer identity, face, biometrics, names, license plates, "
            "or protected traits. Return JSON with exactly one string field: description."
        )
        system = (
            "You are an offline household camera summarizer. The image is already privacy-masked. "
            "Do not identify any person or transcribe any plate."
        )
        try:
            response = self._generate(
                model=self._config.model,
                prompt=prompt,
                images=(frame.data,),
                system=system,
                max_tokens=160,
                temperature=0.0,
            )
            if inspect.isawaitable(response):
                response = await response
        except Exception:
            return None
        return _safe_description(response)


def _safe_description(response: Any) -> str | None:
    if not isinstance(response, str):
        return None
    text = response.strip()
    if not text or len(text) > _MAX_RESPONSE_CHARS or text.lower().startswith("[vlm error"):
        return None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict) or set(payload) != {"description"}:
            return None
        text = payload["description"]
        if not isinstance(text, str):
            return None
        text = text.strip()
    if not text or len(text) > 512 or _FORBIDDEN_OUTPUT.search(text):
        return None
    first_word = text.split(maxsplit=1)[0].lower().rstrip(".,:;!?")
    if _LIKELY_NAME_START.match(text) and first_word not in _SAFE_SENTENCE_STARTS:
        return None
    if _LIKELY_PLATE.search(text):
        return None
    if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
        return None
    return " ".join(text.split())


__all__ = ["LocalCameraVLM", "LocalCameraVLMConfig"]
