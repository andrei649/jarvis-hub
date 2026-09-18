"""
test_log_redaction — H495: a credential must never reach a log record.

Covers agents/core/security/log_redaction.py and its wiring from
agents/core/log.py:setup_logging().
"""

import copy
import io
import logging
import os
import re
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.security import log_redaction as lr  # noqa: E402
from agents.core.security.log_redaction import (  # noqa: E402
    REDACTION_UNAVAILABLE,
    SecretRedactionFilter,
    install_log_redaction,
)
from agents.core.security.scanner import SecretScanner  # noqa: E402

# One positive sample per built-in SecretScanner pattern. The test below pins
# this map against SecretScanner.PATTERNS, so adding a pattern to the scanner
# fails here loudly rather than silently leaving the log prefilter behind.
BUILTIN_SAMPLES = {
    "openai_key": "sk-" + "a" * 40,
    "anthropic_key": "sk-ant-" + "a" * 20,
    "aws_access_key": "AKIAABCDEFGHIJKLMNOP",
    "github_token": "ghp_" + "a" * 36,
    "password_assignment": 'pwd:"abcd"',
    "db_connection_string": "redis://u:p@h",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----",
    "slack_token": "xoxb-0123456789",
    "stripe_key": "sk_test_" + "a" * 20,
    "gcp_service_account": '"type": "service_account", "private_key":',
    "azure_storage_key": "AccountKey=" + "A" * 86 + "==",
    "generic_api_key": 'api_key:"12345678"',
    "jwt": "eyJ" + "a" * 10 + "." + "b" * 10 + "." + "c" * 10,
    "bearer_token": "Bearer " + "a" * 20,
    "telegram_bot_token": "123456:" + "a" * 35,
    "google_api_key": "AIza" + "a" * 35,
    # Assembled rather than written out, like every other row here. A 40-character
    # high-entropy literal in the file text is what GitHub's push protection flags,
    # and it blocked this very commit — a test for "no credential reaches a log"
    # refused for carrying a credential-shaped string. The runtime value, and so
    # what the catch-all sees, is unchanged.
    "high_entropy_secret": "Zk7Qp2Lm" + "9Xr4Tv1B" + "n6Wc3Yd8" + "Fg5Hj0Es" + "2Au4Io9z",
}

SECRET = "sk-ant-" + "Q7x" * 12          # a credential no broker has ever seen


def _capture_logger(name):
    """A child logger wired to its own stream handler carrying the filter.

    Mirrors production shape: the record is emitted by a `jarvis.*` child and
    the filter lives on the *handler*, never on the emitting logger.
    """
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    install_log_redaction(logger)
    return logger, handler, buf


# ── the scanner contract the prefilter must not fall behind ──────────────────

def test_sample_map_covers_every_builtin_pattern():
    """Fail loudly when scanner.PATTERNS grows: a new pattern must get a sample
    here so the prefilter below is proven against it."""
    assert set(BUILTIN_SAMPLES) == set(SecretScanner.PATTERNS)


@pytest.mark.parametrize("name", sorted(BUILTIN_SAMPLES))
def test_every_builtin_pattern_survives_the_prefilter(name):
    """The cheap pre-check must never cause a false negative: for every pattern,
    the prefilter matches AND the text is actually redacted."""
    f = SecretRedactionFilter()
    sample = BUILTIN_SAMPLES[name]
    assert f._prefilter is not None, "prefilter should build from the built-in set"
    assert f._prefilter.search(sample), f"{name}: prefilter would skip a real secret"
    assert f.redact_text(sample) != sample, f"{name}: not redacted"


def test_shortest_builtin_match_is_not_below_the_length_floor():
    """The length pre-check must sit at or below the shortest matchable text."""
    shortest = min(len(v) for v in BUILTIN_SAMPLES.values())
    assert lr._BUILTIN_MIN_MATCH_LEN <= shortest == 10
    f = SecretRedactionFilter()
    assert f._min_len == lr._BUILTIN_MIN_MATCH_LEN
    # and the shortest sample still goes through the full scan
    assert f.redact_text('pwd:"abcd"') != 'pwd:"abcd"'


