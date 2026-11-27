"""Startup, manual reindex, and optional external builders using only temporary synthetic notes."""
import asyncio
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.core.memory import second_brain, vault_sync
from agents.core.routers import jarvis_os
from agents.web import app


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    (root / "Journal" / "Inbox").mkdir(parents=True)
    (root / "Archive").mkdir()
    (root / "Archive" / "hidden.md").write_text("omitted file", encoding="utf-8")
    (root / "restricted.md").write_text("---\nprivacy: restricted\n---\nclosed record", encoding="utf-8")
    (root / "active.md").write_text("active reference cobalt", encoding="utf-8")
    for key, value in {
        "JARVIS_OS_VAULT_PATH": root, "JARVIS_OS_INDEX_DB": tmp_path / "db" / "search.sqlite",
        "JARVIS_OS_VAULT_EXCLUDE": "Archive", "JARVIS_OS_REPOSITORY_DOCS": "0",
        "JARVIS_OS_MASK_VAULT_PATH": "1", "JARVIS_OS_INBOX_SUBDIR": "Journal/Inbox",
        "NERVA_SECOND_BRAIN_PYTHON": sys.executable, "NERVA_MEMORY_COPILOT_URL": "",
        "NERVA_AUTOSTART_MEMORY_COPILOT": "0",
    }.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setattr(vault_sync, "data_root", lambda: tmp_path / "state")
    return root


def test_live_status_and_reindex(library, monkeypatch):
    monkeypatch.setattr(second_brain, "health", lambda: {"connected": True})
    client = TestClient(app)
    summary = client.get("/api/os/status").json()
    assert summary["vaultPath"] == library.name and summary["indexedNotes"] == 1
    assert summary["indexReady"] and summary["copilotConnected"] and summary["lastIndexedAt"]
    assert summary["skippedHardlinks"] == 0 and summary["excludedZones"]
    (library / "later.md").write_text("new cobalt note", encoding="utf-8")
    result = client.post("/api/os/brain/reindex").json()
    assert result["ok"] and result["indexedNotes"] == 2
    assert all("closed record" not in hit["text"] for hit in client.get(
        "/api/os/brain/retrieve", params={"q": "closed record"}).json()["attachments"])
    assert client.get("/api/os/brain/note?relPath=restricted.md&local_only=true").status_code == 403


def test_restricted_reader_requires_unproxied_local_owner(library):
    local = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 30401))
    url = "/api/os/brain/note?relPath=restricted.md"
    assert local.get(url).status_code == 404
    assert "closed record" in local.get(url + "&local_only=true").json()["body"]
    for headers in ({"Forwarded": "for=192.0.2.1"}, {"Origin": "https://remote.example"}):
        assert local.get(url + "&local_only=true", headers=headers).status_code == 403
    assert local.get("/api/os/brain/note?relPath=Archive/hidden.md&local_only=true").status_code == 404


def test_watcher_sees_new_file_without_request(library, monkeypatch):
    monkeypatch.setattr(second_brain, "health", lambda: {"connected": False})
    async def scenario():
        stop = asyncio.Event()
        worker = asyncio.create_task(vault_sync.watch(stop))
        db_path = Path(os.environ["JARVIS_OS_INDEX_DB"])
        def names():
            if not db_path.is_file():
                return set()
            try:
                with sqlite3.connect(db_path) as db:
                    return {item[0] for item in db.execute("SELECT path FROM notes")}
            except sqlite3.OperationalError:
                return set()
        try:
            for _ in range(80):
                if "active.md" in names():
                    break
                await asyncio.sleep(.1)
            assert "active.md" in names()
            (library / "later.md").write_text("new cobalt note", encoding="utf-8")
            for _ in range(70):
                if "later.md" in names():
                    break
                await asyncio.sleep(.1)
            assert "later.md" in names() and "Archive/hidden.md" not in names()
        finally:
            stop.set()
            await worker
    asyncio.run(scenario())


