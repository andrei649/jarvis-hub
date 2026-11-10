"""H226 / H316 — `nerva chat` answers the turn's questions mid-turn, from the terminal.

End to end where it matters: the CLI's own `main` (in a thread, as a terminal user runs
it) talks to the real FastAPI app through a bridge client, the real `/chat` route binds
the real pending-input runtime, and the model turn calls the real clarify and
request_secret tools. Pinned from the owner's side:

* a clarify question is shown on the terminal while the turn waits, and the typed answer
  reaches the SAME turn — fenced as untrusted data, with the turn's taint raised;
* a missing secret is read without echo, goes only to the secret broker route, and never
  appears on the terminal, in the conversation, in the answer route or in a log;
* a non-owner credential is never asked for a secret and cannot store one, cannot answer
  another credential's question, and cannot decide an approval;
* approval cards the turn queued are decided through the admin decision route;
* a script (piped stdin) or `--no-prompts` is never asked anything;
* both tools register only while the clarify preview setting is on (H316), and neither
  can be reached by a delegated child or a job.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from agents import web
from agents.cli.client import HubError
from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, main
from tests.test_ntfy_inbound import until
from tests.test_pending_input_web import stream_host

SECRET_VALUE = "sk-h226-synthetic-VALUE-0042"


class _Tty(io.StringIO):
    """A terminal's stdin: what the user types, line by line."""

    def isatty(self):
        return True


class _Bridge:
    """A synchronous hub client (what the CLI holds) over the real ASGI app.

    Each call is scheduled on the test's event loop, so the CLI runs in a thread exactly
    as it does against a live hub. Every request body is recorded for the leak checks."""

    def __init__(self, loop, client, headers=None):
        self.loop, self.client, self.headers = loop, client, dict(headers or {})
        self.base_url = "http://127.0.0.1:8080"
        self.calls = []

    def request(self, method, path, body=None, *, timeout=None):
        self.calls.append((method, path, body))
        future = asyncio.run_coroutine_threadsafe(
            self.client.request(method, path, json=body, headers=self.headers), self.loop)
        response = future.result(timeout=30)
        if response.status_code >= 400:
            try:
                detail = response.json()
                reason = detail.get("error") or detail.get("detail") or detail.get("status") or ""
            except ValueError:
                reason = ""
            raise HubError(response.status_code, str(reason))
        return response.json() if response.content else None

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None, *, timeout=None):
        return self.request("POST", path, body if body is not None else {}, timeout=timeout)


async def _run_cli(argv, bridge, typed="", secret=None):
    out, err = io.StringIO(), io.StringIO()
    asked = []

    def reader(prompt):
        asked.append(prompt)
        return secret if secret is not None else ""

    ctx = Context(environ={}, out=out, err=err, inp=_Tty(typed),
                  client_factory=lambda env: bridge, secret_reader=reader)
    code = await asyncio.to_thread(main, argv, context=ctx)
    return code, out.getvalue(), err.getvalue(), asked


class _Backend:
    """A model that asks one tool question, then answers."""

    supports_tools = True

    def __init__(self, name, args):
        self.script = [(name, args)]
        self.calls = []

    async def generate_tool_turn(self, **kwargs):
        from agents.core.llm.tool_protocol import ToolCall, ToolTurn

        self.calls.append([dict(m) for m in kwargs["messages"]])
        if self.script:
            name, args = self.script.pop(0)
            return ToolTurn(tool_calls=(ToolCall(id="call-1", name=name, raw_arguments=json.dumps(args),
                                                 arguments=args),), finish_reason="tool_calls")
        return ToolTurn(content="Finished", finish_reason="stop")


def _model_turn(cap, name, args, seen):
    """orch.handle_input: one real agent tool loop over the hub's own ToolRPC server."""
    from agents.core.action_origin import (
        bind_action_origin,
        current_action_origin,
        reset_action_origin,
    )
    from agents.core.agent_runtime import AgentToolRuntime

    async def model(*_args, **_kwargs):
        backend = _Backend(name, args)
        runtime = AgentToolRuntime(cap["server"], enabled=lambda: True, max_iterations=lambda: 4)
        token = bind_action_origin("generated")
        try:
            reply = await runtime.run(agent_id="nerva", backend=backend, model="m", prompt="p",
                                      system="s", max_tokens=64, temperature=0.1)
            seen["origin"] = current_action_origin()
        finally:
            reset_action_origin(token)
        seen["tool_messages"] = [m["content"] for m in backend.calls[-1] if m.get("role") == "tool"]
        return reply

    return model


