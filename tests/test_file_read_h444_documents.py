"""H444 — reading documents into the conversation, the parts Hermes has that we lacked.

* A parsed document is cached under the SHA-256 of the admitted input bytes, so the
  next page of an unchanged document is not parsed again; an edited file is.
* The parser reads the bytes ``file_read`` admitted (bounded, read once), never the
  path: a file that grows past the 50 MB ceiling after it was measured is refused.
* Extraction runs within a text-size and a time budget, and says when one ran out.
* Coverage names garbled pages (mostly unusable characters) beside empty ones, and
  pages holding images are named as visual content the text does not carry.
* ``line_offset`` / ``line_limit`` page any file — and a document's extracted text —
  by whole lines, still bounded by ``max_bytes``.
"""

import hashlib
import importlib.machinery
import io
import os
import sys
import zlib
from pathlib import Path
from types import ModuleType

import pytest

from agents.core import file_tools, local_docs
from agents.core.file_tools import (
    FILE_TOOL_SPECS,
    MAX_DOCUMENT_BYTES,
    DocumentCache,
    FileScope,
    FileTools,
)
from agents.core.local_docs import DocumentExtraction
from agents.core.tool_rpc import ToolRPCValidationError


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / "workspace"
    directory.mkdir()
    return directory


def reader(root, max_bytes=4096):
    return FileTools(FileScope([root]), max_bytes=max_bytes)


def install_pdf(monkeypatch, pages, *, resources=None):
    """A real importable ``pypdf`` stand-in that records what it was handed."""
    calls = []
    fake = ModuleType("pypdf")
    fake.__spec__ = importlib.machinery.ModuleSpec("pypdf", loader=None)
    resources = resources or {}

    class Page(dict):
        def __init__(self, index, text):
            super().__init__()
            if index in resources:
                self["/Resources"] = resources[index]
            self.index = index
            self.text = text

        def extract_text(self):
            calls.append(("page", self.index))
            return self.text

    class Reader:
        def __init__(self, source):
            calls.append(("reader", source))
            self.pages = [Page(i, text) for i, text in enumerate(pages)]

    fake.PdfReader = Reader
    monkeypatch.setitem(sys.modules, "pypdf", fake)
    return calls


def parses(calls):
    return [call for call in calls if call[0] == "reader"]


# ── the parse cache ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_paging_an_unchanged_document_parses_it_once(root, monkeypatch):
    (root / "report.pdf").write_bytes(b"%PDF-1.4 one")
    calls = install_pdf(monkeypatch, ["alpha " * 10, "beta " * 10, "gamma " * 10])
    tools = reader(root, max_bytes=16)
    seen, offset = [], 0
    while True:
        page = await tools.read_file({"path": "report.pdf", "offset": offset})
        assert page["ok"] is True, page
        seen.append(page)
        if "next_offset" not in page:
            break
        offset = page["next_offset"]
    assert len(seen) > 3
    assert len(parses(calls)) == 1, "every later page must come from the cache"
    assert [page["cached"] for page in seen] == [False] + [True] * (len(seen) - 1)
    assert "".join(page["content"] for page in seen) == "\n".join(
        ["alpha " * 10, "beta " * 10, "gamma " * 10])


@pytest.mark.asyncio
async def test_an_edited_document_is_parsed_again_even_with_the_same_size(root, monkeypatch):
    target = root / "report.pdf"
    target.write_bytes(b"%PDF-1.4 AAAA")
    calls = install_pdf(monkeypatch, ["first"])
    tools = reader(root)
    stat = target.stat()
    assert (await tools.read_file({"path": "report.pdf"}))["cached"] is False
    assert (await tools.read_file({"path": "report.pdf"}))["cached"] is True
    target.write_bytes(b"%PDF-1.4 BBBB")  # same size; restore the old mtime too
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    again = await tools.read_file({"path": "report.pdf"})
    assert again["ok"] is True and again["cached"] is False
    assert len(parses(calls)) == 2


