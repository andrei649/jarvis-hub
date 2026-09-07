"""H30.8 — default-off WLED ambient bridge: every write is a governed house.control.

Hermetic: a recording fake transport stands in for the strip, a fake
authorizer stands in for Ultron, and DNS is a stub resolver. The properties
pinned here are the ones the presence guide demanded: off unless configured,
strict-local URL, kernel before bytes, silent (not guessing) when the device is
unreachable, and no re-send of an unchanged scene.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
for entry in (str(repo_root), str(repo_root / "agents")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from agents.core.house.wled import (  # noqa: E402
    WLED_SCENES,
    WLED_URL_ENV,
    HttpxJSONTransport,
    WLEDBridge,
    WLEDConfigError,
    scene_payload,
    validate_wled_origin,
)
from agents.core.kernel import Decision, Verdict  # noqa: E402

_LAN_URL = "http://192.168.1.40"


def _lan_resolver(_host, _port):
    return ["192.168.1.40"]


class _Transport:
    """Records every POST; answers with a WLED-style echo of the request."""

    def __init__(self, *, ok=True, echo=None, reason=None):
        self.calls = []
        self.ok = ok
        self.echo = echo
        self.reason = reason

    async def __call__(self, url, body):
        self.calls.append((url, dict(body)))
        if not self.ok:
            return {"ok": False, "reason": self.reason or "wled_unreachable"}
        echo = self.echo if self.echo is not None else {"on": body["on"], "bri": body.get("bri", 0)}
        return {"ok": True, "status": 200, "echo": echo}


class _Kernel:
    def __init__(self, verdict=Verdict.GRANT):
        self.verdict = verdict
        self.actions = []

    def __call__(self, action, capability=None):
        self.actions.append((action, capability))
        return Decision(self.verdict, reason=f"kernel-{self.verdict.value}", tier=1)


@pytest.fixture
def governed(monkeypatch):
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.delenv(WLED_URL_ENV, raising=False)


def _bridge(**kwargs):
    kwargs.setdefault("url", _LAN_URL)
    kwargs.setdefault("resolver", _lan_resolver)
    kwargs.setdefault("transport", _Transport())
    kwargs.setdefault("authorizer", _Kernel())
    return WLEDBridge(**kwargs)


# ── default-off + configuration ─────────────────────────────────────────────


async def test_unconfigured_bridge_refuses_and_sends_nothing(monkeypatch, governed):
    transport = _Transport()
    bridge = WLEDBridge(transport=transport, authorizer=_Kernel())

    result = await bridge.set_scene("listening")

    assert result == {"ok": False, "reason": "wled_not_configured"}
    assert transport.calls == []
    assert bridge.status()["configured"] is False
    assert bridge.status()["reason"] == "wled_not_configured"


async def test_env_url_configures_the_bridge(monkeypatch, governed):
    monkeypatch.setenv(WLED_URL_ENV, " http://192.168.1.40 ")
    bridge = WLEDBridge(transport=_Transport(), authorizer=_Kernel(), resolver=_lan_resolver)

    assert bridge.configured is True
    assert bridge.status()["host"] == "192.168.1.40"


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8",  # public literal
        "http://wled.example.com",  # hostname without allowlist
        "ftp://192.168.1.40",  # scheme
        "http://192.168.1.40/json",  # path
        "http://user:pw@192.168.1.40",  # credentials
        "http://192.168.1.40?x=1",  # query
    ],
)
def test_non_local_or_non_origin_urls_are_rejected(url):
    with pytest.raises(WLEDConfigError):
        validate_wled_origin(url, resolver=_lan_resolver)


def test_allowlisted_host_must_still_resolve_on_the_lan():
    with pytest.raises(WLEDConfigError):
        validate_wled_origin(
            "http://strip.lan", allowed_hosts=("strip.lan",), resolver=lambda *_: ["1.1.1.1"]
        )
    assert (
        validate_wled_origin("http://strip.lan:8080", allowed_hosts=("strip.lan",), resolver=_lan_resolver)
        == "http://strip.lan:8080"
    )
    assert validate_wled_origin("http://wled.local", resolver=_lan_resolver) == "http://wled.local"


async def test_rejected_url_refuses_without_probing(governed):
    transport = _Transport()
    bridge = _bridge(url="http://8.8.8.8", transport=transport)

    result = await bridge.set_scene("listening")

    assert result["ok"] is False
    assert result["reason"] == "wled_url_rejected"
    assert transport.calls == []


# ── scene table ──────────────────────────────────────────────────────────────


def test_scene_table_mirrors_every_orb_state_and_only_off_turns_the_strip_off():
    assert set(WLED_SCENES) == {"off", "idle", "listening", "transcribing", "speaking", "error"}
    for state in WLED_SCENES:
        body = scene_payload(state)
        assert body["v"] is True, "writes must ask WLED to echo its state back"
        assert body["on"] is (state != "off")
        if state != "off":
            assert 1 <= body["bri"] <= 255
            assert len(body["seg"][0]["col"][0]) == 3
    with pytest.raises(ValueError):
        scene_payload("disco")


async def test_unknown_scene_is_refused_before_the_kernel(governed):
    kernel = _Kernel()
    bridge = _bridge(authorizer=kernel)

    assert await bridge.set_scene("disco") == {"ok": False, "reason": "unknown_scene"}
    assert kernel.actions == []


# ── the governed write ───────────────────────────────────────────────────────


async def test_every_write_crosses_house_control_before_the_transport(governed):
    kernel = _Kernel()
    transport = _Transport()
    bridge = _bridge(authorizer=kernel, transport=transport)

    result = await bridge.set_scene("listening")

    assert result == {"ok": True, "scene": "listening", "verified": True}
    assert len(kernel.actions) == 1
    action, capability = kernel.actions[0]
    assert action.kind == "house.control"
    assert action.agent == "hestia"
    assert action.scope == "house:light.wled_192_168_1_40"
    assert action.payload["control"] == "ambient"
    assert action.payload["scene"] == "listening"
    assert action.payload["reversible"] is True
    assert capability.name == "house.control"
    assert transport.calls == [("http://192.168.1.40/json/state", scene_payload("listening"))]
    assert bridge.status()["scene"] == "listening"


async def test_kernel_deny_sends_nothing(governed):
    transport = _Transport()
    bridge = _bridge(authorizer=_Kernel(Verdict.DENY), transport=transport)

    result = await bridge.set_scene("speaking")

    assert result == {"ok": False, "reason": "kernel-deny", "scene": "speaking"}
    assert transport.calls == []
    assert bridge.status()["scene"] is None


async def test_kernel_queue_waits_for_the_owner(governed):
    transport = _Transport()
    bridge = _bridge(authorizer=_Kernel(Verdict.QUEUE), transport=transport)

    result = await bridge.set_scene("speaking")

    assert result == {
        "ok": False,
        "reason": "approval_required",
        "scene": "speaking",
        "queued": True,
    }
    assert transport.calls == []


async def test_without_a_kernel_the_bridge_refuses(governed):
    transport = _Transport()
    bridge = _bridge(authorizer=None, transport=transport)

    result = await bridge.set_scene("idle")

    assert result["reason"] == "kernel_unavailable"
    assert transport.calls == []


async def test_default_off_flags_keep_the_strip_untouched(monkeypatch):
    monkeypatch.delenv("JARVIS_UNIFIED_ACTION_API", raising=False)
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    transport = _Transport()
    kernel = _Kernel()
    bridge = _bridge(authorizer=kernel, transport=transport)

    result = await bridge.set_scene("idle")

    assert result["ok"] is False
    assert result["reason"] == "unified_action_api_disabled"
    assert transport.calls == []
    assert kernel.actions == []


# ── silence, verification, budget ───────────────────────────────────────────


async def test_unchanged_scene_is_a_no_op_without_a_network_call(governed):
    kernel = _Kernel()
    transport = _Transport()
    bridge = _bridge(authorizer=kernel, transport=transport)

    await bridge.set_scene("listening")
    again = await bridge.set_scene("listening")

    assert again == {"ok": True, "scene": "listening", "unchanged": True}
    assert len(transport.calls) == 1
    assert len(kernel.actions) == 1


async def test_unreachable_strip_is_reported_not_guessed(governed):
    transport = _Transport(ok=False)
    bridge = _bridge(transport=transport)

    result = await bridge.set_scene("listening")

    assert result == {"ok": False, "reason": "wled_unreachable", "scene": "listening"}
    assert bridge.status()["scene"] is None, "an unconfirmed write never becomes the known scene"
    # A retry after the outage is a real write, not a dedupe hit.
    transport.ok = True
    assert (await bridge.set_scene("listening"))["verified"] is True
    assert len(transport.calls) == 2


async def test_echo_mismatch_is_a_verification_failure(governed):
    bridge = _bridge(transport=_Transport(echo={"on": False}))

    result = await bridge.set_scene("speaking")

    assert result == {"ok": False, "reason": "wled_verification_failed", "scene": "speaking"}
    assert bridge.status()["scene"] is None


async def test_write_budget_bounds_a_flapping_pipeline(governed):
    clock = [1000.0]
    transport = _Transport()
    bridge = _bridge(transport=transport, writes_per_minute=2, clock=lambda: clock[0])

    assert (await bridge.set_scene("listening"))["ok"] is True
    assert (await bridge.set_scene("speaking"))["ok"] is True
    limited = await bridge.set_scene("idle")
    assert limited == {"ok": False, "reason": "wled_rate_limited", "scene": "idle"}
    assert len(transport.calls) == 2

    clock[0] += 61.0
    assert (await bridge.set_scene("idle"))["ok"] is True
    assert len(transport.calls) == 3


async def test_dependency_missing_is_an_honest_refusal(monkeypatch):
    monkeypatch.setitem(sys.modules, "httpx", None)

    result = await HttpxJSONTransport()("http://192.168.1.40/json/state", {"on": False, "v": True})

    assert result == {"ok": False, "reason": "dependency_unavailable:httpx"}
