"""0.51 — reference-grounded planning (honest grounding enforcement).

Covers agents/core/grounded_plan.py: a step is grounded only if it cites a known
reference; unknown citations are surfaced not dropped; ungrounded steps are
flagged; coverage + unused references are reported; fully_grounded is honest.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.grounded_plan import ground_plan  # noqa: E402

REFS = [
    {"id": "r1", "title": "Spec A", "url": "http://a"},
    {"id": "r2", "title": "Spec B"},
    {"id": "r3", "title": "Spec C"},
]


def test_fully_grounded_plan():
    steps = [
        {"text": "do X per A", "cites": ["r1"]},
        {"text": "do Y per B+C", "cites": ["r2", "r3"]},
    ]
    p = ground_plan("ship it", REFS, steps)
    assert p["fully_grounded"] is True
    assert p["grounded_steps"] == 2 and p["ungrounded_steps"] == []
    assert p["unknown_citations"] == [] and p["unused_references"] == []
    assert p["coverage"] == 1.0
    assert p["steps"][1]["cited_titles"] == ["Spec B", "Spec C"]


def test_ungrounded_step_is_flagged_not_accepted():
    steps = [
        {"text": "grounded", "cites": ["r1"]},
        {"text": "made up, no citation", "cites": []},
    ]
    p = ground_plan("g", REFS, steps)
    assert p["fully_grounded"] is False
    assert p["ungrounded_steps"] == [1]
    assert p["steps"][1]["grounded"] is False
    assert p["grounded_steps"] == 1


def test_unknown_citation_is_surfaced_not_dropped():
    steps = [{"text": "cites a phantom source", "cites": ["r1", "r99"]}]
    p = ground_plan("g", REFS, steps)
    s = p["steps"][0]
    assert s["cites"] == ["r1"]            # only the valid id is kept as grounding
    assert s["unknown_cites"] == ["r99"]   # the phantom is surfaced
    assert p["unknown_citations"] == ["r99"]
    assert s["grounded"] is True           # still grounded — it has one real cite
    assert p["fully_grounded"] is False    # ...but the plan isn't fully clean


def test_step_grounded_only_by_unknown_is_ungrounded():
    steps = [{"text": "only fake citations", "cites": ["nope", "alsonope"]}]
    p = ground_plan("g", REFS, steps)
    assert p["steps"][0]["grounded"] is False
    assert p["ungrounded_steps"] == [0]
    assert p["unknown_citations"] == ["nope", "alsonope"]


def test_coverage_and_unused_references():
    steps = [{"text": "only uses r1", "cites": ["r1", "r1"]}]   # dup id collapses
    p = ground_plan("g", REFS, steps)
    assert p["steps"][0]["cites"] == ["r1"]            # de-duplicated
    assert round(p["coverage"], 3) == round(1 / 3, 3)
    assert set(p["unused_references"]) == {"r2", "r3"}


def test_empty_plan_is_vacuously_clean_but_zero_coverage():
    p = ground_plan("g", REFS, [])
    assert p["steps"] == [] and p["grounded_steps"] == 0
    assert p["fully_grounded"] is True       # nothing ungrounded, nothing unknown
    assert p["coverage"] == 0.0
    assert set(p["unused_references"]) == {"r1", "r2", "r3"}


def test_no_references_means_zero_coverage_no_crash():
    p = ground_plan("g", [], [{"text": "anything", "cites": ["x"]}])
    assert p["reference_count"] == 0 and p["coverage"] == 0.0
    assert p["ungrounded_steps"] == [0]
    assert p["unknown_citations"] == ["x"]


def test_reference_without_id_raises():
    with pytest.raises(ValueError):
        ground_plan("g", [{"title": "no id"}], [])
