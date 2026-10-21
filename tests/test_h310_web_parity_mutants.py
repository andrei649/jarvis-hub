"""H310 / H537 / H607 — tests added by the mutation pass over unit W.

Each test here pins a guard, bound or branch of ``web_providers`` / ``websearch`` /
``web_tools`` / ``research`` that a one-line mutant could change while the first test
file stayed green (``docs/hermes/evidence/w-mutation-2026-10-11.json`` names the mutant
each test kills). Offline: fakes, a fake ``pypdf`` module and ``httpx.MockTransport``.
"""

import asyncio
import sys
import types
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import web_tools as wt  # noqa: E402
from agents.core.plugins import web_providers as wp  # noqa: E402
from agents.core.plugins import websearch as ws  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402
from tests.test_h310_web_parity import (  # noqa: E402,F401  (fixtures are used by name)
    PUBLIC_IP,
    Reader,
    Recorder,
    _call,
    _clean_web_env,
    _fake_pypdf,
    _pdf_transport,
    _server,
    _slow_pypdf,
    _store,
    swap_builtins,
)

# ── web_providers: classification ────────────────────────────────────────────

def test_dns_failure_is_recognised_only_by_the_message_prefix():
    from agents.core.http_client import PluginEgressError

    assert wp.is_dns_failure(PluginEgressError("egress blocked: DNS resolution failed for x"))
    assert wp.is_dns_failure(PluginEgressError("egress blocked: empty DNS answer"))
    # A refusal that merely mentions the phrase is still a refusal.
    assert not wp.is_dns_failure(PluginEgressError(
        "egress blocked: host not allowed (egress blocked: DNS resolution failed)"))
    assert not wp.is_dns_failure(PluginEgressError("egress blocked: unsafe address"))


async def test_classified_treats_status_400_and_plain_exceptions_as_failures_not_blocks():
    async def bad_request():
        return types.SimpleNamespace(status_code=400)

    with pytest.raises(wp.ProviderFailure, match="http_400"):
        await wp.classified(bad_request())

    async def down():
        raise httpx.ConnectError("refused")

    with pytest.raises(wp.ProviderFailure) as info:
        await wp.classified(down())
    assert not isinstance(info.value, wp.PolicyBlock)

    async def fine():
        return types.SimpleNamespace(status_code=399)

    assert (await wp.classified(fine())).status_code == 399


# ── web_providers: block list, order, registration, providers ────────────────

def test_block_list_tolerates_a_wildcard_prefix_and_a_leading_dot(monkeypatch):
    monkeypatch.setenv(wp.BLOCKED_DOMAINS_ENV, "*.wild.example, .dotted.example")
    assert wp.blocked_domains() == ("wild.example", "dotted.example")
    assert wp.unusable_blocked_entries() == ()
    assert wp.blocked_host("https://wild.example/") is True
    assert wp.blocked_host("https://a.wild.example/") is True
    assert wp.blocked_host("https://sub.dotted.example/") is True


def test_a_keyless_provider_stays_last_in_auto_order_whatever_registers_after_it():
    late = Recorder("late-index")
    wp.register_search_provider(late)
    try:
        order = [p.name for p in wp.auto_order()]
        assert order.index("late-index") < order.index("duckduckgo")
        assert order[-1] == "duckduckgo"
    finally:
        wp.unregister_search_provider("late-index")


def test_a_provider_cannot_be_named_auto():
    with pytest.raises(ValueError, match="name"):
        wp.register_search_provider(Recorder("auto"))
    assert "auto" not in wp.search_providers()


async def test_searxng_hands_back_at_most_max_results_rows():
    async def get(url, **kw):
        return types.SimpleNamespace(status_code=200, json=lambda: {"results": [
            {"title": f"t{i}", "url": f"https://r.example/{i}", "content": "c"} for i in range(10)]})

    client = types.SimpleNamespace(plugin_name="websearch", get=get)
    rows = await wp.SearxngProvider().search(
        client, types.SimpleNamespace(searxng_url="http://searx.local"), "q", 3)
    assert [r["title"] for r in rows] == ["t0", "t1", "t2"]


