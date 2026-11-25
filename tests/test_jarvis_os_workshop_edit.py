"""The authenticated workshop edit route accepts only bounded local parameter edits."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core import workshop_edit
from agents.core.llm import data_handling
from agents.core.llm.auxiliary_text import AuxiliaryBackendFailure
from agents.core.llm.base import LMStudioBackend, OllamaBackend
from agents.core.routers import jarvis_os
from agents.core.routers._deps import user_guard


@pytest.fixture
def client(monkeypatch):
    backend = LMStudioBackend("http://localhost:1234", trust_env=False)
    router = SimpleNamespace(local_backend=backend)
    monkeypatch.setattr(jarvis_os, "get_orch", lambda: SimpleNamespace(llm_router=router))
    monkeypatch.setattr(jarvis_os.estop, "is_engaged", lambda: False)
    yield TestClient(web.app)
    asyncio.run(backend.aclose())


def request(client, view="robot", instruction="make the ring red"):
    return client.post("/api/os/workshop/edit", json={"view": view, "instruction": instruction})


def test_auth_and_request_validation(client, monkeypatch):
    async def answer(*_args, **_kwargs):
        return '{"ringColor":"#FF0000"}'

    monkeypatch.setattr(workshop_edit, "run_oneshot", answer)
    web.app.dependency_overrides.pop(web._user_guard, None)
    web.app.dependency_overrides.pop(user_guard, None)
    monkeypatch.setattr(web, "USER_TOKEN", "workshop-secret")
    assert request(client).status_code == 401
    assert client.post("/api/os/workshop/edit", headers={"x-user-token": "workshop-secret"},
                       json={"view": "robot", "instruction": "ring red"}).status_code == 200
    for body in ({"view": "other", "instruction": "red"},
                 {"view": "robot", "instruction": "   "},
                 {"view": "robot", "instruction": "x" * 1001},
                 {"view": "robot", "instruction": "red", "path": "secrets"}):
        assert client.post("/api/os/workshop/edit", headers={"x-user-token": "workshop-secret"},
                           json=body).status_code == 422


def test_refusal_timeout_and_released_lock(client, monkeypatch):
    async def refused(*_args, **_kwargs):
        raise AuxiliaryBackendFailure("local model refused")

    monkeypatch.setattr(workshop_edit, "run_oneshot", refused)
    assert request(client).status_code == 503

    async def timed_out(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(workshop_edit, "run_oneshot", timed_out)
    assert request(client).status_code == 503

    async def accepted(*_args, **_kwargs):
        return '{"housingColor":"silver"}'

    monkeypatch.setattr(workshop_edit, "run_oneshot", accepted)
    assert request(client).json() == {"ok": True, "params": {"housingColor": "silver"}}


@pytest.mark.parametrize("view,output", [
    ("robot", "{}"),
    ("robot", "I cannot do that"),
    ("robot", '{"ringColor":"red"}'),
    ("robot", '{"ringColor":"#FF0000","command":"delete"}'),
    ("house", '{"enlargeLivingRoom":0}'),
    ("house", '{"enlargeKitchen":5}'),
    ("house", '{"enlargeKitchen":NaN}'),
    ("house", '{"enlargeKitchen":true}'),
    ("house", '{"addGarageCars":false}'),
    ("house", '{"showRoof":"true"}'),
    ("house", '{"ringColor":"#FF0000"}'),
])
def test_invalid_output_is_unrepresentable(client, monkeypatch, view, output):
    async def answer(*_args, **_kwargs):
        return output

    monkeypatch.setattr(workshop_edit, "run_oneshot", answer)
    assert request(client, view).status_code == 422


def test_robot_and_house_edits_use_separate_fixed_prompts(client, monkeypatch):
    calls = []

    async def answer(_router, instruction, **kwargs):
        calls.append((instruction, kwargs))
        if "robot" in kwargs["system"]:
            return '```json\n{"housingColor":"#AABBCC","shellColor":"#102030"}\n```'
        return '{"enlargeLivingRoom":-2.5,"addGarageCars":true,"showRoof":false}'

    monkeypatch.setattr(workshop_edit, "run_oneshot", answer)
    assert request(client, "robot", "make the robot blue").json() == {
        "ok": True, "params": {"housingColor": "#AABBCC", "shellColor": "#102030"}}
    assert request(client, "house", "widen the room and add cars").json() == {
        "ok": True, "params": {"enlargeLivingRoom": -2.5, "addGarageCars": True, "showRoof": False}}
    assert [call[0] for call in calls] == ["make the robot blue", "widen the room and add cars"]
    assert all(call[1]["purpose"] == "workshop_edit" and call[1]["temperature"] == 0
               and call[1]["private_direct"] is True for call in calls)


def test_estop_and_remote_adapter_fail_closed(client, monkeypatch):
    monkeypatch.setattr(jarvis_os.estop, "is_engaged", lambda: True)
    assert request(client).status_code == 503
    monkeypatch.setattr(jarvis_os.estop, "is_engaged", lambda: False)
    jarvis_os.get_orch().llm_router.local_backend.client.base_url = "https://api.example.com"
    assert request(client).status_code == 503
    backend = object.__new__(LMStudioBackend)
    backend.base_url = "https://api.example.com"
    monkeypatch.setattr(jarvis_os, "get_orch", lambda: SimpleNamespace(
        llm_router=SimpleNamespace(local_backend=backend)))
    assert request(client).status_code == 503


def test_busy_worker_returns_429(client, monkeypatch):
    monkeypatch.setattr(jarvis_os, "_workshop_edit_lock", SimpleNamespace(locked=lambda: True))
    assert request(client).status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_type,path", [
    (LMStudioBackend, "/v1/chat/completions"),
    (OllamaBackend, "/api/generate"),
])
async def test_private_direct_check_runs_at_real_http_dispatch(monkeypatch, backend_type, path):
    seen = []
    refuse_local = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            if refuse_local:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            content = ({"choices": [{"message": {"content": '{"ringColor":"#FF0000"}'},
                                     "finish_reason": "stop"}]}
                       if backend_type is LMStudioBackend else
                       {"response": '{"ringColor":"#FF0000"}', "done": True})
            encoded = json.dumps(content).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    backend = backend_type(f"http://127.0.0.1:{server.server_port}", trust_env=False)
    model = "synthetic-local" if backend_type is LMStudioBackend else "cloud-alias"
    router = SimpleNamespace(local_backend=backend, active_model=model)
    monkeypatch.delenv("JARVIS_AUX_ONESHOT_MODEL", raising=False)
    monkeypatch.setattr(data_handling, "authorize", lambda *_args, **_kwargs: None)
    try:
        assert await workshop_edit.propose(router, "robot", "make ring red") == {"ringColor": "#FF0000"}
        assert [row[0] for row in seen] == [path]
        expected_model = model if backend_type is LMStudioBackend else "cloud-alias:latest:local"
        assert seen[0][1]["model"] == expected_model
        monkeypatch.setenv("JARVIS_AUX_ONESHOT_MODEL", "approved-local")
        assert await workshop_edit.propose(router, "robot", "make ring red") == {"ringColor": "#FF0000"}
        assert seen[-1][1]["model"] == (
            "approved-local" if backend_type is LMStudioBackend else "approved-local:latest:local")
        monkeypatch.delenv("JARVIS_AUX_ONESHOT_MODEL")
        if backend_type is OllamaBackend:
            refuse_local = True
            with pytest.raises(AuxiliaryBackendFailure):
                await workshop_edit.propose(router, "robot", "make ring red")
            assert seen[-1][1]["model"] == expected_model
            refuse_local = False

        async def change_final_url(request):
            request.url = httpx.URL(f"http://127.0.0.1:{server.server_port}/changed")

        backend.client.event_hooks["request"].insert(-1, change_final_url)
        sent_count = len(seen)
        with pytest.raises(data_handling.DataHandlingRefused):
            await workshop_edit.propose(router, "robot", "make ring red")
        assert len(seen) == sent_count
    finally:
        await backend.aclose()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
