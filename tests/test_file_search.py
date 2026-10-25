"""Hermes absorption 3a — `file_search`: a bounded content search inside the roots.

The model had `file_read` and `file_list`, so finding anything meant listing and reading file
by file — burning the context budget that is already the problem. `file_search` scans
contents with exactly the read tools' containment (roots, no symlink escape, no secret-looking
names) and every bound reported: matches, matches per file, files visited, seconds.

H303 added two modes on the same containment: ``regex: true`` (ripgrep when installed, a
Python ``re`` fallback with the same results otherwise) and a glob file-finding mode
(``glob`` without ``pattern``).
"""
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core import file_tools  # noqa: E402
from agents.core.file_tools import (  # noqa: E402
    FILE_TOOL_SPECS,
    FileScope,
    FileTools,
    SnapshotStore,
    register_file_tools,
)
from agents.core.tool_rpc import ToolRPCServer, ToolRPCValidationError  # noqa: E402


class _Audit:
    def __init__(self):
        self.calls = []

    def record(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.txt").write_text("Alpha budget\nthe Budget line\nbudgetary\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "plan.md").write_text("# Plan\nbudget: 10\n", encoding="utf-8")
    (root / ".env").write_text("BUDGET=secret\n", encoding="utf-8")
    (root / "api_key.txt").write_text("budget key\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(b"budget\x00\x01\x02")
    return root


@pytest.fixture
def tools(workspace, tmp_path):
    return FileTools(
        FileScope([workspace]), snapshots=SnapshotStore(tmp_path / "snaps"), max_bytes=4096,
    )


def _rows(result):
    return [(os.path.basename(m["path"]), m["line"], m["text"]) for m in result["matches"]]


async def test_literal_search_is_case_insensitive_by_default(tools, workspace):
    out = await tools.search_files({"pattern": "budget"})
    assert out["ok"] is True and out["path"] == str(workspace)
    assert _rows(out) == [
        ("notes.txt", 1, "Alpha budget"),
        ("notes.txt", 2, "the Budget line"),
        ("notes.txt", 3, "budgetary"),
        ("plan.md", 2, "budget: 10"),
    ]
    assert out["files_scanned"] == 2 and out["files_matched"] == 2
    # .env and api_key.txt are secret-looking names: never read, counted as hidden.
    assert out["hidden"] == 2
    assert out["skipped"] == {"binary": 1, "large": 0, "symlink": 0}
    assert out["truncated"] is False and out["stopped_by"] is None
    assert out["case_sensitive"] is False and out["whole_word"] is False and out["glob"] is None


async def test_case_sensitive_and_whole_word_narrow_the_matches(tools):
    out = await tools.search_files({"pattern": "budget", "case_sensitive": True})
    assert [(r[0], r[1]) for r in _rows(out)] == [
        ("notes.txt", 1), ("notes.txt", 3), ("plan.md", 2),
    ]
    out = await tools.search_files({"pattern": "budget", "whole_word": True})
    assert [(r[0], r[1]) for r in _rows(out)] == [
        ("notes.txt", 1), ("notes.txt", 2), ("plan.md", 2),
    ]
    out = await tools.search_files({"pattern": "Budget", "case_sensitive": True, "whole_word": True})
    assert [(r[0], r[1]) for r in _rows(out)] == [("notes.txt", 2)]


async def test_glob_filters_by_file_name_only(tools):
    out = await tools.search_files({"pattern": "budget", "glob": "*.md"})
    assert [(r[0], r[1]) for r in _rows(out)] == [("plan.md", 2)]
    assert out["files_scanned"] == 1 and out["glob"] == "*.md"


async def test_symlinks_are_never_followed_and_large_files_are_skipped(tools, workspace, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text("budget leak\n", encoding="utf-8")
    os.symlink(outside / "leak.txt", workspace / "link.txt")
    os.symlink(outside, workspace / "linkdir")
    (workspace / "big.txt").write_text("budget " + "x" * 5000, encoding="utf-8")
    out = await tools.search_files({"pattern": "budget"})
    names = {r[0] for r in _rows(out)}
    assert "leak.txt" not in names and "link.txt" not in names and "big.txt" not in names
    assert out["skipped"] == {"binary": 1, "large": 1, "symlink": 2}


async def test_secret_directories_are_pruned(tools, workspace):
    (workspace / ".ssh").mkdir()
    (workspace / ".ssh" / "config").write_text("budget host\n", encoding="utf-8")
    (workspace / ".config" / "gcloud").mkdir(parents=True)
    (workspace / ".config" / "gcloud" / "x.txt").write_text("budget\n", encoding="utf-8")
    (workspace / ".config" / "app").mkdir()
    (workspace / ".config" / "app" / "y.txt").write_text("budget app\n", encoding="utf-8")
    out = await tools.search_files({"pattern": "budget"})
    names = {r[0] for r in _rows(out)}
    assert "config" not in names and "x.txt" not in names
    assert "y.txt" in names  # .config itself is not secret; .config/gcloud is
    assert out["hidden"] == 4


async def test_bounds_report_which_cap_stopped_the_search(tools, monkeypatch):
    out = await tools.search_files({"pattern": "budget", "max_matches": 2})
    assert len(out["matches"]) == 2 and out["truncated"] is True
    assert out["stopped_by"] == "max_matches"

    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 1)
    out = await tools.search_files({"pattern": "budget"})
    assert out["files_scanned"] == 1 and out["stopped_by"] == "max_files"
    assert [r[0] for r in _rows(out)] == ["notes.txt"] * 3
    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 5000)

    monkeypatch.setattr(file_tools, "MAX_SEARCH_SECONDS", -1.0)
    out = await tools.search_files({"pattern": "budget"})
    assert out["ok"] is True and out["matches"] == [] and out["files_scanned"] == 0
    assert out["truncated"] is True and out["stopped_by"] == "deadline"


async def test_per_file_cap_keeps_other_files_in_the_result(tools, monkeypatch):
    monkeypatch.setattr(file_tools, "MAX_MATCHES_PER_FILE", 1)
    out = await tools.search_files({"pattern": "budget"})
    assert [(r[0], r[1]) for r in _rows(out)] == [("notes.txt", 1), ("plan.md", 2)]
    assert out["files_capped"] == 1 and out["truncated"] is False


async def test_snippet_is_bounded_around_the_match(tools, workspace):
    line = "a" * 600 + " needle " + "b" * 600
    (workspace / "long.txt").write_text(line + "\n", encoding="utf-8")
    out = await tools.search_files({"pattern": "needle", "glob": "long.txt"})
    text = out["matches"][0]["text"]
    assert "needle" in text and text.startswith("…") and text.endswith("…")
    assert len(text) <= file_tools.SNIPPET_CHARS + 2


