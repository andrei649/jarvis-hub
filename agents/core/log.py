import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

from .env_config import env_int
from .errors import ErrorSeverity, ErrorLog


_LOG_FORMAT = "%(asctime)s  %(levelname)s  %(name)s  %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger(__name__)

#: H145 review — what the last ``setup_logging`` in this process actually did with the
#: log file: ``path`` it writes (None when file logging is off) and ``error`` when it
#: could not open it. The log page reports this rather than re-deriving the settings.
FILE_LOG_STATE: dict = {"configured": False, "path": None, "error": None}


def _setting(category: str, key: str, default):
    """Read a settings_db value, falling back to default on any failure.

    Logging must come up even if the settings DB is unavailable (early boot,
    tests), so every read is defensive — never let log config crash the process.
    """
    try:
        from .settings_db import get_value
        return get_value(category, key, default)
    except Exception:
        return default


def _file_logging_config():
    """Resolve (path, max_bytes, backups) for the rotating file handler, or None.

    Opt-in (default off) so existing installs keep logging only to stderr — where
    a supervisor (systemd/journald, Docker) already captures + rotates stdout. The
    rotating file handler is for bare-metal/no-supervisor runs. Enable via
    /admin → system.log_to_file, or force a path with $JARVIS_LOG_FILE. Env wins
    over settings so a deployment can pin it without a DB write.

    Privacy note: root-logger records at the active level can include
    request-derived content (e.g. a voice-transcript preview); this persists it to
    disk, bounded only by ``max_bytes × backups`` (it is *not* covered by the
    H23.10 retention sweep). The default path inherits the data-root, so an in-repo
    data-root (the SEC-4/F-08 startup warning) puts the log in the checkout too —
    set $JARVIS_HOME to relocate it. Prefer WARNING level for sensitive installs.
    """
    path = os.environ.get("JARVIS_LOG_FILE", "").strip()
    if not path:
        if not bool(_setting("system", "log_to_file", False)):
            return None
        from .paths import data_path
        path = str(data_path("logs", "jarvis.log"))

    def _setting_int(cat_key, default):
        try:
            return int(_setting("system", cat_key, default))
        except (TypeError, ValueError):
            return default

    max_mb = max(1, env_int("JARVIS_LOG_MAX_MB", _setting_int("log_max_mb", 10)))
    backups = max(0, env_int("JARVIS_LOG_BACKUPS", _setting_int("log_backups", 5)))
    return path, max_mb * 1024 * 1024, backups


def _install_redaction() -> None:
    """H495: put the secret redactor on every handler this process owns.

    Not just the root handlers: ``callHandlers`` starts at the *emitting*
    logger, so any logger with its own handlers writes through them first, and
    one with ``propagate = False`` (uvicorn installs ``uvicorn`` and
    ``uvicorn.access`` that way, via ``dictConfig``) never reaches root at all.

    Imported lazily and guarded: logging must come up even if the security
    package cannot be imported (early boot, a partial checkout). Losing
    redaction is bad, but a process that cannot log at all is worse — and the
    failure is announced rather than silent.
    """
    try:
        from .security.log_redaction import install_log_redaction_everywhere
        install_log_redaction_everywhere()
    except Exception:
        logging.getLogger(__name__).warning(
            "Log secret-redaction filter unavailable; logs are NOT redacted",
            exc_info=True,
        )


def setup_logging(level: Optional[int] = None) -> None:
    # When no level is passed, honor /admin → system.log_level (was always INFO).
    if level is None:
        name = str(_setting("system", "log_level", "INFO")).upper()
        level = getattr(logging, name, logging.INFO)
    # force=True closes + drops every existing root handler before reconfiguring,
    # so repeated calls (lifespan + tests) never duplicate or leak handlers — the
    # rotating file handler we attach below is rebuilt cleanly each time too.
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        datefmt=_LOG_DATE_FORMAT,
        force=True,
    )
    _install_redaction()
    cfg = _file_logging_config()
    FILE_LOG_STATE.update(configured=True, path=None, error=None)
    if cfg is not None:
        path, max_bytes, backups = cfg
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            handler = RotatingFileHandler(
                path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATE_FORMAT))
            handler.setLevel(level)
            root = logging.getLogger()
            root.addHandler(handler)
            root.setLevel(level)
            # Cover the handler we just attached (the call above ran before it
            # existed). The install is idempotent, so the stderr handler is not
            # double-filtered.
            _install_redaction()
            FILE_LOG_STATE["path"] = os.path.abspath(path)
        except OSError as exc:
            FILE_LOG_STATE["error"] = f"{os.path.abspath(path)}: {exc.strerror or exc}"
            # A bad path / unwritable dir must not take the process down — we still
            # have stderr logging from basicConfig.
            logger.warning("File logging disabled (cannot open %s): %s", path, exc)


def log_error(
    logger: logging.Logger,
    code: str,
    exc: Optional[BaseException] = None,
    **kwargs,
) -> None:
    from .errors import CODES

    entry = CODES.get(code)
    if not entry:
        logger.error("Unknown error code: %s", code)
        return

    formatted = entry.message.format(**kwargs)
    component = logger.name

    if exc:
        logger.exception("[%s] %s", code, formatted)
    elif entry.severity == ErrorSeverity.CRITICAL:
        logger.critical("[%s] %s", code, formatted)
    elif entry.severity == ErrorSeverity.ERROR:
        logger.error("[%s] %s", code, formatted)
    elif entry.severity == ErrorSeverity.WARNING:
        logger.warning("[%s] %s", code, formatted)
    else:
        logger.info("[%s] %s", code, formatted)

    err_log = ErrorLog(
        code=code,
        message=formatted,
        category=entry.category,
        severity=entry.severity,
        component=component,
        timestamp=datetime.now(timezone.utc).timestamp(),
        meta=kwargs,
    )

    try:
        from .autonomy.error_logger import persist_problem
        persist_problem(err_log)
    except Exception:
        logger.warning("Failed to persist error log entry to backlog", exc_info=True)

    return err_log
