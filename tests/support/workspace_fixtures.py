"""Shared fixtures for every Nerva Workspace test suite (spec §5 "Test fixtures").

Usage — a slice test needs three imports and one fixture::

    from fastapi.testclient import TestClient

    from agents.core.routers import workspace_auth
    from tests.support.workspace_fixtures import (  # noqa: F401  (ws is a fixture)
        authed,
        db,
        login,
        make_app,
        make_department,
        make_user,
        seed_org,
        ws,
    )


    def test_member_sees_only_own_department(ws):
        conn = db()
        seed_org(conn)
        sales = make_department(conn, "Vânzări")
        hr = make_department(conn, "HR")
        member = make_user(conn, role="member", department_ids=[sales])
        client = TestClient(make_app(workspace_auth.router))
        csrf = login(client, member.email)  # DEFAULT_PASSWORD unless you pass one
        ids = [d["id"] for d in client.get("/api/workspace/departments").json()["departments"]]
        assert ids == [sales] and hr not in ids
        r = client.post("/api/workspace/logout", headers=authed(client, csrf))
        assert r.status_code == 204

What ``ws`` gives you (a :class:`WsEnv`): a private data root and key directory under
``tmp_path`` (``JARVIS_HOME``, ``JARVIS_KEY_DIR``), ``NERVA_WORKSPACE=1``, the setup code
``test-setup-code``, scrypt at ``2**10`` (≈4 ms per hash instead of ≈260 ms), every
other workspace variable cleared, and a :class:`FakeEngine` as the model.

The model engine. When ``agents.core.workspace.llm`` (S3) is importable, ``ws`` installs
the engine through ``llm.set_engine_for_tests(engine)`` and resets it with
``set_engine_for_tests(None)`` at teardown; until that module exists the engine is only
kept on ``ws.engine`` for later. Swap it mid-test with ``ws.use_engine(FakeEngine(...))``.

The clock. Workspace code reads time through ``agents.core.workspace.db.now``; move it
with ``clock = freeze_clock(monkeypatch)`` and ``clock.advance(seconds)`` — never patch
``time.time`` (asyncio and the test client read it too).

Helpers in brief: :func:`make_app` (a bare ``FastAPI()`` with the workspace error and
validation handlers, plus the routers you pass); :func:`db` (a connection to this test's
database); :func:`seed_org`, :func:`make_department`, :func:`make_user`, and
:func:`seed_company` for the usual two-department cast (admin, approver, members);
:func:`login` (returns the CSRF token; the client keeps the cookie) and :func:`authed`
(the ``X-CSRF-Token`` + same-origin ``Origin`` headers every mutating call needs).
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import itertools
import re
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agents.core.workspace import db as workspace_db
from agents.core.workspace import identity
from agents.core.workspace.errors import WorkspaceError, register_handlers
from agents.core.workspace.identity import WorkspaceUser

SETUP_CODE = "test-setup-code"
DEFAULT_PASSWORD = "Parola-Buna-2026!"
TEST_SCRYPT_N = 2 ** 10
LLM_MODULE = "agents.core.workspace.llm"

_CLEARED_ENV = (
    "JARVIS_AUDIT_KEY", "JARVIS_TRUSTED_PROXIES", "JARVIS_TRUSTED_PROXY", "JARVIS_PROFILE",
    "NERVA_WORKSPACE_COOKIE_SECURE", "NERVA_WORKSPACE_SSO_HEADER", "NERVA_WORKSPACE_SSO_SECRET",
    "NERVA_WORKSPACE_MAX_UPLOAD_MB", "NERVA_WORKSPACE_SESSION_IDLE_HOURS",
    "NERVA_WORKSPACE_SESSION_MAX_DAYS", "NERVA_WORKSPACE_MAX_CONCURRENT_LLM",
    "NERVA_WORKSPACE_SCHEDULER",
)
_SOURCE = re.compile(r'<source\s+id="(\d+)"[^>]*>(.*?)</source>', re.DOTALL)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_ROMANIAN_CHARS = re.compile(r"[ăâîșşțţĂÂÎȘŞȚŢ]")
_ROMANIAN_WORDS = re.compile(
    r"\b(care|este|sunt|pentru|cum|cât|câte|unde|când|despre|vreau|să|și|din|ce|avem|politica)\b",
    re.IGNORECASE,
)
_user_counter = itertools.count(1)


# ── the model double ─────────────────────────────────────────────────────────────────

@dataclass
class LLMResult:
    """Mirror of ``agents.core.workspace.llm.LLMResult`` (spec §5) until S3 lands."""

    text: str
    model: str
    route: str
    locality: str
    latency_ms: int


def _result_class() -> type:
    """``llm.LLMResult`` when S3's module exists (so ``isinstance`` checks hold), else ours."""
    try:
        module = importlib.import_module(LLM_MODULE)
    except ImportError:
        return LLMResult
    return getattr(module, "LLMResult", LLMResult)


