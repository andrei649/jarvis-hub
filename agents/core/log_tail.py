"""log_tail.py — the hub's own log, read from the end, for the UI and the CLI (H145).

The hub writes its log to ``data_path('logs', 'jarvis.log')`` (or ``$JARVIS_LOG_FILE``)
when file logging is on, with numbered rotations beside it (``jarvis.log.1`` …); see
``agents/core/log.py``. This module reads the newest records of one of those files:

* **Only those files.** The log and its numbered rotations are listed by ``lstat``: a
  link, a pipe or a directory is not listed, and the file is opened without following a
  link or blocking, then checked to be a regular file (review-H145 m1).
* **Bounded.** At most the last ``SCAN_BYTES`` of the file are read, in one go, and the
  file is closed before anything is parsed (a Windows rollover is never held up); at
  most ``MAX_LINES`` records come back, each at most ``MAX_RECORD_CHARS``.
* **Records, not lines.** A line that does not start with the log format's header (a
  traceback, a multi-line message) belongs to the record above it, so a traceback is
  never separated from its error. A record over the limit keeps its header and its
  newest lines, so the error line is always there (review-H145 MAJOR 2); lines above the
  file's first header, or above the window read, are records of their own.
* **Filtered, then redacted.** File, minimum level (a line with no level is not shown
  under a level floor), component (a logger and its children) and count are decided on
  the record as written; only a record that is returned is redacted, which keeps a
  filtered read cheap (review-H145 m5).
* **Redacted whole, then cut.** Every returned field goes through the H495 secret
  scanner, then an assignment rule (``*_TOKEN=…``, ``password: …``), then the known
  values of the process's secret-named environment variables and encrypted settings, so
  the reader masks at least what ``/api/admin/env`` masks (review-H145 m2). Only then is
  anything cut, so a secret is never split into a visible half (review-H145 MAJOR 1).
  When the scanner cannot be loaded, nothing is shown (review-H145 m3). Terminal control
  sequences, C1 controls and bidirectional overrides are removed (review-H145 m4).

When file logging is off (the default), or the hub could not open its file, the answer
says so, with how to turn it on, instead of looking like an empty log.
"""

from __future__ import annotations

import logging
import os
import re
import stat
from pathlib import Path

from .env_config import env_str

logger = logging.getLogger(__name__)

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
MAX_LINES = 500
DEFAULT_LINES = 200
SCAN_BYTES = 4 * 1024 * 1024
MAX_RECORD_CHARS = 8000
MAX_COMPONENTS = 60

_HEADER = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  (" + "|".join(LEVELS) + r")  (\S+)  ?(.*)$")
_ANSI = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|.)")
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_ROTATION = re.compile(r"[0-9]{1,4}")
#: ``name = value`` / ``name: value`` where the name ends like a credential's.
_ASSIGNMENT = re.compile(
    r"(?i)(\b[\w.-]*(?:api[_-]?key|key|token|secret|password|passwd|pass|client_id|credential)\b"
    r"[\"']?\s*[=:]\s*[\"']?)([^\s\"'&,;]{4,})")
_ENV_HINTS = ("key", "token", "secret", "password", "passwd", "pass", "client_id")
_REDACTED = "[REDACTED]"


class LogRequestError(ValueError):
    """A filter the reader refuses (an unknown file or level); the route answers 400."""


class RedactionUnavailable(RuntimeError):
    """The secret scanner could not be loaded: the log is not shown (fail closed)."""


def _setting(category: str, key: str, default):
    from .log import _setting as read

    return read(category, key, default)


def _default_log() -> Path:
    from .paths import data_path

    return data_path("logs", "jarvis.log")


def configured_log() -> tuple[Path, bool]:
    """``(path, enabled)``: the file the hub writes when file logging is on, and whether
    it is on — ``$JARVIS_LOG_FILE`` wins, as it does for the writer."""
    explicit = env_str("JARVIS_LOG_FILE").strip()
    if explicit:
        return Path(explicit), True
    return _default_log(), bool(_setting("system", "log_to_file", False))


def _writer_state() -> dict:
    """What this process's ``setup_logging`` actually did, when it ran."""
    try:
        from .log import FILE_LOG_STATE

        return dict(FILE_LOG_STATE)
    except Exception:  # noqa: BLE001
        return {"configured": False}


