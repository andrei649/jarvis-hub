"""V68 session organization through the real HubClient request/credential path."""
from __future__ import annotations

import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from agents.cli.client import HubClient
from agents.cli.nerva import EXIT_AUTH, EXIT_FAILED, EXIT_OK, EXIT_USAGE, Context, main

SID = "session_68-A"
SECRET = "PRIVATE_ORGANIZATION_BODY_68"
ACTIONS = {"pin": ("pinned", True), "unpin": ("pinned", False),
           "archive": ("archived", True), "unarchive": ("archived", False)}


def receipt(action):
    if action == "rename":
        return {"ok": True, "session": SID, "title": "New name", "title_source": "human"}
    field, value = ACTIONS[action]
    return {"ok": True, "session": SID, field: value}


@pytest.fixture
def hub():
    state = SimpleNamespace(payload=None, raw=None, status=200, calls=[], unavailable=False)

    def opener(request, **kwargs):
        state.calls.append(request)
        if state.unavailable:
            raise URLError(SECRET)
        raw = state.raw if state.raw is not None else json.dumps(state.payload).encode()
        if state.status >= 400:
            raise HTTPError(request.full_url, state.status, SECRET, {}, io.BytesIO(raw))
        return io.BytesIO(raw)

    state.factory = lambda env: HubClient.from_env(env, opener=opener)
    return state


def run(hub, *args):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={"NERVA_HUB_URL": "http://127.0.0.1:8765",
                           "JARVIS_ADMIN_TOKEN": "owner-token-68",
                           "JARVIS_USER_TOKEN": "user-token-68"},
                  client_factory=hub.factory, out=out, err=err, inp=io.StringIO())
    code = main(["sessions", *args], context=ctx)
    return code, out.getvalue(), err.getvalue()


def args_for(action, sid=SID):
    return [action, sid, "  New name  "] if action == "rename" else [action, sid]


@pytest.mark.parametrize("action", ["rename", *ACTIONS])
def test_mutations_use_existing_route_once_with_credentials_and_project_receipt(hub, action):
    hub.payload = {**receipt(action), "raw_history": SECRET}
    code, out, err = run(hub, *args_for(action), "--json")
    assert code == EXIT_OK and not err
    assert json.loads(out) == receipt(action)
    assert SECRET not in out
    assert len(hub.calls) == 1
    req = hub.calls[0]
    assert req.method == ("PATCH" if action == "rename" else "POST")
    assert req.full_url == f"http://127.0.0.1:8765/sessions/{SID}/{'title' if action == 'rename' else action}"
    assert json.loads(req.data) == ({"title": "New name"} if action == "rename" else {})
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers["x-admin-token"] == "owner-token-68"
    assert headers["x-user-token"] == "user-token-68"


@pytest.mark.parametrize("action", ["rename", *ACTIONS])
@pytest.mark.parametrize("sid", ["", "../private", "a/b", "a?x=1", "a%2fb", " a", "a\n", "é", "a" * 129])
def test_invalid_ids_do_not_make_any_request(hub, action, sid):
    code, out, _err = run(hub, *args_for(action, sid))
    assert code == EXIT_USAGE and not out
    assert hub.calls == []


@pytest.mark.parametrize("title", ["", " ", "a\nb", "a\rb", "x" * 101, "\u200b"])
def test_invalid_title_does_not_make_request(hub, title):
    code, out, _err = run(hub, "rename", SID, title)
    assert code == EXIT_USAGE and not out
    assert hub.calls == []


@pytest.mark.parametrize("title,normalized", [("x", "x"), ("x" * 100, "x" * 100),
    ("  New   name  ", "New name"), ("Ｎｅｗ　ｎａｍｅ", "New name"), ("名 🌍", "名 🌍")])
def test_title_boundary_and_backend_canonicalization(hub, title, normalized):
    hub.payload = {**receipt("rename"), "title": normalized}
    code, out, err = run(hub, "rename", SID, title, "--json")
    assert code == EXIT_OK and not err
    assert json.loads(out)["title"] == normalized
    assert json.loads(hub.calls[0].data) == {"title": normalized}


@pytest.mark.parametrize("action", ["rename", *ACTIONS])
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 500, 503])
def test_refusal_preserves_exit_code_without_echo_or_retry(hub, action, status):
    hub.status, hub.payload = status, {"error": SECRET, "detail": SECRET, "reason": SECRET}
    code, out, err = run(hub, *args_for(action), "--json")
    assert code == (EXIT_AUTH if status in (401, 403) else EXIT_FAILED)
    assert not out and err and SECRET not in err
    assert len(hub.calls) == 1