async def test_a_line_is_matched_on_its_first_bytes_only(tools, workspace, monkeypatch):
    # A line is matched on its first MATCH_LINE_CHARS — a match beyond that is not found,
    # and the bound is documented rather than the line read without end.
    monkeypatch.setattr(file_tools, "MATCH_LINE_CHARS", 100)
    (workspace / "tail.txt").write_text("z" * 200 + "needle\n" + "needle early\n", encoding="utf-8")
    out = await tools.search_files({"pattern": "needle", "glob": "tail.txt"})
    assert [(r[1], r[2]) for r in _rows(out)] == [(2, "needle early")]
    assert out["files_scanned"] == 1


async def test_scope_refusals_and_a_single_file_target(tools, workspace):
    assert await tools.search_files({"pattern": "x", "path": "../outside"}) == {
        "ok": False, "reason": "outside_scope",
    }
    assert (await tools.search_files({"pattern": "x", "path": ".env"}))["reason"] == "secret_path"
    assert (await tools.search_files({"pattern": "x", "path": "missing.txt"}))["reason"] == "not_found"
    out = await tools.search_files({"pattern": "budget", "path": "notes.txt"})
    assert out["ok"] is True and out["path"] == str(workspace / "notes.txt")
    assert len(out["matches"]) == 3 and out["files_scanned"] == 1


async def test_bad_arguments_are_refused_by_name(tools):
    preflight = FILE_TOOL_SPECS["file_search"]["preflight"]
    for bad in ({}, {"pattern": ""}, {"pattern": "x" * 513}, {"pattern": "a\x00b"}, {"pattern": 3}):
        with pytest.raises(ToolRPCValidationError) as info:
            preflight(bad)
        assert info.value.reason == "bad_pattern", bad
    for glob in ("", "/abs/*", "a\\b", "x" * 129, 7):
        with pytest.raises(ToolRPCValidationError) as info:
            preflight({"pattern": "x", "glob": glob})
        assert info.value.reason == "bad_glob", glob
    for value in (0, True, "5"):
        with pytest.raises(ToolRPCValidationError) as info:
            preflight({"pattern": "x", "max_matches": value})
        assert info.value.reason == "bad_max_matches", value
    with pytest.raises(ToolRPCValidationError) as info:
        preflight({"pattern": "x", "case_sensitive": "yes"})
    assert info.value.reason == "bad_flag"
    clean = preflight({"pattern": "x", "max_matches": 10_000, "whole_word": True})
    assert clean == {"pattern": "x", "max_matches": file_tools.MAX_SEARCH_MATCHES, "whole_word": True}
    assert await tools.search_files({"pattern": ""}) == {"ok": False, "reason": "bad_pattern"}


def test_spec_is_closed_ungated_and_literal_by_default():
    spec = FILE_TOOL_SPECS["file_search"]
    assert spec["gated"] is False and spec["trusted_execution"] is False
    assert spec["capability_id"] == "tool:file_search"
    schema = spec["input_schema"]
    assert schema["additionalProperties"] is False and "required" not in schema
    assert schema["properties"]["regex"] == {"type": "boolean"}
    assert schema["properties"]["include_ignored"] == {"type": "boolean"}
    assert set(schema["properties"]) == {
        "pattern", "path", "glob", "case_sensitive", "whole_word", "max_matches", "regex",
        "include_ignored",
    }
    # The model-facing description documents the glob syntax, the pruned directories and
    # the regex refusals (H303 round 2), not just the argument names.
    for word in ("regex", "ripgrep", "glob", "Glob syntax", "{py,md}", "negates", "include_ignored",
                 "node_modules", ".gitignore", "bad_regex", "regex_too_complex", "deadline"):
        assert word in spec["description"], word


async def test_registered_ungated_and_runs_inline_through_tool_rpc(tools):
    server = ToolRPCServer()
    names = register_file_tools(server, tools, enabled=True)
    assert names == ["file_read", "file_list", "file_search", "file_write", "file_delete"]
    row = next(t for t in server.tools() if t["name"] == "file_search")
    assert row["gated"] is False and row["capability_id"] == "tool:file_search"
    out = await server.handle({"tool": "file_search", "args": {"pattern": "plan", "glob": "*.md"}})
    assert out["ok"] is True and len(out["result"]["matches"]) == 1
    out = await server.handle({"tool": "file_search", "args": {"pattern": "x", "path": "../etc"}})
    assert out == {"ok": False, "reason": "outside_scope", "tool": "file_search"}
    # Without regex=true the pattern stays literal; with it, it is a regex (H303).
    out = await server.handle({"tool": "file_search", "args": {"pattern": "bud.*"}})
    assert out["ok"] is True and out["result"]["matches"] == [] and out["result"]["mode"] == "literal"
    out = await server.handle({"tool": "file_search", "args": {"pattern": "bud.*", "regex": True}})
    assert out["ok"] is True and len(out["result"]["matches"]) == 4 and out["result"]["mode"] == "regex"
    out = await server.handle({"tool": "file_search", "args": {"glob": "*.md"}})
    assert out["ok"] is True and out["result"]["mode"] == "glob"
    assert [os.path.basename(f["path"]) for f in out["result"]["files"]] == ["plan.md"]


async def test_audit_records_the_search(workspace, tmp_path):
    audit = _Audit()
    tools = FileTools(
        FileScope([workspace]), snapshots=SnapshotStore(tmp_path / "snaps"), audit=audit,
    )
    out = await tools.search_files({"pattern": "budget", "glob": "*.md"})
    assert out["ok"] is True
    record = audit.calls[-1]
    assert record["action"] == "file.search" and record["metadata"]["matches"] == 1
    assert record["why"].endswith(": budget")


# ── H303: regex mode (ripgrep, with a Python fallback) ───────────────────────

HAVE_RG = shutil.which("rg") is not None


@pytest.fixture(params=["ripgrep", "python"])
def engine(request, monkeypatch):
    """Run a test once per engine: ripgrep when installed, and with ripgrep hidden."""
    if request.param == "ripgrep":
        if not HAVE_RG:
            pytest.skip("ripgrep is not installed here")
    else:
        monkeypatch.setattr(file_tools.shutil, "which", lambda name, *a, **k: None)
    return request.param


