"""Contract tests for the local Hermes Hub operator client."""

import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hermes_control.py"


def load_cli():
    spec = importlib.util.spec_from_file_location("hermes_control_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hub():
    calls = []
    response = {"status": 200, "body": {"ready": True}, "location": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._answer()

        def do_POST(self):
            self._answer()

        def _answer(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append((self.command, self.path, self.headers.get("X-Admin-Token"), raw))
            self.send_response(response["status"])
            self.send_header("Content-Type", "application/json")
            if response["location"]:
                self.send_header("Location", response["location"])
            self.end_headers()
            self.wfile.write(json.dumps(response["body"]).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", calls, response
    server.shutdown()
    server.server_close()
    thread.join()


def run_cli(base, *args, token="private-admin-token", input_text=None):
    env = {**os.environ}
    if token is None:
        env.pop("JARVIS_ADMIN_TOKEN", None)
    else:
        env["JARVIS_ADMIN_TOKEN"] = token
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base-url", base, *map(str, args)],
        input=input_text, text=True, capture_output=True, env=env, timeout=10,
    )


def test_status_sends_admin_token_only_to_local_hub(hub):
    base, calls, _ = hub
    result = run_cli(base, "status")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"ready": True}
    assert calls == [("GET", "/api/hermes/status", "private-admin-token", b"")]
    assert "private-admin-token" not in result.stdout + result.stderr


def test_default_origin_matches_normal_hub_port(monkeypatch, capsys):
    cli = load_cli()
    origins = []
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "private-admin-token")
    monkeypatch.setattr(cli, "api_call", lambda origin, *_args: origins.append(origin) or {})
    assert cli.main(["status"]) == 0
    assert origins == ["http://127.0.0.1:8080"]
    assert capsys.readouterr().err == ""


def test_rpc_reads_json_object_from_stdin_and_decision_is_one_post(hub):
    base, calls, response = hub
    response["body"] = {"result": {"disposition": "queued", "task_id": 17}}
    rpc = run_cli(base, "rpc", "tool.execute", "--params-file", "-", input_text='{"path":"/tmp/a"}')
    assert rpc.returncode == 0
    assert calls[-1][:2] == ("POST", "/api/hermes/rpc")
    assert json.loads(calls[-1][3]) == {"method": "tool.execute", "params": {"path": "/tmp/a"}}
    approved = run_cli(base, "approve", "17")
    assert approved.returncode == 0
    assert calls[-1][:2] == ("POST", "/api/hermes/approvals/17/decision")
    assert json.loads(calls[-1][3]) == {"approved": True}
    denied = run_cli(base, "deny", "17")
    assert denied.returncode == 0
    assert json.loads(calls[-1][3]) == {"approved": False}


def test_cli_rejects_missing_auth_and_non_loopback_http(hub):
    base, calls, _ = hub
    missing = run_cli(base, "approvals", token=None)
    assert missing.returncode != 0
    assert "JARVIS_ADMIN_TOKEN" in missing.stderr
    remote = run_cli("http://example.com:8765", "status")
    assert remote.returncode != 0
    assert "loopback" in remote.stderr.lower()
    assert calls == []


def test_cli_refuses_redirect_without_following_or_repeating(hub):
    base, calls, response = hub
    response.update(status=307, location="http://example.com/steal")
    result = run_cli(base, "approve", "9")
    assert result.returncode != 0
    assert "redirect" in result.stderr.lower()
    assert len(calls) == 1
    assert "private-admin-token" not in result.stderr


def test_cli_reports_server_error_as_json_without_token(hub):
    base, calls, response = hub
    response.update(status=403, body={"detail": {"error": "runtime_denied"}})
    result = run_cli(base, "stop")
    assert result.returncode != 0
    assert json.loads(result.stderr)["error"] == "runtime_denied"
    assert len(calls) == 1
    assert "private-admin-token" not in result.stderr


def test_cli_reports_queued_task_identity_without_retry(hub):
    base, calls, response = hub
    response.update(status=409, body={"detail": {
        "error": "approval_required", "task_id": 17, "disposition": "queued",
    }})
    result = run_cli(base, "rpc", "tool.execute")
    assert result.returncode != 0
    assert json.loads(result.stderr) == {
        "error": "approval_required", "status": 409,
        "task_id": 17, "disposition": "queued",
    }
    assert len(calls) == 1


def test_cli_rejects_non_object_rpc_params_before_post(hub, tmp_path):
    base, calls, _ = hub
    params = tmp_path / "params.json"
    params.write_text("[1, 2]")
    result = run_cli(base, "rpc", "tool.execute", "--params-file", params)
    assert result.returncode != 0
    assert "JSON object" in result.stderr
    assert calls == []


@pytest.mark.parametrize("bad_id", ["0", "-1"])
def test_cli_refuses_nonpositive_task_id_before_post(hub, bad_id):
    base, calls, _ = hub
    result = run_cli(base, "approve", bad_id)
    assert result.returncode != 0
    assert "positive integer" in result.stderr
    assert calls == []


@pytest.mark.parametrize("source", ["file", "stdin"])
def test_cli_rejects_oversized_rpc_params_before_post(hub, tmp_path, source):
    base, calls, _ = hub
    params = '{"content":"' + ("x" * (128 * 1024)) + '"}'
    if source == "file":
        filename = tmp_path / "large.json"
        filename.write_text(params)
        result = run_cli(base, "rpc", "tool.execute", "--params-file", filename)
    else:
        result = run_cli(base, "rpc", "tool.execute", "--params-file", "-", input_text=params)
    assert result.returncode != 0
    assert "128 KiB" in result.stderr
    assert calls == []


def test_cli_never_echoes_admin_token_from_a_hub_reply(hub):
    base, _, response = hub
    response["body"] = {"note": "returned private-admin-token from upstream"}
    result = run_cli(base, "status")
    assert result.returncode == 0
    assert "private-admin-token" not in result.stdout + result.stderr
    assert "[redacted]" in result.stdout