@pytest.mark.parametrize("action", ["rename", *ACTIONS])
@pytest.mark.parametrize("failure", ["missing_ok", "false_ok", "integer_ok", "wrong_session",
    "missing_session", "missing_result", "wrong_result", "wrong_type", "not_object", "raw_text"])
def test_malformed_success_is_unconfirmed_and_never_claims_no_change(hub, action, failure):
    body = receipt(action)
    field = "title" if action == "rename" else ACTIONS[action][0]
    if failure == "missing_ok":
        del body["ok"]
    elif failure == "false_ok":
        body["ok"] = False
    elif failure == "integer_ok":
        body["ok"] = 1
    elif failure == "wrong_session":
        body["session"] = "other"
    elif failure == "missing_session":
        del body["session"]
    elif failure == "missing_result":
        del body[field]
    elif failure == "wrong_result":
        body[field] = SECRET if action == "rename" else not body[field]
    elif failure == "wrong_type":
        body[field] = [SECRET] if action == "rename" else int(body[field])
    elif failure == "not_object":
        body = [SECRET]
    elif failure == "raw_text":
        hub.raw = SECRET.encode()
    hub.payload = body
    code, out, err = run(hub, *args_for(action), "--json")
    assert code == EXIT_FAILED and not out and err
    assert SECRET not in err
    assert "unconfirmed" in err.lower() or "may have applied" in err.lower()
    assert "no change" not in err.lower() and "unchanged" not in err.lower()
    assert len(hub.calls) == 1


@pytest.mark.parametrize("source", [None, "model", 1, "HUMAN"])
def test_rename_requires_human_title_source(hub, source):
    hub.payload = {**receipt("rename"), "title_source": source}
    code, out, err = run(hub, *args_for("rename"))
    assert code == EXIT_FAILED and not out and err
    assert len(hub.calls) == 1


@pytest.mark.parametrize("action", ["rename", *ACTIONS])
def test_transport_failure_is_private_single_attempt(hub, action):
    hub.unavailable = True
    code, out, err = run(hub, *args_for(action))
    assert code != EXIT_OK and not out and err
    assert SECRET not in err
    assert len(hub.calls) == 1


@pytest.mark.parametrize("action", ["rename", *ACTIONS])
def test_human_success_is_one_line_and_does_not_dump_private_fields(hub, action):
    hub.payload = {**receipt(action), "metadata": {"secret": SECRET}}
    code, out, err = run(hub, *args_for(action))
    assert code == EXIT_OK and not err
    assert len(out.splitlines()) == 1 and SID in out
    assert SECRET not in out


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("json_output", [False, True])
def test_list_only_changes_query_when_archived_is_explicit(hub, archived, json_output):
    rows = [{"id": SID, "title": "Saved name", "resume_id": SID, "continuations": 2}]
    hub.payload = {"sessions": rows}
    args = (["--archived"] if archived else []) + (["--json"] if json_output else [])
    code, out, err = run(hub, *args)
    assert code == EXIT_OK and not err
    assert len(hub.calls) == 1
    req = hub.calls[0]
    assert req.method == "GET" and req.data is None
    assert req.full_url == "http://127.0.0.1:8765/sessions" + ("?archived=true" if archived else "")
    assert json.loads(out) == rows if json_output else SID in out and "Saved name" in out


@pytest.mark.parametrize("title,status", [("latest", 400), ("@named", 400), (SID, 400), ("Taken", 409)])
def test_reserved_and_taken_titles_are_decided_by_backend(hub, title, status):
    hub.status, hub.payload = status, {"error": SECRET, "reason": "title_reserved" if status == 400 else "title_taken"}
    code, out, err = run(hub, "rename", SID, title)
    assert code == EXIT_FAILED and not out and err
    assert len(hub.calls) == 1 and json.loads(hub.calls[0].data) == {"title": title}
    assert SECRET not in err


def test_parser_and_completion_keep_organization_under_sessions():
    from agents.cli.completion import completion_nodes
    from agents.cli.nerva import build_parser
    parser = build_parser()
    nodes = completion_nodes(parser)
    children = dict(nodes[("sessions",)])
    assert {"rename", *ACTIONS, "transcript", "export", "import", "continue"} <= children.keys()
    assert all(children[name] for name in ("rename", *ACTIONS))
    assert not ({"rename", *ACTIONS} & dict(nodes[()]).keys())
    for action in ("rename", *ACTIONS):
        ns = parser.parse_args(["sessions", *args_for(action), "--json"])
        assert ns.session_action == action and ns.session_id == SID and ns.json
    assert parser.parse_args(["sessions", "--archived", "--json"]).archived is True


