"""log_tail.py — the hub's own log, read from the end, for the UI and the CLI (H145).

The hub writes its log to ``data_path('logs', 'jarvis.log')`` (or ``$JARVIS_LOG_FILE``)
when file logging is on, with numbered rotations beside it (``jarvis.log.1`` …); see
``agents/core/log.py``. This module reads the newest records of one of those files:

* **Bounded.** The file is read backwards in chunks, never more than ``SCAN_BYTES`` per
  request, and at most ``MAX_LINES`` records come back; a record is cut at
  ``MAX_RECORD_CHARS``. A multi-gigabyte log costs the same as a small one.
* **Records, not lines.** A line that does not start with the log format's header (a
  traceback, a multi-line message) belongs to the record above it, so a traceback is
  never separated from its error.
* **Filtered.** By file (one of the listed ones, by name: nothing else is reachable),
  minimum level, and component (a logger and its children); the count is of records
  that match.
* **Redacted again.** Every field is passed through the H495 secret redactor as it is
  read: rotated files and lines written before H495 never went through the filter, and
  a stack trace can carry a token. Terminal control sequences are removed.

When file logging is off (the default) the answer says so, with how to turn it on,
instead of looking like an empty log.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
MAX_LINES = 500
DEFAULT_LINES = 200
SCAN_BYTES = 4 * 1024 * 1024
CHUNK = 64 * 1024
MAX_RECORD_CHARS = 8000
MAX_COMPONENTS = 60

_HEADER = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  (" + "|".join(LEVELS) + r")  (\S+)  ?(.*)$")
_ANSI = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)?|.)")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class LogRequestError(ValueError):
    """A filter the reader refuses (an unknown file or level); the route answers 400."""


def _setting(category: str, key: str, default):
    from .log import _setting as read

    return read(category, key, default)


def _default_log() -> Path:
    from .paths import data_path

    return data_path("logs", "jarvis.log")


def configured_log() -> tuple[Path, bool]:
    """``(path, enabled)``: the file the hub writes when file logging is on, and whether
    it is on — ``$JARVIS_LOG_FILE`` wins, as it does for the writer."""
    explicit = os.environ.get("JARVIS_LOG_FILE", "").strip()
    if explicit:
        return Path(explicit), True
    return _default_log(), bool(_setting("system", "log_to_file", False))


def _regular(path: Path) -> os.stat_result | None:
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def list_files(path: Path) -> list[dict]:
    """The log and its numbered rotations that exist, newest first: ``{name, size,
    modified}``. Nothing else in the directory is ever listed."""
    found = []
    info = _regular(path)
    if info is not None:
        found.append((0, path.name, info))
    rotation = re.compile(re.escape(path.name) + r"\.(\d{1,4})$")
    try:
        names = os.listdir(path.parent)
    except OSError:
        names = []
    for name in names:
        match = rotation.match(name)
        if match and (info := _regular(path.parent / name)) is not None:
            found.append((int(match.group(1)), name, info))
    found.sort(key=lambda item: item[0])
    return [{"name": name, "size": info.st_size, "modified": int(info.st_mtime)}
            for _, name, info in found]


def _redactor():
    global _REDACT
    if _REDACT is None:
        try:
            from .security.log_redaction import SecretRedactionFilter

            _REDACT = SecretRedactionFilter().redact_text
        except Exception:  # noqa: BLE001 (no scanner: mask nothing rather than fail the read)
            _REDACT = lambda text: text  # noqa: E731
    return _REDACT


_REDACT = None


def _clean(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    return _CONTROL.sub("", _ANSI.sub("", text))


class _Backwards:
    """The file's lines from the last to the first, reading at most *budget* bytes."""

    def __init__(self, path: Path, budget: int):
        self.path, self.budget = path, max(0, int(budget))
        self.scanned = 0
        self.exhausted = False           # reached the start of the file

    def __iter__(self):
        fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            pos = os.fstat(fd).st_size
            carry = b""
            while pos > 0 and self.scanned < self.budget:
                want = min(CHUNK, pos, self.budget - self.scanned)
                pos -= want
                os.lseek(fd, pos, os.SEEK_SET)
                data = b""
                while len(data) < want:
                    part = os.read(fd, want - len(data))
                    if not part:
                        break
                    data += part
                self.scanned += len(data)
                parts = (data + carry).split(b"\n")
                carry = parts[0]
                yield from reversed(parts[1:])
            if pos == 0:
                self.exhausted = True
                yield carry
        finally:
            os.close(fd)


