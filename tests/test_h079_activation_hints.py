import hashlib
import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import agents.core.extensions.activation_hints as activation_hints
from agents.core.extensions.activation_hints import (
    ActivationHintStore,
    ActivationHintStoreError,
)
from agents.core.extensions.consent import declared_digest
from agents.core.extensions.manifest import ExtensionManifest, parse_manifest

REVISION = "9" * 64


def manifest(extension_id="demo", *, commands=("zeta", "alpha")):
    value = {
        "manifest_version": 1,
        "api_version": 1,
        "id": extension_id,
        "version": "1.2.3",
        "capabilities": ["commands"] if commands else [],
        "tools": [],
        "commands": list(commands),
        "events": [],
        "requires": {"extensions": {}, "python": {}},
    }
    return value


def test_put_and_read_roundtrip_stores_normalized_complete_manifest(tmp_path):
    path = tmp_path / "activation_hints.json"
    store = ActivationHintStore(path)
    store.put(manifest(), "a" * 64, REVISION)

    rows = store.read_all()
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row.manifest, ExtensionManifest)
    assert row.manifest.id == "demo"
    assert row.manifest.commands == ("alpha", "zeta")
    assert row.manifest.version == "1.2.3"
    assert row.package_hash == "a" * 64
    assert row.declared_digest == declared_digest(row.manifest)
    assert row.grant_revision == REVISION
    stored = json.loads(path.read_text())
    assert stored["hints"][0]["manifest"]["commands"] == ["alpha", "zeta"]
    assert stored["hints"][0]["grant_revision"] == REVISION
    assert set(stored) == {"version", "hints"}
    assert path.stat().st_mode & 0o777 == 0o600


def test_put_rejects_forged_manifest_dataclass(tmp_path):
    forged = ExtensionManifest("demo", "not-a-version", (), (), (), (), (), ())
    with pytest.raises(ActivationHintStoreError):
        ActivationHintStore(tmp_path / "hints.json").put(forged, "a" * 64, REVISION)


def test_put_replaces_same_id_and_remove_reports_actual_change(tmp_path):
    store = ActivationHintStore(tmp_path / "hints.json")
    store.put(manifest(), "a" * 64, REVISION)
    store.put({**manifest(), "version": "2.0.0"}, "b" * 64, "8" * 64)
    assert len(store.read_all()) == 1
    assert store.read_all()[0].package_hash == "b" * 64
    assert store.remove("demo") is True
    assert store.remove("demo") is False
    assert store.read_all() == ()


@pytest.mark.parametrize("value", ["A" * 64, "0" * 63, "g" * 64, 5, None])
def test_put_requires_exact_lowercase_sha256(value, tmp_path):
    store = ActivationHintStore(tmp_path / "hints.json")
    with pytest.raises(ActivationHintStoreError):
        store.put(manifest(), value, REVISION)
    assert store.read_all() == ()


def test_strict_schema_duplicate_and_digest_validation(tmp_path):
    path = tmp_path / "hints.json"
    store = ActivationHintStore(path)
    store.put(manifest(), "c" * 64, REVISION)
    data = json.loads(path.read_text())
    data["hints"][0]["manifest"]["surprise"] = True
    path.write_text(json.dumps(data))
    assert store.read_all() == ()
    with pytest.raises(ActivationHintStoreError):
        store.remove("demo")
    assert "surprise" in path.read_text()

    digest_path = tmp_path / "digest.json"
    digest_store = ActivationHintStore(digest_path)
    digest_store.put(manifest(), "a" * 64, REVISION)
    data = json.loads(digest_path.read_text())
    data["hints"][0]["declared_digest"] = "0" * 64
    digest_path.write_text(json.dumps(data))
    assert digest_store.read_all() == ()
    with pytest.raises(ActivationHintStoreError):
        digest_store.remove("demo")

    path.write_text('{"version":1,"version":1,"hints":[]}')
    assert store.read_all() == ()
    with pytest.raises(ActivationHintStoreError):
        store.put(manifest(), "d" * 64, REVISION)


@pytest.mark.parametrize("revision", ["A" * 64, "0" * 63, "g" * 64, 5, None])
def test_put_requires_exact_lowercase_grant_revision(revision, tmp_path):
    store = ActivationHintStore(tmp_path / "hints.json")
    with pytest.raises(ActivationHintStoreError):
        store.put(manifest(), "a" * 64, revision)
    assert store.read_all() == ()


def test_missing_grant_revision_is_corrupt_and_mutation_fails_closed(tmp_path):
    path = tmp_path / "hints.json"
    store = ActivationHintStore(path)
    store.put(manifest(), "a" * 64, REVISION)
    data = json.loads(path.read_text())
    del data["hints"][0]["grant_revision"]
    path.write_text(json.dumps(data))
    assert store.read_all() == ()
    with pytest.raises(ActivationHintStoreError):
        store.remove("demo")
    assert "grant_revision" not in json.loads(path.read_text())["hints"][0]


