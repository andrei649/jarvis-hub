"""The two query tools that keep a 957 KB backlog and a 1.4 MB ledger out of context.

``docs/AI_CONTEXT.md`` has said "do not load ``BACKLOG.md`` whole" since the
2026-08-27 re-measure, and the file kept being loaded whole anyway, because
advice without a tool is not followable: there was no way to ask "what is still
open" that did not involve reading 176K tokens.

``scripts/backlog.py`` and ``scripts/ledger.py`` are that way. What is pinned
here is what makes them trustworthy enough to replace reading the file: they
parse the real documents (not a fixture), they answer the same numbers the
documents contain, and their output is *bounded* — the whole point is that a
listing costs a rounding error against the source, so a regression that starts
dumping bodies would quietly restore the original problem.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 — fixed argv, no shell
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts import backlog as backlog_tool  # noqa: E402
from scripts import ledger as ledger_tool  # noqa: E402

BACKLOG = REPO / "BACKLOG.md"
LEDGER = REPO / "docs" / "research" / "2026-09-07-hermes-absorption-ledger.json"


def run(script: str, *args: str) -> str:
    """Invoke a tool the way a caller actually does: as a subprocess."""
    proc = subprocess.run(  # nosec B603 — fixed interpreter and script path
        [sys.executable, str(REPO / "scripts" / script), *args],
        capture_output=True, text=True, encoding="utf-8", check=False, cwd=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


# ── the backlog tool ─────────────────────────────────────────────────────────

def test_the_parser_agrees_with_the_file_it_parses():
    """Grep counts the checkboxes; the parser must find exactly those."""
    raw = BACKLOG.read_text(encoding="utf-8").splitlines()
    checkboxes = [line for line in raw if line.startswith("- [")]
    rows = backlog_tool.parse(BACKLOG)
    assert len(rows) == len(checkboxes)
    assert sum(1 for r in rows if not r.done) == sum(
        1 for line in checkboxes if line.startswith("- [ ]")
    )


def test_a_rows_body_is_the_indented_lines_that_follow_it():
    rows = {r.ident: r for r in backlog_tool.parse(BACKLOG) if r.ident}
    row = rows["HA-4i"]
    assert not row.done
    assert row.body, "a multi-line row must carry its continuation"
    assert all(not line.strip() or line.startswith("  ") for line in row.body)
    assert row.body[-1].strip(), "trailing blank lines are trimmed"


def test_lettered_ids_are_recognised_not_just_numbered_ones():
    """SEC-B5 and GAP-4 are real ids; an id pattern demanding a digit after the
    dash silently files them under "(no id)" and they become unaddressable."""
    idents = {r.ident for r in backlog_tool.parse(BACKLOG) if r.ident}
    assert {"SEC-B5", "SEC-B6", "GAP-4", "HA-4i"} <= idents


def test_a_summary_carries_the_rows_words_not_its_markup():
    rows = {r.ident: r for r in backlog_tool.parse(BACKLOG) if r.ident}
    summary = rows["HA-4i"].summary
    assert summary.startswith("HA-4i")
    assert "- [ ]" not in summary and "**" not in summary
    assert len(summary) <= backlog_tool.SUMMARY_CHARS


def test_listing_every_open_row_stays_a_rounding_error_against_the_file():
    """The reason the tool exists. If this ratio ever collapses, so has the point."""
    listing = run("backlog.py", "open", "--limit", "500")
    assert len(listing) * 50 < BACKLOG.stat().st_size
    assert "HA-4i" in listing


def test_counts_matches_a_plain_grep():
    text = run("backlog.py", "counts")
    raw = BACKLOG.read_text(encoding="utf-8").splitlines()
    open_rows = sum(1 for line in raw if line.startswith("- [ ]"))
    assert f"open: {open_rows}" in text


def test_show_prints_one_row_whole_and_says_where_it_lives():
    text = run("backlog.py", "show", "HA-4i")
    assert "BACKLOG.md:" in text and "section:" in text
    assert "the rest of the depth wave" in text


def test_show_reports_an_unknown_id_rather_than_pretending():
    proc = subprocess.run(  # nosec B603
        [sys.executable, str(REPO / "scripts" / "backlog.py"), "show", "NOPE-99"],
        capture_output=True, text=True, check=False, cwd=REPO,
    )
    assert proc.returncode == 1
    assert "not found: NOPE-99" in proc.stderr


def test_find_can_be_narrowed_to_open_rows(tmp_path: Path):
    sample = tmp_path / "B.md"
    sample.write_text(
        "## S\n- [x] **A-1** — done thing about taint\n- [ ] **A-2** — open thing about taint\n",
        encoding="utf-8",
    )
    both = backlog_tool.main(["--file", str(sample), "find", "taint"])
    assert both == 0
    rows = backlog_tool.parse(sample)
    assert len(rows) == 2 and sum(1 for r in rows if not r.done) == 1


def test_a_bad_regex_is_an_error_not_a_traceback(tmp_path: Path):
    sample = tmp_path / "B.md"
    sample.write_text("- [ ] **A-1** — x\n", encoding="utf-8")
    assert backlog_tool.main(["--file", str(sample), "find", "("]) == 2


def test_a_missing_file_is_reported_not_raised(tmp_path: Path):
    assert backlog_tool.main(["--file", str(tmp_path / "nope.md"), "counts"]) == 2
    assert ledger_tool.main(["--file", str(tmp_path / "nope.json"), "stats"]) == 2


def table_fixture(tmp_path: Path) -> Path:
    sample = tmp_path / "B.md"
    sample.write_text(
        "## Horizon work\n"
        "| ID | Task | Status |\n"
        "| --- | --- | --- |\n"
        "| H18.1 ⬜ | Open route; prose says ✅ done later | queued |\n"
        "| T-0.49 ✅ | Finished task | complete |\n"
        "| A1 🔨 | Delivered gate | pending runtime proof |\n"
        "| H18.2 🔴 | Blocked task | owner action |\n"
        "| H18.3 | Fallback state | 🟢 done |\n"
        "| P2 | No marker remains open | unknown |\n"
        "\n## Project history\n"
        "| ID | Task | Status |\n| --- | --- | --- |\n"
        "| H99.1 ⬜ | Historical example | open |\n"
        "\n## Metrics dashboard\n"
        "| ID | Task | Status |\n| --- | --- | --- |\n"
        "| T-99.1 ⬜ | Metric row | open |\n"
        "\n## Evidence snapshot\n"
        "| ID | Task | Status |\n| --- | --- | --- |\n"
        "| A99 ⬜ | Evidence row | open |\n"
        "\n## Unclassified work\n"
        "| ID | Task | Status |\n| --- | --- | --- |\n"
        "| task-alpha | Unclassified item | ⬜ |\n"
        "\n```markdown\n"
        "## Fenced work\n| ID | Task | Status |\n| --- | --- | --- |\n"
        "| H88.1 ⬜ | Fenced example | open |\n```\n",
        encoding="utf-8",
    )
    return sample


def test_table_counts_classify_leading_markers_and_disclose_unclassified_tables(tmp_path: Path):
    sample = table_fixture(tmp_path)
    data = json.loads(run("backlog.py", "--file", str(sample), "tables", "counts", "--json"))
    assert data["totals"] == {
        "total": 6, "done": 2, "delivered": 1, "blocked": 1,
        "open": 2, "open_or_blocked": 3,
    }
    assert data["sections"] == [{"section": "Horizon work", **data["totals"]}]
    assert data["unclassified_tables"] == 1
    assert data["diagnostics"][0]["section"] == "Unclassified work"
    assert data["diagnostics"][0]["line"] > 0
    assert "Unclassified item" not in str(data)
    assert all(word not in str(data) for word in ("Historical example", "Metric row", "Evidence row", "Fenced example"))


def test_table_list_is_bounded_filterable_and_preserves_prose_open(tmp_path: Path):
    sample = table_fixture(tmp_path)
    data = json.loads(run("backlog.py", "--file", str(sample), "tables", "list", "--open-only", "--limit", "2", "--json"))
    assert data["total"] == 3
    assert [row["id"] for row in data["rows"]] == ["H18.1", "H18.2"]
    assert data["rows"][0]["status"] == "open"
    assert data["rows"][0]["line"] == 4
    assert data["rows"][0]["section"] == "Horizon work"
    assert len(data["rows"][0]["summary"]) <= backlog_tool.SUMMARY_CHARS
    filtered = json.loads(run("backlog.py", "--file", str(sample), "tables", "list", "--section", "history", "--json"))
    assert filtered["total"] == 0


def test_table_show_names_exact_ids_and_reports_unknown(tmp_path: Path):
    sample = table_fixture(tmp_path)
    shown = json.loads(run("backlog.py", "--file", str(sample), "tables", "show", "T-0.49", "A1", "--json"))
    assert [row["id"] for row in shown["rows"]] == ["T-0.49", "A1"]
    assert [row["status"] for row in shown["rows"]] == ["done", "delivered"]
    assert all(row["section"] == "Horizon work" for row in shown["rows"])
    assert "Open route" not in str(shown)
    proc = subprocess.run(  # nosec B603
        [sys.executable, str(REPO / "scripts" / "backlog.py"), "--file", str(sample), "tables", "show", "H18.9"],
        capture_output=True, text=True, check=False, cwd=REPO,
    )
    assert proc.returncode == 1
    assert "not found: H18.9" in proc.stderr


def test_table_extension_leaves_checkbox_query_output_unchanged(tmp_path: Path):
    sample = table_fixture(tmp_path)
    with_checkboxes = tmp_path / "C.md"
    with_checkboxes.write_text(sample.read_text(encoding="utf-8") + "\n## Checkboxes\n- [ ] **A-1** — open checkbox\n- [x] **A-2** — done checkbox\n", encoding="utf-8")
    assert run("backlog.py", "--file", str(with_checkboxes), "counts").startswith("rows: 2  done: 1  open: 1")
    assert "A-1" in run("backlog.py", "--file", str(with_checkboxes), "open")
    assert "open checkbox" in run("backlog.py", "--file", str(with_checkboxes), "show", "A-1")


def test_numbered_item_tables_count_work_ids_in_the_item_column(tmp_path: Path):
    sample = tmp_path / "B.md"
    sample.write_text(
        "## Capability program\n"
        "| # | Item | S | P |\n| --- | --- | --- | --- |\n"
        "| 1 | **H27.1 ⬜ — Capability registry** | open | P0 |\n"
        "| 2 | **H27.2 🔨 — Action API** | delivered | P0 |\n"
        "| 3 | T-0.49 | ✅ done | P1 |\n"
        "\n## Evidence snapshot\n"
        "| # | Item | S | P |\n| --- | --- | --- | --- |\n"
        "| 1 | H99.1 ⬜ — old evidence | open | P0 |\n",
        encoding="utf-8",
    )
    data = json.loads(run("backlog.py", "--file", str(sample), "tables", "counts", "--json"))
    assert data["totals"] == {"total": 3, "done": 1, "delivered": 1, "blocked": 0, "open": 1, "open_or_blocked": 1}
    listed = json.loads(run("backlog.py", "--file", str(sample), "tables", "list", "--json"))
    assert [row["id"] for row in listed["rows"]] == ["H27.1", "H27.2", "T-0.49"]
    assert listed["rows"][0]["summary"] == "Capability registry"


def test_table_parser_does_not_promote_cross_references_to_item_ids(tmp_path: Path):
    sample = tmp_path / "B.md"
    sample.write_text(
        "## Mobile work\n| # | Item | S |\n| --- | --- | --- |\n"
        "| 1 | App integration maps to H27.6 | ⬜ |\n"
        "| 2 | H18.x umbrella remains open | ⬜ |\n"
        "| 3 | H18.1 ⬜ — Native shell | open |\n",
        encoding="utf-8",
    )
    data = json.loads(run("backlog.py", "--file", str(sample), "tables", "list", "--json"))
    assert [row["id"] for row in data["rows"]] == ["H18.1"]
    assert data["unclassified_tables"] == 1
    assert data["diagnostics"][0]["unclassified_rows"] == 2


def test_number_column_can_carry_the_work_id_and_leading_marker(tmp_path: Path):
    sample = tmp_path / "B.md"
    sample.write_text(
        "## Observability work\n| # | Item | S |\n| --- | --- | --- |\n"
        "| H10.16 ✅ | APM | done |\n"
        "| H10.17 🔨 | Usage accounting | pending proof |\n"
        "| H10.18 | Context meter | ⬜ open |\n",
        encoding="utf-8",
    )
    data = json.loads(run("backlog.py", "--file", str(sample), "tables", "list", "--json"))
    assert [(row["id"], row["status"], row["summary"]) for row in data["rows"]] == [
        ("H10.16", "done", "APM"),
        ("H10.17", "delivered", "Usage accounting"),
        ("H10.18", "open", "Context meter"),
    ]


def test_project_lettered_horizon_and_gate_ids_are_work_items(tmp_path: Path):
    sample = tmp_path / "B.md"
    sample.write_text(
        "## Program work\n| # | Item | S |\n| --- | --- | --- |\n"
        "| O26-P0.1 ✅ | Golden loop | complete |\n"
        "| H20.L1 🔨 | Iteration budget | pending proof |\n"
        "| H21.A 🔴 | Secret handoff | owner blocked |\n"
        "| H20.M3a ✅ | Execution primitive | complete |\n"
        "| **Gate K** ✅ | Action-auth gate | complete |\n",
        encoding="utf-8",
    )
    data = json.loads(run("backlog.py", "--file", str(sample), "tables", "list", "--json"))
    assert [(row["id"], row["status"]) for row in data["rows"]] == [
        ("O26-P0.1", "done"), ("H20.L1", "delivered"), ("H21.A", "blocked"),
        ("H20.M3a", "done"), ("Gate K", "done"),
    ]


def test_table_queries_reject_unbounded_lists_and_ambiguous_ids(tmp_path: Path):
    sample = tmp_path / "B.md"
    sample.write_text(
        "## Tasks\n| ID | Task |\n| --- | --- |\n"
        "| H18.1 ⬜ | First |\n| H18.1 ✅ | Second |\n",
        encoding="utf-8",
    )
    counts = json.loads(run("backlog.py", "--file", str(sample), "tables", "counts", "--json"))
    assert counts["duplicate_ids"] == 1
    assert counts["duplicate_examples"] == [{"id": "H18.1", "lines": [4, 5]}]
    for args, message in [(("list", "--limit", "501"), "--limit must be between"),
                          (("show", "H18.1"), "ambiguous id: H18.1")]:
        proc = subprocess.run(  # nosec B603
            [sys.executable, str(REPO / "scripts" / "backlog.py"), "--file", str(sample), "tables", *args],
            capture_output=True, text=True, check=False, cwd=REPO,
        )
        assert proc.returncode == 2
        assert message in proc.stderr


def test_nested_history_and_metrics_are_excluded_but_active_metrics_work_is_visible(tmp_path: Path):
    sample = tmp_path / "B.md"
    sample.write_text(
        "## Project history\n### Archived tasks\n"
        "| ID | Task | Status |\n| --- | --- | --- |\n"
        "| H99.1 ⬜ | Historical task | open |\n"
        "## Metrics dashboard\n### Latest indicators\n"
        "| ID | Task | Status |\n| --- | --- | --- |\n"
        "| H99.2 ⬜ | Metric indicator | open |\n"
        "## Active delivery\n"
        "| ID | Task | Status |\n| --- | --- | --- |\n"
        "| H18.1 ⬜ | Current work | open |\n"
        "## Observability metrics integration\n"
        "| ID | Task | Status |\n| --- | --- | --- |\n"
        "| H18.2 ⬜ | Current metric instrumentation | open |\n",
        encoding="utf-8",
    )
    data = json.loads(run("backlog.py", "--file", str(sample), "tables", "list", "--json"))
    assert [row["id"] for row in data["rows"]] == ["H18.1", "H18.2"]
    assert data["excluded_tables"] == 2
    assert [(row["section"], row["excluded_by"]) for row in data["excluded_diagnostics"]] == [
        ("Archived tasks", "Project history"), ("Latest indicators", "Metrics dashboard"),
    ]
    history = json.loads(run("backlog.py", "--file", str(sample), "tables", "counts", "--section", "history", "--json"))
    assert history["totals"]["total"] == 0
    assert history["excluded_tables"] == 1


def test_unknown_ids_in_ranked_work_table_emit_a_bounded_diagnostic(tmp_path: Path):
    sample = tmp_path / "B.md"
    sample.write_text(
        "## Active delivery\n"
        "| Rank | Item | Status |\n| --- | --- | --- |\n"
        "| 1 | alpha-login | ⬜ open |\n"
        "| 2 | beta-session | 🔴 blocked |\n",
        encoding="utf-8",
    )
    data = json.loads(run("backlog.py", "--file", str(sample), "tables", "counts", "--json"))
    assert data["totals"]["total"] == 0
    assert data["unclassified_tables"] == 1
    assert data["diagnostics"] == [{
        "section": "Active delivery", "line": 2, "header": "Rank | Item | Status",
        "unclassified_rows": 2, "sample_key": "alpha-login", "sample_number": "1",
        "mentioned_ids": [], "status_hints": {"done": 0, "delivered": 0, "blocked": 1, "open": 1},
    }]


# ── the ledger tool ──────────────────────────────────────────────────────────

def test_ledger_stats_reports_the_numbers_the_file_records():
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    totals = data["totals"]
    text = run("ledger.py", "stats")
    assert f"capabilities: {totals['capabilities']}" in text
    work = totals["copy"] + totals["update"]
    assert f"work rows (copy + update): {work}" in text


def test_work_means_copy_plus_update_and_nothing_else():
    assert set(ledger_tool.WORK) == {"copy", "update"}
    data = ledger_tool.load(LEDGER)
    counted = sum(1 for r in data["capabilities"] if r["decision"] in ledger_tool.WORK)
    assert counted == data["totals"]["copy"] + data["totals"]["update"]


def test_a_cluster_listing_is_orders_of_magnitude_smaller_than_the_ledger():
    listing = run("ledger.py", "list", "--cluster", "cli", "--limit", "200")
    assert len(listing) * 100 < LEDGER.stat().st_size


def test_listing_filters_compose():
    text = run("ledger.py", "list", "--decision", "copy", "--effort", "S", "--limit", "500")
    body = [line for line in text.splitlines() if line.strip() and not line.startswith("…")]
    rows = [line for line in body if line.startswith("copy")]
    assert rows, "the filter must match something"
    assert len(rows) == len(body) - 1, "no non-copy row may survive a --decision copy filter"


def test_show_reports_no_match_rather_than_an_empty_success():
    proc = subprocess.run(  # nosec B603
        [sys.executable, str(REPO / "scripts" / "ledger.py"), "show", "zzz-not-a-capability"],
        capture_output=True, text=True, check=False, cwd=REPO,
    )
    assert proc.returncode == 1
    assert "no capability matching" in proc.stderr


@pytest.mark.parametrize("script,args", [
    ("backlog.py", ["open", "--limit", "500"]),
    ("backlog.py", ["sections"]),
    ("ledger.py", ["clusters"]),
    ("ledger.py", ["list", "--limit", "500"]),
])
def test_a_closed_pipe_is_a_normal_end_not_a_crash(script: str, args: list[str]):
    """`… | head` is the whole ergonomic point; a traceback there sends the
    reader straight back to opening the file.

    The pipe is built from two processes rather than a shell string: a shell here
    would be an injection seam for no benefit, and `head` closing its end is what
    the tool has to survive either way.
    """
    tool = subprocess.Popen(  # nosec B603 — fixed interpreter and script path
        [sys.executable, str(REPO / "scripts" / script), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=REPO,
    )
    head = subprocess.Popen(  # nosec B603 B607 — fixed argv
        ["head", "-3"], stdin=tool.stdout, stdout=subprocess.DEVNULL, text=True,
    )
    tool.stdout.close()  # only `head` holds the read end, so its exit closes the pipe
    head.wait()
    stderr = tool.communicate()[1]
    assert tool.returncode == 0, stderr
    assert "BrokenPipeError" not in stderr
    assert "Exception ignored" not in stderr


@pytest.mark.parametrize("tool", [backlog_tool, ledger_tool])
@pytest.mark.parametrize("failure_stage", [None, "write", "flush"])
@pytest.mark.parametrize("exit_status", [0, 2])
def test_query_flush_is_inside_broken_pipe_handling(
    monkeypatch, tool, failure_stage, exit_status,
):
    flushes = []
    redirects = []

    class Output:
        def flush(self):
            flushes.append(True)
            if failure_stage == "flush":
                raise BrokenPipeError("reader closed after buffered output")

        def fileno(self):
            return 198

    def command(argv):
        assert argv == ["fixture"]
        if failure_stage == "write":
            raise BrokenPipeError("reader closed during output")
        return exit_status

    with monkeypatch.context() as patch:
        patch.setattr(tool, "_run", command)
        patch.setattr(sys, "stdout", Output())
        patch.setattr(os, "dup2", lambda source, target: redirects.append((source, target)))
        result = tool.main(["fixture"])

    assert result == (0 if failure_stage else exit_status)
    assert len(flushes) == (0 if failure_stage == "write" else 1)
    if failure_stage:
        assert len(redirects) == 1 and redirects[0][1] == 198
        with pytest.raises(OSError):
            os.fstat(redirects[0][0])
    else:
        assert redirects == []


@pytest.mark.parametrize("script,command", [("backlog.py", "sections"), ("ledger.py", "list")])
@pytest.mark.parametrize("missing", [False, True])
def test_redirected_queries_preserve_unicode_with_a_windows_legacy_encoding(tmp_path, script, command, missing):
    """A cp1252 pipe must not crash or replace Romanian text, arrows and emoji."""
    label = "Română → 🟡"
    sample = tmp_path / f"{label}.data"
    if not missing:
        body = (f"## {label}\n- [ ] **A-1** — {label}\n" if script == "backlog.py" else
                json.dumps({"capabilities": [{"name": label, "decision": "copy", "effort": "S"}]}))
        sample.write_text(body, encoding="utf-8")
    result = subprocess.run(  # nosec B603 — fixed interpreter and script path
        [sys.executable, str(REPO / "scripts" / script), "--file", str(sample), command],
        capture_output=True, check=False, cwd=REPO,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert result.returncode == (2 if missing else 0), result.stderr.decode("utf-8", errors="replace")
    output = result.stderr if missing else result.stdout
    assert label in output.decode("utf-8")
    assert b"UnicodeEncodeError" not in result.stderr
