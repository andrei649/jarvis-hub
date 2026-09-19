"""
log_redaction.py — H495 (log hop): mask credentials on every log handler we can
reach, and be explicit about the ones we cannot.

Every other durable sink in this tree already redacts before it writes: the
hash-chained security audit masks findings and runs the preview through
``SecurityAudit._redact_preview`` *before* hashing (AUD-12 / SEC-071), and
``ToolRPC._scrub`` masks every response that crosses to the sandbox. The **log
path had nothing**. ``log_safe`` strips CR/LF (py/log-injection) but not
secrets, and ``ToolRPC._scrub`` only masks values the ``SecretBroker`` already
*knows* — so a ``cat .env`` of a key that was never brokered flowed raw into
``agent.log`` and into the spilled tool-result file.

This module closes that hop with a ``logging.Filter`` that runs
``SecretScanner.redact`` over the rendered message of every record a covered
handler is about to format.

**Scope — what this does and does not cover.** The filter only sees records
that reach a handler it is attached to. ``install_log_redaction_everywhere()``
covers the root handlers *and* every handler owned by any logger in
``logging.Logger.manager``, which is what ``setup_logging()`` calls. What it
cannot cover is a handler created *after* that call: a dependency that runs
``dictConfig`` later, or a process that never calls ``setup_logging()`` at all
(``scripts/coordinator.py`` and ``scripts/nerva_mcp_stdio.py`` call
``logging.basicConfig`` directly and are still uncovered). It also only masks
*credentials* — ``PIIScanner`` (CNP/IBAN/card/email/phone) is not run here, so a
CNP still reaches the log. Neither hop is closed by this module; the row's
transcript, approval-card and export hops are follow-up work.

Four design points worth keeping:

**It installs on HANDLERS, never on loggers.** A filter attached to a
``Logger`` only sees records that logger emitted itself — ``logging.Logger.handle``
applies ``self.filter`` and then ``callHandlers`` walks the ancestor chain
calling *handler* filters only. Every module here logs through
``logging.getLogger(__name__)``, i.e. ``jarvis.*`` children, so a root-*logger*
filter would see essentially nothing. Handler filters see every record that
reaches the handler, whatever emitted it.

**Root handlers alone are not enough.** ``callHandlers`` starts at the
*emitting* logger, so any logger that owns handlers formats the record through
them *before* root is reached — and a logger with ``propagate = False`` never
reaches root at all. uvicorn is the live case: ``uvicorn.Config.__init__`` runs
``dictConfig`` over its default ``LOGGING_CONFIG``, which gives ``uvicorn`` and
``uvicorn.access`` their own handlers with ``propagate: False``. A secret in a
query string (an unbrokered key in a callback/redirect URL is exactly the H495
scenario) would land raw in the access log if only root were covered, and no
number of repeat calls against root could ever reach it. Hence
``install_log_redaction_everywhere()``, and hence ``setup_logging()`` runs
*after* the uvicorn config is built (``serve.py`` constructs
``uvicorn.Config`` in ``main()``; ``setup_logging()`` runs later, in the
FastAPI lifespan).

**The enable flag is snapshotted at import.** ``_ENABLED`` is read once, here,
rather than per call. Everything else in ``env_config`` deliberately re-reads
the environment on every call; this is the one place where caching *is* the
property — an agent-authored mid-session write to the ``JARVIS_LOG_REDACTION``
variable must not be able to switch the redactor off underneath the logs that
would record what it did next. (That example is spelled in prose rather than as
the literal subscript expression on purpose: the AUD-14 ratchet in
``tests/test_o26_p2_env_config.py`` greps this file line by line and would count
the code form as a new raw environment read. Pinned by
``test_module_text_trips_no_raw_env_read_ratchet``.)

**A masked record keeps its shape where it can.** Not every formatter reads
the rendered message: uvicorn's ``AccessFormatter`` unpacks ``record.args`` into
exactly five values, so a record flattened to ``msg``/``()`` makes it raise and
the access line is *dropped*. Because ``high_entropy_secret`` matches any UUID,
flattening would delete every access line whose path carries one. So when a
secret is found, the format string and each argument are masked separately and
the tuple is kept, as long as re-rendering them yields text the scanner no
longer objects to. Only a secret straddling the boundary between format string
and argument (``logger.info("sk-ant-%s", tail)``) falls back to flattening.

**The filter never raises, and says which failure it hit.** An exception out of
``Filter.filter`` propagates through ``Handler.handle`` → ``callHandlers`` →
``Logger._log`` and into the *caller's* ``logger.info(...)`` line. So the
content is dropped rather than emitted unscanned — but the two failures are
reported differently, because they mean different things:

* ``[log-format-error] ...`` — ``record.msg % record.args`` failed. That is a
  *caller* bug (a mismatched format string), nothing to do with the scanner.
  Without a filter, logging prints its own ``--- Logging error ---`` block
  naming the message and the arguments; collapsing that into an anonymous line
  would lose a real diagnostic, and letting it through would print the raw
  arguments. So the format string, the arguments and the exception are kept —
  scanned — and the record is emitted with ``record.name``/``pathname``/
  ``lineno`` intact.
* ``[redaction-unavailable]`` — the scanner itself failed. Nothing about the
  record can be trusted, so everything (message, args, traceback, stack) is
  dropped: fail closed on content, never on control flow.

Known cost, measured, not hidden: ``SecretScanner``'s ``high_entropy_secret``
catch-all (``[A-Za-z0-9+/_-]{32,}`` gated by a Shannon-entropy validator) also
matches canonical UUIDs and 40-char git SHAs, so log lines carrying a
``session_id``/``run_id``/commit will show ``[REDACTED:high_entropy_secret]``
in place of that id. Now that uvicorn's access logger is covered too, that also
applies to request paths: ``/api/run/<uuid>`` logs as
``[REDACTED:high_entropy_secret]`` (the class includes ``/``, so the mask can
swallow surrounding path segments as well). That is a real debuggability cost
and it is the price of catching an unknown-vendor key. The pattern set is **not** narrowed here — a
deployment that cannot pay it turns the filter off wholesale with
``JARVIS_LOG_REDACTION=0`` and accepts the consequence explicitly.
"""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Callable, Iterable

