import logging
import sys
from datetime import datetime, timezone
from typing import Optional

from .errors import ErrorCategory, ErrorSeverity, JarvisError, ErrorLog


_LOG_FORMAT = "%(asctime)s  %(levelname)s  %(name)s  %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        datefmt=_LOG_DATE_FORMAT,
        force=True,
    )


def log_error(
    logger: logging.Logger,
    code: str,
    exc: Optional[BaseException] = None,
    **kwargs,
) -> None:
    from .errors import CODES, ErrorCategory, ErrorSeverity

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

    return ErrorLog(
        code=code,
        message=formatted,
        category=entry.category,
        severity=entry.severity,
        component=component,
        timestamp=datetime.now(timezone.utc).timestamp(),
        meta=kwargs,
    )
