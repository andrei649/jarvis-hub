"""H145, the first review (review-H145) — its findings, pinned.

- MAJOR 1: a record was cut before it was redacted, so a secret across the cut came back
  in part. Every line is redacted whole before anything is cut.
- MAJOR 2: a long traceback lost its error line. A record over the limit keeps its header
  and its newest lines.
- m1: a rotation that is a link reached any file; only regular files are listed and the
  file is opened without following a link. m2: the reader masks what /api/admin/env
  masks (secret-named variables, assignments). m3: a redactor that cannot load shows
  nothing. m4: C1 controls and bidi overrides are removed. m5: records are filtered
  before they are redacted. m6: the note says what the writer actually did. m7: lines not
  in the log format are records of their own, whatever the window. The survivors and
  the nits (rotation names, a directory, no-store) are pinned too.
"""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path

import pytest

from agents.core import log_tail

TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def _line(level="INFO", name="jarvis.web", msg="hello", ts="2026-09-25 10:00:00"):
    return f"{ts}  {level}  {name}  {msg}\n"


@pytest.fixture
def logfile(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "jarvis.log"
    path.parent.mkdir()
    monkeypatch.setenv("JARVIS_LOG_FILE", str(path))
    from agents.core import log

    monkeypatch.setattr(log, "FILE_LOG_STATE", {"configured": False, "path": None, "error": None})
    return path


def _fragments(secret: str, size: int = 8):
    return [secret[i:i + size] for i in range(len(secret) - size + 1)]


# ── MAJOR 1: redacted whole, then cut ────────────────────────────────────────────

@pytest.mark.parametrize("pad", [7960, 7975, 7990, 7999])
def test_a_secret_across_the_cut_never_shows_in_part(logfile, pad):
    logfile.write_text(_line(msg="x" * pad + " " + TOKEN + " tail"))
    entry = log_tail.read_log()["entries"][0]
    for field in ("text", "message"):
        assert not any(f in entry[field] for f in _fragments(TOKEN)), (field, pad)


def test_a_secret_in_a_long_continuation_line_never_shows_in_part(logfile):
    logfile.write_text(_line("ERROR", msg="boom") + "y" * 7990 + TOKEN + "\n")
    text = log_tail.read_log()["entries"][0]["text"]
    assert not any(f in text for f in _fragments(TOKEN))


# ── MAJOR 2: the error line stays ────────────────────────────────────────────────

def test_a_long_traceback_keeps_its_error_line(logfile):
    frames = "".join(f'  File "/srv/nerva/agents/core/module_{n}.py", line {n}, in handler_{n}\n'
                     f"    result = call_{n}(argument, other_argument)\n" for n in range(200))
    logfile.write_text(_line("ERROR", "jarvis.agent", "boom") + "Traceback (most recent call last):\n"
                       + frames + "ValueError: the real reason\n" + _line(msg="after"))
    entry = [e for e in log_tail.read_log()["entries"] if e["message"] == "boom"][0]
    assert entry["text"].startswith("2026-09-25 10:00:00  ERROR  jarvis.agent  boom")
    assert entry["text"].endswith("ValueError: the real reason")
    assert "lines not shown]" in entry["text"] and entry["cut"] is True
    assert len(entry["text"]) <= log_tail.MAX_RECORD_CHARS + 20


# ── m1: only regular files ───────────────────────────────────────────────────────

@pytest.mark.skipif(not hasattr(os, "symlink"), reason="links")
def test_a_rotation_or_log_that_is_a_link_is_never_listed(logfile, tmp_path):
    secret = tmp_path / "outside.env"
    secret.write_text("JARVIS_ADMIN_TOKEN=hunter2-admin\n")
    logfile.write_text(_line())
    Path(f"{logfile}.1").symlink_to(secret)
    assert [f["name"] for f in log_tail.read_log()["files"]] == ["jarvis.log"]
    logfile.unlink()
    logfile.symlink_to(secret)
    out = log_tail.read_log()
    assert out["files"] == [] and out["entries"] == []


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX")
def test_a_file_swapped_for_a_link_after_listing_is_not_read(logfile, tmp_path):
    secret = tmp_path / "outside.env"
    secret.write_text("SMTP_PASS=Tr0ub4dor&3\n")
    logfile.symlink_to(secret)
    with pytest.raises(OSError):
        log_tail.read_path(logfile)


# ── m2: the reader masks what /api/admin/env masks ───────────────────────────────

def test_secret_named_environment_values_are_masked_wherever_they_appear(logfile, monkeypatch):
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "my-admin-pass-2026")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "0f3c8a9b2d4e")
    logfile.write_text(_line(msg="connecting with my-admin-pass-2026 and 0f3c8a9b2d4e"))
    message = log_tail.read_log()["entries"][0]["message"]
    assert "my-admin-pass-2026" not in message and "0f3c8a9b2d4e" not in message


