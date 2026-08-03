"""Deterministic manual operations for the bounded Nerva Episodes E3.0 contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from agents.core.memory._episode_values import (
    EpisodeAssertion,
    EpisodeOperation,
    EpisodeRecord,
    EpisodeReference,
    EpisodeState,
    _ALLOWED_OPERATIONS,
    _ALLOWED_STATES,
    _KEEP,
    _legacy_assertion_from_payload,
    _legacy_reference_from_payload,
    _merge_references,
    _normalize_text,
    _reject_raw_content,
    _require_current_state,
    _require_non_empty,
    _sha256,
    _validate_sha256_hex,
    _validate_time,
    _validated_string_tuple,
)

@dataclass(frozen=True)
class EpisodeAuditEvent:
    """Tamper-evident audit record for one manual episode mutation."""
    audit_id: str
    operation: EpisodeOperation
    actor_id: str
    occurred_at: float
    reason: str
    input_record_ids: tuple[str, ...]
    output_record_ids: tuple[str, ...]
    input_episode_ids: tuple[str, ...]
    output_episode_ids: tuple[str, ...]
    affected_reference_ids: tuple[str, ...]
    integrity_sha256: str
    schema: str = field(default='nerva.episode.audit.v1', init=False)
    authority: str = field(default='memory_record_only', init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.audit_id, 'audit_id')
        _require_non_empty(self.actor_id, 'actor_id')
        _require_non_empty(self.reason, 'audit reason')
        if self.operation not in _ALLOWED_OPERATIONS:
            raise ValueError('Episode audit operation is not recognized')
        _validate_time(self.occurred_at, 'audit occurred_at')
        for name in ('input_record_ids', 'output_record_ids', 'input_episode_ids', 'output_episode_ids', 'affected_reference_ids'):
            normalized = _validated_string_tuple(getattr(self, name), name, allow_empty=True)
            object.__setattr__(self, name, normalized)
        if not self.output_record_ids:
            raise ValueError('Episode audit must name at least one output record')
        _validate_sha256_hex(self.integrity_sha256, 'audit integrity_sha256')
        if self.audit_id != self.expected_audit_id:
            raise ValueError('Episode audit_id does not match canonical event')
        if not self.verify_integrity():
            raise ValueError('Episode audit integrity verification failed')

    @classmethod
    def build(cls, *, operation: EpisodeOperation, actor_id: str, occurred_at: float, reason: str, before: tuple[EpisodeRecord, ...], after: tuple[EpisodeRecord, ...], affected_reference_ids: tuple[str, ...]=()) -> 'EpisodeAuditEvent':
        input_record_ids = tuple(sorted((record.record_id for record in before)))
        output_record_ids = tuple(sorted((record.record_id for record in after)))
        input_episode_ids = tuple(sorted((record.episode_id for record in before)))
        output_episode_ids = tuple(sorted((record.episode_id for record in after)))
        affected_reference_ids = _validated_string_tuple(affected_reference_ids, 'affected_reference_ids', allow_empty=True)
        material = _audit_material(operation=operation, actor_id=actor_id, occurred_at=float(occurred_at), reason=reason, input_record_ids=input_record_ids, output_record_ids=output_record_ids, input_episode_ids=input_episode_ids, output_episode_ids=output_episode_ids, affected_reference_ids=affected_reference_ids)
        audit_id = 'episode:audit:' + _sha256(material)[:24]
        integrity_sha256 = _sha256({**material, 'audit_id': audit_id})
        return cls(audit_id=audit_id, operation=operation, actor_id=actor_id, occurred_at=float(occurred_at), reason=reason, input_record_ids=input_record_ids, output_record_ids=output_record_ids, input_episode_ids=input_episode_ids, output_episode_ids=output_episode_ids, affected_reference_ids=affected_reference_ids, integrity_sha256=integrity_sha256)

    @property
    def expected_audit_id(self) -> str:
        return 'episode:audit:' + _sha256(self.audit_material())[:24]

    def audit_material(self) -> dict[str, Any]:
        return _audit_material(operation=self.operation, actor_id=self.actor_id, occurred_at=self.occurred_at, reason=self.reason, input_record_ids=self.input_record_ids, output_record_ids=self.output_record_ids, input_episode_ids=self.input_episode_ids, output_episode_ids=self.output_episode_ids, affected_reference_ids=self.affected_reference_ids)

    def verify_integrity(self) -> bool:
        return self.integrity_sha256 == _sha256({**self.audit_material(), 'audit_id': self.audit_id})

@dataclass(frozen=True)
class EpisodeMutation:
    """Atomic manual mutation bundle with a deterministic rollback value."""
    before: tuple[EpisodeRecord, ...]
    after: tuple[EpisodeRecord, ...]
    audit: EpisodeAuditEvent

    def __post_init__(self) -> None:
        if not isinstance(self.before, tuple) or not isinstance(self.after, tuple):
            raise ValueError('Episode mutation records must be immutable tuples')
        if not isinstance(self.audit, EpisodeAuditEvent):
            raise ValueError('Episode mutation requires EpisodeAuditEvent')
        for record in (*self.before, *self.after):
            if not isinstance(record, EpisodeRecord):
                raise ValueError('Episode mutation values must be EpisodeRecord')
            if not record.verify_integrity():
                raise ValueError('Episode mutation contains invalid record integrity')
        if tuple((record.record_id for record in self.before)) != self.audit.input_record_ids:
            raise ValueError('Episode mutation before records do not match audit')
        if tuple((record.record_id for record in self.after)) != self.audit.output_record_ids:
            raise ValueError('Episode mutation after records do not match audit')

    def rollback(self) -> tuple[EpisodeRecord, ...]:
        """Return the exact immutable pre-mutation records for atomic restore."""
        return self.before

@dataclass(frozen=True)
class EpisodePartition:
    """Manual split instruction over a disjoint set of episode references."""
    reference_ids: tuple[str, ...]
    participants: tuple[str, ...]
    started_at: float
    ended_at: float | None
    goal: EpisodeAssertion | None = None
    summary: EpisodeAssertion | None = None
    significance: EpisodeAssertion | None = None

    def __post_init__(self) -> None:
        refs = _validated_string_tuple(self.reference_ids, 'partition reference_ids', allow_empty=False)
        object.__setattr__(self, 'reference_ids', refs)
        participants = _validated_string_tuple(self.participants, 'partition participants', allow_empty=False)
        object.__setattr__(self, 'participants', participants)
        _validate_time(self.started_at, 'partition started_at')
        if self.ended_at is not None:
            _validate_time(self.ended_at, 'partition ended_at')
            if self.ended_at < self.started_at:
                raise ValueError('Partition ended_at cannot precede started_at')

@dataclass(frozen=True)
class EpisodeDerivativeTrace:
    """Deletion/export traversal result for one canonical source root."""
    deletion_root_id: str
    episode_id: str
    episode_record_id: str
    reference_ids: tuple[str, ...]
    assertion_ids: tuple[str, ...]
    tombstoned: bool

@dataclass(frozen=True)
class EpisodeQuery:
    """Pure retrieval fixture; it does not alter production recall."""
    situation_terms: tuple[str, ...] = ()
    outcome_record_ids: tuple[str, ...] = ()
    participants: tuple[str, ...] = ()
    states: tuple[EpisodeState, ...] = ('settled', 'consolidated')
    limit: int = 20

    def __post_init__(self) -> None:
        terms = _validated_string_tuple(tuple((_normalize_text(term) for term in self.situation_terms if term.strip())), 'situation_terms', allow_empty=True)
        object.__setattr__(self, 'situation_terms', terms)
        for name in ('outcome_record_ids', 'participants'):
            normalized = _validated_string_tuple(getattr(self, name), name, allow_empty=True)
            object.__setattr__(self, name, normalized)
        if not isinstance(self.states, tuple) or not self.states:
            raise ValueError('Episode query states must be a non-empty tuple')
        if any((state not in _ALLOWED_STATES for state in self.states)):
            raise ValueError('Episode query state is not recognized')
        object.__setattr__(self, 'states', tuple(sorted(set(self.states))))
        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise ValueError('Episode query limit must be an integer')
        if not 1 <= self.limit <= 1000:
            raise ValueError('Episode query limit must be between 1 and 1000')
        if not (self.situation_terms or self.outcome_record_ids or self.participants):
            raise ValueError('Episode query requires at least one retrieval signal')

@dataclass(frozen=True)
class EpisodeMatch:
    episode: EpisodeRecord
    score: float
    reasons: tuple[str, ...]

def open_episode(*, participants: tuple[str, ...], started_at: float, references: tuple[EpisodeReference, ...], actor_id: str, occurred_at: float, reason: str, goal: EpisodeAssertion | None=None) -> EpisodeMutation:
    record = EpisodeRecord.build(state='open', participants=participants, started_at=started_at, ended_at=None, references=references, goal=goal, summary=None, significance=None, created_at=occurred_at, updated_at=occurred_at)
    after = (record,)
    audit = EpisodeAuditEvent.build(operation='open', actor_id=actor_id, occurred_at=occurred_at, reason=reason, before=(), after=after, affected_reference_ids=tuple((ref.reference_id for ref in references)))
    return EpisodeMutation(before=(), after=after, audit=audit)

def settle_episode(record: EpisodeRecord, *, ended_at: float, actor_id: str, occurred_at: float, reason: str, additional_references: tuple[EpisodeReference, ...]=(), summary: EpisodeAssertion | None=None, significance: EpisodeAssertion | None=None) -> EpisodeMutation:
    _require_current_state(record, {'open'}, 'settle')
    references = _merge_references(record.references, additional_references)
    settled = EpisodeRecord.build(episode_id=record.episode_id, revision=record.revision + 1, state='settled', participants=record.participants, started_at=record.started_at, ended_at=ended_at, references=references, goal=record.goal, summary=summary if summary is not None else record.summary, significance=significance if significance is not None else record.significance, parent_episode_ids=record.parent_episode_ids, supersedes_record_id=record.record_id, created_at=record.created_at, updated_at=occurred_at)
    return _mutation('settle', actor_id, occurred_at, reason, (record,), (settled,), tuple((ref.reference_id for ref in additional_references)))

def consolidate_episode(record: EpisodeRecord, *, actor_id: str, occurred_at: float, reason: str, summary: EpisodeAssertion | None=None, significance: EpisodeAssertion | None=None) -> EpisodeMutation:
    _require_current_state(record, {'settled'}, 'consolidate')
    consolidated = EpisodeRecord.build(episode_id=record.episode_id, revision=record.revision + 1, state='consolidated', participants=record.participants, started_at=record.started_at, ended_at=record.ended_at, references=record.references, goal=record.goal, summary=summary if summary is not None else record.summary, significance=significance if significance is not None else record.significance, parent_episode_ids=record.parent_episode_ids, supersedes_record_id=record.record_id, created_at=record.created_at, updated_at=occurred_at)
    return _mutation('consolidate', actor_id, occurred_at, reason, (record,), (consolidated,))

def correct_episode(record: EpisodeRecord, *, actor_id: str, occurred_at: float, reason: str, participants: tuple[str, ...] | object=_KEEP, started_at: float | object=_KEEP, ended_at: float | None | object=_KEEP, references: tuple[EpisodeReference, ...] | object=_KEEP, goal: EpisodeAssertion | None | object=_KEEP, summary: EpisodeAssertion | None | object=_KEEP, significance: EpisodeAssertion | None | object=_KEEP) -> EpisodeMutation:
    _require_current_state(record, {'open', 'settled', 'consolidated'}, 'correct')
    corrected = EpisodeRecord.build(episode_id=record.episode_id, revision=record.revision + 1, state=record.state, participants=record.participants if participants is _KEEP else participants, started_at=record.started_at if started_at is _KEEP else started_at, ended_at=record.ended_at if ended_at is _KEEP else ended_at, references=record.references if references is _KEEP else references, goal=record.goal if goal is _KEEP else goal, summary=record.summary if summary is _KEEP else summary, significance=record.significance if significance is _KEEP else significance, parent_episode_ids=record.parent_episode_ids, supersedes_record_id=record.record_id, created_at=record.created_at, updated_at=occurred_at)
    return _mutation('correct', actor_id, occurred_at, reason, (record,), (corrected,))

def merge_episodes(records: tuple[EpisodeRecord, ...], *, actor_id: str, occurred_at: float, reason: str, goal: EpisodeAssertion | None=None, summary: EpisodeAssertion | None=None, significance: EpisodeAssertion | None=None) -> EpisodeMutation:
    if not isinstance(records, tuple) or len(records) < 2:
        raise ValueError('Episode merge requires at least two records')
    for record in records:
        _require_current_state(record, {'open', 'settled', 'consolidated'}, 'merge')
    if len({record.episode_id for record in records}) != len(records):
        raise ValueError('Episode merge requires distinct logical episodes')
    references = _merge_references((), tuple((reference for record in records for reference in record.references)))
    participants = tuple(sorted({participant for record in records for participant in record.participants}))
    all_closed = all((record.state != 'open' for record in records))
    merged = EpisodeRecord.build(state='settled' if all_closed else 'open', participants=participants, started_at=min((record.started_at for record in records)), ended_at=max((record.ended_at for record in records if record.ended_at is not None)) if all_closed else None, references=references, goal=goal, summary=summary, significance=significance, parent_episode_ids=tuple((record.episode_id for record in records)), created_at=occurred_at, updated_at=occurred_at)
    superseded = tuple((_superseded_revision(record, successor_episode_ids=(merged.episode_id,), occurred_at=occurred_at) for record in records))
    after = (*superseded, merged)
    return _mutation('merge', actor_id, occurred_at, reason, records, after, tuple((reference.reference_id for reference in references)))

def split_episode(record: EpisodeRecord, partitions: tuple[EpisodePartition, ...], *, actor_id: str, occurred_at: float, reason: str) -> EpisodeMutation:
    _require_current_state(record, {'open', 'settled', 'consolidated'}, 'split')
    if not isinstance(partitions, tuple) or len(partitions) < 2:
        raise ValueError('Episode split requires at least two partitions')
    all_reference_ids = {reference.reference_id for reference in record.references}
    partition_ids = [reference_id for partition in partitions for reference_id in partition.reference_ids]
    if len(partition_ids) != len(set(partition_ids)):
        raise ValueError('Episode split partitions must be disjoint')
    if set(partition_ids) != all_reference_ids:
        raise ValueError('Episode split partitions must cover every reference exactly once')
    by_id = {reference.reference_id: reference for reference in record.references}
    children = tuple((EpisodeRecord.build(state='open' if partition.ended_at is None else 'settled', participants=partition.participants, started_at=partition.started_at, ended_at=partition.ended_at, references=tuple((by_id[ref_id] for ref_id in partition.reference_ids)), goal=partition.goal, summary=partition.summary, significance=partition.significance, parent_episode_ids=(record.episode_id,), created_at=occurred_at, updated_at=occurred_at) for partition in partitions))
    children = tuple(sorted(children, key=lambda item: item.episode_id))
    superseded = _superseded_revision(record, successor_episode_ids=tuple((child.episode_id for child in children)), occurred_at=occurred_at)
    after = (superseded, *children)
    return _mutation('split', actor_id, occurred_at, reason, (record,), after, tuple(partition_ids))

def tombstone_sources(record: EpisodeRecord, *, deletion_root_ids: tuple[str, ...], deleted_at: float, actor_id: str, occurred_at: float, reason: str) -> EpisodeMutation:
    _require_current_state(record, {'open', 'settled', 'consolidated'}, 'tombstone')
    roots = _validated_string_tuple(deletion_root_ids, 'deletion_root_ids', allow_empty=False)
    affected = tuple((reference.reference_id for reference in record.references if reference.deletion_root_id in set(roots)))
    if not affected:
        raise ValueError('Episode tombstone did not match any source lineage')
    affected_set = set(affected)
    references = tuple((replace(reference, tombstoned=True, deleted_at=float(deleted_at)) if reference.reference_id in affected_set else reference for reference in record.references))

    def scrub(assertion: EpisodeAssertion | None) -> EpisodeAssertion | None:
        if assertion is None:
            return None
        if set(assertion.evidence_reference_ids) & affected_set:
            return None
        return assertion
    tombstoned = EpisodeRecord.build(episode_id=record.episode_id, revision=record.revision + 1, state=record.state, participants=record.participants, started_at=record.started_at, ended_at=record.ended_at, references=references, goal=scrub(record.goal), summary=scrub(record.summary), significance=scrub(record.significance), parent_episode_ids=record.parent_episode_ids, supersedes_record_id=record.record_id, created_at=record.created_at, updated_at=occurred_at)
    return _mutation('tombstone', actor_id, occurred_at, reason, (record,), (tombstoned,), affected)

def trace_source_derivatives(record: EpisodeRecord, deletion_root_id: str) -> EpisodeDerivativeTrace:
    _require_non_empty(deletion_root_id, 'deletion_root_id')
    reference_ids = tuple((reference.reference_id for reference in record.references if reference.deletion_root_id == deletion_root_id))
    if not reference_ids:
        raise KeyError(deletion_root_id)
    reference_set = set(reference_ids)
    assertion_ids = tuple((assertion.assertion_id for assertion in (record.goal, record.summary, record.significance) if assertion is not None and set(assertion.evidence_reference_ids) & reference_set))
    tombstoned = all((reference.tombstoned for reference in record.references if reference.reference_id in reference_set))
    return EpisodeDerivativeTrace(deletion_root_id=deletion_root_id, episode_id=record.episode_id, episode_record_id=record.record_id, reference_ids=reference_ids, assertion_ids=assertion_ids, tombstoned=tombstoned)

def retrieve_episodes(records: Sequence[EpisodeRecord], query: EpisodeQuery) -> tuple[EpisodeMatch, ...]:
    if not isinstance(query, EpisodeQuery):
        raise ValueError('Episode retrieval requires EpisodeQuery')
    matches: list[EpisodeMatch] = []
    wanted_outcomes = set(query.outcome_record_ids)
    wanted_participants = set(query.participants)
    for record in records:
        if not isinstance(record, EpisodeRecord):
            raise ValueError('Episode retrieval records must be EpisodeRecord')
        if record.state not in query.states:
            continue
        reasons: list[str] = []
        score = 0.0
        if wanted_participants:
            overlap = wanted_participants & set(record.participants)
            if not overlap:
                continue
            score += len(overlap) * 2.0
            reasons.append('participant')
        if wanted_outcomes:
            outcome_ids = {ref.record_id for ref in record.outcome_references}
            overlap = wanted_outcomes & outcome_ids
            if not overlap:
                continue
            score += len(overlap) * 4.0
            reasons.append('outcome')
        if query.situation_terms:
            text = _normalize_text(' '.join((assertion.text for assertion in (record.goal, record.summary, record.significance) if assertion is not None)))
            term_hits = sum((1 for term in query.situation_terms if term in text))
            if not term_hits:
                continue
            score += float(term_hits)
            reasons.append('situation')
        matches.append(EpisodeMatch(episode=record, score=score, reasons=tuple(sorted(reasons))))
    matches.sort(key=lambda match: (-match.score, -match.episode.updated_at, match.episode.episode_id))
    return tuple(matches[:query.limit])

def migrate_manual_episode_v0(payload: dict[str, Any], *, actor_id: str, occurred_at: float, reason: str) -> EpisodeMutation:
    """Migrate the bounded reference-only draft schema; reject raw content."""
    if not isinstance(payload, dict):
        raise ValueError('Legacy episode payload must be an object')
    _reject_raw_content(payload)
    if payload.get('schema') != 'nerva.episode.manual.v0':
        raise ValueError('Unsupported legacy episode schema')
    references_list: list[EpisodeReference] = []
    reference_aliases: dict[str, str] = {}
    for item in payload['references']:
        reference = _legacy_reference_from_payload(item)
        alias = item.get('legacy_id', reference.reference_id)
        _require_non_empty(alias, 'legacy reference alias')
        if alias in reference_aliases:
            raise ValueError('Legacy episode reference aliases must be unique')
        reference_aliases[alias] = reference.reference_id
        references_list.append(reference)
    references = tuple(references_list)
    assertions = {name: _legacy_assertion_from_payload(payload.get(name), reference_aliases=reference_aliases) for name in ('goal', 'summary', 'significance')}
    record = EpisodeRecord.build(state=payload['state'], participants=tuple(payload['participants']), started_at=payload['started_at'], ended_at=payload.get('ended_at'), references=references, goal=assertions['goal'], summary=assertions['summary'], significance=assertions['significance'], created_at=payload.get('created_at', occurred_at), updated_at=occurred_at, parent_episode_ids=tuple(payload.get('parent_episode_ids', ())))
    return _mutation('migrate', actor_id, occurred_at, reason, (), (record,), tuple((ref.reference_id for ref in references)))

def _mutation(operation: EpisodeOperation, actor_id: str, occurred_at: float, reason: str, before: tuple[EpisodeRecord, ...], after: tuple[EpisodeRecord, ...], affected_reference_ids: tuple[str, ...]=()) -> EpisodeMutation:
    before = tuple(sorted(before, key=lambda record: record.record_id))
    after = tuple(sorted(after, key=lambda record: record.record_id))
    audit = EpisodeAuditEvent.build(operation=operation, actor_id=actor_id, occurred_at=occurred_at, reason=reason, before=before, after=after, affected_reference_ids=affected_reference_ids)
    return EpisodeMutation(before=before, after=after, audit=audit)

def _superseded_revision(record: EpisodeRecord, *, successor_episode_ids: tuple[str, ...], occurred_at: float) -> EpisodeRecord:
    return EpisodeRecord.build(episode_id=record.episode_id, revision=record.revision + 1, state='superseded', participants=record.participants, started_at=record.started_at, ended_at=record.ended_at, references=record.references, goal=record.goal, summary=record.summary, significance=record.significance, parent_episode_ids=record.parent_episode_ids, supersedes_record_id=record.record_id, superseded_by_episode_ids=successor_episode_ids, created_at=record.created_at, updated_at=occurred_at)

def _audit_material(*, operation: EpisodeOperation, actor_id: str, occurred_at: float, reason: str, input_record_ids: tuple[str, ...], output_record_ids: tuple[str, ...], input_episode_ids: tuple[str, ...], output_episode_ids: tuple[str, ...], affected_reference_ids: tuple[str, ...]) -> dict[str, Any]:
    return {'operation': operation, 'actor_id': actor_id, 'occurred_at': occurred_at, 'reason': reason, 'input_record_ids': tuple(input_record_ids), 'output_record_ids': tuple(output_record_ids), 'input_episode_ids': tuple(input_episode_ids), 'output_episode_ids': tuple(output_episode_ids), 'affected_reference_ids': tuple(affected_reference_ids), 'schema': 'nerva.episode.audit.v1', 'authority': 'memory_record_only', 'can_authorize': False, 'can_execute': False, 'can_mark_complete': False}
