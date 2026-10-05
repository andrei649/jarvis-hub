"""Actual HUD SSE producer, clarify ToolRPC and guarded HTTP answer path."""

import asyncio
import json

import httpx
import pytest
from starlette.requests import Request

from agents import web
from agents.core.native_human_wait import runtime_human_wait_scope
from tests.test_pending_input_runtime import runtime_host


def request(headers=None):
    return Request({"type": "http", "method": "POST", "path": "/chat/stream",
                    "client": ("127.0.0.1", 123), "headers": [
                        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]})


async def stream_host(tmp_path, monkeypatch, *, choices=None, multi=False, headers=None, store=None, timeout=None):
    orch, cap, _gw, server, _ready, _pair, answers = runtime_host(tmp_path)
    cap["server"] = server
    monkeypatch.setattr(web, "orch", orch)
    from agents.core.routers._deps import user_guard
    monkeypatch.delitem(web.app.dependency_overrides, web._user_guard, raising=False)
    monkeypatch.delitem(web.app.dependency_overrides, user_guard, raising=False)
    if store is None:
        monkeypatch.setattr(web, "_user_credential_required", lambda: False)
        monkeypatch.setattr(web, "_admin_configured", lambda: False)
        monkeypatch.setattr(web, "_admin_credential_ok", lambda _token: False)
    else:
        monkeypatch.setattr(web, "get_token_store", lambda: store)
        monkeypatch.setattr(web, "_env_user_active", lambda: False)
        monkeypatch.setattr(web, "_env_admin_active", lambda: False)
    if timeout is not None:
        orch._runtime_settings["agent.clarify_timeout"] = timeout

    async def model(message, channel, on_token, **kwargs):
        cap["calls"] = cap.get("calls", 0) + 1
        with runtime_human_wait_scope() as credit:
            cap["credit"] = credit
            response = await server.handle({"tool": "clarify", "args": {
                "question": "Choose the synthetic workspace", "choices": choices,
                "multi_select": multi}})
            answers.append(response["result"])
        await on_token("Finished")
        return "Finished"

    orch.handle_input_stream = model
    response = await web.chat_stream(web.ChatRequest(message="ask"), request(headers))
    return orch, cap, answers, response.body_iterator


async def event(stream):
    frame = await asyncio.wait_for(anext(stream), 2)
    if isinstance(frame, bytes):
        frame = frame.decode()
    return json.loads(frame.removeprefix("data: ").strip())


@pytest.mark.asyncio
@pytest.mark.parametrize("value,other,multi,choices", [
    ("2", False, False, ["Local", "Remote"]),
    (["Local", "Remote"], False, True, ["Local", "Remote"]),
    ("Use the test dataset", True, False, ["Local", "Remote"]),
    ("Use the test dataset", False, False, []),
])
async def test_hud_question_answers_same_actual_model_turn(tmp_path, monkeypatch, value, other, multi, choices):
    orch, cap, answers, stream = await stream_host(tmp_path, monkeypatch, choices=choices, multi=multi)
    try:
        assert (await event(stream))["type"] == "start"
        question = await event(stream)
        assert question["type"] == "clarify", "HUD model has no usable pending question"
        assert question["question"] == "Choose the synthetic workspace"
        assert not answers
        # The next generator step acknowledges the yielded question and resumes
        # the runner's delivery wait, while waiting for its model's next token.
        following = asyncio.create_task(event(stream))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
            await asyncio.sleep(0)
            for _ in range(20):
                if orch._pending_input_service()._delivered:
                    break
                await asyncio.sleep(0)
            reply = await client.post(f"/chat/pending/{question['id']}/answer", json={"answer": value, "other": other})
            assert reply.status_code == 200, reply.text
            assert reply.headers["cache-control"] == "no-store"
        assert (await following)["type"] == "token"
        assert (await event(stream))["type"] == "end"
        assert cap["calls"] == 1
        assert answers[0]["user_response"] == ("Remote" if value == "2" else value)
        assert not orch._pending_input_service().inputs._active
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_actual_managed_tokens_cannot_answer_another_actors_question(tmp_path, monkeypatch):
    from agents.core.security.token_store import TokenStore

    store = TokenStore(str(tmp_path / "tokens.db"))
    owner = store.issue("user")
    another = store.issue("user")
    orch, cap, answers, stream = await stream_host(tmp_path, monkeypatch, choices=["Local", "Remote"],
                                                 store=store, headers={"x-user-token": owner})
    try:
        await event(stream)
        question = await event(stream)
        following = asyncio.create_task(event(stream))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
            for _ in range(20):
                if orch._pending_input_service()._delivered:
                    break
                await asyncio.sleep(0)
            path = f"/chat/pending/{question['id']}/answer"
            assert (await client.post(path, json={"answer": "1"})).status_code == 401
            assert (await client.post(path, json={"answer": "1"}, headers={"x-user-token": another})).status_code == 404
            for body in [{"answer": "9"}, {"answer": ""}, {"answer": []},
                         {"cancel": True, "answer": "1"}, {"answer": "1", "actor": "owner"}]:
                assert (await client.post(path, json=body, headers={"x-user-token": owner})).status_code == 422
                assert not answers
            assert (await client.post(path, json={"cancel": True}, headers={"x-user-token": owner})).status_code == 200
            assert (await following)["type"] == "token"
            assert (await event(stream))["type"] == "end"
            assert (await client.post(path, json={"answer": "1"}, headers={"x-user-token": owner})).status_code == 404
        assert cap["calls"] == 1
        assert answers[0]["reason"] == "clarify_cancelled_or_timed_out"
    finally:
        await stream.aclose()
        orch._pending_input_service().close()
        store._conn.close()


