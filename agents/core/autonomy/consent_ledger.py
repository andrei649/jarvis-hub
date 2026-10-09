"""Signed, caller-owned evidence for reusable H487 owner consent.

This is a storage primitive, not execution authority or caller authentication.
Only an owner-authenticated integration may pass the "owner" or "admin" label.
The category catalog must come from reviewed server registrations. HMACs do
not detect rollback of the entire database without an external anchor.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from .mediation import DetachedHMACSigner, MediationHead, MonotonicHeadAnchor

_VERSION = 1
_ATTRIBUTED_VERSION = 2
_NAMESPACE = "h487.reusable_consent"
_GRANT_PURPOSE = "owner-category-grant"
_DECISION_PURPOSE = "owner-consent-decision"
_HEAD_PURPOSE = "h487-consent-head"
_HUMAN_ORIGINS = frozenset({"owner", "admin"})
_KEY = re.compile(r"[A-Za-z0-9_.:/-]{1,128}\Z")
_DECISION_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


@dataclass(frozen=True, slots=True)
class ConsentContext:
    principal: str
    surface: str
    session_id: str
    session_instance: str
    registration_key: str
    policy_revision: str
    target_scope: str


@dataclass(frozen=True, slots=True)
class ConsentCategory:
    key: str
    permanent: bool = True


def _valid_text(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 1024:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _valid_context(value: object) -> bool:
    return type(value) is ConsentContext and all(_valid_text(part) for part in asdict(value).values())


def _valid_category(value: object) -> bool:
    return (
        type(value) is ConsentCategory
        and isinstance(value.key, str)
        and _KEY.fullmatch(value.key) is not None
        and type(value.permanent) is bool
    )


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _identity(context: ConsentContext, scope: str) -> dict[str, str]:
    fields = asdict(context)
    if scope == "always":
        fields.pop("session_id")
        fields.pop("session_instance")
    return fields


def _identity_key(identity: dict[str, str]) -> str:
    return hashlib.sha256(_canonical(identity)).hexdigest()


def _record_version(record: object, purpose: str) -> int | None:
    """Recognize only the two reviewed signed payload shapes."""
    if (type(record) is not dict or record.get("purpose") != purpose
            or record.get("namespace") != _NAMESPACE):
        return None
    version = record.get("version")
    if type(version) is not int or version not in {_VERSION, _ATTRIBUTED_VERSION}:
        return None
    fields = ({"purpose", "namespace", "version", "context", "categories", "choice",
               "decision_id", "decided_by", "state"} if purpose == _DECISION_PURPOSE else
              {"purpose", "namespace", "version", "identity", "category", "scope",
               "choice", "decision_id", "decided_by"})
    if version == _ATTRIBUTED_VERSION:
        fields.add("decider_principal")
        from .consent_authority import valid_telegram_principal
        if (record.get("decided_by") != "owner"
                or not valid_telegram_principal(record.get("decider_principal"))):
            return None
    return version if set(record) == fields else None


class ConsentLedger:
    """Persist signed grants without committing or closing the caller's DB."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        signer: DetachedHMACSigner | None,
        *,
        categories: Iterable[ConsentCategory] = (),
        head_anchor: MonotonicHeadAnchor | None = None,
    ) -> None:
        self._conn = conn
        self._signer = signer
        self._head_anchor = head_anchor
        catalog: dict[str, ConsentCategory] = {}
        try:
            for category in categories:
                if not _valid_category(category) or category.key in catalog:
                    catalog = {}
                    break
                catalog[category.key] = category
        except (TypeError, ValueError):
            catalog = {}
        self._catalog = catalog

    def initialize(self) -> None:
        """Create only private H487 tables, retaining any enclosing transaction."""
        self._conn.execute("SAVEPOINT h487_consent_initialize")
        try:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS h487_consent_decisions (
                    decision_id TEXT PRIMARY KEY, payload BLOB NOT NULL,
                    signature TEXT NOT NULL)"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS h487_consent_grants (
                    identity_key TEXT NOT NULL, scope TEXT NOT NULL,
                    category_key TEXT NOT NULL, decision_id TEXT NOT NULL,
                    payload BLOB NOT NULL, signature TEXT NOT NULL,
                    PRIMARY KEY (identity_key, scope, category_key))"""
            )
            if self._head_anchor is not None:
                self._conn.execute(
                    """CREATE TABLE IF NOT EXISTS h487_consent_state (
                        id INTEGER PRIMARY KEY CHECK (id=1),
                        version INTEGER NOT NULL, revision INTEGER NOT NULL,
                        manifest_digest TEXT NOT NULL, signature TEXT NOT NULL)"""
                )
                state = self._conn.execute("SELECT 1 FROM h487_consent_state LIMIT 1").fetchone()
                if state is None:
                    decisions = self._conn.execute("SELECT 1 FROM h487_consent_decisions LIMIT 1").fetchone()
                    grants = self._conn.execute("SELECT 1 FROM h487_consent_grants LIMIT 1").fetchone()
                    if decisions is None and grants is None and self._head_anchor.read() is None:
                        head = self._make_head_locked(0)
                        if head is not None and self._head_anchor.advance(None, head):
                            self._conn.execute(
                                "INSERT INTO h487_consent_state VALUES (1, 1, ?, ?, ?)",
                                (head.last_sequence, head.last_event_hash, head.signature),
                            )
        except sqlite3.Error:
            self._conn.execute("ROLLBACK TO SAVEPOINT h487_consent_initialize")
            self._conn.execute("RELEASE SAVEPOINT h487_consent_initialize")
            raise
        self._conn.execute("RELEASE SAVEPOINT h487_consent_initialize")

    def _manifest_digest_locked(self) -> str:
        """Bind every stored row column, including primary keys and signed bytes."""
        digest = hashlib.sha256(_canonical({
            "purpose": "h487-consent-manifest", "namespace": _NAMESPACE, "version": _VERSION,
        }))
        for table, query in (
            (b"decisions", "SELECT decision_id, payload, signature FROM h487_consent_decisions ORDER BY decision_id"),
            (b"grants", """SELECT identity_key, scope, category_key, decision_id, payload, signature
                          FROM h487_consent_grants ORDER BY identity_key, scope, category_key"""),
        ):
            digest.update(len(table).to_bytes(8, "big"))
            digest.update(table)
            for row in self._conn.execute(query):
                if table == b"decisions":
                    valid = isinstance(row[0], str) and isinstance(row[1], bytes) and isinstance(row[2], str)
                    encoded = [row[0], row[1].hex(), row[2]] if valid else None
                else:
                    valid = (
                        all(isinstance(value, str) for value in row[:4])
                        and isinstance(row[4], bytes) and isinstance(row[5], str)
                    )
                    encoded = [*row[:4], row[4].hex(), row[5]] if valid else None
                if encoded is None:
                    raise ValueError("invalid consent row type")
                item = _canonical({"row": encoded})
                digest.update(len(item).to_bytes(8, "big"))
                digest.update(item)
        return digest.hexdigest()

    def _head_payload(self, revision: int, digest: str) -> bytes:
        return _canonical({
            "purpose": _HEAD_PURPOSE, "namespace": _NAMESPACE, "version": _VERSION,
            "revision": revision, "manifest_digest": digest,
        })

    def _make_head_locked(self, revision: int) -> MediationHead | None:
        if not isinstance(self._signer, DetachedHMACSigner):
            return None
        digest = self._manifest_digest_locked()
        signature = self._signer.sign(self._head_payload(revision, digest))
        if signature is None:
            return None
        return MediationHead(1, revision, digest, revision, signature)

    def _verified_head_locked(self) -> MediationHead | None:
        if self._head_anchor is None or not isinstance(self._signer, DetachedHMACSigner):
            return None
        row = self._conn.execute(
            "SELECT version, revision, manifest_digest, signature FROM h487_consent_state WHERE id=1"
        ).fetchone()
        if row is None or row[0] != 1 or type(row[1]) is not int or row[1] < 0:
            return None
        digest = self._manifest_digest_locked()
        if row[2] != digest or not self._signer.verify(self._head_payload(row[1], digest), row[3]):
            return None
        try:
            local = MediationHead(1, row[1], digest, row[1], row[3])
        except ValueError:
            return None
        return local if self._head_anchor.read() == local else None

    def _advance_head_locked(self, previous: MediationHead) -> None:
        if self._head_anchor is None:
            return
        replacement = self._make_head_locked(previous.last_sequence + 1)
        if replacement is None:
            raise ValueError("unavailable consent head signer")
        updated = self._conn.execute(
            """UPDATE h487_consent_state SET revision=?, manifest_digest=?, signature=?
               WHERE id=1 AND version=1 AND revision=? AND manifest_digest=? AND signature=?""",
            (replacement.last_sequence, replacement.last_event_hash, replacement.signature,
             previous.last_sequence, previous.last_event_hash, previous.signature),
        )
        if updated.rowcount != 1 or not self._head_anchor.advance(previous, replacement):
            raise ValueError("unavailable consent head anchor")

    def _requested(self, categories: Iterable[ConsentCategory]) -> tuple[ConsentCategory, ...] | None:
        selected: dict[str, ConsentCategory] = {}
        try:
            for category in categories:
                if not _valid_category(category) or self._catalog.get(category.key) != category:
                    return None
                selected[category.key] = category
        except (TypeError, ValueError):
            return None
        return tuple(selected[key] for key in sorted(selected)) or None

    def grant(
        self,
        context: ConsentContext,
        categories: Iterable[ConsentCategory],
        *,
        choice: str,
        decision_id: str,
        decided_by: str,
        decider_principal: str | None = None,
    ) -> bool:
        """Record one owner decision atomically; this never authorizes execution."""
        selected = self._requested(categories)
        if (
            not _valid_context(context)
            or selected is None
            or not isinstance(choice, str)
            or choice not in {"session", "always"}
            or not isinstance(decision_id, str)
            or _DECISION_ID.fullmatch(decision_id) is None
            or not isinstance(decided_by, str)
            or decided_by not in _HUMAN_ORIGINS
            or (decider_principal is not None and (
                decided_by != "owner" or not _valid_text(decider_principal)))
            or not isinstance(self._signer, DetachedHMACSigner)
        ):
            return False
        if decider_principal is not None:
            from .consent_authority import valid_telegram_principal
            if not valid_telegram_principal(decider_principal):
                return False
        record_version = _ATTRIBUTED_VERSION if decider_principal is not None else _VERSION
        decision = {
            "purpose": _DECISION_PURPOSE, "namespace": _NAMESPACE, "version": record_version,
            "context": asdict(context), "categories": [asdict(item) for item in selected],
            "choice": choice, "decision_id": decision_id, "decided_by": decided_by,
            "state": "active",
        }
        if decider_principal is not None:
            decision["decider_principal"] = decider_principal
        decision_payload = _canonical(decision)
        decision_tag = self._signer.sign(decision_payload)
        if decision_tag is None:
            return False
        rows: list[tuple[str, str, str, str, bytes, str]] = []
        for category in selected:
            scope = choice if category.permanent else "session"
            identity = _identity(context, scope)
            payload = _canonical({
                "purpose": _GRANT_PURPOSE, "namespace": _NAMESPACE, "version": record_version,
                "identity": identity, "category": asdict(category), "scope": scope,
                "choice": choice, "decision_id": decision_id, "decided_by": decided_by,
                **({"decider_principal": decider_principal}
                   if decider_principal is not None else {}),
            })
            tag = self._signer.sign(payload)
            if tag is None:
                return False
            rows.append((_identity_key(identity), scope, category.key, decision_id, payload, tag))
        try:
            self._conn.execute("SAVEPOINT h487_consent_grant")
            try:
                previous = self._verified_head_locked() if self._head_anchor is not None else None
                if self._head_anchor is not None and previous is None:
                    raise ValueError("unverified consent head")
                # Consumed IDs remain after revocation, preventing ordinary replay.
                self._conn.execute(
                    "INSERT INTO h487_consent_decisions VALUES (?, ?, ?)",
                    (decision_id, decision_payload, decision_tag),
                )
                self._conn.executemany(
                    """INSERT INTO h487_consent_grants VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(identity_key, scope, category_key) DO UPDATE SET
                    decision_id=excluded.decision_id, payload=excluded.payload,
                    signature=excluded.signature""",
                    rows,
                )
                if previous is not None:
                    self._advance_head_locked(previous)
            except (sqlite3.Error, ValueError):
                self._conn.execute("ROLLBACK TO SAVEPOINT h487_consent_grant")
                self._conn.execute("RELEASE SAVEPOINT h487_consent_grant")
                return False
            self._conn.execute("RELEASE SAVEPOINT h487_consent_grant")
            return True
        except sqlite3.Error:
            return False

    def lookup(self, context: ConsentContext, categories: Iterable[ConsentCategory]) -> bool:
        """Every requested category needs current and correctly signed evidence."""
        selected = self._requested(categories)
        if not _valid_context(context) or selected is None or not isinstance(self._signer, DetachedHMACSigner):
            return False
        try:
            self._conn.execute("SAVEPOINT h487_consent_lookup")
        except sqlite3.Error:
            return False
        try:
            if self._head_anchor is not None and self._verified_head_locked() is None:
                return False
            for category in selected:
                session_key = _identity_key(_identity(context, "session"))
                always_key = _identity_key(_identity(context, "always"))
                rows = self._conn.execute(
                    """SELECT identity_key, scope, category_key, decision_id, payload, signature
                    FROM h487_consent_grants WHERE category_key=? AND
                    ((identity_key=? AND scope='session') OR (identity_key=? AND scope='always'))""",
                    (category.key, session_key, always_key),
                ).fetchall()
                if not rows:
                    return False
                for identity_key, scope, category_key, decision_id, payload, signature in rows:
                    if scope == "always" and not category.permanent:
                        return False
                    identity = _identity(context, scope)
                    if identity_key != _identity_key(identity) or category_key != category.key:
                        return False
                    if not isinstance(payload, bytes) or not self._signer.verify(payload, signature):
                        return False
                    record = json.loads(payload)
                    if (
                        type(record) is not dict
                        or _canonical(record) != payload
                        or record.get("purpose") != _GRANT_PURPOSE
                        or record.get("namespace") != _NAMESPACE
                        or _record_version(record, _GRANT_PURPOSE) is None
                        or record.get("identity") != identity
                        or record.get("category") != asdict(category)
                        or record.get("scope") != scope
                        or record.get("choice") not in {"session", "always"}
                        or record.get("decision_id") != decision_id
                        or record.get("decided_by") not in _HUMAN_ORIGINS
                        or (scope == "always" and record.get("choice") != "always")
                    ):
                        return False
                    decision_row = self._conn.execute(
                        "SELECT payload, signature FROM h487_consent_decisions WHERE decision_id=?",
                        (decision_id,),
                    ).fetchone()
                    if decision_row is None or not isinstance(decision_row[0], bytes):
                        return False
                    decision_payload, decision_tag = decision_row
                    if not self._signer.verify(decision_payload, decision_tag):
                        return False
                    decision = json.loads(decision_payload)
                    if (
                        type(decision) is not dict
                        or _canonical(decision) != decision_payload
                        or decision.get("purpose") != _DECISION_PURPOSE
                        or decision.get("namespace") != _NAMESPACE
                        or _record_version(decision, _DECISION_PURPOSE) is None
                        or decision["version"] != record["version"]
                        or (decision.get("decider_principal")
                            != record.get("decider_principal"))
                        or decision.get("decision_id") != decision_id
                        or decision.get("state") != "active"
                        or decision.get("choice") != record["choice"]
                        or decision.get("decided_by") != record["decided_by"]
                        or asdict(category) not in decision.get("categories", [])
                        or _identity(ConsentContext(**decision["context"]), scope) != identity
                    ):
                        return False
            return self._head_anchor is None or self._verified_head_locked() is not None
        except (sqlite3.Error, ValueError, TypeError, KeyError, UnicodeError):
            return False
        finally:
            try:
                self._conn.execute("RELEASE SAVEPOINT h487_consent_lookup")
            except sqlite3.Error:
                return False

    def current_witness(self, context: ConsentContext,
                        categories: Iterable[ConsentCategory], *,
                        decision_id: str | None = None) -> dict[str, dict[str, str]] | None:
        """Return exact active decision IDs and scopes from the anchored ledger.

        Callers must retain this witness on each task and compare it with a fresh
        lookup at claim and dispatch. An unrelated head advance is harmless;
        replacing a revoked category grant changes its decision ID.
        """
        selected = self._requested(categories)
        if self._head_anchor is None or selected is None or not self.lookup(context, selected):
            return None
        try:
            witness: dict[str, dict[str, str]] = {}
            for category in selected:
                for scope in ("session", "always"):
                    identity = _identity(context, scope)
                    row = self._conn.execute(
                        """SELECT decision_id FROM h487_consent_grants
                           WHERE identity_key=? AND scope=? AND category_key=?""",
                        (_identity_key(identity), scope, category.key),
                    ).fetchone()
                    if row is not None and (decision_id is None or row[0] == decision_id):
                        witness[category.key] = {"scope": scope, "decision_id": row[0]}
                        break
                if category.key not in witness:
                    return None
            return witness if self._verified_head_locked() is not None else None
        except (sqlite3.Error, ValueError, TypeError):
            return None

    def witness_current(self, context: ConsentContext,
                        categories: Iterable[ConsentCategory], witness: object) -> bool:
        """Verify precisely the recorded category/scope/decision IDs remain active."""
        selected = self._requested(categories)
        if (self._head_anchor is None or selected is None or type(witness) is not dict
                or set(witness) != {item.key for item in selected}
                or not self.lookup(context, selected)):
            return False
        try:
            for category in selected:
                entry = witness[category.key]
                if (type(entry) is not dict or set(entry) != {"scope", "decision_id"}
                        or entry["scope"] not in {"session", "always"}
                        or (entry["scope"] == "always" and not category.permanent)
                        or type(entry["decision_id"]) is not str):
                    return False
                scope = entry["scope"]
                row = self._conn.execute(
                    """SELECT decision_id FROM h487_consent_grants
                       WHERE identity_key=? AND scope=? AND category_key=?""",
                    (_identity_key(_identity(context, scope)), scope, category.key),
                ).fetchone()
                if row is None or row[0] != entry["decision_id"]:
                    return False
            return self._verified_head_locked() is not None
        except (sqlite3.Error, ValueError, TypeError):
            return False

    def attributed_decision_current(self, context: ConsentContext,
                                    categories: Iterable[ConsentCategory], *,
                                    decision_id: str, decider_principal: str,
                                    choice: str) -> bool:
        """Bind a v2 task proof to the exact signed human decision."""
        selected = self._requested(categories)
        if (selected is None or not _valid_context(context)
                or not isinstance(self._signer, DetachedHMACSigner)):
            return False
        try:
            row = self._conn.execute(
                "SELECT payload, signature FROM h487_consent_decisions WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
            if row is None or not isinstance(row[0], bytes) or not self._signer.verify(row[0], row[1]):
                return False
            decision = json.loads(row[0])
            return (type(decision) is dict and _canonical(decision) == row[0]
                    and _record_version(decision, _DECISION_PURPOSE) == _ATTRIBUTED_VERSION
                    and decision["namespace"] == _NAMESPACE
                    and decision["decision_id"] == decision_id
                    and decision["decider_principal"] == decider_principal
                    and decision["choice"] == choice
                    and decision["context"] == asdict(context)
                    and decision["categories"] == [asdict(item) for item in selected]
                    and decision["state"] == "active")
        except (sqlite3.Error, ValueError, TypeError, KeyError, UnicodeError):
            return False

    def revoke(self, context: ConsentContext) -> bool:
        """Remove grants for this stable identity across all session instances."""
        if not _valid_context(context) or not isinstance(self._signer, DetachedHMACSigner):
            return False
        stable = _identity(context, "always")
        try:
            self._conn.execute("SAVEPOINT h487_consent_revoke")
            try:
                previous = self._verified_head_locked() if self._head_anchor is not None else None
                if self._head_anchor is not None and previous is None:
                    raise ValueError("unverified consent head")
                decisions = self._conn.execute(
                    "SELECT decision_id, payload, signature FROM h487_consent_decisions"
                ).fetchall()
                for decision_id, payload, signature in decisions:
                    if not isinstance(payload, bytes) or not self._signer.verify(payload, signature):
                        raise ValueError("invalid decision evidence")
                    decision = json.loads(payload)
                    if (
                        type(decision) is not dict
                        or _canonical(decision) != payload
                        or decision.get("purpose") != _DECISION_PURPOSE
                        or decision.get("namespace") != _NAMESPACE
                        or _record_version(decision, _DECISION_PURPOSE) is None
                        or decision.get("decision_id") != decision_id
                        or decision.get("state") not in {"active", "revoked"}
                    ):
                        raise ValueError("invalid decision record")
                    recorded_context = ConsentContext(**decision["context"])
                    if not _valid_context(recorded_context):
                        raise ValueError("invalid decision context")
                    if _identity(recorded_context, "always") == stable and decision.get("state") == "active":
                        decision["state"] = "revoked"
                        revoked_payload = _canonical(decision)
                        revoked_tag = self._signer.sign(revoked_payload)
                        if revoked_tag is None:
                            raise ValueError("unavailable signer")
                        self._conn.execute(
                            "UPDATE h487_consent_decisions SET payload=?, signature=? WHERE decision_id=?",
                            (revoked_payload, revoked_tag, decision_id),
                        )
                rows = self._conn.execute("SELECT rowid, payload FROM h487_consent_grants").fetchall()
                delete_ids = []
                for rowid, payload in rows:
                    try:
                        identity = json.loads(payload).get("identity", {})
                        if all(identity.get(key) == value for key, value in stable.items()):
                            delete_ids.append((rowid,))
                    except (TypeError, ValueError, AttributeError):
                        continue
                self._conn.executemany("DELETE FROM h487_consent_grants WHERE rowid=?", delete_ids)
                if previous is not None:
                    self._advance_head_locked(previous)
            except (sqlite3.Error, ValueError, TypeError, KeyError, UnicodeError):
                self._conn.execute("ROLLBACK TO SAVEPOINT h487_consent_revoke")
                self._conn.execute("RELEASE SAVEPOINT h487_consent_revoke")
                return False
            self._conn.execute("RELEASE SAVEPOINT h487_consent_revoke")
            return True
        except sqlite3.Error:
            return False


__all__ = ["ConsentCategory", "ConsentContext", "ConsentLedger"]
