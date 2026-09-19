"""
test_log_redaction — H495: a credential must never reach a log record.

Covers agents/core/security/log_redaction.py and its wiring from
agents/core/log.py:setup_logging().
"""

import copy
import importlib
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
    _drop_redaction_filters()


def _drop_redaction_filters() -> None:
    """Take the process-wide redactor back off on the way out.

    `setup_logging()` installs a `SecretRedactionFilter` on EVERY handler of EVERY
    logger in the process — that is the point of `install_log_redaction_everywhere`
    — and nothing here removed it, so a pytest worker that ran this file carried a
    live redactor into every test that followed it.

    It is not inert. The scanner's `high_entropy_secret` pattern matches an
    ordinary pytest tmp path, so under `-n auto --dist loadfile`
    `tests/test_soul_injection_guard.py::test_a_truncated_soul_logs_a_warning_naming_the_path`
    received its own warning as `truncated: [REDACTED:high_entropy_secret].md` and
    went red — a real cross-file interaction, found by running the two files
    together, not a flake.
    """
    loggers = [logging.getLogger()]
    loggers += [obj for obj in logging.Logger.manager.loggerDict.values()
                if isinstance(obj, logging.Logger)]
    for lg in loggers:
        for handler in list(getattr(lg, "handlers", ()) or ()):
            for installed in list(getattr(handler, "filters", ()) or ()):
                if _is_redactor(installed):
                    handler.removeFilter(installed)


def _is_redactor(obj) -> bool:
    """By class NAME, not `isinstance` — see `tests/conftest.py`.

    This repo imports both as `agents.core.*` and as `core.*`, so one source file
    becomes two module objects with two distinct classes. An `isinstance` check
    written against one path reports a handler clean while the other path's filter
    sits on it, which is exactly how a redactor survived the first attempt at this
    cleanup.
    """
    cls = type(obj)
    return (cls.__name__ == "SecretRedactionFilter"
            and cls.__module__.endswith("security.log_redaction"))


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


@pytest.mark.parametrize("path", [
    "/login?pwd=",                       # empty value: matches nothing on its own
    "/admin?password=",
    "/x?passwd:",
    '/z?api_key="12345678',              # the access line's own quote closes it
])
def test_a_straddling_secret_does_not_delete_the_access_line(restore_logging, path):
    """The production access log, through uvicorn's real config — the defect an
    unauthenticated client could trigger on any route.

    A scanner pattern can match ACROSS the join between an argument and a
    literal of the format string while matching NEITHER piece alone:
    password_assignment's `\\s*[=:]\\s*` jumps the space
    '%s - "%s %s HTTP/%s" %d' puts between full_path and `HTTP/`. Per-piece
    masking then leaves the rendered line dirty, and flattening the record to
    msg/() costs AccessFormatter the five values it unpacks — it raises,
    Handler.handleError swallows it, and THE LINE IS GONE. Appending `?pwd=` to
    any request would erase its own access-log entry (plus a traceback on
    stderr). The line must survive, redacted.
    """
    import logging.config

    import uvicorn.config

    import agents.core.log as log

    saved = [_restore_logger(n) for n in ("uvicorn", "uvicorn.access", "uvicorn.error")]
    try:
        logging.config.dictConfig(copy.deepcopy(uvicorn.config.LOGGING_CONFIG))
        log.setup_logging(logging.INFO)          # the lifespan's call

        access = logging.getLogger("uvicorn.access")
        buf = io.StringIO()
        for h in access.handlers:
            h.stream = buf
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", path, "1.1", 200)
        out = buf.getvalue()

        assert out.strip(), f"the access line for {path!r} was DROPPED entirely"
        assert "[REDACTED:" in out, f"nothing was masked, so {path!r} leaked: {out!r}"
        assert path.split("?", 1)[1] not in out   # the straddling text is gone
        assert "127.0.0.1:1" in out and "200" in out and "GET" in out
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


