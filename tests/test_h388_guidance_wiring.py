"""H388 guidance is selected by live product settings and turn identity."""

import pytest

from agents.core import settings_db
from agents.core.commands import Principal
from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
from tests.test_h388_guidance_runtime import Backend, run
from tests.test_web_tools_wiring import _coordinator


def wired(config):
    coordinator = _coordinator({})
    values = {"llm.tool_loop_enabled": True, "llm.operating_guidance": config}
    coordinator._orch.get_setting = lambda key, default=None: values.get(key, default)
    coordinator.build_executor()
    return coordinator._orch.agent_tool_runtime, values


@pytest.mark.asyncio
async def test_product_factory_binds_actual_channel_and_live_independent_flags():
    runtime, values = wired({"enabled": True, "flags": {}, "platform_overrides": {}})
    token = bind_turn_principal(Principal(channel="telegram", sender="synthetic-owner", admin=True))
    try:
        first = Backend()
        assert await run(runtime, first) == "done"
        system = first.requests[0]["messages"][0]["content"]
        assert "You are on Telegram" in system and "# Finishing the job" in system
        values["llm.operating_guidance"]["flags"]["task_completion"] = False
        second = Backend()
        assert await run(runtime, second) == "done"
        system = second.requests[0]["messages"][0]["content"]
        assert "# Finishing the job" not in system and "# Tool-use enforcement" in system
        assert [t.name for t in first.requests[0]["tools"]] == [t.name for t in second.requests[0]["tools"]]
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
async def test_product_guidance_can_be_disabled_without_withdrawing_tools():
    runtime, values = wired({"enabled": True})
    first = Backend()
    assert await run(runtime, first) == "done"
    assert "# Finishing the job" in first.requests[0]["messages"][0]["content"]
    values["llm.operating_guidance"] = {"enabled": False}
    second = Backend()
    assert await run(runtime, second) == "done"
    assert second.requests[0]["messages"][0]["content"] == "IDENTITY AUTHORITY\nPERSONA"
    assert [t.name for t in first.requests[0]["tools"]] == [t.name for t in second.requests[0]["tools"]]


@pytest.mark.asyncio
async def test_product_factory_does_not_guess_unbound_channel_or_execution_environment():
    runtime, _ = wired({"enabled": True})
    backend = Backend()
    assert await run(runtime, backend) == "done"
    system = backend.requests[0]["messages"][0]["content"]
    assert "# Finishing the job" in system
    assert "# Surface presentation" not in system and "# Execution environment" not in system


def test_product_guidance_setting_is_persisted_and_visible_in_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    rows = {r["key"]: r for r in settings_db.get_category("llm")}
    assert "operating_guidance" in rows
    assert rows["operating_guidance"]["kind"] == "json"
    assert rows["operating_guidance"]["value"]["enabled"] is True
    config = {"enabled": True, "flags": {"task_completion": False},
              "platform_overrides": {"telegram": "Prefer short paragraphs."}}
    updated, errors = settings_db.put_category("llm", {"operating_guidance": config})
    assert updated == 1 and errors == []
    assert settings_db.get_value("llm", "operating_guidance") == config


@pytest.mark.asyncio
async def test_execution_facts_bind_only_for_exact_terminal_offer_and_enabled_environment(monkeypatch):
    from agents.core import execution_guidance_context as module

    observed = []
    def facts(coordinator, aid):
        observed.append(aid)
        return {'profile': aid, 'environment': {'targets': 'synthetic-local (local): one argv; cwd /synthetic'}}
    monkeypatch.setattr(module, 'execution_guidance_context', facts)
    runtime, values = wired({'enabled': True})
    token = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        backend = Backend()
        await run(runtime, backend)
        assert observed == ['jarvis']
        system = backend.requests[0]['messages'][0]['content']
        assert 'synthetic-local' in system and '# Active profile' in system
        assert 'jarvis' in system
        runtime._tool_profile = lambda aid, rows: ([r for r in rows if r['name'] != 'terminal_run'], None)
        restricted = Backend()
        await run(runtime, restricted)
        assert observed == ['jarvis']
        assert 'synthetic-local' not in restricted.requests[0]['messages'][0]['content']
        runtime._tool_profile = None
        values['llm.operating_guidance']['flags'] = {'environment_hint': False}
        await run(runtime, Backend())
        assert observed == ['jarvis']
    finally:
        reset_turn_principal(token)