async def test_regex_mode_matches_a_regular_expression(tools, engine):
    out = await tools.search_files({"pattern": "bud.et", "regex": True})
    assert out["ok"] is True and out["regex"] is True and out["mode"] == "regex"
    assert out["engine"] == engine
    assert _rows(out) == [
        ("notes.txt", 1, "Alpha budget"),
        ("notes.txt", 2, "the Budget line"),
        ("notes.txt", 3, "budgetary"),
        ("plan.md", 2, "budget: 10"),
    ]
    out = await tools.search_files({"pattern": r"^the\s+\w+\s+line$", "regex": True})
    assert _rows(out) == [("notes.txt", 2, "the Budget line")]
    out = await tools.search_files({"pattern": r"budget:\s*\d+", "regex": True, "glob": "*.md"})
    assert _rows(out) == [("plan.md", 2, "budget: 10")] and out["files_scanned"] == 1


async def test_regex_and_literal_agree_on_a_plain_phrase(tools, engine):
    for flags in ({}, {"case_sensitive": True}, {"whole_word": True},
                  {"case_sensitive": True, "whole_word": True}, {"glob": "*.md"}):
        literal = await tools.search_files({"pattern": "budget", **flags})
        regex = await tools.search_files({"pattern": "budget", "regex": True, **flags})
        assert regex["engine"] == engine
        assert _rows(regex) == _rows(literal), flags
        assert regex["hidden"] == literal["hidden"] == 2
        assert regex["skipped"] == literal["skipped"]
        assert regex["files_scanned"] == literal["files_scanned"]
    literal = await tools.search_files({"pattern": "bud.et"})
    assert literal["matches"] == [] and literal["mode"] == "literal" and "engine" not in literal


async def test_the_two_engines_return_the_same_rows(tools, monkeypatch):
    if not HAVE_RG:
        pytest.skip("ripgrep is not installed here")
    cases = [
        {"pattern": r"\bbudget\b"}, {"pattern": r"[Bb]udget(ary)?", "case_sensitive": True},
        {"pattern": r"\d+"}, {"pattern": r"^#\s"}, {"pattern": "bud", "whole_word": True},
        {"pattern": r"bud\w+", "whole_word": True}, {"pattern": r"line$", "glob": "notes.*"},
    ]
    with_rg = [await tools.search_files({**case, "regex": True}) for case in cases]
    monkeypatch.setattr(file_tools.shutil, "which", lambda name, *a, **k: None)
    without = [await tools.search_files({**case, "regex": True}) for case in cases]
    for case, a, b in zip(cases, with_rg, without, strict=True):
        assert a["engine"] == "ripgrep" and b["engine"] == "python", case
        assert _rows(a) == _rows(b), case
        assert (a["files_scanned"], a["files_matched"]) == (b["files_scanned"], b["files_matched"]), case


async def test_regex_mode_keeps_the_containment_and_the_bounds(tools, workspace, tmp_path, engine,
                                                              monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text("budget leak\n", encoding="utf-8")
    os.symlink(outside / "leak.txt", workspace / "link.txt")
    os.symlink(outside, workspace / "linkdir")
    (workspace / "big.txt").write_text("budget " + "x" * 5000, encoding="utf-8")
    (workspace / ".ssh").mkdir()
    (workspace / ".ssh" / "config").write_text("budget host\n", encoding="utf-8")
    out = await tools.search_files({"pattern": "budget|leak", "regex": True})
    names = {r[0] for r in _rows(out)}
    assert names == {"notes.txt", "plan.md"}
    assert out["skipped"] == {"binary": 1, "large": 1, "symlink": 2} and out["hidden"] == 3
    assert await tools.search_files({"pattern": "x", "regex": True, "path": "../outside"}) == {
        "ok": False, "reason": "outside_scope"}

    out = await tools.search_files({"pattern": "budget", "regex": True, "max_matches": 2})
    assert len(out["matches"]) == 2 and out["stopped_by"] == "max_matches" and out["truncated"] is True
    monkeypatch.setattr(file_tools, "MAX_MATCHES_PER_FILE", 1)
    out = await tools.search_files({"pattern": "budget", "regex": True})
    assert [(r[0], r[1]) for r in _rows(out)] == [("notes.txt", 1), ("plan.md", 2)]
    assert out["files_capped"] == 1 and out["truncated"] is False
    monkeypatch.setattr(file_tools, "MAX_MATCHES_PER_FILE", 20)
    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 1)
    out = await tools.search_files({"pattern": "budget", "regex": True})
    assert out["files_scanned"] == 1 and out["stopped_by"] == "max_files"
    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 5000)
    monkeypatch.setattr(file_tools, "MAX_SEARCH_SECONDS", -1.0)
    out = await tools.search_files({"pattern": "budget", "regex": True})
    assert out["ok"] is True and out["matches"] == [] and out["stopped_by"] == "deadline"


async def test_regex_snippets_are_bounded_around_the_match(tools, workspace, engine):
    line = "a" * 600 + " needle42 " + "b" * 600
    (workspace / "long.txt").write_text(line + "\n", encoding="utf-8")
    out = await tools.search_files({"pattern": r"needle\d+", "regex": True, "glob": "long.txt"})
    text = out["matches"][0]["text"]
    assert "needle42" in text and text.startswith("…") and text.endswith("…")
    assert len(text) <= file_tools.SNIPPET_CHARS + 2


async def test_an_invalid_regex_is_refused_by_name_on_both_engines(tools, engine):
    out = await tools.search_files({"pattern": "(unclosed", "regex": True})
    assert out["ok"] is False and out["reason"] == "bad_regex"
    assert "unterminated subpattern" in out["detail"]      # re's own words, bounded
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_search"]["preflight"]({"pattern": "[z-a]", "regex": True})
    assert info.value.reason == "bad_regex"
    # A nested unbounded repeat is refused up front on both engines, so the pattern set is
    # the same whichever engine answers (Python's re would backtrack on it without bound).
    for pattern in (r"(a+)+$", r"(\w*)*x", r"((ab)*)+"):
        out = await tools.search_files({"pattern": pattern, "regex": True})
        assert out == {"ok": False, "reason": "regex_too_complex"}, pattern
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_search"]["preflight"]({"pattern": "(a+)+", "regex": True})
    assert info.value.reason == "regex_too_complex"
    # The same text is not a regex without the flag: it is a literal with no match.
    out = await tools.search_files({"pattern": "(unclosed"})
    assert out["ok"] is True and out["matches"] == []
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_search"]["preflight"]({"pattern": "x", "regex": "yes"})
    assert info.value.reason == "bad_flag"


async def test_a_python_only_construct_falls_back_to_the_python_engine(tools):
    if not HAVE_RG:
        pytest.skip("ripgrep is not installed here")
    out = await tools.search_files({"pattern": r"(?<=Alpha )budget", "regex": True})
    assert out["engine"] == "python" and _rows(out) == [("notes.txt", 1, "Alpha budget")]


