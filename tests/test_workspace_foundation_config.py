"""Workspace configuration parsing and the setup-code file lifecycle (spec §3)."""

from __future__ import annotations

import logging
import os
import stat

import pytest

from agents.core.workspace import config
from tests.support.workspace_fixtures import ws  # noqa: F401  (pytest fixture)

MIB = 1024 * 1024


@pytest.mark.parametrize(("raw", "expected"), [
    (None, False), ("1", True), ("on", True), ("TRUE", True), ("0", False), ("off", False),
    ("maybe", False), ("", False),
])
def test_enabled_reads_the_flag_at_call_time(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(config.ENV_ENABLED, raising=False)
    else:
        monkeypatch.setenv(config.ENV_ENABLED, raw)
    assert config.enabled() is expected


@pytest.mark.parametrize(("raw", "expected"), [
    (None, "auto"), ("", "auto"), ("auto", "auto"), (" AUTO ", "auto"), ("1", "on"),
    ("true", "on"), ("on", "on"), ("0", "off"), ("false", "off"), ("off", "off"),
])
def test_cookie_secure_mode(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(config.ENV_COOKIE_SECURE, raising=False)
    else:
        monkeypatch.setenv(config.ENV_COOKIE_SECURE, raw)
    assert config.cookie_secure_mode() == expected


def test_cookie_secure_junk_is_auto_with_one_warning_naming_the_variable(monkeypatch, caplog):
    monkeypatch.setattr(config, "_warned_cookie_values", set())
    monkeypatch.setenv(config.ENV_COOKIE_SECURE, "sometimes")
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.config"):
        assert config.cookie_secure_mode() == "auto"
        assert config.cookie_secure_mode() == "auto"
    warnings = [r for r in caplog.records if config.ENV_COOKIE_SECURE in r.getMessage()]
    assert len(warnings) == 1
    assert "sometimes" not in warnings[0].getMessage()


@pytest.mark.parametrize(("raw", "expected_mb"), [
    (None, 25), ("10", 10), ("200", 200), ("500", 200), ("0", 25), ("-3", 25), ("abc", 25),
])
def test_max_upload_bytes(monkeypatch, raw, expected_mb):
    if raw is None:
        monkeypatch.delenv(config.ENV_MAX_UPLOAD_MB, raising=False)
    else:
        monkeypatch.setenv(config.ENV_MAX_UPLOAD_MB, raw)
    assert config.max_upload_bytes() == expected_mb * MIB


@pytest.mark.parametrize(("raw", "hours"), [(None, 12), ("3", 3), ("168", 168), ("500", 168),
                                            ("0", 12), ("x", 12)])
def test_session_idle_seconds(monkeypatch, raw, hours):
    if raw is None:
        monkeypatch.delenv(config.ENV_SESSION_IDLE_HOURS, raising=False)
    else:
        monkeypatch.setenv(config.ENV_SESSION_IDLE_HOURS, raw)
    assert config.session_idle_seconds() == hours * 3600


@pytest.mark.parametrize(("raw", "days"), [(None, 7), ("1", 1), ("90", 90), ("1000", 90), ("0", 7)])
def test_session_max_seconds(monkeypatch, raw, days):
    if raw is None:
        monkeypatch.delenv(config.ENV_SESSION_MAX_DAYS, raising=False)
    else:
        monkeypatch.setenv(config.ENV_SESSION_MAX_DAYS, raw)
    assert config.session_max_seconds() == days * 86400


@pytest.mark.parametrize(("raw", "slots"), [(None, 2), ("1", 1), ("16", 16), ("100", 16), ("0", 2)])
def test_max_concurrent_llm(monkeypatch, raw, slots):
    if raw is None:
        monkeypatch.delenv(config.ENV_MAX_CONCURRENT_LLM, raising=False)
    else:
        monkeypatch.setenv(config.ENV_MAX_CONCURRENT_LLM, raw)
    assert config.max_concurrent_llm() == slots


def test_sso_needs_both_header_and_key(monkeypatch):
    monkeypatch.delenv(config.ENV_SSO_HEADER, raising=False)
    monkeypatch.delenv(config.ENV_SSO_KEY, raising=False)
    assert config.sso_configured() is False
    monkeypatch.setenv(config.ENV_SSO_HEADER, "  X-Forwarded-Email ")
    assert config.sso_header() == "X-Forwarded-Email"
    assert config.sso_configured() is False
    monkeypatch.setenv(config.ENV_SSO_KEY, " shared ")
    assert config.sso_secret() == "shared"
    assert config.sso_configured() is True


@pytest.mark.parametrize(("raw", "expected"), [(None, True), ("0", False), ("off", False),
                                               ("junk", True), ("1", True)])
def test_scheduler_enabled_defaults_on(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(config.ENV_SCHEDULER, raising=False)
    else:
        monkeypatch.setenv(config.ENV_SCHEDULER, raw)
    assert config.scheduler_enabled() is expected


def test_workspace_dir_is_created_private_under_the_data_root(ws):
    path = config.workspace_dir()
    assert path == ws.data_dir / "business"
    assert path.is_dir()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_setup_code_from_env_writes_no_file(ws, monkeypatch):
    monkeypatch.setenv(config.ENV_SETUP_CODE, "  from-the-env  ")
    assert config.setup_code() == "from-the-env"
    assert not config.setup_code_path().exists()


def test_generated_setup_code_lifecycle(ws, monkeypatch, caplog):
    monkeypatch.delenv(config.ENV_SETUP_CODE)
    with caplog.at_level(logging.WARNING, logger="nerva.workspace.config"):
        code = config.setup_code()
    path = config.setup_code_path()
    assert len(code) >= 20
    assert path.read_bytes().decode("utf-8") == code
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert config.setup_code() == code, "a second call reads the same file"
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert str(path) in messages
    assert code not in messages, "the code itself is never logged"
    assert [p.name for p in path.parent.iterdir() if p.name.startswith(".")] == [], "no temp files"
    config.clear_setup_code()
    assert not path.exists()
    config.clear_setup_code()  # idempotent
    assert config.setup_code() != code, "a new code after the old one is consumed"


def test_empty_setup_code_file_is_replaced(ws, monkeypatch):
    monkeypatch.delenv(config.ENV_SETUP_CODE)
    path = config.setup_code_path()
    config.workspace_dir()
    path.write_bytes(b"")
    code = config.setup_code()
    assert code and path.read_bytes().decode("utf-8") == code


def test_create_private_file_keeps_the_first_writer(tmp_path):
    target = tmp_path / "nested" / "secret.txt"
    assert config.create_private_file(target, b"first") == b"first"
    assert config.create_private_file(target, b"second") == b"first"
    assert target.read_bytes() == b"first"
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert sorted(p.name for p in target.parent.iterdir()) == ["secret.txt"]


def test_create_private_file_without_hard_links_falls_back_to_o_excl(tmp_path, monkeypatch):
    def no_links(src, dst):
        raise OSError("hard links not supported")

    monkeypatch.setattr(config.os, "link", no_links)
    target = tmp_path / "key"
    assert config.create_private_file(target, b"abc") == b"abc"
    assert config.create_private_file(target, b"xyz") == b"abc"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["key"]


# ── spec §6 numbers, pinned as literals (review T4) ──────────────────────────────────
# The behaviour tests loop over the module constants, so a changed constant would move the
# test with it; these pins make a change to a documented limit fail until the spec (and
# PILOT_GUIDE §12) say the same.

def test_the_spec_limits_are_the_documented_numbers():
    from agents.core.routers import workspace_chat, workspace_documents
    from agents.core.workspace import auth, documents, extract, reports

    assert (auth.LOGIN_EMAIL_LIMIT, auth.LOGIN_IP_LIMIT, auth.LOGIN_WINDOW_SECONDS) == (5, 20, 900)
    assert (auth.SETUP_IP_LIMIT, auth.SETUP_GLOBAL_LIMIT, auth.SETUP_WINDOW_SECONDS) == (10, 50, 3600)
    assert (auth.INVITE_IP_LIMIT, auth.INVITE_WINDOW_SECONDS) == (30, 3600)
    assert auth.INVITE_TTL_SECONDS == 72 * 3600
    assert workspace_chat.CHAT_RATE_LIMIT == 30
    assert reports.RUNS_PER_HOUR == 10
    assert (documents.UPLOADS_PER_HOUR, documents.PARALLEL_UPLOADS_PER_USER,
            documents.PARALLEL_RETRY_SECONDS) == (60, 3, 5)
    assert documents.STALE_PROCESSING_SECONDS == 600
    assert (extract.MAX_XML_NODES, extract.MAX_XML_DEPTH) == (500_000, 256)
    assert workspace_documents.DOWNLOAD_CSP == SPEC_ATTACHMENT_CSP
    assert reports.EXPORT_CSP == SPEC_ATTACHMENT_CSP


#: spec §6 "Headers": HTML report export and file downloads.
SPEC_ATTACHMENT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"