def test_a_blank_key_does_not_configure_tavily():
    tavily = wp.get_search_provider("tavily")
    assert tavily.configured(types.SimpleNamespace(tavily_api_key="   ")) is False
    assert tavily.configured(types.SimpleNamespace(tavily_api_key="")) is False
    assert tavily.configured(types.SimpleNamespace(tavily_api_key=" k ")) is True


# ── websearch: rescue, cache, row validation ─────────────────────────────────

async def test_a_policy_block_from_the_rescuer_is_reported_as_one(swap_builtins):
    failing = Recorder("tavily", tier="paid", raises=wp.ProviderFailure("http_503"))
    walled = Recorder("searxng", raises=wp.PolicyBlock("egress blocked"))
    swap_builtins(tavily=failing, searxng=walled)
    plugin = ws.WebSearchPlugin(tavily_api_key="k", searxng_url="http://searx.local")
    outcome = await plugin.search_detailed("q")
    assert outcome.rows == [] and outcome.reason == "policy_blocked"
    assert outcome.provider == "searxng" and outcome.rescued_from == "tavily"
    assert outcome.rescue_reason == "provider_failed"


async def test_search_cache_entry_expires_exactly_at_the_ttl(swap_builtins):
    fakes = swap_builtins()
    now = {"t": 50.0}
    plugin = ws.WebSearchPlugin(tavily_api_key="k", clock=lambda: now["t"])
    await plugin.search_detailed("q")
    now["t"] = 50.0 + ws.SEARCH_CACHE_TTL_SECONDS - 0.5
    assert (await plugin.search_detailed("q")).cached is True
    now["t"] = 50.0 + ws.SEARCH_CACHE_TTL_SECONDS
    assert (await plugin.search_detailed("q")).cached is False
    assert len(fakes["tavily"].calls) == 2


async def test_a_provider_that_answers_with_a_non_list_has_failed(swap_builtins):
    class Sloppy(Recorder):
        async def search(self, client, plugin, query, max_results):
            return ({"title": "t", "url": "https://x.example/", "snippet": "s"},)

    swap_builtins(tavily=Sloppy("tavily", tier="paid"))
    plugin = ws.WebSearchPlugin(tavily_api_key="k", rescue=False)
    outcome = await plugin.search_detailed("q")
    assert outcome.rows == [] and outcome.reason == "provider_failed"


# ── websearch: the PDF queue, the parse clock, the page and char bounds ──────

async def test_a_read_that_waits_too_long_for_its_turn_says_parser_busy(monkeypatch):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    monkeypatch.setitem(sys.modules, "pypdf", _fake_pypdf(["text"]))
    monkeypatch.setattr(ws, "PDF_QUEUE_WAIT_SECONDS", 0.05)
    queue = ws._pdf_queue()
    for _ in range(ws.PDF_MAX_CONCURRENT):
        await queue.acquire()
    plugin = ws.WebSearchPlugin()
    try:
        got = await plugin.read_page("https://docs.example/a.pdf", _transport=_pdf_transport())
        # Not fetch_failed: a retry would queue behind the same slow documents.
        assert got.text is None and got.refusal == "parser_busy"
    finally:
        for _ in range(ws.PDF_MAX_CONCURRENT):
            queue.release()
    got = await plugin.read_page("https://docs.example/a.pdf", _transport=_pdf_transport())
    assert got.text == "text"


async def test_exactly_two_pdf_parses_run_at_once_when_five_are_waiting(monkeypatch):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    peak: list = []
    monkeypatch.setitem(sys.modules, "pypdf", _slow_pypdf(pages=2, delay=0.1, peak=peak))
    plugin = ws.WebSearchPlugin()
    got = await asyncio.gather(*[
        plugin.read_page(f"https://docs.example/{i}.pdf", _transport=_pdf_transport())
        for i in range(5)])
    assert [g.refusal for g in got] == [""] * 5
    # The accepted bound is two, written as a literal: the module constant is not the oracle.
    assert max(peak) == 2


