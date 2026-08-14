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
_DELIVERY_KEYS = frozenset({"delivery_id", "fingerprint", "accepted", "reason"})
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
    }
)


def _require_positive_int(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


def _require_ref(value: object, field: str) -> None:
    if not isinstance(value, str) or not _REF_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a canonical ref name")
    if value.startswith("/") or value.endswith("/") or "//" in value or ".." in value:
        raise ValueError(f"{field} must be a canonical ref name")


def _require_sha(value: object, field: str) -> None:
    if not isinstance(value, str) or not _SHA_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be lowercase 40-hex")


@dataclass(frozen=True)
class AuthorityPolicy:
    repository_id: int
    base_ref: str
    owner_id: int
    reviewer_ids: frozenset[int]

    def __post_init__(self) -> None:
        _require_positive_int(self.repository_id, "repository_id")
        _require_ref(self.base_ref, "base_ref")
        _require_positive_int(self.owner_id, "owner_id")
        if not isinstance(self.reviewer_ids, frozenset) or not self.reviewer_ids:
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
    review_revision: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.delivery_id, str) or not _DELIVERY_PATTERN.fullmatch(
            self.delivery_id
        ):
            raise ValueError("delivery_id must be a bounded ASCII identifier")
        _require_positive_int(self.review_id, "review_id")
        _require_positive_int(self.reviewer_id, "reviewer_id")
        _require_positive_int(self.review_revision, "review_revision")
        if not isinstance(self.review_state, str) or not _REVIEW_STATE_PATTERN.fullmatch(
            self.review_state
        ):
            raise ValueError("review_state must be a bounded lowercase identifier")
        if not isinstance(self.subject, PullRequestTuple):
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


