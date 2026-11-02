"""H381 — the proof of where each prompt went survives a restart.

The egress ledger (``agents/core/observability/egress_monitor.py``) used to live in
process memory only, so a restart erased every ``llm:<provider>`` row and with it the
evidence the HUD network panel shows. The module singleton now writes each event
through to one owner-only SQLite file under the data root and reads it back, so the
admin route and the HUD see rows from before a restart (and from other processes on the
same data root) next to this process's live ones.

The restart is real here: a child Python process makes a model call through the real
``ClaudeBackend`` (``llm_async_client``, answered by ``httpx.MockTransport`` — no socket)
and exits; this process then plays the restarted hub and reads
``GET /api/admin/network/calls``. Requests never touch the network. The child exits
right after its turn, so it also proves the write-behind queue is drained at exit.

Round 2: ``record`` runs on the event loop (inside the async request hook), so it must
never wait for SQLite. A background writer persists in batches on one connection; the
tests below lock the file from another connection and measure the loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.core.observability.egress_monitor import (
    EGRESS_MONITOR,
    EgressLedgerStore,
    EgressMonitor,
)

REPO = Path(__file__).resolve().parent.parent
SECRET = "h381-PROMPT-CANARY-do-not-persist"

_CLAUDE_BODY = {"content": [{"type": "text", "text": "hello"}]}

_CHILD = textwrap.dedent(
    """
    import asyncio, httpx, sys
    from agents.core.llm.anthropic import ClaudeBackend

    backend = ClaudeBackend(api_key="k")
    backend.client._mounts = {}
    backend.client._transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}]}))
    asyncio.run(backend.generate(model="claude-opus-5", prompt=sys.argv[1]))
    """
)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A fresh data root for this test; the singleton's store follows it."""
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(root))
    monkeypatch.delenv("JARVIS_MEMORY_DIR", raising=False)
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    EGRESS_MONITOR.reset()
    yield root
    EGRESS_MONITOR.reset()


def _admin_get(path: str):
    from agents import web
    from agents.core.routers._deps import admin_guard

    web.app.dependency_overrides[admin_guard] = lambda: None
    try:
        return TestClient(web.app).get(path)
    finally:
        web.app.dependency_overrides.pop(admin_guard, None)


def _model_call_in_another_process(root: Path, prompt: str = SECRET) -> None:
    env = {**os.environ, "JARVIS_HOME": str(root), "PYTHONPATH": str(REPO)}
    env.pop("JARVIS_MEMORY_DIR", None)
    env.pop("JARVIS_PROFILE", None)
    done = subprocess.run([sys.executable, "-c", _CHILD, prompt], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]


async def _claude_turn(prompt: str = "hi"):
    from agents.core.llm.anthropic import ClaudeBackend

    backend = ClaudeBackend(api_key="k")
    backend.client._mounts = {}
    backend.client._transport = httpx.MockTransport(lambda r: httpx.Response(200, json=_CLAUDE_BODY))
    await backend.generate(model="claude-opus-5", prompt=prompt)
    await backend.client.aclose()


def test_a_model_call_from_before_a_restart_is_served_by_the_admin_route(data_root):
    """Old code: the row lived in the child's memory and died with it."""
    _model_call_in_another_process(data_root)

    resp = _admin_get("/api/admin/network/calls")
    assert resp.status_code == 200
    body = resp.json()
    assert "llm:anthropic" in body["plugins"], "the proof of the cloud call did not survive the restart"
    row = body["plugins"]["llm:anthropic"]
    assert row["external"] == 1 and row["last_host"] == "api.anthropic.com"
    assert body["model_egress_total"] == 1
    recent = [r for r in body["recent"] if r["plugin"] == "llm:anthropic"]
    assert recent and recent[0]["host"] == "api.anthropic.com"
    assert recent[0]["origin"] == "restored"
    ledger = body["ledger"]
    assert ledger["persistent"] is True and ledger["error"] == ""
    assert ledger["restored_events"] >= 1 and ledger["since"]


