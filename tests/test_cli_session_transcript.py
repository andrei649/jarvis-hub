"""Retained transcript CLI contract, through the actual local HTTP transport."""

from __future__ import annotations

import copy
import io
import json
import os
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.cli.nerva import EXIT_AUTH, EXIT_FAILED, EXIT_OK, EXIT_USAGE, Context, main

SID = "session_67-A"
SECRET = "PRIVATE_RAW_SECRET_67"
LIMIT = 2 * 1024 * 1024


def document():
    return {"schema_version": 1, "session_id": SID,
            "scope": "retained_current_history", "redacted": True,
            "turn_count": 2, "turns": [
                {"role": "user", "content": "Salut, lume 🌍", "agent_id": None,
                 "timestamp": "2026-11-13T10:00:00Z"},
                {"role": "assistant", "content": "Hello [REDACTED]", "agent_id": "nerva",
                 "timestamp": "2026-11-13T10:00:01Z"}]}


@pytest.fixture
def hub():
    state = SimpleNamespace(payload=document(), status=200, calls=[], raw=None)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state.calls.append((self.command, self.path, dict(self.headers)))
            raw = state.raw if state.raw is not None else json.dumps(state.payload, ensure_ascii=False).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def run(hub, *args):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={"NERVA_HUB_URL": hub.url, "JARVIS_ADMIN_TOKEN": "owner-token-67",
                           "JARVIS_USER_TOKEN": "user-token-67"},
                  out=out, err=err, inp=io.StringIO())
    code = main(["sessions", "transcript", *args], context=ctx)
    return code, out.getvalue(), err.getvalue()


def test_stdout_is_one_json_document_and_owner_read_only_request(hub):
    code, out, err = run(hub, SID)
    assert code == EXIT_OK
    assert json.loads(out) == document()
    assert not err
    assert len(hub.calls) == 1
    method, path, headers = hub.calls[0]
    assert (method, path) == ("GET", f"/sessions/{SID}/transcript")
    headers = {key.lower(): value for key, value in headers.items()}
    assert headers["x-admin-token"] == "owner-token-67"
    assert headers["x-user-token"] == "user-token-67"


def test_projection_drops_untrusted_extra_fields_without_mutating_hub_document(hub):
    hub.payload["raw_history"] = SECRET
    hub.payload["turns"][0].update(tool_calls=[SECRET], checkpoint=SECRET)
    before = copy.deepcopy(hub.payload)
    code, out, err = run(hub, SID, "-o", "-")
    assert code == EXIT_OK
    assert json.loads(out) == document()
    assert SECRET not in out + err
    assert hub.payload == before


@pytest.mark.parametrize("sid", ["../private", "a/b", "a?download=true", "a%2fb", " a", "a\n", "é", "a" * 129, ""])
def test_invalid_identifier_is_rejected_before_network(hub, sid):
    code, out, _err = run(hub, sid)
    assert code == EXIT_USAGE
    assert not out
    assert hub.calls == []


@pytest.mark.parametrize("status", [401, 403, 404, 409, 413, 422, 500, 503])
def test_api_refusal_is_single_request_without_fallback_or_secret_diagnostics(hub, status, tmp_path):
    hub.status, hub.payload = status, {"error": SECRET, "detail": SECRET}
    target = tmp_path / "transcript.json"
    code, out, err = run(hub, SID, "--out", str(target))
    assert code == (EXIT_AUTH if status in (401, 403) else EXIT_FAILED)
    assert not out and err
    assert SECRET not in out + err
    assert "saved" not in (out + err).lower()
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
    assert [(m, p) for m, p, _ in hub.calls] == [("GET", f"/sessions/{SID}/transcript")]


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 1.0), ("schema_version", 2), ("session_id", "another"),
    ("scope", "complete_history"), ("redacted", False), ("redacted", 1),
    ("turn_count", True), ("turn_count", 2.0), ("turn_count", -1), ("turn_count", 3),
    ("turns", None), ("turns", {}),
])
def test_malformed_envelope_fails_closed(hub, field, value):
    hub.payload[field] = value
    code, out, err = run(hub, SID)
    assert code == EXIT_FAILED and not out and err
    assert len(hub.calls) == 1


@pytest.mark.parametrize("field", ["schema_version", "session_id", "scope", "redacted", "turn_count", "turns"])
def test_missing_envelope_field_fails_closed(hub, field):
    del hub.payload[field]
    code, out, err = run(hub, SID)
    assert code == EXIT_FAILED and not out and err