def _parse_state(raw: bytes, policy: AuthorityPolicy) -> dict[str, Any]:
    parsed = json.loads(raw.decode("ascii"), object_pairs_hook=_reject_duplicate_keys)
    state = _require_exact_keys(parsed, _STATE_KEYS)
    if isinstance(state["schema_version"], bool) or state["schema_version"] != _SCHEMA_VERSION:
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

    accepted_reviews: dict[tuple[object, ...], dict[str, Any]] = {}
    acceptances_by_delivery: dict[str, dict[str, Any]] = {}
    for value in state["acceptances"]:
        record = _require_exact_keys(value, _ACCEPTANCE_KEYS)
        delivery_id = record["delivery_id"]
        fingerprint = record["fingerprint"]
        if not isinstance(delivery_id, str) or not _DELIVERY_PATTERN.fullmatch(delivery_id):
            raise ValueError("invalid acceptance delivery ID")
        if delivery_id in acceptances_by_delivery:
            raise ValueError("duplicate acceptance delivery ID")
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("invalid acceptance fingerprint")
        _require_positive_int(record["review_id"], "review_id")
        _require_positive_int(record["review_revision"], "review_revision")
        _require_positive_int(record["reviewer_id"], "reviewer_id")
        subject = _parse_subject(record["subject"])
        if subject.repository_id != policy.repository_id or subject.base_ref != policy.base_ref:
            raise ValueError("acceptance is outside configured authority")
        if _reviewer_rejection(policy, subject, record["reviewer_id"]) is not None:
            raise ValueError("acceptance reviewer is not independent")
        expected_fingerprint = _review_fingerprint(
            review_id=record["review_id"],
            review_revision=record["review_revision"],
            review_state="approved",
            reviewer_id=record["reviewer_id"],
            subject=subject,
        )
        if fingerprint != expected_fingerprint:
            raise ValueError("acceptance fingerprint does not match its canonical event")
        review_key = (
            *tuple(_subject_dict(subject).values()),
            record["review_id"],
            record["reviewer_id"],
        )
        if review_key in accepted_reviews:
            raise ValueError("duplicate acceptance review")
        accepted_reviews[review_key] = record
        acceptances_by_delivery[delivery_id] = record

    delivery_ids: set[str] = set()
    accepted_delivery_ids: set[str] = set()
    for value in state["deliveries"]:
        record = _require_exact_keys(value, _DELIVERY_KEYS)
        delivery_id = record["delivery_id"]
        fingerprint = record["fingerprint"]
        accepted = record["accepted"]
        reason = record["reason"]
        if not isinstance(delivery_id, str) or not _DELIVERY_PATTERN.fullmatch(delivery_id):
            raise ValueError("invalid delivery ID")
        if delivery_id in delivery_ids:
            raise ValueError("duplicate delivery ID")
        delivery_ids.add(delivery_id)
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise ValueError("invalid delivery fingerprint")
        if not isinstance(accepted, bool) or reason not in _RESULT_REASONS:
            raise ValueError("invalid delivery result")
        if accepted is not (reason == "accepted"):
            raise ValueError("inconsistent delivery result")
        if accepted:
            acceptance = acceptances_by_delivery.get(delivery_id)
            if acceptance is None or acceptance["fingerprint"] != fingerprint:
                raise ValueError("accepted delivery has no matching acceptance")
            accepted_delivery_ids.add(delivery_id)
    if accepted_delivery_ids != set(acceptances_by_delivery):
        raise ValueError("acceptance has no matching accepted delivery")

    revoked_reviews: set[tuple[object, ...]] = set()
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
        expected_fingerprint = _review_fingerprint(
            review_id=record["review_id"],
            review_revision=record["review_revision"],
            review_state=review_state,
            reviewer_id=record["reviewer_id"],
            subject=subject,
        )
        if fingerprint != expected_fingerprint:
            raise ValueError("revocation fingerprint does not match its canonical event")
        delivery = next(
            (item for item in state["deliveries"] if item["delivery_id"] == delivery_id),
            None,
        )
        if (
            delivery is None
            or delivery["accepted"]
            or delivery["reason"] != "review_not_approved"
            or delivery["fingerprint"] != fingerprint
        ):
            raise ValueError("revocation has no matching rejected delivery")
        review_key = (
            *tuple(_subject_dict(subject).values()),
            record["review_id"],
            record["reviewer_id"],
        )
        if review_key in revoked_reviews:
            raise ValueError("duplicate revocation review")
        acceptance = accepted_reviews.get(review_key)
        if acceptance is not None and record["review_revision"] <= acceptance["review_revision"]:
            raise ValueError("revocation does not advance the review revision")
        revoked_reviews.add(review_key)
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
        self._policy = policy
        self._store = store

    def process_review(self, event: ReviewEvent) -> AcceptanceResult:
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
            if previous["accepted"] and not self._has_matching_acceptance(state, event):
                return AcceptanceResult(False, "state_corrupt")
            return AcceptanceResult(
                previous["accepted"],
                previous["reason"],
                idempotent=True,
            )

        result = self._assess_review(event)
        subject_data = _subject_dict(event.subject)
        revoked_reviews = self._revoked_reviews(state)
        event_key = self._event_key(event)
        if event_key in revoked_reviews:
            return AcceptanceResult(False, "review_superseded")
        observed_revisions = [
            record["review_revision"]
            for collection in (state["acceptances"], state["revocations"])
            for record in collection
            if self._acceptance_key(record) == event_key
        ]
        if observed_revisions and event.review_revision <= max(observed_revisions):
            return AcceptanceResult(False, "stale_review_event")
        already_accepted = any(
            record["subject"] == subject_data
            and self._acceptance_key(record) not in revoked_reviews
            for record in state["acceptances"]
        )
        if result.accepted and already_accepted:
            return AcceptanceResult(True, "accepted", idempotent=True)
        state["deliveries"].append(
            {
                "delivery_id": event.delivery_id,
                "fingerprint": fingerprint,
                "accepted": result.accepted,
                "reason": result.reason,
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

        try:
            written = self._store.compare_and_swap(raw, _encode_state(state))
        except Exception:
            return AcceptanceResult(False, "store_unavailable")
        if written is not True:
            return AcceptanceResult(False, "state_conflict")
        return result

    def verdict_for(self, subject: PullRequestTuple) -> AcceptanceResult:
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
        accepted = any(
            record.get("subject") == expected
            and self._acceptance_key(record) not in revoked_reviews
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
        subject = event.subject
        if subject.repository_id != self._policy.repository_id:
            return AcceptanceResult(False, "repository_mismatch")
        if subject.base_ref != self._policy.base_ref:
            return AcceptanceResult(False, "base_ref_mismatch")
        if event.review_state != "approved":
            return AcceptanceResult(False, "review_not_approved")
        reviewer_rejection = _reviewer_rejection(self._policy, subject, event.reviewer_id)
        if reviewer_rejection is not None:
            return AcceptanceResult(False, reviewer_rejection)
        return AcceptanceResult(True, "accepted")

    @staticmethod
    def _has_matching_acceptance(state: dict[str, Any], event: ReviewEvent) -> bool:
        expected_subject = _subject_dict(event.subject)
        return any(
            record["delivery_id"] == event.delivery_id
            and record["fingerprint"] == _event_fingerprint(event)
            and record["review_id"] == event.review_id
            and record["reviewer_id"] == event.reviewer_id
            and record["subject"] == expected_subject
            for record in state["acceptances"]
        )

    @staticmethod
    def _acceptance_key(record: dict[str, Any]) -> tuple[object, ...]:
        subject = record["subject"]
        return (
            subject["repository_id"],
            subject["pull_request_number"],
            subject["base_ref"],
            subject["base_sha"],
            subject["head_sha"],
            subject["author_id"],
            subject["last_pusher_id"],
            record["review_id"],
            record["reviewer_id"],
        )

    @staticmethod
    def _event_key(event: ReviewEvent) -> tuple[object, ...]:
        subject = event.subject
        return (
            subject.repository_id,
            subject.pull_request_number,
            subject.base_ref,
            subject.base_sha,
            subject.head_sha,
            subject.author_id,
            subject.last_pusher_id,
            event.review_id,
            event.reviewer_id,
        )

    @classmethod
    def _revoked_reviews(cls, state: dict[str, Any]) -> set[tuple[object, ...]]:
        return {cls._acceptance_key(record) for record in state["revocations"]}
