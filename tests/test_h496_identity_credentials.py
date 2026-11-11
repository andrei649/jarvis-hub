"""H496 — one identity's credentials never reach another identity's turn.

Each test binds a turn principal (the owner, a guest on the HUD, a paired Telegram
sender who is not the owner, a non-owner OpenAI-API key, an internal job) and tries to
make the turn use an owner credential through every seam that puts one on the wire:
a cloud provider route, a bridged MCP server, a keyed web-search backend, a skill's
stored setup values and a secret-broker handle. A guest is refused at each one until
the owner shares that one integration, and the share is recorded and audited.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest  # noqa: E402

from agents.core.commands import Principal  # noqa: E402
from agents.core.orchestrator import bind_turn_principal, reset_turn_principal  # noqa: E402
from agents.core.security import credential_scope as cs  # noqa: E402

OWNER_WEB = Principal(channel="web", sender="owner", admin=True)
GUEST_WEB = Principal(channel="web", sender="guest-token", admin=False)
TELEGRAM_GUEST = Principal(channel="telegram", sender="7", admin=False)
TELEGRAM_OWNER = Principal(channel="telegram", sender="1", admin=True)
API_GUEST = Principal(channel="openai_api", sender="key-2", admin=False)
GUESTS = (GUEST_WEB, TELEGRAM_GUEST, API_GUEST)


class _Audit:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail

    def log(self, event):
        if self.fail:
            raise RuntimeError("audit down")
        self.events.append(event)


@pytest.fixture(autouse=True)
def _ledger(tmp_path):
    cs.set_ledger_path_for_tests(tmp_path / "credential_shares.json")
    yield
    cs.set_ledger_path_for_tests(None)


class _as:
    def __init__(self, principal):
        self.principal = principal

    def __enter__(self):
        self.token = bind_turn_principal(self.principal) if self.principal else None
        return self

    def __exit__(self, *exc):
        if self.token is not None:
            reset_turn_principal(self.token)


# ── identity placement ───────────────────────────────────────────────────────

def test_turn_identity_places_every_principal():
    assert cs.turn_identity(OWNER_WEB, "generated").kind == cs.IDENTITY_OWNER
    assert cs.turn_identity(TELEGRAM_OWNER, "inbound").kind == cs.IDENTITY_OWNER
    for guest in GUESTS:
        assert cs.turn_identity(guest, "generated").kind == cs.IDENTITY_GUEST
    assert cs.turn_identity(Principal(), "generated").kind == cs.IDENTITY_SYSTEM
    # An inbound turn nobody vouched for on an internal channel is still a guest.
    assert cs.turn_identity(Principal(channel="widget"), "inbound").kind == cs.IDENTITY_GUEST


def test_classifier_failure_reads_as_guest(monkeypatch):
    import agents.core.tool_profiles as tp

    monkeypatch.setattr(tp, "classify_turn", lambda *a, **k: 1 / 0)
    assert cs.turn_identity(OWNER_WEB, "generated").is_guest
    assert not cs.allowed(cs.KIND_MCP, "github", principal=OWNER_WEB, origin="generated")


# ── the share ledger ─────────────────────────────────────────────────────────

def test_guest_is_refused_until_one_integration_is_shared_and_the_share_is_audited():
    audit = _Audit()
    for guest in GUESTS:
        with pytest.raises(cs.CredentialNotShared) as err:
            cs.check(cs.KIND_MCP, "github", principal=guest, origin="generated")
        assert err.value.reason == "credential_not_shared"
    cs.share(cs.KIND_MCP, "github", by="owner", note="read-only issues", audit=audit)
    for guest in GUESTS:
        cs.check(cs.KIND_MCP, "github", principal=guest, origin="generated")
    # Sharing one integration shares nothing else.
    with pytest.raises(cs.CredentialNotShared):
        cs.check(cs.KIND_MCP, "gmail", principal=GUEST_WEB, origin="generated")
    with pytest.raises(cs.CredentialNotShared):
        cs.check(cs.KIND_PROVIDER, "github", principal=GUEST_WEB, origin="generated")
    rows = cs.list_shares()
    assert [r["integration"] for r in rows] == ["mcp:github"]
    assert rows[0]["by"] == "owner" and rows[0]["note"] == "read-only issues" and rows[0]["at"] > 0
    assert len(audit.events) == 1 and "mcp:github" in audit.events[0].content_preview
    cs.unshare(cs.KIND_MCP, "github", audit=audit)
    with pytest.raises(cs.CredentialNotShared):
        cs.check(cs.KIND_MCP, "github", principal=GUEST_WEB, origin="generated")
    assert len(audit.events) == 2


def test_owner_and_system_turns_never_need_a_share():
    for principal, origin in ((OWNER_WEB, "generated"), (TELEGRAM_OWNER, "inbound"),
                              (Principal(), "generated")):
        for kind in cs.KINDS:
            cs.check(kind, "anything", principal=principal, origin=origin)


def test_a_share_the_audit_cannot_record_is_not_granted():
    with pytest.raises(RuntimeError):
        cs.share(cs.KIND_SKILL, "weather-tool", audit=_Audit(fail=True))
    assert cs.list_shares() == []


def test_malformed_ledger_shares_nothing(tmp_path):
    path = tmp_path / "bad.json"
    cs.set_ledger_path_for_tests(path)
    path.write_text(json.dumps({"shares": {"mcp:github": {"at": 1}, "nonsense": {}}}))
    assert not cs.is_shared(cs.KIND_MCP, "github")
    path.write_text("{not json")
    assert cs.list_shares() == []


def test_bad_integration_names_are_refused():
    for bad in ("", "nokind", "weird:x", "mcp:", "mcp:" + "x" * 200, "mcp:a b"):
        with pytest.raises(ValueError):
            cs.parse_integration(bad)
    assert cs.parse_integration("web_search:tavily") == ("web_search", "tavily")


# ── the seams: each tries to use an owner credential from a guest turn ───────

def _resolved(policy):
    from agents.core.llm import data_handling as dh

    return dh.Resolved("openai", policy, "", "")


def test_cloud_provider_route_refused_for_guest_local_route_allowed(monkeypatch):
    from agents.core.llm import data_handling as dh

    monkeypatch.setattr(dh, "_read_ack", lambda: ({}, True))
    backend = SimpleNamespace()
    monkeypatch.setattr(dh, "resolve", lambda *a, **k: _resolved("no-training"))
    for guest in GUESTS:
        with pytest.raises(dh.DataHandlingRefused) as err:
            dh.authorize(None, backend, "m", principal=guest, origin="generated", actual_use=False)
        assert "credential_not_shared" in str(err.value)
    # The owner's turn uses its own key as before.
    assert dh.authorize(None, backend, "m", principal=OWNER_WEB, origin="generated",
                        actual_use=False)["provider"] == "openai"
    # A loopback model holds no credential: a guest uses it.
    monkeypatch.setattr(dh, "resolve", lambda *a, **k: _resolved("local"))
    assert dh.authorize(None, backend, "m", principal=GUEST_WEB, origin="generated",
                        actual_use=False)["policy"] == "local"
    # Shared with guests: the guest turn may use it.
    monkeypatch.setattr(dh, "resolve", lambda *a, **k: _resolved("no-training"))
    cs.share(cs.KIND_PROVIDER, "openai")
    assert dh.authorize(None, backend, "m", principal=API_GUEST, origin="generated",
                        actual_use=False)["provider"] == "openai"


class _Manager:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append(name)
        return {"content": [{"type": "text", "text": "ok"}]}


def test_mcp_server_oauth_token_not_used_for_guest_turn():
    from agents.core.mcp.model_bridge import MCPBridgeError, MCPModelBridge

    manager = _Manager()
    bridge = MCPModelBridge(rpc=None, manager=lambda: manager)
    handler = bridge._handler("mcp__github__issues", "github")
    for guest in GUESTS:
        with _as(guest), pytest.raises(MCPBridgeError, match="credential_not_shared"):
            asyncio.run(handler({}))
    assert manager.calls == []
    with _as(OWNER_WEB):
        asyncio.run(handler({}))
    assert manager.calls == ["mcp__github__issues"]
    cs.share(cs.KIND_MCP, "github")
    with _as(TELEGRAM_GUEST):
        asyncio.run(handler({}))
    assert manager.calls == ["mcp__github__issues"] * 2


def test_session_scoped_editor_server_keeps_its_own_rule():
    from agents.core.mcp.model_bridge import MCPModelBridge

    manager = _Manager()
    handler = MCPModelBridge(rpc=None, manager=lambda: manager)._handler(
        "mcp__editor__read", "editor", "session-1")
    with _as(GUEST_WEB):
        asyncio.run(handler({}))
    assert manager.calls == ["mcp__editor__read"]


class _Provider:
    def __init__(self, name, keyless=False):
        self.name = name
        self.keyless = keyless
        self.plugin_id = "websearch"
        self.calls = 0

    async def search(self, client, plugin, query, max_results):
        self.calls += 1
        return [{"title": "t", "url": "https://example.org", "snippet": "s"}]


def test_keyed_web_search_backend_refused_for_guest_keyless_allowed():
    from agents.core.plugins import web_providers
    from agents.core.plugins.websearch import WebSearchPlugin

    plugin = WebSearchPlugin.__new__(WebSearchPlugin)
    plugin._client = object()
    plugin._view = lambda: SimpleNamespace()
    keyed, keyless = _Provider("tavily"), _Provider("duckduckgo", keyless=True)
    with _as(GUEST_WEB), pytest.raises(web_providers.PolicyBlock, match="credential_not_shared"):
        asyncio.run(plugin._ask(keyed, "q", 3))
    assert keyed.calls == 0
    with _as(GUEST_WEB):
        assert asyncio.run(plugin._ask(keyless, "q", 3))
    with _as(OWNER_WEB):
        assert asyncio.run(plugin._ask(keyed, "q", 3))
    cs.share(cs.KIND_WEB_SEARCH, "tavily")
    with _as(API_GUEST):
        assert asyncio.run(plugin._ask(keyed, "q", 3))
    assert keyed.calls == 2


def test_skill_setup_values_not_used_for_guest_turn(monkeypatch, tmp_path):
    from agents.core import integration_keys
    from agents.core.skills import skill_secrets
    from agents.core.skills.loader import Skill

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(integration_keys, "_store_path", lambda: tmp_path / "secrets.enc")
    monkeypatch.delenv("H496_TOOL_KEY", raising=False)
    seen = []

    async def handle(command, args, context):
        seen.append(dict(context.get("skill_env") or {}))
        return "ran"

    skill = Skill("weather-tool", None, {"name": "weather-tool", "required_environment_variables": [
        {"name": "H496_TOOL_KEY", "prompt": "key"}]})
    skill.module = SimpleNamespace(handle=handle)
    skill_secrets.set_value(skill, "H496_TOOL_KEY", "sk-owner-value-0123456789")
    with _as(TELEGRAM_GUEST):
        refused = asyncio.run(skill.execute("go", "", {"channel": "telegram"}))
    assert "not shared with guests" in refused and seen == []
    with _as(OWNER_WEB):
        assert asyncio.run(skill.execute("go", "", {"channel": "web"})) == "ran"
    assert seen == [{"H496_TOOL_KEY": "sk-owner-value-0123456789"}]
    cs.share(cs.KIND_SKILL, "weather-tool")
    with _as(TELEGRAM_GUEST):
        assert asyncio.run(skill.execute("go", "", {"channel": "telegram"})) == "ran"


def test_secret_broker_handle_not_injected_into_guest_turn():
    from agents.core.security.secret_broker import SecretBroker

    broker = SecretBroker()
    broker.put("github_token", "ghp_owner_value_0123456789")
    with _as(GUEST_WEB):
        out = broker.inject("{{secret:github_token}}", approved=True)
    assert "ghp_owner" not in out["text"] and out["blocked"] == ["github_token"]
    with _as(OWNER_WEB):
        assert broker.inject("{{secret:github_token}}", approved=True)["text"] == "ghp_owner_value_0123456789"
    # A background call (no principal) is the owner's own job.
    assert broker.inject("{{secret:github_token}}", approved=True)["injected"] == ["github_token"]
    cs.share(cs.KIND_SECRET, "github_token")
    with _as(GUEST_WEB):
        assert broker.inject("{{secret:github_token}}", approved=True)["injected"] == ["github_token"]


def test_guest_task_spawned_inside_the_turn_keeps_the_guest_identity():
    """A background task started from a guest turn inherits its principal (contextvars):
    it does not become a system job with the owner's credentials."""
    async def run():
        with _as(GUEST_WEB):
            return await asyncio.create_task(asyncio.sleep(0, result=cs.turn_identity().kind))

    assert asyncio.run(run()) == cs.IDENTITY_GUEST