def test_secret_straddling_msg_and_arg_is_masked_whole_not_flattened():
    """Masking the pieces separately cannot catch a secret that spans the
    boundary — but flattening the record is what DROPS the line on an
    args-reading formatter, so the argument feeding the join is masked whole
    and the tuple survives. Correctness beats shape, and here it costs no shape.
    """
    f = SecretRedactionFilter()
    tail = "Q7x" * 7                                  # inert alone; a key once joined
    assert f.redact_text(tail) == tail
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1, "sk-ant-%s", (tail,), None,
    )
    assert f.filter(record) is True
    assert record.args == ("[REDACTED:anthropic_key]",)   # arity kept, arg masked
    assert "sk-ant-" + tail not in record.getMessage()
    assert "[REDACTED:anthropic_key]" in record.getMessage()


def test_several_straddles_in_one_record_keep_the_args_too():
    """No single argument cleans a record that straddles twice, so the masking
    goes on argument by argument rather than giving up and flattening — the
    arity is what an args-reading formatter needs, whichever argument carried
    the secret."""
    f = SecretRedactionFilter()
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1,
        "%s HTTP/%s and %s HTTP/%s",
        ("/a?pwd=", "1.1", "/b?pwd=", "1.1"),
        None,
    )
    assert f.filter(record) is True
    assert isinstance(record.args, tuple) and len(record.args) == 4
    rendered = record.getMessage()
    assert "pwd=" not in rendered
    assert f.redact_text(rendered) == rendered


def test_a_straddle_no_masking_can_clean_still_falls_back_to_flattening():
    """The fallback is still there for the case masking cannot reach: with
    `pwd=` in the FORMAT STRING, password_assignment matches whatever non-space
    run follows it — the mask included — so no argument can be replaced to make
    the joined line clean. The record flattens and the secret still goes.
    """
    f = SecretRedactionFilter()
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1, "pwd=%s", ("hunter2",), None,
    )
    assert f.filter(record) is True
    assert record.args == ()                          # flattened
    assert "hunter2" not in record.getMessage()
    assert "[REDACTED:password_assignment]" in record.getMessage()


def test_a_straddling_secret_keeps_the_args_arity_and_the_innocent_args():
    """The crossing case the two tests above bracket but never meet: a secret
    that straddles AND a record an args-reading formatter will unpack.

    `password_assignment`'s `\\s*[=:]\\s*` jumps the space uvicorn's
    '%s - "%s %s HTTP/%s" %d' puts between full_path and `HTTP/`, so
    `/login?pwd=` matches nothing on its own (it is under the 10-char floor)
    and is a match once rendered. Masking the pieces separately leaves the
    rendered line dirty; flattening to msg/() then costs AccessFormatter its
    five values. Only the argument that fed the join may be lost.
    """
    f = SecretRedactionFilter()
    assert f.redact_text("/login?pwd=") == "/login?pwd="      # inert on its own
    record = logging.LogRecord(
        "jarvis.test", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/login?pwd=", "1.1", 200),
        None,
    )
    assert f.filter(record) is True
    assert isinstance(record.args, tuple) and len(record.args) == 5
    assert record.args[4] == 200                      # AccessFormatter int()s it
    assert record.args[0] == "127.0.0.1:1"            # innocent args untouched
    assert record.args[1] == "GET"
    assert record.args[3] == "1.1"
    assert record.args[2] == "[REDACTED:password_assignment]"
    rendered = record.getMessage()
    assert "pwd=" not in rendered
    assert f.redact_text(rendered) == rendered        # the JOINED text is clean


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


# ── a handler that refuses the filter is a hole, and says so ─────────────────

class _RefusingHandler(logging.Handler):
    """A handler whose ``addFilter`` raises — a third-party handler with a
    locked-down or re-implemented filter API. Rare, but the failure mode matters:
    it goes on writing records the scanner never sees."""

    def addFilter(self, fltr):
        raise RuntimeError("this handler does not take filters")

    def emit(self, record):
        pass


