"""op-visual-grounding — LocalVLMLocator: gate-not-label, presets, a11y-first ordering. Offline."""

from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

import pytest

from agents.core.desktop_host import WindowsDesktopDriver
from agents.core.llm.vlm import VLM_PRESETS, VLMConfig
from agents.core.screen_locator import (
    PROVENANCE,
    REASON_NOT_LOCAL,
    LocalVLMLocator,
    build_local_vlm_locator,
)

SCREEN = b"png-bytes-of-a-screen"


class FakeVLM:
    """Records every prompt and image it receives; returns a fixed grounding text."""

    def __init__(self, text="Save at (12,24)\nCancel at (300, 40)"):
        self.text = text
        self.calls = []

    async def __call__(self, prompt, images, system):
        self.calls.append({"prompt": prompt, "images": list(images), "system": system})
        return self.text


def _config(*, is_local=True, preset="", convention="absolute", base="http://localhost:1234/v1"):
    return VLMConfig(
        backend="lmstudio", base_url=base, model="qwen3-vl-8b", api_key="",
        is_local=is_local, preset=preset, convention=convention,
    )


# ── the happy path and its audit trail ───────────────────────────────────────


async def test_fake_vlm_grounding_yields_a_point_with_screenshot_hash():
    vlm = FakeVLM()
    locator = LocalVLMLocator(_config(), vlm_generate=vlm)

    result = await locator(query="Save", screenshot=SCREEN)

    assert result["ok"] is True
    assert (result["x"], result["y"]) == (12, 24)
    assert result["label"] == "Save"
    assert result["provenance"] == PROVENANCE == "local_vlm"
    assert result["source"] == "local_vlm"
    assert result["screenshot_sha256"] == hashlib.sha256(SCREEN).hexdigest()
    assert result["preset"] == ""
    assert result["convention"] == "absolute"
    assert result["model"] == "qwen3-vl-8b"
    assert result["candidates"] == 2
    # The bytes went to the injected (local) VLM exactly once, unmodified.
    assert len(vlm.calls) == 1
    assert vlm.calls[0]["images"] == [SCREEN]
    assert locator.is_local is True
    assert locator.calls == 1


async def test_query_miss_is_an_honest_not_found():
    locator = LocalVLMLocator(_config(), vlm_generate=FakeVLM())
    result = await locator(query="Submit", screenshot=SCREEN)
    assert result["ok"] is False
    assert result["reason"] == "not_found"
    assert result["candidates"] == 2
    assert result["screenshot_sha256"] == hashlib.sha256(SCREEN).hexdigest()


async def test_vlm_error_sentinel_and_empty_answer_refuse_without_inventing():
    for text in ("", "[VLM error]", "   "):
        locator = LocalVLMLocator(_config(), vlm_generate=FakeVLM(text))
        result = await locator(query="Save", screenshot=SCREEN)
        assert result == {
            "ok": False, "reason": "vlm_no_answer", "provenance": "local_vlm",
            "screenshot_sha256": hashlib.sha256(SCREEN).hexdigest(),
        }


async def test_vlm_exception_is_redacted_to_a_stable_reason():
    async def _boom(prompt, images, system):
        raise RuntimeError("socket detail that must not leak")

    locator = LocalVLMLocator(_config(), vlm_generate=_boom)
    result = await locator(query="Save", screenshot=SCREEN)
    assert result["ok"] is False
    assert result["reason"] == "local_vlm_failed"
    assert "socket" not in repr(result)


# ── the gate ─────────────────────────────────────────────────────────────────


async def test_non_loopback_config_refuses_before_any_bytes_leave():
    vlm = FakeVLM()
    locator = LocalVLMLocator(
        _config(is_local=False, base="http://gpu-box.lan:8000/v1"), vlm_generate=vlm
    )

    assert locator.is_local is False
    result = await locator(query="Save", screenshot=SCREEN)

    assert result == {"ok": False, "reason": REASON_NOT_LOCAL, "provenance": "local_vlm"}
    assert vlm.calls == []          # the fake VLM never received the screenshot
    assert locator.calls == 0
    assert "screenshot_sha256" not in result  # nothing was even hashed for a remote


async def test_is_local_is_derived_from_config_and_nothing_else():
    """A locator built from a remote config cannot be talked into locality by
    provenance strings alone: the driver's _is_proven_local also refuses it."""
    locator = LocalVLMLocator(_config(is_local=False), vlm_generate=FakeVLM())
    assert locator.provenance == "local_vlm"
    assert WindowsDesktopDriver._is_proven_local(locator) is False
    local = LocalVLMLocator(_config(is_local=True), vlm_generate=FakeVLM())
    assert WindowsDesktopDriver._is_proven_local(local) is True


