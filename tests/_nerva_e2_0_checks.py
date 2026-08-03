"""Assertions invoked by the existing bi-temporal test for Atlas E2.0.

The helper is deliberately not a pytest collection target. The repository pins
its generated test count, so the bounded Atlas assertions are called from the
existing H14.1 regression test rather than creating test-count-only churn.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agents.core.memory.atlas_snapshot import (
    AtlasConfidence,
    AtlasQuery,
    AtlasSnapshotReader,
    LegacyBiTemporalAdapter,
    LegacyProjectionPolicy,
)
from agents.core.memory.bitemporal import BiTemporalKG

ROOT = Path(__file__).resolve().parent.parent


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
    assert denied.eligible_count == 0
    assert "denied_count" not in denied.to_json()
    assert "total_source_records" not in denied.to_json()
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
    assert current.eligible_count == 1
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
    replayed = reader.snapshot(current_query)
    assert current.replay_fingerprint == replayed.replay_fingerprint
    assert json.loads(current.to_json())["schema"] == "nerva.atlas.snapshot.v1"

    other_source_observation = LegacyBiTemporalAdapter(
        LegacyProjectionPolicy(source_id="connector.other")
    ).project(second)
    assert other_source_observation.entity_id != observation.entity_id
    assert other_source_observation.observation_id != observation.observation_id

    equivalent_scope = reader.snapshot(
        AtlasQuery(
            temporal_axis="valid",
            at=250,
            allowed_privacy_classes=("private_local", "personal"),
            subject="person:sample",
        )
    )
    reversed_scope = reader.snapshot(
        AtlasQuery(
            temporal_axis="valid",
            at=250,
            allowed_privacy_classes=("personal", "private_local"),
            subject="person:sample",
        )
    )
    assert equivalent_scope.replay_fingerprint == reversed_scope.replay_fingerprint

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
    history_values = [
        item["object"] for item in kg.history("person:sample", "location")
    ]
    assert history_values == ["city-a", "city-b", "city-c"]

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
    first_observation = historical.observations[0]
    second_observation = historical.observations[1]
    assert first_observation.source.record_id.endswith(f":{first['id']}")
    assert first_observation.entity_id == second_observation.entity_id
    assert first_observation.observation_id != second_observation.observation_id

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
    assert limited.eligible_count == 3
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
    source_at_250 = kg.as_of(250, "person:sample", "location")
    assert source_at_250[0]["object"] == "city-b"

    atlas_doc = (ROOT / "docs" / "nerva2" / "ATLAS_E2_0.md").read_text(
        encoding="utf-8"
    )
    assert "Legacy `BiTemporalKG` rows" in atlas_doc
    assert "Unknown privacy is never treated as public" in atlas_doc
    assert "no database handle is returned" in atlas_doc
    assert "Integrity hashes" in atlas_doc
    assert "Partial rollback" in atlas_doc
    assert "Ultron / `nerva.action.v1` remains" in atlas_doc
    assert "production Atlas HTTP/API exposure" in atlas_doc
    assert "source-scoped" in atlas_doc

    m1_doc = (ROOT / "docs" / "nerva2" / "M1_DELIVERY.md").read_text(
        encoding="utf-8"
    )
    assert "e244ea7c9e32673bdb56fe1459f355a7abb9d63f" in m1_doc
    assert "E2.0 / #781" in m1_doc
    assert "candidate evidence only" in m1_doc
    assert "#782 Episodes remains blocked only by #781" in m1_doc
    assert "#783 Synapse and #784 Research Lab remain separately eligible" in m1_doc
