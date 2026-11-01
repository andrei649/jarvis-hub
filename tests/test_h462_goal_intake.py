"""H462 — the owner's door to a goal: the text, the commands, the routes, the CLI.

Before H462 nothing called ``goal_contract.propose``: no command, route, CLI verb or
HUD control created a goal. These pin the surfaces that now do, and the criteria an
owner can add to a running goal:

  · the goal text uses the five-field completion contract through a CLOSED alias
    table — an incidental colon is headline text, never a field;
  · every field lands on a field the contract already requires, and nothing widens
    it: no scope and no plan is refused, never defaulted to unrestricted;
  · the budget defaults to Hermes' 20 turns, as 20 steps;
  · proposing refuses with company mode off and on a kernel DENY, and enqueues nothing;
  · ``/goal`` and ``/subgoal`` answer only the owner;
  · a criterion added mid-run resets nothing, is refused once grading started, and
    the verifier (and the judge's rubric) see it;
  · ``POST /api/company/goals`` is admin-guarded and opens no run;
    ``POST /api/company/runs/{id}/subgoals`` is user-guarded like stop;
  · ``nerva goal propose`` / ``nerva goal subgoal`` post exactly that.

Hermetic: a recording governed intake, an in-memory ledger, a fake hub.
"""

from __future__ import annotations

import io
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents"))

from agents.core.autonomy import goal_intake  # noqa: E402
from agents.core.autonomy.goal_contract import GoalContractError  # noqa: E402
from agents.core.autonomy.goal_intake import (  # noqa: E402
    CONTRACT_ALIASES,
    CONTRACT_FIELDS,
    DEFAULT_MAX_STEPS,
    DEFAULT_STOP,
    draft_from_text,
    parse_goal_text,
    propose_goal,
    subgoal_target,
)
from agents.core.autonomy.work_runs import MAX_SUBGOALS, WorkRunError, WorkRunLedger  # noqa: E402
from agents.core.commands import Principal, build_default_registry  # noqa: E402

NOW = 1_000_000.0
OWNER = Principal(channel="telegram", sender="42", admin=True)
GUEST = Principal(channel="telegram", sender="7", admin=False)

GOAL = (
    "Prepare the quarterly brief\n"
    "verify: the brief is in docs/\n"
    "scope: research, write\n"
    "step: research: read the Q3 figures\n"
    "must not: touch the ledger\n"
    "stop when: the figures are missing"
)


# ── the text ─────────────────────────────────────────────────────────────────

def test_the_alias_table_is_hermes_closed_table_onto_five_fields():
    assert CONTRACT_FIELDS == ("outcome", "verification", "constraints", "boundaries", "stop_when")
    assert set(CONTRACT_ALIASES.values()) == set(CONTRACT_FIELDS)
    assert {k for k, v in CONTRACT_ALIASES.items() if v == "verification"} == {
        "verification", "verify", "verified by", "evidence", "proof"}
    assert {k for k, v in CONTRACT_ALIASES.items() if v == "stop_when"} == {
        "stop when", "stop_when", "blocked", "stop if blocked", "give up when"}
    assert len(CONTRACT_ALIASES) == 24


@pytest.mark.parametrize("alias,field", sorted(CONTRACT_ALIASES.items()))
def test_every_alias_is_recognised_at_the_start_of_a_line(alias, field):
    parsed = parse_goal_text(f"Ship it\n{alias.upper()}: the value")
    assert parsed.get(field) == ("the value",)
    assert parsed.headline == "Ship it"


def test_an_incidental_colon_is_headline_text_never_a_field():
    parsed = parse_goal_text("Fix bug: the parser drops commas\nsee http://example.test")
    assert parsed.fields == {}
    assert parsed.headline == "Fix bug: the parser drops commas see http://example.test"