def _record(header: re.Match | None, lines: list[str], dropped: int) -> dict:
    redact = _redactor()
    body = "\n".join(lines)
    if dropped:
        body = f"{lines[0]}\n[… {dropped} lines not shown]\n" + "\n".join(lines[1:])
    cut = dropped > 0
    if len(body) > MAX_RECORD_CHARS:
        body, cut = body[:MAX_RECORD_CHARS] + " …[cut]", True
    if header is None:
        ts, level, component, message = "", "", "", lines[0]
    else:
        ts, level, component, message = header.groups()
    message = message[:MAX_RECORD_CHARS]
    return {"ts": ts, "level": level, "component": redact(component), "message": redact(message),
            "text": redact(body), "cut": cut}


def _matches(entry: dict, floor: int | None, component: str) -> bool:
    if floor is not None and (not entry["level"] or LEVELS.index(entry["level"]) < floor):
        return False
    return not component or (entry["component"] == component
                             or entry["component"].startswith(component + "."))


def read_path(path: Path, *, level: str = "", component: str = "",
              lines: int = DEFAULT_LINES, cap: int = MAX_LINES) -> dict:
    """The newest *lines* records of *path* that pass the filters, oldest first."""
    limit = max(1, min(int(lines), cap))
    floor = _level_floor(level)
    component = _component(component)
    reader = _Backwards(path, SCAN_BYTES)
    newest_first: list[dict] = []
    seen: dict[str, int] = {}
    pending: list[str] = []          # continuation lines, last line first
    pending_chars = dropped = 0

    def emit(entry: dict) -> bool:
        if entry["component"]:
            seen[entry["component"]] = seen.get(entry["component"], 0) + 1
        if _matches(entry, floor, component):
            newest_first.append(entry)
        return len(newest_first) >= limit

    done = False
    for raw in reader:
        line = _clean(raw)
        if not line.strip():
            continue
        header = _HEADER.match(line)
        if header is None:
            if pending_chars > 2 * MAX_RECORD_CHARS:
                dropped += 1                  # keep the tail of a huge traceback
            else:
                pending.append(line)
                pending_chars += len(line)
            continue
        done = emit(_record(header, [line] + pending[::-1], dropped))
        pending, pending_chars, dropped = [], 0, 0
        if done:
            break
    if not done and reader.exhausted:
        # Lines above the file's first header (a record whose header rotated away, or a
        # file not in the log format): each is its own record, newest first.
        for line in pending:
            if emit(_record(None, [line], 0)):
                break
    return {
        "entries": newest_first[::-1],
        "components": sorted(seen)[:MAX_COMPONENTS],
        "limit": limit,
        "scanned_bytes": reader.scanned,
        "truncated": not done and not reader.exhausted,
    }


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


def read_log(*, file: str | None = None, level: str = "", component: str = "",
             lines: int = DEFAULT_LINES) -> dict:
    """The answer for ``GET /api/admin/logs``: the listed files, the chosen one's newest
    records and an honest note when file logging is off."""
    path, enabled = configured_log()
    files = list_files(path)
    names = [f["name"] for f in files]
    if file and file not in names:
        raise LogRequestError("file must be one of the listed log files")
    _level_floor(level)
    _component(component)
    out = {"enabled": enabled, "path": str(path), "files": files, "file": None, "entries": [],
           "components": [], "limit": max(1, min(int(lines), MAX_LINES)),
           "scanned_bytes": 0, "truncated": False, "note": ""}
    if not enabled and not files:
        out["note"] = ("File logging is off, so there is no log file to read. Turn on "
                       "system.log_to_file (Admin → system) or set JARVIS_LOG_FILE and restart "
                       "the hub; until then it logs to stderr, which your supervisor keeps "
                       "(journalctl, docker logs).")
        return out
    if not files:
        out["note"] = (f"No log file yet at {path}: it is created when the hub next starts "
                       "with file logging on.")
        return out
    if not enabled:
        out["note"] = ("File logging is off: this file is not being written any more. Turn on "
                       "system.log_to_file to follow the hub again.")
    chosen = file or names[0]
    out["file"] = chosen
    try:
        out.update(read_path(path.parent / chosen, level=level, component=component, lines=lines))
    except OSError as exc:
        out["note"] = f"{chosen} could not be read ({exc.strerror or exc.__class__.__name__})."
    return out
