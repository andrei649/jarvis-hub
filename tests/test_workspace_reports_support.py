"""Shared fixtures and helpers of the S4 suites (reports, approvals, mailer, scheduler).

This module holds no tests; the S4 test modules import from it. What it adds on top
of ``tests/support/workspace_fixtures`` (whose ``ws`` fixture already installs a
:class:`FakeEngine` as the model through ``llm.set_engine_for_tests``):

* ``sink`` — a running :class:`~tests.support.smtp_sink.SmtpSink`, and
  :func:`configure_smtp` to point the workspace mailer at it.
* ``cast`` — the usual company plus an approver of department B and a second admin.
* :func:`app_client` — a TestClient over the auth, reports, approvals and documents
  routers, and :func:`signed_in` to log a user in on a fresh client.
* :func:`run_now` / :func:`drain` — finish background report runs deterministically.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from agents.core.routers import (
    workspace_approvals,
    workspace_auth,
    workspace_documents,
    workspace_reports,
)
from agents.core.workspace import mailer, reports
from agents.core.workspace.identity import WorkspaceUser
from tests.fixtures.workspace.doc_helpers import seed_document
from tests.support.smtp_sink import SmtpSink
from tests.support.workspace_fixtures import (
    Company,
    authed,
    db,
    login,
    make_app,
    make_user,
    seed_company,
)

SENDER = "nerva@acme.test"

__all__ = [
    "Cast", "app_client", "cast", "configure_smtp", "drain", "run_now", "seed_document",
    "signed_in", "sink",
]


@pytest.fixture
def sink():
    """A running SMTP sink on 127.0.0.1 (free port)."""
    with SmtpSink() as running:
        yield running


def configure_smtp(conn, port: int, *, host: str = "127.0.0.1", security: str = "none",
                   username: str = "", from_address: str = SENDER,
                   from_name: str = "Nerva Acme", allowed_domains: tuple[str, ...] = ()) -> None:
    """Store SMTP settings pointing at a local sink."""
    mailer.save_settings(conn, {
        "host": host, "port": port, "security": security, "username": username,
        "from_address": from_address, "from_name": from_name,
        "allowed_domains": list(allowed_domains),
    })


@dataclass
class Cast(Company):
    """:class:`Company` plus an approver of department B and a second admin."""

    approver_b: WorkspaceUser | None = None
    admin_2: WorkspaceUser | None = None


@pytest.fixture
def cast(ws) -> Cast:
    conn = db()
    try:
        company = seed_company(conn)
        return Cast(**vars(company),
                    approver_b=make_user(conn, role="approver", department_ids=[company.dept_b],
                                         name="Bogdan Approver"),
                    admin_2=make_user(conn, role="admin", department_ids=[company.dept_b],
                                      name="Second Admin"))
    finally:
        conn.close()


def app_client() -> TestClient:
    """A client for the auth, reports, approvals and documents routers."""
    return TestClient(make_app(workspace_auth.router, workspace_reports.router,
                               workspace_approvals.router, workspace_documents.router))


def signed_in(user: WorkspaceUser) -> tuple[TestClient, dict]:
    """A fresh client logged in as *user* and the headers its mutating calls need."""
    client = app_client()
    csrf = login(client, user.email)
    return client, authed(client, csrf)


def run_now(run_id: int) -> None:
    """Execute one queued run to completion (outside any event loop)."""
    asyncio.run(reports.execute_run(run_id))


async def drain() -> None:
    """Wait for every background report run spawned on the current loop."""
    while reports._TASKS:
        await asyncio.gather(*list(reports._TASKS), return_exceptions=True)
