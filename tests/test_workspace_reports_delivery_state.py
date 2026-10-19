"""A report run's email delivery has a state of its own (review NWS-20).

A live run page polled only while the run was ``queued``/``running``, and a run is stored
``succeeded`` before its email is sent (each SMTP step may take 15 s), so the page showed
"done" and never the delivery's outcome until it was reloaded. Now ``delivery_state`` says
what the delivery is doing: ``null`` for a run with no approved delivery, ``pending`` from
the very statement that marks the run ``succeeded`` until the mail server answered, then
``sent`` or ``failed`` — and a delivery whose sender stopped (a hub restart or shutdown
mid-send) is resolved ``failed`` / ``delivery_interrupted`` instead of staying pending.

The SMTP sink holds its greeting on a gate, so a test can look at a delivery while it is
really under way, over the HTTP API, without sleeping for a fixed time.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents.core.workspace import db, mailer, reports, scheduler
from tests.support.ports import closed_port
from tests.support.smtp_sink import SmtpSink
from tests.support.workspace_fixtures import freeze_clock, ws  # noqa: F401  (ws is a fixture)
from tests.test_workspace_reports_support import (  # noqa: F401  (fixtures)
    cast,
    configure_smtp,
    drain,
    run_now,
    seed_document,
    signed_in,
    sink,
)

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=ZoneInfo("Europe/Bucharest")).timestamp()
RECIPIENTS = ["sef@client.ro", "ana@client.ro"]
POLL_SECONDS = 0.01
POLL_LIMIT_SECONDS = 20.0


@pytest.fixture
def conn(ws, monkeypatch):
    freeze_clock(monkeypatch, NOW)
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def gated_sink():
    """An SMTP sink whose greeting waits until the test sets ``sink.greeting_gate``."""
    gate = threading.Event()
    with SmtpSink(greeting_gate=gate) as running:
        try:
            yield running
        finally:
            gate.set()


def _report(conn, cast, *, emails=None):
    seed_document(conn, department_id=cast.dept_a, uploader_id=cast.member_a.id,
                  title="Raport Nord", chunks=["Vânzările din regiunea Nord au crescut cu 12%."])
    report_id = reports.create_report(conn, cast.member_a, {
        "department_id": cast.dept_a, "name": "Vânzări Nord",
        "instructions": "Rezumă vânzările din regiunea Nord."})
    if emails:
        conn.execute("UPDATE reports SET delivery_emails_json = ?, delivery_status = 'approved', "
                     "delivery_approved_json = ? WHERE id = ?",
                     (json.dumps(emails), json.dumps(emails), report_id))
    return report_id


def _row(conn, run_id):
    return conn.execute("SELECT * FROM report_runs WHERE id = ?", (run_id,)).fetchone()


def _poll(client, run_id, until, seen):
    """GET the run until *until(run)*; every (status, delivery_state) observed lands in *seen*."""
    deadline = time.monotonic() + POLL_LIMIT_SECONDS
    while True:
        run = client.get(f"/api/workspace/report-runs/{run_id}").json()
        seen.append((run["status"], run["delivery_state"]))
        if until(run):
            return run
        assert time.monotonic() < deadline, f"the run never got there: {seen[-5:]}"
        time.sleep(POLL_SECONDS)


# ── no delivery ──────────────────────────────────────────────────────────────────────

def test_a_run_without_an_approved_delivery_has_no_delivery_state(conn, cast, sink):
    configure_smtp(conn, sink.port)
    plain = _report(conn, cast)
    run_id = reports.start_manual_run(conn, cast.member_a, plain)
    run_now(run_id)
    run = reports.get_run(conn, cast.member_a, run_id)
    assert (run["status"], run["delivery_state"], run["delivered_to"]) == ("succeeded", None, [])
    assert run["error_code"] is None and run["error_reason"] is None
    [listed] = reports.list_runs(conn, cast.member_a, plain)
    assert listed["delivery_state"] is None and "error_reason" in listed
    # Recipients waiting for their approval are no delivery either.
    conn.execute("UPDATE reports SET delivery_emails_json = '[\"sef@client.ro\"]', "
                 "delivery_status = 'pending', delivery_approved_json = '[\"sef@client.ro\"]' "
                 "WHERE id = ?", (plain,))
    waiting = reports.start_manual_run(conn, cast.member_a, plain)
    run_now(waiting)
    assert _row(conn, waiting)["delivery_state"] is None and sink.messages == []


def test_a_failed_run_has_no_delivery_state(conn, cast, sink, ws):
    from tests.support.workspace_fixtures import FakeEngine

    configure_smtp(conn, sink.port)
    ws.use_engine(FakeEngine(reply="   "))
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast, emails=RECIPIENTS))
    run_now(run_id)
    row = _row(conn, run_id)
    assert (row["status"], row["delivery_state"]) == ("failed", None) and sink.messages == []


# ── pending, then sent — over the HTTP API, with the greeting held ───────────────────

def test_the_run_api_shows_the_delivery_pending_until_the_mail_server_answers(
        conn, cast, gated_sink):
    configure_smtp(conn, gated_sink.port)
    report_id = _report(conn, cast, emails=RECIPIENTS)
    client, headers = signed_in(cast.member_a)
    seen: list[tuple[str, str | None]] = []
    with client:
        started = client.post(f"/api/workspace/reports/{report_id}/run", headers=headers)
        assert started.status_code == 202
        run_id = started.json()["run"]["id"]
        run = _poll(client, run_id, lambda r: r["status"] == "succeeded", seen)
        assert run["delivery_state"] == "pending" and run["delivered_to"] == []
        assert run["content_md"], "the report itself is ready while its email is on its way"
        gated_sink.wait_for_connections(1)      # the hub is really talking to the server
        listed = client.get(f"/api/workspace/reports/{report_id}/runs").json()["runs"]
        assert listed[0]["delivery_state"] == "pending"
        gated_sink.greeting_gate.set()          # the slow relay finally greets
        run = _poll(client, run_id, lambda r: r["delivery_state"] != "pending", seen)
        client.portal.call(drain)
    assert (run["status"], run["delivery_state"]) == ("succeeded", "sent")
    assert sorted(run["delivered_to"]) == sorted(RECIPIENTS)
    assert (run["error_code"], run["error"], run["error_reason"]) == (None, None, None)
    assert ("succeeded", None) not in seen, "a finished run never reads without its delivery"
    [mail] = gated_sink.wait_for(1)
    assert sorted(mail.rcpt_tos) == sorted(RECIPIENTS)
    delivered = json.loads(conn.execute("SELECT details_json FROM audit WHERE action = "
                                        "'report.delivered'").fetchone()[0])
    assert delivered["refused"] == 0


def test_the_state_is_pending_already_when_the_success_is_committed(conn, cast, sink,
                                                                     monkeypatch):
    """No window: the statement that marks the run succeeded marks its delivery pending."""
    configure_smtp(conn, sink.port)
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast, emails=RECIPIENTS))
    observed = {}
    real = reports._store_success

    def store_then_look(job, result, text, citations):
        recipients = real(job, result, text, citations)
        side = db.connect()
        try:
            row = _row(side, run_id)
            observed["committed"] = (row["status"], row["delivery_state"])
        finally:
            side.close()
        return recipients

    async def look_at_send(**kwargs):
        side = db.connect()
        try:
            row = _row(side, run_id)
            observed["sending"] = (row["status"], row["delivery_state"])
        finally:
            side.close()
        return list(kwargs["to"])

    monkeypatch.setattr(reports, "_store_success", store_then_look)
    monkeypatch.setattr(reports.mailer, "send_mail", look_at_send)
    run_now(run_id)
    assert observed == {"committed": ("succeeded", "pending"), "sending": ("succeeded", "pending")}
    assert _row(conn, run_id)["delivery_state"] == "sent"


def test_no_commit_ever_shows_the_run_succeeded_without_its_pending_delivery(conn, cast, sink,
                                                                             monkeypatch):
    """Review R4-03: the run's state is read right after every COMMIT of ``_store_success``.

    Looking only once the function returned cannot tell one statement from two transactions
    (``succeeded`` committed first, ``pending`` a moment later): a poll in between would
    stop a live run page at "succeeded" again (NWS-20). Here each commit is observed on its
    own, from a second connection, before anything else runs.
    """
    configure_smtp(conn, sink.port)
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast, emails=RECIPIENTS))
    after_each_commit: list[tuple[str, str | None, int | None]] = []
    real_tx, real_store = db.tx, reports._store_success

    def committed_state():
        side = sqlite3.connect(str(db.db_path()))
        try:
            return side.execute("SELECT status, delivery_state, delivery_attempted "
                                "FROM report_runs WHERE id = ?", (run_id,)).fetchone()
        finally:
            side.close()

    @contextlib.contextmanager
    def observed_tx(connection):
        outermost = not connection.in_transaction
        with real_tx(connection) as inner:
            yield inner
        if outermost:                           # this block's COMMIT has just run
            after_each_commit.append(committed_state())

    def store_observed(job, result, text, citations):
        with monkeypatch.context() as patch:
            patch.setattr(db, "tx", observed_tx)
            return real_store(job, result, text, citations)

    monkeypatch.setattr(reports, "_store_success", store_observed)
    run_now(run_id)
    assert after_each_commit == [("succeeded", "pending", 2)]
    assert _row(conn, run_id)["delivery_state"] == "sent"


# ── failed ───────────────────────────────────────────────────────────────────────────

def test_a_mail_server_that_cannot_be_reached_ends_the_delivery_failed(conn, cast):
    configure_smtp(conn, closed_port())
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast, emails=RECIPIENTS))
    run_now(run_id)
    run = reports.get_run(conn, cast.member_a, run_id)
    assert (run["status"], run["delivery_state"], run["delivered_to"]) == (
        "succeeded", "failed", [])
    assert (run["error_code"], run["error_reason"], run["error"]) == (
        "smtp_failed", "connection_failed", "delivery_failed")
    assert run["content_md"]


def test_a_viewer_outside_the_department_learns_nothing_of_a_shared_runs_delivery(
        conn, cast, sink):
    """Review R4-02: the delivery is the report's configuration, hidden outside its department.

    ``delivered_to`` and ``delivery_state`` already read ``[]`` / ``null`` there, but a failed
    delivery's ``error``, ``error_code`` and ``error_reason`` still told every reader of a
    company-shared run that the report is mailed, that the email failed and the mail server's
    cause. Now the whole delivery is hidden outside, as the run detail and the shared feed
    both show it; inside the department nothing changes.
    """
    report_id = _report(conn, cast, emails=RECIPIENTS)
    configure_smtp(conn, sink.port)
    sent = reports.start_manual_run(conn, cast.member_a, report_id)
    run_now(sent)
    configure_smtp(conn, closed_port())
    failed = reports.start_manual_run(conn, cast.member_a, report_id)
    run_now(failed)
    conn.execute("UPDATE report_runs SET shared_company = 1 WHERE id IN (?, ?)", (sent, failed))
    delivery = ("delivery_state", "delivered_to", "error", "error_code", "error_reason")

    def fields(run):
        return tuple(run[name] for name in delivery)

    inside = {run_id: reports.get_run(conn, cast.member_a, run_id) for run_id in (sent, failed)}
    assert fields(inside[failed]) == ("failed", [], "delivery_failed", "smtp_failed",
                                      "connection_failed")
    assert inside[sent]["delivery_state"] == "sent"
    assert sorted(inside[sent]["delivered_to"]) == sorted(RECIPIENTS)
    outsider, _ = signed_in(cast.member_b)       # another department: the shared run only
    with outsider:
        detail = {run_id: outsider.get(f"/api/workspace/report-runs/{run_id}")
                  for run_id in (sent, failed)}
        feed = outsider.get("/api/workspace/shared-reports")
    assert {run_id: answer.status_code for run_id, answer in detail.items()} == {
        sent: 200, failed: 200}
    assert feed.status_code == 200
    listed = {run["id"]: run for run in feed.json()["runs"]}
    assert sorted(listed) == sorted((sent, failed))
    hidden = (None, [], None, None, None)
    for run_id in (sent, failed):
        assert fields(detail[run_id].json()) == hidden, run_id
        assert fields(listed[run_id]) == hidden, run_id
        assert detail[run_id].json()["content_md"], "the shared report itself stays readable"
        assert listed[run_id]["status"] == "succeeded"


def test_a_greeting_that_never_comes_ends_the_delivery_failed_with_the_timeout_reason(
        conn, cast, gated_sink, monkeypatch):
    """The mail server's own reason is kept, as the admin's SMTP test shows it."""
    monkeypatch.setattr(mailer, "SMTP_TIMEOUT_SECONDS", 0.3)
    configure_smtp(conn, gated_sink.port)
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast, emails=RECIPIENTS))
    run_now(run_id)
    row = _row(conn, run_id)
    assert (row["status"], row["delivery_state"], row["error_code"], row["error_reason"]) == (
        "succeeded", "failed", "smtp_failed", "timeout")
    failed = json.loads(conn.execute("SELECT details_json FROM audit WHERE action = "
                                     "'email.failed'").fetchone()[0])
    assert failed == {"source": "report_delivery", "report_id": row["report_id"],
                      "error_code": "smtp_failed", "recipient_count": 2}


def test_a_crash_while_delivering_resolves_the_delivery(conn, cast, sink, monkeypatch, caplog):
    configure_smtp(conn, sink.port)
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast, emails=RECIPIENTS))

    async def explode(**kwargs):
        raise RuntimeError("mailer bug")

    monkeypatch.setattr(reports.mailer, "send_mail", explode)
    with caplog.at_level(logging.ERROR, logger="nerva.workspace.reports"):
        run_now(run_id)
    row = _row(conn, run_id)
    assert (row["status"], row["delivery_state"], row["error_code"]) == (
        "succeeded", "failed", "internal_error")
    assert "delivery crashed" in caplog.text


# ── a sender that stopped: shutdown mid-send, and a restart ──────────────────────────

async def test_a_shutdown_while_sending_resolves_the_delivery_as_interrupted(
        conn, cast, gated_sink):
    configure_smtp(conn, gated_sink.port)
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast, emails=RECIPIENTS))
    reports.spawn_run(run_id)
    await asyncio.to_thread(gated_sink.wait_for_connections, 1)
    assert _row(conn, run_id)["delivery_state"] == "pending"
    await reports.cancel_runs()                 # the hub's shutdown
    row = _row(conn, run_id)
    assert (row["status"], row["delivery_state"], row["error_code"], row["error"]) == (
        "succeeded", "failed", reports.DELIVERY_INTERRUPTED, "delivery_failed")
    bodies = [r[0] for r in conn.execute(
        "SELECT body FROM notifications WHERE user_id = ? AND kind = 'report.delivery_failed'",
        (cast.member_a.id,))]
    assert bodies == [reports._delivery_failure_bodies(reports.DELIVERY_INTERRUPTED)["ro"]]
    assert "nu se știe dacă destinatarii l-au primit" in bodies[0]
    gated_sink.greeting_gate.set()              # let the orphaned SMTP thread finish now


async def test_a_shutdown_whose_interrupted_delivery_cannot_be_written_still_cancels_the_run(
        conn, cast, gated_sink, monkeypatch, caplog):
    """Review R4-04: a database error while recording ``delivery_interrupted`` at shutdown.

    It must not replace the cancellation: ``execute_run`` would then log the run as crashed
    and the shutdown's cancellation would be swallowed. One WARNING, the cancellation goes
    on, the delivery stays ``pending`` and the next start's sweep resolves it.
    """
    configure_smtp(conn, gated_sink.port)
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast, emails=RECIPIENTS))
    real = reports._record_delivery
    tried: list[str | None] = []

    def disk_gone(job, accepted, error_code, attempted, reason=None):
        tried.append(error_code)
        if error_code == reports.DELIVERY_INTERRUPTED:
            raise sqlite3.OperationalError("disk I/O error")
        return real(job, accepted, error_code, attempted, reason)

    monkeypatch.setattr(reports, "_record_delivery", disk_gone)
    reports.spawn_run(run_id)
    [task] = [t for t in reports._TASKS if t.get_name() == f"workspace-report-run-{run_id}"]
    await asyncio.to_thread(gated_sink.wait_for_connections, 1)
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.reports"):
        await reports.cancel_runs()             # the hub's shutdown
    try:
        assert tried == [reports.DELIVERY_INTERRUPTED]
        assert task.cancelled(), "the shutdown's cancellation went on"
        assert f"report run {run_id}: the interrupted delivery could not be recorded" in caplog.text
        assert "crashed" not in caplog.text
        row = _row(conn, run_id)
        assert (row["status"], row["delivery_state"], row["error_code"]) == (
            "succeeded", "pending", None)
        # The next start resolves it, as it resolves a delivery of a hub that was killed.
        assert reports.fail_stuck_deliveries(conn, NOW, stored_before=NOW + 1) == 1
        row = _row(conn, run_id)
        assert (row["delivery_state"], row["error_code"], row["error"]) == (
            "failed", reports.DELIVERY_INTERRUPTED, "delivery_failed")
    finally:
        gated_sink.greeting_gate.set()          # let the orphaned SMTP thread finish now


def _left_pending(conn, cast, monkeypatch) -> int:
    """A run whose hub stopped after storing it and before the mail server answered."""
    configure_smtp(conn, closed_port())
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast, emails=RECIPIENTS))

    async def the_process_died(job, text, recipients):
        return None

    with monkeypatch.context() as patch:
        patch.setattr(reports, "_deliver", the_process_died)
        run_now(run_id)
    assert _row(conn, run_id)["delivery_state"] == "pending"
    return run_id


def test_a_restart_resolves_a_delivery_left_pending_at_the_first_tick(conn, cast, monkeypatch):
    run_id = _left_pending(conn, cast, monkeypatch)
    restarted = scheduler.WorkspaceScheduler(started_at=NOW + 5)
    summary = asyncio.run(restarted.tick(now=NOW + 5))
    assert summary["deliveries_interrupted"] == 1 and summary["errors"] == []
    row = _row(conn, run_id)
    assert (row["status"], row["delivery_state"], row["error_code"], row["error"]) == (
        "succeeded", "failed", reports.DELIVERY_INTERRUPTED, "delivery_failed")
    assert row["delivered_to_json"] == "[]" and row["content_md"]
    failed = json.loads(conn.execute("SELECT details_json FROM audit WHERE action = "
                                     "'email.failed'").fetchone()[0])
    assert failed == {"source": "report_delivery", "report_id": row["report_id"],
                      "error_code": reports.DELIVERY_INTERRUPTED, "recipient_count": 2}
    actor = conn.execute("SELECT actor_email FROM audit WHERE action = 'email.failed'").fetchone()
    assert actor[0] == reports.SCHEDULER_ACTOR
    kinds = [r[0] for r in conn.execute("SELECT kind FROM notifications WHERE user_id = ? "
                                        "ORDER BY id", (cast.member_a.id,))]
    assert kinds == ["report.run_succeeded", "report.delivery_failed"]
    assert asyncio.run(restarted.tick(now=NOW + 35))["deliveries_interrupted"] == 0


def test_a_live_process_leaves_a_fresh_delivery_alone_until_the_bound(conn, cast, monkeypatch):
    run_id = _left_pending(conn, cast, monkeypatch)
    live = scheduler.WorkspaceScheduler(started_at=NOW - 60)   # the process that is sending
    assert asyncio.run(live.tick(now=NOW + 60))["deliveries_interrupted"] == 0
    assert _row(conn, run_id)["delivery_state"] == "pending"
    assert reports.fail_stuck_deliveries(conn, NOW + reports.DELIVERY_TIMEOUT_SECONDS - 1) == 0
    assert reports.fail_stuck_deliveries(conn, NOW + reports.DELIVERY_TIMEOUT_SECONDS) == 1
    assert _row(conn, run_id)["delivery_state"] == "failed"


def test_an_outcome_after_the_sweep_does_not_settle_the_delivery_twice(conn, cast, monkeypatch,
                                                                       caplog):
    run_id = _left_pending(conn, cast, monkeypatch)
    assert reports.fail_stuck_deliveries(conn, NOW, stored_before=NOW + 1) == 1
    job = reports._Job(run_id=run_id, report_id=int(_row(conn, run_id)["report_id"]),
                       report_name="Vânzări Nord", department_name="Vânzări", org_name="Acme",
                       locale="ro", timezone="Europe/Bucharest", policy="local_only",
                       system="", prompt="", citations=[])
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.reports"):
        reports._record_delivery(job, list(RECIPIENTS), None, 2)
    row = _row(conn, run_id)
    assert (row["delivery_state"], row["delivered_to_json"]) == ("failed", "[]")
    assert conn.execute("SELECT COUNT(*) FROM audit WHERE action IN ('report.delivered', "
                        "'email.failed')").fetchone()[0] == 1
    assert "after the delivery was resolved" in caplog.text


def _job(conn, run_id) -> reports._Job:
    """The sender's view of a run, to deliver an outcome the way ``_deliver`` does."""
    return reports._Job(run_id=run_id, report_id=int(_row(conn, run_id)["report_id"]),
                        report_name="Vânzări Nord", department_name="Vânzări", org_name="Acme",
                        locale="ro", timezone="Europe/Bucharest", policy="local_only",
                        system="", prompt="", citations=[])


