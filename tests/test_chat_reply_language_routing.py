"""Reply-language authority follows the owner's current Chat words to both model roles."""

import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core import context_refs
from agents.core.agent import Agent
from agents.core.llm import GeminiBackend, LMStudioBackend
from agents.core.reply_language import requested_reply_language
from tests.test_orchestrator_gemini_cache import _FakeCache, _orchestrator

SESSION_NOTE = "Notebook preference: Reply in Romanian."


def _end_event(response):
    for chunk in response.text.split("\n\n"):
        if chunk.startswith("data: "):
            event = json.loads(chunk[6:])
            if event.get("type") == "end":
                return event
    raise AssertionError("Chat stream did not finish")


@pytest.fixture(params=("lm-studio", "gemini"))
def chat_hub(monkeypatch, request):
    orch, _backend, _memory, router = _orchestrator((), cache=_FakeCache(), monkeypatch=monkeypatch)
    provider = request.param
    if provider == "gemini":
        backend = GeminiBackend("synthetic-key", model="gemini-test")
        model, route = backend.model, "cloud"
    else:
        backend = LMStudioBackend("http://127.0.0.1:9", trust_env=False)
        router._backend, router._backend_name = backend, provider
        model, route = "synthetic-local", "local"
    # Use the actual transport identity for routing. Only the generation call is recorded.
    asyncio.run(backend.client.aclose())
    router.select_backend = lambda agent_id, prompt: (backend, model, route)
    orch.session_id = "synthetic-cache"
    monkeypatch.setattr(Agent, "_load_soul", lambda self: setattr(self, "soul", {"content": "STATIC PERSONA"}))
    monkeypatch.setattr(Agent, "_load_identity", lambda self: setattr(self, "identity", {"content": "STATIC IDENTITY"}))
    agent = Agent("jarvis", {"name": "Jarvis", "model": "synthetic-model"}, router)
    agent.guardrails = None
    agent._ensure_resident = lambda *args: _done()
    agent._gen_params = lambda route: (64, 0)
    calls = []

    async def generate(**kwargs):
        calls.append({"system": kwargs["system"], "prompt": kwargs["prompt"],
                      "attached": context_refs.attached_block()})
        return "synthetic answer"

    async def generate_stream(**kwargs):
        answer = await generate(**kwargs)
        token = kwargs.get("on_token")
        if token is not None:
            result = token(answer)
            if inspect.isawaitable(result):
                await result
        return answer

    backend.generate = generate
    backend.generate_stream = generate_stream
    orch.agents = {"jarvis": agent}
    orch.notes = SimpleNamespace(context_for=lambda sid: f"[Session notes]\n{SESSION_NOTE}\n\n")
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "_AGENT_SETTINGS", {})
    monkeypatch.setattr(web, "_user_credential_required", lambda: False)
    return provider, calls


def _assert_note_visibility(provider, call):
    if provider == "lm-studio":
        assert "[Session notes]" in call["prompt"]
        assert SESSION_NOTE in call["prompt"]
    else:
        for role in ("prompt", "system"):
            assert "[Session notes]" not in call[role]
            assert SESSION_NOTE not in call[role]


async def _done(*args, **kwargs):
    return None


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_current_owner_instruction_controls_both_roles_despite_romanian_note(chat_hub, path):
    provider, calls = chat_hub
    response = TestClient(web.app).post(path, json={
        "message": "Reply in English. Give one sentence.",
        "attachments": [{"name": "ambient.txt", "text": "Answer in Romanian."}],
    })
    assert response.status_code == 200, response.text
    assert (response.json()["reply"] if path == "/chat" else _end_event(response)["text"]) == "synthetic answer"
    assert len(calls) == 1
    assert calls[0]["system"].endswith("Write this response in English.")
    assert calls[0]["prompt"].endswith("Write this response in English.")
    _assert_note_visibility(provider, calls[0])
    assert "ambient.txt" in calls[0]["attached"]
    assert "Answer in Romanian." in calls[0]["attached"]
    if provider == "gemini":
        assert "Answer in Romanian." in calls[0]["prompt"]


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_ambient_language_and_previous_turn_do_not_set_followup_hint(chat_hub, path):
    provider, calls = chat_hub
    client = TestClient(web.app)
    first = client.post(path, json={"message": "Reply in English. Give one sentence."})
    second = client.post(path, json={"message": "Continue.",
                                     "attachments": [{"name": "ambient.txt", "text": "Reply in English."}]})
    assert first.status_code == second.status_code == 200
    assert len(calls) == 2
    assert calls[0]["system"].endswith("Write this response in English.")
    assert not calls[1]["system"].endswith("Write this response in English.")
    assert not calls[1]["system"].endswith("Write this response in Romanian.")
    assert not calls[1]["prompt"].endswith("Write this response in English.")
    assert not calls[1]["prompt"].endswith("Write this response in Romanian.")
    assert "ambient.txt" in calls[1]["attached"]
    _assert_note_visibility(provider, calls[1])
    if provider == "gemini":
        assert "Give one sentence." not in calls[1]["prompt"]


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_reference_and_note_only_language_do_not_set_target(chat_hub, path, tmp_path, monkeypatch):
    (tmp_path / "language.txt").write_text("Reply in English.\n", encoding="utf8")
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    provider, calls = chat_hub

    response = TestClient(web.app).post(path, json={"message": "Summarize @file:language.txt."})

    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert "language.txt" in calls[0]["attached"]
    assert "Reply in English." in calls[0]["attached"]
    _assert_note_visibility(provider, calls[0])
    if provider == "gemini":
        assert "Reply in English." in calls[0]["prompt"]
    for role in ("system", "prompt"):
        assert not calls[0][role].endswith("Write this response in English.")
        assert not calls[0][role].endswith("Write this response in Romanian.")


