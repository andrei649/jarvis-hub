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
