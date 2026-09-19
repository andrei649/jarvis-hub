"""A progress percentage must never turn partial, excluded or stale work into done."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import hermes_status as hs


@pytest.fixture
def sample(tmp_path):
    caps = [
        {"name": "Already equivalent", "cluster": "core", "decision": "keep", "nerva_state": "parity"},
        {"name": "Needs work despite old parity label", "cluster": "core", "decision": "update", "nerva_state": "superior"},
        {"name": "Deliberately omitted", "cluster": "ui", "decision": "skip", "nerva_state": "superior"},
        {"name": "No implementation", "cluster": "ui", "decision": "copy", "nerva_state": "missing"},
    ]
    ledger = {"generated": "2026-09-07", "capabilities": caps}
    review = {
        "schema_version": 1, "inventory_count": 4,
        "inventory_sha256": hs.digest(ledger), "base_sha": "a" * 40,
        "assessed_at": "2026-09-09T14:20:00Z", "reviews": [],
    }
    for name in ["agents/core/example.py", "tests/test_example.py"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# inspected source\n", encoding="utf-8")
    return ledger, review, tmp_path


def add_review(sample, status="equivalent", remaining=""):
    ledger, data, root = sample
    data["reviews"].append({
        "id": "H002", "row_sha256": hs.digest(ledger["capabilities"][1]),
        "status": status, "summary": "Inspected the complete capability contract.",
        "remaining": remaining,
        "evidence": [
            {"path": path, "sha256": hs.file_digest(root / path)}
            for path in ["agents/core/example.py", "tests/test_example.py"]
        ],
    })
    return data["reviews"][-1]


def test_excluded_and_partial_never_count_as_done(sample):
    rows = hs.assess(*sample)
    result = hs.metrics(rows)
    assert result["total"] == 4 and result["accepted"] == 3
    assert result["counts"] == {"equivalent": 1, "partial": 1, "missing": 1, "excluded": 1, "needs_review": 0}
    assert result["all_percent"] == 25.0
    assert result["accepted_percent"] == 33.3
    assert result["inherited_equivalent"] == 1 and result["reviewed_equivalent"] == 0


def test_equivalent_requires_a_review_and_surviving_source_and_tests(sample):
    add_review(sample)
    result = hs.metrics(hs.assess(*sample))
    assert result["counts"]["equivalent"] == 2
    assert result["reviewed_equivalent"] == 1
    assert result["reviewed"] == 1


def test_partial_work_gets_zero_fractional_credit(sample):
    add_review(sample, "partial", "Event delivery is still missing.")
    assert hs.metrics(hs.assess(*sample))["all_percent"] == 25.0


def test_modified_evidence_removes_completion_until_reviewed_again(sample):
    add_review(sample)
    (sample[2] / "agents/core/example.py").write_text("# changed\n", encoding="utf-8")
    rows = hs.assess(*sample)
    assert rows[1]["status"] == "needs_review"
    assert hs.metrics(rows)["counts"]["equivalent"] == 1
    assert hs.metrics(rows)["reviewed"] == 0


def test_deleted_evidence_cannot_leave_green_completion(sample):
    add_review(sample)
    (sample[2] / "agents/core/example.py").unlink()
    assert hs.assess(*sample)[1]["status"] == "needs_review"


def test_windows_checkout_newlines_do_not_invalidate_unchanged_code(sample):
    add_review(sample)
    path = sample[2] / "agents/core/example.py"
    path.write_bytes(b"# inspected source\r\n")
    assert hs.assess(*sample)[1]["status"] == "equivalent"


def test_partial_review_must_name_the_remaining_work(sample):
    add_review(sample, "partial", "")
    with pytest.raises(ValueError, match="unfinished"):
        hs.assess(*sample)


@pytest.mark.parametrize("mutation", ["reorder", "rename", "append", "decision"])
def test_frozen_inventory_cannot_change_without_explicit_migration(sample, mutation):
    ledger, _, _ = sample
    if mutation == "reorder":
        ledger["capabilities"].reverse()
    elif mutation == "rename":
        ledger["capabilities"][0]["name"] = "Something else"
    elif mutation == "append":
        ledger["capabilities"].append(copy.deepcopy(ledger["capabilities"][0]))
    else:
        ledger["capabilities"][0]["decision"] = "skip"
    with pytest.raises(ValueError, match="inventory"):
        hs.assess(*sample)


@pytest.mark.parametrize("field,value", [
    ("id", "H999"), ("row_sha256", "f" * 64), ("status", "done"),
    ("remaining", "Still needs the actual execution path"),
    ("summary", ""), ("extra", True),
])
def test_bad_or_overclaimed_review_is_refused(sample, field, value):
    item = add_review(sample)
    item[field] = value
    with pytest.raises(ValueError):
        hs.assess(*sample)


def test_duplicate_review_is_not_counted_twice(sample):
    item = add_review(sample)
    sample[1]["reviews"].append(copy.deepcopy(item))
    with pytest.raises(ValueError, match="duplicate"):
        hs.assess(*sample)


def test_an_excluded_row_cannot_be_silently_promoted(sample):
    item = add_review(sample)
    item.update(id="H003", row_sha256=hs.digest(sample[0]["capabilities"][2]))
    with pytest.raises(ValueError, match="excluded"):
        hs.assess(*sample)


@pytest.mark.parametrize("path", ["../outside.py", "/tmp/a.py", "C:/temp/a.py", "agents\\a.py"])
def test_evidence_paths_must_stay_in_the_repository(sample, path):
    item = add_review(sample)
    item["evidence"][0]["path"] = path
    with pytest.raises(ValueError, match="path"):
        hs.assess(*sample)


def test_documentation_alone_is_not_code_equivalence_proof(sample):
    item = add_review(sample)
    item["evidence"] = [item["evidence"][1]]
    with pytest.raises(ValueError, match="source and tests"):
        hs.assess(*sample)


def cite(sample, citation):
    """A review whose prose points at a line of the source it pinned."""
    (sample[2] / "agents/core/example.py").write_text("first line\n\nthird line\n", encoding="utf-8")
    item = add_review(sample)
    item["summary"] = f"Inspected the whole contract at {citation}."
    return item


@pytest.mark.parametrize("citation", [
    "agents/core/example.py:4",    # past the end of the file whose hash it pinned
    "agents/core/example.py:1-9",  # a range running past the end
    "agents/core/example.py:2",    # a blank line points at nothing
    "agents/core/example.py:0",    # line numbers start at 1
    "agents/core/example.py:3-1",  # a reversed range
    "example.py:4",                # the same file, named the short way in prose
])
def test_line_numbers_from_another_checkout_are_refused(sample, citation):
    cite(sample, citation)
    with pytest.raises(ValueError, match="citation"):
        hs.assess(*sample)


def test_a_citation_landing_on_pinned_source_is_accepted(sample):
    cite(sample, "agents/core/example.py:3")
    assert hs.assess(*sample)[1]["status"] == "equivalent"


def test_positions_in_unpinned_files_are_not_second_guessed(sample):
    # Only the files a review hashed can be checked: everything else may have moved
    # since, and inventing a verdict on it would be the same unpinned guess twice.
    cite(sample, "agents/core/elsewhere.py:9999")
    assert hs.assess(*sample)[1]["status"] == "equivalent"


def test_stale_evidence_is_still_demoted_rather_than_fatal(sample):
    # A row whose code moved already loses its credit; its old positions are expected
    # to be stale, so they must not turn a routine refresh into a hard failure.
    cite(sample, "agents/core/example.py:3")
    (sample[2] / "agents/core/example.py").write_text("shorter\n", encoding="utf-8")
    assert hs.assess(*sample)[1]["status"] == "needs_review"


def test_reviewed_rows_cite_lines_that_exist_in_the_code_they_pinned():
    """The corrected citations resolve, checked against the pins that still hold.

    These three published positions copied from a checkout other than the one they
    hashed, and correcting them is what this slice delivers.

    Asserting `basis == "reviewed"` for named rows would have pinned the wrong thing.
    `assess` only screens citations when EVERY file a row pinned is still byte-identical
    (`if current:`), so that assertion makes the test hostage to all ~44 files these
    three rows pin between them: an unrelated edit to any one of them demotes the row,
    the screen is skipped, and this test fails while reporting nothing about the
    citations it exists to check. That is not hypothetical — H477 pins
    `tests/test_h2311_operability.py`, which the serve.py EACCES fix in this same PR
    added cases to, so the original form of this test went red on its own commit.

    So screen the citations directly, against the subset of each row's evidence whose
    hash still matches. Drift in one pinned file then narrows what can be verified
    instead of silencing the check, and the non-vacuity assertions below keep a narrowed
    set from passing by checking nothing.
    """
    ledger, data = hs.load()
    reviews = {item["id"]: item for item in data["reviews"]}

    for ident in ("H456", "H477", "H510"):
        item = reviews[ident]
        pinned = {}
        for entry in item["evidence"]:
            path = hs.REPO / entry["path"]
            if path.is_file() and hs.file_digest(path) == entry["sha256"]:
                pinned[entry["path"]] = path.read_text(encoding="utf-8").splitlines()

        text = f"{item['summary']}\n{item['remaining']}"
        assert pinned, f"{ident}: every pinned file drifted, so nothing could be screened"
        cited = [m.group(0) for m in hs.CITATION.finditer(text)
                 if sum(p == m.group(1) or p.endswith("/" + m.group(1)) for p in pinned) == 1]
        assert cited, f"{ident}: no citation lands in a file still pinned — screen is vacuous"
        assert hs._cited_lines(text, pinned) == [], f"{ident}: citation does not resolve"

    # And the real corpus still exercises the screen broadly, so a repo-wide drift
    # cannot quietly reduce every row to the skipped path.
    rows = hs.assess(ledger, data, hs.REPO)
    assert sum(row["basis"] == "reviewed" for row in rows) >= 50


def test_real_inventory_covers_exactly_697_rows_and_reports_are_current():
    ledger, data = hs.load()
    rows = hs.assess(ledger, data, hs.REPO)
    assert len(rows) == 697
    assert len({row["id"] for row in rows}) == 697
    result = hs.metrics(rows)
    assert sum(result["counts"].values()) == 697
    assert result["counts"]["excluded"] == 107
    assert result["accepted"] == 590
    for relative, generated in hs.reports(rows, data).items():
        assert (hs.REPO / relative).read_text(encoding="utf-8") == generated, relative


def test_current_images_and_sdk_are_not_mistaken_for_full_inventory_parity():
    ledger, data = hs.load()
    rows = {row["id"]: row for row in hs.assess(ledger, data, hs.REPO)}
    assert rows["H515"]["status"] == rows["H598"]["status"] == "partial"
    assert rows["H566"]["status"] == "partial"
    # K2 built the resident interpreter, so H660 is no longer `missing` — and it is
    # not done either: the remote kernel and K3's operator controls are unwritten, and
    # no container has been proven. The pin moves with the evidence, never past it.
    assert rows["H660"]["status"] == "partial"
    assert rows["H595"]["status"] == "partial"


def test_json_summary_and_bounded_listing(sample, capsys):
    # The public functions retain exact values; CLI formatting must not invent totals.
    result = hs.metrics(hs.assess(*sample))
    assert json.loads(json.dumps(result))["total"] == 4
    assert hs.main(["list", "--limit", "2"]) == 0
    output = capsys.readouterr().out
    assert len([line for line in output.splitlines() if line.startswith("H")]) == 2
    assert len(output) < 800


def test_cli_unknown_row_is_a_named_failure(capsys):
    assert hs.main(["show", "H999"]) == 1
    assert "not found" in capsys.readouterr().err
