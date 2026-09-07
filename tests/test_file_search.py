"""Hermes absorption 3a — `file_search`: a literal, bounded content search inside the roots.

The model had `file_read` and `file_list`, so finding anything meant listing and reading file
by file — burning the context budget that is already the problem. `file_search` scans
contents with exactly the read tools' containment (roots, no symlink escape, no secret-looking
names) and every bound reported: matches, matches per file, files visited, seconds.
"""
import os
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
    for glob in ("", "*/x", "a\\b", "x" * 129, 7):
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


def test_spec_is_closed_ungated_and_literal():
    spec = FILE_TOOL_SPECS["file_search"]
    assert spec["gated"] is False and spec["trusted_execution"] is False
    assert spec["capability_id"] == "tool:file_search"
    schema = spec["input_schema"]
    assert schema["additionalProperties"] is False and schema["required"] == ["pattern"]
    assert "regex" not in schema["properties"]
    assert set(schema["properties"]) == {
        "pattern", "path", "glob", "case_sensitive", "whole_word", "max_matches",
    }


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
    # There is no regex: an unknown key is dropped by the preflight (as for every file
    # tool) and the pattern stays literal.
    out = await server.handle({"tool": "file_search", "args": {"pattern": "bud.*", "regex": True}})
    assert out["ok"] is True and out["result"]["matches"] == []


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
