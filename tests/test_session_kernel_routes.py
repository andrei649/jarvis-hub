"""K3: the owner's window onto their own session kernel, and the seat nobody else has.

K2 built the resident interpreter; this is the surface over it. The interesting part
is what the two routes do *not* accept: neither takes a session id, a principal or a
kernel token, because both derive the key from the request's own K0 authority. "Another
session cannot inspect or reset this one" is therefore a property of the shape rather
than a check somebody could forget to write — and these tests hold that shape by driving
the real FastAPI app with two different callers.

The guards themselves are pinned elsewhere on purpose: `conftest` overrides the user
guard for the whole suite, so an HTTP-level auth assertion here would pass for the wrong
reason. `test_route_auth_matrix.py` reads the live dependency graph instead.

The other thing under test is honesty. `kernel: null` must mean "you have none", never
"none exist"; `reset: false` must mean "there was nothing to reset", never "the call
failed"; and a host with sessions switched off must say which switch, not fall silent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.sandbox import Sandbox  # noqa: E402
from agents.core.session_kernels import (  # noqa: E402
    WORKER_SOURCE,
    PipeKernelBackend,
    SessionKernelManager,
)
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402

ON = {"llm.execute_code": True, "llm.execute_code_sessions": True}


def _sandbox(tmp_path, *, isolated=True):
    sandbox = Sandbox(allow_subprocess=True, work_dir=str(tmp_path), timeout=10)
    sandbox._has_docker = False
    sandbox._has_wasmtime = False
    sandbox.is_isolated = lambda: isolated
    return sandbox


def _manager(tmp_path):
    return SessionKernelManager(
        PipeKernelBackend(lambda key, token, rpc_dir="": [sys.executable, "-c", WORKER_SOURCE],
                          name="local"),
        cell_timeout_seconds=20, rpc_root=str(tmp_path / "rpc"))


def _server():
    async def echo(args):
        return {"echo": args.get("value")}

    server = ToolRPCServer()
    server.register_tool("echo", echo, description="Echo.", input_schema={
        "type": "object", "properties": {"value": {"type": "string"}}})
    return server


def _orch(tmp_path, *, settings=None, kernels=..., isolated=True, session="s1"):
    values = dict(settings if settings is not None else ON)
    return SimpleNamespace(
        sandbox=_sandbox(tmp_path, isolated=isolated),
        tool_rpc=_server(),
        session_kernels=(_manager(tmp_path) if kernels is ... else kernels),
        session_id=session,
        get_setting=lambda key, default=None: values.get(key, default),
    )


@pytest.fixture
def client():
    from agents.web import app
    with TestClient(app) as c:
        yield c


def _bind(monkeypatch, orch):
    from agents import web
    monkeypatch.setattr(web, "orch", orch, raising=False)
    monkeypatch.setattr(web, "DEV_MODE", True, raising=False)


def _owner(monkeypatch):
    """Make this process's requests resolve as the owner, the way /chat would."""
    from agents import web
    from agents.core.commands import Principal
    monkeypatch.setattr(
        web, "_web_principal",
        lambda request: Principal(channel="web", sender="owner", admin=True),
        raising=False)


def _guest(monkeypatch):
    from agents import web
    from agents.core.commands import Principal
    monkeypatch.setattr(
        web, "_web_principal",
        lambda request: Principal(channel="web", sender="guest", admin=False),
        raising=False)


# ── the mode, told honestly ──────────────────────────────────────────────────

def test_the_mode_names_the_switch_to_change_not_the_symptom(client, monkeypatch, tmp_path):
    _owner(monkeypatch)
    for settings, expected in (
        ({}, "code_execution_disabled"),
        ({"llm.execute_code": True}, "sessions_disabled"),
    ):
        _bind(monkeypatch, _orch(tmp_path, settings=settings, kernels=None))
        body = client.get("/sandbox/kernels").json()
        assert body["mode"] == "one_shot"
        assert body["reason"] == expected
        assert body["kernel"] is None


def test_sessions_on_without_a_composed_manager_says_so(client, monkeypatch, tmp_path):
    # The coordinator composes None when the image is missing or not pinned by digest.
    _owner(monkeypatch)
    _bind(monkeypatch, _orch(tmp_path, kernels=None))
    body = client.get("/sandbox/kernels").json()
    assert body == {"mode": "one_shot", "reason": "kernels_not_composed", "kernel": None}


def test_a_host_without_isolation_is_one_shot_even_with_a_manager(client, monkeypatch, tmp_path):
    _owner(monkeypatch)
    _bind(monkeypatch, _orch(tmp_path, isolated=False))
    body = client.get("/sandbox/kernels").json()
    assert body["mode"] == "one_shot" and body["reason"] == "sandbox_not_isolated"


def test_an_isolated_host_with_sessions_on_reports_session_mode(client, monkeypatch, tmp_path):
    _owner(monkeypatch)
    _bind(monkeypatch, _orch(tmp_path))
    body = client.get("/sandbox/kernels").json()
    assert body["mode"] == "session" and body["reason"] == ""
    # No kernel yet, and that reads as "you have none" rather than "none exist".
    assert body["kernel"] is None


# ── the caller's own seat, and only theirs ───────────────────────────────────

