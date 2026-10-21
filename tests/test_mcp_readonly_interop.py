"""Real MCP producer/consumer interoperability; in-process wire, synthetic memory."""

import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.mcp.client import MCPServer
from agents.core.mcp.route_tools import (
    MUTATING_ROUTE_ALLOWLIST,
    ROUTE_TOOL_ALLOWLIST,
    MutatingRouteTool,
    RouteToolSpec,
    build_route_tools,
)
from agents.core.mcp.server import JarvisMCPServer


async def _unexpected_call(*args, **kwargs):
    pytest.fail("a read-only consumer dispatched a write or agent call")


async def _consumer(hub, monkeypatch, *, name="reader", **options):
    consumer = MCPServer(name, **options)  # Keep production's default trust tier.
    sent = []

    async def send(message):
        sent.append(message)
        # Round-trip the wire representation; do not share descriptor objects.
        response = await hub.handle(json.loads(json.dumps(message)))
        return json.loads(json.dumps(response))

    monkeypatch.setattr(consumer, "_send", send)
    await consumer._initialize()
    sent.clear()
    return consumer, sent


@pytest.mark.parametrize("spec", ROUTE_TOOL_ALLOWLIST, ids=lambda spec: spec.name)
async def test_default_consumer_can_call_each_curated_read_route(spec, monkeypatch):
    async def read():
        return {"synthetic": spec.name}

    hub = JarvisMCPServer(
        _unexpected_call, {}, route_tools=build_route_tools({spec.name: read})
    )
    consumer, sent = await _consumer(hub, monkeypatch)
    result = await consumer.call_tool(f"route_{spec.name}")
    assert result.get("isError") is False, result
    assert json.loads(result["content"][0]["text"]) == {"synthetic": spec.name}
    assert [message["method"] for message in sent] == ["tools/call"]


async def test_independent_readers_recall_the_same_real_memory(monkeypatch):
    from agents.core.ingestion.embedder import Embedder
    from agents.core.memory.manager import MemoryManager
    from agents.core.routers import memory_kg

    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "1")
    memory = MemoryManager(graph_backend="memory", vector_backend="memory")
    memory._embedder = Embedder(backend="hash")
    monkeypatch.setattr(memory_kg, "get_orch", lambda: SimpleNamespace(memory=memory))
    hub = JarvisMCPServer(
        _unexpected_call, {},
        route_tools=build_route_tools({"memory_search": memory_kg.memory_search}),
    )
    readers = [
        (await _consumer(hub, monkeypatch, name=f"synthetic-reader-{i}"))[0]
        for i in range(3)
    ]
    # Seed after discovery: each reader must query the current store.
    fact = "Synthetic project Cedar review is on Thursday."
    record_id = await memory.remember(fact, metadata={"source": "synthetic"})
    assert record_id is not None
    for reader in readers:
        result = await reader.call_tool("route_memory_search", {"q": fact, "top_k": 1})
        assert result.get("isError") is False, result
        payload = json.loads(result["content"][0]["text"])
        assert payload["total"] == 1
        assert payload["results"][0]["id"] == record_id
        assert payload["results"][0]["payload"]["metadata"]["text"] == fact
    assert len(memory.vectors) == 1


@pytest.mark.parametrize("name", ["route_memory_remember", "ask_jarvis", "unknown_tool"])
async def test_default_consumer_still_refuses_writes_agents_and_unknown_tools(name, monkeypatch):
    hub = JarvisMCPServer(
        _unexpected_call, {"jarvis": "Synthetic agent"},
        mutating_route_tools=[
            MutatingRouteTool(spec=MUTATING_ROUTE_ALLOWLIST[0], invoke=_unexpected_call)
        ],
    )
    consumer, sent = await _consumer(hub, monkeypatch)
    result = await consumer.call_tool(name, {"text": "synthetic"})
    assert result["error"] == "trust_denied"
    assert sent == []


async def test_read_annotation_does_not_bypass_owner_tool_filter(monkeypatch):
    hub = JarvisMCPServer(
        _unexpected_call, {},
        route_tools=build_route_tools({"memory_search": _unexpected_call}),
    )
    consumer, sent = await _consumer(hub, monkeypatch, tools_deny=["route_memory_*"])
    result = await consumer.call_tool("route_memory_search", {"q": "synthetic"})
    assert result["error"] == "tool_filtered"
    assert sent == []


async def test_disabled_read_routes_stay_unavailable(monkeypatch):
    hub = JarvisMCPServer(_unexpected_call, {})
    consumer, sent = await _consumer(hub, monkeypatch)
    result = await consumer.call_tool("route_memory_search", {"q": "synthetic"})
    assert result["reason"] == "unlisted_tool"
    assert sent == []


@pytest.mark.parametrize("spec", [
    RouteToolSpec("custom", "/custom", "Unreviewed extension"),
    replace(ROUTE_TOOL_ALLOWLIST[1], method="POST"),
    replace(ROUTE_TOOL_ALLOWLIST[1], path="/api/memory/remember"),
    replace(ROUTE_TOOL_ALLOWLIST[1], guard="admin"),
], ids=["unknown-get", "known-name-post", "known-name-new-path", "new-authority"])
async def test_custom_specs_do_not_inherit_read_permission(spec, monkeypatch):
    hub = JarvisMCPServer(
        _unexpected_call, {},
        route_tools=build_route_tools({spec.name: _unexpected_call}, allowlist=(spec,)),
    )
    consumer, sent = await _consumer(hub, monkeypatch)
    result = await consumer.call_tool(f"route_{spec.name}")
    assert result["error"] == "trust_denied"
    assert sent == []
