"""screen_locator.py — visual grounding fallback for the desktop drivers (rank 3, strictly local).

The desktop drivers resolve a target by accessibility name first; when the a11y
tree has no match they hand ``(query, screenshot)`` to an injected locator
(``desktop_host.WindowsDesktopDriver._locate_with_local_vlm``). Before this
module nothing ever bound that seam in production, so the visual route was a
docstring. ``LocalVLMLocator`` is the binding:

* ``ScreenReflex(mode="ground")`` asks the resolved VLM for ``label at (x, y)``
  lines, ``screen_grounding.normalize_coords`` converts the model's coordinate
  convention (from the ``JARVIS_VLM_PRESET`` table) to absolute pixels on the
  original screenshot, ``screen_grounding.locate`` picks the element.
* **Gate, not label.** ``is_local`` is ``True`` only when
  ``resolve_vlm_config().is_local`` is; ``__call__`` re-checks it and refuses
  ``local_vlm_not_proven_local`` *before* the backend is even constructed, so a
  non-loopback VLM never receives a single screenshot byte. The driver applies
  the same test on its side (``_is_proven_local``) — two independent gates.
* **Auditable.** Every result carries ``screenshot_sha256``, the preset, the
  emitted and normalized coordinates and ``provenance: "local_vlm"`` — the
  desktop step contract requires exactly that provenance for coordinate clicks,
  and the kernel kind stays ``desktop.step`` (nothing new to authorize).
* **Bounded.** Screenshot bytes are size-capped and never persisted; the VLM
  backend is opened per call and closed in ``finally``.

The module never actuates: it returns a point; the click still crosses
``GovernedDesktop`` → ``DesktopActionExecutor`` → the Action Kernel.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import io
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from agents.core.llm.vlm import VLMConfig, VLMNotConfigured, VLMPreset, resolve_vlm_config
from agents.core.screen_grounding import (
    CONVENTION_ABSOLUTE,
    CONVENTION_ABSOLUTE_RESIZED,
    CONVENTIONS,
    locate,
    normalize_coords,
    resized_dims,
)
from agents.core.screen_reflex import ScreenReflex

logger = logging.getLogger("jarvis.screen_locator")

PROVENANCE = "local_vlm"
REASON_NOT_LOCAL = "local_vlm_not_proven_local"
_MAX_IMAGE_BYTES = 8 << 20
_MAX_QUERY_CHARS = 512

# An async callable ``(prompt, images, system) -> str`` (the ScreenReflex seam).
VLMGenerate = Callable[..., Awaitable[str]]
# ``(png_bytes) -> (width, height)``; injectable so tests need no Pillow.
ImageSizeReader = Callable[[bytes], Any]


def _read_image_size(image_bytes: bytes) -> tuple[int, int] | None:
    """Best-effort ``(width, height)`` via Pillow; ``None`` when unavailable."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return int(width), int(height)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class LocalVLMLocator:
    """``(query=, screenshot=)`` → located point, over a proven-local VLM only.

    ``config`` is the resolved ``VLMConfig``; ``is_local`` is derived from it and
    from nothing else. ``vlm_generate`` injects the model call (tests); in
    production the OpenAI-vision backend is built from ``config`` per call.
    ``preset`` overrides the config's preset (tests / explicit callers).
    """

    provenance = PROVENANCE

    def __init__(
        self,
        config: VLMConfig,
        *,
        vlm_generate: VLMGenerate | None = None,
        preset: VLMPreset | None = None,
        image_size_reader: ImageSizeReader | None = None,
        max_image_bytes: int = _MAX_IMAGE_BYTES,
        max_dim: int = 1024,
    ) -> None:
        if not isinstance(config, VLMConfig):
            raise TypeError("config must be a VLMConfig")
        if preset is not None and not isinstance(preset, VLMPreset):
            raise TypeError("preset must be a VLMPreset")
        if type(max_image_bytes) is not int or max_image_bytes <= 0:
            raise ValueError("max_image_bytes must be a positive integer")
        if type(max_dim) is not int or max_dim <= 0:
            raise ValueError("max_dim must be a positive integer")
        self.config = config
        # The GATE: only a loopback base can make this True, and only here.
        self.is_local: bool = config.is_local is True
        self.preset_id: str = preset.id if preset is not None else (config.preset or "")
        self.convention: str = preset.convention if preset is not None else config.convention
        if self.convention not in CONVENTIONS:
            raise ValueError(f"unknown coordinate convention: {self.convention!r}")
        self.prompt_hint: str = preset.prompt_hint if preset is not None else ""
        if preset is None and config.preset:
            from agents.core.llm.vlm import VLM_PRESETS

            known = VLM_PRESETS.get(config.preset)
            self.prompt_hint = known.prompt_hint if known is not None else ""
        self._vlm_generate = vlm_generate
        self._image_size_reader = image_size_reader or _read_image_size
        self.max_image_bytes = max_image_bytes
        self.max_dim = max_dim
        self.calls = 0

    # ── the locator protocol the desktop drivers consume ──────────────────────

    async def __call__(self, *, query: str, screenshot: bytes) -> dict:
        """Locate ``query`` on ``screenshot``; never raises, never leaks bytes remotely."""
        if not self.is_local:
            return {"ok": False, "reason": REASON_NOT_LOCAL, "provenance": PROVENANCE}
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "reason": "query_required", "provenance": PROVENANCE}
        query = query.strip()[:_MAX_QUERY_CHARS]
        if not isinstance(screenshot, (bytes, bytearray, memoryview)) or not screenshot:
            return {"ok": False, "reason": "screenshot_required", "provenance": PROVENANCE}
        image = bytes(screenshot)
        if len(image) > self.max_image_bytes:
            return {"ok": False, "reason": "screenshot_too_large", "provenance": PROVENANCE}
        digest = hashlib.sha256(image).hexdigest()

        image_size = None
        if self.convention != CONVENTION_ABSOLUTE:
            image_size = await self._image_size(image)
            if image_size is None:
                return self._refuse("image_size_unavailable", digest)

        self.calls += 1
        generate, close = await self._generation()
        try:
            reflex = ScreenReflex(
                generate,
                model=self.config.model,
                max_image_bytes=self.max_image_bytes,
                max_dim=self.max_dim,
            )
            observed = await reflex.observe(image, mode="ground")
        except Exception:
            logger.warning("local VLM locator failed (detail withheld)")
            return self._refuse("local_vlm_failed", digest)
        finally:
            if close is not None:
                with contextlib.suppress(Exception):  # best-effort release
                    await _maybe_await(close())

        if not observed.get("ok") or not observed.get("generated"):
            return self._refuse("vlm_no_answer", digest)
        elements = list(observed.get("elements") or [])
        if not elements:
            return self._refuse("not_found", digest)

        if self.convention != CONVENTION_ABSOLUTE:
            resized = None
            if self.convention == CONVENTION_ABSOLUTE_RESIZED:
                resized = resized_dims(image_size, self.max_dim)
            elements = normalize_coords(
                elements, convention=self.convention,
                image_size=image_size, resized_size=resized,
            )
        match = locate(elements, query)
        if match is None:
            return self._refuse("not_found", digest, candidates=len(elements))
        result = {
            "ok": True,
            "x": int(match["x"]),
            "y": int(match["y"]),
            "label": str(match.get("label", ""))[:_MAX_QUERY_CHARS],
            "source": PROVENANCE,
            "provenance": PROVENANCE,
            "screenshot_sha256": digest,
            "preset": self.preset_id,
            "convention": self.convention,
            "model": self.config.model,
            "candidates": len(elements),
        }
        if image_size is not None:
            result["image_width"], result["image_height"] = image_size
        return result

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _refuse(reason: str, digest: str, **extra: Any) -> dict:
        out = {"ok": False, "reason": reason, "provenance": PROVENANCE,
               "screenshot_sha256": digest}
        out.update(extra)
        return out

    async def _image_size(self, image: bytes) -> tuple[int, int] | None:
        try:
            size = await _maybe_await(self._image_size_reader(image))
        except Exception:
            return None
        if not size:
            return None
        try:
            width, height = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError):
            return None
        if width <= 0 or height <= 0:
            return None
        return width, height

    async def _generation(self) -> tuple[VLMGenerate, Callable[[], Any] | None]:
        """The injected generator, or a per-call backend built from ``config``.

        Reached only after the ``is_local`` gate: constructing the backend is the
        first step that could open a socket, so it must stay behind the refusal.
        """
        hint = self.prompt_hint

        if self._vlm_generate is not None:
            inner = self._vlm_generate

            async def _injected(prompt, images, system):
                return await inner(_with_hint(prompt, hint), images, system)

            return _injected, None

        from agents.core.llm.vlm import VLMBackend

        backend = VLMBackend(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            max_image_dim=self.max_dim,
        )
        model = self.config.model

        async def _generate(prompt, images, system):
            return await backend.generate_vision(
                model, _with_hint(prompt, hint), images=images, system=system,
            )

        return _generate, backend.aclose


def _with_hint(prompt: str, hint: str) -> str:
    return f"{prompt}\n{hint}" if hint else prompt


def build_local_vlm_locator(env: Mapping[str, str] | None = None, **kwargs) -> LocalVLMLocator | None:
    """Bind a locator to the resolved VLM, or ``None`` when no VLM is configured.

    Used by the desktop driver factory: ``None`` keeps the driver's honest
    ``not_found`` path; a configured-but-remote VLM yields a locator whose
    ``is_local`` is ``False``, which both the locator and the driver refuse.
    Extra keyword arguments reach :class:`LocalVLMLocator`.
    """
    try:
        config = resolve_vlm_config(env)
    except VLMNotConfigured as exc:
        logger.info("local VLM locator not bound: %s", exc.reason)
        return None
    return LocalVLMLocator(config, **kwargs)


__all__ = [
    "PROVENANCE",
    "REASON_NOT_LOCAL",
    "LocalVLMLocator",
    "build_local_vlm_locator",
]
