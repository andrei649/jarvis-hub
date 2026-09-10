"""The owner-facing half of S2: consent, activation, and what each refuses.

Consent is granted against a *manifest*, never against an id. That is the whole
point of the hash: agreeing to "the boats extension" would be agreeing to whatever
boats declares next, which is the failure H570 exists to prevent.

Activation is a separate act, and it is the one that costs a sandbox round trip.
These tests pin that neither route can be reached without admin, that a malformed
descriptor never reaches a runtime, and that withdrawing consent takes the tools
off the surface in the same call rather than leaving them live until someone
remembers to deactivate.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.core.extensions.consent import ExtensionConsentStore
from agents.core.extensions.manifest import parse_manifest
from agents.core.extensions.runtime import ExtensionRuntimeError
from agents.core.routers import _component, plugins

DESCRIPTOR = {
    "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.0.0",
    "capabilities": ["tools"], "tools": ["summarize"], "commands": [], "events": [],
    "requires": {"extensions": {}, "python": {}},
}
OWNER = {"X-User-Token": "ext-user", "X-Admin-Token": "ext-owner"}


class _Runtime:
    def __init__(self, *, activation=None, refusal=None):
        self.activation = activation
        self.refusal = refusal
        self.deactivated: list[str] = []

    async def activate(self, manifest):
        if self.refusal is not None:
            raise ExtensionRuntimeError(self.refusal)
        return SimpleNamespace(as_dict=lambda: {
            "id": manifest.id, "version": manifest.version, "package_hash": "c" * 64,
            "callable_tools": list(manifest.qualified_tools),
            "callable_commands": [], "observed_events": []})

    async def deactivate(self, extension_id):
        self.deactivated.append(extension_id)
        return True


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr(web, "USER_TOKEN", "ext-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "ext-owner")
    runtime = _Runtime()
    orch = SimpleNamespace(acquisition=SimpleNamespace(extensions=lambda: runtime),
                           permission_gate=None)
    monkeypatch.setattr(_component, "get_orch", lambda: orch)
    monkeypatch.setattr(plugins, "get_orch", lambda: orch)
    app = FastAPI()
    app.include_router(plugins.router)
    return SimpleNamespace(app=app, runtime=runtime, orch=orch,
                           store=ExtensionConsentStore(tmp_path / "extensions" / "consent.json"))


def client(rig):
    return httpx.AsyncClient(transport=httpx.ASGITransport(rig.app, client=("198.51.100.2", 1234)),
                             base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/plugins/extensions/consent", "/api/plugins/extensions/activate"])
async def test_neither_route_is_reachable_without_the_owner(rig, path):
    async with client(rig) as http:
        assert (await http.post(path, json={"manifest": DESCRIPTOR})).status_code == 401
        anonymous = await http.post(path, json={"manifest": DESCRIPTOR},
                                    headers={"X-User-Token": "ext-user"})
        assert anonymous.status_code == 401


@pytest.mark.asyncio
async def test_consent_records_the_exact_declared_surface(rig):
    async with client(rig) as http:
        granted = await http.post("/api/plugins/extensions/consent",
                                  json={"manifest": DESCRIPTOR}, headers=OWNER)
        assert granted.status_code == 200
        value = granted.json()
        assert value["ok"] is True and value["consent"] == "granted"
        assert len(value["declared_digest"]) == 64
    assert rig.store.check(parse_manifest(DESCRIPTOR)).allowed


@pytest.mark.asyncio
async def test_an_update_that_widens_the_surface_reads_as_changed_with_the_difference(rig):
    widened = {**DESCRIPTOR, "version": "1.1.0", "capabilities": ["tools", "commands"],
               "commands": ["boats_summary"]}
    async with client(rig) as http:
        await http.post("/api/plugins/extensions/consent", json={"manifest": DESCRIPTOR}, headers=OWNER)
        # Re-consenting to the widened document is the owner's *new* decision, and it
        # is only reachable because the state in between reads `changed`, not granted.
        second = await http.post("/api/plugins/extensions/consent", json={"manifest": widened}, headers=OWNER)
    decision = rig.store.check(parse_manifest(DESCRIPTOR))
    assert second.json()["consent"] == "granted"
    assert decision.state == "changed", "the original surface is no longer the agreed one"
    assert decision.removed == ("capability:commands", "command:boats_summary")
    # The runtime is the thing that refuses a `changed` state; that is pinned in
    # tests/test_extension_runtime.py, against the real gate rather than this double.


@pytest.mark.asyncio
async def test_revoking_consent_also_takes_the_tools_off_the_surface(rig):
    async with client(rig) as http:
        await http.post("/api/plugins/extensions/consent", json={"manifest": DESCRIPTOR}, headers=OWNER)
        revoked = await http.post("/api/plugins/extensions/consent",
                                  json={"manifest": DESCRIPTOR, "revoke": True}, headers=OWNER)
    value = revoked.json()
    assert value["ok"] is True and value["revoked"] is True
    assert value["consent"] == "not_granted" and value["granted_digest"] is None
    assert rig.runtime.deactivated == ["boats"], "a withdrawn grant must not stay callable"
    assert not rig.store.check(parse_manifest(DESCRIPTOR)).allowed


@pytest.mark.asyncio
async def test_revoking_a_grant_that_was_never_made_is_honest_about_it(rig):
    async with client(rig) as http:
        revoked = await http.post("/api/plugins/extensions/consent",
                                  json={"manifest": DESCRIPTOR, "revoke": True}, headers=OWNER)
    assert revoked.json()["revoked"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("manifest", [
    {**DESCRIPTOR, "id": "Boats"},
    {**DESCRIPTOR, "tools": ["summarize"], "capabilities": []},
    {**DESCRIPTOR, "commands": ["status"], "capabilities": ["tools", "commands"]},
    {**DESCRIPTOR, "manifest_version": 2},
    {**DESCRIPTOR, "events": ["anything"], "capabilities": ["tools", "events.observe"]},
    {"id": "boats"},
], ids=["bad-id", "undeclared-capability", "core-command", "wrong-version", "unknown-event", "not-a-manifest"])
async def test_a_malformed_descriptor_never_reaches_a_runtime(rig, manifest):
    async with client(rig) as http:
        for path in ("/api/plugins/extensions/consent", "/api/plugins/extensions/activate"):
            refused = await http.post(path, json={"manifest": manifest}, headers=OWNER)
            assert refused.status_code == 422, (path, manifest)
            assert refused.json()["ok"] is False and isinstance(refused.json()["reason"], str)
    assert rig.runtime.deactivated == []


@pytest.mark.asyncio
async def test_an_unknown_body_field_is_refused_rather_than_ignored(rig):
    async with client(rig) as http:
        for path in ("/api/plugins/extensions/consent", "/api/plugins/extensions/activate"):
            refused = await http.post(path, json={"manifest": DESCRIPTOR, "force": True}, headers=OWNER)
            assert refused.status_code == 422, path


@pytest.mark.asyncio
async def test_activation_reports_the_tools_it_proved(rig):
    async with client(rig) as http:
        activated = await http.post("/api/plugins/extensions/activate",
                                    json={"manifest": DESCRIPTOR}, headers=OWNER)
    assert activated.status_code == 200
    assert activated.json()["activation"]["callable_tools"] == ["boats.summarize"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [
    "consent_required", "consent_changed", "registration_mismatch",
    "package_unavailable", "attestation_mismatch", "extensions_disabled",
])
async def test_a_refused_activation_returns_a_bounded_reason_and_nothing_else(rig, reason):
    """Whatever the extension printed stays in the sandbox; only the code comes out."""
    rig.runtime.refusal = reason
    async with client(rig) as http:
        refused = await http.post("/api/plugins/extensions/activate",
                                  json={"manifest": DESCRIPTOR}, headers=OWNER)
    assert refused.status_code == 422
    assert refused.json() == {"ok": False, "reason": reason}


@pytest.mark.asyncio
async def test_a_hub_without_a_composed_extension_runtime_says_so(rig, monkeypatch):
    rig.orch.acquisition = SimpleNamespace(extensions=lambda: None)
    async with client(rig) as http:
        unavailable = await http.post("/api/plugins/extensions/activate",
                                      json={"manifest": DESCRIPTOR}, headers=OWNER)
    assert unavailable.status_code == 503
    assert unavailable.json() == {"ok": False, "reason": "extensions_unavailable"}


@pytest.mark.asyncio
async def test_consent_still_records_on_a_hub_with_no_acquisition_at_all(rig, monkeypatch):
    """Consent is a local decision. It does not require a runtime to exist yet."""
    monkeypatch.setattr(_component, "get_orch", lambda: None)
    async with client(rig) as http:
        granted = await http.post("/api/plugins/extensions/consent",
                                  json={"manifest": DESCRIPTOR}, headers=OWNER)
        revoked = await http.post("/api/plugins/extensions/consent",
                                  json={"manifest": DESCRIPTOR, "revoke": True}, headers=OWNER)
    assert granted.json()["consent"] == "granted"
    assert revoked.json()["ok"] is True and revoked.json()["revoked"] is True
