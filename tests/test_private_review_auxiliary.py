"""Review text must reach only a proven direct local model request."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from agents.core.llm import data_handling
from agents.core.llm.auxiliary_text import prepare_local_auxiliary
from agents.core.llm.base import LMStudioBackend, OllamaBackend
from agents.core.llm.providers import get_profile
from agents.core.orchestrator import Orchestrator


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_type,path", [
    (LMStudioBackend, "/v1/chat/completions"), (OllamaBackend, "/api/generate")])
async def test_orchestrator_review_uses_direct_loopback_request(monkeypatch, backend_type, path):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            answer = ({"choices": [{"message": {"content": '{"nothing": true}'},
                                    "finish_reason": "stop"}]}
                      if backend_type is LMStudioBackend else
                      {"response": '{"nothing": true}', "done": True})
            encoded = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    backend = backend_type(f"http://127.0.0.1:{server.server_port}", trust_env=False)
    router = SimpleNamespace(local_backend=backend, active_model="cloud-alias")
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = router
    orch.get_setting = lambda key, default=None: 512 if key == "learning.review_max_tokens" else default
    monkeypatch.delenv("JARVIS_AUX_REVIEW_MODEL", raising=False)
    monkeypatch.setattr(data_handling, "authorize", lambda *_args, **_kwargs: None)
    try:
        assert await orch._review_llm("synthetic private conversation") == '{"nothing": true}'
        assert len(seen) == 1 and seen[0][0] == path
        expected_model = "cloud-alias" if backend_type is LMStudioBackend else "cloud-alias:latest:local"
        assert seen[0][1]["model"] == expected_model
        assert seen[0][1]["stream"] is False
        if backend_type is LMStudioBackend:
            assert seen[0][1]["max_tokens"] == 512
            assert seen[0][1]["messages"][-1]["content"] == "synthetic private conversation"
        else:
            assert seen[0][1]["options"]["num_predict"] == 512
            assert seen[0][1]["prompt"] == "synthetic private conversation"
    finally:
        await backend.aclose()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_review_refuses_unproven_backend_before_generation():
    sent = []

    async def generate(**kwargs):
        sent.append(kwargs)
        return "should not answer"

    backend = SimpleNamespace(profile=get_profile("lm-studio"), base_url="http://127.0.0.1:1234",
                              generate=generate)
    router = SimpleNamespace(local_backend=backend, active_model="local")
    with pytest.raises(data_handling.DataHandlingRefused, match="unsupported"):
        await prepare_local_auxiliary(router, "review")(
            system="review", prompt="synthetic private conversation", max_tokens=512, temperature=.2)
    assert sent == []


@pytest.mark.asyncio
async def test_review_refuses_nonloopback_before_generation(monkeypatch):
    backend = LMStudioBackend("https://example.invalid", trust_env=False)
    router = SimpleNamespace(local_backend=backend, active_model="local")
    monkeypatch.setattr(data_handling, "authorize", lambda *_args, **_kwargs: None)
    try:
        with pytest.raises(data_handling.DataHandlingRefused, match="not local"):
            await prepare_local_auxiliary(router, "review")(
                system="review", prompt="synthetic private conversation", max_tokens=512, temperature=.2)
    finally:
        await backend.aclose()