def test_process_help_is_available_without_loading_backend():
    import subprocess
    import sys
    proc = subprocess.run([sys.executable, "-m", "agents.cli.nerva", "sessions", "--help"],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0
    assert all(name in proc.stdout for name in ("rename", *ACTIONS, "--archived", "transcript", "export"))


@pytest.mark.parametrize("args", [["pin", SID], ["rename", SID, "New name"],
    ["unpin", SID], ["archive", SID], ["unarchive", SID], ["transcript", SID],
    ["export", SID],
    ["continue", SID, "--request-id", "00000000-0000-4000-8000-000000000068"],
    ["import", "--from", "claude", "fixture.jsonl"]])
def test_archived_flag_is_listing_only_and_never_silently_mutates(hub, args):
    code, out, _err = run(hub, "--archived", *args)
    assert code == EXIT_USAGE and not out
    assert hub.calls == []


@pytest.fixture
def backend(tmp_path, monkeypatch):
    """Actual routes/store behind HubClient; no server or network listener."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agents.core.checkpoint import CheckpointManager
    from agents.core.routers import sessions
    from agents.core.session_import import import_turns
    cp = CheckpointManager(str(tmp_path / "organization.db"))
    cp.initialize()
    cp.create_session_record(SID)
    imported = import_turns(cp, source="claude", external_id="organization-import",
        request_id="00000000-0000-4000-8000-000000000068",
        turns=[{"role": "user", "content": "inert imported text", "timestamp": "2026-11-13T00:00:00Z"}])["session_id"]
    monkeypatch.setattr(sessions, "get_orch", lambda: SimpleNamespace(checkpoints=cp))
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "owner-token-68")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "user-token-68")
    app = FastAPI()
    app.include_router(sessions.router)
    http = TestClient(app, client=("192.0.2.10", 4000))
    state = SimpleNamespace(calls=[], guest=False, cp=cp, imported=imported)

    def opener(request, **kwargs):
        state.calls.append(request)
        response = http.request(request.method, request.full_url,
            headers=dict(request.header_items()), content=request.data)
        if response.status_code >= 400:
            raise HTTPError(request.full_url, response.status_code, "refused", {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)

    state.factory = lambda env: HubClient.from_env(
        {**env, "JARVIS_ADMIN_TOKEN": ""} if state.guest else env, opener=opener)
    yield state
    http.close()
    cp.close()


@pytest.mark.parametrize("action", ["rename", *ACTIONS])
def test_actual_routes_allow_native_guest_but_owner_fence_imports(backend, action):
    from agents.core.foreign_history import status
    backend.guest = True
    before = backend.cp._conn.execute("SELECT * FROM session_imports WHERE session_id=?", (backend.imported,)).fetchone()
    code, out, err = run(backend, *args_for(action, backend.imported), "--json")
    assert code == EXIT_AUTH and not out and err
    assert len(backend.calls) == 1
    # Guest native mutations remain supported by existing user-guarded routes.
    code, out, err = run(backend, *args_for(action), "--json")
    assert code == EXIT_OK and not err and json.loads(out) == receipt(action)
    backend.guest = False
    # Rename chooses a distinct name to avoid the native title collision.
    args = [action, backend.imported, "Imported name"] if action == "rename" else [action, backend.imported]
    code, out, err = run(backend, *args, "--json")
    assert code == EXIT_OK and not err
    assert json.loads(out)["session"] == backend.imported
    after = backend.cp._conn.execute("SELECT * FROM session_imports WHERE session_id=?", (backend.imported,)).fetchone()
    assert tuple(before) == tuple(after)
    assert status(backend.cp, backend.imported).tainted is True
    assert len(backend.calls) == 3


@pytest.mark.parametrize("action", ["rename", *ACTIONS])
def test_parent_json_flag_projects_public_receipt_with_one_request(hub, action):
    hub.payload = {**receipt(action), "raw_history": SECRET}
    code, out, err = run(hub, "--json", *args_for(action))
    assert code == EXIT_OK and not err
    assert json.loads(out) == receipt(action)
    assert SECRET not in out
    assert len(hub.calls) == 1
