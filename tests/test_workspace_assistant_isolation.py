"""Isolation of the assistant (spec §6 "Authorization", DoD 2).

A conversation belongs to exactly one person: nobody else reads it, renames it,
deletes it, posts into it or rates its answers — not a colleague in the same
department, not a member of another, not an admin — and every such attempt gets the
same ``404`` as an id that does not exist. Chat happens only in departments the user
may use, and retrieval only ever receives the conversation's department.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.core.routers import workspace_chat
from agents.core.workspace import db as workspace_db
from agents.core.workspace import retrieval
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    authed,
    db,
    login,
    seed_company,
    ws,
)
from tests.test_workspace_assistant_helpers import (
    ask,
    ask_stream,
    chat_client,
    new_conversation,
    parse_sse,
    seed_doc,
)

SECRET_B = "Salariul directorului de resurse umane este confidențial: 42.000 lei pe lună."
MISSING = 999_999

#: Every route of the chat router → how a stranger probes someone else's resource with it.
PROBES = {
    ("GET", "/api/workspace/conversations"): None,  # lists: see the list tests
    ("POST", "/api/workspace/conversations"): None,  # foreign departments: see below
    ("GET", "/api/workspace/conversations/{conversation_id}"): ("GET", "conversation", ""),
    ("PATCH", "/api/workspace/conversations/{conversation_id}"):
        ("PATCH", "conversation", {"title": "Preluată"}),
    ("DELETE", "/api/workspace/conversations/{conversation_id}"): ("DELETE", "conversation", ""),
    ("POST", "/api/workspace/conversations/{conversation_id}/messages"):
        ("POST", "messages", {"content": "Ce scrie aici?"}),
    ("POST", "/api/workspace/messages/{message_id}/feedback"):
        ("POST", "feedback", {"value": -1, "note": "rău"}),
    ("GET", "/api/workspace/model"): None,  # no resource: the org's model posture
    ("POST", "/api/workspace/admin/model/test"): None,  # admins only: see the API suite
}
RESOURCE_PROBES = [probe for probe in PROBES.values() if probe is not None]


@pytest.fixture
def cast(ws):
    conn = db()
    company = seed_company(conn)
    seed_doc(conn, department_id=company.dept_b, title="Salarii HR", text=SECRET_B)
    clients = {}
    for key in ("member_a", "approver_a", "member_b", "admin"):
        client = chat_client()
        clients[key] = (client, login(client, getattr(company, key).email))
    owner, owner_csrf = clients["member_a"]
    conversation_id = new_conversation(owner, owner_csrf, company.dept_a, title="A mea")
    answer = ask(owner, owner_csrf, conversation_id, "Prima întrebare").json()
    yield SimpleNamespace(conn=conn, company=company, clients=clients, ws=ws,
                          conversation_id=conversation_id,
                          message_id=answer["assistant_message"]["id"])
    conn.close()


def _url(kind: str, resource_id: int) -> str:
    if kind == "feedback":
        return f"/api/workspace/messages/{resource_id}/feedback"
    suffix = "/messages" if kind == "messages" else ""
    return f"/api/workspace/conversations/{resource_id}{suffix}"


def _probe(cast, prober: str, probe: tuple, resource_id: int):
    method, kind, payload = probe
    client, csrf = cast.clients[prober]
    kwargs = {"headers": authed(client, csrf)}
    if payload:
        kwargs["json"] = payload
    return client.request(method, _url(kind, resource_id), **kwargs)


def test_the_probe_inventory_lists_every_route():
    routes = {(method, route.path) for route in workspace_chat.router.routes
              for method in route.methods}
    assert routes == set(PROBES)


@pytest.mark.parametrize("prober", ["approver_a", "member_b", "admin"])
@pytest.mark.parametrize("probe", RESOURCE_PROBES, ids=lambda p: f"{p[0]}-{p[1]}")
def test_nobody_else_reaches_a_conversation_and_it_looks_like_it_does_not_exist(cast, prober,
                                                                                 probe):
    resource_id = cast.message_id if probe[1] == "feedback" else cast.conversation_id
    calls_before = len(cast.ws.engine.calls)
    foreign = _probe(cast, prober, probe, resource_id)
    missing = _probe(cast, prober, probe, MISSING)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"error": "not_found",
                                                "message": foreign.json()["message"]}
    assert len(cast.ws.engine.calls) == calls_before
    owner, _ = cast.clients["member_a"]
    view = owner.get(f"/api/workspace/conversations/{cast.conversation_id}").json()
    assert view["conversation"]["title"] == "A mea"
    assert len(view["messages"]) == 2
    assert view["messages"][1]["feedback"] is None


def test_a_stranger_cannot_stream_into_a_conversation_either(cast):
    client, csrf = cast.clients["member_b"]
    response, body = ask_stream(client, csrf, cast.conversation_id, "Ce scrie aici?")
    assert (response.status_code, json.loads(body)["error"]) == (404, "not_found")


def test_each_list_holds_only_its_owners_conversations(cast):
    for key in ("approver_a", "member_b", "admin"):
        client, _ = cast.clients[key]
        listed = client.get("/api/workspace/conversations").json()["conversations"]
        assert cast.conversation_id not in [item["id"] for item in listed]
    owner, _ = cast.clients["member_a"]
    listed = owner.get("/api/workspace/conversations").json()["conversations"]
    assert [item["id"] for item in listed] == [cast.conversation_id]


def test_nobody_chats_in_a_department_they_do_not_belong_to(cast):
    client, csrf = cast.clients["member_a"]
    response = client.post("/api/workspace/conversations",
                           json={"department_id": cast.company.dept_b},
                           headers=authed(client, csrf))
    assert (response.status_code, response.json()["error"]) == (404, "not_found")
    response = client.get("/api/workspace/conversations",
                          params={"department_id": cast.company.dept_b})
    assert response.status_code == 404


def test_leaving_a_department_closes_its_conversations(cast):
    with workspace_db.tx(cast.conn):
        cast.conn.execute("DELETE FROM user_departments WHERE user_id = ? AND department_id = ?",
                          (cast.company.member_a.id, cast.company.dept_a))
    client, csrf = cast.clients["member_a"]
    assert client.get(f"/api/workspace/conversations/{cast.conversation_id}").status_code == 404
    assert ask(client, csrf, cast.conversation_id, "Mai pot?").status_code == 404
    assert client.get("/api/workspace/conversations").json()["conversations"] == []


def test_an_archived_department_hides_a_members_conversations(cast):
    with workspace_db.tx(cast.conn):
        cast.conn.execute("UPDATE departments SET archived = 1 WHERE id = ?",
                          (cast.company.dept_a,))
    client, _ = cast.clients["member_a"]
    assert client.get(f"/api/workspace/conversations/{cast.conversation_id}").status_code == 404


def _spy_on_retrieval(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    real = retrieval.search

    def spy(conn, **kwargs):
        calls.append(kwargs)
        return real(conn, **kwargs)

    monkeypatch.setattr(retrieval, "search", spy)
    return calls


def test_retrieval_only_ever_receives_the_conversations_department(cast, monkeypatch):
    calls = _spy_on_retrieval(monkeypatch)
    member, member_csrf = cast.clients["member_a"]
    ask(member, member_csrf, cast.conversation_id, "Care este salariul directorului HR?")
    admin, admin_csrf = cast.clients["admin"]
    hr_conversation = new_conversation(admin, admin_csrf, cast.company.dept_b)
    ask(admin, admin_csrf, hr_conversation, "Care este salariul directorului HR?")
    assert [(c["department_ids"], c["include_company"]) for c in calls] == [
        ([cast.company.dept_a], True), ([cast.company.dept_b], True)]
    for call, user in zip(calls, (cast.company.member_a, cast.company.admin), strict=True):
        assert set(call["department_ids"]) <= set(user.allowed_department_ids(cast.conn))


def test_another_departments_document_never_reaches_the_prompt_or_the_sources(cast):
    seed_doc(cast.conn, department_id=None, visibility="company", title="Grila de salarizare",
             text="Salariile se revizuiesc anual pentru fiecare director.")
    client, csrf = cast.clients["member_a"]
    _, body = ask_stream(client, csrf, cast.conversation_id,
                         "Care este salariul directorului de resurse umane?")
    events = parse_sse(body)
    titles = [c["title"] for c in events[1][1]["citations"]]
    assert titles == ["Grila de salarizare"]
    prompt = cast.ws.engine.calls[-1]["prompt"]
    assert "42.000" not in prompt and "Salarii HR" not in prompt
    assert "42.000" not in body


def test_every_route_needs_a_session(cast):
    anonymous = chat_client()
    for (method, path), _ in PROBES.items():
        url = path.format(conversation_id=cast.conversation_id, message_id=cast.message_id)
        response = anonymous.request(method, url, json={})
        assert (response.status_code, response.json()["error"]) == (401, "auth_required"), path


def test_a_disabled_workspace_answers_nothing(cast, monkeypatch):
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    client, csrf = cast.clients["member_a"]
    for (method, path), _ in PROBES.items():
        url = path.format(conversation_id=cast.conversation_id, message_id=cast.message_id)
        response = client.request(method, url, json={}, headers=authed(client, csrf))
        assert (response.status_code, response.json()["error"]) == (404, "workspace_disabled")
