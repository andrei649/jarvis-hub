"""Who a workspace user is and what they may touch (spec §5, §6).

Passwords are hashed with scrypt (memory-hard, stdlib) and the work factor is stored
in each hash, so raising ``SCRYPT_N`` later never invalidates existing accounts.
Verification of an unknown or password-less account still runs a full scrypt against a
fixed dummy hash: the login timing must not reveal which emails exist.

:class:`WorkspaceUser` is the immutable view every authorization decision is made on.
Its ``department_ids`` holds only the user's *non-archived* departments — an archived
department is visible to admins only, and building that rule into the value means no
caller can forget it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any

from agents.core.workspace.errors import WorkspaceError

logger = logging.getLogger("nerva.workspace.identity")

COMPANY = "company"
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024

ROLES = ("admin", "approver", "member")
STATUSES = ("invited", "active", "disabled")
LOCALES = ("ro", "en")
THEMES = ("light", "dark", "system")
MIN_PASSWORD_LEN = 12
MAX_PASSWORD_LEN = 256

# Embedded list of very common choices (international + Romanian). Exact matches and
# "word + digits/symbols" variants of them are refused, so "Password2026!" fails too.
_COMMON_TEXT = """
123456 123456789 12345678 1234567890 12345 1234567 123123 111111 000000 654321 666666
121212 112233 123321 987654321 7777777 555555 11111111 1q2w3e4r 1qaz2wsx qwerty qwerty123
qwertyuiop qwertyuiop12 asdfgh asdfghjkl zxcvbn zxcvbnm qazwsx 123qwe abc123 a1b2c3
password password1 password12 password123 password1234 passw0rd p@ssw0rd p@ssword
letmein letmein123 welcome welcome1 welcome123 welcome12345 admin admin123 admin1234
administrator root toor changeme changeme123 default guest login master monkey dragon
shadow sunshine princess football baseball soccer hockey basketball superman batman
iloveyou trustno1 starwars freedom whatever hello hello123 secret secret123 access
michael jennifer jordan hunter buster harley tigger charlie robert thomas daniel andrew
jessica ashley michelle nicole amanda matthew joshua ginger pepper summer winter
computer internet samsung google mustang ferrari killer cheese chocolate flower
qwerty12345 abcdef abcdefgh abcd1234 1234abcd test test123 testtest demo demo123
nerva nerva123 jarvis workspace company office business
parola parola1 parola12 parola123 parola1234 parolamea parolanoua parolaparola
romania bucuresti bucharest cluj iasi timisoara constanta brasov craiova steaua
dinamo rapid craciun iubire iubirea dragoste fericire libertate soare floare
mama tata familie copii prieten salut buna buna123 noroc
"""
_COMMON_CHOICES = frozenset(_COMMON_TEXT.split())
_TRIVIAL_TAIL = re.compile(r"[\d\W_]+$")
_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")
_DUMMY_HASHES: dict[int, str] = {}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen,
                          maxmem=SCRYPT_MAXMEM)


def hash_password(pw: str) -> str:
    """``scrypt$<log2 n>$8$1$<salt b64>$<hash b64>``. CPU-heavy: use ``asyncio.to_thread``."""
    n = SCRYPT_N
    salt = secrets.token_bytes(16)
    digest = _scrypt(pw, salt, n, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
    return f"scrypt${n.bit_length() - 1}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def _parse_hash(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        log_n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = base64.b64decode(parts[4], validate=True)
        digest = base64.b64decode(parts[5], validate=True)
    except ValueError:
        return None
    # Bounds keep a corrupted row from turning one login into a memory bomb; parameters
    # OpenSSL would refuse (over SCRYPT_MAXMEM, or n >= 2**(16r)) count as unreadable.
    if not (1 <= log_n <= 20 and 1 <= r <= 16 and 1 <= p <= 4 and salt and 16 <= len(digest) <= 64):
        return None
    n = 1 << log_n
    if log_n >= 16 * r or _scrypt_memory(n, r, p) > SCRYPT_MAXMEM:
        return None
    return n, r, p, salt, digest


def _scrypt_memory(n: int, r: int, p: int) -> int:
    """Bytes OpenSSL's scrypt allocates for these parameters (its ``maxmem`` check)."""
    return 128 * r * (n + 2) + 128 * r * p