@pytest.mark.parametrize("line,secret", [
    ("SMTP_PASS=Tr0ub4dor&3", "Tr0ub4dor"),
    ("OPENWEATHER_API_KEY=3b1f9c0a7e2d4b6f", "3b1f9c0a7e2d4b6f"),
    ("url https://x/api?token=abcd1234efgh5678", "abcd1234efgh5678"),
    ('password: "s3cret-value"', "s3cret-value"),
])
def test_assignments_to_credential_names_are_masked(logfile, line, secret):
    logfile.write_text(_line(msg=line))
    assert secret not in log_tail.read_log()["entries"][0]["text"]


def test_ordinary_numbers_are_left_alone(logfile):
    logfile.write_text(_line(msg="max_tokens=2048 tokens=512 keyboard ok"))
    assert log_tail.read_log()["entries"][0]["message"] == "max_tokens=2048 tokens=512 keyboard ok"


# ── m3: fail closed ──────────────────────────────────────────────────────────────

def test_a_redactor_that_cannot_load_shows_nothing(logfile, monkeypatch):
    from agents.core.security import log_redaction

    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("no scanner")

    monkeypatch.setattr(log_redaction, "SecretRedactionFilter", Broken)
    logfile.write_text(_line(msg=f"token={TOKEN}"))
    out = log_tail.read_log()
    assert out["entries"] == [] and "redactor could not be loaded" in out["note"]
    from agents.cli import nerva

    err = io.StringIO()
    ctx = nerva.Context(environ={"JARVIS_LOG_FILE": str(logfile)}, out=io.StringIO(), err=err)
    assert nerva.main(["logs"], context=ctx) == nerva.EXIT_FAILED and "redactor" in err.getvalue()


# ── m4: terminal controls ────────────────────────────────────────────────────────

def test_c1_controls_and_bidi_overrides_are_removed(logfile):
    logfile.write_text(_line(msg="csi \x9b31mRED\x9b0m osc \x9d0;TITLE\x9c bidi ‮evil ⁦x⁩"))
    message = log_tail.read_log()["entries"][0]["message"]
    assert not any(ch in message for ch in "\x9b\x9c\x9d‮⁦⁩")


# ── m5: filtered before redacted ─────────────────────────────────────────────────

def test_only_returned_records_are_redacted(logfile, monkeypatch):
    logfile.write_text("".join(_line(msg=f"m{n}") for n in range(1000)) + _line("ERROR", msg="the one"))
    calls = []
    real = log_tail._Redactor.__call__

    def counting(self, text):
        calls.append(text)
        return real(self, text)

    monkeypatch.setattr(log_tail._Redactor, "__call__", counting)
    out = log_tail.read_log(level="ERROR")
    assert [e["message"] for e in out["entries"]] == ["the one"]
    assert len(calls) < 20


# ── m6: what the writer did ──────────────────────────────────────────────────────

def test_a_file_the_hub_could_not_open_is_said(logfile, monkeypatch):
    from agents.core import log

    monkeypatch.setattr(log, "FILE_LOG_STATE", {"configured": True, "path": None,
                                                "error": f"{logfile}: Not a directory"})
    out = log_tail.read_log()
    assert out["enabled"] is False and "could not open its log file" in out["note"]


def test_the_file_the_writer_opened_is_the_one_read(tmp_path, monkeypatch):
    from agents.core import log

    real = tmp_path / "elsewhere" / "hub.log"
    real.parent.mkdir()
    real.write_text(_line(msg="from the writer"))
    monkeypatch.delenv("JARVIS_LOG_FILE", raising=False)
    monkeypatch.setattr(log_tail, "_setting", lambda cat, key, default: False)
    monkeypatch.setattr(log, "FILE_LOG_STATE", {"configured": True, "path": str(real), "error": None})
    out = log_tail.read_log()
    assert out["enabled"] is True and [e["message"] for e in out["entries"]] == ["from the writer"]


def test_setup_logging_records_what_it_did(tmp_path, monkeypatch):
    import logging

    from agents.core import log

    monkeypatch.setattr(log, "FILE_LOG_STATE", {"configured": False, "path": None, "error": None})
    target = tmp_path / "blocked"
    target.write_text("a file, not a directory")
    monkeypatch.setenv("JARVIS_LOG_FILE", str(target / "jarvis.log"))
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    try:
        log.setup_logging(logging.INFO)
        assert log.FILE_LOG_STATE["configured"] and log.FILE_LOG_STATE["path"] is None
        assert "jarvis.log" in log.FILE_LOG_STATE["error"]
        monkeypatch.setenv("JARVIS_LOG_FILE", str(tmp_path / "ok" / "jarvis.log"))
        log.setup_logging(logging.INFO)
        assert log.FILE_LOG_STATE["path"] == str(tmp_path / "ok" / "jarvis.log")
        assert log.FILE_LOG_STATE["error"] is None
    finally:
        for h in list(root.handlers):
            if h not in handlers:
                root.removeHandler(h)
                h.close()
        for h in handlers:
            if h not in root.handlers:
                root.addHandler(h)
        root.setLevel(level)


def test_no_log_file_yet_is_said(logfile):
    out = log_tail.read_log()
    assert out["enabled"] is True and out["files"] == [] and "No log file yet" in out["note"]


# ── m7: lines not in the log format ──────────────────────────────────────────────

