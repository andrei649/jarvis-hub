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
``GET /api/admin/network/calls``. Requests never touch the network.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.core.observability.egress_monitor import EGRESS_MONITOR, EgressMonitor

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

    files = [p for p in data_root.iterdir() if p.name.startswith("egress_ledger.db")]
    assert files
    blob = b"".join(p.read_bytes() for p in files)
    assert SECRET.encode() not in blob
    assert b"models.example.test" in blob
    row = EGRESS_MONITOR.snapshot()["plugins"]["llm:openrouter"]
    assert row["total"] == 1 and row["last_host"] == "models.example.test"


def test_the_store_is_bounded_and_plugin_noise_never_evicts_model_rows(tmp_path):
    from agents.core.observability.egress_monitor import EgressLedgerStore

    store = EgressLedgerStore(tmp_path / "ledger.db", max_events=5, max_rows=4)
    writer = EgressMonitor(store=store)
    for _ in range(3):
        writer.record("llm:anthropic", "api.anthropic.com", "POST", allowed=True, local=False)
    for _ in range(50):
        writer.record("worldview", "127.0.0.1", "GET", allowed=True, local=True)

    reader = EgressMonitor(store=store)       # a restarted process
    snap = reader.snapshot(limit=1000)
    assert snap["ledger"]["stored_events"] == 8            # 5 plugin + 3 model, never more
    assert sum(r["plugin"] == "llm:anthropic" for r in snap["recent"]) == 3
    assert snap["plugins"]["worldview"]["total"] == 50     # tallies stay exact
    assert snap["plugins"]["llm:anthropic"]["external"] == 3
    assert all(r["origin"] == "restored" for r in snap["recent"])

    for name in ("a", "b", "c", "d", "e"):
        writer.record(name, "h", "GET", allowed=True, local=True)
    assert len(reader.snapshot(limit=0)["plugins"]) == 4   # tally rows are bounded too


@pytest.mark.asyncio
async def test_an_unwritable_store_never_breaks_egress_and_says_so(tmp_path, monkeypatch):
    from agents.core.llm import egress
    from agents.core.observability.egress_monitor import EgressLedgerStore

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monitor = EgressMonitor(store=EgressLedgerStore(blocker / "ledger.db"))
    monkeypatch.setattr(egress, "EGRESS_MONITOR", monitor)

    client = egress.llm_async_client("anthropic", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=_CLAUDE_BODY)))
    resp = await client.post("https://api.anthropic.com/v1/messages", json={})
    await client.aclose()
    assert resp.status_code == 200                       # the turn still ran

    snap = monitor.snapshot()
    assert snap["plugins"]["llm:anthropic"]["external"] == 1   # still counted, from memory
    assert snap["recent"][0]["origin"] == "live"
    assert snap["ledger"]["persistent"] is False
    assert snap["ledger"]["unsaved_events"] == 1
    assert snap["ledger"]["error"]


def test_a_failed_write_is_kept_as_unsaved_beside_persisted_rows(tmp_path):
    from agents.core.observability.egress_monitor import EgressLedgerStore

    store = EgressLedgerStore(tmp_path / "ledger.db")
    monitor = EgressMonitor(store=store)
    monitor.record("llm:gemini", "generativelanguage.googleapis.com", "POST", allowed=True, local=False)

    original = store.append
    store.append = lambda boot, event: (_ for _ in ()).throw(OSError("disk full"))
    monitor.record("llm:gemini", "generativelanguage.googleapis.com", "POST", allowed=True, local=False)
    store.append = original

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
    assert not data_purge._is_kept(Path("egress_ledger.db"))
    deleted = data_purge._purge_db(data_root / "egress_ledger.db")
    assert sum(deleted.values()) >= 2
    snap = EgressMonitor(store=EGRESS_MONITOR._store).snapshot()
    assert snap["plugins"] == {} and snap["recent"] == []


def test_snapshot_shape_is_unchanged_for_a_memory_only_monitor():
    """Ad-hoc monitors (tests, tools) stay memory-only and report it."""
    monitor = EgressMonitor()
    monitor.record("weather", "wttr.in", "GET", allowed=True, local=False)
    snap = monitor.snapshot()
    assert snap["ledger"]["persistent"] is False and snap["ledger"]["store"] is None
    assert json.loads(json.dumps(snap))["plugins"]["weather"]["external"] == 1