def _listed(path: Path) -> os.stat_result | None:
    """The file's own status when it is a regular file (never through a link)."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def list_files(path: Path) -> list[dict]:
    """The log and its numbered rotations that are regular files, newest first:
    ``{name, size, modified}``. Nothing else in the directory is ever listed."""
    found = []
    info = _listed(path)
    if info is not None:
        found.append((0, path.name, info))
    try:
        names = os.listdir(path.parent)
    except OSError:
        names = []
    prefix = path.name + "."
    for name in names:
        suffix = name[len(prefix):] if name.startswith(prefix) else ""
        if _ROTATION.fullmatch(suffix) and (info := _listed(path.parent / name)) is not None:
            found.append((int(suffix), name, info))
    found.sort(key=lambda item: item[0])
    return [{"name": name, "size": info.st_size, "modified": int(info.st_mtime)}
            for _, name, info in found]


# ── redaction ────────────────────────────────────────────────────────────────────

def _known_secret_values() -> list[str]:
    """Values the process holds as secrets: environment variables named like one, and
    the encrypted settings. Masked wherever they appear, whatever their shape."""
    values = set()
    for name, value in os.environ.items():
        lowered, value = name.lower(), value.strip()
        if (any(hint in lowered for hint in _ENV_HINTS) and len(value) >= 6
                and value.lower() not in ("true", "false", "enabled", "disabled")):
            values.add(value)
    try:
        from .settings_db import _SPEC, SECRET_KEYS, get_value

        for (cat, key) in _SPEC:
            if key in SECRET_KEYS:
                value = get_value(cat, key, "")
                if isinstance(value, str) and len(value.strip()) >= 6:
                    values.add(value.strip())
    except Exception as exc:  # noqa: BLE001 (no settings store here: the environment still counts)
        logger.debug("log reader: the settings store is not readable here: %s", type(exc).__name__)
    return sorted(values, key=len, reverse=True)


class _Redactor:
    def __init__(self):
        from .security.log_redaction import SecretRedactionFilter

        self._scan = SecretRedactionFilter().redact_text
        self._known = _known_secret_values()

    def __call__(self, text: str) -> str:
        if not text:
            return text
        text = self._scan(text)
        text = _ASSIGNMENT.sub(lambda m: m.group(1) + _REDACTED, text)
        for value in self._known:
            if value in text:
                text = text.replace(value, _REDACTED)
        return text


def _redactor() -> _Redactor:
    """A redactor for one read; the scanner failing to load is an error, never an
    identity function (fail closed), and it is tried again on the next read."""
    try:
        return _Redactor()
    except Exception as exc:  # noqa: BLE001
        raise RedactionUnavailable(str(exc) or exc.__class__.__name__) from exc


def _clean(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    return _CONTROL.sub("", _ANSI.sub("", text))


# ── reading ──────────────────────────────────────────────────────────────────────

def _read_window(path: Path, budget: int) -> tuple[bytes, bool, int]:
    """``(bytes, reached_start, scanned)``: the last *budget* bytes of the regular file
    at *path*, read in one go. The file is opened without following a link or blocking
    on a pipe, checked to be a regular file, and closed before anything is parsed."""
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_BINARY", 0))
    fd = os.open(path, flags)
    chunks: list[bytes] = []
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(0, "not a regular file")
        size = info.st_size
        start = max(0, size - max(0, int(budget)))
        os.lseek(fd, start, os.SEEK_SET)
        got = 0
        while got < size - start:
            part = os.read(fd, min(1024 * 1024, size - start - got))
            if not part:
                break
            chunks.append(part)
            got += len(part)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    return data, start == 0, len(data)


def _level_floor(level: str) -> int | None:
    level = (level or "").strip().upper()
    if level in ("", "ALL"):
        return None
    if level not in LEVELS:
        raise LogRequestError(f"level must be one of ALL, {', '.join(LEVELS)}")
    return LEVELS.index(level)


def _component(component: str) -> str:
    component = (component or "").strip()
    if len(component) > 200 or any(ch.isspace() for ch in component):
        raise LogRequestError("component must be a logger name")
    return component


def _matches(level: str, component: str, floor: int | None, wanted: str) -> bool:
    if floor is not None and (not level or LEVELS.index(level) < floor):
        return False
    return not wanted or (component == wanted or component.startswith(wanted + "."))


def _cut(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit] + " …[cut]", True)


def _record(redact: _Redactor, header: re.Match | None, head: str, tail: list[str]) -> dict:
    """A record from its header line and its continuation lines (oldest first). Every
    line is redacted whole before anything is cut; then the record keeps its header and
    the newest lines that fit, so the error at the end of a traceback is always there."""
    first = redact(head)
    budget = MAX_RECORD_CHARS - len(first)
    kept: list[str] = []
    for line in reversed(tail):
        clean = redact(line)
        if kept and budget - len(clean) - 1 < 0:
            break
        kept.append(clean)
        budget -= len(clean) + 1
    kept.reverse()
    dropped = len(tail) - len(kept)
    marker = [f"[… {dropped} line{'s' if dropped != 1 else ''} not shown]"] if dropped else []
    text, cut = _cut("\n".join([first] + marker + kept), MAX_RECORD_CHARS)
    if header is None:
        ts, level, component, message = "", "", "", first
    else:
        ts, level, component, raw_message = header.groups()
        component = redact(component)
        message = redact(raw_message)
    message, cut_message = _cut(message, MAX_RECORD_CHARS)
    return {"ts": ts, "level": level, "component": component, "message": message,
            "text": text, "cut": cut or cut_message or dropped > 0}


def read_path(path: Path, *, level: str = "", component: str = "",
              lines: int = DEFAULT_LINES, cap: int = MAX_LINES) -> dict:
    """The newest *lines* records of *path* that pass the filters, oldest first."""
    limit = max(1, min(int(lines), cap))
    floor = _level_floor(level)
    wanted = _component(component)
    redact = _redactor()
    data, reached_start, scanned = _read_window(path, SCAN_BYTES)
    raw_lines = data.split(b"\n")
    if not reached_start and raw_lines:
        raw_lines = raw_lines[1:]            # the first line of the window is partial
    newest_first: list[dict] = []
    seen: dict[str, int] = {}
    pending: list[str] = []                  # continuation lines, last line first
    done = False
    for raw in reversed(raw_lines):
        line = _clean(raw)
        if not line.strip():
            continue
        header = _HEADER.match(line)
        if header is None:
            pending.append(line)
            continue
        rec_level, rec_component = header.group(2), header.group(3)
        seen[rec_component] = seen.get(rec_component, 0) + 1
        if _matches(rec_level, rec_component, floor, wanted):
            newest_first.append(_record(redact, header, line, pending[::-1]))
            done = len(newest_first) >= limit
        pending = []
        if done:
            break
    if not done and pending and floor is None and not wanted:
        # Lines above the first header read (a record whose header rotated away, or a
        # file not in the log format): each is a record of its own, newest first.
        for line in pending:
            newest_first.append(_record(redact, None, line, []))
            if len(newest_first) >= limit:
                done = True
                break
    return {
        "entries": newest_first[::-1],
        "components": sorted(redact(name) for name in seen)[:MAX_COMPONENTS],
        "limit": limit,
        "scanned_bytes": scanned,
        "truncated": not done and not reached_start,
    }


def read_log(*, file: str | None = None, level: str = "", component: str = "",
             lines: int = DEFAULT_LINES) -> dict:
    """The answer for ``GET /api/admin/logs``: the listed files, the chosen one's newest
    records, and an honest note on what the hub is writing."""
    path, enabled = configured_log()
    writer = _writer_state()
    if writer.get("configured"):
        if writer.get("path"):
            path, enabled = Path(writer["path"]), True
        elif writer.get("error"):
            enabled = False
    files = list_files(path)
    names = [f["name"] for f in files]
    if file and file not in names:
        raise LogRequestError("file must be one of the listed log files")
    _level_floor(level)
    _component(component)
    out = {"enabled": enabled, "path": str(path), "files": files, "file": None, "entries": [],
           "components": [], "limit": max(1, min(int(lines), MAX_LINES)),
           "scanned_bytes": 0, "truncated": False, "note": ""}
    if writer.get("error"):
        out["note"] = ("The hub could not open its log file when it started "
                       f"({writer['error']}), so it logs to stderr only; fix the path or the "
                       "directory and restart.")
    elif not enabled and not files:
        out["note"] = ("File logging is off, so there is no log file to read. Turn on "
                       "system.log_to_file (Admin → system) or set JARVIS_LOG_FILE and restart "
                       "the hub; until then it logs to stderr, which your supervisor keeps "
                       "(journalctl, docker logs).")
    elif not files:
        out["note"] = (f"No log file yet at {path}: it is created when the hub next starts "
                       "with file logging on.")
    elif not enabled:
        out["note"] = ("File logging is off, or is turned off from the next restart: this file "
                       "may no longer be written. Turn on system.log_to_file to follow the hub.")
    if not files:
        return out
    chosen = file or names[0]
    out["file"] = chosen
    try:
        out.update(read_path(path.parent / chosen, level=level, component=component, lines=lines))
    except RedactionUnavailable as exc:
        out["note"] = (f"The secret redactor could not be loaded ({exc}), so the log is not "
                       "shown: it could carry a credential.")
    except OSError as exc:
        out["note"] = f"{chosen} could not be read ({exc.strerror or exc.__class__.__name__})."
    return out