def _matches(pw: str, parsed: tuple[int, int, int, bytes, bytes]) -> bool:
    n, r, p, salt, digest = parsed
    try:
        computed = _scrypt(pw, salt, n, r, p, len(digest))
    except ValueError:
        # OpenSSL refused the stored parameters: a failed login, never a 500.
        logger.warning("a stored login hash has parameters scrypt refuses")
        return False
    return hmac.compare_digest(computed, digest)


def _dummy_hash() -> str:
    """A fixed hash at the current work factor, computed once per factor."""
    if SCRYPT_N not in _DUMMY_HASHES:
        _DUMMY_HASHES[SCRYPT_N] = hash_password(secrets.token_urlsafe(24))
    return _DUMMY_HASHES[SCRYPT_N]


def verify_password(pw: str, stored: str | None) -> bool:
    """Constant-time check; ``None`` or an unreadable hash burns a dummy verify and fails."""
    parsed = _parse_hash(stored) if stored else None
    if parsed is None:
        dummy = _parse_hash(_dummy_hash())
        if dummy is not None:
            _matches(pw, dummy)
        return False
    return _matches(pw, parsed)


def _too_common(pw: str) -> bool:
    folded = pw.casefold()
    if folded in _COMMON_CHOICES or len(set(folded)) <= 3:
        return True
    core = _TRIVIAL_TAIL.sub("", folded)
    return core in _COMMON_CHOICES


def validate_password(pw: str, *, email: str = "") -> None:
    """Raise ``422 weak_password`` with ``reason`` too_short|too_long|contains_email|too_common."""
    def weak(reason: str, message: str) -> WorkspaceError:
        return WorkspaceError("weak_password", message, 422, reason=reason,
                              min_length=MIN_PASSWORD_LEN)

    if len(pw) > MAX_PASSWORD_LEN:
        raise weak("too_long", f"use at most {MAX_PASSWORD_LEN} characters")
    if len(pw) < MIN_PASSWORD_LEN:
        raise weak("too_short", f"use at least {MIN_PASSWORD_LEN} characters")
    local_part = email.split("@", 1)[0].casefold() if email else ""
    if len(local_part) >= 3 and local_part in pw.casefold():
        raise weak("contains_email", "the password must not contain your email address")
    if _too_common(pw):
        raise weak("too_common", "this password is too common")


@dataclass(frozen=True)
class WorkspaceUser:
    """An authenticated (or looked-up) user; ``department_ids`` excludes archived ones."""

    id: int
    email: str
    name: str
    role: str
    status: str
    locale: str
    theme: str
    department_ids: tuple[int, ...]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @staticmethod
    def _check_id(department_id: object) -> None:
        if isinstance(department_id, bool) or not isinstance(department_id, int):
            raise TypeError(
                "department_id must be an int; company-wide scope is handled explicitly "
                f"(got {department_id!r})"
            )

    def can_access_department(self, department_id: int) -> bool:
        """Admins: any department (archived included); others: their non-archived ones."""
        self._check_id(department_id)
        return self.is_admin or department_id in self.department_ids

    def can_approve_in(self, department_id: int) -> bool:
        """Admins anywhere; approvers in their own (non-archived) departments."""
        self._check_id(department_id)
        if self.is_admin:
            return True
        return self.role == "approver" and department_id in self.department_ids

    def allowed_department_ids(self, conn: sqlite3.Connection) -> list[int]:
        """Departments the user may work in: admins all non-archived, others their own."""
        rows = conn.execute("SELECT id FROM departments WHERE archived = 0 ORDER BY id").fetchall()
        live = [int(row["id"]) for row in rows]
        if self.is_admin:
            return live
        return [dept_id for dept_id in live if dept_id in self.department_ids]