from ..env_config import env_flag
from .scanner import SecretScanner

__all__ = [
    "SecretRedactionFilter",
    "install_log_redaction",
    "install_log_redaction_everywhere",
    "uncovered_handler_count",
    "REDACTION_UNAVAILABLE",
    "LOG_FORMAT_ERROR",
]

REDACTION_UNAVAILABLE = "[redaction-unavailable]"
LOG_FORMAT_ERROR = "[log-format-error]"

# Snapshotted at import ON PURPOSE — see the module docstring. Default ON: the
# floor ships enabled and only an operator's boot environment can lower it.
_ENABLED = env_flag("JARVIS_LOG_REDACTION", True)

# Shortest text any built-in SecretScanner pattern can match is 10 chars
# (`pwd:"abcd"` / `pwd=abcdef` via `password_assignment`). Records shorter than
# that cannot contain a built-in secret, so they skip the regex work entirely.
# Pinned by test_shortest_builtin_match_is_not_below_length_floor.
_BUILTIN_MIN_MATCH_LEN = 10

# Flags a pattern may carry and still be safely inlined into the prefilter
# alternation. `re.UNICODE` is implicit for str patterns; `re.IGNORECASE` is
# reproduced with a scoped `(?i:...)`. Anything else would be silently dropped
# by the alternation and could cause a false negative, so it disables the
# prefilter instead.
_PREFILTER_SAFE_FLAGS = re.UNICODE | re.IGNORECASE

_BACKREF = re.compile(r"\\[1-9]")