def test_plain_lines_are_records_even_beyond_the_window(logfile, monkeypatch):
    monkeypatch.setattr(log_tail, "SCAN_BYTES", 4096)
    logfile.write_text("".join(f"plain line {n}\n" for n in range(2000)))
    out = log_tail.read_path(logfile, lines=20)
    assert [e["text"] for e in out["entries"]] == [f"plain line {n}" for n in range(1980, 2000)]


def test_nerva_logs_prints_as_many_plain_lines_as_asked(logfile):
    from agents.cli import nerva

    logfile.write_text("".join(f"plain line {n}\n" for n in range(2000)))
    out = io.StringIO()
    ctx = nerva.Context(environ={"JARVIS_LOG_FILE": str(logfile)}, out=out, err=io.StringIO())
    assert nerva.main(["logs", "-n", "1000"], context=ctx) == nerva.EXIT_OK
    assert len(out.getvalue().splitlines()) == 1000


# ── the survivors ────────────────────────────────────────────────────────────────

def test_the_budget_is_four_mebibytes_and_holds(logfile):
    assert log_tail.SCAN_BYTES == 4 * 1024 * 1024
    line = _line(msg="z" * 200)
    logfile.write_text(line * (5 * 1024 * 1024 // len(line) + 10))
    out = log_tail.read_log(level="ERROR")
    assert out["scanned_bytes"] <= log_tail.SCAN_BYTES and out["truncated"] is True


def test_a_line_with_no_level_is_hidden_under_a_level_floor(logfile):
    logfile.write_text("stray output\n" + _line("ERROR", msg="real"))
    assert [e["message"] for e in log_tail.read_log(level="WARNING")["entries"]] == ["real"]


def test_component_names_are_redacted_too(logfile):
    logfile.write_text(_line(name=TOKEN, msg="x"))
    out = log_tail.read_log()
    assert TOKEN not in out["entries"][0]["component"] and TOKEN not in " ".join(out["components"])


def test_nerva_logs_prints_whole_records_and_says_when_the_window_ran_out(logfile, monkeypatch):
    from agents.cli import nerva

    monkeypatch.setattr(log_tail, "SCAN_BYTES", 4096)
    logfile.write_text("".join(_line(msg=f"m{n}") for n in range(500))
                       + _line("ERROR", msg="boom") + "Traceback: here\n")
    out, err = io.StringIO(), io.StringIO()
    ctx = nerva.Context(environ={"JARVIS_LOG_FILE": str(logfile)}, out=out, err=err)
    assert nerva.main(["logs", "-n", "1"], context=ctx) == nerva.EXIT_OK
    assert out.getvalue().splitlines()[-1] == "Traceback: here"
    out2, err2 = io.StringIO(), io.StringIO()
    ctx = nerva.Context(environ={"JARVIS_LOG_FILE": str(logfile)}, out=out2, err=err2)
    assert nerva.main(["logs", "-n", "400"], context=ctx) == nerva.EXIT_OK
    assert "only the last" in err2.getvalue()
    out3 = io.StringIO()
    ctx = nerva.Context(environ={"JARVIS_LOG_FILE": str(logfile)}, out=out3, err=io.StringIO())
    assert nerva.main(["logs", "-n", "0"], context=ctx) == nerva.EXIT_OK and out3.getvalue() == ""


# ── nits ─────────────────────────────────────────────────────────────────────────

def test_only_ascii_numbered_rotations_are_listed(logfile):
    logfile.write_text(_line())
    for name in ("jarvis.log.١", "jarvis.log.3\n", "jarvis.log.12345", "jarvis.log.2"):
        with contextlib.suppress(OSError):
            (logfile.parent / name).write_text(_line())
    assert [f["name"] for f in log_tail.read_log()["files"]] == ["jarvis.log", "jarvis.log.2"]


def test_nerva_logs_on_a_directory_says_so(tmp_path):
    from agents.cli import nerva

    err = io.StringIO()
    ctx = nerva.Context(environ={"JARVIS_LOG_FILE": str(tmp_path)}, out=io.StringIO(), err=err)
    assert nerva.main(["logs"], context=ctx) == nerva.EXIT_FAILED and "could not be read" in err.getvalue()


def test_a_refused_filter_is_not_cached(logfile, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h145b")
    logfile.write_text(_line())
    got = TestClient(web.app).get("/api/admin/logs", params={"level": "LOUD"},
                                  headers={"X-Admin-Token": "adm-h145b"})
    assert got.status_code == 400 and "no-store" in got.headers.get("cache-control", "")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX named pipes")
def test_a_pipe_is_never_read_and_never_blocks(tmp_path):
    fifo = tmp_path / "jarvis.log"
    os.mkfifo(fifo)
    with pytest.raises(OSError):
        log_tail.read_path(fifo)


def test_the_partial_first_line_of_the_window_is_dropped(logfile, monkeypatch):
    monkeypatch.setattr(log_tail, "SCAN_BYTES", 4096)
    logfile.write_text("".join(_line(msg=f"message number {n}") for n in range(1000)))
    out = log_tail.read_path(logfile, lines=500)
    assert out["truncated"] is True and all(e["level"] == "INFO" for e in out["entries"])