@pytest.mark.asyncio
async def test_revocation_stops_wait_credit_and_retires_the_owned_wait(tmp_path, monkeypatch):
    from agents.core.security.token_store import TokenStore

    store = TokenStore(str(tmp_path / "tokens.db"))
    token = store.issue("user")
    orch, cap, answers, stream = await stream_host(tmp_path, monkeypatch, choices=["Local", "Remote"],
                                                 store=store, headers={"x-user-token": token})
    try:
        await event(stream)
        question = await event(stream)
        following = asyncio.create_task(event(stream))
        for _ in range(20):
            if orch._pending_input_service()._delivered:
                break
            await asyncio.sleep(0)
        store.revoke_all("user")
        cap["credit"].seconds()  # Real runtime budget sampling observes auth revocation.
        assert (await following)["type"] == "token"
        assert answers[0]["reason"] == "prompt_binding_lost"
        assert (await event(stream))["type"] == "end"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
            assert (await client.post(f"/chat/pending/{question['id']}/answer", json={"answer": "1"},
                                      headers={"x-user-token": token})).status_code == 401
    finally:
        await stream.aclose()
        orch._pending_input_service().close()
        store._conn.close()


@pytest.mark.asyncio
async def test_expired_hud_question_unblocks_without_answer_or_new_model_turn(tmp_path, monkeypatch):
    orch, cap, answers, stream = await stream_host(tmp_path, monkeypatch, choices=["Local", "Remote"], timeout=.02)
    try:
        await event(stream)
        question = await event(stream)
        assert (await event(stream))["type"] == "token"
        assert (await event(stream))["type"] == "end"
        assert answers[0]["reason"] == "clarify_cancelled_or_timed_out" and cap["calls"] == 1
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
            assert (await client.post(f"/chat/pending/{question['id']}/answer", json={"answer": "1"})).status_code == 404
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_human_credit_starts_only_after_stream_yield_is_acknowledged(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import agents.core.native_human_wait as human_wait

    clock = {"now": 1000.0}
    monkeypatch.setattr(human_wait, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    orch, cap, _answers, stream = await stream_host(tmp_path, monkeypatch, choices=["Local", "Remote"])
    try:
        await event(stream)
        question = await event(stream)
        clock["now"] += 5
        assert cap["credit"].seconds() == 0
        assert not orch._pending_input_service()._delivered
        following = asyncio.create_task(event(stream))
        for _ in range(20):
            if orch._pending_input_service()._delivered:
                break
            await asyncio.sleep(0)
        clock["now"] += 5
        assert cap["credit"].seconds() == 5
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
            assert (await client.post(f"/chat/pending/{question['id']}/answer", json={"answer": "1"})).status_code == 200
        await following
        await event(stream)
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_ordinary_channel_binding_cannot_impersonate_a_live_http_producer(tmp_path, monkeypatch):
    orch, cap, _answers, stream = await stream_host(tmp_path, monkeypatch, choices=["Local", "Remote"])
    following = None
    try:
        await event(stream)
        question = await event(stream)
        following = asyncio.create_task(event(stream))
        runtime = orch._pending_input_service()
        for _ in range(20):
            if runtime._delivered:
                break
            await asyncio.sleep(0)
        original = runtime._delivered[question["id"]]
        # Even knowledge of the server-side source identity does not confer
        # bind_http's private transport/auth capability on ordinary metadata.
        with runtime.bind(original.source, {"client_id": "claimed-owner"}):
            response = await cap["server"].handle({"tool": "clarify", "args": {"question": "Impersonated"}})
        assert response.get("result", {}).get("reason") == "clarify_context_unavailable"
        assert len(runtime.inputs._active) == 1
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
            assert (await client.post(f"/chat/pending/{question['id']}/answer", json={"answer": "1"})).status_code == 200
        await following
        await event(stream)
    finally:
        if following is not None and not following.done():
            following.cancel()
            await asyncio.gather(following, return_exceptions=True)
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_disconnect_retires_prompt_and_cannot_be_answered_later(tmp_path, monkeypatch):
    orch, _cap, answers, stream = await stream_host(tmp_path, monkeypatch, choices=["Local", "Remote"])
    try:
        await event(stream)
        question = await event(stream)
        assert question["type"] == "clarify"
        await stream.aclose()
        assert not orch._pending_input_service().inputs._active
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
            response = await client.post(f"/chat/pending/{question['id']}/answer", json={"answer": "1"})
            assert response.status_code == 404
        assert not answers
    finally:
        await stream.aclose()
        orch._pending_input_service().close()
