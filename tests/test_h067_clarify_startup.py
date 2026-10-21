"""Fresh app composition must register opted-in clarification on its live RPC."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agents.core import settings_db


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    settings_db.init_db(force=True)
    return settings_db.DB_PATH


def _save_enabled(value):
    conn = settings_db.get_conn()
    try:
        conn.execute(
            "UPDATE settings SET value=? WHERE category='channels' AND key='pending_inputs_enabled'",
            (json.dumps(value),),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("enabled", [True, False])
def test_fresh_app_registration_follows_persisted_opt_in(isolated_settings, enabled):
    from agents import web

    _save_enabled(enabled)
    with TestClient(web.app):
        assert web.orch.get_setting("channels.pending_inputs_enabled", False) is enabled
        assert web.orch.tool_rpc.allows("clarify") is enabled
        if enabled:
            assert web.orch.agent_tool_runtime._server is web.orch.tool_rpc


def test_fresh_app_keeps_shipped_default_off(isolated_settings):
    from agents import web

    with TestClient(web.app):
        assert web.orch.get_setting("channels.pending_inputs_enabled", False) is False
        assert not web.orch.tool_rpc.allows("clarify")
        _save_enabled(True)
        web.orch.load_runtime_settings()
        assert web.orch.get_setting("channels.pending_inputs_enabled") is True
        assert not web.orch.tool_rpc.allows("clarify")  # registration is restart-to-apply
    with TestClient(web.app):
        assert web.orch.tool_rpc.allows("clarify")


def test_effective_setting_can_narrow_saved_opt_in(isolated_settings, monkeypatch):
    from agents import web
    from agents.core.orchestrator import Orchestrator

    _save_enabled(True)
    load = Orchestrator.load_runtime_settings

    def narrowed(self):
        load(self)
        self._runtime_settings["channels.pending_inputs_enabled"] = False

    monkeypatch.setattr(Orchestrator, "load_runtime_settings", narrowed)
    with TestClient(web.app):
        assert settings_db.get_value("channels", "pending_inputs_enabled") is True
        assert web.orch.get_setting("channels.pending_inputs_enabled") is False
        assert not web.orch.tool_rpc.allows("clarify")


def test_initial_registered_spec_is_not_replaced(isolated_settings, monkeypatch):
    from agents import web
    from agents.core.orchestrator import Orchestrator
    from agents.core.tool_rpc import ToolRPCServer

    _save_enabled(True)
    get_setting = Orchestrator.get_setting
    register = ToolRPCServer.register_tool
    existing = []

    def early_effective(self, key, default=None):
        if key == "channels.pending_inputs_enabled" and not self._runtime_settings:
            return True
        return get_setting(self, key, default)

    def observed(self, name, *args, **kwargs):
        result = register(self, name, *args, **kwargs)
        if name == "clarify":
            existing.append(self._tools[name])
        return result

    monkeypatch.setattr(Orchestrator, "get_setting", early_effective)
    monkeypatch.setattr(ToolRPCServer, "register_tool", observed)
    with TestClient(web.app):
        assert web.orch.tool_rpc.allows("clarify")
        assert len(existing) == 1
        assert web.orch.tool_rpc._tools["clarify"] is existing[0]


def test_registered_handler_checks_live_disable(isolated_settings):
    from agents import web

    _save_enabled(True)
    with TestClient(web.app):
        service = web.orch._pending_input_service()
        assert service is not None
        web.orch._runtime_settings["channels.pending_inputs_enabled"] = False
        assert web.orch._pending_input_service() is None
        assert web.orch.tool_rpc.allows("clarify")
        result = asyncio.run(web.orch.tool_rpc.handle({
            "tool": "clarify", "args": {"question": "No question may be sent"},
        }))
        assert result["result"] == {"ok": False, "reason": "clarify_context_unavailable"}
