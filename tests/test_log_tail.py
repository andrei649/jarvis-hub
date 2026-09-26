"""H145 — read the system logs from the UI.

``GET /api/admin/logs`` tails the hub's own log file and its rotations: admin only,
read backwards from the end within a byte budget, at most 500 records, filtered by
file, minimum level, component and count, with the H495 secret redaction applied
again as it is read (rotated files and lines written before H495 never went through
the filter). When file logging is off (the default) the answer says so instead of
pretending an empty log.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from agents.core import log_tail

TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # a GitHub token shape the scanner knows


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


# ── where the log is ─────────────────────────────────────────────────────────────

def test_the_log_is_the_one_the_hub_writes(logfile):
    path, enabled = log_tail.configured_log()
    assert path == logfile and enabled is True


def test_file_logging_off_is_said_not_hidden(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_LOG_FILE", raising=False)
    monkeypatch.setattr(log_tail, "_setting", lambda cat, key, default: False)
    monkeypatch.setattr(log_tail, "_default_log", lambda: tmp_path / "logs" / "jarvis.log")
    out = log_tail.read_log()
    assert out["enabled"] is False and out["files"] == [] and out["entries"] == []
    assert "system.log_to_file" in out["note"]


def test_an_old_file_is_still_readable_when_logging_is_off(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_LOG_FILE", raising=False)
    monkeypatch.setattr(log_tail, "_setting", lambda cat, key, default: False)
    path = tmp_path / "logs" / "jarvis.log"
    path.parent.mkdir()
    path.write_text(_line(msg="from before"))
    monkeypatch.setattr(log_tail, "_default_log", lambda: path)
    out = log_tail.read_log()
    assert out["enabled"] is False and [e["message"] for e in out["entries"]] == ["from before"]
    assert "may no longer be written" in out["note"]


def test_rotations_are_listed_newest_first_and_nothing_else(logfile):
    logfile.write_text(_line())
    for n in (1, 2, 10):
        Path(f"{logfile}.{n}").write_text(_line(msg=f"rot {n}"))
    (logfile.parent / "other.log").write_text("x")
    (logfile.parent / "jarvis.log.bak").write_text("x")
    names = [f["name"] for f in log_tail.read_log()["files"]]
    assert names == ["jarvis.log", "jarvis.log.1", "jarvis.log.2", "jarvis.log.10"]


def test_a_rotation_is_read_by_name(logfile):
    logfile.write_text(_line(msg="current"))
    Path(f"{logfile}.1").write_text(_line(msg="older"))
    out = log_tail.read_log(file="jarvis.log.1")
    assert out["file"] == "jarvis.log.1" and [e["message"] for e in out["entries"]] == ["older"]


@pytest.mark.parametrize("bad", ["../secrets.env", "/etc/passwd", "other.log", "jarvis.log.x",
                                 "jarvis.log/../../x"])
def test_a_file_not_in_the_list_is_refused(logfile, bad):
    logfile.write_text(_line())
    with pytest.raises(log_tail.LogRequestError):
        log_tail.read_log(file=bad)


# ── records ──────────────────────────────────────────────────────────────────────

def test_records_come_back_in_order_with_their_fields(logfile):
    logfile.write_text(_line("INFO", "jarvis.web", "one", "2026-09-25 10:00:00")
                       + _line("ERROR", "jarvis.agent", "two", "2026-09-25 10:00:01"))
    entries = log_tail.read_log()["entries"]
    assert [(e["ts"], e["level"], e["component"], e["message"]) for e in entries] == [
        ("2026-09-25 10:00:00", "INFO", "jarvis.web", "one"),
        ("2026-09-25 10:00:01", "ERROR", "jarvis.agent", "two"),
    ]


def test_a_traceback_stays_with_its_record(logfile):
    logfile.write_text(_line("INFO", msg="before")
                       + _line("ERROR", "jarvis.agent", "boom")
                       + "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: bad\n"
                       + _line("INFO", msg="after"))
    entries = log_tail.read_log()["entries"]
    assert [e["message"] for e in entries] == ["before", "boom", "after"]
    assert entries[1]["text"].endswith("ValueError: bad") and "Traceback" in entries[1]["text"]


def test_lines_before_the_first_header_are_their_own_record(logfile):
    logfile.write_text("stray output from a child process\n" + _line(msg="real"))
    entries = log_tail.read_log()["entries"]
    assert [e["level"] for e in entries] == ["", "INFO"]


def test_the_count_is_capped_at_500(logfile):
    logfile.write_text("".join(_line(msg=f"m{n}") for n in range(700)))
    out = log_tail.read_log(lines=10_000)
    assert out["limit"] == 500 and len(out["entries"]) == 500
    assert out["entries"][-1]["message"] == "m699" and out["entries"][0]["message"] == "m200"
    assert len(log_tail.read_log(lines=3)["entries"]) == 3


@pytest.mark.parametrize("value", [0, -5])
def test_a_count_below_one_is_one(logfile, value):
    logfile.write_text(_line(msg="a") + _line(msg="b"))
    out = log_tail.read_log(lines=value)
    assert [e["message"] for e in out["entries"]] == ["b"] and out["limit"] == 1


def test_the_level_is_a_floor(logfile):
    logfile.write_text("".join(_line(level, msg=level) for level in
                               ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")))
    got = [e["level"] for e in log_tail.read_log(level="WARNING")["entries"]]
    assert got == ["WARNING", "ERROR", "CRITICAL"]
    with pytest.raises(log_tail.LogRequestError):
        log_tail.read_log(level="LOUD")


def test_the_component_is_a_logger_and_its_children(logfile):
    logfile.write_text(_line(name="jarvis.agent", msg="a") + _line(name="jarvis.agent.tools", msg="b")
                       + _line(name="jarvis.agents", msg="c") + _line(name="jarvis.web", msg="d"))
    out = log_tail.read_log(component="jarvis.agent")
    assert [e["message"] for e in out["entries"]] == ["a", "b"]
    assert set(out["components"]) >= {"jarvis.agent", "jarvis.agent.tools", "jarvis.agents", "jarvis.web"}


def test_filters_count_matching_records_only(logfile):
    logfile.write_text("".join(_line("ERROR" if n % 10 == 0 else "INFO", msg=f"m{n}") for n in range(100)))
    got = log_tail.read_log(level="ERROR", lines=3)["entries"]
    assert [e["message"] for e in got] == ["m70", "m80", "m90"]


# ── bounds ───────────────────────────────────────────────────────────────────────

def test_the_read_is_bounded_and_says_so(logfile, monkeypatch):
    monkeypatch.setattr(log_tail, "SCAN_BYTES", 4096)
    logfile.write_text("".join(_line(msg=f"m{n}") for n in range(2000)))
    reads = []
    real = os.read

    def counting(fd, n):
        data = real(fd, n)
        reads.append(len(data))
        return data

    monkeypatch.setattr(log_tail.os, "read", counting)
    out = log_tail.read_log(lines=500)
    assert sum(reads) <= 4096 and out["truncated"] is True
    assert out["entries"] and out["entries"][-1]["message"] == "m1999"
    assert out["scanned_bytes"] <= 4096


def test_a_long_record_is_cut(logfile):
    logfile.write_text(_line(msg="x" * 50_000))
    entry = log_tail.read_log()["entries"][0]
    assert len(entry["text"]) <= log_tail.MAX_RECORD_CHARS + 20 and entry["cut"] is True


def test_a_partial_last_line_is_kept(logfile):
    logfile.write_text(_line(msg="done") + "2026-09-25 10:00:09  INFO  jarvis.web  still writing")
    assert log_tail.read_log()["entries"][-1]["message"] == "still writing"


def test_bytes_that_are_not_utf8_do_not_break_the_read(logfile):
    logfile.write_bytes(_line(msg="ok").encode() + b"2026-09-25 10:00:01  INFO  x  caf\xe9\n")
    assert [e["message"] for e in log_tail.read_log()["entries"]] == ["ok", "caf�"]


def test_control_characters_are_removed(logfile):
    logfile.write_text(_line(msg="red \x1b[31mtext\x1b[0m bell\x07 nul\x00 tab\tkept"))
    assert log_tail.read_log()["entries"][0]["message"] == "red text bell nul tab\tkept"


# ── redaction at read time ───────────────────────────────────────────────────────

def test_a_secret_written_before_redaction_is_masked_when_read(logfile):
    logfile.write_text(_line(msg=f"token={TOKEN}"))
    Path(f"{logfile}.1").write_text(_line(msg=f"old token {TOKEN}"))
    for name in ("jarvis.log", "jarvis.log.1"):
        entry = log_tail.read_log(file=name)["entries"][0]
        assert TOKEN not in entry["text"] and TOKEN not in entry["message"]


def test_a_secret_in_a_traceback_line_is_masked(logfile):
    logfile.write_text(_line("ERROR", msg="boom") + f"  headers={{'Authorization': 'Bearer {TOKEN}'}}\n")
    assert TOKEN not in log_tail.read_log()["entries"][0]["text"]


def test_a_secret_split_by_the_filters_is_never_returned(logfile):
    logfile.write_text(_line("ERROR", "jarvis.x", f"{TOKEN}"))
    out = log_tail.read_log(component="jarvis.x", level="ERROR")
    assert TOKEN not in repr(out)


# ── the route ────────────────────────────────────────────────────────────────────

ADMIN = {"X-Admin-Token": "adm-h145"}


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h145")
    return TestClient(web.app)


def test_the_route_is_admin_only(logfile, client):
    logfile.write_text(_line(msg="x"))
    assert client.get("/api/admin/logs").status_code == 401
    assert client.get("/api/admin/logs", headers={"X-Admin-Token": "wrong"}).status_code == 401
    ok = client.get("/api/admin/logs", headers=ADMIN)
    assert ok.status_code == 200 and ok.json()["entries"][0]["message"] == "x"
    assert "no-store" in ok.headers.get("cache-control", "")


def test_the_route_answers_a_bad_filter_with_400(logfile, client):
    logfile.write_text(_line())
    got = client.get("/api/admin/logs", params={"file": "../../etc/passwd"}, headers=ADMIN)
    assert got.status_code == 400 and "file" in got.json()["reason"]
    got = client.get("/api/admin/logs", params={"level": "LOUD"}, headers=ADMIN)
    assert got.status_code == 400 and "level" in got.json()["reason"]
    assert client.get("/api/admin/logs", params={"lines": 9999}, headers=ADMIN).json()["limit"] == 500


def test_the_route_passes_every_filter(logfile, client):
    logfile.write_text(_line("INFO", "a", "one") + _line("ERROR", "b", "two"))
    got = client.get("/api/admin/logs", params={"level": "ERROR", "component": "b", "lines": 5},
                     headers=ADMIN).json()
    assert [e["message"] for e in got["entries"]] == ["two"] and got["limit"] == 5


# ── the CLI reads the same way ───────────────────────────────────────────────────

def test_nerva_logs_reads_the_tail_bounded_and_masked(logfile, monkeypatch):
    import io

    from agents.cli import nerva

    monkeypatch.setattr(log_tail, "SCAN_BYTES", 4096)
    logfile.write_text("".join(_line(msg=f"m{n}") for n in range(2000)) + _line(msg=f"t {TOKEN}"))
    out = io.StringIO()
    ctx = nerva.Context(environ={"JARVIS_LOG_FILE": str(logfile)}, out=out)
    assert nerva.main(["logs", "-n", "3"], context=ctx) == nerva.EXIT_OK
    text = out.getvalue().splitlines()
    assert len(text) == 3 and text[1].endswith("m1999") and TOKEN not in out.getvalue()


def test_the_level_names_are_the_logging_modules():
    assert log_tail.LEVELS == ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    assert all(logging.getLevelName(name) == value
               for name, value in zip(log_tail.LEVELS, (10, 20, 30, 40, 50), strict=True))


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX named pipes")
def test_only_regular_files_are_listed(logfile):
    logfile.write_text(_line())
    os.mkfifo(f"{logfile}.1")                 # reading a pipe would hang the request
    Path(f"{logfile}.2").mkdir()
    assert [f["name"] for f in log_tail.read_log()["files"]] == ["jarvis.log"]
    with pytest.raises(log_tail.LogRequestError):
        log_tail.read_log(file="jarvis.log.1")
