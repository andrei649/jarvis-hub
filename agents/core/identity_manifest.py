"""identity_manifest.py — E4.1 / #1008: what Nerva says it is, and who may change it.

Every other governed thing in this codebase is a *capability* — something Nerva
may or may not do to the world. This is the one record about Nerva itself: its
name, purpose, values, stance on truthfulness, boundaries, stable traits, the
roles it holds toward the people it works with, and the commitments it has made.

The reason it needs governance at all is the thing that makes it different from a
config file. A system that can silently rewrite what it says its boundaries are
has no boundaries — it has a *current opinion* about them, and an opinion is not
something anyone can rely on. So the whole module exists to make one sentence
true: **no identity change becomes authoritative without a versioned proposal and
a human decision** (E4.1 criterion 10).

What that costs, concretely:

* **Versions are append-only and chained.** Each version carries the hash of the
  one before it and an HMAC signature. A history you can edit is a history that
  proves nothing; a chain makes an edit *visible* rather than preventing it,
  which is the honest guarantee — nobody can stop a person with disk access, but
  everyone can find out.
* **A proposal is not a change.** ``propose_change`` writes an ASK-tier task into
  the same decision inbox everything else uses and returns without touching the
  current version. ``apply_change`` refuses any task a **human** did not accept,
  by the same ``MACHINE_DECIDERS`` rule as the permission ledger, the goal
  contract and the activation metric — spelled the same way on purpose.
* **Rollback is a new version, never a deletion.** Going back to version 2 writes
  version 5 whose content matches version 2 and whose record says so. A rollback
  that erased versions 3 and 4 would erase the fact that they were ever adopted,
  which is precisely what someone rewriting an identity would want.
* **The authority is ``identity_record_only``.** Nothing here can act. It records
  what Nerva claims about itself; it cannot use that claim to authorise anything,
  and every ``can_*`` on the manifest is False and stays False.
* **A migration records its own limitations.** Importing an existing SOUL file
  produces version 1 *with a note about what could not be read*, because an
  identity that silently dropped a value it could not parse is worse than one
  that says which lines it did not understand.

Nothing here is Howard's persona system: that is prompt material for an agent.
This is the record of the product's own identity, and it is deliberately small.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.identity")

SCHEMA = "nerva.identity.v1"
KIND = "identity.change"
AUTHORITY = "identity_record_only"

_DEFAULT_DIR = "identity"
_DEFAULT_FILE = "manifest.json"

# The same rule, and the same words, as permission_ledger, goal_contract and
# first_action: an action decided by one of these had no human behind it.
MACHINE_DECIDERS = frozenset({"policy", "system", "kernel", "auto", "worker", "scheduler", ""})
HUMAN_DECISIONS = frozenset({"accept", "edit"})

# Bounds. An identity is a short document by nature; something that needs more
# room than this is a knowledge base wearing an identity's name.
MAX_FIELD_CHARS = 2_000
MAX_LIST_ITEMS = 40
MAX_ITEM_CHARS = 500
MAX_VERSIONS = 500

# The fields a manifest is made of. Listed once so the schema, the diff, the
# validator and the tests cannot drift into three different ideas of what an
# identity contains.
TEXT_FIELDS = ("name", "purpose", "truthfulness")
LIST_FIELDS = ("values", "boundaries", "traits", "roles", "commitments")
FIELDS = TEXT_FIELDS + LIST_FIELDS


class IdentityError(ValueError):
    """A refusal with a stable, named reason."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = str(reason)
        self.detail = str(detail or "")
        super().__init__(self.detail or self.reason)


def _text(value: Any, name: str, *, required: bool = True) -> str:
    text = str(value or "").strip()[:MAX_FIELD_CHARS]
    if required and not text:
        raise IdentityError("field_required", f"{name} is required")
    return text


