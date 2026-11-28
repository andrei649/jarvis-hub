"""Tests for modern agent-harness & personal-assistant upgrades (H386, H395, H444).

Covers:
  1. H386 — Tiered system prompt assembly, memoization, SQLite session prefix store,
            and Anthropic `[cached_prefix, uncached_volatile_tail]` cache boundary.
  2. H395 — Live mid-turn `/steer` across `turn_steer`, `AgentToolRuntime` (both
            inter-tool and late final-round steers), `POST /chat/steer` credential
            isolation, `/steer` slash command, `nerva chat -i` REPL steering, and
            proof that steering never grants an `ActionKernel` approval.
  3. H444 — Zero-dependency stdlib document readers (`.xlsx`, `.ods`, `.odt`,
            `.ipynb`, `.epub`, `.rtf`) in `file_read` and `local_docs` (including
            DOCX table indexing and zip-bomb / XML-entity fail-closed guards).
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agents.core.commands import Principal, build_default_registry
from agents.core.conversation_clock import ClockSnapshot, clock_scope
from agents.core.file_tools import FileScope, FileTools
from agents.core.llm.tool_dialects import CACHE_BREAKPOINT, cache_marked_system
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.local_docs import LocalDocsIndexer, extract_text
from agents.core.operating_prompt import TieredSystemPrompt, clocked_prompt
from agents.core.prompt_tiers import (
    PROMPT_MEMO,
    PromptTiers,
    SessionPromptStore,
    runtime_identity_digest,
    split_system_cache_boundary,
)
from agents.core.skills.tools import PRUNED_NOTICE_HEADER, pruned_marker, with_pruned_skill_notice
from agents.core.turn_steer import (
    active_steer_turns,
    steer_http,
    track_turn_steer,
)

# ── 1. H386: Tiered system prompt & cache boundary ──────────────────────────


def test_tiered_system_prompt_preserves_cache_prefix_across_midnight_and_skill_prune():
    born = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    next_day = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
    same_snap = ClockSnapshot("sess-1", born, born, 1, "inst-1")
    next_snap = ClockSnapshot("sess-1", born, next_day, 2, "inst-1")

    base_tiered = TieredSystemPrompt(
        stable="AUTHORITY\n\nPERSONA\n\n# Operating guidance scope\nFollow rules.",
        base="AUTHORITY\n\nPERSONA",
        model="claude-sonnet-4-6",
        identity_digest="abc123",
    )

    same_clocked = clocked_prompt(base_tiered, same_snap)
    assert isinstance(same_clocked, TieredSystemPrompt)
    assert "Conversation started:" in same_clocked.context_tier
    assert same_clocked.volatile_tier == ""
    blocks_same = cache_marked_system(same_clocked)
    assert len(blocks_same) == 1
    assert blocks_same[0]["cache_control"] == CACHE_BREAKPOINT

    next_clocked = clocked_prompt(base_tiered, next_snap)
    assert isinstance(next_clocked, TieredSystemPrompt)
    # Prefix block (stable + Conversation started) is 100% byte-identical across midnight!
    assert next_clocked.prefix_block == same_clocked.prefix_block
    assert "Today's date (as of the last context rebuild):" in next_clocked.volatile_tier

    blocks_next = cache_marked_system(next_clocked)
    assert len(blocks_next) == 2
    assert blocks_next[0] == {"type": "text", "text": same_clocked.prefix_block, "cache_control": CACHE_BREAKPOINT}
    assert "Today's date" in blocks_next[1]["text"]
    assert "cache_control" not in blocks_next[1]

    # Plain string round-trip (as after prepare_profile_messages JSON copy) splits identically.
    blocks_plain = cache_marked_system(str(next_clocked))
    assert blocks_plain == blocks_next

    # Adding a compaction pruned-skill notice lands in volatile_tier without touching prefix_block.
    pruned_messages = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "skill_view", "arguments": '{"name":"deploy"}'}}
        ]},
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": json.dumps({
                "ok": True,
                "tool": "skill_view",
                "name": "deploy",
                "pruned": pruned_marker("deploy"),
                "original_bytes": 256,
            }),
        },
    ]
    noticed = with_pruned_skill_notice(next_clocked, pruned_messages)
    assert isinstance(noticed, TieredSystemPrompt)
    assert noticed.prefix_block == same_clocked.prefix_block
    assert PRUNED_NOTICE_HEADER in noticed.volatile_tier
    prefix, volatile = split_system_cache_boundary(str(noticed))
    assert prefix == same_clocked.prefix_block
    assert PRUNED_NOTICE_HEADER in volatile


def test_prompt_memo_hits_on_identical_inputs_and_invalidates_per_agent():
    from tests.test_h388_guidance_wiring import wired

    PROMPT_MEMO.invalidate()
    runtime, values = wired({"enabled": True})
    born = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    snap = ClockSnapshot("sess-memo", born, born, 1, "inst")

    before_hits = PROMPT_MEMO.hits
    with clock_scope(object(), snap):
        first = runtime.prepare_system("IDENTITY\n\nSOUL", backend=None, model="gpt-5", agent_id="jarvis")
        second = runtime.prepare_system("IDENTITY\n\nSOUL", backend=None, model="gpt-5", agent_id="jarvis")
    assert first == second
    assert isinstance(first, TieredSystemPrompt)
    assert PROMPT_MEMO.hits >= before_hits + 1

    # Changing live guidance flags produces a fresh digest & updated guidance immediately.
    values["llm.operating_guidance"]["agents"] = {"jarvis": {"flags": {"help_guidance": False}}}
    with clock_scope(object(), snap):
        third = runtime.prepare_system("IDENTITY\n\nSOUL", backend=None, model="gpt-5", agent_id="jarvis")
    assert "# Nerva help" in first and "# Nerva help" not in third

    removed = PROMPT_MEMO.invalidate("jarvis")
    assert removed >= 1


def test_session_prompt_store_restores_byte_exact_and_rejects_identity_drift(tmp_path):
    store = SessionPromptStore(tmp_path / "prompt_tiers.db")
    try:
        digest = runtime_identity_digest(
            agent_id="jarvis",
            base_authority="AUTH\nSOUL",
            model="qwen3:32b",
            provider="ollama",
            surface="web",
            offered_tools=("file_read", "memory"),
            guidance_signature="sig-1",
        )
        tiers = PromptTiers(
            stable="AUTH\nSOUL\n\n# Guidance",
            context="Conversation started: Friday, November 20, 2026 (UTC+00:00)",
            volatile="Today's date (as of the last context rebuild): Saturday, November 21, 2026 — trust this over the start date",
            identity_digest=digest,
        )
        store.save("sess-42", "jarvis", model="qwen3:32b", tiers=tiers)

        restored = store.restore("sess-42", "jarvis", expected_digest=digest, volatile="NEW VOLATILE")
        assert restored is not None
        assert restored.stable == tiers.stable
        assert restored.context == tiers.context
        assert restored.volatile == "NEW VOLATILE"

        # Any SOUL / model / toolset drift changes the digest and refuses stale restoration.
        drifted = runtime_identity_digest(
            agent_id="jarvis",
            base_authority="AUTH\nMODIFIED SOUL",
            model="qwen3:32b",
            provider="ollama",
            surface="web",
            offered_tools=("file_read", "memory"),
            guidance_signature="sig-1",
        )
        assert store.restore("sess-42", "jarvis", expected_digest=drifted) is None
        assert store.invalidate_session("sess-42", "jarvis") == 1
        assert store.restore("sess-42", "jarvis", expected_digest=digest) is None
    finally:
        store.close()


# ── 2. H395: Live mid-turn /steer across runtime, HTTP, slash & CLI ─────────


@pytest.mark.asyncio
async def test_turn_steer_delivers_both_between_tools_and_on_late_final_round():
    from tests.test_h388_guidance_runtime import setup_runtime

    runtime = setup_runtime()
    events: list[dict] = []

    class SteerableBackend:
        supports_tools = True

        def __init__(self):
            self.requests: list[list[dict]] = []

        async def generate_tool_turn(self, *, model, messages, tools, max_tokens, temperature):
            self.requests.append([dict(m) for m in messages])
            if len(self.requests) == 1:
                return ToolTurn(content="", tool_calls=[
                    ToolCall(id="call_1", name="echo", arguments={"n": 1}),
                ])
            if len(self.requests) == 2:
                # Simulate user sending a second /steer while the final answer is generating!
                status, _ = steer_http("actor-owner", "also mention port 8765", session_id="sess-live")
                assert status == "queued"
                return ToolTurn(content="Initial draft before second steer.", tool_calls=[])
            return ToolTurn(content="Final answer including port 8765.", tool_calls=[])

    backend = SteerableBackend()
    orig_echo = runtime._server._tools["echo"]["handler"]

    async def echo_and_steer(args):
        status, pending = steer_http("actor-owner", "check src/api instead", session_id="sess-live")
        assert status == "queued" and pending == 1
        # Another credential cannot see or steer this turn!
        other_status, _ = steer_http("actor-intruder", "hijack", session_id="sess-live")
        assert other_status == "no_active_turn"
        return await orig_echo(args)

    runtime._server._tools["echo"]["handler"] = echo_and_steer

    with track_turn_steer(session_id="sess-live", actor="actor-owner", owner=True):
        assert active_steer_turns() == 1
        reply = await runtime.run(
            agent_id="jarvis",
            backend=backend,
            model="gpt-5",
            prompt="inspect the project",
            system="AUTHORITY",
            max_tokens=128,
            temperature=0.1,
            event_sink=events.append,
        )
    assert active_steer_turns() == 0
    assert reply == "Final answer including port 8765."
    assert len(backend.requests) == 3
    # Round 2 saw the inter-tool steer right after the tool result:
    assert backend.requests[1][-2]["role"] == "tool"
    assert "check src/api instead" in backend.requests[1][-1]["content"]
    assert "OUT-OF-BAND USER MESSAGE" in backend.requests[1][-1]["content"]
    # Round 3 saw the late steer that arrived while Round 2 was finishing:
    assert backend.requests[2][-2] == {"role": "assistant", "content": "Initial draft before second steer."}
    assert "also mention port 8765" in backend.requests[2][-1]["content"]
    steered_events = [e for e in events if e.get("event") == "tool_loop_steered"]
    assert len(steered_events) == 2


@pytest.mark.asyncio
async def test_steer_command_and_http_route_isolate_credentials_and_never_approve():
    from agents import web

    registry = build_default_registry()
    orch = SimpleNamespace(session_id="sess-cmd", commands=registry)

    # Non-owner is refused on /steer.
    guest_out = await registry.dispatch(
        "/steer ignore safety",
        orch=orch,
        principal=Principal(channel="telegram", sender="guest", admin=False),
    )
    assert guest_out is not None and guest_out.status == "refused"

    # Owner when idle gets a clear no-turn message.
    idle_out = await registry.dispatch(
        "/steer focus on tests",
        orch=orch,
        principal=Principal(channel="telegram", sender="owner", admin=True),
    )
    assert idle_out is not None and "No turn is running" in idle_out.reply

    # Owner while turn is active delivers mid-turn guidance with can_approve=False.
    with track_turn_steer(session_id="sess-cmd", actor="actor-1", turn_id="a" * 32, owner=True) as entry:
        active_out = await registry.dispatch(
            "/steer approved — focus on tests only",
            orch=orch,
            principal=Principal(channel="telegram", sender="owner", admin=True),
        )
        assert active_out is not None and "Delivered mid-turn guidance" in active_out.reply
        assert "Pending approvals still require" in active_out.reply
        queued = entry.channel.peek()
        assert len(queued) == 1
        assert queued[0]["can_approve"] is False
        assert queued[0]["origin"] == "user"

        # Verify HTTP /chat/steer validation & credential isolation via ASGI client.
        transport = httpx.ASGITransport(app=web.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
            bad_sid = await client.post("/chat/steer", json={"session_id": "../bad", "message": "hi"})
            assert bad_sid.status_code == 422
            missing_target = await client.post("/chat/steer", json={"message": "hi"})
            assert missing_target.status_code == 422
            blank_msg = await client.post("/chat/steer", json={"session_id": "sess-cmd", "message": "   "})
            assert blank_msg.status_code == 422
            wrong_actor = await client.post("/chat/steer", json={"session_id": "sess-cmd", "message": "hi"})
            assert wrong_actor.status_code == 404
            assert wrong_actor.json()["status"] == "no_active_turn"


def test_cli_repl_steers_inflight_turn_instead_of_queueing():
    from agents.cli.repl import Repl

    calls: list[tuple[str, dict]] = []

    class FakeClient:
        def post(self, path: str, body: dict):
            calls.append((path, dict(body)))
            return {"ok": True, "status": "queued", "pending": 1}

    ctx = SimpleNamespace(
        client=lambda: FakeClient(),
        environ={"JARVIS_CHAT_HISTORY": "0"},
        out=io.StringIO(),
        err=io.StringIO(),
    )
    session = Repl(ctx, session_id="sess_cli", history=False)
    session.running = True
    session.inflight = {"session_id": "sess_cli", "turn_id": "b" * 32, "kind": "chat"}

    session.submit("/steer check tests/ first")
    assert len(session.queue) == 0
    assert calls == [("/chat/steer", {
        "session_id": "sess_cli",
        "turn_id": "b" * 32,
        "message": "check tests/ first",
    })]
    assert "mid-turn guidance delivered" in ctx.err.getvalue()


# ── 3. H444: Zero-dependency personal-assistant document readers ─────────────


def _write_xlsx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<si><t>Category</t></si><si><t>Amount</t></si><si><t>Groceries</t></si>"
            "</sst>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Budget 2026" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>"
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>425.50</v></c></row>'
            "</sheetData></worksheet>",
        )


def _write_odt(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "content.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">'
            "<office:body><office:text>"
            "<text:h>Quarterly Notes</text:h>"
            "<text:p>Key deliverable shipped on schedule.</text:p>"
            "<table:table><table:table-row>"
            "<table:table-cell><text:p>Owner</text:p></table:table-cell>"
            "<table:table-cell><text:p>Andrei</text:p></table:table-cell>"
            "</table:table-row></table:table>"
            "</office:text></office:body></office:document-content>",
        )


def _write_ods(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "content.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">'
            "<office:body><office:spreadsheet>"
            '<table:table table:name="KPIs">'
            "<table:table-row>"
            "<table:table-cell><text:p>Metric</text:p></table:table-cell>"
            "<table:table-cell><text:p>Value</text:p></table:table-cell>"
            '<table:table-cell table:number-columns-repeated="1024"/>'
            "</table:table-row>"
            "<table:table-row>"
            "<table:table-cell><text:p>MRR</text:p></table:table-cell>"
            "<table:table-cell><text:p>12800</text:p></table:table-cell>"
            "</table:table-row>"
            "</table:table></office:spreadsheet></office:body></office:document-content>",
        )


def _write_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
            "</container>",
        )
        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<manifest><item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="ch1"/></spine>'
            "</package>",
        )
        zf.writestr(
            "OEBPS/ch1.xhtml",
            "<html><head><style>body{color:red}</style></head>"
            "<body><h1>Chapter One</h1><p>Deep work compounds daily.</p></body></html>",
        )


@pytest.mark.asyncio
async def test_file_read_and_local_docs_extract_xlsx_odt_ods_ipynb_epub_and_rtf(tmp_path):
    xlsx = tmp_path / "budget.xlsx"
    odt = tmp_path / "notes.odt"
    ods = tmp_path / "kpis.ods"
    epub = tmp_path / "book.epub"
    ipynb = tmp_path / "analysis.ipynb"
    rtf = tmp_path / "memo.rtf"

    _write_xlsx(xlsx)
    _write_odt(odt)
    _write_ods(ods)
    _write_epub(epub)
    ipynb.write_text(
        json.dumps({
            "metadata": {"kernelspec": {"language": "python"}},
            "cells": [
                {"cell_type": "markdown", "source": ["# Revenue Study\n", "Cohort overview."]},
                {
                    "cell_type": "code",
                    "source": ["total = 40 + 2\n", "print(total)"],
                    "outputs": [
                        {"output_type": "stream", "text": ["42\n"]},
                        {
                            "output_type": "display_data",
                            "data": {"image/png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB", "text/plain": ["<Figure>"]},
                        },
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )
    rtf.write_bytes(
        b"{\\rtf1\\ansi{\\fonttbl{\\f0 Arial;}}{\\*\\generator SecretGen;}"
        b"Salut \\u259?i bun venit!\\par Linie 2: caf\\'e9.}"
    )

    tools = FileTools(FileScope([tmp_path]))

    r_xlsx = await tools.read_file({"path": str(xlsx)})
    assert r_xlsx["ok"] is True and r_xlsx["extracted"] is True and r_xlsx["format"] == "xlsx"
    assert "## Sheet: Budget 2026" in r_xlsx["content"]
    assert "| Category |  | Amount |" in r_xlsx["content"]
    assert "425.50" in r_xlsx["content"]
    r_xlsx_cached = await tools.read_file({"path": str(xlsx)})
    assert r_xlsx_cached["cached"] is True

    r_odt = await tools.read_file({"path": str(odt)})
    assert r_odt["ok"] is True and "Quarterly Notes" in r_odt["content"] and "| Owner | Andrei |" in r_odt["content"]

    r_ods = await tools.read_file({"path": str(ods)})
    assert r_ods["ok"] is True and "## Sheet: KPIs" in r_ods["content"] and "| MRR | 12800 |" in r_ods["content"]

    r_ipynb = await tools.read_file({"path": str(ipynb)})
    assert r_ipynb["ok"] is True
    assert "# Revenue Study" in r_ipynb["content"]
    assert "total = 40 + 2" in r_ipynb["content"]
    assert "42" in r_ipynb["content"]
    assert "iVBORw0KGgo" not in r_ipynb["content"]
    assert r_ipynb["visual_content"]["images"] == 1

    r_epub = await tools.read_file({"path": str(epub)})
    assert r_epub["ok"] is True and "Chapter One" in r_epub["content"] and "color:red" not in r_epub["content"]

    r_rtf = await tools.read_file({"path": str(rtf)})
    assert r_rtf["ok"] is True
    assert "SecretGen" not in r_rtf["content"]
    assert "ă" in r_rtf["content"] and "café" in r_rtf["content"]

    # Second Brain local_docs indexer indexes all new formats + DOCX tables too.
    docx_mod = pytest.importorskip("docx")
    docx_path = tmp_path / "contract.docx"
    doc = docx_mod.Document()
    doc.add_paragraph("Service Agreement")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Deliverable"
    table.rows[0].cells[1].text = "Security Audit"
    doc.save(str(docx_path))
    assert "Security Audit" in (extract_text(docx_path) or "")

    remembered: list[tuple[str, dict]] = []

    async def remember(chunk: str, meta: dict) -> str:
        remembered.append((chunk, meta))
        return f"id-{len(remembered)}"

    summary = await LocalDocsIndexer(remember).index(tmp_path)
    assert summary["files_indexed"] == 7
    joined = "\n".join(chunk for chunk, _ in remembered)
    for needle in ("Groceries", "Quarterly Notes", "12800", "Revenue Study", "Chapter One", "café", "Security Audit"):
        assert needle in joined


@pytest.mark.asyncio
async def test_xml_entity_expansion_fails_closed_in_structured_documents(tmp_path):
    xxe_xlsx = tmp_path / "evil.xlsx"
    with zipfile.ZipFile(xxe_xlsx, "w") as zf:
        zf.writestr(
            "xl/workbook.xml",
            b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "boom">]><workbook>&lol;</workbook>',
        )
    tools = FileTools(FileScope([tmp_path]))
    res = await tools.read_file({"path": str(xxe_xlsx)})
    assert res["ok"] is False and res["reason"] == "extraction_failed"