async def test_ripgrep_is_run_without_a_shell_and_within_the_deadline(tools, monkeypatch):
    if not HAVE_RG:
        pytest.skip("ripgrep is not installed here")
    seen = {}
    real = file_tools.subprocess.run

    def spy(argv, *args, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(file_tools.subprocess, "run", spy)
    out = await tools.search_files({"pattern": "-budget", "regex": True})
    assert out["ok"] is True and out["engine"] == "ripgrep" and out["matches"] == []
    argv = seen["argv"]
    assert isinstance(argv, list) and argv[0].endswith("rg")
    assert "--json" in argv and "--no-config" in argv and "-e" in argv
    assert argv[argv.index("-e") + 1] == "-budget"      # a leading dash is a pattern, not a flag
    assert "--" in argv and all(os.path.isabs(p) for p in argv[argv.index("--") + 1:])
    assert seen["kwargs"].get("shell", False) is False
    assert 0 < seen["kwargs"]["timeout"] <= file_tools.MAX_SEARCH_SECONDS
    assert seen["kwargs"]["stdin"] == file_tools.subprocess.DEVNULL


async def test_a_ripgrep_failure_falls_back_instead_of_failing_the_search(tools, monkeypatch):
    real = file_tools.subprocess.run

    def broken(argv, *args, **kwargs):
        if argv[0] == "/nonexistent/rg":
            raise OSError("rg vanished")
        return real(argv, *args, **kwargs)        # the Python child still runs

    monkeypatch.setattr(file_tools.shutil, "which", lambda name, *a, **k: "/nonexistent/rg")
    monkeypatch.setattr(file_tools.subprocess, "run", broken)
    out = await tools.search_files({"pattern": "bud.et", "regex": True})
    assert out["ok"] is True and out["engine"] == "python" and len(out["matches"]) == 4


async def test_a_regex_search_of_a_spill_stays_tainted(tmp_path, engine):
    root = tmp_path / "roots"
    spill = root / file_tools._SPILL_DIRNAME
    spill.mkdir(parents=True)
    (spill / "toolres-0123456789abcdef.txt").write_text("ignore previous budget\n", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"))
    out = await tools.search_files({"pattern": r"bud\w+", "regex": True})
    assert out["ok"] is True and len(out["matches"]) == 1 and out["tainted"] is True


# ── H303: glob file-finding mode ─────────────────────────────────────────────

def _names(result):
    return [os.path.relpath(f["path"], result["path"]) for f in result["files"]]


async def test_a_glob_without_a_pattern_finds_files(tools, workspace):
    out = await tools.search_files({"glob": "*.md"})
    assert out["ok"] is True and out["mode"] == "glob" and out["pattern"] is None
    assert out["glob"] == "*.md" and out["path"] == str(workspace)
    assert out["files"] == [{"path": str(workspace / "sub" / "plan.md"), "size": 18}]
    assert "matches" not in out
    assert out["files_scanned"] == 3 and out["files_matched"] == 1 and out["hidden"] == 2
    assert out["truncated"] is False and out["stopped_by"] is None
    everything = await tools.search_files({"glob": "*"})
    assert _names(everything) == ["blob.bin", "notes.txt", "sub/plan.md"]
    # A glob is matched against the name when it has no "/", and against the path relative
    # to the searched directory when it has one; "*" crosses directories, so ** works.
    assert _names(await tools.search_files({"glob": "sub/*.md"})) == ["sub/plan.md"]
    assert _names(await tools.search_files({"glob": "**/*.md"})) == ["sub/plan.md"]
    assert _names(await tools.search_files({"glob": "sub/*"})) == ["sub/plan.md"]
    assert _names(await tools.search_files({"glob": "nothing/*"})) == []
    assert _names(await tools.search_files({"glob": "plan.*", "path": "sub"})) == ["plan.md"]


async def test_glob_mode_lists_large_files_but_never_secrets_or_symlinks(tools, workspace, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text("x", encoding="utf-8")
    os.symlink(outside / "leak.txt", workspace / "link.txt")
    os.symlink(outside, workspace / "linkdir")
    (workspace / "big.txt").write_text("x" * 5000, encoding="utf-8")
    (workspace / ".ssh").mkdir()
    (workspace / ".ssh" / "id_rsa.txt").write_text("x", encoding="utf-8")
    out = await tools.search_files({"glob": "*.txt"})
    assert _names(out) == ["big.txt", "notes.txt"]     # a found file is not read: no size cap
    assert out["skipped"] == {"binary": 0, "large": 0, "symlink": 2} and out["hidden"] == 3
    assert await tools.search_files({"glob": "*", "path": "../outside"}) == {
        "ok": False, "reason": "outside_scope"}
    assert await tools.search_files({"glob": "*", "path": "linkdir"}) == {
        "ok": False, "reason": "symlink_escape"}
    assert (await tools.search_files({"glob": "*", "path": ".ssh"}))["reason"] == "secret_path"
    assert (await tools.search_files({"glob": "*", "path": "nope"}))["reason"] == "not_found"
    single = await tools.search_files({"glob": "*.txt", "path": "notes.txt"})
    assert single["files"] == [{"path": str(workspace / "notes.txt"), "size": 39}]
    assert (await tools.search_files({"glob": "*.md", "path": "notes.txt"}))["files"] == []


async def test_glob_mode_is_bounded_and_names_the_cap(tools, monkeypatch):
    out = await tools.search_files({"glob": "*", "max_matches": 2})
    assert _names(out) == ["blob.bin", "notes.txt"]
    assert out["truncated"] is True and out["stopped_by"] == "max_matches"
    # A glob search is bounded by the files it VISITS (MAX_WALK_FILES), not by the files
    # whose contents are searched (MAX_SEARCH_FILES, which it never reads).
    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 1)
    assert len((await tools.search_files({"glob": "*"}))["files"]) == 3
    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 5000)
    monkeypatch.setattr(file_tools, "MAX_WALK_FILES", 1)
    out = await tools.search_files({"glob": "*"})
    assert _names(out) == ["blob.bin"] and out["stopped_by"] == "max_files"
    monkeypatch.setattr(file_tools, "MAX_WALK_FILES", 100_000)
    monkeypatch.setattr(file_tools, "MAX_SEARCH_SECONDS", -1.0)
    out = await tools.search_files({"glob": "*"})
    assert out["files"] == [] and out["stopped_by"] == "deadline"


async def test_a_path_glob_also_narrows_a_content_search(tools):
    out = await tools.search_files({"pattern": "budget", "glob": "sub/*.md"})
    assert [(r[0], r[1]) for r in _rows(out)] == [("plan.md", 2)] and out["files_scanned"] == 1
    out = await tools.search_files({"pattern": "budget", "glob": "**/*.txt"})
    assert {r[0] for r in _rows(out)} == {"notes.txt"}
    out = await tools.search_files({"pattern": "budget", "glob": "sub/*.txt"})
    assert out["matches"] == [] and out["files_scanned"] == 0


async def test_glob_mode_refusals(tools):
    preflight = FILE_TOOL_SPECS["file_search"]["preflight"]
    with pytest.raises(ToolRPCValidationError) as info:
        preflight({})
    assert info.value.reason == "bad_pattern"
    assert preflight({"glob": "*.py"}) == {"glob": "*.py"}
    for glob in ("/etc/*", "a\\b", ""):
        with pytest.raises(ToolRPCValidationError) as info:
            preflight({"glob": glob})
        assert info.value.reason == "bad_glob", glob
    with pytest.raises(ToolRPCValidationError) as info:
        preflight({"glob": "*.py", "regex": True})
    assert info.value.reason == "bad_pattern"      # regex applies to a pattern, there is none
    assert await tools.search_files({}) == {"ok": False, "reason": "bad_pattern"}


async def test_the_audit_names_the_mode(workspace, tmp_path):
    audit = _Audit()
    tools = FileTools(FileScope([workspace]), snapshots=SnapshotStore(tmp_path / "snaps"), audit=audit)
    await tools.search_files({"glob": "*.md"})
    record = audit.calls[-1]
    assert record["action"] == "file.search" and record["metadata"]["matches"] == 1
    assert record["why"].endswith(": glob *.md")
    await tools.search_files({"pattern": "bud.et", "regex": True})
    assert audit.calls[-1]["why"].endswith(": regex bud.et") and audit.calls[-1]["metadata"]["matches"] == 4


# ── H303 round 2: the Python regex engine cannot hang the host ───────────────

def _no_ripgrep(monkeypatch):
    monkeypatch.setattr(file_tools.shutil, "which", lambda name, *a, **k: None)


def _loose(root, **kw):
    return FileTools(FileScope([root]), max_bytes=kw.pop("max_bytes", 100_000), **kw)


# Patterns whose Python backtracking is exponential on a line that does not match. The
# star-height guard accepts every one of them (none nests an unbounded repeat in
# another), so what protects the host is the killable worker, not the guard.
REDOS = [
    (r"(a|aa)+$", "a" * 44 + "b", True),
    (r"(a|a)+$", "a" * 44 + "b", True),
    (r"(.|.)*x", "a" * 44, True),
    # CPython happens to finish these two on 40+ characters; they are in the reviewer's
    # list of patterns the guard accepts, so they must stay bounded either way.
    (r"(\w|\d)+$", "1" * 44 + "!", False),
    (r"(a?){30}a{30}", "a" * 29, False),
]


@pytest.mark.parametrize("pattern,line,hangs", REDOS)
async def test_a_backtracking_pattern_cannot_hang_the_python_engine(tmp_path, monkeypatch,
                                                                    pattern, line, hangs):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "x.txt").write_text(line + "\n", encoding="utf-8")
    assert not file_tools._regex_too_complex(pattern)        # the guard does not catch it
    _no_ripgrep(monkeypatch)
    monkeypatch.setattr(file_tools, "MAX_SEARCH_SECONDS", 1.5)
    started = time.monotonic()
    out = await _loose(root).search_files({"pattern": pattern, "regex": True})
    assert time.monotonic() - started < 8, "the search outlived its deadline"
    assert out["ok"] is True and out["engine"] == "python" and out["matches"] == []
    if hangs:
        assert out["truncated"] is True and out["stopped_by"] == "deadline"
    else:
        assert out["stopped_by"] in (None, "deadline")


