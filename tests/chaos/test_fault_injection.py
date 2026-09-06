"""T-0.63 — failure-injection harness (kill LLM / corrupt DB / disk-full / clock skew).

Hermetic: no network (httpx.MockTransport sits *under* the patched send), no
subprocess, no OS permission. The data root is redirected to ``tmp_path`` through
``JARVIS_HOME`` so the path-bounded faults can only ever touch the test's own files.
"""

from __future__ import annotations

import builtins
import io
import sqlite3
import sys
import time
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.core.observability.fault_injection as fi  # noqa: E402
from agents.core.llm.base import LMStudioBackend, is_degraded_reply  # noqa: E402
from agents.core.observability.fault_injection import (  # noqa: E402
    FaultInjectionRefused,
    FaultPlan,
    active_faults,
    boot_problem,
    inject,
    refusal_reason,
)
from agents.core.security.audit import AuditLogger  # noqa: E402
from agents.core.security.types import SecurityEvent, SecurityEventType  # noqa: E402


@pytest.fixture
def armed(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    monkeypatch.setenv("JARVIS_FAULT_INJECT", "1")
    return tmp_path


def _mock_backend(reply: str = "hello from the model") -> LMStudioBackend:
    """An LM Studio backend whose transport always answers — so any degraded reply
    can only come from the fault, never from a missing server."""
    backend = LMStudioBackend()

    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
        }, request=request)

    backend.client = httpx.AsyncClient(
        base_url=backend.base_url, transport=httpx.MockTransport(handler), timeout=backend.client.timeout,
    )
    return backend


# ── plan validation + fingerprint ────────────────────────────────────────────

@pytest.mark.parametrize("kwargs", [
    {"kind": "nuke_from_orbit"},
    {"kind": "llm_down", "duration_s": 0},
    {"kind": "llm_down", "duration_s": -1},
    {"kind": "llm_down", "duration_s": float("inf")},
    {"kind": "llm_down", "duration_s": fi.MAX_DURATION_S + 1},
    {"kind": "llm_down", "target": ""},
    {"kind": "db_corrupt"},
    {"kind": "clock_skew"},
    {"kind": "clock_skew", "skew_s": float("nan")},
    {"kind": "clock_skew", "skew_s": fi.MAX_SKEW_S * 2},
    {"kind": "llm_down", "skew_s": 5},
    {"kind": "llm_down", "note": "x" * 201},
])
def test_plan_rejects_malformed(kwargs):
    with pytest.raises(ValueError):
        FaultPlan(**kwargs)


def test_plan_is_frozen_and_fingerprinted():
    a = FaultPlan(kind="llm_down", duration_s=5)
    b = FaultPlan(kind="llm_down", duration_s=5)
    c = FaultPlan(kind="llm_down", duration_s=6)
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != c.fingerprint()
    assert len(a.fingerprint()) == 64
    with pytest.raises(AttributeError):
        a.kind = "disk_full"  # type: ignore[misc]
    assert set(a.to_dict()) == {"kind", "duration_s", "target", "skew_s", "note"}


# ── posture: default off, hardened refuses, boot guard sentence ──────────────

def test_default_off_refuses_by_name(monkeypatch):
    monkeypatch.delenv("JARVIS_FAULT_INJECT", raising=False)
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    assert refusal_reason() == fi.REASON_DISABLED
    with pytest.raises(FaultInjectionRefused) as exc, inject(FaultPlan(kind="llm_down")):
        pass
    assert exc.value.reason == fi.REASON_DISABLED
    assert boot_problem() is None
    assert active_faults() == []


def test_hardened_wins_over_armed(monkeypatch):
    monkeypatch.setenv("JARVIS_FAULT_INJECT", "1")
    monkeypatch.setenv("JARVIS_HARDENED", "1")
    assert refusal_reason() == fi.REASON_HARDENED
    with pytest.raises(FaultInjectionRefused) as exc, inject(FaultPlan(kind="clock_skew", skew_s=60)):
        pass
    assert exc.value.reason == fi.REASON_HARDENED
    assert boot_problem() == fi.BOOT_PROBLEM
    assert time.time is not None and "fault" not in getattr(time.time, "__name__", "")


