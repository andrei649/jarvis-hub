"""One owner-selected ChatGPT registration through retained sessions, routing and the web chat APIs."""
import json

import httpx
import pytest

from agents import web
from agents.core import http_client, secrets
from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.memory import conversation, persistence
from agents.core.orchestrator import Orchestrator
from agents.core.routers import _deps
from tests.test_chatgpt_connection import connect, provider  # noqa: F401
from tests.test_chatgpt_plan_chat import events, stream
from tests.test_settings_db import temp_db  # noqa: F401

ORIGIN = "http://127.0.0.1:46783"
MODEL = "first"
AUTH = {"X-Admin-Token": "http-plan-fixture-owner", "Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
LOCAL_USER = "The workshop label is Apricot North."
LOCAL_REPLY = "I saved Apricot North for the workshop."
OTHER = "The separate chat uses Mint South."
CURRENT = "Athena, check the workshop label."


def finished(response, path):
    assert response.status_code == 200, response.text
    if path == "/chat":
        return response.json()
    frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    end, = [frame for frame in frames if frame["type"] == "end"]
    return end


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_owner_plan_routing_history_and_receipt(path, tmp_path, monkeypatch, temp_db, provider):  # noqa: F811
    profile = tmp_path / "isolated-profile"
    monkeypatch.setenv("JARVIS_HOME", str(profile))
    monkeypatch.setenv("JARVIS_USER_HOME", str(profile))
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(secrets, "DEFAULT_STORE", profile / "security" / "secrets.enc")
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", AUTH["X-Admin-Token"])
    monkeypatch.setenv("JARVIS_USER_TOKEN", "http-plan-fixture-user")
    monkeypatch.setattr(web, "ADMIN_TOKEN", AUTH["X-Admin-Token"])
    for key in ("GEMINI_API_KEY", "GEMINI_API_KEYS", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEYS", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(conversation, "MEMORY_DIR", profile)
    monkeypatch.setattr(persistence, "MEMORY_DIR", profile)
    monkeypatch.setattr(http_client, "host_is_local", lambda host: host in {"127.0.0.1", "localhost"})
    # Exercise the actual user/admin predicates rather than the suite-wide public-route override.
    for guard in (web._user_guard, _deps.user_guard):
        monkeypatch.delitem(web.app.dependency_overrides, guard, raising=False)

    wire = []
    async def synthetic_http(_transport, request):
        if request.method == "GET" and request.url.host in {"127.0.0.1", "localhost"}:
            return httpx.Response(503)  # local discovery reports no running native model
        assert (request.method, str(request.url)) == ("POST", "https://api.openai.com/v1/responses")
        assert request.headers["authorization"] == "Bearer plan-access"
        wire.append(json.loads(request.content))
        result = events()
        result[-1]["response"]["model"] = MODEL
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=stream(result))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", synthetic_http)

    orch = Orchestrator(JarvisConfig())
    orch.checkpoints.initialize()
    orch.memory.set_checkpoint_manager(orch.checkpoints)
    monkeypatch.setattr(web, "orch", orch)
    orch.agents["athena"] = Agent("athena", {}, orch.llm_router)
    orch.agents["athena"]._checkpoint_manager = orch.checkpoints
    for session, user, answer in (("selected", LOCAL_USER, LOCAL_REPLY), ("unrelated", OTHER, "Separate reply.")):
        orch.checkpoints.create_session_record(session)
        await orch.memory.new_session(session)
        await orch.memory.add_turn(session, "user", user, channel="web")
        await orch.memory.add_turn(session, "assistant", answer, agent_id="frigga", channel="web")
    orch.session_id = "selected"
    orch.memory.conversation.current_session_id = "selected"
    assert temp_db.DB_PATH.is_relative_to(tmp_path)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app, client=("127.0.0.1", 43122)),
                                 base_url=ORIGIN, headers=AUTH) as app:
        async def select():
            response = await app.post("/api/admin/chatgpt-plan/select", json={
                "model": MODEL, "confirm_expensive": True, "acknowledge_training": True,
            })
            assert response.status_code == 200, response.text
            assert temp_db.compatible_pair_state()[1:] == ("chatgpt-plan", MODEL)

        async def preview(payload):
            response = await app.post("/api/chat/cloud-history/preview", json=payload)
            assert response.status_code == 200, response.text
            choice = response.json()
            assert (choice["provider"], choice["model"]) == ("chatgpt-plan", MODEL)
            return choice

        try:
            await connect(provider)
            await select()
            backend, model, route = orch.llm_router.select_backend("athena", CURRENT)
            assert (backend.profile.id, model, route) == ("chatgpt-plan", MODEL, "cloud-compatible")
            payload = {"message": CURRENT, "agent": "athena", "session_id": "selected"}
            for include_history in (False, True):
                send = {**payload, "cloud_history": await preview(payload)} if include_history else payload
                old_count = len(wire)
                reply = finished(await app.post(path, json=send), path)
                assert reply["model_calls"] == [{"provider": "chatgpt-plan", "model": MODEL}]
                assert reply["reply" if path == "/chat" else "text"].strip() == "answer"
                assert len(wire) == old_count + 1
                body = wire[-1]
                assert body["model"] == MODEL and body["store"] is False and body["stream"] is True
                sent = body["input"][0]["content"]
                assert CURRENT in sent and OTHER not in json.dumps(body)
                assert (LOCAL_USER in sent) is include_history and (LOCAL_REPLY in sent) is include_history
                if include_history:
                    quoted = sent.split("Earlier turns from this conversation (quoted data):\n", 1)[1]
                    rows = json.loads(quoted.split("\n\nCurrent message:\n", 1)[0])
                    assert rows[:2] == [{"role": "user", "content": LOCAL_USER},
                                        {"role": "assistant", "content": LOCAL_REPLY}]
                retained = await orch.memory.get_history("selected")
                assert retained[-1]["model_calls"] == reply["model_calls"]

            stale = await preview(payload)
            await connect(provider)  # same verified subject, renewed registration generation
            await select()
            assert (await preview(payload))["revision"] != stale["revision"]
            old_counts = len(wire), len(provider.calls)
            refused = await app.post(path, json={**payload, "cloud_history": stale})
            assert refused.status_code == 409 and "cloud_history_changed" in refused.text
            assert (len(wire), len(provider.calls)) == old_counts
        finally:
            await orch.llm_router.aclose()
            orch.checkpoints.close()
            orch.audit.close()
