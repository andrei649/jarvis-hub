"""H309 — the model points at the owner's HUD: a tip on one element, or a short tour.

``canvas_point`` (ungated) posts a ``tip`` or a ``tour`` canvas element; the canvas
sanitises it (named anchors only, one-line captions, at most eight steps) and the HUD's
pointer overlay draws it next to the element carrying that ``data-anchor``. A tip an
untrusted turn, or a turn that is not the owner's, wrote is marked ``untrusted``.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.core import canvas as cv
from agents.core import pointer_tool as pt
from agents.core.canvas import CanvasStore
from agents.core.tool_rpc import ToolRPCServer

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    return CanvasStore(tmp_path / "canvas.json")


# ── the canvas types ─────────────────────────────────────────────────────────────

def test_the_anchors_and_bounds():
    assert cv.POINTER_ANCHORS[:3] == ("mode.cockpit", "mode.chat", "mode.projects")
    assert cv.POINTER_ANCHORS[-3:] == ("composer", "decisions", "console")
    assert len(cv.POINTER_ANCHORS) == len(set(cv.POINTER_ANCHORS)) == 19
    assert (cv.MAX_TOUR_STEPS, cv.MAX_CAPTION) == (8, 160)
    assert cv.ALLOWED_TYPES[-2:] == ("tip", "tour")
    assert not any(re.search(r"approv|reject|deny|decide|accept", a) for a in cv.POINTER_ANCHORS)


def test_the_hud_holds_the_same_anchor_list():
    src = (REPO / "frontend" / "src" / "pointer.tsx").read_text(encoding="utf-8")
    block = src[src.index("export const POINTER_ANCHORS = ["):src.index("] as const;")]
    assert tuple(re.findall(r"'([^']+)'", block)) == cv.POINTER_ANCHORS


def test_every_anchor_is_on_the_hud():
    shell = (REPO / "frontend" / "src" / "shell.tsx").read_text(encoding="utf-8")
    cockpit = (REPO / "frontend" / "src" / "cockpit.tsx").read_text(encoding="utf-8")
    app = (REPO / "frontend" / "src" / "app.tsx").read_text(encoding="utf-8")
    assert "data-anchor={'mode.'+m.id}" in shell and 'data-anchor="decisions"' in shell
    assert 'data-anchor="composer"' in cockpit and 'data-anchor="console"' in app
    modes = re.findall(r"id:'([a-z_]+)'", shell[shell.index("const MODES"):shell.index("];", shell.index("const MODES"))])
    assert tuple(f"mode.{m}" for m in modes) == cv.POINTER_ANCHORS[:16]


def test_a_tip_is_sanitised_to_one_line(store):
    el = store.post("jarvis", "tip", {"target": "console", "caption": "  Open the\n\tConsole  here  ", "extra": 1})
    assert el["payload"] == {"target": "console", "caption": "Open the Console here", "untrusted": False}
    long = store.post("jarvis", "tip", {"target": "composer", "caption": "x" * 400, "untrusted": True})
    assert long["payload"]["caption"] == "x" * 160 and long["payload"]["untrusted"] is True
    assert store.post("jarvis", "tip", {"target": "composer", "caption": "c", "untrusted": "yes"})["payload"]["untrusted"] is False


@pytest.mark.parametrize("payload,why", [
    ({"target": "approve-button", "caption": "click"}, "unknown target"),
    ({"target": "", "caption": "click"}, "unknown target"),
    ({"caption": "click"}, "unknown target"),
    ({"target": "console", "caption": "   \n "}, "caption is required"),
    ({"target": "console"}, "caption is required"),
    ("not a dict", "unknown target"),
])
def test_a_bad_tip_is_refused(store, payload, why):
    with pytest.raises(ValueError, match=why):
        store.post("jarvis", "tip", payload)
    assert store.list() == []


def test_a_tour_is_sanitised_and_bounded(store):
    steps = [{"target": "mode.memory", "caption": "Memory\nlives here"}, {"target": "decisions", "caption": "Approvals"}]
    el = store.post("jarvis", "tour", {"title": "  Getting\naround " + "t" * 200, "steps": steps})
    assert el["payload"]["steps"] == [{"target": "mode.memory", "caption": "Memory lives here"},
                                      {"target": "decisions", "caption": "Approvals"}]
    assert el["payload"]["title"].startswith("Getting around t") and len(el["payload"]["title"]) == 120
    assert el["payload"]["untrusted"] is False
    marked = store.post("jarvis", "tour", {"steps": steps, "untrusted": True})
    assert marked["payload"]["untrusted"] is True
    eight = [{"target": "console", "caption": str(i)} for i in range(8)]
    assert len(store.post("jarvis", "tour", {"steps": eight})["payload"]["steps"]) == 8


@pytest.mark.parametrize("payload,why", [
    ({"steps": []}, "steps is required"),
    ({}, "steps is required"),
    ({"steps": "console"}, "steps is required"),
    ({"steps": [{"target": "console", "caption": str(i)} for i in range(9)]}, "at most 8 steps"),
    ({"steps": [{"target": "console", "caption": "ok"}, {"target": "nope", "caption": "x"}]}, "unknown target"),
    ({"steps": [{"target": "console", "caption": ""}]}, "caption is required"),
    ({"steps": ["console"]}, "unknown target"),
])
def test_a_bad_tour_is_refused(store, payload, why):
    with pytest.raises(ValueError, match=why):
        store.post("jarvis", "tour", payload)


# ── the tool ─────────────────────────────────────────────────────────────────────

def _server(store, *, posture=lambda: "owner/owner", origin=lambda: "generated"):
    server = ToolRPCServer()
    name = pt.register_pointer_tool(server, canvas=lambda: store, posture=posture, origin=origin)
    return server, name


async def _call(server, args, **kw):
    reply = await server.handle({"tool": "canvas_point", "args": args}, **kw)
    assert reply["ok"] is True, reply
    return reply["result"]


def test_the_tool_is_ungated_and_offers_only_the_anchors(store):
    server, name = _server(store)
    row = next(r for r in server.tools() if r["name"] == name)
    assert name == pt.TOOL_NAME == "canvas_point" and row["gated"] is False
    schema = pt.INPUT_SCHEMA
    assert schema["properties"]["target"]["enum"] == list(cv.POINTER_ANCHORS)
    assert schema["properties"]["steps"]["items"]["properties"]["target"]["enum"] == list(cv.POINTER_ANCHORS)
    assert schema["properties"]["steps"]["maxItems"] == 8 and schema["additionalProperties"] is False
    assert pt.CAPABILITY_ID == "tool:canvas_point"


async def test_a_tip_lands_on_the_canvas(store):
    server, _ = _server(store)
    got = await _call(server, {"target": "mode.trust", "caption": "Your trust settings"}, actor="nerva")
    assert got["ok"] is True and got["type"] == "tip" and got["untrusted"] is False
    (el,) = store.list()
    assert el["id"] == got["id"] and el["agent"] == "nerva" and el["type"] == "tip"
    assert el["payload"] == {"target": "mode.trust", "caption": "Your trust settings", "untrusted": False}


async def test_a_tour_lands_on_the_canvas(store):
    server, _ = _server(store)
    got = await _call(server, {"title": "Tour", "steps": [{"target": "composer", "caption": "Type here"},
                                                          {"target": "console", "caption": "Tools"}]})
    assert got["type"] == "tour"
    (el,) = store.list()
    assert [s["target"] for s in el["payload"]["steps"]] == ["composer", "console"]
    assert el["agent"] == "jarvis"


@pytest.mark.parametrize("posture,origin,untrusted", [
    (lambda: "owner/owner", lambda: "generated", False),
    (lambda: "inbound/guest", lambda: "generated", True),
    (lambda: "shared/member", lambda: "generated", True),
    (lambda: "owner/owner", lambda: "inbound", True),
    (lambda: "owner/owner", lambda: "recall:untrusted", True),
    (lambda: 1 / 0, lambda: "generated", True),
    (lambda: "owner/owner", lambda: 1 / 0, True),
])
async def test_who_wrote_it_is_marked(store, posture, origin, untrusted):
    server, _ = _server(store, posture=posture, origin=origin)
    got = await _call(server, {"target": "decisions", "caption": "Look here"})
    assert got["untrusted"] is untrusted and store.list()[0]["payload"]["untrusted"] is untrusted


async def test_no_posture_getter_reads_as_the_owner(store):
    server = ToolRPCServer()
    pt.register_pointer_tool(server, canvas=lambda: store, origin=lambda: "generated")
    got = await _call(server, {"target": "decisions", "caption": "Look here"})
    assert got["untrusted"] is False


@pytest.mark.parametrize("args,reason", [
    ({"target": "console", "caption": "x", "steps": [{"target": "console", "caption": "y"}]}, "tip_or_tour"),
    ({}, "nothing_to_point_at"),
    ({"title": "only a title"}, "nothing_to_point_at"),
])
async def test_a_confused_call_is_refused_by_name(store, args, reason):
    server, _ = _server(store)
    got = await _call(server, args)
    assert got["ok"] is False and got["reason"] == reason and store.list() == []


async def test_a_refused_element_says_why(store):
    server, _ = _server(store)
    got = await _call(server, {"target": "console", "caption": "  "})
    assert got == {"ok": False, "reason": "invalid", "detail": "caption is required"}


async def test_an_unknown_target_is_refused_even_past_the_schema(store):
    # The schema offers only the anchors; the canvas refuses anything else again.
    server, _ = _server(store)
    got = await _call(server, {"target": "approve", "caption": "x"})
    assert got["ok"] is False and got["reason"] == "invalid" and "unknown target" in got["detail"]
    assert store.list() == []


async def test_no_canvas_is_said(store):
    server = ToolRPCServer()
    pt.register_pointer_tool(server, canvas=lambda: None, origin=lambda: "generated")
    got = await _call(server, {"target": "console", "caption": "x"})
    assert got == {"ok": False, "reason": "canvas_unavailable"}


def test_the_coordinator_registers_it_on_the_live_canvas():
    from agents.core import autonomy_coordinator

    src = inspect.getsource(autonomy_coordinator)
    assert 'register_pointer_tool(server, canvas=lambda: getattr(self._orch, "canvas", None),' in src
    assert "posture=lambda: tool_profile.posture().key)" in src


def test_it_is_not_a_guest_tool():
    from agents.core.tool_profiles import DEFAULT_GUEST_TOOLS

    assert "canvas_point" not in DEFAULT_GUEST_TOOLS


def test_the_canvas_route_accepts_a_tip(tmp_path, monkeypatch):
    from agents.core.routers import canvas as route

    monkeypatch.setattr(route, "get_orch", lambda: None)
    monkeypatch.setattr(route, "_canvas_store", CanvasStore(tmp_path / "c.json"))
    import asyncio

    body = route.CanvasPostBody(type="tip", payload={"target": "composer", "caption": "here"})
    resp = asyncio.run(route.canvas_post(body))
    assert resp.status_code == 200
    bad = asyncio.run(route.canvas_post(route.CanvasPostBody(type="tip", payload={"target": "x", "caption": "y"})))
    assert bad.status_code == 422
