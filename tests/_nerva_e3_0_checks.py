"""Assertions invoked by the existing bi-temporal test for Episodes E3.0.

The helper is deliberately not a pytest collection target. The repository pins
its generated test count, so the bounded Episodes assertions are called from an
existing memory regression test rather than creating count-only churn.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from agents.core.memory.atlas_snapshot import (
    AtlasConfidence,
    LegacyBiTemporalAdapter,
)
from agents.core.memory.bitemporal import BiTemporalKG
from agents.core.memory.episodes import (
    EpisodeAssertion,
    EpisodePartition,
    EpisodeQuery,
    EpisodeRecord,
    EpisodeReference,
    consolidate_episode,
    correct_episode,
    merge_episodes,
    migrate_manual_episode_v0,
    open_episode,
    retrieve_episodes,
    settle_episode,
    split_episode,
    tombstone_sources,
    trace_source_derivatives,
)

ROOT = Path(__file__).resolve().parent.parent


def _direct(text: str, *reference_ids: str) -> EpisodeAssertion:
    return EpisodeAssertion.build(
        kind="direct",
        text=text,
        evidence_reference_ids=tuple(reference_ids),
        confidence=AtlasConfidence("unknown"),
    )


def _inference(
    text: str,
    confidence: float,
    *reference_ids: str,
) -> EpisodeAssertion:
    return EpisodeAssertion.build(
        kind="inference",
        text=text,
        evidence_reference_ids=tuple(reference_ids),
        confidence=AtlasConfidence("measured", confidence, "tests.e3_fixture"),
    )


def _outcome_reference(record_id: str, occurred_at: float) -> EpisodeReference:
    return EpisodeReference.build(
        role="outcome",
        source_id="tests.outcomes",
        record_id=record_id,
        source_kind="verified_outcome",
        source_schema="nerva.outcome.v1",
        privacy_class="private_local",
        integrity_sha256="a" * 64,
        occurred_at=occurred_at,
        deletion_root_id=record_id,
        confidence=AtlasConfidence("measured", 1.0, "tests.verified_outcome"),
    )


def run_e3_0_checks(tmp_path) -> None:
    """Exercise typed lifecycle, manual boundaries, lineage and rollback."""

    kg = BiTemporalKG(path=tmp_path / "episodes-e3-0.json")
    first_fact = kg.add_fact(
        "project:sample",
        "travel_event",
        "raw-private-alpha",
        valid_from=100,
        ingested_at=101,
        multi=True,
    )
    second_fact = kg.add_fact(
        "project:sample",
        "travel_event",
        "raw-private-beta",
        valid_from=200,
        ingested_at=201,
        multi=True,
    )
    third_fact = kg.add_fact(
        "project:sample",
        "packing_event",
        "raw-private-gamma",
        valid_from=400,
        ingested_at=401,
        multi=True,
    )
    adapter = LegacyBiTemporalAdapter()
    first_observation = adapter.project(first_fact)
    second_observation = adapter.project(second_fact)
    third_observation = adapter.project(third_fact)
    first_ref = EpisodeReference.from_atlas(first_observation)
    second_ref = EpisodeReference.from_atlas(second_observation)
    third_ref = EpisodeReference.from_atlas(third_observation)

    forged_observation = replace(first_observation, integrity_sha256="0" * 64)
    with pytest.raises(ValueError, match="integrity"):
        EpisodeReference.from_atlas(forged_observation)

    goal = _direct("resolve family travel planning", first_ref.reference_id)
    opened = open_episode(
        participants=("person:alexandra", "person:andrei"),
        started_at=100,
        references=(second_ref, first_ref),
        actor_id="owner:andrei",
        occurred_at=205,
        reason="manual situation boundary",
        goal=goal,
    )
    opened_reordered = open_episode(
        participants=("person:andrei", "person:alexandra"),
        started_at=100,
        references=(first_ref, second_ref),
        actor_id="owner:andrei",
        occurred_at=205,
        reason="manual situation boundary",
        goal=goal,
    )
    assert opened.after[0] == opened_reordered.after[0]
    assert opened.audit == opened_reordered.audit
    assert opened.before == ()
    open_record = opened.after[0]
    assert open_record.state == "open"
    assert open_record.authority == "memory_record_only"
    assert not open_record.can_authorize
    assert not open_record.can_execute
    assert not open_record.can_mark_complete
    assert open_record.source_references == (first_ref, second_ref)
    serialized_open = open_record.to_json()
    assert "raw-private-alpha" not in serialized_open
    assert "raw-private-beta" not in serialized_open
    assert "transcript" not in serialized_open

    outcome = _outcome_reference("outcome:travel-plan-confirmed", 300)
    weak_summary = _inference(
        "the travel plan probably worked",
        0.50,
        second_ref.reference_id,
    )
    with pytest.raises(ValueError, match="Low-confidence"):
        settle_episode(
            open_record,
            ended_at=300,
            actor_id="owner:andrei",
            occurred_at=310,
            reason="manual close",
            additional_references=(outcome,),
            summary=weak_summary,
        )

    summary = _direct(
        "family travel plan completed",
        first_ref.reference_id,
        outcome.reference_id,
    )
    significance = _inference(
        "the planning session was materially useful",
        0.90,
        second_ref.reference_id,
    )
    settled = settle_episode(
        open_record,
        ended_at=300,
        actor_id="owner:andrei",
        occurred_at=310,
        reason="manual verified close",
        additional_references=(outcome,),
        summary=summary,
        significance=significance,
    )
    settled_record = settled.after[0]
    assert settled_record.state == "settled"
    assert settled_record.revision == 2
    assert settled_record.supersedes_record_id == open_record.record_id
    assert settled_record.outcome_references == (outcome,)
    assert settled.rollback() == (open_record,)
    assert settled.audit.verify_integrity()

    replayed = EpisodeRecord.from_json(settled_record.to_json())
    assert replayed == settled_record
    assert replayed.replay_fingerprint == settled_record.replay_fingerprint
    with pytest.raises(FrozenInstanceError):
        settled_record.state = "open"  # type: ignore[misc]
    tampered_payload = json.loads(settled_record.to_json())
    tampered_payload["can_execute"] = True
    with pytest.raises(ValueError, match="authority"):
        EpisodeRecord.from_payload(tampered_payload)
    tampered_payload = json.loads(settled_record.to_json())
    tampered_payload["summary"]["text"] = "silently changed"
    with pytest.raises(ValueError, match="canonical|integrity"):
        EpisodeRecord.from_payload(tampered_payload)

    matches = retrieve_episodes(
        (settled_record,),
        EpisodeQuery(
            situation_terms=("travel planning",),
            outcome_record_ids=("outcome:travel-plan-confirmed",),
        ),
    )
    assert len(matches) == 1
    assert matches[0].episode == settled_record
    assert matches[0].reasons == ("outcome", "situation")

    clarified_summary = _direct(
        "family travel plan completed and confirmed",
        outcome.reference_id,
    )
    corrected = correct_episode(
        settled_record,
        actor_id="owner:andrei",
        occurred_at=320,
        reason="manual clarification",
        summary=clarified_summary,
    )
    corrected_record = corrected.after[0]
    assert corrected_record.revision == 3
    assert corrected_record.supersedes_record_id == settled_record.record_id
    assert corrected.rollback() == (settled_record,)

    consolidated = consolidate_episode(
        corrected_record,
        actor_id="owner:andrei",
        occurred_at=330,
        reason="manual consolidation",
    )
    assert consolidated.after[0].state == "consolidated"
    assert consolidated.rollback() == (corrected_record,)

    packing_goal = _direct("prepare the family packing", third_ref.reference_id)
    packing_open = open_episode(
        participants=("person:andrei",),
        started_at=400,
        references=(third_ref,),
        actor_id="owner:andrei",
        occurred_at=405,
        reason="manual packing boundary",
        goal=packing_goal,
    ).after[0]
    packing_summary = _direct("packing completed", third_ref.reference_id)
    packing_settled = settle_episode(
        packing_open,
        ended_at=500,
        actor_id="owner:andrei",
        occurred_at=505,
        reason="manual verified close",
        summary=packing_summary,
    ).after[0]

    merge_summary = _direct(
        "family journey preparation completed",
        first_ref.reference_id,
        third_ref.reference_id,
    )
    merged = merge_episodes(
        (settled_record, packing_settled),
        actor_id="owner:andrei",
        occurred_at=600,
        reason="same manual journey boundary",
        summary=merge_summary,
    )
    merged_reordered = merge_episodes(
        (packing_settled, settled_record),
        actor_id="owner:andrei",
        occurred_at=600,
        reason="same manual journey boundary",
        summary=_direct(
            "family journey preparation completed",
            third_ref.reference_id,
            first_ref.reference_id,
        ),
    )
    merged_record = next(
        record
        for record in merged.after
        if record.episode_id not in {settled_record.episode_id, packing_settled.episode_id}
    )
    reordered_record = next(
        record
        for record in merged_reordered.after
        if record.episode_id not in {settled_record.episode_id, packing_settled.episode_id}
    )
    assert merged_record == reordered_record
    assert merged.audit == merged_reordered.audit
    assert len([record for record in merged.after if record.state == "superseded"]) == 2
    assert merged.rollback() == tuple(
        sorted((settled_record, packing_settled), key=lambda record: record.record_id)
    )

    first_partition_ids = (first_ref.reference_id,)
    remaining_ids = tuple(
        reference.reference_id
        for reference in merged_record.references
        if reference.reference_id not in set(first_partition_ids)
    )
    split = split_episode(
        merged_record,
        (
            EpisodePartition(
                reference_ids=first_partition_ids,
                participants=("person:andrei",),
                started_at=100,
                ended_at=150,
            ),
            EpisodePartition(
                reference_ids=remaining_ids,
                participants=("person:alexandra", "person:andrei"),
                started_at=151,
                ended_at=500,
            ),
        ),
        actor_id="owner:andrei",
        occurred_at=700,
        reason="manual situation correction",
    )
    assert len(split.after) == 3
    assert len([record for record in split.after if record.state == "superseded"]) == 1
    child_references = {
        reference.reference_id
        for record in split.after
        if record.state != "superseded"
        for reference in record.references
    }
    assert child_references == {
        reference.reference_id for reference in merged_record.references
    }
    assert split.rollback() == (merged_record,)

    trace = trace_source_derivatives(
        settled_record,
        first_ref.deletion_root_id,
    )
    assert trace.reference_ids == (first_ref.reference_id,)
    assert goal.assertion_id in trace.assertion_ids
    assert summary.assertion_id in trace.assertion_ids
    tombstoned = tombstone_sources(
        settled_record,
        deletion_root_ids=(first_ref.deletion_root_id,),
        deleted_at=800,
        actor_id="owner:andrei",
        occurred_at=800,
        reason="canonical source deleted",
    )
    tombstoned_record = tombstoned.after[0]
    assert trace_source_derivatives(
        tombstoned_record,
        first_ref.deletion_root_id,
    ).tombstoned
    assert tombstoned_record.goal is None
    assert tombstoned_record.summary is None
    assert tombstoned_record.significance is not None
    assert tombstoned.rollback() == (settled_record,)

    legacy = {
        "schema": "nerva.episode.manual.v0",
        "state": "settled",
        "participants": ["person:andrei"],
        "started_at": 100,
        "ended_at": 200,
        "created_at": 100,
        "references": [
            {
                "legacy_id": "source-1",
                "role": "source",
                "source_id": "legacy.turn-store",
                "record_id": "legacy:turn:10",
                "source_kind": "turn",
                "source_schema": "legacy.turn.v1",
                "privacy_class": "private_local",
                "integrity_sha256": "b" * 64,
                "occurred_at": 100,
                "deletion_root_id": "legacy:turn:10",
                "confidence": {
                    "status": "unknown",
                    "value": None,
                    "source": None,
                },
            }
        ],
        "goal": {
            "kind": "direct",
            "text": "remember the appointment",
            "evidence_reference_ids": ["source-1"],
            "confidence": {
                "status": "unknown",
                "value": None,
                "source": None,
            },
        },
        "summary": None,
        "significance": None,
    }
    migrated = migrate_manual_episode_v0(
        legacy,
        actor_id="owner:andrei",
        occurred_at=900,
        reason="bounded reference-only migration",
    )
    assert migrated.audit.operation == "migrate"
    assert migrated.after[0].schema == "nerva.episode.v1"
    assert migrated.rollback() == ()
    raw_legacy = dict(legacy)
    raw_legacy["raw_transcript"] = "must not be copied"
    with pytest.raises(ValueError, match="raw content"):
        migrate_manual_episode_v0(
            raw_legacy,
            actor_id="owner:andrei",
            occurred_at=900,
            reason="invalid migration",
        )

    episode_doc = (ROOT / "docs" / "nerva2" / "EPISODES_E3_0.md").read_text(
        encoding="utf-8"
    )
    assert "Reference-only storage" in episode_doc
    assert "Low-confidence inference" in episode_doc
    assert "Atomic rollback" in episode_doc
    assert "production recall" in episode_doc
    assert "Ultron / `nerva.action.v1`" in episode_doc
    assert "Partial rollback is invalid" in episode_doc
    assert "f2901528e452586f9702c7df1678e72ca36ca2ee" in episode_doc

    m1_doc = (ROOT / "docs" / "nerva2" / "M1_DELIVERY.md").read_text(
        encoding="utf-8"
    )
    assert "E2.0 / #781 / PR #794 is accepted" in m1_doc
    assert "f2901528e452586f9702c7df1678e72ca36ca2ee" in m1_doc
    assert "E3.0 / #782" in m1_doc
    assert "independent integration" in m1_doc
    assert "#783 Synapse and #784 Research Lab remain separately eligible" in m1_doc