def _declare_skill_keys(orch, names=("WEATHER_API_KEY", "MISSING_KEY", "X_KEY", "Y_KEY", "Z_KEY")):
    """An installed, owner-vouched skill that declares these keys as required."""
    skill = SimpleNamespace(owner_vouched=True, required_env=list(names))
    orch.skills = SimpleNamespace(skills={"weather": skill})


async def _host(tmp_path, monkeypatch, **kwargs):
    orch, cap, _answers, stream = await stream_host(tmp_path, monkeypatch, **kwargs)
    return orch, cap, stream


# ── clarify, mid-turn ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("typed,expected", [("2\n", "Remote"), ("Use the staging box\n", "Use the staging box")])
async def test_cli_answers_clarify_mid_turn_and_answer_is_untrusted(tmp_path, monkeypatch, typed, expected):
    from agents.core.security.taint import TAINTED_RECALL_ORIGIN

    orch, cap, stream = await _host(tmp_path, monkeypatch)
    seen = {}
    orch.handle_input = _model_turn(cap, "clarify", {"question": "Which workspace?",
                                                    "choices": ["Local", "Remote"]}, seen)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            bridge = _Bridge(asyncio.get_running_loop(), client)
            code, out, err, _ = await _run_cli(["chat", "set up the build"], bridge, typed)
        assert code == EXIT_OK, err
        assert out.strip() == "Finished"
        assert "  │ Which workspace?" in err and "1. Local (Recommended)" in err and "2. Remote" in err
        (content,) = seen["tool_messages"]
        # The same turn read the answer, fenced as data …
        assert content.startswith("<<UNTRUSTED source=clarify>>")
        assert f'"user_response": "{expected}"' in content
        # … and the owner's typed answer raised the turn's taint, as a HUD answer does.
        assert seen["origin"] == TAINTED_RECALL_ORIGIN
        answers = [c for c in bridge.calls if c[1].startswith("/chat/pending/") and c[0] == "POST"]
        assert len(answers) == 1
        assert answers[0][2] == ({"answer": "2"} if typed == "2\n" else {"answer": expected, "other": True})
        assert not orch._pending_input_service().inputs._active
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_cli_answers_a_batch_one_locked_question_at_a_time(tmp_path, monkeypatch):
    orch, cap, stream = await _host(tmp_path, monkeypatch)
    seen = {}
    orch.handle_input = _model_turn(cap, "clarify", {"questions": [
        {"question": "Which region?", "choices": ["EU", "US"]},
        {"question": "Which services?", "choices": ["db", "web", "cache"], "multi_select": True},
        {"question": "Anything else?"}]}, seen)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            bridge = _Bridge(asyncio.get_running_loop(), client)
            code, out, err, _ = await _run_cli(["chat", "deploy"], bridge, "2\n1,3\nno\n")
        assert code == EXIT_OK, err
        assert err.index("Which region?") < err.index("Which services?") < err.index("Anything else?")
        payload = seen["tool_messages"][0]
        envelope = json.loads(payload.split("\n", 2)[2].rsplit("\n", 1)[0])
        responses = [r["user_response"] for r in envelope["result"]["responses"]]
        assert responses == ["US", ["db", "cache"], "no"]
        # Each question had its own id and was answered exactly once.
        posted = [p for m, p, _b in bridge.calls if m == "POST" and p.startswith("/chat/pending/")]
        assert len(posted) == len(set(posted)) == 3
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_cli_cancel_declines_and_turn_continues(tmp_path, monkeypatch):
    orch, cap, stream = await _host(tmp_path, monkeypatch)
    seen = {}
    orch.handle_input = _model_turn(cap, "clarify", {"question": "Which?", "choices": ["A", "B"]}, seen)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            code, out, err, _ = await _run_cli(["chat", "go"], _Bridge(asyncio.get_running_loop(), client),
                                               "/cancel\n")
        assert code == EXIT_OK and out.strip() == "Finished"
        assert "declined" in err
        assert "clarify_cancelled_or_timed_out" in seen["tool_messages"][0]
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_another_credential_cannot_see_or_answer_the_turns_question(tmp_path, monkeypatch):
    from agents.core.security.token_store import TokenStore

    store = TokenStore(str(tmp_path / "tokens.db"))
    owner, stranger = store.issue("user"), store.issue("user")
    orch, cap, stream = await _host(tmp_path, monkeypatch, store=store)
    results = []

    async def model(*_args, **_kwargs):
        results.append(await cap["server"].handle({"tool": "clarify", "args": {"question": "Private?"}}))
        return "Finished"

    orch.handle_input = model
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            turn = asyncio.create_task(client.post("/chat", json={"message": "ask"},
                                                   headers={"x-user-token": owner}))
            await until(lambda: orch._pending_input_service()._offered)
            prompt_id = next(iter(orch._pending_input_service()._offered))
            # The stranger's terminal session: its poll lists nothing, its answer is refused.
            bridge = _Bridge(asyncio.get_running_loop(), client, {"x-user-token": stranger})
            from agents.cli.chat_prompts import _pending

            assert await asyncio.to_thread(_pending, bridge, None) == []
            with pytest.raises(HubError) as refused:
                await asyncio.to_thread(bridge.post, f"/chat/pending/{prompt_id}/answer", {"answer": "x"})
            assert refused.value.status == 404
            assert not turn.done()
            owner_bridge = _Bridge(asyncio.get_running_loop(), client, {"x-user-token": owner})
            listed = await asyncio.to_thread(_pending, owner_bridge, None)
            assert [q["id"] for q in listed] == [prompt_id] and listed[0]["kind"] == "clarify"
            await asyncio.to_thread(owner_bridge.post, f"/chat/pending/{prompt_id}/answer", {"answer": "mine"})
            await asyncio.wait_for(turn, 5)
        assert results[0]["result"]["user_response"] == "mine"
    finally:
        await stream.aclose()
        orch._pending_input_service().close()
        store._conn.close()


