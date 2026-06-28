"""0.31 — codeintel search is exposed as a read-only MCP route tool (under the kill-switch)."""

import pytest

from agents.core.mcp.route_tools import ALLOWLIST_BY_NAME, build_route_tools


def test_codeintel_search_is_an_allowlisted_read_tool():
    spec = ALLOWLIST_BY_NAME["codeintel_search"]
    assert spec.method == "GET"
    assert spec.path == "/api/codeintel/search"
    assert spec.guard == "user"     # pinned to route_auth.json by the 0.36 parity gate


@pytest.mark.asyncio
async def test_codeintel_search_tool_reflects_schema_and_dispatches():
    # mirror the production adapter's plain signature
    async def _handler(q: str = "", kind: str = "", limit: int = 50):
        return {"query": q, "kind": kind or None, "count": 0, "results": []}

    tools = {t.spec.name: t for t in build_route_tools({"codeintel_search": _handler})}
    tool = tools["codeintel_search"]
    props = tool.input_schema["properties"]
    assert {"q", "kind", "limit"} <= set(props)
    assert props["q"]["type"] == "string" and props["limit"]["type"] == "integer"

    out = await tool.handler(**tool.filtered_kwargs({"q": "run_heartbeat", "bogus": 1}))
    assert out["query"] == "run_heartbeat"   # known arg passed; unknown 'bogus' filtered out
