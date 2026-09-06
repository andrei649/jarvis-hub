"""E5.0 — the company brief: what the night shift did, told honestly.

A summary is where a long-running agent gets to be generous about itself, so the
tests here are all about the unflattering facts being the hardest ones to hide:

  · the headline is the verdict, never the effort — forty steps and no verdict is
    "unfinished", not "40 steps completed";
  · an unauthorised step is the FIRST thing said about a run, above what it
    achieved, and it leads the whole brief;
  · a blocked run says what it is waiting for, because "in progress" is not
    actionable;
  · no runs at all reads as "nothing ran", never as a tidy row of zeros;
  · no task payloads reach the brief, only bounded summaries and task ids.

Pure: these run against snapshot dicts, plus one end-to-end pass over a real
ledger to prove the projection matches what the ledger actually produces.
"""

import types

from agents.core.autonomy.company_report import (
    SCHEMA,
    build_company_brief,
    build_run_summary,
    render_company_brief,
)


def _snapshot(**over):
    base = {
        "run": {
            "id": "run-1", "title": "Prepare the quarterly brief", "status": "working",
            "steps_used": 2, "interrupts_used": 0, "stop_reason": "",
        },
        "budget": {"steps_left": 48, "exceeded": None},
        "steps": [
            {"seq": 1, "summary": "read last quarter's numbers", "outcome": "ok", "task_id": 11},
            {"seq": 2, "summary": "drafted the summary", "outcome": "ok", "task_id": 12},
        ],
        "verdicts": [],
        "tampered": False,
        "unauthorised_steps": [],
    }
    for key, value in over.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


# ── the headline is the verdict, not the effort ──────────────────────────────

def test_a_busy_run_with_no_verdict_reads_as_unfinished():
    """The failure mode this exists to prevent: lots of activity summarised as
    achievement."""
    snap = _snapshot(steps=[
        {"seq": i, "summary": f"step {i}", "outcome": "ok", "task_id": i}
        for i in range(1, 41)
    ])
    summary = build_run_summary(snap)
    assert summary["headline"] == "in progress"
    assert summary["verdict_lines"] == ["· nobody has graded it yet"]
    assert summary["steps"] == 40


def test_a_graded_run_reports_both_graders_in_their_own_words():
    snap = _snapshot(
        run={"status": "succeeded"},
        verdicts=[
            {"role": "verifier", "passed": True, "reason": "every required check holds"},
            {"role": "judge", "passed": True, "reason": "the brief is in docs/"},
        ],
    )
    summary = build_run_summary(snap)
    assert summary["headline"] == "met its goal"
    assert "the evidence held: every required check holds" in summary["verdict_lines"][0]
    assert "the goal was accepted: the brief is in docs/" in summary["verdict_lines"][1]


def test_a_rejected_run_is_not_softened():
    snap = _snapshot(
        run={"status": "failed"},
        verdicts=[
            {"role": "verifier", "passed": False, "reason": "the artifact was never produced"},
        ],
    )
    summary = build_run_summary(snap)
    assert summary["headline"] == "did not meet its goal"
    assert "did not hold" in summary["verdict_lines"][0]
    assert "the goal was" not in " ".join(summary["verdict_lines"])


def test_a_verified_but_ungraded_run_says_the_judge_never_spoke():
    snap = _snapshot(verdicts=[{"role": "verifier", "passed": True, "reason": "holds"}])
    lines = build_run_summary(snap)["verdict_lines"]
    assert len(lines) == 1
    assert lines[0].startswith("· the evidence held")


# ── the unflattering facts lead ──────────────────────────────────────────────

def test_an_unauthorised_step_outranks_whatever_the_run_achieved():
    snap = _snapshot(
        run={"status": "succeeded"},
        unauthorised_steps=[3],
        verdicts=[{"role": "judge", "passed": True, "reason": "goal met"}],
    )
    summary = build_run_summary(snap)
    assert summary["headline"] == (
        "1 step changed something without an approved task behind it"
    )
    assert "met its goal" not in summary["headline"]


def test_a_tampered_record_outranks_everything_including_unauthorised_steps():
    snap = _snapshot(tampered=True, unauthorised_steps=[1], run={"status": "succeeded"})
    assert "does not match its own fingerprint" in build_run_summary(snap)["headline"]


def test_the_brief_leads_with_unauthorised_runs_above_successes():
    brief = build_company_brief([
        _snapshot(run={"id": "good", "status": "succeeded"}),
        _snapshot(run={"id": "bad", "status": "succeeded"}, unauthorised_steps=[2]),
    ], company_mode_enabled=True)
    assert brief["unauthorised"] == ["bad"]
    text = render_company_brief(brief)
    assert text.index("no approved task") < text.index("met its goal")


# ── actionable states ────────────────────────────────────────────────────────

def test_a_blocked_run_says_what_it_is_waiting_for():
    """"in progress" is not actionable; "waiting on your approval" is."""
    summary = build_run_summary(_snapshot(run={"status": "blocked"}))
    assert summary["headline"] == "waiting on your approval"
    brief = build_company_brief([_snapshot(run={"status": "blocked"})])
    assert brief["needs_you"] == ["run-1"]
    assert "waiting on your approval" in render_company_brief(brief)