# ── secret entry, mid-turn ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cli_secret_goes_only_to_the_broker_and_is_never_echoed(tmp_path, monkeypatch, caplog):
    from agents.core.security.secret_broker import SecretBroker

    caplog.set_level(logging.DEBUG)
    orch, cap, stream = await _host(tmp_path, monkeypatch)
    orch.secret_broker = SecretBroker()
    _declare_skill_keys(orch)
    seen = {}
    orch.handle_input = _model_turn(cap, "request_secret", {
        "name": "WEATHER_API_KEY", "reason": "The weather plugin has no key."}, seen)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            bridge = _Bridge(asyncio.get_running_loop(), client)
            code, out, err, asked = await _run_cli(["chat", "weather?"], bridge, secret=SECRET_VALUE)
        assert code == EXIT_OK, err
        assert asked == ["WEATHER_API_KEY: "]
        assert orch.secret_broker.has("WEATHER_API_KEY")
        assert "! Nerva needs the key WEATHER_API_KEY" in err and "stored WEATHER_API_KEY" in err
        # The value went to the broker route and nowhere else.
        carrying = [c for c in bridge.calls if SECRET_VALUE in json.dumps(c[2])]
        assert [(m, p) for m, p, _ in carrying] == [("POST", "/api/secrets/broker")]
        answer = [c for c in bridge.calls if c[1].startswith("/chat/pending/") and c[0] == "POST"]
        assert answer[0][2] == {"answer": "stored"}
        # Not on the terminal, not in the turn, not in a log.
        assert SECRET_VALUE not in out and SECRET_VALUE not in err
        assert all(SECRET_VALUE not in m for m in seen["tool_messages"])
        assert '"reference": "{{secret:WEATHER_API_KEY}}"' in seen["tool_messages"][0]
        assert SECRET_VALUE not in caplog.text
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_secret_declined_stores_nothing(tmp_path, monkeypatch):
    from agents.core.security.secret_broker import SecretBroker

    orch, cap, stream = await _host(tmp_path, monkeypatch)
    orch.secret_broker = SecretBroker()
    _declare_skill_keys(orch)
    seen = {}
    orch.handle_input = _model_turn(cap, "request_secret", {"name": "MISSING_KEY"}, seen)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            bridge = _Bridge(asyncio.get_running_loop(), client)
            code, out, err, _ = await _run_cli(["chat", "go"], bridge, secret="")
        assert code == EXIT_OK and "declined; nothing was stored" in err
        assert not orch.secret_broker.has("MISSING_KEY")
        assert not any(p == "/api/secrets/broker" for _, p, _b in bridge.calls)
        assert "secret_not_provided" in seen["tool_messages"][0]
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_non_owner_turn_is_never_asked_for_a_secret(tmp_path, monkeypatch):
    from agents.core.security.secret_broker import SecretBroker
    from agents.core.security.token_store import TokenStore

    store = TokenStore(str(tmp_path / "tokens.db"))
    user = store.issue("user")
    store.issue("admin")  # the box has an owner credential, and this terminal does not hold it
    orch, cap, stream = await _host(tmp_path, monkeypatch, store=store)
    orch.secret_broker = SecretBroker()
    _declare_skill_keys(orch)
    results = []

    async def model(*_args, **_kwargs):
        results.append(await cap["server"].handle({"tool": "request_secret", "args": {"name": "X_KEY"}}))
        return "Finished"

    orch.handle_input = model
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            bridge = _Bridge(asyncio.get_running_loop(), client, {"x-user-token": user})
            code, _out, err, asked = await _run_cli(["chat", "go"], bridge, secret=SECRET_VALUE)
            assert code == EXIT_OK
            # The broker route itself refuses a non-owner credential.
            with pytest.raises(HubError) as refused:
                await asyncio.to_thread(bridge.post, "/api/secrets/broker", {"name": "X_KEY", "value": "v"})
            assert refused.value.status in (401, 403)
        assert asked == [] and "Nerva needs the key" not in err
        assert results[0]["result"] == {"ok": False, "reason": "secret_prompt_unavailable_here"}
        assert not orch.secret_broker.has("X_KEY")
    finally:
        await stream.aclose()
        orch._pending_input_service().close()
        store._conn.close()


