"""Scheduled tool policy is a strict, bounded intersection at offer and intake."""
import json
from types import SimpleNamespace

import pytest

from agents.core import job_toolsets, settings_db
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.autonomy.jobs import JobRunner, JobStore
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_rpc import ToolRPCServer
from tests.test_agent_runtime_v2 import _ScriptedBackend


@pytest.fixture
def policy_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    settings_db.init_db(force=True)
    return settings_db.DB_PATH


def server():
    rpc = ToolRPCServer()
    calls = []

    async def handle(args):
        calls.append(args)
        return args

    for name in ("echo", "time", "clarify", "messaging", "cronjob", "web_search", "web_extract"):
        rpc.register_tool(name, handle)
    return rpc, calls


@pytest.mark.asyncio
async def test_legacy_always_removes_interactive_offer_and_rpc(policy_db):
    rpc, calls = server()
    policy = job_toolsets.resolve_job_policy({}, rpc)
    assert policy.source == "legacy"
    assert "clarify" not in policy.allowed_names
    assert "messaging" not in policy.allowed_names
    assert "cronjob" not in policy.allowed_names
    assert "echo" in policy.allowed_names
    backend = _ScriptedBackend([ToolTurn(tool_calls=(ToolCall(
        id="a", name="clarify", raw_arguments="{}", arguments={}),)), ToolTurn(content="done")])
    runtime = AgentToolRuntime(rpc, enabled=lambda: True)
    with job_toolsets.toolset_scope(policy.allowed_names):
        assert await runtime.run(agent_id="jarvis", backend=backend, model="m", prompt="hi") == "done"
        assert "clarify" not in [tool.name for tool in backend.calls[0]["tools"]]
        assert (await rpc.handle({"tool": "clarify", "args": {}}))["reason"] == "job_toolset_not_allowed"
    assert not calls


def test_job_cron_legacy_precedence_and_operator_intersection(policy_db):
    rpc, _ = server()
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value=? WHERE category='llm' AND key='platform_toolsets'",
                     (json.dumps({"cron": ["web"]}),))
        conn.execute("UPDATE settings SET value=? WHERE category='agents' AND key='disabled_toolsets'",
                     (json.dumps(["basic"]),))
        conn.commit()
    finally:
        conn.close()
    cron = job_toolsets.resolve_job_policy({}, rpc)
    assert cron.source == "cron" and cron.allowed_names == frozenset({"web_search", "web_extract"})
    explicit = job_toolsets.resolve_job_policy({"enabled_toolsets": ["basic", "web"]}, rpc)
    assert explicit.source == "job"
    assert explicit.allowed_names == frozenset({"web_search", "web_extract"})
    assert {"echo", "time"} <= explicit.removed_names
    empty = job_toolsets.resolve_job_policy({"enabled_toolsets": []}, rpc)
    assert empty.source == "job" and empty.allowed_names == frozenset()


def test_corrupt_or_missing_policy_store_refuses_instead_of_widening(policy_db):
    rpc, _ = server()
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value=? WHERE category='agents' AND key='disabled_toolsets'",
                     ('{"invalid": true}',))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(settings_db.SettingsUnreadable):
        settings_db.read_job_tool_policy()
    with pytest.raises(settings_db.SettingsUnreadable):
        job_toolsets.resolve_job_policy({}, rpc)
    policy_db.unlink()
    with pytest.raises(settings_db.SettingsUnreadable):
        job_toolsets.resolve_job_policy({}, rpc)


def test_doctor_reports_malformed_policy_with_no_jobs(policy_db, tmp_path):
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value=? WHERE category='llm' AND key='platform_toolsets'",
                     ('{"cron": ["not-a-group"]}',))
        conn.commit()
    finally:
        conn.close()
    store = JobStore(tmp_path / "jobs.db")
    scheduler = SimpleNamespace(running=True, state=1, timezone="UTC", get_jobs=lambda: [])
    runner = JobRunner(store, orch=SimpleNamespace(channels={}), scheduler=lambda: scheduler,
                       quiet=lambda: False)
    try:
        report = runner.doctor()
        assert report['jobs'] == []
        assert any(row['code'] == 'tool_policy_unreadable' for row in report['problems'])
    finally:
        store.close()


def test_unavailable_allow_group_refuses_but_absent_operator_group_is_valid(policy_db):
    rpc, _ = server()
    with pytest.raises(ValueError, match="unavailable"):
        job_toolsets.resolve_job_policy({"enabled_toolsets": ["files"]}, rpc)
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value=? WHERE category='agents' AND key='disabled_toolsets'",
                     (json.dumps(["files"]),))
        conn.commit()
    finally:
        conn.close()
    assert "echo" in job_toolsets.resolve_job_policy({}, rpc).allowed_names


def test_scheduling_flag_lifts_only_loop_exclusion_and_legacy_rows_default(policy_db):
    rpc, _ = server()
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value='true' WHERE category='autonomy' "
                     "AND key='allow_agent_scheduling'")
        conn.commit()
    finally:
        conn.close()
    enabled = job_toolsets.resolve_job_policy({'enabled_toolsets': ['cronjob']}, rpc)
    assert enabled.allowed_names == frozenset({'cronjob'})
    assert {'clarify', 'messaging'} <= job_toolsets.resolve_job_policy({}, rpc).removed_names
    conn = settings_db.get_conn()
    try:
        conn.execute("UPDATE settings SET value=? WHERE category='agents' AND key='disabled_toolsets'",
                     (json.dumps(['cronjob']),))
        conn.commit()
    finally:
        conn.close()
    denied = job_toolsets.resolve_job_policy({'enabled_toolsets': ['cronjob']}, rpc)
    assert denied.allowed_names == frozenset() and denied.removed_names == frozenset({'cronjob'})
    conn = settings_db.get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE (category='llm' AND key='platform_toolsets') OR "
                     "(category='agents' AND key='disabled_toolsets') OR "
                     "(category='autonomy' AND key='allow_agent_scheduling')")
        conn.commit()
    finally:
        conn.close()
    legacy = job_toolsets.resolve_job_policy({}, rpc)
    assert legacy.source == 'legacy' and 'cronjob' not in legacy.allowed_names


@pytest.mark.parametrize('key,bad', [
    ('platform_toolsets', {'cron': ['bogus']}),
    ('platform_toolsets', {'cron': ['basic', 'basic']}),
    ('platform_toolsets', {'other': []}),
    ('disabled_toolsets', ['basic', 'basic']),
    ('disabled_toolsets', ['bogus']),
])
def test_owner_settings_writer_rejects_invalid_policy(policy_db, key, bad):
    category = 'llm' if key == 'platform_toolsets' else 'agents'
    assert settings_db.validate_category(category, {key: bad})
