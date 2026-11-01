"""Built-in settings on a data root that is not private, and while a lease is held (#1321).

The selection gate refused any store whose directory was group-writable, and built-in
settings took that gate on first use: a fresh install under umask 002 (the per-user
default on Ubuntu and Fedora) could not read a single setting, where main read them. And a
process whose first settings read came while another process held a shared lease (a
signed or custom stream) got an uncaught ``SelectionBusy``.

Signed selection still refuses where it cannot prove its lease; built-in settings read and
write as on a host without flock, and never through a second name of the store.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path

import pytest

from agents.core import settings_db
from agents.core.llm.providers import selection_gates


def _hold_shared(path: str, ready, release):
    settings_db.DB_PATH = Path(path)
    with selection_gates.shared(path):
        ready.set()
        release.wait(10)


@pytest.fixture
def shared_root(tmp_path, monkeypatch):
    """A data root as umask 002 leaves it: group-writable, and not yet holding a store."""
    root = tmp_path / "home"
    root.mkdir()
    root.chmod(0o775)
    monkeypatch.setattr(settings_db, "DB_PATH", root / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    return root


def test_a_group_writable_root_still_reads_and_writes_builtin_settings(shared_root):
    assert settings_db.get_value("llm", "compatible_model", "fallback") is not None
    assert (shared_root / "settings.db").exists()
    settings_db.put_category("system", {"error_backlog_sync_enabled": True})
    assert settings_db.get_value("system", "error_backlog_sync_enabled") is True
    settings_db.put_category("llm", {"compatible_model": "builtin-pair"})
    assert settings_db.get_value("llm", "compatible_model") == "builtin-pair"
    assert settings_db.compatible_pair_state()[2] == "builtin-pair"


def test_a_fresh_root_created_under_umask_002_starts(tmp_path, monkeypatch):
    previous = os.umask(0o002)
    try:
        monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "fresh" / "settings.db")
        monkeypatch.setattr(settings_db, "_initialized", False)
        settings_db.ensure_initialized()
        assert (tmp_path / "fresh").stat().st_mode & 0o020
        assert settings_db.get_value("llm", "compatible_model", "x") is not None
    finally:
        os.umask(previous)


def test_signed_selection_still_refuses_a_root_it_cannot_prove(shared_root):
    settings_db.ensure_initialized()
    store = shared_root / "settings.db"
    with pytest.raises(selection_gates.SelectionUnavailable):
        selection_gates.acquire_shared(store)
    with (pytest.raises(selection_gates.SelectionUnavailable),
          selection_gates.exclusive(store, signed=True)):
        pass
    # A signed CAS nested in a built-in writer does not inherit its unfenced path.
    with (selection_gates.exclusive(store),
          pytest.raises(selection_gates.SelectionUnavailable),
          selection_gates.exclusive(store, signed=True)):
        pass


def test_a_group_writable_store_file_refuses_signed_but_not_builtin(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.ensure_initialized()
    (tmp_path / "settings.db").chmod(0o664)
    with pytest.raises(selection_gates.SelectionUnavailable):
        selection_gates.acquire_shared(tmp_path / "settings.db")
    settings_db.put_category("llm", {"compatible_model": "still-writable"})
    assert settings_db.get_value("llm", "compatible_model") == "still-writable"


def test_an_unfenced_builtin_writer_still_refuses_a_hardlinked_store(shared_root, tmp_path,
                                                                     monkeypatch):
    settings_db.ensure_initialized()
    alias = shared_root / "alias.db"
    os.link(shared_root / "settings.db", alias)
    monkeypatch.setattr(settings_db, "DB_PATH", alias)
    with pytest.raises(selection_gates.SelectionUnavailable):
        settings_db.put_category("llm", {"compatible_model": "alias-write"})


def test_a_process_starting_mid_stream_reads_its_settings(tmp_path, monkeypatch):
    store = tmp_path / "settings.db"
    monkeypatch.setattr(settings_db, "DB_PATH", store)
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.put_category("llm", {"compatible_model": "streaming-pair"})
    ctx = mp.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_shared, args=(str(store), ready, release))
    child.start()
    try:
        assert ready.wait(10)
        # A fresh process: its first settings access happens while the lease is held.
        monkeypatch.setattr(settings_db, "_initialized", False)
        assert settings_db.get_value("llm", "compatible_model") == "streaming-pair"
        settings_db.ensure_initialized()
        # The seeding writer itself still waits for the lease (H361).
        with pytest.raises(selection_gates.SelectionBusy):
            settings_db.init_db()
        assert settings_db._initialized is False
    finally:
        release.set()
        child.join(10)
        assert child.exitcode == 0
    settings_db.get_value("llm", "compatible_model")
    assert settings_db._initialized is True
