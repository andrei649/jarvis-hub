"""Adversarial regressions for the encrypted vault persistence boundary."""

from __future__ import annotations

import json
import math
import multiprocessing
import os
import stat
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import core.vault as vault_module  # noqa: E402
from core.vault import Vault, VaultError  # noqa: E402

from agents.core.secrets import SecretStore  # noqa: E402

KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def _vault(tmp_path: Path, **kwargs) -> Vault:
    return Vault(tmp_path / "vault", key=KEY, **kwargs)


def _index_payload(root: Path) -> tuple[SecretStore, dict]:
    cipher = SecretStore(root / "vault.keys", key=KEY)
    raw = cipher.decrypt_bytes((root / "index.enc").read_bytes())
    return cipher, json.loads(raw.decode("utf-8"))


def _write_index_payload(root: Path, payload: dict) -> None:
    cipher = SecretStore(root / "vault.keys", key=KEY)
    raw = json.dumps(payload, allow_nan=True, separators=(",", ":")).encode("utf-8")
    (root / "index.enc").write_bytes(cipher.encrypt_bytes(raw))


def _quota_worker(root: str, start, results, payload: bytes) -> None:
    try:
        vault = Vault(root, key=KEY, max_items=1)
        start.wait(10)
        vault.put(payload, now=1.0)
    except VaultError:
        results.put("refused")
    else:
        results.put("stored")


def test_clear_memory_then_purge_erases_disk_from_same_instance(tmp_path):
    vault = _vault(tmp_path)
    entry = vault.put(b"private", now=1.0)

    vault.clear_memory()

    assert vault.purge() == 1
    assert not (vault.root / f"{entry['id']}.blob").exists()


def test_clear_memory_then_put_reloads_catalog_without_orphaning_old_blob(tmp_path):
    vault = _vault(tmp_path)
    first = vault.put(b"first", now=1.0)
    vault.clear_memory()

    second = vault.put(b"second", now=2.0)

    reopened = _vault(tmp_path)
    assert {entry["id"] for entry in reopened.list()} == {first["id"], second["id"]}
    assert reopened.get(first["id"]) == b"first"


def test_generated_ids_that_are_not_strictly_safe_fail_closed(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    monkeypatch.setattr(vault_module, "_token_urlsafe", lambda _n: "../escape")

    with pytest.raises(VaultError, match="safe vault id"):
        vault.put(b"blocked", now=1.0)

    assert not (vault.root.parent / "escape.blob").exists()


def test_corrupt_index_fails_closed_instead_of_starting_empty(tmp_path):
    vault = _vault(tmp_path)
    vault.put(b"kept", now=1.0)
    index_path = next(p for p in vault.root.iterdir() if p.name.startswith("index."))
    index_path.write_bytes(b"not a valid authenticated catalog")

    with pytest.raises(VaultError, match="index"):
        _vault(tmp_path)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_put_rejects_non_finite_timestamps(tmp_path, value):
    vault = _vault(tmp_path)
    with pytest.raises(VaultError, match="finite"):
        vault.put(b"x", now=value)
    with pytest.raises(VaultError, match="finite"):
        vault.put(b"x", now=1.0, expires_at=value)


@pytest.mark.parametrize(
    ("name", "value"),
    [("max_items", True), ("max_items", -1), ("max_total_bytes", math.inf), ("max_item_bytes", 0)],
)
def test_constructor_rejects_invalid_quota_configuration(tmp_path, name, value):
    kwargs = {name: value}
    with pytest.raises(VaultError, match="positive integer"):
        _vault(tmp_path, **kwargs)


def test_two_live_instances_merge_writes_instead_of_losing_catalog_entries(tmp_path):
    first_instance = _vault(tmp_path)
    second_instance = _vault(tmp_path)

    first = first_instance.put(b"first", now=1.0)
    second = second_instance.put(b"second", now=2.0)

    reopened = _vault(tmp_path)
    assert {entry["id"] for entry in reopened.list()} == {first["id"], second["id"]}


def test_index_is_authenticated_encrypted_and_tampering_fails_closed(tmp_path):
    vault = _vault(tmp_path)
    vault.put(b"sensitive", name="private-name.txt", now=1.0)
    index_path = vault.root / "index.enc"
    raw = index_path.read_bytes()
    assert b"private-name.txt" not in raw
    raw = raw[: len(raw) // 2] + bytes([raw[len(raw) // 2] ^ 1]) + raw[len(raw) // 2 + 1 :]
    index_path.write_bytes(raw)

    with pytest.raises(VaultError, match="index"):
        _vault(tmp_path)


def test_authenticated_index_cannot_be_swapped_between_vault_roots(tmp_path):
    first = Vault(tmp_path / "first", key=KEY)
    first.put(b"first", now=1.0)
    second = Vault(tmp_path / "second", key=KEY)
    second.put(b"second", now=1.0)
    (second.root / "index.enc").write_bytes((first.root / "index.enc").read_bytes())

    with pytest.raises(VaultError, match="different vault"):
        Vault(second.root, key=KEY)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema=999),
        lambda payload: payload.update(entries=[]),
        lambda payload: payload["entries"][next(iter(payload["entries"]))].update(bytes=-1),
        lambda payload: payload["entries"][next(iter(payload["entries"]))].update(
            created_at=math.nan
        ),
    ],
)
def test_authenticated_but_invalid_index_schema_fails_closed(tmp_path, mutation):
    vault = _vault(tmp_path)
    vault.put(b"data", now=1.0)
    _, payload = _index_payload(vault.root)
    mutation(payload)
    _write_index_payload(vault.root, payload)

    with pytest.raises(VaultError, match="index"):
        _vault(tmp_path)


