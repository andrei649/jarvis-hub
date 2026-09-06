"""permission_ledger.py — one consent ledger for what Nerva may touch.

Per-app / per-site / OS-input / file-root / terminal-target grants with the
scopes ``once | session | always | never``, a built-in default-deny list
(banks, brokerages, crypto wallets, password managers, SSO identity providers,
adult sites; secret-bearing file roots), and a durable audit trail.

Governance (MOONSHOT §5 — capability growth only through approval):

* **Widening** what Nerva may touch is a privileged effect. ``request()`` never
  grants anything: it validates the ask against :data:`PERMISSION_GRANT_CONTRACT`
  and enqueues a durable ``permission.grant`` task through the *injected*
  ``govern_enqueue`` (the worker's governed intake) at ``RiskTier.EXTERNAL`` /
  ``ASK``, so the ask lands in the decision inbox (QUEUE). Ultron/the owner is the
  sole authority; the ledger cannot self-authorize.
* **Applying** a grant happens only from the approved task's execution
  (``apply_grant`` is the executor handler for kind ``permission.grant``). It
  refuses any task that was not decided by a human (``decided_by`` missing or a
  machine decider such as ``policy``), or whose decision is not accept/edit.
* **Narrowing** (``revoke``) needs no approval. ``never`` rows — the default-deny
  list and owner-set denials — are immutable: they can neither be requested nor
  revoked.
* ``session`` grants die with the process: a new ledger instance expires every
  session grant recorded under a previous boot id.
* ``once`` grants are consumed by exactly one ``check()`` that answers ``allow``.
* ``os_input`` grants mint a *restore token* kept in the SecretStore (never in the
  SQLite row), so an input driver can re-arm consent after a restart only with the
  token the owner's approval minted.

Runtime flag: ``JARVIS_PERMISSION_LEDGER`` (default off). Off → ``check()`` answers
``allow`` for legacy callers and records nothing; on → first contact answers
``ask`` until a grant exists.

Persistence: SQLite WAL at ``data_path('permissions.db')`` (never CWD), one
``threading.Lock`` per store, a strict status transition table, schema versioned
through ``persistence.migrations``. Grant rows carry a canonical-JSON SHA-256
fingerprint so a tampered row is detectable on read.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets as _secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.core.automation_contracts import ContractTemplate, predicate
from agents.core.autonomy.policy import ASK, RiskTier
from agents.core.env_config import env_flag
from agents.core.paths import data_path
from agents.core.persistence.migrations import apply_migrations

logger = logging.getLogger("jarvis.permissions")

# ── vocabulary ───────────────────────────────────────────────────────────────

KIND = "permission.grant"
FLAG = "JARVIS_PERMISSION_LEDGER"

SURFACES = ("app", "site", "os_input", "file_root", "terminal_target")
SCOPES = ("once", "session", "always", "never")
REQUESTABLE_SCOPES = ("once", "session", "always")

GRANT_STATUSES = ("active", "consumed", "revoked", "expired", "never")
# Strict transition table: a row may only move along these edges.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "active": frozenset({"consumed", "revoked", "expired"}),
    "consumed": frozenset(),
    "revoked": frozenset(),
    "expired": frozenset(),
    "never": frozenset(),  # immutable by construction
}

# Deciders that are machines, never humans. A task carrying one of these in
# ``decided_by`` was auto-decided by policy and must not widen a grant.
MACHINE_DECIDERS = frozenset({"policy", "system", "kernel", "auto", "worker", "scheduler", ""})
HUMAN_DECISIONS = frozenset({"accept", "approve", "edit"})

_MAX_KEY = 512
_MAX_REQUESTER = 128
_MAX_REASON = 500
_DEFAULT_DB = "permissions.db"


# ── default deny ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DenyRule:
    """One built-in ``never`` entry. ``match`` is ``suffix`` (host / process
    basename equals the value or ends with ``.<value>``), ``token`` (the value
    appears as a whole dotted/dashed/underscored token of the key) or
    ``path_part`` (a path component equals the value)."""

    surface: str
    match: str
    value: str
    category: str

    def __post_init__(self) -> None:
        if self.surface not in SURFACES:
            raise ValueError(f"unknown surface: {self.surface}")
        if self.match not in ("suffix", "token", "path_part"):
            raise ValueError(f"unknown match mode: {self.match}")
        if not self.value or not self.category:
            raise ValueError("deny rule needs a value and a category")


def _site(value: str, category: str, match: str = "suffix") -> DenyRule:
    return DenyRule("site", match, value, category)


def _app(value: str, category: str) -> DenyRule:
    return DenyRule("app", "token", value, category)


def _root(value: str, category: str) -> DenyRule:
    return DenyRule("file_root", "path_part", value, category)


DEFAULT_DENY: tuple[DenyRule, ...] = (
    # banks / brokerages — generic tokens, then well-known hosts
    _site("bank", "bank", "token"),
    _site("banking", "bank", "token"),
    _site("brokerage", "brokerage", "token"),
    _site("chase.com", "bank"),
    _site("bankofamerica.com", "bank"),
    _site("wellsfargo.com", "bank"),
    _site("revolut.com", "bank"),
    _site("n26.com", "bank"),
    _site("wise.com", "bank"),
    _site("paypal.com", "bank"),
    _site("schwab.com", "brokerage"),
    _site("fidelity.com", "brokerage"),
    _site("etrade.com", "brokerage"),
    _site("robinhood.com", "brokerage"),
    _site("interactivebrokers.com", "brokerage"),
    _site("degiro.com", "brokerage"),
    _site("tradingview.com", "brokerage"),
    # crypto wallets / exchanges
    _site("coinbase.com", "crypto_wallet"),
    _site("binance.com", "crypto_wallet"),
    _site("kraken.com", "crypto_wallet"),
    _site("metamask.io", "crypto_wallet"),
    _site("ledger.com", "crypto_wallet"),
    _site("trezor.io", "crypto_wallet"),
    _site("wallet", "crypto_wallet", "token"),
    # password managers
    _site("1password.com", "password_manager"),
    _site("bitwarden.com", "password_manager"),
    _site("lastpass.com", "password_manager"),
    _site("dashlane.com", "password_manager"),
    _site("keepersecurity.com", "password_manager"),
    _site("nordpass.com", "password_manager"),
    # SSO / identity providers
    _site("okta.com", "sso_idp"),
    _site("login.microsoftonline.com", "sso_idp"),
    _site("accounts.google.com", "sso_idp"),
    _site("auth0.com", "sso_idp"),
    _site("onelogin.com", "sso_idp"),
    _site("id.apple.com", "sso_idp"),
    _site("appleid.apple.com", "sso_idp"),
    _site("sso", "sso_idp", "token"),
    # adult
    _site("porn", "adult", "token"),
    _site("xxx", "adult", "token"),
    _site("onlyfans.com", "adult"),
    _site("xvideos.com", "adult"),
    _site("xhamster.com", "adult"),
    # processes (password managers, wallets, authenticators)
    _app("1password", "password_manager"),
    _app("bitwarden", "password_manager"),
    _app("lastpass", "password_manager"),
    _app("keepassxc", "password_manager"),
    _app("keepass", "password_manager"),
    _app("dashlane", "password_manager"),
    _app("ledger live", "crypto_wallet"),
    _app("electrum", "crypto_wallet"),
    _app("exodus", "crypto_wallet"),
    _app("authy", "sso_idp"),
    _app("okta verify", "sso_idp"),
    # secret-bearing file roots
    _root(".ssh", "secrets"),
    _root(".gnupg", "secrets"),
    _root(".aws", "secrets"),
    _root(".azure", "secrets"),
    _root(".kube", "secrets"),
    _root(".password-store", "password_manager"),
    _root("Keychains", "secrets"),
)

_TOKEN_SPLIT = re.compile(r"[.\-_\s/\\:]+")


def normalize_key(surface: str, key: Any) -> str:
    """Canonical key for ``surface``: lowercase host (port/scheme/path stripped)
    for sites, lowercase basename without ``.exe/.app`` for apps, ``~``/slash
    normalised path for file roots, stripped lowercase text otherwise. Empty or
    over-long keys come back as ``""`` (the contract rejects them)."""
    text = str(key or "").strip()
    if not text or len(text) > _MAX_KEY:
        return ""
    if surface == "site":
        host = text.lower()
        if "://" in host:
            host = host.split("://", 1)[1]
        host = host.split("/", 1)[0].split("?", 1)[0]
        if "@" in host:
            host = host.rsplit("@", 1)[1]
        host = host.split(":", 1)[0].strip(".")
        return host
    if surface == "app":
        base = text.replace("\\", "/").rsplit("/", 1)[-1].lower()
        for ext in (".exe", ".app"):
            if base.endswith(ext):
                base = base[: -len(ext)]
        return base.strip()
    if surface == "file_root":
        return text.replace("\\", "/").rstrip("/") or "/"
    return text.lower()


def _rule_matches(rule: DenyRule, key: str) -> bool:
    if rule.match == "suffix":
        return key == rule.value or key.endswith("." + rule.value)
    if rule.match == "token":
        parts = [p for p in _TOKEN_SPLIT.split(key) if p]
        wanted = [p for p in _TOKEN_SPLIT.split(rule.value) if p]
        if not wanted:
            return False
        n = len(wanted)
        return any(parts[i : i + n] == wanted for i in range(len(parts) - n + 1))
    return rule.value in key.split("/")


def default_denied(surface: str, key: Any) -> DenyRule | None:
    """The first :data:`DEFAULT_DENY` rule matching ``(surface, key)``, or None."""
    norm = normalize_key(surface, key)
    if not norm:
        return None
    for rule in DEFAULT_DENY:
        if rule.surface == surface and _rule_matches(rule, norm):
            return rule
    return None


# ── contract ─────────────────────────────────────────────────────────────────

def _permission_grant_contract() -> ContractTemplate:
    return ContractTemplate(
        kind="permission_grant",
        description=(
            "Widening what Nerva may touch is held for owner approval; never entries "
            "and the default-deny list cannot be requested."
        ),
        constraints=(
            predicate(
                "permission-kind",
                lambda view, _now: str(view.get("kind") or KIND).startswith("permission."),
                reason="invalid_kind",
            ),
            predicate(
                "surface-known",
                lambda view, _now: view.get("surface") in SURFACES,
                reason="invalid_surface",
            ),
            predicate(
                "key-present",
                lambda view, _now: bool(normalize_key(str(view.get("surface")), view.get("key"))),
                reason="invalid_key",
            ),
            predicate(
                "scope-requestable",
                lambda view, _now: view.get("scope") in REQUESTABLE_SCOPES,
                reason="scope_not_requestable",
            ),
            predicate(
                "requested-by",
                lambda view, _now: isinstance(view.get("requested_by"), str)
                and 0 < len(view["requested_by"].strip()) <= _MAX_REQUESTER,
                reason="requested_by_required",
            ),
            predicate(
                "not-default-denied",
                lambda view, _now: default_denied(str(view.get("surface")), view.get("key")) is None,
                reason="default_denied",
            ),
        ),
        requires_approval=True,
    )


PERMISSION_GRANT_CONTRACT = _permission_grant_contract()


class PermissionRequestError(ValueError):
    """A grant request the contract (or the ledger's never rows) refuses."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# ── records ──────────────────────────────────────────────────────────────────

def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Grant:
    """One ledger row. Frozen; ``fingerprint`` covers the identity fields."""

    id: str
    surface: str
    key: str
    scope: str
    status: str
    requested_by: str
    granted_by: str
    task_id: int | None
    boot_id: str
    created_at: float
    updated_at: float
    reason: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.surface not in SURFACES:
            raise ValueError(f"unknown surface: {self.surface}")
        if self.scope not in SCOPES:
            raise ValueError(f"unknown scope: {self.scope}")
        if self.status not in GRANT_STATUSES:
            raise ValueError(f"unknown status: {self.status}")
        if (self.scope == "never") != (self.status == "never"):
            raise ValueError("never scope and never status go together")
        if not self.key:
            raise ValueError("grant key is required")
        expected = _fingerprint(self.identity())
        if self.fingerprint and self.fingerprint != expected:
            raise ValueError("grant fingerprint mismatch")
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", expected)

    def identity(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "surface": self.surface,
            "key": self.key,
            "scope": self.scope,
            "requested_by": self.requested_by,
            "granted_by": self.granted_by,
            "task_id": self.task_id,
            "boot_id": self.boot_id,
            "created_at": self.created_at,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.identity(),
            "status": self.status,
            "updated_at": self.updated_at,
            "reason": self.reason,
            "fingerprint": self.fingerprint,
            "immutable": self.scope == "never",
        }


def _v1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS grants (
            id           TEXT PRIMARY KEY,
            surface      TEXT NOT NULL,
            key          TEXT NOT NULL,
            scope        TEXT NOT NULL,
            status       TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            granted_by   TEXT NOT NULL,
            task_id      INTEGER,
            boot_id      TEXT NOT NULL,
            created_at   REAL NOT NULL,
            updated_at   REAL NOT NULL,
            reason       TEXT NOT NULL DEFAULT '',
            fingerprint  TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS grants_lookup ON grants (surface, key, status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit (
            seq       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        REAL NOT NULL,
            event     TEXT NOT NULL,
            grant_id  TEXT,
            surface   TEXT,
            key       TEXT,
            scope     TEXT,
            actor     TEXT,
            task_id   INTEGER,
            detail    TEXT NOT NULL DEFAULT ''
        )
        """
    )


MIGRATIONS = [_v1]


# ── the ledger ───────────────────────────────────────────────────────────────

def _kernel_on() -> bool:
    """Default-off, like ``FileTools._authorize`` and ``ToolRPCServer``: the hook is
    bound at boot but consulted only once ``JARVIS_ACTION_KERNEL`` is on."""
    from agents.core.kernel import kernel_enabled

    return kernel_enabled()


class PermissionLedger:
    """The durable consent ledger. See the module docstring for the rules.

    ``authorizer`` is an optional kernel hook ``authorize(Action) -> Decision``
    (``kernel.binding.make_action_kernel``); a DENY refuses the request before it
    reaches the inbox. ``secret_store`` receives os_input restore tokens; it is
    built lazily from :class:`agents.core.secrets.SecretStore` when absent.
    ``enabled`` overrides the env flag (tests); ``None`` reads the flag per call.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        authorizer: Callable[..., Any] | None = None,
        secret_store: Any | None = None,
        enabled: bool | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path) if path is not None else data_path(_DEFAULT_DB)
        self._authorizer = authorizer
        self._secret_store = secret_store
        self._enabled_override = enabled
        self._clock = clock
        self._lock = threading.Lock()
        self.boot_id = uuid.uuid4().hex
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        apply_migrations(self._conn, MIGRATIONS, name="permissions")
        self._expire_previous_sessions()

    # ── plumbing ──────────────────────────────────────────────────────────

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        return env_flag(FLAG, False)

    def _now(self) -> float:
        return float(self._clock())

    def _secrets(self):
        if self._secret_store is None:
            from agents.core.secrets import SecretStore

            self._secret_store = SecretStore()
        return self._secret_store

    @staticmethod
    def _secret_name(grant_id: str) -> str:
        return f"permission.os_input.{grant_id}"

    def _row_to_grant(self, row: sqlite3.Row) -> Grant:
        return Grant(
            id=row["id"],
            surface=row["surface"],
            key=row["key"],
            scope=row["scope"],
            status=row["status"],
            requested_by=row["requested_by"],
            granted_by=row["granted_by"],
            task_id=row["task_id"],
            boot_id=row["boot_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            reason=row["reason"],
            fingerprint=row["fingerprint"],
        )

    def _audit(
        self,
        event: str,
        *,
        grant_id: str | None = None,
        surface: str | None = None,
        key: str | None = None,
        scope: str | None = None,
        actor: str | None = None,
        task_id: int | None = None,
        detail: str = "",
    ) -> None:
        """Append one audit row. Caller holds ``self._lock``."""
        self._conn.execute(
            "INSERT INTO audit (ts, event, grant_id, surface, key, scope, actor, task_id, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self._now(), event, grant_id, surface, key, scope, actor, task_id, detail[:_MAX_REASON]),
        )

    def _transition(self, grant: Grant, new_status: str, *, actor: str, detail: str = "") -> Grant:
        """Move ``grant`` along the strict table. Caller holds ``self._lock``."""
        if new_status not in _TRANSITIONS.get(grant.status, frozenset()):
            raise PermissionRequestError("invalid_transition")
        now = self._now()
        self._conn.execute(
            "UPDATE grants SET status=?, updated_at=? WHERE id=? AND status=?",
            (new_status, now, grant.id, grant.status),
        )
        self._audit(
            f"grant.{new_status}",
            grant_id=grant.id,
            surface=grant.surface,
            key=grant.key,
            scope=grant.scope,
            actor=actor,
            task_id=grant.task_id,
            detail=detail,
        )
        return Grant(**{**grant.__dict__, "status": new_status, "updated_at": now})

    def _expire_previous_sessions(self) -> int:
        """Session grants belong to the boot that approved them."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM grants WHERE scope='session' AND status='active' AND boot_id<>?",
                (self.boot_id,),
            ).fetchall()
            for row in rows:
                self._transition(self._row_to_grant(row), "expired", actor="boot", detail="new boot")
            self._conn.commit()
        return len(rows)

    def _never_row(self, surface: str, key: str) -> Grant | None:
        row = self._conn.execute(
            "SELECT * FROM grants WHERE surface=? AND key=? AND status='never' LIMIT 1",
            (surface, key),
        ).fetchone()
        return self._row_to_grant(row) if row is not None else None

    # ── reads ─────────────────────────────────────────────────────────────

    def check(self, surface: str, key: Any, now: float | None = None) -> str:
        """``allow`` | ``ask`` | ``deny`` for touching ``key`` on ``surface``.

        Flag off → ``allow`` and nothing recorded (legacy callers). Flag on →
        default-deny and ``never`` rows deny; an ``always`` grant, a ``session``
        grant of this boot, or an unconsumed ``once`` grant (consumed here,
        exactly once) allow; otherwise ``ask``.
        """
        if not self.enabled:
            return "allow"
        if surface not in SURFACES:
            return "deny"
        norm = normalize_key(surface, key)
        if not norm:
            return "deny"
        if default_denied(surface, norm) is not None:
            return "deny"
        with self._lock:
            if self._never_row(surface, norm) is not None:
                return "deny"
            rows = self._conn.execute(
                "SELECT * FROM grants WHERE surface=? AND key=? AND status='active'"
                " ORDER BY created_at ASC",
                (surface, norm),
            ).fetchall()
            grants = [self._row_to_grant(r) for r in rows]
            for grant in grants:
                if grant.scope == "always":
                    return "allow"
                if grant.scope == "session" and grant.boot_id == self.boot_id:
                    return "allow"
            for grant in grants:
                if grant.scope == "once":
                    self._transition(grant, "consumed", actor="check", detail="once consumed")
                    self._conn.commit()
                    return "allow"
        return "ask"

    def get(self, grant_id: str) -> Grant | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM grants WHERE id=?", (str(grant_id),)).fetchone()
        return self._row_to_grant(row) if row is not None else None

    def list_grants(self, *, include_inactive: bool = False, limit: int = 200) -> list[Grant]:
        q = "SELECT * FROM grants"
        if not include_inactive:
            q += " WHERE status IN ('active', 'never')"
        q += " ORDER BY created_at DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, (int(limit),)).fetchall()
        return [self._row_to_grant(r) for r in rows]

    def audit_rows(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

    def restore_token(self, grant_id: str) -> str | None:
        """The os_input restore token minted by the owner's approval, or None."""
        grant = self.get(grant_id)
        if grant is None or grant.surface != "os_input" or grant.status != "active":
            return None
        try:
            return self._secrets().get(self._secret_name(grant.id))
        except Exception:
            # The message names the token; the only value interpolated is the grant
            # id. The secret itself never leaves the SecretStore.
            # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
            logger.warning("permission restore token unreadable for %s", grant_id)
            return None

    def snapshot(self, *, limit: int = 200) -> dict[str, Any]:
        grants = self.list_grants(include_inactive=True, limit=limit)
        return {
            "enabled": self.enabled,
            "flag": FLAG,
            "boot_id": self.boot_id,
            "surfaces": list(SURFACES),
            "scopes": list(SCOPES),
            "grants": [g.as_dict() for g in grants],
            "active": sum(1 for g in grants if g.status == "active"),
            "default_deny": [
                {"surface": r.surface, "match": r.match, "value": r.value, "category": r.category}
                for r in DEFAULT_DENY
            ],
            "audit": self.audit_rows(limit=50),
        }

    # ── widening: request → approval queue ────────────────────────────────

    def request(
        self,
        surface: str,
        key: Any,
        scope: str,
        requested_by: str,
        govern_enqueue: Callable[..., int],
        *,
        agent: str = "jarvis",
        reason: str = "",
        title: str | None = None,
    ) -> int:
        """Ask the owner to widen a grant. Returns the durable task id.

        Runs the contract, the ledger's ``never`` rows and (when bound) the kernel,
        then hands the ask to ``govern_enqueue`` at EXTERNAL/ASK so it lands in the
        decision inbox. The task is never transitioned here.
        """
        norm = normalize_key(surface, key)
        payload = {
            "kind": KIND,
            "surface": surface,
            "key": norm,
            "scope": scope,
            "requested_by": str(requested_by or "").strip(),
            "reason": str(reason or "")[:_MAX_REASON],
            "risk_tier": int(RiskTier.EXTERNAL),
            "reversible": True,
        }
        decision = PERMISSION_GRANT_CONTRACT.evaluate(payload, now=self._now())
        if not decision.admissible:
            raise PermissionRequestError(decision.reason or "contract_denied")
        with self._lock:
            if self._never_row(surface, norm) is not None:
                raise PermissionRequestError("never_entry")
        if self._authorizer is not None and _kernel_on():
            from agents.core.kernel import Action, Verdict

            verdict = self._authorizer(
                Action(kind=KIND, agent=agent, title=title or f"grant {surface}:{norm}", payload=payload)
            )
            if getattr(verdict, "verdict", None) is Verdict.DENY:
                raise PermissionRequestError(f"kernel_denied:{getattr(verdict, 'reason', '') or 'denied'}")
        task_id = govern_enqueue(
            agent=agent,
            kind=KIND,
            title=title or f"Allow {scope} access to {surface} {norm}",
            payload=payload,
            risk_tier=int(RiskTier.EXTERNAL),
            autonomy_level=ASK,
            origin="generated",
        )
        with self._lock:
            self._audit(
                "grant.requested",
                surface=surface,
                key=norm,
                scope=scope,
                actor=payload["requested_by"],
                task_id=int(task_id) if isinstance(task_id, int) else None,
                detail=payload["reason"],
            )
            self._conn.commit()
        return task_id

    # ── widening: apply from the approved task ────────────────────────────

    async def apply_grant(self, task: Any) -> dict[str, Any]:
        """Executor handler for ``permission.grant``: record the grant the owner
        approved. Refuses unless a human decided accept/edit on this very task."""
        kind = str(getattr(task, "kind", "") or "")
        if kind != KIND:
            return {"status": "refused", "reason": "kind_mismatch"}
        decided_by = str(getattr(task, "decided_by", "") or "").strip().lower()
        decision_word = str(getattr(task, "decision", "") or "").strip().lower()
        if decided_by in MACHINE_DECIDERS:
            return {"status": "refused", "reason": "human_decision_required"}
        if decision_word not in HUMAN_DECISIONS:
            return {"status": "refused", "reason": "decision_not_approval"}
        payload = getattr(task, "payload", None)
        if not isinstance(payload, Mapping):
            return {"status": "refused", "reason": "payload_required"}
        surface = payload.get("surface")
        norm = normalize_key(str(surface), payload.get("key"))
        view = {**payload, "kind": KIND, "key": norm}
        decision = PERMISSION_GRANT_CONTRACT.evaluate(view, now=self._now())
        if not decision.admissible:
            return {"status": "refused", "reason": decision.reason or "contract_denied"}
        scope = str(payload["scope"])
        task_id = getattr(task, "id", None)
        task_id = int(task_id) if isinstance(task_id, int) and not isinstance(task_id, bool) else None
        now = self._now()
        grant = Grant(
            id=uuid.uuid4().hex,
            surface=str(surface),
            key=norm,
            scope=scope,
            status="active",
            requested_by=str(payload["requested_by"]).strip(),
            granted_by=decided_by,
            task_id=task_id,
            boot_id=self.boot_id,
            created_at=now,
            updated_at=now,
            reason=str(payload.get("reason") or "")[:_MAX_REASON],
        )
        with self._lock:
            if self._never_row(grant.surface, grant.key) is not None:
                return {"status": "refused", "reason": "never_entry"}
            self._insert(grant)
            self._audit(
                "grant.applied",
                grant_id=grant.id,
                surface=grant.surface,
                key=grant.key,
                scope=grant.scope,
                actor=decided_by,
                task_id=task_id,
                detail=f"decision={decision_word}",
            )
            self._conn.commit()
        out: dict[str, Any] = {
            "status": "ok",
            "grant_id": grant.id,
            "surface": grant.surface,
            "key": grant.key,
            "scope": grant.scope,
        }
        if grant.surface == "os_input":
            token = _secrets.token_urlsafe(24)
            try:
                self._secrets().set(self._secret_name(grant.id), token)
                out["restore_token_stored"] = True
            except Exception:
                # `token` is in scope here and is deliberately NOT logged: only the
                # grant id is interpolated, so a failed store cannot leak the secret.
                # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
                logger.warning("os_input restore token could not be stored for %s", grant.id)
                out["restore_token_stored"] = False
        return out

    def _insert(self, grant: Grant) -> None:
        self._conn.execute(
            "INSERT INTO grants (id, surface, key, scope, status, requested_by, granted_by,"
            " task_id, boot_id, created_at, updated_at, reason, fingerprint)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                grant.id, grant.surface, grant.key, grant.scope, grant.status,
                grant.requested_by, grant.granted_by, grant.task_id, grant.boot_id,
                grant.created_at, grant.updated_at, grant.reason, grant.fingerprint,
            ),
        )

    # ── narrowing: no approval needed ─────────────────────────────────────

    def revoke(self, grant_id: str, *, by: str = "owner", reason: str = "") -> Grant:
        """Narrow: active → revoked. ``never`` rows are immutable."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM grants WHERE id=?", (str(grant_id),)).fetchone()
            if row is None:
                raise KeyError(grant_id)
            grant = self._row_to_grant(row)
            if grant.scope == "never":
                raise PermissionRequestError("never_is_immutable")
            updated = self._transition(grant, "revoked", actor=str(by), detail=reason)
            self._conn.commit()
        if grant.surface == "os_input":
            try:
                self._secrets().delete(self._secret_name(grant.id))
            except Exception:
                # Grant id only; the secret is addressed by name, never rendered.
                # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
                logger.warning("os_input restore token could not be deleted for %s", grant.id)
        return updated

    def deny(self, surface: str, key: Any, *, by: str = "owner", reason: str = "") -> Grant:
        """Narrow: add an owner ``never`` row (immutable; revokes any active grant
        for the same key). Idempotent for an existing never row."""
        if surface not in SURFACES:
            raise PermissionRequestError("invalid_surface")
        norm = normalize_key(surface, key)
        if not norm:
            raise PermissionRequestError("invalid_key")
        now = self._now()
        with self._lock:
            existing = self._never_row(surface, norm)
            if existing is not None:
                return existing
            rows = self._conn.execute(
                "SELECT * FROM grants WHERE surface=? AND key=? AND status='active'", (surface, norm)
            ).fetchall()
            for row in rows:
                self._transition(self._row_to_grant(row), "revoked", actor=str(by), detail="superseded by never")
            grant = Grant(
                id=uuid.uuid4().hex,
                surface=surface,
                key=norm,
                scope="never",
                status="never",
                requested_by=str(by),
                granted_by=str(by),
                task_id=None,
                boot_id=self.boot_id,
                created_at=now,
                updated_at=now,
                reason=str(reason or "")[:_MAX_REASON],
            )
            self._insert(grant)
            self._audit(
                "grant.never", grant_id=grant.id, surface=surface, key=norm, scope="never",
                actor=str(by), detail=reason,
            )
            self._conn.commit()
        return grant


__all__ = [
    "DEFAULT_DENY",
    "DenyRule",
    "FLAG",
    "Grant",
    "HUMAN_DECISIONS",
    "KIND",
    "MACHINE_DECIDERS",
    "MIGRATIONS",
    "PERMISSION_GRANT_CONTRACT",
    "PermissionLedger",
    "PermissionRequestError",
    "REQUESTABLE_SCOPES",
    "SCOPES",
    "SURFACES",
    "default_denied",
    "normalize_key",
]