def _build_prefilter(scanner: SecretScanner) -> re.Pattern | None:
    """One combined regex that matches iff some scanner pattern matches.

    Derived from the scanner's *own* compiled patterns rather than a
    hand-maintained parallel list, so it cannot drift out of sync and cannot
    produce a false negative: if no branch matches, no individual pattern
    matches, and ``redact`` would have been a no-op.

    Returns ``None`` — meaning "always run the full scan" — whenever the
    alternation cannot be built faithfully (a backreference would be renumbered
    inside the union, an unsupported flag would be dropped, the alternation
    fails to compile, or the scanner exposes no compiled patterns). Every
    bail-out costs speed, never coverage.
    """
    compiled = getattr(scanner, "_compiled", None)
    if not compiled:
        return None
    parts: list[str] = []
    for row in compiled:
        try:
            pattern = row[1]
            source = pattern.pattern
            flags = pattern.flags
        except (IndexError, AttributeError):
            return None
        if _BACKREF.search(source):
            return None
        if flags & ~_PREFILTER_SAFE_FLAGS:
            return None
        parts.append(f"(?i:{source})" if flags & re.IGNORECASE else f"(?:{source})")
    try:
        return re.compile("|".join(parts))
    except re.error:
        return None


def _length_floor(scanner: SecretScanner) -> int:
    """The length pre-check, or 0 when it cannot be proven safe.

    ``JARVIS_SCANNER_EXTRA_PATTERNS`` (AUD-18) lets a deployment add its own
    secret formats, and those can match text shorter than any built-in, so the
    floor must be dropped to 0 whenever one is present.

    Extras are detected by SHAPE, not by name. ``SecretScanner.__init__``
    *appends* extras to ``_compiled`` without checking for collisions, so an
    extra named after a built-in (``jwt``, ``slack_token``, …) leaves the set of
    names unchanged — a name-set difference cannot see it, and the floor would
    stay at 10 while the scanner itself happily matched a 5-char deployment
    secret. So every compiled row must correspond one-to-one to a built-in with
    the same regex source: a duplicate name, an unknown name, a changed source,
    a scanner that exposes no ``_compiled`` at all — any of those returns 0 and
    the full scan always runs. Pinned by
    ``test_length_floor_drops_to_zero_when_an_extra_shadows_a_builtin_name``.
    """
    compiled = getattr(scanner, "_compiled", None)
    if not compiled:
        return 0
    builtin = SecretScanner.PATTERNS
    seen: set[str] = set()
    for row in compiled:
        try:
            name = row[0]
            source = row[1].pattern
        except (IndexError, AttributeError, TypeError):
            return 0
        entry = builtin.get(name)
        if entry is None or entry[0] != source or name in seen:
            return 0
        seen.add(name)
    return _BUILTIN_MIN_MATCH_LEN


