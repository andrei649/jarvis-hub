"""The S1 operator benchmark: the 20-task pack, and the ways a benchmark lies.

A pass rate is easy to produce and easy to inflate, so almost every test here is
about a specific inflation being impossible:

  · a hermetic pass can never be read as a live pass — there are two columns and
    the headline always says the word "hermetic";
  · governance outranks correctness: a task that got the right answer via an
    ungoverned action FAILS, and one ungoverned action fails the whole pack at any
    rate;
  · skips are not folded into the denominator, so "we could not try" never
    flatters the rate;
  · a stored rate carries the fingerprint of the questions it answered, and a
    changed pack marks it stale rather than serving it;
  · the pack ships a negative control — a task expected to fail — because a
    governance rule with no failing example is a rule nobody has tested.
"""

from __future__ import annotations

import json

import pytest

from agents.core.observability.operator_benchmark import (
    SCHEMA,
    SURFACES,
    BenchmarkError,
    GovernanceLedger,
    Task,
    build_report,
    load_report,
    pack_fingerprint,
    run_pack,
    save_report,
)
from agents.core.observability.operator_pack import (
    NEGATIVE_CONTROLS,
    TASKS,
    scored_tasks,
)

pytestmark = pytest.mark.asyncio


def _task(task_id="t1", surface="desktop", run=None, judge=None, **kw):
    return Task(
        id=task_id, surface=surface, describe="does a thing",
        run=run or (lambda: {"ok": True, "ledger": GovernanceLedger()}),
        judge=judge or (lambda out: bool(out and out.get("ok"))),
        live_twin="do the same thing on a real box",
        **kw,
    )


def _governed(steps=1, ungoverned=0, **extra):
    ledger = GovernanceLedger()
    for i in range(steps):
        ledger.act(f"s{i}", governed=i >= ungoverned)
    return {"ok": True, "ledger": ledger, **extra}


# ── the pack itself ──────────────────────────────────────────────────────────

async def test_the_pack_is_twenty_tasks_across_five_surfaces():
    """Twenty passes inside one surface would be a real 20/20 and a useless one —
    the S1 claim is breadth."""
    assert len(TASKS) == 20
    surfaces = {t.surface for t in TASKS}
    assert surfaces == set(SURFACES)
    for surface in SURFACES:
        assert sum(1 for t in TASKS if t.surface == surface) == 4


async def test_every_task_names_a_live_twin():
    """A task with no live twin can only ever be a hermetic claim; naming the twin
    is how the live gap stays countable."""
    for task in TASKS:
        assert task.live_twin.strip()


async def test_a_task_without_a_live_twin_cannot_be_declared():
    with pytest.raises(BenchmarkError) as exc:
        Task(id="x", surface="desktop", describe="d", live_twin="")
    assert "live_twin_required" in exc.value.reason


async def test_task_ids_are_unique():
    assert len({t.id for t in TASKS}) == len(TASKS)


async def test_an_unknown_surface_is_refused():
    with pytest.raises(BenchmarkError):
        Task(id="x", surface="telepathy", describe="d", live_twin="t")


async def test_the_scored_pack_excludes_the_negative_controls():
    scored = scored_tasks()
    assert len(scored) == 19
    assert NEGATIVE_CONTROLS and not (NEGATIVE_CONTROLS & {t.id for t in scored})


async def test_the_whole_scored_pack_passes_hermetically_and_cleanly():
    report = await run_pack(scored_tasks())
    assert report["hermetic"] == {
        "attempted": 19, "passed": 19, "failed": 0, "skipped": 0, "rate": 1.0
    }
    assert report["governance_clean"] is True


async def test_the_negative_control_really_fails():
    """The rule is only load-bearing if something actually trips it."""
    control = [t for t in TASKS if t.id in NEGATIVE_CONTROLS]
    report = await run_pack(control)
    assert report["governance_clean"] is False
    assert report["hermetic"]["passed"] == 0
    assert "bypassed governance" in report["results"][0]["detail"]


# ── governance outranks correctness ──────────────────────────────────────────

async def test_a_right_answer_reached_ungoverned_still_fails():
    """Rewarding the result and ignoring the route trains exactly the wrong thing."""
    task = _task(run=lambda: _governed(3, ungoverned=1), judge=lambda out: True)
    report = await run_pack([task])
    assert report["results"][0]["outcome"] == "failed"
    assert report["results"][0]["ungoverned"] == 1
    assert report["governance_clean"] is False


async def test_one_ungoverned_action_fails_the_whole_pack_at_any_rate():
    tasks = [_task(f"t{i}") for i in range(5)]
    tasks.append(_task("bad", run=lambda: _governed(2, ungoverned=1), judge=lambda o: True))
    report = await run_pack(tasks)
    assert report["hermetic"]["passed"] == 5
    assert report["governance_clean"] is False
    assert "does not pass at any rate" in report["headline"]


async def test_the_headline_leads_with_governance_not_the_rate():
    report = await run_pack(
        [_task("bad", run=lambda: _governed(1, ungoverned=1), judge=lambda o: True)]
    )
    assert report["headline"].startswith("1 action(s) bypassed governance")


# ── hermetic is never live ───────────────────────────────────────────────────