@pytest.mark.asyncio
async def test_the_status_shows_this_callers_kernel_with_its_age_and_cell_count(
    client, monkeypatch, tmp_path,
):
    _owner(monkeypatch)
    orch = _orch(tmp_path)
    _bind(monkeypatch, orch)
    from agents.core import sandbox_invocation
    invocation, _ = sandbox_invocation.bind(
        tools=orch.tool_rpc.tools(), agent="jarvis",
        principal=SimpleNamespace(admin=True, channel="web"), origin="operator",
        session_id="s1")
    await orch.session_kernels.run(invocation, "kept = 1")

    body = client.get("/sandbox/kernels").json()
    assert body["mode"] == "session"
    row = body["kernel"]
    assert row is not None and row["cells_run"] == 1 and row["alive"] is True
    assert row["idle_seconds"] >= 0
    await orch.session_kernels.shutdown()


@pytest.mark.asyncio
async def test_a_guest_sees_no_kernel_of_the_owners_and_cannot_reset_it(
    client, monkeypatch, tmp_path,
):
    """The access-control story: there is no argument with which to name another seat."""
    from agents.core import sandbox_invocation

    orch = _orch(tmp_path)
    _bind(monkeypatch, orch)
    _owner(monkeypatch)
    owner_invocation, _ = sandbox_invocation.bind(
        tools=orch.tool_rpc.tools(), agent="jarvis",
        principal=SimpleNamespace(admin=True, channel="web"), origin="operator",
        session_id="s1")
    await orch.session_kernels.run(owner_invocation, "secret = 'owner state'")
    assert len(orch.session_kernels.status()) == 1

    _guest(monkeypatch)
    seen = client.get("/sandbox/kernels").json()
    assert seen["kernel"] is None            # the owner's row is not theirs to read
    reset = client.post("/sandbox/kernels/reset").json()
    assert reset["reset"] is False           # and not theirs to destroy
    assert len(orch.session_kernels.status()) == 1
    await orch.session_kernels.shutdown()


# ── reset, and the three things it must not be confused with ─────────────────

@pytest.mark.asyncio
async def test_reset_destroys_this_callers_kernel_and_reports_that_it_did(
    client, monkeypatch, tmp_path,
):
    from agents.core import sandbox_invocation

    orch = _orch(tmp_path)
    _bind(monkeypatch, orch)
    _owner(monkeypatch)
    invocation, _ = sandbox_invocation.bind(
        tools=orch.tool_rpc.tools(), agent="jarvis",
        principal=SimpleNamespace(admin=True, channel="web"), origin="operator",
        session_id="s1")
    await orch.session_kernels.run(invocation, "kept = 1")

    body = client.post("/sandbox/kernels/reset").json()
    assert body["reset"] is True and body["mode"] == "session"
    assert orch.session_kernels.status() == []
    # And the next cell is told it started over rather than quietly getting a new one.
    outcome = await orch.session_kernels.run(invocation, "print('kept' in dir())")
    assert outcome.continuity == "reset" and outcome.state_lost is True
    await orch.session_kernels.shutdown()


def test_reset_over_an_empty_seat_is_a_success_that_says_nothing_was_lost(
    client, monkeypatch, tmp_path,
):
    _owner(monkeypatch)
    _bind(monkeypatch, _orch(tmp_path))
    body = client.post("/sandbox/kernels/reset").json()
    # False here means "there was nothing to reset", not "the call failed" — the two
    # must never render the same, which is what the panel's wording turns on.
    assert body["reset"] is False and body["mode"] == "session"


def test_reset_with_sessions_off_names_the_switch_rather_than_claiming_success(
    client, monkeypatch, tmp_path,
):
    _owner(monkeypatch)
    _bind(monkeypatch, _orch(tmp_path, settings={"llm.execute_code": True}, kernels=None))
    body = client.post("/sandbox/kernels/reset").json()
    assert body == {"reset": False, "mode": "one_shot", "reason": "sessions_disabled"}


# ── what the projection may never carry ──────────────────────────────────────

@pytest.mark.asyncio
async def test_the_projection_carries_no_cell_source_no_value_and_no_reply_token(
    client, monkeypatch, tmp_path,
):
    from agents.core import sandbox_invocation

    orch = _orch(tmp_path)
    _bind(monkeypatch, orch)
    _owner(monkeypatch)
    invocation, _ = sandbox_invocation.bind(
        tools=orch.tool_rpc.tools(), agent="jarvis",
        principal=SimpleNamespace(admin=True, channel="web"), origin="operator",
        session_id="s1")
    await orch.session_kernels.run(invocation, "PASSWORD = 'hunter2'\nprint('set')")

    raw = client.get("/sandbox/kernels").text
    assert "hunter2" not in raw and "PASSWORD" not in raw
    record = next(iter(orch.session_kernels._records.values()))
    assert record.handle.token not in raw   # the framing token frames replies, not rows
    assert set(client.get("/sandbox/kernels").json()["kernel"]) == {
        "agent", "principal", "session_id", "data_scope", "token", "cells_run",
        "idle_seconds", "alive", "backend"}
    await orch.session_kernels.shutdown()


def test_both_routes_are_pinned_as_user_guarded_in_the_auth_matrix():
    """Where the guard is actually proven — and why not here.

    `conftest` installs an autouse override of the user guard, so an HTTP-level
    assertion in this module would return 200 for an unauthenticated caller and pass
    for entirely the wrong reason. The real gate is `test_route_auth_matrix.py`, which
    reads each route's resolved dependency graph from the live app and pins it in
    `tests/_snapshots/route_auth.json`. This asserts the classification the K3 routes
    were consciously given there, so removing a guard cannot pass silently by also
    editing the snapshot in the same breath without a reader noticing.
    """
    import json

    snapshot = json.loads(
        (repo_root / "tests" / "_snapshots" / "route_auth.json").read_text(encoding="utf-8"))
    assert snapshot["GET /sandbox/kernels"] == "user"
    assert snapshot["POST /sandbox/kernels/reset"] == "user"
