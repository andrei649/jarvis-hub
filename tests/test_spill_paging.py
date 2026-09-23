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
from agents.core.security.quarantine import split_fenced_tool_result
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
    assert spec["input_schema"]["properties"]["offset"] == {
        "type": "integer", "minimum": 0, "maximum": file_tools.MAX_OFFSET}
    assert "offset" in spec["description"] and "next_offset" in spec["description"]
    assert spec["preflight"]({"path": "x", "offset": 0}) == {"path": "x", "offset": 0}
    assert spec["preflight"]({"path": "x", "offset": 7})["offset"] == 7
    top = file_tools.MAX_OFFSET
    assert spec["preflight"]({"path": "x", "offset": top})["offset"] == top


#: Offsets no file has: past the ceiling every JSON reader holds exactly, past what a
#: seek can express (2**63), and absurd. Each one used to escape as a ValueError from
#: ``seek`` (a ``tool_error`` with a traceback) or an ``io_error`` from the kernel.
_ABSURD_OFFSETS = [2**63 - 1, 2**63, 10**30]


@pytest.mark.parametrize("bad", [True, False, -1, 1.5, "10", None, *_ABSURD_OFFSETS])
def test_a_bad_offset_is_refused_by_the_preflight(bad):
    with pytest.raises(ToolRPCValidationError) as info:
        FILE_TOOL_SPECS["file_read"]["preflight"]({"path": "x", "offset": bad})
    assert info.value.reason == "bad_offset"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [True, -1, 1.5, "10", *_ABSURD_OFFSETS])
async def test_a_direct_caller_with_a_bad_offset_is_refused_not_read_from_zero(tmp_path, bad):
    """Silently reading from 0 would hand back the first page labelled as the one asked for."""
    root = _workspace(tmp_path)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    out = await _tools(root, tmp_path).read_file({"path": "a.txt", "offset": bad})
    assert out == {"ok": False, "reason": "bad_offset"}


@pytest.mark.asyncio
@pytest.mark.parametrize("huge", _ABSURD_OFFSETS)
async def test_an_absurd_offset_through_the_server_is_a_named_refusal(tmp_path, huge):
    root = _workspace(tmp_path)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    server = ToolRPCServer()
    register_file_tools(server, _tools(root, tmp_path), enabled=True)

    reply = await server.handle({"tool": "file_read", "args": {"path": "a.txt", "offset": huge}})

    assert reply["ok"] is False and reply["reason"] == "bad_offset"


@pytest.mark.asyncio
async def test_the_largest_offset_is_an_empty_final_page_not_an_io_error(tmp_path):
    """Past the end is answered without seeking there: the kernel's own file-size limit
    (EINVAL on ext4 far below 2**63) is not the reader's business."""
    root = _workspace(tmp_path)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    out = await _tools(root, tmp_path).read_file({"path": "a.txt",
                                                  "offset": file_tools.MAX_OFFSET})
    assert out["ok"] is True and out["content"] == "" and out["bytes"] == 0
    assert out["offset"] == file_tools.MAX_OFFSET and "next_offset" not in out


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
    store = ToolResultStore(tmp_path / "spills", read_back=lambda path: False)
    body = json.dumps({"ok": True, "filler": "y" * 40_000})
    spill = store.spill(body, tool="web_extract")

    envelope = json.loads(preview_envelope(body, tool="web_extract", ok=True,
                                           reason=None, spill=spill))

    assert spill.readable is False
    assert "read_with" not in envelope
    assert envelope["result_file"] == spill.path, "the file is still named for the owner"
    assert "file_read is not available" in envelope["notice"]


def test_the_probe_is_asked_about_the_very_path_the_recipe_names(tmp_path):
    """Reach is a property of one path, not of a registry: the probe gets the path."""
    asked: list[str] = []

    def probe(path):
        asked.append(path)
        return True

    store = ToolResultStore(tmp_path / "spills", read_back=probe)
    spill = store.spill("x" * 100, tool="echo")
    stream = store.open_stream(tool="echo")
    stream.write(b"abc")
    landed = stream.close()

    assert asked == [spill.path, landed.path]


