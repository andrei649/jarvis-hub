"""H444/H576 PDF text-layer coverage is metadata beside unchanged text pages."""

import hashlib
import importlib.machinery
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from agents.core import file_tools, local_docs
from agents.core.file_tools import FileScope, FileTools

DETAIL = (
    "Some PDF pages yielded no extractable text. Do not assume the document is "
    "silent on a topic; inspect only the relevant page gaps."
)


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "workspace"
    path.mkdir()
    (path / "report.PDF").write_bytes(b"%PDF-1.4 fake parser input")
    (path / "memo.docx").write_bytes(b"PK fake parser input")
    (path / "plain.txt").write_text("plain", encoding="utf-8")
    return path


def install_pdf(monkeypatch, values, *, reader_error=None, iteration_error=None):
    """Install a real importable optional-parser stand-in, observing every visit."""
    calls = []
    fake = ModuleType("pypdf")
    fake.__spec__ = importlib.machinery.ModuleSpec("pypdf", loader=None)

    class Page:
        def __init__(self, index, value):
            self.index = index
            self.value = value

        def extract_text(self):
            calls.append(("page", self.index))
            if isinstance(self.value, Exception):
                raise self.value
            return self.value

    class FailingPages:
        def __iter__(self):
            calls.append(("iterate",))
            raise iteration_error

    class Reader:
        def __init__(self, filename):
            calls.append(("reader", filename))
            if reader_error is not None:
                raise reader_error
            self.pages = (
                FailingPages() if iteration_error is not None
                else [Page(index, value) for index, value in enumerate(values)]
            )

    fake.PdfReader = Reader
    monkeypatch.setitem(sys.modules, "pypdf", fake)
    return calls


def read_tools(root, *, max_bytes=64):
    return FileTools(FileScope([root]), max_bytes=max_bytes)


def warning(result):
    value = result["coverage_warning"]
    assert set(value) == {
        "reason", "detail", "total_pages", "pages_without_text", "gap_count",
        "gaps", "omitted_gap_count", "gaps_truncated",
    }
    assert value["reason"] == "pdf_text_layer_gaps" and value["detail"] == DETAIL
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("total,missing,expected_warning", [
    (5, 1, False),   # exactly 20%, below the ten-page absolute trigger
    (5, 2, True),    # strictly above 20%
    (50, 10, True),  # ten missing pages at exactly 20%
    (100, 10, True), # ten missing pages at only 10%
    (0, 0, False),
    (3, 3, True),
])
async def test_trigger_counts_and_zero_page_behavior(root, monkeypatch, total, missing, expected_warning):
    pages = ["" for _ in range(missing)] + [f"page {i}" for i in range(total - missing)]
    calls = install_pdf(monkeypatch, pages)
    result = await read_tools(root).read_file({"path": "report.PDF"})
    joined = "\n".join(pages)
    assert result["ok"] is True and result["extracted"] is True
    assert result["text_size"] == len(joined.encode("utf-8"))
    assert result["content"] == joined[:64]
    assert calls == [("reader", str(root / "report.PDF"))] + [
        ("page", i) for i in range(total)
    ]
    if expected_warning:
        item = warning(result)
        assert item["total_pages"] == total
        assert item["pages_without_text"] == missing
    else:
        assert "coverage_warning" not in result


@pytest.mark.asyncio
async def test_grouped_initial_middle_and_trailing_gaps_name_nearest_prior_text(root, monkeypatch):
    pages = [None, " \t", "Intro  ", "X", "\t", None, "Later", "", "  "]
    calls = install_pdf(monkeypatch, pages)
    result = await read_tools(root).read_file({"path": "report.PDF", "max_bytes": 64})
    joined = "\n".join(page or "" for page in pages)
    assert result["ok"] is True and result["content"] == joined
    assert result["text_size"] == len(joined.encode("utf-8"))
    assert len(calls) == 1 + len(pages)
    item = warning(result)
    assert (item["total_pages"], item["pages_without_text"], item["gap_count"]) == (9, 6, 3)
    assert item["gaps"] == [
        {"start_page": 1, "end_page": 2, "after_page": None,
         "after": "", "after_truncated": False},
        {"start_page": 5, "end_page": 6, "after_page": 4,
         "after": "X", "after_truncated": False},
        {"start_page": 8, "end_page": 9, "after_page": 7,
         "after": "Later", "after_truncated": False},
    ]
    assert item["omitted_gap_count"] == 0 and item["gaps_truncated"] is False


