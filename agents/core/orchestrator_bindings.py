"""Typed contract for orchestrator slots populated outside ``Orchestrator``.

These attributes are deliberately late-bound by lifecycle owners such as the web
lifespan, plugin manager, autonomy coordinator, ambient runtime, and scheduler.
Keeping the inventory here makes that cross-module contract reviewable while the
orchestrator supplies explicit ``None`` defaults before any writer runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

EXTERNAL_BINDING_WRITERS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "ambient_runtime": ("agents/core/ambient/runtime.py",),
        "acquisition": ("agents/core/autonomy_coordinator.py",),
        "tool_rpc": ("agents/core/autonomy_coordinator.py",),
        "agent_tool_runtime": ("agents/core/autonomy_coordinator.py",),
        "writeback": ("agents/core/autonomy_coordinator.py",),
        "social": ("agents/core/autonomy_coordinator.py",),
        "channel_replies": ("agents/core/autonomy_coordinator.py",),
        "call_broker": ("agents/core/autonomy_coordinator.py",),
        "node_mesh": ("agents/core/autonomy_coordinator.py",),
        "subagents": ("agents/core/autonomy_coordinator.py",),
        "task_executor": ("agents/core/autonomy_coordinator.py",),
        "last_memory_maintenance": ("agents/core/scheduler_service.py",),
        "channel_inbox": ("agents/web.py",),
        "oracle_bridge": ("agents/core/plugin_manager.py",),
        "argus": ("agents/core/plugin_manager.py",),
    }
)


@runtime_checkable
class ExternalOrchestratorBindings(Protocol):
    """Structural surface written by modules outside ``orchestrator.py``."""

    ambient_runtime: Any | None
    acquisition: Any | None
    tool_rpc: Any | None
    agent_tool_runtime: Any | None
    writeback: Any | None
    social: Any | None
    channel_replies: Any | None
    call_broker: Any | None
    node_mesh: Any | None
    subagents: Any | None
    task_executor: Any | None
    last_memory_maintenance: Any | None
    channel_inbox: Any | None
    oracle_bridge: Any | None
    argus: Any | None


__all__ = ["EXTERNAL_BINDING_WRITERS", "ExternalOrchestratorBindings"]
