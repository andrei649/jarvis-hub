"""Durable checkpoint intent/task journal, never a source of effect authority.

A claim records that a separately authorized executor may have started. It does
not prove approval, owner identity, a live queue task, or physical route scope.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable
from contextlib import closing
from urllib.parse import quote

from .file_checkpoint_history import HISTORY_SUPPORTED, CheckpointRefusal, _locked
from .file_tools import SnapshotStore

MAX_JSON_BYTES = 128 * 1024
_REQUEST_ID = re.compile(r"[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA = """CREATE TABLE IF NOT EXISTS checkpoint_operations (
    request_id TEXT PRIMARY KEY,
    intent_sha TEXT NOT NULL,
    intent_json TEXT NOT NULL,
    task_id INTEGER UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('prepared','bound','running','completed','uncertain')),
    result_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)"""


class CheckpointOperationError(ValueError):
    """Malformed input or an untrusted/unavailable operation store."""


def _refused(reason: str) -> dict:
    return {"ok": False, "state": "refused", "reason": reason}


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > 64:
        raise ValueError("json_too_deep")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("invalid_json")
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("invalid_json_key")
            _validate_json_value(item, depth=depth + 1)
        return
    raise ValueError("invalid_json")


def _canonical(value: dict) -> tuple[str, str]:
    if type(value) is not dict:
        raise ValueError("invalid_json_object")
    _validate_json_value(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid_json") from exc
    if len(encoded) > MAX_JSON_BYTES:
        raise ValueError("json_too_large")
    return encoded.decode("utf-8"), hashlib.sha256(encoded).hexdigest()


def _parse_json(raw: str) -> dict:
    try:
        result = json.loads(raw, parse_constant=lambda _token: (_ for _ in ()).throw(
            ValueError("invalid_json")))
        canonical, _ = _canonical(result)
        if canonical != raw:
            raise ValueError("noncanonical_json")
        return result
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise CheckpointOperationError("store_invalid") from exc


def _valid_request(value: object) -> str:
    if type(value) is not str or _REQUEST_ID.fullmatch(value) is None:
        raise ValueError("invalid_request_id")
    return value


def _valid_sha(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError("invalid_intent_sha")
    return value


def _valid_task(value: object) -> int:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError("invalid_task_id")
    return value


class CheckpointOperationStore:
    """Monotonic, identity-bound operation records in a dedicated private DB."""

    def __init__(self, snapshots: SnapshotStore) -> None:
        self.snapshots = snapshots
        self._db = snapshots.directory / "checkpoint_operations.sqlite3"

    def _directory(self, *, create: bool) -> bool:
        directory = self.snapshots.directory
        if not directory.is_absolute():
            raise CheckpointOperationError("store_invalid")
        try:
            info = os.stat(directory, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                return False
            try:
                directory.mkdir(parents=True, exist_ok=False, mode=0o700)
            except FileExistsError:
                # Another cooperating producer created the directory first.
                pass
            except (OSError, ValueError) as exc:
                raise CheckpointOperationError("store_invalid") from exc
            try:
                info = os.stat(directory, follow_symlinks=False)
            except OSError as exc:
                raise CheckpointOperationError("store_invalid") from exc
        except OSError as exc:
            raise CheckpointOperationError("store_invalid") from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            raise CheckpointOperationError("store_invalid")
        return True

    def _db_identity(self, *, create: bool) -> tuple[int, int] | None:
        try:
            info = os.stat(self._db, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                return None
            try:
                fd = os.open(self._db, os.O_RDWR | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
                os.close(fd)
                info = os.stat(self._db, follow_symlinks=False)
            except OSError as exc:
                raise CheckpointOperationError("store_invalid") from exc
        except OSError as exc:
            raise CheckpointOperationError("store_invalid") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise CheckpointOperationError("store_invalid")
        return info.st_dev, info.st_ino

    def _connect(self, identity: tuple[int, int], *, readonly: bool) -> sqlite3.Connection:
        try:
            if readonly:
                uri = "file:" + quote(str(self._db), safe="/") + "?mode=ro"
                db = sqlite3.connect(uri, uri=True, timeout=5)
            else:
                db = sqlite3.connect(self._db, timeout=5)
            info = os.stat(self._db, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                    or (info.st_dev, info.st_ino) != identity):
                db.close()
                raise CheckpointOperationError("store_invalid")
            db.row_factory = sqlite3.Row
            if readonly:
                db.execute("PRAGMA query_only=ON")
            else:
                db.execute("PRAGMA synchronous=FULL")
            return db
        except (OSError, sqlite3.Error) as exc:
            raise CheckpointOperationError("store_invalid") from exc

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        if (type(row["request_id"]) is not str
                or _REQUEST_ID.fullmatch(row["request_id"]) is None
                or type(row["intent_sha"]) is not str
                or _SHA256.fullmatch(row["intent_sha"]) is None
                or row["state"] not in {"prepared", "bound", "running", "completed", "uncertain"}
                or (row["task_id"] is not None and
                    (type(row["task_id"]) is not int or row["task_id"] <= 0))
                or (row["state"] == "prepared" and row["task_id"] is not None)
                or (row["state"] != "prepared" and row["task_id"] is None)
                or (row["state"] == "completed") != (row["result_json"] is not None)):
            raise CheckpointOperationError("store_invalid")
        intent = _parse_json(row["intent_json"])
        if hashlib.sha256(row["intent_json"].encode()).hexdigest() != row["intent_sha"]:
            raise CheckpointOperationError("store_invalid")
        result = _parse_json(row["result_json"]) if row["result_json"] is not None else None
        return {"ok": True, "request_id": row["request_id"],
                "intent_sha": row["intent_sha"], "intent": intent,
                "task_id": row["task_id"], "state": row["state"], "result": result}

    @staticmethod
    def _row(db: sqlite3.Connection, request_id: str) -> sqlite3.Row | None:
        return db.execute("SELECT * FROM checkpoint_operations WHERE request_id=?",
                          (request_id,)).fetchone()

    def _write(self, body: Callable[[sqlite3.Connection], dict], *, create: bool = False) -> dict:
        if not HISTORY_SUPPORTED:
            raise CheckpointOperationError("unsupported_platform")
        if not self._directory(create=create):
            return _refused("request_missing")
        try:
            with _locked(self.snapshots.directory):
                identity = self._db_identity(create=create)
                if identity is None:
                    return _refused("request_missing")
                with closing(self._connect(identity, readonly=False)) as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    if create:
                        db.execute(_SCHEMA)
                    return body(db)
        except (OSError, sqlite3.Error, CheckpointRefusal) as exc:
            raise CheckpointOperationError("store_invalid") from exc

    def prepare(self, intent: dict) -> dict:
        canonical, intent_sha = _canonical(intent)  # Validate before any filesystem I/O.

        def insert(db: sqlite3.Connection) -> dict:
            for _ in range(3):
                request_id = secrets.token_hex(16)
                try:
                    now = time.time()
                    db.execute("INSERT INTO checkpoint_operations "
                               "(request_id,intent_sha,intent_json,state,created_at,updated_at) "
                               "VALUES (?,?,?,'prepared',?,?)",
                               (request_id, intent_sha, canonical, now, now))
                    return self._record(self._row(db, request_id))
                except sqlite3.IntegrityError:
                    continue
            raise CheckpointOperationError("request_id_collision")

        return self._write(insert, create=True)

    def get(self, request_id: str) -> dict | None:
        _valid_request(request_id)
        if not self._directory(create=False):
            return None
        identity = self._db_identity(create=False)
        if identity is None:
            return None
        with closing(self._connect(identity, readonly=True)) as db:
            try:
                row = self._row(db, request_id)
            except sqlite3.Error as exc:
                raise CheckpointOperationError("store_invalid") from exc
            return self._record(row) if row is not None else None

    def bind_task(self, request_id: str, task_id: int, intent_sha: str) -> dict:
        _valid_request(request_id)
        _valid_task(task_id)
        _valid_sha(intent_sha)

        def bind(db: sqlite3.Connection) -> dict:
            row = self._row(db, request_id)
            if row is None:
                return _refused("request_missing")
            record = self._record(row)
            if record["intent_sha"] != intent_sha:
                return _refused("intent_mismatch")
            if record["state"] == "bound" and record["task_id"] == task_id:
                return record
            if record["state"] != "prepared":
                return _refused("already_bound")
            try:
                db.execute("UPDATE checkpoint_operations SET task_id=?, state='bound', "
                           "updated_at=? WHERE request_id=? AND state='prepared'",
                           (task_id, time.time(), request_id))
            except sqlite3.IntegrityError:
                return _refused("task_bound_elsewhere")
            return self._record(self._row(db, request_id))

        return self._write(bind)

    def claim(self, request_id: str, *, task_id: int, intent_sha: str) -> dict:
        _valid_request(request_id)
        _valid_task(task_id)
        _valid_sha(intent_sha)

        def start(db: sqlite3.Connection) -> dict:
            row = self._row(db, request_id)
            if row is None:
                return _refused("request_missing")
            record = self._record(row)
            if record["intent_sha"] != intent_sha or record["task_id"] != task_id:
                return _refused("identity_mismatch")
            if record["state"] == "completed":
                record["replay"] = True
                return record
            if record["state"] == "running":
                return _refused("operation_in_flight")
            if record["state"] == "uncertain":
                return _refused("operation_uncertain")
            if record["state"] != "bound":
                return _refused("not_bound")
            db.execute("UPDATE checkpoint_operations SET state='running', updated_at=? "
                       "WHERE request_id=? AND state='bound'", (time.time(), request_id))
            result = self._record(self._row(db, request_id))
            result["replay"] = False
            return result

        return self._write(start)

    def finish(self, request_id: str, *, task_id: int,
               intent_sha: str, result: dict) -> dict:
        _valid_request(request_id)
        _valid_task(task_id)
        _valid_sha(intent_sha)
        canonical, _ = _canonical(result)  # No I/O for malformed result.

        def complete(db: sqlite3.Connection) -> dict:
            row = self._row(db, request_id)
            if row is None:
                return _refused("request_missing")
            record = self._record(row)
            if record["intent_sha"] != intent_sha or record["task_id"] != task_id:
                return _refused("identity_mismatch")
            if record["state"] != "running":
                return _refused("not_running")
            db.execute("UPDATE checkpoint_operations SET state='completed', result_json=?, "
                       "updated_at=? WHERE request_id=? AND state='running'",
                       (canonical, time.time(), request_id))
            return self._record(self._row(db, request_id))

        return self._write(complete)

    def mark_uncertain(self, request_id: str, *, task_id: int,
                       intent_sha: str) -> dict:
        _valid_request(request_id)
        _valid_task(task_id)
        _valid_sha(intent_sha)

        def uncertain(db: sqlite3.Connection) -> dict:
            row = self._row(db, request_id)
            if row is None:
                return _refused("request_missing")
            record = self._record(row)
            if record["intent_sha"] != intent_sha or record["task_id"] != task_id:
                return _refused("identity_mismatch")
            if record["state"] != "running":
                return _refused("not_running")
            db.execute("UPDATE checkpoint_operations SET state='uncertain', updated_at=? "
                       "WHERE request_id=? AND state='running'", (time.time(), request_id))
            return self._record(self._row(db, request_id))

        return self._write(uncertain)