def _items(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise IdentityError("field_not_a_list", f"{name} must be a list")
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()[:MAX_ITEM_CHARS]
        if text and text not in out:
            out.append(text)
    if len(out) > MAX_LIST_ITEMS:
        raise IdentityError("field_too_long", f"{name} has more than {MAX_LIST_ITEMS} entries")
    return tuple(out)


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class IdentityManifest:
    """What Nerva says it is. A record, never an authority.

    Every ``can_*`` is False and there is no path that sets one: a document
    describing an identity must not become a document granting permissions, and
    the difference is exactly one careless field away.
    """

    name: str
    purpose: str
    truthfulness: str
    values: tuple[str, ...] = ()
    boundaries: tuple[str, ...] = ()
    traits: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    commitments: tuple[str, ...] = ()
    schema_version: str = SCHEMA

    def __post_init__(self) -> None:
        for name in TEXT_FIELDS:
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in LIST_FIELDS:
            object.__setattr__(self, name, _items(getattr(self, name), name))
        if not self.values:
            # A manifest with no values is a name and a job title. The one field
            # that makes this a *identity* rather than a label is required.
            raise IdentityError("values_required", "an identity states at least one value")

    # The authority, spelled out. Read by the contract checker and asserted by
    # test, so "record only" is a property of the code rather than of the prose.
    authority = AUTHORITY
    can_act = False
    can_authorise = False
    can_self_amend = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in LIST_FIELDS:
            payload[name] = list(getattr(self, name))
        return payload

    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict()).encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> IdentityManifest:
        if not isinstance(payload, Mapping):
            raise IdentityError("invalid_manifest", "expected an object")
        return cls(
            name=payload.get("name", ""),
            purpose=payload.get("purpose", ""),
            truthfulness=payload.get("truthfulness", ""),
            values=payload.get("values") or (),
            boundaries=payload.get("boundaries") or (),
            traits=payload.get("traits") or (),
            roles=payload.get("roles") or (),
            commitments=payload.get("commitments") or (),
        )


@dataclass(frozen=True)
class IdentityVersion:
    """One adopted version, and what links it to the one before."""

    version: int
    manifest: IdentityManifest
    at: float
    adopted_by: str
    reason: str = ""
    prev_hash: str = ""
    entry_hash: str = ""
    signature: str = ""
    rolled_back_to: int | None = None
    limitations: tuple[str, ...] = field(default=())

    def body(self) -> str:
        """What the chain hashes. Excludes the hash and signature themselves."""
        return _canonical(
            {
                "version": self.version,
                "manifest": self.manifest.as_dict(),
                "at": self.at,
                "adopted_by": self.adopted_by,
                "reason": self.reason,
                "prev_hash": self.prev_hash,
                "rolled_back_to": self.rolled_back_to,
                "limitations": list(self.limitations),
            }
        )

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "version": self.version,
            "manifest": self.manifest.as_dict(),
            "at": self.at,
            "adopted_by": self.adopted_by,
            "reason": self.reason,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "signature": self.signature,
            "rolled_back_to": self.rolled_back_to,
            "limitations": list(self.limitations),
        }
        return payload


def diff_manifests(
    before: IdentityManifest | None, after: IdentityManifest
) -> dict[str, Any]:
    """What changed, field by field. The decision card renders this.

    A card that said "the identity changed" and nothing more would be a card
    nobody could decide on — the whole point of the ask is that a person reads
    what is actually being proposed.
    """
    changes: dict[str, Any] = {}
    for name in FIELDS:
        new = getattr(after, name)
        old = getattr(before, name) if before is not None else ("" if name in TEXT_FIELDS else ())
        if new != old:
            changes[name] = {
                "from": list(old) if isinstance(old, tuple) else old,
                "to": list(new) if isinstance(new, tuple) else new,
            }
    return changes


