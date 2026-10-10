"""H049: named, allowlisted tails of the configured rotating hub log."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from agents.cli import nerva
from agents.core import log_tail


def _run(argv: list[str], primary: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    ctx = nerva.Context(environ={"JARVIS_LOG_FILE": str(primary)}, out=out, err=err)
    code = nerva.main(["logs", *argv], context=ctx)
    return code, out.getvalue(), err.getvalue()


def test_named_rotation_tails_exact_file_in_record_order_and_count(tmp_path):
    primary = tmp_path / "jarvis.log"
    primary.write_text("current\n")
    (tmp_path / "jarvis.log.1").write_text("old one\nold two\nold three\n")
    code, out, err = _run(["jarvis.log.1", "-n", "2"], primary)
    assert (code, out.splitlines(), err) == (nerva.EXIT_OK, ["old two", "old three"], "")


def test_default_prefers_primary_then_first_available_rotation(tmp_path):
    primary = tmp_path / "jarvis.log"
    primary.write_text("current\n")
    (tmp_path / "jarvis.log.1").write_text("one\n")
    (tmp_path / "jarvis.log.2").write_text("two\n")
    assert _run([], primary)[:2] == (nerva.EXIT_OK, "current\n")
    primary.unlink()
    assert _run([], primary)[:2] == (nerva.EXIT_OK, "one\n")


def test_list_exposes_only_configured_regular_files_and_safe_metadata(tmp_path):
    primary = tmp_path / "jarvis.log"
    primary.write_text("current\n")
    (tmp_path / "jarvis.log.2").write_text("old\n")
    (tmp_path / "neighbor.log").write_text("private\n")
    (tmp_path / "jarvis.log.bak").write_text("private\n")
    (tmp_path / "jarvis.log.1").symlink_to(tmp_path / "neighbor.log")
    code, out, err = _run(["list"], primary)
    assert code == nerva.EXIT_OK and err == ""
    assert [line.split()[0] for line in out.splitlines()] == ["jarvis.log", "jarvis.log.2"]
    assert "neighbor.log" not in out and "jarvis.log.bak" not in out
    assert all("bytes" in line for line in out.splitlines())


def test_list_empty_is_clear_but_default_read_keeps_missing_log_guidance(tmp_path):
    primary = tmp_path / "missing.log"
    code, out, err = _run(["list"], primary)
    assert code == nerva.EXIT_OK and "no log files" in out.lower() and err == ""
    code, out, err = _run([], primary)
    assert code == nerva.EXIT_FAILED and out == "" and "system.log_to_file" in err


def test_name_flag_selects_configured_basename_that_is_the_list_keyword(tmp_path):
    primary = tmp_path / "list"
    primary.write_text("literal list log\n")
    assert _run(["--name", "list"], primary) == (nerva.EXIT_OK, "literal list log\n", "")
    code, out, err = _run(["list"], primary)
    assert code == nerva.EXIT_OK and "bytes" in out and err == ""


def test_conflicting_name_selectors_refuse_before_read(tmp_path, monkeypatch):
    primary = tmp_path / "jarvis.log"
    primary.write_text("current\n")
    calls = []
    monkeypatch.setattr(log_tail, "read_path", lambda *args, **kwargs: calls.append(args))
    code, out, err = _run(["jarvis.log", "--name", "jarvis.log"], primary)
    assert code == nerva.EXIT_USAGE and out == "" and err and calls == []


def test_name_flag_can_select_a_leading_dash_basename(tmp_path):
    primary = tmp_path / "-hub.log"
    primary.write_text("leading dash\n")
    assert _run(["--name=-hub.log"], primary) == (nerva.EXIT_OK, "leading dash\n", "")


@pytest.mark.parametrize("name", [
    "../neighbor.log", "/etc/passwd", "neighbor.log", "jarvis.log.x",
    "jarvis.log.01", "jarvis.log.1/../neighbor.log", "jarvis.log.2",
])
def test_unlisted_names_are_rejected_before_any_read(tmp_path, monkeypatch, name):
    primary = tmp_path / "jarvis.log"
    primary.write_text("current\n")
    (tmp_path / "neighbor.log").write_text("private\n")
    (tmp_path / "jarvis.log.2").symlink_to(tmp_path / "neighbor.log")
    calls = []
    monkeypatch.setattr(log_tail, "read_path", lambda *args, **kwargs: calls.append(args))
    code, out, err = _run([name], primary)
    assert code == nerva.EXIT_FAILED and out == "" and err and calls == []
    assert "private" not in err


def test_selected_rotation_uses_redactor_and_refuses_redactor_failure(tmp_path, monkeypatch):
    primary = tmp_path / "jarvis.log"
    rotation = tmp_path / "jarvis.log.1"
    monkeypatch.setenv("H049_API_TOKEN", "h049-secret-value-123")
    rotation.write_text("token h049-secret-value-123\n")
    code, out, err = _run([rotation.name], primary)
    assert code == nerva.EXIT_OK and err == "" and "h049-secret-value-123" not in out
    assert out.strip()

    def redaction_failed(*_args, **_kwargs):
        raise log_tail.RedactionUnavailable("scanner unavailable")

    monkeypatch.setattr(log_tail, "read_path", redaction_failed)
    code, out, err = _run([rotation.name], primary)
    assert code == nerva.EXIT_FAILED and out == "" and "redactor" in err


@pytest.mark.parametrize("replacement", ["delete", "symlink"])
def test_selected_rotation_disappearing_or_becoming_symlink_fails_closed(
    tmp_path, monkeypatch, replacement,
):
    primary = tmp_path / "jarvis.log"
    rotation = tmp_path / "jarvis.log.1"
    rotation.write_text("old\n")
    neighbor = tmp_path / "neighbor.log"
    neighbor.write_text("private\n")
    original = log_tail.list_files

    def changed(path):
        listed = original(path)
        rotation.unlink()
        if replacement == "symlink":
            rotation.symlink_to(neighbor)
        return listed

    monkeypatch.setattr(log_tail, "list_files", changed)
    code, out, err = _run([rotation.name], primary)
    assert code == nerva.EXIT_FAILED and out == "" and err
    assert "private" not in err


def test_list_does_not_emit_controls_in_configured_filename(tmp_path):
    primary = tmp_path / "jarvis\n\u202ename.log"
    primary.write_text("line\n")
    code, out, err = _run(["list"], primary)
    assert code == nerva.EXIT_OK and err == ""
    assert len(out.splitlines()) == 1 and "jarvis name.log" in out
    assert "\u202e" not in out