@pytest.mark.parametrize("row", [
    None, [], {"role": "system", "content": SECRET, "agent_id": None, "timestamp": "now"},
    {"role": "tool", "content": SECRET, "agent_id": None, "timestamp": "now"},
    {"role": [], "content": SECRET, "agent_id": None, "timestamp": "now"},
    {"role": "user", "content": [SECRET], "agent_id": None, "timestamp": "now"},
    {"role": "user", "content": SECRET, "agent_id": 7, "timestamp": "now"},
    {"role": "user", "content": SECRET, "agent_id": None, "timestamp": None},
    {"role": "user", "content": SECRET, "agent_id": None},
])
def test_malformed_turn_fails_without_echoing_content(hub, row):
    hub.payload["turns"][0] = row
    code, out, err = run(hub, SID)
    assert code == EXIT_FAILED and not out and err
    assert SECRET not in out + err


@pytest.mark.parametrize("count,ok", [(0, True), (100, True), (101, False)])
def test_turn_limit_is_inclusive(hub, count, ok):
    hub.payload["turns"] = [document()["turns"][0]] * count
    hub.payload["turn_count"] = count
    code, out, _err = run(hub, SID)
    assert code == (EXIT_OK if ok else EXIT_FAILED)
    assert (json.loads(out)["turn_count"] == count) if ok else not out


def test_unicode_byte_limit_is_enforced(hub):
    hub.payload["turns"][0]["content"] = "🌍" * (LIMIT // 4)
    code, out, err = run(hub, SID)
    assert code == EXIT_FAILED and not out and err


@pytest.mark.parametrize("excess", [0, 1])
def test_compact_utf8_document_byte_boundary(hub, excess):
    hub.payload["turns"][0]["content"] = ""
    overhead = len(json.dumps(hub.payload, ensure_ascii=False, separators=(",", ":")).encode())
    hub.payload["turns"][0]["content"] = "x" * (LIMIT - overhead + excess)
    code, out, _err = run(hub, SID)
    assert code == (EXIT_FAILED if excess else EXIT_OK)
    if excess:
        assert not out
    else:
        result = json.loads(out)
        assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) == LIMIT


@pytest.mark.parametrize("raw", [b"not json PRIVATE_RAW_SECRET_67", b"[]", b"null"])
def test_non_document_response_is_safely_refused(hub, raw):
    hub.raw = raw
    code, out, err = run(hub, SID)
    assert code == EXIT_FAILED and not out and err
    assert SECRET not in out + err


def test_unencodable_content_is_safely_refused(hub):
    # JSON can carry an escaped lone surrogate, while a UTF-8 artifact cannot.
    hub.raw = json.dumps({**document(), "turns": [
        {**document()["turns"][0], "content": "\ud800"}, document()["turns"][1]]}).encode()
    code, out, err = run(hub, SID)
    assert code == EXIT_FAILED and not out and err


def test_validation_failure_preserves_existing_file(hub, tmp_path):
    target = tmp_path / "out.json"
    target.write_text(SECRET)
    hub.payload["turn_count"] = True
    code, out, err = run(hub, SID, "-o", str(target))
    assert code == EXIT_FAILED and not out and err
    assert target.read_text() == SECRET
    assert list(tmp_path.iterdir()) == [target]


def test_http_failure_preserves_existing_file(hub, tmp_path):
    target = tmp_path / "out.json"
    target.write_text(SECRET)
    hub.status, hub.payload = 409, {"error": SECRET}
    code, out, err = run(hub, SID, "-o", str(target))
    assert code == EXIT_FAILED and not out and err
    assert target.read_text() == SECRET
    assert SECRET not in out + err
    assert list(tmp_path.iterdir()) == [target]


def test_file_is_private_json_and_stdout_stays_empty(hub, tmp_path):
    target = tmp_path / "private transcript.json"
    code, out, _err = run(hub, SID, "--out", str(target))
    assert code == EXIT_OK and not out
    assert json.loads(target.read_text()) == document()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("kind", ["file", "symlink", "dangling", "directory"])
def test_existing_output_is_never_clobbered(hub, tmp_path, kind):
    target, prior = tmp_path / "out.json", tmp_path / "prior.json"
    prior.write_text(SECRET)
    if kind == "file":
        target.write_text(SECRET)
    elif kind in ("symlink", "dangling"):
        target.symlink_to(prior if kind == "symlink" else tmp_path / "absent")
    else:
        target.mkdir()
    names = set(tmp_path.iterdir())
    code, out, err = run(hub, SID, "-o", str(target))
    assert code == EXIT_FAILED and not out and err
    assert "saved" not in (out + err).lower() and SECRET not in out + err
    assert prior.read_text() == SECRET
    assert set(tmp_path.iterdir()) == names
    if kind == "file":
        assert target.read_text() == SECRET
    elif kind in ("symlink", "dangling"):
        assert target.is_symlink()
    else:
        assert target.is_dir()


