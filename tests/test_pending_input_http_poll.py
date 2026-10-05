"""Concurrent actual nonstream POST, private discovery and exact HTTP answer."""

import asyncio

import httpx
import pytest

from agents import web
from tests.test_ntfy_inbound import until
from tests.test_pending_input_web import stream_host


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [{"answer": "2"}, {"other": True, "answer": "Test dataset"}, {"cancel": True}])
async def test_poll_answers_original_nonstream_model(tmp_path, monkeypatch, answer):
    orch, cap, _answers, unused_stream = await stream_host(tmp_path, monkeypatch)
    results = []

    async def model(*_args, **_kwargs):
        cap["calls"] = cap.get("calls", 0) + 1
        result = await cap["server"].handle({"tool": "clarify", "args": {
            "question": "Choose a workspace", "choices": ["Local", "Remote"]}})
        results.append(result["result"])
        return "Finished"

    orch.handle_input = model
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
        pending = asyncio.create_task(client.post("/chat", json={"message": "ask"}))
        try:
            await until(lambda: orch._pending_input_service()._offered or pending.done())
            response = await client.get("/chat/pending")
            assert response.status_code == 200, "Nonstream HTTP has no pending discovery route"
            assert response.headers["cache-control"] == "no-store"
            question = response.json()["questions"][0]
            assert question["question"] == "Choose a workspace" and not pending.done()
            assert (await client.get("/chat/pending", params={"session_id": "different_session"})).json()["questions"] == []
            reply = await client.post(f"/chat/pending/{question['id']}/answer", json=answer)
            assert reply.status_code == 200
            assert (await asyncio.wait_for(pending, 2)).json()["reply"] == "Finished"
            assert cap["calls"] == 1
            assert (await client.get("/chat/pending")).json()["questions"] == []
            if answer.get("cancel"):
                assert results[0]["reason"] == "clarify_cancelled_or_timed_out"
            else:
                assert results[0]["user_response"] == ("Remote" if answer["answer"] == "2" else answer["answer"])
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await unused_stream.aclose()
            orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_another_managed_token_cannot_discover_unacknowledged_offer(tmp_path, monkeypatch):
    from agents.core.security.token_store import TokenStore

    store = TokenStore(str(tmp_path / "tokens.db"))
    owner, stranger = store.issue("user"), store.issue("user")
    orch, cap, _answers, unused_stream = await stream_host(tmp_path, monkeypatch, store=store)

    async def model(*_args, **_kwargs):
        await cap["server"].handle({"tool": "clarify", "args": {"question": "Private question"}})
        return "Finished"

    orch.handle_input = model
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
        pending = asyncio.create_task(client.post("/chat", json={"message": "ask"}, headers={"x-user-token": owner}))
        try:
            await until(lambda: orch._pending_input_service()._offered or pending.done())
            assert not pending.done(), "Model has no nonstream HTTP clarify binding"
            prompt_id = next(iter(orch._pending_input_service()._offered))
            path = f"/chat/pending/{prompt_id}/answer"
            assert (await client.post(path, json={"answer": "x"}, headers={"x-user-token": owner})).status_code == 404
            assert (await client.get("/chat/pending")).status_code == 401
            hidden = await client.get("/chat/pending", headers={"x-user-token": stranger})
            assert hidden.json()["questions"] == []
            assert not orch._pending_input_service()._delivered
            visible = await client.get("/chat/pending", headers={"x-user-token": owner})
            assert visible.json()["questions"][0]["id"] == prompt_id
            assert (await client.post(path, json={"answer": "x"}, headers={"x-user-token": owner})).status_code == 200
            await pending
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await unused_stream.aclose()
            orch._pending_input_service().close()
            store._conn.close()


@pytest.mark.asyncio
async def test_unpolled_expiry_and_cancelled_request_leave_no_prompt(tmp_path, monkeypatch):
    orch, cap, _answers, unused_stream = await stream_host(tmp_path, monkeypatch, timeout=.02)

    async def model(*_args, **_kwargs):
        return str(await cap["server"].handle({"tool": "clarify", "args": {"question": "Never polled"}}))

    orch.handle_input = model
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
        try:
            response = await asyncio.wait_for(client.post("/chat", json={"message": "ask"}), 2)
            assert response.status_code == 200
            assert not orch._pending_input_service().inputs._active
            assert (await client.get("/chat/pending")).json()["questions"] == []
            orch._runtime_settings["agent.clarify_timeout"] = 3600
            pending = asyncio.create_task(client.post("/chat", json={"message": "ask"}))
            await until(lambda: orch._pending_input_service()._offered or pending.done())
            assert not pending.done()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            assert not orch._pending_input_service().inputs._active
        finally:
            await unused_stream.aclose()
            orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_failed_discovery_send_does_not_acknowledge_delivery(tmp_path, monkeypatch):
    from agents.core.routers.chat_pending import list_pending
    from tests.test_pending_input_web import request

    orch, cap, _answers, unused_stream = await stream_host(tmp_path, monkeypatch)

    async def model(*_args, **_kwargs):
        await cap["server"].handle({"tool": "clarify", "args": {"question": "Read first"}})
        return "Finished"

    orch.handle_input = model
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
        pending = asyncio.create_task(client.post("/chat", json={"message": "ask"}))
        try:
            await until(lambda: orch._pending_input_service()._offered)
            runtime = orch._pending_input_service()
            prompt_id = next(iter(runtime._offered))
            response = await list_pending(request(), session_id=None, offset=0, limit=20)

            async def failed_send(message):
                if message["type"] == "http.response.body":
                    raise OSError("synthetic disconnected discovery")

            with pytest.raises(OSError):
                await response({"type": "http"}, None, failed_send)
            assert not runtime._delivered and not pending.done()
            path = f"/chat/pending/{prompt_id}/answer"
            assert (await client.post(path, json={"answer": "x"})).status_code == 404
            assert (await client.get("/chat/pending")).json()["questions"][0]["id"] == prompt_id
            assert (await client.post(path, json={"answer": "x"})).status_code == 200
            await pending
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await unused_stream.aclose()
            orch._pending_input_service().close()