async def test_rows_found_before_the_deadline_are_kept(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a_first.txt").write_text("aaa\n", encoding="utf-8")
    (root / "z_slow.txt").write_text("a" * 44 + "b\n", encoding="utf-8")
    _no_ripgrep(monkeypatch)
    monkeypatch.setattr(file_tools, "MAX_SEARCH_SECONDS", 1.5)
    out = await _loose(root).search_files({"pattern": r"(a|aa)+$", "regex": True})
    assert [(os.path.basename(m["path"]), m["line"]) for m in out["matches"]] == [("a_first.txt", 1)]
    assert out["stopped_by"] == "deadline" and out["truncated"] is True
    # Only the file whose search finished is counted; the one the kill cut is not.
    assert out["files_scanned"] == 1 and out["files_matched"] == 1


# Backtracking patterns the static guard cannot see, each with a line it cannot finish
# on. `(?=a)` is a look-ahead that ripgrep rejects, so with ripgrep installed that one
# is answered by the (killable) Python child; the others are linear in ripgrep.
HEAVY = [
    (r"(a|a)*b", "a" * 5000),
    (r"(?=a)(a|a)*b", "a" * 5000),
    (r"(a|aa)+$", "a" * 5000 + "b"),
    (r"(.*)(.*)x", "a" * 5000),
]


@pytest.mark.parametrize("pattern,line", HEAVY)
@pytest.mark.parametrize("use_rg", [True, False], ids=["ripgrep", "no-ripgrep"])
async def test_heavy_patterns_are_refused_or_return_within_the_deadline(
        tmp_path, monkeypatch, pattern, line, use_rg):
    if use_rg and not HAVE_RG:
        pytest.skip("ripgrep is not installed here")
    root = tmp_path / "ws"
    root.mkdir()
    (root / "x.txt").write_text(line + "\n", encoding="utf-8")
    if not use_rg:
        _no_ripgrep(monkeypatch)
    monkeypatch.setattr(file_tools, "MAX_SEARCH_SECONDS", 1.5)
    started = time.monotonic()
    out = await _loose(root).search_files({"pattern": pattern, "regex": True})
    assert time.monotonic() - started < 8, "the search outlived its deadline"
    if out["ok"]:
        assert out["stopped_by"] in (None, "deadline"), out
        if out["stopped_by"] is None:
            assert out["engine"] == "ripgrep" and out["matches"] == []   # finished: only rg can
    else:
        assert out["reason"] in ("bad_regex", "regex_too_complex"), out


def test_the_subprocess_import_carries_its_bandit_waiver():
    # security.yml runs bandit against .bandit-baseline.json: a new finding fails CI.
    source = Path(file_tools.__file__).read_text(encoding="utf-8")
    assert "import subprocess  # nosec B404" in source
    assert source.count("subprocess.run(  # nosec B603") == 2


@pytest.mark.skipif(not HAVE_RG, reason="ripgrep is not installed here")
@pytest.mark.parametrize("pattern,line", [(pat, text) for pat, text, _ in REDOS])
async def test_ripgrep_answers_the_same_patterns_in_linear_time(tmp_path, pattern, line):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "x.txt").write_text(line + "\n", encoding="utf-8")
    started = time.monotonic()
    out = await _loose(root).search_files({"pattern": pattern, "regex": True})
    assert time.monotonic() - started < 5
    assert out["engine"] == "ripgrep" and out["stopped_by"] is None and out["matches"] == []


