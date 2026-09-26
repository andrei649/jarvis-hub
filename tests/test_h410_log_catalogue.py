"""H410 — no credential or Romanian identifier reaches a log, from any process.

The H495 filter masks the credentials SecretScanner knows by their shape (vendor
prefixes, quoted ``api_key="…"``, long high-entropy runs). What it let through:
an opaque token that matches no vendor shape, carried by a query parameter
(``?access_token=``), an unquoted body key (``client_secret=``), or a header
(``X-Api-Key:``, ``Authorization: Token …``); a CNP or an IBAN, which only the PII
scanner knows; and every record written by the coordinator and the MCP stdio
bridge, which configured logging with a bare ``basicConfig``. ``core/log_catalogue``
adds a second filter, after the first, on every handler ``setup_logging`` covers,
and both entry points now install both.
"""
from __future__ import annotations

import importlib.util
import io
import logging
from pathlib import Path

import pytest

from agents.core import log_catalogue as cat
from agents.core.security import log_redaction as lr

REPO = Path(__file__).resolve().parents[1]
CNP = "1800101221144"            # a valid CNP (control digit checked)
IBAN = "RO49AAAA1B31007593840000"  # the standard example IBAN (mod-97 checked)


def _valid_cnp() -> str:
    from agents.core.security.scanner import is_valid_cnp

    assert is_valid_cnp(CNP)
    return CNP


def _logger(name: str):
    """A child logger on its own stream handler, covered the way setup_logging covers
    every handler: the H495 filter first, then the catalogue."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    lr.install_log_redaction(logger)
    cat.install_catalogue_redaction(logger)
    return logger, handler, buf


# ── what the H495 scanner let through ────────────────────────────────────────────

@pytest.mark.parametrize("line,secret", [
    ("GET /cb?access_token=abcdef1234567890", "abcdef1234567890"),
    ("GET /cb?state=x&access_token=abcdef1234567890&next=/", "abcdef1234567890"),
    ("callback ?api_key=abcd1234efgh5678", "abcd1234efgh5678"),
    ("GET /x?apikey=abcd1234efgh5678 HTTP/1.1", "abcd1234efgh5678"),
    ("GET /login?password=hunter2 HTTP/1.1", "hunter2"),
    ("GET /s3?X-Amz-Signature=0a1b2c3d4e5f", "0a1b2c3d4e5f"),
    ("GET /hook?token=abc", "abc"),
    ("body client_secret=Zx81kdfLq0PaW3", "Zx81kdfLq0PaW3"),
    ("form refresh_token=Zx81kdfLq0PaW3&grant_type=refresh_token", "Zx81kdfLq0PaW3"),
    ('json {"access_token": "Zx81kdfLq0PaW3", "expires_in": 3600}', "Zx81kdfLq0PaW3"),
    ("dict {'client_secret': 'Zx81kdfLq0PaW3'}", "Zx81kdfLq0PaW3"),
    ('kw client_secret="Zx81kdfLq0PaW3"', "Zx81kdfLq0PaW3"),
    ("X-Api-Key: 9f8e7d6c5b4a3f2e", "9f8e7d6c5b4a3f2e"),
    ("headers {'x-api-key': '9f8e7d6c5b4a3f2e'}", "9f8e7d6c5b4a3f2e"),
    ("X-User-Token: 9f8e7d6c5b4a3f2e", "9f8e7d6c5b4a3f2e"),
    ("x-goog-api-key: 9f8e7d6c5b4a3f2e", "9f8e7d6c5b4a3f2e"),
    ("Authorization: Token abcd1234efgh5678ijkl", "abcd1234efgh5678ijkl"),
    ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
    ("Authorization: Bearer short1", "short1"),
    ("{'Authorization': 'Token abcd1234efgh5678ijkl'}", "abcd1234efgh5678ijkl"),
    ("Authorization: abcd1234efgh5678ijkl", "abcd1234efgh5678ijkl"),
    ("Cookie: session=abc123; theme=dark", "session=abc123"),
    ("Set-Cookie: sid=abc123def; HttpOnly", "sid=abc123def"),
])
def test_an_opaque_credential_is_masked_by_its_name(line, secret):
    logger, _, buf = _logger("jarvis.test.h410.names")
    logger.info(line)
    out = buf.getvalue()
    assert secret not in out, out
    assert "[REDACTED:" in out


def test_the_masked_line_keeps_everything_around_the_credential():
    logger, _, buf = _logger("jarvis.test.h410.keep")
    logger.info("GET /cb?state=abc&access_token=abcdef1234567890&next=/home")
    out = buf.getvalue().strip()
    assert out == "GET /cb?state=abc&access_token=[REDACTED:query_secret]&next=/home"
    buf.truncate(0), buf.seek(0)
    logger.info("Authorization: Token abcd1234efgh5678ijkl")
    assert buf.getvalue().strip() == "Authorization: Token [REDACTED:auth_header]"


@pytest.mark.parametrize("line", [
    "authorization failed for user bob",
    "Authorization: denied",
    "settings key=llm.model changed",
    "GET /api/settings?key=llm.model HTTP/1.1",
    "exit code=1 after 3 s",
    "no token given; token=None",
    "the order 4000000000000 shipped",           # 13 digits, not a CNP
    "RO49AAAA1B31007593840001",                  # IBAN-shaped, checksum fails
    "an api key is required",
])
def test_ordinary_text_is_left_alone(line):
    logger, _, buf = _logger("jarvis.test.h410.plain")
    logger.info(line)
    assert buf.getvalue().strip() == line


def test_a_cnp_and_an_iban_are_masked_only_when_their_checksum_holds():
    logger, _, buf = _logger("jarvis.test.h410.pii")
    cnp = _valid_cnp()
    logger.info("client %s pays from %s", cnp, IBAN)
    logger.info("spaced RO49 AAAA 1B31 0075 9384 0000 too")
    out = buf.getvalue()
    assert cnp not in out and IBAN not in out and "RO49 AAAA 1B31" not in out
    assert "[REDACTED:ro_cnp]" in out and out.count("[REDACTED:ro_iban]") == 2


def test_an_access_log_line_keeps_its_five_arguments():
    """uvicorn's AccessFormatter unpacks five args: the path is masked in place."""
    logger, handler, buf = _logger("jarvis.test.h410.access")
    records = []
    handler.addFilter(lambda r: records.append(r) or True)
    logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/cb?access_token=abcdef123456", "1.1", 200)
    (record,) = records
    assert len(record.args) == 5 and record.args[4] == 200
    assert "abcdef123456" not in buf.getvalue() and "GET" in buf.getvalue()