def test_an_exhausted_run_names_the_limit_in_plain_words():
    for limit, phrase in (
        ("steps", "used every step it was allowed"),
        ("seconds", "ran out of time"),
        ("deadline", "passed its deadline"),
        ("interrupts", "had no interruptions left"),
    ):
        snap = _snapshot(run={"status": "exhausted", "stop_reason": f"budget:{limit}"})
        assert phrase in build_run_summary(snap)["headline"]


def test_an_exhausted_run_with_an_unrecognised_reason_still_reads_plainly():
    snap = _snapshot(run={"status": "exhausted", "stop_reason": "budget:something_new"})
    assert build_run_summary(snap)["headline"] == "ran out of budget"


def test_an_owner_stop_carries_the_reason_they_gave():
    snap = _snapshot(run={"status": "stopped", "stop_reason": "changed my mind"})
    assert build_run_summary(snap)["headline"] == "you stopped it (changed my mind)"


# ── nothing inferred ─────────────────────────────────────────────────────────

def test_no_runs_reads_as_nothing_ran_not_as_a_clean_sheet():
    brief = build_company_brief([], company_mode_enabled=True)
    assert brief["empty"] is True
    assert brief["reason"] == "no work runs have been opened"
    assert brief["counts"] == {"runs": 0, "by_status": {}}
    assert "no work runs have been opened" in render_company_brief(brief)


def test_company_mode_off_is_reported_as_off_not_as_no_work():
    """Two different facts. A brief that rendered them identically would let a
    disabled feature look like a quiet night."""
    brief = build_company_brief([], company_mode_enabled=False)
    assert brief["reason"] == "company mode is off, so no run was opened"
    assert brief["enabled"] is False


def test_the_brief_counts_runs_by_status_from_the_snapshots_alone():
    brief = build_company_brief([
        _snapshot(run={"id": "a", "status": "succeeded"}),
        _snapshot(run={"id": "b", "status": "succeeded"}),
        _snapshot(run={"id": "c", "status": "blocked"}),
    ])
    assert brief["counts"] == {"runs": 3, "by_status": {"succeeded": 2, "blocked": 1}}
    assert brief["schema"] == SCHEMA


# ── no payloads ──────────────────────────────────────────────────────────────

def test_a_step_payload_never_reaches_the_brief():
    """The ledger keeps detail; the brief carries summaries and task ids only."""
    snap = _snapshot(steps=[{
        "seq": 1, "summary": "wrote the file", "outcome": "ok", "task_id": 9,
        "detail": {"content": "SECRET-CONTENTS-OF-THE-FILE"},
    }])
    summary = build_run_summary(snap)
    assert summary["recent"] == [
        {"summary": "wrote the file", "outcome": "ok", "task_id": 9}
    ]
    assert "SECRET" not in render_company_brief(build_company_brief([snap]))


def test_only_the_last_few_steps_are_shown():
    snap = _snapshot(steps=[
        {"seq": i, "summary": f"step {i}", "outcome": "ok", "task_id": i}
        for i in range(1, 11)
    ])
    recent = build_run_summary(snap)["recent"]
    assert [r["summary"] for r in recent] == ["step 8", "step 9", "step 10"]


def test_outcomes_are_counted_rather_than_listed():
    snap = _snapshot(steps=[
        {"seq": 1, "summary": "a", "outcome": "ok", "task_id": 1},
        {"seq": 2, "summary": "b", "outcome": "failed", "task_id": 2},
        {"seq": 3, "summary": "c", "outcome": "ok", "task_id": 3},
    ])
    assert build_run_summary(snap)["outcomes"] == {"ok": 2, "failed": 1}


# ── against a real ledger ────────────────────────────────────────────────────

def test_the_projection_matches_what_the_ledger_really_produces():
    """The dict fixtures above are only useful if they match reality — so build a
    brief straight off a live ledger snapshot."""
    from agents.core.autonomy.work_runs import WorkRunLedger

    led = WorkRunLedger(":memory:", clock=lambda: 1_000.0)
    try:
        goal = types.SimpleNamespace(
            goal_id="g-1", title="Prepare the quarterly brief",
            approved_by="receipt:1", deadline_at=100_000.0,
        )
        run = led.open_run(goal)
        led.record_step(run.id, kind="research", summary="read the numbers",
                        outcome="ok", task_id=11)
        led.record_verdict(run.id, role="verifier", passed=True, reason="holds")
        led.record_verdict(run.id, role="judge", passed=True, reason="goal met")

        brief = build_company_brief([led.snapshot(run.id)], company_mode_enabled=True)
        assert brief["empty"] is False
        assert brief["counts"]["by_status"] == {"succeeded": 1}
        assert brief["runs"][0]["headline"] == "met its goal"
        assert brief["runs"][0]["recent"][0]["task_id"] == 11
        assert "Prepare the quarterly brief" in render_company_brief(brief)
    finally:
        led.close()


def test_a_run_with_an_unauthorised_step_is_caught_end_to_end():
    from agents.core.autonomy.work_runs import WorkRunLedger

    led = WorkRunLedger(":memory:", clock=lambda: 1_000.0)
    try:
        goal = types.SimpleNamespace(
            goal_id="g-2", title="Tidy the workspace",
            approved_by="receipt:2", deadline_at=100_000.0,
        )
        run = led.open_run(goal)
        led.record_step(run.id, kind="edit", summary="deleted a file", outcome="ok")
        brief = build_company_brief([led.snapshot(run.id)], company_mode_enabled=True)
        assert brief["unauthorised"] == [run.id]
        assert "no approved task" in render_company_brief(brief)
    finally:
        led.close()