async def test_the_parse_clock_starts_after_the_wait_for_a_turn(monkeypatch):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    monkeypatch.setattr(ws, "PDF_PARSE_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setitem(sys.modules, "pypdf", _slow_pypdf(pages=4, delay=0.15))
    queue = ws._pdf_queue()
    for _ in range(ws.PDF_MAX_CONCURRENT):
        await queue.acquire()
    loop = asyncio.get_running_loop()

    def release():
        for _ in range(ws.PDF_MAX_CONCURRENT):
            queue.release()

    loop.call_later(0.7, release)       # the read waits 0.7 s, parses for ~0.6 s of a 1.0 s budget
    plugin = ws.WebSearchPlugin()
    got = await plugin.read_page("https://docs.example/a.pdf", _transport=_pdf_transport())
    assert got.refusal == "" and got.text == "\n\n".join(["page"] * 4)


async def test_a_timed_out_parse_really_stops_its_worker(monkeypatch):
    import time as _time

    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    monkeypatch.setattr(ws, "PDF_PARSE_TIMEOUT_SECONDS", 0.3)
    extracted = []
    module = types.ModuleType("pypdf")

    class _Page:
        def extract_text(self):
            extracted.append(1)
            _time.sleep(0.1)
            return "p"

    class PdfReader:
        def __init__(self, stream):
            self.is_encrypted = False
            self.pages = [_Page() for _ in range(100)]

    module.PdfReader = PdfReader
    monkeypatch.setitem(sys.modules, "pypdf", module)
    plugin = ws.WebSearchPlugin()
    got = await plugin.read_page("https://docs.example/slow.pdf", _transport=_pdf_transport())
    assert got.refusal == "fetch_failed"
    # Every slot must come back: one slot being free proves nothing (the worker holds one).
    # A worker that ran on to the last page would hold its slot for ~10 s.
    held = 0
    for _ in range(60):
        while held < ws.PDF_MAX_CONCURRENT and ws._PDF_SLOTS.acquire(blocking=False):
            held += 1
        if held == ws.PDF_MAX_CONCURRENT:
            break
        await asyncio.sleep(0.05)
    for _ in range(held):
        ws._PDF_SLOTS.release()
    assert held == ws.PDF_MAX_CONCURRENT
    assert len(extracted) < 15


async def test_pdf_text_stops_at_the_char_cap_and_at_two_hundred_pages(monkeypatch):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    plugin = ws.WebSearchPlugin()
    monkeypatch.setitem(sys.modules, "pypdf", _fake_pypdf(["aaaa", "bbbb", "cccc"]))
    got = await plugin.read_page("https://docs.example/a.pdf", full_chars=3,
                                 _transport=_pdf_transport())
    assert got.text == "aaa" and got.text_cut is True and got.pages == (1, 3)
    monkeypatch.setitem(sys.modules, "pypdf", _fake_pypdf(["x"] * 201))
    got = await plugin.read_page("https://docs.example/long.pdf", _transport=_pdf_transport())
    assert ws.PDF_MAX_PAGES == 200
    assert got.pages == (200, 201) and got.text_cut is True


# ── web_tools: fences and bounds ─────────────────────────────────────────────

async def test_a_broker_that_cannot_answer_is_read_as_a_secret(tmp_path):
    class Broken:
        def redact(self, text):
            raise RuntimeError("broker down")

    reader = Reader(rows=[{"title": "t", "url": "https://x.example/", "snippet": "s"}])
    server = _server(reader, secret_broker=Broken(), result_store=_store(tmp_path))
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://a.example/p"})
    assert out["result"]["ok"] is False and out["result"]["reason"] == "secret_in_url"
    assert reader.reads == []
    out = await _call(server, wt.TOOL_SEARCH, {"query": "anything"})
    assert out["result"]["ok"] is False and out["result"]["reason"] == "secret_in_query"


def test_head_tail_never_exceeds_its_limit_even_when_the_marker_does_not_fit():
    text = "x" * 1000
    for limit in (1, 2, 5, 10, 31, 64, 100, 999):
        cut, was_cut = wt.head_tail(text, limit)
        assert was_cut is True and len(cut) <= limit, limit
    assert wt.head_tail(text, 1000) == (text, False)


def test_read_back_probe_honours_the_turn_tool_offer(monkeypatch, tmp_path):
    from agents.core import autonomy_coordinator, file_tools, job_toolsets

    server = ToolRPCServer()
    monkeypatch.setattr(server, "allows", lambda name: name == "file_read")
    monkeypatch.setattr(job_toolsets, "allows", lambda name: True)
    monkeypatch.setattr(file_tools.FileTools, "reaches", lambda self, p: True)
    probe = wt.default_read_back(server)
    path = str(tmp_path / "x.txt")
    assert probe(path) is True                               # no offer recorded: the registry decides
    token = autonomy_coordinator._TURN_TOOL_OFFER.set(frozenset({"web_search"}))
    try:
        assert probe(path) is False                          # this turn was not offered file_read
    finally:
        autonomy_coordinator._TURN_TOOL_OFFER.reset(token)
    token = autonomy_coordinator._TURN_TOOL_OFFER.set(frozenset({"file_read"}))
    try:
        assert probe(path) is True
    finally:
        autonomy_coordinator._TURN_TOOL_OFFER.reset(token)


# ── research: local research cannot be steered onto another backend ──────────

def test_research_pins_its_own_plugin_against_the_rescue_switch_and_extra_backends(monkeypatch):
    from agents.core.acquisition.research import WebSearchResearchBackend

    extra = Recorder("extra-index")
    wp.register_search_provider(extra)
    try:
        monkeypatch.setenv(wp.RESCUE_ENV, "1")
        backend = WebSearchResearchBackend(searxng_url="https://searx.local")
        selection = backend.plugin.selection()
        assert selection.primary.name == "searxng" and selection.rescue == ()
    finally:
        wp.unregister_search_provider("extra-index")


def test_research_refuses_a_supplied_plugin_that_could_leave_searxng(monkeypatch):
    from agents.core.acquisition.research import ResearchError, WebSearchResearchBackend

    extra = Recorder("extra-index")
    wp.register_search_provider(extra)
    try:
        rescuing = ws.WebSearchPlugin(searxng_url="https://searx.local", backend="searxng",
                                      rescue=True)
        assert rescuing.selection().primary.name == "searxng" and rescuing.selection().rescue
        with pytest.raises(ResearchError, match="cloud"):
            WebSearchResearchBackend(plugin=rescuing)
        elsewhere = ws.WebSearchPlugin(searxng_url="https://searx.local", backend="extra-index",
                                       rescue=False)
        assert elsewhere.selection().primary.name == "extra-index"
        with pytest.raises(ResearchError, match="cloud"):
            WebSearchResearchBackend(plugin=elsewhere)
    finally:
        wp.unregister_search_provider("extra-index")


def test_research_refuses_a_plugin_nothing_can_answer_for():
    from agents.core.acquisition.research import ResearchError, WebSearchResearchBackend

    mute = ws.WebSearchPlugin(searxng_url="https://searx.local", backend="no-such-backend")
    with pytest.raises(ResearchError, match="unavailable"):
        WebSearchResearchBackend(plugin=mute)


# ── honesty: what the HUD tells the owner a configured search needs ──────────

def test_honesty_names_searxng_as_a_way_to_configure_web_search():
    from agents.core.plugins.honesty import honesty_for

    verdict = honesty_for("websearch", False, "")
    assert verdict["status"] == "needs_config"
    assert any("SEARXNG_URL" in need for need in verdict["needs"])
    assert any("TAVILY_API_KEY" in need for need in verdict["needs"])