async def test_the_python_worker_is_a_child_process_with_no_shell(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "x.txt").write_text("needle\n", encoding="utf-8")
    _no_ripgrep(monkeypatch)
    seen = {}
    real = file_tools.subprocess.run

    def spy(argv, *args, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(file_tools.subprocess, "run", spy)
    out = await _loose(root).search_files({"pattern": "need.e", "regex": True})
    assert len(out["matches"]) == 1 and out["engine"] == "python"
    argv = seen["argv"]
    assert argv[0] == sys.executable and argv[1:3] == ["-I", "-S"]
    assert seen["kwargs"].get("shell", False) is False
    assert 0 < seen["kwargs"]["timeout"] <= file_tools.MAX_SEARCH_SECONDS
    assert set(seen["kwargs"]["env"]) <= {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"}


async def test_a_build_without_a_python_child_says_so_instead_of_pretending(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "x.txt").write_text("needle\n", encoding="utf-8")
    _no_ripgrep(monkeypatch)
    monkeypatch.setattr(file_tools.sys, "executable", "")      # no interpreter to start a child with
    out = await _loose(root).search_files({"pattern": "need.e", "regex": True})
    assert out["ok"] is False and out["reason"] == "regex_unavailable" and "ripgrep" in out["detail"]
    # A literal search needs no child and still works.
    assert (await _loose(root).search_files({"pattern": "needle"}))["ok"] is True


def test_the_worker_snippet_is_the_parents_snippet(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    cases = {
        "mid.txt": "x" * 500 + " needle " + "y" * 500,
        "short.txt": "a short needle line",
        "end.txt": "n" * 300 + "needle",
        "start.txt": "needle" + "z" * 300,
    }
    for name, line in cases.items():
        (root / name).write_text(line + "\n", encoding="utf-8")
    files = [root / name for name in cases]
    found, timed_out = file_tools._py_regex_scan(
        files, "needle", ignore_case=False, deadline=time.monotonic() + 20, max_bytes=100_000)
    assert timed_out is False
    for name, line in cases.items():
        rows, capped = found[root / name]
        assert capped is False and len(rows) == 1
        assert rows[0]["text"] == file_tools._snippet(line, line.index("needle"), 6), name


# ── H303 round 2: both engines give the same answer ──────────────────────────

@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "long.txt").write_text("a" * 9000 + " needle tail\nshort needle\n", encoding="utf-8")
    (root / "latin1.txt").write_bytes(b"caf\xe9 needle\nneedle \xff\xfe end\nplain needle\n")
    (root / "multi.txt").write_text(
        "日本語 needle 日本語\nÜnï needle café\nneedle\u2028x\n", encoding="utf-8")
    (root / "crlf.txt").write_bytes(b"alpha needle\r\nneedle\r\nlast\r\n")
    (root / "ff.txt").write_text("needle\x0cneedle\nneedle", encoding="utf-8")
    (root / "posix.txt").write_text("alpha beta\n123\n", encoding="utf-8")
    (root / "blank.txt").write_text("one\n\ntwo\n", encoding="utf-8")
    # Anchored matches past the 8 KiB mark of a very long line must be found by both engines.
    (root / "long2.txt").write_text("b" * 20000 + "needle\n" + "c" * 20000 + "\n", encoding="utf-8")
    return root


def _summary(result):
    keys = ("ok", "reason", "files_scanned", "files_matched", "files_capped", "hidden", "ignored",
            "skipped", "non_utf8", "stopped_by", "truncated")
    return {key: result.get(key) for key in keys}


async def _both(root, args, monkeypatch):
    """The same search under ripgrep and under the Python child."""
    with_rg = await _loose(root).search_files(args)
    with monkeypatch.context() as scope:
        scope.setattr(file_tools.shutil, "which", lambda name, *a, **k: None)
        without = await _loose(root).search_files(args)
    return with_rg, without


PARITY_CASES = [
    {"pattern": "needle"},
    {"pattern": "needle", "case_sensitive": True},
    {"pattern": "NEEDLE"},
    {"pattern": "needle", "whole_word": True},
    {"pattern": "needle$"},
    {"pattern": "^needle$"},
    {"pattern": r"needle tail$"},          # past the first 8 KiB of a 9 KiB line
    {"pattern": r"b{3}needle$"},           # $-anchored, 20 000 characters in
    {"pattern": r"c$"},                    # the end of a 20 000-character line
    {"pattern": r"^b+needle$"},
    {"pattern": r"a{3} needle"},
    {"pattern": "caf."},                   # the invalid byte of a latin-1 file
    {"pattern": r"needle \S+ end"},
    {"pattern": r"\w+ needle"},
    {"pattern": "日本."},
    {"pattern": r"é|ï"},
    {"pattern": r"needle\s"},
    {"pattern": r"\x0c"},
    {"pattern": r"^$"},
    {"pattern": r"o*"},
    {"pattern": r"(?<=caf.) needle"},      # look-behind: ripgrep refuses, Python answers
    {"pattern": r"needle", "max_matches": 3},
    {"pattern": r"needle", "max_matches": 1},
    {"pattern": r"needle", "glob": "*.txt"},
    {"pattern": r"needle", "glob": "!l*"},
]


@pytest.mark.skipif(not HAVE_RG, reason="ripgrep is not installed here")
@pytest.mark.parametrize("case", PARITY_CASES, ids=[c["pattern"] + str(sorted(c)) for c in PARITY_CASES])
async def test_the_two_engines_agree_on_a_hard_corpus(corpus, monkeypatch, case):
    args = {**case, "regex": True}
    with_rg, without = await _both(corpus, args, monkeypatch)
    assert without["engine"] == "python"
    assert _rows(with_rg) == _rows(without)
    assert _summary(with_rg) == _summary(without)
    assert with_rg["ok"] is True and with_rg["matches"], case


@pytest.mark.skipif(not HAVE_RG, reason="ripgrep is not installed here")
async def test_the_corpus_specifics_both_engines_share(corpus, monkeypatch):
    # (a) a match past the first 8 KiB of a line is found by both, snippet still bounded;
    # (b) a latin-1 file is searched with replacement characters, and counted;
    # a CRLF file's `$` matches before the \r\n; `\u2028` does not split a line.
    for engine_args in ({"pattern": r"needle tail$", "regex": True},):
        for out in await _both(corpus, engine_args, monkeypatch):
            assert _rows(out) == [("long.txt", 1, out["matches"][0]["text"])]
            assert len(out["matches"][0]["text"]) <= file_tools.SNIPPET_CHARS + 2
    for out in await _both(corpus, {"pattern": "caf.", "regex": True}, monkeypatch):
        assert ("latin1.txt", 1, "caf� needle") in _rows(out) and out["non_utf8"] == 1
    for out in await _both(corpus, {"pattern": "^needle$", "regex": True, "glob": "crlf.txt"}, monkeypatch):
        assert _rows(out) == [("crlf.txt", 2, "needle")]
    for out in await _both(corpus, {"pattern": "x$", "regex": True, "glob": "multi.txt"}, monkeypatch):
        assert _rows(out) == [("multi.txt", 3, "needle\u2028x")]
    # (d) files_scanned stops at the file that reached max_matches, in both engines
    # (blank.txt has no match, crlf.txt is the first with one).
    first, second = await _both(corpus, {"pattern": "needle", "regex": True, "max_matches": 1}, monkeypatch)
    assert first["files_scanned"] == second["files_scanned"] == 2
    assert first["stopped_by"] == second["stopped_by"] == "max_matches"


@pytest.mark.parametrize("pattern", [
    r"[[:alpha:]]+", r"[[:digit:]]", r"[a&&b]", r"[a--b]", r"[a~~b]", r"[a||b]",
    r"\<needle\>", r"needle\>", r"[x[y]]", r"\p{L}+",
])
async def test_a_non_portable_regex_is_refused_by_name_on_both_engines(corpus, monkeypatch, pattern):
    args = {"pattern": pattern, "regex": True}
    # \p{L} is not a portability case: Python's own parser rejects it, which is the point —
    # whichever engine would have run, the pattern is refused before either does.
    assert file_tools._portability_error(pattern) is not None or pattern == r"\p{L}+"
    outs = [await _loose(corpus).search_files(args)]
    with monkeypatch.context() as scope:
        scope.setattr(file_tools.shutil, "which", lambda name, *a, **k: None)
        outs.append(await _loose(corpus).search_files(args))
    for out in outs:
        assert out["ok"] is False and out["reason"] == "bad_regex" and out["detail"], pattern
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_search"]["preflight"](args)
    assert info.value.reason == "bad_regex"


@pytest.mark.parametrize("pattern", [r"[\[]", r"[]a]", r"[^]a]", r"[a-z]+", r"\\<", r"[a\-z]", r"[\w-]+",
                                     r"needle\b", r"[ab]{2}", r"x[-a]", r"\[\[:alpha:\]\]"])
def test_ordinary_classes_and_escapes_stay_portable(pattern):
    assert file_tools._portability_error(pattern) is None


# ── H303 round 2: directories nobody searches ────────────────────────────────

def _tree(tmp_path, *, noise_files=0):
    root = tmp_path / "ws"
    (root / "node_modules" / "pkg").mkdir(parents=True)
    for i in range(noise_files):
        (root / "node_modules" / "pkg" / f"f{i:05d}.js").write_text("x\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "target_file.py").write_text("needle\n", encoding="utf-8")
    return root


async def test_a_glob_finds_a_file_behind_a_5200_file_dependency_tree(tmp_path):
    root = _tree(tmp_path, noise_files=5200)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("needle\n", encoding="utf-8")
    tools = _loose(root)
    out = await tools.search_files({"glob": "target_file.py"})
    assert [os.path.relpath(f["path"], root) for f in out["files"]] == ["src/target_file.py"]
    assert out["truncated"] is False and out["stopped_by"] is None
    assert out["ignored"] == 1 and out["hidden"] == 1 and out["include_ignored"] is False
    # Opting in walks node_modules too, and still finds the target: a glob search is bounded
    # by files visited (MAX_WALK_FILES), not by the 5 000 whose contents are searched.
    out = await tools.search_files({"glob": "*.js", "include_ignored": True, "max_matches": 500})
    assert len(out["files"]) == 500 and out["ignored"] == 0
    out = await tools.search_files({"glob": "target_file.py", "include_ignored": True})
    assert [os.path.basename(f["path"]) for f in out["files"]] == ["target_file.py"]
    assert out["files_scanned"] == 5201 and out["truncated"] is False


async def test_a_content_search_skips_noise_directories_unless_asked(tmp_path, monkeypatch, engine):
    root = _tree(tmp_path, noise_files=120)
    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 50)
    tools = _loose(root)
    for args in ({"pattern": "needle"}, {"pattern": "needle", "regex": True}):
        out = await tools.search_files(args)
        assert [os.path.relpath(m["path"], root) for m in out["matches"]] == ["src/target_file.py"]
        assert out["ignored"] == 1 and out["stopped_by"] is None
        # With the tree included, the 50-file budget runs out in node_modules first.
        out = await tools.search_files({**args, "include_ignored": True})
        assert out["matches"] == [] and out["stopped_by"] == "max_files" and out["ignored"] == 0


async def test_every_well_known_heavy_directory_is_pruned_and_a_path_inside_one_is_searched(tmp_path):
    root = tmp_path / "ws"
    names = ["node_modules", "venv", ".venv", "__pycache__", "dist", "build", "target", ".tox",
             ".mypy_cache"]
    for name in names:
        (root / name).mkdir(parents=True)
        (root / name / "f.txt").write_text("needle\n", encoding="utf-8")
    (root / "keep").mkdir()
    (root / "keep" / "f.txt").write_text("needle\n", encoding="utf-8")
    tools = _loose(root)
    out = await tools.search_files({"pattern": "needle"})
    assert [os.path.relpath(m["path"], root) for m in out["matches"]] == ["keep/f.txt"]
    assert out["ignored"] == len(names)
    assert len((await tools.search_files({"pattern": "needle", "include_ignored": True}))["matches"]) == 10
    # Pruning applies below the searched directory only: naming one searches it.
    inside = await tools.search_files({"pattern": "needle", "path": "node_modules"})
    assert [os.path.relpath(m["path"], root) for m in inside["matches"]] == ["node_modules/f.txt"]
    assert inside["ignored"] == 0
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_search"]["preflight"]({"pattern": "x", "include_ignored": "yes"})
    assert info.value.reason == "bad_flag"


async def test_plain_directory_names_in_the_root_gitignore_are_honoured(tmp_path):
    root = tmp_path / "ws"
    for rel in ("generated", "out", "a/out", "docs/_build", "docs", "src"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    for rel in ("generated/x.txt", "out/y.txt", "a/out/z.txt", "docs/_build/w.txt", "docs/keep.txt",
                "root.log", "src/s.txt"):
        (root / rel).write_text("needle\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        "# build output\ngenerated/\n/out\n*.log\ndocs/_build\n\n", encoding="utf-8")
    tools = _loose(root)
    out = await tools.search_files({"pattern": "needle"})
    # `generated` anywhere, `/out` and `docs/_build` only where they are written; the
    # wildcard line is not read, so root.log is searched.
    assert sorted(os.path.relpath(m["path"], root) for m in out["matches"]) == [
        "a/out/z.txt", "docs/keep.txt", "root.log", "src/s.txt"]
    assert out["ignored"] == 3
    assert len((await tools.search_files({"pattern": "needle", "include_ignored": True}))["matches"]) == 7
    # One re-include line makes the file untrustworthy, so none of it is applied.
    (root / ".gitignore").write_text("generated/\n!generated/keep.txt\n", encoding="utf-8")
    out = await tools.search_files({"pattern": "needle"})
    assert out["ignored"] == 0 and len(out["matches"]) == 7


async def test_files_that_do_not_match_a_glob_do_not_use_up_the_file_budget(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    for i in range(10):
        (root / f"aaa{i}").mkdir(parents=True)
        (root / f"aaa{i}" / "noise.txt").write_text("x\n", encoding="utf-8")
    (root / "zzz").mkdir()
    (root / "zzz" / "target.py").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 3)
    tools = _loose(root)
    out = await tools.search_files({"glob": "target.py"})
    assert [os.path.basename(f["path"]) for f in out["files"]] == ["target.py"]
    assert out["stopped_by"] is None
    # The same holds for a content search narrowed by a glob: only files searched count.
    out = await tools.search_files({"pattern": "needle", "glob": "*.py"})
    assert [os.path.basename(m["path"]) for m in out["matches"]] == ["target.py"]
    assert out["files_scanned"] == 1 and out["stopped_by"] is None


# ── H303 round 2: the glob syntax the description promises ───────────────────

@pytest.fixture
def globs(tmp_path):
    root = tmp_path / "ws"
    (root / "src" / "deep").mkdir(parents=True)
    for rel in ("a.py", "b.md", "c.txt", "app.min.js", "app.js", "src/m.py", "src/n.md",
                "src/deep/o.py", "x{y}.txt"):
        (root / rel).write_text("needle\n", encoding="utf-8")
    return root


def _found(result, root):
    return sorted(os.path.relpath(f["path"], root) for f in result["files"])


async def test_brace_alternation_and_negation_are_supported(globs):
    tools = _loose(globs)
    assert _found(await tools.search_files({"glob": "*.{py,md}"}), globs) == [
        "a.py", "b.md", "src/deep/o.py", "src/m.py", "src/n.md"]
    assert _found(await tools.search_files({"glob": "src/*.{py,md}"}), globs) == [
        "src/deep/o.py", "src/m.py", "src/n.md"]
    assert _found(await tools.search_files({"glob": "{a,b}.*"}), globs) == ["a.py", "b.md"]
    # Each alternative is its own glob: `a.*` is a name glob, `src/m.*` a path glob.
    assert _found(await tools.search_files({"glob": "{a,src/{m,n}}.*"}), globs) == [
        "a.py", "src/m.py", "src/n.md"]
    assert _found(await tools.search_files({"glob": "src/{m,n}.*"}), globs) == ["src/m.py", "src/n.md"]
    # `**/` also matches at depth zero; the empty alternative `**/*.` matches no file.
    assert _found(await tools.search_files({"glob": "**/*.{py,}"}), globs) == [
        "a.py", "src/deep/o.py", "src/m.py"]
    # A negated glob lists what does NOT match.
    not_py = _found(await tools.search_files({"glob": "!*.py"}), globs)
    assert "a.py" not in not_py and "src/m.py" not in not_py and "b.md" in not_py and "c.txt" in not_py
    assert _found(await tools.search_files({"glob": "!*.{py,md,txt,js}"}), globs) == []
    only_src = _found(await tools.search_files({"glob": "!src/*"}), globs)
    assert not any(name.startswith("src/") for name in only_src) and "a.py" in only_src
    # A brace with no comma, or an unclosed one, is an ordinary character.
    assert _found(await tools.search_files({"glob": "x{y}.txt"}), globs) == ["x{y}.txt"]
    assert _found(await tools.search_files({"glob": "x{y.txt"}), globs) == []


async def test_braces_and_negation_narrow_a_content_search_too(globs):
    tools = _loose(globs)
    out = await tools.search_files({"pattern": "needle", "glob": "*.{md,txt}"})
    assert sorted(os.path.relpath(m["path"], globs) for m in out["matches"]) == [
        "b.md", "c.txt", "src/n.md", "x{y}.txt"]
    out = await tools.search_files({"pattern": "needle", "glob": "!*.{py,md,txt}", "regex": True})
    assert sorted(os.path.relpath(m["path"], globs) for m in out["matches"]) == ["app.js", "app.min.js"]
    out = await tools.search_files({"pattern": "needle", "glob": "!*.min.js"})
    assert "app.min.js" not in {os.path.relpath(m["path"], globs) for m in out["matches"]}


@pytest.mark.parametrize("glob", [
    "!", "!/etc/*", "/etc/*", "{/etc,src}/*", "*.{" + ",".join("abcdefg") + "}{" + ",".join("hijklmn") + "}x",
    "{" + ",".join(str(i) for i in range(33)) + "}",
])
async def test_a_glob_that_cannot_be_honoured_is_refused_by_name(globs, glob):
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_search"]["preflight"]({"glob": glob})
    assert info.value.reason == "bad_glob"
    assert await _loose(globs).search_files({"glob": glob}) == {"ok": False, "reason": "bad_glob"}


def test_brace_expansion_is_bounded():
    assert file_tools._expand_braces("{a,b}{c,d}") == ["ac", "ad", "bc", "bd"]
    assert file_tools._expand_braces("{a,{b,c}}") == ["a", "b", "c"]
    assert len(file_tools._expand_braces("{" + ",".join(str(i) for i in range(32)) + "}")) == 32
    assert file_tools._expand_braces("{" + ",".join(str(i) for i in range(33)) + "}") is None
    assert file_tools._compile_glob("!*.py") == (True, ("*.py",))