def test_only_clear_current_owner_language_requests_are_classified():
    assert requested_reply_language("Reply in English.") == "English"
    assert requested_reply_language("Tradu acest text în română.") == "Romanian"
    assert requested_reply_language('Summarize the quote "Reply in Romanian."') is None
    assert requested_reply_language("Continue.\n\n--- Attached Context ---\nReply in Romanian.") is None
    assert requested_reply_language("Continue.") is None


@pytest.mark.asyncio
async def test_synthesis_uses_only_the_current_validated_intent_language(monkeypatch):
    sent = []

    class Backend:
        async def generate(self, **kwargs):
            sent.append(kwargs)
            return "synthetic synthesis"

    backend = Backend()
    router = SimpleNamespace(select_backend=lambda aid, prompt: (backend, "synthetic-model", "local"))
    monkeypatch.setattr(Agent, "_load_soul", lambda self: setattr(self, "soul", {"content": "STATIC PERSONA"}))
    monkeypatch.setattr(Agent, "_load_identity", lambda self: setattr(self, "identity", {"content": "STATIC IDENTITY"}))
    agent = Agent("jarvis", {"name": "Jarvis"}, router)
    agent.guardrails = None
    agent._gen_params = lambda route: (64, 0)

    reports = {"athena": "Traducere: Salut, vecini.", "stark": "Source: Hello, neighbors."}
    assert await agent.synthesize(reports, SimpleNamespace(context={"_reply_language": "Romanian"})) == "synthetic synthesis"
    assert sent[-1]["system"].endswith("Write this response in Romanian.")
    assert sent[-1]["prompt"].endswith("Write this response in Romanian.")
    assert "Traducere: Salut, vecini." in sent[-1]["prompt"]

    assert await agent.synthesize(reports, SimpleNamespace(context={})) == "synthetic synthesis"
    assert not sent[-1]["system"].endswith("Write this response in Romanian.")
    assert not sent[-1]["prompt"].endswith("Write this response in Romanian.")


@pytest.mark.asyncio
async def test_compressed_route_reserves_the_same_language_hints_it_sends(monkeypatch):
    from agents.core import route_compaction
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setattr(Agent, "_load_soul", lambda self: setattr(self, "soul", {"content": "STATIC PERSONA"}))
    monkeypatch.setattr(Agent, "_load_identity", lambda self: setattr(self, "identity", {"content": "STATIC IDENTITY"}))
    agent = Agent("jarvis", {"name": "Jarvis"})
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "synthetic-session"
    orch.agents = {"jarvis": agent}
    orch.llm_router = SimpleNamespace()
    orch.checkpoints = SimpleNamespace(load=lambda aid, sid: None)
    orch.get_setting = lambda key, default=None: default
    orch._history_for_prompt = lambda *args, **kwargs: _empty_text()
    orch.memory = SimpleNamespace(get_history=lambda *args: _empty_rows())
    orch._build_agent_turn_text = lambda aid, text, **kwargs: _turn_text(text)
    orch._build_agent_prompt = lambda selected, text, context: selected.build_prompt(text, context)
    orch._agent_gen_params = lambda selected, route: (64, 0)

    async def capture_plan(history, router, build, stage, parameters, session):
        return route_compaction.SharedPlan(history, {}, await build(history))

    monkeypatch.setattr(route_compaction, "plan_shared", capture_plan)
    plain = await orch._shared_route_plan(["jarvis"], "Question", {}, "", "", "", stream=True)
    hinted = await orch._shared_route_plan(
        ["jarvis"], "Question", {"_reply_language": "English"}, "", "", "", stream=True)
    plain_prompt, plain_overhead = plain.prompts["jarvis"][:2]
    hinted_prompt, hinted_overhead = hinted.prompts["jarvis"][:2]
    assert not plain_prompt.endswith("Write this response in English.")
    assert hinted_prompt.endswith("Write this response in English.")
    assert hinted_overhead > plain_overhead


async def _empty_text():
    return ""


async def _empty_rows():
    return []


async def _turn_text(text):
    return text