def _looks_romanian(text: str) -> bool:
    return bool(_ROMANIAN_CHARS.search(text) or len(_ROMANIAN_WORDS.findall(text)) >= 2)


def _first_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    sentence = _SENTENCE_END.split(cleaned, maxsplit=1)[0] if cleaned else ""
    return sentence[:240].rstrip()


def default_reply(*, system: str, prompt: str) -> str:
    """The deterministic, citation-aware answer :class:`FakeEngine` gives by default.

    With a ``<source id="1" …>`` block in the prompt it quotes that source's first
    sentence and cites ``[1]``; without sources it says it found nothing. The language
    follows the question (the prompt's text after the last ``</source>``): Romanian when
    it has Romanian diacritics or at least two common Romanian words, else English.
    """
    sources = {int(num): body for num, body in _SOURCE.findall(prompt)}
    question = prompt.rsplit("</source>", 1)[-1]
    romanian = _looks_romanian(question)
    if 1 in sources:
        sentence = _first_sentence(sources[1])
        if romanian:
            return f"Conform documentelor companiei: {sentence} [1]"
        return f"According to the company documents: {sentence} [1]"
    if romanian:
        return "Nu am găsit această informație în documentele companiei."
    return "I could not find this in the company documents."


def _tokens(text: str) -> list[str]:
    """Word-sized pieces whose concatenation is exactly *text*."""
    return re.findall(r"\S+\s*|\s+", text) or [text]


async def _emit(on_token: Callable[[str], Any], token: str) -> None:
    outcome = on_token(token)
    if inspect.isawaitable(outcome):
        await outcome


def _error_class(name: str) -> type[WorkspaceError] | None:
    try:
        module = importlib.import_module(LLM_MODULE)
    except ImportError:
        return None
    candidate = getattr(module, name, None)
    return candidate if isinstance(candidate, type) and issubclass(candidate, WorkspaceError) else None


def _timeout_error(seconds: float) -> WorkspaceError:
    cls = _error_class("ModelTimeout")
    if cls is not None:
        try:
            return cls()
        except TypeError:
            pass
    return WorkspaceError("model_timeout", f"the model did not answer within {seconds:g} s", 504)


class FakeEngine:
    """A deterministic model engine with the ``llm`` engine interface.

    ``reply`` is a fixed string, or a callable ``(system=..., prompt=...) -> str``, or
    ``None`` for :func:`default_reply`. ``stream=True`` feeds ``on_token`` word by word
    (sync or async callbacks), ``fail`` is a :class:`WorkspaceError` raised instead of
    answering (after ``delay``), ``delay`` waits before the first token and
    ``token_delay`` between tokens. A ``timeout_seconds`` shorter than the total delay
    raises ``model_timeout`` like the real engine. Every call is recorded in ``calls``.
    """

    def __init__(self, reply: str | Callable[..., str] | None = None, *, stream: bool = True,
                 fail: WorkspaceError | None = None, delay: float = 0.0,
                 token_delay: float = 0.0, model: str = "fake-local-model",
                 route: str = "local", locality: str = "local",
                 posture: dict | None = None) -> None:
        self.reply = reply
        self.stream = stream
        self.fail = fail
        self.delay = delay
        self.token_delay = token_delay
        self.model = model
        self.route = route
        self.locality = locality
        self.posture_override = posture
        self.calls: list[dict] = []
        self.posture_calls: list[str] = []

    def _text(self, system: str, prompt: str) -> str:
        if self.reply is None:
            return default_reply(system=system, prompt=prompt)
        if callable(self.reply):
            return self.reply(system=system, prompt=prompt)
        return self.reply

    async def _run(self, system: str, prompt: str,
                   on_token: Callable[[str], Awaitable[None]] | None) -> str:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        text = self._text(system, prompt)
        if self.stream and on_token is not None:
            for token in _tokens(text):
                await _emit(on_token, token)
                if self.token_delay:
                    await asyncio.sleep(self.token_delay)
        return text

    async def complete(self, *, system: str, prompt: str, policy: str, max_tokens: int = 1200,
                       temperature: float = 0.2,
                       on_token: Callable[[str], Awaitable[None]] | None = None,
                       timeout_seconds: float = 180.0) -> Any:
        """Answer like ``llm.complete`` and return an ``LLMResult``-shaped object."""
        self.calls.append({
            "system": system, "prompt": prompt, "policy": policy, "max_tokens": max_tokens,
            "temperature": temperature, "timeout_seconds": timeout_seconds,
            "streamed": on_token is not None,
        })
        started = time.monotonic()
        try:
            text = await asyncio.wait_for(self._run(system, prompt, on_token), timeout_seconds)
        except TimeoutError as exc:
            raise _timeout_error(timeout_seconds) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        return _result_class()(text=text, model=self.model, route=self.route,
                               locality=self.locality, latency_ms=latency_ms)

    async def posture(self, policy: str) -> dict:
        """``llm.posture`` shape; unavailable (with the failure's reason) when ``fail`` is set."""
        self.posture_calls.append(policy)
        if self.posture_override is not None:
            return {"policy": policy, **self.posture_override}
        available = self.fail is None or self.fail.code not in ("model_unavailable",
                                                                "model_policy_blocked")
        return {
            "available": available, "backend": "fake", "model": self.model, "route": self.route,
            "locality": self.locality, "policy": policy,
            "reason": "" if available else str(self.fail.extra.get("reason", self.fail.code)),
            "guardrails_mode": "off",
        }


