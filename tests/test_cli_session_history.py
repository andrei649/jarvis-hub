"""V69 owner session history contract through HubClient and saved-session routes."""
from __future__ import annotations

import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from agents.cli.client import HubClient
from agents.cli.nerva import EXIT_AUTH, EXIT_FAILED, EXIT_NO_HUB, EXIT_OK, EXIT_USAGE, Context, main

SECRET = "PRIVATE_HISTORY_BODY_69"


def test_history_parser_and_completion_are_nested_and_bounded():
    from agents.cli.completion import completion_nodes
    from agents.cli.nerva import build_parser
    parser = build_parser()
    ns = parser.parse_args(["sessions", "history"])
    assert ns.session_action == "history"
    assert ns.limit == 100 and ns.max_pages == 10
    assert "history" in dict(completion_nodes(parser)[("sessions",)])
    assert "history" not in dict(completion_nodes(parser)[()])


def row(sid="session-69", **changes):
    return {"id": sid, "started_at": "2020-01-01T00:00:00+00:00", "agent_id": "nerva",
            "title": "Saved conversation", "resume_id": sid, "continuations": 0, **changes}


def page(*rows, cursor=None):
    return {"sessions": list(rows), "next_cursor": cursor}


@pytest.fixture
def hub():
    state = SimpleNamespace(pages=[page()], calls=[])

    def opener(request, **kwargs):
        state.calls.append(request)
        body = state.pages[len(state.calls) - 1]
        if isinstance(body, Exception):
            raise body
        if isinstance(body, int):
            raise HTTPError(request.full_url, body, SECRET, {}, io.BytesIO(json.dumps({"detail": SECRET}).encode()))
        return io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())

    state.factory = lambda env: HubClient.from_env(env, opener=opener)
    return state


def run(hub, *args):
    out, err = io.StringIO(), io.StringIO()
    code = main(["sessions", "history", *args], context=Context(
        environ={"NERVA_HUB_URL": "http://127.0.0.1:8765", "JARVIS_ADMIN_TOKEN": "owner-token-69",
                 "JARVIS_USER_TOKEN": "user-token-69"},
        client_factory=hub.factory, out=out, err=err, inp=io.StringIO()))
    return code, out.getvalue(), err.getvalue()


def query(request):
    return parse_qs(urlsplit(request.full_url).query)


def test_history_owner_read_projects_metadata_and_reports_scan(hub):
    hub.pages = [{**page({**row(), "metadata": {"secret": SECRET}, "raw_history": SECRET}), "secret": SECRET}]
    code, out, err = run(hub, "--json")
    assert code == EXIT_OK and not err
    body = json.loads(out)
    assert body["sessions"] == [row()]
    assert body["next_cursor"] is None and body["has_more"] is False
    assert (body["scanned_pages"], body["scanned_rows"], body["stop_reason"]) == (1, 1, "exhausted")
    assert body["filters"] == {"archived": False, "agent": None, "unassigned": False,
                               "older_than_days": None, "query": None}
    from datetime import datetime
    assert datetime.fromisoformat(body["as_of"].replace("Z", "+00:00")).tzinfo is not None
    assert SECRET not in out + err
    req = hub.calls[0]
    assert req.method == "GET" and req.data is None and urlsplit(req.full_url).path == "/sessions/page"
    assert query(req).get("limit") == ["100"]
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers["x-admin-token"] == "owner-token-69" and headers["x-user-token"] == "user-token-69"


def test_filters_intersect_and_remaining_match_limit_does_not_drop_rows(hub):
    hub.pages = [page(row("wrong-agent", agent_id="other"), row("wrong-query", title="other"), cursor="cursor-a"),
                 page(row("match-a", title="Needle"), row("wrong-age", started_at="2999-01-01T00:00:00Z"), cursor="cursor-b"),
                 page(row("match-b", title="NEEDLE"), cursor="cursor-c")]
    code, out, err = run(hub, "--limit", "2", "--agent", "nerva", "--older-than", "1", "--query", "needle", "--archived", "--json")
    assert code == EXIT_OK and not err
    body = json.loads(out)
    assert [r["id"] for r in body["sessions"]] == ["match-a", "match-b"]
    assert [query(req)["limit"] for req in hub.calls] == [["2"], ["2"], ["1"]]
    assert all(query(req)["archived"] == ["true"] for req in hub.calls)
    assert query(hub.calls[1])["cursor"] == ["cursor-a"]
    assert body["stop_reason"] == "result_limit" and body["next_cursor"] == "cursor-c" and body["has_more"]
    assert (body["scanned_pages"], body["scanned_rows"]) == (3, 5)


