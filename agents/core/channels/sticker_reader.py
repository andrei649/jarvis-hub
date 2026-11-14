"""Static WebP sticker validation and transient, policy-checked caption reuse."""

from __future__ import annotations

import asyncio
import io
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .media_reader import (
    REASON_DOWNLOAD,
    REASON_EMPTY,
    REASON_FAILED,
    REASON_NO_VLM,
    REASON_NOT_LOCAL,
    REASON_POLICY,
    REASON_TOO_LARGE,
    Description,
)

MAX_STICKER_EDGE = 512
MAX_CACHE_ENTRIES = 256
VALIDATION_TIMEOUT_S = 3.0
REASON_INVALID = "sticker_invalid_webp"
REASON_ADMISSION = "sticker_sender_not_admitted"


@dataclass(frozen=True)
class _Cached:
    description: Description
    actual_bytes: int


def _valid_static_webp(data: bytes) -> bool:
    """Validate decoded pixels before VLM's permissive image encoding fallback."""
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if (image.format != "WEBP" or getattr(image, "n_frames", 1) != 1
                    or not 0 < width <= MAX_STICKER_EDGE
                    or not 0 < height <= MAX_STICKER_EDGE):
                return False
            image.load()
        return True
    except Exception:
        return False


class StickerCaptioner:
    """One bounded in-memory LRU per adapter, with concurrent duplicate coalescing."""

    def __init__(self, *, max_entries: int = MAX_CACHE_ENTRIES):
        if type(max_entries) is not int or not 1 <= max_entries <= MAX_CACHE_ENTRIES:
            raise ValueError("max_entries must be between 1 and 256")
        self._max_entries = max_entries
        self._cache: OrderedDict[tuple, _Cached] = OrderedDict()
        self._inflight: dict[tuple, asyncio.Future[tuple[Description, int]]] = {}
        self._identity: tuple | None = None
        self._generation = 0

    def clear(self) -> None:
        self._generation += 1
        self._cache.clear()
        self._inflight.clear()
        self._identity = None

    @staticmethod
    def _admitted(reader: Any, allowed: Callable[[], bool]) -> Description | None:
        try:
            if allowed() is not True:
                return Description(False, reason=REASON_ADMISSION)
            refused = reader.refusal()
            if refused is not None:
                return refused
        except Exception:
            return Description(False, reason=REASON_POLICY)
        return None

    async def describe(self, attachment, *, reader: Any, download: Callable,
                       allowed: Callable[[], bool]) -> Description:
        refused = self._admitted(reader, allowed)
        if refused is not None:
            return refused
        try:
            cap = reader.max_bytes
            identity = reader.cache_identity()
            if type(cap) is not int or cap <= 0:
                return Description(False, reason=REASON_POLICY)
            if identity is not None and type(identity) is not tuple:
                identity = None
        except Exception:
            return Description(False, reason=REASON_POLICY)
        if identity != self._identity:
            self._cache.clear()
            self._identity = identity
        if attachment.size > cap:
            return Description(False, reason=REASON_TOO_LARGE)
        unique = attachment.file_unique_id
        key = (unique, identity) if unique and identity is not None else None
        generation = self._generation
        if key is not None:
            cached = self._cache.get(key)
            if cached is not None:
                if cached.actual_bytes > cap:
                    return Description(False, reason=REASON_TOO_LARGE)
                self._cache.move_to_end(key)
                return self._return_if_admitted(cached.description, reader, allowed, identity,
                                                cached.actual_bytes)
            pending = self._inflight.get(key)
            if pending is not None:
                result, actual_bytes = await asyncio.shield(pending)
                if generation != self._generation:
                    return Description(False, reason=REASON_POLICY)
                return self._return_if_admitted(result, reader, allowed, identity, actual_bytes)
        future = asyncio.get_running_loop().create_future() if key is not None else None
        if key is not None:
            self._inflight[key] = future
        result = Description(False, reason=REASON_FAILED)
        actual_bytes = 0
        try:
            try:
                data = await download(attachment.file_id, cap)
            except Exception:
                result = Description(False, reason=REASON_DOWNLOAD)
            else:
                if type(data) is not bytes or not data:
                    result = Description(False, reason=REASON_DOWNLOAD)
                elif len(data) > cap:
                    result = Description(False, reason=REASON_TOO_LARGE)
                else:
                    actual_bytes = len(data)
                    try:
                        valid = await asyncio.wait_for(asyncio.to_thread(_valid_static_webp, data),
                                                       timeout=VALIDATION_TIMEOUT_S)
                    except Exception:
                        valid = False
                    if not valid:
                        result = Description(False, reason=REASON_INVALID)
                    elif generation != self._generation:
                        result = Description(False, reason=REASON_POLICY)
                    elif actual_bytes > self._current_cap(reader):
                        result = Description(False, reason=REASON_TOO_LARGE)
                    elif self._admitted(reader, allowed) is None:
                        try:
                            result = await reader.describe_sticker(data)
                        except Exception:
                            result = Description(False, reason=REASON_FAILED)
                    else:
                        result = Description(False, reason=REASON_POLICY)
            result = self._return_if_admitted(result, reader, allowed, identity, actual_bytes)
            if generation != self._generation:
                result = Description(False, reason=REASON_POLICY)
            if (key is not None and result.ok and generation == self._generation
                    and self._identity == identity):
                self._cache[key] = _Cached(result, actual_bytes)
                self._cache.move_to_end(key)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)
            return result
        finally:
            if future is not None:
                if not future.done():
                    future.set_result((result, actual_bytes))
                if self._inflight.get(key) is future:
                    self._inflight.pop(key, None)

    def _return_if_admitted(self, result: Description, reader: Any,
                            allowed: Callable[[], bool], identity: tuple | None,
                            actual_bytes: int) -> Description:
        refused = self._admitted(reader, allowed)
        if refused is not None:
            return refused
        try:
            if actual_bytes > self._current_cap(reader):
                return Description(False, reason=REASON_TOO_LARGE)
            if reader.cache_identity() != identity:
                return Description(False, reason=REASON_POLICY)
        except Exception:
            return Description(False, reason=REASON_POLICY)
        return result

    @staticmethod
    def _current_cap(reader: Any) -> int:
        try:
            value = reader.max_bytes
            return value if type(value) is int and value > 0 else 0
        except Exception:
            return 0


_NOTES = {
    REASON_ADMISSION: "the sender is not paired",
    REASON_INVALID: "its image data is not a valid static WebP sticker",
    REASON_POLICY: "the local vision model is not approved for stickers",
    REASON_NO_VLM: "no local vision model is configured here yet",
    REASON_NOT_LOCAL: "the configured vision model is not local",
    REASON_EMPTY: "its download was empty",
    REASON_TOO_LARGE: "it exceeds the inbound image limit",
    REASON_FAILED: "the local vision model did not answer",
    REASON_DOWNLOAD: "it could not be downloaded",
}


def note(description: Description) -> str:
    return _NOTES.get(description.reason, "it could not be read")


def turn_text(description: Description, caption: str = "") -> str:
    if not description.ok:
        return caption.strip() if isinstance(caption, str) else ""
    asked = caption.strip() if isinstance(caption, str) else ""
    lead = asked or "What does this sticker show?"
    return (f"{lead}\n\nA local vision model described this sticker. "
            "It is a machine description, not something you observed:\n"
            f"{description.text}")
