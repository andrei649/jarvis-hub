"""Tamper-evident audit trail of the workspace (spec §6 "Audit").

Every consequential action appends one row whose ``hash`` is an HMAC over the previous
row's hash plus a canonical JSON of the row. Editing, deleting or re-ordering a row
breaks every hash after it, and without the key nobody can recompute a valid chain —
which is why the key lives outside the data root (``JARVIS_AUDIT_KEY``, else a 0600
file under ``JARVIS_KEY_DIR``): a backup or a leaked data folder never carries it.

Rows are appended inside the caller's transaction (``BEGIN IMMEDIATE`` holds the write
lock), so reading the previous hash and inserting the next one cannot interleave with
another writer — in this process or another.

Details never carry passwords, tokens, prompts, answers or document text; a key with
such a name — at any nesting depth, or any key naming a credential such as
``smtp_password`` — is dropped (and the drop logged by key name) rather than failing
the user's action.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.core.env_config import env_str
from agents.core.workspace import config, db
from agents.core.workspace.errors import WorkspaceError

if TYPE_CHECKING:
    from agents.core.workspace.identity import WorkspaceUser

logger = logging.getLogger("nerva.workspace.audit")

ENV_AUDIT_KEY = "JARVIS_AUDIT_KEY"
ENV_KEY_DIR = "JARVIS_KEY_DIR"
KEY_FILE = "workspace_audit.key"
GENESIS_HASH = "0" * 64
_DOMAIN = b"nerva-ws-audit-v1"

#: Detail keys that would carry secrets or content; they never reach the audit table.
FORBIDDEN_DETAIL_KEYS = frozenset({
    "password", "new_password", "current_password", "password_hash", "token", "csrf_token",
    "secret", "setup_code", "prompt", "answer", "content", "content_md", "text", "body",
    "body_markdown", "preview",
})


def key_path() -> Path:
    """``(JARVIS_KEY_DIR or ~/.config/jarvis)/workspace_audit.key``."""
    base = env_str(ENV_KEY_DIR, "").strip()
    directory = Path(base).expanduser() if base else Path.home() / ".config" / "jarvis"
    return directory / KEY_FILE


class AuditKeyError(WorkspaceError):
    """This process cannot extend the trail with the key it has (``503``; nothing is written)."""


class AuditKeyMissing(AuditKeyError):
    """``503 audit_key_missing``: the trail has rows but this process has no key for it.

    Minting a fresh key then would sign every new row with a key the earlier rows were
    not written with, and break the chain for good — a process started without the
    service's ``JARVIS_AUDIT_KEY`` / ``JARVIS_KEY_DIR`` (a bare-shell CLI, a moved or
    restored install) must stop instead. Nothing is written while the key is missing.
    """

    def __init__(self, path: Path) -> None:
        super().__init__("audit_key_missing",
                         "the audit key of this workspace is not available to this process", 503)
        self.path = path


class AuditKeyMismatch(AuditKeyError):
    """``503 audit_key_mismatch``: this process has a key, but not the trail's (review OPS2-01).

    The newest row was signed with another key — a hub rebuilt with freshly generated
    keys, another ``JARVIS_KEY_DIR``, a restore without ``/etc/jarvis-hub/jarvis.env``.
    One row signed with this key would break the chain for good: restoring the right key
    afterwards could not repair it. So every write stops (logged with the key's source
    and both fingerprints, never the key) until the service's key is back — or until an
    operator replaces a key that is truly lost with :func:`rekey` (``audit-rekey``).
    """

    def __init__(self, source: str, key_fp: str, trail_key_fp: str) -> None:
        super().__init__("audit_key_mismatch",
                         "the audit key of this process is not the one the workspace's audit "
                         "trail was written with", 503)
        self.source = source
        self.key_fp = key_fp
        self.trail_key_fp = trail_key_fp


class RekeyRefused(RuntimeError):
    """:func:`rekey` will not run; ``reason`` is ``not_needed``, ``no_key`` or ``broken``."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _configured_key() -> bytes | None:
    configured = env_str(ENV_AUDIT_KEY, "").strip()
    return configured.encode("utf-8") if configured else None


def _stored_key(path: Path) -> bytes | None:
    if not path.exists():
        return None
    stored = path.read_bytes().strip()
    if not stored:
        raise RuntimeError(f"workspace audit key file {path} is empty")
    return stored