@pytest.mark.asyncio
async def test_restored_and_live_rows_are_merged_without_double_counting(data_root):
    _model_call_in_another_process(data_root)
    await _claude_turn()   # this process: a live row on top of the restored one
    assert EGRESS_MONITOR.flush(10)

    snap = EGRESS_MONITOR.snapshot()
    assert snap["plugins"]["llm:anthropic"]["external"] == 2
    assert snap["plugins"]["llm:anthropic"]["total"] == 2
    origins = [r["origin"] for r in snap["recent"] if r["plugin"] == "llm:anthropic"]
    assert origins == ["live", "restored"]          # newest first
    assert snap["ledger"]["live_events"] == 1
    assert snap["ledger"]["restored_events"] == 1
    assert snap["ledger"]["stored_events"] == 2

    resp = _admin_get("/api/admin/network/calls?plugin=llm:anthropic&limit=1")
    body = resp.json()
    assert set(body["plugins"]) == {"llm:anthropic"}
    assert len(body["recent"]) == 1 and body["recent"][0]["origin"] == "live"


def test_the_ledger_file_is_owner_only_and_never_holds_the_prompt(data_root):
    _model_call_in_another_process(data_root, prompt=SECRET)
    # A refusal reason carrying a URL (plugin and kernel reasons can) is stored redacted.
    EGRESS_MONITOR.record("weather", "wttr.in", "GET", allowed=False, local=False,
                          reason=f"egress blocked: tried https://wttr.in/x?q={SECRET}")
    assert EGRESS_MONITOR.flush(10)

    ledger = data_root / "egress_ledger.db"
    assert ledger.is_file()
    files = [p for p in data_root.iterdir() if p.name.startswith("egress_ledger.db")]
    for path in files:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, f"{path.name} is not owner-only"
        assert SECRET.encode() not in path.read_bytes(), f"{path.name} holds prompt content"
    blob = b"".join(p.read_bytes() for p in files)
    assert b"api.anthropic.com" in blob          # the destination is the proof

    blocked = [r for r in EGRESS_MONITOR.snapshot()["recent"] if r["plugin"] == "weather"][0]
    assert SECRET not in blocked["reason"] and "<url>" in blocked["reason"]


@pytest.mark.asyncio
async def test_no_url_header_or_body_content_reaches_the_file(data_root):
    """Through the real constructor: a request whose path, query, header and body all
    carry the canary leaves only its host behind."""
    from agents.core.llm.egress import llm_async_client

    client = llm_async_client("openrouter", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={})))
    await client.post(f"https://models.example.test/v1/{SECRET}/chat?q={SECRET}",
                      headers={"Authorization": f"Bearer {SECRET}"},
                      json={"messages": [{"role": "user", "content": SECRET}]})
    await client.aclose()
    assert EGRESS_MONITOR.flush(10)

    files = [p for p in data_root.iterdir() if p.name.startswith("egress_ledger.db")]
    assert files
    blob = b"".join(p.read_bytes() for p in files)
    assert SECRET.encode() not in blob
    assert b"models.example.test" in blob
    row = EGRESS_MONITOR.snapshot()["plugins"]["llm:openrouter"]
    assert row["total"] == 1 and row["last_host"] == "models.example.test"


def test_the_store_is_bounded_and_plugin_noise_never_evicts_model_rows(tmp_path):
    store = EgressLedgerStore(tmp_path / "ledger.db", max_events=5, max_rows=4)
    writer = EgressMonitor(store=store)
    for _ in range(3):
        writer.record("llm:anthropic", "api.anthropic.com", "POST", allowed=True, local=False)
    for _ in range(50):
        writer.record("worldview", "127.0.0.1", "GET", allowed=True, local=True)
    assert writer.flush(10)

    reader = EgressMonitor(store=store)       # a restarted process
    snap = reader.snapshot(limit=1000)
    assert snap["ledger"]["stored_events"] == 8            # 5 plugin + 3 model, never more
    assert sum(r["plugin"] == "llm:anthropic" for r in snap["recent"]) == 3
    assert snap["plugins"]["worldview"]["total"] == 50     # tallies stay exact
    assert snap["plugins"]["llm:anthropic"]["external"] == 3
    assert all(r["origin"] == "restored" for r in snap["recent"])

    for name in ("a", "b", "c", "d", "e"):
        writer.record(name, "h", "GET", allowed=True, local=True)
    assert writer.flush(10)
    assert len(reader.snapshot(limit=0)["plugins"]) == 4   # tally rows are bounded too


