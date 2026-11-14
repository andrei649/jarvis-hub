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
    "cloud_images",
    "cloud_videos",
    "agent_tool_runtime",
    "writeback",
    "social",
    "channel_replies",
    "call_broker",
    "node_mesh",
    "room_peers",
    "subagents",
    "task_executor",
    "last_memory_maintenance",
    "channel_inbox",
    "oracle_bridge",
    "argus",
    "permission_ledger",
    "work_runs",
    "company_runtime",
    "custom_endpoint_service",
    "session_kernels",
    "code_environment",
]

ExternalBindingCallsite = tuple[str, int, int]


EXTERNAL_BINDING_WRITERS: Mapping[str, tuple[ExternalBindingCallsite, ...]] = MappingProxyType(
    {
        "ambient_runtime": (("agents/core/ambient/runtime.py", 216, 16),),
        "acquisition": (("agents/core/autonomy_coordinator.py", 1730, 8),),
        "cloud_images": (("agents/core/autonomy_coordinator.py", 2164, 8),),
        "cloud_videos": (("agents/core/creative/video_generation.py", 831, 4),),
        "tool_rpc": (("agents/core/autonomy_coordinator.py", 2000, 8),),
        "agent_tool_runtime": (("agents/core/autonomy_coordinator.py", 2001, 8),),
        "session_kernels": (("agents/core/autonomy_coordinator.py", 1820, 8),),
        "writeback": (("agents/core/autonomy_coordinator.py", 2333, 8),),
        "social": (("agents/core/autonomy_coordinator.py", 2355, 8),),
        "channel_replies": (("agents/core/autonomy_coordinator.py", 2376, 8),),
        "call_broker": (("agents/core/autonomy_coordinator.py", 2397, 8),),
        "node_mesh": (("agents/core/autonomy_coordinator.py", 2417, 8),),
        "room_peers": (("agents/core/autonomy_coordinator.py", 2451, 8),),
        "subagents": (("agents/core/autonomy_coordinator.py", 2643, 8),),
        "task_executor": (("agents/core/autonomy_coordinator.py", 2683, 8),),
        "last_memory_maintenance": (("agents/core/scheduler_service.py", 594, 8),),
        "channel_inbox": (("agents/web.py", 628, 4),),
        "oracle_bridge": (("agents/core/plugin_manager.py", 362, 8),),
        "permission_ledger": (("agents/core/autonomy_coordinator.py", 2511, 12),),
        "work_runs": (("agents/core/autonomy_coordinator.py", 2546, 12),),
        "argus": (("agents/core/plugin_manager.py", 367, 8),),
        "company_runtime": (("agents/core/scheduler_service.py", 378, 12),),
        "custom_endpoint_service": (("agents/core/llm/custom_endpoint_service.py", 551, 4),),
        "code_environment": (("agents/core/autonomy_coordinator.py", 1777, 8),),
    }
)


@runtime_checkable
class ExternalOrchestratorBindings(Protocol):
    """Structural surface written by modules outside ``orchestrator.py``."""

    ambient_runtime: Any | None
    acquisition: Any | None
    tool_rpc: Any | None
    cloud_images: Any | None
    cloud_videos: Any | None
    agent_tool_runtime: Any | None
    writeback: Any | None
    social: Any | None
    channel_replies: Any | None
    call_broker: Any | None
    node_mesh: Any | None
    room_peers: Any | None
    subagents: Any | None
    task_executor: Any | None
    last_memory_maintenance: Any | None
    channel_inbox: Any | None
    oracle_bridge: Any | None
    argus: Any | None
    permission_ledger: Any | None
    work_runs: Any | None
    company_runtime: Any | None
    custom_endpoint_service: Any | None
    session_kernels: Any | None
    code_environment: Any | None


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