def test_a_late_failure_after_the_sweep_does_not_settle_the_delivery_twice(conn, cast,
                                                                          monkeypatch, caplog):
    """Review R4-05: the failed branch's compare-and-set on ``pending``, as the sent one's.

    A sender the sweep already resolved as ``delivery_interrupted`` that finally fails
    (``smtp_failed`` / ``timeout``) must not overwrite the code and reason, audit a second
    ``email.failed`` nor notify a second time.
    """
    run_id = _left_pending(conn, cast, monkeypatch)
    assert reports.fail_stuck_deliveries(conn, NOW, stored_before=NOW + 1) == 1
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.reports"):
        reports._record_delivery(_job(conn, run_id), [], "smtp_failed", 2, "timeout")
    row = _row(conn, run_id)
    assert (row["delivery_state"], row["error_code"], row["error_reason"], row["error"]) == (
        "failed", reports.DELIVERY_INTERRUPTED, None, "delivery_failed")
    assert conn.execute("SELECT COUNT(*) FROM audit WHERE action IN ('report.delivered', "
                        "'email.failed')").fetchone()[0] == 1
    notified = conn.execute("SELECT user_id, COUNT(*), MIN(body) FROM notifications "
                            "WHERE kind = 'report.delivery_failed' GROUP BY user_id").fetchall()
    assert [tuple(r) for r in notified] == [(
        cast.member_a.id, 1,
        reports._delivery_failure_bodies(reports.DELIVERY_INTERRUPTED)["ro"])]
    assert "after the delivery was resolved (failed); it is not recorded again" in caplog.text


