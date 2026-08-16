from __future__ import annotations

import json
from dataclasses import replace

import pytest

import services.integration_authority.state as state_module
from services.integration_authority import (
    AcceptanceStateMachine,
    AtomicStateStore,
    AuthorityPolicy,
    PullRequestTuple,
    ReviewEvent,
    empty_state_bytes,
)

REPOSITORY_ID = 42
OWNER_ID = 900
AUTHOR_ID = 100
LAST_PUSHER_ID = 101
REVIEWER_ID = 901
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


class MemoryStore(AtomicStateStore):
    def __init__(self, initial: bytes | None) -> None:
        self.value = initial
        self.write_count = 0

    def read(self) -> bytes | None:
        return self.value

    def compare_and_swap(self, expected: bytes, replacement: bytes) -> bool:
        if self.value != expected:
            return False
        self.value = replacement
        self.write_count += 1
        return True


class ReadFailureStore(MemoryStore):
    def read(self) -> bytes | None:
        raise OSError("sensitive backend detail")


class WriteFailureStore(MemoryStore):
    def compare_and_swap(self, expected: bytes, replacement: bytes) -> bool:
        raise OSError("sensitive backend detail")


class ConflictStore(MemoryStore):
    def compare_and_swap(self, expected: bytes, replacement: bytes) -> bool:
        return False


class NonBooleanSuccessStore(MemoryStore):
    def compare_and_swap(self, expected: bytes, replacement: bytes) -> bool:
        return 1


class InvalidReadTypeStore(MemoryStore):
    def __init__(self, value: object) -> None:
        self.value = value
        self.write_count = 0

    def read(self) -> bytes | None:
        return self.value  # type: ignore[return-value]


class EvilBytes(bytes):
    def decode(self, *args: object, **kwargs: object) -> str:
        raise OSError("attacker-controlled bytes subclass")


class LyingFrozenset(frozenset[int]):
    def __contains__(self, value: object) -> bool:
        return True


class LyingStr(str):
    def __eq__(self, value: object) -> bool:
        return value == "approved"

    def __ne__(self, value: object) -> bool:
        return False


class LyingInt(int):
    def __le__(self, value: object) -> bool:
        return False

    def __gt__(self, value: object) -> bool:
        return False


@pytest.fixture
def policy() -> AuthorityPolicy:
    return AuthorityPolicy(
        repository_id=REPOSITORY_ID,
        base_ref="main",
        owner_id=OWNER_ID,
        reviewer_ids=frozenset({AUTHOR_ID, LAST_PUSHER_ID, OWNER_ID, REVIEWER_ID}),
    )


@pytest.fixture
def subject() -> PullRequestTuple:
    return PullRequestTuple(
        repository_id=REPOSITORY_ID,
        pull_request_number=17,
        base_ref="main",
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        author_id=AUTHOR_ID,
        last_pusher_id=LAST_PUSHER_ID,
    )


def review(subject: PullRequestTuple, reviewer_id: int = REVIEWER_ID) -> ReviewEvent:
    return ReviewEvent(
        delivery_id="delivery-1",
        review_id=501,
        reviewer_id=reviewer_id,
        review_state="approved",
        subject=subject,
        review_revision=1,
    )


def machine(policy: AuthorityPolicy) -> tuple[AcceptanceStateMachine, MemoryStore]:
    store = MemoryStore(empty_state_bytes())
    return AcceptanceStateMachine(policy=policy, store=store), store


def test_distinct_allowlisted_reviewer_accepts_exact_tuple(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)

    result = authority.process_review(review(subject))

    assert result.accepted is True
    assert result.reason == "accepted"
    assert result.idempotent is False
    assert store.write_count == 1
    assert authority.verdict_for(subject).accepted is True


@pytest.mark.parametrize(
    ("reviewer_id", "reason"),
    [
        (AUTHOR_ID, "reviewer_is_author"),
        (LAST_PUSHER_ID, "reviewer_is_last_pusher"),
        (OWNER_ID, "reviewer_is_owner"),
        (999, "reviewer_not_allowed"),
    ],
)
def test_non_independent_reviewer_is_rejected(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
    reviewer_id: int,
    reason: str,
) -> None:
    authority, _store = machine(policy)

    result = authority.process_review(review(subject, reviewer_id))

    assert result.accepted is False
    assert result.reason == reason
    assert authority.verdict_for(subject).accepted is False