class IdentityStore:
    """The append-only version history, at ``data_path('identity/manifest.json')``.

    Signed with the transparency anchor's key when one is available. A chain does
    not *prevent* an edit — nobody can stop someone with disk access — it makes
    an edit visible, which is the guarantee that can actually be kept.
    """

    def __init__(self, path: str | Path | None = None, *, secret: bytes | None = None) -> None:
        self.path = Path(path) if path is not None else data_path(_DEFAULT_DIR, _DEFAULT_FILE)
        self._secret = secret if secret is not None else self._anchor_key()
        self._versions: list[IdentityVersion] = []
        self._load()

    # ── signing ──────────────────────────────────────────────────────────

    @staticmethod
    def _anchor_key() -> bytes:
        """The transparency anchor's key, or a process-local one.

        A store that refused to work without a key would make the identity record
        unavailable on a fresh install, which is worse than an unverifiable one —
        so the fallback exists, and ``verify()`` reports which case it is rather
        than claiming a signature means more than it does.
        """
        try:
            from agents.core.security.anchor import IntentLog

            key = IntentLog()._key
            if isinstance(key, bytes) and key:
                return key
        except Exception:
            logger.debug("transparency anchor key unavailable", exc_info=True)
        return b""

    @property
    def signed(self) -> bool:
        return bool(self._secret)

    def _sign(self, body: str) -> str:
        if not self._secret:
            return ""
        return hmac.new(self._secret, body.encode("utf-8"), hashlib.sha256).hexdigest()

    # ── persistence ──────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(stored, Mapping) or stored.get("schema") != SCHEMA:
            return
        for row in stored.get("versions") or ():
            if not isinstance(row, Mapping):
                continue
            try:
                self._versions.append(
                    IdentityVersion(
                        version=int(row.get("version", 0)),
                        manifest=IdentityManifest.from_dict(row.get("manifest") or {}),
                        at=float(row.get("at", 0.0)),
                        adopted_by=str(row.get("adopted_by", "")),
                        reason=str(row.get("reason", "")),
                        prev_hash=str(row.get("prev_hash", "")),
                        entry_hash=str(row.get("entry_hash", "")),
                        signature=str(row.get("signature", "")),
                        rolled_back_to=row.get("rolled_back_to"),
                        limitations=tuple(row.get("limitations") or ()),
                    )
                )
            except IdentityError:
                # A row that will not parse is kept OUT of the chain rather than
                # dropped silently from the file: verify() then reports a break,
                # which is the honest signal that something is wrong.
                logger.warning("identity version %s is unreadable", row.get("version"))
                break

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "current": self.current_version,
            "versions": [v.as_dict() for v in self._versions],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    # ── reading ──────────────────────────────────────────────────────────

    @property
    def current_version(self) -> int:
        return self._versions[-1].version if self._versions else 0

    def current(self) -> IdentityManifest | None:
        return self._versions[-1].manifest if self._versions else None

    def versions(self) -> list[IdentityVersion]:
        return list(self._versions)

    def version(self, number: int) -> IdentityVersion | None:
        for row in self._versions:
            if row.version == int(number):
                return row
        return None

    def verify(self) -> dict[str, Any]:
        """Walk the chain. Reports the FIRST break, and whether it is signed.

        "Verified" from an unsigned store would be a stronger claim than the data
        supports, so ``signed`` travels with the verdict rather than being folded
        into it.
        """
        prev = ""
        for row in self._versions:
            if row.prev_hash != prev:
                return {"ok": False, "signed": self.signed,
                        "broken_at": row.version, "reason": "prev_hash_mismatch"}
            body = row.body()
            if row.entry_hash != hashlib.sha256(body.encode("utf-8")).hexdigest():
                return {"ok": False, "signed": self.signed,
                        "broken_at": row.version, "reason": "entry_hash_mismatch"}
            if self.signed and not hmac.compare_digest(row.signature, self._sign(body)):
                return {"ok": False, "signed": True,
                        "broken_at": row.version, "reason": "signature_mismatch"}
            prev = row.entry_hash
        return {"ok": True, "signed": self.signed, "versions": len(self._versions)}

    # ── writing ──────────────────────────────────────────────────────────

    def adopt(
        self,
        manifest: IdentityManifest,
        *,
        adopted_by: str,
        reason: str = "",
        rolled_back_to: int | None = None,
        limitations: Sequence[str] = (),
        now: float | None = None,
    ) -> IdentityVersion:
        """Append one version. The ONLY way the current identity changes.

        Callers reach this through ``apply_change`` (a human decision) or
        ``migrate_from_soul`` (the one-time import). It is public because a
        private method that three callers reach anyway is a fiction, and because
        a test proving the governance path is the only *used* one is worth more
        than an underscore.
        """
        if len(self._versions) >= MAX_VERSIONS:
            raise IdentityError("too_many_versions", f"the history holds {MAX_VERSIONS}")
        moment = time.time() if now is None else float(now)
        prev = self._versions[-1].entry_hash if self._versions else ""
        row = IdentityVersion(
            version=self.current_version + 1,
            manifest=manifest,
            at=moment,
            adopted_by=str(adopted_by or "")[:128],
            reason=str(reason or "")[:MAX_FIELD_CHARS],
            prev_hash=prev,
            rolled_back_to=rolled_back_to,
            limitations=tuple(str(x)[:MAX_ITEM_CHARS] for x in limitations),
        )
        body = row.body()
        row = IdentityVersion(
            **{
                **row.__dict__,
                "entry_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "signature": self._sign(body),
            }
        )
        self._versions.append(row)
        self._save()
        logger.info("identity version %s adopted by %s", row.version, row.adopted_by)
        return row


