"""H303 — `file_read` line-numbered output and the per-line length cap.

H444 gave `file_read` a line window (`line_offset` / `line_limit`); the two gaps left for a
codebase reader were that the page carried no line numbers — so the model had to count — and
that one over-long line (a minified bundle, a data row) filled a page by itself. Now
`line_numbers: true` prefixes every line with its 1-based number, and `max_line_chars` cuts a
long line with a visible marker while the paging stays exact: a cut line is still one line,
`next_line_offset` still names the next one, and the byte budget still holds.
"""
import hashlib
import importlib.machinery
import os
import sys
from types import ModuleType

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from agents.core import file_tools  # noqa: E402
from agents.core.file_tools import (  # noqa: E402
    FILE_TOOL_SPECS,
    LINE_CUT_MARKER,
    FileScope,
    FileTools,
)
from agents.core.tool_rpc import ToolRPCValidationError  # noqa: E402


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / "workspace"
    directory.mkdir()
    return directory


def reader(root, max_bytes=4096):
    return FileTools(FileScope([root]), max_bytes=max_bytes)


def cut(more):
    return LINE_CUT_MARKER.format(more=more)


# ── line numbers ─────────────────────────────────────────────────────────────

async def test_line_numbers_prefix_each_line_with_its_1_based_number(root):
    (root / "notes.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    page = await reader(root).read_file({"path": "notes.txt", "line_numbers": True, "line_limit": 2})
    assert page["ok"] is True and page["line_numbers"] is True
    assert page["content"] == "1\tone\n2\ttwo\n"
    assert page["line_offset"] == 1 and page["lines"] == 2 and page["next_line_offset"] == 3
    assert page["bytes"] == len(page["content"].encode("utf-8"))
    assert page["sha256"] == hashlib.sha256(page["content"].encode("utf-8")).hexdigest()
    # line_numbers alone is a line window from the first line (never a byte page).
    whole = await reader(root).read_file({"path": "notes.txt", "line_numbers": True})
    assert whole["content"] == "  1\tone\n  2\ttwo\n  3\tthree\n"   # width of 500, the default limit
    assert whole["total_lines"] == 3 and "offset" not in whole and "next_line_offset" not in whole


async def test_numbers_are_right_aligned_to_the_window_so_a_page_lines_up(root):
    (root / "rows.txt").write_text("".join(f"r{i}\n" for i in range(1, 13)), encoding="utf-8")
    page = await reader(root).read_file(
        {"path": "rows.txt", "line_offset": 9, "line_limit": 2, "line_numbers": True})
    assert page["content"] == " 9\tr9\n10\tr10\n"
    assert page["next_line_offset"] == 11
    plain = await reader(root).read_file({"path": "rows.txt", "line_offset": 9, "line_limit": 2})
    assert plain["content"] == "r9\nr10\n" and "line_numbers" not in plain


async def test_a_byte_page_is_never_numbered_and_numbers_beside_an_offset_are_refused(root):
    (root / "notes.txt").write_text("one\ntwo\n", encoding="utf-8")
    tools = reader(root)
    assert await tools.read_file({"path": "notes.txt", "offset": 4, "line_numbers": True}) == {
        "ok": False, "reason": "bad_window"}
    page = await tools.read_file({"path": "notes.txt", "offset": 4, "line_numbers": False})
    assert page["content"] == "two\n" and page["offset"] == 4 and "line_numbers" not in page
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_read"]["preflight"]({"path": "notes.txt", "line_numbers": "yes"})
    assert info.value.reason == "bad_flag"
    assert await tools.read_file({"path": "notes.txt", "line_numbers": 1}) == {
        "ok": False, "reason": "bad_flag"}


async def test_the_byte_budget_counts_the_number_prefix(root):
    (root / "rows.txt").write_text("aaaa\nbbbb\ncccc\n", encoding="utf-8")
    # "1\taaaa\n" is 7 bytes: two numbered lines (14) do not fit in 12, one does.
    page = await reader(root, max_bytes=12).read_file(
        {"path": "rows.txt", "line_limit": 3, "line_numbers": True})
    assert page["content"] == "1\taaaa\n" and page["lines"] == 1 and page["bytes"] == 7
    assert page["next_line_offset"] == 2
    plain = await reader(root, max_bytes=12).read_file({"path": "rows.txt", "line_limit": 3})
    assert plain["content"] == "aaaa\nbbbb\n" and plain["lines"] == 2  # H444 unchanged


async def test_a_first_line_bigger_than_the_budget_is_cut_after_its_number(root):
    (root / "wide.txt").write_text("head\n" + "é" * 40 + "\n" + "tail\n", encoding="utf-8")
    page = await reader(root, max_bytes=9).read_file(
        {"path": "wide.txt", "line_offset": 2, "line_limit": 1, "line_numbers": True})
    assert page["line_truncated"] is True and page["lines"] == 1
    assert page["content"] == "2\tééé" and page["bytes"] == 8      # 2 + 3 whole characters
    assert page["line_byte_offset"] == 5 and page["next_line_offset"] == 3


# ── the per-line cap ─────────────────────────────────────────────────────────

async def test_a_long_line_is_cut_with_a_marker_and_the_paging_stays_exact(root):
    text = "short\n" + "abcdefghijklmnopqrstuvwxyz\n" + "x" * 300 + "\n" + "end\n"
    (root / "long.txt").write_text(text, encoding="utf-8")
    page = await reader(root).read_file({"path": "long.txt", "max_line_chars": 10, "line_limit": 3})
    assert page["content"] == "short\n" + "abcdefghij" + cut(16) + "\n" + "x" * 10 + cut(290) + "\n"
    assert page["lines"] == 3 and page["lines_cut"] == 2 and page["max_line_chars"] == 10
    assert page["next_line_offset"] == 4 and "line_truncated" not in page
    assert page["bytes"] == len(page["content"].encode("utf-8"))
    rest = await reader(root).read_file({"path": "long.txt", "line_offset": 4, "max_line_chars": 10})
    assert rest["content"] == "end\n" and rest["lines_cut"] == 0 and rest["total_lines"] == 4
    # A line of exactly the cap is intact; the newline does not count.
    (root / "edge.txt").write_text("abcdefghij\nabcdefghijk\n", encoding="utf-8")
    edge = await reader(root).read_file({"path": "edge.txt", "max_line_chars": 10})
    assert edge["content"] == "abcdefghij\n" + "abcdefghij" + cut(1) + "\n" and edge["lines_cut"] == 1


async def test_the_cap_counts_characters_not_bytes_and_keeps_crlf_lines_whole(root):
    (root / "u.txt").write_bytes("ééééééééé\r\n".encode() + b"ab\r\n")
    page = await reader(root).read_file({"path": "u.txt", "max_line_chars": 8})
    assert page["content"] == "éééééééé" + cut(1) + "\n" + "ab\r\n"
    assert page["lines"] == 2 and page["lines_cut"] == 1 and page["total_lines"] == 2


async def test_the_cap_lets_a_page_hold_many_lines_after_an_over_long_one(root):
    # Before H303 the 5 000-char line filled a 4 096-byte page by itself (cut, with
    # line_truncated). With a cap it is one line among the others and the budget holds.
    lines = ["a" * 5000] + [f"line {i}" for i in range(1, 50)]
    (root / "bundle.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    page = await reader(root, max_bytes=4096).read_file(
        {"path": "bundle.txt", "max_line_chars": 80, "line_numbers": True})
    assert page["lines"] == 50 and page["lines_cut"] == 1 and page["truncated"] is False
    assert page["content"].startswith("  1\t" + "a" * 80 + cut(4920) + "\n  2\tline 1\n")
    assert page["bytes"] <= 4096 and "line_truncated" not in page
    old = await reader(root, max_bytes=4096).read_file({"path": "bundle.txt", "line_limit": 50})
    assert old["lines"] == 1 and old["line_truncated"] is True   # H444 behaviour without a cap


async def test_numbered_output_caps_lines_by_default_and_a_plain_window_does_not(root):
    (root / "w.txt").write_text("y" * 2500 + "\n", encoding="utf-8")
    numbered = await reader(root).read_file({"path": "w.txt", "line_numbers": True})
    assert numbered["max_line_chars"] == file_tools.DEFAULT_LINE_CHARS == 2000
    assert numbered["content"] == "  1\t" + "y" * 2000 + cut(500) + "\n" and numbered["lines_cut"] == 1
    plain = await reader(root).read_file({"path": "w.txt", "line_offset": 1})
    assert plain["content"] == "y" * 2500 + "\n" and "max_line_chars" not in plain
    lifted = await reader(root).read_file(
        {"path": "w.txt", "line_numbers": True, "max_line_chars": 3000})
    assert lifted["content"] == "  1\t" + "y" * 2500 + "\n" and lifted["lines_cut"] == 0


async def test_following_next_line_offset_with_a_cap_visits_every_line_once(root):
    text = "".join(("z" * 400 if i % 5 == 0 else f"line {i}") + "\n" for i in range(1, 61))
    (root / "mix.txt").write_text(text, encoding="utf-8")
    tools = reader(root, max_bytes=256)
    seen, line, guard = [], 1, 0
    while True:
        page = await tools.read_file(
            {"path": "mix.txt", "line_offset": line, "line_limit": 7, "max_line_chars": 20,
             "line_numbers": True})
        assert "line_truncated" not in page
        seen.extend(int(row.split("\t", 1)[0]) for row in page["content"].splitlines())
        if "next_line_offset" not in page:
            break
        assert page["next_line_offset"] == line + page["lines"]
        line = page["next_line_offset"]
        guard += 1
        assert guard < 100
    assert seen == list(range(1, 61)) and page["total_lines"] == 60


async def test_a_document_is_numbered_and_capped_like_a_text_file(root, monkeypatch):
    fake = ModuleType("pypdf")
    fake.__spec__ = importlib.machinery.ModuleSpec("pypdf", loader=None)

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class Reader:
        def __init__(self, source):
            self.pages = [Page("Title\n" + "w" * 30), Page("Last line")]

    fake.PdfReader = Reader
    monkeypatch.setitem(sys.modules, "pypdf", fake)
    (root / "report.pdf").write_bytes(b"%PDF-1.4")
    page = await reader(root).read_file(
        {"path": "report.pdf", "line_numbers": True, "max_line_chars": 10, "line_limit": 2})
    assert page["extracted"] is True and page["format"] == "pdf"
    assert page["content"] == "1\tTitle\n2\t" + "w" * 10 + cut(20) + "\n"
    assert page["lines_cut"] == 1 and page["next_line_offset"] == 3 and page["total_lines"] == 3


# ── refusals and the schema ──────────────────────────────────────────────────

@pytest.mark.parametrize("args,reason", [
    ({"max_line_chars": 7}, "bad_max_line_chars"),
    ({"max_line_chars": 0}, "bad_max_line_chars"),
    ({"max_line_chars": True}, "bad_max_line_chars"),
    ({"max_line_chars": "80"}, "bad_max_line_chars"),
    ({"max_line_chars": 100_001}, "bad_max_line_chars"),
    ({"max_line_chars": 80, "offset": 3}, "bad_window"),
    ({"line_numbers": True, "offset": 1}, "bad_window"),
])
async def test_bad_line_format_arguments_are_refused_by_name(root, args, reason):
    (root / "notes.txt").write_text("x\n", encoding="utf-8")
    assert await reader(root).read_file({"path": "notes.txt", **args}) == {"ok": False, "reason": reason}
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_read"]["preflight"]({"path": "notes.txt", **args})
    assert info.value.reason == reason


def test_the_schema_declares_line_numbers_and_the_cap():
    spec = FILE_TOOL_SPECS["file_read"]
    props = spec["input_schema"]["properties"]
    assert props["line_numbers"] == {"type": "boolean"}
    assert props["max_line_chars"] == {
        "type": "integer", "minimum": file_tools.MIN_LINE_CHARS, "maximum": file_tools.MAX_LINE_CHARS}
    assert file_tools.MIN_LINE_CHARS == 8 and file_tools.MAX_LINE_CHARS == 100_000
    assert spec["preflight"]({"path": "a", "line_numbers": True, "max_line_chars": 40}) == {
        "path": "a", "line_numbers": True, "max_line_chars": 40}
    assert "line_numbers" in spec["description"] and "max_line_chars" in spec["description"]
    assert spec["input_schema"]["additionalProperties"] is False