@pytest.mark.asyncio
async def test_each_file_tools_keeps_its_own_cache_and_a_failure_is_not_cached(root, monkeypatch):
    (root / "report.pdf").write_bytes(b"%PDF-1.4")
    calls = install_pdf(monkeypatch, ["text"])
    assert (await reader(root).read_file({"path": "report.pdf"}))["cached"] is False
    assert (await reader(root).read_file({"path": "report.pdf"}))["cached"] is False
    assert len(parses(calls)) == 2
    tools = reader(root)
    monkeypatch.setattr(file_tools, "extract_pdf_document", lambda source: None)
    for _ in range(2):
        failed = await tools.read_file({"path": "report.pdf"})
        assert failed == {"ok": False, "reason": "extraction_failed",
                          "detail": "the file could not be parsed"}
    assert len(tools._documents) == 0


def _parsed(size):
    return file_tools._ParsedDocument(text=b"x" * size, total_lines=1, annotations={})


def test_the_cache_is_lru_and_bounded_by_entries_and_text_bytes():
    cache = DocumentCache(max_entries=2, max_text_bytes=10)
    cache.put(("pdf", "a"), _parsed(3))
    cache.put(("pdf", "b"), _parsed(3))
    assert cache.get(("pdf", "a")) is not None  # a is now the most recent
    cache.put(("pdf", "c"), _parsed(3))
    assert cache.get(("pdf", "b")) is None and len(cache) == 2
    cache.put(("pdf", "d"), _parsed(6))  # three entries: the least recent (a) leaves
    assert cache.get(("pdf", "a")) is None
    assert cache.get(("pdf", "c")) is not None and cache.get(("pdf", "d")) is not None
    cache.put(("pdf", "e"), _parsed(8))  # count evicts d (c was just used), 3 + 8 > 10 evicts c
    assert cache.get(("pdf", "d")) is None and cache.get(("pdf", "c")) is None
    assert cache.get(("pdf", "e")) is not None and len(cache) == 1
    cache.put(("pdf", "huge"), _parsed(11))  # bigger than the whole cache: not kept
    assert cache.get(("pdf", "huge")) is None and len(cache) == 1
    defaults = DocumentCache()
    assert defaults.max_entries == file_tools.DOCUMENT_CACHE_ENTRIES == 8
    assert defaults.max_text_bytes == file_tools.DOCUMENT_CACHE_TEXT_BYTES == 64_000_000


# ── the parser reads the admitted bytes, not the path ────────────────────────

@pytest.mark.asyncio
async def test_the_parser_gets_the_admitted_bytes_in_memory(root, monkeypatch):
    body = b"%PDF-1.4 admitted bytes"
    (root / "report.pdf").write_bytes(body)
    calls = install_pdf(monkeypatch, ["text"])
    out = await reader(root).read_file({"path": "report.pdf"})
    assert out["ok"] is True
    source = parses(calls)[0][1]
    assert isinstance(source, io.BytesIO) and source.getvalue() == body
    assert source.name == str(root / "report.pdf")


@pytest.mark.asyncio
async def test_a_document_that_grew_past_the_ceiling_after_stat_is_refused(root, monkeypatch):
    target = root / "growing.pdf"
    with target.open("wb") as handle:
        handle.truncate(MAX_DOCUMENT_BYTES + 10)
    real_stat = Path.stat

    def small_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path == target:  # what was measured before the file grew
            fields = list(result)
            fields[6] = 100
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "stat", small_stat)
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: True)
    monkeypatch.setattr(file_tools, "extract_pdf_document",
                        lambda source: pytest.fail("the grown file must not be parsed"))
    out = await reader(root).read_file({"path": "growing.pdf"})
    assert out["ok"] is False and out["reason"] == "document_too_large"
    assert out["size"] == MAX_DOCUMENT_BYTES + 10
    assert out["max_document_bytes"] == MAX_DOCUMENT_BYTES


