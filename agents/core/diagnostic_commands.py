"""Owner-only local diagnostic report for the H084 /debug chat command."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import stat
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from . import log_tail, support_bundle
from .channels import outbound_safety
from .paths import data_path

logger = logging.getLogger("nerva.diagnostic_commands")

LOG_LINES = 50
MAX_REPORT_BYTES = 512 * 1024
_WITHHELD = "A reply could not be checked before sending, so it was withheld."
# Keep the report local only where the kernel can pin its directory and refuse
# symlinks for the final directory/file. On Windows, openat-style dir_fd is not
# available; a path-based fallback would weaken that boundary.
SUPPORTED = (os.open in os.supports_dir_fd and os.unlink in os.supports_dir_fd
             and bool(getattr(os, "O_DIRECTORY", 0)) and bool(getattr(os, "O_NOFOLLOW", 0)))


class _ReportUnavailable(RuntimeError):
    """A safe, fixed reason why no report was saved."""


def _report_text(orch) -> str:
    """Build off-loop; the existing log reader and transport gate own redaction."""
    try:
        # read_log() returns a note on a failed redactor, so test its authority
        # directly before rendering a report that might otherwise look complete.
        log_tail._redactor()
    except Exception as exc:
        raise _ReportUnavailable("The secret redactor is unavailable; no report was saved.") from exc

    bundle = support_bundle.build_bundle(orch, now_iso=datetime.now(UTC).isoformat(),
                                         log_lines=LOG_LINES)
    logs = bundle.get("logs") if isinstance(bundle, dict) else None
    if not isinstance(logs, dict) or logs.get("error"):
        raise _ReportUnavailable("The log reader is unavailable; no report was saved.")
    if "secret redactor could not be loaded" in str(logs.get("note", "")).lower():
        raise _ReportUnavailable("The secret redactor is unavailable; no report was saved.")

    raw = support_bundle.render_text(bundle)
    if len(raw.encode("utf-8")) > MAX_REPORT_BYTES:
        raise _ReportUnavailable("The diagnostic report is too large; no report was saved.")
    try:
        clean = outbound_safety.sanitize_text(raw)
    except Exception as exc:
        raise _ReportUnavailable("Report redaction failed; no report was saved.") from exc
    if not clean.startswith("Nerva ") or clean == _WITHHELD:
        raise _ReportUnavailable("Report redaction failed; no report was saved.")
    if len(clean.encode("utf-8")) > MAX_REPORT_BYTES:
        raise _ReportUnavailable("The diagnostic report is too large; no report was saved.")
    return clean


def _save_private_report(text: str) -> Path:
    """Create under the configured data root, pinning the final report directory."""
    directory = data_path("support_reports")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise OSError("report directory is a symlink")
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                           | getattr(os, "O_NOFOLLOW", 0))
    name = ""
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise OSError("report directory is not a directory")
        if os.name != "nt":
            os.fchmod(directory_fd, 0o700)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"nerva-debug-{stamp}-{secrets.token_hex(8)}.txt"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
        try:
            if os.name != "nt":
                os.fchmod(file_fd, 0o600)
            data = text.encode("utf-8")
            offset = 0
            while offset < len(data):
                written = os.write(file_fd, data[offset:])
                if written <= 0:
                    raise OSError("report write stopped")
                offset += written
            os.fsync(file_fd)
        except BaseException:
            with suppress(OSError):
                os.unlink(name, dir_fd=directory_fd)
            raise
        finally:
            os.close(file_fd)
        return directory / name
    finally:
        os.close(directory_fd)


async def debug_command(ctx) -> str:
    """Save a bounded, local-only support report and give the owner its path."""
    if not ctx.principal.admin:
        return "Only the owner can create a diagnostic report; nothing was saved."
    if ctx.args.strip():
        return "Usage: /debug (no arguments); nothing was saved."
    if not SUPPORTED:
        return "Private local debug reports are unavailable on this platform; no report was saved."
    try:
        # This worker only reads. Cancellation before it returns cannot create a
        # report. The bounded, synchronous write below has no cancellation point.
        text = await asyncio.to_thread(_report_text, ctx.orch)
        path = _save_private_report(text)
    except _ReportUnavailable as exc:
        return str(exc)
    except OSError:
        logger.warning("Local diagnostic report could not be saved", exc_info=True)
        return "The local diagnostic report could not be saved. Check the hub log."
    except Exception:
        logger.warning("Local diagnostic report failed", exc_info=True)
        return "The local diagnostic report could not be prepared. Check the hub log."
    return f"Local diagnostic report: {path}"
