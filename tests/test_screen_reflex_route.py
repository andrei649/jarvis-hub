"""DRA-06 — `POST /api/screen/reflex`, the HTTP half of the 0.65 screen reflex.

`agents/core/screen_reflex.py` had zero non-test importers: the capture-to-answer
core existed but nothing in the product could reach it. This route drives it with
screenshot BYTES supplied by the caller (a file pick, a paste, or
`getDisplayMedia` in the console) — never a filesystem path.

Non-negotiable, asserted below: a non-loopback VLM is refused with 503 BEFORE any
generation is attempted. Screen bytes can hold anything on the owner's display;
they must never leave the host.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.llm import vlm as vlm_mod
from agents.core.llm.vlm import VLMConfig, VLMNotConfigured
from agents.core.routers import multimodal

# A real 1×1 PNG — small enough that _downscale is a pass-through.
PNG = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
).decode("ascii")


def _local(**kw):
    return VLMConfig(
        backend=kw.get("backend", "custom"),
        base_url=kw.get("base_url", "http://localhost:1234/v1"),
        model=kw.get("model", "qwen2.5-vl"),
        api_key="",
        is_local=kw.get("is_local", True),
    )


def _stub_generation(monkeypatch, text, *, calls=None):
    async def _generate_vision(self, model, prompt, images=None, system="", **kw):
        if calls is not None:
            calls.append({"model": model, "prompt": prompt, "images": images, "system": system})
        return text

    monkeypatch.setattr(vlm_mod.VLMBackend, "generate_vision", _generate_vision)


def _body(**kw):
    return multimodal.ScreenReflexBody(image_base64=kw.pop("image_base64", PNG), **kw)


@pytest.mark.asyncio
async def test_reflex_answers_from_a_local_vlm(monkeypatch):
    monkeypatch.setattr(vlm_mod, "resolve_vlm_config", lambda *a, **k: _local())
    calls: list[dict] = []
    _stub_generation(monkeypatch, "A settings window is open.", calls=calls)

    resp = await multimodal.screen_reflex(_body(question="what is open?"))
    payload = json.loads(resp.body)

    assert resp.status_code == 200
    assert payload["ok"] is True and payload["generated"] is True
    assert payload["answer"] == "A settings window is open."
    assert payload["mode"] == "answer"
    assert payload["model"] == "qwen2.5-vl"
    # the real screenshot bytes reached the VLM, not a path or a data URI string
    assert calls and isinstance(calls[0]["images"][0], bytes)


@pytest.mark.asyncio
async def test_reflex_ground_mode_parses_elements(monkeypatch):
    monkeypatch.setattr(vlm_mod, "resolve_vlm_config", lambda *a, **k: _local())
    _stub_generation(monkeypatch, "Save at (12, 34)")

    resp = await multimodal.screen_reflex(_body(mode="ground"))
    payload = json.loads(resp.body)

    assert resp.status_code == 200
    # proves the ScreenReflex core (parse_grounding) is driven, not re-implemented
    assert payload["elements"] == [{"label": "Save", "x": 12, "y": 34, "source": "vlm"}]


@pytest.mark.asyncio
async def test_reflex_refuses_when_no_vlm_is_configured(monkeypatch):
    def _raise(*a, **k):
        raise VLMNotConfigured("vlm_disabled")

    monkeypatch.setattr(vlm_mod, "resolve_vlm_config", _raise)

    resp = await multimodal.screen_reflex(_body())
    payload = json.loads(resp.body)

    assert resp.status_code == 503
    assert payload["ok"] is False and payload["generated"] is False
    assert "vlm_disabled" in payload["reason"]
    assert "answer" not in payload  # never a fabricated description


@pytest.mark.asyncio
async def test_reflex_refuses_a_non_loopback_vlm_without_sending_the_screen(monkeypatch):
    monkeypatch.setattr(
        vlm_mod,
        "resolve_vlm_config",
        lambda *a, **k: _local(base_url="http://gpu-box.lan:8000/v1", is_local=False),
    )
    calls: list[dict] = []
    _stub_generation(monkeypatch, "should never run", calls=calls)

    resp = await multimodal.screen_reflex(_body(question="what is open?"))
    payload = json.loads(resp.body)

    assert resp.status_code == 503
    assert payload["ok"] is False and payload["generated"] is False
    assert "non-loopback" in payload["reason"]
    # THE point of the guard: the screen bytes never left the host.
    assert calls == []


@pytest.mark.asyncio
async def test_reflex_rejects_invalid_base64(monkeypatch):
    monkeypatch.setattr(vlm_mod, "resolve_vlm_config", lambda *a, **k: _local())
    resp = await multimodal.screen_reflex(_body(image_base64="!!!"))
    assert resp.status_code == 400
    assert json.loads(resp.body)["error"] == "image_base64 is not valid base64"


@pytest.mark.asyncio
async def test_reflex_reports_an_empty_model_answer_honestly(monkeypatch):
    monkeypatch.setattr(vlm_mod, "resolve_vlm_config", lambda *a, **k: _local())
    # "[VLM error]" is exactly what VLMBackend.generate_vision returns when the
    # local server is down — the reflex must report that as "not generated",
    # never render it as an answer.
    _stub_generation(monkeypatch, "[VLM error]")

    payload = json.loads((await multimodal.screen_reflex(_body())).body)
    assert payload["ok"] is False and payload["generated"] is False
    assert payload["reason"] == "VLM produced no answer"
    assert "answer" not in payload

    _stub_generation(monkeypatch, "   ")
    payload = json.loads((await multimodal.screen_reflex(_body())).body)
    assert payload["ok"] is False and payload["generated"] is False


def test_reflex_route_is_user_guarded():
    from agents.core.routers._deps import user_guard

    route = next(r for r in multimodal.router.routes if getattr(r, "path", "") == "/api/screen/reflex")
    assert "POST" in route.methods
    assert any(dep.call is user_guard for dep in route.dependant.dependencies)