@pytest.mark.asyncio
async def test_an_unwritable_store_never_breaks_egress_and_says_so(tmp_path, monkeypatch):
    from agents.core.llm import egress

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monitor = EgressMonitor(store=EgressLedgerStore(blocker / "ledger.db"))
    monkeypatch.setattr(egress, "EGRESS_MONITOR", monitor)

    client = egress.llm_async_client("anthropic", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=_CLAUDE_BODY)))
    resp = await client.post("https://api.anthropic.com/v1/messages", json={})
    await client.aclose()
    assert resp.status_code == 200                       # the turn still ran
    assert monitor.flush(10)

    snap = monitor.snapshot()
    assert snap["plugins"]["llm:anthropic"]["external"] == 1   # still counted, from memory
    assert snap["recent"][0]["origin"] == "live"
    assert snap["ledger"]["persistent"] is False
    assert snap["ledger"]["unsaved_events"] == 1
    assert snap["ledger"]["error"]


def test_a_failed_write_is_kept_as_unsaved_beside_persisted_rows(tmp_path):
    store = EgressLedgerStore(tmp_path / "ledger.db")
    monitor = EgressMonitor(store=store)
    monitor.record("llm:gemini", "generativelanguage.googleapis.com", "POST", allowed=True, local=False)
    assert monitor.flush(10)

    original = store.append_many
    store.append_many = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    monitor.record("llm:gemini", "generativelanguage.googleapis.com", "POST", allowed=True, local=False)
    assert monitor.flush(10)
    store.append_many = original

    snap = monitor.snapshot()
    assert snap["plugins"]["llm:gemini"]["total"] == 2
    assert [r["origin"] for r in snap["recent"]] == ["unsaved", "live"]
    assert snap["ledger"]["persistent"] is True and snap["ledger"]["unsaved_events"] == 1
    assert "write failed" in snap["ledger"]["error"]


def test_the_support_bundle_reports_restored_model_egress(data_root):
    from agents.core import support_bundle

    _model_call_in_another_process(data_root)
    egress = support_bundle._egress()
    assert egress["model_egress_total"] == 1


def test_a_forget_erases_the_ledger_like_any_other_store(data_root):
    """The file is under the data root and not on a KEEP list: ``data_purge`` deletes
    its rows (schema kept), so the next snapshot is empty."""
    from agents.core import data_purge

    EGRESS_MONITOR.record("llm:anthropic", "api.anthropic.com", "POST", allowed=True, local=False)
    assert EGRESS_MONITOR.flush(10)
    assert not data_purge._is_kept(Path("egress_ledger.db"))
    deleted = data_purge._purge_db(data_root / "egress_ledger.db")
    assert sum(deleted.values()) >= 2
    snap = EgressMonitor(store=EGRESS_MONITOR._store).snapshot()
    assert snap["plugins"] == {} and snap["recent"] == []
    # The writer keeps its connection open; the purge's VACUUM + WAL TRUNCATE still
    # reach every byte (no host left in the file or its sidecars).
    assert EGRESS_MONITOR._store._writer is not None
    blob = b"".join(p.read_bytes() for p in data_root.iterdir()
                    if p.name.startswith("egress_ledger.db"))
    assert b"api.anthropic.com" not in blob


def test_snapshot_shape_is_unchanged_for_a_memory_only_monitor():
    """Ad-hoc monitors (tests, tools) stay memory-only and report it."""
    monitor = EgressMonitor()
    monitor.record("weather", "wttr.in", "GET", allowed=True, local=False)
    snap = monitor.snapshot()
    assert snap["ledger"]["persistent"] is False and snap["ledger"]["store"] is None
    assert json.loads(json.dumps(snap))["plugins"]["weather"]["external"] == 1


# ── round 2: the event loop never waits for the ledger file ──────────────────

def _lock_the_file(path: Path) -> sqlite3.Connection:
    """Another connection holding the write lock — what a concurrent CLI turn's
    writer, a backup or a forget does to the file for a moment."""
    holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    return holder


