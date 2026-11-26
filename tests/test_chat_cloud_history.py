"""Same-chat cloud disclosure through the two HTTP chat entry points, without network I/O."""

import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.agent import Agent
from agents.core.llm import data_handling
from agents.core.llm.gemini import GeminiBackend
from tests.test_session_transcript import client, host, seed  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_cloud_sees_only_this_send_or_confirmed_same_chat(path, host, monkeypatch):  # noqa: F811
    from agents import web
    from agents.core.llm.egress import llm_async_client
    from agents.core.llm.providers import get_profile

    orch, _ = host
    await seed(orch, "chosen", "LOCAL_USER_CANARY")
    await orch.memory.add_turn("chosen", "assistant", "LOCAL_REPLY_CANARY", agent_id="frigga", channel="web")
    await seed(orch, "elsewhere", "UNRELATED_SESSION_CANARY")
    orch.session_id = "chosen"
    orch.session_trust = lambda sid: "clean"
    orch._pending_input_service = lambda: None
    wire = []

    async def transport(request):
        wire.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Synthetic cloud answer"}]}}]})

    backend = GeminiBackend("synthetic", model="gemini-2.5-flash", profile=get_profile("gemini"))
    await backend.client.aclose()
    backend.client = llm_async_client("gemini", transport=httpx.MockTransport(transport))
    model = "gemini-2.5-flash"
    router = SimpleNamespace(select_backend=lambda aid, prompt: (backend, model, "cloud-gemini"))
    router.check_data_handling = lambda b, m, route="", **kw: data_handling.authorize(router, b, m, route, **kw)
    agent = Agent("athena", {}, llm_router=router)
    orch.llm_router = router
    orch.agents = {"athena": agent}
    monkeypatch.setattr(web, "orch", orch)
    http = client(monkeypatch, orch)
    auth = {"X-Admin-Token": "owner-secret"}
    payload = {"message": "CURRENT_MESSAGE", "session_id": "chosen", "agent": "athena"}

    async def handle(message, **kwargs):
        await orch.memory.add_turn("chosen", "user", message, channel="web")
        # The ordinary orchestration assembles much more than the owner typed.
        text = await agent.generate_response(
            backend, model, "LOCAL_USER_CANARY LOCAL_REPLY_CANARY Previous summary: UNRELATED_SESSION_CANARY " + message,
            "Reply in the configured Nerva voice.", 100, 0.0, session_id="chosen",
        )
        await orch.memory.add_turn("chosen", "assistant", text, agent_id="athena", channel="web")
        return text

    orch.handle_input = orch.handle_input_stream = handle
    try:
        attachment = {"name": "current-note.txt", "text": "SUPPLIED_ATTACHMENT_CANARY"}
        response = http.post(path, json={**payload, "attachments": [attachment]}, headers=auth)
        assert response.status_code == 200
        assert len(wire) == 1
        emitted = json.dumps(wire[-1])
        assert "CURRENT_MESSAGE" in emitted
        assert "Reply in the configured Nerva voice." in emitted
        assert "SUPPLIED_ATTACHMENT_CANARY" in emitted
        assert "LOCAL_USER_CANARY" not in emitted and "LOCAL_REPLY_CANARY" not in emitted
        assert "UNRELATED_SESSION_CANARY" not in emitted and "cachedContent" not in wire[-1]

        preview = http.post("/api/chat/cloud-history/preview", json=payload, headers=auth)
        assert preview.status_code == 200
        decision = preview.json()
        assert decision["provider"] == "gemini" and decision["model"] == model
        for changed in ({"model": "changed"}, {"session_id": "elsewhere"}, {"revision": "0" * 64}):
            response = http.post(path, json={**payload, "cloud_history": {**decision, **changed}}, headers=auth)
            assert response.status_code == 409
        response = http.post(path, json={**payload, "message": "changed", "cloud_history": decision}, headers=auth)
        assert response.status_code == 409 and len(wire) == 1
        response = http.post(path, json={**payload, "cloud_history": decision}, headers={"X-User-Token": "guest-secret"})
        assert response.status_code == 403 and len(wire) == 1
        response = http.post(path, json={**payload, "cloud_history": decision}, headers=auth)
        assert response.status_code == 200 and len(wire) == 2
        emitted = json.dumps(wire[-1])
        assert all(text in emitted for text in ("LOCAL_USER_CANARY", "LOCAL_REPLY_CANARY", "CURRENT_MESSAGE"))
        assert "UNRELATED_SESSION_CANARY" not in emitted
        rows = await orch.memory.get_history("chosen")
        assert [row["content"] for row in rows].count("CURRENT_MESSAGE") == 2
        assert any(row["content"] == "LOCAL_REPLY_CANARY" for row in rows)
        source = http.get("/sessions/chosen/transcript?references=true", headers=auth).json()["turns"][0]
        reference = {"session_id": "chosen", "turn": 0, "revision": source["reference_revision"],
                     "excerpt": "LOCAL_USER_CANARY"}
        use_source = {**payload, "message": "Use the selected passage", "history_reference": reference}
        assert http.post(path, json=use_source, headers=auth).status_code == 403
        assert len(wire) == 2
        reference["allow_cloud"] = True
        assert http.post(path, json=use_source, headers=auth).status_code == 200
        assert len(wire) == 3
        excerpt_wire = json.dumps(wire[-1])
        assert "LOCAL_USER_CANARY" in excerpt_wire and "LOCAL_REPLY_CANARY" not in excerpt_wire
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_governed_current_turn_tool_rounds_and_physical_destination():
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.chat_cloud_history import WebTurn, cloud_dispatch, cloud_prompt, web_turn
    from agents.core.commands import Principal
    from agents.core.llm.egress import llm_async_client
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
    from agents.core.tool_rpc import ToolRPCServer

    wire = []
    seen = []

    async def transport(request):
        wire.append(json.loads(request.content))
        part = ({"functionCall": {"name": "echo", "args": {"value": "current argument"}}}
                if len(wire) == 1 else {"text": "the tool succeeded"})
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [part]},
                                                       "finishReason": "STOP"}]})

    def echo(args):
        seen.append(args["value"])
        return {"result": "current tool output"}

    model = "gemini-2.5-flash"
    backend = GeminiBackend("synthetic", model=model)
    await backend.client.aclose()
    backend.client = llm_async_client("gemini", transport=httpx.MockTransport(transport))
    router = SimpleNamespace()
    router.check_data_handling = lambda b, m, route="", **kw: data_handling.authorize(router, b, m, route, **kw)
    agent = Agent("athena", {}, llm_router=router)
    server = ToolRPCServer()
    server.register_tool("echo", echo)
    agent.tool_runtime = AgentToolRuntime(server, enabled=lambda: True)
    principal = bind_turn_principal(Principal(channel="web", admin=True))
    try:
        with web_turn(WebTurn("Please echo.", "chosen", "athena")):
            reply = await agent.generate_response(
                backend, model, "MUST_NOT_SEND old summary plus instruction",
                "Configured system.", 128, 0.0, session_id="chosen",
            )
            assert reply == "the tool succeeded"
            assert seen == ["current argument"] and len(wire) == 2
            assert "tools" in wire[0] and "Configured system." in json.dumps(wire[0])
            assert "current tool output" in json.dumps(wire[1]) and "MUST_NOT_SEND" not in json.dumps(wire)
            _, dispatch = cloud_prompt(router, backend, model, "athena", "chosen")
            origin = "https://generativelanguage.googleapis.com"
            with cloud_dispatch(dispatch):
                for url, body in (
                    ("https://other.invalid/v1/models/gemini-2.5-flash:generateContent", {}),
                    (origin + "/v1/models/other-model:generateContent", {}),
                    (origin + "/v1/models/gemini-2.5-flash:generateContent", {"cachedContent": "old-prefix"}),
                ):
                    with pytest.raises(data_handling.DataHandlingRefused):
                        await data_handling.check_physical_request(httpx.Request("POST", url, json=body))
            assert len(wire) == 2
    finally:
        reset_turn_principal(principal)
        await backend.client.aclose()
