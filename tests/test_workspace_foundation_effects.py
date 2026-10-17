"""The approval effect registry and decider eligibility (spec §5 effects_api.py)."""

from __future__ import annotations

import dataclasses

import pytest

from agents.core.workspace import effects_api
from agents.core.workspace.effects_api import EffectSpec, ValidatedRequest
from agents.core.workspace.errors import WorkspaceError
from tests.support.workspace_fixtures import db, make_user, seed_company, ws  # noqa: F401


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch):
    monkeypatch.setattr(effects_api, "_REGISTRY", {})


def _validate(conn, user, payload) -> ValidatedRequest:
    return ValidatedRequest(department_id=payload.get("department_id"), summary="s", payload=payload)


async def _execute(approval, requester, decider) -> dict:
    return {"done": True, "by": decider.id}


def _spec(kind="report.delivery", rule="department") -> EffectSpec:
    return EffectSpec(kind=kind, validate=_validate, execute=_execute, decider_rule=rule)


def test_register_get_and_list():
    effects_api.register_effect(_spec("b.kind"))
    effects_api.register_effect(_spec("a.kind", "admin"))
    assert effects_api.kinds() == ["a.kind", "b.kind"]
    assert effects_api.get_effect("a.kind").decider_rule == "admin"


def test_registering_again_replaces():
    effects_api.register_effect(_spec("x"))
    effects_api.register_effect(_spec("x", "admin"))
    assert effects_api.kinds() == ["x"] and effects_api.get_effect("x").decider_rule == "admin"


def test_default_rule_is_department():
    assert EffectSpec(kind="k", validate=_validate, execute=_execute).decider_rule == "department"


@pytest.mark.parametrize("bad", [_spec(rule="anyone"), dataclasses.replace(_spec(), kind="")])
def test_invalid_specs_are_refused(bad):
    with pytest.raises(ValueError):
        effects_api.register_effect(bad)
    assert effects_api.kinds() == []


def test_unknown_kind():
    with pytest.raises(WorkspaceError) as caught:
        effects_api.get_effect("nope")
    assert (caught.value.status, caught.value.code, caught.value.extra) == (400, "unknown_kind",
                                                                            {"kind": "nope"})


async def test_specs_validate_and_execute(ws):
    conn = db()
    company = seed_company(conn)
    spec = _spec()
    effects_api.register_effect(spec)
    validated = effects_api.get_effect(spec.kind).validate(conn, company.member_a,
                                                           {"department_id": company.dept_a})
    assert validated.department_id == company.dept_a
    result = await spec.execute({"id": 1, "payload": validated.payload}, company.member_a,
                                company.approver_a)
    assert result == {"done": True, "by": company.approver_a.id}


def test_eligible_deciders(ws):
    conn = db()
    company = seed_company(conn)
    dept_rule, admin_rule = _spec(), _spec("doc.publish", "admin")
    assert effects_api.eligible_decider_ids(conn, dept_rule, company.dept_a,
                                            exclude=company.member_a.id) == sorted(
        [company.admin.id, company.approver_a.id])
    assert effects_api.eligible_decider_ids(conn, dept_rule, company.dept_a,
                                            exclude=company.approver_a.id) == [company.admin.id]
    assert effects_api.eligible_decider_ids(conn, admin_rule, company.dept_a) == [company.admin.id]
    assert effects_api.eligible_decider_ids(conn, dept_rule, None) == [company.admin.id]
    assert effects_api.eligible_decider_ids(conn, admin_rule, company.dept_a,
                                            exclude=company.admin.id) == []


def test_can_decide(ws):
    conn = db()
    company = seed_company(conn)
    disabled_admin = make_user(conn, role="admin", department_ids=[company.dept_a], status="disabled")
    dept_rule, admin_rule = _spec(), _spec("doc.publish", "admin")
    requester = company.member_a.id
    assert effects_api.can_decide(company.approver_a, dept_rule, company.dept_a, requester)
    assert not effects_api.can_decide(company.approver_a, dept_rule, company.dept_b, requester)
    assert not effects_api.can_decide(company.member_b, dept_rule, company.dept_b, requester)
    assert effects_api.can_decide(company.admin, dept_rule, company.dept_b, requester)
    assert not effects_api.can_decide(company.approver_a, admin_rule, company.dept_a, requester)
    assert effects_api.can_decide(company.admin, admin_rule, company.dept_a, requester)
    assert not effects_api.can_decide(company.admin, dept_rule, company.dept_a, company.admin.id), \
        "never one's own request"
    assert not effects_api.can_decide(disabled_admin, dept_rule, company.dept_a, requester)
    assert not effects_api.can_decide(company.approver_a, dept_rule, None, requester)
