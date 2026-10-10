"""Independent HTTP and kernel review of durable foreign-session access."""

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.core.action_origin import bind_action_origin, current_action_origin, reset_action_origin
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.checkpoint import CheckpointManager
from agents.core.commands import Principal
from agents.core.foreign_history import ForeignHistoryRefused, status
from agents.core.kernel import Action, Verdict, authorize
from agents.core.memory import conversation, persistence
from agents.core.memory.manager import MemoryManager
from agents.core.orchestrator import Orchestrator, bind_turn_principal, reset_turn_principal
from agents.core.security.capability import KillSwitch
from agents.core.security.taint import TAINTED_RECALL_ORIGIN

ADMIN = {"X-Admin-Token": "h441-owner-review"}
USER = {"X-User-Token": "h441-user-review"}
SECRET = "PRIVATE IMPORTED TRANSCRIPT 63927"


@pytest.fixture
def context(tmp_path, monkeypatch):
    from agents import web

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(web, "ADMIN_TOKEN", ADMIN["X-Admin-Token"])
    monkeypatch.setattr(web, "USER_TOKEN", USER["X-User-Token"])
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", ADMIN["X-Admin-Token"])
    monkeypatch.setenv("JARVIS_USER_TOKEN", USER["X-User-Token"])
    monkeypatch.setattr(web, "get_token_store", lambda: SimpleNamespace(
        verify=lambda _value: None, env_revoked=lambda _tier: False))
    cp = CheckpointManager(str(tmp_path / "history.db"))
    cp.initialize()
    native = "session_native_review"
    cp.create_session_record(native)
    memory = MemoryManager(graph_backend="memory")
    memory.set_checkpoint_manager(cp)
    orch = SimpleNamespace(checkpoints=cp, memory=memory, session_id=native)
    monkeypatch.setattr(web, "orch", orch)
    # ASGI requests exercise the real app without its lifespan boot replacing the
    # synthetic orchestrator or launching background channels.
    client = TestClient(web.app)
    yield SimpleNamespace(client=client, cp=cp, memory=memory, orch=orch, native=native)
    client.close()
    cp.close()


def _import(context):
    response = context.client.post("/sessions/import", headers=ADMIN, json={
        "source": "claude", "external_id": "synthetic-review", "request_id": str(uuid.uuid4()),
        "turns": [{"role": "user", "content": SECRET,
                   "timestamp": "2026-10-01T00:00:00+00:00"}],
    })
    assert response.status_code == 201, response.text
    sid = response.json()["session_id"]
    assert status(context.cp, sid).kind == "imported"
    return sid


def test_import_and_resolve_are_owner_only_and_guest_cannot_enumerate_title(context):
    client = context.client
    assert client.post("/sessions/import", headers=USER, json={}).status_code in {401, 403}
    sid = _import(context)
    with context.cp._lock, context.cp._conn:
        row = context.cp._conn.execute("SELECT metadata FROM sessions WHERE id=?", (sid,)).fetchone()
        meta = json.loads(row[0])
        meta["title"] = SECRET
        context.cp._conn.execute("UPDATE sessions SET metadata=? WHERE id=?", (json.dumps(meta), sid))
    assert client.post("/sessions/resolve", headers=USER,
                       json={"selector": sid}).status_code in {401, 403}
    resolved = client.post("/sessions/resolve", headers=ADMIN, json={"selector": sid})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["session_id"] == sid
    assert SECRET in json.dumps(resolved.json())
    assert context.orch.session_id == context.native  # resolving never silently swaps the active chat
    guest = client.get("/sessions", headers=USER)
    assert guest.status_code == 200, guest.text
    assert sid not in guest.text and SECRET not in guest.text
    assert context.native in guest.text
    owner = client.get("/sessions", headers=ADMIN)
    assert owner.status_code == 200 and sid in owner.text and SECRET in owner.text


