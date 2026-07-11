"""screen_reflex.py — 0.65 One-Hotkey Screen-Capture Reflex (offline orchestration core).

The reflex is the competitor's signature move: **one keypress → screenshot the current
screen → local VLM → answer, with no copy-paste**. Two seams are owner/host-gated — the
global hotkey (see 0.64 `quickbar.py`) and the actual screen grab (needs OS capture
permission + a desktop). This module is everything *between* them: it takes the captured
image **bytes** and drives the H13.1 VLM adapter to an answer, purely and offline-testably
via an injected VLM callable.

Design (capability-pack discipline):

* **Reuses, never reinvents** — the vision request is built with `vlm.build_vision_messages`
  and UI grounding is parsed with `screen_grounding.parse_grounding` / `fuse_with_a11y`.
* **Strict-local & non-persistent** — the image is held in memory and handed only to the
  injected VLM (the H13.1 adapter targets a localhost vision server). Nothing here writes the
  screenshot to disk or sends it to a remote host; a screen capture can hold anything on
  screen, so it must not leak.
* **Bytes only** — like `encode_image_block`, the reflex accepts in-memory bytes, never a
  filesystem path, so a caller-supplied value can't be turned into a host-file read.
* **Bounded** — the image is size-capped (a screenshot that large is a mistake, refused).
* **Honest** — no VLM wired, a refused image, or the adapter's ``[VLM error]`` sentinel comes
  back as ``{ok: False, generated: False, reason: …}``; an answer is only ever reported with
  ``generated: True`` when the model actually produced text. It never fabricates a description.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from agents.core.llm.vlm import build_vision_messages
from agents.core.screen_grounding import fuse_with_a11y, parse_grounding

# A concise, deterministic default so the reflex answers even with no typed question.
DEFAULT_PROMPT = "Describe what is on the screen. Be concise and specific."
# For the grounding mode: ask for the format `parse_grounding` understands.
_GROUND_SYSTEM = (
    "You are a UI grounding model. List the interactive on-screen elements, one per line, "
    "as `label at (x, y)` using pixel coordinates. Do not add commentary."
)
_GROUND_PROMPT = "List the interactive UI elements on this screen with their coordinates."

MODES: tuple[str, ...] = ("answer", "ground")

_DEFAULT_MODEL = "qwen2.5-vl"
_MAX_IMAGE_BYTES = 8 << 20          # 8 MB — a PNG screenshot is well under this
_VLM_ERROR_SENTINEL = "[VLM error]"

# An async callable: (prompt, images, system) -> model text.
VLMGenerate = Callable[..., Awaitable[str]]


def build_observation(image_bytes: bytes, question: str = "", *,
                      mode: str = "answer", max_dim: int = 1024) -> dict:
    """Pure request spec for a reflex observation — the vision ``messages`` + metadata.

    Split out so the request can be inspected/tested without a VLM. ``mode`` selects the
    prompt/system: ``answer`` (free-form Q&A) or ``ground`` (UI-element listing).
    """
    if mode not in MODES:
        raise ValueError(f"unknown reflex mode: {mode!r}")
    if mode == "ground":
        prompt, system = _GROUND_PROMPT, _GROUND_SYSTEM
    else:
        prompt, system = (question.strip() or DEFAULT_PROMPT), ""
    messages = build_vision_messages(prompt, images=[image_bytes], system=system, max_dim=max_dim)
    return {"messages": messages, "prompt": prompt, "system": system, "mode": mode}


class ScreenReflex:
    """Capture-to-answer orchestration over an injected (strict-local) VLM.

    ``vlm_generate`` is an async callable ``(prompt, images, system) -> str``; inject a fake
    in tests, or use :meth:`from_backend` to adapt a real ``VLMBackend``. With no VLM the
    reflex is honestly inert (``ok: False``) rather than fabricating an answer.
    """

    def __init__(self, vlm_generate: VLMGenerate | None = None, *,
                 model: str = _DEFAULT_MODEL, max_image_bytes: int = _MAX_IMAGE_BYTES,
                 max_dim: int = 1024) -> None:
        self._vlm = vlm_generate
        self.model = model
        self.max_image_bytes = int(max_image_bytes)
        self.max_dim = int(max_dim)

    @classmethod
    def from_backend(cls, backend, model: str = _DEFAULT_MODEL, **kw) -> ScreenReflex:
        """Adapt a real ``vlm.VLMBackend`` (or anything with ``generate_vision``)."""
        async def _gen(prompt, images, system):
            return await backend.generate_vision(model, prompt, images=images, system=system)
        return cls(_gen, model=model, **kw)

    def _reject_image(self, image_bytes) -> dict | None:
        if not isinstance(image_bytes, (bytes, bytearray)):
            return {"ok": False, "generated": False, "reason": "reflex needs screenshot bytes"}
        if not image_bytes:
            return {"ok": False, "generated": False, "reason": "empty screenshot"}
        if len(image_bytes) > self.max_image_bytes:
            return {"ok": False, "generated": False,
                    "reason": f"screenshot exceeds cap ({len(image_bytes)} > {self.max_image_bytes})"}
        return None

    async def observe(self, image_bytes: bytes, question: str = "", *,
                      mode: str = "answer", a11y: list | None = None) -> dict:
        """Run one reflex: screenshot bytes (+ optional question) → VLM → answer/elements.

        Never persists the image; sends it only to the injected VLM. Returns a dict with
        ``ok``/``generated`` set honestly.
        """
        if mode not in MODES:
            return {"ok": False, "generated": False, "reason": f"unknown mode: {mode}"}
        bad = self._reject_image(image_bytes)
        if bad is not None:
            return bad
        if self._vlm is None:
            return {"ok": False, "generated": False, "mode": mode,
                    "reason": "no local VLM configured (set JARVIS_VLM_URL)"}

        spec = build_observation(bytes(image_bytes), question, mode=mode, max_dim=self.max_dim)
        text = await self._vlm(spec["prompt"], [bytes(image_bytes)], spec["system"])
        text = (text or "").strip()
        if not text or text == _VLM_ERROR_SENTINEL:
            return {"ok": False, "generated": False, "mode": mode,
                    "reason": "VLM produced no answer", "model": self.model}

        out = {"ok": True, "generated": True, "mode": mode, "model": self.model,
               "answer": text, "question": (question.strip() or DEFAULT_PROMPT)}
        if mode == "ground":
            elements = parse_grounding(text)
            if a11y:
                elements = fuse_with_a11y(elements, a11y)
            out["elements"] = elements
        return out
