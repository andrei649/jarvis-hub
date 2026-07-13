"""Encrypted bi-temporal store for occupant, presence, and privacy facts."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import math
import re
import stat
import threading
import time
from collections import OrderedDict, defaultdict
from collections.abc import Mapping
from pathlib import Path

from agents.core.paths import data_path
from agents.core.secrets import SecretStore, SecretStoreError

DEFAULT_PATH = data_path("house", "private_graph.enc")
_KEY_REF = "{{secret:house_private_key}}"
_KEY_HANDLE = re.compile(r"\{\{\s*secret:([A-Za-z0-9_.\-]+)\s*\}\}")
_MAX_FACTS = 10_000
_MAX_TOMBSTONES = 20_000
_MAX_IDENTITIES = 5_000
_MAX_CACHE = 256
_MAX_TEXT = 256
_MAX_EVIDENCE_CATEGORIES = 16
_FACT_FIELDS = frozenset(
    {
        "id",
        "seq",
        "subject_id",
        "predicate",
        "object",
        "valid_from",
        "valid_to",
        "observed_at",
        "superseded_at",
        "source_event_key",
        "_source_ref",
        "confidence",
        "fresh_until",
        "privacy_class",
        "consent_version",
        "key_version",
        "multi",
        "evidence_categories",
    }
)
_PSEUDONYM = re.compile(r"occ-[0-9a-f]{32}")
_EVENT_KEY = re.compile(r"evt-[0-9a-f]{48}")


class PrivateStoreError(RuntimeError):
    """The private store cannot be opened or safely mutated."""


def _text(value: object, *, label: str, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    result = value.strip()
    if len(result) > limit:
        raise ValueError(f"{label} exceeds its size limit")
    return result


def _time(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a finite timestamp")
    return result


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence must be between zero and one")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError("confidence must be between zero and one")
    return result


def _evidence_categories(value: object) -> list[str]:
    if isinstance(value, (str, bytes)):
        raise ValueError("evidence categories must be a bounded collection")
    try:
        items = list(value)
    except TypeError as exc:
        raise ValueError("evidence categories must be a bounded collection") from exc
    if len(items) > _MAX_EVIDENCE_CATEGORIES:
        raise ValueError("evidence categories exceed their count limit")
    normalized = sorted({_text(item, label="evidence category", limit=64) for item in items})
    return normalized


def _secret_from_broker(secret_broker, key_ref: str) -> str:
    match = _KEY_HANDLE.fullmatch(key_ref)
    if match is None or secret_broker is None:
        raise PrivateStoreError("private store key is unavailable")
    try:
        result = secret_broker.inject(key_ref, approved=True)
    except Exception as exc:
        raise PrivateStoreError("private store key is unavailable") from exc
    if (
        not isinstance(result, Mapping)
        or result.get("blocked")
        or result.get("injected") != [match.group(1)]
    ):
        raise PrivateStoreError("private store key is unavailable")
    secret = result.get("text")
    if not isinstance(secret, str) or not 32 <= len(secret) <= 4_096:
        raise PrivateStoreError("private store key is invalid")
    return secret


class PrivateHouseStore:
    """Fail-closed encrypted store with consent tombstones and bitemporal reads."""

    def __init__(
        self,
        path: str | Path = DEFAULT_PATH,
        *,
        secret_broker=None,
        key_ref: str = _KEY_REF,
        clock=None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._query_cache: OrderedDict[tuple, list[dict]] = OrderedDict()
        secret = _secret_from_broker(secret_broker, key_ref)
        self._cipher_path = self.path.with_suffix(".cipher")
        self._set_crypto(secret)
        self._load()

    def _set_crypto(self, secret: str) -> None:
        if not isinstance(secret, str) or not 32 <= len(secret) <= 4_096:
            raise PrivateStoreError("private store key is invalid")
        self._id_key = hashlib.sha256(
            b"jarvis-house-pseudonym-v1\0" + secret.encode("utf-8")
        ).digest()
        self._cipher = SecretStore(path=self._cipher_path, key=secret)

    def _empty(self) -> None:
        self._seq = 0
        self._key_version = 1
        self._facts: list[dict] = []
        self._tombstones: dict[str, dict] = {}
        self._revocations: dict[str, dict] = {}
        self._identity_refs: dict[str, str] = {}

    def _load(self) -> None:
        self._empty()
        if not self.path.exists():
            return
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict) or envelope.get("version") != 1:
                raise ValueError("invalid envelope")
            plaintext = self._cipher.decrypt_value(envelope["ciphertext"])
            state = json.loads(plaintext)
            self._deserialize(state)
        except (KeyError, OSError, TypeError, ValueError, SecretStoreError) as exc:
            self._empty()
            raise PrivateStoreError("cannot decrypt or validate private house store") from exc

    def _validate_fact(self, fact: dict, *, key_version: int) -> None:
        if not _FACT_FIELDS.issubset(fact):
            raise ValueError("private fact is incomplete")
        seq = fact["seq"]
        fact_key_version = fact["key_version"]
        if (
            isinstance(seq, bool)
            or not isinstance(seq, int)
            or seq < 1
            or fact["id"] != f"phf-{seq}"
            or isinstance(fact_key_version, bool)
            or not isinstance(fact_key_version, int)
            or not 1 <= fact_key_version <= key_version
            or not isinstance(fact["multi"], bool)
        ):
            raise ValueError("private fact metadata is invalid")
        _text(fact["subject_id"], label="subject_id")
        _text(fact["predicate"], label="predicate", limit=64)
        _text(fact["object"], label="object")
        source_ref = _text(fact["_source_ref"], label="source_event_id")
        source_key = fact["source_event_key"]
        if (
            not isinstance(source_key, str)
            or _EVENT_KEY.fullmatch(source_key) is None
            or source_key != self._event_key(source_ref)
        ):
            raise ValueError("private fact source is invalid")
        valid_from = _time(fact["valid_from"], label="valid_from")
        observed_at = _time(fact["observed_at"], label="observed_at")
        fresh_until = _time(fact["fresh_until"], label="fresh_until")
        if fact["valid_to"] is not None:
            _time(fact["valid_to"], label="valid_to")
        if fact["superseded_at"] is not None:
            _time(fact["superseded_at"], label="superseded_at")
        if fresh_until < observed_at or valid_from > fresh_until:
            raise ValueError("private fact timeline is invalid")
        _confidence(fact["confidence"])
        _text(fact["privacy_class"], label="privacy_class", limit=64)
        _text(fact["consent_version"], label="consent_version", limit=64)
        if fact["evidence_categories"] != _evidence_categories(fact["evidence_categories"]):
            raise ValueError("private fact evidence categories are not canonical")

    def _validate_index_records(
        self, tombstones: dict, revocations: dict, identities: dict
    ) -> None:
        for event_key, record in tombstones.items():
            if not isinstance(record, dict):
                raise ValueError("private tombstone is invalid")
            source_ref = _text(record.get("source_ref"), label="source_event_id")
            _time(record.get("purged_at"), label="purged_at")
            if event_key != self._event_key(source_ref):
                raise ValueError("private tombstone key is invalid")
        for occupant_id, record in revocations.items():
            if not isinstance(record, dict):
                raise ValueError("private revocation is invalid")
            identity_ref = _text(record.get("identity_ref"), label="identity_ref")
            _text(record.get("consent_version"), label="consent_version", limit=64)
            _time(record.get("purged_at"), label="purged_at")
            if occupant_id != self.pseudonym_for(identity_ref):
                raise ValueError("private revocation key is invalid")
        for occupant_id, identity_ref in identities.items():
            identity = _text(identity_ref, label="identity_ref")
            if occupant_id != self.pseudonym_for(identity):
                raise ValueError("private identity key is invalid")
        if set(revocations).intersection(identities):
            raise ValueError("revoked identity cannot remain active")

    def _deserialize(self, state: object) -> None:
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("invalid state")
        facts = state.get("facts", [])
        tombstones = state.get("tombstones", {})
        revocations = state.get("revocations", {})
        identities = state.get("identity_refs", {})
        seq = state.get("seq", 0)
        key_version = state.get("key_version", 1)
        if (
            not isinstance(facts, list)
            or len(facts) > _MAX_FACTS
            or not isinstance(tombstones, dict)
            or len(tombstones) > _MAX_TOMBSTONES
            or not isinstance(revocations, dict)
            or len(revocations) > _MAX_IDENTITIES
            or not isinstance(identities, dict)
            or len(identities) > _MAX_IDENTITIES
            or any(not isinstance(item, dict) for item in facts)
            or isinstance(seq, bool)
            or not isinstance(seq, int)
            or seq < 0
            or isinstance(key_version, bool)
            or not isinstance(key_version, int)
            or key_version < 1
        ):
            raise ValueError("private state exceeds bounds")
        for fact in facts:
            fact.setdefault("evidence_categories", [])
            self._validate_fact(fact, key_version=key_version)
        fact_ids = {fact["id"] for fact in facts}
        event_keys = {fact["source_event_key"] for fact in facts}
        if (
            len(fact_ids) != len(facts)
            or len(event_keys) != len(facts)
            or seq < max((fact["seq"] for fact in facts), default=0)
            or event_keys.intersection(tombstones)
        ):
            raise ValueError("private fact index is invalid")
        self._validate_index_records(tombstones, revocations, identities)
        self._seq = seq
        self._key_version = key_version
        self._facts = facts
        self._tombstones = tombstones
        self._revocations = revocations
        self._identity_refs = {str(key): str(value) for key, value in identities.items()}

    def _state(self) -> dict:
        return {
            "version": 1,
            "seq": self._seq,
            "key_version": self._key_version,
            "facts": self._facts,
            "tombstones": self._tombstones,
            "revocations": self._revocations,
            "identity_refs": self._identity_refs,
        }

    def _save_locked(self) -> None:
        if (
            len(self._facts) > _MAX_FACTS
            or len(self._tombstones) > _MAX_TOMBSTONES
            or len(self._revocations) > _MAX_IDENTITIES
            or len(self._identity_refs) > _MAX_IDENTITIES
        ):
            raise PrivateStoreError("private store capacity exceeded")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(self._state(), sort_keys=True, separators=(",", ":"))
        envelope = {"version": 1, "ciphertext": self._cipher.encrypt_value(plaintext)}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
        with contextlib.suppress(OSError, NotImplementedError):
            tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
        tmp.replace(self.path)
        with contextlib.suppress(OSError, NotImplementedError):
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def _hmac(self, kind: str, value: str, *, length: int = 32) -> str:
        digest = hmac.new(self._id_key, f"{kind}\0{value}".encode(), hashlib.sha256).hexdigest()
        return digest[:length]

    def pseudonym_for(self, occupant_ref: str) -> str:
        occupant = _text(occupant_ref, label="occupant_ref")
        return f"occ-{self._hmac('occupant', occupant)}"

    def _event_key(self, source_event_id: str) -> str:
        return f"evt-{self._hmac('source_event', source_event_id, length=48)}"

    def _remember_identity(self, occupant_ref: str) -> str:
        pseudonym = self.pseudonym_for(occupant_ref)
        existing = self._identity_refs.get(pseudonym)
        if existing is not None and existing != occupant_ref:
            raise PrivateStoreError("pseudonymous identity collision")
        if existing is None and len(self._identity_refs) >= _MAX_IDENTITIES:
            raise PrivateStoreError("private identity capacity exceeded")
        self._identity_refs[pseudonym] = occupant_ref
        return pseudonym

    def _recompute(self, subject: str, predicate: str) -> None:
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for fact in self._facts:
            if fact["subject_id"] == subject and fact["predicate"] == predicate:
                groups[self._group_key(fact)].append(fact)
        for facts in groups.values():
            facts.sort(key=lambda fact: (fact["valid_from"], fact["observed_at"], fact["seq"]))
            for index, fact in enumerate(facts):
                following = facts[index + 1] if index + 1 < len(facts) else None
                fact["valid_to"] = following["valid_from"] if following else None
                fact["superseded_at"] = following["observed_at"] if following else None

    @staticmethod
    def _group_key(fact: Mapping) -> tuple:
        return (
            fact["subject_id"],
            fact["predicate"],
            fact["object"] if fact.get("multi") else "",
        )

    def _record(
        self,
        *,
        occupant_ref: str,
        subject_id: str,
        predicate: str,
        obj: str,
        valid_from: float,
        observed_at: float,
        source_event_id: str,
        confidence: float,
        fresh_until: float,
        consent_version: str,
        privacy_class: str = "household_sensitive",
        linked_identity_ref: str = "",
        multi: bool = False,
        evidence_categories=(),
    ) -> dict:
        occupant = _text(occupant_ref, label="occupant_ref")
        source_ref = _text(source_event_id, label="source_event_id")
        predicate = _text(predicate, label="predicate", limit=64)
        obj = _text(obj, label="object")
        consent = _text(consent_version, label="consent_version", limit=64)
        privacy = _text(privacy_class, label="privacy_class", limit=64)
        valid = _time(valid_from, label="valid_from")
        observed = _time(observed_at, label="observed_at")
        fresh = _time(fresh_until, label="fresh_until")
        if fresh < observed:
            raise ValueError("fresh_until cannot precede observed_at")
        score = _confidence(confidence)
        categories = _evidence_categories(evidence_categories)
        with self._lock:
            occupant_id = self.pseudonym_for(occupant)
            event_key = self._event_key(source_ref)
            if event_key in self._tombstones:
                return {"status": "suppressed", "reason": "source_event_tombstoned"}
            if occupant_id in self._revocations:
                return {"status": "suppressed", "reason": "consent_revoked"}
            if linked_identity_ref and self.pseudonym_for(linked_identity_ref) in self._revocations:
                return {"status": "suppressed", "reason": "consent_revoked"}
            if any(fact.get("source_event_key") == event_key for fact in self._facts):
                return {"status": "duplicate", "reason": "source_event_seen"}
            if len(self._facts) >= _MAX_FACTS:
                raise PrivateStoreError("private fact capacity exceeded")
            backup = json.loads(json.dumps(self._state()))
            try:
                self._remember_identity(occupant)
                if linked_identity_ref:
                    self._remember_identity(linked_identity_ref)
                self._seq += 1
                fact = {
                    "id": f"phf-{self._seq}",
                    "seq": self._seq,
                    "subject_id": subject_id.replace("{occupant}", occupant_id),
                    "predicate": predicate,
                    "object": obj.replace("{occupant}", occupant_id),
                    "valid_from": valid,
                    "valid_to": None,
                    "observed_at": observed,
                    "superseded_at": None,
                    "source_event_key": event_key,
                    "_source_ref": source_ref,
                    "confidence": score,
                    "fresh_until": fresh,
                    "privacy_class": privacy,
                    "consent_version": consent,
                    "key_version": self._key_version,
                    "multi": bool(multi),
                    "evidence_categories": categories,
                }
                self._facts.append(fact)
                self._recompute(fact["subject_id"], predicate)
                self._query_cache.clear()
                self._save_locked()
            except Exception as exc:
                self._deserialize(backup)
                self._query_cache.clear()
                raise PrivateStoreError("cannot persist private house mutation") from exc
            return {"status": "stored", "fact": self._public_fact(fact)}

    def record_presence(self, *, occupant_ref: str, room_id: str, **metadata) -> dict:
        room = _text(room_id, label="room_id", limit=128)
        return self._record(
            occupant_ref=occupant_ref,
            subject_id="{occupant}",
            predicate="present_in",
            obj=room,
            **metadata,
        )

    def record_presence_state(self, *, occupant_ref: str, state: str, **metadata) -> dict:
        value = _text(state, label="presence state", limit=32).lower()
        if value not in {"present", "vacant"}:
            raise ValueError("presence state is invalid")
        return self._record(
            occupant_ref=occupant_ref,
            subject_id="{occupant}",
            predicate="presence_status",
            obj=value,
            **metadata,
        )

    def record_occupancy(self, *, room_id: str, occupant_ref: str, **metadata) -> dict:
        room = _text(room_id, label="room_id", limit=128)
        return self._record(
            occupant_ref=occupant_ref,
            subject_id=f"room:{room}",
            predicate="occupied_by",
            obj="{occupant}",
            multi=True,
            **metadata,
        )

    def record_privacy_context(self, *, occupant_ref: str, context: str, **metadata) -> dict:
        value = _text(context, label="privacy context", limit=128)
        return self._record(
            occupant_ref=occupant_ref,
            subject_id="{occupant}",
            predicate="privacy_context",
            obj=value,
            **metadata,
        )

    def record_identity_link(
        self, *, occupant_ref: str, linked_identity_ref: str, **metadata
    ) -> dict:
        linked = _text(linked_identity_ref, label="linked_identity_ref")
        linked_id = self.pseudonym_for(linked)
        return self._record(
            occupant_ref=occupant_ref,
            subject_id="{occupant}",
            predicate="identity_link",
            obj=linked_id,
            linked_identity_ref=linked,
            multi=True,
            **metadata,
        )

    def _public_fact(self, fact: Mapping) -> dict:
        now = _time(self._clock(), label="clock")
        result = {key: value for key, value in fact.items() if not key.startswith("_")}
        result["fresh"] = now <= float(fact["fresh_until"])
        result["age_seconds"] = max(0.0, now - float(fact["observed_at"]))
        return result

    @staticmethod
    def _effective(facts: list[dict], *, at: float) -> list[dict]:
        grouped: dict[tuple, list[dict]] = defaultdict(list)
        for fact in facts:
            grouped[PrivateHouseStore._group_key(fact)].append(fact)
        visible = []
        for group in grouped.values():
            group.sort(key=lambda fact: (fact["valid_from"], fact["observed_at"], fact["seq"]))
            for index, fact in enumerate(group):
                valid_to = group[index + 1]["valid_from"] if index + 1 < len(group) else None
                if fact["valid_from"] <= at and (valid_to is None or at < valid_to):
                    copy = dict(fact)
                    copy["valid_to"] = valid_to
                    visible.append(copy)
        return visible

    def query(
        self,
        *,
        occupant_ref: str = "",
        room_id: str = "",
        at: float | None = None,
        known_at: float | None = None,
        limit: int = 500,
    ) -> list[dict]:
        target_time = _time(self._clock() if at is None else at, label="at")
        known_time = None if known_at is None else _time(known_at, label="known_at")
        occupant_id = self.pseudonym_for(occupant_ref) if occupant_ref else ""
        room = _text(room_id, label="room_id", limit=128) if room_id else ""
        bounded_limit = max(1, min(int(limit), _MAX_FACTS))
        cache_key = (occupant_id, room, target_time, known_time, bounded_limit)
        with self._lock:
            cached = self._query_cache.get(cache_key)
            if cached is not None:
                self._query_cache.move_to_end(cache_key)
                return [dict(fact) for fact in cached]
            candidates = [
                dict(fact)
                for fact in self._facts
                if known_time is None or fact["observed_at"] <= known_time
            ]
            visible = self._effective(candidates, at=target_time)
            if occupant_id:
                visible = [
                    fact
                    for fact in visible
                    if fact["subject_id"] == occupant_id or fact["object"] == occupant_id
                ]
            if room:
                visible = [
                    fact
                    for fact in visible
                    if fact["subject_id"] == f"room:{room}" or fact["object"] == room
                ]
            visible.sort(key=lambda fact: (fact["subject_id"], fact["predicate"], fact["seq"]))
            result = [self._public_fact(fact) for fact in visible[:bounded_limit]]
            self._query_cache[cache_key] = result
            self._query_cache.move_to_end(cache_key)
            while len(self._query_cache) > _MAX_CACHE:
                self._query_cache.popitem(last=False)
            return [dict(fact) for fact in result]

    def history(self, occupant_ref: str, *, limit: int = 1_000) -> list[dict]:
        occupant_id = self.pseudonym_for(occupant_ref)
        bounded_limit = max(1, min(int(limit), _MAX_FACTS))
        with self._lock:
            facts = [
                dict(fact)
                for fact in self._facts
                if fact["subject_id"] == occupant_id or fact["object"] == occupant_id
            ]
        facts.sort(key=lambda fact: (fact["valid_from"], fact["observed_at"], fact["seq"]))
        return [self._public_fact(fact) for fact in facts[:bounded_limit]]

    def purge_occupant(
        self, occupant_ref: str, *, consent_version: str, purged_at: float | None = None
    ) -> dict:
        occupant = _text(occupant_ref, label="occupant_ref")
        consent = _text(consent_version, label="consent_version", limit=64)
        timestamp = _time(self._clock() if purged_at is None else purged_at, label="purged_at")
        with self._lock:
            occupant_id = self.pseudonym_for(occupant)
            removed = [
                fact
                for fact in self._facts
                if fact["subject_id"] == occupant_id or fact["object"] == occupant_id
            ]
            new_tombstones = {
                self._event_key(fact["_source_ref"])
                for fact in removed
                if self._event_key(fact["_source_ref"]) not in self._tombstones
            }
            if len(self._tombstones) + len(new_tombstones) > _MAX_TOMBSTONES:
                raise PrivateStoreError("private tombstone capacity exceeded")
            if occupant_id not in self._revocations and len(self._revocations) >= _MAX_IDENTITIES:
                raise PrivateStoreError("private revocation capacity exceeded")
            backup = json.loads(json.dumps(self._state()))
            try:
                self._facts = [fact for fact in self._facts if fact not in removed]
                for fact in removed:
                    source_ref = fact["_source_ref"]
                    self._tombstones[self._event_key(source_ref)] = {
                        "source_ref": source_ref,
                        "purged_at": timestamp,
                    }
                self._revocations[occupant_id] = {
                    "identity_ref": occupant,
                    "consent_version": consent,
                    "purged_at": timestamp,
                }
                self._identity_refs.pop(occupant_id, None)
                self._query_cache.clear()
                self._save_locked()
            except Exception as exc:
                self._deserialize(backup)
                self._query_cache.clear()
                raise PrivateStoreError("cannot persist private house purge") from exc
            return {
                "status": "purged",
                "facts_removed": len(removed),
                "events_tombstoned": len(removed),
            }

    def rotate_key(self, *, secret_broker, key_ref: str = _KEY_REF) -> dict:
        new_secret = _secret_from_broker(secret_broker, key_ref)
        with self._lock:
            backup = json.loads(json.dumps(self._state()))
            old_cipher = self._cipher
            old_id_key = self._id_key
            try:
                self._set_crypto(new_secret)
                raw_identities = {
                    **self._identity_refs,
                    **{
                        pseudonym: record["identity_ref"]
                        for pseudonym, record in self._revocations.items()
                    },
                }
                mapping = {old: self.pseudonym_for(raw) for old, raw in raw_identities.items()}
                self._identity_refs = {
                    mapping.get(old, old): raw for old, raw in self._identity_refs.items()
                }
                for fact in self._facts:
                    fact["subject_id"] = mapping.get(fact["subject_id"], fact["subject_id"])
                    fact["object"] = mapping.get(fact["object"], fact["object"])
                    fact["source_event_key"] = self._event_key(fact["_source_ref"])
                    fact["key_version"] = self._key_version + 1
                self._tombstones = {
                    self._event_key(record["source_ref"]): record
                    for record in self._tombstones.values()
                }
                self._revocations = {
                    mapping.get(old, old): record for old, record in self._revocations.items()
                }
                self._key_version += 1
                self._query_cache.clear()
                self._save_locked()
            except Exception as exc:
                self._cipher = old_cipher
                self._id_key = old_id_key
                self._deserialize(backup)
                raise PrivateStoreError("private key rotation failed") from exc
            return {
                "status": "rotated",
                "key_version": self._key_version,
                "facts_rekeyed": len(self._facts),
            }

    def stats(self) -> dict:
        with self._lock:
            return {
                "facts": len(self._facts),
                "tombstones": len(self._tombstones),
                "revocations": len(self._revocations),
                "identity_refs": len(self._identity_refs),
                "cache_entries": len(self._query_cache),
                "key_version": self._key_version,
                "encrypted_at_rest": True,
            }
