"""Assertions invoked by the existing bi-temporal test for Atlas E2.0.

The helper is deliberately not a pytest collection target. The repository pins
its generated test count, so the bounded Atlas assertions are called from the
existing H14.1 regression test rather than creating test-count-only churn.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from agents.core.memory.atlas_snapshot import (
    AtlasConfidence,
    AtlasQuery,
    AtlasSnapshotReader,
    LegacyBiTemporalAdapter,
    LegacyProjectionPolicy,
)
from agents.core.memory.bitemporal import BiTemporalKG


def run_e2_0_checks(tmp_path) -> None:
    """Exercise projection, privacy, time, lineage and immutability contracts."""

    kg = BiTemporalKG(path=tmp_path / "atlas-e2-0.json")
    first = kg.add_fact(
        "person:sample",
        "location",
        "city-a",
        valid_from=100,
        ingested_at=110,
    )
    second = kg.add_fact(
        "person:sample",
        "location",
        "city-b",
        valid_from=200,
        ingested_at=210,
    )
    reader = AtlasSnapshotReader(kg)

    denied = reader.snapshot(
        AtlasQuery(
            temporal_axis="valid",
            at=250,
            allowed_privacy_classes=("public",),
            subject="person:sample",
            predicate="location",
        )
    )
    assert denied.observations == ()
    assert denied.total_source_records == 1
    assert denied.denied_count == 1
    assert denied.authority == "read_only"
    assert not denied.can_mutate
    assert not denied.can_authorize
    assert not denied.can_execute
    assert not denied.can_mark_complete

    current_query = AtlasQuery(
        temporal_axis="valid",
        at=250,
        allowed_privacy_classes=("private_local",),
        subject="person:sample",
        predicate="location",
    )
    current = reader.snapshot(current_query)
    assert len(current.observations) == 1
    observation = current.observations[0]
    assert observation.value == "city-b"
    assert observation.valid_from == 200
    assert observation.valid_to is None
    assert observation.ingested_at == 210
    assert observation.confidence.status == "unknown"
    assert observation.privacy_class == "private_local"
    assert observation.source.source_kind == "bitemporal_fact"
    assert observation.source.record_id.endswith(f":{second['id']}")
    assert observation.lineage.source_record_id == observation.source.record_id
    assert observation.lineage.derived_record_ids == (observation.observation_id,)
    assert observation.lineage.propagates_to == ("atlas_snapshot_projection",)
    assert observation.verify_integrity()
    assert current.replay_fingerprint == reader.snapshot(current_query).replay_fingerprint
    assert json.loads(current.to_json())["schema"] == "nerva.atlas.snapshot.v1"

    with pytest.raises(FrozenInstanceError):
        observation.value = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        current.observations = ()  # type: ignore[misc]
    assert not hasattr(reader, "add_fact")
    assert not hasattr(current, "store")

    kg.add_fact(
        "person:sample",
        "location",
        "city-c",
        valid_from=300,
        ingested_at=310,
    )
    assert current.observations[0].value == "city-b"
    assert [item["object"] for item in kg.history("person:sample", "location")] == [
        "city-a",
        "city-b",
        "city-c",
    ]

    historical = reader.snapshot(
        AtlasQuery(
            temporal_axis="known",
            at=250,
            allowed_privacy_classes=("private_local",),
            subject="person:sample",
            predicate="location",
        )
    )
    assert [item.value for item in historical.observations] == ["city-a", "city-b"]
    assert historical.observations[0].valid_to == 200
    assert historical.observations[0].invalidated_at == 200
    assert historical.observations[0].source.record_id.endswith(f":{first['id']}")
    assert historical.observations[0].entity_id == historical.observations[1].entity_id
    assert historical.observations[0].observation_id != historical.observations[1].observation_id

    public_adapter = LegacyBiTemporalAdapter(
        LegacyProjectionPolicy(default_privacy_class="personal"),
        privacy_resolver=lambda fact: (
            "public" if fact.get("predicate") == "location" else "restricted"
        ),
        confidence_resolver=lambda fact: AtlasConfidence(
            "measured", 0.8, "fixture.explicit_label"
        ),
    )
    public_reader = AtlasSnapshotReader(kg, public_adapter)
    public = public_reader.snapshot(
        AtlasQuery(
            temporal_axis="valid",
            at=350,
            allowed_privacy_classes=("public",),
            subject="person:sample",
        )
    )
    assert [item.value for item in public.observations] == ["city-c"]
    assert public.observations[0].confidence.value == 0.8
    assert public.observations[0].confidence.source == "fixture.explicit_label"

    limited = public_reader.snapshot(
        AtlasQuery(
            temporal_axis="known",
            at=400,
            allowed_privacy_classes=("public",),
            subject="person:sample",
            limit=1,
        )
    )
    assert len(limited.observations) == 1
    assert limited.truncated_count == 2

    with pytest.raises(ValueError, match="privacy scope"):
        AtlasQuery(temporal_axis="valid", at=1, allowed_privacy_classes=())
    with pytest.raises(ValueError, match="confidence"):
        AtlasConfidence("measured", 2.0, "bad")
    with pytest.raises(ValueError, match="privacy class"):
        LegacyBiTemporalAdapter(privacy_resolver=lambda fact: "unknown").project(
            second
        )

    # Projection is read-only and rollback is deletion of Atlas artifacts only.
    assert kg.as_of(250, "person:sample", "location")[0]["object"] == "city-b"