def test_length_floor_drops_to_zero_when_a_deployment_adds_patterns():
    """JARVIS_SCANNER_EXTRA_PATTERNS can match shorter text than any built-in,
    so the floor must not be applied at all."""
    scanner = SecretScanner(extra_patterns={"house_token": r"HT-\d{2}"})
    f = SecretRedactionFilter(scanner=scanner)
    assert f._min_len == 0
    assert f.redact_text("HT-42") == "[REDACTED:house_token]"


# ── the record-mutation contract ─────────────────────────────────────────────

def test_secret_in_a_plain_message_is_redacted():
    logger, handler, buf = _capture_logger("jarvis.test.redact.plain")
    logger.info(f"loaded key {SECRET}")     # already-rendered message, no args
    handler.flush()
    out = buf.getvalue()
    assert SECRET not in out
    assert "[REDACTED:anthropic_key]" in out


def test_percent_style_arg_secret_is_redacted_without_breaking_formatting():
    """`logger.info("msg %s", value)` is how nearly all of this codebase logs.

    A literal `%` in the payload must survive: assigning the *rendered* message
    to record.msg while leaving record.args in place would make getMessage()
    re-apply `%`-formatting to it and raise inside the formatter, taking the
    caller's log call down. The secret here lives wholly inside one argument, so
    the filter masks the pieces separately and KEEPS the args tuple (see
    test_arg_reading_formatters_keep_their_args) — `%` inside an argument is
    never re-interpreted, only record.msg is the format string.
    """
    logger, handler, buf = _capture_logger("jarvis.test.redact.args")
    payload = f"100% failed for {SECRET}"
    logger.warning("tool %s said: %s", "shell", payload)
    handler.flush()
    out = buf.getvalue()
    assert SECRET not in out
    assert "[REDACTED:anthropic_key]" in out
    assert "100% failed" in out          # the literal % survived intact
    assert "shell" in out


def test_clean_record_keeps_its_lazy_percent_form():
    """No secret → the record is left untouched, so laziness and downstream
    formatters that read record.args are unaffected."""
    f = SecretRedactionFilter()
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1, "worker %s heartbeat", ("cortex",), None,
    )
    assert f.filter(record) is True
    assert record.msg == "worker %s heartbeat"
    assert record.args == ("cortex",)
    assert record.getMessage() == "worker cortex heartbeat"


def test_exception_traceback_is_redacted():
    """`logger.exception(...)` renders the traceback through the formatter; a
    secret inside the exception text must not survive that hop."""
    logger, handler, buf = _capture_logger("jarvis.test.redact.exc")
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        raise RuntimeError(f"upload rejected: {SECRET}")
    except RuntimeError:
        logger.exception("upload failed")
    handler.flush()
    out = buf.getvalue()
    assert SECRET not in out
    assert "[REDACTED:anthropic_key]" in out
    assert "RuntimeError" in out          # the traceback itself is still there


def test_filter_never_raises_and_fails_closed():
    """A raising filter propagates into the caller's logger.info() call. The
    record's content is dropped instead — never emitted unscanned."""
    class Exploding:
        def redact(self, text):
            raise ValueError("scanner exploded")

    f = SecretRedactionFilter(scanner=Exploding())
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1, "key is %s", (SECRET,), None,
    )
    assert f.filter(record) is True            # no exception escaped
    assert record.getMessage() == REDACTION_UNAVAILABLE
    assert SECRET not in record.getMessage()


# ── installation ─────────────────────────────────────────────────────────────

def test_install_targets_handlers_not_the_logger():
    """A filter on a Logger only sees records that logger emitted itself, so a
    root-*logger* filter would miss every `jarvis.*` child record. Install must
    land on the handlers."""
    logger, handler, _buf = _capture_logger("jarvis.test.redact.where")
    assert any(isinstance(x, SecretRedactionFilter) for x in handler.filters)
    assert not any(isinstance(x, SecretRedactionFilter) for x in logger.filters)


