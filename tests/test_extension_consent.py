"""What the owner agreed an extension may declare, and the hash that pins it (H570).

Consent here is not a boolean. It is the SHA-256 of the exact declared surface the
owner saw, so the failure this file exists to prevent has a name: an extension
approved at 1.0.0 shipping 1.1.0 that also declares a command, and being treated as
still-consented because the id matched.

The other half is the fail-closed rule. Every way of failing to read the store —
missing, truncated, wrong version, a symlink, too large — is *not granted*. There is
deliberately no "unknown" state, because a runtime cannot act on one.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.core.extensions.consent import (
    CHANGED,
    GRANTED,
    NOT_GRANTED,
    ExtensionConsentStore,
    declared_digest,
)
from agents.core.extensions.manifest import parse_manifest
from agents.core.extensions.manifest_catalog import ExtensionManifestCatalog
from agents.core.routers import plugins


def descriptor(**overrides):
    value = {
        "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.0.0",
        "capabilities": ["tools"], "tools": ["summarize"], "commands": [], "events": [],
        "requires": {"extensions": {}, "python": {}},
    }
    value.update(overrides)
    capabilities = [name for name, declared in (
        ("tools", value["tools"]), ("commands", value["commands"]),
        ("events.observe", value["events"])) if declared]
    value.setdefault("capabilities", capabilities)
    value["capabilities"] = capabilities
    return parse_manifest(value)


@pytest.fixture()
def store(tmp_path):
    return ExtensionConsentStore(tmp_path / "consent.json")


# ── the digest ───────────────────────────────────────────────────────────────

def test_the_digest_covers_the_surface_an_owner_would_be_shown():
    base = descriptor()
    assert declared_digest(base) == declared_digest(descriptor())
    for changed in (descriptor(tools=["summarize", "translate"]),
                    descriptor(commands=["boats_summary"]),
                    descriptor(events=["tool.completed"]),
                    descriptor(id="ships")):
        assert declared_digest(changed) != declared_digest(base), changed


def test_a_patch_release_that_declares_the_same_surface_is_the_same_agreement():
    """Re-asking on every bugfix is how an owner learns to click through a consent
    screen without reading it. The version is not in the digest for that reason."""
    assert declared_digest(descriptor(version="1.0.1")) == declared_digest(descriptor())


# ── the states ───────────────────────────────────────────────────────────────

def test_nothing_is_granted_until_it_is(store):
    assert store.check(descriptor()).state == NOT_GRANTED
    assert store.granted_ids() == ()


def test_granting_records_exactly_these_declarations(store):
    manifest = descriptor()
    assert store.grant(manifest).state == GRANTED
    decision = store.check(manifest)
    assert decision.allowed and decision.granted_digest == declared_digest(manifest)
    assert store.granted_ids() == ("boats",)


def test_a_widened_declaration_is_changed_and_says_what_was_added(store):
    """The whole reason the record is a hash: this update must not pass as consented."""
    store.grant(descriptor())
    decision = store.check(descriptor(version="1.1.0", tools=["summarize"], commands=["boats_summary"]))
    assert decision.state == CHANGED and not decision.allowed
    assert decision.added == ("capability:commands", "command:boats_summary")
    assert decision.removed == ()


def test_a_narrowed_declaration_is_also_re_asked_rather_than_assumed_fine(store):
    store.grant(descriptor(tools=["summarize", "translate"]))
    decision = store.check(descriptor())
    assert decision.state == CHANGED
    assert decision.removed == ("tool:boats.translate",)


def test_consent_is_per_extension(store):
    store.grant(descriptor())
    assert store.check(descriptor(id="ships")).state == NOT_GRANTED


def test_revoking_removes_the_grant_and_reports_whether_there_was_one(store):
    store.grant(descriptor())
    assert store.revoke("boats") is True
    assert store.check(descriptor()).state == NOT_GRANTED
    assert store.revoke("boats") is False


def test_regranting_the_same_surface_is_idempotent(store):
    first = store.grant(descriptor())
    second = store.grant(descriptor())
    assert first.digest == second.digest and store.granted_ids() == ("boats",)


# ── fail closed ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("content", [
    "not json at all", "[]", "null", '{"grants": {}}',
    '{"consent_version": 99, "grants": {"boats": {"declared_digest": "x"}}}',
    '{"consent_version": 1, "grants": []}',
], ids=["garbage", "list", "null", "no-version", "wrong-version", "grants-not-object"])
def test_an_unreadable_store_is_not_a_granted_one(tmp_path, content):
    path = tmp_path / "consent.json"
    path.write_text(content, encoding="utf-8")
    assert ExtensionConsentStore(path).check(descriptor()).state == NOT_GRANTED


def test_a_row_without_a_real_digest_is_dropped_rather_than_trusted(tmp_path):
    path = tmp_path / "consent.json"
    path.write_text(json.dumps({"consent_version": 1, "grants": {
        "boats": {"declared_digest": "short"},
        "ships": {"granted": True},
    }}), encoding="utf-8")
    store = ExtensionConsentStore(path)
    assert store.granted_ids() == ()
    assert store.check(descriptor()).state == NOT_GRANTED


def test_an_oversized_store_is_not_a_granted_one(tmp_path):
    path = tmp_path / "consent.json"
    path.write_text(json.dumps({"consent_version": 1, "grants": {
        "boats": {"declared_digest": declared_digest(descriptor()), "pad": "x" * 300_000},
    }}), encoding="utf-8")
    assert ExtensionConsentStore(path).check(descriptor()).state == NOT_GRANTED


def test_a_symlinked_store_is_not_read(tmp_path):
    real = tmp_path / "elsewhere.json"
    real.write_text(json.dumps({"consent_version": 1, "grants": {
        "boats": {"declared_digest": declared_digest(descriptor())}}}), encoding="utf-8")
    link = tmp_path / "consent.json"
    link.symlink_to(real)
    assert ExtensionConsentStore(link).check(descriptor()).state == NOT_GRANTED


def test_a_grant_survives_a_reopen_and_the_write_is_atomic(tmp_path):
    path = tmp_path / "nested" / "consent.json"
    ExtensionConsentStore(path).grant(descriptor())
    assert ExtensionConsentStore(path).check(descriptor()).allowed
    assert sorted(p.name for p in path.parent.iterdir()) == [
        "consent.json", "manifest_catalog.json",
    ], "both durable records exist with no temp file left behind"


def test_owner_declaration_pins_are_visible_before_activation_and_survive_revoke(tmp_path):
    path = tmp_path / "extensions" / "consent.json"
    manifest = descriptor(requires={"extensions": {}, "python": {"Requests": "2.31.0"}})
    ExtensionConsentStore(path).grant(manifest)
    rows, errors = ExtensionManifestCatalog(path.with_name("manifest_catalog.json")).snapshot()
    assert errors == []
    assert rows == [{"id": "boats", "version": "1.0.0",
                     "python_requires": [["requests", "2.31.0"]]}]

    ExtensionConsentStore(path).revoke("boats")
    assert ExtensionManifestCatalog(path.with_name("manifest_catalog.json")).snapshot() == (rows, [])
    assert not ExtensionConsentStore(path).check(manifest).allowed


def test_same_consent_surface_refreshes_independent_dependency_pin_metadata(tmp_path):
    path = tmp_path / "extensions" / "consent.json"
    first = descriptor(requires={"extensions": {}, "python": {"requests": "2.31.0"}})
    second = descriptor(requires={"extensions": {}, "python": {"requests": "2.32.0"}})
    store = ExtensionConsentStore(path)
    assert declared_digest(first) == declared_digest(second)
    store.grant(first)
    store.grant(second)
    assert ExtensionManifestCatalog(path.with_name("manifest_catalog.json")).snapshot() == (
        [{"id": "boats", "version": "1.0.0", "python_requires": [["requests", "2.32.0"]]}],
        [],
    )


def test_catalog_write_failure_refuses_new_grant_before_consent_durability(tmp_path):
    path = tmp_path / "extensions" / "consent.json"
    path.parent.mkdir()
    path.with_name("manifest_catalog.json").write_text("broken", encoding="utf-8")
    store = ExtensionConsentStore(path)
    with pytest.raises(ValueError, match="manifest_catalog_corrupt"):
        store.grant(descriptor(requires={"extensions": {}, "python": {"requests": "2.31.0"}}))
    assert not path.exists()
    assert store.granted_ids() == ()


def test_catalog_metadata_alone_never_grants_consent(tmp_path):
    manifest = descriptor(requires={"extensions": {}, "python": {"requests": "2.31.0"}})
    path = tmp_path / "extensions" / "consent.json"
    ExtensionManifestCatalog(path.with_name("manifest_catalog.json")).record(manifest)
    assert ExtensionConsentStore(path).check(manifest).state == NOT_GRANTED


def test_explicit_owner_redeclaration_repairs_legacy_unreadable_consent(tmp_path):
    path = tmp_path / "extensions" / "consent.json"
    path.parent.mkdir()
    path.write_text("broken", encoding="utf-8")
    manifest = descriptor(requires={"extensions": {}, "python": {"requests": "2.31.0"}})
    store = ExtensionConsentStore(path)
    assert store.check(manifest).state == NOT_GRANTED
    assert store.grant(manifest).state == GRANTED
    assert store.check(manifest).allowed
    assert ExtensionManifestCatalog(path.with_name("manifest_catalog.json")).snapshot() == (
        [{"id": "boats", "version": "1.0.0", "python_requires": [["requests", "2.31.0"]]}],
        [],
    )


@pytest.mark.asyncio
async def test_http_owner_declaration_persists_pins_for_cli_shared_consent_path(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr(web, "USER_TOKEN", "extension-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "extension-admin")
    app = FastAPI()
    app.include_router(plugins.router)
    body = {
        "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.0.0",
        "capabilities": ["tools"], "tools": ["summarize"], "commands": [], "events": [],
        "requires": {"extensions": {}, "python": {"requests": "2.31.0"}},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("198.51.100.2", 1234)),
                                 base_url="http://test") as client:
        denied = await client.post("/api/plugins/extensions/consent", json={"manifest": body})
        assert denied.status_code == 401
        granted = await client.post("/api/plugins/extensions/consent", json={"manifest": body},
                                    headers={"X-User-Token": "extension-user",
                                             "X-Admin-Token": "extension-admin"})
        assert granted.status_code == 200 and granted.json()["consent"] == "granted"
    # The CLI sends this same validated descriptor to the same route.
    catalog = ExtensionManifestCatalog()
    assert catalog.snapshot() == ([{"id": "boats", "version": "1.0.0",
                                   "python_requires": [["requests", "2.31.0"]]}], [])


@pytest.mark.asyncio
async def test_http_grant_refuses_corrupt_catalog_without_creating_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setattr(web, "USER_TOKEN", "extension-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "extension-admin")
    path = tmp_path / "extensions" / "manifest_catalog.json"
    path.parent.mkdir()
    path.write_text("broken", encoding="utf-8")
    app = FastAPI()
    app.include_router(plugins.router)
    body = {
        "manifest_version": 1, "api_version": 1, "id": "boats", "version": "1.0.0",
        "capabilities": ["tools"], "tools": ["summarize"], "commands": [], "events": [],
        "requires": {"extensions": {}, "python": {"requests": "2.31.0"}},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("198.51.100.2", 1234)),
                                 base_url="http://test") as client:
        refused = await client.post("/api/plugins/extensions/consent", json={"manifest": body},
                                    headers={"X-User-Token": "extension-user",
                                             "X-Admin-Token": "extension-admin"})
    assert refused.status_code == 422
    assert refused.json() == {"ok": False, "reason": "manifest_catalog_corrupt"}
    assert not path.with_name("consent.json").exists()
