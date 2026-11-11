"""The scripted Hermes pin bump, offline: fake archives stand in for codeload."""

import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from agents.core.hermes_runtime import distribution, policy
from scripts import hermes_runtime_bump as bump

OLD, NEW = "a" * 40, "b" * 40
SCHEMA_REF = "#/components/schemas/"


def _contract(methods: dict[str, dict], *, schemas: dict | None = None, notifications=(), requests=()) -> bytes:
    components = dict(schemas or {})
    entries = []
    for name, params in methods.items():
        schema_name = name.replace(".", "_") + "Params"
        components.setdefault(schema_name, params)
        entries.append({"name": name, "summary": f"{name} summary",
                        "params": [{"name": "params", "schema": {"$ref": SCHEMA_REF + schema_name}}],
                        "result": {"name": "result", "schema": {"type": "object"}}})
    document = {"openrpc": "1.3.2", "info": {"title": "test", "version": "1"}, "methods": entries,
                "components": {"schemas": components},
                "x-server-requests": [{"name": name, "summary": "", "params": []} for name in requests],
                "x-notifications": [{"name": name, "summary": "", "params": []} for name in notifications]}
    return json.dumps(document, indent=2).encode()


def _archive(path: Path, commit: str, contract: bytes, *, recorded: str | None = None,
             extra: bytes = b"") -> Path:
    root = f"hermes-agent-{commit}"
    files = {"LICENSE": (b"MIT", 0o664), "bin/run": (b"#!/bin/sh\n" + extra, 0o775),
             bump.CONTRACT: (contract, 0o664)}
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT,
                      pax_headers={"comment": recorded or commit}) as tar:
        for name, (data, mode) in files.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
    return path


def _identity(archive: Path, commit: str, tmp: Path) -> dict:
    facts = bump.archive_facts(archive, commit)
    source = tmp / f"identity-{commit[:4]}"
    distribution._extract_archive(archive, source, facts["archive_root"], facts["executables"])
    return {"tree_sha1": distribution._git_tree_sha1(source), "source_sha256": distribution._source_sha256(source),
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "executables": facts["executables"]}


@pytest.fixture
def checkout(tmp_path):
    """A minimal Hub checkout pinned to OLD, plus archives for OLD and NEW."""
    root = tmp_path / "repo"
    runtime = root / "runtime/hermes"
    runtime.mkdir(parents=True)
    code = root / "agents/core/hermes_runtime"
    code.mkdir(parents=True)
    (code / "distribution.py").write_text(f'PINNED_COMMIT = "{OLD}"\n')
    (code / "worker.py").write_text(f'SOURCE_SHA = "{OLD}"\n')
    (runtime / "NOTICE.md").write_text(f"MIT\nCommit: {OLD}\n")
    archives = tmp_path / "archives"
    archives.mkdir()
    old_contract = _contract({"session.list": {"type": "object", "properties": {}},
                              "shell.exec": {"type": "object", "properties": {"command": {"type": "string"}}},
                              "gone.method": {"type": "object"}},
                             notifications=("message.delta",), requests=("approval",))
    new_contract = _contract({"session.list": {"type": "object", "properties": {}},
                              "shell.exec": {"type": "object", "properties": {"command": {"type": "string"},
                                                                               "cwd": {"type": "string"}}},
                              "future.effect": {"type": "object"}},
                             notifications=("message.delta", "tool.progress"), requests=("approval", "theme.pick"))
    old_archive = _archive(archives / OLD, OLD, old_contract)
    new_archive = _archive(archives / NEW, NEW, new_contract)
    old = _identity(old_archive, OLD, tmp_path)
    (runtime / "upstream.lock.json").write_text(json.dumps({
        "project": bump.PROJECT, "commit": OLD, "tree_sha1": old["tree_sha1"], "source_sha256": old["source_sha256"],
        "git_tree_sha1": "c" * 40, "archive_url": distribution.ARCHIVE_URL.format(commit=OLD),
        "archive_sha256": old["archive_sha256"], "archive_root": f"hermes-agent-{OLD}", "license": "MIT"}, indent=2) + "\n")
    (runtime / "executable-paths.json").write_text(json.dumps(old["executables"]))
    (runtime / "gateway-catalog.json").write_text(bump.render_catalog(bump.build_catalog(old_contract, OLD)))
    (runtime / "rpc-policy.json").write_text(json.dumps({"source_sha": OLD, "tiers": {
        "gone.method": 3, "session.list": 0, "shell.exec": 3}}, indent=2) + "\n")

    def fetch(commit, destination):
        shutil.copyfile(archives / commit, destination)
        return destination

    return {"root": root, "runtime": runtime, "archives": archives, "fetch": fetch,
            "new_contract": new_contract, "new_identity": _identity(new_archive, NEW, tmp_path)}


