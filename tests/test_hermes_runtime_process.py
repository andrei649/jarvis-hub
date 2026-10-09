import asyncio
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from agents.core.hermes_runtime.process import RuntimeProcess


@pytest.mark.asyncio
async def test_stopped_process_has_no_public_secret(tmp_path):
    runtime = RuntimeProcess(tmp_path / "source", tmp_path / "home", tmp_path / "python")
    assert runtime.status() == {"ready": False, "url": None, "generation": None, "pid": None}
    assert (await runtime.stop())["ready"] is False


@pytest.mark.asyncio
async def test_rejects_external_bridge_and_empty_token_before_launch(tmp_path):
    runtime = RuntimeProcess(tmp_path / "source", tmp_path / "home", tmp_path / "python")
    with pytest.raises(ValueError, match="loopback"):
        await runtime.start(bridge_url="http://example.com", bridge_token="secret")
    with pytest.raises(ValueError, match="token"):
        await runtime.start(bridge_url="http://127.0.0.1:1234", bridge_token="")


@pytest.mark.asyncio
async def test_owned_worker_readiness_and_cleanup(tmp_path, monkeypatch):
    from agents.core.hermes_runtime import process

    source, home = tmp_path / "source", tmp_path / "home"
    source.mkdir()
    home.mkdir()
    worker = tmp_path / "worker.py"
    worker.write_text("""
import argparse, json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
parser = argparse.ArgumentParser()
for arg in ('source', 'home', 'host', 'port'):
    parser.add_argument('--' + arg)
args = parser.parse_args()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/__jarvis__/ready' or self.headers.get('X-Jarvis-Runtime-Token') != os.environ['HERMES_DASHBOARD_SESSION_TOKEN']:
            self.send_error(403)
            return
        body = json.dumps({'ready': not bool(os.environ.get('OPENAI_API_KEY')), 'generation': os.environ['JARVIS_HERMES_GENERATION'], 'source_sha': '0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7'}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
HTTPServer((args.host, int(args.port)), Handler).serve_forever()
""")
    monkeypatch.setattr(process, "WORKER_SCRIPT", worker)
    monkeypatch.setattr(process, "verify_source", lambda path: {})
    monkeypatch.setattr(process, "validate_python", lambda python, source, home: python)
    monkeypatch.setenv("OPENAI_API_KEY", "operator-secret")
    runtime = RuntimeProcess(source, home, Path(sys.executable))
    descriptor = await runtime.start(bridge_url="http://127.0.0.1:4321", bridge_token="bridge-secret")
    try:
        assert descriptor["ready"] is True
        assert descriptor["token"] not in str(runtime.status())
        assert runtime.status()["ready"] is True
        assert (await runtime.start(bridge_url="http://127.0.0.1:4321", bridge_token="bridge-secret"))["generation"] == descriptor["generation"]
        assert process.RuntimeProcess._readiness(descriptor["url"], descriptor["token"], descriptor["generation"], process.load_pin()["commit"])
        assert not process.RuntimeProcess._readiness(descriptor["url"], descriptor["token"], "old-generation", process.load_pin()["commit"])
    finally:
        await runtime.stop()
    assert runtime.status()["ready"] is False
    assert list((home / "logs").glob("worker-*.log"))


@pytest.mark.asyncio
async def test_worker_exit_during_start_cleans_generation(tmp_path, monkeypatch):
    from agents.core.hermes_runtime import process

    source, home = tmp_path / "source", tmp_path / "home"
    source.mkdir()
    home.mkdir()
    worker = tmp_path / "worker.py"
    worker.write_text("raise SystemExit(7)\n")
    monkeypatch.setattr(process, "WORKER_SCRIPT", worker)
    monkeypatch.setattr(process, "verify_source", lambda path: {})
    monkeypatch.setattr(process, "validate_python", lambda python, source, home: python)
    runtime = RuntimeProcess(source, home, Path(sys.executable))
    with pytest.raises(RuntimeError, match="exited during startup"):
        await runtime.start(bridge_url="http://127.0.0.1:4321", bridge_token="bridge-secret")
    assert runtime.status()["ready"] is False
    assert runtime._process is None


def test_readiness_refuses_redirect_with_private_token():
    received = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("X-Jarvis-Runtime-Token"))
            body = b'{"ready": true, "generation": "generation", "source_sha": "sha"}'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    target = HTTPServer(("127.0.0.1", 0), Target)

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/stolen")
            self.end_headers()

        def log_message(self, *args):
            pass

    redirect = HTTPServer(("127.0.0.1", 0), Redirect)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (target, redirect)]
    for thread in threads:
        thread.start()
    try:
        assert not RuntimeProcess._readiness(f"http://127.0.0.1:{redirect.server_port}", "secret", "generation", "sha")
        assert received == []
    finally:
        for server in (redirect, target):
            server.shutdown()
            server.server_close()
