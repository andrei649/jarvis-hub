"""Every operator hint names the command form the pilot guide uses (review OPS2-07).

The guide runs every operator command through ``nerva-run`` (PILOT_GUIDE §2: ``python -m``
with the service's environment). The log lines of a mismatched or missing audit key and
the CLI's own usage line used to say ``python -m agents.core.workspace …`` — the bare
form that, typed into a shell, runs without the service's ``JARVIS_AUDIT_KEY`` /
``JARVIS_HOME`` and reports a problem that is not there. They now name ``nerva-run``.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from agents.core.workspace import audit, cli, scheduler
from agents.core.workspace import db as workspace_db
from tests.support.workspace_fixtures import db, ws  # noqa: F401  (ws is a fixture)

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO / "agents" / "core" / "workspace"
GUIDE_FORM = "nerva-run -m agents.core.workspace"
BARE_FORM = "python -m agents.core.workspace"
OTHER_KEY = "b" * 64


def _strings_outside_docstrings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings]


def test_no_workspace_message_names_the_bare_python_form():
    offenders = {path.name: [text for text in _strings_outside_docstrings(path)
                             if BARE_FORM in text]
                 for path in sorted(WORKSPACE.glob("*.py"))}
    assert {name: texts for name, texts in offenders.items() if texts} == {}


def test_the_cli_usage_and_help_name_nerva_run(capsys):
    parser = cli.build_parser()
    assert parser.format_usage().startswith(f"usage: {GUIDE_FORM} ")
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    out = capsys.readouterr().out
    assert GUIDE_FORM in out and BARE_FORM not in out and "PILOT_GUIDE §2" in out


@pytest.fixture(autouse=True)
def every_log_level(caplog):
    """Capture every level, as once the hub's ``setup_logging`` ran earlier in the process.

    Importing ``agents.web`` sets the root logger to INFO, so whether the database's INFO
    lines reach ``caplog.records`` used to depend on which test ran first (REV-POLISH-01);
    starting every test here from the most verbose state makes the result order-free.
    """
    caplog.set_level(logging.DEBUG)


def _errors(caplog) -> list[str]:
    """The audit module's ERROR lines only (review REV-POLISH-01).

    ``caplog.records`` holds every record of the test at the root logger's level, so once
    an earlier test in the process has run the hub's ``setup_logging`` (root at INFO) it
    also holds the database's ``migrated to schema 1`` INFO line logged by ``db()``.
    """
    return [record.getMessage() for record in caplog.records
            if record.name == "nerva.workspace.audit" and record.levelno >= logging.ERROR]


def _write(conn) -> None:
    with workspace_db.tx(conn):
        audit.record(conn, actor=None, actor_email="cli", action="department.created",
                     target_type="department", target_id=1)


def test_the_key_log_lines_name_the_guides_commands(ws, monkeypatch, caplog):
    conn = db()
    try:
        _write(conn)
        monkeypatch.setenv(audit.ENV_AUDIT_KEY, OTHER_KEY)
        with caplog.at_level(logging.ERROR, logger="nerva.workspace.audit"):
            assert audit.startup_key_check() == "mismatch"
            with pytest.raises(audit.AuditKeyMismatch):
                _write(conn)
        start, refusal = _errors(caplog)
        assert f"{GUIDE_FORM} check" in start and "PILOT_GUIDE §17" in start
        assert f"{GUIDE_FORM} check" in refusal and f"{GUIDE_FORM} audit-rekey" in refusal
        caplog.clear()
        monkeypatch.delenv(audit.ENV_AUDIT_KEY)
        (ws.key_dir / audit.KEY_FILE).unlink()
        with (caplog.at_level(logging.ERROR, logger="nerva.workspace.audit"),
              pytest.raises(audit.AuditKeyMissing)):
            _write(conn)
        assert f"{GUIDE_FORM} check" in caplog.text
        assert BARE_FORM not in caplog.text
    finally:
        conn.close()


async def test_the_scheduler_pause_names_the_guides_check(ws, monkeypatch, caplog):
    conn = db()
    try:
        _write(conn)
    finally:
        conn.close()
    monkeypatch.setenv(audit.ENV_AUDIT_KEY, OTHER_KEY)
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.scheduler"):
        await scheduler.WorkspaceScheduler().tick()
    assert f"{GUIDE_FORM} check" in caplog.text and BARE_FORM not in caplog.text
