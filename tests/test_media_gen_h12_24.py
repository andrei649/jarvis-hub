"""H12.24 — Governed media generation. Offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.media_gen import MediaGenManager, KINDS


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append(dict(kind=kind, payload=payload, autonomy_level=autonomy_level))
        return len(self.calls)


def test_supports_and_kinds():
    assert set(KINDS) == {"image", "thumbnail", "video"}
    m = MediaGenManager()
    assert m.supports("image") and not m.supports("hologram")
    assert m.kinds() == {"image": False, "thumbnail": False, "video": False}


@pytest.mark.asyncio
async def test_unsupported_and_no_prompt():
    m = MediaGenManager()
    assert (await m.generate("hologram", "x"))["reason"] == "unsupported_kind"
    assert (await m.generate("image", ""))["reason"] == "no_prompt"


@pytest.mark.asyncio
async def test_local_backend_runs_inline():
    async def img(prompt, opts):
        return {"path": "/tmp/x.png", "prompt": prompt}

    m = MediaGenManager(backends={"image": img})
    out = await m.generate("image", "a cat")
    assert out["ok"] is True and out["result"]["path"] == "/tmp/x.png"
    assert m.available("image") is True


@pytest.mark.asyncio
async def test_cloud_generation_is_gated():
    q = _FakeQueue()
    m = MediaGenManager(enqueue=q.enqueue)
    out = await m.generate("video", "a sunset", cloud=True)
    assert out["ok"] is False and out["reason"] == "approval_required" and out["task_id"] == 1
    assert q.calls[0]["kind"] == "media.video" and q.calls[0]["autonomy_level"] == "ask"


@pytest.mark.asyncio
async def test_no_backend_unavailable():
    out = await MediaGenManager().generate("image", "x")
    assert out["reason"] == "backend_unavailable"
