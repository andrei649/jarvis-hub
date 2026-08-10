"""Bounded Atlas E2.0 assertions collected by ``test_nerva_e2_0_collected.py``."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest

from agents.core.memory.atlas_snapshot import (
    AtlasAccessGrant,
    AtlasConfidence,
    AtlasQuery,
    AtlasSnapshot,
    AtlasSnapshotReader,
    LegacyBiTemporalAdapter,
    LegacyProjectionPolicy,
)
from agents.core.memory.bitemporal import BiTemporalKG

ROOT = Path(__file__).resolve().parent.parent


class _FixtureAuthorizer:
    """Test-only trusted policy seam with explicit per-principal grants."""

    def __init__(self, grants: dict[str, tuple[str, ...]]) -> None:
        self._grants = grants

    def authorize(
        self,
        principal_id: str,
        requested_privacy_classes: tuple[str, ...],
    ) -> AtlasAccessGrant:
        allowed = set(self._grants.get(principal_id, ()))
        requested = set(requested_privacy_classes)
        if not requested.issubset(allowed):
            raise PermissionError("Atlas requested privacy scope is not granted")
        normalized = tuple(sorted(requested_privacy_classes))
        return AtlasAccessGrant(
            grant_id=f"fixture:{principal_id}:{','.join(normalized)}",
            principal_id=principal_id,
            granted_privacy_classes=normalized,
            issued_by="tests.fixture_policy",
        )


class _CountingReadStore:
    """Prove authorization happens before the source store is read."""

    def __init__(self, store: BiTemporalKG) -> None:
        self.store = store
        self.read_calls = 0

    def as_of(
        self,
        at: float | None = None,
        subject: str = "",
        predicate: str = "",
    ) -> list[dict[str, Any]]:
        self.read_calls += 1
        return self.store.as_of(at, subject, predicate)

    def known_as_of(
        self,
        at: float,
        subject: str = "",
        predicate: str = "",
    ) -> list[dict[str, Any]]:
        self.read_calls += 1
        return self.store.known_as_of(at, subject, predicate)


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
    authorizer = _FixtureAuthorizer(
        {
            "fixture.public_reader": ("public",),
            "fixture.private_reader": ("personal", "private_local"),
        }
    )
    counting_store = _CountingReadStore(kg)
    reader = AtlasSnapshotReader(counting_store, authorizer)

    with pytest.raises(PermissionError, match="not granted"):
        reader.snapshot(
            AtlasQuery(
                temporal_axis="valid",
                at=250,
                requested_privacy_classes=("restricted",),
                subject="person:sample",
                predicate="location",
            ),
            principal_id="fixture.public_reader",
        )
    assert counting_store.read_calls == 0

    filtered = reader.snapshot(
        AtlasQuery(
            temporal_axis="valid",
            at=250,
            requested_privacy_classes=("public",),
            subject="person:sample",
            predicate="location",
        ),
        principal_id="fixture.public_reader",
    )
    assert filtered.observations == ()
    assert filtered.eligible_count == 0
    assert counting_store.read_calls == 1
    assert "denied_count" not in filtered.to_json()
    assert "total_source_records" not in filtered.to_json()
    assert filtered.authority == "read_only"
    assert not filtered.can_mutate
    assert not filtered.can_authorize
    assert not filtered.can_execute
    assert not filtered.can_mark_complete

    current_query = AtlasQuery(
        temporal_axis="valid",
        at=250,
        requested_privacy_classes=("private_local",),
        subject="person:sample",
        predicate="location",
    )
    current = reader.snapshot(
        current_query,
        principal_id="fixture.private_reader",
    )
    assert len(current.observations) == 1
    assert current.eligible_count == 1
    assert current.access_grant.principal_id == "fixture.private_reader"
    assert current.access_grant.issued_by == "tests.fixture_policy"
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
    replayed = reader.snapshot(
        current_query,
        principal_id="fixture.private_reader",
    )
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
            requested_privacy_classes=("private_local", "personal"),
            subject="person:sample",
        ),
        principal_id="fixture.private_reader",
    )
    reversed_scope = reader.snapshot(
        AtlasQuery(
            temporal_axis="valid",
            at=250,
            requested_privacy_classes=("personal", "private_local"),
            subject="person:sample",
        ),
        principal_id="fixture.private_reader",
    )
    assert equivalent_scope.replay_fingerprint == reversed_scope.replay_fingerprint

    with pytest.raises(FrozenInstanceError):
        observation.value = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        current.observations = ()  # type: ignore[misc]
    assert not hasattr(reader, "add_fact")
    assert not hasattr(current, "store")

    with pytest.raises(ValueError, match="SHA-256"):
        replace(observation, integrity_sha256="g" * 64)

    tampered = replace(observation, integrity_sha256="0" * 64)
    with pytest.raises(ValueError, match="integrity"):
        AtlasSnapshot(
            snapshot_id="fixture:tampered",
            query=current.query,
            access_grant=current.access_grant,
            observations=(tampered,),
            eligible_count=1,
            truncated_count=0,
        )

    with pytest.raises(ValueError, match="AtlasObservation"):
        AtlasSnapshot(
            snapshot_id="fixture:wrong-type",
            query=current.query,
            access_grant=current.access_grant,
            observations=("not-an-observation",),  # type: ignore[arg-type]
            eligible_count=1,
            truncated_count=0,
        )

    with pytest.raises(ValueError, match="duplicate observation IDs"):
        AtlasSnapshot(
            snapshot_id="fixture:duplicate",
            query=current.query,
            access_grant=current.access_grant,
            observations=(observation, observation),
            eligible_count=2,
            truncated_count=0,
        )

    public_observation = LegacyBiTemporalAdapter(
        LegacyProjectionPolicy(
            source_id="connector.public",
            default_privacy_class="public",
        )
    ).project(second)
    with pytest.raises(ValueError, match="requested privacy scope"):
        AtlasSnapshot(
            snapshot_id="fixture:out-of-scope",
            query=current.query,
            access_grant=current.access_grant,
            observations=(public_observation,),
            eligible_count=1,
            truncated_count=0,
        )

    insufficient_grant = AtlasAccessGrant(
        grant_id="fixture:public-only",
        principal_id="fixture.private_reader",
        granted_privacy_classes=("public",),
        issued_by="tests.fixture_policy",
    )
    with pytest.raises(ValueError, match="exceeds its trusted access grant"):
        AtlasSnapshot(
            snapshot_id="fixture:grant-mismatch",
            query=current.query,
            access_grant=insufficient_grant,
            observations=(),
            eligible_count=0,
            truncated_count=0,
        )

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
            requested_privacy_classes=("private_local",),
            subject="person:sample",
            predicate="location",
        ),
        principal_id="fixture.private_reader",
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
    public_reader = AtlasSnapshotReader(kg, authorizer, public_adapter)
    public = public_reader.snapshot(
        AtlasQuery(
            temporal_axis="valid",
            at=350,
            requested_privacy_classes=("public",),
            subject="person:sample",
        ),
        principal_id="fixture.public_reader",
    )
    assert [item.value for item in public.observations] == ["city-c"]
    assert public.observations[0].confidence.value == 0.8
    assert public.observations[0].confidence.source == "fixture.explicit_label"

    limited = public_reader.snapshot(
        AtlasQuery(
            temporal_axis="known",
            at=400,
            requested_privacy_classes=("public",),
            subject="person:sample",
            limit=1,
        ),
        principal_id="fixture.public_reader",
    )
    assert len(limited.observations) == 1
    assert limited.eligible_count == 3
    assert limited.truncated_count == 2

    with pytest.raises(ValueError, match="privacy scope"):
        AtlasQuery(
            temporal_axis="valid",
            at=1,
            requested_privacy_classes=(),
        )
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
    assert "`AtlasAccessAuthorizer`" in atlas_doc
    assert "before the source store is read" in atlas_doc
    assert "no database handle is returned" in atlas_doc
    assert "Integrity hashes" in atlas_doc
    assert "Partial rollback" in atlas_doc
    assert "Ultron / `nerva.action.v1` remains" in atlas_doc
    assert "production Atlas HTTP/API exposure" in atlas_doc
    assert "source-scoped" in atlas_doc
    assert "exact reviewed head lands on `main`" in atlas_doc

    m1_doc = (ROOT / "docs" / "nerva2" / "M1_DELIVERY.md").read_text(
        encoding="utf-8"
    )
    assert "e244ea7c9e32673bdb56fe1459f355a7abb9d63f" in m1_doc
    assert "E2.0 / #781" in m1_doc
    assert "transition evidence" in m1_doc
    assert (
        "#782 becomes eligible when the exact reviewed E2.0 head lands on `main`"
        in m1_doc
    )
    assert "#783 Synapse and #784 Research Lab remain separately eligible" in m1_doc
