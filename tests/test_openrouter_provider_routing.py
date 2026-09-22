"""H583 — steer which upstream provider serves an OpenRouter request.

OpenRouter fans one model id out to several upstream providers. Six knobs shape
that choice: ``sort`` (price / throughput / latency), ``only`` (whitelist of
provider slugs), ``ignore`` (blacklist), ``order`` (explicit priority, unlisted
providers stay as fallbacks), ``require_parameters`` (refuse a provider that would
silently drop tools / temperature) and ``data_collection`` (``deny`` keeps prompts
away from providers that store or train on them). They travel as one ``provider``
object in the request body, only to OpenRouter, and live on the ``llm`` settings
surface next to ``compatible_provider`` — ``data_collection`` defaults to ``deny``.

Everything here is offline: a capturing fake client, or ``httpx.MockTransport``.
"""

from __future__ import annotations

import io
import json

import httpx
import pytest

from agents.core import settings_db
from agents.core.llm.egress import llm_async_client
from agents.core.llm.openrouter import OPENROUTER_BASE, OpenRouterBackend
from agents.core.llm.provider_routing import (
    ProviderRoutingInvalid,
    build_provider_block,
    provider_routing_from_settings,
)
from agents.core.llm.providers import DEFAULT_REGISTRY

_ALL_SIX = {
    "sort": "price",
    "only": ["anthropic", "google-vertex"],
    "ignore": ["together"],
    "order": ["anthropic", "google-vertex"],
    "require_parameters": True,
    "data_collection": "deny",
}
_OK = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}


class _Resp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _Client:
    """Captures every body the backend would have sent."""

    def __init__(self):
        self.bodies = []

    async def post(self, url, json=None, headers=None):
        self.bodies.append(json)
        return _Resp(_OK)

    async def aclose(self):
        pass


def _wire(handler, base_url=OPENROUTER_BASE):
    """The real egress client (ledger hook and all) over an in-memory transport."""
    return llm_async_client("openrouter", base_url=base_url, transport=httpx.MockTransport(handler))


# ── the request body ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_turn_payload_carries_provider_block():
    client = _Client()
    backend = OpenRouterBackend(api_key="k", client=client, provider_routing=_ALL_SIX)
    await backend.generate_tool_turn("acme/model-a", [{"role": "user", "content": "hi"}], [])
    assert client.bodies[0]["provider"] == {
        "sort": "price",
        "only": ["anthropic", "google-vertex"],
        "ignore": ["together"],
        "order": ["anthropic", "google-vertex"],
        "require_parameters": True,
        "data_collection": "deny",
    }


@pytest.mark.asyncio
async def test_text_turn_payload_carries_provider_block():
    client = _Client()
    backend = OpenRouterBackend(api_key="k", client=client,
                                provider_routing={"data_collection": "deny", "sort": "latency"})
    await backend.generate("acme/model-a", "hi")
    assert client.bodies[0]["provider"] == {"sort": "latency", "data_collection": "deny"}


@pytest.mark.asyncio
async def test_block_is_absent_when_nothing_is_set():
    client = _Client()
    await OpenRouterBackend(client=client).generate("acme/model-a", "hi")
    empty = {"sort": "", "only": [], "ignore": [], "order": [],
             "require_parameters": False, "data_collection": ""}
    await OpenRouterBackend(client=client, provider_routing=empty).generate_tool_turn(
        "acme/model-a", [{"role": "user", "content": "hi"}], [])
    assert "provider" not in client.bodies[0]
    assert "provider" not in client.bodies[1]


@pytest.mark.asyncio
async def test_block_is_never_sent_to_an_openai_compatible_endpoint():
    """An arbitrary OpenAI-compatible server does not know OpenRouter's object."""
    client = _Client()
    backend = OpenRouterBackend(client=client, profile=DEFAULT_REGISTRY.get("openai-compatible"),
                                provider_routing=_ALL_SIX)
    await backend.generate("m", "hi")
    await backend.generate_tool_turn("m", [{"role": "user", "content": "hi"}], [])
    assert all("provider" not in body for body in client.bodies)


@pytest.mark.asyncio
async def test_each_request_gets_its_own_copy_of_the_block():
    client = _Client()
    backend = OpenRouterBackend(client=client, provider_routing=_ALL_SIX)
    await backend.generate("acme/model-a", "one")
    client.bodies[0]["provider"]["only"].append("mutated")
    await backend.generate("acme/model-a", "two")
    assert client.bodies[1]["provider"]["only"] == ["anthropic", "google-vertex"]


