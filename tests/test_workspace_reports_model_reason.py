"""A report run the model failed says why, in the chat's own words (review UX-23).

With the model server stopped the chat said "Serverul modelului nu poate fi contactat (este
oprit sau conexiunea s-a întrerupt)", while the run page only said "Modelul AI nu este
disponibil acum.": the run kept ``error_code='model_unavailable'`` and dropped the failure's
``reason``. Now the run stores it as ``error_reason`` — the very value the chat's ``error``
event carries (``model_unreachable``, ``model_error``, ``empty_answer``, ``no_local_model``,
``data_policy_unacknowledged`` …) — so the run page can word it as the chat does;
``error_code`` keeps its stable meaning and ``error_reason`` is ``null`` when the failure
names no reason (``model_timeout``, ``model_busy``, ``content_blocked``).

The first half drives every failure kind through the test engine; the second half runs the
hub's real router against the fake OpenAI-compatible server (error, empty, stopped, slow,
none at all), and compares a run with a chat turn on the same dead server.
"""

from __future__ import annotations

import json

import httpx
import pytest

from agents.core.llm.base import THINKING_EXHAUSTED_REPLY
from agents.core.workspace import db, llm, reports
from agents.core.workspace.errors import WorkspaceError
from tests.support import fake_openai_server
from tests.support.ports import closed_port
from tests.support.workspace_fixtures import FakeEngine, seed_company, ws  # noqa: F401
from tests.test_workspace_assistant_helpers import SSE_ACCEPT, chat_app, parse_sse, seed_doc
from tests.test_workspace_llm_integration import (  # noqa: F401  (model_server is a fixture)
    _install_router,
    _point_hub_at,
    model_server,
)
from tests.test_workspace_reports_support import (  # noqa: F401  (fixtures)
    cast,
    run_now,
    seed_document,
    signed_in,
)

NORTH = "Vânzările din regiunea Nord au crescut cu 12% în septembrie."


def _queued_run(conn, department_id: int, user, instructions: str = "Rezumă vânzările.") -> int:
    seed_document(conn, department_id=department_id, uploader_id=user.id, title="Raport Nord",
                  chunks=[NORTH])
    report_id = reports.create_report(conn, user, {
        "department_id": department_id, "name": "Vânzări Nord", "instructions": instructions})
    return reports.start_manual_run(conn, user, report_id)


def _failure(conn, run_id: int) -> tuple:
    row = conn.execute("SELECT status, error_code, error_reason, error FROM report_runs "
                       "WHERE id = ?", (run_id,)).fetchone()
    return tuple(row)


def _audited_reason(conn, run_id: int):
    row = conn.execute("SELECT details_json FROM audit WHERE action = 'report.run_failed' "
                       "AND target_id = ?", (str(run_id),)).fetchone()
    return json.loads(row[0]).get("reason")


# ── every failure kind, through the test engine ──────────────────────────────────────

@pytest.mark.parametrize(("engine", "code", "reason"), [
    (FakeEngine(fail=llm.LLMUnavailable("no_local_model")), "model_unavailable",
     "no_local_model"),
    (FakeEngine(fail=llm.LLMUnavailable("hub_not_ready")), "model_unavailable", "hub_not_ready"),
    (FakeEngine(fail=llm.LLMUnavailable("model_not_approved")), "model_unavailable",
     "model_not_approved"),
    (FakeEngine(reply="⚠️ I can't reach the local LM Studio model right now."),
     "model_unavailable", "model_unreachable"),
    (FakeEngine(reply="   "), "model_unavailable", "empty_answer"),
    (FakeEngine(reply=THINKING_EXHAUSTED_REPLY), "model_unavailable", "thinking_exhausted"),
    (FakeEngine(fail=llm.ModelPolicyBlocked("data_policy_unacknowledged")),
     "model_policy_blocked", "data_policy_unacknowledged"),
    (FakeEngine(fail=llm.ModelPolicyBlocked("provider_may_train")), "model_policy_blocked",
     "provider_may_train"),
    (FakeEngine(fail=llm.ModelTimeout(300)), "model_timeout", None),
    (FakeEngine(fail=llm.ModelBusy()), "model_busy", None),
    (FakeEngine(fail=llm.ContentBlocked()), "content_blocked", None),
    # A reason that is not a string, or empty, is no reason.
    (FakeEngine(fail=WorkspaceError("model_unavailable", "down", 503, reason="")),
     "model_unavailable", None),
    (FakeEngine(fail=WorkspaceError("model_unavailable", "down", 503, reason=7)),
     "model_unavailable", None),
])
def test_a_model_failure_is_stored_with_its_reason(cast, ws, engine, code, reason):
    conn = db.connect()
    try:
        ws.use_engine(engine)
        run_id = _queued_run(conn, cast.dept_a, cast.member_a)
        run_now(run_id)
        assert _failure(conn, run_id) == ("failed", code, reason, reports._RUN_ERRORS[code])
        assert _audited_reason(conn, run_id) == reason
        run = reports.get_run(conn, cast.member_a, run_id)
        assert (run["error_code"], run["error_reason"], run["delivery_state"]) == (
            code, reason, None)
        [listed] = reports.list_runs(conn, cast.member_a, run["report_id"])
        assert (listed["error_code"], listed["error_reason"]) == (code, reason)
    finally:
        conn.close()


