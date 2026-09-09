"""Doctor observes declarations and existing acquisition state without activating it."""

import importlib
import io
import json
import os
import sys
from types import SimpleNamespace

import httpx
import pytest

from agents.cli.nerva import Context, main
from tests.test_extension_manifest import descriptor


def doctor():
    return importlib.import_module("agents.core.extensions.doctor")


def write_descriptor(root, name="boats", **changes):
    path = root / (name + ".json")
    path.write_text(json.dumps(descriptor(name, **changes)), encoding="utf-8")
    return path


def test_dependency_check_reads_distribution_metadata_without_importing_package(tmp_path, monkeypatch):
    package = tmp_path / "nerva_extension_test_pkg.py"
    package.write_text("raise AssertionError('doctor must never import candidates')")
    dist = tmp_path / "nerva_extension_test_pkg-1.2.3.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: nerva-extension-test-pkg\nVersion: 1.2.3\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    manifest = write_descriptor(tmp_path, requires={"extensions": {}, "python": {"nerva-extension-test-pkg": "1.2.3"}})
    before = set(tmp_path.rglob("*"))
    report = doctor().doctor_paths([manifest])
    assert report["ok"] is True
    assert report["extensions"][0]["python_dependencies"] == [{"distribution": "nerva-extension-test-pkg", "required": "1.2.3", "installed": "1.2.3", "satisfied": True}]
    assert "nerva_extension_test_pkg" not in sys.modules
    assert set(tmp_path.rglob("*")) == before
    assert report["extensions"][0]["callable_tools"] == []
    assert report["extensions"][0]["execution_available"] is False


def test_missing_dependencies_propagate_to_dependents_without_installation(tmp_path):
    base = write_descriptor(tmp_path, "base", requires={"extensions": {}, "python": {"nerva-absent-extension-fixture": "1.0"}})
    child = write_descriptor(tmp_path, requires={"extensions": {"base": "1.0.0"}, "python": {}})
    report = doctor().doctor_paths([child, base])
    assert report["ok"] is False
    assert report["order"] == ["base", "boats"]
    by_id = {row["id"]: row for row in report["extensions"]}
    assert "python_dependency_missing" in by_id["base"]["issues"]
    assert "extension_dependency_unavailable" in by_id["boats"]["issues"]
    assert all(row["callable_tools"] == [] and row["callable_commands"] == [] for row in by_id.values())


