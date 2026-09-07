"""Hermes absorption 4h — `file_read` reads a document, not a page of replacement characters.

A .pdf / .docx inside the roots comes back as its extracted text through the same optional
parsers the local-docs indexer uses; without the parser the refusal names it; `raw=true`
still returns the bytes. Same containment and the same byte cap as any other read.
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
)
from agents.core.tool_rpc import ToolRPCValidationError  # noqa: E402


@pytest.fixture
def tools(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "report.pdf").write_bytes(b"%PDF-1.4 binary \x00\x01 stuff")
    (root / "memo.docx").write_bytes(b"PK\x03\x04 zipped docx")
    (root / "notes.txt").write_text("plain notes", encoding="utf-8")
    return FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"), max_bytes=64)


@pytest.mark.asyncio
async def test_a_document_comes_back_as_bounded_text(tools, monkeypatch):
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: True)
    monkeypatch.setattr(file_tools, "extract_text", lambda path: "Quarterly report: " + "revenue up " * 20)
    out = await tools.read_file({"path": "report.pdf"})
    assert out["ok"] is True and out["extracted"] is True and out["format"] == "pdf"
    assert out["content"].startswith("Quarterly report: revenue up")
    assert out["bytes"] == 64 and out["truncated"] is True and len(out["sha256"]) == 64
    out = await tools.read_file({"path": "report.pdf", "max_bytes": 10})
    assert out["content"] == "Quarterly " and out["bytes"] == 10
    out = await tools.read_file({"path": "memo.docx"})
    assert out["format"] == "docx" and out["extracted"] is True


@pytest.mark.asyncio
async def test_missing_parser_and_failed_extraction_are_named(tools, monkeypatch):
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: False)
    out = await tools.read_file({"path": "report.pdf"})
    assert out["ok"] is False and out["reason"] == "parser_missing" and "pypdf" in out["detail"]
    out = await tools.read_file({"path": "memo.docx"})
    assert out["reason"] == "parser_missing" and "docx" in out["detail"]
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: True)
    monkeypatch.setattr(file_tools, "extract_text", lambda path: None)
    out = await tools.read_file({"path": "report.pdf"})
    assert out == {"ok": False, "reason": "extraction_failed", "detail": "the file could not be parsed"}


@pytest.mark.asyncio
async def test_raw_returns_the_bytes_and_text_files_are_untouched(tools, monkeypatch):
    monkeypatch.setattr(file_tools, "extract_text", lambda path: pytest.fail("must not extract"))
    out = await tools.read_file({"path": "report.pdf", "raw": True})
    assert out["ok"] is True and "extracted" not in out and out["content"].startswith("%PDF-1.4")
    out = await tools.read_file({"path": "notes.txt"})
    assert out["ok"] is True and out["content"] == "plain notes" and "extracted" not in out


def test_the_parser_check_reads_the_import_system(monkeypatch):
    assert file_tools._parser_available(".txt") is False
    assert isinstance(file_tools._parser_available(".pdf"), bool)


def test_preflight_accepts_raw_and_the_schema_declares_it():
    preflight = FILE_TOOL_SPECS["file_read"]["preflight"]
    assert preflight({"path": "a.pdf", "raw": True}) == {"path": "a.pdf", "raw": True}
    with pytest.raises(ToolRPCValidationError) as info:
        preflight({"path": "a.pdf", "raw": "yes"})
    assert info.value.reason == "bad_flag"
    assert FILE_TOOL_SPECS["file_read"]["input_schema"]["properties"]["raw"] == {"type": "boolean"}
    assert "docx" in FILE_TOOL_SPECS["file_read"]["description"]