def test_a_handler_that_refuses_the_filter_does_not_stop_the_others():
    logger = logging.getLogger("jarvis.test.redact.refuse.some")
    good = logging.StreamHandler(io.StringIO())
    logger.handlers = [_RefusingHandler(), good]
    logger.propagate = False

    covered = install_log_redaction(logger)

    assert covered == 1, "the refusing handler aborted the loop"
    assert any(isinstance(x, SecretRedactionFilter) for x in good.filters)


def test_an_uncovered_handler_is_counted_not_swallowed():
    """The count is the whole point: `install_*` returns how many handlers it
    covered, which reads identically whether the rest were already covered or
    refused outright. Only this figure separates the two."""
    logger = logging.getLogger("jarvis.test.redact.refuse.count")
    logger.handlers = [_RefusingHandler(), _RefusingHandler()]
    logger.propagate = False

    assert install_log_redaction(logger) == 0
    assert lr.uncovered_handler_count() == 2


def test_a_clean_install_reports_no_uncovered_handlers(monkeypatch):
    """The figure describes the *last* install, so a clean one must clear it.
    A count that only ever rises would keep reporting a hole that was closed."""
    monkeypatch.setattr(lr, "_UNCOVERED_HANDLERS", 3)
    logger = logging.getLogger("jarvis.test.redact.refuse.clean")
    logger.handlers = [logging.StreamHandler(io.StringIO())]
    logger.propagate = False

    install_log_redaction(logger)

    assert lr.uncovered_handler_count() == 0, "a stale count survived a clean install"


def test_an_uncovered_handler_is_announced(caplog):
    """Counted is not enough — nobody polls the accessor. The operator has to be
    told, on the logging surface they already read."""
    logger = logging.getLogger("jarvis.test.redact.refuse.warn")
    logger.handlers = [_RefusingHandler()]
    logger.propagate = False

    with caplog.at_level(logging.WARNING, logger="agents.core.security.log_redaction"):
        install_log_redaction(logger)

    assert any("NOT redacted" in r.getMessage() for r in caplog.records), (
        "a handler writing unredacted records was skipped without a word"
    )


class _BrokenManager:
    """The real logging manager, with a registry that cannot be read.

    It delegates everything else — `logging.getLogger` goes through
    `Logger.manager.getLogger`, so a manager that broke that too would fail the
    install for the wrong reason.
    """

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def loggerDict(self):
        raise RuntimeError("the logger registry is not readable here")