def test_every_field_lands_on_a_field_the_contract_already_requires():
    draft = draft_from_text(GOAL + "\noutcome: one brief in docs/\nverify: a reviewer signs it",
                            now=NOW, requested_by="telegram:42")
    assert draft.title == "Prepare the quarterly brief"
    assert draft.deliverable == "one brief in docs/"
    assert [(c.id, c.describe, c.required, c.probe_ref) for c in draft.checks] == [
        ("verify-1", "the brief is in docs/", True, ""),
        ("verify-2", "a reviewer signs it", True, ""),
    ]
    assert draft.scope_kinds == ("research", "write") and draft.unrestricted is False
    assert draft.stop_conditions == (
        "the figures are missing", "continuing would break a constraint: touch the ledger")
    assert [(r["kind"], r["summary"]) for r in draft.plan] == [("research", "read the Q3 figures")]
    assert draft.plan[0]["task"]["kind"] == "research"
    assert draft.budget.max_steps == DEFAULT_MAX_STEPS == 20
    assert draft.deadline_at == NOW + 24 * 3600
    assert draft.requested_by == "telegram:42"


def test_with_no_verification_the_outcome_itself_is_the_one_unprobed_check():
    draft = draft_from_text("Tidy the docs\nscope: unrestricted", now=NOW)
    assert [(c.id, c.probe_ref) for c in draft.checks] == [("outcome", "")]
    assert draft.stop_conditions == (DEFAULT_STOP,)
    assert draft.unrestricted is True and draft.plan == ()


def test_with_no_scope_the_scope_is_exactly_the_plan_s_own_kinds():
    draft = draft_from_text("Brief\nstep: research: read\nstep: write: draft\nstep: research: check",
                            now=NOW)
    assert draft.scope_kinds == ("research", "write")
    assert draft.unrestricted is False


@pytest.mark.parametrize("text,reason", [
    ("Prepare the brief", "scope_required_or_declare_unrestricted"),
    ("", "missing_title"),
    ("verify: x\nscope: research", "missing_title"),
    ("Brief\nscope: src/parser.py", "invalid_scope_kind"),
    ("Brief\nstep: read the figures", "invalid_plan_step"),
    ("Brief\nscope: research\nstep: write: draft", "plan_step_out_of_scope"),
    ("Brief\nscope: research, unrestricted", "scope_and_unrestricted_conflict"),
    ("x" * (goal_intake.MAX_TEXT + 1), "goal_text_too_long"),
])
def test_a_goal_that_does_not_say_enough_is_refused_never_widened(text, reason):
    with pytest.raises(GoalContractError) as exc:
        draft_from_text(text, now=NOW)
    assert exc.value.reason == reason


def test_a_plan_longer_than_twenty_rows_gets_a_budget_that_can_finish_it():
    rows = "\n".join(f"step: research: row {n}" for n in range(25))
    assert draft_from_text(f"Long\n{rows}", now=NOW).budget.max_steps == 25


# ── proposing ────────────────────────────────────────────────────────────────

class _Intake:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return 41


def _orch(intake=None, ledger=None):
    return types.SimpleNamespace(
        govern_enqueue=intake, autonomy=None, work_runs=ledger,
        commands=build_default_registry(),
    )


def test_proposing_with_company_mode_off_enqueues_nothing(monkeypatch):
    monkeypatch.delenv("JARVIS_COMPANY_MODE", raising=False)
    intake = _Intake()
    with pytest.raises(GoalContractError) as exc:
        propose_goal(_orch(intake), GOAL, now=NOW)
    assert exc.value.reason == "company_mode_off"
    assert intake.calls == []


