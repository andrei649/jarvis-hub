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


def audit_key() -> bytes:
    """The HMAC key: the env value, else the persisted key file (created atomically)."""
    configured = env_str(ENV_AUDIT_KEY, "").strip()
    if configured:
        return configured.encode("utf-8")
    path = key_path()
    if path.exists():
        stored = path.read_bytes().strip()
        if not stored:
            raise RuntimeError(f"workspace audit key file {path} is empty")
        return stored
    return config.create_private_file(path, secrets.token_hex(32).encode("ascii")).strip()


def key_fingerprint(key: bytes | None = None) -> str:
    """First 16 hex chars of SHA-256(key) — identifies a key without revealing it."""
    return hashlib.sha256(key if key is not None else audit_key()).hexdigest()[:16]


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
    message = _DOMAIN + prev_hash.encode("ascii") + canonical.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def record(conn: sqlite3.Connection, *, actor: WorkspaceUser | None, action: str,
           target_type: str = "", target_id: str | int = "", department_id: int | None = None,
           ip: str = "", details: dict | None = None, actor_email: str = "") -> None:
    """Append one audit row inside the caller's open transaction.

    *actor_email* names a non-user actor (``'cli'``) or the email a failed login tried;
    with an *actor* it defaults to the actor's email.
    """
    if not conn.in_transaction:
        raise RuntimeError("audit.record must run inside a transaction (use db.tx)")
    key = audit_key()
    clean = _clean_details(details, action)
    fields = {
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
        "details": clean,
    }
    row = conn.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = row["hash"] if row else GENESIS_HASH
    digest = _row_hash(key, prev_hash, _canonical(fields))
    conn.execute(
        "INSERT INTO audit (ts, actor_user_id, actor_email, action, target_type, target_id, "
        "department_id, ip, details_json, prev_hash, hash, key_fp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fields["ts"], fields["actor_user_id"], fields["actor_email"], action, target_type,
         fields["target_id"], department_id, ip, _canonical(clean), prev_hash, digest,
         key_fingerprint(key)),
    )


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


def verify_chain(conn: sqlite3.Connection) -> dict:
    """Walk the chain from the first row; stop at the first break.

    ``key_mismatch`` is true when the broken row was written under a different key
    (its ``key_fp`` differs from the current key's): the log may be intact but cannot
    be verified with the key this install has now.
    """
    key = audit_key()
    current_fp = key_fingerprint(key)
    prev_hash = GENESIS_HASH
    checked = 0
    cursor = conn.execute("SELECT * FROM audit ORDER BY id")
    for row in cursor:
        expected = _row_hash(key, prev_hash, _canonical(_fields_of(row)))
        if row["prev_hash"] != prev_hash or not hmac.compare_digest(row["hash"], expected):
            cursor.close()
            return {"ok": False, "checked": checked, "broken_at": int(row["id"]), "keyed": True,
                    "key_mismatch": row["key_fp"] != current_fp}
        prev_hash = row["hash"]
        checked += 1
    return {"ok": True, "checked": checked, "broken_at": None, "keyed": True,
            "key_mismatch": False}
