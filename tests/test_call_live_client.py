"""Live-vs-Plumbing: the call broker's live telephony rail activates behind approval.

Mirror of ``test_social_live_client.py`` for ``CallBroker``: the default Null
client lazily upgrades to the HTTP telephony rail the moment an approved task
resolves a real owner credential; unconfigured stays honestly deferred (now
stamped ``_degraded``); an explicitly injected client is never replaced.
All offline. The node mesh (no client pair exists at all) is covered too: its
deferred dispatch is stamped degraded, naming the unbuilt transport.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy import call_broker as cb_mod  # noqa: E402
from agents.core.autonomy.call_broker import (  # noqa: E402
    CallBroker,
    HttpCallClient,
    NullCallClient,
)
from agents.core.plugins.degradation import is_degraded  # noqa: E402
from agents.core.security.secret_broker import SecretBroker  # noqa: E402


def _task(provider="twilio", credential_ref=""):
    return SimpleNamespace(payload={
        "provider": provider, "action": "call",
        "to": "+40711111111", "message": "hello",
        "credential_ref": credential_ref,
    })


class _RecordingHttp:
    """Stands in for HttpCallClient at the module seam."""

    instances: list = []

    def __init__(self):
        self.placed: list[dict] = []
        _RecordingHttp.instances.append(self)

    async def call(self, provider, to, message, credentials, config):
        self.placed.append({"provider": provider, "to": to,
                            "token": credentials.get("token")})
        return {"status": "ok", "http_status": 201}


async def test_unconfigured_stays_deferred_and_degraded():
    broker = CallBroker()  # no secrets, default Null client
    out = await broker.execute(_task())
    assert out["status"] == "ok"
    assert out["call"]["status"] == "deferred"
    assert is_degraded(out["call"])
    assert out["call"]["_degraded"]["needs"] == ["secret:twilio_auth_token"]
    assert isinstance(broker._client, NullCallClient)  # no silent upgrade


async def test_live_rail_activates_when_credential_resolves(monkeypatch):
    _RecordingHttp.instances = []
    monkeypatch.setattr(cb_mod, "HttpCallClient", _RecordingHttp)
    secrets = SecretBroker()
    secrets.put("twilio_auth_token", "real-token-123")
    broker = CallBroker(secret_broker=secrets)

    out = await broker.execute(
        _task(credential_ref=SecretBroker.reference("twilio_auth_token")))

    assert out["status"] == "ok"
    assert out["call"]["status"] == "ok"            # placed via the live rail
    assert len(_RecordingHttp.instances) == 1
    assert _RecordingHttp.instances[0].placed == [
        {"provider": "twilio", "to": "+40711111111", "token": "real-token-123"}]
    # Subsequent executes reuse the upgraded client.
    await broker.execute(_task(credential_ref=SecretBroker.reference("twilio_auth_token")))
    assert len(_RecordingHttp.instances) == 1


async def test_injected_client_is_never_replaced(monkeypatch):
    monkeypatch.setattr(cb_mod, "HttpCallClient", _RecordingHttp)
    secrets = SecretBroker()
    secrets.put("twilio_auth_token", "real-token-123")
    null = NullCallClient()
    broker = CallBroker(secret_broker=secrets, client=null)

    out = await broker.execute(
        _task(credential_ref=SecretBroker.reference("twilio_auth_token")))

    assert out["call"]["status"] == "deferred"      # injected Null kept
    assert broker._client is null
    assert null.calls[0]["has_credential"] is True


def test_http_client_is_the_real_upgrade_target():
    """The lazy upgrade constructs the genuine HttpCallClient (SSRF-guarded)."""
    assert cb_mod.HttpCallClient is HttpCallClient


async def test_node_mesh_deferred_dispatch_is_stamped_degraded():
    from agents.core.node_mesh import NodeMesh
    from agents.core.security.capability import CapabilityBroker

    mesh = NodeMesh(capability_broker=CapabilityBroker())
    mesh.register_node("phone", ["notify"])
    task = SimpleNamespace(payload={"node": "phone", "capability": "notify"})
    out = await mesh.execute(task)
    assert out["status"] == "ok"
    assert out["dispatch"]["status"] == "deferred"
    assert is_degraded(out["dispatch"])
    assert out["dispatch"]["_degraded"]["reason"] == "node_transport_not_built"
