"""URL attachment tools and egress guards are connected to their real consumers."""

from types import SimpleNamespace

import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.commands import Principal
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.settings_db import DEFAULTS
from agents.core.tool_profiles import ToolPosture, resolve_tools
from tests.test_hermes_kanban_dispatcher import create
from tests.test_hermes_kanban_network import approve, propose, rig  # noqa: F401


def test_url_setting_is_separate_default_off_and_safe_mode_forces_off(monkeypatch):
    from agents.core import safe_mode
    defaults = {f'{row["category"]}.{row["key"]}': row["value"] for row in DEFAULTS}
    assert defaults["llm.kanban_network_attachments"] is False
    monkeypatch.setenv(safe_mode.ENV_NAME, "1")
    assert safe_mode.override_settings({"llm.kanban_network_attachments": True})[
        "llm.kanban_network_attachments"
    ] is False


def test_real_profile_offers_url_only_with_explicit_opt_in(rig):
    tools = [{"name": "kanban_attach_url", "gated": False}]
    settings = rig[2]
    for enabled in (False, True):
        settings["llm.kanban_network_attachments"] = enabled
        offered, _ = resolve_tools(
            tools, posture=ToolPosture("operator", "owner"), settings=rig[1].get_setting
        )
        assert bool(offered) is enabled
        assert resolve_tools(
            tools, posture=ToolPosture("inbound", "guest"), settings=rig[1].get_setting
        )[0] == []


@pytest.mark.asyncio
async def test_coordinator_rpc_proposes_and_composed_executor_stores_exact_bytes(rig, monkeypatch):
    from agents.core import orchestrator, paths
    controller, orch, _, requests, _, adapter = rig
    coordinator = AutonomyCoordinator(orch)
    coordinator._kanban_network_adapter = adapter
    assert coordinator.kanban_network() is adapter
    monkeypatch.setattr(paths, "data_path", lambda *parts: controller.home)
    monkeypatch.setattr(orchestrator, "current_principal", lambda: Principal(channel="web", admin=True))
    orch.agents = {name: SimpleNamespace() for name in orch.agents}
    coordinator._wire_agent_tool_runtime()
    tid = create(controller)
    answer = await orch.tool_rpc.handle(
        {"tool": "kanban_attach_url", "args": {"task_id": tid, "url": "https://example.com/file.bin"}},
        actor="jarvis",
    )
    proposal = answer["result"]
    assert proposal["status"] == "approval_required"
    assert requests == []
    executor = TaskExecutor(execution_guard=orch.autonomy.execution_allowed)
    coordinator._wire_url_monitor(executor)
    coordinator._wire_cloud_image(executor)
    coordinator._wire_kanban_network(executor)
    orch.autonomy.executor = executor.execute
    assert (await approve(rig, proposal["queue_id"])).result["status"] == "ok"
    with kanban_scope(KanbanContext(controller.home, "jarvis", can_mutate=True)), kb.connect_closing() as conn:
        attachment = kb.list_attachments(conn, tid)[0]
        from pathlib import Path
        assert Path(attachment.stored_path).read_bytes() == b"\x00\xffraw bytes"


@pytest.mark.asyncio
async def test_network_mux_preserves_previous_domain_guard_and_rejects_unknown(rig):
    _, orch, _, requests, _, adapter = rig
    coordinator = AutonomyCoordinator(orch)
    coordinator._kanban_network_adapter = adapter
    executor = TaskExecutor(execution_guard=lambda task: False)
    coordinator._wire_kanban_network(executor)
    unknown = SimpleNamespace(kind="plugin.egress", payload={"plugin": "unknown"})
    assert executor.execution_guard(unknown) is False
    assert requests == []
    _, proposal = propose(rig)
    task = orch.autonomy_queue.get(proposal["queue_id"])
    assert (await executor.execute(task))["status"] == "refused"
    assert requests == []
