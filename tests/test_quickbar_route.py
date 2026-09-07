"""The quickbar surface — and the one thing it must never grow into.

`agents/core/quickbar.py` has shipped a complete command parser since 0.64 with
no route and no consumer: a parser nobody could reach, which is code that looks
alive and is not. These routes make it reachable.

A command bar is the most tempting place in a product to put a shortcut past the
rules — one keystroke, one line, and something happens. So the tests here are
mostly about what the surface refuses to be:

  · resolving is NOT doing. The route returns a plan and performs nothing, so the
    parser's own promise ("never performs the action") stays true from outside;
  · a `summon` plan is not a summon — it names an agent, and sending is the chat
    path with the governance the chat path has;
  · there is no history route. A server-side quickbar history is a keystroke log
    of everything the owner typed into a floating bar, which would be the most
    sensitive store in the product for the least reason;
  · an unresolved line stays unresolved. A bar that fell back to "ask the default
    agent" whenever it did not understand would do the wrong thing confidently.

Hermetic: the parser is offline and deterministic; nothing here needs a model.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from agents.core.routers import quickbar as quickbar_routes
from agents.core.routers._deps import user_guard


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(quickbar_routes.router)
    return app


@pytest.fixture
def client():
    app = _app()
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app)


def _plan(client, text: str) -> dict:
    response = client.post("/api/quickbar/resolve", json={"text": text})
    assert response.status_code == 200
    return response.json()["plan"]


# ── the surface, and what it deliberately omits ──────────────────────────────

def test_the_surface_is_two_read_only_routes():
    """A quickbar that could also execute would be a second, keyboard-shaped
    route to every action in the product, reached in one keystroke."""
    from tests._route_introspect import iter_effective_routes

    paths = {
        (m, r.path)
        for r in iter_effective_routes(_app())
        for m in sorted(getattr(r, "methods", ()) or ())
        if m not in {"HEAD", "OPTIONS"} and r.path.startswith("/api/")
    }
    assert paths == {
        ("POST", "/api/quickbar/resolve"),
        ("GET", "/api/quickbar/help"),
    }


def test_there_is_no_history_route():
    """A server-side quickbar history is a keystroke log of everything the owner
    typed into a floating bar — the most sensitive store in the product, for the
    least reason. Recall belongs in the browser."""
    from tests._route_introspect import iter_effective_routes

    assert not any(
        "history" in r.path for r in iter_effective_routes(_app())
    )


def test_both_routes_are_user_guarded():
    from tests.test_route_auth_matrix import _runtime_guards

    guards = _runtime_guards()
    assert guards["POST /api/quickbar/resolve"] == "user"
    assert guards["GET /api/quickbar/help"] == "user"


def test_the_routes_refuse_without_a_user_token():
    app = _app()

    async def _deny(request: Request):
        raise HTTPException(status_code=401, detail="user token required")

    app.dependency_overrides[user_guard] = _deny
    c = TestClient(app)
    assert c.post("/api/quickbar/resolve", json={"text": "/memory"}).status_code == 401
    assert c.get("/api/quickbar/help").status_code == 401


# ── resolving is not doing ───────────────────────────────────────────────────

def test_a_navigate_plan_names_a_destination_and_goes_nowhere(client):
    plan = _plan(client, "/memory")
    assert plan["kind"] == "navigate"
    assert plan.get("mode") == "memory" or plan.get("tab") == "memory"
    # nothing in the response claims anything happened
    assert "executed" not in plan and "result" not in plan


def test_a_summon_plan_is_not_a_summon(client):
    """It names an agent. Sending the message is the chat path, with the
    governance the chat path has."""
    plan = _plan(client, "@friday what is on my calendar")
    assert plan["kind"] == "summon"
    assert plan["agent"] == "friday"
    assert plan["text"] == "what is on my calendar"
    assert "response" not in plan and "reply" not in plan


def test_a_query_plan_carries_a_hint_not_a_decision(client):
    """The authoritative routing happens on submit; a preview that read as a
    decision would be a lie about which agent is going to answer."""
    plan = _plan(client, "what is the weather like tomorrow")
    assert plan["kind"] == "query"
    assert "route_hint" in plan


# ── an unresolved line stays unresolved ──────────────────────────────────────

def test_an_unknown_command_is_unresolved_with_a_reason(client):
    """A bar that quietly fell back to "ask the default agent" would do the wrong
    thing confidently, which is worse than saying it did not understand."""
    plan = _plan(client, "/nosuchthing")
    assert plan["kind"] == "unresolved"
    assert "nosuchthing" in plan["reason"]


def test_an_unknown_agent_is_never_guessed_into_a_real_one(client):
    plan = _plan(client, "@nobody hello")
    assert plan["kind"] == "unresolved"
    assert "nobody" in plan["reason"]


def test_an_empty_line_is_its_own_state(client):
    plan = _plan(client, "   ")
    assert plan["kind"] == "empty"


# ── bounds ───────────────────────────────────────────────────────────────────

def test_an_over_long_body_is_refused_at_the_edge(client):
    """Refused rather than parsed and trimmed: the bar is one line, and anything
    longer is not a bar line."""
    response = client.post(
        "/api/quickbar/resolve", json={"text": "x" * (quickbar_routes.MAX_INPUT + 1)}
    )
    assert response.status_code == 422


def test_a_missing_text_field_resolves_as_empty_rather_than_erroring(client):
    response = client.post("/api/quickbar/resolve", json={})
    assert response.status_code == 200
    assert response.json()["plan"]["kind"] == "empty"


# ── the help menu is grounded ────────────────────────────────────────────────

def test_the_help_menu_cannot_advertise_a_destination_that_does_not_exist(client):
    """It is built from the same table the parser resolves against, so a menu
    entry always corresponds to a plan the parser can actually produce."""
    body = client.get("/api/quickbar/help").json()
    for command in body["commands"]:
        name = command["command"]
        if not name.startswith("/"):
            continue
        plan = _plan(client, name)
        assert plan["kind"] in {"navigate", "help"}, f"{name} → {plan['kind']}"


def test_the_help_menu_lists_the_real_roster_and_destinations(client):
    from agents.core.quickbar import AGENTS, CENTER_TABS, HUD_MODES

    body = client.get("/api/quickbar/help").json()
    assert body["agents"] == list(AGENTS)
    assert body["modes"] == list(HUD_MODES)
    assert body["tabs"] == list(CENTER_TABS)


def test_every_advertised_agent_can_actually_be_summoned(client):
    body = client.get("/api/quickbar/help").json()
    for agent in body["agents"]:
        plan = _plan(client, f"@{agent} hello")
        assert plan["kind"] == "summon" and plan["agent"] == agent
