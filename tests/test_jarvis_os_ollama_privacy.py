"""Exercise actual Ollama request construction with synthetic metadata and no network."""
import importlib.util
import io
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("jarvis_os_ollama_privacy", Path(__file__).resolve().parents[1]
                                             / "apps/jarvis-os/server.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
PAYLOAD = "SYNTHETIC-PRIVATE-CONTEXT"


def local_model(name="local:latest"):
    return {"name": name, "size": 1000, "details": {"format": "gguf"}}


@pytest.fixture
def transport(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "CONFIG_PATH", tmp_path / "config.json")
    engine._STATUS_CACHE["ollama"] = (0, {})
    models, requests = [], []

    class FakeOpener:
        def open(self, req, **kwargs):
            data = json.loads(req.data) if req.data else None
            requests.append((req.full_url, data))
            if req.full_url.endswith("/api/tags"):
                return io.BytesIO(json.dumps({"models": models}).encode())
            assert req.full_url.endswith("/api/chat")
            return io.BytesIO(b'{"message":{"content":"{\\"reply\\":\\"ok\\"}"}}')

    opener = FakeOpener()
    monkeypatch.setattr(engine.urllib.request, "urlopen", opener.open)
    monkeypatch.setattr(engine.urllib.request, "build_opener", lambda *a: opener)
    return models, requests


@pytest.mark.parametrize("model", [
    {"name": "gpt-oss:120b-cloud", "remote_host": "https://ollama.com", "remote_model": "gpt-oss:120b"},
    {**local_model("innocent-alias"), "remote_host": "https://ollama.com"},
    {**local_model("innocent-alias"), "remote_model": "remote"},
    local_model("model:cloud"), local_model("model-cloud:latest"),
    {"name": "unknown-provenance"}, {"name": "bad", "size": "1000", "details": []},
    {**local_model(), "remote_model": []},
])
def test_loopback_login_or_model_alias_never_grants_cloud_consent(transport, model):
    models, requests = transport
    models.append(model)
    cfg = engine.load_config()
    cfg["ollamaModel"] = model["name"]
    with pytest.raises(RuntimeError):
        engine._call_ollama(PAYLOAD, cfg)
    assert not any(data and "messages" in data for _url, data in requests)


def test_missing_preferred_model_falls_back_only_to_verified_local_model(transport):
    models, requests = transport
    models.extend([{"name": "cloud-alias", "remote_host": "https://ollama.com"}, local_model()])
    result = engine._call_ollama(PAYLOAD, engine.load_config())
    assert result["reply"] == "ok"
    chat = requests[-1][1]
    assert chat["model"] == "local:latest:local"
    assert chat["messages"][1]["content"] == PAYLOAD


def test_explicit_saved_consent_allows_cloud_model_through_ollama(transport):
    models, requests = transport
    models.append({"name": "cloud-alias", "remote_model": "remote"})
    engine.save_config({"cloudConsent": True})
    assert engine._call_ollama(PAYLOAD, engine.load_config())["reply"] == "ok"
    assert requests[-1][1]["model"] == "cloud-alias"


def test_model_provenance_refreshes_before_each_prompt(transport):
    models, requests = transport
    models.append(local_model())
    cfg = engine.load_config()
    engine._call_ollama(PAYLOAD, cfg)
    requests.clear()
    models[0]["remote_host"] = "https://ollama.com"
    with pytest.raises(RuntimeError):
        engine._call_ollama(PAYLOAD, cfg)
    assert requests and requests[-1][0].endswith("/api/tags")
    assert not any(data and "messages" in data for _url, data in requests)


def test_untagged_local_model_gets_explicit_latest_before_local_selector(transport):
    models, requests = transport
    models.append(local_model("alias"))
    engine._call_ollama(PAYLOAD, engine.load_config())
    assert requests[-1][1]["model"] == "alias:latest:local"


def test_revocation_during_metadata_probe_blocks_remote_ollama_post(transport, monkeypatch):
    models, requests = transport
    models.append(local_model())
    engine.save_config({"cloudConsent": True, "ollamaUrl": "https://synthetic.invalid"})
    cfg = engine.load_config()
    original = engine.check_ollama_status

    def probe(*args, **kwargs):
        result = original(*args, **kwargs)
        engine.save_config({"cloudConsent": False})
        return result

    monkeypatch.setattr(engine, "check_ollama_status", probe)
    with pytest.raises(RuntimeError):
        engine._call_ollama(PAYLOAD, cfg)
    assert not any(data and "messages" in data for _url, data in requests)


@pytest.mark.parametrize("redirect", [301, 302, 303, 307, 308])
def test_model_requests_bypass_proxy_and_refuse_all_redirects(monkeypatch, tmp_path, redirect):
    """Only a temporary loopback HTTP double; no provider or vault involved."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            body = json.dumps({"models": [local_model()]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            requests.append(self.path)
            body = self.rfile.read(int(self.headers["Content-Length"]))
            assert PAYLOAD.encode() in body
            self.send_response(redirect)
            self.send_header("Location", "/must-not-be-followed")
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(engine, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setenv("http_proxy", "http://203.0.113.1:1")
        monkeypatch.setenv("HTTP_PROXY", "http://203.0.113.1:1")
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setenv("NO_PROXY", "")
        cfg = engine.load_config()
        cfg["ollamaUrl"] = f"http://127.0.0.1:{server.server_port}"
        with pytest.raises(urllib.error.HTTPError) as exc:
            engine._call_ollama(PAYLOAD, cfg)
        assert exc.value.code == redirect
        assert requests == ["/api/tags", "/api/chat"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
