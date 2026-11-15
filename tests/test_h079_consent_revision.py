"""Private consent grant epochs for H079 lifecycle fencing."""

import hashlib
import json
import re
import threading
from contextlib import contextmanager

import pytest

from agents.core.extensions import consent as consent_module
from agents.core.extensions.consent import (
    CHANGED,
    GRANTED,
    NOT_GRANTED,
    ExtensionConsentStore,
    declared_digest,
)
from agents.core.extensions.manifest import parse_manifest
from agents.core.extensions.manifest_catalog import ExtensionManifestCatalog
from agents.core.extensions.store_lock import StoreLockError


def descriptor(**overrides):
    value = {
        "manifest_version": 1,
        "api_version": 1,
        "id": "boats",
        "version": "1.0.0",
        "capabilities": ["tools"],
        "tools": ["summarize"],
        "commands": [],
        "events": [],
        "requires": {"extensions": {}, "python": {}},
    }
    value.update(overrides)
    value["capabilities"] = [name for name, declared in (
        ("tools", value["tools"]), ("commands", value["commands"]),
        ("events.observe", value["events"])) if declared]
    return parse_manifest(value)


def test_grant_revision_persists_and_same_digest_grant_is_idempotent(tmp_path):
    path = tmp_path / "consent.json"
    manifest = descriptor()
    first = ExtensionConsentStore(path).grant(manifest)
    assert first.grant_revision is not None
    assert re.fullmatch(r"[0-9a-f]{64}", first.grant_revision)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["grants"]["boats"]["grant_revision"] == first.grant_revision
    reopened = ExtensionConsentStore(path).check(manifest)
    assert reopened.state == GRANTED
    assert reopened.grant_revision == first.grant_revision

    second = ExtensionConsentStore(path).grant(manifest)
    assert second.grant_revision == first.grant_revision
    assert ExtensionConsentStore(path).check(manifest).grant_revision == first.grant_revision


def test_revoke_then_regrant_same_digest_creates_new_revision(tmp_path):
    store = ExtensionConsentStore(tmp_path / "consent.json")
    manifest = descriptor()
    first = store.grant(manifest)
    assert store.revoke("boats")
    assert store.check(manifest).grant_revision is None
    second = store.grant(manifest)
    assert second.grant_revision != first.grant_revision
    assert ExtensionConsentStore(store._path).check(manifest).grant_revision == second.grant_revision


def _legacy_revision(row):
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b"nerva-extension-consent-legacy-revision-v1\0" + canonical).hexdigest()


def test_valid_legacy_grant_remains_allowed_with_deterministic_private_revision(tmp_path):
    path = tmp_path / "consent.json"
    manifest = descriptor()
    row = {"declared_digest": declared_digest(manifest), "version": "1.0.0",
           "declarations": ["capability:tools", "tool:boats.summarize"]}
    path.write_text(json.dumps({"consent_version": 1, "grants": {"boats": row}}), encoding="utf-8")

    first = ExtensionConsentStore(path).check(manifest)
    second = ExtensionConsentStore(path).check(manifest)
    assert first.state == GRANTED and second.state == GRANTED
    assert first.grant_revision == second.grant_revision == _legacy_revision(row)
    assert json.loads(path.read_text(encoding="utf-8"))["grants"]["boats"] == row

    upgraded = ExtensionConsentStore(path).grant(manifest)
    assert upgraded.grant_revision != first.grant_revision
    assert json.loads(path.read_text(encoding="utf-8"))["grants"]["boats"]["grant_revision"] == upgraded.grant_revision


@pytest.mark.parametrize("bad_revision", ["A" * 64, "a" * 63, "g" * 64, 7, None])
def test_malformed_explicit_revision_is_not_granted_and_owner_grant_repairs_it(tmp_path, bad_revision):
    path = tmp_path / "consent.json"
    manifest = descriptor()
    row = {"declared_digest": declared_digest(manifest), "version": "1.0.0",
           "declarations": ["capability:tools", "tool:boats.summarize"],
           "grant_revision": bad_revision}
    path.write_text(json.dumps({"consent_version": 1, "grants": {"boats": row}}), encoding="utf-8")

    refused = ExtensionConsentStore(path).check(manifest)
    assert refused.state == NOT_GRANTED
    assert refused.grant_revision is None
    repaired = ExtensionConsentStore(path).grant(manifest)
    assert repaired.state == GRANTED and re.fullmatch(r"[0-9a-f]{64}", repaired.grant_revision)
    assert repaired.grant_revision != row["grant_revision"]