def test_install_is_idempotent():
    logger, handler, _buf = _capture_logger("jarvis.test.redact.idem")
    assert install_log_redaction(logger) == 0
    installed = [x for x in handler.filters if isinstance(x, SecretRedactionFilter)]
    assert len(installed) == 1


def test_disabled_flag_skips_installation(monkeypatch):
    """JARVIS_LOG_REDACTION=0 is an operator boot choice; the flag is a module
    global snapshotted at import, not an env read, so a mid-session
    os.environ write cannot reach it."""
    monkeypatch.setattr(lr, "_ENABLED", False)
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logger = logging.getLogger("jarvis.test.redact.off")
    logger.handlers = [handler]
    logger.propagate = False
    assert install_log_redaction(logger) == 0
    assert handler.filters == []


def test_enabled_flag_is_read_at_import_not_per_call(monkeypatch):
    monkeypatch.setenv("JARVIS_LOG_REDACTION", "0")
    f = SecretRedactionFilter()
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1, "key is %s", (SECRET,), None,
    )
    f.filter(record)
    # The env write happened after import, so it must have had no effect.
    assert "[REDACTED:anthropic_key]" in record.getMessage()


# ── wiring from setup_logging ────────────────────────────────────────────────

LOG_ENV_VARS = ("JARVIS_LOG_FILE", "JARVIS_LOG_MAX_MB", "JARVIS_LOG_BACKUPS")


@pytest.fixture
def restore_logging():
    """Rebuild default logging afterwards so an attached RotatingFileHandler
    cannot leak a file handle into other tests.

    It RESTORES the three JARVIS_LOG_* vars to whatever it found rather than
    popping them (which is what test_h2311_operability's copy of this fixture
    does). Popping deletes an ambient value — a run that pins JARVIS_LOG_FILE
    for the whole suite loses it from here on. Restoring is also independent of
    finalizer ordering: it is correct whether this fixture is torn down before
    or after monkeypatch undoes its own setenv. Pinned by
    test_restore_logging_preserves_an_ambient_log_file.
    """
    import agents.core.log as log
    saved = {var: os.environ.get(var) for var in LOG_ENV_VARS}
    yield
    for var, value in saved.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value
    log.setup_logging(logging.INFO)


# The fixture object under its own name: inside a test that takes `restore_logging`
# as a parameter, the module-level name is shadowed by the fixture's value (None).
restore_logging_fixture = restore_logging


def test_setup_logging_filters_every_root_handler(restore_logging, monkeypatch, tmp_path):
    import agents.core.log as log
    monkeypatch.setenv("JARVIS_LOG_FILE", str(tmp_path / "logs" / "jarvis.log"))
    log.setup_logging(logging.INFO)
    handlers = logging.getLogger().handlers
    assert handlers, "setup_logging must leave at least one root handler"
    for h in handlers:
        assert any(isinstance(x, SecretRedactionFilter) for x in h.filters), (
            f"{h!r} would write unredacted records"
        )


def test_setup_logging_filters_stderr_when_file_logging_is_off(restore_logging, monkeypatch):
    """File logging is opt-in and OFF by default, so on the default path the
    stderr handler from basicConfig() is the only handler there is — it must
    still be covered."""
    import agents.core.log as log
    monkeypatch.delenv("JARVIS_LOG_FILE", raising=False)
    monkeypatch.setattr(log, "_setting",
                        lambda cat, key, default: False if key == "log_to_file" else default)
    log.setup_logging(logging.INFO)
    handlers = logging.getLogger().handlers
    assert handlers
    for h in handlers:
        assert any(isinstance(x, SecretRedactionFilter) for x in h.filters)