def test_a_failed_registry_walk_is_announced_not_absorbed(monkeypatch):
    """`_managed_loggers` returns `()` on failure, and `()` reads exactly like a
    process that simply owns no other loggers. Without a word, the install
    silently degrades to root-only — the one configuration this function exists
    to rule out, because a non-propagating logger never reaches root.

    `caplog` cannot be used here: its own setup walks `manager.loggerDict`, which
    is the very thing this test breaks. The capture is wired by hand instead.
    """
    captured = []

    class _Collect(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    module_logger = logging.getLogger("agents.core.security.log_redaction")
    collector = _Collect()
    module_logger.addHandler(collector)
    previous = module_logger.level
    module_logger.setLevel(logging.WARNING)
    try:
        monkeypatch.setattr(logging.Logger, "manager", _BrokenManager(logging.Logger.manager))
        lr.install_log_redaction_everywhere()
    finally:
        monkeypatch.undo()
        module_logger.removeHandler(collector)
        module_logger.setLevel(previous)

    assert any("NOT redacted" in m for m in captured), (
        "the registry walk failed and the install reported full coverage anyway"
    )


def test_the_fixture_leaves_no_redactor_behind(restore_logging, tmp_path, monkeypatch):
    """The isolation pin. `setup_logging()` installs the filter process-wide, and a
    test file that leaves it installed rewrites log records for every later test on
    the same worker — which is exactly how this was found, with a tmp path arriving
    as `[REDACTED:high_entropy_secret]` in an unrelated file's assertion.

    The fixture body is driven directly so its teardown is observable.
    """
    monkeypatch.setenv("JARVIS_LOG_FILE", str(tmp_path / "x.log"))
    fixture_fn = getattr(restore_logging_fixture, "__wrapped__", restore_logging_fixture)
    gen = fixture_fn()
    next(gen)                                  # setup
    import agents.core.log as log
    log.setup_logging(logging.INFO)            # installs the redactor everywhere
    installed_before = _count_redaction_filters()
    assert installed_before, "premise: setup_logging really does install the filter"

    with pytest.raises(StopIteration):
        next(gen)                              # teardown

    assert _count_redaction_filters() == 0, (
        "the redactor survived teardown and will rewrite records in later tests"
    )


def _count_redaction_filters() -> int:
    loggers = [logging.getLogger()]
    loggers += [obj for obj in logging.Logger.manager.loggerDict.values()
                if isinstance(obj, logging.Logger)]
    return sum(
        _is_redactor(f)
        for lg in loggers
        for handler in (getattr(lg, "handlers", ()) or ())
        for f in (getattr(handler, "filters", ()) or ())
    )


# ---------------------------------------------------------------------------
# The harness pin. These two are a PAIR and run in file order: the first leaves a
# process-wide install behind exactly as a `setup_logging()` call does, and the
# second asserts it was gone before it started. What they pin lives in
# `tests/conftest.py::_isolate_log_redaction`, not here — deliberately, because
# the leak is not this file's alone. `test_h2311_operability.py`,
# `test_errors.py` and `test_admin_knobs_wiring.py` each reproduce it too, so a
# per-file teardown is whack-a-mole: the next file to call `setup_logging()`
# brings it straight back.
# ---------------------------------------------------------------------------


def test_a_process_wide_install_is_left_behind_for_the_next_test():
    """First half of the pair. Installs, asserts the install is real, cleans nothing."""
    lr.install_log_redaction_everywhere()
    assert _count_redaction_filters(), (
        "premise failed: the process-wide install attached no filter at all, so "
        "the test below would pass without proving anything"
    )


def test_the_next_test_does_not_inherit_the_redactor():
    """Second half. Runs after the one above and must start clean.

    If this goes red, every test that follows a `setup_logging()` call in the same
    xdist worker is reading log records the secret scanner has rewritten — which
    is how `test_soul_injection_guard.py` came to assert against
    `truncated: [REDACTED:high_entropy_secret].md`.
    """
    assert _count_redaction_filters() == 0, (
        "a redactor installed by the previous test survived into this one; "
        "tests/conftest.py::_isolate_log_redaction is not stripping it"
    )


def test_a_redactor_installed_through_the_other_import_path_is_left_behind():
    """Third of the group, and the one that would have caught the first miss.

    `agents/` is on `sys.path`, so `core.security.log_redaction` and
    `agents.core.security.log_redaction` are two module objects over one file with
    two distinct `SecretRedactionFilter` classes. The first version of this cleanup
    used `isinstance` against one of them and reported a process clean while the
    root `StreamHandler` carried the other — which is why
    `test_soul_injection_guard.py` stayed red after the "fix".
    """
    other = importlib.import_module("core.security.log_redaction")
    assert other is not lr, (
        "premise: the two import paths no longer produce distinct modules, so this "
        "test proves nothing — delete it or re-point it at whatever replaced them"
    )
    other.install_log_redaction_everywhere()
    assert _count_redaction_filters(), (
        "premise failed: nothing was installed through the alternate path"
    )


def test_the_next_test_does_not_inherit_the_other_paths_redactor():
    """Fourth. Same contract as the second, against the alternate class."""
    assert _count_redaction_filters() == 0, (
        "a redactor installed through the `core.*` import path survived into this "
        "test; tests/conftest.py::_isolate_log_redaction is matching by isinstance "
        "somewhere instead of by class name"
    )
