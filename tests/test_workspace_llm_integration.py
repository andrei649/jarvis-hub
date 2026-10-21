"""``llm.complete`` through the hub's real router against a real model server (Appendix A).

A :class:`FakeOpenAIServer` on 127.0.0.1 plays the local model; a real
``HybridRouter`` detects it as the ``lm-studio`` backend (``JARVIS_LM_STUDIO_URL``),
Ollama points at a closed port, and a minimal orchestrator stand-in exposes the
router plus a ``GuardrailsEngine`` in WARN mode so ``get_orch()`` finds them. Every
step of the algorithm then runs for real: local backend selection, the data-handling
gate, the guardrails binding, the physical-request scope and the deadline.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace

import httpx
import pytest

import agents.web as web
from agents.core.llm import data_handling
from agents.core.llm.hybrid_router import HybridRouter
from agents.core.security.guardrails import GuardrailsEngine
from agents.core.security.types import RedactionMode
from agents.core.workspace import llm
from tests.support import fake_openai_server
from tests.support.fake_openai_server import FakeOpenAIServer
from tests.support.ports import closed_port
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    db,
    make_user,
    origin_of,
    seed_company,
    ws,
)
from tests.test_workspace_assistant_helpers import SSE_ACCEPT, chat_app, parse_sse, seed_doc

QUESTION_RO = ('<source id="1" title="Politica de concedii">Concediul anual este de 21 de zile '
               "lucrătoare. Cererea se depune din timp.</source>\n\n"
               "Întrebarea utilizatorului:\nCâte zile de concediu avem?")
_CLOUD_ENV = ("GEMINI_API_KEY", "GEMINI_API_KEYS", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS",
              "XAI_API_KEY", "OPENAI_API_KEY", "DEEPINFRA_API_KEY", "HTTP_PROXY", "http_proxy",
              "ALL_PROXY", "all_proxy")


def _closed_port() -> int:
    return closed_port()


def _point_hub_at(monkeypatch: pytest.MonkeyPatch, lm_studio_url: str) -> None:
    for name in _CLOUD_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_LM_STUDIO_URL", lm_studio_url)
    monkeypatch.setenv("JARVIS_OLLAMA_URL", f"http://127.0.0.1:{_closed_port()}")
    monkeypatch.setenv("JARVIS_LLM_WARMUP", "0")


async def _install_router(monkeypatch: pytest.MonkeyPatch) -> HybridRouter:
    router = HybridRouter()
    await router.detect()
    llm.set_engine_for_tests(None)
    monkeypatch.setattr(web, "orch", SimpleNamespace(
        llm_router=router, security=GuardrailsEngine(mode=RedactionMode.WARN)))
    return router


@pytest.fixture
async def model_server(ws, monkeypatch) -> AsyncIterator[tuple[FakeOpenAIServer, HybridRouter]]:
    """The fake local model, a real router that detected it, and the orch stand-in."""
    with FakeOpenAIServer(slow_seconds=3.0) as server:
        _point_hub_at(monkeypatch, server.url)
        router = await _install_router(monkeypatch)
        try:
            yield server, router
        finally:
            await router.aclose()


def _collector() -> tuple[list[str], object]:
    tokens: list[str] = []

    async def on_token(text: str) -> None:
        tokens.append(text)

    return tokens, on_token


def _completions(server: FakeOpenAIServer) -> list[dict]:
    return [r["body"] for r in server.requests if r["path"] == "/v1/chat/completions"]


async def test_the_router_detected_the_fake_server_as_the_local_backend(model_server):
    _, router = model_server
    assert router.local_backend_name == "lm-studio"
    assert router.get_model("workspace") == fake_openai_server.DEFAULT_MODEL


async def test_complete_streams_tokens_and_reports_a_local_route(model_server):
    server, _ = model_server
    tokens, on_token = _collector()
    result = await llm.complete(system="Ești asistentul.", prompt=QUESTION_RO,
                                policy="local_only", on_token=on_token, max_tokens=300)
    assert result.text == "Conform documentelor companiei: Concediul anual este de 21 de zile " \
                          "lucrătoare. [1]"
    assert (result.route, result.locality) == ("local", "local")
    assert result.model == fake_openai_server.DEFAULT_MODEL
    assert "".join(tokens) == result.text
    assert len(tokens[0]) >= llm.HOLD_BACK_CHARS
    sent = _completions(server)[-1]
    assert sent["stream"] is True and sent["max_tokens"] == 300
    assert sent["messages"] == [{"role": "system", "content": "Ești asistentul."},
                                {"role": "user", "content": QUESTION_RO}]


async def test_posture_reports_the_local_model_and_the_guardrails_mode(model_server):
    posture = await llm.posture("local_only")
    assert posture == {"available": True, "backend": "lm-studio",
                       "model": fake_openai_server.DEFAULT_MODEL, "route": "local",
                       "locality": "local", "policy": "local_only", "reason": "",
                       "guardrails_mode": "warn"}


async def test_a_server_that_went_down_is_model_unavailable_and_nothing_is_streamed(
        model_server):
    server, _ = model_server
    await llm.complete(system="s", prompt="Salut, ce faci azi?", policy="local_only")
    server.stop()
    tokens, on_token = _collector()
    with pytest.raises(llm.LLMUnavailable) as caught:
        await llm.complete(system="s", prompt=QUESTION_RO, policy="local_only",
                           on_token=on_token)
    assert caught.value.code == "model_unavailable"
    assert caught.value.extra["reason"] == "model_unreachable"
    assert tokens == []
    posture = await llm.posture("local_only")
    assert (posture["available"], posture["reason"]) == (False, "model_unreachable"), \
        "the failed call marks the server down at once, not at the hub's next re-probe"


async def test_the_posture_asks_the_server_and_reports_one_that_died(model_server,
                                                                      monkeypatch):
    """Review fix UX-02: the hub re-probes its servers only every 5 minutes; the chip must
    not stay green over a dead server for that long."""
    server, router = model_server
    assert (await llm.posture("local_only"))["available"] is True
    server.stop()
    assert router.local_backend_name == "lm-studio", "the router has not noticed yet"
    monkeypatch.setattr(llm, "LIVENESS_TTL_SECONDS", 0.0)
    posture = await llm.posture("local_only")
    assert posture["available"] is False and posture["reason"] == "model_unreachable"
    assert (posture["backend"], posture["route"], posture["locality"]) == (
        "lm-studio", "local", "local")
    assert [r for r in server.requests if r["path"] == "/v1/chat/completions"] == [], \
        "a posture read sends no prompt"


async def test_a_stream_cut_mid_answer_is_model_unreachable(ws, monkeypatch):
    """Review fix F2: the server dying mid-stream ("peer closed connection") is not an
    error the server answered with."""
    with FakeOpenAIServer(token_delay=0.05) as server:
        _point_hub_at(monkeypatch, server.url)
        router = await _install_router(monkeypatch)
        try:
            call = asyncio.ensure_future(llm.complete(system="s", prompt=QUESTION_RO,
                                                      policy="local_only"))
            for _ in range(200):
                if _completions(server):
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.15)
            server.stop()
            with pytest.raises(llm.LLMUnavailable) as caught:
                await call
            assert caught.value.extra["reason"] == "model_unreachable"
            assert (await llm.posture("local_only"))["reason"] == "model_unreachable"
        finally:
            await router.aclose()


async def test_a_server_error_is_model_unavailable(model_server):
    tokens, on_token = _collector()
    with pytest.raises(llm.LLMUnavailable) as caught:
        await llm.complete(system="s", prompt=f"{fake_openai_server.ERROR_TRIGGER} întrebare",
                           policy="local_only", on_token=on_token)
    assert caught.value.extra["reason"] == "model_error"
    assert tokens == []


async def test_an_empty_completion_is_an_empty_answer(model_server):
    with pytest.raises(llm.LLMUnavailable) as caught:
        await llm.complete(system="s", prompt=fake_openai_server.EMPTY_TRIGGER,
                           policy="local_only")
    assert caught.value.extra["reason"] == "empty_answer"


async def test_a_slow_model_hits_the_answer_deadline(model_server):
    with pytest.raises(llm.ModelTimeout):
        await llm.complete(system="s", prompt=f"{fake_openai_server.SLOW_TRIGGER} întrebare",
                           policy="local_only", timeout_seconds=0.3)


async def test_without_any_local_server_local_only_is_no_local_model(ws, monkeypatch):
    _point_hub_at(monkeypatch, f"http://127.0.0.1:{_closed_port()}")
    router = await _install_router(monkeypatch)
    try:
        with pytest.raises(llm.LLMUnavailable) as caught:
            await llm.complete(system="s", prompt="p", policy="local_only")
        assert caught.value.extra["reason"] == "no_local_model"
        assert (await llm.posture("local_only"))["reason"] == "no_local_model"
    finally:
        await router.aclose()


async def test_allow_cloud_never_sends_company_text_to_a_provider_that_may_train(
        ws, monkeypatch):
    """Gemini's data handling is ``unknown``: refused while unacknowledged, and still
    refused under ``allow_cloud`` once the owner acknowledged it (it may train)."""
    with FakeOpenAIServer() as server:
        _point_hub_at(monkeypatch, server.url)
        monkeypatch.setenv("GEMINI_API_KEY", "workspace-test-key-not-real")
        router = await _install_router(monkeypatch)
        router.set_cloud_fallback_mode("always")  # the workspace agent now routes to cloud
        audit_sink = SimpleNamespace(log=lambda event: None)
        scope = ""
        try:
            with pytest.raises(llm.ModelPolicyBlocked) as unacknowledged:
                await llm.complete(system="s", prompt=QUESTION_RO, policy="allow_cloud")
            assert unacknowledged.value.extra["reason"] == "data_policy_unacknowledged"

            gemini = next(row for row in data_handling.posture(router)["providers"]
                          if row["provider"] == "gemini")
            scope = gemini["scope"]
            data_handling.acknowledge(router, "gemini", True, scope, audit_sink)
            with pytest.raises(llm.ModelPolicyBlocked) as acknowledged:
                await llm.complete(system="s", prompt=QUESTION_RO, policy="allow_cloud")
            assert acknowledged.value.code == "model_policy_blocked"
            assert acknowledged.value.extra["reason"] == "provider_may_train"
            assert (await llm.posture("allow_cloud"))["reason"] == "provider_may_train"

            # local_only still answers from the local server meanwhile.
            result = await llm.complete(system="s", prompt=QUESTION_RO, policy="local_only")
            assert result.locality == "local"
            assert len(_completions(server)) == 1
        finally:
            if scope:
                data_handling.acknowledge(router, "gemini", False, scope, audit_sink)
            await router.aclose()


async def test_the_chat_route_streams_a_cited_answer_from_the_real_model(model_server):
    """The whole stack: login, a seeded document, the SSE route, the real engine."""
    server, _ = model_server
    conn = db()
    company = seed_company(conn)
    seed_doc(conn, department_id=company.dept_a, title="Politica de concedii",
             text="Concediul anual este de 21 de zile lucrătoare. Cererea se depune din timp.")
    transport = httpx.ASGITransport(app=chat_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        origin = {"Origin": "http://testserver"}
        login = await client.post("/api/workspace/login", headers=origin, json={
            "email": company.member_a.email, "password": "Parola-Buna-2026!"})
        assert login.status_code == 200, login.text
        headers = {**origin, "X-CSRF-Token": login.json()["csrf_token"]}
        created = await client.post("/api/workspace/conversations", headers=headers,
                                    json={"department_id": company.dept_a})
        conversation_id = created.json()["id"]
        response = await client.post(
            f"/api/workspace/conversations/{conversation_id}/messages",
            headers={**headers, **SSE_ACCEPT},
            json={"content": "Câte zile de concediu avem?"})
    assert response.status_code == 200
    events = parse_sse(response.text)
    kinds = [kind for kind, _ in events]
    assert kinds[:2] == ["start", "sources"] and kinds[-1] == "done"
    streamed = "".join(data["t"] for kind, data in events if kind == "token")
    done = events[-1][1]["assistant_message"]
    assert done["content"] == streamed
    assert "[1]" in done["content"] and "21 de zile" in done["content"]
    assert (done["status"], done["locality"]) == ("complete", "local")
    assert done["model"] == fake_openai_server.DEFAULT_MODEL
    assert [c["title"] for c in done["citations"]] == ["Politica de concedii"]
    prompt = _completions(server)[-1]["messages"][-1]["content"]
    assert '<source id="1" title="Politica de concedii">' in prompt
    conn.close()


# ── the owner's personal pipeline is never touched (spec §1 non-goal; review T10) ─────

#: What the owner's assistant is made of: the workspace must reach none of it.
PERSONAL_PARTS = frozenset({"handle_input", "process", "memory", "memory_store",
                            "living_memory", "agents", "skills", "channels", "conversation"})


#: The attribute names that only the owner's pipeline has (``conversation`` and the like are
#: workspace words too, so the static check looks for these alone).
PIPELINE_ENTRY_POINTS = frozenset({"handle_input", "process", "memory", "memory_store",
                                   "living_memory"})


class _OwnersHub:
    """An orchestrator offering the router and the guardrails; any other attribute read is
    recorded (and answered with AttributeError, so hub code's ``getattr(…, default)`` keeps
    working) and its personal parts would raise if called."""

    def __init__(self, router: HybridRouter) -> None:
        self.llm_router = router
        self.security = GuardrailsEngine(mode=RedactionMode.WARN)
        self.touched: list[str] = []

    def __getattr__(self, name: str):
        self.__dict__.setdefault("touched", []).append(name)
        if name in PERSONAL_PARTS:
            def refuse(*_args, **_kwargs):
                raise AssertionError(f"the workspace called the owner's orch.{name}")
            return refuse
        raise AttributeError(name)


async def test_a_chat_answer_and_a_report_run_never_reach_the_personal_pipeline(model_server,
                                                                              monkeypatch):
    from agents.core.workspace import reports
    from tests.test_workspace_reports_support import seed_document as seed_report_document

    _, router = model_server
    owners = _OwnersHub(router)
    monkeypatch.setattr(web, "orch", owners)
    conn = db()
    company = seed_company(conn)
    seed_doc(conn, department_id=company.dept_a, title="Politica de concedii",
             text="Concediul anual este de 21 de zile lucrătoare. Cererea se depune din timp.")
    transport = httpx.ASGITransport(app=chat_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        origin = {"Origin": "http://testserver"}
        login = await client.post("/api/workspace/login", headers=origin, json={
            "email": company.member_a.email, "password": "Parola-Buna-2026!"})
        headers = {**origin, "X-CSRF-Token": login.json()["csrf_token"]}
        conversation = (await client.post("/api/workspace/conversations", headers=headers,
                                          json={"department_id": company.dept_a})).json()["id"]
        answer = await client.post(f"/api/workspace/conversations/{conversation}/messages",
                                   headers={**headers, **SSE_ACCEPT},
                                   json={"content": "Câte zile de concediu avem?"})
    assert parse_sse(answer.text)[-1][0] == "done"
    seed_report_document(conn, department_id=company.dept_a, uploader_id=company.member_a.id,
                         title="Vânzări Nord", chunks=["Vânzările din Nord au crescut cu 12%."])
    report_id = reports.create_report(conn, company.member_a, {
        "department_id": company.dept_a, "name": "Nord", "instructions": "Rezumă vânzările."})
    run_id = reports.start_manual_run(conn, company.member_a, report_id)
    await reports.execute_run(run_id)
    status = conn.execute("SELECT status FROM report_runs WHERE id = ?", (run_id,)).fetchone()[0]
    assert status == "succeeded"
    assert not PERSONAL_PARTS & set(owners.touched), owners.touched
    conn.close()


def test_no_workspace_module_names_the_personal_pipeline():
    """The static half: no workspace source reads ``.handle_input``, ``.process`` or the
    owner's memory, and none imports the orchestrator or the memory package."""
    import ast
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    sources = [*sorted((repo / "agents" / "core" / "workspace").rglob("*.py")),
               *sorted((repo / "agents" / "core" / "routers").glob("workspace_*.py"))]
    assert len(sources) > 20
    offenders = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in PIPELINE_ENTRY_POINTS:
                offenders.append(f"{path.name}:{node.lineno} .{node.attr}")
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                       else [alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [])
            for module in modules:
                if module.startswith(("agents.core.memory", "agents.core.orchestrator",
                                      "agents.orchestrator")):
                    offenders.append(f"{path.name}:{node.lineno} import {module}")
    assert offenders == []


async def test_parallel_posture_reads_share_one_liveness_probe(model_server, monkeypatch):
    server, _ = model_server
    monkeypatch.setattr(llm, "LIVENESS_TTL_SECONDS", 30.0)
    llm._liveness.clear()
    probes: list[str] = []
    real_get = httpx.AsyncClient.get

    async def counting_get(self, url, *args, **kwargs):
        probes.append(str(url))
        return await real_get(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", counting_get)
    postures = await asyncio.gather(*(llm.posture("local_only") for _ in range(5)))
    assert all(p["available"] for p in postures)
    assert probes == [f"{server.url}/v1/models"]
