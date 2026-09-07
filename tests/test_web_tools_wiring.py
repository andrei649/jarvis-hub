"""Hermes absorption 5a — the coordinator wires web_search / web_extract / search_memory
onto the live ToolRPC registry, declares osint_enrich untrusted, and the research task
kind reaches the web search plugin instead of being a permanent noop.

Every test here fails on the checkout before the wiring: the three tools were not on
the registry, osint_enrich rows were trusted, and ``_research`` tested for a ``handle``
attribute the plugin never had.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core import tool_profiles as tp  # noqa: E402
from agents.core.autonomy_coordinator import AutonomyCoordinator  # noqa: E402
from agents.core.security import taint  # noqa: E402

DEFAULTS = lambda key, default: default  # noqa: E731 — the settings a fresh install has
NEW_TOOLS = ("search_memory", "web_extract", "web_search")


def _live_registry(root: str) -> list[dict]:
    """The coordinator's real ToolRPC allowlist, file tools switched on (as the
    profile snapshot test builds it)."""
    os.environ["JARVIS_FILE_TOOLS"] = "1"
    os.environ["JARVIS_FILE_ROOTS"] = root
    orch = SimpleNamespace(agents={})
    AutonomyCoordinator(orch)._wire_agent_tool_runtime()
    return orch.tool_rpc.tools()


def _offered(tools: list[dict], surface: str, principal: str) -> list[str]:
    offered, _withheld = tp.resolve_tools(
        tools, posture=tp.ToolPosture(surface, principal), settings=DEFAULTS,
    )
    return [t["name"] for t in offered]


def _coordinator(plugins: dict) -> AutonomyCoordinator:
    """The orchestrator shape build_executor needs, with the plugins map under test."""
    from agents.core.autonomy.policy import AutonomyPolicy

    class _Queue:
        def enqueue(self, *_args, **_kwargs):
            return 1

        def get(self, _task_id):
            return None

    async def process(*_args, **_kwargs):
        return "ok"

    orch = SimpleNamespace(
        agents={},
        audit=None,
        autonomy=SimpleNamespace(policy=AutonomyPolicy(), budget=None),
        autonomy_queue=_Queue(),
        budget_ledger=None,
        capabilities=None,
        channel_inbox=None,
        channel_manager=None,
        cognition=None,
        intent_log=None,
        kill_switch=None,
        loop_detector=None,
        permission_gate=None,
        plugins=plugins,
        process=process,
        secret_broker=None,
        get_setting=lambda _key, default=None: default,
    )
    return AutonomyCoordinator(orch)


def _task(kind: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(id=1, agent="jarvis", kind=kind, payload=payload, title="research")


# ── the registry ─────────────────────────────────────────────────────────────

def test_live_registry_offers_web_and_memory_tools_to_the_owner_and_never_to_an_inbound_guest(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("JARVIS_FILE_TOOLS", "1")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    tools = _live_registry(str(tmp_path))
    names = [t["name"] for t in tools]
    for name in NEW_TOOLS:
        assert name in names, f"{name} is not on the live registry"
    by_name = {t["name"]: t for t in tools}
    # Ungated (they read; nothing actuates) and the two web tools declare their output
    # untrusted so the loop fences it; memory declares taint per hit instead.
    for name in NEW_TOOLS:
        assert by_name[name]["gated"] is False
    assert by_name["web_search"]["untrusted_output"] is True
    assert by_name["web_extract"]["untrusted_output"] is True
    assert "untrusted_output" not in by_name["search_memory"]
    assert by_name["web_search"]["capability_id"] == "tool:web_search"
    assert by_name["web_extract"]["capability_id"] == "tool:web_extract"
    assert by_name["search_memory"]["capability_id"] == "tool:search_memory"

    owner = _offered(tools, "operator", "owner")
    assert set(NEW_TOOLS) <= set(owner)
    # A stranger on an inbound channel still sees only the two harmless defaults.
    assert _offered(tools, "inbound", "guest") == ["echo", "time"]


def test_osint_enrich_declares_untrusted_output(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_FILE_TOOLS", "1")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    by_name = {t["name"]: t for t in _live_registry(str(tmp_path))}
    row = by_name["osint_enrich"]
    assert row["gated"] is True
    assert row["untrusted_output"] is True


# ── the research task ────────────────────────────────────────────────────────

class _SearchPlugin:
    """Stands in for the web search plugin: rows come back taint-marked, as the
    real plugin marks them."""

    def __init__(self, rows=None, error=None):
        self.rows = rows
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        self.calls.append((query, max_results))
        if self.error is not None:
            raise self.error
        return [taint.mark(dict(row), source="websearch") for row in self.rows]


@pytest.mark.asyncio
async def test_research_task_uses_search_and_is_no_longer_noop():
    rows = [
        {"title": f"row {i}", "url": f"https://example.invalid/{i}", "snippet": "s"}
        for i in range(7)
    ]
    plugin = _SearchPlugin(rows=rows)
    executor = _coordinator({"websearch": plugin}).build_executor()

    result = await executor.execute(_task("research", {"query": "x"}))

    assert result["status"] == "ok"
    assert result["kind"] == "research"
    assert plugin.calls == [("x", 5)]
    output = result["output"]
    assert output["query"] == "x"
    assert output["count"] == 5
    assert len(output["results"]) == 5
    assert all(taint.is_tainted(row) for row in output["results"])
    assert all(row["taint_source"] == "websearch" for row in output["results"])
    # Every research-shaped kind rides the same handler.
    for kind in ("search", "monitor", "scan", "lookup", "check"):
        assert executor.resolve(kind) is executor.resolve("research")


@pytest.mark.asyncio
async def test_research_task_is_noop_without_the_plugin_and_failed_on_error():
    executor = _coordinator({}).build_executor()
    assert await executor.execute(_task("research", {"query": "x"})) == {
        "status": "noop",
        "note": "websearch unavailable",
    }

    # A plugin without a callable search is the same honest noop, never an exception.
    executor = _coordinator({"websearch": SimpleNamespace(search="not-callable")}).build_executor()
    assert await executor.execute(_task("research", {"query": "x"})) == {
        "status": "noop",
        "note": "websearch unavailable",
    }

    # A plugin whose keyless fallback is all it has is not a backend the owner set up:
    # an unattended task must not send its title to a search engine on its own.
    unconfigured = _SearchPlugin(rows=[{"title": "t", "url": "https://x.example/", "snippet": "s"}])
    unconfigured.available = lambda: False
    executor = _coordinator({"websearch": unconfigured}).build_executor()
    assert await executor.execute(_task("research", {"query": "x"})) == {
        "status": "noop",
        "note": "websearch backend not configured",
    }
    assert unconfigured.calls == []

    # A search that raises is reported as failed with a short note — no traceback,
    # no query, no exception text.
    plugin = _SearchPlugin(error=RuntimeError("provider down: secret-token"))
    executor = _coordinator({"websearch": plugin}).build_executor()
    result = await executor.execute(_task("research", {"query": "x"}))
    assert result == {"status": "failed", "note": "websearch error"}
    assert "secret-token" not in repr(result)


# ── search_memory over the orchestrator's memory ─────────────────────────────

@pytest.mark.asyncio
async def test_search_memory_on_the_live_registry_reads_the_orchestrators_memory():
    seen: list[tuple[str, int]] = []

    async def recall(query, top_k):
        seen.append((query, top_k))
        return [{"text": "the owner takes tea at four", "score": 0.9, "source": "memory"}]

    orch = SimpleNamespace(agents={}, memory=SimpleNamespace(recall=recall))
    AutonomyCoordinator(orch)._wire_agent_tool_runtime()

    reply = await orch.tool_rpc.handle(
        {"tool": "search_memory", "args": {"query": "tea", "top_k": 3}}, actor="jarvis"
    )

    assert reply["ok"] is True
    assert reply["tool"] == "search_memory"
    assert seen == [("tea", 3)]
    result = reply["result"]
    assert result["query"] == "tea"
    assert result["count"] == 1
    assert result["tainted"] is False
    hit = result["hits"][0]
    assert hit["text"] == "the owner takes tea at four"
    assert hit["source"] == "memory"
    assert not taint.is_tainted(hit)
