"""H21.0 — Cognition skeleton: facade (master-OFF no-op), TurnContext, store."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import asyncio
import pytest

from agents.core.cognition import CognitionFacade, TurnContext, KeyedStore


def _facade(flags=None):
    flags = flags or {}
    return CognitionFacade(get_setting=lambda k, d=None: flags.get(k, d))


# ── facade ────────────────────────────────────────────────────────────────────

def test_master_off_is_no_op():
    f = _facade()                      # nothing configured → all OFF
    assert f.enabled() is False
    st = f.status()
    assert st["enabled"] is False and st["available"] is True
    assert all(v is False for v in st["flags"].values())
    assert st["modules"] == []


def test_sub_flag_requires_master():
    f = _facade({"cognition.honesty_enabled": True})  # sub on, master off
    assert f.sub_enabled("honesty_enabled") is False
    assert f.status()["flags"]["honesty_enabled"] is False


def test_sub_flag_on_with_master():
    f = _facade({"cognition.enabled": True, "cognition.affect_enabled": True})
    assert f.enabled() is True
    assert f.sub_enabled("affect_enabled") is True
    assert f.sub_enabled("memory_enabled") is False
    assert f.status()["flags"]["affect_enabled"] is True


# ── turn context ──────────────────────────────────────────────────────────────

def test_turn_context_scratch():
    ctx = TurnContext(session_id="s1", agent="jarvis", user="andrei")
    ctx.set("k", 1)
    assert ctx.get("k") == 1 and ctx.get("missing", "d") == "d"
    assert ctx.snapshot()["session_id"] == "s1"


def test_turn_context_current_and_bind():
    assert TurnContext.current() is None
    ctx = TurnContext(session_id="s1")
    with TurnContext.bind(ctx):
        assert TurnContext.current() is ctx
    assert TurnContext.current() is None   # reset after block


@pytest.mark.asyncio
async def test_turn_context_is_isolated_across_tasks():
    seen = {}

    async def worker(name):
        ctx = TurnContext(session_id=name)
        with TurnContext.bind(ctx):
            await asyncio.sleep(0.01)      # yield — would clobber if shared
            seen[name] = TurnContext.current().session_id

    await asyncio.gather(worker("a"), worker("b"), worker("c"))
    assert seen == {"a": "a", "b": "b", "c": "c"}


# ── keyed store ───────────────────────────────────────────────────────────────

def test_keyed_store_roundtrip_and_persist(tmp_path):
    path = str(tmp_path / "cog.json")
    s = KeyedStore(path)
    k = KeyedStore.key("jarvis", "andrei")
    s.put(k, {"mood": 0.5})
    assert s.get(k) == {"mood": 0.5}
    assert k in s.keys()
    # survives a reload
    assert KeyedStore(path).get(k) == {"mood": 0.5}
    assert s.delete(k) is True and s.get(k) is None


# ── api router ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_endpoint_reads_facade(monkeypatch):
    import agents.web as web
    from agents.core.cognition.api import cognition_status

    class _Orch:
        cognition = _facade()

    monkeypatch.setattr(web, "orch", _Orch(), raising=False)
    out = await cognition_status()
    assert out["enabled"] is False and out["available"] is True


@pytest.mark.asyncio
async def test_status_endpoint_without_orch(monkeypatch):
    import agents.web as web
    from agents.core.cognition.api import cognition_status
    monkeypatch.setattr(web, "orch", None, raising=False)
    out = await cognition_status()
    assert out == {"enabled": False, "available": False}