class SecretRedactionFilter(logging.Filter):
    """Mask credentials in a ``LogRecord`` before any handler formats it.

    Attach to a *handler* (see ``install_log_redaction_everywhere``), not to a
    logger.
    """

    def __init__(self, name: str = "", scanner: SecretScanner | None = None):
        super().__init__(name)
        self._scanner = SecretScanner() if scanner is None else scanner
        self._prefilter = _build_prefilter(self._scanner)
        self._min_len = _length_floor(self._scanner)

    # ── internals ────────────────────────────────────────────────────────────

    def redact_text(self, text: str) -> str:
        """Cheap pre-checks, then the full scan only when something could match."""
        if not text:
            return text
        if self._min_len and len(text) < self._min_len:
            return text
        if self._prefilter is not None and not self._prefilter.search(text):
            return text
        return self._scanner.redact(text)

    def _note_format_error(self, record: logging.LogRecord, exc: BaseException) -> None:
        """`record.msg % record.args` raised — a caller bug, not a scanner one.

        Keep the diagnostic Python would have printed (format string, arguments,
        exception) instead of collapsing to an anonymous line, but run all of it
        through the scanner first so nothing unscanned is emitted. If *that*
        raises, the caller in `filter` falls back to REDACTION_UNAVAILABLE.
        """
        detail = f"{record.msg!r} % {record.args!r} -> {type(exc).__name__}: {exc}"
        record.msg = f"{LOG_FORMAT_ERROR} {self.redact_text(detail)}"
        record.args = ()

    def _redact_in_place(self, record: logging.LogRecord) -> bool:
        """Mask the secret while KEEPING ``record.args``, or report that it cannot.

        Some formatters read ``record.args`` structurally rather than the
        rendered message: uvicorn's ``AccessFormatter`` unpacks exactly five
        args, so a record flattened to ``msg``/``()`` makes it raise and the
        access line is DROPPED. Since ``high_entropy_secret`` matches any UUID,
        flattening would silently delete every access line whose path carries
        one — a redaction that eats the log is not a win.

        When the secret sits wholly inside the format string or inside an
        individual argument, masking each piece separately keeps the shape and
        the ``%``-formatting still works (a literal ``%`` inside an *argument*
        is never re-interpreted; only ``msg`` is the format string). This is
        only accepted when re-rendering the masked pieces yields text the
        scanner no longer objects to — a secret straddling the boundary
        (``logger.info("sk-ant-%s", tail)``) is not caught this way. Returns
        False then, and the caller flattens: correctness beats shape.
        """
        args = record.args
        if not args:
            return False
        try:
            msg = record.msg
            new_msg = self.redact_text(msg) if isinstance(msg, str) else msg
            if isinstance(args, dict):
                new_args: object = {
                    k: (self.redact_text(v) if isinstance(v, str) else v)
                    for k, v in args.items()
                }
            elif isinstance(args, tuple):
                new_args = tuple(
                    self.redact_text(a) if isinstance(a, str) else a for a in args
                )
            else:
                return False
            candidate = new_msg % new_args
            if self.redact_text(candidate) != candidate:
                return False
        except Exception:
            return False
        record.msg = new_msg
        record.args = new_args
        return True

    def _apply(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception as exc:
            self._note_format_error(record, exc)
        else:
            redacted = self.redact_text(message)
            if redacted != message and not self._redact_in_place(record):
                # Fallback: assign the *rendered* text and drop the args.
                # Leaving `args` in place alongside a rendered `msg` would make
                # `getMessage()` re-apply `%`-formatting to a payload that may
                # now contain a literal `%`, which raises inside the formatter.
                # `()` is falsy, so `getMessage()` returns msg as-is.
                record.msg = redacted
                record.args = ()

        # A traceback is a log sink too — `logger.exception(...)` on an error
        # whose text embeds a token leaks it through `Formatter.formatException`.
        # Render it here (the formatter caches and reuses `exc_text`) so the
        # redacted copy is the one that reaches disk.
        if record.exc_info and not record.exc_text and isinstance(record.exc_info, tuple):
            record.exc_text = "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
        if record.exc_text:
            record.exc_text = self.redact_text(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact_text(record.stack_info)

    # ── logging.Filter ───────────────────────────────────────────────────────

    def filter(self, record: logging.LogRecord) -> bool:
        # Module global, not a constructor snapshot, so a test can patch it;
        # it is only ever assigned from the environment at import time.
        if not _ENABLED:
            return True
        try:
            self._apply(record)
        except Exception:
            # Never propagate: a raising filter takes down the caller's log
            # call. The scanner itself failed, so nothing here can be trusted —
            # drop the whole record's content rather than emit text that was not
            # successfully scanned.
            try:
                record.msg = REDACTION_UNAVAILABLE
                record.args = ()
                record.exc_info = None
                record.exc_text = None
                record.stack_info = None
            except Exception:  # nosec B110 — a logging.Filter that raises takes
                # down the caller's log call, and the scanner has already failed
                # by the time we get here: there is nothing left to try and
                # nothing safe to emit. Deliberately the only silent swallow in
                # this module; the install-time one below is counted and warned.
                pass
        return True


#: Handlers the last install could not attach the filter to. Each one still
#: writes records the scanner never sees, so this is a coverage figure an
#: operator can read back — a security control that degrades quietly is worse
#: than one that fails loudly.
_UNCOVERED_HANDLERS = 0


def uncovered_handler_count() -> int:
    """Handlers the most recent install call failed to cover (0 when clean)."""
    return _UNCOVERED_HANDLERS


def _report_refused(refused: int) -> None:
    """Record and announce handlers that refused the filter.

    Announced through ``logging`` on purpose: the handler that refused is the
    one place the message might not reach, and every other handler in the
    process will carry it.
    """
    global _UNCOVERED_HANDLERS
    _UNCOVERED_HANDLERS = refused
    if refused:
        logging.getLogger(__name__).warning(
            "Log secret-redaction filter could not be attached to %d handler(s); "
            "records written through them are NOT redacted",
            refused,
        )


def _cover(
    logger: logging.Logger, factory: Callable[[], SecretRedactionFilter]
) -> tuple[int, int]:
    """Attach the shared filter to every handler *logger* owns.

    Returns ``(covered, refused)``. One uncooperative handler must not stop the
    others being covered — but a handler this fails on goes on writing records
    the scanner never saw, which is a hole in a security control. It is counted
    and reported by the installer rather than skipped in silence.
    """
    added = refused = 0
    for handler in list(getattr(logger, "handlers", ()) or ()):
        try:
            existing = getattr(handler, "filters", ()) or ()
            if any(isinstance(f, SecretRedactionFilter) for f in existing):
                continue
            handler.addFilter(factory())
            added += 1
        except Exception:
            refused += 1
    return added, refused


def _shared_factory() -> Callable[[], SecretRedactionFilter]:
    """One filter instance per install call, built only if a handler needs it."""
    holder: list[SecretRedactionFilter] = []

    def factory() -> SecretRedactionFilter:
        if not holder:
            holder.append(SecretRedactionFilter())
        return holder[0]

    return factory


def _managed_loggers() -> Iterable[logging.Logger]:
    """Every real ``Logger`` the logging module knows about (PlaceHolders skipped).

    An empty result is indistinguishable from a successful walk over a process
    that owns no other loggers, so a walk that *fails* says so rather than
    quietly degrading the install to root-only — which is precisely the case
    where every non-propagating logger goes on writing unscanned.
    """
    try:
        registry = list(logging.Logger.manager.loggerDict.values())
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not enumerate the logger registry; only the root handlers are "
            "covered, so records from a non-propagating logger are NOT redacted",
            exc_info=True,
        )
        return ()
    return [obj for obj in registry if isinstance(obj, logging.Logger)]


def install_log_redaction(root: logging.Logger | None = None) -> int:
    """Attach one ``SecretRedactionFilter`` to every handler on *root*.

    Covers only the handlers *root* itself owns. For the process-wide install
    use ``install_log_redaction_everywhere()`` — a logger that owns handlers
    formats records through them before root is ever consulted, and one with
    ``propagate = False`` never consults root at all.

    Idempotent — a handler that already carries one is skipped, so repeated
    ``setup_logging()`` calls (lifespan + tests) never stack filters. Returns
    the number of handlers newly covered. A no-op when redaction is disabled.
    """
    if not _ENABLED:
        return 0
    target = logging.getLogger() if root is None else root
    added, refused = _cover(target, _shared_factory())
    _report_refused(refused)
    return added


def install_log_redaction_everywhere() -> int:
    """Cover the root handlers **and** every other logger's own handlers.

    ``logging.Logger.callHandlers`` walks from the *emitting* logger upwards, so
    a logger that owns handlers formats the record through them before root is
    reached, and a logger with ``propagate = False`` — uvicorn's ``uvicorn`` and
    ``uvicorn.access``, installed by ``dictConfig`` from inside the dependency —
    never reaches root at all. Root-only coverage leaves those writing raw, and
    no repeat call against root can ever fix it.

    Still only covers handlers that exist *now*: a dependency that reconfigures
    logging after this runs is not reached. ``setup_logging()`` is called from
    the FastAPI lifespan, i.e. after ``serve.py`` has built its
    ``uvicorn.Config`` (which is what applies uvicorn's ``LOGGING_CONFIG``), so
    the production server's access log is covered. Idempotent; returns the
    number of handlers newly covered; a no-op when redaction is disabled.
    """
    if not _ENABLED:
        return 0
    factory = _shared_factory()
    added, refused = _cover(logging.getLogger(), factory)
    for logger in _managed_loggers():
        covered, missed = _cover(logger, factory)
        added += covered
        refused += missed
    _report_refused(refused)
    return added
