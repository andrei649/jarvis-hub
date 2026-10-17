"""The shared workspace fixtures behave as documented — other slices build on them."""

from __future__ import annotations

import asyncio
import importlib.util

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import workspace_auth
from agents.core.workspace import config, identity
from agents.core.workspace import db as workspace_db
from agents.core.workspace.errors import WorkspaceError
from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
    DEFAULT_PASSWORD,
    SETUP_CODE,
    FakeEngine,
    authed,
    db,
    default_reply,
    freeze_clock,
    login,
    make_app,
    make_department,
    make_user,
    seed_company,
    seed_org,
    ws,
)

SOURCES = ('<source id="1" title="Politica de concedii">Angajații au 25 de zile de concediu pe an. '
           'Cererile se fac în aplicație.</source>\n<source id="2" title="Altceva">Text doi.</source>\n')


def test_ws_environment(ws):
    assert config.enabled() and config.setup_code() == SETUP_CODE
    assert identity.SCRYPT_N == 2 ** 10
    assert workspace_db.db_path().is_relative_to(ws.tmp_path)
    assert isinstance(ws.engine, FakeEngine)
    llm_exists = importlib.util.find_spec("agents.core.workspace.llm") is not None
    assert ws.llm_installed is llm_exists


def test_seed_helpers(ws):
    conn = db()
    org = seed_org(conn, "Beta SRL")
    assert org["name"] == "Beta SRL" and seed_org(conn, "Ignored")["name"] == "Beta SRL"
    dept = make_department(conn, "Juridic", assistant_instructions="Citează articolele.")
    invited = make_user(conn, role="member", department_ids=[dept], status="invited")
    assert invited.status == "invited"
    assert conn.execute("SELECT password_hash FROM users WHERE id = ?", (invited.id,)).fetchone()[0] is None
    active = make_user(conn, role="approver", department_ids=[dept], email="Ana@Beta.test", name="Ana")
    assert (active.email, active.name, active.department_ids) == ("ana@beta.test", "Ana", (dept,))
    assert seed_company(db()).org["name"] == "Beta SRL", "an existing org is kept"


def test_seed_company_cast(ws):
    company = seed_company(db())
    assert company.org["name"] == "Acme"
    assert company.admin.is_admin and company.approver_a.role == "approver"
    assert company.member_a.department_ids == (company.dept_a,)
    assert company.member_b.department_ids == (company.dept_b,)


def test_login_and_authed(ws):
    company = seed_company(db())
    client = TestClient(make_app(workspace_auth.router))
    csrf = login(client, company.member_a.email)
    headers = authed(client, csrf)
    assert headers == {"X-CSRF-Token": csrf, "Origin": "http://testserver"}
    assert client.post("/api/workspace/logout", headers=headers).status_code == 204
    https = TestClient(make_app(workspace_auth.router), base_url="https://ws.example:8443")
    assert authed(https, "t")["Origin"] == "https://ws.example:8443"


def test_freeze_clock(ws, monkeypatch):
    clock = freeze_clock(monkeypatch, start=100)
    assert workspace_db.now() == 100
    assert clock.advance(5) == 105 and workspace_db.now() == 105


def test_default_reply_quotes_source_one_in_the_questions_language():
    ro = default_reply(system="", prompt=SOURCES + "Întrebare: câte zile de concediu am?")
    assert ro == "Conform documentelor companiei: Angajații au 25 de zile de concediu pe an. [1]"
    en = default_reply(system="", prompt=SOURCES + "Question: how many vacation days do I get?")
    assert en == "According to the company documents: Angajații au 25 de zile de concediu pe an. [1]"
    assert "Nu am găsit" in default_reply(system="", prompt="Care este politica de concedii?")
    assert "could not find" in default_reply(system="", prompt="What is the leave policy?")


async def test_complete_streams_token_by_token():
    engine = FakeEngine()
    seen: list[str] = []

    async def on_token(token: str) -> None:
        seen.append(token)

    result = await engine.complete(system="sys", prompt=SOURCES + "How many days?", policy="local_only",
                                   on_token=on_token)
    assert len(seen) > 5 and "".join(seen) == result.text
    assert "[1]" in result.text
    assert (result.model, result.route, result.locality) == ("fake-local-model", "local", "local")
    assert result.latency_ms >= 0
    assert engine.calls == [{"system": "sys", "prompt": SOURCES + "How many days?",
                             "policy": "local_only", "max_tokens": 1200, "temperature": 0.2,
                             "timeout_seconds": 180.0, "streamed": True}]


async def test_sync_callbacks_and_no_stream():
    tokens: list[str] = []
    engine = FakeEngine("Un răspuns fix, scurt.")
    result = await engine.complete(system="", prompt="x", policy="local_only", on_token=tokens.append)
    assert "".join(tokens) == "Un răspuns fix, scurt." == result.text
    quiet: list[str] = []
    silent = FakeEngine("abc def", stream=False)
    await silent.complete(system="", prompt="x", policy="local_only", on_token=quiet.append)
    assert quiet == []


async def test_callable_reply():
    engine = FakeEngine(lambda *, system, prompt: f"{system}|{prompt}")
    assert (await engine.complete(system="s", prompt="p", policy="allow_cloud")).text == "s|p"


async def test_failures_and_delays():
    error = WorkspaceError("model_unavailable", status=503, reason="no_local_model")
    engine = FakeEngine(fail=error)
    with pytest.raises(WorkspaceError) as caught:
        await engine.complete(system="", prompt="x", policy="local_only")
    assert caught.value is error and len(engine.calls) == 1
    slow = FakeEngine("late", delay=0.2)
    with pytest.raises(WorkspaceError) as timed_out:
        await slow.complete(system="", prompt="x", policy="local_only", timeout_seconds=0.05)
    assert timed_out.value.code == "model_timeout" and timed_out.value.status == 504
    started = asyncio.get_running_loop().time()
    assert (await FakeEngine("ok", delay=0.05).complete(system="", prompt="x", policy="p")).text == "ok"
    assert asyncio.get_running_loop().time() - started >= 0.05


async def test_posture():
    engine = FakeEngine()
    posture = await engine.posture("local_only")
    assert posture == {"available": True, "backend": "fake", "model": "fake-local-model",
                       "route": "local", "locality": "local", "policy": "local_only", "reason": "",
                       "guardrails_mode": "off"}
    down = FakeEngine(fail=WorkspaceError("model_unavailable", status=503, reason="no_local_model"))
    assert (await down.posture("local_only"))["available"] is False
    assert (await down.posture("local_only"))["reason"] == "no_local_model"
    custom = FakeEngine(posture={"available": True, "locality": "cloud", "guardrails_mode": "redact"})
    assert await custom.posture("allow_cloud") == {"policy": "allow_cloud", "available": True,
                                                   "locality": "cloud", "guardrails_mode": "redact"}
    assert custom.posture_calls == ["allow_cloud"]


def test_use_engine_swaps_the_engine(ws):
    replacement = FakeEngine("altceva")
    assert ws.use_engine(replacement) is replacement and ws.engine is replacement


def test_login_helper_fails_loudly_on_a_bad_password(ws):
    company = seed_company(db())
    client = TestClient(make_app(workspace_auth.router))
    with pytest.raises(AssertionError):
        login(client, company.member_a.email, DEFAULT_PASSWORD + "x")
