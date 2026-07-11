"""0.65 One-Hotkey Screen-Capture Reflex — offline orchestration core.

Screenshot bytes (+ optional question) → local VLM → answer/elements. Reuses the H13.1 VLM
adapter + H15.2 grounding; bytes-only + size-capped + non-persistent; honest ok/generated.
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.screen_reflex import (  # noqa: E402
    DEFAULT_PROMPT,
    ScreenReflex,
    build_observation,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 4     # stand-in screenshot bytes


class _FakeVLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def __call__(self, prompt, images, system):
        self.calls.append((prompt, images, system))
        return self.reply


# ── build_observation (pure request spec) ─────────────────────────
def test_build_observation_answer_mode_embeds_text_and_image():
    spec = build_observation(PNG, "what app is this?", mode="answer")
    user = spec["messages"][-1]["content"]
    assert user[0] == {"type": "text", "text": "what app is this?"}
    assert user[1]["type"] == "image_url" and user[1]["image_url"]["url"].startswith("data:image")
    assert spec["system"] == ""          # answer mode has no system prompt


def test_build_observation_defaults_prompt_and_ground_mode_has_system():
    assert build_observation(PNG, "")["prompt"] == DEFAULT_PROMPT
    g = build_observation(PNG, "", mode="ground")
    assert g["system"] and "grounding" in g["system"].lower()


def test_build_observation_rejects_unknown_mode():
    with pytest.raises(ValueError):
        build_observation(PNG, "x", mode="teleport")


# ── observe: the reflex path ──────────────────────────────────────
async def test_answer_mode_returns_generated_answer():
    vlm = _FakeVLM("This is a code editor with a terminal open.")
    out = await ScreenReflex(vlm).observe(PNG, "what am I looking at?")
    assert out["ok"] is True and out["generated"] is True
    assert out["answer"].startswith("This is a code editor")
    assert out["question"] == "what am I looking at?" and out["mode"] == "answer"
    # the image bytes were handed to the VLM, exactly once
    assert len(vlm.calls) == 1 and vlm.calls[0][1] == [PNG]


async def test_no_question_uses_default_prompt():
    vlm = _FakeVLM("A desktop.")
    out = await ScreenReflex(vlm).observe(PNG)
    assert out["question"] == DEFAULT_PROMPT and vlm.calls[0][0] == DEFAULT_PROMPT


async def test_ground_mode_parses_elements_and_fuses_a11y():
    vlm = _FakeVLM("Submit at (120, 340)\nCancel at (200, 340)")
    a11y = [{"label": "Submit", "x": 121, "y": 339, "source": "a11y"}]
    out = await ScreenReflex(vlm).observe(PNG, mode="ground", a11y=a11y)
    assert out["ok"] is True and out["mode"] == "ground"
    labels = {e["label"] for e in out["elements"]}
    assert "Submit" in labels and "Cancel" in labels
    # the ground prompt/system were used, not the free-form default
    assert vlm.calls[0][2]                        # non-empty system


# ── honesty: never fabricates ─────────────────────────────────────
async def test_no_vlm_is_honestly_inert():
    out = await ScreenReflex(None).observe(PNG, "hi")
    assert out["ok"] is False and out["generated"] is False and "VLM" in out["reason"]


async def test_vlm_error_sentinel_is_not_an_answer():
    out = await ScreenReflex(_FakeVLM("[VLM error]")).observe(PNG)
    assert out["ok"] is False and out["generated"] is False


async def test_empty_reply_is_not_an_answer():
    out = await ScreenReflex(_FakeVLM("   ")).observe(PNG)
    assert out["ok"] is False and out["generated"] is False


# ── bounds + bytes-only (path-injection / oversize guards) ────────
async def test_rejects_non_bytes_and_empty_and_oversize():
    r = ScreenReflex(_FakeVLM("x"), max_image_bytes=32)
    assert (await r.observe("/etc/passwd"))["ok"] is False        # a path is not bytes
    assert (await r.observe(b""))["ok"] is False                  # empty
    over = await r.observe(b"y" * 64)                             # over the cap
    assert over["ok"] is False and "cap" in over["reason"]


async def test_unknown_mode_is_honest_not_raised_in_observe():
    out = await ScreenReflex(_FakeVLM("x")).observe(PNG, mode="teleport")
    assert out["ok"] is False and "mode" in out["reason"]


# ── from_backend adapts the real VLMBackend contract ──────────────
async def test_from_backend_drives_generate_vision():
    class _Backend:
        def __init__(self):
            self.seen = None

        async def generate_vision(self, model, prompt, images=None, system=""):
            self.seen = {"model": model, "prompt": prompt, "images": images}
            return "answer from backend"

    be = _Backend()
    out = await ScreenReflex.from_backend(be, model="qwen-vl").observe(PNG, "q?")
    assert out["ok"] is True and out["answer"] == "answer from backend"
    assert be.seen["model"] == "qwen-vl" and be.seen["images"] == [PNG]
