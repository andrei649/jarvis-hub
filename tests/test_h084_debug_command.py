"""H084: the owner can save a local, redacted diagnostic report from chat."""

from __future__ import annotations

import asyncio
import os
import stat
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import diagnostic_commands, log_tail, settings_db, support_bundle
from agents.core.channels import outbound_safety
from agents.core.commands import Principal, build_default_registry

OWNER = Principal(channel="web", admin=True)
GUEST = Principal(channel="telegram", sender="guest", admin=False)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("JARVIS_HOME", str(home))
    orch = SimpleNamespace(commands=build_default_registry())
    return SimpleNamespace(home=home, orch=orch)


async def _dispatch(rig, text="/debug", principal=OWNER):
    return await rig.orch.commands.dispatch(text, orch=rig.orch, principal=principal)


requires_private_report = pytest.mark.skipif(
    not diagnostic_commands.SUPPORTED, reason="openat and nofollow report creation unavailable")


def _bundle(message="A diagnostic warning"):
    return {"meta": {"version": "test", "platform": "linux", "python": "3.12",
                     "generated_at": "NOW"},
            "logs": {"included": True, "level": "WARNING", "file": "jarvis.log",
                     "entries": [message], "truncated": False, "note": ""}}


def _report_path(reply: str) -> Path:
    assert reply.startswith("Local diagnostic report: ")
    return Path(reply.removeprefix("Local diagnostic report: "))


@requires_private_report
async def test_owner_gets_private_local_report_and_guest_cannot_create_one(rig, monkeypatch):
    calls = []
    monkeypatch.setattr(log_tail, "_redactor", lambda: object())
    monkeypatch.setattr(outbound_safety, "_known_redactor", None)
    monkeypatch.setattr(support_bundle, "build_bundle",
                        lambda orch, **kw: calls.append((orch, kw)) or _bundle())
    assert rig.orch.commands.get("debug").tier == "admin"
    denied = await _dispatch(rig, principal=GUEST)
    assert denied.status == "refused" and not rig.home.exists()
    bad = await _dispatch(rig, "/debug /tmp/other")
    assert "Usage" in bad.reply and not rig.home.exists()

    result = await _dispatch(rig)
    assert result.status == "answered"
    path = _report_path(result.reply)
    assert path.parent == rig.home / "support_reports"
    assert path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert "A diagnostic warning" in path.read_text(encoding="utf-8")
    assert len(calls) == 1 and calls[0][0] is rig.orch
    assert calls[0][1]["log_lines"] == 50 and calls[0][1]["now_iso"]


@requires_private_report
async def test_report_fields_are_redacted_before_the_file_is_written(rig, monkeypatch):
    secret = "sk-DIAGNOSTIC-SECRET-1234567890"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setattr(log_tail, "_redactor", lambda: object())
    monkeypatch.setattr(support_bundle, "build_bundle", lambda _orch, **_kw: _bundle(secret))
    path = _report_path((await _dispatch(rig)).reply)
    text = path.read_text(encoding="utf-8")
    assert secret not in text and "[REDACTED" in text