def test_a_traceback_is_masked_too():
    logger, _, buf = _logger("jarvis.test.h410.exc")
    try:
        raise RuntimeError("upstream said: X-Api-Key: 9f8e7d6c5b4a3f2e rejected")
    except RuntimeError:
        logger.exception("call failed")
    assert "9f8e7d6c5b4a3f2e" not in buf.getvalue()


def test_the_log_redaction_switch_turns_the_catalogue_off_too(monkeypatch):
    monkeypatch.setattr(lr, "_ENABLED", False)
    logger, _, buf = _logger("jarvis.test.h410.off")
    logger.info("X-Api-Key: 9f8e7d6c5b4a3f2e")
    assert "9f8e7d6c5b4a3f2e" in buf.getvalue()


def test_a_scanner_that_fails_drops_the_record_content(monkeypatch):
    logger, _, buf = _logger("jarvis.test.h410.fail")

    def boom(self, text):
        raise RuntimeError("scanner down")

    monkeypatch.setattr(cat.CatalogueScanner, "redact", boom)
    logger.info("X-Api-Key: 9f8e7d6c5b4a3f2e")
    assert buf.getvalue().strip() == lr.REDACTION_UNAVAILABLE


def test_the_log_reader_masks_what_was_written_before_the_catalogue():
    """H145 re-redacts every line it serves; lines written before H410 (or by a process
    that was not covered) still carry named tokens and CNP/IBAN, so it runs the
    catalogue too."""
    from agents.core import log_tail

    redact = log_tail._redactor()
    line = f"GET /cb?access_token=abcdef1234567890 client {_valid_cnp()} X-Api-Key: 9f8e7d6c5b4a3f2e"
    out = redact(line)
    for secret in ("abcdef1234567890", CNP, "9f8e7d6c5b4a3f2e"):
        assert secret not in out
    assert redact("an ordinary line") == "an ordinary line"


