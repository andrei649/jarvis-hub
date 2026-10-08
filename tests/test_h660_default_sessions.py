"""Enabled isolated code execution defaults to the resident interpreter."""

from types import SimpleNamespace

import pytest

from agents.core import code_tools
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.kernel import Decision, Verdict
from tests.test_code_tools import _run, _session_tool
from tests.test_session_kernel_routes import _bind, _orch, _owner
from tests.test_session_kernel_routes import client as client


@pytest.mark.asyncio
async def test_unset_second_switch_preserves_variables_between_real_cells(tmp_path):
    _server, tool = _session_tool(tmp_path, authorizer=lambda _action: Decision(Verdict.GRANT))
    tool._settings = lambda key, default: True if key == code_tools.SETTING else default
    try:
        first = await _run(tool, "kept = 'resident'")
        assert first.get("session") is True, "Enabled code still defaults to one-shot execution"
        second = await _run(tool, "print(kept)")
        assert second["ok"] and "resident" in second["stdout"]
        assert second["continuity"] == "continued"
    finally:
        await tool._kernels.shutdown()


@pytest.mark.parametrize("settings,composed", [
    ({"llm.execute_code": True}, True),
    ({"llm.execute_code": True, "llm.execute_code_sessions": False}, False),
    ({"llm.execute_code": False, "llm.execute_code_sessions": True}, False),
])
def test_production_composition_requires_code_opt_in_but_no_second_switch(tmp_path, monkeypatch, settings, composed):
    from agents.core import paths

    monkeypatch.setattr(paths, "data_path", lambda *_parts: tmp_path / "sessions")
    coordinator = object.__new__(AutonomyCoordinator)
    coordinator._orch = SimpleNamespace(sandbox=SimpleNamespace(active_backend=lambda: "docker", timeout=10))
    values = {"llm.execute_code_image": "python@sha256:" + "a" * 64, **settings}
    manager = coordinator._session_kernels(lambda key, default: values.get(key, default))
    assert (manager is not None) is composed
    if manager is not None:
        assert manager.status() == [], "Composition must not launch an interpreter"


def test_current_route_reports_sessions_without_second_switch(client, tmp_path, monkeypatch):
    _owner(monkeypatch)
    _bind(monkeypatch, _orch(tmp_path, settings={"llm.execute_code": True}))
    response = client.get("/sandbox/kernels")
    assert response.status_code == 200
    assert response.json()["mode"] == "session", "HUD still reports the absent switch as disabled"