def test_a_failure_without_a_model_call_has_no_reason(cast, ws):
    conn = db.connect()
    try:
        report_id = reports.create_report(conn, cast.member_a, {
            "department_id": cast.dept_a, "name": "Gol", "instructions": "Rezumă."})
        run_id = reports.start_manual_run(conn, cast.member_a, report_id)
        run_now(run_id)
        assert _failure(conn, run_id)[:3] == ("failed", "no_documents", None)
        assert _audited_reason(conn, run_id) is None
    finally:
        conn.close()


def test_the_run_api_carries_the_reason(cast, ws):
    conn = db.connect()
    try:
        ws.use_engine(FakeEngine(fail=llm.LLMUnavailable(llm.UNREACHABLE)))
        run_id = _queued_run(conn, cast.dept_a, cast.member_a)
        run_now(run_id)
    finally:
        conn.close()
    client, _ = signed_in(cast.member_a)
    run = client.get(f"/api/workspace/report-runs/{run_id}").json()
    assert (run["status"], run["error_code"], run["error_reason"]) == (
        "failed", "model_unavailable", "model_unreachable")


# ── the real router against the fake model server ────────────────────────────────────

@pytest.mark.parametrize(("instructions", "reason"), [
    (f"Rezumă vânzările. {fake_openai_server.ERROR_TRIGGER}", "model_error"),
    (f"Rezumă vânzările. {fake_openai_server.EMPTY_TRIGGER}", "empty_answer"),
])
async def test_the_real_model_servers_failures_are_named(model_server, instructions, reason):
    conn = db.connect()
    try:
        company = seed_company(conn)
        run_id = _queued_run(conn, company.dept_a, company.member_a, instructions)
        await reports.execute_run(run_id)
        assert _failure(conn, run_id)[:3] == ("failed", "model_unavailable", reason)
    finally:
        conn.close()


async def test_a_slow_real_model_is_a_timeout_without_a_reason(model_server, monkeypatch):
    monkeypatch.setattr(reports, "REPORT_TIMEOUT_SECONDS", 0.3)
    conn = db.connect()
    try:
        company = seed_company(conn)
        run_id = _queued_run(conn, company.dept_a, company.member_a,
                             f"Rezumă vânzările. {fake_openai_server.SLOW_TRIGGER}")
        await reports.execute_run(run_id)
        assert _failure(conn, run_id)[:3] == ("failed", "model_timeout", None)
    finally:
        conn.close()


async def test_without_any_local_model_server_the_run_says_so(ws, monkeypatch):
    _point_hub_at(monkeypatch, f"http://127.0.0.1:{closed_port()}")
    router = await _install_router(monkeypatch)
    conn = db.connect()
    try:
        company = seed_company(conn)
        run_id = _queued_run(conn, company.dept_a, company.member_a)
        await reports.execute_run(run_id)
        assert _failure(conn, run_id)[:3] == ("failed", "model_unavailable", "no_local_model")
    finally:
        conn.close()
        await router.aclose()


async def test_a_stopped_model_server_reads_as_in_the_chat(model_server):
    """The evidence of UX-23, side by side: the chat's error event and the run name one reason."""
    server, _ = model_server
    conn = db.connect()
    try:
        company = seed_company(conn)
        seed_doc(conn, department_id=company.dept_a, title="Politica de concedii",
                 text="Concediul anual este de 21 de zile lucrătoare.")
        run_id = _queued_run(conn, company.dept_a, company.member_a)
        await llm.complete(system="s", prompt="Salut, ce faci azi?", policy="local_only")
        server.stop()                           # the model server goes down
        transport = httpx.ASGITransport(app=chat_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            origin = {"Origin": "http://testserver"}
            login = await client.post("/api/workspace/login", headers=origin, json={
                "email": company.member_a.email, "password": "Parola-Buna-2026!"})
            headers = {**origin, "X-CSRF-Token": login.json()["csrf_token"]}
            conversation = (await client.post("/api/workspace/conversations", headers=headers,
                                              json={"department_id": company.dept_a})).json()["id"]
            answer = await client.post(f"/api/workspace/conversations/{conversation}/messages",
                                       headers={**headers, **SSE_ACCEPT},
                                       json={"content": "Câte zile de concediu avem?"})
        event, data = parse_sse(answer.text)[-1]
        assert (event, data["error"], data["reason"]) == (
            "error", "model_unavailable", "model_unreachable")
        await reports.execute_run(run_id)
        assert _failure(conn, run_id)[:3] == ("failed", data["error"], data["reason"])
    finally:
        conn.close()
