"""Typed contract for orchestrator slots populated outside ``Orchestrator``.

These attributes are deliberately late-bound by lifecycle owners such as the web
lifespan, plugin manager, autonomy coordinator, ambient runtime, and scheduler.
Keeping the inventory here makes that cross-module contract reviewable while the
orchestrator supplies explicit ``None`` defaults before any writer runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

ExternalBindingName = Literal[
    "ambient_runtime",
    "acquisition",
    "tool_rpc",
    "agent_tool_runtime",
    "writeback",
    "social",
    "channel_replies",
    "call_broker",
    "node_mesh",
    "subagents",
    "task_executor",
    "last_memory_maintenance",
    "channel_inbox",
    "oracle_bridge",
    "argus",
    "permission_ledger",
    "work_runs",
]

ExternalBindingCallsite = tuple[str, int, int]


EXTERNAL_BINDING_WRITERS: Mapping[str, tuple[ExternalBindingCallsite, ...]] = MappingProxyType(
    {
        "ambient_runtime": (("agents/core/ambient/runtime.py", 216, 16),),
        "acquisition": (("agents/core/autonomy_coordinator.py", 705, 8),),
        "tool_rpc": (("agents/core/autonomy_coordinator.py", 715, 8),),
        "agent_tool_runtime": (("agents/core/autonomy_coordinator.py", 716, 8),),
        "writeback": (("agents/core/autonomy_coordinator.py", 849, 8),),
        "social": (("agents/core/autonomy_coordinator.py", 871, 8),),
        "channel_replies": (("agents/core/autonomy_coordinator.py", 892, 8),),
        "call_broker": (("agents/core/autonomy_coordinator.py", 912, 8),),
        "node_mesh": (("agents/core/autonomy_coordinator.py", 932, 8),),
        "subagents": (("agents/core/autonomy_coordinator.py", 1077, 8),),
        "task_executor": (("agents/core/autonomy_coordinator.py", 1094, 8),),
        "last_memory_maintenance": (("agents/core/scheduler_service.py", 323, 8),),
        "channel_inbox": (("agents/web.py", 336, 4),),
        "oracle_bridge": (("agents/core/plugin_manager.py", 146, 8),),
        "permission_ledger": (("agents/core/autonomy_coordinator.py", 976, 12),),
        "work_runs": (("agents/core/autonomy_coordinator.py", 997, 12),),
        "argus": (("agents/core/plugin_manager.py", 192, 8),),
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
    permission_ledger: Any | None
    work_runs: Any | None


def bind_external_orchestrator_attribute(
    orchestrator: ExternalOrchestratorBindings,
    name: ExternalBindingName,
    value: Any,
) -> None:
    """Write one inventoried external slot through the sole supported API."""
    if name not in EXTERNAL_BINDING_WRITERS:
        raise ValueError(f"undeclared external orchestrator binding: {name}")
    setattr(orchestrator, name, value)


__all__ = [
    "EXTERNAL_BINDING_WRITERS",
    "ExternalBindingCallsite",
    "ExternalBindingName",
    "ExternalOrchestratorBindings",
    "bind_external_orchestrator_attribute",
]
