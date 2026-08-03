"""Current-revision selection for the bounded Episodes E3.0 retrieval facade."""

from __future__ import annotations

from collections.abc import Sequence

from agents.core.memory._episode_operations import (
    EpisodeMatch,
    EpisodeQuery,
    retrieve_episodes as _score_current_episodes,
)
from agents.core.memory._episode_values import EpisodeRecord


def retrieve_episodes(
    records: Sequence[EpisodeRecord],
    query: EpisodeQuery,
) -> tuple[EpisodeMatch, ...]:
    """Score only the deterministic current revision of each logical episode.

    Callers may provide an immutable revision ledger or a current-only snapshot.
    Complete adjacent revisions are lineage-checked, conflicting forks fail
    closed, and stale pre-correction, pre-tombstone or pre-supersession records
    are never scored.
    """

    return _score_current_episodes(_current_episode_revisions(records), query)


def _current_episode_revisions(
    records: Sequence[EpisodeRecord],
) -> tuple[EpisodeRecord, ...]:
    revisions_by_episode: dict[str, dict[int, EpisodeRecord]] = {}
    for record in records:
        if not isinstance(record, EpisodeRecord):
            raise ValueError("Episode retrieval records must be EpisodeRecord")
        revisions = revisions_by_episode.setdefault(record.episode_id, {})
        existing = revisions.get(record.revision)
        if existing is not None and existing.record_id != record.record_id:
            raise ValueError(
                "Episode retrieval contains conflicting revisions for one episode"
            )
        revisions[record.revision] = record

    current: list[EpisodeRecord] = []
    for episode_id, revisions in revisions_by_episode.items():
        ordered = [revisions[revision] for revision in sorted(revisions)]
        for previous, candidate in zip(ordered, ordered[1:], strict=False):
            if candidate.updated_at < previous.updated_at:
                raise ValueError(
                    "Episode retrieval revision history reverses update time"
                )
            if (
                candidate.revision == previous.revision + 1
                and candidate.supersedes_record_id != previous.record_id
            ):
                raise ValueError(
                    "Episode retrieval revision history has broken lineage"
                )
        current.append(ordered[-1])

    return tuple(sorted(current, key=lambda record: (record.episode_id, record.record_id)))
