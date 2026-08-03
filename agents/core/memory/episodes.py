"""Typed, deterministic Episodes E3.0 contract and manual boundary facade.

The facade stores content-free source pointers and bounded caller-supplied
derived assertions. It never copies source payloads automatically and never
gains action authority.
"""

from agents.core.memory._episode_operations import (
    EpisodeAuditEvent,
    EpisodeDerivativeTrace,
    EpisodeMatch,
    EpisodeMutation,
    EpisodePartition,
    EpisodeQuery,
    consolidate_episode,
    correct_episode,
    merge_episodes,
    migrate_manual_episode_v0,
    open_episode,
    settle_episode,
    split_episode,
    tombstone_sources,
    trace_source_derivatives,
)
from agents.core.memory._episode_retrieval import retrieve_episodes
from agents.core.memory._episode_values import (
    EpisodeAssertion,
    EpisodeAssertionKind,
    EpisodeOperation,
    EpisodeRecord,
    EpisodeReference,
    EpisodeReferenceRole,
    EpisodeState,
)

__all__ = [
    "EpisodeAssertion",
    "EpisodeAssertionKind",
    "EpisodeAuditEvent",
    "EpisodeDerivativeTrace",
    "EpisodeMatch",
    "EpisodeMutation",
    "EpisodeOperation",
    "EpisodePartition",
    "EpisodeQuery",
    "EpisodeRecord",
    "EpisodeReference",
    "EpisodeReferenceRole",
    "EpisodeState",
    "consolidate_episode",
    "correct_episode",
    "merge_episodes",
    "migrate_manual_episode_v0",
    "open_episode",
    "retrieve_episodes",
    "settle_episode",
    "split_episode",
    "tombstone_sources",
    "trace_source_derivatives",
]