@pytest.mark.asyncio
async def test_the_block_reaches_the_wire_through_the_real_client():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=_OK)

    backend = OpenRouterBackend(api_key="k", provider_routing=_ALL_SIX, client=_wire(handler))
    await backend.generate_tool_turn("acme/model-a", [{"role": "user", "content": "hi"}], [])
    await backend.aclose()
    assert seen[0]["provider"]["data_collection"] == "deny"
    assert seen[0]["provider"]["require_parameters"] is True


# ── validation ──────────────────────────────────────────────────────────────


def test_build_normalises_and_omits_the_falsy_knobs():
    assert build_provider_block() is None
    assert build_provider_block(only="Anthropic, google-vertex , anthropic") == {
        "only": ["anthropic", "google-vertex"],
    }
    # require_parameters=False is omitted rather than sent as false.
    assert build_provider_block(require_parameters=False, data_collection="allow") == {
        "data_collection": "allow",
    }


@pytest.mark.parametrize("knobs", [
    {"only": ["bad slug"]},
    {"ignore": ["evil;rm -rf"]},
    {"order": ["-leading-dash"]},
    {"only": ["x" * 65]},
    {"only": [f"p{i}" for i in range(33)]},
    {"only": [7]},
    {"sort": "cheapest"},
    {"data_collection": "maybe"},
    {"require_parameters": "yes"},
])
def test_invalid_knobs_are_refused(knobs):
    with pytest.raises(ProviderRoutingInvalid):
        build_provider_block(**knobs)


@pytest.mark.parametrize("knobs", [{"only": ["bad slug"]}, {"sort": "cheapest"}])
def test_the_backend_refuses_an_invalid_block_at_construction(knobs):
    with pytest.raises(ProviderRoutingInvalid):
        OpenRouterBackend(client=_Client(), provider_routing=knobs)


# ── the settings surface ────────────────────────────────────────────────────


def _spec(key):
    return next(d for d in settings_db.DEFAULTS if d["category"] == "llm" and d["key"] == key)


def test_the_six_knobs_are_llm_settings_and_data_collection_defaults_to_deny():
    assert _spec("openrouter_sort")["opts"] == ["", "price", "throughput", "latency"]
    assert _spec("openrouter_sort")["value"] == ""
    for key in ("openrouter_only", "openrouter_ignore", "openrouter_order"):
        assert _spec(key)["kind"] == "tags" and _spec(key)["value"] == []
    assert _spec("openrouter_require_parameters")["kind"] == "toggle"
    assert _spec("openrouter_require_parameters")["value"] is False
    assert _spec("openrouter_data_collection")["value"] == "deny"
    assert _spec("openrouter_data_collection")["opts"] == ["deny", "allow"]
    keys = [d["key"] for d in settings_db.DEFAULTS if d["category"] == "llm"]
    # Seeded beside the compatible-provider selector they qualify.
    assert keys.index("openrouter_sort") == keys.index("compatible_provider") + 1


def test_settings_writes_refuse_an_invalid_slug():
    errors = settings_db.validate_category("llm", {"openrouter_only": ["anthropic", "bad slug!"]})
    assert errors and "openrouter_only" in errors[0]
    assert settings_db.validate_category("llm", {"openrouter_ignore": ["together", "deepinfra/turbo"]}) == []
    assert settings_db.validate_category("llm", {"openrouter_sort": "cheapest"})
    assert settings_db.validate_category("llm", {"openrouter_data_collection": "maybe"})


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    return tmp_path


def test_owner_sets_the_knobs_through_nerva_config(temp_settings):
    from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, main

    def run(argv):
        out, err = io.StringIO(), io.StringIO()
        ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""),
                      client_factory=lambda env: None)
        return main(argv, context=ctx), out.getvalue(), err.getvalue()

    assert settings_db.get_value("llm", "openrouter_data_collection") == "deny"
    code, _out, _err = run(["config", "set", "llm.openrouter_only", "anthropic, google-vertex"])
    assert code == EXIT_OK
    assert settings_db.get_value("llm", "openrouter_only") == ["anthropic", "google-vertex"]
    code, _out, err = run(["config", "set", "llm.openrouter_ignore", "together, bad slug"])
    assert code == EXIT_FAILED and "openrouter_ignore" in err
    assert settings_db.get_value("llm", "openrouter_ignore") == []


