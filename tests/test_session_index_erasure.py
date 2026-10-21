"""H574 review round 3: the FTS5 indexes erase what they forget, a busy index is never
mistaken for a corrupt one, and the index stays off the save path's hot locks.

* Erasure: a plain FTS5 DELETE leaves the deleted terms in ``<table>_data`` until the
  segments merge (neither ``secure_delete`` nor VACUUM merges them). Every test here
  writes a unique token, removes it through a real flow, and looks for its *bytes* in
  the database file and its sidecars, not for a row count.
* Contention: a lock held by another connection makes ``open_index`` answer
  ``IndexUnavailable(busy=True)``; the index file (inode, rows) is untouched.
* Cost: a save that appends one turn segments one turn, never waits on a busy index, and
  runs after the checkpoint lock is released; the first search over a large history is
  bounded, answering the snapshots its sync did not reach with the bounded scan.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from agents.core import data_purge, session_archive
from agents.core.memory import cjk_fts, persistence, session_index, session_search
from agents.core.memory.session_search import search_sessions
from agents.core.memory.store import MemoryStore

TOKEN = "zebrasecretword"
CJK_TOKEN = "斑马秘密"


def _turn(role, content):
    return {"role": role, "content": content, "timestamp": "2026-09-01T10:00:00+00:00"}


def _write(root, sid, turns, *, age=0.0):
    path = root / f"{sid}.json"
    path.write_text(json.dumps({"session_id": sid, "turns": turns}, ensure_ascii=False),
                    encoding="utf-8")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def _files(db: Path) -> list[Path]:
    return [p for p in (db, *(Path(str(db) + s) for s in ("-wal", "-shm", "-journal")))
            if p.exists()]


def _holds(db: Path, needle: str) -> list[str]:
    """Which of *db*'s files still contain *needle*'s bytes."""
    raw = needle.encode("utf-8")
    return [p.name for p in _files(db) if raw in p.read_bytes()]


@pytest.fixture
def root(tmp_path, monkeypatch):
    directory = tmp_path / "memory"
    directory.mkdir()
    monkeypatch.setattr(persistence, "MEMORY_DIR", directory)
    return directory


def _history(root, secret_sid="session_secret"):
    """Several sessions saved one by one (several FTS segments), the secret in the middle."""
    for i in range(4):
        persistence.save_memory(f"session_before_{i}", [_turn("user", f"filler words {i} 牙医")])
    persistence.save_memory(secret_sid, [_turn("user", f"the code is {TOKEN} and {CJK_TOKEN}"),
                                         _turn("assistant", "noted")])
    for i in range(4):
        persistence.save_memory(f"session_after_{i}", [_turn("user", f"more filler {i} 眼科")])
    index = root / session_index.INDEX_NAME
    assert _holds(index, TOKEN) == [session_index.INDEX_NAME]
    assert search_sessions(TOKEN, directory=root)["hits"]
    return index


# ── erasure ─────────────────────────────────────────────────────────────────

def test_delete_memory_erases_the_sessions_words_from_the_index_file(root):
    index = _history(root)
    persistence.delete_memory("session_secret")
    assert _holds(index, TOKEN) == [] and _holds(index, CJK_TOKEN) == []
    assert search_sessions("filler", directory=root)["hits"]          # the rest still answers


def test_session_delete_and_retention_erase_the_words(root, tmp_path):
    # session_archive.delete_session is the HUD delete and retention's expiry delete.
    index = _history(root)

    class _Checkpoints:
        def session_rows_for_backup(self, sid):
            return {"session": {"id": sid}}

        def delete_session_rows(self, sid):
            return {"sessions": 1}

    result = asyncio.run(session_archive.delete_session(
        "session_secret", checkpoints=_Checkpoints(), backup_root=tmp_path / "backups",
        archive_root=tmp_path / "archive"))
    assert result["ok"] is True and result["removed"]["search_index"] is True
    assert _holds(index, TOKEN) == [] and _holds(index, CJK_TOKEN) == []


def test_a_snapshot_removed_behind_the_hooks_is_erased_by_the_next_sync(root):
    index = _history(root)
    (root / "session_secret.json").unlink()
    assert search_sessions("filler", directory=root)["hits"]
    assert _holds(index, TOKEN) == []


def test_a_rewind_erases_the_turns_it_removed(root):
    index = _history(root)
    persistence.save_memory("session_secret", [_turn("user", "only this is left")])
    assert _holds(index, TOKEN) == []
    assert search_sessions(TOKEN, directory=root)["hits"] == []


def test_without_fts5_secure_delete_an_optimize_erases_the_words(root, monkeypatch):
    # An SQLite older than 3.44 has no FTS5 secure-delete: the delete path rewrites the
    # index (optimize) instead.
    monkeypatch.setattr(cjk_fts, "enable_secure_delete", lambda conn, table: False)
    index = _history(root)
    conn = sqlite3.connect(str(index))
    try:
        assert conn.execute("SELECT v FROM turn_fts_config WHERE k='secure-delete'").fetchone() is None
    finally:
        conn.close()
    persistence.delete_memory("session_secret")
    assert _holds(index, TOKEN) == []


def test_forget_of_all_memory_removes_the_index_file(root):
    index = _history(root)
    report = data_purge._purge_memory_at_rest(root, ["session_secret"])
    assert session_index.INDEX_NAME in report["files"]
    assert not _files(index)
    for path in root.rglob("*"):
        if path.is_file():
            assert TOKEN.encode() not in path.read_bytes(), path.name
    assert search_sessions("filler", directory=root)["engine"] == "fts5"   # rebuilt


def test_forget_sweep_erases_fts_tables_through_purge_db(root, tmp_path):
    index = _history(root)
    copy = tmp_path / "copy.db"
    shutil.copy(index, copy)
    deleted = data_purge._purge_db(copy)
    assert deleted["turn_fts"] == 10 and deleted["turns"] == 10
    assert _holds(copy, TOKEN) == [] and _holds(copy, "filler") == []
    conn = sqlite3.connect(str(copy))
    try:   # still a readable, empty FTS5 table
        assert conn.execute("SELECT count(*) FROM turn_fts WHERE turn_fts MATCH 'x'").fetchone() == (0,)
    finally:
        conn.close()


def test_purge_db_reports_a_virtual_table_it_cannot_erase(tmp_path, monkeypatch):
    db = tmp_path / "x.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE VIRTUAL TABLE f USING fts5(seg)")
    conn.execute("INSERT INTO f VALUES (?)", (TOKEN,))
    conn.commit()
    conn.close()

    def broken(conn, table, sql, path):
        raise OSError("could not erase virtual table f")

    monkeypatch.setattr(data_purge, "_delete_all_virtual_rows", broken)
    with pytest.raises(OSError):
        data_purge._purge_db(db)


def _store(tmp_path):
    return MemoryStore(db_path=tmp_path / "memory.db")


def _fill(store, n=5):
    for i in range(n):
        asyncio.run(store.upsert("fact", f"k{i}", f"filler fact {i} 牙医"))


def test_memory_store_delete_erases_the_fact_from_db_and_wal(tmp_path):
    store = _store(tmp_path)
    _fill(store)
    asyncio.run(store.upsert("fact", "secret", f"the code is {TOKEN} {CJK_TOKEN}"))
    _fill(store)
    assert asyncio.run(store.search(CJK_TOKEN))
    assert asyncio.run(store.delete("fact", "secret")) is True
    db = tmp_path / "memory.db"
    assert _holds(db, TOKEN) == [] and _holds(db, CJK_TOKEN) == []
    assert asyncio.run(store.search("牙医"))                    # the index still answers


def test_memory_store_update_erases_the_old_value(tmp_path):
    store = _store(tmp_path)
    _fill(store)
    asyncio.run(store.upsert("fact", "secret", f"old value {TOKEN}"))
    _fill(store)
    asyncio.run(store.upsert("fact", "secret", "new value"))
    conn = sqlite3.connect(str(tmp_path / "memory.db"))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    assert _holds(tmp_path / "memory.db", TOKEN) == []


def test_memory_store_re_enables_secure_delete_after_a_purge_recreated_its_index(tmp_path):
    store = _store(tmp_path)
    _fill(store)
    data_purge._purge_db(tmp_path / "memory.db")      # drops and recreates memory_fts
    asyncio.run(store.upsert("fact", "secret", f"value {TOKEN}"))
    _fill(store)
    assert asyncio.run(store.delete("fact", "secret")) is True
    assert _holds(tmp_path / "memory.db", TOKEN) == []


# ── a busy index is not a corrupt one ───────────────────────────────────────

def _hold_exclusive(index: Path) -> sqlite3.Connection:
    holder = sqlite3.connect(str(index), isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN EXCLUSIVE")
    return holder


def test_a_busy_index_is_never_deleted(root, monkeypatch):
    _write(root, "session_a", [_turn("user", "牙医 appointment")])
    assert search_sessions("牙医", directory=root)["engine"] == "fts5"
    index = root / session_index.INDEX_NAME
    inode = index.stat().st_ino
    holder = _hold_exclusive(index)
    try:
        with pytest.raises(session_index.IndexUnavailable) as caught:
            session_index.open_index(root, timeout=0.05)
        assert caught.value.busy is True
        monkeypatch.setattr(session_search, "INDEX_BUSY_SECONDS", 0.05)
        out = search_sessions("牙医", directory=root)
        assert out["engine"] == "scan" and out["hits"][0]["session_id"] == "session_a"
        assert index.stat().st_ino == inode
    finally:
        holder.rollback()
        holder.close()
    conn = sqlite3.connect(str(index))
    try:
        assert conn.execute("SELECT count(*) FROM turns").fetchone() == (1,)
    finally:
        conn.close()
    assert search_sessions("牙医", directory=root)["engine"] == "fts5"


def test_only_corruption_codes_count_as_corrupt():
    def error(message, code):
        exc = sqlite3.OperationalError(message)
        exc.sqlite_errorcode = code
        return exc

    assert session_index.is_busy_error(error("database is locked", 5))
    assert session_index.is_busy_error(error("database table is locked", 6))
    assert not session_index.is_corrupt_error(error("database is locked", 5))
    assert session_index.is_corrupt_error(sqlite3.DatabaseError("file is not a database"))
    assert session_index.is_corrupt_error(error("database disk image is malformed", 11))
    assert session_index.is_corrupt_error(error("invalid fts5 file format (found 0, expected 4 or 5)", 267))
    assert not session_index.is_corrupt_error(error("disk I/O error", 10))


def test_an_index_that_cannot_be_unlinked_falls_back_to_the_scan(root, monkeypatch):
    # Windows refuses to unlink an open file: that must not make a search raise.
    _write(root, "session_a", [_turn("user", "牙医")])
    (root / session_index.INDEX_NAME).write_bytes(b"not a database at all" * 100)
    real_unlink = Path.unlink

    def refuse(self, *args, **kwargs):
        if self.name.startswith(session_index.INDEX_NAME):
            raise PermissionError("in use")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse)
    out = search_sessions("牙医", directory=root)
    assert out["engine"] == "scan" and out["hits"][0]["session_id"] == "session_a"
    assert session_index.forget_sessions(root, ["session_a"]) == 0


# ── cost: incremental saves off the hot locks, a bounded first search ─────────

@pytest.fixture
def segmented(monkeypatch):
    calls: list[str] = []
    real = cjk_fts.index_text

    def counting(text):
        calls.append(text)
        return real(text)

    monkeypatch.setattr(cjk_fts, "index_text", counting)
    return calls


def test_a_save_that_appends_one_turn_segments_only_that_turn(root, segmented):
    turns = [_turn("user" if i % 2 else "assistant", f"turn {i} " + "x" * 1000) for i in range(500)]
    persistence.save_memory("session_long", turns)
    assert len(segmented) == 500
    segmented.clear()
    turns.append(_turn("user", f"the newest turn {TOKEN}"))
    persistence.save_memory("session_long", turns)
    assert segmented == [f"the newest turn {TOKEN}"]
    hit = search_sessions(TOKEN, directory=root)["hits"][0]
    assert (hit["session_id"], hit["turn"]) == ("session_long", 500)
    # a replace of an earlier turn re-reads the session
    segmented.clear()
    turns[3] = _turn("user", "edited")
    persistence.save_memory("session_long", turns)
    assert len(segmented) == 501


def test_a_save_does_not_wait_on_a_busy_index(root):
    persistence.save_memory("session_a", [_turn("user", "first")])
    index = root / session_index.INDEX_NAME
    inode = index.stat().st_ino
    holder = _hold_exclusive(index)
    try:
        started = time.monotonic()
        persistence.save_memory("session_a", [_turn("user", "first"), _turn("user", f"second {TOKEN}")])
        assert time.monotonic() - started < 1.0
        assert TOKEN in (root / "session_a.json").read_text(encoding="utf-8")
    finally:
        holder.rollback()
        holder.close()
    assert index.stat().st_ino == inode
    # the next search's sync repairs the skipped update
    assert search_sessions(TOKEN, directory=root)["hits"][0]["session_id"] == "session_a"


def test_the_index_update_runs_after_the_checkpoint_lock_is_released(root, monkeypatch):
    class _Checkpoints:
        _lock = threading.Lock()

    held: list[bool] = []
    monkeypatch.setattr(session_index, "index_session",
                        lambda directory, sid, **kw: held.append(_Checkpoints._lock.locked()))
    persistence.save_memory("session_a", [_turn("user", "hello")], checkpoint_mgr=_Checkpoints())
    assert held == [False]


def test_the_first_search_over_a_large_history_is_bounded(root, monkeypatch):
    for i in range(60):
        turns = [_turn("user", f"session {i} turn {t}") for t in range(5)]
        if i == 0:
            turns.append(_turn("user", f"the oldest one says {TOKEN}"))
        _write(root, f"session_{i:03d}", turns, age=1000 - i)
    real = cjk_fts.index_text

    def slow(text):
        time.sleep(0.02)                    # 300+ turns: ~6 s to index them all
        return real(text)

    monkeypatch.setattr(cjk_fts, "index_text", slow)
    monkeypatch.setattr(session_search, "MAX_INDEX_SECONDS", 0.3)
    started = time.monotonic()
    out = search_sessions(TOKEN, directory=root)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, elapsed
    assert out["engine"] == "fts5" and out["stopped_by"] is None
    assert [h["session_id"] for h in out["hits"]] == ["session_000"]   # reached by the scan
    assert out["sessions_scanned"] == 60
    conn = session_index.open_index(root)
    try:
        indexed = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
    finally:
        conn.close()
    assert 0 < indexed < 60                  # newest first, the rest left for later


def test_stale_rows_of_an_unsynced_snapshot_never_answer(root, monkeypatch):
    _write(root, "session_a", [_turn("user", "牙医 secret")], age=10)
    assert search_sessions("牙医", directory=root)["hits"]
    _write(root, "session_a", [_turn("user", "眼科 now")])
    monkeypatch.setattr(session_search, "MAX_INDEX_SECONDS", -1.0)   # no time to sync
    assert search_sessions("牙医", directory=root)["hits"] == []
    assert search_sessions("眼科", directory=root)["hits"][0]["session_id"] == "session_a"


def test_sync_past_its_deadline_reports_pending_newest_first(root):
    for i in range(3):
        _write(root, f"session_{i}", [_turn("user", f"text {i}")], age=100 - i)
    conn = session_index.open_index(root)
    try:
        out = session_index.sync(conn, root, deadline=time.monotonic() - 1)
        assert out == {"indexed": 0, "dropped": 0, "pending": ["session_2", "session_1", "session_0"]}
        assert session_index.sync(conn, root)["indexed"] == 3
    finally:
        conn.close()