def test_the_sweep_audits_the_recipients_the_delivery_was_addressed_to(conn, cast, monkeypatch):
    """Review R4-07: ``recipient_count`` is what was attempted, not the report's list now.

    The count is stored with the pending state; the owner removing the recipients after the
    hub died (the approved list is then ``[]``) no longer makes the stranded email audit as
    addressed to nobody — the sender's own ``email.failed`` counts what it attempted too.
    """
    run_id = _left_pending(conn, cast, monkeypatch)
    report_id = int(_row(conn, run_id)["report_id"])
    assert _row(conn, run_id)["delivery_attempted"] == 2
    reports.update_report(conn, cast.member_a, report_id, {"delivery_emails": []})
    report = conn.execute("SELECT delivery_status, delivery_approved_json FROM reports "
                          "WHERE id = ?", (report_id,)).fetchone()
    assert tuple(report) == ("none", "[]")
    assert reports.fail_stuck_deliveries(conn, NOW, stored_before=NOW + 1) == 1
    failed = json.loads(conn.execute("SELECT details_json FROM audit WHERE action = "
                                     "'email.failed'").fetchone()[0])
    assert failed == {"source": "report_delivery", "report_id": report_id,
                      "error_code": reports.DELIVERY_INTERRUPTED, "recipient_count": 2}