def _user_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> WorkspaceUser:
    dept_rows = conn.execute(
        "SELECT ud.department_id FROM user_departments ud "
        "JOIN departments d ON d.id = ud.department_id "
        "WHERE ud.user_id = ? AND d.archived = 0 ORDER BY ud.department_id",
        (row["id"],),
    ).fetchall()
    return WorkspaceUser(
        id=int(row["id"]), email=row["email"], name=row["name"], role=row["role"],
        status=row["status"], locale=row["locale"], theme=row["theme"],
        department_ids=tuple(int(r["department_id"]) for r in dept_rows),
    )


def get_user(conn: sqlite3.Connection, user_id: int) -> WorkspaceUser | None:
    """The user with *user_id* (any status), or ``None``."""
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_from_row(conn, row) if row else None


def get_user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    """The raw ``users`` row for *email* (case-insensitive), or ``None``."""
    return conn.execute("SELECT * FROM users WHERE email = ?", (email.strip(),)).fetchone()


def member_department_ids(conn: sqlite3.Connection, user_id: int) -> list[int]:
    """Every membership of *user_id*, archived departments included (admin views)."""
    rows = conn.execute(
        "SELECT department_id FROM user_departments WHERE user_id = ? ORDER BY department_id",
        (user_id,),
    ).fetchall()
    return [int(row["department_id"]) for row in rows]


def user_to_json(u: WorkspaceUser, conn: sqlite3.Connection | None = None) -> dict:
    """The user as the API shows it; with *conn*, permissions list the usable departments."""
    permissions: dict[str, Any] = {
        "admin_console": u.is_admin,
        "approve": u.role in ("admin", "approver"),
        "decide_admin_approvals": u.is_admin,
        "upload_company": u.is_admin,
    }
    if conn is not None:
        permissions["department_ids"] = u.allowed_department_ids(conn)
    return {
        "id": u.id, "email": u.email, "name": u.name, "role": u.role, "status": u.status,
        "locale": u.locale, "theme": u.theme, "department_ids": list(u.department_ids),
        "permissions": permissions,
    }


def department_to_json(row: sqlite3.Row | dict, *, counts: dict | None = None) -> dict:
    """A department row as JSON (``archived`` as a bool), plus any *counts* given."""
    data = {
        "id": int(row["id"]), "slug": row["slug"], "name": row["name"],
        "description": row["description"], "assistant_instructions": row["assistant_instructions"],
        "archived": bool(row["archived"]), "created_at": row["created_at"],
    }
    if counts:
        data.update(counts)
    return data


def ensure_org(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """The organisation row, or ``None`` while first-run setup has not happened."""
    return conn.execute("SELECT * FROM org WHERE id = 1").fetchone()


def org_to_json(row: sqlite3.Row) -> dict:
    """Public organisation fields; ``settings_json`` (SMTP and the like) never leaves here."""
    return {
        "name": row["name"], "default_locale": row["default_locale"],
        "model_policy": row["model_policy"], "created_at": row["created_at"],
    }


def slugify(name: str) -> str:
    """ASCII slug of *name* (Romanian diacritics folded), at most 64 chars, never empty."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_SEPARATORS.sub("-", folded.lower()).strip("-")[:64].strip("-")
    return slug or "departament"


def unique_department_slug(conn: sqlite3.Connection, name: str) -> str:
    """:func:`slugify` made unique among departments with a ``-2``, ``-3`` … suffix."""
    base = slugify(name)
    candidate = base
    suffix = 2
    while conn.execute("SELECT 1 FROM departments WHERE slug = ?", (candidate,)).fetchone():
        tail = f"-{suffix}"
        candidate = base[: 64 - len(tail)].rstrip("-") + tail
        suffix += 1
    return candidate
