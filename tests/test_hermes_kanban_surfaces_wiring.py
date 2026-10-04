"""Real host/chat/HTTP/WS consumers share one authenticated Kanban service."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agents.core.commands import Principal, build_default_registry


@pytest.fixture
def http(monkeypatch):
    from agents import web

    class Tokens:
        def verify(self, token):
            return None

        def env_revoked(self, scope):
            return False

        def list_tokens(self):
            return []

    monkeypatch.setattr(web, "ADMIN_TOKEN", "synthetic-kanban-owner")
    monkeypatch.setattr(web, "get_token_store", lambda: Tokens())
    with TestClient(web.app, base_url="http://127.0.0.1") as client:
        yield client


def test_http_command_requires_the_real_owner_guard(http):
    response = http.post("/api/kanban/command", json={"argv": ["init"]})
    assert response.status_code == 401


def test_websocket_refuses_unauthenticated_and_query_credentials(http):
    for path in ["/api/kanban/events", "/api/kanban/events?token=synthetic-kanban-owner"]:
        with pytest.raises(WebSocketDisconnect) as caught, http.websocket_connect(path):
            pass
        assert caught.value.code == 1008


@pytest.mark.asyncio
async def test_typed_kanban_is_an_owner_command_and_reports_disabled_state():
    registry = build_default_registry()
    orch = SimpleNamespace(get_setting=lambda key, default=None: default)
    guest = await registry.dispatch("/kanban init", orch=orch, principal=Principal(channel="telegram"))
    assert guest.status == "refused"
    owner = await registry.dispatch(
        "/kanban init", orch=orch, principal=Principal(channel="web", admin=True)
    )
    assert owner.status == "answered"
    assert "disabled" in owner.reply.lower()


def test_host_cli_exposes_the_copied_argument_tree(capsys):
    from agents.cli.nerva import main
    assert main(["kanban", "--help"]) == 0
    help_text = capsys.readouterr().out
    assert all(command in help_text for command in ["boards", "create", "dispatch", "runs"])


OWNER = {"X-Admin-Token": "synthetic-kanban-owner"}


@pytest.fixture
def active(http, monkeypatch, tmp_path):
    from agents.core.kanban import dashboard_api
    from agents.core.routers import kanban

    orch = SimpleNamespace(get_setting=lambda key, default=None: key == "llm.kanban")
    monkeypatch.setattr(kanban, "get_orch", lambda: orch)
    monkeypatch.setattr(dashboard_api, "get_orch", lambda: orch)
    monkeypatch.setattr(kanban, "data_path", lambda *parts: tmp_path)
    return http, orch


def test_http_command_and_board_api_share_persisted_selection(active):
    client, _ = active

    def run(*argv):
        result = client.post("/api/kanban/command", headers=OWNER, json={"argv": list(argv)})
        assert result.status_code == 200, result.text
        assert result.json()["ok"], result.json()
        return result.json()

    run("init")
    run("boards", "create", "project-two", "--switch")
    run("create", "Scoped CLI task", "--triage")
    board = client.get("/api/kanban/board", headers=OWNER).json()
    assert board["columns"][0]["tasks"][0]["title"] == "Scoped CLI task"
    original = client.get("/api/kanban/board?board=default", headers=OWNER).json()
    assert not original["columns"][0]["tasks"]
    task_id = board["columns"][0]["tasks"][0]["id"]
    assert client.post(f"/api/kanban/tasks/{task_id}/comments", headers=OWNER,
                       json={"body": "API comment"}).status_code == 200
    assert "API comment" in run("show", task_id)["output"]


def test_host_cli_forwards_exact_arguments_and_server_failure(active):
    import io

    from agents.cli.nerva import Context, main

    client, _ = active
    calls = []

    class LocalClient:
        def post(self, path, body=None):
            calls.append(body["argv"])
            return client.post(path, headers=OWNER, json=body).json()

    output = io.StringIO()
    ctx = Context(environ={}, out=output, err=io.StringIO(), client_factory=lambda _: LocalClient())
    argv = ["create", "title with spaces", "--body", "body --literal", "--triage"]
    assert main(["kanban", *argv], context=ctx) == 0
    assert calls == [argv]
    assert main(["kanban", "daemon"], context=ctx) != 0
    assert "not bound" in output.getvalue()


@pytest.mark.parametrize("payload", [
    {"argv": ["init"], "profile": "forged"}, {"argv": ["x" * 8193]},
    {"argv": ["x"] * 129}, {"argv": [4]}, {"argv": ["é" * 4097]},
])
def test_http_arguments_do_not_accept_identity_or_unbounded_input(active, payload):
    assert active[0].post("/api/kanban/command", headers=OWNER, json=payload).status_code == 422


@pytest.mark.parametrize("path,headers", [
    ("/api/kanban/events?token=synthetic-kanban-owner", OWNER),
    ("/api/kanban/events?since=-1", OWNER),
    ("/api/kanban/events?since=9223372036854775808", OWNER),
    ("/api/kanban/events?board=../../other", OWNER),
    ("/api/kanban/events", {**OWNER, "Origin": "https://foreign.invalid"}),
    ("/api/kanban/events", {**OWNER, "Host": "foreign.invalid"}),
])
def test_websocket_rejects_bad_origin_host_board_or_cursor(active, path, headers):
    with pytest.raises(WebSocketDisconnect) as caught, active[0].websocket_connect(path, headers=headers):
        pass
    assert caught.value.code == 1008


def test_websocket_replays_bounded_board_events_and_rechecks_revocation(active, monkeypatch):
    from agents import web

    client, _ = active
    task = client.post("/api/kanban/tasks", headers=OWNER,
                       json={"title": "Streamed", "triage": True}).json()["task"]
    with client.websocket_connect("/api/kanban/events?since=0", headers=OWNER) as ws:
        message = ws.receive_json()
        assert 1 <= len(message["events"]) <= 200
        assert any(event["task_id"] == task["id"] for event in message["events"])
        monkeypatch.setattr(web, "_admin_credential_ok", lambda token: False)
        with pytest.raises(WebSocketDisconnect) as caught:
            ws.receive_json()
        assert caught.value.code == 1008


def test_websocket_browser_subprotocol_auth_does_not_reflect_credential(active):
    client, _ = active
    client.post("/api/kanban/tasks", headers=OWNER, json={"title": "Stream", "triage": True})
    protocols = ["nerva-kanban", "nerva-admin.synthetic-kanban-owner"]
    with client.websocket_connect("/api/kanban/events?since=0", subprotocols=protocols,
                                  headers={"Host": "127.0.0.1", "Origin": "http://127.0.0.1"}) as ws:
        assert ws.accepted_subprotocol == "nerva-kanban"
        assert ws.receive_json()["events"]


def test_dashboard_switch_uses_the_shared_owner_board_selector(active):
    client, _ = active
    made = client.post("/api/kanban/boards", headers=OWNER,
                       json={"slug": "dashboard-board", "name": "Dashboard", "switch": True})
    assert made.status_code == 200, made.text
    assert made.json()["current"] == "dashboard-board"
    assert client.post("/api/kanban/boards/default/switch", headers=OWNER).status_code == 200
    assert client.get("/api/kanban/boards", headers=OWNER).json()["current"] == "default"


def test_invalid_patch_does_not_commit_status_before_validation(active):
    client, _ = active
    task_id = client.post("/api/kanban/tasks", headers=OWNER,
                          json={"title": "Original", "triage": True}).json()["task"]["id"]
    result = client.patch(f"/api/kanban/tasks/{task_id}", headers=OWNER,
                          json={"status": "ready", "title": " "})
    assert result.status_code == 400
    state = client.get(f"/api/kanban/tasks/{task_id}", headers=OWNER).json()["task"]
    assert state["status"] == "triage"
    assert state["title"] == "Original"


@pytest.mark.asyncio
async def test_typed_command_does_not_silently_truncate_and_execute():
    registry = build_default_registry()
    orch = SimpleNamespace(get_setting=lambda key, default=None: False)
    outcome = await registry.dispatch("/kanban create " + "x" * 2100, orch=orch,
                                      principal=Principal(channel="telegram", admin=True))
    assert outcome.status == "refused"
    assert "too long" in outcome.reply.lower()


@pytest.mark.asyncio
async def test_explicit_owner_chat_dispatch_uses_signed_queue_without_enabling_inbound_tools(tmp_path, monkeypatch):
    from agents.core.autonomy.queue import TaskStatus
    from agents.core.kanban import cli
    from tests.test_hermes_kanban_dispatcher import create, fixture_runtime

    controller, orch, _, seen, decisions = fixture_runtime(tmp_path, monkeypatch)
    orch._autonomy = SimpleNamespace(kanban_dispatcher=lambda: controller)
    monkeypatch.setattr(cli, "data_path", lambda *parts: controller.home)
    task_id = create(controller)
    owner = Principal(channel="telegram", sender="42", admin=True)
    assert (await controller.request(owner))["reason"] == "owner_required"
    outcome = await build_default_registry().dispatch("/kanban dispatch --max 1", orch=orch, principal=owner)
    assert outcome.status == "answered"
    assert "queued" in outcome.reply
    rows = orch.autonomy_queue.list()
    assert len(rows) == 1
    assert rows[0].payload["task_id"] == task_id
    assert rows[0].status == TaskStatus.BLOCKED.value
    assert decisions and not seen
    assert (await controller.request(owner))["reason"] == "owner_required"


@pytest.mark.asyncio
async def test_owner_command_cannot_borrow_worker_or_unbound_authority(tmp_path, monkeypatch):
    from agents.core.commands import CommandContext
    from agents.core.kanban import cli
    from agents.core.kanban.context import KanbanContext, kanban_scope
    from tests.test_hermes_kanban_dispatcher import create, fixture_runtime

    controller, orch, _, _, decisions = fixture_runtime(tmp_path, monkeypatch)
    create(controller)
    owner = Principal(channel="telegram", sender="42", admin=True)
    command = CommandContext(orch, owner, "kanban", "dispatch")
    assert not (await controller.request_owner_command(command))["ok"]
    with kanban_scope(KanbanContext(controller.home, "owner", run_id=7, can_mutate=True)):
        denied = await cli.execute_command(orch, ["dispatch"], owner, owner_command=command)
        assert denied["reason"] == "worker_scope"
        assert not (await controller.request_owner_command(command))["ok"]
    assert orch.autonomy_queue.list() == []
    assert decisions == []