@requires_private_report
async def test_real_bundle_reads_the_bounded_log_tail_and_masks_a_key(rig, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", rig.home / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    rig.home.mkdir()
    log = rig.home / "jarvis.log"
    secret = "sk-DIAGNOSTIC-REAL-1234567890"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setenv("JARVIS_LOG_FILE", str(log))
    monkeypatch.setattr(log_tail, "_writer_state", lambda: {"configured": False})
    log.write_text(f"2026-11-12 12:00:00  WARNING  jarvis.test  key={secret}\n",
                   encoding="utf-8")

    result = await _dispatch(rig)
    text = _report_path(result.reply).read_text(encoding="utf-8")
    assert "newest WARNING+" in text and "jarvis.test" in text
    assert secret not in text and "[REDACTED" in text


@requires_private_report
async def test_absent_log_file_is_reported_but_unavailable_redactor_refuses(rig, monkeypatch):
    monkeypatch.setattr(log_tail, "_redactor", lambda: object())
    missing = _bundle("")
    missing["logs"].update(entries=[], file=None, note="File logging is off.")
    monkeypatch.setattr(support_bundle, "build_bundle", lambda _orch, **_kw: missing)
    path = _report_path((await _dispatch(rig)).reply)
    assert "File logging is off" in path.read_text(encoding="utf-8")

    failed_during_read = _bundle("")
    failed_during_read["logs"].update(entries=[], note="The secret redactor could not be loaded.")
    monkeypatch.setattr(support_bundle, "build_bundle", lambda _orch, **_kw: failed_during_read)
    result = await _dispatch(rig)
    assert "redactor" in result.reply.lower() and list(path.parent.iterdir()) == [path]

    def unavailable():
        raise log_tail.RedactionUnavailable("scanner unavailable")

    monkeypatch.setattr(log_tail, "_redactor", unavailable)
    result = await _dispatch(rig)
    assert "redactor" in result.reply.lower() and "report:" not in result.reply.lower()
    assert list(path.parent.iterdir()) == [path]


@requires_private_report
async def test_redaction_failure_and_report_write_failure_leave_no_new_file(rig, monkeypatch):
    monkeypatch.setattr(log_tail, "_redactor", lambda: object())
    monkeypatch.setattr(support_bundle, "build_bundle", lambda _orch, **_kw: _bundle())
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda _text: 42)
    refused = await _dispatch(rig)
    assert "redaction" in refused.reply.lower() and not (rig.home / "support_reports").exists()

    def failed_redactor(_text):
        raise RuntimeError("redactor failed")

    monkeypatch.setattr(outbound_safety, "_known_redactor", failed_redactor)
    refused = await _dispatch(rig)
    assert "redaction" in refused.reply.lower() and not (rig.home / "support_reports").exists()

    monkeypatch.setattr(outbound_safety, "_known_redactor", None)
    def failed_fsync(_fd):
        raise OSError("disk full")
    monkeypatch.setattr(os, "fsync", failed_fsync)
    failed = await _dispatch(rig)
    assert "could not" in failed.reply.lower() and "report:" not in failed.reply.lower()
    assert list((rig.home / "support_reports").iterdir()) == []


@requires_private_report
async def test_oversized_report_is_refused_before_a_file_is_created(rig, monkeypatch):
    monkeypatch.setattr(log_tail, "_redactor", lambda: object())
    monkeypatch.setattr(support_bundle, "build_bundle",
                        lambda _orch, **_kw: _bundle("x" * diagnostic_commands.MAX_REPORT_BYTES))
    result = await _dispatch(rig)
    assert "too large" in result.reply.lower() and not (rig.home / "support_reports").exists()


@requires_private_report
async def test_symlinked_report_directory_cannot_redirect_output(rig, monkeypatch, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    rig.home.mkdir()
    (rig.home / "support_reports").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(log_tail, "_redactor", lambda: object())
    monkeypatch.setattr(support_bundle, "build_bundle", lambda _orch, **_kw: _bundle())
    result = await _dispatch(rig)
    assert "could not" in result.reply.lower()
    assert list(outside.iterdir()) == []


@requires_private_report
async def test_cancelled_bundle_read_never_announces_or_writes_a_report(rig, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(log_tail, "_redactor", lambda: object())

    def blocked(_orch, **_kw):
        entered.set()
        assert release.wait(5)
        return _bundle()

    monkeypatch.setattr(support_bundle, "build_bundle", blocked)
    task = asyncio.create_task(_dispatch(rig))
    assert await asyncio.to_thread(entered.wait, 4)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (rig.home / "support_reports").exists()


async def test_platform_without_openat_refuses_without_reading_or_writing(rig, monkeypatch):
    monkeypatch.setattr(diagnostic_commands, "SUPPORTED", False)
    monkeypatch.setattr(support_bundle, "build_bundle", lambda *_a, **_kw: pytest.fail("read bundle"))
    result = await _dispatch(rig)
    assert "unavailable on this platform" in result.reply.lower()
    assert not rig.home.exists()
