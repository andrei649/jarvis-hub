"""'Forget me' data purge (0.14 · H23.9).

Offline: builds a throwaway data root with real content DBs (missions/autonomy/
analytics), a notes.json store, and a settings.db holding a secret, then exercises
``purge_data``. Asserts the safety/honesty properties — content rows erased but schema
kept, JSON content reset, the excluded settings.db (secrets) left untouched, a verified
backup taken first, and the purge refused (nothing deleted) when that backup won't verify.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from agents.core import backup as bk
from agents.core import data_purge as dp


def _seed_db(path: Path, table: str, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany(f"INSERT INTO {table} (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def _count(path: Path, table: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _tables(path: Path) -> list[str]:
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
    finally:
        conn.close()


@pytest.fixture()
def data_root(tmp_path):
    root = tmp_path / "data"
    _seed_db(root / "missions.db", "missions", 4)
    _seed_db(root / "autonomy.db", "tasks", 5)
    _seed_db(root / "analytics.db", "events", 6)
    _seed_db(root / "settings.db", "settings", 3)  # excluded — secrets/config
    (root / "notes.json").write_text(
        json.dumps({"sess-1": {"content": "private", "updated_at": 1}}), encoding="utf-8")
    return root


def test_purge_empties_content_keeps_schema(data_root):
    report = dp.purge_data(source_root=str(data_root), backup_first=False)
    assert report["ok"] is True
    # every content DB has zero rows but its table still exists
    assert _count(data_root / "missions.db", "missions") == 0
    assert _count(data_root / "autonomy.db", "tasks") == 0
    assert _count(data_root / "analytics.db", "events") == 0
    assert _tables(data_root / "missions.db") == ["missions"]
    # notes.json reset to an empty object
    assert json.loads((data_root / "notes.json").read_text()) == {}
    # counts reported
    assert report["total_rows"] == 4 + 5 + 6
    assert report["purged"]["analytics.db"] == {"events": 6}
    assert report["purged"]["notes.json"] == {"reset": 1}


def test_settings_db_untouched(data_root):
    dp.purge_data(source_root=str(data_root), backup_first=False)
    assert _count(data_root / "settings.db", "settings") == 3  # secrets survive
    assert "settings.db" not in dp.purge_data(  # not even in the allow-list
        source_root=str(data_root), backup_first=False)["purged"]


def test_backup_first_is_recoverable(data_root, tmp_path):
    report = dp.purge_data(source_root=str(data_root), backup_first=True)
    assert report["backup"]["verified"] is True
    archive = report["backup"]["archive"]
    assert Path(archive).exists()
    # data is gone live, but recoverable from the pre-forget snapshot
    assert _count(data_root / "missions.db", "missions") == 0
    target = tmp_path / "restored"
    out = bk.restore_backup(archive, str(target))
    assert out["ok"] is True
    assert _count(target / "missions.db", "missions") == 4


def test_refuses_when_backup_unverifiable(data_root, monkeypatch):
    monkeypatch.setattr(dp._backup, "verify_backup", lambda *_a, **_k: {"ok": False})
    with pytest.raises(dp.PurgeError):
        dp.purge_data(source_root=str(data_root), backup_first=True)
    # nothing deleted — the content is intact
    assert _count(data_root / "missions.db", "missions") == 4
    assert _count(data_root / "analytics.db", "events") == 6
    assert json.loads((data_root / "notes.json").read_text()) != {}


def test_purge_is_idempotent(data_root):
    dp.purge_data(source_root=str(data_root), backup_first=False)
    again = dp.purge_data(source_root=str(data_root), backup_first=False)
    assert again["total_rows"] == 0
    assert again["purged"]["notes.json"] == {"reset": 0}


def test_cli_refuses_without_confirm(data_root, capsys):
    rc = dp._main(["--source-root", str(data_root), "--no-backup"])
    assert rc == 2
    assert _count(data_root / "missions.db", "missions") == 4  # untouched
    assert "confirm" in capsys.readouterr().out.lower()


def test_forget_route_is_admin_guarded():
    snap = json.loads((Path(__file__).resolve().parent / "_snapshots" / "route_auth.json").read_text())
    assert snap.get("POST /api/admin/forget") == "admin"


# ── AUD-2: the CLI must purge memory too (the endpoint did; the CLI was the gap) ──
# Function-level memory purge is covered in test_data_purge_memory.py; this is the
# CLI parity that #315 missed — `_main` now defaults to memory=True with a --no-memory escape.

def _seed_memory(root: Path) -> None:
    """Seed the at-rest memory subsystem: fixed graph/entity/decay stores, the embedding
    cache dir, and a session transcript."""
    for name in ("bitemporal_kg.json", "entities.json", "decay.json"):
        (root / name).write_text('{"pii": "remember me"}', encoding="utf-8")
    cache = root / "embedding_cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "vec.bin").write_bytes(b"\x00\x01")
    (root / "sess-1.jsonl").write_text('{"role": "user", "content": "secret"}\n', encoding="utf-8")
    (root / "sess-1.json").write_text('{"turns": 1}', encoding="utf-8")


def test_cli_purges_memory_by_default_and_no_memory_opts_out(data_root):
    _seed_memory(data_root)
    rc = dp._main(["--source-root", str(data_root), "--confirm", "--no-backup"])
    assert rc == 0
    assert not (data_root / "bitemporal_kg.json").exists()   # memory erased by default
    assert not (data_root / "sess-1.jsonl").exists()

    _seed_memory(data_root)  # reseed, then opt out
    rc = dp._main(["--source-root", str(data_root), "--confirm", "--no-backup", "--no-memory"])
    assert rc == 0
    assert (data_root / "bitemporal_kg.json").exists()        # memory left intact
    assert (data_root / "sess-1.jsonl").exists()