def test_explicit_and_effective_default_chat_stream_and_active_memory_are_private(context):
    sid = _import(context)
    resolved = context.client.post("/sessions/resolve", headers=ADMIN, json={"selector": sid})
    assert resolved.status_code == 200, resolved.text
    context.orch.session_id = sid
    client = context.client
    owner_history = client.get("/memory", headers=ADMIN)
    assert owner_history.status_code == 200 and SECRET in owner_history.text
    for path in ("/chat", "/chat/stream"):
        for payload in ({"message": "hello", "session_id": sid}, {"message": "hello"}):
            denied = client.post(path, headers=USER, json=payload)
            assert denied.status_code == 403, (path, payload, denied.text)
            assert SECRET not in denied.text
    for method, path, headers in (("get", "/memory", {}),
                                  ("post", "/memory/clear", {"X-Confirm": "true"}),
                                  ("post", "/sessions/resume", {}),
                                  ("get", f"/sessions/{sid}/todo", {}),
                                  ("post", f"/sessions/{sid}/pin", {}),
                                  ("post", f"/sessions/{sid}/archive", {})):
        kwargs = {"json": {"session_id": sid}} if path == "/sessions/resume" else {}
        denied = getattr(client, method)(path, headers={**USER, **headers}, **kwargs)
        assert denied.status_code == 403, (method, path, denied.text)
        assert SECRET not in denied.text
    assert context.orch.session_id == sid
    # The same user token still reads ordinary native history: the extra fence is conditional.
    context.orch.session_id = context.native
    native = client.get("/memory", headers=USER)
    assert native.status_code == 200, native.text
    assert native.json()["session"] == context.native


def test_recent_todo_omits_foreign_plans_and_native_stamps_remain_usable(context, monkeypatch):
    from agents.core import todo_tool

    sid = _import(context)
    monkeypatch.setattr(todo_tool, "TODOS", SimpleNamespace(
        recent=lambda _limit: [{"session_id": sid, "items": [SECRET]},
                               {"session_id": context.native, "items": ["safe"]}],
        read=lambda _sid: {"items": [SECRET]}))
    guest = context.client.get("/sessions/todo", headers=USER)
    assert guest.status_code == 200, guest.text
    assert sid not in guest.text and SECRET not in guest.text
    assert context.native in guest.text
    assert sid in context.client.get("/sessions/todo", headers=ADMIN).text
    assert context.client.get(f"/sessions/{sid}/todo", headers=ADMIN).status_code == 200
    assert context.client.post(f"/sessions/{sid}/pin", headers=ADMIN).status_code == 200
    assert context.client.post(f"/sessions/{context.native}/pin", headers=USER).status_code == 200
    assert context.client.post(f"/sessions/{context.native}/archive", headers=USER).status_code == 200
    assert context.client.post(f"/sessions/{context.native}/unarchive", headers=USER).status_code == 200


@pytest.mark.parametrize("corruption", ["marker", "receipt"])
def test_missing_durable_lineage_refuses_access_even_with_owner_token(context, corruption):
    sid = _import(context)
    with context.cp._lock, context.cp._conn:
        if corruption == "marker":
            context.cp._conn.execute("UPDATE sessions SET metadata='{}' WHERE id=?", (sid,))
        else:
            context.cp._conn.execute("DELETE FROM session_imports WHERE session_id=?", (sid,))
    with pytest.raises(ForeignHistoryRefused):
        status(context.cp, sid)
    for path in ("/chat", "/chat/stream"):
        response = context.client.post(path, headers=ADMIN,
                                       json={"message": "hello", "session_id": sid})
        assert response.status_code == 503, (path, response.text)
    assert context.client.get(f"/sessions/{sid}/todo", headers=ADMIN).status_code == 503


@pytest.mark.asyncio
async def test_direct_orchestrator_guard_denies_guest_and_escalates_owner_action(context, tmp_path):
    sid = _import(context)
    orch = Orchestrator.__new__(Orchestrator)
    orch.checkpoints = context.cp
    origin = bind_action_origin("generated")
    try:
        guest = bind_turn_principal(Principal(channel="web", admin=False))
        try:
            with pytest.raises(ForeignHistoryRefused) as denied:
                await orch._guard_foreign_turn(sid)
            assert denied.value.status == 403
            assert current_action_origin() == "generated"
        finally:
            reset_turn_principal(guest)
        owner = bind_turn_principal(Principal(channel="web", admin=True))
        try:
            await orch._guard_foreign_turn(sid)
            assert current_action_origin() == TAINTED_RECALL_ORIGIN
            decision = authorize(Action(kind="kg.write", payload={"risk_tier": 1},
                                        origin=current_action_origin()),
                                 kill_switch=KillSwitch(tmp_path / "kill.json"),
                                 policy=AutonomyPolicy())
            assert decision.verdict is Verdict.QUEUE and decision.card is not None
        finally:
            reset_turn_principal(owner)
    finally:
        reset_action_origin(origin)
