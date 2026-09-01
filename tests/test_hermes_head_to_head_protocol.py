"""Bit-rot guard for the GAP-4 / DRA-45 head-to-head protocol (docs/HERMES_HEAD_TO_HEAD.md).

The measurement itself is owner-gated and has NOT been run. What is closed here is the tracking
half: a frozen, pre-registered protocol that exists before the run, is honestly stamped NOT RUN,
keeps the "publish the losses" rule, and is reachable from the owner lane and the roadmap.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROTOCOL = REPO / "docs/HERMES_HEAD_TO_HEAD.md"


def _text() -> str:
    return PROTOCOL.read_text(encoding="utf-8")


def test_protocol_doc_exists_and_declares_not_run() -> None:
    assert PROTOCOL.is_file()
    head = "\n".join(_text().splitlines()[:40])
    assert "NOT RUN" in head
    assert "owner-gated" in head


def test_protocol_enumerates_ten_tasks_across_the_four_buckets() -> None:
    text = _text()
    tasks = re.findall(r"^###\s+T(10|[1-9])\b", text, re.M)
    assert len(tasks) == 10, tasks
    assert sorted(int(t) for t in tasks) == list(range(1, 11))
    for bucket in ("browser", "desktop", "house", "acquisition"):
        assert bucket in text.lower(), bucket


def test_protocol_names_its_owner_preconditions_and_the_loss_rule() -> None:
    text = _text()
    assert "licence" in text.lower() or "license" in text.lower()
    assert "OWNER_TASKS" in text
    assert "publish the losses" in text.lower() or "including the losses" in text.lower()


def test_results_table_is_an_unfilled_template() -> None:
    """No fabricated measurement may sit in the table while the run has not happened."""
    rows = [ln for ln in _text().splitlines() if re.match(r"^\|\s*T\d+\s*\|", ln)]
    assert len(rows) == 10, rows
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert cells[2:] == ["—", "—", "—", "—"], row


def test_head_to_head_is_reachable_from_the_owner_lane() -> None:
    for rel in ("docs/OWNER_TASKS.md", "docs/DEVELOPMENT_ROADMAP.md"):
        assert "HERMES_HEAD_TO_HEAD.md" in (REPO / rel).read_text(encoding="utf-8"), rel