def test_invalid_batch_has_no_partial_callable_catalog(tmp_path):
    good = write_descriptor(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text('{"invalid": "candidate-controlled text"}')
    report = doctor().doctor_paths([good, bad])
    assert report["ok"] is False
    assert report["errors"] == [{"index": 1, "reason": "invalid_manifest_fields"}]
    assert report["extensions"] == []
    assert "candidate-controlled text" not in json.dumps(report)


def test_unreadable_descriptor_is_loaded_once(monkeypatch):
    calls = []

    def unstable(path):
        calls.append(path)
        if len(calls) == 1:
            raise doctor().ManifestError("manifest_unreadable")
        return object()

    monkeypatch.setattr(doctor(), "load_manifest", unstable)
    report = doctor().doctor_paths(["changing.json"])
    assert report["errors"] == [{"index": 0, "reason": "manifest_unreadable"}]
    assert calls == ["changing.json"]


@pytest.mark.parametrize("response", [None, [], "bad", {}, {"mode": "inspection_only", "extensions": "bad"}])
def test_cli_list_rejects_malformed_hub_response(response):
    calls = []

    def get(path):
        calls.append(path)
        return response

    context = Context(environ={}, out=io.StringIO(), err=io.StringIO(),
                      client_factory=lambda _: SimpleNamespace(get=get))
    assert main(["extensions", "list", "--json"], context=context) == 1
    assert calls == ["/api/plugins/extensions"]


def test_cli_list_reports_an_honest_empty_inspection():
    report = {"mode": "inspection_only", "reason": "acquisition_not_composed", "extensions": []}
    out = io.StringIO()
    context = Context(environ={}, out=out, err=io.StringIO(),
                      client_factory=lambda _: SimpleNamespace(get=lambda path: report))
    assert main(["extensions", "list", "--json"], context=context) == 0
    assert json.loads(out.getvalue()) == report


def test_distribution_version_mismatch_is_cached_and_not_satisfied(tmp_path, monkeypatch):
    calls = []

    def version(distribution):
        calls.append(distribution)
        return "2.0.0"

    monkeypatch.setattr(doctor().metadata, "version", version)
    paths = [write_descriptor(tmp_path, name, requires={"extensions": {}, "python": {"package": "1.0.0"}})
             for name in ("base", "boats")]
    report = doctor().doctor_paths(paths)
    assert report["ok"] is False
    assert calls == ["package"]
    assert all(row["issues"] == ["python_version_mismatch"] for row in report["extensions"])


def test_acquisition_inspection_is_bounded_and_sanitizes_registry_errors():
    def broken(**_kwargs):
        raise RuntimeError("secret candidate content")

    runtime = SimpleNamespace(is_enabled=lambda: True, package_store=SimpleNamespace(list_records=broken))
    report = doctor().inspect_acquisition(runtime)
    assert report == {"mode": "inspection_only", "reason": "acquisition_inspection_unavailable", "extensions": []}
    runtime.package_store.list_records = lambda **kwargs: [object()] * 129
    assert doctor().inspect_acquisition(runtime)["reason"] == "extension_capacity"


@pytest.mark.parametrize("capacity", [False, True])
def test_cli_list_fails_when_the_inspector_cannot_read_the_catalog(capacity):
    def records(**_kwargs):
        if capacity:
            return [object()] * 129
        raise OSError("unreadable registry")

    runtime = SimpleNamespace(is_enabled=lambda: True, package_store=SimpleNamespace(list_records=records))
    report = doctor().inspect_acquisition(runtime)
    out = io.StringIO()
    context = Context(environ={}, out=out, err=io.StringIO(),
                      client_factory=lambda _: SimpleNamespace(get=lambda path: report))
    assert main(["extensions", "list", "--json"], context=context) == 1
    assert json.loads(out.getvalue()) == report


def test_cli_doctor_is_offline_read_only_and_has_truthful_exit_codes(tmp_path):
    path = write_descriptor(tmp_path)
    def no_network(_env):
        pytest.fail("offline doctor contacted the hub")
    out = io.StringIO()
    context = Context(environ={}, out=out, err=io.StringIO(), client_factory=no_network)
    assert main(["extensions", "doctor", str(path), "--json"], context=context) == 0
    report = json.loads(out.getvalue())
    assert report["extensions"][0]["reason"] == "sdk_dispatch_unavailable"
    out.seek(0)
    out.truncate()
    assert main(["extensions", "doctor", str(path.parent / "absent.json"), "--json"], context=context) == 1
    assert json.loads(out.getvalue())["ok"] is False


def test_unavailable_and_disabled_acquisition_inspection_do_not_initialize_stores(tmp_path):
    from agents.core.acquisition.runtime import AcquisitionRuntime
    runtime = AcquisitionRuntime(root=tmp_path / "must_not_exist")
    report = doctor().inspect_acquisition(runtime)
    assert report["reason"] == "acquisition_disabled"
    assert report["extensions"] == []
    assert not (tmp_path / "must_not_exist").exists()
    enabled = AcquisitionRuntime(root=tmp_path / "also_absent", enabled=lambda: True)
    assert doctor().inspect_acquisition(enabled)["reason"] == "acquisition_not_composed"
    assert not (tmp_path / "also_absent").exists()
    assert doctor().inspect_acquisition(None)["reason"] == "acquisition_unavailable"


@pytest.mark.asyncio
async def test_signed_acquired_projection_stays_inspection_only_and_refuses_tamper(tmp_path):
    from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
    from agents.core.acquisition.package_store import AcquiredPackageStore
    from tests.test_h32_promotion import _verified_artifact

    _, _, package, _, receipt, quarantine = await _verified_artifact(tmp_path)
    keys = ManagedSigningKeyStore(root=tmp_path / "keys")
    keys.provision(key_id="owner", version=1, key=b"k" * 32)
    packages = AcquiredPackageStore(root=tmp_path / "packages", signing=keys)
    record = packages.install(package=package, receipt=receipt, version="0.1.0")
    runtime = SimpleNamespace(is_enabled=lambda: True, package_store=packages)
    before = quarantine.get_record(package.artifact_id)
    row = doctor().inspect_acquisition(runtime)["extensions"][0]
    assert row["signature_verified"] is True
    assert row["approval_verified"] is False
    assert row["quarantine_state"] == "not_inspected"
    assert row["source"] == "acquired_manifest_projection"
    assert row["declared_tools"] == [package.name + ".run"]
    assert row["callable_tools"] == []
    assert row["reason"] == "sdk_dispatch_unavailable"
    assert quarantine.get_record(package.artifact_id) == before
    os.chmod(record.path / "main.py", 0o600)
    (record.path / "main.py").write_text("raise AssertionError('tampered package must not import')")
    row = doctor().inspect_acquisition(runtime)["extensions"][0]
    assert row["signature_verified"] is False
    assert row["reason"] == "acquired_integrity_unverified"
    packages.revoke(package.name)
    row = doctor().inspect_acquisition(runtime)["extensions"][0]
    assert row["reason"] == "acquired_inactive"
    assert row["callable_tools"] == []


@pytest.mark.asyncio
async def test_inspection_endpoint_requires_user_identity_and_never_initializes_runtime(monkeypatch, tmp_path):
    from fastapi import FastAPI

    from agents import web
    from agents.core.acquisition.runtime import AcquisitionRuntime
    from agents.core.routers import plugins

    runtime = AcquisitionRuntime(root=tmp_path / "absent", enabled=lambda: True)
    monkeypatch.setattr(web, "orch", SimpleNamespace(acquisition=runtime, permission_gate=None))
    monkeypatch.setattr(web, "USER_TOKEN", "extension-test-token")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "")
    app = FastAPI()
    app.include_router(plugins.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("198.51.100.2", 1234)), base_url="http://test") as client:
        assert (await client.get("/api/plugins/extensions")).status_code == 401
        allowed = await client.get("/api/plugins/extensions", headers={"X-User-Token": "extension-test-token"})
        assert allowed.status_code == 200
        assert allowed.json()["reason"] == "acquisition_not_composed"
        assert allowed.json()["extensions"] == []
        public = await client.get("/plugins")
        assert public.json() == {"plugins": [], "total": 0}
        monkeypatch.setattr(web, "orch", None)
        unavailable = await client.get("/api/plugins/extensions", headers={"X-User-Token": "extension-test-token"})
        assert unavailable.status_code == 503
        assert unavailable.json() == {"error": "extension acquisition not available"}
        monkeypatch.setattr(web, "USER_TOKEN", "")
        assert (await client.get("/api/plugins/extensions")).status_code == 403
    assert not (tmp_path / "absent").exists()