@pytest.mark.asyncio
async def test_secret_prompt_answer_requires_owner_and_a_stored_value(tmp_path, monkeypatch):
    from agents.core.routers.chat_pending import http_actor
    from agents.core.security.secret_broker import SecretBroker
    from tests.test_pending_input_web import request

    orch, cap, stream = await _host(tmp_path, monkeypatch)
    orch.secret_broker = SecretBroker()
    _declare_skill_keys(orch)
    results = []

    async def model(*_args, **_kwargs):
        results.append(await cap["server"].handle({"tool": "request_secret", "args": {"name": "Y_KEY"}}))
        return "Finished"

    orch.handle_input = model
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            turn = asyncio.create_task(client.post("/chat", json={"message": "ask"}))
            await until(lambda: orch._pending_input_service()._offered)
            listed = (await client.get("/chat/pending")).json()["questions"]
            assert listed[0]["kind"] == "secret" and listed[0]["name"] == "Y_KEY"
            assert "value" not in listed[0]
            prompt_id = listed[0]["id"]
            runtime = orch._pending_input_service()
            actor = http_actor(request())
            # Same actor, but not the owner at answer time: refused.
            assert runtime.answer_http(prompt_id, actor, "stored", owner=False) == "unavailable"
            # Claiming "stored" before the broker holds it: refused, prompt still waiting.
            path = f"/chat/pending/{prompt_id}/answer"
            assert (await client.post(path, json={"answer": "stored"})).status_code == 422
            # A value sent to the answer route is never accepted.
            assert (await client.post(path, json={"answer": "sk-not-here"})).status_code == 422
            orch.secret_broker.put("Y_KEY", "v")
            assert (await client.post(path, json={"answer": "stored"})).status_code == 200
            await asyncio.wait_for(turn, 5)
        assert results[0]["result"]["stored"] is True
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_secret_is_never_asked_over_a_chat_channel_or_the_hud_stream(tmp_path):
    from agents.core.channels.pending_input import PendingInputs
    from agents.core.channels.session import SessionSource
    from agents.core.security.secret_broker import SecretBroker
    from tests.test_pending_input_runtime import runtime_host

    orch, _cap, _gw, server, _ready, _pair, _answers = runtime_host(tmp_path)
    orch.secret_broker = SecretBroker()
    _declare_skill_keys(orch)
    runtime = orch._pending_input_service()
    source = SessionSource(channel="telegram", sender="42", thread_id="123", chat_type="private")
    with runtime.bind(source, {"chat_id": 123}):
        result = await server.handle({"tool": "request_secret", "args": {"name": "Z_KEY"}})
    assert result["result"] == {"ok": False, "reason": "secret_prompt_unavailable_here"}

    async def send(_event):
        return True

    with runtime.bind_http("a" * 64, "s1", send, lambda: True, owner=lambda: True):
        result = await server.handle({"tool": "request_secret", "args": {"name": "Z_KEY"}})
    assert result["result"] == {"ok": False, "reason": "secret_prompt_unavailable_here"}
    # Typed channel text never reaches a secret prompt.
    inputs = PendingInputs()
    key = ("telegram", "k", "42")
    prompt = inputs.register_secret(key, "Z_KEY", "why")
    assert inputs.pending(key) is None and inputs.pending(key, "secret") is prompt
    assert inputs.intercept(key, "stored").status == "no_pending"
    assert inputs.resolve(prompt.id, key, "sk-value") is False
    runtime.close()