def test_a_spill_under_a_symlinked_root_names_the_real_path(tmp_path):
    """The file tools check a path lexically against *resolved* roots, so a recipe that
    carries the symlinked spelling is refused even though it names the same file."""
    real = tmp_path / "real_spills"
    real.mkdir()
    link = tmp_path / "spills_link"
    link.symlink_to(real, target_is_directory=True)
    store = ToolResultStore(link)

    spill = store.spill("x" * 100, tool="echo")
    stream = store.open_stream(tool="echo")
    stream.write(b"abc")
    landed = stream.close()

    assert spill.path == str(real.resolve() / spill.reference)
    assert landed.path == str(real.resolve() / landed.reference)


@pytest.mark.parametrize("tool", [
    "mcp__stripe__list_webhook_endpoints", "rotate_api_key", "id_rsa_lookup",
    "mcp__vault__read_secret", "refresh-token", "AUTH",
])
def test_a_spill_is_never_named_like_a_secret(tmp_path, tool):
    """file_read refuses a secret-looking *name* anywhere inside the roots. A spill is
    Nerva's own file; naming it after a tool called `…webhook…` must not lock it."""
    store = ToolResultStore(tmp_path / "spills")
    spill = store.spill("x" * 100, tool=tool)
    stream = store.open_stream(tool=tool)
    stream.write(b"abc")
    landed = stream.close()

    assert not file_tools.looks_secret_name(spill.reference)
    assert not file_tools.looks_secret_name(landed.reference)
    assert trs.is_reference(spill.reference) and trs.is_reference(landed.reference)


def test_an_ordinary_tool_keeps_its_name_on_the_spill(tmp_path):
    spill = ToolResultStore(tmp_path / "spills").spill("x" * 100, tool="web_extract")
    assert spill.reference.startswith("web_extract-")


def test_a_read_back_probe_that_raises_counts_as_unavailable(tmp_path):
    def broken(path):
        raise RuntimeError("registry gone")

    store = ToolResultStore(tmp_path / "spills", read_back=broken)
    assert store.spill("x" * 100, tool="echo").readable is False
    stream = store.open_stream(tool="echo")
    stream.write(b"abc")
    assert stream.close().readable is False


# ── file_read reaches Nerva's own spills, and nothing else new ───────────────

def _spill_reader(tmp_path: Path) -> tuple[FileTools, Path, Path]:
    projects = tmp_path / "projects"
    projects.mkdir()
    spills = tmp_path / "spills"
    spills.mkdir()
    tools = FileTools(FileScope([projects]), snapshots=SnapshotStore(tmp_path / "snaps"),
                      max_bytes=1_000, spill_dirs=[spills])
    return tools, projects, spills


@pytest.mark.asyncio
async def test_file_read_opens_a_spill_outside_the_owner_roots_by_its_exact_path(tmp_path):
    """JARVIS_FILE_ROOTS replaces the default root, and with it the spill directory.
    The owner narrowed the *workspace*; a spill is the turn's own output, named in the
    turn's own result, so its exact path stays readable — read-only, name by name."""
    tools, _projects, spills = _spill_reader(tmp_path)
    spill = ToolResultStore(spills).spill("z" * 2_500, tool="web_extract")

    pages, rebuilt = await _page_through(tools.read_file, spill.path, max_bytes=1_000)

    assert rebuilt == "z" * 2_500 and len(pages) == 3
    assert tools.reaches(spill.path) is True


@pytest.mark.asyncio
async def test_the_spill_door_admits_nothing_but_a_spill_file(tmp_path):
    tools, projects, spills = _spill_reader(tmp_path)
    (spills / "notes.md").write_text("owner notes", encoding="utf-8")
    (spills / "sub").mkdir()
    (spills / "sub" / "web_extract-0123456789abcdef.json").write_text("{}", encoding="utf-8")
    secret = tmp_path / "api_key.txt"
    secret.write_text("sk-live", encoding="utf-8")
    (spills / "echo-fedcba9876543210.txt").symlink_to(secret)
    ToolResultStore(spills).spill("z" * 100, tool="echo")

    for path in (
        str(spills / "notes.md"),                                   # not a spill name
        str(spills / "sub" / "web_extract-0123456789abcdef.json"),  # not directly inside
        str(spills / "echo-fedcba9876543210.txt"),                  # a symlink out
        "spills/echo-fedcba9876543210.txt",                         # relative
        str(spills / ".." / "api_key.txt"),                         # traversal
    ):
        out = await tools.read_file({"path": path})
        assert out["ok"] is False, path
        assert tools.reaches(path) is False, path
    listing = await tools.list_dir({"path": str(spills)})
    assert listing == {"ok": False, "reason": "outside_scope"}, "read by name, never listed"
    search = await tools.search_files({"pattern": "z", "path": str(spills)})
    assert search["ok"] is False
    with pytest.raises(ToolRPCValidationError):
        tools.preflight("file_write")({"path": str(next(spills.glob("echo-*.json"))),
                                       "content": "x"})