def test_record_never_waits_for_a_locked_ledger_file(tmp_path):
    """Old code: every record() opened the file and waited out the 0.5 s busy timeout
    while another connection held the write lock — 20 records took ~10 s."""
    store = EgressLedgerStore(tmp_path / "ledger.db")
    monitor = EgressMonitor(store=store)
    monitor.record("llm:anthropic", "api.anthropic.com", "POST", allowed=True, local=False)
    assert monitor.flush(10)

    holder = _lock_the_file(store.path)
    try:
        started = time.perf_counter()
        for _ in range(20):
            monitor.record("llm:anthropic", "api.anthropic.com", "POST", allowed=True, local=False)
        elapsed = time.perf_counter() - started
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert elapsed < 0.25, f"20 record() calls took {elapsed:.2f}s with the file locked"

    assert monitor.flush(10)
    snap = monitor.snapshot()
    # Every event is accounted for exactly once: on disk, or held as unsaved.
    assert snap["plugins"]["llm:anthropic"]["total"] == 21
    assert snap["ledger"]["stored_events"] + snap["ledger"]["unsaved_events"] == 21
    assert snap["ledger"]["queued_events"] == 0


async def test_the_event_loop_keeps_ticking_while_the_ledger_file_is_locked(tmp_path, monkeypatch):
    """Through the real request hook (llm_async_client): ten cloud requests while the
    ledger file is locked never stall the loop. Old code: each request's hook blocked
    the loop for the busy timeout (the round-1 review measured a 1009 ms gap)."""
    from agents.core.llm import egress

    store = EgressLedgerStore(tmp_path / "ledger.db")
    monitor = EgressMonitor(store=store)
    monitor.record("llm:anthropic", "api.anthropic.com", "POST", allowed=True, local=False)
    assert monitor.flush(10)
    monkeypatch.setattr(egress, "EGRESS_MONITOR", monitor)
    client = egress.llm_async_client("anthropic", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=_CLAUDE_BODY)))

    gaps: list[float] = []
    done = asyncio.Event()

    async def ticker():
        last = time.perf_counter()
        while not done.is_set():
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    holder = _lock_the_file(store.path)
    try:
        tick = asyncio.create_task(ticker())
        await asyncio.sleep(0.03)
        for _ in range(10):
            resp = await client.post("https://api.anthropic.com/v1/messages", json={})
            assert resp.status_code == 200
        done.set()
        await tick
    finally:
        holder.execute("ROLLBACK")
        holder.close()
        await client.aclose()
    assert max(gaps) < 0.25, f"the event loop stalled for {max(gaps):.2f}s"
    assert monitor.flush(10)
    assert monitor.snapshot()["plugins"]["llm:anthropic"]["total"] == 11


def test_the_writer_uses_one_connection_and_batches_its_transactions(tmp_path, monkeypatch):
    """Old code opened, wrote and closed the file for every event (the round-1 review
    counted ~4 fsyncs per event: closing the last connection checkpoints and deletes the
    WAL). The writer keeps one connection and commits a batch per transaction."""
    store = EgressLedgerStore(tmp_path / "ledger.db")
    monitor = EgressMonitor(store=store)
    connects = []
    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: connects.append(a) or real_connect(*a, **k))
    commits = []
    real_append = store.append_many
    monkeypatch.setattr(store, "append_many",
                        lambda boot, events, *a, **k: commits.append(len(events)) or real_append(
                            boot, events, *a, **k))

    gate = threading.Event()
    blocked = store.append_many

    def slow_first(boot, events, *a, **k):
        gate.wait(10)       # the first batch waits, so the next 199 queue up behind it
        return blocked(boot, events, *a, **k)

    monkeypatch.setattr(store, "append_many", slow_first)
    for _ in range(200):
        monitor.record("weather", "wttr.in", "GET", allowed=True, local=False)
    gate.set()
    assert monitor.flush(10)
    assert sum(commits) == 200
    assert len(commits) <= 3, f"{len(commits)} transactions for 200 events"
    assert len(connects) == 1, f"{len(connects)} connections for 200 events"
    assert EgressMonitor(store=store).snapshot(limit=0)["plugins"]["weather"]["total"] == 200
    store.close()


