"""Focused revision-ledger regressions for the Episodes E3.0 facade."""

from __future__ import annotations

import pytest

from agents.core.memory.atlas_snapshot import AtlasConfidence
from agents.core.memory.episodes import (
    EpisodeAssertion,
    EpisodeQuery,
    EpisodeRecord,
    EpisodeReference,
    correct_episode,
    merge_episodes,
    open_episode,
    retrieve_episodes,
    settle_episode,
    tombstone_sources,
)


def _source(record_id: str, occurred_at: float) -> EpisodeReference:
    return EpisodeReference.build(
        role="source",
        source_id="tests.revision-ledger",
        record_id=record_id,
        source_kind="event",
        source_schema="tests.event.v1",
        privacy_class="private_local",
        integrity_sha256="c" * 64,
        occurred_at=occurred_at,
        deletion_root_id=record_id,
        confidence=AtlasConfidence("unknown"),
    )


def _outcome(record_id: str, occurred_at: float) -> EpisodeReference:
    return EpisodeReference.build(
        role="outcome",
        source_id="tests.revision-ledger",
        record_id=record_id,
        source_kind="verified_outcome",
        source_schema="nerva.outcome.v1",
        privacy_class="private_local",
        integrity_sha256="d" * 64,
        occurred_at=occurred_at,
        deletion_root_id=record_id,
        confidence=AtlasConfidence("measured", 1.0, "tests.revision-ledger"),
    )


def _direct(text: str, *reference_ids: str) -> EpisodeAssertion:
    return EpisodeAssertion.build(
        kind="direct",
        text=text,
        evidence_reference_ids=tuple(reference_ids),
        confidence=AtlasConfidence("unknown"),
    )


def _settled_episode(
    *,
    source: EpisodeReference,
    outcome: EpisodeReference | None,
    summary_text: str,
    started_at: float,
) -> EpisodeRecord:
    opened = open_episode(
        participants=("person:andrei",),
        started_at=started_at,
        references=(source,),
        actor_id="owner:andrei",
        occurred_at=started_at + 10,
        reason="revision-ledger fixture open",
    ).after[0]
    additional = () if outcome is None else (outcome,)
    evidence = (source.reference_id,)
    if outcome is not None:
        evidence += (outcome.reference_id,)
    return settle_episode(
        opened,
        ended_at=started_at + 20,
        actor_id="owner:andrei",
        occurred_at=started_at + 30,
        reason="revision-ledger fixture settle",
        additional_references=additional,
        summary=_direct(summary_text, *evidence),
    ).after[0]


def run_e3_0_revision_checks() -> None:
    """Prove stale immutable revisions cannot satisfy facade retrieval."""

    source = _source("event:travel-plan", 100)
    outcome = _outcome("outcome:travel-plan-confirmed", 120)
    settled = _settled_episode(
        source=source,
        outcome=outcome,
        summary_text="obsolete itinerary wording",
        started_at=100,
    )

    tombstoned = tombstone_sources(
        settled,
        deletion_root_ids=(outcome.deletion_root_id,),
        deleted_at=500,
        actor_id="owner:andrei",
        occurred_at=500,
        reason="verified outcome deleted",
    ).after[0]
    outcome_query = EpisodeQuery(
        outcome_record_ids=("outcome:travel-plan-confirmed",)
    )
    assert retrieve_episodes((settled, tombstoned), outcome_query) == ()
    assert retrieve_episodes((tombstoned, settled), outcome_query) == ()

    corrected = correct_episode(
        settled,
        actor_id="owner:andrei",
        occurred_at=510,
        reason="replace obsolete derived wording",
        summary=_direct("confirmed itinerary retained", source.reference_id),
    ).after[0]
    assert retrieve_episodes(
        (settled, corrected),
        EpisodeQuery(situation_terms=("obsolete itinerary",)),
    ) == ()
    corrected_matches = retrieve_episodes(
        (corrected, settled),
        EpisodeQuery(situation_terms=("confirmed itinerary",)),
    )
    assert len(corrected_matches) == 1
    assert corrected_matches[0].episode == corrected

    second_source = _source("event:packing", 200)
    second = _settled_episode(
        source=second_source,
        outcome=None,
        summary_text="packing complete",
        started_at=200,
    )
    merged = merge_episodes(
        (settled, second),
        actor_id="owner:andrei",
        occurred_at=600,
        reason="same journey boundary",
    )
    superseded = next(
        record for record in merged.after if record.episode_id == settled.episode_id
    )
    assert superseded.state == "superseded"
    assert retrieve_episodes((settled, superseded), outcome_query) == ()

    fork_a = correct_episode(
        settled,
        actor_id="owner:andrei",
        occurred_at=700,
        reason="fork a",
        summary=_direct("fork alpha", source.reference_id),
    ).after[0]
    fork_b = correct_episode(
        settled,
        actor_id="owner:andrei",
        occurred_at=700,
        reason="fork b",
        summary=_direct("fork beta", source.reference_id),
    ).after[0]
    with pytest.raises(ValueError, match="conflicting revisions"):
        retrieve_episodes(
            (fork_a, fork_b),
            EpisodeQuery(participants=("person:andrei",)),
        )

    broken_lineage = EpisodeRecord.build(
        episode_id=settled.episode_id,
        revision=settled.revision + 1,
        state=settled.state,
        participants=settled.participants,
        started_at=settled.started_at,
        ended_at=settled.ended_at,
        references=settled.references,
        goal=settled.goal,
        summary=settled.summary,
        significance=settled.significance,
        parent_episode_ids=settled.parent_episode_ids,
        supersedes_record_id="episode:record:broken-lineage",
        created_at=settled.created_at,
        updated_at=710,
    )
    with pytest.raises(ValueError, match="broken lineage"):
        retrieve_episodes(
            (settled, broken_lineage),
            EpisodeQuery(participants=("person:andrei",)),
        )