def test_provider_routing_from_settings_reads_the_six_rows():
    stored = {"openrouter_sort": "throughput", "openrouter_only": ["anthropic"],
              "openrouter_require_parameters": True}
    routing = provider_routing_from_settings(lambda key, default: stored.get(key, default))
    assert routing == {"sort": "throughput", "only": ["anthropic"], "ignore": [], "order": [],
                       "require_parameters": True, "data_collection": "deny"}


# ── the router wires the settings into the backend ──────────────────────────


async def _detect(monkeypatch, settings):
    from unittest.mock import AsyncMock

    from agents.core.llm.hybrid_router import HybridRouter
    from agents.core.llm.router import LLMRouter

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(LLMRouter, "detect", AsyncMock())
    monkeypatch.setattr(HybridRouter, "_check", AsyncMock(return_value=False))
    monkeypatch.setattr(HybridRouter, "_admin_setting",
                        staticmethod(lambda k, d: settings.get(k, d) or d))
    router = HybridRouter()
    await router.detect()
    return router


@pytest.mark.asyncio
async def test_router_passes_the_owner_settings_to_openrouter(monkeypatch):
    router = await _detect(monkeypatch, {
        "compatible_provider": "openrouter", "compatible_model": "acme/model-a",
        "openrouter_sort": "price", "openrouter_ignore": ["together"],
        "openrouter_require_parameters": True,
    })
    backend = router._compatible_backend
    assert backend.provider_block == {"sort": "price", "ignore": ["together"],
                                      "require_parameters": True, "data_collection": "deny"}
    await router.aclose()


@pytest.mark.asyncio
async def test_router_default_is_deny_for_openrouter_and_nothing_for_compatible(monkeypatch):
    router = await _detect(monkeypatch, {"compatible_provider": "openrouter",
                                         "compatible_model": "acme/model-a"})
    assert router._compatible_backend.provider_block == {"data_collection": "deny"}
    await router.aclose()
    router = await _detect(monkeypatch, {"compatible_provider": "openai-compatible",
                                         "compatible_model": "m", "openrouter_sort": "price"})
    assert router._compatible_backend is not None
    assert router._compatible_backend.provider_block is None
    await router.aclose()


@pytest.mark.asyncio
async def test_router_fails_closed_on_a_tampered_stored_value(monkeypatch, caplog):
    """A row written around the validator must not widen routing — no backend at all."""
    router = await _detect(monkeypatch, {
        "compatible_provider": "openrouter", "compatible_model": "acme/model-a",
        "openrouter_only": ["anthropic", "not a slug"],
    })
    assert router._compatible_backend is None
    assert "provider routing" in caplog.text.lower()
    await router.aclose()


# ── live: an owner's change reaches the next request, not the next detect() ─


async def _detect_from_db(monkeypatch, stored):
    """HybridRouter.detect() against the real (temporary) settings DB — no stubbed reads."""
    from unittest.mock import AsyncMock

    from agents.core.llm.hybrid_router import HybridRouter
    from agents.core.llm.router import LLMRouter

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    for name in ("OPENROUTER_BASE_URL", "OPENAI_BASE_URL", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(LLMRouter, "detect", AsyncMock())
    monkeypatch.setattr(HybridRouter, "_check", AsyncMock(return_value=False))
    settings_db.put_category("llm", {"compatible_provider": "openrouter",
                                     "compatible_model": "acme/model-a", **stored})
    router = HybridRouter()
    await router.detect()
    return router


def _capture(backend):
    """Re-point a router-built backend at an in-memory transport; return its bodies."""
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_OK)

    backend.client = _wire(handler)
    return bodies


@pytest.mark.asyncio
async def test_router_builds_the_block_from_the_stored_rows(temp_settings, monkeypatch):
    router = await _detect_from_db(monkeypatch, {"openrouter_sort": "throughput",
                                                 "openrouter_order": ["anthropic"]})
    backend = router._compatible_backend
    bodies = _capture(backend)
    await backend.generate("acme/model-a", "hi")
    assert bodies[0]["provider"] == {"sort": "throughput", "order": ["anthropic"],
                                     "data_collection": "deny"}
    await router.aclose()


