"""Fail-closed state machine for exact-head integration acceptance.

This module has no GitHub, network, filesystem, credential, or merge capability. A separately
hosted service must provide authoritative live inputs and an atomic external store.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Protocol

_SCHEMA_VERSION = 1
_MAX_STATE_RECORDS = 4_096
_MAX_STATE_BYTES = 16 * 1024 * 1024
_STATE_KEYS = frozenset({"schema_version", "acceptances", "deliveries", "revocations"})
_SUBJECT_KEYS = frozenset(
    {
        "repository_id",
        "pull_request_number",
        "base_ref",
        "base_sha",
        "head_sha",
        "author_id",
        "last_pusher_id",
    }
)
_ACCEPTANCE_KEYS = frozenset(
    {"delivery_id", "fingerprint", "review_id", "review_revision", "reviewer_id", "subject"}
)
_DELIVERY_KEYS = frozenset(
    {
        "accepted",
        "delivery_id",
        "fingerprint",
        "reason",
        "review_id",
        "review_revision",
        "review_state",
        "reviewer_id",
        "subject",
    }
)
_REVOCATION_KEYS = frozenset(
    {
        "delivery_id",
        "fingerprint",
        "review_id",
        "review_revision",
        "reviewer_id",
        "review_state",
        "subject",
    }
)
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_DELIVERY_PATTERN = re.compile(r"[A-Za-z0-9-]{1,128}\Z")
_REVIEW_STATE_PATTERN = re.compile(r"[a-z_]{1,32}\Z")
_REF_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}\Z")
_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MAX_INTEGER_ID = (1 << 63) - 1
_RESULT_REASONS = frozenset(
    {
        "accepted",
        "base_ref_mismatch",
        "repository_mismatch",
        "review_not_approved",
        "reviewer_is_author",
        "reviewer_is_last_pusher",
        "reviewer_is_owner",
        "reviewer_not_allowed",
        "review_identity_conflict",
        "review_superseded",
        "stale_review_event",
    }
)


def _require_positive_int(value: object, field: str) -> None:
    if type(value) is not int or value <= 0 or value > _MAX_INTEGER_ID:
        raise ValueError(f"{field} must be a positive signed 64-bit integer")


def _require_ref(value: object, field: str) -> None:
    if type(value) is not str or not _REF_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a canonical ref name")
    if value.startswith("/") or value.endswith("/") or "//" in value or ".." in value:
        raise ValueError(f"{field} must be a canonical ref name")


def _require_sha(value: object, field: str) -> None:
    if type(value) is not str or not _SHA_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be lowercase 40-hex")


@dataclass(frozen=True)
class AuthorityPolicy:
    repository_id: int
    base_ref: str
    owner_id: int
    reviewer_ids: frozenset[int]

    def __post_init__(self) -> None:
        if type(self) is not AuthorityPolicy:
            raise ValueError("policy must be an exact AuthorityPolicy")
        _require_positive_int(self.repository_id, "repository_id")
        _require_ref(self.base_ref, "base_ref")
        _require_positive_int(self.owner_id, "owner_id")
        if type(self.reviewer_ids) is not frozenset or not self.reviewer_ids:
            raise ValueError("reviewer_ids must be a non-empty frozenset")
        for reviewer_id in self.reviewer_ids:
            _require_positive_int(reviewer_id, "reviewer_id")


@dataclass(frozen=True)
class PullRequestTuple:
    repository_id: int
    pull_request_number: int
    base_ref: str
    base_sha: str
    head_sha: str
    author_id: int
    last_pusher_id: int

    def __post_init__(self) -> None:
        if type(self) is not PullRequestTuple:
            raise ValueError("subject must be an exact PullRequestTuple")
        _require_positive_int(self.repository_id, "repository_id")
        _require_positive_int(self.pull_request_number, "pull_request_number")
        _require_ref(self.base_ref, "base_ref")
        _require_sha(self.base_sha, "base_sha")
        _require_sha(self.head_sha, "head_sha")
        _require_positive_int(self.author_id, "author_id")
        _require_positive_int(self.last_pusher_id, "last_pusher_id")


@dataclass(frozen=True)
class ReviewEvent:
    delivery_id: str
    review_id: int
    reviewer_id: int
    review_state: str
    subject: PullRequestTuple
    review_revision: int

    def __post_init__(self) -> None:
        if type(self) is not ReviewEvent:
            raise ValueError("event must be an exact ReviewEvent")
        if type(self.delivery_id) is not str or not _DELIVERY_PATTERN.fullmatch(self.delivery_id):
            raise ValueError("delivery_id must be a bounded ASCII identifier")
        _require_positive_int(self.review_id, "review_id")
        _require_positive_int(self.reviewer_id, "reviewer_id")
        _require_positive_int(self.review_revision, "review_revision")
        if type(self.review_state) is not str or not _REVIEW_STATE_PATTERN.fullmatch(
            self.review_state
        ):
            raise ValueError("review_state must be a bounded lowercase identifier")
        if type(self.subject) is not PullRequestTuple:
            raise ValueError("subject must be a PullRequestTuple")


@dataclass(frozen=True)
class AcceptanceResult:
    accepted: bool
    reason: str
    idempotent: bool = False


class AtomicStateStore(Protocol):
    """External store boundary; replacement must be an atomic compare-and-swap."""

    def read(self) -> bytes | None: ...

    def compare_and_swap(self, expected: bytes, replacement: bytes) -> bool: ...


def _encode_state(state: dict[str, object]) -> bytes:
    return (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def empty_state_bytes() -> bytes:
    """Return explicit bootstrap state for an owner-controlled external store."""

    return _encode_state(
        {
            "acceptances": [],
            "deliveries": [],
            "revocations": [],
            "schema_version": _SCHEMA_VERSION,
        }
    )


def _subject_dict(subject: PullRequestTuple) -> dict[str, object]:
    return asdict(subject)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("duplicate JSON key")
        parsed[key] = value
    return parsed


def _require_exact_keys(value: object, expected: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("state object has unexpected keys")
    return value


def _parse_subject(value: object) -> PullRequestTuple:
    subject = _require_exact_keys(value, _SUBJECT_KEYS)
    return PullRequestTuple(**subject)


def _reviewer_rejection(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
    reviewer_id: int,
) -> str | None:
    if reviewer_id == subject.author_id:
        return "reviewer_is_author"
    if reviewer_id == subject.last_pusher_id:
        return "reviewer_is_last_pusher"
    if reviewer_id == policy.owner_id:
        return "reviewer_is_owner"
    if reviewer_id not in policy.reviewer_ids:
        return "reviewer_not_allowed"
    return None


def _review_fingerprint(
    *,
    review_id: int,
    review_revision: int,
    review_state: str,
    reviewer_id: int,
    subject: PullRequestTuple,
) -> str:
    payload = {
        "review_id": review_id,
        "review_revision": review_revision,
        "review_state": review_state,
        "reviewer_id": reviewer_id,
        "subject": _subject_dict(subject),
    }
    return sha256(_encode_state(payload)).hexdigest()


def _review_key(*, repository_id: int, review_id: int) -> tuple[int, int]:
    """Return the immutable repository-scoped identity for one GitHub review."""

    return repository_id, review_id


def _review_identity(*, subject: PullRequestTuple, reviewer_id: int) -> tuple[object, ...]:
    """Return fields that one repository-scoped review ID may never change."""

    return (
        subject.repository_id,
        subject.pull_request_number,
        subject.base_ref,
        subject.base_sha,
        subject.head_sha,
        subject.author_id,
        subject.last_pusher_id,
        reviewer_id,
    )


def _record_review_key(record: dict[str, Any], subject: PullRequestTuple) -> tuple[int, int]:
    return _review_key(repository_id=subject.repository_id, review_id=record["review_id"])


def _record_review_identity(
    record: dict[str, Any], subject: PullRequestTuple
) -> tuple[object, ...]:
    return _review_identity(subject=subject, reviewer_id=record["reviewer_id"])


def _assessed_review_reason(
    *,
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
    reviewer_id: int,
    review_state: str,
) -> str:
    if subject.repository_id != policy.repository_id:
        return "repository_mismatch"
    if subject.base_ref != policy.base_ref:
        return "base_ref_mismatch"
    if review_state != "approved":
        return "review_not_approved"
    return _reviewer_rejection(policy, subject, reviewer_id) or "accepted"


def _parse_state(raw: bytes, policy: AuthorityPolicy) -> dict[str, Any]:
    parsed = json.loads(raw.decode("ascii"), object_pairs_hook=_reject_duplicate_keys)
    state = _require_exact_keys(parsed, _STATE_KEYS)
    if type(state["schema_version"]) is not int or state["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("unsupported schema version")
    if (
        not isinstance(state["acceptances"], list)
        or not isinstance(state["deliveries"], list)
        or not isinstance(state["revocations"], list)
    ):
        raise ValueError("state collections must be lists")
    if any(
        len(state[key]) > _MAX_STATE_RECORDS for key in ("acceptances", "deliveries", "revocations")
    ):
        raise ValueError("state collection exceeds its record bound")

    delivery_ids: set[str] = set()
    deliveries_by_id: dict[str, dict[str, Any]] = {}
    review_identities: dict[tuple[int, int], set[tuple[object, ...]]] = {}
    maximum_revisions: dict[tuple[int, int], int] = {}
    revoked_reviews: set[tuple[int, int]] = set()
    expected_acceptance_ids: set[str] = set()
    expected_revocation_ids: set[str] = set()
    for value in state["deliveries"]:
        record = _require_exact_keys(value, _DELIVERY_KEYS)
        delivery_id = record["delivery_id"]
        fingerprint = record["fingerprint"]
        accepted = record["accepted"]
        reason = record["reason"]
        review_state = record["review_state"]
        if not isinstance(delivery_id, str) or not _DELIVERY_PATTERN.fullmatch(delivery_id):
            raise ValueError("invalid delivery ID")
        if delivery_id in delivery_ids:
            raise ValueError("duplicate delivery ID")
        delivery_ids.add(delivery_id)
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("invalid delivery fingerprint")
        if (
            not isinstance(accepted, bool)
            or not isinstance(reason, str)
            or reason not in _RESULT_REASONS
        ):
            raise ValueError("invalid delivery result")
        _require_positive_int(record["review_id"], "review_id")
        _require_positive_int(record["review_revision"], "review_revision")
        _require_positive_int(record["reviewer_id"], "reviewer_id")
        if not isinstance(review_state, str) or not _REVIEW_STATE_PATTERN.fullmatch(review_state):
            raise ValueError("invalid delivery review state")
        subject = _parse_subject(record["subject"])
        expected_fingerprint = _review_fingerprint(
            review_id=record["review_id"],
            review_revision=record["review_revision"],
            review_state=review_state,
            reviewer_id=record["reviewer_id"],
            subject=subject,
        )
        if fingerprint != expected_fingerprint:
            raise ValueError("delivery fingerprint does not match its canonical event")

        expected_reason = _assessed_review_reason(
            policy=policy,
            subject=subject,
            reviewer_id=record["reviewer_id"],
            review_state=review_state,
        )
        if subject.repository_id == policy.repository_id:
            review_key = _record_review_key(record, subject)
            review_identity = _record_review_identity(record, subject)
            prior_identities = review_identities.setdefault(review_key, set())
            prior_revision = maximum_revisions.get(review_key)
            if expected_reason not in {"repository_mismatch", "base_ref_mismatch"}:
                if review_key in revoked_reviews:
                    expected_reason = "review_superseded"
                elif any(identity != review_identity for identity in prior_identities):
                    expected_reason = "review_identity_conflict"
                elif prior_revision is not None and record["review_revision"] <= prior_revision:
                    expected_reason = "stale_review_event"
            prior_identities.add(review_identity)
            maximum_revisions[review_key] = max(
                record["review_revision"],
                maximum_revisions.get(review_key, 0),
            )
            if (
                expected_reason == "review_not_approved"
                and _reviewer_rejection(policy, subject, record["reviewer_id"]) is None
            ):
                revoked_reviews.add(review_key)
                expected_revocation_ids.add(delivery_id)

        if reason != expected_reason or accepted is not (expected_reason == "accepted"):
            raise ValueError("inconsistent delivery result")
        if accepted:
            expected_acceptance_ids.add(delivery_id)
        deliveries_by_id[delivery_id] = record

    acceptance_ids: set[str] = set()
    for value in state["acceptances"]:
        record = _require_exact_keys(value, _ACCEPTANCE_KEYS)
        delivery_id = record["delivery_id"]
        fingerprint = record["fingerprint"]
        if not isinstance(delivery_id, str) or not _DELIVERY_PATTERN.fullmatch(delivery_id):
            raise ValueError("invalid acceptance delivery ID")
        if delivery_id in acceptance_ids:
            raise ValueError("duplicate acceptance delivery ID")
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("invalid acceptance fingerprint")
        _require_positive_int(record["review_id"], "review_id")
        _require_positive_int(record["review_revision"], "review_revision")
        _require_positive_int(record["reviewer_id"], "reviewer_id")
        subject = _parse_subject(record["subject"])
        delivery = deliveries_by_id.get(delivery_id)
        if (
            delivery is None
            or not delivery["accepted"]
            or delivery["reason"] != "accepted"
            or delivery["fingerprint"] != fingerprint
            or delivery["review_id"] != record["review_id"]
            or delivery["review_revision"] != record["review_revision"]
            or delivery["review_state"] != "approved"
            or delivery["reviewer_id"] != record["reviewer_id"]
            or delivery["subject"] != record["subject"]
        ):
            raise ValueError("acceptance has no matching accepted delivery")
        if subject.repository_id != policy.repository_id or subject.base_ref != policy.base_ref:
            raise ValueError("acceptance is outside configured authority")
        if _reviewer_rejection(policy, subject, record["reviewer_id"]) is not None:
            raise ValueError("acceptance reviewer is not independent")
        acceptance_ids.add(delivery_id)
    if acceptance_ids != expected_acceptance_ids:
        raise ValueError("accepted delivery and acceptance records differ")

    revocation_ids: set[str] = set()
    revocation_review_keys: set[tuple[int, int]] = set()
    for value in state["revocations"]:
        record = _require_exact_keys(value, _REVOCATION_KEYS)
        delivery_id = record["delivery_id"]
        fingerprint = record["fingerprint"]
        review_state = record["review_state"]
        if not isinstance(delivery_id, str) or not _DELIVERY_PATTERN.fullmatch(delivery_id):
            raise ValueError("invalid revocation delivery ID")
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("invalid revocation fingerprint")
        _require_positive_int(record["review_id"], "review_id")
        _require_positive_int(record["review_revision"], "review_revision")
        _require_positive_int(record["reviewer_id"], "reviewer_id")
        if (
            not isinstance(review_state, str)
            or not _REVIEW_STATE_PATTERN.fullmatch(review_state)
            or review_state == "approved"
        ):
            raise ValueError("invalid revocation review state")
        subject = _parse_subject(record["subject"])
        if subject.repository_id != policy.repository_id or subject.base_ref != policy.base_ref:
            raise ValueError("revocation is outside configured authority")
        if _reviewer_rejection(policy, subject, record["reviewer_id"]) is not None:
            raise ValueError("revocation reviewer is not independent")
        delivery = deliveries_by_id.get(delivery_id)
        if (
            delivery is None
            or delivery["accepted"]
            or delivery["reason"] != "review_not_approved"
            or delivery["fingerprint"] != fingerprint
            or delivery["review_id"] != record["review_id"]
            or delivery["review_revision"] != record["review_revision"]
            or delivery["review_state"] != review_state
            or delivery["reviewer_id"] != record["reviewer_id"]
            or delivery["subject"] != record["subject"]
        ):
            raise ValueError("revocation has no matching rejected delivery")
        review_key = _record_review_key(record, subject)
        if delivery_id in revocation_ids or review_key in revocation_review_keys:
            raise ValueError("duplicate revocation review")
        revocation_ids.add(delivery_id)
        revocation_review_keys.add(review_key)
    if revocation_ids != expected_revocation_ids:
        raise ValueError("revoked delivery and revocation records differ")
    return state


def _event_fingerprint(event: ReviewEvent) -> str:
    return _review_fingerprint(
        review_id=event.review_id,
        review_revision=event.review_revision,
        review_state=event.review_state,
        reviewer_id=event.reviewer_id,
        subject=event.subject,
    )


class AcceptanceStateMachine:
    def __init__(self, *, policy: AuthorityPolicy, store: AtomicStateStore) -> None:
        if type(policy) is not AuthorityPolicy:
            raise ValueError("policy must be an exact AuthorityPolicy")
        self._policy = policy
        self._store = store

    def process_review(self, event: ReviewEvent) -> AcceptanceResult:
        if type(event) is not ReviewEvent:
            return AcceptanceResult(False, "invalid_review_event")
        loaded = self._read_state()
        if isinstance(loaded, AcceptanceResult):
            return loaded
        raw, state = loaded
        if len(state["deliveries"]) >= _MAX_STATE_RECORDS:
            return AcceptanceResult(False, "state_capacity_exceeded")

        fingerprint = _event_fingerprint(event)
        previous = next(
            (
                delivery
                for delivery in state["deliveries"]
                if delivery["delivery_id"] == event.delivery_id
            ),
            None,
        )
        if previous is not None:
            if previous["fingerprint"] != fingerprint:
                return AcceptanceResult(False, "delivery_conflict")
            if previous["accepted"]:
                acceptance = self._matching_acceptance(state, event)
                if acceptance is None:
                    return AcceptanceResult(False, "state_corrupt")
                review_key = self._record_key(acceptance)
                if review_key in self._revoked_reviews(state):
                    return AcceptanceResult(False, "review_superseded", idempotent=True)
                if review_key in self._conflicted_reviews(state):
                    return AcceptanceResult(False, "review_identity_conflict", idempotent=True)
            return AcceptanceResult(
                previous["accepted"],
                previous["reason"],
                idempotent=True,
            )

        result = self._assess_review(event)
        subject_data = _subject_dict(event.subject)
        revoked_reviews = self._revoked_reviews(state)
        event_key = self._event_key(event)
        observed_records = [
            record for record in state["deliveries"] if self._record_key(record) == event_key
        ]
        observed_revisions = [record["review_revision"] for record in observed_records]
        if result.reason not in {"repository_mismatch", "base_ref_mismatch"}:
            if event_key in revoked_reviews:
                result = AcceptanceResult(False, "review_superseded")
            elif any(
                self._record_identity(record) != self._event_identity(event)
                for record in observed_records
            ):
                result = AcceptanceResult(False, "review_identity_conflict")
            elif observed_revisions and event.review_revision <= max(observed_revisions):
                result = AcceptanceResult(False, "stale_review_event")
        state["deliveries"].append(
            {
                "delivery_id": event.delivery_id,
                "fingerprint": fingerprint,
                "accepted": result.accepted,
                "reason": result.reason,
                "review_id": event.review_id,
                "review_revision": event.review_revision,
                "review_state": event.review_state,
                "reviewer_id": event.reviewer_id,
                "subject": subject_data,
            }
        )
        if result.accepted:
            state["acceptances"].append(
                {
                    "delivery_id": event.delivery_id,
                    "fingerprint": fingerprint,
                    "review_id": event.review_id,
                    "review_revision": event.review_revision,
                    "reviewer_id": event.reviewer_id,
                    "subject": subject_data,
                }
            )
        elif (
            result.reason == "review_not_approved"
            and _reviewer_rejection(self._policy, event.subject, event.reviewer_id) is None
        ):
            state["revocations"].append(
                {
                    "delivery_id": event.delivery_id,
                    "fingerprint": fingerprint,
                    "review_id": event.review_id,
                    "review_revision": event.review_revision,
                    "reviewer_id": event.reviewer_id,
                    "review_state": event.review_state,
                    "subject": subject_data,
                }
            )

        replacement = _encode_state(state)
        if len(replacement) > _MAX_STATE_BYTES:
            return AcceptanceResult(False, "state_capacity_exceeded")
        saturated = len(state["deliveries"]) >= _MAX_STATE_RECORDS
        try:
            written = self._store.compare_and_swap(raw, replacement)
        except Exception:
            return AcceptanceResult(False, "store_unavailable")
        if written is not True:
            return AcceptanceResult(False, "state_conflict")
        if saturated:
            return AcceptanceResult(False, "state_capacity_exceeded")
        return result

    def verdict_for(self, subject: PullRequestTuple) -> AcceptanceResult:
        if type(subject) is not PullRequestTuple:
            return AcceptanceResult(False, "invalid_subject")
        if subject.repository_id != self._policy.repository_id:
            return AcceptanceResult(False, "repository_mismatch")
        if subject.base_ref != self._policy.base_ref:
            return AcceptanceResult(False, "base_ref_mismatch")
        loaded = self._read_state()
        if isinstance(loaded, AcceptanceResult):
            return loaded
        _raw, state = loaded
        if len(state["deliveries"]) >= _MAX_STATE_RECORDS:
            return AcceptanceResult(False, "state_capacity_exceeded")
        expected = _subject_dict(subject)
        revoked_reviews = self._revoked_reviews(state)
        conflicted_reviews = self._conflicted_reviews(state)
        accepted = any(
            record.get("subject") == expected
            and self._record_key(record) not in revoked_reviews
            and self._record_key(record) not in conflicted_reviews
            for record in state["acceptances"]
        )
        return AcceptanceResult(accepted, "accepted" if accepted else "not_accepted")

    def _read_state(self) -> tuple[bytes, dict[str, object]] | AcceptanceResult:
        try:
            raw = self._store.read()
        except Exception:
            return AcceptanceResult(False, "store_unavailable")
        if raw is None:
            return AcceptanceResult(False, "state_missing")
        if type(raw) is not bytes or len(raw) > _MAX_STATE_BYTES:
            return AcceptanceResult(False, "state_corrupt")
        try:
            state = _parse_state(raw, self._policy)
        except (
            KeyError,
            RecursionError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            return AcceptanceResult(False, "state_corrupt")
        return raw, state

    def _assess_review(self, event: ReviewEvent) -> AcceptanceResult:
        reason = _assessed_review_reason(
            policy=self._policy,
            subject=event.subject,
            reviewer_id=event.reviewer_id,
            review_state=event.review_state,
        )
        return AcceptanceResult(reason == "accepted", reason)

    @staticmethod
    def _matching_acceptance(state: dict[str, Any], event: ReviewEvent) -> dict[str, Any] | None:
        expected_subject = _subject_dict(event.subject)
        return next(
            (
                record
                for record in state["acceptances"]
                if record["delivery_id"] == event.delivery_id
                and record["fingerprint"] == _event_fingerprint(event)
                and record["review_id"] == event.review_id
                and record["reviewer_id"] == event.reviewer_id
                and record["subject"] == expected_subject
            ),
            None,
        )

    @staticmethod
    def _record_key(record: dict[str, Any]) -> tuple[int, int]:
        subject = record["subject"]
        return _review_key(repository_id=subject["repository_id"], review_id=record["review_id"])

    @staticmethod
    def _event_key(event: ReviewEvent) -> tuple[int, int]:
        return _review_key(repository_id=event.subject.repository_id, review_id=event.review_id)

    @staticmethod
    def _record_identity(record: dict[str, Any]) -> tuple[object, ...]:
        subject = PullRequestTuple(**record["subject"])
        return _record_review_identity(record, subject)

    @staticmethod
    def _event_identity(event: ReviewEvent) -> tuple[object, ...]:
        return _review_identity(subject=event.subject, reviewer_id=event.reviewer_id)

    @classmethod
    def _revoked_reviews(cls, state: dict[str, Any]) -> set[tuple[int, int]]:
        return {cls._record_key(record) for record in state["revocations"]}

    @classmethod
    def _conflicted_reviews(cls, state: dict[str, Any]) -> set[tuple[int, int]]:
        identities: dict[tuple[int, int], set[tuple[object, ...]]] = {}
        for record in state["deliveries"]:
            identities.setdefault(cls._record_key(record), set()).add(cls._record_identity(record))
        return {review_key for review_key, values in identities.items() if len(values) > 1}