# ── where it is installed ────────────────────────────────────────────────────────

def _has(handler, name):
    return any(type(f).__name__ == name for f in handler.filters)


def test_setup_logging_covers_every_handler_with_both_filters_once(monkeypatch):
    import agents.core.log as log

    monkeypatch.delenv("JARVIS_LOG_FILE", raising=False)
    detached = logging.getLogger("jarvis.test.h410.detached")
    own = logging.StreamHandler(io.StringIO())
    detached.handlers, detached.propagate = [own], False
    log.setup_logging(logging.INFO)
    log.setup_logging(logging.INFO)                   # idempotent
    for handler in logging.getLogger().handlers + [own]:
        assert _has(handler, "SecretRedactionFilter") and _has(handler, "CatalogueRedactionFilter")
        names = [type(f).__name__ for f in handler.filters]
        assert names.count("CatalogueRedactionFilter") == 1
        assert names.index("SecretRedactionFilter") < names.index("CatalogueRedactionFilter")


def test_a_handler_that_refuses_the_filter_is_counted_and_named(caplog):
    class Refusing(logging.Handler):
        def addFilter(self, _f):
            raise RuntimeError("no")

        def emit(self, record):
            pass

    lonely = logging.getLogger("jarvis.test.h410.refusing")
    lonely.handlers, lonely.propagate = [Refusing()], False
    with caplog.at_level(logging.WARNING, logger=cat.logger.name):
        cat.install_catalogue_redaction_everywhere()
    assert cat.uncovered_handler_count() >= 1
    assert "NOT" in caplog.text and "catalogue" in caplog.text
    lonely.handlers = []
    cat.install_catalogue_redaction_everywhere()
    assert cat.uncovered_handler_count() == 0


@pytest.fixture
def fresh_root():
    """Call it for the root logger of a process that has not configured logging yet
    (basicConfig is a no-op on a root that already has handlers, and pytest attaches
    its own for the test's call phase, so they are taken off inside the test)."""
    root = logging.getLogger()
    saved: list = []

    def clear():
        saved.append((list(root.handlers), root.level))
        root.handlers = []
        return root

    yield clear
    if saved:
        for handler in root.handlers:
            handler.close()
        root.handlers, root.level = saved[0]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script,call", [
    ("scripts/coordinator.py", lambda m: m.configure_logging()),
    ("scripts/nerva_mcp_stdio.py", lambda m: m.configure_logging(verbose=False)),
])
def test_the_coordinator_and_the_mcp_bridge_log_through_both_filters(script, call, fresh_root):
    """Both called a bare basicConfig and wrote every record unredacted."""
    module = _load(REPO / script, "h410_" + Path(script).stem)
    root = fresh_root()
    call(module)
    handlers = root.handlers
    assert handlers
    for handler in handlers:
        assert _has(handler, "SecretRedactionFilter") and _has(handler, "CatalogueRedactionFilter")
    src = (REPO / script).read_text(encoding="utf-8")
    assert "configure_logging(" in src.split("def main", 1)[1]


def test_the_mcp_bridge_still_logs_to_stderr_only(fresh_root, capsys):
    """Its stdout is the protocol channel: nothing may be written there."""
    import sys

    module = _load(REPO / "scripts/nerva_mcp_stdio.py", "h410_mcp_stderr")
    root = fresh_root()
    module.configure_logging(verbose=True)
    assert root.level == logging.DEBUG and root.handlers
    for handler in root.handlers:
        assert getattr(handler, "stream", None) is sys.stderr
    logging.getLogger("jarvis.test.h410.bridge").info("X-Api-Key: 9f8e7d6c5b4a3f2e")
    for handler in root.handlers:
        handler.flush()
    out, err = capsys.readouterr()
    assert out == "" and "9f8e7d6c5b4a3f2e" not in err