async def test_remote_locator_never_constructs_a_backend(monkeypatch):
    """Production path (no injected generator): the gate precedes VLMBackend()."""
    import agents.core.llm.vlm as vlm_mod

    def _never(*_a, **_k):
        raise AssertionError("VLMBackend constructed for a non-local config")

    monkeypatch.setattr(vlm_mod, "VLMBackend", _never)
    locator = LocalVLMLocator(_config(is_local=False))
    result = await locator(query="Save", screenshot=SCREEN)
    assert result["reason"] == REASON_NOT_LOCAL


async def test_production_backend_is_built_per_call_and_closed(monkeypatch):
    import agents.core.llm.vlm as vlm_mod

    events = []

    class _Backend:
        def __init__(self, *, base_url, api_key, max_image_dim):
            events.append(("open", base_url, max_image_dim))

        async def generate_vision(self, model, prompt, images=None, system="", **kw):
            events.append(("generate", model, len(images or [])))
            return "Save at (5, 6)"

        async def aclose(self):
            events.append(("close",))

    monkeypatch.setattr(vlm_mod, "VLMBackend", _Backend)
    locator = LocalVLMLocator(_config(), max_dim=800)
    result = await locator(query="save", screenshot=SCREEN)
    assert result["ok"] is True and (result["x"], result["y"]) == (5, 6)
    assert events == [
        ("open", "http://localhost:1234/v1", 800),
        ("generate", "qwen3-vl-8b", 1),
        ("close",),
    ]


# ── bounds ───────────────────────────────────────────────────────────────────


async def test_input_bounds_refuse_before_the_vlm_is_called():
    vlm = FakeVLM()
    locator = LocalVLMLocator(_config(), vlm_generate=vlm, max_image_bytes=8)

    assert (await locator(query="", screenshot=SCREEN))["reason"] == "query_required"
    assert (await locator(query="Save", screenshot=b""))["reason"] == "screenshot_required"
    assert (await locator(query="Save", screenshot="not-bytes"))["reason"] == "screenshot_required"
    assert (await locator(query="Save", screenshot=b"x" * 9))["reason"] == "screenshot_too_large"
    assert vlm.calls == []


def test_constructor_validates_its_inputs():
    with pytest.raises(TypeError):
        LocalVLMLocator({"is_local": True})
    with pytest.raises(TypeError):
        LocalVLMLocator(_config(), preset="ui-tars-1.5-7b")
    with pytest.raises(ValueError):
        LocalVLMLocator(_config(), max_image_bytes=0)
    with pytest.raises(ValueError):
        LocalVLMLocator(_config(), max_dim=True)


# ── presets: each convention round-trips to absolute pixels ──────────────────


@pytest.mark.parametrize("preset_id", sorted(VLM_PRESETS))
async def test_each_preset_convention_round_trips_to_original_pixels(preset_id):
    preset = VLM_PRESETS[preset_id]
    image_size = (2000, 1000)       # original screenshot
    target = (1000, 250)            # where "Save" truly is, in original pixels
    max_dim = 1000                  # model sees 1000×500

    if preset.convention == "relative_1000":
        emitted = (500, 250)
    elif preset.convention == "absolute_resized":
        emitted = (500, 125)
    elif preset.convention == "relative_unit":
        emitted = (0.5, 0.25)
    else:
        emitted = target
    vlm = FakeVLM(f"Save at ({emitted[0]}, {emitted[1]})")
    locator = LocalVLMLocator(
        _config(), vlm_generate=vlm, preset=preset,
        image_size_reader=lambda _b: image_size, max_dim=max_dim,
    )

    result = await locator(query="save", screenshot=SCREEN)

    assert result["ok"] is True, result
    assert (result["x"], result["y"]) == target
    assert result["preset"] == preset_id
    assert result["convention"] == preset.convention
    assert (result["image_width"], result["image_height"]) == image_size
    assert preset.license == "Apache-2.0"
    # The preset's prompt hint reaches the model so it answers in its convention.
    assert preset.prompt_hint in vlm.calls[0]["prompt"]


async def test_preset_from_config_is_honoured_without_an_explicit_preset():
    vlm = FakeVLM("Save at (500, 250)")
    locator = LocalVLMLocator(
        _config(preset="qwen3-vl-8b", convention="relative_1000"), vlm_generate=vlm,
        image_size_reader=lambda _b: (2000, 1000),
    )
    result = await locator(query="Save", screenshot=SCREEN)
    assert (result["x"], result["y"]) == (1000, 250)
    assert result["preset"] == "qwen3-vl-8b"
    assert VLM_PRESETS["qwen3-vl-8b"].prompt_hint in vlm.calls[0]["prompt"]