# ── environment ──────────────────────────────────────────────────────────────────────

@dataclass
class WsEnv:
    """What :func:`ws_env` set up for one test."""

    tmp_path: Path
    data_dir: Path
    key_dir: Path
    engine: FakeEngine
    setup_code: str = SETUP_CODE
    llm_installed: bool = False

    def use_engine(self, engine: FakeEngine) -> FakeEngine:
        """Replace the model engine for the rest of the test; returns it."""
        self.engine = engine
        self.llm_installed = _install_engine(engine)
        return engine


def _install_engine(engine: Any) -> bool:
    """``llm.set_engine_for_tests(engine)`` when S3's module exists; True when installed."""
    try:
        module = importlib.import_module(LLM_MODULE)
    except ImportError:
        return False
    setter = getattr(module, "set_engine_for_tests", None)
    if setter is None:
        return False
    setter(engine)
    return True


def ws_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WsEnv:
    """Point the workspace at a private, enabled, fast environment under *tmp_path*."""
    data_dir = tmp_path / "data"
    key_dir = tmp_path / "keys"
    data_dir.mkdir()
    key_dir.mkdir(mode=0o700)
    monkeypatch.setenv("JARVIS_HOME", str(data_dir))
    monkeypatch.setenv("JARVIS_KEY_DIR", str(key_dir))
    monkeypatch.setenv("NERVA_WORKSPACE", "1")
    monkeypatch.setenv("NERVA_WORKSPACE_SETUP_CODE", SETUP_CODE)
    for name in _CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(identity, "SCRYPT_N", TEST_SCRYPT_N)
    engine = FakeEngine()
    env = WsEnv(tmp_path=tmp_path, data_dir=data_dir, key_dir=key_dir, engine=engine)
    env.llm_installed = _install_engine(engine)
    return env


@pytest.fixture
def ws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The workspace test environment (see the module docstring); engine reset afterwards."""
    env = ws_env(monkeypatch, tmp_path)
    try:
        yield env
    finally:
        if env.llm_installed:
            _install_engine(None)


@dataclass
class Clock:
    """A controllable ``db.now`` (see :func:`freeze_clock`)."""

    current: float

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> float:
        """Move time forward; returns the new now."""
        self.current += seconds
        return self.current


def freeze_clock(monkeypatch: pytest.MonkeyPatch, start: float | None = None) -> Clock:
    """Freeze ``agents.core.workspace.db.now`` at *start* (default: the real now)."""
    clock = Clock(time.time() if start is None else float(start))
    monkeypatch.setattr(workspace_db, "now", clock)
    return clock


# ── app, database and seed data ──────────────────────────────────────────────────────

def make_app(*routers: APIRouter, root_path: str = "") -> FastAPI:
    """A bare app with the workspace error/validation handlers and *routers* included."""
    app = FastAPI(root_path=root_path)
    register_handlers(app)
    for router in routers:
        app.include_router(router)
    return app


def db() -> sqlite3.Connection:
    """A connection to this test's workspace database (schema ensured)."""
    return workspace_db.connect()