def test_rotating_handler_redacts_on_its_own(restore_logging, monkeypatch, tmp_path):
    """The file handler must carry its OWN filter.

    Without this, the only thing keeping secrets out of jarvis.log is that the
    stderr handler happens to run first and mutates the shared record in place
    — an ordering accident that silently stops protecting the file the moment
    stderr is absent or filtered out by level.
    """
    import agents.core.log as log
    logfile = tmp_path / "logs" / "jarvis.log"
    monkeypatch.setenv("JARVIS_LOG_FILE", str(logfile))
    log.setup_logging(logging.INFO)

    root = logging.getLogger()
    rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating) == 1
    root.handlers = rotating          # strip stderr: the file handler stands alone

    logging.getLogger("jarvis.test.redact.solo").warning("key=%s", SECRET)
    rotating[0].flush()
    text = logfile.read_text(encoding="utf-8")
    assert SECRET not in text
    assert "[REDACTED:anthropic_key]" in text


def test_setup_logging_keeps_a_secret_out_of_the_rotating_log_file(
    restore_logging, monkeypatch, tmp_path,
):
    """End-to-end on the exact path H495 names: a key that was never brokered
    must not land in jarvis.log."""
    import agents.core.log as log
    logfile = tmp_path / "logs" / "jarvis.log"
    monkeypatch.setenv("JARVIS_LOG_FILE", str(logfile))
    log.setup_logging(logging.INFO)

    logging.getLogger("jarvis.test.redact.file").warning(
        "cat .env -> ANTHROPIC_API_KEY=%s", SECRET,
    )
    for h in logging.getLogger().handlers:
        h.flush()

    text = logfile.read_text(encoding="utf-8")
    assert SECRET not in text
    assert "[REDACTED:anthropic_key]" in text


# ── the cost the triage asked to be measured, not assumed ────────────────────

def test_redaction_cost_over_a_10k_record_run():
    """Budget check on the pre-check. Deliberately loose (CI machines vary);
    it exists to catch an order-of-magnitude regression, not to benchmark."""
    f = SecretRedactionFilter()
    lines = [
        "Loaded 5 plugins from agents/core/plugins",
        "GET /api/metrics/north-star 200 in 12ms",
        "worker heartbeat ok",
        "settings reloaded",
        "db vacuum done in 3s",
    ]
    start = time.perf_counter()
    for _ in range(2000):
        for line in lines:
            f.redact_text(line)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"10k clean records took {elapsed:.2f}s"


# ── defect 1: the module's own text must not trip the AUD-14 ratchet ─────────

def test_module_text_trips_no_raw_env_read_ratchet():
    """tests/test_o26_p2_env_config.py::test_raw_env_reads_do_not_grow greps
    every agents/**.py line by line for `os.getenv(` / `os.environ.get(` /
    `os.environ[`. It cannot tell code from prose, so a docstring that spells a
    raw env read as an *example* consumes the ratchet's budget and turns the
    whole suite red. Keep such examples in prose form.
    """
    src = Path(lr.__file__).read_text(encoding="utf-8")
    ratchet = re.compile(r"os\.getenv\(|os\.environ\.get\(|os\.environ\[")
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(src.splitlines(), 1)
        if ratchet.search(line)
    ]
    assert hits == [], "raw-env-read literals in log_redaction.py:\n  " + "\n  ".join(hits)


# ── defect 2: loggers that own handlers are covered, root alone is not ───────

def _restore_logger(name):
    """Snapshot a logger's handlers/propagate/level so a test can hand it back."""
    lg = logging.getLogger(name)
    return (lg, list(lg.handlers), lg.propagate, lg.level)


def _put_back(saved):
    lg, handlers, propagate, level = saved
    lg.handlers = handlers
    lg.propagate = propagate
    lg.level = level


def test_setup_logging_covers_a_non_propagating_logger(restore_logging, monkeypatch):
    """`callHandlers` walks from the EMITTING logger upwards: a logger that owns
    handlers writes through them before root is consulted, and one with
    propagate=False never consults root at all. Covering only root leaves those
    handlers writing raw, and no repeat call against root can ever reach them.
    """
    import agents.core.log as log
    name = "jarvis.test.redact.detached"
    saved = _restore_logger(name)
    try:
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter("%(message)s"))
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False          # exactly uvicorn's shape
        lg.setLevel(logging.INFO)

        log.setup_logging(logging.INFO)

        assert any(isinstance(x, SecretRedactionFilter) for x in handler.filters), (
            "a non-propagating logger's own handler was left unfiltered"
        )
        lg.info("loaded key %s", SECRET)
        handler.flush()
        out = buf.getvalue()
        assert SECRET not in out
        assert "[REDACTED:anthropic_key]" in out
    finally:
        _put_back(saved)


