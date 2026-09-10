"""H298: a huge tool result leaves the context window without leaving the machine.

The old behaviour truncated an oversized result to head+tail and dropped the rest.
That is safe for the context and wrong for two other things, and both are what these
tests are really about:

* the **audit** and the model stop agreeing — a truncated `file_read` or governed
  `terminal_run` transcript means the owner reviewing an approval sees less than the
  tool produced;
* the bytes are **repeatable but not recoverable** — the only way back is to run the
  tool again, which is the expensive thing the cap existed to prevent, and a
  non-deterministic tool cannot even do that.

So the result is spilled and the preview names the file. The tests below pin the
resolution order that decides *when*, the budget that decides *how much*, the regress
guard that stops a spill's own read from spilling, and the retention that stops the
directory growing on a box nobody is watching.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from agents.core import tool_result_store as trs
from agents.core.tool_result_store import (
    MCP_DEFAULT_BYTES,
    PER_RESULT_FLOOR_BYTES,
    PER_TURN_FLOOR_BYTES,
    ToolResultStore,
    budget_for_context_window,
    preview_envelope,
    threshold_for,
)


def _store(tmp_path, **kwargs):
    return ToolResultStore(tmp_path / "spills", **kwargs)


# ── which tool, and how much ─────────────────────────────────────────────────

def test_the_threshold_resolves_most_specific_rule_first():
    # pinned beats an override, an override beats the mcp_ family, the family beats
    # a declared maximum, and a declared maximum beats the default.
    assert threshold_for("file_read", overrides={"file_read": 10}) == math.inf
    assert threshold_for("mcp_notes", overrides={"mcp_notes": 999}) == 999
    assert threshold_for("mcp_notes") == MCP_DEFAULT_BYTES
    assert threshold_for("echo", declared=1234) == 1234
    assert threshold_for("echo", default=4321) == 4321


@pytest.mark.parametrize("bad", [0, -1, "", "big", None, 3.7e400])
def test_an_unusable_override_falls_through_rather_than_disabling_the_cap(bad):
    # A malformed override must not read as "no limit": the next rule down applies.
    assert threshold_for("echo", overrides={"echo": bad}, default=777) == 777


def test_file_read_is_pinned_because_it_is_how_a_spill_is_read_back():
    """The regress guard. Without it a large file spills, and reading that spill
    spills again, and each file describes the last — unbounded, on disk."""
    assert threshold_for("file_read") == math.inf
    assert threshold_for("file_read", declared=10, overrides={"file_read": 10}) == math.inf


# ── how much, scaled to the model actually in use ────────────────────────────

def test_the_budget_scales_with_the_window_and_never_below_the_floors():
    small = budget_for_context_window(1_000)
    assert small.per_result_bytes == PER_RESULT_FLOOR_BYTES
    assert small.per_turn_bytes == PER_TURN_FLOOR_BYTES
    big = budget_for_context_window(200_000)
    assert big.per_result_bytes == int(200_000 * 4 * 0.15)
    assert big.per_turn_bytes == int(200_000 * 4 * 0.30)
    # A turn may hold more than one result, but not many: that is the whole point of
    # having a second number rather than one cap applied repeatedly.
    assert big.per_turn_bytes == 2 * big.per_result_bytes


@pytest.mark.parametrize("window", [None, "eight thousand", -5, 0])
def test_an_unreadable_window_uses_the_floors(window):
    budget = budget_for_context_window(window)
    assert budget.per_result_bytes == PER_RESULT_FLOOR_BYTES
    assert budget.per_turn_bytes == PER_TURN_FLOOR_BYTES


# ── the spill itself ─────────────────────────────────────────────────────────

def test_a_spill_keeps_every_byte_and_names_the_file(tmp_path):
    store = _store(tmp_path)
    body = json.dumps({"ok": True, "rows": ["x" * 200] * 500})
    spill = store.spill(body, tool="file_read")
    assert spill is not None
    assert spill.original_bytes == len(body.encode("utf-8"))
    # The whole thing, byte for byte — that is the difference from truncation.
    assert (tmp_path / "spills" / spill.reference).read_text(encoding="utf-8") == body
    # `read` is bounded by default on purpose (the next test pins that); ask for
    # enough here, because what this test is about is that nothing was lost.
    assert store.read(spill.reference, max_bytes=len(body) + 1) == body


def test_the_preview_carries_the_path_and_a_bounded_slice_of_the_result(tmp_path):
    store = _store(tmp_path)
    body = json.dumps({"ok": True, "head_marker": "FIRST", "tail_marker": "LAST",
                       "filler": "y" * 40_000})
    spill = store.spill(body, tool="web_extract")
    envelope = json.loads(preview_envelope(
        body, tool="web_extract", ok=True, reason=None, spill=spill))
    assert envelope["spilled"] is True and envelope["truncated"] is True
    assert envelope["result_file"] == spill.path
    assert envelope["original_bytes"] == len(body.encode("utf-8"))
    assert envelope["sha256"] == spill.sha256
    # Bounded, and still useful at both ends.
    assert len(envelope["preview"]["head"]) + len(envelope["preview"]["tail"]) <= trs.PREVIEW_CHARS
    assert "FIRST" in envelope["preview"]["head"]
    assert "y" * 40_000 not in json.dumps(envelope)
    # And it says what to do instead of running the expensive tool a second time.
    assert "file_read" in envelope["notice"]


def test_an_unwritable_store_reports_failure_instead_of_raising(tmp_path):
    # A spill that cannot be written is not a lost turn: the caller still has a
    # correct bounded answer, it is only the lossy one.
    blocker = tmp_path / "spills"
    blocker.write_text("not a directory", encoding="utf-8")
    assert ToolResultStore(blocker).spill("{}", tool="echo") is None


def test_the_same_bytes_reuse_one_file_rather_than_multiplying(tmp_path):
    store = _store(tmp_path)
    body = json.dumps({"ok": True, "v": "z" * 5_000})
    first = store.spill(body, tool="echo")
    second = store.spill(body, tool="echo")
    assert first.reference == second.reference
    assert len(list((tmp_path / "spills").glob("*.json"))) == 1


# ── reading one back, and refusing anything that is not one ──────────────────

@pytest.mark.parametrize("reference", [
    "../../etc/passwd", "/etc/passwd", "..%2Fx.json", "", "x.md", "x",
    "a" * 200 + ".json", "sub/dir.json",
])
def test_read_refuses_anything_that_is_not_a_reference_in_the_spill_directory(
    tmp_path, reference,
):
    store = _store(tmp_path)
    store.spill("{}", tool="echo")
    assert store.read(reference) is None


def test_only_the_name_pattern_stands_between_a_normalising_path_and_a_read(tmp_path):
    """The pattern is load-bearing on its own, not a duplicate of the parent check.

    Every case above is *also* caught by the containment check that follows it, so
    deleting the pattern leaves them all green. These two are the difference. A
    reference carrying path segments that normalise straight back into the spill
    directory passes containment — ``resolve()`` collapses ``sub/..`` before the
    parent is compared — and a plain file dropped in that directory by something
    else is contained by definition. Neither is a spilled result, and the door only
    opens for spilled results.
    """
    store = _store(tmp_path)
    root = tmp_path / "spills"
    spill = store.spill(json.dumps({"secret": "s" * 100}), tool="echo")
    assert store.read(spill.reference) is not None, "the real reference still works"

    # Contained (resolve() collapses the traversal) but not a reference.
    assert store.read(f"sub/../{spill.reference}") is None
    assert store.read(f"./{spill.reference}") is None

    # Contained because it genuinely lives there — and still not a reference: the
    # spill root sits under the workspace the file tools write to, so "a file in
    # this directory" is not the same claim as "a result this store wrote".
    # `.json` and `.txt` are both real spill shapes (a result and a stream), so the
    # names that prove the pattern are the ones outside that vocabulary.
    for name in ("notes.md", "UPPER.JSON", "has space.json", "readme",
                 "x" * 130 + ".txt"):
        (root / name).write_text("not a spill", encoding="utf-8")
        assert store.read(name) is None, name


def test_only_the_containment_check_stands_between_a_symlink_and_a_read(tmp_path):
    """And the converse: the pattern alone would serve a link pointing out.

    A name can satisfy the pattern perfectly and still resolve outside the spill
    directory, because the store's root is inside the workspace and a link is a
    file the model can create there. Containment is checked against the resolved
    path for exactly this reason.
    """
    outside = tmp_path / "elsewhere.json"
    outside.write_text(json.dumps({"private": True}), encoding="utf-8")
    store = _store(tmp_path)
    store.spill("{}", tool="echo")
    link = tmp_path / "spills" / "echo-0123456789abcdef.json"
    link.symlink_to(outside)
    assert trs._REFERENCE.fullmatch(link.name), "the name is a valid reference by pattern"
    assert store.read(link.name) is None


def test_read_is_bounded_so_a_spill_cannot_be_pulled_back_whole_by_accident(tmp_path):
    store = _store(tmp_path)
    body = "q" * 90_000
    spill = store.spill(body, tool="echo")
    assert len(store.read(spill.reference, max_bytes=1_000)) == 1_000


# ── retention: the dependency the row names ──────────────────────────────────

def test_age_retention_removes_old_spills_and_never_the_one_just_written(tmp_path):
    now = {"t": 10_000.0}
    store = _store(tmp_path, retention_seconds=100, clock=lambda: now["t"])
    old = store.spill(json.dumps({"v": "old"}), tool="echo")
    now["t"] += 10_000
    fresh = store.spill(json.dumps({"v": "new"}), tool="echo")
    names = {path.name for path in (tmp_path / "spills").glob("*.json")}
    assert fresh.reference in names
    assert old.reference not in names


def test_the_file_count_is_bounded_oldest_first(tmp_path):
    now = {"t": 0.0}
    store = _store(tmp_path, max_files=3, clock=lambda: now["t"])
    references = []
    for index in range(6):
        now["t"] += 10
        references.append(store.spill(json.dumps({"i": index}), tool="echo").reference)
    names = {path.name for path in (tmp_path / "spills").glob("*.json")}
    assert len(names) <= 3
    assert references[-1] in names      # the newest survives
    assert references[0] not in names   # the oldest does not


def test_the_total_size_is_bounded_too(tmp_path):
    now = {"t": 0.0}
    store = _store(tmp_path, max_total_bytes=20_000, clock=lambda: now["t"])
    for index in range(8):
        now["t"] += 10
        store.spill(json.dumps({"i": index, "pad": "p" * 8_000}), tool="echo")
    total = sum(path.stat().st_size for path in (tmp_path / "spills").glob("*.json"))
    assert total <= 20_000


def test_a_sweep_over_a_directory_that_does_not_exist_is_not_an_error(tmp_path):
    assert _store(tmp_path).sweep() == 0


# ── the claim the preview footer makes ───────────────────────────────────────

def test_the_default_spill_root_is_inside_the_file_tools_default_scope(monkeypatch):
    """The footer tells the model to read the file with `file_read`. It must be able to.

    This is the whole bargain of a spill: bounded in context, complete on disk,
    and reachable without a second mechanism. If either side's default root moves,
    the preview starts naming a path the model is refused, and the row quietly
    goes back to being a truncation with extra steps.
    """
    from agents.core.file_tools import ROOTS_ENV, FileScope

    monkeypatch.delenv(ROOTS_ENV, raising=False)
    scope = FileScope.from_env()
    root = ToolResultStore().root.resolve()

    assert scope.root_for(root) is not None, f"{root} is outside {scope.roots}"


# ── a stream nobody may hold whole (H305/H595) ───────────────────────────────

def test_a_streamed_spill_lands_content_addressed_and_complete(tmp_path):
    store = _store(tmp_path)
    spill = store.open_stream(tool="execute-code-stdout")
    body = b"".join(b"line-%d\n" % i for i in range(50_000))
    for start in range(0, len(body), 4_096):
        spill.write(body[start:start + 4_096])

    assert spill.written_bytes == len(body)
    landed = spill.close()

    assert landed.original_bytes == len(body)
    assert landed.sha256 == hashlib.sha256(body).hexdigest()
    assert landed.reference.startswith("execute-code-stdout-")
    assert landed.reference.endswith(".txt")
    assert Path(landed.path).read_bytes() == body


def test_the_digest_is_computed_as_the_bytes_go_past(tmp_path):
    """Not by re-reading the finished file — the whole point is never holding it.

    Re-reading would work and would be simpler, which is exactly why this is
    pinned: it would also reintroduce, at naming time, the memory cost the
    streaming write exists to avoid.
    """
    store = _store(tmp_path)
    spill = store.open_stream(tool="echo")
    spill.write(b"abc")
    spill.write(b"def")
    landed = spill.close()

    assert landed.sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert landed.reference == f"echo-{landed.sha256[:16]}.txt"


def test_a_streamed_spill_is_readable_through_the_same_door(tmp_path):
    store = _store(tmp_path)
    spill = store.open_stream(tool="echo")
    spill.write(b"hello stream")
    landed = spill.close()

    assert store.read(landed.reference) == "hello stream"


def test_discard_leaves_nothing_behind(tmp_path):
    store = _store(tmp_path)
    spill = store.open_stream(tool="echo")
    spill.write(b"output the model already has in full")
    spill.discard()

    assert list((tmp_path / "spills").iterdir()) == []
    assert spill.close() is None, "a discarded spill cannot then be landed"


def test_an_empty_stream_lands_nothing(tmp_path):
    """A run that printed nothing must not leave a file to age out of the budget."""
    store = _store(tmp_path)
    spill = store.open_stream(tool="echo")

    assert spill.close() is None
    assert list((tmp_path / "spills").iterdir()) == []


def test_a_write_that_fails_is_reported_rather_than_half_landed(tmp_path):
    store = _store(tmp_path)
    spill = store.open_stream(tool="echo")
    spill.write(b"the first half")
    spill._handle.close()          # the disk goes away mid-run
    spill.write(b"the second half")

    assert spill.close() is None, "half a stream must never be offered as the whole"
    assert not list((tmp_path / "spills").glob("*.txt"))


def test_an_unopenable_store_returns_no_writer_rather_than_raising(tmp_path):
    blocker = tmp_path / "spills"
    blocker.write_text("not a directory", encoding="utf-8")

    assert ToolResultStore(blocker).open_stream(tool="echo") is None


def test_retention_sweeps_streamed_spills_too(tmp_path):
    """Both shapes share one directory, so they have to share one budget."""
    now = {"t": 10_000.0}
    store = _store(tmp_path, retention_seconds=100, clock=lambda: now["t"])
    old = store.open_stream(tool="echo")
    old.write(b"x" * 1_000)
    stale = old.close()

    now["t"] += 1_000
    fresh = store.open_stream(tool="echo")
    fresh.write(b"y" * 1_000)
    kept = fresh.close()

    assert store.read(kept.reference) is not None
    assert store.read(stale.reference) is None
    assert not (tmp_path / "spills" / stale.reference).exists()
