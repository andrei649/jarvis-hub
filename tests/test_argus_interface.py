"""Tests for the Argus governed interface over Signal Layer + WorldView."""

import pytest

from agents.core.argus import ArgusInterface
from agents.core.plugin_gate import PermissionGate


class _SignalStub:
    def __init__(self):
        self.calls = []

    async def ask_world(self, question, mode="general", country="", limit=12):
        self.calls.append(("ask_world", question, mode, country, limit))
        return {"status": "ok", "answer": "brief", "mode": mode, "country": country}

    async def world_brief(self):
        return {"status": "ok", "brief": {"title": "Global Intelligence Brief"}}

    async def country_assessment(self, iso2):
        return {"status": "ok", "assessment": {"subject": {"id": iso2}}}

    async def boom(self):
        raise ConnectionError("refused")


class _WorldViewStub:
    async def state_at(self, layer, t, bbox="", lod=""):
        return {"status": "ok", "layer": layer, "t": t}

    async def recon_overview(self, lead=None):
        return {"status": "ok", "lead": lead}


async def test_argus_routes_signal_layer_when_permitted():
    sig = _SignalStub()
    argus = ArgusInterface(PermissionGate(), signal_layer=sig, worldview=_WorldViewStub())
    out = await argus.ask_world("what changed overnight", mode="overnight_brief", country="RO", limit=8)
    assert out["status"] == "ok"
    assert sig.calls[0] == ("ask_world", "what changed overnight", "overnight_brief", "RO", 8)

    brief = await argus.world_brief()
    assert brief["brief"]["title"] == "Global Intelligence Brief"
    risk = await argus.country_risk("RO")
    assert risk["assessment"]["subject"]["id"] == "RO"


async def test_argus_routes_worldview():
    argus = ArgusInterface(PermissionGate(), signal_layer=_SignalStub(), worldview=_WorldViewStub())
    state = await argus.worldview_state("aircraft", 123.0, bbox="x")
    assert state["status"] == "ok" and state["layer"] == "aircraft"
    recon = await argus.recon_overview(lead=30)
    assert recon["lead"] == 30


async def test_argus_forbids_unpermitted_agent():
    # 'frigga' is not in agents_served for these manifests → must be blocked.
    argus = ArgusInterface(PermissionGate(), signal_layer=_SignalStub(), worldview=_WorldViewStub(), agent_id="frigga")
    out = await argus.ask_world("x")
    assert out["status"] == "forbidden" and out["plugin"] == "signal-layer"
    wv = await argus.worldview_state("aircraft", 1.0)
    assert wv["status"] == "forbidden" and wv["plugin"] == "worldview"


async def test_argus_unavailable_when_backend_not_wired():
    argus = ArgusInterface(PermissionGate(), signal_layer=None, worldview=None)
    out = await argus.world_brief()
    assert out["status"] == "unavailable" and out["plugin"] == "signal-layer"


async def test_argus_failsafe_on_backend_error():
    sig = _SignalStub()
    argus = ArgusInterface(PermissionGate(), signal_layer=sig)
    # Point a method at the raising stub method to simulate a backend failure.
    sig.world_brief = sig.boom
    out = await argus.world_brief()
    assert out["status"] == "unavailable" and "error" in out


def test_argus_gate_failure_fails_closed():
    class _BadGate:
        def check_call(self, *a, **k):
            raise RuntimeError("gate exploded")

    argus = ArgusInterface(_BadGate(), signal_layer=_SignalStub())
    caps = argus.capabilities()
    assert caps["signal_layer"]["permitted"] is False  # error → deny, never allow


def test_argus_capabilities_reflects_gate_and_wiring():
    argus = ArgusInterface(PermissionGate(), signal_layer=_SignalStub(), worldview=None)
    caps = argus.capabilities()
    assert caps["agent"] == "argus"
    assert caps["signal_layer"]["permitted"] is True
    assert caps["signal_layer"]["wired"] is True
    assert caps["worldview"]["permitted"] is True
    assert caps["worldview"]["wired"] is False
