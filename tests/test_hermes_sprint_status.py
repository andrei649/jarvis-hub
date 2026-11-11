"""A progress percentage must never turn partial, excluded or unproven work into done.

Evidence model (owner decision 2026-11-10 §3): each row sits in exactly one feature area, and
an area's acceptance suite, not a hash of the files a review cited, keeps its equivalent rows
honest. A failing suite demotes only that area's equivalent rows; moving code demotes nothing.
"""

from __future__ import annotations

import copy
import json

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
        "schema_version": 3, "inventory_count": 4,
        "inventory_sha256": hs.digest(ledger), "base_sha": "a" * 40,
        "assessed_at": "2026-09-09T14:20:00Z", "reviews": [], "scope_reopenings": [],
    }
    areas = {"schema_version": 1, "decision": "docs/decisions/x.md", "areas": [
        {"id": "core", "title": "Core", "lanes": ["own"], "suite_origin": "seeded",
         "rows": ["H001", "H002"], "suite": ["tests/test_example.py"]},
        {"id": "ui", "title": "Interface", "lanes": ["own", "run"], "suite_origin": "owner",
         "rows": ["H003", "H004"], "suite": ["tests/test_ui.py::TestOwner::test_can_open", "tests/test_ui.py::test_attacker"]},
    ]}
    files = {
        "agents/core/example.py": "# inspected source\n",
        "tests/test_example.py": "def test_core():\n    pass\n",
        "tests/test_ui.py": "class TestOwner:\n    def test_can_open(self):\n        pass\n\n"
                            "async def test_attacker():\n    pass\n",
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return ledger, review, areas, tmp_path


def add_review(sample, status="equivalent", remaining="", ident="H002"):
    ledger, data, _, _ = sample
    data["reviews"].append({
        "id": ident, "row_sha256": hs.digest(ledger["capabilities"][int(ident[1:]) - 1]),
        "status": status, "summary": "Inspected the complete capability contract at agents/core/example.py:1.",
        "remaining": remaining, "evidence": ["agents/core/example.py", "tests/test_example.py"],
    })
    return data["reviews"][-1]


def reopen_scope(sample):
    ledger, data, _, _ = sample
    entry = {'id': 'H003', 'row_sha256': hs.digest(ledger['capabilities'][2]),
             'decided_at': '2026-09-27T00:00:00Z',
             'reason': 'Owner requests full functional parity, including former exclusions.'}
    data['scope_reopenings'] = [entry]
    return entry


def junit(*cases):
    """A pytest JUnit file: (classname, name, outcome) with outcome passed|failure|error|skipped."""
    body = "".join(
        f'<testcase classname="{c}" name="{n}" time="0.1" />' if o == "passed" else
        f'<testcase classname="{c}" name="{n}" time="0.1"><{o} message="x">boom</{o}></testcase>'
        for c, n, o in cases)
    return (f'<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest" '
            f'tests="{len(cases)}">{body}</testsuite></testsuites>')


GREEN = [("tests.test_example", "test_core", "passed"),
         ("tests.test_ui.TestOwner", "test_can_open", "passed"),
         ("tests.test_ui", "test_attacker", "passed")]


def judged(sample, *cases):
    ledger, data, areas, root = sample
    results = hs.suite_results(areas["areas"], hs.read_junit(junit(*cases)))
    return results, {row["id"]: row for row in hs.assess(ledger, data, areas, root, results=results)}


# --- the counting rule -------------------------------------------------------------------------

def test_excluded_and_partial_never_count_as_done(sample):
    rows = hs.assess(*sample)
    result = hs.metrics(rows)
    assert result["total"] == 4 and result["accepted"] == 3
    assert result["counts"] == {"equivalent": 1, "partial": 1, "missing": 1, "excluded": 1, "needs_review": 0}
    assert result["all_percent"] == 25.0
    assert result["accepted_percent"] == 33.3
    assert result["inherited_equivalent"] == 1 and result["reviewed_equivalent"] == 0
    assert [row["area"] for row in rows] == ["core", "core", "ui", "ui"]


def test_equivalent_requires_a_review_naming_source_and_tests(sample):
    add_review(sample)
    result = hs.metrics(hs.assess(*sample))
    assert result["counts"]["equivalent"] == 2
    assert result["reviewed_equivalent"] == 1
    assert result["reviewed"] == 1


def test_partial_work_gets_zero_fractional_credit(sample):
    add_review(sample, "partial", "Event delivery is still missing.")
    assert hs.metrics(hs.assess(*sample))["all_percent"] == 25.0


def test_partial_review_must_name_the_remaining_work(sample):
    add_review(sample, "partial", "")
    with pytest.raises(ValueError, match="unfinished"):
        hs.assess(*sample)


def test_documentation_alone_is_not_code_equivalence_proof(sample):
    item = add_review(sample)
    item["evidence"] = ["tests/test_example.py"]
    with pytest.raises(ValueError, match="source and tests"):
        hs.assess(*sample)


# --- moving code changes nothing ---------------------------------------------------------------

def test_a_merge_that_only_moves_code_changes_no_row(sample):
    ledger, data, areas, root = sample
    add_review(sample)
    before = hs.assess(*sample)
    reports = hs.reports(before, data, areas)
    moved = root / "agents/core/moved/example.py"
    moved.parent.mkdir()
    (root / "agents/core/example.py").rename(moved)
    moved.write_text("# rewritten, lines shifted\n\n\n# inspected source\n", encoding="utf-8")
    after = hs.assess(*sample)
    assert after == before
    assert after[1]["status"] == "equivalent" and after[1]["basis"] == "reviewed"
    assert hs.reports(after, data, areas) == reports


def test_citations_are_prose_and_never_screened(sample):
    item = add_review(sample)
    item["summary"] = "Lives at agents/core/example.py:9999 on some other checkout."
    assert hs.assess(*sample)[1]["status"] == "equivalent"


def test_old_hash_pinned_evidence_is_refused(sample):
    item = add_review(sample)
    item["evidence"] = [{"path": "agents/core/example.py", "sha256": "0" * 64}, "tests/test_example.py"]
    with pytest.raises(ValueError, match="evidence path"):
        hs.assess(*sample)


@pytest.mark.parametrize("version", [1, 2, 4, "3"])
def test_only_the_area_schema_is_accepted(sample, version):
    sample[1]["schema_version"] = version
    with pytest.raises(ValueError, match="schema"):
        hs.assess(*sample)


# --- acceptance suites -------------------------------------------------------------------------

def test_passing_suites_keep_every_verdict(sample):
    add_review(sample)
    results, rows = judged(sample, *GREEN)
    assert {area: result["state"] for area, result in results.items()} == {"core": "passed", "ui": "passed"}
    assert [rows[i]["status"] for i in ("H001", "H002", "H003", "H004")] == [
        "equivalent", "equivalent", "excluded", "missing"]


def test_a_failing_suite_demotes_only_its_own_areas_equivalent_rows(sample):
    reopen_scope(sample)
    add_review(sample)                                      # H002 equivalent in core
    add_review(sample, "partial", "Not yet.", ident="H004")  # partial in ui
    item = add_review(sample, ident="H003")                 # reopened, equivalent in ui
    assert item["status"] == "equivalent"
    results, rows = judged(sample, ("tests.test_example", "test_core", "failure"), *GREEN[1:])
    assert results["core"]["state"] == "failed" and results["ui"]["state"] == "passed"
    for ident in ("H001", "H002"):
        assert rows[ident]["status"] == "needs_review" and rows[ident]["basis"] == "suite_failed"
        assert "core" in rows[ident]["remaining"]
    assert rows["H003"]["status"] == "equivalent" and rows["H003"]["basis"] == "reviewed"
    assert rows["H004"]["status"] == "partial"
    assert hs.metrics(list(rows.values()))["counts"]["equivalent"] == 1


def test_a_failing_suite_leaves_partial_and_missing_rows_alone(sample):
    add_review(sample, "partial", "Event delivery is still missing.")
    _, rows = judged(sample, ("tests.test_example", "test_core", "error"), *GREEN[1:])
    assert rows["H002"]["status"] == "partial" and rows["H002"]["basis"] == "reviewed"
    assert rows["H001"]["basis"] == "suite_failed"


@pytest.mark.parametrize("cases,reason", [
    # an entry the run never reached: the suite rotted or collection broke
    (GREEN[:2], "nerulate"),
    # a collection error is reported against the module, not a test
    ([("", "tests.test_ui", "error"), GREEN[0]], "picate"),
    # nothing passed: skips prove nothing
    ([GREEN[0], ("tests.test_ui.TestOwner", "test_can_open", "skipped"),
      ("tests.test_ui", "test_attacker", "skipped")], "niciun test"),
    # a parametrised case of a named node counts as that node
    ([GREEN[0], GREEN[1], ("tests.test_ui", "test_attacker[evil-input]", "failure")], "picate"),
])
def test_suite_state_is_judged_strictly(sample, cases, reason):
    results, _ = judged(sample, *cases)
    assert results["core"]["state"] == "passed"
    assert results["ui"]["state"] == "failed" and reason in results["ui"]["reason"]


def test_node_entries_do_not_absorb_neighbouring_tests(sample):
    # test_attacker_extra is not the node test_attacker; a failure there is not this suite's.
    results, _ = judged(sample, *GREEN, ("tests.test_ui", "test_attacker_extra", "failure"),
                        ("tests.test_ui.TestOther", "test_can_open", "failure"))
    assert results["ui"]["state"] == "passed"


def test_a_skipped_case_in_a_passing_suite_is_counted_not_fatal(sample):
    results, _ = judged(sample, *GREEN, ("tests.test_example", "test_live", "skipped"))
    assert results["core"] == {"state": "passed", "reason": "", "passed": 1, "skipped": 1,
                               "failed": [], "missing": []}


def test_an_area_left_out_of_the_run_keeps_its_verdicts(sample):
    ledger, data, areas, root = sample
    add_review(sample)
    results = hs.suite_results(areas["areas"], hs.read_junit(junit(GREEN[1], GREEN[2])), only={"ui"})
    assert set(results) == {"ui"}
    rows = hs.assess(ledger, data, areas, root, results=results)
    assert rows[1]["status"] == "equivalent"


def test_empty_junit_is_an_error_not_a_pass():
    with pytest.raises(ValueError, match="testcase"):
        hs.read_junit(junit())


# --- the area map ------------------------------------------------------------------------------

def test_an_unmapped_row_is_refused(sample):
    sample[2]["areas"][1]["rows"] = ["H003"]
    with pytest.raises(ValueError, match="no area: H004"):
        hs.assess(*sample)


def test_a_doubly_mapped_row_is_refused(sample):
    sample[2]["areas"][1]["rows"].append("H002")
    with pytest.raises(ValueError, match="H002 is mapped to both core and ui"):
        hs.assess(*sample)


@pytest.mark.parametrize("mutate,message", [
    (lambda a: a["areas"][0]["rows"].append("H999"), "unknown row"),
    (lambda a: a["areas"][0].update(lanes=["borrow"]), "lanes"),
    (lambda a: a["areas"][0].update(lanes=[]), "lanes"),
    (lambda a: a["areas"][0].update(suite_origin="guess"), "suite_origin"),
    (lambda a: a["areas"][0].update(id="ui"), "duplicate area"),
    (lambda a: a["areas"][0].update(extra=True), "fields"),
    (lambda a: a["areas"][0].update(suite=["tests/test_gone.py"]), "names no test file"),
    (lambda a: a["areas"][0].update(suite=["tests/test_example.py::test_gone"]), "nothing defined"),
    (lambda a: a["areas"][0].update(suite=["../outside.py"]), "invalid suite entry"),
    (lambda a: a["areas"][0].update(suite=["tests/test_example.py", "tests/test_example.py"]), "duplicate suite"),
    (lambda a: a.update(areas=[]), "area map"),
])
def test_a_broken_area_map_is_refused(sample, mutate, message):
    mutate(sample[2])
    with pytest.raises(ValueError, match=message):
        hs.assess(*sample)


def test_equivalent_rows_need_an_acceptance_suite(sample):
    sample[2]["areas"][0]["suite"] = []
    with pytest.raises(ValueError, match="acceptance suite"):
        hs.assess(*sample)
    sample[2]["areas"][1]["suite"] = []          # an area with no equivalent row may wait
    sample[2]["areas"][0]["suite"] = ["tests/test_example.py"]
    hs.assess(*sample)


def test_scoreboard_reports_lane_counts_and_thin_suites(sample):
    ledger, data, areas, root = sample
    add_review(sample)
    rows = hs.assess(*sample)
    items = {item["id"]: item for item in hs.board(rows, areas["areas"])}
    assert items["core"]["lanes"] == ["own"] and items["core"]["rows"] == 2
    assert items["core"]["counts"]["equivalent"] == 2 and items["core"]["suite"] == 1
    assert items["core"]["thin"] and items["core"]["covered"] == 1 and items["core"]["reviewed"] == 1
    status = hs.reports(rows, data, areas)["HERMES_STATUS.md"]
    detail = hs.reports(rows, data, areas)["docs/HERMES_CAPABILITIES.md"]
    assert "| [core](docs/HERMES_CAPABILITIES.md#area-core) — Core | own | 2 | 2 | 0 | 0 | 0 | 0 | 1 | **subțire**" in status
    assert "own/run" in status and "scrisă de owner" in status
    assert detail.index("| [core](#area-core)") < detail.index('<a id="h001">')


# --- inventory and review integrity --------------------------------------------------------------

@pytest.mark.parametrize("mutation", ["reorder", "rename", "append", "decision"])
def test_frozen_inventory_cannot_change_without_explicit_migration(sample, mutation):
    ledger = sample[0]
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
    ("summary", ""), ("extra", True), ("evidence", []),
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
    add_review(sample, ident="H003")
    with pytest.raises(ValueError, match="excluded"):
        hs.assess(*sample)


def test_explicit_reopening_preserves_identity_without_inheriting_equivalence(sample):
    before = copy.deepcopy(sample[0])
    reopen_scope(sample)
    rows = hs.assess(*sample)
    assert sample[0] == before
    assert rows[2]['id'] == 'H003' and rows[2]['decision'] == 'skip'
    assert rows[2]['status'] == 'needs_review'
    assert rows[2]['basis'] == 'scope_reopened'
    result = hs.metrics(rows)
    assert result['accepted'] == 4 and result['counts']['excluded'] == 0
    assert result['counts']['equivalent'] == 1 and result['reviewed'] == 0
    reports = hs.reports(rows, sample[1], sample[2])
    assert 'scope_reopened' not in reports['docs/HERMES_CAPABILITIES.md']
    assert 'Readmis' in reports['docs/HERMES_CAPABILITIES.md']


@pytest.mark.parametrize('field,value', [
    ('id', 'H999'), ('row_sha256', 'f' * 64), ('reason', ''),
    ('decided_at', 'yesterday'), ('decided_at', '2026-09-27'), ('extra', True),
])
def test_invalid_scope_reopening_is_refused(sample, field, value):
    entry = reopen_scope(sample)
    entry[field] = value
    with pytest.raises(ValueError):
        hs.assess(*sample)


def test_scope_reopening_cannot_duplicate_or_reclassify_accepted_rows(sample):
    entry = reopen_scope(sample)
    sample[1]['scope_reopenings'].append(copy.deepcopy(entry))
    with pytest.raises(ValueError, match='duplicate'):
        hs.assess(*sample)
    sample[1]['scope_reopenings'] = [entry]
    entry.update(id='H002', row_sha256=hs.digest(sample[0]['capabilities'][1]))
    with pytest.raises(ValueError, match='excluded'):
        hs.assess(*sample)


@pytest.mark.parametrize("path", ["../outside.py", "/tmp/a.py", "C:/temp/a.py", "agents\\a.py", ""])  # nosec B108  # refused input, never opened
def test_evidence_paths_must_stay_in_the_repository(sample, path):
    item = add_review(sample)
    item["evidence"][0] = path
    with pytest.raises(ValueError, match="path"):
        hs.assess(*sample)


# --- the real records ------------------------------------------------------------------------------

def test_real_inventory_covers_exactly_697_rows_and_reports_are_current():
    ledger, data, areas = hs.load()
    rows = hs.assess(ledger, data, areas, hs.REPO)
    assert len(rows) == 697
    assert len({row["id"] for row in rows}) == 697
    result = hs.metrics(rows)
    assert sum(result["counts"].values()) == 697
    formerly_excluded = {f'H{i:03}' for i, row in enumerate(ledger['capabilities'], 1)
                         if row['decision'] == 'skip'}
    assert len(formerly_excluded) == 107
    # Owner decision 2026-11-10 (docs/decisions/2026-11-10-hermes-integration-by-feature.md, §4):
    # these 32 return to the original audit's exclusion; every other former exclusion stays reopened.
    re_excluded = {
        "H050", "H054", "H077", "H087", "H102", "H110", "H125", "H128", "H149", "H166", "H213",
        "H215", "H233", "H239", "H292", "H324", "H341", "H371", "H376", "H384", "H489", "H546",
        "H565", "H568", "H572", "H584", "H587", "H609", "H627", "H628", "H638", "H662",
    }
    assert len(re_excluded) == 32 and re_excluded <= formerly_excluded
    assert {item['id'] for item in data['scope_reopenings']} == formerly_excluded - re_excluded
    assert {row["id"] for row in rows if row["status"] == "excluded"} == re_excluded
    assert result["counts"]["excluded"] == 32
    assert result["accepted"] == 697 - 32 == 665
    for relative, generated in hs.reports(rows, data, areas).items():
        assert (hs.REPO / relative).read_text(encoding="utf-8") == generated, relative


def test_real_area_map_holds_every_row_once_with_real_suites():
    ledger, data, areas = hs.load()
    row_ids = [f"H{i:03}" for i in range(1, 698)]
    area_list, owner = hs.areas_by_row(areas, row_ids, hs.REPO)
    assert set(owner) == set(row_ids)
    assert sum(len(a["rows"]) for a in area_list) == 697
    assert 18 <= len(area_list) <= 26
    rows = hs.assess(ledger, data, areas, hs.REPO)
    with_equivalent = {r["area"] for r in rows if r["status"] == "equivalent"}
    assert all(a["suite"] for a in area_list if a["id"] in with_equivalent)
    # No review still pins file content: evidence is a list of repository paths.
    assert all(isinstance(path, str) for item in data["reviews"] for path in item["evidence"])


def test_current_images_and_sdk_are_not_mistaken_for_full_inventory_parity():
    rows = {row["id"]: row for row in hs.assess(*hs.load(), hs.REPO)}
    # None of these is complete: the image/video providers, the SDK, the resident interpreter
    # (no remote kernel, no proven container) and execute_code (Docker, remote, output limits).
    for ident in ("H515", "H598", "H566", "H660", "H595"):
        assert rows[ident]["status"] == "partial", ident


def test_json_summary_and_bounded_listing(sample, capsys):
    # The public functions retain exact values; CLI formatting must not invent totals.
    result = hs.metrics(hs.assess(*sample))
    assert json.loads(json.dumps(result))["total"] == 4
    assert hs.main(["list", "--limit", "2"]) == 0
    output = capsys.readouterr().out
    assert len([line for line in output.splitlines() if line.startswith("H")]) == 2
    assert len(output) < 800
    assert hs.main(["list", "--area", "mcp", "--limit", "697"]) == 0
    assert "13 of 13 rows" in capsys.readouterr().out


def test_cli_unknown_row_is_a_named_failure(capsys):
    assert hs.main(["show", "H999"]) == 1
    assert "not found" in capsys.readouterr().err


def test_show_recorded_keeps_the_stored_review_beside_a_demoted_assessment(sample):
    """Main's `show --recorded` (historical reviews made explicit), carried into schema 3: the
    stored review is diagnostic history; the current assessment a failing suite demoted wins."""
    ledger, data, areas, _ = sample
    item = copy.deepcopy(add_review(sample))
    _, rows = judged(sample, ("tests.test_example", "test_core", "failure"), *GREEN[1:])
    shown = hs.show_payload(ledger, data, areas, rows["H002"], recorded=True)
    assert shown["assessment"]["status"] == "needs_review" and shown["assessment"]["basis"] == "suite_failed"
    assert shown["recorded_review"] == item and shown["recorded_review"]["status"] == "equivalent"
    assert shown["original"] == ledger["capabilities"][1] and shown["area"]["id"] == "core"
    plain = hs.show_payload(ledger, data, areas, rows["H001"])
    assert "recorded_review" not in plain
    assert hs.show_payload(ledger, data, areas, rows["H001"], recorded=True)["recorded_review"] is None


def test_cli_show_recorded_flag_is_reachable(capsys):
    assert hs.main(["show", "--recorded", "h001"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"assessment", "area", "original", "recorded_review"}
    assert hs.main(["show", "h999", "--recorded"]) == 1
    assert "not found: h999" in capsys.readouterr().err


def test_cli_verify_reads_a_junit_result_without_running_tests(tmp_path, capsys):
    _, _, areas = hs.load()
    area = next(a for a in areas["areas"] if a["id"] == "agent-interop")
    modules = [entry.split("::")[0][:-3].replace("/", ".") for entry in area["suite"]]
    path = tmp_path / "junit.xml"
    path.write_text(junit(*[(m, "test_anything", "passed") for m in modules]), encoding="utf-8")
    assert hs.main(["verify", "--junit", str(path), "--area", "agent-interop"]) == 0
    assert "1/1 area suites pass" in capsys.readouterr().out
    path.write_text(junit(*[(m, "test_anything", "failure") for m in modules]), encoding="utf-8")
    assert hs.main(["verify", "--junit", str(path), "--area", "agent-interop"]) == 1
    assert "FAIL agent-interop" in capsys.readouterr().out
    assert hs.main(["verify", "--junit", str(path), "--area", "nowhere"]) == 2
