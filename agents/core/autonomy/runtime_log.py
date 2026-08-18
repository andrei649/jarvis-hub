"""runtime_log.py — structured run-log for the Always-On runtime (one JSON line per cycle).

The supervised runtime (`runtime.py` + `runtime_supervisor.py`) appends exactly one
JSON object per coordinator cycle, plus one per supervisor lifecycle event
(child start/exit/stop). The file is the runtime's flight recorder: `tail -3` is a
health check, and the morning brief consumes `summarize_recent()` so "what did the
loop actually do overnight" is answerable from disk, not from memory.

Format contract (consumed by the morning brief and by tests — change additively):
  every line is a self-contained JSON object with at least
    ts       ISO-8601 UTC timestamp
    phase    "cycle" | "supervisor" | "shutdown"
  cycle lines add: cycle (int, monotonic across restarts), boot_id (int),
    status ("clean" | "degraded" | "error"), worker (tick summary dict),
    queue (status→count), night_shift (dict), heartbeats (dict), duration_ms, pid.
  supervisor lines add: event ("child_start" | "child_exit" | "supervisor_stop"), …

Writers append a single compact line per record; the reader skips lines that do not
parse (a kill -9 mid-write may truncate the final line — that must never poison the
whole log). Network-free, stdlib-only, unit-testable offline.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("jarvis.autonomy.runtime")

RUNTIME_LOG_ENV = "JARVIS_RUNTIME_LOG"


def default_log_path() -> Path:
    """`$JARVIS_RUNTIME_LOG`, else `<app root>/logs/runtime.jsonl`.

    The operator-facing default deliberately lives under the checkout's `logs/`
    (gitignored) rather than the data root: `tail logs/runtime.jsonl` is the
    documented health check. Packaged installs point the env var at a writable
    location (the systemd unit in `deploy/` does exactly that).
    """
    env = os.environ.get(RUNTIME_LOG_ENV, "").strip()
    if env:
        return Path(env).expanduser()
    from agents.core.paths import app_root

    return app_root() / "logs" / "runtime.jsonl"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def append_record(path: Path | str, record: dict) -> dict:
    """Append one record as a single compact JSON line. Never raises.

    A run-log write must not be able to kill the cycle that produced it: on any
    OS error the record is dropped with a debug log (the state store still holds
    the cycle counter, so nothing governance-relevant is lost).
    """
    record.setdefault("ts", utc_now_iso())
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        logger.debug("runtime run-log append failed", exc_info=True)
    return record


def read_records(path: Path | str, limit: int | None = None) -> list[dict]:
    """Parse the run-log, newest last. Corrupt/truncated lines are skipped.

    `limit` keeps only the newest N records (the file is append-only and can span
    weeks). A missing file is an empty history, not an error.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    records: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    if limit is not None and limit >= 0:
        records = records[-limit:]
    return records


def _epoch(iso_ts: str) -> float | None:
    try:
        dt = datetime.fromisoformat(iso_ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def summarize_recent(
    path: Path | str | None = None, *, hours: float = 24.0, now: float | None = None
) -> dict:
    """Roll the trailing window of the run-log into the dict the morning brief renders.

    Returns zeros (`cycles: 0`) rather than raising when the log is missing or
    empty — the brief shows the runtime section only when there is something real
    to say.
    """
    log_path = default_log_path() if path is None else Path(path)
    now = time.time() if now is None else float(now)
    cutoff = now - hours * 3600.0
    cycles = clean = degraded = errors = 0
    restarts = 0
    boots: set = set()
    done = failed = 0
    last_cycle: dict | None = None
    consecutive_clean = 0
    for rec in read_records(log_path):
        ts = _epoch(str(rec.get("ts", "")))
        if ts is None or ts < cutoff:
            continue
        phase = rec.get("phase")
        if phase == "supervisor":
            if rec.get("event") == "child_exit":
                restarts += 1
            continue
        if phase != "cycle":
            continue
        cycles += 1
        last_cycle = rec
        status = rec.get("status")
        if status == "clean":
            clean += 1
            consecutive_clean += 1
        else:
            consecutive_clean = 0
            if status == "degraded":
                degraded += 1
            else:
                errors += 1
        if rec.get("boot_id") is not None:
            boots.add(rec.get("boot_id"))
        worker = rec.get("worker")
        if isinstance(worker, dict):
            done += int(worker.get("done_delta", 0) or 0)
            failed += int(worker.get("failed_delta", 0) or 0)
    return {
        "window_hours": hours,
        "cycles": cycles,
        "clean": clean,
        "degraded": degraded,
        "errors": errors,
        "consecutive_clean": consecutive_clean,
        "boots": len(boots),
        "child_restarts": restarts,
        "tasks_done": done,
        "tasks_failed": failed,
        "last_cycle_ts": (last_cycle or {}).get("ts"),
        "last_status": (last_cycle or {}).get("status"),
        "night_shift_active": bool(((last_cycle or {}).get("night_shift") or {}).get("active")),
    }