async def test_relative_convention_without_image_size_refuses_instead_of_guessing():
    locator = LocalVLMLocator(
        _config(), vlm_generate=FakeVLM(), preset=VLM_PRESETS["qwen3-vl-4b"],
        image_size_reader=lambda _b: None,
    )
    result = await locator(query="Save", screenshot=SCREEN)
    assert result["ok"] is False
    assert result["reason"] == "image_size_unavailable"


async def test_absolute_convention_needs_no_image_decoder():
    """The default (no preset) path must work on opaque bytes without Pillow."""
    def _never(_b):
        raise AssertionError("image size read for an absolute grounder")

    locator = LocalVLMLocator(_config(), vlm_generate=FakeVLM(), image_size_reader=_never)
    result = await locator(query="Save", screenshot=SCREEN)
    assert result["ok"] is True


# ── the driver seam: a11y first, then the local VLM ──────────────────────────


class _A11yBackend:
    def __init__(self, elements):
        self.elements = list(elements)
        self.snapshots = 0

    async def accessibility_elements(self):
        self.snapshots += 1
        return self.elements

    async def close(self):
        pass


def _driver(elements, locator, *, screenshots):
    def _shot():
        screenshots.append(1)
        return SCREEN

    return WindowsDesktopDriver(
        host_enabled=True, isolated=True,
        backend_factory=lambda: _A11yBackend(elements),
        screenshotter=_shot,
        local_vlm_locator=locator,
    )


async def test_driver_uses_accessibility_before_the_local_vlm():
    vlm = FakeVLM()
    locator = LocalVLMLocator(_config(), vlm_generate=vlm)
    shots: list = []
    driver = _driver([{"name": "Save", "role": "Button"}], locator, screenshots=shots)

    result = await driver.perform("locate", {"query": "Save"})

    assert result["ok"] is True
    assert result["source"] == "accessibility"
    assert vlm.calls == [] and shots == []   # no screenshot, no VLM when a11y hits


async def test_driver_falls_back_to_local_vlm_only_after_an_a11y_miss():
    vlm = FakeVLM()
    locator = LocalVLMLocator(_config(), vlm_generate=vlm)
    shots: list = []
    driver = _driver([{"name": "Title", "role": "Edit"}], locator, screenshots=shots)

    result = await driver.perform("locate", {"query": "Save"})

    assert result["ok"] is True
    assert result["source"] == "local_vlm"
    assert result["provenance"] == "local"
    element = result["element"]
    assert (element["x"], element["y"]) == (12, 24)
    assert element["provenance"] == "local_vlm"
    assert element["screenshot_sha256"] == hashlib.sha256(SCREEN).hexdigest()
    assert len(shots) == 1 and vlm.calls[0]["images"] == [SCREEN]


async def test_driver_refuses_a_remote_locator_before_taking_a_screenshot():
    vlm = FakeVLM()
    locator = LocalVLMLocator(_config(is_local=False), vlm_generate=vlm)
    shots: list = []
    driver = _driver([], locator, screenshots=shots)

    result = await driver.perform("locate", {"query": "Save"})

    assert result == {"ok": False, "reason": "local_vlm_not_proven_local"}
    assert shots == [] and vlm.calls == []


# ── the factory binding ──────────────────────────────────────────────────────


def test_build_returns_none_when_no_vlm_is_configured():
    assert build_local_vlm_locator(env={}) is None
    assert build_local_vlm_locator(env={"JARVIS_VLM_BACKEND": "off"}) is None
    assert build_local_vlm_locator(env={"JARVIS_VLM_BACKEND": "lmstudio"}) is None  # model unset


def test_build_binds_local_config_and_marks_remote_config_not_local():
    local = build_local_vlm_locator(env={
        "JARVIS_VLM_BACKEND": "lmstudio", "JARVIS_VLM_MODEL": "ui-tars-1.5-7b",
        "JARVIS_VLM_PRESET": "ui-tars-1.5-7b",
    })
    assert isinstance(local, LocalVLMLocator)
    assert local.is_local is True
    assert local.preset_id == "ui-tars-1.5-7b"
    assert local.convention == "absolute_resized"
    assert WindowsDesktopDriver._is_proven_local(local) is True

    remote = build_local_vlm_locator(env={
        "JARVIS_VLM_BACKEND": "custom", "JARVIS_VLM_URL": "http://gpu-box.lan:8000/v1",
    })
    assert isinstance(remote, LocalVLMLocator)
    assert remote.is_local is False
    assert WindowsDesktopDriver._is_proven_local(remote) is False