# ── approvals, from the same terminal ─────────────────────────────────────────

class _FakeHub:
    def __init__(self, routes):
        self.routes, self.calls = dict(routes), []
        self.base_url = "http://127.0.0.1:8080"

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        answer = self.routes.get(f"{method} {path}")
        if answer is None:
            raise HubError(404, "no route")
        if isinstance(answer, Exception):
            raise answer
        return answer(body) if callable(answer) else answer

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body if body is not None else {})


def _cli(argv, hub, typed="", tty=True, secret=None):
    out, err = io.StringIO(), io.StringIO()
    asked = []

    def reader(prompt):
        asked.append(prompt)
        return secret or ""

    ctx = Context(environ={}, out=out, err=err, inp=_Tty(typed) if tty else io.StringIO(typed),
                  client_factory=lambda env: hub, secret_reader=reader)
    return main(argv, context=ctx), out.getvalue(), err.getvalue(), asked


_CARD = {"id": 41, "kind": "terminal.exec", "title": "Remove the build cache", "risk_tier": 3,
         "tier_name": "IRREVERSIBLE", "reversible": False, "payload": {"command": "rm -rf build/"},
         "rollback": {"mode": "none", "description": "Deleted files are gone."}}
_QUEUED = {"reply": "This requires approval.", "pending_approvals": [41], "runtime_stops": []}


def test_cli_decides_the_turns_approval_card_through_the_admin_route():
    hub = _FakeHub({"POST /chat": _QUEUED, "GET /chat/pending": {"questions": []},
                    "GET /autonomy/approvals": {"pending": [_CARD]},
                    "POST /autonomy/tasks/41/decision": {"ok": True, "task": {"status": "approved"}}})
    code, out, err, _ = _cli(["chat", "clean up"], hub, "a\n")
    assert code == EXIT_OK
    assert "approval #41" in err and "command:\n  │ rm -rf build/" in err and "IRREVERSIBLE" in err
    assert "rollback:\n  │ Deleted files are gone." in err
    assert ("POST", "/autonomy/tasks/41/decision", {"action": "accept"}) in hub.calls
    assert "#41 accepted → approved" in err


def test_cli_leaves_the_card_queued_on_enter_and_never_batch_accepts():
    hub = _FakeHub({"POST /chat": _QUEUED, "GET /chat/pending": {"questions": []},
                    "GET /autonomy/approvals": {"pending": [_CARD]}})
    code, _out, err, _ = _cli(["chat", "-z", "clean up"], hub, "\n")
    assert code == EXIT_FAILED
    assert not any("/decision" in path for _m, path, _b in hub.calls)
    assert "#41 stays queued" in err


def test_non_owner_terminal_cannot_decide_an_approval():
    hub = _FakeHub({"POST /chat": _QUEUED, "GET /chat/pending": {"questions": []},
                    "GET /autonomy/approvals": HubError(401, "admin token required")})
    code, _out, err, _ = _cli(["chat", "clean up"], hub, "a\n")
    assert code == EXIT_OK
    assert "approvals need the owner's admin credential; they stay queued" in err
    assert not any("/decision" in path for _m, path, _b in hub.calls)


def test_decision_refused_by_the_hub_stays_queued():
    hub = _FakeHub({"POST /chat": _QUEUED, "GET /chat/pending": {"questions": []},
                    "GET /autonomy/approvals": {"pending": [_CARD]},
                    "POST /autonomy/tasks/41/decision": HubError(403, "admin disabled from network")})
    _code, _out, err, _ = _cli(["chat", "clean up"], hub, "a\n")
    assert "#41 not decided: only the owner can; it stays queued" in err


# ── who is never asked ────────────────────────────────────────────────────────