def test_non_approved_review_state_is_rejected(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, _store = machine(policy)

    result = authority.process_review(replace(review(subject), review_state="commented"))

    assert result.accepted is False
    assert result.reason == "review_not_approved"
    assert authority.verdict_for(subject).accepted is False


@pytest.mark.parametrize("review_state", ["dismissed", "changes_requested", "commented"])
def test_later_non_approval_for_same_review_revokes_acceptance(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
    review_state: str,
) -> None:
    authority, store = machine(policy)
    approved = review(subject)
    assert authority.process_review(approved).accepted is True

    revoked = authority.process_review(
        replace(
            approved,
            delivery_id="delivery-2",
            review_state=review_state,
            review_revision=2,
        )
    )

    assert revoked.accepted is False
    assert revoked.reason == "review_not_approved"
    assert store.write_count == 2
    assert authority.verdict_for(subject).accepted is False


@pytest.mark.parametrize(
    ("reviewer_id", "base_ref", "reason"),
    [
        (999, "main", "reviewer_not_allowed"),
        (OWNER_ID, "main", "reviewer_is_owner"),
        (AUTHOR_ID, "main", "reviewer_is_author"),
        (LAST_PUSHER_ID, "main", "reviewer_is_last_pusher"),
        (REVIEWER_ID, "release", "base_ref_mismatch"),
    ],
)
def test_rejected_first_observation_binds_review_identity_and_revision(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
    reviewer_id: int,
    base_ref: str,
    reason: str,
) -> None:
    authority, store = machine(policy)
    rejected_subject = replace(subject, base_ref=base_ref)
    first = replace(
        review(rejected_subject, reviewer_id),
        review_revision=100,
    )
    assert authority.process_review(first) == state_module.AcceptanceResult(False, reason)

    rebound = authority.process_review(
        replace(
            review(subject),
            delivery_id="delivery-2",
            review_revision=1,
        )
    )

    assert rebound == state_module.AcceptanceResult(False, "review_identity_conflict")
    assert store.write_count == 2
    persisted = json.loads(store.value)
    assert persisted["deliveries"][0]["review_id"] == first.review_id
    assert persisted["deliveries"][0]["review_revision"] == 100
    assert persisted["deliveries"][0]["reviewer_id"] == first.reviewer_id
    assert authority.verdict_for(subject).accepted is False


def test_rejected_first_observation_rejects_a_decreasing_revision(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    first = replace(review(subject, 999), review_revision=100)
    assert authority.process_review(first).reason == "reviewer_not_allowed"

    stale = authority.process_review(replace(first, delivery_id="delivery-2", review_revision=1))

    assert stale == state_module.AcceptanceResult(False, "stale_review_event")
    assert store.write_count == 2
    assert authority.verdict_for(subject).accepted is False


def test_replayed_accepted_delivery_is_denied_after_terminal_revocation(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    approved = review(subject)
    assert authority.process_review(approved).accepted is True
    dismissed = replace(
        approved,
        delivery_id="delivery-2",
        review_state="dismissed",
        review_revision=2,
    )
    assert authority.process_review(dismissed).accepted is False

    replayed = authority.process_review(approved)

    assert replayed == state_module.AcceptanceResult(False, "review_superseded", idempotent=True)
    assert store.write_count == 2
    assert authority.verdict_for(subject).accepted is False


def test_revoked_review_id_cannot_be_rebound_to_a_new_head(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    approved = review(subject)
    assert authority.process_review(approved).accepted is True
    assert (
        authority.process_review(
            replace(
                approved,
                delivery_id="delivery-2",
                review_state="dismissed",
                review_revision=2,
            )
        ).accepted
        is False
    )
    new_head = replace(subject, head_sha="c" * 40, last_pusher_id=202)

    rebound = authority.process_review(
        replace(
            approved,
            delivery_id="delivery-3",
            subject=new_head,
            review_revision=3,
        )
    )

    assert rebound == state_module.AcceptanceResult(False, "review_superseded")
    assert store.write_count == 3
    assert authority.verdict_for(new_head).accepted is False


def test_review_id_cannot_be_rebound_to_another_reviewer(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    other_reviewer_id = 902
    policy = replace(
        policy,
        reviewer_ids=policy.reviewer_ids | {other_reviewer_id},
    )
    authority, store = machine(policy)
    approved = review(subject)
    assert authority.process_review(approved).accepted is True

    rebound = authority.process_review(
        replace(
            approved,
            delivery_id="delivery-2",
            reviewer_id=other_reviewer_id,
            review_revision=2,
        )
    )

    assert rebound == state_module.AcceptanceResult(False, "review_identity_conflict")
    assert store.write_count == 2
    assert authority.verdict_for(subject).accepted is False
    replayed = authority.process_review(approved)
    assert replayed == state_module.AcceptanceResult(
        False, "review_identity_conflict", idempotent=True
    )


def test_unrelated_non_approved_review_does_not_revoke_acceptance(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, _store = machine(policy)
    assert authority.process_review(review(subject)).accepted is True

    unrelated = replace(
        review(subject),
        delivery_id="delivery-2",
        review_id=502,
        review_state="dismissed",
        review_revision=2,
    )
    assert authority.process_review(unrelated).accepted is False

    assert authority.verdict_for(subject).accepted is True


def test_new_review_can_restore_acceptance_after_revocation(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    approved = review(subject)
    assert authority.process_review(approved).accepted is True
    assert (
        authority.process_review(
            replace(
                approved,
                delivery_id="delivery-2",
                review_state="dismissed",
                review_revision=2,
            )
        ).accepted
        is False
    )

    replacement_review = replace(approved, delivery_id="delivery-3", review_id=502)
    assert authority.process_review(replacement_review).accepted is True

    assert store.write_count == 3
    assert authority.verdict_for(subject).accepted is True


def test_state_capacity_exhaustion_fails_closed_without_another_write(
    monkeypatch: pytest.MonkeyPatch,
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    assert authority.process_review(review(subject)).accepted is True
    monkeypatch.setattr(state_module, "_MAX_STATE_RECORDS", 1, raising=False)

    result = authority.process_review(
        replace(
            review(subject),
            delivery_id="delivery-2",
            review_state="dismissed",
            review_revision=2,
        )
    )

    assert result.accepted is False
    assert result.reason == "state_capacity_exceeded"
    assert store.write_count == 1
    assert authority.verdict_for(subject).accepted is False
    assert authority.verdict_for(subject).reason == "state_capacity_exceeded"


def test_write_that_exactly_fills_delivery_capacity_never_returns_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    monkeypatch.setattr(state_module, "_MAX_STATE_RECORDS", 1, raising=False)

    result = authority.process_review(review(subject))

    assert result == state_module.AcceptanceResult(False, "state_capacity_exceeded")
    assert store.write_count == 1
    assert authority.verdict_for(subject) == state_module.AcceptanceResult(
        False, "state_capacity_exceeded"
    )
    assert authority.process_review(review(subject)) == state_module.AcceptanceResult(
        False, "state_capacity_exceeded"
    )


def test_saturated_state_overrides_identical_delivery_replay(
    monkeypatch: pytest.MonkeyPatch,
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    approved = review(subject)
    assert authority.process_review(approved).accepted is True
    monkeypatch.setattr(state_module, "_MAX_STATE_RECORDS", 1, raising=False)

    replay = authority.process_review(approved)

    assert replay == state_module.AcceptanceResult(False, "state_capacity_exceeded")
    assert store.write_count == 1
    assert authority.verdict_for(subject).accepted is False


def test_late_approval_for_revoked_review_is_terminally_rejected(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    approved = review(subject)
    assert authority.process_review(approved).accepted is True
    assert (
        authority.process_review(
            replace(
                approved,
                delivery_id="delivery-2",
                review_state="dismissed",
                review_revision=3,
            )
        ).accepted
        is False
    )

    late = authority.process_review(replace(approved, delivery_id="delivery-3", review_revision=4))

    assert late == state_module.AcceptanceResult(False, "review_superseded")
    assert store.write_count == 3
    assert authority.process_review(
        replace(approved, delivery_id="delivery-3", review_revision=4)
    ) == replace(late, idempotent=True)
    assert authority.process_review(
        replace(approved, delivery_id="delivery-3", review_id=502, review_revision=4)
    ) == state_module.AcceptanceResult(False, "delivery_conflict")
    assert store.write_count == 3
    assert authority.verdict_for(subject).accepted is False


def test_out_of_order_approval_after_newer_dismissal_is_rejected(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    dismissed = replace(
        review(subject),
        delivery_id="delivery-2",
        review_state="dismissed",
        review_revision=3,
    )
    assert authority.process_review(dismissed).accepted is False

    delayed = authority.process_review(review(subject))

    assert delayed == state_module.AcceptanceResult(False, "review_superseded")
    assert store.write_count == 2
    assert authority.verdict_for(subject).accepted is False


def test_new_review_id_can_restore_after_terminal_revocation(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, _store = machine(policy)
    approved = review(subject)
    authority.process_review(approved)
    authority.process_review(
        replace(
            approved,
            delivery_id="delivery-2",
            review_state="dismissed",
            review_revision=2,
        )
    )

    replacement = replace(
        approved,
        delivery_id="delivery-3",
        review_id=502,
        review_revision=1,
    )
    assert authority.process_review(replacement).accepted is True
    assert authority.verdict_for(subject).accepted is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository_id", REPOSITORY_ID + 1),
        ("pull_request_number", 18),
        ("base_ref", "release"),
        ("base_sha", "c" * 40),
        ("head_sha", "d" * 40),
    ],
)
def test_acceptance_never_matches_a_different_identity_field(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
    field: str,
    value: int | str,
) -> None:
    authority, _store = machine(policy)
    assert authority.process_review(review(subject)).accepted is True

    changed = replace(subject, **{field: value})

    assert authority.verdict_for(changed).accepted is False


def test_new_head_invalidates_previous_acceptance(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, _store = machine(policy)
    assert authority.process_review(review(subject)).accepted is True

    pushed = replace(subject, head_sha="c" * 40, last_pusher_id=202)

    assert authority.verdict_for(pushed).accepted is False
    assert authority.verdict_for(subject).accepted is True


def test_identical_delivery_replay_is_idempotent(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    event = review(subject)
    assert authority.process_review(event).accepted is True

    replayed = authority.process_review(event)

    assert replayed.accepted is True
    assert replayed.reason == "accepted"
    assert replayed.idempotent is True
    assert store.write_count == 1


def test_delivery_id_cannot_be_reused_for_different_payload(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    event = review(subject)
    assert authority.process_review(event).accepted is True

    conflicted = authority.process_review(replace(event, review_id=502))

    assert conflicted.accepted is False
    assert conflicted.reason == "delivery_conflict"
    assert conflicted.idempotent is False
    assert store.write_count == 1
    assert authority.verdict_for(subject).accepted is True


def test_redundant_approval_delivery_is_persisted_and_replay_bound(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    first = review(subject)
    second = replace(first, delivery_id="delivery-2", review_id=502)
    assert authority.process_review(first).accepted is True

    accepted = authority.process_review(second)

    assert accepted == state_module.AcceptanceResult(True, "accepted")
    assert store.write_count == 2
    conflict = authority.process_review(
        replace(second, review_state="dismissed", review_revision=2)
    )
    assert conflict == state_module.AcceptanceResult(False, "delivery_conflict")
    assert store.write_count == 2

    revoked_first = replace(
        first,
        delivery_id="delivery-3",
        review_state="dismissed",
        review_revision=2,
    )
    assert authority.process_review(revoked_first).accepted is False
    assert authority.verdict_for(subject).accepted is True


def test_newer_approved_revision_is_recorded_before_later_revocation(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    first = review(subject)
    assert authority.process_review(first).accepted is True
    edited = replace(first, delivery_id="delivery-2", review_revision=2)

    assert authority.process_review(edited) == state_module.AcceptanceResult(True, "accepted")
    assert authority.verdict_for(subject).accepted is True

    dismissed = replace(
        edited,
        delivery_id="delivery-3",
        review_state="dismissed",
        review_revision=3,
    )
    assert authority.process_review(dismissed).accepted is False
    assert store.write_count == 3
    assert authority.verdict_for(subject).accepted is False


def test_rejected_delivery_is_also_idempotent(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    event = review(subject, OWNER_ID)
    first = authority.process_review(event)

    replayed = authority.process_review(event)

    assert replayed == replace(first, idempotent=True)
    assert store.write_count == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda values: {**values, "repository_id": True},
        lambda values: {**values, "repository_id": 0},
        lambda values: {**values, "pull_request_number": -1},
        lambda values: {**values, "base_ref": ""},
        lambda values: {**values, "base_ref": "refs/heads/main\nforged"},
        lambda values: {**values, "base_sha": "A" * 40},
        lambda values: {**values, "head_sha": "b" * 39},
        lambda values: {**values, "author_id": False},
        lambda values: {**values, "last_pusher_id": 0},
    ],
)
def test_pull_request_identity_rejects_noncanonical_fields(mutate) -> None:
    values = {
        "repository_id": REPOSITORY_ID,
        "pull_request_number": 17,
        "base_ref": "main",
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "author_id": AUTHOR_ID,
        "last_pusher_id": LAST_PUSHER_ID,
    }

    with pytest.raises(ValueError):
        PullRequestTuple(**mutate(values))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repository_id": 0},
        {"base_ref": ""},
        {"owner_id": True},
        {"reviewer_ids": frozenset()},
        {"reviewer_ids": frozenset({False})},
        {"reviewer_ids": frozenset({10**5_000})},
    ],
)
def test_policy_rejects_invalid_external_identity(kwargs: dict[str, object]) -> None:
    values = {
        "repository_id": REPOSITORY_ID,
        "base_ref": "main",
        "owner_id": OWNER_ID,
        "reviewer_ids": frozenset({REVIEWER_ID}),
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        AuthorityPolicy(**values)


def test_policy_rejects_frozenset_subclass_with_hostile_membership() -> None:
    with pytest.raises(ValueError):
        AuthorityPolicy(
            repository_id=REPOSITORY_ID,
            base_ref="main",
            owner_id=OWNER_ID,
            reviewer_ids=LyingFrozenset({REVIEWER_ID}),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"delivery_id": ""},
        {"delivery_id": "line\nforged"},
        {"review_id": True},
        {"review_id": 10**5_000},
        {"reviewer_id": 0},
        {"reviewer_id": 10**5_000},
        {"review_state": "approved\nforged"},
        {"review_revision": True},
        {"review_revision": 0},
        {"review_revision": 10**5_000},
    ],
)
def test_review_event_rejects_invalid_identity(kwargs: dict[str, object], subject) -> None:
    values = {
        "delivery_id": "delivery-1",
        "review_id": 501,
        "reviewer_id": REVIEWER_ID,
        "review_state": "approved",
        "subject": subject,
        "review_revision": 1,
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        ReviewEvent(**values)


def test_review_event_requires_trusted_revision(subject: PullRequestTuple) -> None:
    with pytest.raises(TypeError):
        ReviewEvent(
            delivery_id="delivery-1",
            review_id=501,
            reviewer_id=REVIEWER_ID,
            review_state="approved",
            subject=subject,
        )


def test_security_primitive_subclasses_are_rejected(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    with pytest.raises(ValueError):
        ReviewEvent(
            delivery_id="delivery-1",
            review_id=501,
            reviewer_id=REVIEWER_ID,
            review_state=LyingStr("dismissed"),
            subject=subject,
            review_revision=1,
        )
    with pytest.raises(ValueError):
        ReviewEvent(
            delivery_id="delivery-1",
            review_id=501,
            reviewer_id=REVIEWER_ID,
            review_state="approved",
            subject=subject,
            review_revision=LyingInt(2**100),
        )

    class SubjectSubclass(PullRequestTuple):
        pass

    with pytest.raises(ValueError):
        SubjectSubclass(**state_module._subject_dict(subject))

    class EventSubclass(ReviewEvent):
        pass

    with pytest.raises(ValueError):
        EventSubclass(
            delivery_id="delivery-1",
            review_id=501,
            reviewer_id=REVIEWER_ID,
            review_state="approved",
            subject=subject,
            review_revision=1,
        )

    class PolicySubclass(AuthorityPolicy):
        pass

    with pytest.raises(ValueError):
        PolicySubclass(
            repository_id=policy.repository_id,
            base_ref=policy.base_ref,
            owner_id=policy.owner_id,
            reviewer_ids=policy.reviewer_ids,
        )


def _state_bytes(**updates: object) -> bytes:
    state = json.loads(empty_state_bytes())
    state.update(updates)
    return (json.dumps(state, separators=(",", ":")) + "\n").encode("ascii")


def _encoded_state(state: object) -> bytes:
    return (json.dumps(state, separators=(",", ":")) + "\n").encode("ascii")


def _delivery_record(
    event: ReviewEvent,
    *,
    accepted: bool,
    reason: str,
) -> dict[str, object]:
    return {
        "accepted": accepted,
        "delivery_id": event.delivery_id,
        "fingerprint": state_module._event_fingerprint(event),
        "reason": reason,
        "review_id": event.review_id,
        "review_revision": event.review_revision,
        "review_state": event.review_state,
        "reviewer_id": event.reviewer_id,
        "subject": state_module._subject_dict(event.subject),
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json\n",
        b"\xff\n",
        b'{"schema_version":1,"schema_version":1,"acceptances":[],"deliveries":[]}\n',
        b'{"schema_version":1,"acceptances":[],"deliveries":[],"extra":'
        + (b"[" * 2_000)
        + b"0"
        + (b"]" * 2_000)
        + b"}\n",
        _state_bytes(schema_version=2),
        _state_bytes(schema_version=1.0),
        _state_bytes(schema_version=True),
        _state_bytes(extra="candidate-controlled"),
        _state_bytes(acceptances=[{"subject": {}}]),
        _state_bytes(deliveries=[{"delivery_id": "x"}]),
    ],
)
def test_corrupt_or_noncanonical_state_fails_closed(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
    raw: bytes,
) -> None:
    authority = AcceptanceStateMachine(policy=policy, store=MemoryStore(raw))

    assert authority.process_review(review(subject)).reason == "state_corrupt"
    verdict = authority.verdict_for(subject)
    assert verdict.accepted is False
    assert verdict.reason == "state_corrupt"


def test_missing_state_fails_closed_without_initializing(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    store = MemoryStore(None)
    authority = AcceptanceStateMachine(policy=policy, store=store)

    assert authority.process_review(review(subject)).reason == "state_missing"
    assert authority.verdict_for(subject).reason == "state_missing"
    assert store.value is None
    assert store.write_count == 0


def test_store_read_failure_is_bounded_and_fails_closed(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority = AcceptanceStateMachine(policy=policy, store=ReadFailureStore(empty_state_bytes()))

    assert authority.process_review(review(subject)).reason == "store_unavailable"
    assert authority.verdict_for(subject).reason == "store_unavailable"


@pytest.mark.parametrize(
    "raw",
    ["not-bytes", bytearray(empty_state_bytes()), 1],
)
def test_non_bytes_store_state_is_bounded_and_fails_closed(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
    raw: object,
) -> None:
    authority = AcceptanceStateMachine(policy=policy, store=InvalidReadTypeStore(raw))

    assert authority.process_review(review(subject)).reason == "state_corrupt"
    assert authority.verdict_for(subject).reason == "state_corrupt"


def test_bytes_subclass_cannot_execute_an_overridden_decoder(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    raw = EvilBytes(empty_state_bytes())
    authority = AcceptanceStateMachine(policy=policy, store=InvalidReadTypeStore(raw))

    assert authority.process_review(review(subject)).reason == "state_corrupt"
    assert authority.verdict_for(subject).reason == "state_corrupt"


def test_oversized_raw_store_state_fails_closed_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    raw = empty_state_bytes()
    monkeypatch.setattr(state_module, "_MAX_STATE_BYTES", len(raw) - 1, raising=False)
    authority = AcceptanceStateMachine(policy=policy, store=MemoryStore(raw))

    assert authority.process_review(review(subject)).reason == "state_corrupt"
    assert authority.verdict_for(subject).reason == "state_corrupt"


def test_state_that_would_exceed_raw_size_bound_is_not_written(
    monkeypatch: pytest.MonkeyPatch,
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    monkeypatch.setattr(
        state_module,
        "_MAX_STATE_BYTES",
        len(empty_state_bytes()),
        raising=False,
    )

    result = authority.process_review(review(subject))

    assert result == state_module.AcceptanceResult(False, "state_capacity_exceeded")
    assert store.write_count == 0
    assert store.value == empty_state_bytes()


def test_store_write_failure_never_returns_acceptance(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority = AcceptanceStateMachine(policy=policy, store=WriteFailureStore(empty_state_bytes()))

    result = authority.process_review(review(subject))

    assert result.accepted is False
    assert result.reason == "store_unavailable"


def test_atomic_write_conflict_never_returns_acceptance(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority = AcceptanceStateMachine(policy=policy, store=ConflictStore(empty_state_bytes()))

    result = authority.process_review(review(subject))

    assert result.accepted is False
    assert result.reason == "state_conflict"


def test_non_boolean_cas_result_never_returns_acceptance(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    store = NonBooleanSuccessStore(empty_state_bytes())
    authority = AcceptanceStateMachine(policy=policy, store=store)

    result = authority.process_review(review(subject))

    assert result.accepted is False
    assert result.reason == "state_conflict"
    assert authority.verdict_for(subject).accepted is False


def test_persisted_owner_acceptance_is_corrupt_not_trusted(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    assert authority.process_review(review(subject)).accepted is True
    state = json.loads(store.value)
    state["acceptances"][0]["reviewer_id"] = OWNER_ID
    store.value = _encoded_state(state)

    verdict = authority.verdict_for(subject)

    assert verdict.accepted is False
    assert verdict.reason == "state_corrupt"


def test_persisted_acceptance_fingerprint_is_recomputed(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    assert authority.process_review(review(subject)).accepted is True
    state = json.loads(store.value)
    state["acceptances"][0]["fingerprint"] = "0" * 64
    state["deliveries"][0]["fingerprint"] = "0" * 64
    store.value = _encoded_state(state)

    verdict = authority.verdict_for(subject)

    assert verdict.accepted is False
    assert verdict.reason == "state_corrupt"


def test_persisted_delivery_requires_its_full_review_observation(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    assert authority.process_review(review(subject)).accepted is True
    state = json.loads(store.value)
    del state["deliveries"][0]["review_revision"]
    store.value = _encoded_state(state)

    assert authority.verdict_for(subject).reason == "state_corrupt"


def test_persisted_acceptance_for_other_repository_is_corrupt_not_trusted(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    assert authority.process_review(review(subject)).accepted is True
    state = json.loads(store.value)
    state["acceptances"][0]["subject"]["repository_id"] = REPOSITORY_ID + 1
    store.value = _encoded_state(state)

    verdict = authority.verdict_for(subject)

    assert verdict.accepted is False
    assert verdict.reason == "state_corrupt"


def test_accepted_delivery_without_matching_acceptance_is_corrupt(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    event = review(subject)
    assert authority.process_review(event).accepted is True
    state = json.loads(store.value)
    state["acceptances"] = []
    store.value = _encoded_state(state)

    replayed = authority.process_review(event)

    assert replayed.accepted is False
    assert replayed.reason == "state_corrupt"


def test_acceptance_without_matching_delivery_is_corrupt(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    assert authority.process_review(review(subject)).accepted is True
    state = json.loads(store.value)
    state["deliveries"] = []
    store.value = _encoded_state(state)

    verdict = authority.verdict_for(subject)

    assert verdict.accepted is False
    assert verdict.reason == "state_corrupt"


def test_persisted_non_monotonic_revocation_revision_is_corrupt(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    approved = review(subject)
    authority.process_review(approved)
    dismissed = replace(
        approved,
        delivery_id="delivery-2",
        review_state="dismissed",
        review_revision=2,
    )
    authority.process_review(dismissed)
    state = json.loads(store.value)
    fingerprint = state_module._review_fingerprint(
        review_id=dismissed.review_id,
        review_revision=1,
        review_state=dismissed.review_state,
        reviewer_id=dismissed.reviewer_id,
        subject=dismissed.subject,
    )
    state["revocations"][0]["review_revision"] = 1
    state["revocations"][0]["fingerprint"] = fingerprint
    state["deliveries"][1]["fingerprint"] = fingerprint
    store.value = _encoded_state(state)

    assert authority.verdict_for(subject).reason == "state_corrupt"


def test_persisted_conflicting_same_revision_observation_is_corrupt(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    dismissed = replace(
        review(subject),
        review_state="dismissed",
        review_revision=3,
    )
    authority.process_review(dismissed)
    state = json.loads(store.value)
    conflicting = replace(
        dismissed,
        delivery_id="delivery-2",
        review_state="changes_requested",
    )
    fingerprint = state_module._event_fingerprint(conflicting)
    record = dict(state["revocations"][0])
    record.update(
        delivery_id=conflicting.delivery_id,
        fingerprint=fingerprint,
        review_state=conflicting.review_state,
    )
    state["revocations"].append(record)
    state["deliveries"].append(
        _delivery_record(conflicting, accepted=False, reason="review_not_approved")
    )
    store.value = _encoded_state(state)

    assert authority.verdict_for(subject).reason == "state_corrupt"


def test_persisted_review_id_bound_to_multiple_subjects_is_corrupt(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    authority, store = machine(policy)
    approved = review(subject)
    assert authority.process_review(approved).accepted is True
    changed_subject = replace(subject, head_sha="c" * 40, last_pusher_id=202)
    conflicting = replace(
        approved,
        delivery_id="delivery-2",
        subject=changed_subject,
        review_revision=2,
    )
    state = json.loads(store.value)
    fingerprint = state_module._event_fingerprint(conflicting)
    state["acceptances"].append(
        {
            "delivery_id": conflicting.delivery_id,
            "fingerprint": fingerprint,
            "review_id": conflicting.review_id,
            "review_revision": conflicting.review_revision,
            "reviewer_id": conflicting.reviewer_id,
            "subject": state_module._subject_dict(conflicting.subject),
        }
    )
    state["deliveries"].append(_delivery_record(conflicting, accepted=True, reason="accepted"))
    store.value = _encoded_state(state)

    assert authority.verdict_for(subject).reason == "state_corrupt"


def test_persisted_review_id_bound_to_multiple_reviewers_is_corrupt(
    policy: AuthorityPolicy,
    subject: PullRequestTuple,
) -> None:
    other_reviewer_id = 902
    policy = replace(
        policy,
        reviewer_ids=policy.reviewer_ids | {other_reviewer_id},
    )
    authority, store = machine(policy)
    approved = review(subject)
    assert authority.process_review(approved).accepted is True
    conflicting = replace(
        approved,
        delivery_id="delivery-2",
        reviewer_id=other_reviewer_id,
        review_revision=2,
    )
    state = json.loads(store.value)
    fingerprint = state_module._event_fingerprint(conflicting)
    state["acceptances"].append(
        {
            "delivery_id": conflicting.delivery_id,
            "fingerprint": fingerprint,
            "review_id": conflicting.review_id,
            "review_revision": conflicting.review_revision,
            "reviewer_id": conflicting.reviewer_id,
            "subject": state_module._subject_dict(conflicting.subject),
        }
    )
    state["deliveries"].append(_delivery_record(conflicting, accepted=True, reason="accepted"))
    store.value = _encoded_state(state)

    assert authority.verdict_for(subject).reason == "state_corrupt"