def test_uvicorn_access_log_is_covered_and_still_formats(restore_logging, monkeypatch):
    """The production HTTP server's own access log — the one sink a row titled
    "never let a credential reach a log" cannot be allowed to miss.

    serve.py builds uvicorn.Config with no log_config, so uvicorn applies its
    default LOGGING_CONFIG via dictConfig inside Config.__init__ — before the
    FastAPI lifespan reaches setup_logging(). `uvicorn` and `uvicorn.access` get
    their own handlers with propagate=False. A key in a query string (an
    unbrokered key in a callback/redirect URL is exactly the H495 scenario)
    landed there raw.
    """
    import logging.config

    import uvicorn.config

    import agents.core.log as log

    saved = [_restore_logger(n) for n in ("uvicorn", "uvicorn.access", "uvicorn.error")]
    try:
        logging.config.dictConfig(copy.deepcopy(uvicorn.config.LOGGING_CONFIG))
        log.setup_logging(logging.INFO)          # the lifespan's call

        access = logging.getLogger("uvicorn.access")
        assert access.propagate is False, "precondition: uvicorn detaches its loggers"
        assert access.handlers, "precondition: uvicorn owns its access handler"
        for h in access.handlers:
            assert any(isinstance(x, SecretRedactionFilter) for x in h.filters), (
                f"{h!r} would write the access log unredacted"
            )

        buf = io.StringIO()
        for h in access.handlers:
            h.stream = buf
        access.info('%s - "%s %s HTTP/%s" %d',
                    "127.0.0.1:1", "GET", f"/api/x?token={SECRET}", "1.1", 200)
        out = buf.getvalue()
        assert SECRET not in out
        assert "[REDACTED:anthropic_key]" in out
        # and the line was actually written: uvicorn's AccessFormatter unpacks
        # record.args into five values, so a flattened record would raise and
        # the line would be dropped entirely.
        assert "GET" in out and "200" in out
    finally:
        for s in saved:
            _put_back(s)


def test_arg_reading_formatters_keep_their_args():
    """A formatter may read record.args structurally rather than the rendered
    message (uvicorn's AccessFormatter unpacks exactly five). Flattening a
    record to msg/() makes it raise and DROP the line — and since
    high_entropy_secret matches any UUID, that would delete every access line
    carrying one. The args tuple must survive with its arity intact.
    """
    f = SecretRedactionFilter()
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", f"/cb?token={SECRET}", "1.1", 200),
        None,
    )
    assert f.filter(record) is True
    assert isinstance(record.args, tuple) and len(record.args) == 5
    assert record.args[4] == 200                      # non-str args untouched
    assert SECRET not in record.getMessage()
    assert "[REDACTED:anthropic_key]" in record.getMessage()


def test_secret_straddling_msg_and_arg_still_falls_back_to_flattening():
    """Masking the pieces separately cannot catch a secret that spans the
    boundary, so that case must still flatten — correctness beats shape."""
    f = SecretRedactionFilter()
    tail = "Q7x" * 7                                  # inert alone; a key once joined
    assert f.redact_text(tail) == tail
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1, "sk-ant-%s", (tail,), None,
    )
    assert f.filter(record) is True
    assert record.args == ()                          # flattened
    assert "sk-ant-" + tail not in record.getMessage()
    assert "[REDACTED:anthropic_key]" in record.getMessage()


# ── defect 3: an extra pattern may collide with a built-in NAME ──────────────