def test_deduplication_preserves_first_seen_order_across_pages(hub):
    hub.pages = [page(row("first"), cursor="cursor-a"), page(row("first"), row("second"))]
    code, out, err = run(hub, "--json")
    assert code == EXIT_OK and not err
    body = json.loads(out)
    assert [r["id"] for r in body["sessions"]] == ["first", "second"]
    assert body["scanned_rows"] == 3


def test_page_cap_zero_matches_discloses_continuation_in_json_and_human(hub):
    hub.pages = [page(row(agent_id="other"), cursor="cursor-a")]
    code, out, err = run(hub, "--agent", "nerva", "--max-pages", "1", "--json")
    assert code == EXIT_OK and not err
    body = json.loads(out)
    assert body["sessions"] == [] and body["next_cursor"] == "cursor-a" and body["has_more"]
    assert body["stop_reason"] == "page_limit"
    hub.calls.clear()
    code, out, err = run(hub, "--agent", "nerva", "--max-pages", "1")
    assert code == EXIT_OK and "cursor-a" in out + err
    assert "page_limit" in out + err and "resume" in (out + err).lower()


def test_cursor_resumes_at_exact_result_boundary(hub):
    hub.pages = [page(row("one"), cursor="cursor-a")]
    code, out, err = run(hub, "--limit", "1", "--json")
    assert code == EXIT_OK and not err
    cursor = json.loads(out)["next_cursor"]
    hub.calls.clear()
    hub.pages = [page(row("two"))]
    code, out, err = run(hub, "--cursor", cursor, "--limit", "1", "--json")
    assert code == EXIT_OK and not err
    assert query(hub.calls[0])["cursor"] == [cursor]
    assert [r["id"] for r in json.loads(out)["sessions"]] == ["two"]


def test_unknown_agent_matches_nothing_and_unassigned_is_explicit(hub):
    hub.pages = [page(row("none", agent_id=None), row("absent"), row("assigned", agent_id="nerva"))]
    hub.pages[0]["sessions"][1].pop("agent_id")
    code, out, err = run(hub, "--agent", "unknown-agent", "--json")
    assert code == EXIT_OK and not err and json.loads(out)["sessions"] == []
    hub.calls.clear()
    code, out, err = run(hub, "--unassigned", "--json")
    assert code == EXIT_OK and not err
    assert [r["id"] for r in json.loads(out)["sessions"]] == ["none", "absent"]


@pytest.mark.parametrize("args", [
    ["--limit", "0"], ["--limit", "1001"], ["--max-pages", "0"], ["--max-pages", "101"],
    ["--older-than", "-1"], ["--older-than", "36501"], ["--older-than", "1.5"],
    ["--query", "x" * 257], ["--agent", "bad\nagent"], ["--agent", ""],
    ["--agent", "nerva", "--unassigned"], ["--cursor", "!"], ["--cursor", "x" * 513],
])
def test_invalid_options_fail_before_http(hub, args):
    code, out, _err = run(hub, *args)
    assert code == EXIT_USAGE and not out and hub.calls == []


@pytest.mark.parametrize("status", [401, 403, 400, 404, 500, 503])
def test_http_refusal_is_private_and_never_falls_back(hub, status):
    hub.pages = [status]
    code, out, err = run(hub, "--json")
    assert code == (EXIT_AUTH if status in (401, 403) else EXIT_FAILED)
    assert not out and err and SECRET not in err and len(hub.calls) == 1


@pytest.mark.parametrize("bad", [503, URLError(SECRET), b"not json", page({"id": "bad/id"})])
def test_late_failure_discards_buffered_output(hub, bad):
    hub.pages = [page(row(), cursor="cursor-a"), bad]
    code, out, err = run(hub, "--json")
    assert code == (EXIT_NO_HUB if isinstance(bad, URLError) else EXIT_FAILED)
    assert not out and err and SECRET not in err
    assert len(hub.calls) == 2