@pytest.mark.asyncio
async def test_a_settings_change_after_detect_reaches_the_next_request(temp_settings, monkeypatch):
    """HUD PUT / `nerva config set` store the row; the live backend must send it next."""
    router = await _detect_from_db(monkeypatch, {})
    backend = router._compatible_backend
    bodies = _capture(backend)
    await backend.generate("acme/model-a", "before")
    assert bodies[0]["provider"] == {"data_collection": "deny"}

    change = {"openrouter_only": ["anthropic"], "openrouter_ignore": ["together"]}
    assert settings_db.validate_category("llm", change) == []
    settings_db.put_category("llm", change)
    await backend.generate_tool_turn("acme/model-a", [{"role": "user", "content": "after"}], [])
    assert bodies[1]["provider"] == {"only": ["anthropic"], "ignore": ["together"],
                                     "data_collection": "deny"}

    # Loosening applies on the next request too — and so does tightening back.
    settings_db.put_category("llm", {"openrouter_data_collection": "allow"})
    await backend.generate("acme/model-a", "loose")
    assert bodies[2]["provider"]["data_collection"] == "allow"
    settings_db.put_category("llm", {"openrouter_data_collection": "deny"})
    await backend.generate("acme/model-a", "tight")
    assert bodies[3]["provider"]["data_collection"] == "deny"
    await router.aclose()


@pytest.mark.asyncio
async def test_a_tampered_row_after_detect_refuses_the_request(temp_settings, monkeypatch, caplog):
    """Written around the validator while running: nothing is sent, never a wider route."""
    router = await _detect_from_db(monkeypatch, {"openrouter_only": ["anthropic"]})
    backend = router._compatible_backend
    bodies = _capture(backend)
    settings_db.put_category("llm", {"openrouter_only": ["anthropic", "not a slug"]})
    out = await backend.generate("acme/model-a", "hi")
    turn = await backend.generate_tool_turn("acme/model-a", [{"role": "user", "content": "hi"}], [])
    assert bodies == []
    assert out == "[OpenRouter error]" and turn.content == "[OpenRouter error]"
    assert "llm.openrouter_" in caplog.text and "not a slug" in caplog.text
    # Fixed through the validated path, the very next request flows again.
    settings_db.put_category("llm", {"openrouter_only": ["anthropic"]})
    await backend.generate("acme/model-a", "hi")
    assert bodies[0]["provider"]["only"] == ["anthropic"]
    await router.aclose()


# ── a routing-caused refusal says which setting to look at ──────────────────


@pytest.mark.asyncio
async def test_a_data_policy_404_names_the_setting_in_the_log(caplog):
    policy = {"error": {"code": 404,
                        "message": "No endpoints found matching your data policy\n(forged line)"}}
    backend = OpenRouterBackend(api_key="k", provider_routing={"data_collection": "deny"},
                                client=_wire(lambda request: httpx.Response(404, json=policy)))
    out = await backend.generate("acme/model-a", "hi")
    turn = await backend.generate_tool_turn("acme/model-a", [{"role": "user", "content": "hi"}], [])
    await backend.aclose()
    assert out == "[OpenRouter error]" and turn.content == "[OpenRouter error]"
    hints = [r.getMessage() for r in caplog.records
             if "llm.openrouter_data_collection" in r.getMessage()]
    assert len(hints) == 2
    assert "No endpoints found matching your data policy" in hints[0]
    assert '"data_collection": "deny"' in hints[0]
    assert "\n" not in hints[0]                        # the provider's text is log-safe


@pytest.mark.asyncio
async def test_no_routing_hint_without_a_block_or_for_an_auth_error(caplog):
    bare = OpenRouterBackend(api_key="k", client=_wire(
        lambda request: httpx.Response(404, json={"error": {"message": "no such model"}})))
    await bare.generate("acme/model-a", "hi")
    denied = OpenRouterBackend(api_key="k", provider_routing={"data_collection": "deny"}, client=_wire(
        lambda request: httpx.Response(401, json={"error": {"message": "bad key"}})))
    await denied.generate("acme/model-a", "hi")
    await bare.aclose()
    await denied.aclose()
    assert "OpenRouter generate failed" in caplog.text
    assert "llm.openrouter_" not in caplog.text
