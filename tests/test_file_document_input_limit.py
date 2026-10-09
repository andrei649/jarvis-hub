"""H444: parser-backed reads admit at most 50,000,000 observed input bytes."""

from pathlib import Path

import pytest

from agents.core import file_tools
from agents.core.file_tools import FileScope, FileTools

CEILING = 50_000_000  # Contract boundary, deliberately independent of source constant.
DETAIL = (
    "document extraction is limited to 50000000 bytes (50 MB); "
    "raw=true returns a bounded byte page"
)


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / "workspace"
    directory.mkdir()
    return directory


def tools(root):
    return FileTools(FileScope([root]), max_bytes=32)


def sparse(path, size):
    with path.open("wb") as stream:
        stream.truncate(size)
    assert path.stat().st_size == size
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize("name,offset", [
    ("oversize.pdf", 0),
    ("OVERSIZE.PDF", 17),
    ("oversize.docx", 0),
    ("OVERSIZE.DOCX", 17),
])
async def test_oversized_documents_refuse_before_parser_probe_or_extraction(
    root, monkeypatch, name, offset,
):
    target = sparse(root / name, CEILING + 1)
    calls = []

    def available(suffix):
        calls.append(("probe", suffix))
        return True

    def extract(path):
        calls.append(("extract", path))
        return "extracted text"

    monkeypatch.setattr(file_tools, "_parser_available", available)
    monkeypatch.setattr(file_tools, "extract_text", extract)
    result = await tools(root).read_file({"path": name, "offset": offset, "max_bytes": 5})
    assert target.stat().st_size == CEILING + 1
    assert calls == [], f"oversized parser path was reached: {calls!r}"
    assert result == {
        "ok": False, "reason": "document_too_large", "size": CEILING + 1,
        "max_document_bytes": CEILING, "detail": DETAIL,
    }


@pytest.mark.asyncio
async def test_oversized_document_refuses_even_when_parser_is_unavailable(root, monkeypatch):
    target = sparse(root / "unavailable.pdf", CEILING + 1)
    calls = []

    def unavailable(suffix):
        calls.append(suffix)
        return False

    monkeypatch.setattr(file_tools, "_parser_available", unavailable)
    monkeypatch.setattr(file_tools, "extract_text", lambda path: pytest.fail("extract called"))
    result = await tools(root).read_file({"path": target.name})
    assert target.stat().st_size == CEILING + 1
    assert calls == [], f"oversized parser discovery was reached: {calls!r}"
    assert result == {
        "ok": False, "reason": "document_too_large", "size": CEILING + 1,
        "max_document_bytes": CEILING, "detail": DETAIL,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("name,size", [
    ("EXACT.PDF", CEILING),
    ("EXACT.DOCX", CEILING),
    ("below.PDF", CEILING - 1),
    ("below.docx", CEILING - 1),
])
async def test_equal_and_below_limit_keep_extracted_utf8_paging(
    root, monkeypatch, name, size,
):
    target = sparse(root / name, size)
    calls = []

    def available(suffix):
        calls.append(("probe", suffix))
        return True

    def extract(path):
        calls.append(("extract", path))
        return "Café text"

    monkeypatch.setattr(file_tools, "_parser_available", available)
    monkeypatch.setattr(file_tools, "extract_text", extract)
    result = await tools(root).read_file({"path": name, "max_bytes": 5})
    assert target.stat().st_size == size
    assert calls == [("probe", target.suffix.lower()), ("extract", target)]
    assert result["ok"] is True and result["extracted"] is True
    assert result["content"] == "Café" and result["bytes"] == 5
    assert result["size"] == size and result["text_size"] == 10
    assert result["truncated"] is True and result["next_offset"] == 5
    second = await tools(root).read_file({"path": name, "offset": 5, "max_bytes": 5})
    assert second["content"] == " text" and second["offset"] == 5
    assert second["truncated"] is False and "next_offset" not in second


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["raw.pdf", "plain.txt"])
async def test_large_raw_document_and_plain_file_still_page_bytes_near_eof(
    root, monkeypatch, name,
):
    size = CEILING + 3
    target = sparse(root / name, size)
    with target.open("r+b") as stream:
        stream.seek(size - 3)
        stream.write(b"END")
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: pytest.fail("probe"))
    monkeypatch.setattr(file_tools, "extract_text", lambda path: pytest.fail("extract"))
    args = {"path": name, "offset": size - 3, "max_bytes": 2}
    if name.endswith(".pdf"):
        args["raw"] = True
    reader = tools(root)
    first = await reader.read_file(args)
    assert target.stat().st_size == size
    assert first["ok"] is True and first["content"] == "EN"
    assert first["size"] == size and first["bytes"] == 2
    assert first["next_offset"] == size - 1
    last = await reader.read_file({**args, "offset": first["next_offset"]})
    assert last["content"] == "D" and last["truncated"] is False
    assert "next_offset" not in last
    past = await reader.read_file({**args, "offset": size + 2})
    assert past["ok"] is True and past["content"] == ""
    assert past["bytes"] == 0 and past["truncated"] is False


@pytest.mark.asyncio
async def test_smaller_document_keeps_named_parser_and_extraction_failures(root, monkeypatch):
    target = sparse(root / "small.pdf", CEILING - 1)
    calls = []

    def missing(suffix):
        calls.append(suffix)
        return False

    monkeypatch.setattr(file_tools, "_parser_available", missing)
    first = await tools(root).read_file({"path": target.name})
    assert target.stat().st_size == CEILING - 1 and calls == [".pdf"]
    assert first == {
        "ok": False, "reason": "parser_missing",
        "detail": "reading .pdf needs the pypdf package; raw=true returns the bytes",
    }

    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: True)
    monkeypatch.setattr(file_tools, "extract_text", lambda path: None)
    second = await tools(root).read_file({"path": target.name})
    assert second == {
        "ok": False, "reason": "extraction_failed",
        "detail": "the file could not be parsed",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("path,offset,reason", [
    ("large.pdf", True, "bad_offset"),
    ("../outside.pdf", 0, "outside_scope"),
    (".env.pdf", 0, "secret_path"),
    ("missing.pdf", 0, "not_found"),
    ("directory.pdf", 0, "not_a_file"),
])
async def test_existing_input_refusals_precede_document_guard(root, monkeypatch, path, offset, reason):
    sparse(root / "large.pdf", CEILING + 1)
    (root / "directory.pdf").mkdir()
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: pytest.fail("probe"))
    result = await tools(root).read_file({"path": path, "offset": offset})
    assert result["ok"] is False and result["reason"] == reason
    assert "max_document_bytes" not in result


@pytest.mark.asyncio
async def test_stat_error_stays_io_error_before_parser_guard(root, monkeypatch):
    target = sparse(root / "large.pdf", CEILING + 1)
    original_stat = Path.stat
    calls = 0

    def fail_size_stat(path, *args, **kwargs):
        nonlocal calls
        if path == target:
            calls += 1
            if calls == 3:
                raise OSError("stat failed")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_size_stat)
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: pytest.fail("probe"))
    result = await tools(root).read_file({"path": target.name})
    assert calls >= 3
    assert result == {"ok": False, "reason": "io_error", "detail": "OSError"}