@pytest.mark.asyncio
async def test_without_a_spill_directory_the_scope_is_unchanged(tmp_path):
    tools = _tools(_workspace(tmp_path), tmp_path)
    spill = ToolResultStore(tmp_path / "spills").spill("z" * 100, tool="echo")
    assert (await tools.read_file({"path": spill.path})) == {"ok": False,
                                                             "reason": "outside_scope"}
    assert tools.reaches(spill.path) is False


# ── the coordinator: the store and the reader it wires must agree ────────────

def _wire_coordinator(monkeypatch, *, home: Path, roots: Path | None,
                      file_tools_on: bool = True, agents: dict | None = None):
    from types import SimpleNamespace

    from agents.core.autonomy_coordinator import AutonomyCoordinator

    monkeypatch.setenv("JARVIS_HOME", str(home))
    if roots is None:
        monkeypatch.delenv("JARVIS_FILE_ROOTS", raising=False)
    else:
        monkeypatch.setenv("JARVIS_FILE_ROOTS", str(roots))
    if file_tools_on:
        monkeypatch.setenv("JARVIS_FILE_TOOLS", "1")
    else:
        monkeypatch.delenv("JARVIS_FILE_TOOLS", raising=False)
    orch = SimpleNamespace(agents={}, config=SimpleNamespace(agents=agents or {}))
    runtime = AutonomyCoordinator(orch)._wire_agent_tool_runtime()
    return orch, runtime


async def _follow(handle, read_with: dict) -> str:
    """Make the call the result names, then each next_offset, through the live server."""
    args = dict(read_with["arguments"])
    pages: list[str] = []
    while True:
        reply = await handle({"tool": read_with["tool"], "args": dict(args)})
        assert reply["ok"] is True, reply
        page = reply["result"]
        pages.append(page["content"])
        if "next_offset" not in page:
            return "".join(pages)
        args["offset"] = page["next_offset"]
        assert len(pages) < 1_000


_BODY = json.dumps({"ok": True, "rows": "".join(f"row-{i:05d};" for i in range(4_000))})


@pytest.mark.parametrize("file_tools_on", [True, False])
def test_the_coordinator_names_file_read_only_while_the_registry_has_it(
        tmp_path, monkeypatch, file_tools_on):
    """`file_read` is behind JARVIS_FILE_TOOLS. The live store asks the live registry."""
    orch, runtime = _wire_coordinator(monkeypatch, home=tmp_path / "home", roots=None,
                                      file_tools_on=file_tools_on)

    spill = runtime._result_store.spill(_BODY, tool="web_extract")

    assert orch.tool_rpc.allows("file_read") is file_tools_on
    assert spill.readable is file_tools_on


@pytest.mark.asyncio
@pytest.mark.parametrize("setup", ["default_roots", "owner_roots_elsewhere", "symlinked_home"])
async def test_the_coordinator_recipe_is_followed_to_the_last_byte(tmp_path, monkeypatch, setup):
    """The review's three live setups, joined end to end: the coordinator's store spills,
    its envelope names a call, and the coordinator's own file_read answers that call.

    ``owner_roots_elsewhere`` is the documented owner setup (a workspace under
    JARVIS_FILE_ROOTS), which replaces the default root the spill directory lives in;
    ``symlinked_home`` puts the data root behind a symlink the scope resolves away.
    """
    home, roots = tmp_path / "home", None
    if setup == "owner_roots_elsewhere":
        roots = tmp_path / "projects"
        roots.mkdir()
    elif setup == "symlinked_home":
        real = tmp_path / "real_home"
        real.mkdir()
        home = tmp_path / "home_link"
        home.symlink_to(real, target_is_directory=True)
    orch, runtime = _wire_coordinator(monkeypatch, home=home, roots=roots)

    spill = runtime._result_store.spill(_BODY, tool="web_extract")
    envelope = json.loads(preview_envelope(_BODY, tool="web_extract", ok=True, reason=None,
                                           spill=spill))

    assert "read_with" in envelope, envelope["notice"]
    assert await _follow(orch.tool_rpc.handle, envelope["read_with"]) == _BODY


