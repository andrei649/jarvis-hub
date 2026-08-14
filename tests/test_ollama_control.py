"""Offline tests for the fixed-command Ollama lifecycle controller."""

from __future__ import annotations

import pytest

from agents.core.autonomy.remediation import ExecResult
from agents.core.llm.ollama_control import OllamaController


class _Response:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, active=None):
        self.active = list(active or [])
        self.calls = []

    async def get(self, path):
        self.calls.append(("GET", path, None))
        return _Response({"models": [{"name": name} for name in self.active]})

    async def post(self, path, json):
        self.calls.append(("POST", path, dict(json)))
        return _Response()


class _Gate:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def check_call(self, plugin, agent):
        return self.allowed and plugin == "system-control" and agent == "jarvis"


class _BrokenListClient(_Client):
    def __init__(self, *, payload=None, raises=False):
        super().__init__()
        self.payload = payload
        self.raises = raises

    async def get(self, path):
        self.calls.append(("GET", path, None))
        if self.raises:
            raise OSError("/api/ps unavailable")
        return _Response(self.payload)


@pytest.mark.asyncio
async def test_start_uses_fixed_no_shell_detached_argv():
    calls = []
    probes = iter([False, True])

    async def exec_fn(argv, timeout, detach):
        calls.append((argv, timeout, detach))
        return ExecResult(exit_code=0)

    ctrl = OllamaController(
        permission_gate=_Gate(),
        exec_fn=exec_fn,
        probe_fn=lambda _host, _port: next(probes),
        verify_attempts=1,
        verify_delay=0,
    )

    result = await ctrl.start_server(agent="jarvis")

    assert result["status"] == "ok"
    assert calls == [(["ollama", "serve"], ctrl.timeout, True)]


@pytest.mark.asyncio
async def test_load_and_unload_use_keep_alive_without_shell():
    client = _Client(active=["qwen2.5:7b", "llama3.2:3b"])
    ctrl = OllamaController(
        permission_gate=_Gate(), client=client, probe_fn=lambda _h, _p: True
    )

    loaded = await ctrl.load_model("qwen2.5:7b", agent="jarvis")
    unloaded = await ctrl.unload_model(None, agent="jarvis")

    assert loaded["status"] == "ok"
    assert unloaded["status"] == "ok"
    posts = [call for call in client.calls if call[0] == "POST"]
    assert posts[0][2] == {
        "model": "qwen2.5:7b",
        "prompt": "",
        "keep_alive": -1,
        "stream": False,
    }
    assert [call[2]["model"] for call in posts[1:]] == [
        "qwen2.5:7b",
        "llama3.2:3b",
    ]
    assert all(call[2]["keep_alive"] == 0 for call in posts[1:])


@pytest.mark.asyncio
async def test_load_refuses_to_auto_start_when_server_is_offline():
    exec_calls = []
    client = _Client()

    async def exec_fn(argv, timeout, detach):
        exec_calls.append((argv, timeout, detach))
        return ExecResult(exit_code=0)

    ctrl = OllamaController(
        permission_gate=_Gate(),
        client=client,
        exec_fn=exec_fn,
        probe_fn=lambda _h, _p: False,
    )

    result = await ctrl.load_model("qwen2.5:7b", agent="jarvis")

    assert result["status"] == "failed"
    assert "authorize and start" in result["reason"]
    assert exec_calls == []
    assert client.calls == []


@pytest.mark.asyncio
async def test_invalid_model_and_permission_denial_never_touch_ollama():
    client = _Client()
    ctrl = OllamaController(
        permission_gate=_Gate(), client=client, probe_fn=lambda _h, _p: True
    )
    rejected = await ctrl.load_model("qwen; rm -rf /", agent="jarvis")
    assert rejected["status"] == "rejected"
    assert client.calls == []

    ctrl = OllamaController(
        permission_gate=_Gate(False), client=client, probe_fn=lambda _h, _p: True
    )
    blocked = await ctrl.unload_model("qwen2.5:7b", agent="jarvis")
    assert blocked["status"] == "blocked"
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [
        _BrokenListClient(raises=True),
        _BrokenListClient(payload={"models": "not-a-list"}),
    ],
)
async def test_unload_all_fails_closed_when_active_model_inventory_is_unknown(client):
    ctrl = OllamaController(
        permission_gate=_Gate(), client=client, probe_fn=lambda _h, _p: True
    )

    result = await ctrl.unload_model(None, agent="jarvis")

    assert result["status"] == "failed"
    assert "active model" in result["reason"].lower()
    assert not [call for call in client.calls if call[0] == "POST"]


@pytest.mark.asyncio
async def test_unload_all_prevalidates_every_inventory_entry_before_effect():
    client = _Client(active=["qwen2.5:7b", "invalid model id"])
    ctrl = OllamaController(
        permission_gate=_Gate(), client=client, probe_fn=lambda _h, _p: True
    )

    result = await ctrl.unload_model(None, agent="jarvis")

    assert result["status"] == "failed"
    assert "active model" in result["reason"].lower()
    assert not [call for call in client.calls if call[0] == "POST"]


@pytest.mark.asyncio
async def test_status_reports_unknown_instead_of_no_resident_models_on_list_failure():
    client = _BrokenListClient(raises=True)
    ctrl = OllamaController(
        permission_gate=_Gate(), client=client, probe_fn=lambda _h, _p: True
    )

    result = await ctrl.status()

    assert result["online"] is True
    assert result["status"] == "unknown"
    assert result["active_models"] is None
    assert "active model" in result["reason"].lower()