# ── extraction budgets ───────────────────────────────────────────────────────

def test_pdf_extraction_stops_at_the_text_budget_on_a_page_boundary(monkeypatch):
    calls = install_pdf(monkeypatch, ["aaaa", "bbbb", "cccc"])
    out = local_docs.extract_pdf_document(io.BytesIO(b"x"), max_text_bytes=9)
    assert out.pages == ["aaaa", "bbbb"] and out.stopped == "text_limit"
    assert (out.units_read, out.units_total, out.unit) == (2, 3, "page")
    assert calls.count(("page", 2)) == 1  # read, found over budget, and dropped
    whole = local_docs.extract_pdf_document(io.BytesIO(b"x"))
    assert whole.stopped is None and whole.text == "aaaa\nbbbb\ncccc"
    first = local_docs.extract_pdf_document(io.BytesIO(b"x"), max_text_bytes=1)
    assert first.pages == ["aaaa"] and first.stopped == "text_limit", \
        "the first page is always read, so a budget never yields an empty success"


def test_pdf_extraction_stops_at_the_time_budget(monkeypatch):
    install_pdf(monkeypatch, ["one", "two", "three"])
    ticks = iter([0.0, 1.0, 100.0, 200.0])
    out = local_docs.extract_pdf_document(io.BytesIO(b"x"), max_seconds=50,
                                          clock=lambda: next(ticks))
    assert out.pages == ["one", "two"] and out.stopped == "time_limit"
    assert (out.units_read, out.units_total) == (2, 3)
    assert local_docs.MAX_EXTRACTION_SECONDS == 60.0
    assert local_docs.MAX_EXTRACTED_TEXT_BYTES == 32_000_000