async def test_a_hermetic_pass_is_never_reported_as_a_live_pass():
    report = await run_pack(scored_tasks())
    assert report["live"]["passed"] == 0
    assert report["live"]["not_run"] == 19
    # There is no live rate until a live run happens. Reporting the hermetic
    # number here is the exact lie the module exists to avoid.
    assert report["live"]["rate"] is None


async def test_the_headline_always_says_the_word_hermetic():
    report = await run_pack(scored_tasks())
    assert "hermetic" in report["headline"]
    assert "nothing confirmed on a real host yet" in report["headline"]


# ── skips do not flatter the rate ────────────────────────────────────────────

async def test_a_skipped_task_is_not_a_passed_task_and_leaves_the_denominator():
    tasks = [_task("a"), _task("b"), _task("c")]

    def _supported(task):
        return "desktop_platform_unsupported" if task.id == "c" else ""

    report = await run_pack(tasks, supported=_supported)
    assert report["hermetic"]["passed"] == 2
    assert report["hermetic"]["skipped"] == 1
    # 2/2, not 2/3 and not 3/3: "we could not try" is neither a pass nor a fail
    assert report["hermetic"]["attempted"] == 2
    assert report["hermetic"]["rate"] == 1.0
    assert "1 skipped on this host" in report["headline"]


async def test_a_skip_carries_the_reason_the_host_gave():
    report = await run_pack(
        [_task("a")], supported=lambda t: "wayland_input_unavailable"
    )
    assert report["results"][0]["detail"] == "wayland_input_unavailable"


async def test_an_all_skipped_pack_reports_zero_not_a_perfect_score():
    report = await run_pack([_task("a")], supported=lambda t: "no_display")
    assert report["hermetic"]["rate"] == 0.0
    assert report["hermetic"]["passed"] == 0


# ── failures are honest ──────────────────────────────────────────────────────

async def test_a_task_that_raises_is_a_failure_not_a_crash():
    def _boom():
        raise RuntimeError("the twin fell over")

    report = await run_pack([_task("a", run=_boom)])
    assert report["results"][0]["outcome"] == "failed"
    assert report["results"][0]["detail"] == "raised RuntimeError"


async def test_a_judge_that_raises_fails_the_task():
    def _boom(_out):
        raise ValueError("cannot tell")

    report = await run_pack([_task("a", judge=_boom)])
    assert report["results"][0]["detail"] == "judge raised"


async def test_a_task_with_no_judge_cannot_pass():
    """No way to tell whether it worked is not the same as it worked."""
    task = Task(id="a", surface="files", describe="d", run=lambda: {"ok": True},
                live_twin="t")
    report = await run_pack([task])
    assert report["results"][0]["outcome"] == "failed"


async def test_a_failure_carries_the_twin_s_own_reason_when_it_gives_one():
    report = await run_pack(
        [_task("a", run=lambda: {"ok": False, "reason": "element_not_found"},
               judge=lambda o: False)]
    )
    assert report["results"][0]["detail"] == "element_not_found"


async def test_an_async_task_is_awaited():
    async def _run():
        return _governed(1)

    report = await run_pack([_task("a", run=_run)])
    assert report["results"][0]["outcome"] == "passed"


# ── the rate travels with what it measured ───────────────────────────────────

async def test_the_fingerprint_covers_the_questions_not_the_answers():
    a = _task("a")
    b = _task("a")  # same declaration, different callables
    assert pack_fingerprint([a]) == pack_fingerprint([b])
    assert pack_fingerprint([a]) != pack_fingerprint([_task("a2")])


async def test_the_fingerprint_is_order_independent():
    a, b = _task("a"), _task("b")
    assert pack_fingerprint([a, b]) == pack_fingerprint([b, a])


async def test_a_stored_rate_is_marked_stale_when_the_pack_changes(tmp_path):
    """A number measured against different questions is not a number for these."""
    path = tmp_path / "bench.json"
    report = await run_pack([_task("a")])
    save_report(report, path)

    fresh = load_report(path, tasks=[_task("a")])
    assert fresh["stale"] is False
    assert fresh["hermetic"]["passed"] == 1

    changed = load_report(path, tasks=[_task("a"), _task("b")])
    assert changed["stale"] is True


async def test_a_stored_report_records_when_it_was_taken(tmp_path):
    path = tmp_path / "bench.json"
    save_report(await run_pack([_task("a")]), path)
    stored = json.loads(path.read_text())
    assert stored["schema"] == SCHEMA
    assert stored["recorded_at"] > 0


async def test_a_missing_or_corrupt_store_reads_as_never_run(tmp_path):
    assert load_report(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_report(bad) is None
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema": "something.else"}))
    assert load_report(wrong) is None


# ── the report shape a caller depends on ─────────────────────────────────────

async def test_the_report_breaks_the_rate_down_by_surface():
    report = await run_pack(scored_tasks())
    assert set(report["by_surface"]) == set(SURFACES)
    assert report["by_surface"]["desktop"]["passed"] == 4


async def test_build_report_is_pure_over_its_inputs():
    from agents.core.observability.operator_benchmark import TaskResult

    tasks = [_task("a"), _task("b")]
    results = [
        TaskResult("a", "desktop", "passed"),
        TaskResult("b", "desktop", "failed", "nope"),
    ]
    report = build_report(tasks, results)
    assert report["hermetic"]["rate"] == 0.5
    assert report["governance_clean"] is True