@pytest.mark.parametrize("argv,tty", [(["chat", "hi"], False), (["chat", "--no-prompts", "hi"], True),
                                      (["chat", "--json", "hi"], True)])
def test_scripts_and_opt_outs_are_never_asked(argv, tty):
    hub = _FakeHub({"POST /chat": _QUEUED})
    _cli(argv, hub, "a\n", tty=tty)
    assert [path for _m, path, _b in hub.calls] == ["/chat"]


def test_secret_is_not_sent_to_a_remote_plain_http_hub():
    calls = {"n": 0}

    def pending(_body):
        calls["n"] += 1
        return {"questions": [{"id": "f" * 32, "kind": "secret", "name": "K_KEY", "question": "q"}]
                if calls["n"] == 1 else []}

    class _SlowHub(_FakeHub):
        def post(self, path, body=None):
            if path == "/chat":
                import time

                time.sleep(1.2)  # the turn is still running while the prompt is answered
            return super().post(path, body)

    hub = _SlowHub({"POST /chat": {"reply": "ok"}, "GET /chat/pending": pending,
                    "POST /chat/pending/" + "f" * 32 + "/answer": {"ok": True}})
    hub.base_url = "http://192.0.2.10:8080"
    code, _out, err, asked = _cli(["chat", "hi"], hub, secret=SECRET_VALUE)
    assert code == EXIT_OK and asked == []
    assert "plain http on another machine" in err
    assert ("POST", "/chat/pending/" + "f" * 32 + "/answer", {"cancel": True}) in hub.calls
    assert not any(p == "/api/secrets/broker" for _m, p, _b in hub.calls)


# ── registration follows the preview setting (H316) ───────────────────────────

@pytest.mark.parametrize("enabled", [True, False])
def test_tools_register_only_while_the_preview_setting_is_on(enabled):
    from agents.core.channels.pending_input_runtime import register_clarify_tool
    from agents.core.tool_rpc import ToolRPCServer

    server = ToolRPCServer()
    orch = SimpleNamespace(get_setting=lambda key, default=None: enabled
                           if key == "channels.pending_inputs_enabled" else default)
    assert register_clarify_tool(server, orch) is enabled
    for name in ("clarify", "request_secret"):
        assert server.allows(name) is enabled
        if enabled:
            assert server.declares_untrusted_output(name) is True


def test_children_and_jobs_cannot_reach_the_secret_prompt():
    from agents.core.subagents import DELEGATE_BLOCKED_CAPABILITIES, blocked_tool_names

    assert "request_secret" in blocked_tool_names(DELEGATE_BLOCKED_CAPABILITIES,
                                                  {"clarify", "request_secret", "echo"})
    from agents.core.channels.pending_input_runtime import register_clarify_tool
    from agents.core.job_toolsets import resolve_job_policy
    from agents.core.tool_rpc import ToolRPCServer

    server = ToolRPCServer()
    register_clarify_tool(server, SimpleNamespace(get_setting=lambda key, default=None: True))
    policy = resolve_job_policy({}, server, {"platform_toolsets": {}, "disabled_toolsets": [],
                                             "allow_agent_scheduling": False})
    assert {"clarify", "request_secret"} <= policy.removed_names
    assert not {"clarify", "request_secret"} & policy.allowed_names


# ── G4 adversarial review: a secret prompt is not a phishing channel ──────────

async def _request_in_turn(cap, args, *, origin="generated"):
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    token = bind_action_origin(origin)
    try:
        return (await cap["server"].handle({"tool": "request_secret", "args": args}))["result"]
    finally:
        reset_action_origin(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["recall:untrusted", "inbound"])