def test_a_run_with_no_delivery_records_no_attempt(conn, cast, sink):
    configure_smtp(conn, sink.port)
    run_id = reports.start_manual_run(conn, cast.member_a, _report(conn, cast))
    run_now(run_id)
    row = _row(conn, run_id)
    assert (row["status"], row["delivery_state"], row["delivery_attempted"]) == (
        "succeeded", None, None)


def test_the_delivery_sweep_pauses_under_a_wrong_audit_key(conn, cast, monkeypatch):
    run_id = _left_pending(conn, cast, monkeypatch)
    monkeypatch.setattr(scheduler.audit, "key_check", lambda _conn: "mismatch")
    summary = asyncio.run(scheduler.WorkspaceScheduler(started_at=NOW + 5).tick(now=NOW + 5))
    assert "deliveries_interrupted" in summary["paused"]
    assert _row(conn, run_id)["delivery_state"] == "pending"


# ── the schema change on an existing database ────────────────────────────────────────

def test_a_database_at_schema_1_gains_the_columns_and_keeps_its_runs(ws, monkeypatch):
    """A dev install's database (schema 1) is migrated in place at the next connect."""
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:1])
        old = db.connect()
        assert old.execute("PRAGMA user_version").fetchone()[0] == 1
        with db.tx(old):
            dept = old.execute("INSERT INTO departments (slug, name, created_at) "
                               "VALUES ('v', 'Vânzări', 1)").lastrowid
            report = old.execute("INSERT INTO reports (department_id, name, instructions, "
                                 "created_at, updated_at) VALUES (?, 'R', 'i', 1, 1)",
                                 (dept,)).lastrowid
            run = old.execute("INSERT INTO report_runs (report_id, status, trigger, created_at, "
                              "delivered_to_json) VALUES (?, 'succeeded', 'manual', 1, "
                              "'[\"a@b.ro\"]')", (report,)).lastrowid
        old.close()
    conn = db.connect()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.schema_version() == 3
        row = _row(conn, run)
        assert (row["delivery_state"], row["error_reason"], row["delivered_to_json"]) == (
            None, None, '["a@b.ro"]')
        assert row["delivery_attempted"] is None
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE report_runs SET delivery_state = 'maybe' WHERE id = ?", (run,))
    finally:
        conn.close()