def test_corrupt_unreadable_and_oversized_mutations_never_reset_to_empty(tmp_path):
    path = tmp_path / "hints.json"
    path.write_text("not json")
    store = ActivationHintStore(path)
    assert store.read_all() == ()
    with pytest.raises(ActivationHintStoreError):
        store.put(manifest(), "e" * 64, REVISION)
    assert path.read_text() == "not json"

    path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    assert store.read_all() == ()
    with pytest.raises(ActivationHintStoreError):
        store.remove("demo")
    assert path.stat().st_size == 2 * 1024 * 1024 + 1


def test_row_and_byte_bounds_reject_add_without_clobbering_existing(tmp_path):
    path = tmp_path / "hints.json"
    store = ActivationHintStore(path)
    for i in range(128):
        store.put(manifest(f"ext{i}"), f"{i:064x}", REVISION)
    before = path.read_bytes()
    with pytest.raises(ActivationHintStoreError):
        store.put(manifest("overflow"), "f" * 64, REVISION)
    assert path.read_bytes() == before
    assert len(store.read_all()) == 128


def test_symlink_and_nonregular_targets_are_refused_without_replacement(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink unavailable")
    victim = tmp_path / "victim"
    victim.write_text("keep")
    link = tmp_path / "hints.json"
    try:
        link.symlink_to(victim)
    except OSError:
        pytest.skip("symlink creation unavailable")
    store = ActivationHintStore(link)
    assert store.read_all() == ()
    with pytest.raises(ActivationHintStoreError):
        store.put(manifest(), "1" * 64, REVISION)
    assert link.is_symlink()
    assert victim.read_text() == "keep"

    directory = tmp_path / "directory.json"
    directory.mkdir()
    other = ActivationHintStore(directory)
    assert other.read_all() == ()
    with pytest.raises(ActivationHintStoreError):
        other.remove("demo")
    assert directory.is_dir()


def test_distinct_concurrent_instances_do_not_lose_updates(tmp_path):
    path = tmp_path / "hints.json"
    stores = [ActivationHintStore(path) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda args: args[0].put(manifest(args[1]), hashlib.sha256(args[1].encode()).hexdigest(), REVISION),
            [(stores[0], "one"), (stores[1], "two")],
        ))
    assert results == [None, None]
    assert {hint.manifest.id for hint in stores[0].read_all()} == {"one", "two"}


def _process_put(path, extension_id, package_hash, ready):
    store = ActivationHintStore(path)
    ready.wait(5)
    store.put(manifest(extension_id), package_hash, REVISION)


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="fork unavailable")
def test_cross_process_updates_do_not_lose_distinct_rows(tmp_path):
    path = tmp_path / "hints.json"
    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    children = [
        ctx.Process(target=_process_put, args=(path, "proc_one", "1" * 64, ready)),
        ctx.Process(target=_process_put, args=(path, "proc_two", "2" * 64, ready)),
    ]
    for child in children:
        child.start()
    ready.set()
    for child in children:
        child.join(10)
    assert [child.exitcode for child in children] == [0, 0]
    assert {hint.manifest.id for hint in ActivationHintStore(path).read_all()} == {"proc_one", "proc_two"}


def test_temp_descriptor_is_closed_when_private_mode_setup_fails(tmp_path, monkeypatch):
    opened = []
    real_mkstemp = activation_hints.tempfile.mkstemp
    real_close = os.close
    closed = []

    def track_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        opened.append(fd)
        return fd, name

    def track_close(fd):
        closed.append(fd)
        return real_close(fd)

    def fail_fchmod(*args, **kwargs):
        raise OSError("injected chmod failure")

    monkeypatch.setattr(activation_hints.tempfile, "mkstemp", track_mkstemp)
    monkeypatch.setattr(activation_hints.os, "close", track_close)
    monkeypatch.setattr(activation_hints.os, "fchmod", fail_fchmod)
    with pytest.raises(ActivationHintStoreError):
        activation_hints._write_atomic(tmp_path / "hints.json", b"payload")
    assert opened and opened[-1] in closed
    with pytest.raises(OSError):
        os.fstat(opened[-1])
    assert not (tmp_path / "hints.json").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_open_path_identity_rejects_symlink_swap_without_nofollow(tmp_path, monkeypatch):
    target = tmp_path / "hints.json"
    victim = tmp_path / "victim"
    target.write_text("original")
    victim.write_text("secret")
    real_open = os.open
    swapped = False

    def race_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == target and not swapped:
            swapped = True
            target.unlink()
            target.symlink_to(victim)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(activation_hints.os, "O_NOFOLLOW", 0, raising=False)
    monkeypatch.setattr(activation_hints.os, "open", race_open)
    with pytest.raises(ActivationHintStoreError):
        activation_hints._read_bytes(target)
    assert target.is_symlink()
    assert victim.read_text() == "secret"


def test_directory_fsync_failure_reports_uncertain_after_replace(tmp_path, monkeypatch):
    target = tmp_path / "hints.json"
    real_fsync = os.fsync
    calls = 0

    def fail_directory_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(activation_hints.os, "fsync", fail_directory_fsync)
    with pytest.raises(ActivationHintStoreError) as raised:
        activation_hints._write_atomic(target, b"payload")
    assert raised.value.reason == "activation_hints_durability_uncertain"
    assert target.read_bytes() == b"payload"
