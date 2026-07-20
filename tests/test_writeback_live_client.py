"""Live-vs-Plumbing: the write-back broker's live rail activates behind approval.

Mirror of ``test_social_live_client.py`` for ``WriteBackBroker``: the default
Null client lazily upgrades to the HTTP rail the moment an approved task
resolves a real owner credential; unconfigured stays honestly deferred (now
stamped ``_degraded``); an explicitly injected client is never replaced.
All offline.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import writeback as wb_mod  # noqa: E402
from agents.core.plugins.degradation import is_degraded  # noqa: E402
from agents.core.security.secret_broker import SecretBroker  # noqa: E402
from agents.core.writeback import (  # noqa: E402
    HttpWriteBackClient,
    NullWriteBackClient,
    WriteBackBroker,
)


def _task(target="github", action="create_issue", credential_ref=""):
    return SimpleNamespace(payload={
        "system": target, "action": action,
        "fields": {"repo": "owner/repo", "title": "hello"},
        "credential_ref": credential_ref,
    })


class _RecordingHttp:
    """Stands in for HttpWriteBackClient at the module seam."""

    instances: list = []

    def __init__(self):
        self.written: list[dict] = []
        _RecordingHttp.instances.append(self)

    async def write(self, target, action, fields, credentials):
        self.written.append({"target": target, "action": action,
                             "token": credentials.get("token")})
        return {"status": "ok", "http_status": 201}


async def test_unconfigured_stays_deferred_and_degraded():
    broker = WriteBackBroker()  # no secrets, default Null client
    out = await broker.execute(_task())
    assert out["status"] == "ok"
    assert out["writeback"]["status"] == "deferred"
    assert is_degraded(out["writeback"])
    assert out["writeback"]["_degraded"]["needs"] == ["secret:github_token"]
    assert isinstance(broker._client, NullWriteBackClient)  # no silent upgrade


async def test_live_rail_activates_when_credential_resolves(monkeypatch):
    _RecordingHttp.instances = []
    monkeypatch.setattr(wb_mod, "HttpWriteBackClient", _RecordingHttp)
    secrets = SecretBroker()
    secrets.put("github_token", "real-token-123")
    broker = WriteBackBroker(secret_broker=secrets)

    out = await broker.execute(_task(credential_ref=SecretBroker.reference("github_token")))

    assert out["status"] == "ok"
    assert out["writeback"]["status"] == "ok"       # wrote via the live rail
    assert len(_RecordingHttp.instances) == 1
    assert _RecordingHttp.instances[0].written == [
        {"target": "github", "action": "create_issue", "token": "real-token-123"}]
    # Subsequent executes reuse the upgraded client.
    await broker.execute(_task(credential_ref=SecretBroker.reference("github_token")))
    assert len(_RecordingHttp.instances) == 1


async def test_injected_client_is_never_replaced(monkeypatch):
    monkeypatch.setattr(wb_mod, "HttpWriteBackClient", _RecordingHttp)
    secrets = SecretBroker()
    secrets.put("github_token", "real-token-123")
    null = NullWriteBackClient()
    broker = WriteBackBroker(secret_broker=secrets, client=null)

    out = await broker.execute(_task(credential_ref=SecretBroker.reference("github_token")))

    assert out["writeback"]["status"] == "deferred"  # injected Null kept
    assert broker._client is null
    assert null.calls[0]["has_credential"] is True


def test_http_client_is_the_real_upgrade_target():
    """The lazy upgrade constructs the genuine HttpWriteBackClient (SSRF-guarded)."""
    assert wb_mod.HttpWriteBackClient is HttpWriteBackClient