def test_malformed_flag_spelling_stays_off(monkeypatch):
    monkeypatch.setenv("JARVIS_FAULT_INJECT", "yess")
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    assert refusal_reason() == fi.REASON_DISABLED


# ── llm_down: the backend degrades honestly, then recovers ───────────────────

async def test_llm_down_backend_serves_degraded_reply_not_exception(armed):
    backend = _mock_backend()
    assert not is_degraded_reply(await backend.generate("m", "hi"))
    with inject(FaultPlan(kind="llm_down", duration_s=10)) as handle:
        reply = await backend.generate("m", "hi")
        assert is_degraded_reply(reply)
        assert "can't reach" in reply.lower()
        assert "fault_injection" not in reply, "the raw exception must never reach the bubble"
        assert handle.events and handle.events[0].detail.startswith("llm_down:POST")
        assert handle.active
    assert not is_degraded_reply(await backend.generate("m", "hi"))
    assert handle.released and not handle.active


async def test_llm_down_target_filter_is_host_scoped(armed):
    backend = _mock_backend()
    with inject(FaultPlan(kind="llm_down", target="nowhere.invalid")):
        assert not is_degraded_reply(await backend.generate("m", "hi"))
    with inject(FaultPlan(kind="llm_down", target="localhost")):
        assert is_degraded_reply(await backend.generate("m", "hi"))


async def test_llm_down_expires_after_duration_without_release(armed, monkeypatch):
    backend = _mock_backend()
    now = [1000.0]
    monkeypatch.setattr(fi, "_monotonic", lambda: now[0])
    with inject(FaultPlan(kind="llm_down", duration_s=2)) as handle:
        assert is_degraded_reply(await backend.generate("m", "hi"))
        now[0] += 2.5
        assert handle.expired and not handle.active
        assert handle.remaining_s == 0.0
        assert not is_degraded_reply(await backend.generate("m", "hi"))
        assert active_faults()[0]["active"] is False


def test_llm_down_sync_client_and_restore_on_exception(armed):
    orig_async, orig_sync = httpx.AsyncClient.send, httpx.Client.send

    def handler(request):
        return httpx.Response(204, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="boom"), inject(FaultPlan(kind="llm_down")):
        with pytest.raises(httpx.ConnectError):
            client.get("http://localhost:1234/v1/models")
        raise RuntimeError("boom")
    assert httpx.AsyncClient.send is orig_async and httpx.Client.send is orig_sync
    assert client.get("http://localhost:1234/v1/models").status_code == 204
    assert active_faults() == []


# ── db_corrupt: a non-audit store dies honestly, the audit chain survives ─────

def _audit_event(preview: str) -> SecurityEvent:
    return SecurityEvent(SecurityEventType.AUDIT_LOG, time.time(), [], preview, "blocked")