def test_authenticated_path_injection_in_index_fails_closed(tmp_path):
    vault = _vault(tmp_path)
    entry = vault.put(b"data", now=1.0)
    _, payload = _index_payload(vault.root)
    payload["entries"]["../escape"] = payload["entries"].pop(entry["id"])
    payload["entries"]["../escape"]["id"] = "../escape"
    _write_index_payload(vault.root, payload)

    with pytest.raises(VaultError, match="safe vault id"):
        _vault(tmp_path)
    assert not (vault.root.parent / "escape.blob").exists()


def test_valid_index_load_reconciles_unreferenced_blob(tmp_path):
    vault = _vault(tmp_path)
    vault.put(b"kept", now=1.0)
    orphan = vault.root / "AAAAAAAAAAAAAAAA.blob"
    orphan.write_bytes(b"crash residue")

    _vault(tmp_path)

    assert not orphan.exists()


def test_purge_enumerates_all_contained_blob_files_independent_of_index(tmp_path):
    vault = _vault(tmp_path)
    vault.put(b"indexed", now=1.0)
    orphan = vault.root / "orphan.blob"
    orphan.write_bytes(b"orphan")
    vault.clear_memory()

    assert vault.purge() == 2
    assert list(vault.root.glob("*.blob")) == []


def test_failed_index_commit_cleans_new_blob_transaction_residue(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    monkeypatch.setattr(
        vault, "_save_index", lambda _index: (_ for _ in ()).throw(OSError("disk full"))
    )

    with pytest.raises(VaultError, match="commit"):
        vault.put(b"never catalogued", now=1.0)

    assert list(vault.root.glob("*.blob")) == []


def test_unencodable_metadata_fails_as_vault_error_without_orphan(tmp_path):
    vault = _vault(tmp_path)

    with pytest.raises(VaultError, match="index commit"):
        vault.put(b"never catalogued", name="\ud800", now=1.0)

    assert list(vault.root.glob("*.blob")) == []


def test_blob_temp_symlink_cannot_overwrite_file_outside_vault(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"do not touch")
    safe_id = "AAAAAAAAAAAAAAAA"

    def arm_symlink(_size):
        try:
            (vault.root / f"{safe_id}.blob.tmp").symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")
        return safe_id

    monkeypatch.setattr(vault_module, "_token_urlsafe", arm_symlink)
    with pytest.raises(VaultError, match="blob commit"):
        vault.put(b"blocked", now=1.0)

    assert outside.read_bytes() == b"do not touch"
    assert not (vault.root / f"{safe_id}.blob").exists()


def test_index_temp_symlink_cannot_overwrite_file_outside_vault(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"do not touch")
    original_write_blob = vault._write_blob

    def write_blob_then_arm_index(path, token):
        original_write_blob(path, token)
        try:
            (vault.root / "index.enc.tmp").symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")

    monkeypatch.setattr(vault, "_write_blob", write_blob_then_arm_index)
    with pytest.raises(VaultError, match="index commit"):
        vault.put(b"blocked", now=1.0)

    assert outside.read_bytes() == b"do not touch"
    assert list(vault.root.glob("*.blob")) == []


def test_lock_symlink_is_rejected_without_touching_target(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    outside = tmp_path / "outside-lock.txt"
    outside.write_bytes(b"")
    try:
        (root / "vault.lock").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(VaultError, match="unsafe vault lock"):
        Vault(root, key=KEY)

    assert outside.read_bytes() == b""


def test_index_symlink_is_rejected_even_when_target_is_authentic(tmp_path):
    vault = _vault(tmp_path)
    vault.put(b"data", now=1.0)
    outside = tmp_path / "outside-index.enc"
    (vault.root / "index.enc").replace(outside)
    try:
        (vault.root / "index.enc").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(VaultError, match="unsafe vault index"):
        _vault(tmp_path)


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX permission bits are not authoritative on Windows"
)
def test_vault_files_use_restrictive_permissions(tmp_path):
    vault = _vault(tmp_path)
    entry = vault.put(b"secret", now=1.0)
    paths = [vault.root / "index.enc", vault.root / f"{entry['id']}.blob"]
    assert stat.S_IMODE(vault.root.stat().st_mode) & 0o077 == 0
    assert all(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0 for path in paths)


def test_cross_process_quota_update_is_serialized(tmp_path):
    root = str(tmp_path / "vault")
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(target=_quota_worker, args=(root, start, results, bytes([n])))
        for n in (1, 2)
    ]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(20)
        assert worker.exitcode == 0

    outcomes = sorted(results.get(timeout=5) for _ in workers)
    assert outcomes == ["refused", "stored"]
    assert Vault(root, key=KEY, max_items=1).stats()["items"] == 1
