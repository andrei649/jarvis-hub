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
    assert set(schema["properties"]) == {
        "pattern", "path", "glob", "case_sensitive", "whole_word", "max_matches", "regex",
    }
    for word in ("regex", "ripgrep", "glob"):
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
    def broken(argv, *args, **kwargs):
        raise OSError("rg vanished")

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
    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 1)
    out = await tools.search_files({"glob": "*"})
    assert _names(out) == ["blob.bin"] and out["stopped_by"] == "max_files"
    monkeypatch.setattr(file_tools, "MAX_SEARCH_FILES", 5000)
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
