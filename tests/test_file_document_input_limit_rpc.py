"""The registered file reader reports the document input limit inside its result."""

import pytest

from agents.core import file_tools
from agents.core.file_tools import FileScope, FileTools, SnapshotStore, register_file_tools
from agents.core.tool_rpc import ToolRPCServer

LIMIT = 50_000_000
DETAIL = (
    "document extraction is limited to 50000000 bytes (50 MB); "
    "raw=true returns a bounded byte page"
)


@pytest.fixture
def registered(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"),
                      max_bytes=16)
    server = ToolRPCServer()
    assert register_file_tools(server, tools, enabled=True) == [
        "file_read", "file_list", "file_search", "file_write", "file_delete",
    ]
    return root, server


async def _read(server, **args):
    return await server.handle({"tool": "file_read", "args": args})


@pytest.mark.parametrize("name", ["large.pdf", "large.PDF", "large.docx", "large.DOCX"])
async def test_oversized_document_is_nested_refusal_before_parser_probe(
    registered, monkeypatch, name,
):
    root, server = registered
    path = root / name
    with path.open("wb") as handle:
        handle.truncate(LIMIT + 1)
    assert path.stat().st_size == LIMIT + 1
    parser_calls = []

    def parser_available(suffix):
        parser_calls.append(suffix)
        return False

    monkeypatch.setattr(file_tools, "_parser_available", parser_available)
    monkeypatch.setattr(file_tools, "extract_text",
                        lambda path: pytest.fail("oversized document must not be extracted"))
    monkeypatch.setattr(file_tools, "extract_pdf_pages",
                        lambda path: pytest.fail("oversized PDF must not be extracted"))
    response = await _read(server, path=name, offset=11)
    assert response["ok"] is True and response["tool"] == "file_read"
    assert "task_id" not in response
    assert response["result"] == {
        "ok": False,
        "reason": "document_too_large",
        "size": LIMIT + 1,
        "max_document_bytes": LIMIT,
        "detail": DETAIL,
    }, f"parser_calls={parser_calls}"
    assert parser_calls == []


async def test_exact_boundary_still_extracts_and_pages_utf8_text(registered, monkeypatch):
    root, server = registered
    path = root / "exact.PDF"
    with path.open("wb") as handle:
        handle.truncate(LIMIT)
    assert path.stat().st_size == LIMIT
    parser_calls = []
    extracted = []

    def parser_available(suffix):
        parser_calls.append(suffix)
        return True

    def extract(target):
        extracted.append(target)
        return ["alpha beta gamma"]

    monkeypatch.setattr(file_tools, "_parser_available", parser_available)
    monkeypatch.setattr(file_tools, "extract_pdf_pages", extract)
    response = await _read(server, path=path.name, offset=6, max_bytes=4)
    assert response["ok"] is True and response["tool"] == "file_read"
    result = response["result"]
    assert result["ok"] is True and result["extracted"] is True
    assert result["path"] == str(path) and result["format"] == "pdf"
    assert result["size"] == LIMIT and result["text_size"] == 16
    assert result["content"] == "beta" and result["bytes"] == 4
    assert result["offset"] == 6 and result["next_offset"] == 10
    assert result["truncated"] is True
    assert parser_calls == [".pdf"] and extracted == [path]


async def test_raw_oversized_document_and_plain_file_stay_bounded_pages(
    registered, monkeypatch,
):
    root, server = registered
    for name in ("large.docx", "large.txt"):
        path = root / name
        with path.open("wb") as handle:
            handle.truncate(LIMIT + 1)
            handle.seek(LIMIT - 3)
            handle.write(b"tail")
        assert path.stat().st_size == LIMIT + 1
    monkeypatch.setattr(file_tools, "_parser_available",
                        lambda suffix: pytest.fail("raw/plain read must not probe parser"))
    monkeypatch.setattr(file_tools, "extract_text",
                        lambda path: pytest.fail("raw/plain read must not extract"))
    monkeypatch.setattr(file_tools, "extract_pdf_pages",
                        lambda path: pytest.fail("raw/plain read must not extract PDF"))

    for name, raw in (("large.docx", True), ("large.txt", False)):
        first = (await _read(server, path=name, raw=raw, offset=LIMIT - 3,
                             max_bytes=2))["result"]
        assert first["ok"] is True and first["size"] == LIMIT + 1
        assert first["content"] == "ta" and first["bytes"] == 2
        assert first["offset"] == LIMIT - 3 and first["next_offset"] == LIMIT - 1
        assert first["truncated"] is True and "extracted" not in first
        last = (await _read(server, path=name, raw=raw, offset=LIMIT - 1,
                            max_bytes=16))["result"]
        assert last["content"] == "il" and last["bytes"] == 2
        assert last["truncated"] is False and "next_offset" not in last
        end = (await _read(server, path=name, raw=raw, offset=LIMIT + 1))["result"]
        assert end["ok"] is True and end["content"] == "" and end["bytes"] == 0
        assert end["truncated"] is False and "next_offset" not in end


async def test_preflight_and_existing_refusals_keep_their_envelope_and_precedence(
    registered, monkeypatch,
):
    root, server = registered
    small = root / "small.docx"
    small.write_bytes(b"placeholder")
    parser_calls = []

    def parser_available(suffix):
        parser_calls.append(suffix)
        return False

    monkeypatch.setattr(file_tools, "_parser_available", parser_available)
    for args, reason in (
        ({"path": "small.docx", "raw": "yes"}, "bad_flag"),
        ({"path": "small.docx", "offset": True}, "bad_offset"),
        ({"path": "../outside.pdf"}, "outside_scope"),
        ({"path": ".env"}, "secret_path"),
    ):
        response = await _read(server, **args)
        assert response == {"ok": False, "reason": reason, "tool": "file_read"}
    assert parser_calls == []
    missing = await _read(server, path="missing.pdf")
    directory = await _read(server, path=".")
    assert missing["ok"] is True and missing["result"] == {
        "ok": False, "reason": "not_found",
    }
    assert directory["ok"] is True and directory["result"] == {
        "ok": False, "reason": "not_a_file",
    }
    assert parser_calls == []
    smaller = await _read(server, path="small.docx")
    assert smaller["ok"] is True and smaller["result"]["ok"] is False
    assert smaller["result"]["reason"] == "parser_missing"
    assert "docx" in smaller["result"]["detail"] and parser_calls == [".docx"]
