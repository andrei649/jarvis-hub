"""H661 — an oversized output is paged back from its spill file, not re-run.

Hermes' ``execute_code`` writes the whole stdout beside the truncation (capped at
5,000,000 bytes, then an explicit ``[... spill capped ...]`` marker) and puts the exact
re-read call in the result: "FULL output saved to {path} — page it with
read_file(path=…, offset=…)". Nerva already spilled (H298 for a whole tool result,
H305/H595 for a sandboxed stream). What these tests pin is the part that closes the
loop, and each one was missing:

* ``file_read`` could only start at byte 0, so everything past the first page of a
  spill was unreachable and the notices' "whole or in parts" had nothing behind it;
* no notice carried a call the model could copy — the path, the offset and the page
  size, filled in;
* a stream spill had no ceiling, so a runaway child filled the spill until timeout,
  with no marker in the file and no flag in the result.

The end-to-end test at the bottom is the one the row is about: the model gets a
spilled result, follows the recipe page by page, and recovers every byte without the
tool running a second time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agents.core import file_tools
from agents.core import tool_result_store as trs
from agents.core.file_tools import (
    FILE_TOOL_SPECS,
    FileScope,
    FileTools,
    SnapshotStore,
    register_file_tools,
)
from agents.core.tool_result_store import ToolResultStore, preview_envelope
from agents.core.tool_rpc import ToolRPCServer, ToolRPCValidationError


def _tools(root: Path, tmp_path: Path, *, max_bytes: int = 1_000) -> FileTools:
    return FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"),
                     max_bytes=max_bytes)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


async def _page_through(read, path: str, *, max_bytes: int) -> tuple[list[dict], str]:
    """Follow ``next_offset`` from 0 until it is absent, the way the notice says."""
    pages: list[dict] = []
    args = {"path": path, "offset": 0, "max_bytes": max_bytes}
    while True:
        page = await read(dict(args))
        assert page["ok"] is True, page
        pages.append(page)
        if "next_offset" not in page:
            break
        assert page["next_offset"] > args["offset"], "a page must always make progress"
        args["offset"] = page["next_offset"]
        assert len(pages) < 10_000
    return pages, "".join(page["content"] for page in pages)


# ── file_read can start anywhere ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_offset_returns_the_middle_page_and_names_the_next_one(tmp_path):
    root = _workspace(tmp_path)
    (root / "three.txt").write_bytes(b"A" * 100 + b"B" * 100 + b"C" * 100)
    tools = _tools(root, tmp_path)

    middle = await tools.read_file({"path": "three.txt", "offset": 100, "max_bytes": 100})

    assert middle["ok"] is True and middle["content"] == "B" * 100
    assert middle["offset"] == 100 and middle["bytes"] == 100 and middle["size"] == 300
    assert middle["truncated"] is True and middle["next_offset"] == 200
    assert middle["sha256"] == hashlib.sha256(b"B" * 100).hexdigest()

    last = await tools.read_file({"path": "three.txt", "offset": 200, "max_bytes": 100})
    assert last["content"] == "C" * 100 and last["truncated"] is False
    assert "next_offset" not in last, "the last page has no next page to name"

    first = await tools.read_file({"path": "three.txt", "max_bytes": 100})
    assert first["offset"] == 0 and first["next_offset"] == 100, \
        "a plain truncated read says where to continue too"


@pytest.mark.asyncio
async def test_an_offset_past_the_end_is_an_empty_final_page(tmp_path):
    root = _workspace(tmp_path)
    (root / "short.txt").write_bytes(b"abc")
    out = await _tools(root, tmp_path).read_file({"path": "short.txt", "offset": 50})
    assert out["ok"] is True and out["content"] == "" and out["bytes"] == 0
    assert out["truncated"] is False and "next_offset" not in out and out["size"] == 3


@pytest.mark.asyncio
async def test_following_next_offset_rebuilds_the_file_exactly_across_multibyte_characters(
        tmp_path):
    """A byte page can end inside a character. The page stops before it instead.

    Without that, a split character is a replacement mark at the end of one page and
    another at the start of the next — the model reassembles a corrupted text from a
    file that was never corrupted.
    """
    root = _workspace(tmp_path)
    text = "ăîșțâ €uro 𝄞 clef — " * 40
    (root / "ro.txt").write_text(text, encoding="utf-8")
    tools = _tools(root, tmp_path)

    pages, rebuilt = await _page_through(tools.read_file, "ro.txt", max_bytes=7)

    assert rebuilt == text
    assert all("\ufffd" not in page["content"] for page in pages)
    assert sum(page["bytes"] for page in pages) == len(text.encode("utf-8"))


@pytest.mark.asyncio
async def test_a_page_smaller_than_one_character_still_makes_progress(tmp_path):
    root = _workspace(tmp_path)
    (root / "clef.txt").write_text("𝄞𝄞", encoding="utf-8")
    pages, _rebuilt = await _page_through(_tools(root, tmp_path).read_file, "clef.txt",
                                          max_bytes=1)
    assert sum(page["bytes"] for page in pages) == 8


@pytest.mark.asyncio
async def test_a_document_pages_through_its_extracted_text(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    (root / "report.pdf").write_bytes(b"%PDF-1.4 not really")
    text = "Quarterly report: " + "revenue up, costs down; " * 30
    monkeypatch.setattr(file_tools, "_parser_available", lambda suffix: True)
    monkeypatch.setattr(file_tools, "extract_text", lambda path: text)
    tools = _tools(root, tmp_path)

    second = await tools.read_file({"path": "report.pdf", "offset": 18, "max_bytes": 12})
    assert second["extracted"] is True and second["content"] == "revenue up, "
    assert second["offset"] == 18 and second["next_offset"] == 30

    _pages, rebuilt = await _page_through(tools.read_file, "report.pdf", max_bytes=50)
    assert rebuilt == text


def test_the_schema_declares_offset_and_the_preflight_keeps_it():
    spec = FILE_TOOL_SPECS["file_read"]
    assert spec["input_schema"]["properties"]["offset"] == {"type": "integer", "minimum": 0}
    assert "offset" in spec["description"] and "next_offset" in spec["description"]
    assert spec["preflight"]({"path": "x", "offset": 0}) == {"path": "x", "offset": 0}
    assert spec["preflight"]({"path": "x", "offset": 7})["offset"] == 7


@pytest.mark.parametrize("bad", [True, False, -1, 1.5, "10", None])
def test_a_bad_offset_is_refused_by_the_preflight(bad):
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_read"]["preflight"]({"path": "x", "offset": bad})
    assert info.value.reason == "bad_offset"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [True, -1, 1.5, "10"])
async def test_a_direct_caller_with_a_bad_offset_is_refused_not_read_from_zero(tmp_path, bad):
    """Silently reading from 0 would hand back the first page labelled as the one asked for."""
    root = _workspace(tmp_path)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    out = await _tools(root, tmp_path).read_file({"path": "a.txt", "offset": bad})
    assert out == {"ok": False, "reason": "bad_offset"}


@pytest.mark.asyncio
async def test_the_offset_reaches_the_handler_through_the_tool_rpc_server(tmp_path):
    root = _workspace(tmp_path)
    (root / "three.txt").write_bytes(b"A" * 100 + b"B" * 100 + b"C" * 100)
    server = ToolRPCServer()
    assert "file_read" in register_file_tools(server, _tools(root, tmp_path), enabled=True)

    reply = await server.handle({"tool": "file_read",
                                 "args": {"path": "three.txt", "offset": 100, "max_bytes": 100}})

    assert reply["ok"] is True
    assert reply["result"]["content"] == "B" * 100 and reply["result"]["next_offset"] == 200
    refused = await server.handle({"tool": "file_read", "args": {"path": "three.txt", "offset": -5}})
    assert refused["ok"] is False and refused["reason"] == "bad_offset"


# ── a stream spill has a ceiling, and says when it hit it ────────────────────

def test_the_default_stream_ceiling_is_five_million_bytes():
    assert trs.DEFAULT_MAX_STREAM_BYTES == 5_000_000
    assert ToolResultStore().max_stream_bytes == 5_000_000


def test_a_runaway_stream_stops_at_the_ceiling_with_one_marker(tmp_path):
    store = ToolResultStore(tmp_path / "spills")
    spill = store.open_stream(tool="execute-code-stdout")
    chunk = b"r" * 65_536
    total = 0
    while total < 6_000_000:
        spill.write(chunk)
        total += len(chunk)

    landed = spill.close()

    raw = Path(landed.path).read_bytes()
    assert landed.capped is True
    assert raw[:5_000_000] == b"r" * 5_000_000, "the head is kept byte for byte"
    marker = raw[5_000_000:]
    assert marker.count(b"[... spill capped") == 1 and marker.endswith(b"...]\n")
    assert b"5000000" in marker and str(total - 5_000_000).encode() in marker
    assert landed.original_bytes == total, "what the stream produced, not what was kept"
    assert landed.stored_bytes == len(raw) and spill.written_bytes == total
    assert landed.sha256 == hashlib.sha256(raw).hexdigest(), "the digest names the file"
    assert landed.as_dict()["capped"] is True


def test_a_chunk_straddling_the_ceiling_keeps_its_head(tmp_path):
    store = ToolResultStore(tmp_path / "spills", max_stream_bytes=10)
    spill = store.open_stream(tool="echo")
    spill.write(b"x" * 7)
    spill.write(b"y" * 7)
    spill.write(b"z" * 7)

    landed = spill.close()

    raw = Path(landed.path).read_bytes()
    assert raw.startswith(b"x" * 7 + b"yyy\n[... spill capped at 10 bytes")
    assert landed.capped is True and landed.original_bytes == 21


def test_a_stream_exactly_at_the_ceiling_is_complete_and_unmarked(tmp_path):
    store = ToolResultStore(tmp_path / "spills", max_stream_bytes=10)
    spill = store.open_stream(tool="echo")
    spill.write(b"0123456789")
    landed = spill.close()
    assert Path(landed.path).read_bytes() == b"0123456789"
    assert landed.capped is False and landed.original_bytes == landed.stored_bytes == 10


# ── the result carries the exact call ────────────────────────────────────────

def test_the_recipe_is_the_exact_call_with_the_path_filled_in():
    path = 'C:\\spills\\a "quoted" name.txt'
    recipe = trs.page_recipe(path, page_bytes=4_000)
    assert recipe["tool"] == "file_read"
    assert recipe["arguments"] == {"path": path, "offset": 0, "max_bytes": 4_000}
    assert recipe["call"] == f"file_read(path={json.dumps(path)}, offset=0, max_bytes=4000)"


def test_the_preview_names_the_exact_read_call(tmp_path):
    store = ToolResultStore(tmp_path / "spills")
    body = json.dumps({"ok": True, "filler": "y" * 40_000})
    spill = store.spill(body, tool="web_extract")

    envelope = json.loads(preview_envelope(body, tool="web_extract", ok=True,
                                           reason=None, spill=spill))

    expected = trs.page_recipe(spill.path, page_bytes=trs.DEFAULT_PAGE_BYTES)
    assert envelope["read_with"] == {"tool": expected["tool"], "arguments": expected["arguments"]}
    assert expected["call"] in envelope["notice"]
    assert "next_offset" in envelope["notice"]
    assert "whole or in parts" not in envelope["notice"]


def test_a_host_without_file_read_is_told_so_instead_of_handed_a_dead_call(tmp_path):
    store = ToolResultStore(tmp_path / "spills", read_back=lambda: False)
    body = json.dumps({"ok": True, "filler": "y" * 40_000})
    spill = store.spill(body, tool="web_extract")

    envelope = json.loads(preview_envelope(body, tool="web_extract", ok=True,
                                           reason=None, spill=spill))

    assert spill.readable is False
    assert "read_with" not in envelope
    assert envelope["result_file"] == spill.path, "the file is still named for the owner"
    assert "file_read is not available" in envelope["notice"]


@pytest.mark.parametrize("file_tools_on", [True, False])
def test_the_coordinator_names_file_read_only_while_the_registry_has_it(
        tmp_path, monkeypatch, file_tools_on):
    """`file_read` is behind JARVIS_FILE_TOOLS. The live store asks the live registry."""
    from types import SimpleNamespace

    from agents.core.autonomy_coordinator import AutonomyCoordinator

    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path))
    if file_tools_on:
        monkeypatch.setenv("JARVIS_FILE_TOOLS", "1")
    else:
        monkeypatch.delenv("JARVIS_FILE_TOOLS", raising=False)
    orch = SimpleNamespace(agents={})

    runtime = AutonomyCoordinator(orch)._wire_agent_tool_runtime()

    assert orch.tool_rpc.allows("file_read") is file_tools_on
    assert runtime._result_store.readable() is file_tools_on


def test_a_read_back_probe_that_raises_counts_as_unavailable(tmp_path):
    def broken():
        raise RuntimeError("registry gone")

    store = ToolResultStore(tmp_path / "spills", read_back=broken)
    assert store.spill("x" * 100, tool="echo").readable is False
    stream = store.open_stream(tool="echo")
    stream.write(b"abc")
    assert stream.close().readable is False


# ── the loop the row is about ────────────────────────────────────────────────

class _PagingBackend:
    """Calls ``blob`` once, then does exactly what the result tells it to."""

    supports_tools = True

    def __init__(self) -> None:
        self.pages: list[str] = []
        self.turns = 0

    async def generate_tool_turn(self, **kwargs):
        from agents.core.llm.tool_protocol import ToolTurn

        self.turns += 1
        tool_messages = [m for m in kwargs["messages"] if m.get("role") == "tool"]
        if not tool_messages:
            return self._call("blob", {"n": 1})
        last = json.loads(tool_messages[-1]["content"])
        if last.get("spilled"):
            recipe = last["read_with"]
            return self._call(recipe["tool"], recipe["arguments"])
        page = last["result"]
        self.pages.append(page["content"])
        if "next_offset" in page:
            return self._call("file_read", {"path": page["path"], "offset": page["next_offset"],
                                            "max_bytes": trs.DEFAULT_PAGE_BYTES})
        return ToolTurn(content="done", finish_reason="stop")

    def _call(self, name: str, arguments: dict):
        from agents.core.llm.tool_protocol import ToolCall, ToolTurn

        return ToolTurn(
            tool_calls=(ToolCall(id=f"call-{self.turns}", name=name,
                                 raw_arguments=json.dumps(arguments), arguments=arguments),),
            finish_reason="tool_calls",
        )


@pytest.mark.asyncio
async def test_the_loop_pages_a_spilled_result_back_without_running_the_tool_again(
        tmp_path, monkeypatch):
    from agents.core import agent_runtime
    from agents.core.agent_runtime import AgentToolRuntime

    monkeypatch.setattr(
        agent_runtime, "estimate_messages",
        lambda messages: sum(len(str(m.get("content", ""))) for m in messages) // 4)
    spill_root = tmp_path / "spills"
    store = ToolResultStore(spill_root)
    server = ToolRPCServer()
    runs = []

    async def blob(args):
        runs.append(args)
        return {"blob": "".join(f"row-{i:05d};" for i in range(4_000)), "n": args.get("n")}

    server.register_tool("blob", blob, description="Return a large payload.",
                         input_schema={"type": "object",
                                       "properties": {"n": {"type": "integer"}}})
    spill_root.mkdir()
    register_file_tools(server, _tools(spill_root, tmp_path, max_bytes=2_000_000),
                        enabled=True)
    backend = _PagingBackend()
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_result_bytes=5_000,
                               max_iterations=lambda: 40, result_store=store)

    answer = await runtime.run(agent_id="nerva", backend=backend, model="local-model",
                               prompt="fetch a lot", system="You are Nerva.",
                               max_tokens=256, temperature=0.2)

    assert answer == "done"
    assert len(runs) == 1, "the expensive tool ran once; the rest came from the file"
    assert len(backend.pages) > 1, "it really was paged, not read whole"
    [spilled] = list(spill_root.glob("blob-*.json"))
    rebuilt = "".join(backend.pages)
    assert rebuilt == spilled.read_text(encoding="utf-8")
    assert json.loads(rebuilt)["result"]["blob"].endswith("row-03999;")