def test_proposing_hands_the_card_to_the_governed_intake_as_an_ask(monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    intake = _Intake()
    result = propose_goal(_orch(intake), GOAL, requested_by="owner:api", now=NOW)
    assert result["task_id"] == 41
    [call] = intake.calls
    assert call["kind"] == "goal.approve" and call["autonomy_level"] == "ask"
    assert call["payload"]["title"] == "Prepare the quarterly brief"
    assert call["payload"]["requested_by"] == "owner:api"
    assert call["payload"]["fingerprint"]
    assert "plan: none" not in "\n".join(result["card"])


def test_proposing_with_no_intake_says_so(monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    with pytest.raises(GoalContractError) as exc:
        propose_goal(_orch(None), GOAL, now=NOW)
    assert exc.value.reason == "intake_unavailable"


def test_a_kernel_deny_refuses_before_the_intake_is_reached(monkeypatch):
    from agents.core.kernel import Decision, Verdict

    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel",
                        lambda orch: lambda action, capability=None: Decision(Verdict.DENY, reason="budget"))
    intake = _Intake()
    with pytest.raises(GoalContractError) as exc:
        propose_goal(_orch(intake), GOAL, now=NOW)
    assert exc.value.reason == "kernel_denied:budget"
    assert intake.calls == []
    assert "Action Kernel refused" in goal_intake.refusal_text(exc.value.reason)


# ── /goal and /subgoal ───────────────────────────────────────────────────────

@pytest.fixture
def ledger():
    led = WorkRunLedger(":memory:", clock=lambda: NOW)
    yield led
    led.close()


def _open(ledger, goal_id="g-1", title="Prepare the brief"):
    return ledger.open_run(types.SimpleNamespace(
        goal_id=goal_id, title=title, approved_by="receipt:owner", deadline_at=NOW + 3600))


async def test_goal_and_subgoal_are_owner_commands(monkeypatch, ledger):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    intake = _Intake()
    orch = _orch(intake, ledger)
    for text in (f"/goal {GOAL}", "/subgoal the brief has a summary"):
        outcome = await orch.commands.dispatch(text, orch=orch, principal=GUEST)
        assert outcome.status == "refused" and "owner command" in outcome.reply
    assert intake.calls == []
    assert {"goal", "subgoal"} <= {c.name for c in orch.commands.visible(OWNER)}
    assert not {"goal", "subgoal"} & {c.name for c in orch.commands.visible(GUEST)}


async def test_goal_in_chat_proposes_and_says_where_it_waits(monkeypatch, ledger):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    intake = _Intake()
    orch = _orch(intake, ledger)
    outcome = await orch.commands.dispatch(f"/goal {GOAL}", orch=orch, principal=OWNER)
    assert outcome.status == "answered"
    assert "as task 41" in outcome.reply and "decision inbox" in outcome.reply
    assert "check verify-1: the brief is in docs/" in outcome.reply
    assert intake.calls[0]["payload"]["requested_by"] == "telegram:42"
    assert ledger.list_runs() == []


async def test_goal_refusals_reach_the_owner_in_words(monkeypatch, ledger):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    orch = _orch(_Intake(), ledger)
    outcome = await orch.commands.dispatch("/goal Prepare the brief", orch=orch, principal=OWNER)
    assert outcome.reply.startswith("Not proposed: say what the run may do")
    monkeypatch.delenv("JARVIS_COMPANY_MODE")
    outcome = await orch.commands.dispatch(f"/goal {GOAL}", orch=orch, principal=OWNER)
    assert "company mode is off" in outcome.reply


async def test_a_goal_too_long_for_the_chat_is_refused_whole_never_cut(monkeypatch, ledger):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    intake = _Intake()
    orch = _orch(intake, ledger)
    text = "/goal Brief\nscope: research\n" + "must not: " + "x" * 2_100
    outcome = await orch.commands.dispatch(text, orch=orch, principal=OWNER)
    assert outcome.status == "refused"
    assert intake.calls == []


async def test_bare_goal_shows_the_usage_and_what_runs(ledger):
    run = _open(ledger)
    ledger.add_subgoal(run.id, "a summary")
    orch = _orch(None, ledger)
    outcome = await orch.commands.dispatch("/goal", orch=orch, principal=OWNER)
    assert outcome.reply.startswith("Usage: /goal")
    assert f"{run.id} · planning · Prepare the brief, 1 criteria added" in outcome.reply


async def test_subgoal_adds_to_the_only_running_goal_without_resetting_it(ledger):
    run = _open(ledger)
    orch = _orch(None, ledger)
    before = ledger.get(run.id)
    outcome = await orch.commands.dispatch("/subgoal the brief has a summary", orch=orch,
                                           principal=OWNER)
    assert "as subgoal:1" in outcome.reply
    after = ledger.get(run.id)
    assert after == before
    assert ledger.tampered(run.id) is False
    assert ledger.subgoals(run.id)[0]["by"] == "telegram:42"
    listed = await orch.commands.dispatch("/subgoal", orch=orch, principal=OWNER)
    assert "subgoal:1: the brief has a summary" in listed.reply


async def test_subgoal_with_several_running_goals_asks_which(ledger):
    one, two = _open(ledger, "g-1"), _open(ledger, "g-2", "Another")
    orch = _orch(None, ledger)
    outcome = await orch.commands.dispatch("/subgoal a summary", orch=orch, principal=OWNER)
    assert "Several goals are running" in outcome.reply
    assert ledger.subgoals(one.id) == ledger.subgoals(two.id) == []
    outcome = await orch.commands.dispatch(f"/subgoal {two.id} a summary", orch=orch,
                                           principal=OWNER)
    assert "as subgoal:1" in outcome.reply
    assert [s["describe"] for s in ledger.subgoals(two.id)] == ["a summary"]
    assert ledger.subgoals(one.id) == []


async def test_subgoal_naming_a_finished_run_is_refused_not_added_to_another(ledger):
    stopped, running = _open(ledger, "g-1"), _open(ledger, "g-2", "Another")
    ledger.request_stop(stopped.id)
    ledger.settle_stop(stopped.id)
    orch = _orch(None, ledger)
    outcome = await orch.commands.dispatch(f"/subgoal {stopped.id} a summary", orch=orch,
                                           principal=OWNER)
    assert outcome.reply == ("Not added: that run is stopped, and a criterion is added only "
                             "to a running goal.")
    assert ledger.subgoals(running.id) == ledger.subgoals(stopped.id) == []


async def test_subgoal_with_nothing_running_says_so(ledger):
    orch = _orch(None, ledger)
    outcome = await orch.commands.dispatch("/subgoal a summary", orch=orch, principal=OWNER)
    assert outcome.reply.startswith("No goal is running")


def test_subgoal_target_rules():
    a = types.SimpleNamespace(id="r1", status="working")
    b = types.SimpleNamespace(id="r2", status="blocked")
    done = types.SimpleNamespace(id="r3", status="succeeded")
    assert subgoal_target([a, done], "a summary") == (a, "a summary")
    assert subgoal_target([a, b], "r2 a summary") == (b, "a summary")
    assert subgoal_target([a, b], "a summary") == (None, "a summary")
    assert subgoal_target([done], "r3 a summary") == (None, "r3 a summary")


# ── the ledger's criteria ────────────────────────────────────────────────────

def test_a_criterion_is_refused_on_a_stopped_run_and_once_grading_started(ledger):
    run = _open(ledger)
    ledger.record_verdict(run.id, role="verifier", passed=False, reason="no probe")
    with pytest.raises(WorkRunError) as exc:
        ledger.add_subgoal(run.id, "a summary")
    assert exc.value.reason == "run_already_graded"

    other = _open(ledger, "g-2")
    ledger.request_stop(other.id)
    with pytest.raises(WorkRunError) as exc:
        ledger.add_subgoal(other.id, "a summary")
    assert exc.value.reason == "run_stopping"
    with pytest.raises(WorkRunError) as exc:
        ledger.add_subgoal("nope", "a summary")
    assert exc.value.reason == "unknown_run"


def test_criteria_are_bounded_and_survive_a_restart(tmp_path):
    led = WorkRunLedger(tmp_path / "w.db", clock=lambda: NOW)
    run = _open(led)
    for n in range(MAX_SUBGOALS):
        led.add_subgoal(run.id, f"criterion {n}")
    with pytest.raises(WorkRunError) as exc:
        led.add_subgoal(run.id, "one more")
    assert exc.value.reason == "too_many_subgoals"
    with pytest.raises(WorkRunError) as exc:
        led.add_subgoal(run.id, "   ")
    assert exc.value.reason == "missing_subgoal"
    led.close()
    again = WorkRunLedger(tmp_path / "w.db", clock=lambda: NOW)
    assert [s["id"] for s in again.subgoals(run.id)][-1] == f"subgoal:{MAX_SUBGOALS}"
    assert len(again.snapshot(run.id)["subgoals"]) == MAX_SUBGOALS
    again.close()


async def test_the_verifier_does_not_pass_a_run_while_a_criterion_is_unchecked(ledger):
    from agents.core.autonomy.work_verifier import Check, WorkVerifier

    run = _open(ledger)
    ledger.record_step(run.id, kind="research", summary="read", outcome="ok", task_id=5)
    checks = [Check(id="brief", describe="a brief", probe=lambda: True)]
    assert (await WorkVerifier(ledger).verify(run.id, checks, record=False)).passed is True
    ledger.add_subgoal(run.id, "a summary")
    report = await WorkVerifier(ledger).verify(run.id, checks, record=False)
    assert report.passed is False
    assert report.reason == "1 required check(s) had no probe: subgoal:1"
    probed = [*checks, Check(id="subgoal:1", describe="a summary", probe=lambda: False)]
    assert (await WorkVerifier(ledger).verify(run.id, probed, record=False)).reason.startswith(
        "1 check(s) failed: subgoal:1")


async def test_the_judge_rubric_sees_the_criteria_added(ledger):
    from agents.core.autonomy.work_judge import GoalTerms, WorkJudge

    run = _open(ledger)
    ledger.record_step(run.id, kind="research", summary="read", outcome="ok", task_id=5)
    ledger.add_subgoal(run.id, "a summary")
    ledger.record_verdict(run.id, role="verifier", passed=True, reason="ok")
    seen = []

    def rubric(view):
        seen.append(view)
        return {"passed": True}

    judge = WorkJudge(ledger, rubric=rubric)
    terms = GoalTerms(goal_id="g-1", title="Prepare the brief")
    await judge.wait_probe(run.id, terms)
    await judge.judge(run.id, terms, record=False)
    assert [(v["phase"], v["subgoals"]) for v in seen] == [
        ("wait_probe", ["a summary"]), ("settle", ["a summary"])]


def test_the_brief_lists_the_criteria_in_the_owner_s_words(ledger):
    from agents.core.autonomy.company_report import build_run_summary

    run = _open(ledger)
    ledger.add_subgoal(run.id, "a summary")
    assert build_run_summary(ledger.snapshot(run.id), now=NOW)["subgoals"] == ["a summary"]


# ── the routes ───────────────────────────────────────────────────────────────

def _client(ledger, monkeypatch, orch=None, *, admin_ok=True, user_ok=True):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from agents.core.routers import company as company_routes
    from agents.core.routers._deps import admin_guard, user_guard

    async def _get():
        return ledger

    async def _deny():
        raise HTTPException(status_code=401, detail="token required")

    monkeypatch.setattr(company_routes, "_get_ledger", _get)
    monkeypatch.setattr(company_routes, "get_orch", lambda: orch)
    app = FastAPI()
    app.include_router(company_routes.router)
    app.dependency_overrides[admin_guard] = (lambda: None) if admin_ok else _deny
    app.dependency_overrides[user_guard] = (lambda: None) if user_ok else _deny
    return TestClient(app)


def test_the_propose_route_is_admin_guarded(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    intake = _Intake()
    c = _client(ledger, monkeypatch, _orch(intake, ledger), admin_ok=False)
    assert c.post("/api/company/goals", json={"text": GOAL}).status_code == 401
    assert intake.calls == []


@pytest.mark.parametrize("env,text,status,reason", [
    (False, GOAL, 409, "company_mode_off"),
    (True, "Prepare the brief", 400, "scope_required_or_declare_unrestricted"),
])
def test_the_propose_route_refuses_in_the_contract_s_words(ledger, monkeypatch, env, text,
                                                           status, reason):
    if env:
        monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    else:
        monkeypatch.delenv("JARVIS_COMPANY_MODE", raising=False)
    intake = _Intake()
    reply = _client(ledger, monkeypatch, _orch(intake, ledger)).post(
        "/api/company/goals", json={"text": text})
    assert reply.status_code == status
    assert reply.json()["reason"] == reason and reply.json()["detail"]
    assert intake.calls == []


def test_the_propose_route_opens_no_run_and_returns_no_payload(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    intake = _Intake()
    reply = _client(ledger, monkeypatch, _orch(intake, ledger)).post(
        "/api/company/goals", json={"text": GOAL})
    assert reply.status_code == 200
    body = reply.json()
    assert set(body) == {"ok", "task_id", "title", "card"}
    assert body["task_id"] == 41
    assert ledger.list_runs() == []


def test_the_propose_route_without_an_orchestrator_is_unavailable(ledger, monkeypatch):
    monkeypatch.setenv("JARVIS_COMPANY_MODE", "1")
    reply = _client(ledger, monkeypatch, None).post("/api/company/goals", json={"text": GOAL})
    assert reply.status_code == 503


def test_the_subgoal_route_adds_a_criterion_and_refuses_honestly(ledger, monkeypatch):
    run = _open(ledger)
    c = _client(ledger, monkeypatch)
    reply = c.post(f"/api/company/runs/{run.id}/subgoals", json={"text": "a summary"})
    assert reply.status_code == 200
    assert reply.json()["subgoal"]["id"] == "subgoal:1"
    assert [s["describe"] for s in reply.json()["subgoals"]] == ["a summary"]
    assert ledger.get(run.id).status == "planning"
    assert c.post("/api/company/runs/nope/subgoals", json={"text": "x"}).status_code == 404
    assert c.post(f"/api/company/runs/{run.id}/subgoals", json={"text": ""}).status_code == 422
    ledger.record_verdict(run.id, role="verifier", passed=False, reason="r")
    graded = c.post(f"/api/company/runs/{run.id}/subgoals", json={"text": "more"})
    assert graded.status_code == 409 and graded.json()["reason"] == "run_already_graded"


def test_the_subgoal_route_is_user_guarded(ledger, monkeypatch):
    run = _open(ledger)
    c = _client(ledger, monkeypatch, user_ok=False)
    assert c.post(f"/api/company/runs/{run.id}/subgoals", json={"text": "x"}).status_code == 401
    assert ledger.subgoals(run.id) == []


# ── the CLI ──────────────────────────────────────────────────────────────────

def _cli(argv, routes, stdin=""):
    from agents.cli.nerva import Context, main
    from tests.test_nerva_cli import _FakeHub

    hub = _FakeHub(routes)
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(stdin),
                  client_factory=lambda env: hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue(), hub


def test_nerva_goal_propose_posts_one_line_per_argument():
    code, out, _err, hub = _cli(
        ["goal", "propose", "Prepare the brief", "scope: research", "verify: brief in docs/"],
        {"POST /api/company/goals": {"ok": True, "task_id": 9, "card": ["goal: Prepare the brief"]}})
    assert code == 0
    assert hub.calls == [("POST", "/api/company/goals",
                          {"text": "Prepare the brief\nscope: research\nverify: brief in docs/"})]
    assert "proposed as task 9" in out and "  goal: Prepare the brief" in out


def test_nerva_goal_propose_reads_stdin_for_dash():
    code, _out, _err, hub = _cli(["goal", "propose", "-"],
                                 {"POST /api/company/goals": {"ok": True, "task_id": 3}},
                                 stdin="Brief\n\nscope: unrestricted\n")
    assert code == 0
    assert hub.calls[0][2] == {"text": "Brief\nscope: unrestricted"}


def test_nerva_goal_subgoal_posts_the_criterion():
    code, out, _err, hub = _cli(
        ["goal", "subgoal", "r1", "the", "brief", "has", "a", "summary"],
        {"POST /api/company/runs/r1/subgoals": {
            "ok": True, "subgoal": {"id": "subgoal:1", "describe": "the brief has a summary"}}})
    assert code == 0
    assert hub.calls == [("POST", "/api/company/runs/r1/subgoals",
                          {"text": "the brief has a summary"})]
    assert out.strip() == "added subgoal:1: the brief has a summary"
    code, _out, err, _hub = _cli(["goal", "subgoal", "../x", "c"], {})
    assert code == 2 and "not a run id" in err