@pytest.mark.parametrize("hits", [1, 0])
def test_builder_only_publishes_verified_scoped_copy(tmp_path, library, monkeypatch, hits):
    script = tmp_path / "generator.py"
    script.write_text(
        "import json, pathlib, sqlite3\nVAULT_ROOT = None\n"
        "def main():\n"
        "    assert VAULT_ROOT.is_dir() and (VAULT_ROOT / 'active.md').exists()\n"
        "    assert not (VAULT_ROOT / 'Archive').exists() and not (VAULT_ROOT / 'restricted.md').exists()\n"
        "    db = sqlite3.connect(OUT_DB)\n    db.execute('create table verified (value)')\n    db.close()\n"
        f"    print(json.dumps(dict(ok=True, unmasked_friend_core_names={hits})))\n",
        encoding="utf-8")
    original = tmp_path / "upstream.sqlite"
    original.write_bytes(b"external archive")
    for key, val in {"NERVA_VAULT_FTS_BUILD_SCRIPT": script, "NERVA_VAULT_FTS_DB": original,
                     "NERVA_AUTO_BUILD_VAULT_INDEX": "1"}.items():
        monkeypatch.setenv(key, str(val))
    cfg = jarvis_os._config(jarvis_os._engine())
    dest = vault_sync.data_root() / "verified_vault_fts.sqlite"
    if hits:
        with pytest.raises(ValueError, match="privacy"):
            vault_sync.rebuild_if_stale(cfg, 1)
        assert not dest.exists()
    else:
        vault_sync.rebuild_if_stale(cfg, 1)
        assert dest.is_file()
    assert original.read_bytes() == b"external archive"
    assert not list(dest.parent.glob(".vault-build-*"))


def test_slow_optional_builder_does_not_pause_sync_or_overlap(library, monkeypatch):
    monkeypatch.setenv("NERVA_AUTO_BUILD_VAULT_INDEX", "1")
    monkeypatch.setattr(second_brain, "start_memory_copilot", lambda: None)
    monkeypatch.setattr(second_brain, "health", lambda: {"connected": False})
    engine = jarvis_os._engine()
    original_sync = engine.sync_vault_index
    syncs = []
    started = threading.Event()
    finished = threading.Event()
    builds = []

    def sync(cfg):
        syncs.append(time.monotonic())
        return original_sync(cfg)

    def slow_builder(_cfg, _stamp, _signature, *, stop):
        builds.append(time.monotonic())
        started.set()
        stop.wait(10)
        finished.set()

    monkeypatch.setattr(engine, "sync_vault_index", sync)
    monkeypatch.setattr(vault_sync, "rebuild_if_stale", slow_builder)

    async def scenario():
        stop = asyncio.Event()
        worker = asyncio.create_task(vault_sync.watch(stop))
        try:
            for _ in range(40):
                if started.is_set():
                    break
                await asyncio.sleep(.05)
            assert started.is_set()
            for _ in range(60):
                if len(syncs) >= 2:
                    break
                await asyncio.sleep(.05)
            assert len(syncs) >= 2 and len(builds) == 1
        finally:
            stop.set()
            await asyncio.wait_for(worker, timeout=.6)
        assert finished.wait(.5)

    asyncio.run(scenario())


def test_stop_kills_external_builder_and_disposes_snapshot(tmp_path, library, monkeypatch):
    marker = tmp_path / "started"
    script = tmp_path / "slow_generator.py"
    script.write_text(
        "import pathlib, time\nVAULT_ROOT = None\n"
        "def main():\n"
        f"    pathlib.Path({str(marker)!r}).write_text('started')\n"
        "    time.sleep(10)\n",
        encoding="utf-8")
    monkeypatch.setenv("NERVA_AUTO_BUILD_VAULT_INDEX", "1")
    monkeypatch.setenv("NERVA_VAULT_FTS_BUILD_SCRIPT", str(script))
    cfg = jarvis_os._config(jarvis_os._engine())
    stop = threading.Event()
    outcome = []

    def build():
        try:
            vault_sync.rebuild_if_stale(cfg, 1, stop=stop)
        except RuntimeError:
            outcome.append("stopped")

    worker = threading.Thread(target=build)
    worker.start()
    for _ in range(100):
        if marker.is_file():
            break
        time.sleep(.05)
    assert marker.is_file()
    stop.set()
    worker.join(2)
    assert not worker.is_alive() and outcome == ["stopped"]
    assert not list(vault_sync.data_root().glob(".vault-build-*"))
    assert not (vault_sync.data_root() / "verified_vault_fts.sqlite").exists()