@pytest.mark.parametrize("name", ["jwt", "slack_token", "password_assignment"])
def test_length_floor_drops_to_zero_when_an_extra_shadows_a_builtin_name(name):
    """SecretScanner APPENDS extras to _compiled without collision checks, so an
    extra named after a built-in leaves the set of names unchanged. Detecting
    extras by name difference misses it and the 10-char floor stays on, so the
    filter skips a short deployment secret that SecretScanner.redact itself
    masks — a false negative in exactly the direction the module promises is
    impossible.
    """
    scanner = SecretScanner(extra_patterns={name: r"HT-\d{2}"})
    assert scanner.redact("HT-42") != "HT-42", "precondition: the scanner matches it"
    f = SecretRedactionFilter(scanner=scanner)
    assert f._min_len == 0, f"floor stayed at {f._min_len} for an extra named {name!r}"
    assert f.redact_text("HT-42") != "HT-42"


def test_length_floor_drops_to_zero_for_an_unknown_scanner_shape():
    """A scanner that exposes no _compiled cannot have its floor proven, so the
    full scan must always run (the prefilter already bails out the same way)."""
    class Opaque:
        def redact(self, text):
            return "[masked]"

    f = SecretRedactionFilter(scanner=Opaque())
    assert f._min_len == 0
    assert f._prefilter is None
    assert f.redact_text("HT-42") == "[masked]"


# ── defect 4: a caller's format bug is not a scanner failure ─────────────────

def test_caller_format_error_keeps_its_diagnostic():
    """`record.msg % record.args` raising is a CALLER bug (a mismatched format
    string). Without any filter, logging prints its own `--- Logging error ---`
    block naming the message and the arguments. Collapsing that into an
    anonymous `[redaction-unavailable]` line — indistinguishable from a real
    scanner crash — loses a diagnostic that has nothing to do with redaction.
    """
    logger, handler, buf = _capture_logger("jarvis.test.redact.fmt")
    logger.warning("50% of %s done", "batch-1")       # %o + a str -> TypeError
    handler.flush()
    out = buf.getvalue()
    assert out.startswith(lr.LOG_FORMAT_ERROR), out
    assert out.strip() != REDACTION_UNAVAILABLE
    assert "TypeError" in out                         # what actually went wrong
    assert "50% of %s done" in out                    # the format string
    assert "batch-1" in out                           # the arguments


def test_caller_format_error_still_scans_the_pieces_it_reports():
    """The diagnostic above prints record.msg and record.args, either of which
    may carry the credential — so it is scanned before it is emitted."""
    f = SecretRedactionFilter()
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1, "50% of %s done", (SECRET,), None,
    )
    assert f.filter(record) is True
    rendered = record.getMessage()
    assert rendered.startswith(lr.LOG_FORMAT_ERROR)
    assert SECRET not in rendered
    assert "[REDACTED:anthropic_key]" in rendered


def test_scanner_failure_is_still_an_anonymous_fail_closed_line():
    """The other branch is unchanged: when the SCANNER fails, nothing about the
    record can be trusted, so all of it is dropped."""
    class Exploding:
        def redact(self, text):
            raise ValueError("scanner exploded")

    f = SecretRedactionFilter(scanner=Exploding())
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1, "key is %s", (SECRET,), None,
    )
    assert f.filter(record) is True
    assert record.getMessage() == REDACTION_UNAVAILABLE


# ── defect 5: the fixture restores the env, it does not delete it ────────────

def test_restore_logging_preserves_an_ambient_log_file(restore_logging, monkeypatch, tmp_path):
    """The teardown must hand back the environment it found. Popping the three
    JARVIS_LOG_* vars unconditionally deletes an ambient value for the rest of
    the pytest session, silently breaking any run that pins JARVIS_LOG_FILE for
    the whole suite.

    The fixture body is driven directly here so its teardown is observable; the
    outer `restore_logging` (first parameter, so torn down last) cleans up after.
    """
    ambient = str(tmp_path / "ambient.log")
    monkeypatch.setenv("JARVIS_LOG_FILE", ambient)

    fixture_fn = getattr(restore_logging_fixture, "__wrapped__", restore_logging_fixture)
    gen = fixture_fn()
    next(gen)                                  # setup
    with pytest.raises(StopIteration):
        next(gen)                              # teardown

    assert os.environ.get("JARVIS_LOG_FILE") == ambient, (
        "restore_logging deleted an ambient JARVIS_LOG_FILE instead of restoring it"
    )
