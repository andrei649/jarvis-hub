"""Normal text and streamed ChatGPT-plan wire contracts, entirely on MockTransport."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from agents.core import chatgpt_connection
from agents.core.action_origin import bind_action_origin, reset_action_origin
from agents.core.chat_cloud_history import WebTurn, cloud_dispatch, cloud_prompt, web_turn
from agents.core.commands import Principal
from agents.core.llm.chatgpt_plan import ChatGPTPlanBackend
from agents.core.llm.data_handling import DataHandlingRefused, physical_request_scope
from agents.core.llm.usage_context import text_usage_scope
from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
from agents.core.turn_usage import model_calls_from_snapshot, model_usage_scope, turn_usage_scope

MODEL = "owner-selected"
GENERATION = "synthetic-registration"
URL = "https://api.openai.com/v1/responses"


def stream(events):
    return b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)


def events():
    return [{"type": "response.reasoning_summary_text.delta", "delta": "private thought"},
            {"type": "response.output_text.delta", "delta": "answer"},
            {"type": "response.completed", "response": {
                "model": MODEL, "status": "completed",
                "output": [{"type": "reasoning", "summary": [{"text": "private thought"}]},
                           {"type": "message", "role": "assistant",
                            "content": [{"type": "output_text", "text": "answer"}]}],
                "usage": {"input_tokens": 5, "output_tokens": 2}}}]


@pytest.fixture
def fixture(monkeypatch):
    from agents.core import http_client

    scenario = SimpleNamespace(wire=[], events=events(), active=True, after=None, code=200)
    def access(model, generation):
        if not scenario.active or (model, generation) != (MODEL, GENERATION):
            raise chatgpt_connection.ConnectionError("connection_changed", 409)
        return "synthetic-plan-bearer"
    monkeypatch.setattr(chatgpt_connection, "access_for_chat", access)
    monkeypatch.setattr(chatgpt_connection, "selected_chat_generation",
                        lambda model: GENERATION if model == MODEL else None)
    # The monitor normally resolves host names to classify them. This fixture has no DNS.
    monkeypatch.setattr(http_client, "host_is_local", lambda host: False)
    async def respond(request):
        scenario.wire.append((str(request.url), dict(request.headers), json.loads(request.content)))
        if scenario.after:
            scenario.after()
        return httpx.Response(scenario.code, headers={"content-type": "text/event-stream",
                              "location": "https://different.invalid/"}, content=stream(scenario.events))
    scenario.transport = httpx.MockTransport(respond)
    return scenario


@contextmanager
def governed(backend, *, channel="web", owner=True, origin="generated"):
    principal = bind_turn_principal(Principal(channel=channel, admin=owner))
    bound_origin = bind_action_origin(origin)
    try:
        with web_turn(WebTurn("current message", "selected", "athena")):
            projected, dispatch = cloud_prompt(None, backend, MODEL, "athena", "selected")
            with cloud_dispatch(dispatch), physical_request_scope(lambda: None):
                yield projected
    finally:
        reset_action_origin(bound_origin)
        reset_turn_principal(principal)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_selected_plan_text_and_stream_use_minimal_sse_wire(fixture, streaming):
    backend = ChatGPTPlanBackend(MODEL, GENERATION, transport=fixture.transport)
    tokens, usage = [], []
    try:
        assert backend.supports_tools is False
        assert backend.generation == GENERATION and backend.profile.id == "chatgpt-plan" and backend.endpoint == URL
        async def token(value):
            tokens.append(value)
        with governed(backend) as prompt, text_usage_scope(usage.append):
            if streaming:
                reply = await backend.generate_stream(MODEL, prompt, "native instructions", on_token=token)
            else:
                reply = await backend.generate(MODEL, prompt, "native instructions")
        assert reply == "answer"
        assert "".join(tokens) == ("answer" if streaming else "")
        assert len(usage) == 1 and usage[0].output_tokens == 2
        (url, headers, body), = fixture.wire
        assert url == URL and headers["authorization"] == "Bearer synthetic-plan-bearer"
        assert body == {"model": MODEL, "instructions": "native instructions",
                        "input": [{"role": "user", "content": "current message"}], "store": False, "stream": True}
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["other_model", "missing_model", "incomplete", "tool", "redirect", "closed"])
async def test_refused_terminal_never_retried_or_counted(fixture, problem):
    terminal = fixture.events[-1]["response"]
    if problem == "other_model":
        terminal["model"] = "other"
    elif problem == "missing_model":
        del terminal["model"]
    elif problem == "incomplete":
        terminal["status"] = "incomplete"
    elif problem == "tool":
        terminal["output"].append({"type": "function_call", "name": "run", "arguments": "{}", "call_id": "call"})
    elif problem == "redirect":
        fixture.code = 307
    else:
        fixture.after = lambda: setattr(fixture, "active", False)
    backend = ChatGPTPlanBackend(MODEL, GENERATION, transport=fixture.transport)
    usage = []
    try:
        with governed(backend) as prompt, text_usage_scope(usage.append):
            assert await backend.generate(MODEL, prompt) == backend.error
        assert len(fixture.wire) == 1 and usage == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["nonweb", "unprojected", "guest", "channel", "inbound", "model", "expired", "tool"])
async def test_disallowed_egress_sends_nothing(fixture, problem):
    backend = ChatGPTPlanBackend(MODEL, GENERATION, transport=fixture.transport)
    try:
        if problem == "expired":
            # Runs after the normal client hooks, before the physical transport.
            async def revoke(_request):
                fixture.active = False
            backend.client.event_hooks["request"].append(revoke)
        if problem == "nonweb":
            with pytest.raises(DataHandlingRefused):
                await backend.generate(MODEL, "outside chat")
        elif problem == "unprojected":
            with web_turn(WebTurn("current message", "selected", "athena")), pytest.raises(DataHandlingRefused):
                await backend.generate(MODEL, "unreviewed content")
        else:
            with governed(backend, channel="telegram" if problem == "channel" else "web",
                          owner=problem != "guest", origin="inbound" if problem == "inbound" else "generated") as prompt:
                if problem == "expired":
                    assert await backend.generate(MODEL, prompt) == backend.error
                elif problem == "tool":
                    with pytest.raises(DataHandlingRefused):
                        await backend.generate_tool_turn(MODEL, [], [])
                else:
                    with pytest.raises(DataHandlingRefused):
                        await backend.generate("unselected" if problem == "model" else MODEL, prompt)
        assert fixture.wire == []
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_normal_agent_chat_projects_history_and_receipts_the_physical_model(fixture):
    from agents.core.agent import Agent
    from agents.core.llm.data_handling import authorize

    backend = ChatGPTPlanBackend(MODEL, GENERATION, transport=fixture.transport)
    router = SimpleNamespace()
    router.check_data_handling = lambda b, m: authorize(router, b, m)
    agent = Agent("athena", {}, llm_router=router)
    principal = bind_turn_principal(Principal(channel="web", admin=True))
    try:
        with (web_turn(WebTurn("current message", "selected", "athena")), turn_usage_scope() as usage,
              model_usage_scope(model=MODEL, route="cloud-compatible", agent_id="athena")):
            reply = await agent.generate_response(
                backend, MODEL, "private earlier turn", "Owner instructions.", 128, 0.7, session_id="selected",
            )
            assert reply == "answer"
            assert model_calls_from_snapshot(usage.snapshot()) == [{"provider": "chatgpt-plan", "model": MODEL}]
        assert len(fixture.wire) == 1
        assert "private earlier turn" not in json.dumps(fixture.wire[0][-1])
    finally:
        reset_turn_principal(principal)
        await backend.aclose()
