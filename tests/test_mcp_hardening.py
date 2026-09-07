"""Hermes absorption 4a — two MCP client bugs with a security edge.

`MCPManager.call_tool` dispatched a bare tool name to whichever server came first in dict
order, so adding a second server could silently redirect an existing call; now a name two
servers offer is refused as ambiguous unless the server is named. And a tool result could
carry Unicode TAG characters — invisible on screen, readable by the model — which are now
stripped at both boundaries (the ToolRPC server and the MCP client).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core.mcp.client import MCPManager, MCPServer, MCPTool  # noqa: E402
from agents.core.security.quarantine import strip_invisible, strip_invisible_deep  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402

TAGS = "\U000E0069\U000E0067\U000E006E\U000E006F\U000E0072\U000E0065"  # "ignore", invisibly


class _Server(MCPServer):
    def __init__(self, name, tools):
        super().__init__(name, transport="stdio", command="true")
        self.tools = [MCPTool(t, "", {"type": "object"}, name) for t in tools]
        self.calls = []

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        return {"from": self.name, "tool": name}


def _manager():
    manager = MCPManager()
    manager.register(_Server("alpha", ["search", "only_alpha"]))
    manager.register(_Server("beta", ["search"]))
    return manager


@pytest.mark.asyncio
async def test_a_name_two_servers_offer_is_ambiguous_not_first_wins():
    manager = _manager()
    out = await manager.call_tool("search", {"q": "x"})
    assert out == {"error": "ambiguous_tool", "tool": "search", "servers": ["alpha", "beta"]}
    assert manager.servers["alpha"].calls == [] and manager.servers["beta"].calls == []
    assert manager.find_tool("search") is None


@pytest.mark.asyncio
async def test_a_qualified_name_or_an_explicit_server_pins_the_dispatch():
    manager = _manager()
    assert await manager.call_tool("beta/search", {"q": "x"}) == {"from": "beta", "tool": "search"}
    assert manager.servers["beta"].calls == [("search", {"q": "x"})]
    assert await manager.call_tool("search", {"q": "y"}, server="alpha") == {"from": "alpha", "tool": "search"}
    assert manager.servers["alpha"].calls == [("search", {"q": "y"})]
    tool = manager.find_tool("beta/search")
    assert tool.server == "beta" and tool.qualified_name == "beta/search"
    assert manager.find_tool("search", server="alpha").server == "alpha"


@pytest.mark.asyncio
async def test_unique_and_missing_names_behave_as_before():
    manager = _manager()
    assert await manager.call_tool("only_alpha") == {"from": "alpha", "tool": "only_alpha"}
    assert await manager.call_tool("nope") == {"error": "Tool 'nope' not found"}
    assert await manager.call_tool("search", server="gamma") == {
        "error": "server_not_found", "tool": "search", "server": "gamma",
    }
    assert await manager.call_tool("only_alpha", server="beta") == {
        "error": "Tool 'only_alpha' not found", "server": "beta",
    }
    # An unknown prefix is not a server: the whole string is the (unknown) tool name.
    assert (await manager.call_tool("zeta/search"))["error"] == "Tool 'zeta/search' not found"


def test_invisible_tag_characters_are_stripped_and_visible_text_is_not():
    assert strip_invisible(f"open the door{TAGS} now") == "open the door now"
    assert strip_invisible("plain ✓ text — 日本語") == "plain ✓ text — 日本語"
    assert strip_invisible("") == ""
    assert strip_invisible_deep({"a": [f"x{TAGS}", 1, {"b": (f"{TAGS}y",)}], f"k{TAGS}": None}) == {
        "a": ["x", 1, {"b": ("y",)}], "k": None,
    }
    # A cyclic or absurdly deep value is left to the strict-JSON check downstream, not
    # recursed into until the interpreter gives up.
    cyclic: dict = {"text": f"a{TAGS}"}
    cyclic["self"] = cyclic
    out = strip_invisible_deep(cyclic)
    assert out["text"] == "a" and out["self"] is cyclic
    deep: list = []
    node = deep
    for _ in range(200):
        node.append([])
        node = node[0]
    assert strip_invisible_deep(deep) is not None


@pytest.mark.asyncio
async def test_tool_rpc_results_never_carry_invisible_text():
    server = ToolRPCServer()

    async def fetch(args):
        return {"page": f"Hello{TAGS} world", "items": [f"a{TAGS}"]}

    server.register_tool("fetch", fetch, description="Fetch.")
    out = await server.handle({"tool": "fetch", "args": {}})
    assert out == {"ok": True, "tool": "fetch", "result": {"page": "Hello world", "items": ["a"]}}


@pytest.mark.asyncio
async def test_mcp_call_results_never_carry_invisible_text(monkeypatch):
    srv = MCPServer("remote", transport="stdio", command="true")
    srv.tools = [MCPTool("read", "", {"type": "object"}, "remote")]

    async def fake_send(payload):
        return {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"text": f"note{TAGS}"}]}}

    monkeypatch.setattr(srv, "_send", fake_send)
    assert await srv.call_tool("read", {}) == {"content": [{"text": "note"}]}