def test_validation_failure_creates_no_output_or_temporary_file(hub, tmp_path):
    hub.payload["redacted"] = False
    code, out, err = run(hub, SID, "-o", str(tmp_path / "out.json"))
    assert code == EXIT_FAILED and not out and err
    assert list(tmp_path.iterdir()) == []


def test_disk_sync_failure_leaves_no_partial_artifact(hub, tmp_path, monkeypatch):
    def fail(_fd):
        raise OSError(SECRET)
    monkeypatch.setattr(os, "fsync", fail)
    code, out, err = run(hub, SID, "-o", str(tmp_path / "out.json"))
    assert code == EXIT_FAILED and not out and err
    assert SECRET not in out + err and "saved" not in (out + err).lower()
    assert list(tmp_path.iterdir()) == []


def test_concurrent_destination_creation_wins_without_clobber(hub, tmp_path, monkeypatch):
    target = tmp_path / "out.json"
    link = os.link

    def concurrent_link(source, destination, *args, **kwargs):
        target.write_text(SECRET)
        return link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", concurrent_link)
    code, out, err = run(hub, SID, "-o", str(target))
    assert code == EXIT_FAILED and not out and err
    assert target.read_text() == SECRET
    assert SECRET not in out + err and "saved" not in (out + err).lower()
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("feature", ["fchmod", "link"])
@pytest.mark.parametrize("absent", [True, False])
def test_unsupported_private_publish_fails_safely_and_stdout_still_works(hub, tmp_path, monkeypatch, feature, absent):
    if absent:
        monkeypatch.delattr(os, feature)
    else:
        monkeypatch.setattr(os, feature, None)
    code, out, err = run(hub, SID, "-o", str(tmp_path / "out.json"))
    assert code == EXIT_FAILED and not out and err
    assert "saved" not in err.lower() and SECRET not in err
    assert list(tmp_path.iterdir()) == []
    code, out, err = run(hub, SID)
    assert code == EXIT_OK and json.loads(out) == document() and not err


def test_real_entrypoint_help_discovers_transcript_options():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts/nerva.py"), "sessions", "transcript", "--help"],
                            cwd=root, text=True, capture_output=True, timeout=15,
                            env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 0, result.stderr
    assert "--out" in result.stdout and "session_id" in result.stdout.lower()


def test_real_entrypoint_requires_session_id_before_client_creation():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts/nerva.py"), "sessions", "transcript"],
                            cwd=root, text=True, capture_output=True, timeout=15,
                            env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == EXIT_USAGE
    assert not result.stdout
    assert "required" in result.stderr and "session_id" in result.stderr.lower()


def test_existing_export_still_reads_training_trajectories(hub):
    hub.payload = {"trajectories": [{"conversations": [{"from": "gpt", "value": "training"}]}]}
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={"NERVA_HUB_URL": hub.url}, out=out, err=err, inp=io.StringIO())
    assert main(["sessions", "export", SID, "--sharegpt"], context=ctx) == EXIT_OK
    assert json.loads(out.getvalue()) == hub.payload["trajectories"][0]
    assert hub.calls[0][:2] == ("GET", f"/sessions/{SID}/trajectories?format=sharegpt")


@pytest.mark.parametrize('operation', ['fsync', 'link'])
def test_publish_cancellation_cleans_private_temporary_files(tmp_path, monkeypatch, operation):
    import asyncio

    from agents.cli.session_transcript import write_transcript_file

    def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(os, operation, cancel)
    with pytest.raises(asyncio.CancelledError):
        write_transcript_file(str(tmp_path / 'out.json'), b'{}')
    assert list(tmp_path.iterdir()) == []


def test_link_failure_has_no_overwrite_fallback(hub, tmp_path, monkeypatch):
    def unsupported(*args, **kwargs):
        raise OSError('unsupported hard links ' + SECRET)

    monkeypatch.setattr(os, 'link', unsupported)
    code, out, err = run(hub, SID, '-o', str(tmp_path / 'out.json'))
    assert code == EXIT_FAILED and not out and SECRET not in err
    assert list(tmp_path.iterdir()) == []


def test_nested_json_option_preserves_parent_parser_flag():
    from agents.cli.nerva import build_parser
    parser = build_parser()
    assert parser.parse_args(['sessions', '--json', 'transcript', SID]).json is True
    assert parser.parse_args(['sessions', 'transcript', SID, '--json']).json is True
