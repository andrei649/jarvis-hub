"""Portable data export (0.14 · H23.9, export half) — offline.

Seeds a throwaway data root with content DBs + a secrets DB, then asserts the
export dumps only allow-listed user content as readable JSON, excludes
settings.db, and never mutates anything.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from agents.core import data_export as dx


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
