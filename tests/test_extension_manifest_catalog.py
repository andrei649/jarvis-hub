"""Persisted extension dependency pins remain inspectable without activation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.extensions.consent import declared_digest
from agents.core.extensions.manifest import ExtensionManifest, parse_manifest
from agents.core.extensions.runtime import ExtensionRuntime, ExtensionRuntimeError


def _manifest(*, version="1.0.0", python=None):
    return parse_manifest({
        "manifest_version": 1, "api_version": 1, "id": "boats", "version": version,
        "capabilities": [], "tools": [], "commands": [], "events": [],
        "requires": {"extensions": {}, "python": python or {}},
    })


def _catalog(tmp_path):
    from agents.core.extensions.manifest_catalog import ExtensionManifestCatalog

    return ExtensionManifestCatalog(tmp_path / "extensions" / "manifest_catalog.json")


def test_default_catalog_path_uses_profile_data_path_without_creating_it(tmp_path, monkeypatch):
    from agents.core.extensions.manifest_catalog import ExtensionManifestCatalog

    monkeypatch.setattr("agents.core.paths.data_path",
                        lambda *parts: tmp_path.joinpath("profile", *parts))
    catalog = ExtensionManifestCatalog()
    assert catalog.path == tmp_path / "profile" / "extensions" / "manifest_catalog.json"
    assert catalog.snapshot() == ([], [])
    assert not (tmp_path / "profile").exists()


def test_record_update_digest_and_deactivation_independence(tmp_path):
    catalog = _catalog(tmp_path)
    first = _manifest(python={"Requests": "2.31.0"})
    catalog.record(first)
    assert catalog.snapshot() == ([{
        "id": "boats", "version": "1.0.0", "python_requires": [["requests", "2.31.0"]],
    }], [])
    stored = json.loads(catalog.path.read_text())
    assert stored["rows"][0]["manifest_digest"] != declared_digest(first)
    digest_before = stored["rows"][0]["manifest_digest"]

    catalog.record(_manifest(version="1.0.1", python={"Requests": "2.32.0"}))
    assert catalog.snapshot()[0][0]["python_requires"] == [["requests", "2.32.0"]]
    assert json.loads(catalog.path.read_text())["rows"][0]["manifest_digest"] != digest_before
    # Deactivation is not uninstall; only explicit removal erases metadata.
    catalog.remove("boats")
    assert catalog.snapshot() == ([], [])


def test_fresh_missing_legacy_missing_and_corrupt_are_distinct(tmp_path):
    catalog = _catalog(tmp_path)
    assert catalog.snapshot() == ([], [])
    assert not catalog.path.parent.exists(), "read-only inventory must not create a profile"

    catalog.path.parent.mkdir()
    (catalog.path.parent / "consent.json").write_text(json.dumps({
        "consent_version": 1, "grants": {"boats": {"declared_digest": "a" * 64}},
    }))
    assert catalog.snapshot() == ([], [{
        "surface": "extension", "reason": "legacy_manifest_metadata_missing",
        "coverage_unavailable": True,
    }])

    catalog.path.write_text("{bad json")
    assert catalog.snapshot() == ([], [{
        "surface": "extension", "reason": "manifest_catalog_corrupt",
        "coverage_unavailable": True,
    }])
    with pytest.raises(ValueError, match="manifest_catalog_corrupt"):
        catalog.record(_manifest())


def test_legacy_profile_remains_visibly_partial_after_one_registered_extension(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.path.parent.mkdir()
    (catalog.path.parent / "consent.json").write_text(json.dumps({
        "consent_version": 1,
        "grants": {"boats": {"declared_digest": "a" * 64},
                   "ships": {"declared_digest": "b" * 64}},
    }))
    catalog.record(_manifest())
    rows, errors = catalog.snapshot()
    assert [row["id"] for row in rows] == ["boats"]
    assert errors == [{"surface": "extension", "reason": "legacy_manifest_metadata_missing",
                       "coverage_unavailable": True}]


def test_bounded_rows_pins_and_file_read_refuse_without_partial_write(tmp_path):
    from agents.core.extensions.manifest_catalog import MAX_CATALOG_BYTES

    catalog = _catalog(tmp_path)
    malformed = ExtensionManifest("boats", "1.0.0", (), (), (), (), (),
                                  tuple((f"dep{n}", "1.0.0") for n in range(65)))
    with pytest.raises(ValueError, match="invalid_dependencies"):
        catalog.record(malformed)
    assert not catalog.path.exists()

    catalog.record(_manifest())
    original = catalog.path.read_bytes()
    catalog.path.write_bytes(b"x" * (MAX_CATALOG_BYTES + 1))
    assert catalog.snapshot()[1][0]["reason"] == "manifest_catalog_too_large"
    with pytest.raises(ValueError, match="manifest_catalog_too_large"):
        catalog.record(_manifest(version="1.0.1"))
    assert catalog.path.read_bytes() == b"x" * (MAX_CATALOG_BYTES + 1)
    assert original != catalog.path.read_bytes()


def test_digest_mismatch_and_symlink_refused(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.record(_manifest(python={"requests": "2.31.0"}))
    stored = json.loads(catalog.path.read_text())
    stored["rows"][0]["python_requires"] = [["requests", "2.32.0"]]
    catalog.path.write_text(json.dumps(stored))
    assert catalog.snapshot()[1][0]["reason"] == "manifest_catalog_corrupt"

    catalog.path.unlink()
    target = tmp_path / "target.json"
    target.write_text("private")
    catalog.path.symlink_to(target)
    assert catalog.snapshot()[1][0]["reason"] == "manifest_catalog_unreadable"
    with pytest.raises(ValueError, match="manifest_catalog_unreadable"):
        catalog.record(_manifest())
    assert target.read_text() == "private"


def test_capacity_and_atomic_replace_failure_preserve_previous_snapshot(tmp_path, monkeypatch):
    catalog = _catalog(tmp_path)
    for number in range(128):
        manifest = _manifest()
        manifest = ExtensionManifest(f"ext{number}", manifest.version, (), (), (), (), (), ())
        catalog.record(manifest)
    before = catalog.path.read_bytes()
    with pytest.raises(ValueError, match="extension_capacity"):
        catalog.record(_manifest())
    assert catalog.path.read_bytes() == before

    def refused_replace(_source, _target):
        raise OSError("disk unavailable")

    monkeypatch.setattr("agents.core.extensions.manifest_catalog.os.replace", refused_replace)
    with pytest.raises(OSError, match="disk unavailable"):
        catalog.remove("ext0")
    assert catalog.path.read_bytes() == before
    assert list(catalog.path.parent.glob("*.tmp")) == []


def _runtime(tmp_path, catalog):
    runtime = ExtensionRuntime(
        packages=object(), profile=SimpleNamespace(timeout_seconds=1, max_output_bytes=1024),
        runtime_root=tmp_path / "runs", runner=object(), consent=object(),
        catalog=catalog, enabled=lambda: True,
    )
    runtime._require_consent = lambda _manifest: None
    runtime._require_package = lambda _manifest: SimpleNamespace(package_hash="a" * 64,
                                                                  version="1.0.0")
    async def registered(_record, **_kwargs):
        return {"registered": {"tools": [], "commands": [], "events": []}}
    runtime._run = registered
    return runtime


def test_runtime_records_only_after_successful_registration_and_keeps_deactivated_metadata(tmp_path):
    catalog = _catalog(tmp_path)
    runtime = _runtime(tmp_path, catalog)
    manifest = _manifest(python={"requests": "2.31.0"})
    asyncio.run(runtime.activate(manifest))
    assert catalog.snapshot()[0][0]["python_requires"] == [["requests", "2.31.0"]]
    assert asyncio.run(runtime.deactivate("boats")) is True
    assert catalog.snapshot()[0][0]["id"] == "boats"


def test_failed_registration_or_catalog_write_has_no_activation_effect(tmp_path):
    catalog = _catalog(tmp_path)
    runtime = _runtime(tmp_path, catalog)
    manifest = _manifest()

    async def mismatch(_record, **_kwargs):
        return {"registered": {"tools": ["boats.extra"], "commands": [], "events": []}}
    runtime._run = mismatch
    with pytest.raises(ExtensionRuntimeError, match="registration_mismatch"):
        asyncio.run(runtime.activate(manifest))
    assert catalog.snapshot() == ([], [])

    runtime = _runtime(tmp_path, catalog)
    catalog.path.parent.mkdir(parents=True, exist_ok=True)
    catalog.path.write_text("broken")
    exposed = []
    runtime._expose = lambda activation: exposed.append(activation)
    with pytest.raises(ExtensionRuntimeError, match="manifest_catalog_unavailable"):
        asyncio.run(runtime.activate(manifest))
    assert runtime.active() == ()
    assert runtime.callable_tools() == ()
    assert exposed == [], "a failed catalog write must refuse before RPC exposure"