@pytest.mark.asyncio
async def test_a_bridged_tool_with_a_secret_looking_name_can_be_paged_back(tmp_path, monkeypatch):
    orch, runtime = _wire_coordinator(monkeypatch, home=tmp_path / "home", roots=None)
    tool = "mcp__stripe__list_webhook_endpoints"

    spill = runtime._result_store.spill(_BODY, tool=tool)
    envelope = json.loads(preview_envelope(_BODY, tool=tool, ok=True, reason=None, spill=spill))

    assert await _follow(orch.tool_rpc.handle, envelope["read_with"]) == _BODY


def test_the_coordinator_probe_checks_reach_per_path_not_registration(tmp_path, monkeypatch):
    """Registered is not reachable. A store whose files file_read cannot open — here one
    rooted outside both the owner's roots and the spill directory — names no call."""
    _orch, runtime = _wire_coordinator(monkeypatch, home=tmp_path / "home",
                                       roots=tmp_path / "projects")
    (tmp_path / "projects").mkdir()
    probe = runtime._result_store._read_back
    stray = ToolResultStore(tmp_path / "elsewhere", read_back=probe)

    spill = stray.spill(_BODY, tool="web_extract")
    envelope = json.loads(preview_envelope(_BODY, tool="web_extract", ok=True, reason=None,
                                           spill=spill))

    assert spill.readable is False
    assert "read_with" not in envelope
    assert "cannot be paged" in envelope["notice"] or "not available" in envelope["notice"]


class _OneSpillBackend:
    """Calls ``blob`` once and keeps what came back."""

    supports_tools = True

    def __init__(self) -> None:
        self.seen: list[dict] = []

    async def generate_tool_turn(self, **kwargs):
        from agents.core.llm.tool_protocol import ToolCall, ToolTurn

        tool_messages = [m for m in kwargs["messages"] if m.get("role") == "tool"]
        if not tool_messages:
            return ToolTurn(tool_calls=(ToolCall(id="call-1", name="blob", raw_arguments="{}",
                                                 arguments={}),),
                            finish_reason="tool_calls")
        self.seen.append(json.loads(tool_messages[-1]["content"]))
        return ToolTurn(content="done", finish_reason="stop")


