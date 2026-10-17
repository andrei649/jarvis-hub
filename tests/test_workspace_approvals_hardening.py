"""Regression tests for the approvals defects the independent S4 review found.

* A pending request past its expiry is *shown* as ``expired`` before the scheduler
  rewrites it, but the ``status`` filter compared the stored value: ``?status=pending``
  listed requests that read as expired and nobody can decide, ``?status=expired`` missed
  them. The filters now compare the effective status.
* An admin's own admin-rule request executes at once and skipped the duplicate check,
  so a double click started a second execution of an effect the first was still
  carrying out (ending as a spurious failed approval). It is refused with
  ``409 already_requested`` like any other open duplicate.
* An effect that finished after the stale-execution sweep had already failed its row
  (``interrupted``) still told the requester "approved", contradicting the row and the
  "failed" notice they had just received. The late finish is now audit-only.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from agents.core.workspace import approvals, db, effects_api
from agents.core.workspace.effects_api import EffectSpec
from agents.core.workspace.errors import WorkspaceError
from tests.support.workspace_fixtures import freeze_clock, ws  # noqa: F401  (ws is a fixture)
from tests.test_workspace_approvals_engine import (  # noqa: F401  (fixtures)
    ADMIN_KIND,
    DEPT_KIND,
    effect,
)
from tests.test_workspace_reports_support import cast, signed_in  # noqa: F401  (a fixture)

START = 1_790_000_000.0


@pytest.fixture
def clock(ws, monkeypatch):
    return freeze_clock(monkeypatch, START)


@pytest.fixture
def conn(clock):
    connection = db.connect()
    yield connection
    connection.close()


def _ids(client, query: str) -> list[int]:
    response = client.get(f"/api/workspace/approvals?{query}")
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_status_filters_follow_the_status_people_see(conn, cast, effect, clock):
    lapsing, _ = approvals.create_request(conn, cast.member_a, DEPT_KIND,
                                          {"department_id": cast.dept_a, "label": "veche"})
    clock.advance(approvals.APPROVAL_TTL_SECONDS - 60)
    fresh, _ = approvals.create_request(conn, cast.member_a, DEPT_KIND,
                                        {"department_id": cast.dept_a, "label": "noua"})
    clock.advance(120)  # the first is past its expiry; no scheduler tick has run
    assert conn.execute("SELECT status FROM approvals WHERE id = ?", (lapsing,)).fetchone()[0] == (
        "pending")
    member, _ = signed_in(cast.member_a)
    approver, _ = signed_in(cast.approver_a)
    admin, _ = signed_in(cast.admin)
    for client, box in ((member, "mine"), (approver, "inbox"), (admin, "all")):
        assert _ids(client, f"box={box}&status=pending") == [fresh], box
        assert _ids(client, f"box={box}&status=expired") == [lapsing], box
        assert _ids(client, f"box={box}") == [fresh, lapsing], box
    listing = approver.get("/api/workspace/approvals?box=inbox&status=expired").json()
    assert listing["items"][0]["status"] == "expired" and listing["pending_inbox_count"] == 1


def test_an_admins_double_click_does_not_execute_twice(conn, cast, effect):
    payload = {"department_id": cast.dept_a, "label": "partajare"}
    first, immediate = approvals.create_request(conn, cast.admin, ADMIN_KIND, payload)
    assert immediate is True  # stored 'executing'; its effect is still being carried out
    with pytest.raises(WorkspaceError) as caught:
        asyncio.run(approvals.request(conn, cast.admin, ADMIN_KIND, payload))
    assert (caught.value.code, caught.value.status, caught.value.extra) == (
        "already_requested", 409, {"approval_id": first})
    assert effect.executions == []
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1


def test_once_finished_the_same_admin_action_can_be_asked_again(conn, cast, effect):
    admin, headers = signed_in(cast.admin)
    body = {"kind": ADMIN_KIND, "payload": {"department_id": cast.dept_a, "label": "din nou"}}
    first = admin.post("/api/workspace/approvals", json=body, headers=headers)
    second = admin.post("/api/workspace/approvals", json=body, headers=headers)
    assert [first.json()["status"], second.json()["status"]] == ["approved", "approved"]
    assert len(effect.executions) == 2


def test_an_effect_finishing_after_the_sweep_does_not_contradict_it(conn, cast, effect,
                                                                  monkeypatch):
    def late(approval, requester, decider):
        async def run() -> dict:
            sweep = db.connect()
            try:
                swept = approvals.fail_stale_executing(
                    sweep, db.now() + approvals.EXECUTING_TIMEOUT_SECONDS + 1)
            finally:
                sweep.close()
            assert swept == 1
            return {"done": "târziu"}
        return run()

    spec = effects_api.get_effect(DEPT_KIND)
    monkeypatch.setitem(effects_api._REGISTRY, DEPT_KIND, EffectSpec(
        kind=DEPT_KIND, validate=spec.validate, execute=late, decider_rule="department"))
    approval_id, _ = approvals.create_request(conn, cast.member_a, DEPT_KIND,
                                              {"department_id": cast.dept_a, "label": "lent"})
    item = asyncio.run(approvals.decide(conn, cast.approver_a, approval_id, decision="approve",
                                        note=""))
    assert (item["status"], item["error_code"], item["result"]) == ("failed", "interrupted", None)
    told = [r[0] for r in conn.execute("SELECT kind FROM notifications WHERE user_id = ? "
                                       "ORDER BY id", (cast.member_a.id,))]
    assert told == ["approval.failed"]
    executed = conn.execute("SELECT details_json FROM audit WHERE action = 'approval.executed'"
                            ).fetchone()
    assert json.loads(executed[0]) == {"kind": DEPT_KIND, "late": True}