async def test_a_turn_that_read_untrusted_content_cannot_ask_for_a_secret(tmp_path, monkeypatch, origin):
    from agents.core.security.secret_broker import SecretBroker

    orch, cap, stream = await _host(tmp_path, monkeypatch)
    orch.secret_broker = SecretBroker()
    _declare_skill_keys(orch)
    try:
        result = await _request_in_turn(cap, {"name": "WEATHER_API_KEY"}, origin=origin)
        assert result == {"ok": False, "reason": "secret_request_refused_tainted_turn"}
        assert not orch._pending_input_service().inputs._active
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,reason", [
    ("house_confirmation_key", "invalid_secret_args"),   # system names are lower-case/dotted
    ("camera.vault_key", "invalid_secret_args"),
    ("a2a.peer.abc", "invalid_secret_args"),
    ("frigate.token", "invalid_secret_args"),
    ("UNDECLARED_KEY", "secret_name_not_declared"),      # no installed skill asks for it
    ("OPENAI_API_KEY", "secret_name_not_declared"),      # a provider key, even if declared
    ("JARVIS_ADMIN_TOKEN", "secret_name_not_declared"),  # a hub credential, even if declared
])
async def test_only_a_key_a_vouched_skill_declares_can_be_asked_for(tmp_path, monkeypatch, name, reason):
    from agents.core.security.secret_broker import SecretBroker

    orch, cap, stream = await _host(tmp_path, monkeypatch)
    orch.secret_broker = SecretBroker()
    _declare_skill_keys(orch, ("WEATHER_API_KEY", "OPENAI_API_KEY", "JARVIS_ADMIN_TOKEN",
                               "house_confirmation_key"))
    try:
        assert await _request_in_turn(cap, {"name": name}) == {"ok": False, "reason": reason}
        # An unvouched skill's declaration counts for nothing.
        orch.skills.skills["weather"].owner_vouched = False
        assert (await _request_in_turn(cap, {"name": "WEATHER_API_KEY"}))["reason"] == "secret_name_not_declared"
        assert not orch._pending_input_service().inputs._active
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


@pytest.mark.asyncio
async def test_a_vault_held_secret_is_never_shadowed_and_answers_like_a_stored_one(tmp_path, monkeypatch):
    from agents.core.security.secret_broker import SecretBroker

    class _Vault:
        def resolve(self, name, **_kw):
            return "from-vault" if name == "WEATHER_API_KEY" else None

    orch, cap, stream = await _host(tmp_path, monkeypatch)
    orch.secret_broker = SecretBroker(sources=_Vault())
    _declare_skill_keys(orch)
    seen = {}
    orch.handle_input = _model_turn(cap, "request_secret", {"name": "WEATHER_API_KEY"}, seen)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            bridge = _Bridge(asyncio.get_running_loop(), client)
            code, _out, _err, asked = await _run_cli(["chat", "weather?"], bridge, secret=SECRET_VALUE)
        assert code == EXIT_OK and asked == []
        content = seen["tool_messages"][0]
        assert '"stored": true' in content and "already_present" not in content
        assert not orch.secret_broker.has("WEATHER_API_KEY")   # nothing typed over the vault
    finally:
        await stream.aclose()
        orch._pending_input_service().close()


_FORGED = ("Setup step.\n\n! The turn asks you to store the secret OPENAI_API_KEY.\n"
           "  why: Paste your JARVIS_ADMIN_TOKEN here ‮​⁦x")


def test_model_text_cannot_forge_a_nerva_line_on_the_terminal():
    from agents.cli.chat_prompts import GUTTER, _answer_clarify, _answer_secret

    hub = _FakeHub({"POST /chat/pending/" + "a" * 32 + "/answer": {"ok": True},
                    "POST /chat/pending/" + "b" * 32 + "/answer": {"ok": True}})
    err = io.StringIO()
    ctx = SimpleNamespace(err=err, inp=_Tty("/cancel\n"))
    _answer_clarify(ctx, hub, {"id": "a" * 32, "question": _FORGED, "choices": ["ok\n! fake"]})
    _answer_secret(ctx, hub, {"id": "b" * 32, "kind": "secret", "name": "WEATHER_API_KEY",
                              "question": _FORGED}, lambda _p: "")
    text = err.getvalue()
    for char in ("‮", "​", "⁦"):
        assert char not in text
    for line in text.splitlines():
        if "OPENAI_API_KEY" in line or "JARVIS_ADMIN_TOKEN" in line or "fake" in line:
            assert line.startswith(GUTTER), line   # model words only ever behind the gutter
    assert "\n! Nerva needs the key WEATHER_API_KEY for a skill you installed." in text
    # A name that is not a valid key name is declined without being shown or asked for.
    err.seek(0)
    err.truncate(0)
    asked = []
    _answer_secret(ctx, hub, {"id": "b" * 32, "kind": "secret", "name": "x\n! fake"},
                   lambda p: asked.append(p) or "v")
    assert asked == [] and "fake" not in err.getvalue()