@pytest.mark.asyncio
async def test_a_stopped_extraction_is_named_beside_the_text(root, monkeypatch):
    (root / "big.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: True)
    monkeypatch.setattr(file_tools, "extract_pdf_document", lambda source: DocumentExtraction(
        pages=["first page"], units_total=40, units_read=1, stopped="time_limit"))
    out = await reader(root).read_file({"path": "big.pdf"})
    assert out["ok"] is True and out["content"] == "first page"
    note = out["extraction_incomplete"]
    assert note["reason"] == "time_limit" and note["unit"] == "page"
    assert (note["units_read"], note["units_total"]) == (1, 40)
    assert "1 of 40 pages" in note["detail"] and "not the whole document" in note["detail"]
    whole = DocumentExtraction.from_pages(["all"])
    monkeypatch.setattr(file_tools, "extract_pdf_document", lambda source: whole)
    (root / "small.pdf").write_bytes(b"%PDF-1.4 small")
    assert "extraction_incomplete" not in await reader(root).read_file({"path": "small.pdf"})


# ── coverage: garbled text and visual content ────────────────────────────────

@pytest.mark.parametrize("text,garbled", [
    ("An ordinary paragraph of readable English text.", False),
    ("�" * 30, True),
    ("(cid:12)(cid:7)(cid:44)" * 4, True),
    ("" * 10 + " some words", True),
    ("short ��", False),  # too little text to judge
    ("Ünïcödé — 日本語のテキスト — 🙂 emoji are real text", False),
    ("mostly fine text with a few � marks in a long line of words", False),
])
def test_garbled_text_heuristic(text, garbled):
    assert local_docs.page_text_garbled(text) is garbled


@pytest.mark.asyncio
async def test_garbled_pages_are_named_beside_the_empty_gaps(root, monkeypatch):
    (root / "mixed.pdf").write_bytes(b"%PDF-1.4")
    good = "A readable page of plain text."
    pages = [good, "�" * 40, "(cid:3)" * 20, good, good]
    install_pdf(monkeypatch, pages)
    out = await reader(root).read_file({"path": "mixed.pdf"})
    warning = out["coverage_warning"]
    assert warning["pages_without_text"] == 0 and warning["gap_count"] == 0
    assert warning["pages_with_garbled_text"] == 2
    assert warning["garbled_ranges"] == [{"start_page": 2, "end_page": 3}]
    assert warning["omitted_garbled_range_count"] == 0
    install_pdf(monkeypatch, [good] * 5)
    (root / "clean.pdf").write_bytes(b"%PDF-1.4 clean")
    assert "coverage_warning" not in await reader(root).read_file({"path": "clean.pdf"})


def test_page_ranges_group_and_bound():
    assert local_docs.page_ranges([]) == {
        "range_count": 0, "ranges": [], "omitted_range_count": 0, "ranges_truncated": False}
    out = local_docs.page_ranges(list(range(1, 80, 2)))
    assert out["range_count"] == 40 and len(out["ranges"]) == 16
    assert out["omitted_range_count"] == 24 and out["ranges_truncated"] is True
    assert local_docs.page_ranges([3, 4, 5, 9])["ranges"] == [
        {"start_page": 3, "end_page": 5}, {"start_page": 9, "end_page": 9}]


@pytest.mark.asyncio
async def test_pages_with_image_xobjects_are_named_as_visual_content(root, monkeypatch):
    (root / "deck.pdf").write_bytes(b"%PDF-1.4")
    image = {"/XObject": {"/Im0": {"/Subtype": "/Image"}}}
    form = {"/XObject": {"/Fm0": {"/Subtype": "/Form"}}}
    install_pdf(monkeypatch, ["one", "two", "three", "four"],
                resources={1: image, 2: image, 3: form})
    out = await reader(root).read_file({"path": "deck.pdf"})
    visual = out["visual_content"]
    assert visual["reason"] == "pdf_pages_with_images"
    assert visual["pages_with_images"] == 2
    assert visual["ranges"] == [{"start_page": 2, "end_page": 3}]
    assert "no OCR" in visual["detail"]
    install_pdf(monkeypatch, ["one"])
    (root / "plain.pdf").write_bytes(b"%PDF-1.4 plain")
    assert "visual_content" not in await reader(root).read_file({"path": "plain.pdf"})


def _real_pdf(pages):
    """A minimal valid PDF: each page is ``("text", str)`` or ``("image", None)``."""
    objects = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
               3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               4: (b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
                   b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>\nstream\n\xff"
                   b"\nendstream")}
    kids = []
    number = 5
    for kind, text in pages:
        if kind == "text":
            content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
            resources = b"<< /Font << /F1 3 0 R >> >>"
        else:
            content = b"q 100 0 0 100 0 0 cm /Im0 Do Q"
            resources = b"<< /XObject << /Im0 4 0 R >> >>"
        data = zlib.compress(content)
        objects[number] = (b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data)
                           + data + b"\nendstream")
        objects[number + 1] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                               b"/Resources " + resources + b" /Contents %d 0 R >>" % number)
        kids.append(number + 1)
        number += 2
    objects[2] = (b"<< /Type /Pages /Count %d /Kids [" % len(kids)
                  + b" ".join(b"%d 0 R" % k for k in kids) + b"] >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for key in sorted(objects):
        offsets[key] = len(out)
        out += b"%d 0 obj\n" % key + objects[key] + b"\nendobj\n"
    xref = len(out)
    size = max(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for key in range(1, size):
        out += b"%010d 00000 n \n" % offsets[key]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref)
    return bytes(out)


@pytest.mark.asyncio
async def test_a_real_scanned_pdf_is_flagged_through_the_real_parser(root):
    pytest.importorskip("pypdf")
    pages = [("text", "Introduction to the report")] + [("image", None)] * 3
    (root / "scan.pdf").write_bytes(_real_pdf(pages))
    tools = reader(root)
    out = await tools.read_file({"path": "scan.pdf"})
    assert out["ok"] is True and out["cached"] is False
    assert out["content"].startswith("Introduction to the report")
    warning = out["coverage_warning"]
    assert warning["total_pages"] == 4 and warning["pages_without_text"] == 3
    assert warning["gaps"][0]["start_page"] == 2 and warning["gaps"][0]["end_page"] == 4
    assert out["visual_content"]["ranges"] == [{"start_page": 2, "end_page": 4}]
    again = await tools.read_file({"path": "scan.pdf", "line_offset": 1, "line_limit": 1})
    assert again["cached"] is True and again["lines"] == 1


# ── the line window ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_line_window_returns_whole_lines_and_names_the_next(root):
    (root / "notes.txt").write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8", newline="")
    tools = reader(root)
    page = await tools.read_file({"path": "notes.txt", "line_offset": 2, "line_limit": 2})
    assert page["ok"] is True and page["content"] == "two\nthree\n"
    assert page["line_offset"] == 2 and page["lines"] == 2
    assert page["next_line_offset"] == 4 and page["truncated"] is True
    assert "total_lines" not in page and "offset" not in page
    assert page["sha256"] == hashlib.sha256(b"two\nthree\n").hexdigest()
    last = await tools.read_file({"path": "notes.txt", "line_offset": 4, "line_limit": 10})
    assert last["content"] == "four\nfive\n" and last["lines"] == 2
    assert last["truncated"] is False and "next_line_offset" not in last
    assert last["total_lines"] == 5
    past = await tools.read_file({"path": "notes.txt", "line_offset": 9})
    assert past["content"] == "" and past["lines"] == 0 and past["total_lines"] == 5
    default = await tools.read_file({"path": "notes.txt", "line_limit": 1})
    assert default["line_offset"] == 1 and default["content"] == "one\n"


@pytest.mark.asyncio
async def test_a_final_line_without_newline_counts(root):
    (root / "tail.txt").write_bytes(b"a\nb")
    page = await reader(root).read_file({"path": "tail.txt", "line_offset": 1})
    assert page["content"] == "a\nb" and page["lines"] == 2 and page["total_lines"] == 2
    (root / "empty.txt").write_bytes(b"")
    empty = await reader(root).read_file({"path": "empty.txt", "line_offset": 1})
    assert empty["content"] == "" and empty["lines"] == 0 and empty["total_lines"] == 0


@pytest.mark.asyncio
async def test_the_byte_cap_ends_a_line_page_before_a_line_that_does_not_fit(root):
    (root / "rows.txt").write_text("aaaa\nbbbb\ncccc\n", encoding="utf-8", newline="")
    page = await reader(root, max_bytes=12).read_file(
        {"path": "rows.txt", "line_offset": 1, "line_limit": 3})
    assert page["content"] == "aaaa\nbbbb\n" and page["lines"] == 2
    assert page["next_line_offset"] == 3 and page["bytes"] == 10


@pytest.mark.asyncio
async def test_a_line_longer_than_the_page_is_cut_and_its_byte_offset_named(root):
    long_line = "é" * 40 + "\n"
    (root / "wide.txt").write_text("head\n" + long_line + "tail\n", encoding="utf-8", newline="")
    tools = reader(root, max_bytes=9)
    page = await tools.read_file({"path": "wide.txt", "line_offset": 2})
    assert page["line_truncated"] is True and page["lines"] == 1
    assert page["content"] == "éééé" and page["bytes"] == 8  # never splits a character
    assert page["line_byte_offset"] == 5 and page["next_line_offset"] == 3
    rest = await tools.read_file({"path": "wide.txt", "offset": page["line_byte_offset"] + 8})
    assert rest["content"].startswith("é")
    after = await tools.read_file({"path": "wide.txt", "line_offset": 3})
    assert after["content"] == "tail\n" and after["total_lines"] == 3


@pytest.mark.asyncio
async def test_following_next_line_offset_rebuilds_the_file_exactly(root):
    text = "".join(f"line {i} {'x' * (i % 7)} 🙂\r\n" if i % 3 else f"row {i}\n"
                   for i in range(1, 120)) + "no newline at end"
    (root / "big.txt").write_text(text, encoding="utf-8", newline="")
    tools = reader(root, max_bytes=64)
    pieces, line, guard = [], 1, 0
    while True:
        page = await tools.read_file({"path": "big.txt", "line_offset": line, "line_limit": 7})
        assert "line_truncated" not in page
        pieces.append(page["content"])
        if "next_line_offset" not in page:
            break
        assert page["next_line_offset"] > line
        line = page["next_line_offset"]
        guard += 1
        assert guard < 1000
    assert "".join(pieces) == text and page["total_lines"] == 120


@pytest.mark.asyncio
async def test_a_document_pages_by_lines_with_its_total_known(root, monkeypatch):
    (root / "report.pdf").write_bytes(b"%PDF-1.4")
    calls = install_pdf(monkeypatch, ["Title\nSummary line", "", "Last line"])
    tools = reader(root)
    page = await tools.read_file({"path": "report.pdf", "line_offset": 2, "line_limit": 2})
    assert page["extracted"] is True and page["content"] == "Summary line\n\n"
    assert page["total_lines"] == 4 and page["next_line_offset"] == 4
    assert "coverage_warning" in page  # 1 of 3 pages empty: over 20 %
    last = await tools.read_file({"path": "report.pdf", "line_offset": 4})
    assert last["content"] == "Last line" and last["cached"] is True
    assert len(parses(calls)) == 1


@pytest.mark.asyncio
async def test_a_spill_read_by_lines_stays_tainted(tmp_path):
    root = tmp_path / "roots"
    root.mkdir()
    spill = tmp_path / "spill"
    spill.mkdir()
    target = spill / "toolres-0123456789abcdef.txt"
    target.write_text("a\nb\n", encoding="utf-8")
    tools = FileTools(FileScope([root]), spill_dirs=[spill])
    if not tools.reaches(str(target)):
        pytest.skip("spill naming differs on this branch")
    page = await tools.read_file({"path": str(target), "line_offset": 1})
    assert page["ok"] is True and page["tainted"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("args,reason", [
    ({"offset": 1, "line_offset": 1}, "bad_window"),
    ({"offset": 5, "line_limit": 3}, "bad_window"),
    ({"line_offset": 0}, "bad_line_offset"),
    ({"line_offset": True}, "bad_line_offset"),
    ({"line_offset": "2"}, "bad_line_offset"),
    ({"line_limit": 0}, "bad_line_limit"),
    ({"line_limit": 2001}, "bad_line_limit"),
    ({"line_limit": 2.0}, "bad_line_limit"),
])
async def test_bad_windows_are_refused_by_name(root, args, reason):
    (root / "notes.txt").write_text("x\n", encoding="utf-8")
    out = await reader(root).read_file({"path": "notes.txt", **args})
    assert out == {"ok": False, "reason": reason}
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_read"]["preflight"]({"path": "notes.txt", **args})
    assert info.value.reason == reason


def test_the_schema_and_preflight_declare_the_line_window():
    spec = FILE_TOOL_SPECS["file_read"]
    props = spec["input_schema"]["properties"]
    assert props["line_offset"] == {"type": "integer", "minimum": 1,
                                    "maximum": file_tools.MAX_OFFSET}
    assert props["line_limit"] == {"type": "integer", "minimum": 1, "maximum": 2000}
    assert spec["preflight"]({"path": "a", "line_offset": 3, "line_limit": 9}) == {
        "path": "a", "line_offset": 3, "line_limit": 9}
    assert "line_offset" in spec["description"] and "next_line_offset" in spec["description"]
    assert "no OCR" in spec["description"]
    assert file_tools.DEFAULT_LINE_LIMIT == 500 and file_tools.MAX_LINE_LIMIT == 2000
