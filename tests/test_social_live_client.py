"""Live-vs-Plumbing: the social broker's live rail activates behind approval.

The BACKLOG item — "instantiate `HttpSocialClient` behind approval (drop
`NullSocialClient` when `x_api_token` present)". The default Null client lazily
upgrades to the HTTP rail the moment an approved task resolves a real owner
credential; unconfigured stays honestly deferred (now stamped `_degraded`);
an explicitly injected client is never replaced. All offline.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import social as social_mod  # noqa: E402
from agents.core.plugins.degradation import is_degraded  # noqa: E402
from agents.core.security.secret_broker import SecretBroker  # noqa: E402
from agents.core.social import HttpSocialClient, NullSocialClient, SocialBroker  # noqa: E402


def _task(platform="x", action="post", credential_ref=""):
    return SimpleNamespace(payload={
        "platform": platform, "action": action,
        "fields": {"text": "hello world"},
        "credential_ref": credential_ref,
    })


class _RecordingHttp:
    """Stands in for HttpSocialClient at the module seam."""

    instances: list = []

    def __init__(self):
        self.sent: list[dict] = []
        _RecordingHttp.instances.append(self)

    async def send(self, platform, action, fields, credentials):
        self.sent.append({"platform": platform, "action": action,
                          "token": credentials.get("token")})
        return {"status": "ok", "http_status": 200}


async def test_unconfigured_stays_deferred_and_degraded():
    broker = SocialBroker()  # no secrets, default Null client
    out = await broker.execute(_task())
    assert out["status"] == "ok"
    assert out["social"]["status"] == "deferred"
    assert is_degraded(out["social"])
    assert out["social"]["_degraded"]["needs"] == ["secret:x_api_token"]
    assert isinstance(broker._client, NullSocialClient)  # no silent upgrade


async def test_live_rail_activates_when_credential_resolves(monkeypatch):
    _RecordingHttp.instances = []
    monkeypatch.setattr(social_mod, "HttpSocialClient", _RecordingHttp)
    secrets = SecretBroker()
    secrets.put("x_api_token", "real-token-123")
    broker = SocialBroker(secret_broker=secrets)

    out = await broker.execute(_task(credential_ref=SecretBroker.reference("x_api_token")))

    assert out["status"] == "ok"
    assert out["social"]["status"] == "ok"          # posted via the live rail
    assert len(_RecordingHttp.instances) == 1
    assert _RecordingHttp.instances[0].sent == [
        {"platform": "x", "action": "post", "token": "real-token-123"}]
    # Subsequent executes reuse the upgraded client.
    await broker.execute(_task(credential_ref=SecretBroker.reference("x_api_token")))
    assert len(_RecordingHttp.instances) == 1


async def test_injected_client_is_never_replaced(monkeypatch):
    monkeypatch.setattr(social_mod, "HttpSocialClient", _RecordingHttp)
    secrets = SecretBroker()
    secrets.put("x_api_token", "real-token-123")
    null = NullSocialClient()
    broker = SocialBroker(secret_broker=secrets, client=null)

    out = await broker.execute(_task(credential_ref=SecretBroker.reference("x_api_token")))

    assert out["social"]["status"] == "deferred"    # injected Null kept
    assert broker._client is null
    assert null.calls[0]["has_credential"] is True


def test_http_client_is_the_real_upgrade_target():
    """The lazy upgrade constructs the genuine HttpSocialClient (SSRF-guarded)."""
    assert social_mod.HttpSocialClient is HttpSocialClient