def test_workspace_secrets_live_in_their_own_store():
    """The Workspace pilot's one credential (SMTP) is the organisation's, in its own
    store under business/; no hub seam reads it and it is not the hub's secrets.enc."""
    from agents.core.workspace import config as wconfig

    assert wconfig.SECRETS_FILE == "secrets.enc"
    src = (repo_root / "agents/core/workspace/mailer.py").read_text()
    assert "data_path(config.DATA_DIRNAME" in src


# ── the owner's route ────────────────────────────────────────────────────────

def test_share_route_is_admin_only_and_records(monkeypatch):
    from fastapi.testclient import TestClient

    import agents.web as web

    audit = _Audit()
    monkeypatch.setattr(web, "orch", SimpleNamespace(audit=audit))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-test")
    client = TestClient(web.app)
    body = {"integration": "mcp:github", "shared": True, "note": "issues"}
    assert client.post("/api/security/credential-shares", json=body).status_code in (401, 403)
    admin = {"X-Admin-Token": "owner-test"}
    ok = client.post("/api/security/credential-shares", json=body, headers=admin)
    assert ok.status_code == 200 and ok.json()["shared"] is True
    from agents.core.routers.security import _credential_shares_posture

    listed = _credential_shares_posture()   # what /api/security/posture shows the HUD
    assert [r["integration"] for r in listed["shares"]] == ["mcp:github"]
    bad = client.post("/api/security/credential-shares", headers=admin,
                      json={"integration": "root:everything", "shared": True})
    assert bad.status_code == 422
    off = client.post("/api/security/credential-shares", headers=admin,
                      json={"integration": "mcp:github", "shared": False})
    assert off.json() == {"integration": "mcp:github", "shared": False, "changed": True}
    assert cs.list_shares() == []
    assert [e.action_taken for e in audit.events
            if e.action_taken.startswith("credential_")] == ["credential_shared_with_guests",
                                                             "credential_unshared"]