@pytest.mark.parametrize("bad", [
    [], {}, {"sessions": [], "next_cursor": 1}, {"sessions": {}, "next_cursor": None},
    page(None), page({}), page(row(session_id="different")), page(row(pinned=1)),
    page(row(continuations=True)), page(row(title=[])), page(row(agent_id=1)),
    page(row(summary="🌍" * 4097)), page(row("bad/id")), page(cursor="cursor-a"),
])
def test_malformed_or_oversized_known_metadata_fails_closed(hub, bad):
    hub.pages = [bad]
    code, out, err = run(hub, "--json")
    assert code == EXIT_FAILED and not out and err and SECRET not in err


def test_repeated_cursor_refused_without_third_request(hub):
    hub.pages = [page(row("one"), cursor="cursor-a"), page(row("two"), cursor="cursor-a")]
    code, out, err = run(hub, "--json")
    assert code == EXIT_FAILED and not out and err and len(hub.calls) == 2


def test_age_uses_fixed_anchor_and_excludes_unparseable_or_missing_dates(hub):
    from datetime import UTC, datetime

    from agents.cli.session_history import collect_history
    hub.pages = [page(row("old", started_at="2026-11-11T11:59:59Z"),
                      row("young", started_at="2026-11-12T12:00:01Z"), cursor="cursor-a"),
                 page(row("bad", started_at="unknown"), row("missing", started_at=None))]
    client = hub.factory({"NERVA_HUB_URL": "http://127.0.0.1:8765"})
    result = collect_history(client, older_than_days=1, as_of=datetime(2026, 11, 13, 12, tzinfo=UTC))
    assert [r["id"] for r in result["sessions"]] == ["old"]
    assert result["as_of"].startswith("2026-11-13T12:00:00")


def test_projected_output_limit_fails_without_partial_stdout(hub):
    # Every individual field is within 16 KiB; their aggregate exceeds 8 MiB.
    hub.pages = [page(*(row(f"session-{p}-{n}", title="t" * 16384, summary="s" * 16384)
                              for n in range(100)), cursor=f"cursor-{p}") for p in range(3)]
    code, out, err = run(hub, "--limit", "1000", "--json")
    assert code == EXIT_FAILED and not out and err and len(hub.calls) == 3


@pytest.fixture
def backend(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agents.core.checkpoint import CheckpointManager
    from agents.core.routers import sessions
    cp = CheckpointManager(str(tmp_path / "history.db"))
    cp.initialize()
    for index in range(27):
        sid = f"saved-{index:02d}"
        cp.create_session_record(sid)
        cp._conn.execute("UPDATE sessions SET started_at=? WHERE id=?", (f"2026-10-{index + 1:02d}T10:00:00+00:00", sid))
    cp._conn.commit()
    cp.set_archived("saved-26", True)
    monkeypatch.setattr(sessions, "get_orch", lambda: SimpleNamespace(checkpoints=cp))
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "owner-token-69")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "user-token-69")
    app = FastAPI()
    app.include_router(sessions.router)
    http = TestClient(app, client=("192.0.2.10", 4000))
    state = SimpleNamespace(calls=[], cp=cp, guest=False)

    def opener(request, **kwargs):
        state.calls.append(request)
        response = http.request(request.method, request.full_url,
                                headers=dict(request.header_items()), content=request.data)
        if response.status_code >= 400:
            raise HTTPError(request.full_url, response.status_code, "refused", {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)

    state.factory = lambda env: HubClient.from_env({**env, "JARVIS_ADMIN_TOKEN": ""} if state.guest else env, opener=opener)
    yield state
    http.close()
    cp.close()


def test_real_owner_history_beyond_twenty_archive_lineage_and_guest_refusal(backend):
    from datetime import UTC, datetime

    from agents.core.session_continuation import ContinuationStore
    child = ContinuationStore(backend.cp).create("saved-25", "00000000-0000-4000-8000-000000000069",
        [{"role": "user", "content": "continue", "timestamp": datetime.now(UTC).isoformat(), "token_count": 1}],
        backend.cp.clock_snapshot("saved-25"))["session_id"]
    before = backend.cp._conn.total_changes
    code, out, err = run(backend, "--json")
    assert code == EXIT_OK and not err
    rows = json.loads(out)["sessions"]
    assert len(rows) == 26 and child in {r["id"] for r in rows}
    assert "saved-25" not in {r["id"] for r in rows} and "saved-26" not in {r["id"] for r in rows}
    assert next(r for r in rows if r["id"] == child)["continuations"] == 1
    code, out, err = run(backend, "--archived", "--json")
    assert code == EXIT_OK and not err and [r["id"] for r in json.loads(out)["sessions"]] == ["saved-26"]
    backend.guest = True
    code, out, err = run(backend, "--json")
    assert code == EXIT_AUTH and not out and err and len(backend.calls) == 3
    assert backend.cp._conn.total_changes == before


def test_custom_dotted_agent_is_a_metadata_value(hub):
    hub.pages = [page(row(agent_id="custom.agent"))]
    code, out, err = run(hub, "--agent", "custom.agent", "--json")
    assert code == EXIT_OK and not err
    assert json.loads(out)["sessions"][0]["agent_id"] == "custom.agent"


def test_query_never_searches_raw_metadata(hub):
    hub.pages = [page({**row(), "metadata": {"note": SECRET}, "raw_history": SECRET})]
    code, out, err = run(hub, "--query", SECRET, "--json")
    assert code == EXIT_OK and not err and json.loads(out)["sessions"] == []


@pytest.mark.parametrize("args", [["sessions", "--json", "history"],
                                   ["sessions", "history", "--json"]])
def test_history_json_flag_before_or_after_subcommand(hub, args):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, context=Context(
        environ={"NERVA_HUB_URL": "http://127.0.0.1:8765"},
        client_factory=hub.factory, out=out, err=err, inp=io.StringIO()))
    assert code == EXIT_OK and not err.getvalue()
    assert json.loads(out.getvalue())["stop_reason"] == "exhausted"


