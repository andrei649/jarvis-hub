"""H12.24 — Governed media generation. Offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.automation_contracts import ContractDecision
import agents.core.media_gen as media_gen
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

    m = MediaGenManager(
        backends={"image": img},
        local_guard=lambda kind, prompt, opts: (True, ""),
    )
    out = await m.generate("image", "a cat")
    assert out["ok"] is True and out["result"]["path"] == "/tmp/x.png"
    assert m.available("image") is True


@pytest.mark.asyncio
async def test_local_backend_requires_explicit_fail_closed_guard():
    calls = []

    async def img(prompt, opts):
        calls.append((prompt, opts))
        return {"path": "/tmp/must-not-run.png"}

    out = await MediaGenManager(backends={"image": img}).generate("image", "a cat")

    assert out == {"ok": False, "reason": "local_guard_unavailable", "kind": "image"}
    assert calls == []


@pytest.mark.asyncio
async def test_cloud_generation_is_gated():
    q = _FakeQueue()
    m = MediaGenManager(enqueue=q.enqueue)
    out = await m.generate("video", "a sunset", cloud=True)
    assert out["ok"] is False and out["reason"] == "approval_required" and out["task_id"] == 1
    assert q.calls[0]["kind"] == "media.video" and q.calls[0]["autonomy_level"] == "ask"


@pytest.mark.asyncio
async def test_cloud_generation_obeys_live_media_generation_contract(monkeypatch):
    q = _FakeQueue()

    class _Contract:
        def __init__(self):
            self.calls = []

        def evaluate(self, payload=None, **kwargs):
            self.calls.append((payload, kwargs))
            return ContractDecision(
                kind="media_generation",
                admissible=False,
                requires_approval=True,
                reason="contract_blocked",
            )

    contract = _Contract()
    monkeypatch.setattr(media_gen, "MEDIA_GENERATION_CONTRACT", contract, raising=False)
    m = MediaGenManager(enqueue=q.enqueue)

    out = await m.generate("image", "a cat in a space suit", cloud=True, opts={"size": "1024"})

    assert out == {"ok": False, "reason": "contract_blocked", "kind": "media.image"}
    assert q.calls == []
    assert contract.calls
    payload, kwargs = contract.calls[-1]
    assert payload["kind"] == "media.image"
    assert payload["media_kind"] == "image"
    assert payload["target"] == "image"
    assert payload["prompt_length"] == len("a cat in a space suit")
    assert payload["opts_keys"] == ["size"]
    assert kwargs.get("now") is not None


@pytest.mark.asyncio
async def test_no_backend_unavailable():
    out = await MediaGenManager().generate("image", "x")
    assert out["reason"] == "backend_unavailable"


# ── 0.46 catalog wiring (opt-in) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_local_gen_is_cataloged_when_attached(tmp_path):
    from agents.core.media_catalog import MediaCatalog

    async def img(prompt, opts):
        return {"path": "/tmp/cat.png", "prompt": prompt}

    cat = MediaCatalog(tmp_path / "c.json")
    m = MediaGenManager(
        backends={"image": img},
        catalog=cat,
        clock=lambda: 1234.0,
        local_guard=lambda kind, prompt, opts: (True, ""),
    )
    out = await m.generate("image", "a cat", opts={"tags": ["pet"]})

    assert out["ok"] is True and "catalog_id" in out
    rec = cat.get(out["catalog_id"])
    assert rec is not None
    assert rec["kind"] == "image" and rec["prompt"] == "a cat"
    assert rec["path"] == "/tmp/cat.png" and rec["created_at"] == 1234.0
    assert rec["tags"] == ["pet"] and rec["cloud"] is False


@pytest.mark.asyncio
async def test_no_catalog_means_no_recording_and_unchanged_output(tmp_path):
    async def img(prompt, opts):
        return {"path": "/tmp/x.png"}

    m = MediaGenManager(
        backends={"image": img},
        local_guard=lambda kind, prompt, opts: (True, ""),
    )  # no catalog attached
    out = await m.generate("image", "a cat")
    # default path is byte-identical: no catalog_id key added
    assert out == {"ok": True, "kind": "image", "result": {"path": "/tmp/x.png"}}


@pytest.mark.asyncio
async def test_cloud_and_failed_gen_are_not_cataloged(tmp_path):
    from agents.core.media_catalog import MediaCatalog

    async def boom(prompt, opts):
        raise RuntimeError("backend down")

    q = _FakeQueue()
    cat = MediaCatalog(tmp_path / "c.json")
    m = MediaGenManager(
        backends={"image": boom},
        enqueue=q.enqueue,
        catalog=cat,
        local_guard=lambda kind, prompt, opts: (True, ""),
    )
    # cloud → only enqueues an approval, produces no artifact
    assert (await m.generate("video", "x", cloud=True))["reason"] == "approval_required"
    # local backend that errors → no artifact
    assert (await m.generate("image", "x"))["reason"] == "generation_error"
    assert cat.stats()["total"] == 0   # nothing cataloged in either case


@pytest.mark.asyncio
async def test_catalog_failure_never_breaks_generation(tmp_path):
    async def img(prompt, opts):
        return {"path": "/tmp/x.png"}

    class _BrokenCatalog:
        def add(self, **kw):
            raise RuntimeError("disk full")

    m = MediaGenManager(
        backends={"image": img},
        catalog=_BrokenCatalog(),
        local_guard=lambda kind, prompt, opts: (True, ""),
    )
    out = await m.generate("image", "a cat")
    # generation still succeeds; the catalog hiccup is swallowed (no catalog_id)
    assert out["ok"] is True and "catalog_id" not in out
