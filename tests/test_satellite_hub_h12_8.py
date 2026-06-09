"""H12.8 — Split mic satellites → shared-GPU inference. All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import asyncio
import pytest

from agents.core.satellite_hub import SatelliteHub, NullInference


def test_register_list_get_unregister():
    hub = SatelliteHub()
    hub.register("kitchen", {"room": "kitchen"})
    hub.register("office")
    assert {s["id"] for s in hub.list()} == {"kitchen", "office"}
    assert hub.get("kitchen")["meta"] == {"room": "kitchen"}
    assert hub.unregister("office") is True
    assert hub.get("office") is None


@pytest.mark.asyncio
async def test_dispatch_unknown_rejected():
    hub = SatelliteHub()
    out = await hub.dispatch("ghost", "audio")
    assert out["ok"] is False and out["reason"] == "unknown_satellite"


@pytest.mark.asyncio
async def test_dispatch_routes_to_inference():
    class _Inf:
        async def process(self, kind, data):
            return {"engine": "test", "kind": kind, "text": f"got:{data}"}

    hub = SatelliteHub(inference=_Inf())
    hub.register("kitchen")
    out = await hub.dispatch("kitchen", "hello", kind="transcribe")
    assert out["ok"] is True and out["result"]["text"] == "got:hello"
    assert hub.get("kitchen")["calls"] == 1


@pytest.mark.asyncio
async def test_null_inference_echoes():
    hub = SatelliteHub()
    hub.register("s1")
    out = await hub.dispatch("s1", "ping")
    assert out["result"]["engine"] == "null" and out["result"]["text"] == "ping"


@pytest.mark.asyncio
async def test_inference_error_is_reported():
    class _Boom:
        async def process(self, kind, data):
            raise RuntimeError("gpu oom")

    hub = SatelliteHub(inference=_Boom())
    hub.register("s1")
    out = await hub.dispatch("s1", "x")
    assert out["ok"] is False and out["reason"] == "inference_error"


@pytest.mark.asyncio
async def test_shared_gpu_serializes_concurrent_dispatches():
    class _Probe:
        def __init__(self):
            self.cur = 0
            self.peak = 0

        async def process(self, kind, data):
            self.cur += 1
            self.peak = max(self.peak, self.cur)
            await asyncio.sleep(0.01)  # hold the "GPU"
            self.cur -= 1
            return {"ok": True}

    probe = _Probe()
    hub = SatelliteHub(inference=probe, max_concurrency=1)
    for i in range(4):
        hub.register(f"s{i}")
    await asyncio.gather(*(hub.dispatch(f"s{i}", "audio") for i in range(4)))
    assert probe.peak == 1                     # single GPU → never concurrent
    assert hub.stats()["peak_inflight"] == 1


@pytest.mark.asyncio
async def test_higher_concurrency_allows_parallelism():
    class _Probe:
        def __init__(self):
            self.cur = 0
            self.peak = 0

        async def process(self, kind, data):
            self.cur += 1
            self.peak = max(self.peak, self.cur)
            await asyncio.sleep(0.01)
            self.cur -= 1
            return {"ok": True}

    probe = _Probe()
    hub = SatelliteHub(inference=probe, max_concurrency=2)
    for i in range(4):
        hub.register(f"s{i}")
    await asyncio.gather(*(hub.dispatch(f"s{i}", "audio") for i in range(4)))
    assert probe.peak == 2


@pytest.mark.asyncio
async def test_stats():
    hub = SatelliteHub()
    hub.register("a")
    hub.register("b")
    await hub.dispatch("a", "x")
    await hub.dispatch("a", "y")
    stats = hub.stats()
    assert stats["satellites"] == 2 and stats["by_satellite"]["a"] == 2