@pytest.mark.asyncio
@pytest.mark.parametrize("patterns, named", [
    (["blob"], False),               # the agent's profile withholds file_read
    (["blob", "file_*"], True),      # it offers it
    (None, True),                    # unrestricted
])
async def test_a_spilled_result_names_file_read_only_to_a_turn_offered_it(
        tmp_path, monkeypatch, patterns, named):
    """The whole-result path, like execute_code, asks what *this turn* was offered: a
    call the loop would refuse with tool_not_allowed is no recipe."""
    from types import SimpleNamespace

    from agents.core import agent_runtime

    monkeypatch.setattr(
        agent_runtime, "estimate_messages",
        lambda messages: sum(len(str(m.get("content", ""))) for m in messages) // 4)
    orch, runtime = _wire_coordinator(
        monkeypatch, home=tmp_path / "home", roots=None,
        agents={"nerva": SimpleNamespace(tools=patterns)})

    async def blob(args):
        return {"rows": "".join(f"row-{i:05d};" for i in range(40_000))}

    orch.tool_rpc.register_tool("blob", blob, description="Return a large payload.",
                                input_schema={"type": "object", "properties": {}})
    backend = _OneSpillBackend()

    answer = await runtime.run(agent_id="nerva", backend=backend, model="local-model",
                               prompt="fetch a lot", system="You are Nerva.",
                               max_tokens=256, temperature=0.2)

    assert answer == "done"
    [envelope] = backend.seen
    assert envelope["spilled"] is True
    assert ("read_with" in envelope) is named, envelope["notice"]
    if named:
        assert await _follow(orch.tool_rpc.handle, envelope["read_with"]) == \
            Path(envelope["result_file"]).read_text(encoding="utf-8")
    else:
        assert "file_read(" not in envelope["notice"]


@pytest.mark.asyncio
async def test_concurrent_turns_each_get_their_own_offer(tmp_path, monkeypatch):
    """The offer is noted in each run's own context: two agents sharing one runtime, run
    at once, are told what *they* may call — not whichever turn resolved last."""
    import asyncio
    from types import SimpleNamespace

    from agents.core import agent_runtime

    monkeypatch.setattr(
        agent_runtime, "estimate_messages",
        lambda messages: sum(len(str(m.get("content", ""))) for m in messages) // 4)
    orch, runtime = _wire_coordinator(
        monkeypatch, home=tmp_path / "home", roots=None,
        agents={"reader": SimpleNamespace(tools=["blob", "file_read"]),
                "narrow": SimpleNamespace(tools=["blob"])})

    async def blob(args):
        await asyncio.sleep(0.05)  # both turns resolve their offers before either spills
        return {"rows": "".join(f"row-{i:05d};" for i in range(40_000))}

    orch.tool_rpc.register_tool("blob", blob, description="Return a large payload.",
                                input_schema={"type": "object", "properties": {}})
    backends = {"reader": _OneSpillBackend(), "narrow": _OneSpillBackend()}

    await asyncio.gather(*(
        runtime.run(agent_id=agent, backend=backend, model="local-model", prompt="x",
                    system="s", max_tokens=256, temperature=0.2)
        for agent, backend in backends.items()))

    assert "read_with" in backends["reader"].seen[0]
    assert "read_with" not in backends["narrow"].seen[0]


def test_a_synchronous_capability_check_leaves_no_offer_behind(tmp_path, monkeypatch):
    """`can_run` resolves the same profile outside any turn. It must not leave a note
    in the caller's context that a later spill there would read as this turn's offer."""
    from types import SimpleNamespace

    orch, runtime = _wire_coordinator(
        monkeypatch, home=tmp_path / "home", roots=None,
        agents={"narrow": SimpleNamespace(tools=["echo"])})
    orch.get_setting = lambda key, default: True if key == "llm.tool_loop_enabled" else default

    assert runtime.can_run(SimpleNamespace(supports_tools=True), agent_id="narrow") is True

    assert runtime._result_store.spill(_BODY, tool="web_extract").readable is True


# ── the loop the row is about ────────────────────────────────────────────────

class _PagingBackend:
    """Calls ``blob`` once, then does exactly what the result tells it to."""

    supports_tools = True

    def __init__(self) -> None:
        self.pages: list[str] = []
        self.fenced: list[bool] = []
        self.turns = 0

    async def generate_tool_turn(self, **kwargs):
        from agents.core.llm.tool_protocol import ToolTurn

        self.turns += 1
        tool_messages = [m for m in kwargs["messages"] if m.get("role") == "tool"]
        if not tool_messages:
            return self._call("blob", {"n": 1})
        content = tool_messages[-1]["content"]
        fence = split_fenced_tool_result(content)
        self.fenced.append(fence is not None)
        last = json.loads(fence[1] if fence else content)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("through", ["spill_door", "owner_roots"])
async def test_a_paged_spill_is_fenced_and_taints_the_turn(tmp_path, monkeypatch, through):
    """A spill is a tool's output parked on disk. Paged back through ``file_read`` it
    used to arrive as trusted file text — no fence, no turn taint — so third-party
    output re-entered the turn clean (lot-1 verifier finding). Every page of a spill
    now declares taint. The producing tool here is a *trusted* one with a clean
    payload, so the fences and the raised origin can only come from the read-back.
    """
    from agents.core import agent_runtime
    from agents.core.action_origin import current_action_origin
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.security.taint import TAINTED_RECALL_ORIGIN

    monkeypatch.setattr(
        agent_runtime, "estimate_messages",
        lambda messages: sum(len(str(m.get("content", ""))) for m in messages) // 4)
    spill_root = tmp_path / "spills"
    spill_root.mkdir()
    server = ToolRPCServer()

    async def blob(args):
        return {"blob": "".join(f"row-{i:05d};" for i in range(4_000))}

    server.register_tool("blob", blob, description="Return a large payload.",
                         input_schema={"type": "object",
                                       "properties": {"n": {"type": "integer"}}})
    root = spill_root
    if through == "spill_door":
        root = tmp_path / "projects"
        root.mkdir()
    register_file_tools(server, FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"),
                                          max_bytes=2_000_000, spill_dirs=(spill_root,)),
                        enabled=True)
    backend = _PagingBackend()
    events: list[dict] = []
    runtime = AgentToolRuntime(server, enabled=lambda: True, max_result_bytes=5_000,
                               max_iterations=lambda: 40, result_store=ToolResultStore(spill_root))

    answer = await runtime.run(agent_id="nerva", backend=backend, model="local-model",
                               prompt="fetch a lot", system="You are Nerva.",
                               max_tokens=256, temperature=0.2, event_sink=events.append)

    assert answer == "done"
    assert len(backend.pages) > 1
    assert backend.fenced == [False] + [True] * len(backend.pages)
    untrusted = [e for e in events if e["event"] == "tool_result_untrusted"]
    assert len(untrusted) == len(backend.pages)
    assert all(e["source"] == "file_read" and "declared_taint" in e["reasons"] for e in untrusted)
    assert current_action_origin() == TAINTED_RECALL_ORIGIN


@pytest.mark.asyncio
async def test_a_page_of_a_spill_declares_taint_and_an_ordinary_file_does_not(tmp_path):
    root = _workspace(tmp_path)
    spills = tmp_path / "spills"
    spills.mkdir()
    (spills / "web-extract-0123456789abcdef.json").write_text('{"ok": true}', encoding="utf-8")
    (root / "notes.json").write_text('{"ok": true}', encoding="utf-8")
    store_named = root / trs.SPILL_DIRNAME
    store_named.mkdir()
    (store_named / "web-extract-fedcba9876543210.json").write_text('{"ok": true}', encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"),
                      spill_dirs=(spills,))

    door = await tools.read_file({"path": str(spills / "web-extract-0123456789abcdef.json")})
    in_roots = await tools.read_file({"path": str(store_named / "web-extract-fedcba9876543210.json")})
    ordinary = await tools.read_file({"path": str(root / "notes.json")})

    assert door["ok"] is True and door["tainted"] is True
    assert in_roots["ok"] is True and in_roots["tainted"] is True
    assert ordinary["ok"] is True and "tainted" not in ordinary


@pytest.mark.asyncio
async def test_a_search_that_reaches_a_spill_declares_taint(tmp_path):
    # file_search returns 200-char snippets of whatever it matched, with a pattern the
    # model chooses: a match inside a spill is that tool's output, and says so.
    root = _workspace(tmp_path)
    spills = root / trs.SPILL_DIRNAME
    spills.mkdir()
    (spills / "web-extract-0123456789abcdef.json").write_text(
        '{"ok": true, "result": {"page": "THIRD-PARTY text"}}', encoding="utf-8")
    (root / "notes.txt").write_text("my own THIRD-PARTY notes", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"))

    everything = await tools.search_files({"pattern": "THIRD-PARTY", "path": str(root)})
    own_only = await tools.search_files({"pattern": "THIRD-PARTY", "path": str(root),
                                         "glob": "notes.txt"})

    assert everything["ok"] is True and len(everything["matches"]) == 2
    assert everything["tainted"] is True
    assert own_only["ok"] is True and len(own_only["matches"]) == 1
    assert "tainted" not in own_only


@pytest.mark.asyncio
async def test_a_stream_temp_file_left_in_the_spill_directory_is_tainted_too(tmp_path):
    root = _workspace(tmp_path)
    spills = root / trs.SPILL_DIRNAME
    spills.mkdir()
    (spills / "execute-code-0123456789abcdef.txt.part").write_text("partial stdout",
                                                                    encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"))
    page = await tools.read_file({"path": str(spills / "execute-code-0123456789abcdef.txt.part")})
    assert page["ok"] is True and page["tainted"] is True
