"""Production wiring for the default-advisory tool-loop stall policy."""

from types import SimpleNamespace

from agents.core import settings_db
from tests.test_web_tools_wiring import _coordinator


def test_stall_halts_are_declared_default_off():
    rows = [row for row in settings_db.DEFAULTS
            if (row["category"], row["key"]) == ("llm", "tool_loop_stall_halt_enabled")]
    assert len(rows) == 1
    assert rows[0]["value"] is False and rows[0]["kind"] == "toggle"


def test_coordinator_rereads_stall_opt_in_without_truthy_coercion(monkeypatch):
    from agents.core import agent_runtime

    captured = {}

    def runtime_factory(_server, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(agent_runtime, "AgentToolRuntime", runtime_factory)
    coordinator = _coordinator({})
    selected = {}
    coordinator._orch.get_setting = lambda key, default=None: selected.get(key, default)
    coordinator._wire_agent_tool_runtime()
    read_policy = captured["stall_halt_enabled"]
    assert read_policy() is False
    for value, expected in ((True, True), (False, False), ("true", False), (1, False)):
        selected["llm.tool_loop_stall_halt_enabled"] = value
        assert read_policy() is expected