@pytest.mark.asyncio
@pytest.mark.parametrize("discovered", [False, True])
async def test_revocation_retires_polled_or_unpolled_wait(tmp_path, monkeypatch, discovered):
    from agents.core.security.token_store import TokenStore

    store = TokenStore(str(tmp_path / "tokens.db"))
    owner = store.issue("user")
    orch, cap, _answers, unused_stream = await stream_host(tmp_path, monkeypatch, store=store)
    results = []

    async def model(*_args, **_kwargs):
        results.append(await cap["server"].handle({"tool": "clarify", "args": {"question": "Private"}}))
        return "Finished"

    orch.handle_input = model
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
        pending = asyncio.create_task(client.post("/chat", json={"message": "ask"}, headers={"x-user-token": owner}))
        try:
            await until(lambda: orch._pending_input_service()._offered)
            runtime = orch._pending_input_service()
            if discovered:
                assert (await client.get("/chat/pending", headers={"x-user-token": owner})).json()["questions"]
            store.revoke_all("user")
            assert (await asyncio.wait_for(pending, 2)).json()["reply"] == "Finished"
            assert not runtime.inputs._active and not runtime._offered and not runtime._delivered
            assert results[0]["result"]["ok"] is False
            assert (await client.get("/chat/pending", headers={"x-user-token": owner})).status_code == 401
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await unused_stream.aclose()
            orch._pending_input_service().close()
            store._conn.close()


@pytest.mark.asyncio
async def test_actual_disconnect_event_cancels_owned_nonstream_wait(tmp_path, monkeypatch):
    from starlette.requests import Request

    orch, cap, _answers, unused_stream = await stream_host(tmp_path, monkeypatch)
    disconnected = asyncio.Event()

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def model(*_args, **_kwargs):
        await cap["server"].handle({"tool": "clarify", "args": {"question": "Disconnect now"}})
        return "Finished"

    orch.handle_input = model
    request = Request({"type": "http", "method": "POST", "path": "/chat",
                       "client": ("127.0.0.1", 123), "headers": []}, receive=receive)
    pending = asyncio.create_task(web.chat(web.ChatRequest(message="ask"), request))
    try:
        await until(lambda: orch._pending_input_service()._offered)
        disconnected.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 2)
        runtime = orch._pending_input_service()
        assert not runtime.inputs._active and not runtime._offered
        assert not any(t.get_name() == "chat-pending-disconnect" for t in asyncio.all_tasks())
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await unused_stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_parallel_clarify_rejection_cannot_cancel_original_delivery_ack(tmp_path, monkeypatch):
    orch, cap, _answers, unused_stream = await stream_host(tmp_path, monkeypatch)
    results = []
    rejected = asyncio.Event()

    async def model(*_args, **_kwargs):
        first = asyncio.create_task(cap["server"].handle({"tool": "clarify", "args": {"question": "First"}}))
        await until(lambda: orch._pending_input_service()._offered)
        second = await cap["server"].handle({"tool": "clarify", "args": {"question": "Concurrent"}})
        assert second["result"]["ok"] is False
        rejected.set()
        results.append(await first)
        return "Finished"

    orch.handle_input = model
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://localhost") as client:
        pending = asyncio.create_task(client.post("/chat", json={"message": "ask"}))
        try:
            await asyncio.wait_for(rejected.wait(), 2)
            question = (await client.get("/chat/pending")).json()["questions"][0]
            assert question["question"] == "First"
            answer = await client.post(f"/chat/pending/{question['id']}/answer", json={"answer": "original"})
            assert answer.status_code == 200, "Concurrent rejection cancelled the original response acknowledgement"
            assert (await asyncio.wait_for(pending, 2)).json()["reply"] == "Finished"
            assert results[0]["result"]["user_response"] == "original"
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await unused_stream.aclose()
            orch._pending_input_service().close()