def _trail_has_rows(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM audit LIMIT 1").fetchone() is not None


def audit_key(conn: sqlite3.Connection | None = None) -> bytes:
    """The HMAC key: the env value, else the persisted key file (created atomically).

    A key file is created only for a trail that is still empty. With *conn* given and
    rows already in its trail, a missing key raises :class:`AuditKeyMissing` instead
    (logged with the path that was looked at); :func:`record` and :func:`verify_chain`
    always pass their connection.
    """
    configured = _configured_key()
    if configured is not None:
        return configured
    path = key_path()
    stored = _stored_key(path)
    if stored is not None:
        return stored
    if conn is not None and _trail_has_rows(conn):
        logger.error(
            "workspace audit key missing: %s is not set and %s does not exist, but the audit "
            "trail already has rows — refusing to create a new key (it would break the chain). "
            "Run with the service's environment (JARVIS_AUDIT_KEY / JARVIS_KEY_DIR).",
            ENV_AUDIT_KEY, path)
        raise AuditKeyMissing(path)
    return config.create_private_file(path, secrets.token_hex(32).encode("ascii")).strip()


def key_source() -> str:
    """Where this process's key comes from: ``JARVIS_AUDIT_KEY`` or the key file's path."""
    return ENV_AUDIT_KEY if _configured_key() is not None else str(key_path())


def existing_key() -> bytes | None:
    """The key this process would sign with, without ever creating one (``None``: none here).

    Raises ``OSError`` / ``RuntimeError`` for a key file that cannot be read or is empty.
    """
    return _configured_key() or _stored_key(key_path())


def key_check(conn: sqlite3.Connection) -> str:
    """Can this process extend *conn*'s trail? ``ok``, ``missing``, ``unreadable`` or ``mismatch``.

    ``ok`` for an empty trail or when the key this process would sign with is the one
    the newest row was signed with. ``missing``: no ``JARVIS_AUDIT_KEY`` and no key file
    here. ``mismatch``: a key, but another one than the newest row's. Never creates a key.
    """
    row = conn.execute("SELECT key_fp FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return "ok"
    try:
        key = existing_key()
    except (OSError, RuntimeError):
        return "unreadable"
    if key is None:
        return "missing"
    return "ok" if row["key_fp"] == key_fingerprint(key) else "mismatch"


def startup_key_check() -> str | None:
    """Say at hub start, in the log, that this hub cannot sign the audit trail (OPS2-01).

    Reads only, and only a workspace database that already exists (opened read-only:
    nothing is created or migrated). Returns :func:`key_check`'s state, or ``None`` when
    there is nothing to check (workspace off, no database yet). A key that is not ``ok``
    is logged as an error naming its source and both fingerprints: every sign-in and
    every change will answer ``503`` until the service's key is restored.
    """
    if not config.enabled():
        return None
    path = db.existing_db_path()
    if not path.exists():
        return None
    conn = db.connect_read_only(path)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit'"
                        ).fetchone() is None:
            return None
        state = key_check(conn)
        newest = conn.execute("SELECT key_fp FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if state == "ok":
        return state
    trail_fp = newest["key_fp"] if newest is not None else ""
    if state == "mismatch":
        key = existing_key()
        detail = (f"the key from {key_source()} (fingerprint "
                  f"{key_fingerprint(key) if key is not None else '?'}) is not the one the newest "
                  f"audit row was signed with (fingerprint {trail_fp})")
        code = "audit_key_mismatch"
    else:
        detail = (f"the audit key is {state}: {ENV_AUDIT_KEY} is not set and {key_path()} does "
                  f"not exist or cannot be read, but the audit trail has rows")
        code = "audit_key_missing"
    logger.error(
        "Nerva Workspace cannot sign its audit trail: %s. Every sign-in and every change will be "
        "refused (503 %s) and nothing will be written until the service's %s / %s are "
        "restored; check with: python -m agents.core.workspace check (PILOT_GUIDE §17).",
        detail, code, ENV_AUDIT_KEY, ENV_KEY_DIR)
    return state


def key_fingerprint(key: bytes | None = None, conn: sqlite3.Connection | None = None) -> str:
    """First 16 hex chars of SHA-256(key) — identifies a key without revealing it."""
    return hashlib.sha256(key if key is not None else audit_key(conn)).hexdigest()[:16]


#: A key containing one of these names a credential (``smtp_password``, ``api_token`` …).
_CREDENTIAL_KEY_PARTS = ("password", "token", "secret", "api_key", "apikey")


def _forbidden_detail(name: str, value: Any) -> bool:
    lowered = name.lower()
    if lowered in FORBIDDEN_DETAIL_KEYS:
        return True
    # Flags and counts cannot carry a credential, so ``has_password: true`` and
    # ``prompt_tokens: 512`` stay readable; text and structures under such a name go.
    if value is None or isinstance(value, bool | int | float):
        return False
    return any(part in lowered for part in _CREDENTIAL_KEY_PARTS)


def _clean_value(value: Any, action: str, path: str) -> Any:
    if isinstance(value, dict):
        return _clean_details(value, action, path)
    if isinstance(value, list | tuple):
        return [_clean_value(item, action, path) for item in value]
    return value


def _clean_details(details: dict | None, action: str, path: str = "") -> dict:
    """*details* without credential or content keys, at any nesting depth."""
    cleaned: dict[str, Any] = {}
    for name, value in (details or {}).items():
        key = str(name)
        if _forbidden_detail(key, value):
            logger.warning("audit %s: dropped detail key %r (content never goes to audit)",
                           action, path + key)
            continue
        cleaned[key] = _clean_value(value, action, f"{path}{key}.")
    return cleaned


def _canonical(fields: dict) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _row_hash(key: bytes, prev_hash: str, canonical: str) -> str:
    # utf-8, not ascii: identical bytes for a real (hex) hash, and a tampered non-ASCII
    # one reads as a broken row instead of an exception.
    message = _DOMAIN + prev_hash.encode("utf-8") + canonical.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _newest(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT id, hash, key_fp FROM audit ORDER BY id DESC LIMIT 1").fetchone()


def _fields(*, actor: WorkspaceUser | None, action: str, target_type: str, target_id: str | int,
            department_id: int | None, ip: str, details: dict, actor_email: str) -> dict:
    return {
        # float(): the column is REAL, so an int clock value would read back as 1.0-style
        # and change the canonical JSON the hash was computed over.
        "ts": float(db.now()),
        "actor_user_id": actor.id if actor is not None else None,
        "actor_email": actor_email or (actor.email if actor is not None else ""),
        "action": action,
        "target_type": target_type,
        "target_id": str(target_id),
        "department_id": department_id,
        "ip": ip,
        "details": details,
    }


def _append(conn: sqlite3.Connection, key: bytes, newest: sqlite3.Row | None,
            fields: dict) -> int:
    prev_hash = newest["hash"] if newest is not None else GENESIS_HASH
    digest = _row_hash(key, prev_hash, _canonical(fields))
    cursor = conn.execute(
        "INSERT INTO audit (ts, actor_user_id, actor_email, action, target_type, target_id, "
        "department_id, ip, details_json, prev_hash, hash, key_fp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fields["ts"], fields["actor_user_id"], fields["actor_email"], fields["action"],
         fields["target_type"], fields["target_id"], fields["department_id"], fields["ip"],
         _canonical(fields["details"]), prev_hash, digest, key_fingerprint(key)),
    )
    return int(cursor.lastrowid)


def record(conn: sqlite3.Connection, *, actor: WorkspaceUser | None, action: str,
           target_type: str = "", target_id: str | int = "", department_id: int | None = None,
           ip: str = "", details: dict | None = None, actor_email: str = "") -> None:
    """Append one audit row inside the caller's open transaction.

    *actor_email* names a non-user actor (``'cli'``) or the email a failed login tried;
    with an *actor* it defaults to the actor's email. Raises :class:`AuditKeyMissing` /
    :class:`AuditKeyMismatch` (``503``, nothing written — the caller's transaction rolls
    back with it) when this process's key is not the one the newest row was signed with.
    """
    if not conn.in_transaction:
        raise RuntimeError("audit.record must run inside a transaction (use db.tx)")
    key = audit_key(conn)
    newest = _newest(conn)
    fingerprint = key_fingerprint(key)
    if newest is not None and newest["key_fp"] != fingerprint:
        source = key_source()
        logger.error(
            "workspace audit key mismatch: the key from %s (fingerprint %s) is not the one the "
            "newest audit row was signed with (fingerprint %s) — refusing to write %s: one row "
            "under this key would break the chain for good. Restore the service's %s / %s "
            "(check with: python -m agents.core.workspace check); a key that is truly lost is "
            "replaced with: python -m agents.core.workspace audit-rekey.",
            source, fingerprint, newest["key_fp"], action, ENV_AUDIT_KEY, ENV_KEY_DIR)
        raise AuditKeyMismatch(source, fingerprint, newest["key_fp"])
    _append(conn, key, newest, _fields(
        actor=actor, action=action, target_type=target_type, target_id=target_id,
        department_id=department_id, ip=ip, details=_clean_details(details, action),
        actor_email=actor_email))


def _fields_of(row: sqlite3.Row) -> dict:
    try:
        details = json.loads(row["details_json"])
    except ValueError:
        details = {"__unreadable__": row["details_json"]}
    return {
        "ts": row["ts"], "actor_user_id": row["actor_user_id"], "actor_email": row["actor_email"],
        "action": row["action"], "target_type": row["target_type"], "target_id": row["target_id"],
        "department_id": row["department_id"], "ip": row["ip"], "details": details,
    }


def _hmac_ok(key: bytes, prev_hash: str, row: sqlite3.Row) -> bool:
    expected = _row_hash(key, prev_hash, _canonical(_fields_of(row)))
    return hmac.compare_digest(str(row["hash"]).encode("utf-8"), expected.encode("ascii"))


# ── re-keying: replacing a key that is truly lost, on purpose and on the record ───────

#: The action of the row :func:`rekey` writes.
REKEY_ACTION = "audit.rekeyed"
#: Every stored column of a row, in a fixed order: what a re-key pins.
_PIN_COLUMNS = ("id", "ts", "actor_user_id", "actor_email", "action", "target_type", "target_id",
                "department_id", "ip", "details_json", "prev_hash", "hash", "key_fp")


def _pin_line(row: sqlite3.Row) -> bytes:
    return (_canonical({name: row[name] for name in _PIN_COLUMNS}) + "\n").encode("utf-8")


def rekey_plan(conn: sqlite3.Connection) -> dict:
    """What :func:`rekey` would do with the key this process has; reads only.

    ``{state, rows, unverified, broken_at, from_key_fp, to_key_fp, through_id, digest}``:
    *state* is :func:`key_check`'s answer; *unverified* counts the rows the key in use
    cannot verify (signed with another key); *broken_at* is the first row that is broken
    for another reason — a link to the previous row that does not hold, or a row the key
    in use signed whose HMAC fails — which a re-key must never paper over. *through_id*
    and *digest* pin every row as it stands now (SHA-256 over all their columns).
    """
    state = key_check(conn)
    newest = _newest(conn)
    rows = int(conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0])
    plan: dict[str, Any] = {
        "state": state, "rows": rows, "unverified": 0, "broken_at": None,
        "from_key_fp": newest["key_fp"] if newest is not None else None, "to_key_fp": None,
        "through_id": None, "digest": None,
    }
    key = existing_key() if state in ("ok", "mismatch") else None
    if key is None:
        return plan
    fingerprint = key_fingerprint(key)
    plan["to_key_fp"] = fingerprint
    pin = hashlib.sha256()
    prev_hash = GENESIS_HASH
    cursor = conn.execute("SELECT * FROM audit ORDER BY id")
    try:
        for row in cursor:
            valid = row["prev_hash"] == prev_hash and _hmac_ok(key, prev_hash, row)
            if not valid and (row["prev_hash"] != prev_hash or row["key_fp"] == fingerprint):
                plan["broken_at"] = int(row["id"])
                return plan
            if not valid:
                plan["unverified"] += 1
            pin.update(_pin_line(row))
            plan["through_id"] = int(row["id"])
            prev_hash = row["hash"]
    finally:
        cursor.close()
    plan["digest"] = pin.hexdigest()
    return plan


def rekey(conn: sqlite3.Connection, *, actor_email: str) -> int:
    """Make the key this process has the trail's key from now on; returns the new row's id.

    Only for a key that is truly lost (PILOT_GUIDE §16): the rows signed with the old
    key can never be verified again. One ``audit.rekeyed`` row, signed with the new key,
    records both fingerprints and pins every earlier row (:func:`rekey_plan`), so
    :func:`verify_chain` checks every row the new key can, counts the others as
    ``unverified``, and still notices any later edit, deletion or reordering of them.
    Never creates a key. Raises :class:`RekeyRefused` — nothing written — when the key
    already matches (``not_needed``), when this process has no key (``no_key``), or when
    the trail is broken for another reason than the key (``broken``).
    """
    with db.tx(conn):
        plan = rekey_plan(conn)
        if plan["state"] == "ok":
            raise RekeyRefused("not_needed", "the audit key already matches the trail's newest "
                                             "row; there is nothing to re-key")
        if plan["state"] in ("missing", "unreadable"):
            raise RekeyRefused("no_key", f"this process has no readable audit key "
                                         f"({ENV_AUDIT_KEY} is unset and {key_path()} is missing "
                                         f"or unreadable); a re-key never creates one")
        if plan["broken_at"] is not None:
            raise RekeyRefused("broken", f"the audit trail is broken at row {plan['broken_at']} "
                                         f"for another reason than the key; a re-key cannot "
                                         f"repair that — restore a backup")
        key = existing_key()
        if key is None:   # removed between the plan and now
            raise RekeyRefused("no_key", "the audit key disappeared; nothing was changed")
        details = {name: plan[name] for name in ("from_key_fp", "to_key_fp", "through_id", "rows",
                                                 "unverified", "digest")}
        row_id = _append(conn, key, _newest(conn), _fields(
            actor=None, action=REKEY_ACTION, target_type="audit", target_id=plan["through_id"],
            department_id=None, ip="", details=details, actor_email=actor_email))
    logger.warning("workspace audit trail re-keyed by %s: key %s replaces %s; %d of the %d "
                   "earlier rows can no longer be verified", actor_email, plan["to_key_fp"],
                   plan["from_key_fp"], plan["unverified"], plan["rows"])
    return row_id


def _adoption(conn: sqlite3.Connection, fingerprint: str) -> int | None:
    """The newest re-key to the key *fingerprint* names (verified while walking the chain)."""
    row = conn.execute("SELECT id FROM audit WHERE action = ? AND key_fp = ? "
                       "ORDER BY id DESC LIMIT 1", (REKEY_ACTION, fingerprint)).fetchone()
    return int(row["id"]) if row is not None else None


def _pin_holds(row: sqlite3.Row, digest: str, rows: int, through_id: int | None) -> bool:
    try:
        details = json.loads(row["details_json"])
    except ValueError:
        return False
    return (isinstance(details, dict) and details.get("digest") == digest
            and details.get("rows") == rows and details.get("through_id") == through_id)


def verify_chain(conn: sqlite3.Connection) -> dict:
    """Walk the chain from the first row; stop at the first break.

    ``key_mismatch`` is true when the broken row was written under a different key
    (its ``key_fp`` differs from the current key's): the log may be intact but cannot
    be verified with the key this install has now.

    After a re-key to the current key (:func:`rekey`; ``rekeyed_at`` is that row's id,
    else ``None``) the rows before it that another key signed cannot be checked: they
    are counted as ``unverified`` instead of breaking the chain, as long as the re-key
    row's pin of them still holds. Every row the current key signed is checked, before
    the re-key as after it; ``checked`` counts those.
    """
    key = audit_key(conn)
    current_fp = key_fingerprint(key)
    adopted_at = _adoption(conn, current_fp)
    pin = hashlib.sha256()
    pinned = 0
    through_id: int | None = None
    prev_hash = GENESIS_HASH
    checked = unverified = 0

    def result(broken_at: int | None, key_mismatch: bool = False) -> dict:
        return {"ok": broken_at is None, "checked": checked, "broken_at": broken_at,
                "keyed": True, "key_mismatch": key_mismatch, "unverified": unverified,
                "rekeyed_at": adopted_at}

    cursor = conn.execute("SELECT * FROM audit ORDER BY id")
    try:
        for row in cursor:
            row_id = int(row["id"])
            other_key = row["key_fp"] != current_fp
            if row["prev_hash"] != prev_hash:
                return result(row_id, other_key)
            valid = _hmac_ok(key, prev_hash, row)
            if adopted_at is not None and row_id < adopted_at:
                if not valid and not other_key:
                    return result(row_id)     # the key in use signed it: it must verify
                if valid:
                    checked += 1
                else:
                    unverified += 1
                pin.update(_pin_line(row))
                pinned += 1
                through_id = row_id
            else:
                if not valid:
                    return result(row_id, other_key)
                if row_id == adopted_at and not _pin_holds(row, pin.hexdigest(), pinned,
                                                           through_id):
                    return result(row_id)     # the rows it pinned changed after the re-key
                checked += 1
            prev_hash = row["hash"]
    finally:
        cursor.close()
    return result(None)