def test_real_route_filter_page_cap_and_cursor_resume(backend):
    # Each page has at most two rows, even when metadata filters reject all rows.
    code, out, err = run(backend, "--limit", "2", "--max-pages", "2",
                         "--query", "saved-00", "--json")
    assert code == EXIT_OK and not err
    body = json.loads(out)
    assert body["sessions"] == [] and body["stop_reason"] == "page_limit"
    assert body["has_more"] and body["next_cursor"]
    assert body["scanned_pages"] == 2 and body["scanned_rows"] == 4
    assert len(backend.calls) == 2
    code, out, err = run(backend, "--limit", "2", "--max-pages", "20",
                         "--cursor", body["next_cursor"], "--query", "saved-00", "--json")
    assert code == EXIT_OK and not err
    resumed = json.loads(out)
    assert [r["id"] for r in resumed["sessions"]] == ["saved-00"]
    assert resumed["stop_reason"] == "exhausted" and not resumed["has_more"]
    assert all(int(query(req)["limit"][0]) <= 2 for req in backend.calls)


def test_cancellation_on_late_page_has_no_partial_stdout(hub):
    hub.pages = [page(row(), cursor="cursor-a"), KeyboardInterrupt()]
    # BaseException is intentionally outside the fixture's Exception handler.
    factory = hub.factory
    def cancelled_factory(env):
        client = factory(env)
        original_get = client.get
        def get(path):
            if hub.calls:
                hub.calls.append(path)
                raise KeyboardInterrupt
            return original_get(path)
        client.get = get
        return client
    hub.factory = cancelled_factory
    code, out, err = run(hub, "--json")
    assert code == 130 and not out and len(hub.calls) == 2


def test_initial_cursor_cycle_fails_on_first_response(hub):
    hub.pages = [page(row(), cursor="cursor-a")]
    code, out, err = run(hub, "--cursor", "cursor-a", "--json")
    assert code == EXIT_FAILED and not out and err and len(hub.calls) == 1


@pytest.mark.parametrize("failure", ["unavailable", "malformed"])
def test_real_route_late_failure_never_claims_exhaustion(backend, monkeypatch, failure):
    original_page = backend.cp.get_sessions_page
    calls = []
    def read_page(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2 and failure == "unavailable":
            raise RuntimeError(SECRET)
        rows, more = original_page(*args, **kwargs)
        if len(calls) == 2:
            rows[0]["turn_count"] = True
        return rows, more
    monkeypatch.setattr(backend.cp, "get_sessions_page", read_page)
    code, out, err = run(backend, "--limit", "2", "--query", "saved-00", "--json")
    assert code == EXIT_FAILED and not out and err and SECRET not in err
    assert len(backend.calls) == 2 and len(calls) == 2