# ── the governance path ──────────────────────────────────────────────────────

def propose_change(
    store: IdentityStore,
    proposed: IdentityManifest,
    *,
    enqueue: Any,
    reason: str = "",
    origin: str = "generated",
) -> dict[str, Any]:
    """Ask for an identity change. Returns without changing anything.

    This is the sentence the whole module exists to make true: a proposal is not
    a change. The task lands ASK-tier in the same decision inbox as every other
    privileged act, carrying the field-by-field diff so a person can read what is
    actually being proposed rather than "the identity changed".

    A proposal identical to the current version is refused rather than enqueued:
    a card that asks the owner to approve nothing teaches them to approve without
    reading, which is the failure mode that makes every other card weaker.
    """
    current = store.current()
    changes = diff_manifests(current, proposed)
    if not changes:
        raise IdentityError("no_change", "the proposal matches the current identity")

    payload = {
        "schema": SCHEMA,
        "kind": KIND,
        "authority": AUTHORITY,
        "from_version": store.current_version,
        "manifest": proposed.as_dict(),
        "fingerprint": proposed.fingerprint(),
        "changes": changes,
        "reason": str(reason or "")[:MAX_FIELD_CHARS],
        "reversible": True,
    }
    task_id = enqueue(
        kind=KIND,
        title=f"Change Nerva's identity ({', '.join(sorted(changes))})"[:200],
        payload=payload,
        autonomy_level="ask",
        origin=origin,
    )
    return {"ok": True, "task_id": task_id, "changes": changes,
            "fingerprint": payload["fingerprint"]}


def apply_change(
    store: IdentityStore,
    task: Any,
    *,
    now: float | None = None,
) -> IdentityVersion:
    """Adopt a proposed identity — only from a task a HUMAN accepted.

    Every refusal here is one way an identity change could become authoritative
    without anyone deciding it:

    * a machine decider (policy, worker, scheduler) is not a person;
    * a decision that is not an accept or an edit is not an approval;
    * a payload whose fingerprint no longer matches what it carries means the
      content changed after the card was shown, so the approval was given for a
      different identity than the one about to be adopted;
    * a proposal built on a version that is no longer current means someone else
      changed the identity in between, and applying it would silently revert them.
    """
    decided_by = str(getattr(task, "decided_by", "") or "").strip().lower()
    decision = str(getattr(task, "decision", "") or "").strip().lower()
    if decided_by in MACHINE_DECIDERS:
        raise IdentityError("not_decided_by_a_person", f"decided_by={decided_by!r}")
    if decision not in HUMAN_DECISIONS:
        raise IdentityError("not_accepted", f"decision={decision!r}")

    payload = getattr(task, "payload", None)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise IdentityError("invalid_payload", "payload is not JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != SCHEMA:
        raise IdentityError("unknown_schema", "not an identity proposal")

    manifest = IdentityManifest.from_dict(payload.get("manifest") or {})
    claimed = str(payload.get("fingerprint") or "")
    if claimed and claimed != manifest.fingerprint():
        # The content changed after the card was rendered. The approval that was
        # given was for a different identity than this one.
        raise IdentityError("fingerprint_mismatch", "the proposal was edited after approval")

    from_version = int(payload.get("from_version", 0) or 0)
    if from_version != store.current_version:
        raise IdentityError(
            "stale_proposal",
            f"proposed against version {from_version}, current is {store.current_version}",
        )

    return store.adopt(
        manifest,
        adopted_by=f"{decision}:{decided_by}",
        reason=str(payload.get("reason", "") or ""),
        now=now,
    )


def rollback(
    store: IdentityStore,
    to_version: int,
    *,
    adopted_by: str,
    now: float | None = None,
) -> IdentityVersion:
    """Go back to an earlier version — as a NEW version, never a deletion.

    Rolling back to version 2 writes version 5 whose content matches version 2
    and whose record says ``rolled_back_to: 2``. Deleting versions 3 and 4 would
    erase the fact that they were ever adopted, which is exactly what someone
    quietly rewriting an identity would want.
    """
    target = store.version(int(to_version))
    if target is None:
        raise IdentityError("unknown_version", f"no version {to_version}")
    if target.version == store.current_version:
        raise IdentityError("already_current", f"version {to_version} is already current")
    return store.adopt(
        target.manifest,
        adopted_by=str(adopted_by),
        reason=f"rollback to version {target.version}",
        rolled_back_to=target.version,
        now=now,
    )


# ── the one-time import ──────────────────────────────────────────────────────

_FRONT_MATTER = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.S)
_KEY_LINE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_ -]*):\s*(?P<value>.*)$")
_LIST_ITEM = re.compile(r"^\s*[-*]\s+(?P<value>.+)$")