def test_a_queued_event_is_served_live_and_counted_once_while_it_is_written(tmp_path, monkeypatch):
    """A snapshot never waits for the writer and never loses or double-counts an event:
    while the batch is being written it is served from the queue; in the window after
    the commit and before the writer clears its batch it is served from the file only."""
    store = EgressLedgerStore(tmp_path / "ledger.db")
    monitor = EgressMonitor(store=store)
    entered, committed, release_before, release_after = (threading.Event() for _ in range(4))
    real_append = store.append_many

    def staged(boot, events, *a, **k):
        entered.set()
        release_before.wait(10)
        real_append(boot, events, *a, **k)
        committed.set()
        release_after.wait(10)

    monkeypatch.setattr(store, "append_many", staged)
    monitor.record("llm:openrouter", "openrouter.ai", "POST", allowed=True, local=False)
    assert entered.wait(10)

    started = time.perf_counter()
    before = monitor.snapshot()                    # in flight, not on disk
    assert time.perf_counter() - started < 0.5     # did not wait for the writer
    assert before["plugins"]["llm:openrouter"]["total"] == 1
    assert [r["origin"] for r in before["recent"]] == ["live"]
    assert before["ledger"]["queued_events"] == 1 and before["ledger"]["stored_events"] == 0

    release_before.set()
    assert committed.wait(10)
    during = monitor.snapshot()                    # on disk, writer not yet done
    assert during["plugins"]["llm:openrouter"]["total"] == 1
    assert len(during["recent"]) == 1 and during["recent"][0]["origin"] == "live"
    assert during["ledger"]["queued_events"] == 0 and during["ledger"]["stored_events"] == 1

    release_after.set()
    assert monitor.flush(10)
    after = monitor.snapshot()
    assert after["plugins"]["llm:openrouter"]["total"] == 1 and len(after["recent"]) == 1


def test_the_async_routes_read_the_file_off_the_event_loop(data_root, monkeypatch):
    """GET /api/admin/network/calls, GET /api/system-map and GET /api/support/bundle are
    async routes: the ledger's SQLite read runs in a worker thread, never on the event loop."""
    from agents import web
    from agents.core.routers._deps import user_guard

    where = []
    real_snapshot = EGRESS_MONITOR.snapshot

    def snapshot(*a, **k):
        try:
            asyncio.get_running_loop()
            where.append("event loop")
        except RuntimeError:
            where.append("worker thread")
        return real_snapshot(*a, **k)

    monkeypatch.setattr(EGRESS_MONITOR, "snapshot", snapshot)
    assert _admin_get("/api/admin/network/calls").status_code == 200
    web.app.dependency_overrides[user_guard] = lambda: None
    try:
        assert TestClient(web.app).get("/api/system-map").status_code == 200
    finally:
        web.app.dependency_overrides.pop(user_guard, None)
    bundle = _admin_get("/api/support/bundle")
    assert bundle.status_code == 200 and "model_egress_total" in bundle.json()["egress"]
    assert where == ["worker thread", "worker thread", "worker thread"], where


_SLOW_CHILD = textwrap.dedent(
    """
    import time
    from agents.core.observability.egress_monitor import EGRESS_MONITOR

    store = EGRESS_MONITOR._store
    real = store.append_many

    def slow(*args, **kwargs):     # a slow disk: the writer is still busy when we exit
        time.sleep(0.2)
        return real(*args, **kwargs)

    store.append_many = slow
    for _ in range(3):
        EGRESS_MONITOR.record("llm:anthropic", "api.anthropic.com", "POST",
                              allowed=True, local=False)
    """
)


def test_queued_events_reach_the_file_when_the_process_exits(data_root):
    """Write-behind must not cost a short CLI turn its proof: interpreter exit waits
    (bounded) for the queue. Without the exit drain the daemon writer dies with the
    process and the file never holds these rows."""
    env = {**os.environ, "JARVIS_HOME": str(data_root), "PYTHONPATH": str(REPO)}
    env.pop("JARVIS_MEMORY_DIR", None)
    env.pop("JARVIS_PROFILE", None)
    done = subprocess.run([sys.executable, "-c", _SLOW_CHILD], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    snap = EgressMonitor(store=EgressLedgerStore(data_root / "egress_ledger.db")).snapshot()
    assert snap["plugins"]["llm:anthropic"]["total"] == 3
    assert [r["origin"] for r in snap["recent"]] == ["restored"] * 3
