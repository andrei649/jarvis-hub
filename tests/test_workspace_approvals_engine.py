"""The approvals engine (spec §6 four-eyes rule, §7 approvals): life cycle and authorization.

The engine is exercised with two small test effects registered for the duration of
each test (one decided by department approvers, one by admins), so every rule is
proven independently of any domain: nobody decides their own request except an admin
asking for an admin-rule kind, nobody decides outside their departments, a double
decision executes once, and the effect is re-validated before it runs.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from agents.core.workspace import approvals, audit, db, effects_api, identity
from agents.core.workspace.effects_api import EffectSpec, ValidatedRequest
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.http import require_int, require_str
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    freeze_clock,
    make_department,
    make_user,
    seed_org,
    ws,
)
from tests.test_workspace_reports_support import cast  # noqa: F401  (a fixture)

DEPT_KIND = "test.department_effect"
ADMIN_KIND = "test.admin_effect"


class Recorder:
    """A test effect: validates scope, records executions, can be told to fail."""

    def __init__(self) -> None:
        self.executions: list[dict] = []
        self.validations = 0
        self.fail: BaseException | None = None

    def validate(self, conn, requester, payload) -> ValidatedRequest:
        self.validations += 1
        department_id = require_int(payload, "department_id", minimum=1)
        label = require_str(payload, "label", max_len=50, min_len=1)
        if not requester.can_access_department(department_id):
            raise WorkspaceError("not_found", "no such department", 404)
        return ValidatedRequest(department_id=department_id, summary=f"Test {label}",
                                payload={"department_id": department_id, "label": label})

    async def execute(self, approval, requester, decider) -> dict:
        await asyncio.sleep(0)
        self.executions.append({"approval_id": approval["id"], "payload": approval["payload"],
                                "requester": requester.id, "decider": decider.id})
        if self.fail is not None:
            raise self.fail
        return {"done": approval["payload"]["label"]}


@pytest.fixture
def effect(monkeypatch):
    recorder = Recorder()
    for kind, rule in ((DEPT_KIND, "department"), (ADMIN_KIND, "admin")):
        monkeypatch.setitem(effects_api._REGISTRY, kind,
                            EffectSpec(kind=kind, validate=recorder.validate,
                                       execute=recorder.execute, decider_rule=rule))
    closed: list[tuple[int, str]] = []
    requested: list[int] = []
    monkeypatch.setitem(approvals._HOOKS, DEPT_KIND, approvals.Hooks(
        on_requested=lambda conn, approval_id, validated, requester: requested.append(approval_id),
        on_closed=lambda conn, row, outcome: closed.append((int(row["id"]), outcome))))
    recorder.closed = closed
    recorder.requested = requested
    return recorder


@pytest.fixture
def conn(ws):
    connection = db.connect()
    yield connection
    connection.close()


def _user(conn, user):
    return identity.get_user(conn, user.id)


def _request(conn, user, department_id, label="raport", kind=DEPT_KIND):
    return asyncio.run(approvals.request(conn, user, kind,
                                         {"department_id": department_id, "label": label}))


def _decide(conn, user, approval_id, decision="approve", note=""):
    return asyncio.run(approvals.decide(conn, user, approval_id, decision=decision, note=note))


def _actions(conn):
    return [row[0] for row in conn.execute("SELECT action FROM audit ORDER BY id")]


def _notified(conn, user):
    return [(row["kind"], row["link"]) for row in conn.execute(
        "SELECT kind, link FROM notifications WHERE user_id = ? ORDER BY id", (user.id,))]


# ── requesting ───────────────────────────────────────────────────────────────────────

def test_a_request_is_pending_and_its_deciders_are_told(conn, cast, effect):
    item = _request(conn, cast.member_a, cast.dept_a)
    assert item["status"] == "pending" and item["summary"] == "Test raport"
    assert item["requester"] == {"id": cast.member_a.id, "name": cast.member_a.name,
                                 "email": cast.member_a.email}
    assert item["decider"] is None and item["can_decide"] is False and item["can_cancel"] is True
    assert item["expires_at"] - item["created_at"] == approvals.APPROVAL_TTL_SECONDS
    assert effect.requested == [item["id"]] and effect.executions == []
    link = f"/workspace/approvals/{item['id']}"
    for decider in (cast.approver_a, cast.admin, cast.admin_2):
        assert _notified(conn, decider) == [("approval.requested", link)]
    for bystander in (cast.member_a, cast.member_b, cast.approver_b):
        assert _notified(conn, bystander) == []
    assert _actions(conn) == ["approval.requested"]
    stored = conn.execute("SELECT payload_json FROM approvals WHERE id = ?", (item["id"],)).fetchone()
    assert json.loads(stored[0]) == {"department_id": cast.dept_a, "label": "raport"}


def test_validation_errors_store_nothing(conn, cast, effect):
    with pytest.raises(WorkspaceError) as caught:
        _request(conn, cast.member_a, cast.dept_b)
    assert caught.value.code == "not_found"
    with pytest.raises(WorkspaceError) as caught:
        asyncio.run(approvals.request(conn, cast.member_a, DEPT_KIND, ["not", "an", "object"]))
    assert (caught.value.code, caught.value.extra["field"]) == ("invalid_request", "payload")
    with pytest.raises(WorkspaceError) as caught:
        asyncio.run(approvals.request(conn, cast.member_a, "no.such.kind", {}))
    assert (caught.value.code, caught.value.status) == ("unknown_kind", 400)
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    assert _actions(conn) == []


def test_nobody_else_to_decide_is_refused_up_front(ws, effect):
    conn = db.connect()
    seed_org(conn)
    dept = make_department(conn, "Unic")
    solo_admin = make_user(conn, role="admin", department_ids=[dept])
    with pytest.raises(WorkspaceError) as caught:
        _request(conn, solo_admin, dept)
    assert (caught.value.code, caught.value.status) == ("no_eligible_approver", 409)
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    member = make_user(conn, role="member", department_ids=[dept])
    assert _request(conn, member, dept)["status"] == "pending"
    conn.close()


def test_the_same_open_request_is_not_stored_twice(conn, cast, effect):
    first = _request(conn, cast.member_a, cast.dept_a)
    with pytest.raises(WorkspaceError) as caught:
        _request(conn, cast.approver_a, cast.dept_a)
    assert (caught.value.code, caught.value.extra["approval_id"]) == ("already_requested", first["id"])
    assert _request(conn, cast.member_a, cast.dept_a, label="altul")["status"] == "pending"


# ── four eyes ────────────────────────────────────────────────────────────────────────

def test_nobody_decides_their_own_request(conn, cast, effect):
    own = _request(conn, cast.approver_a, cast.dept_a)
    with pytest.raises(WorkspaceError) as caught:
        _decide(conn, cast.approver_a, own["id"])
    assert (caught.value.code, caught.value.status) == ("forbidden", 403)
    admin_own = _request(conn, cast.admin, cast.dept_a, label="admin")
    with pytest.raises(WorkspaceError) as caught:
        _decide(conn, cast.admin, admin_own["id"])
    assert caught.value.code == "forbidden"
    assert effect.executions == []
    assert _decide(conn, cast.admin_2, admin_own["id"])["status"] == "approved"
    assert _decide(conn, cast.admin, own["id"])["status"] == "approved"


def test_no_decision_across_departments_or_without_the_role(conn, cast, effect):
    item = _request(conn, cast.member_a, cast.dept_a)
    for outsider in (cast.approver_b, cast.member_b):
        with pytest.raises(WorkspaceError) as caught:
            _decide(conn, outsider, item["id"])
        assert (caught.value.code, caught.value.status) == ("not_found", 404)
        with pytest.raises(WorkspaceError):
            approvals.detail_json(conn, outsider, item["id"])
    colleague = make_user(conn, role="member", department_ids=[cast.dept_a])
    with pytest.raises(WorkspaceError) as caught:
        _decide(conn, colleague, item["id"])
    assert caught.value.code == "not_found"
    assert effect.executions == []
    assert conn.execute("SELECT status FROM approvals").fetchone()[0] == "pending"


def test_admin_rule_kinds_are_for_admins_and_an_admins_own_request_runs_at_once(conn, cast,
                                                                               effect):
    item = _request(conn, cast.member_a, cast.dept_a, kind=ADMIN_KIND)
    with pytest.raises(WorkspaceError) as caught:
        _decide(conn, cast.approver_a, item["id"])
    assert caught.value.code == "not_found"
    assert _notified(conn, cast.approver_a) == []
    immediate = _request(conn, cast.admin, cast.dept_a, label="acum", kind=ADMIN_KIND)
    assert immediate["status"] == "approved"
    assert immediate["decider"]["id"] == cast.admin.id
    # No English marker in stored user-facing data: the note column stays empty, and the
    # audit row of the approval says it was an admin's immediate action.
    assert immediate["decision_note"] is None
    assert conn.execute("SELECT decision_note FROM approvals WHERE id = ?",
                        (immediate["id"],)).fetchone()[0] is None
    approved = conn.execute(
        "SELECT details_json FROM audit WHERE action = 'approval.approved' AND target_id = ?",
        (str(immediate["id"]),)).fetchone()
    assert json.loads(approved[0]) == {"kind": ADMIN_KIND, "immediate": True,
                                       "note": approvals.ADMIN_ACTION_NOTE}
    assert immediate["result"] == {"done": "acum"}
    assert effect.executions == [{"approval_id": immediate["id"],
                                  "payload": {"department_id": cast.dept_a, "label": "acum"},
                                  "requester": cast.admin.id, "decider": cast.admin.id}]
    assert _notified(conn, cast.admin_2) == [("approval.requested", f"/workspace/approvals/{item['id']}")]
    assert _actions(conn)[-3:] == ["approval.requested", "approval.approved", "approval.executed"]


def test_an_admins_department_rule_request_still_needs_someone_else(conn, cast, effect):
    item = _request(conn, cast.admin, cast.dept_a)
    assert item["status"] == "pending" and effect.executions == []


# ── deciding ─────────────────────────────────────────────────────────────────────────

def test_approve_executes_once_records_the_result_and_tells_the_requester(conn, cast, effect):
    item = _request(conn, cast.member_a, cast.dept_a)
    decided = _decide(conn, cast.approver_a, item["id"], note="De acord.")
    assert decided["status"] == "approved" and decided["result"] == {"done": "raport"}
    assert decided["decider"]["id"] == cast.approver_a.id and decided["decision_note"] == "De acord."
    assert decided["can_decide"] is False and decided["can_cancel"] is False
    assert len(effect.executions) == 1 and effect.validations == 2
    assert _notified(conn, cast.member_a) == [("approval.approved",
                                               f"/workspace/approvals/{item['id']}")]
    assert _actions(conn) == ["approval.requested", "approval.approved", "approval.executed"]
    with pytest.raises(WorkspaceError) as caught:
        _decide(conn, cast.admin, item["id"])
    assert (caught.value.code, caught.value.extra["current_status"]) == ("already_decided", "approved")
    assert audit.verify_chain(conn)["ok"]


def test_reject_closes_the_request_with_the_note(conn, cast, effect):
    item = _request(conn, cast.member_a, cast.dept_a)
    decided = _decide(conn, cast.admin, item["id"], decision="reject", note="Nu acum.")
    assert decided["status"] == "rejected" and decided["decision_note"] == "Nu acum."
    assert effect.executions == [] and effect.closed == [(item["id"], "rejected")]
    body = conn.execute("SELECT body FROM notifications WHERE user_id = ? AND kind = "
                        "'approval.rejected'", (cast.member_a.id,)).fetchone()[0]
    assert body == f"Test raport\n{cast.admin.name}: Nu acum."
    with pytest.raises(WorkspaceError) as caught:
        _decide(conn, cast.approver_a, item["id"], decision="reject")
    assert caught.value.extra["current_status"] == "rejected"


def test_an_invalid_decision_word_is_refused(conn, cast, effect):
    item = _request(conn, cast.member_a, cast.dept_a)
    with pytest.raises(WorkspaceError) as caught:
        _decide(conn, cast.approver_a, item["id"], decision="maybe")
    assert caught.value.extra["field"] == "decision"


async def test_two_deciders_at_once_yield_one_execution(ws, cast, effect):
    setup = db.connect()
    item = await approvals.request(setup, cast.member_a, DEPT_KIND,
                                   {"department_id": cast.dept_a, "label": "dublu"})
    first, second = db.connect(), db.connect()
    try:
        outcomes = await asyncio.gather(
            approvals.decide(first, cast.approver_a, item["id"], decision="approve", note=""),
            approvals.decide(second, cast.admin, item["id"], decision="approve", note=""),
            return_exceptions=True)
    finally:
        first.close()
        second.close()
    errors = [o for o in outcomes if isinstance(o, WorkspaceError)]
    results = [o for o in outcomes if isinstance(o, dict)]
    assert len(results) == 1 and results[0]["status"] == "approved"
    assert len(errors) == 1 and errors[0].code == "already_decided"
    assert len(effect.executions) == 1
    assert [a for a in _actions(setup) if a == "approval.executed"] == ["approval.executed"]
    setup.close()


def test_an_expired_request_cannot_be_decided_or_cancelled(conn, cast, effect, monkeypatch):
    clock = freeze_clock(monkeypatch, 1_800_000_000)
    item = _request(conn, cast.member_a, cast.dept_a)
    clock.advance(approvals.APPROVAL_TTL_SECONDS + 1)
    shown = approvals.detail_json(conn, cast.approver_a, item["id"])
    assert shown["status"] == "expired" and shown["can_decide"] is False
    assert shown["can_cancel"] is False
    with pytest.raises(WorkspaceError) as caught:
        _decide(conn, cast.approver_a, item["id"])
    assert (caught.value.code, caught.value.extra["current_status"]) == ("already_decided", "expired")
    with pytest.raises(WorkspaceError) as caught:
        approvals.cancel(conn, cast.member_a, item["id"])
    assert caught.value.code == "already_decided"
    assert effect.executions == []


def test_revalidation_against_the_current_state_fails_the_approval(conn, cast, effect):
    item = _request(conn, cast.member_a, cast.dept_a)
    conn.execute("DELETE FROM user_departments WHERE user_id = ?", (cast.member_a.id,))
    decided = _decide(conn, cast.approver_a, item["id"])
    assert (decided["status"], decided["error_code"]) == ("failed", "not_found")
    assert effect.executions == [] and effect.closed == [(item["id"], "failed")]
    assert _notified(conn, cast.member_a)[-1][0] == "approval.failed"
    assert _actions(conn)[-2:] == ["approval.approved", "approval.failed"]


def test_a_disabled_requesters_approval_never_executes(conn, cast, effect):
    item = _request(conn, cast.member_a, cast.dept_a)
    conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (cast.member_a.id,))
    decided = _decide(conn, cast.approver_a, item["id"])
    assert (decided["status"], decided["error_code"]) == ("failed", "requester_inactive")
    assert effect.executions == []


def test_effect_failures_end_as_failed_approvals(conn, cast, effect, caplog):
    effect.fail = WorkspaceError("smtp_failed", "down", 502)
    first = _request(conn, cast.member_a, cast.dept_a, label="unu")
    assert _decide(conn, cast.approver_a, first["id"])["error_code"] == "smtp_failed"
    effect.fail = RuntimeError("bug")
    second = _request(conn, cast.member_a, cast.dept_a, label="doi")
    with caplog.at_level(logging.ERROR, logger="nerva.workspace.approvals"):
        decided = _decide(conn, cast.approver_a, second["id"])
    assert (decided["status"], decided["error_code"]) == ("failed", "execution_failed")
    assert "the test.department_effect effect raised" in caplog.text
    assert effect.closed == [(first["id"], "failed"), (second["id"], "failed")]


def test_a_kind_whose_module_is_gone_cannot_be_decided(conn, cast, effect, monkeypatch):
    item = _request(conn, cast.member_a, cast.dept_a)
    monkeypatch.delitem(effects_api._REGISTRY, DEPT_KIND)
    shown = approvals.detail_json(conn, cast.admin, item["id"])
    assert shown["can_decide"] is False and shown["eligible_deciders"] == []
    with pytest.raises(WorkspaceError) as caught:
        _decide(conn, cast.admin, item["id"])
    assert caught.value.code == "unknown_kind"


# ── cancelling ───────────────────────────────────────────────────────────────────────

def test_only_the_requester_cancels_and_only_while_pending(conn, cast, effect):
    item = _request(conn, cast.member_a, cast.dept_a)
    with pytest.raises(WorkspaceError) as caught:
        approvals.cancel(conn, cast.admin, item["id"])
    assert (caught.value.code, caught.value.status) == ("forbidden", 403)
    with pytest.raises(WorkspaceError) as caught:
        approvals.cancel(conn, cast.member_b, item["id"])
    assert caught.value.code == "not_found"
    cancelled = approvals.cancel(conn, cast.member_a, item["id"])
    assert cancelled["status"] == "cancelled" and effect.closed == [(item["id"], "cancelled")]
    with pytest.raises(WorkspaceError) as caught:
        approvals.cancel(conn, cast.member_a, item["id"])
    assert (caught.value.code, caught.value.extra["current_status"]) == ("already_decided", "cancelled")
    with pytest.raises(WorkspaceError):
        _decide(conn, cast.approver_a, item["id"])


def test_cancel_superseded_withdraws_only_pending_requests(conn, cast, effect):
    pending = _request(conn, cast.member_a, cast.dept_a, label="p")
    done = _request(conn, cast.member_a, cast.dept_a, label="d")
    _decide(conn, cast.approver_a, done["id"], decision="reject")
    assert approvals.cancel_superseded(conn, [pending["id"], done["id"], 999], actor=cast.member_a,
                                       reason="superseded") == [pending["id"]]
    details = json.loads(conn.execute("SELECT details_json FROM audit WHERE action = "
                                      "'approval.cancelled'").fetchone()[0])
    assert details == {"kind": DEPT_KIND, "reason": "superseded"}
    assert effect.closed == [(done["id"], "rejected")]
    # The withdrawn request says why (the UI words it); the rejected one is untouched.
    rows = dict(conn.execute("SELECT id, error_code FROM approvals WHERE id IN (?, ?)",
                             (pending["id"], done["id"])).fetchall())
    assert rows == {pending["id"]: "superseded", done["id"]: None}


def test_a_request_the_requester_cancels_carries_no_withdrawal_reason(conn, cast, effect):
    """The UI tells "you cancelled it" from "a change withdrew it" by error_code."""
    item = _request(conn, cast.member_a, cast.dept_a, label="own")
    cancelled = approvals.cancel(conn, cast.member_a, item["id"])
    assert (cancelled["status"], cancelled["error_code"]) == ("cancelled", None)
    other = _request(conn, cast.member_a, cast.dept_a, label="moved")
    approvals.cancel_superseded(conn, [other["id"]], actor=cast.admin, reason="report_deleted")
    shown = approvals.detail_json(conn, cast.member_a, other["id"])
    assert (shown["status"], shown["error_code"]) == ("cancelled", "report_deleted")


# ── listing ──────────────────────────────────────────────────────────────────────────

def test_boxes_show_each_person_what_they_may_see(conn, cast, effect):
    a = _request(conn, cast.member_a, cast.dept_a, label="a")
    b = _request(conn, cast.member_b, cast.dept_b, label="b")
    admin_kind = _request(conn, cast.member_a, cast.dept_a, label="adm", kind=ADMIN_KIND)
    own = _request(conn, cast.approver_a, cast.dept_a, label="own")

    def ids(user, box="inbox", status=None):
        return [i["id"] for i in approvals.list_items(conn, user, box=box, status=status)["items"]]

    assert ids(cast.approver_a) == [a["id"]]
    assert ids(cast.approver_b) == [b["id"]]
    assert ids(cast.member_a) == []
    assert ids(cast.admin) == [own["id"], admin_kind["id"], b["id"], a["id"]]
    assert ids(cast.member_a, "mine") == [admin_kind["id"], a["id"]]
    assert ids(cast.admin, "all") == [own["id"], admin_kind["id"], b["id"], a["id"]]
    with pytest.raises(WorkspaceError) as caught:
        ids(cast.approver_a, "all")
    assert caught.value.code == "forbidden"
    listing = approvals.list_items(conn, cast.approver_a, box="inbox", status=None)
    assert listing["pending_inbox_count"] == 1 and listing["items"][0]["can_decide"] is True
    _decide(conn, cast.approver_a, a["id"], decision="reject")
    assert ids(cast.approver_a) == [a["id"]]  # decided by them: kept as history
    assert ids(cast.approver_a, status="pending") == []
    assert approvals.pending_inbox_count(conn, _user(conn, cast.approver_a)) == 0
    with pytest.raises(WorkspaceError):
        approvals.list_items(conn, cast.admin, box="outbox", status=None)


def test_detail_names_the_people_who_could_decide(conn, cast, effect):
    item = _request(conn, cast.member_a, cast.dept_a)
    detail = approvals.detail_json(conn, cast.member_a, item["id"])
    assert sorted(p["id"] for p in detail["eligible_deciders"]) == sorted(
        [cast.approver_a.id, cast.admin.id, cast.admin_2.id])
    _decide(conn, cast.approver_a, item["id"])
    assert approvals.detail_json(conn, cast.approver_a, item["id"])["eligible_deciders"] == []


def test_eligible_counts_others_and_flags_immediate_admin_actions(conn, cast, effect):
    assert approvals.eligible(conn, cast.member_a, DEPT_KIND, cast.dept_a) == {
        "count": 3, "immediate": False}
    assert approvals.eligible(conn, cast.approver_a, DEPT_KIND, cast.dept_a)["count"] == 2
    assert approvals.eligible(conn, cast.admin, ADMIN_KIND, None) == {"count": 1,
                                                                      "immediate": True}
    with pytest.raises(WorkspaceError) as caught:
        approvals.eligible(conn, cast.member_a, DEPT_KIND, cast.dept_b)
    assert caught.value.code == "not_found"
    with pytest.raises(WorkspaceError) as caught:
        approvals.eligible(conn, cast.member_a, "nope", None)
    assert caught.value.code == "unknown_kind"


# ── sweeps ───────────────────────────────────────────────────────────────────────────

def test_expire_due_and_fail_stale_executing(conn, cast, effect, monkeypatch):
    clock = freeze_clock(monkeypatch, 1_800_000_000)
    old = _request(conn, cast.member_a, cast.dept_a, label="vechi")
    stuck = _request(conn, cast.member_a, cast.dept_a, label="blocat")
    conn.execute("UPDATE approvals SET status = 'executing', decided_by = ?, decided_at = ? "
                 "WHERE id = ?", (cast.approver_a.id, clock.current, stuck["id"]))
    assert approvals.expire_due(conn, clock.current) == 0
    assert approvals.fail_stale_executing(conn, clock.current + 599) == 0
    assert approvals.fail_stale_executing(conn, clock.current + 600) == 1
    clock.advance(approvals.APPROVAL_TTL_SECONDS)
    assert approvals.expire_due(conn, clock.current) == 1
    assert approvals.expire_due(conn, clock.current) == 0
    rows = dict(conn.execute("SELECT id, status || ':' || COALESCE(error_code, '') FROM approvals"))
    assert rows == {old["id"]: "expired:", stuck["id"]: "failed:interrupted"}
    assert effect.closed == [(stuck["id"], "failed"), (old["id"], "expired")]
    kinds = [k for k, _ in _notified(conn, cast.member_a)]
    assert kinds == ["approval.failed", "approval.expired"]
    actors = conn.execute("SELECT actor_email FROM audit WHERE action IN "
                          "('approval.expired', 'approval.failed')").fetchall()
    assert [a[0] for a in actors] == ["scheduler", "scheduler"]
