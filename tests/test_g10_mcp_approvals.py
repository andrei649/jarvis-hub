"""G10 / H559 — the owner's conversations and approval cards over Nerva's MCP server.

What the owner can do from an authorised MCP client, and what nobody else can:

* list and read the owner's own conversations (never a channel's, an API key's or an
  imported one), read-only;
* list pending approval cards and approve/deny one, through the HUD/CLI decision handler
  (same ``decided_by``, same queue transition, same audit), exactly once;
* a user/guest token, an OAuth token without ``mcp:owner``, a read-only server, a bad,
  unknown or already-answered card id, and approving an irreversible card are refused
  with nothing decided.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.mcp.inbox_tools import (  # noqa: E402
    APPROVAL_RESPOND,
    INBOX_TOOL_NAMES,
    READ_TOOL_NAMES,
    InboxBackend,
    InboxRefusal,
    InboxTools,
    owner_conversation,
    parse_card_id,
)
from agents.core.mcp.server import JarvisMCPServer  # noqa: E402

ADMIN = "g10-admin-token"
USER = "g10-user-token"
OWNER_H = {"X-Admin-Token": ADMIN}
USER_H = {"X-User-Token": USER}


# ── unit: the tool layer over a fake backend ────────────────────────────────

class _Audit:
    def __init__(self):
        self.rows = []

    def log(self, event):
        self.rows.append(event.action_taken)


def _fake(pending, *, writes=True, audit=True):
    calls = []

    async def list_conversations(limit):
        return [{"session_id": "s1"}]

    async def read_conversation(sid, limit):
        return {"session_id": sid, "turns": []}

    async def list_approvals():
        return {"pending": list(pending), "counts": {"total": len(pending)}, "mode": "ask"}

    async def decide(task_id, action, reason):
        calls.append((task_id, action, reason, list(auditor.rows) if auditor else None))
        return 200, {"ok": True, "task": {"id": task_id, "status": "approved"}}

    auditor = _Audit() if audit else None
    tools = InboxTools(InboxBackend(list_conversations, read_conversation, list_approvals, decide),
                       writes_enabled=lambda: writes, auditor=auditor)
    server = JarvisMCPServer(lambda *_: None, {}, inbox_tools=tools)
    return server, calls, auditor


def _text(result):
    return result["content"][0]["text"]


@pytest.mark.parametrize("name", INBOX_TOOL_NAMES)
async def test_every_tool_refuses_a_caller_who_is_not_the_owner(name):
    server, calls, audit = _fake([{"id": 7, "reversible": True}])
    args = {"session_id": "s1"} if name == "conversation_read" else {}
    if name == APPROVAL_RESPOND:
        args = {"card_id": 7, "decision": "approve"}
    result = await server.call_tool(name, args, identity=USER, owner=False)
    assert result["isError"] is True
    assert "owner" in _text(result)
    assert calls == []
    assert audit.rows == [f"mcp {name} (refused-identity)"]


async def test_handle_defaults_to_not_owner():
    server, calls, _ = _fake([{"id": 7, "reversible": True}])
    reply = await server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "approvals_list", "arguments": {}}},
                                identity=ADMIN)
    assert reply["result"]["isError"] is True


async def test_owner_approves_once_after_an_authorization_row():
    server, calls, audit = _fake([{"id": 7, "reversible": True}])
    result = await server.call_tool(APPROVAL_RESPOND, {"card_id": "7", "decision": "approve",
                                                       "reason": "fine"}, owner=True)
    assert result["isError"] is False, result
    assert json.loads(_text(result))["task"]["status"] == "approved"
    task_id, action, reason, rows_before = calls[0]
    assert (task_id, action, reason) == (7, "accept", "fine")
    assert rows_before == ["mcp approval_respond (authorized)"]
    assert audit.rows[-1] == "mcp approval_respond (ok)"


async def test_no_audit_sink_no_answer():
    server, calls, _ = _fake([{"id": 7, "reversible": True}], audit=False)
    result = await server.call_tool(APPROVAL_RESPOND, {"card_id": 7, "decision": "deny"}, owner=True)
    assert result["isError"] is True and "audit" in _text(result)
    assert calls == []


async def test_read_only_server_neither_lists_nor_answers():
    server, calls, audit = _fake([{"id": 7, "reversible": True}], writes=False)
    names = [t["name"] for t in server.list_tools()]
    assert names == list(READ_TOOL_NAMES)
    result = await server.call_tool(APPROVAL_RESPOND, {"card_id": 7, "decision": "approve"},
                                    owner=True)
    assert result["isError"] is True and "read-only" in _text(result)
    assert calls == []
    assert audit.rows == ["mcp approval_respond (refused-read-only)"]


@pytest.mark.parametrize("bad", [True, 0, -3, 1.0, "abc", "07", "7 ", "", None, [7], 10 ** 18])
async def test_card_id_must_be_a_positive_integer(bad):
    server, calls, _ = _fake([{"id": 7, "reversible": True}])
    result = await server.call_tool(APPROVAL_RESPOND, {"card_id": bad, "decision": "approve"},
                                    owner=True)
    assert result["isError"] is True and "invalid card id" in _text(result)
    assert calls == []


def test_card_id_parser_accepts_int_and_decimal_string():
    assert parse_card_id(12) == 12 and parse_card_id("12") == 12
    with pytest.raises(InboxRefusal):
        parse_card_id("1e3")


@pytest.mark.parametrize("args, needle", [
    ({"card_id": 7, "decision": "allow"}, "approve' or 'deny"),
    ({"card_id": 7, "decision": "approve", "reason": "x" * 281}, "280"),
    ({"card_id": 7, "decision": "approve", "payload": {}}, "unknown argument"),
    ({"card_id": 8, "decision": "approve"}, "not pending"),
])
async def test_bad_answers_are_refused(args, needle):
    server, calls, _ = _fake([{"id": 7, "reversible": True}])
    result = await server.call_tool(APPROVAL_RESPOND, args, owner=True)
    assert result["isError"] is True and needle in _text(result)
    assert calls == []


async def test_irreversible_card_can_be_denied_but_not_approved():
    server, calls, audit = _fake([{"id": 9, "reversible": False}])
    refused = await server.call_tool(APPROVAL_RESPOND, {"card_id": 9, "decision": "approve"},
                                     owner=True)
    assert refused["isError"] is True and "irreversible" in _text(refused)
    assert calls == []
    denied = await server.call_tool(APPROVAL_RESPOND, {"card_id": 9, "decision": "deny"}, owner=True)
    assert denied["isError"] is False
    assert calls[0][:2] == (9, "reject")


async def test_inventory_and_status_name_the_owner_tools():
    server, _, _ = _fake([])
    status = server.status()
    assert status["exposed_owner_tools"] == list(INBOX_TOOL_NAMES)
    rows = {r["name"]: r for r in status["tool_inventory"]}
    assert rows[APPROVAL_RESPOND]["direct_route_mutation"] is True
    assert "owner_required" in rows["conversation_read"]["controls"]
    assert all(rows[n]["governance"] == "governed" for n in INBOX_TOOL_NAMES)


# ── unit: whose conversation it is ──────────────────────────────────────────

class _Store:
    _conn = None


def test_owner_conversation_filters_channels_api_keys_and_foreign(monkeypatch):
    from agents.core import foreign_history

    origins = {"imported1": foreign_history.Origin("imported", "claude", "i")}
    monkeypatch.setattr(foreign_history, "status",
                        lambda _cp, sid: origins.get(sid, foreign_history.Origin()))
    orch = SimpleNamespace(checkpoints=_Store(),
                           session_unclean_evidence=lambda sid: sid == "flagged")
    assert owner_conversation(orch, "session_20261110_120000") is True
    for sid in ("ch_telegram_dm_abc", "oai-0123", "imported1", "flagged", "../x", ""):
        assert owner_conversation(orch, sid) is False
    # No evidence check bound → fail closed.
    assert owner_conversation(SimpleNamespace(checkpoints=_Store()), "session_1") is False


def test_hardened_profile_makes_the_server_read_only(monkeypatch):
    from agents import web
    from agents.core.security import hardened

    monkeypatch.setenv("JARVIS_MCP_ROUTE_TOOLS", "1")
    monkeypatch.setenv("JARVIS_MCP_MUTATING_TOOLS", "1")
    assert APPROVAL_RESPOND in web._build_mcp_inbox_tools().names()
    monkeypatch.setattr(hardened, "mutating_mcp_blocked", lambda: True)
    assert APPROVAL_RESPOND not in web._build_mcp_inbox_tools().names()
    monkeypatch.delenv("JARVIS_MCP_ROUTE_TOOLS")
    assert web._build_mcp_inbox_tools() is None


# ── integration: the real hub, over the HTTP MCP transport ───────────────────

@pytest.fixture(scope="module")
def hub():
    import agents.web as web

    mp = pytest.MonkeyPatch()
    mp.setattr(web, "ADMIN_TOKEN", ADMIN)
    mp.setattr(web, "USER_TOKEN", USER)
    mp.setenv("JARVIS_MCP_ROUTE_TOOLS", "1")
    mp.setenv("JARVIS_MCP_MUTATING_TOOLS", "1")
    with TestClient(web.app) as client:
        original = web.orch.get_setting

        def get_setting(key, default=None):
            if key == "mcp.server_enabled":
                return True
            if key == "mcp.oauth_required":
                return False
            return original(key, default)

        mp.setattr(web.orch, "get_setting", get_setting)
        yield client, web
    mp.undo()


def _rpc(client, name, arguments=None, headers=OWNER_H):
    reply = client.post("/api/mcp/server/rpc", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}}})
    assert reply.status_code == 200, reply.text
    return reply.json()["result"]


def _submit(client, kind):
    task = client.post("/autonomy/tasks", headers=OWNER_H,
                       json={"agent": "jarvis", "kind": kind, "title": f"g10 {kind}"}).json()["task"]
    assert task["status"] == "blocked", task
    return task["id"]


def _task(client, task_id):
    import agents.web as web

    return web.orch.autonomy_queue.get(task_id).to_dict()


def _decision_shape(task):
    keep = ("status", "decided_by", "decision", "agent", "kind", "risk_tier", "autonomy_level",
            "origin", "human_decision")
    shape = {k: task.get(k) for k in keep}
    human = dict(shape["human_decision"] or {})
    for volatile in ("id", "first_at", "at"):   # per record, not per path
        human.pop(volatile, None)
    shape["human_decision"] = human
    return shape


def test_tools_are_listed_for_the_owner(hub):
    client, _ = hub
    reply = client.post("/api/mcp/server/rpc", headers=OWNER_H,
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
    names = {t["name"] for t in reply["result"]["tools"]}
    assert set(INBOX_TOOL_NAMES) <= names


def test_deny_over_mcp_is_recorded_as_the_hud_records_it(hub):
    client, _ = hub
    via_mcp, via_hud = _submit(client, "delete_file"), _submit(client, "delete_file")
    listed = json.loads(_text(_rpc(client, "approvals_list")))
    assert via_mcp in {card["id"] for card in listed["pending"]}

    result = _rpc(client, APPROVAL_RESPOND, {"card_id": via_mcp, "decision": "deny",
                                             "reason": "not now"})
    assert result["isError"] is False, result
    hud = client.post(f"/autonomy/tasks/{via_hud}/decision", headers=OWNER_H,
                      json={"action": "reject", "reason": "not now"})
    assert hud.status_code == 200

    mcp_task, hud_task = _task(client, via_mcp), _task(client, via_hud)
    assert mcp_task["status"] == "rejected"
    assert _decision_shape(mcp_task) == _decision_shape(hud_task)

    # Single use: the same card cannot be answered again, by MCP or by anyone.
    replay = _rpc(client, APPROVAL_RESPOND, {"card_id": via_mcp, "decision": "deny"})
    assert replay["isError"] is True and "not pending" in _text(replay)
    unknown = _rpc(client, APPROVAL_RESPOND, {"card_id": 987654321, "decision": "deny"})
    assert unknown["isError"] is True and "not pending" in _text(unknown)
    malformed = _rpc(client, APPROVAL_RESPOND, {"card_id": "1; drop", "decision": "deny"})
    assert malformed["isError"] is True and "invalid card id" in _text(malformed)


def test_owner_approves_a_reversible_card(hub):
    client, _ = hub
    before = client.get("/autonomy/policy", headers=OWNER_H).json().get("global") or "auto"
    assert client.post("/autonomy/mode", headers=OWNER_H, json={"mode": "ask"}).status_code == 200
    try:
        card = _submit(client, "draft_email")
        result = _rpc(client, APPROVAL_RESPOND, {"card_id": card, "decision": "approve"})
        assert result["isError"] is False, result
        task = _task(client, card)
        assert (task["status"], task["decided_by"], task["decision"]) == ("approved", "admin", "accept")
    finally:
        client.post("/autonomy/mode", headers=OWNER_H, json={"mode": before})


def test_irreversible_card_is_not_approved_over_mcp(hub):
    client, _ = hub
    card = _submit(client, "delete_file")
    result = _rpc(client, APPROVAL_RESPOND, {"card_id": card, "decision": "approve"})
    assert result["isError"] is True and "irreversible" in _text(result)
    assert _task(client, card)["status"] == "blocked"


def test_user_token_is_not_the_owner(hub):
    client, _ = hub
    card = _submit(client, "delete_file")
    for name, args in (("approvals_list", {}), ("conversations_list", {}),
                       (APPROVAL_RESPOND, {"card_id": card, "decision": "deny"})):
        result = _rpc(client, name, args, headers=USER_H)
        assert result["isError"] is True and "owner" in _text(result), name
    assert _task(client, card)["status"] == "blocked"


def test_read_only_server_refuses_the_answer(hub, monkeypatch):
    client, _ = hub
    card = _submit(client, "delete_file")
    monkeypatch.delenv("JARVIS_MCP_MUTATING_TOOLS")
    names = {t["name"] for t in client.post(
        "/api/mcp/server/rpc", headers=OWNER_H,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]}
    assert APPROVAL_RESPOND not in names and "approvals_list" in names
    result = _rpc(client, APPROVAL_RESPOND, {"card_id": card, "decision": "deny"})
    assert result["isError"] is True and "read-only" in _text(result)
    assert _task(client, card)["status"] == "blocked"


def test_owner_reads_own_conversations_but_not_a_channels(hub):
    client, web = hub
    orch = web.orch
    own, channel, api = "g10_owner_chat", "ch_telegram_dm_g10guest", "oai-g10guestkey"
    for sid, text in ((own, "owner says hi"), (channel, "guest secret"), (api, "api secret")):
        if orch.checkpoints.session_row(sid) is None:
            orch.checkpoints.create_session_record(sid, "jarvis")
        client.portal.call(orch.memory.add_turn, sid, "user", text)

    listed = json.loads(_text(_rpc(client, "conversations_list", {"limit": 50})))
    ids = {row["session_id"] for row in listed["conversations"]}
    assert own in ids and channel not in ids and api not in ids

    read = json.loads(_text(_rpc(client, "conversation_read", {"session_id": own})))
    assert [t["content"] for t in read["turns"]][-1] == "owner says hi"
    active = orch.memory.conversation.current_session_id
    for sid in (channel, api):
        refused = _rpc(client, "conversation_read", {"session_id": sid})
        assert refused["isError"] is True and "not found" in _text(refused)
    assert orch.memory.conversation.current_session_id == active  # a read never resumes

    bad = _rpc(client, "conversation_read", {"session_id": "../etc/passwd"})
    assert bad["isError"] is True and "invalid session_id" in _text(bad)
    guest = _rpc(client, "conversation_read", {"session_id": own}, headers=USER_H)
    assert guest["isError"] is True and "owner" in _text(guest)


def test_oauth_token_needs_the_owner_scope(hub, monkeypatch):
    client, web = hub
    card = _submit(client, "delete_file")
    current = web.orch.get_setting

    def oauth_on(key, default=None):
        return True if key == "mcp.oauth_required" else current(key, default)

    monkeypatch.setattr(web.orch, "get_setting", oauth_on)
    resource = "http://testserver/api/mcp/server"
    plain = web._get_mcp_rs().issue_token(subject="peer", resource=resource,
                                          scopes=["mcp"], ttl=300)
    owner = web._get_mcp_rs().issue_token(subject="owner-laptop", resource=resource,
                                          scopes=["mcp", "mcp:owner"], ttl=300)
    # An admin header does not make an OAuth caller the owner: only the minted scope does.
    peer = _rpc(client, "approvals_list", headers={"Authorization": f"Bearer {plain}", **OWNER_H})
    assert peer["isError"] is True and "owner" in _text(peer)
    listed = _rpc(client, "approvals_list", headers={"Authorization": f"Bearer {owner}"})
    assert listed["isError"] is False
    answered = _rpc(client, APPROVAL_RESPOND, {"card_id": card, "decision": "deny"},
                    headers={"Authorization": f"Bearer {owner}"})
    assert answered["isError"] is False, answered
    assert _task(client, card)["status"] == "rejected"