@pytest.mark.asyncio
async def test_unicode_paging_hash_and_warning_repeat_without_text_changes(root, monkeypatch):
    pages = ["Café🙂", "", "fin"]
    calls = install_pdf(monkeypatch, pages)
    tools = read_tools(root, max_bytes=20)
    joined = "\n".join(pages).encode("utf-8")
    first = await tools.read_file({"path": "report.PDF", "max_bytes": 7})
    assert first["ok"] is True and first["content"] == "Café"
    assert first["bytes"] == 5 and first["offset"] == 0 and first["next_offset"] == 5
    assert first["sha256"] == hashlib.sha256(joined[:5]).hexdigest()
    second = await tools.read_file({"path": "report.PDF", "offset": 5, "max_bytes": 20})
    assert second["ok"] is True and second["content"] == joined[5:].decode("utf-8")
    assert second["bytes"] == len(joined) - 5 and second["offset"] == 5
    assert second["sha256"] == hashlib.sha256(joined[5:]).hexdigest()
    assert second["text_size"] == first["text_size"] == len(joined)
    assert warning(first) == warning(second)
    assert calls == [
        ("reader", str(root / "report.PDF")), ("page", 0), ("page", 1), ("page", 2),
        ("reader", str(root / "report.PDF")), ("page", 0), ("page", 1), ("page", 2),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("snippet_char", ["🙂", "\x00"])
async def test_first_sixteen_ranges_exact_counts_and_unicode_snippet_cap(
    root, monkeypatch, snippet_char,
):
    pages = []
    for _ in range(17):
        pages.extend([snippet_char * 161 + "  \n", "\t"])
    calls = install_pdf(monkeypatch, pages)
    result = await read_tools(root, max_bytes=8).read_file({"path": "report.PDF", "max_bytes": 8})
    assert result["ok"] is True and result["bytes"] <= 8
    assert len(calls) == 1 + len(pages)
    item = warning(result)
    assert (item["total_pages"], item["pages_without_text"], item["gap_count"]) == (34, 17, 17)
    assert len(item["gaps"]) == 16
    assert item["omitted_gap_count"] == 1 and item["gaps_truncated"] is True
    for i, gap in enumerate(item["gaps"]):
        assert gap == {
            "start_page": 2 * i + 2, "end_page": 2 * i + 2,
            "after_page": 2 * i + 1, "after": snippet_char * 160,
            "after_truncated": True,
        }
    assert len(json.dumps(item, ensure_ascii=False).encode("utf-8")) < 20_000


@pytest.mark.asyncio
async def test_retained_sixteenth_range_extends_but_omitted_seventeenth_is_counted(root, monkeypatch):
    pages = []
    for index in range(17):
        pages.extend([f"text {index}", ""])
        if index >= 15:
            pages.append(" ")  # Both final ranges span two missing-text pages.
    calls = install_pdf(monkeypatch, pages)
    result = await read_tools(root).read_file({"path": "report.PDF"})
    assert result["ok"] is True
    assert result["text_size"] == len("\n".join(pages).encode("utf-8"))
    assert len(calls) == 1 + len(pages)
    item = warning(result)
    assert (item["total_pages"], item["pages_without_text"], item["gap_count"]) == (36, 19, 17)
    assert len(item["gaps"]) == 16
    assert item["gaps"][-1] == {
        "start_page": 32, "end_page": 33, "after_page": 31,
        "after": "text 15", "after_truncated": False,
    }
    assert item["omitted_gap_count"] == 1 and item["gaps_truncated"] is True


@pytest.mark.asyncio
async def test_exact_160_code_point_snippet_is_not_truncated(root, monkeypatch):
    pages = ["é" * 160 + "  ", ""]
    install_pdf(monkeypatch, pages)
    result = await read_tools(root).read_file({"path": "report.PDF", "max_bytes": 5})
    assert result["ok"] is True and result["content"] == "éé"
    gap = warning(result)["gaps"][0]
    assert gap == {
        "start_page": 2, "end_page": 2, "after_page": 1,
        "after": "é" * 160, "after_truncated": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["reader", "iterate", "page", "nonstring"])
async def test_failed_or_ambiguous_pdf_extraction_keeps_named_failure_without_warning(
    root, monkeypatch, case,
):
    kwargs = {}
    pages = ["first", "second"]
    if case == "reader":
        kwargs["reader_error"] = ValueError("unreadable")
    elif case == "iterate":
        kwargs["iteration_error"] = RuntimeError("iteration failed")
    elif case == "page":
        pages[1] = RuntimeError("later page failed")
    else:
        pages[1] = {"not": "text"}
    calls = install_pdf(monkeypatch, pages, **kwargs)
    result = await read_tools(root).read_file({"path": "report.PDF"})
    assert result == {
        "ok": False, "reason": "extraction_failed",
        "detail": "the file could not be parsed",
    }
    assert "coverage_warning" not in result
    assert calls[0] == ("reader", str(root / "report.PDF"))


@pytest.mark.asyncio
async def test_raw_plain_docx_and_parser_missing_have_no_pdf_warning(root, monkeypatch):
    calls = install_pdf(monkeypatch, ["", ""])
    tools = read_tools(root)
    raw = await tools.read_file({"path": "report.PDF", "raw": True})
    plain = await tools.read_file({"path": "plain.txt"})
    assert raw["ok"] is True and plain["ok"] is True and calls == []
    assert "coverage_warning" not in raw and "coverage_warning" not in plain
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: True)
    monkeypatch.setattr(file_tools, "extract_text", lambda path: "docx text")
    docx = await tools.read_file({"path": "memo.docx"})
    assert docx["ok"] is True and docx["content"] == "docx text"
    assert "coverage_warning" not in docx
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: False)
    missing = await tools.read_file({"path": "report.PDF"})
    assert missing["reason"] == "parser_missing" and "coverage_warning" not in missing


@pytest.mark.parametrize("pages,expected", [
    (["first", None, "  ", "last"], "first\n\n  \nlast"),
    ([], ""),
    (["first", RuntimeError("bad page")], None),
    (["first", {"not": "text"}], None),
])
def test_legacy_extract_text_pdf_projection_stays_joined_or_none(
    root, monkeypatch, pages, expected,
):
    calls = install_pdf(monkeypatch, pages)
    result = local_docs.extract_text(root / "report.PDF")
    assert result == expected
    assert calls[0] == ("reader", str(root / "report.PDF"))
    if expected is not None:
        assert calls == [("reader", str(root / "report.PDF"))] + [
            ("page", i) for i in range(len(pages))
        ]
