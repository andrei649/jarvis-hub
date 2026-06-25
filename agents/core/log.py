import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

from .errors import ErrorSeverity, ErrorLog


_LOG_FORMAT = "%(asctime)s  %(levelname)s  %(name)s  %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger(__name__)


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

    def _int(env, cat_key, default):
        raw = os.environ.get(env, "").strip()
        try:
            return int(raw) if raw else int(_setting("system", cat_key, default))
        except (TypeError, ValueError):
            return default

    max_mb = max(1, _int("JARVIS_LOG_MAX_MB", "log_max_mb", 10))
    backups = max(0, _int("JARVIS_LOG_BACKUPS", "log_backups", 5))
    return path, max_mb * 1024 * 1024, backups


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
    cfg = _file_logging_config()
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
        except OSError as exc:
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