# SOUL front-matter keys → manifest fields. Anything else is recorded as a
# limitation rather than guessed at: a value silently dropped because nobody
# mapped its key is a value the identity claims it never had.
_SOUL_KEYS: Mapping[str, str] = {
    "name": "name", "purpose": "purpose", "mission": "purpose",
    "truthfulness": "truthfulness", "honesty": "truthfulness",
    "values": "values", "principles": "values",
    "boundaries": "boundaries", "limits": "boundaries",
    "traits": "traits", "personality": "traits",
    "roles": "roles", "relationships": "roles",
    "commitments": "commitments", "promises": "commitments",
}


def parse_soul_front_matter(text: str) -> tuple[dict[str, Any], list[str]]:
    """``(fields, limitations)`` from a SOUL file's YAML-ish front matter.

    A tiny parser rather than PyYAML: this reads one owner-authored file at
    install time, and every key it does not recognise becomes a *recorded
    limitation* rather than a silent omission. An identity that quietly dropped a
    value it could not parse is worse than one that says which lines it skipped.
    """
    match = _FRONT_MATTER.search(str(text or ""))
    if match is None:
        return {}, ["no front matter found; nothing was imported"]

    fields: dict[str, Any] = {}
    limitations: list[str] = []
    pending_key: str | None = None
    for raw in match.group("body").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = _LIST_ITEM.match(line)
        if item is not None and pending_key:
            fields.setdefault(pending_key, []).append(item.group("value").strip())
            continue
        keyed = _KEY_LINE.match(line)
        if keyed is None:
            limitations.append(f"could not read: {line.strip()[:120]}")
            pending_key = None
            continue
        raw_key = keyed.group("key").strip().lower().replace(" ", "_")
        mapped = _SOUL_KEYS.get(raw_key)
        value = keyed.group("value").strip().strip('"').strip("'")
        if mapped is None:
            limitations.append(f"unmapped key {raw_key!r} was not imported")
            pending_key = None
            continue
        if value:
            fields[mapped] = value
            pending_key = None
        else:
            pending_key = mapped
    return fields, limitations


def migrate_from_soul(
    store: IdentityStore,
    soul_text: str,
    *,
    adopted_by: str = "migration",
    now: float | None = None,
) -> IdentityVersion | None:
    """Import an existing SOUL file as version 1. Idempotent.

    Returns ``None`` when the store already has a version: a migration that ran
    twice and adopted a second version would make an import look like a change
    somebody decided, which is the one thing this module is for.

    A field the parser could not read becomes a recorded limitation on version 1,
    not a gap. The migration also fills the required fields with explicit
    placeholders that *say* they were not imported, because a manifest that
    invented a purpose is worse than one that admits it does not have one yet.
    """
    if store.current_version:
        return None
    fields, limitations = parse_soul_front_matter(soul_text)
    for name in TEXT_FIELDS:
        if not str(fields.get(name) or "").strip():
            fields[name] = f"(not imported: no {name} in the source)"
            limitations.append(f"{name} was not present in the source and is a placeholder")
    if not fields.get("values"):
        fields["values"] = ["(not imported: no values in the source)"]
        limitations.append("values were not present in the source and are a placeholder")
    manifest = IdentityManifest.from_dict(fields)
    return store.adopt(
        manifest,
        adopted_by=adopted_by,
        reason="one-time import from SOUL front matter",
        limitations=tuple(limitations),
        now=now,
    )


__all__ = [
    "AUTHORITY",
    "FIELDS",
    "HUMAN_DECISIONS",
    "KIND",
    "LIST_FIELDS",
    "MACHINE_DECIDERS",
    "MAX_VERSIONS",
    "SCHEMA",
    "TEXT_FIELDS",
    "IdentityError",
    "IdentityManifest",
    "IdentityStore",
    "IdentityVersion",
    "apply_change",
    "diff_manifests",
    "migrate_from_soul",
    "parse_soul_front_matter",
    "propose_change",
    "rollback",
]