def _snapshot(root: Path) -> dict:
    return {path: path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _run(checkout, **kwargs):
    return bump.bump(NEW, fetch=checkout["fetch"], git_tree=lambda commit: "d" * 40, root=checkout["root"], **kwargs)


def test_bump_computes_every_lock_field_as_distribution_verifies_them(checkout, tmp_path):
    report = _run(checkout)
    lock = json.loads((checkout["runtime"] / "upstream.lock.json").read_text())
    identity = checkout["new_identity"]
    assert lock == report["lock"]
    assert lock["commit"] == NEW and lock["git_tree_sha1"] == "d" * 40
    assert lock["archive_url"] == f"https://codeload.github.com/NousResearch/hermes-agent/tar.gz/{NEW}"
    assert lock["archive_root"] == f"hermes-agent-{NEW}"
    assert {key: lock[key] for key in ("tree_sha1", "source_sha256", "archive_sha256")} == {
        key: identity[key] for key in ("tree_sha1", "source_sha256", "archive_sha256")}
    assert distribution.load_pin(checkout["runtime"] / "upstream.lock.json", commit=NEW) == lock
    # The written executable list restores modes so the runtime's own verification passes.
    assert json.loads((checkout["runtime"] / "executable-paths.json").read_text()) == ["bin/run"]
    source = tmp_path / "prepared"
    distribution._extract_archive(checkout["archives"] / NEW, source, lock["archive_root"], ["bin/run"])
    assert distribution.verify_source(source, lock)["tree_sha1"] == lock["tree_sha1"]
    # Every code anchor moved with the lock.
    for relative, pattern in bump._ANCHORS:
        assert pattern.format(commit=NEW) in (checkout["root"] / relative).read_text()


def test_catalog_generation_is_deterministic(checkout):
    _run(checkout)
    first = (checkout["runtime"] / "gateway-catalog.json").read_bytes()
    assert first == bump.render_catalog(bump.build_catalog(checkout["new_contract"], NEW)).encode()
    assert bump.render_catalog(bump.build_catalog(checkout["new_contract"], NEW)).encode() == first
    catalog = json.loads(first)
    assert catalog["contract_sha256"] == hashlib.sha256(checkout["new_contract"]).hexdigest()
    assert [method["name"] for method in catalog["methods"]] == ["session.list", "shell.exec", "future.effect"]
    assert catalog["methods"][1]["params"]["properties"]["cwd"] == {"type": "string"}


def test_new_methods_stay_unclassified_and_fail_closed(checkout, monkeypatch):
    report = _run(checkout)
    assert report["diff"]["methods"]["added"] == ["future.effect"]
    assert report["diff"]["methods"]["removed"] == ["gone.method"]
    assert report["diff"]["methods"]["params_changed"] == ["shell.exec"]
    assert report["diff"]["server_requests"]["added"] == ["theme.pick"]
    assert report["diff"]["notifications"]["added"] == ["tool.progress"]
    assert report["review"]["unclassified_methods"] == ["future.effect"]
    assert report["review"]["recheck_methods"] == ["shell.exec"]
    assert report["review"]["required"] is True
    written = json.loads((checkout["runtime"] / "rpc-policy.json").read_text())
    assert written == {"source_sha": OLD, "tiers": {"session.list": 0, "shell.exec": 3}}
    monkeypatch.setattr(policy, "CATALOG_FILE", checkout["runtime"] / "gateway-catalog.json")
    monkeypatch.setattr(policy, "POLICY_FILE", checkout["runtime"] / "rpc-policy.json")
    with pytest.raises(policy.RuntimeDenied, match="incomplete"):
        policy.catalog()
    # Classifying the method is not enough while the policy still attests the previous pin.
    written["tiers"]["future.effect"] = 3
    (checkout["runtime"] / "rpc-policy.json").write_text(json.dumps(written))
    with pytest.raises(policy.RuntimeDenied, match="incomplete"):
        policy.catalog()
    written["source_sha"] = NEW
    (checkout["runtime"] / "rpc-policy.json").write_text(json.dumps(written))
    assert policy.classify("rpc", "future.effect") == 3
    assert "UNCLASSIFIED" in bump.format_report(report)


def test_refuses_when_current_pin_archive_hash_differs(checkout):
    before = _snapshot(checkout["root"])
    _archive(checkout["archives"] / OLD, OLD, b"{}", extra=b"tampered")
    with pytest.raises(bump.BumpRefused, match="pinned SHA-256"):
        _run(checkout)
    assert _snapshot(checkout["root"]) == before


def test_refuses_archive_that_records_another_commit(checkout):
    before = _snapshot(checkout["root"])
    _archive(checkout["archives"] / NEW, NEW, checkout["new_contract"], recorded="e" * 40)
    with pytest.raises(bump.BumpRefused, match="requested commit"):
        _run(checkout)
    assert _snapshot(checkout["root"]) == before


def test_refuses_hand_edited_catalog(checkout):
    path = checkout["runtime"] / "gateway-catalog.json"
    edited = json.loads(path.read_text())
    edited["methods"].pop()
    path.write_text(bump.render_catalog(edited))
    with pytest.raises(bump.BumpRefused, match="by hand"):
        _run(checkout)


def test_dry_run_writes_nothing(checkout):
    before = _snapshot(checkout["root"])
    report = _run(checkout, write=False)
    assert report["lock"]["commit"] == NEW
    assert _snapshot(checkout["root"]) == before


def test_diff_sees_changes_inside_referenced_schemas():
    old = _contract({"prompt.submit": {"type": "object", "properties": {"opts": {"$ref": SCHEMA_REF + "Opts"}}}},
                    schemas={"Opts": {"type": "object", "properties": {"a": {"type": "string"}}}})
    new = _contract({"prompt.submit": {"type": "object", "properties": {"opts": {"$ref": SCHEMA_REF + "Opts"}}}},
                    schemas={"Opts": {"type": "object", "properties": {"a": {"type": "string"},
                                                                       "delete_all": {"type": "boolean"}}}})
    assert bump.contract_diff(old, new)["methods"]["params_changed"] == ["prompt.submit"]
    # The catalog keeps the top-level schema only, so the diff, not the catalog, carries this.
    assert bump.build_catalog(old, OLD)["methods"] == bump.build_catalog(new, OLD)["methods"]


def test_refuses_archive_with_a_link_before_extracting(checkout, tmp_path):
    path = checkout["archives"] / NEW
    _archive(path, NEW, checkout["new_contract"])
    with tarfile.open(path, "r:gz") as tar:
        members = [(member, tar.extractfile(member).read() if member.isfile() else None) for member in tar]
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": NEW}) as tar:
        for member, data in members:
            tar.addfile(member, io.BytesIO(data) if data is not None else None)
        link = tarfile.TarInfo(f"hermes-agent-{NEW}/escape")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)
    before = _snapshot(checkout["root"])
    with pytest.raises(bump.BumpRefused, match="symlink"):
        _run(checkout)
    assert _snapshot(checkout["root"]) == before


def test_commit_must_be_a_full_sha(checkout):
    with pytest.raises(bump.BumpRefused, match="40-character"):
        bump.bump("main", fetch=checkout["fetch"], git_tree=lambda commit: "d" * 40, root=checkout["root"])