def test_a_delivery_left_pending_at_schema_2_is_audited_with_the_reports_list(ws, monkeypatch):
    """A pending delivery stored before schema 3 has no attempted count (review R4-07).

    The migration keeps it (``delivery_attempted`` reads ``NULL``) and the sweep then counts
    the report's approved list, as it did before the count was stored.
    """
    freeze_clock(monkeypatch, NOW)
    approved = json.dumps(RECIPIENTS)
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:2])
        old = db.connect()
        assert old.execute("PRAGMA user_version").fetchone()[0] == 2
        with db.tx(old):
            dept = old.execute("INSERT INTO departments (slug, name, created_at) "
                               "VALUES ('v', 'Vânzări', 1)").lastrowid
            report = old.execute(
                "INSERT INTO reports (department_id, name, instructions, delivery_emails_json, "
                "delivery_status, delivery_approved_json, created_at, updated_at) "
                "VALUES (?, 'R', 'i', ?, 'approved', ?, 1, 1)", (dept, approved, approved)).lastrowid
            run = old.execute(
                "INSERT INTO report_runs (report_id, status, trigger, created_at, finished_at, "
                "content_md, delivery_state) VALUES (?, 'succeeded', 'manual', ?, ?, 'Raport', "
                "'pending')", (report, NOW - 5, NOW - 5)).lastrowid
        old.close()
    conn = db.connect()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        row = _row(conn, run)
        assert (row["delivery_state"], row["delivery_attempted"]) == ("pending", None)
        assert reports.fail_stuck_deliveries(conn, NOW, stored_before=NOW) == 1
        failed = json.loads(conn.execute("SELECT details_json FROM audit WHERE action = "
                                         "'email.failed'").fetchone()[0])
        assert failed == {"source": "report_delivery", "report_id": report,
                          "error_code": reports.DELIVERY_INTERRUPTED,
                          "recipient_count": len(RECIPIENTS)}
    finally:
        conn.close()