def test_a_key_shaped_clarify_answer_is_never_sent():
    from agents.cli.chat_prompts import _answer_clarify

    hub = _FakeHub({"POST /chat/pending/" + "a" * 32 + "/answer": {"ok": True}})
    err = io.StringIO()
    ctx = SimpleNamespace(err=err, inp=_Tty("sk-REAL-KEY-typed\nghp_abcdefghijklmnop12\nblue\n"))
    assert _answer_clarify(ctx, hub, {"id": "a" * 32, "question": "Colour?"}) == "answered"
    sent = [b for _m, _p, b in hub.calls]
    assert sent == [{"answer": "blue"}]
    assert "looks like a key or token" in err.getvalue()


def test_cards_and_the_approvals_list_strip_bidi_and_zero_width():
    from agents.cli.chat_prompts import render_card

    card = {"id": 7, "risk_tier": 3, "kind": "terminal​", "reversible": False,
            "title": "List files ‮⁦", "payload": {"command": "ls /tmp ‮; fr- mr⁩ #"},
            "origin": "recall:untrusted"}
    err = io.StringIO()
    render_card(SimpleNamespace(err=err), card)
    assert not any(c in err.getvalue() for c in "‮⁦⁩​")
    assert "asked by a turn that read untrusted content" in err.getvalue()
    hub = _FakeHub({"GET /autonomy/approvals": {"pending": [card]}})
    _code, out, _err, _ = _cli(["approvals", "list"], hub, tty=False)
    assert not any(c in out for c in "‮⁦⁩​") and "#7" in out


def test_a_card_with_no_command_shows_its_payload():
    from agents.cli.chat_prompts import render_card

    err = io.StringIO()
    render_card(SimpleNamespace(err=err), {"id": 9, "kind": "house.control", "title": "Unlock",
                                           "payload": {"entity": "lock.front_door", "state": "unlocked"}})
    assert "payload:\n  │ " in err.getvalue() and "lock.front_door" in err.getvalue()


def test_oneshot_receipt_names_what_was_decided_here(tmp_path):
    hub = _FakeHub({"POST /chat": _QUEUED, "GET /chat/pending": {"questions": []},
                    "GET /autonomy/approvals": {"pending": [_CARD]},
                    "POST /autonomy/tasks/41/decision": {"ok": True, "task": {"status": "approved"}}})
    receipt = tmp_path / "run.json"
    code, out, err, _ = _cli(["chat", "-z", "--usage-file", str(receipt), "clean up"], hub, "a\n")
    assert code == EXIT_FAILED and out == ""
    assert "decided here: #41 accept" in json.loads(receipt.read_text())["reason"]


def test_a_refused_poll_is_shown_not_waited_on_in_silence():
    class _SlowHub(_FakeHub):
        def post(self, path, body=None):
            if path == "/chat":
                import time

                time.sleep(1.0)
            return super().post(path, body)

    hub = _SlowHub({"POST /chat": {"reply": "ok"}, "GET /chat/pending": HubError(401, "user token required")})
    code, _out, err, _ = _cli(["chat", "hi"], hub)
    assert code == EXIT_OK and "cannot read the turn's questions (HTTP 401)" in err
    assert sum(1 for _m, p, _b in hub.calls if p == "/chat/pending") == 1


@pytest.mark.asyncio
async def test_broker_route_validates_names_and_obeys_managed_mode(tmp_path, monkeypatch):
    from agents.core import managed_scope
    from agents.core.security.secret_broker import SecretBroker

    orch, _cap, stream = await _host(tmp_path, monkeypatch)
    orch.secret_broker = SecretBroker()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),
                                     base_url="http://localhost") as client:
            for body in ({"name": "bad name", "value": "v"}, {"name": "K", "value": 5},
                         {"name": "x" * 129, "value": "v"}):
                assert (await client.post("/api/secrets/broker", json=body)).status_code == 400

            def locked(current=None):
                raise managed_scope.ManagedRefused("managed mode: change it in the system configuration",
                                                   names=["*"], source="/etc/nerva/.managed")

            monkeypatch.setattr(managed_scope, "check_writable", locked)
            refused = await client.post("/api/secrets/broker", json={"name": "WEATHER_API_KEY", "value": "v"})
            assert refused.status_code == 409
            refused = await client.post("/api/secrets/broker", json={"name": "plugin.token", "value": "v"})
            assert refused.status_code == 409
            assert orch.secret_broker.names() == []
    finally:
        await stream.aclose()
        orch._pending_input_service().close()
