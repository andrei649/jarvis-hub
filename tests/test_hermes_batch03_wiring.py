"""Skill approval routing and startup preserve the strict switch boundary."""

from __future__ import annotations

import sys
from types import MappingProxyType, ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.core import settings_db
from tests.test_web_tools_wiring import _coordinator


@pytest.mark.parametrize("missing_key", ["disabled", "channel_disabled"])
def test_general_settings_startup_cannot_reseed_marked_skill_switches(tmp_path, monkeypatch, missing_key):
    from agents.core.skills import switches

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    assert switches.state() == {"disabled": [], "channel_disabled": {}}
    conn = settings_db.get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE category='skills' AND key=?", (missing_key,))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(settings_db, "_initialized", False)
    # A normal boot reads unrelated settings before the first skill catalog.
    settings_db.ensure_initialized()
    assert settings_db.get_value("llm", "tool_loop_stall_halt_enabled", True) is False
    with pytest.raises(settings_db.SettingsUnreadable):
        switches.state()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["skill_switch", "site", None])
async def test_executor_routes_skill_approval_only_to_its_bound_handler(monkeypatch, surface):
    from agents.core import permission_ledger, skills

    ordinary = AsyncMock(return_value={"status": "ok", "route": "ordinary"})
    approved = AsyncMock(return_value={"status": "ok", "route": "skill_switch"})
    ledger = SimpleNamespace(apply_grant=ordinary)
    monkeypatch.setattr(permission_ledger, "PermissionLedger", lambda **_kwargs: ledger)
    bridge = ModuleType("agents.core.skills.switch_approval")
    bridge.apply_approved = approved
    monkeypatch.setitem(sys.modules, bridge.__name__, bridge)
    monkeypatch.setattr(skills, "switch_approval", bridge, raising=False)
    coordinator = _coordinator({})
    loader, usage, intent_log = object(), object(), object()
    coordinator._orch.skills = loader
    coordinator._orch.skill_usage = usage
    coordinator._orch.intent_log = intent_log
    executor = coordinator.build_executor()
    payload = MappingProxyType({"surface": surface}) if surface is not None else None
    task = SimpleNamespace(kind="permission.grant", payload=payload)
    handler = executor.resolve(task.kind)
    assert handler is not None and handler is not executor.fallback
    result = await handler(task)
    if surface == "skill_switch":
        assert result["route"] == "skill_switch"
        approved.assert_awaited_once_with(task, ledger=ledger, loader=loader,
                                          usage=usage, intent_log=intent_log)
        ordinary.assert_not_awaited()
    else:
        assert result["route"] == "ordinary"
        ordinary.assert_awaited_once_with(task)
        approved.assert_not_awaited()
