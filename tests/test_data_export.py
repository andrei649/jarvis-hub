"""Portable data export (0.14 · H23.9, export half) — offline.

Seeds a throwaway data root with content DBs + a secrets DB, then asserts the
export dumps only allow-listed user content as readable JSON, excludes
settings.db, and never mutates anything.
"""
import base64
import json
import sqlite3
from pathlib import Path

import pytest

from agents.core import data_export as dx
from agents.core.vault import Vault


def _make_db(path: Path, table: str, rows: list[tuple], cols=("id", "v")) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE {table} ({cols[0]} INTEGER PRIMARY KEY, {cols[1]} TEXT)")
    conn.executemany(f"INSERT INTO {table} ({cols[1]}) VALUES (?)", [(r,) for r in rows])
    conn.commit()
    conn.close()


@pytest.fixture()
def data_root(tmp_path):
    root = tmp_path / "data"
    _make_db(root / "notes.db", "notes", ["buy milk", "call mom"])
    _make_db(root / "missions.db", "missions", ["ship demo"])
    _make_db(root / "settings.db", "settings", ["secret-token-xyz"])  # must NOT export
    return root


def test_export_includes_user_content(data_root):
    res = dx.export_data(source_root=str(data_root))
    doc = json.loads(Path(res["export"]).read_text())
    assert "notes.db" in doc["databases"]
    assert "missions.db" in doc["databases"]
    notes = doc["databases"]["notes.db"]["notes"]
    assert {r["v"] for r in notes} == {"buy milk", "call mom"}
    assert res["row_counts"]["notes.db"] == 2


def test_export_excludes_settings_secrets(data_root):
    res = dx.export_data(source_root=str(data_root))
    doc = json.loads(Path(res["export"]).read_text())
    assert "settings.db" not in doc["databases"]
    # the secret value must appear nowhere in the export
    assert "secret-token-xyz" not in Path(res["export"]).read_text()


def test_export_skips_absent_dbs(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    res = dx.export_data(source_root=str(root))
    assert res["databases"] == []
    assert Path(res["export"]).exists()


def test_export_is_read_only(data_root):
    before = (data_root / "notes.db").read_bytes()
    dx.export_data(source_root=str(data_root))
    after = (data_root / "notes.db").read_bytes()
    assert before == after


def test_export_manifest_shape(data_root):
    res = dx.export_data(source_root=str(data_root))
    assert set(res) >= {"export", "bytes", "generated_at", "databases", "row_counts"}
    assert res["bytes"] > 0
    doc = json.loads(Path(res["export"]).read_text())
    assert doc["version"] == dx.EXPORT_VERSION


# ── T-0.20: the vault holds ciphertext at rest — export must decrypt it, or a
# "portable JSON export of what you own" silently omits (or worse, dumps
# unreadable ciphertext for) whatever the owner explicitly vaulted. ───────────

def test_export_decrypts_and_embeds_vault_items(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    # No explicit key: matches how the router/live app open the vault
    # (Vault() with no passphrase persists its own generated key file), so a
    # second Vault(root=...) instance opened over the same root — exactly
    # what _dump_vault does — can actually decrypt it.
    v = Vault(root / "vault")
    entry = v.put(b"a vaulted secret", name="secret.txt", kind="document", now=1.0)

    res = dx.export_data(source_root=str(root))
    doc = json.loads(Path(res["export"]).read_text())

    assert doc["vault"]["available"] is True
    items = doc["vault"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "secret.txt"
    assert items[0]["id"] == entry["id"]
    assert base64.b64decode(items[0]["data_base64"]) == b"a vaulted secret"
    assert res["vault_items"] == 1
    # the raw ciphertext bytes must never leak into the export either
    for blob_path in (root / "vault").glob("*.blob"):
        assert blob_path.read_bytes() not in Path(res["export"]).read_bytes()


def test_export_vault_absent_is_honest_not_an_error(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    res = dx.export_data(source_root=str(root))
    doc = json.loads(Path(res["export"]).read_text())
    assert doc["vault"] == {"available": False, "items": [], "skipped": []}
    assert res["vault_items"] == 0


def test_vault_is_not_exempt_from_forget():
    """The forget/export erasure invariant (test_forget_export_purge_parity.py)
    only checks EXPORT_DBS/EXPORT_JSON against KEEP_FILES/KEEP_DIRS — the vault
    is neither (it's a directory, exported via _dump_vault, not an allow-listed
    name). Pin the same guarantee for it explicitly: a forget must not retain
    what an export can now reveal."""
    from agents.core.data_purge import KEEP_DIRS
    assert "vault" not in KEEP_DIRS


def test_export_vault_never_mutates_it(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    # No explicit key: matches how the router/live app open the vault
    # (Vault() with no passphrase persists its own generated key file), so a
    # second Vault(root=...) instance opened over the same root — exactly
    # what _dump_vault does — can actually decrypt it.
    v = Vault(root / "vault")
    v.put(b"content", name="a", now=1.0)
    before = sorted(p.name for p in (root / "vault").glob("*"))

    dx.export_data(source_root=str(root))

    after = sorted(p.name for p in (root / "vault").glob("*"))
    assert before == after