def seed_org(conn: sqlite3.Connection, name: str = "Acme", *, default_locale: str = "ro",
             model_policy: str = "local_only") -> dict:
    """Create the organisation row (setup done); returns ``org_to_json``."""
    with workspace_db.tx(conn):
        conn.execute(
            "INSERT OR IGNORE INTO org (id, name, default_locale, model_policy, created_at) "
            "VALUES (1, ?, ?, ?, ?)",
            (name, default_locale, model_policy, workspace_db.now()),
        )
    org = identity.ensure_org(conn)
    assert org is not None
    return identity.org_to_json(org)


def make_department(conn: sqlite3.Connection, name: str, *, description: str = "",
                    assistant_instructions: str = "", archived: bool = False) -> int:
    """Insert a department (unique slug derived from *name*); returns its id."""
    with workspace_db.tx(conn):
        cursor = conn.execute(
            "INSERT INTO departments (slug, name, description, assistant_instructions, archived, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (identity.unique_department_slug(conn, name), name, description,
             assistant_instructions, int(archived), workspace_db.now()),
        )
    return int(cursor.lastrowid)


def make_user(conn: sqlite3.Connection, *, role: str, department_ids: list[int],
              email: str | None = None, password: str | None = None,
              status: str = "active", name: str | None = None, locale: str = "ro") -> WorkspaceUser:
    """Insert a user with memberships; ``invited`` users get no password hash.

    *password* defaults to :data:`DEFAULT_PASSWORD` (``'Parola-Buna-2026!'``).
    """
    password = DEFAULT_PASSWORD if password is None else password
    number = next(_user_counter)
    email = (email or f"{role}-{number}@acme.test").lower()
    name = name or f"{role.capitalize()} {number}"
    password_hash = None if status == "invited" else identity.hash_password(password)
    with workspace_db.tx(conn):
        user_id = int(conn.execute(
            "INSERT INTO users (email, name, role, status, password_hash, locale, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (email, name, role, status, password_hash, locale, workspace_db.now()),
        ).lastrowid)
        conn.executemany("INSERT INTO user_departments (user_id, department_id) VALUES (?, ?)",
                         [(user_id, dept_id) for dept_id in department_ids])
    user = identity.get_user(conn, user_id)
    assert user is not None
    return user


@dataclass
class Company:
    """The usual cast: departments A and B, an admin, an approver and a member in A, a member in B."""

    org: dict
    dept_a: int
    dept_b: int
    admin: WorkspaceUser
    approver_a: WorkspaceUser
    member_a: WorkspaceUser
    member_b: WorkspaceUser


def seed_company(conn: sqlite3.Connection) -> Company:
    """Seed :class:`Company` — the fixture most isolation tests start from."""
    org = seed_org(conn)
    dept_a = make_department(conn, "Vânzări")
    dept_b = make_department(conn, "Resurse Umane")
    return Company(
        org=org, dept_a=dept_a, dept_b=dept_b,
        admin=make_user(conn, role="admin", department_ids=[dept_a]),
        approver_a=make_user(conn, role="approver", department_ids=[dept_a]),
        member_a=make_user(conn, role="member", department_ids=[dept_a]),
        member_b=make_user(conn, role="member", department_ids=[dept_b]),
    )


# ── HTTP helpers ─────────────────────────────────────────────────────────────────────

def origin_of(client: TestClient) -> str:
    """The same-origin ``Origin`` value for requests made by *client*."""
    base = client.base_url
    return f"{base.scheme}://{base.netloc.decode('ascii')}"


def login(client: TestClient, email: str, password: str | None = None) -> str:
    """Sign in through ``POST /api/workspace/login``; returns the CSRF token.

    *password* defaults to :data:`DEFAULT_PASSWORD`; the session cookie stays in
    *client*'s cookie jar.
    """
    password = DEFAULT_PASSWORD if password is None else password
    response = client.post("/api/workspace/login", json={"email": email, "password": password},
                           headers={"Origin": origin_of(client)})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def authed(client: TestClient, csrf: str) -> dict:
    """Headers for a mutating request: the CSRF token plus a same-origin ``Origin``."""
    return {"X-CSRF-Token": csrf, "Origin": origin_of(client)}