def test_changed_and_not_granted_decisions_have_no_revision_and_public_dict_is_unchanged(tmp_path):
    store = ExtensionConsentStore(tmp_path / "consent.json")
    manifest = descriptor()
    before = store.check(manifest)
    assert before.state == NOT_GRANTED and before.grant_revision is None
    assert set(before.as_dict()) == {
        "consent", "declared_digest", "granted_digest", "added_declarations", "removed_declarations",
    }

    store.grant(manifest)
    changed = store.check(descriptor(commands=["boats_summary"]))
    assert changed.state == CHANGED and changed.grant_revision is None
    assert set(changed.as_dict()) == set(before.as_dict())


def test_grant_and_revoke_serialize_across_store_instances(tmp_path, monkeypatch):
    path = tmp_path / "consent.json"
    grant_store = ExtensionConsentStore(path)
    revoke_store = ExtensionConsentStore(path)
    manifest = descriptor()
    entered_catalog = threading.Event()
    release_catalog = threading.Event()
    revoke_started = threading.Event()
    revoke_done = threading.Event()
    grant_results, revoke_results, failures = [], [], []
    original_record = ExtensionManifestCatalog.record

    def pause_during_catalog_write(catalog, candidate):
        if candidate.id == manifest.id:
            entered_catalog.set()
            if not release_catalog.wait(5):
                raise AssertionError("timed out waiting to finish grant catalog write")
        return original_record(catalog, candidate)

    monkeypatch.setattr(ExtensionManifestCatalog, "record", pause_during_catalog_write)

    def run_grant():
        try:
            grant_results.append(grant_store.grant(manifest))
        except Exception as exc:
            failures.append(exc)

    def run_revoke():
        revoke_started.set()
        try:
            revoke_results.append(revoke_store.revoke(manifest.id))
        except Exception as exc:
            failures.append(exc)
        finally:
            revoke_done.set()

    grant_thread = threading.Thread(target=run_grant)
    grant_thread.start()
    assert entered_catalog.wait(5)
    revoke_thread = threading.Thread(target=run_revoke)
    revoke_thread.start()
    assert revoke_started.wait(5)
    # The grant is paused after its read. A concurrent revoke must wait for its
    # mutation lock, then observe and remove the newly written row.
    assert not revoke_done.wait(0.2)
    release_catalog.set()
    grant_thread.join(5)
    revoke_thread.join(5)
    assert not grant_thread.is_alive() and not revoke_thread.is_alive()
    assert failures == []
    assert len(grant_results) == 1 and revoke_results == [True]
    assert ExtensionConsentStore(path).check(manifest).state == NOT_GRANTED


def test_distinct_concurrent_grants_from_separate_instances_are_not_lost(tmp_path):
    path = tmp_path / "consent.json"
    stores = [ExtensionConsentStore(path), ExtensionConsentStore(path)]
    manifests = [descriptor(id="boats"), descriptor(id="ships")]
    start = threading.Barrier(3)
    results, failures = [], []

    def grant(index):
        try:
            start.wait(5)
            results.append(stores[index].grant(manifests[index]))
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=grant, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    start.wait(5)
    for thread in threads:
        thread.join(5)
    assert all(not thread.is_alive() for thread in threads)
    assert failures == [] and len(results) == 2
    reopened = ExtensionConsentStore(path)
    assert reopened.granted_ids() == ("boats", "ships")
    assert all(reopened.check(manifest).allowed for manifest in manifests)


def test_read_only_check_does_not_create_store_or_lock_file(tmp_path):
    path = tmp_path / "nested" / "consent.json"
    assert ExtensionConsentStore(path).check(descriptor()).state == NOT_GRANTED
    assert not path.exists()
    assert not path.with_name(path.name + ".lock").exists()
    assert not path.parent.exists()


def test_lock_failures_are_mapped_to_bounded_consent_error(tmp_path, monkeypatch):
    @contextmanager
    def unavailable(_path):
        raise StoreLockError()
        yield  # pragma: no cover

    monkeypatch.setattr(consent_module, "locked_store", unavailable)
    store = ExtensionConsentStore(tmp_path / "consent.json")
    with pytest.raises(ValueError, match="^consent_unavailable$"):
        store.grant(descriptor())
    with pytest.raises(ValueError, match="^consent_unavailable$"):
        store.revoke("boats")
