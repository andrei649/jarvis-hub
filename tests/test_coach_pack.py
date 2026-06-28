"""0.43 — Learning Coach pack: SM-2 spaced repetition, session builder, curriculum planner."""

from agents.core import coach


# ── SM-2 spaced repetition ────────────────────────────────────────────────────
def test_first_successful_review_is_one_day():
    out = coach.review({"id": "a"}, quality=5, now_day=10)
    assert out["repetitions"] == 1 and out["interval"] == 1
    assert out["due_day"] == 11 and out["lapsed"] is False
    assert out["ease"] >= 2.5  # a perfect grade nudges ease up


def test_second_review_is_six_days_then_scales_by_ease():
    c = coach.review({"id": "a"}, 5, now_day=0)      # reps=1, interval=1
    c = coach.review(c, 4, now_day=1)                 # reps=2, interval=6
    assert c["repetitions"] == 2 and c["interval"] == 6
    c2 = coach.review(c, 4, now_day=7)                # reps=3, interval=round(6*ease)
    assert c2["repetitions"] == 3 and c2["interval"] == round(6 * c["ease"])


def test_lapse_resets_and_floors_ease():
    c = coach.review({"id": "a", "repetitions": 5, "interval": 40, "ease": 1.3}, quality=1, now_day=3)
    assert c["repetitions"] == 0 and c["interval"] == 1 and c["lapsed"] is True
    assert c["ease"] == 1.3  # never drops below the SM-2 floor


def test_review_does_not_mutate_input():
    original = {"id": "a", "repetitions": 2, "interval": 6, "ease": 2.5}
    coach.review(original, 5, now_day=0)
    assert original == {"id": "a", "repetitions": 2, "interval": 6, "ease": 2.5}


# ── session builder ───────────────────────────────────────────────────────────
def test_build_session_splits_due_and_new_with_honest_counts():
    cards = [
        {"id": "due1", "repetitions": 2, "due_day": 5},
        {"id": "due2", "repetitions": 1, "due_day": 9},     # not yet due at now_day=8
        {"id": "new1"}, {"id": "new2"}, {"id": "new3"},
    ]
    s = coach.build_session(cards, now_day=8, new_limit=2)
    assert [c["id"] for c in s["due"]] == ["due1"]
    assert [c["id"] for c in s["new"]] == ["new1", "new2"]   # capped at new_limit
    assert s["counts"] == {"due_total": 1, "due_selected": 1,
                           "new_total": 3, "new_selected": 2, "deferred": 1}


def test_never_reviewed_card_is_treated_as_new_not_due():
    s = coach.build_session([{"id": "x"}], now_day=0, new_limit=0)
    assert s["new"] == [] and s["counts"]["new_total"] == 1   # deferred by the cap, not lost


# ── curriculum planner ────────────────────────────────────────────────────────
def test_curriculum_orders_by_prereqs_and_splits():
    topics = [
        {"id": "c", "prereqs": ["b"]},
        {"id": "b", "prereqs": ["a"]},
        {"id": "a"},
        {"id": "d", "prereqs": ["a"]},
    ]
    out = coach.plan_curriculum(topics, per_session=2)
    order = [t["id"] for t in out["order"]]
    assert order.index("a") < order.index("b") < order.index("c")
    assert order.index("a") < order.index("d")
    assert out["session_count"] == 2 and len(out["sessions"][0]) == 2


def test_curriculum_reports_cycles_and_unknown_prereqs_honestly():
    topics = [
        {"id": "x", "prereqs": ["y"]},
        {"id": "y", "prereqs": ["x"]},         # cycle
        {"id": "z", "prereqs": ["ghost"]},     # unknown prereq
    ]
    out = coach.plan_curriculum(topics)
    assert set(out["cycles"]) == {"x", "y"}                 # surfaced, not dropped
    assert {"topic": "z", "missing_prereq": "ghost"} in out["unknown_prereqs"]
    assert {t["id"] for t in out["order"]} == {"x", "y", "z"}  # every topic still planned