def _seed_store(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    conn.executemany("INSERT INTO notes (body) VALUES (?)", [(f"n{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def test_db_corrupt_non_audit_store_keeps_audit_chain_verifiable(armed):
    audit = AuditLogger(db_path=str(armed / "security" / "audit.db"))
    for i in range(3):
        audit.log(_audit_event(f"e{i}"))
    assert audit.verify_chain() == (True, None)
    store = armed / "notes.db"
    _seed_store(store)
    original = store.read_bytes()

    with inject(FaultPlan(kind="db_corrupt", target="notes.db", duration_s=10)) as handle:
        assert not store.read_bytes().startswith(fi._SQLITE_MAGIC)
        assert (armed / "notes.db.fault-backup").is_file()
        with pytest.raises(sqlite3.DatabaseError):
            sqlite3.connect(store).execute("SELECT count(*) FROM notes").fetchone()
        # The failure is contained: the audit chain (a different store) still verifies
        # and still accepts writes while the neighbour is corrupt.
        audit.log(_audit_event("during"))
        assert audit.verify_chain() == (True, None)
        assert handle.events[0].detail.startswith("db_corrupt:notes.db")

    assert store.read_bytes() == original
    assert not (armed / "notes.db.fault-backup").exists()
    assert sqlite3.connect(store).execute("SELECT count(*) FROM notes").fetchone()[0] == 3
    assert audit.verify_chain() == (True, None)


def test_db_corrupt_refuses_outside_data_root_and_missing(armed, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "x.db"
    _seed_store(outside)
    with pytest.raises(FaultInjectionRefused) as exc, inject(FaultPlan(kind="db_corrupt", target=str(outside))):
        pass
    assert exc.value.reason == fi.REASON_OUTSIDE_ROOT
    assert outside.read_bytes().startswith(fi._SQLITE_MAGIC)
    with pytest.raises(FaultInjectionRefused) as exc, inject(FaultPlan(kind="db_corrupt", target="never-created.db")):
        pass
    assert exc.value.reason == fi.REASON_TARGET_MISSING
    with pytest.raises(FaultInjectionRefused) as exc, inject(FaultPlan(kind="db_corrupt", target="../escape.db")):
        pass
    assert exc.value.reason == fi.REASON_OUTSIDE_ROOT
    assert active_faults() == []


# ── disk_full: writes refused with ENOSPC, reads pass, nothing crashes ────────

def test_disk_full_write_refused_not_crashed(armed, tmp_path_factory):
    existing = armed / "before.txt"
    existing.write_text("kept", encoding="utf-8")
    elsewhere = tmp_path_factory.mktemp("other")
    orig_open, orig_io_open, orig_connect = builtins.open, io.open, sqlite3.connect

    with inject(FaultPlan(kind="disk_full", duration_s=10)) as handle:
        with pytest.raises(OSError) as exc:
            (armed / "new.txt").write_text("x", encoding="utf-8")
        assert exc.value.errno == fi.errno.ENOSPC
        with pytest.raises(OSError), open(armed / "append.log", "a"):
            pass
        assert existing.read_text(encoding="utf-8") == "kept"
        (elsewhere / "fine.txt").write_text("ok", encoding="utf-8")

        conn = sqlite3.connect(armed / "state.db")
        assert conn.execute("SELECT 1").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match="disk is full"):
            conn.execute("CREATE TABLE t (x)")
        with pytest.raises(sqlite3.OperationalError, match="disk is full"):
            conn.cursor().execute("INSERT INTO t VALUES (1)")
        conn.close()
        # A store constructed inside the window fails at its schema DDL — an honest
        # error at the boundary, not a half-created database and not a crash.
        with pytest.raises(sqlite3.OperationalError):
            AuditLogger(db_path=str(armed / "security" / "late.db"))
        kinds = {e.detail.split(":")[0] for e in handle.events}
        assert kinds == {"disk_full"}
        assert any(e.detail.startswith("disk_full:sqlite") for e in handle.events)

    assert builtins.open is orig_open and io.open is orig_io_open and sqlite3.connect is orig_connect
    (armed / "new.txt").write_text("x", encoding="utf-8")
    conn = sqlite3.connect(armed / "state.db")
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()


def test_disk_full_scope_can_be_narrowed_to_a_subdirectory(armed):
    (armed / "sub").mkdir()
    with inject(FaultPlan(kind="disk_full", target="sub")):
        (armed / "root-ok.txt").write_text("x", encoding="utf-8")
        with pytest.raises(OSError):
            (armed / "sub" / "no.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FaultInjectionRefused), inject(FaultPlan(kind="disk_full", target="/")):
        pass


def test_disk_full_commit_of_pending_transaction_is_refused(armed, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(fi, "_monotonic", lambda: now[0])
    with inject(FaultPlan(kind="disk_full", duration_s=5)):
        conn = sqlite3.connect(armed / "tx.db")
        now[0] = 10.0  # expired: DDL passes through again ...
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (1)")
        now[0] = 0.0  # ... re-armed: the pending commit hits the full disk
        with pytest.raises(sqlite3.OperationalError, match="disk is full"):
            conn.commit()
        conn.rollback()
        conn.close()


# ── clock_skew: time.time moves, the harness's own expiry clock does not ──────

def test_clock_skew_offsets_time_time_and_handle_clock(armed):
    real = time.time
    with inject(FaultPlan(kind="clock_skew", skew_s=-6 * 3600, duration_s=10)) as handle:
        before = real()
        assert time.time() < before - 6 * 3600 + 1
        assert handle.clock() < before - 6 * 3600 + 1
        assert time.time_ns() < int((before - 6 * 3600 + 1) * 1e9)
        assert handle.active and handle.remaining_s > 5
    assert time.time is real
    assert abs(time.time() - real()) < 1


def test_clock_skew_can_drive_an_injectable_clock(armed):
    """The attention ledger's day window follows the handle clock: two days of skew
    move it to a different owner-local day than a real-clock ledger sees."""
    from agents.core.ambient.policy import AttentionLedger

    real = AttentionLedger(armed / "attention-real.db", timezone_name="Europe/Bucharest")
    try:
        with inject(FaultPlan(kind="clock_skew", skew_s=2 * 86400, duration_s=10)) as handle:
            skewed = AttentionLedger(armed / "attention-skewed.db", timezone_name="Europe/Bucharest",
                                     clock=handle.clock)
            try:
                assert skewed.status()["window_id"] != real.status()["window_id"]
                assert skewed.status()["window_id"] > real.status()["window_id"]
            finally:
                skewed.close()
    finally:
        real.close()


# ── registry: one per kind, snapshots, nested different kinds ────────────────

def test_same_kind_twice_is_refused_and_nested_kinds_compose(armed):
    with inject(FaultPlan(kind="llm_down")) as outer:
        with pytest.raises(FaultInjectionRefused) as exc, inject(FaultPlan(kind="llm_down")):
            pass
        assert exc.value.reason == fi.REASON_ALREADY_ACTIVE
        with inject(FaultPlan(kind="clock_skew", skew_s=5)):
            snaps = {s["kind"]: s for s in active_faults()}
            assert set(snaps) == {"llm_down", "clock_skew"}
            assert snaps["llm_down"]["fingerprint"] == outer.plan.fingerprint()
            assert snaps["clock_skew"]["last_events"] == ["clock_skew:+5s"]
        assert [s["kind"] for s in active_faults()] == ["llm_down"]
    assert active_faults() == []


def test_db_corrupt_restore_survives_an_enclosing_disk_full(armed):
    store = armed / "inner.db"
    _seed_store(store)
    original = store.read_bytes()
    with inject(FaultPlan(kind="disk_full")):
        with inject(FaultPlan(kind="db_corrupt", target="inner.db")):
            assert not store.read_bytes().startswith(fi._SQLITE_MAGIC)
        assert store.read_bytes() == original, "restore must use the real open(), not the faulted one"


def test_handle_event_ring_is_bounded(armed):
    with inject(FaultPlan(kind="llm_down")) as handle:
        for i in range(fi.MAX_EVENTS + 7):
            handle.record(f"e{i}")
        assert len(handle.events) == fi.MAX_EVENTS
        assert handle.dropped_events == 7
        assert len(handle.snapshot()["last_events"]) == 20


def test_fault_scope_documents_every_kind():
    assert set(fi.FAULT_SCOPE) == set(fi.FAULT_KINDS)
    for scope in fi.FAULT_SCOPE.values():
        assert scope["intercepts"] and scope["not_intercepted"]
