"""H31.5 — bounded, deterministic temporal retrieval over redacted camera events."""

from __future__ import annotations

import json
from datetime import UTC

import pytest

from agents.core.cameras.models import CameraEvent
from agents.core.cameras.retrieval import (
    CameraEventRetrieval,
    CameraFilter,
    CameraSearchError,
)
from agents.core.cameras.vault import CameraVaultError


class _Index:
    def __init__(self, events=(), *, error: Exception | None = None) -> None:
        self.events = tuple(events)
        self.error = error
        self.calls: list[tuple[float | None, int]] = []

    def list_events(self, *, now=None, limit=100):
        self.calls.append((now, limit))
        if self.error is not None:
            raise self.error
        return self.events[:limit]


def _event(
    event_id: str,
    *,
    occurred_at: float,
    label: str = "person",
    camera_id: str = "front-door",
    zone: str | None = "porch",
    room_id: str | None = "entry",
    description: str | None = None,
) -> CameraEvent:
    return CameraEvent(
        event_id=event_id,
        camera_id=camera_id,
        label=label,
        occurred_at=occurred_at,
        confidence=0.9,
        zone=zone,
        room_id=room_id,
        description=description,
        description_provenance="local_vlm_on_demand" if description else None,
    )


def _retrieval(events=(), *, now: float = 200_000.0, error=None) -> CameraEventRetrieval:
    return CameraEventRetrieval(
        index=_Index(events, error=error),
        clock=lambda: now,
        timezone=UTC,
    )


def test_structured_query_filters_time_label_camera_zone_and_room_deterministically():
    events = (
        _event("latest", occurred_at=190.0, label="package"),
        _event("match", occurred_at=150.0, label="person"),
        _event("wrong-camera", occurred_at=140.0, camera_id="garage"),
        _event("too-old", occurred_at=99.0),
    )
    retrieval = _retrieval(events, now=200.0)
    result = retrieval.query(
        CameraFilter(
            after=100.0,
            before=180.0,
            label="person",
            camera_id="front-door",
            zone="porch",
            room_id="entry",
            limit=10,
        )
    )
    assert result.status == "ok"
    assert [event.event_id for event in result.events] == ["match"]
    assert result.interpretation == {
        "after": 100.0,
        "before": 180.0,
        "label": "person",
        "camera_id": "front-door",
        "zone": "porch",
        "room_id": "entry",
    }


def test_query_sorts_newest_first_applies_limit_and_reports_empty_honestly():
    events = tuple(_event(f"event-{number}", occurred_at=float(number)) for number in range(5))
    retrieval = _retrieval(reversed(events), now=10.0)
    result = retrieval.query(CameraFilter(limit=2))
    assert [event.occurred_at for event in result.events] == [4.0, 3.0]
    assert retrieval.query(CameraFilter(label="animal")).status == "empty"


def test_natural_language_yesterday_and_romanian_ieri_map_courier_to_anonymous_person():
    now = 3 * 86_400.0 + 12 * 3600.0
    yesterday = 2 * 86_400.0 + 10 * 3600.0
    today = 3 * 86_400.0 + 8 * 3600.0
    retrieval = _retrieval(
        (
            _event("yesterday", occurred_at=yesterday),
            _event("today", occurred_at=today),
        ),
        now=now,
    )
    english = retrieval.search("When did the courier come yesterday?")
    romanian = retrieval.search("Cand a venit curierul ieri?")
    assert [event.event_id for event in english.events] == ["yesterday"]
    assert [event.event_id for event in romanian.events] == ["yesterday"]
    assert english.interpretation["label"] == "person"
    assert "query" not in english.interpretation


def test_last_n_hours_and_label_synonyms_are_bounded_and_local():
    now = 100_000.0
    retrieval = _retrieval(
        (
            _event("recent", occurred_at=now - 60, label="package"),
            _event("old", occurred_at=now - 3 * 3600, label="package"),
            _event("vehicle", occurred_at=now - 30, label="vehicle"),
        ),
        now=now,
    )
    result = retrieval.search("show deliveries from the last 2 hours")
    assert [event.event_id for event in result.events] == ["recent"]
    assert result.interpretation["label"] == "package"
    assert result.interpretation["after"] == now - 2 * 3600


@pytest.mark.parametrize(
    "query",
    (
        "today yesterday",
        "person and vehicle today",
        "last 2 hours yesterday",
    ),
)
def test_ambiguous_time_or_class_returns_no_events_without_guessing(query: str):
    result = _retrieval((_event("event", occurred_at=1.0),)).search(query)
    assert result.status == "ambiguous"
    assert result.events == ()
    assert result.reason == "query_ambiguous"


def test_empty_and_unbounded_queries_are_refused_before_index_access():
    index = _Index((_event("event", occurred_at=1.0),))
    retrieval = CameraEventRetrieval(index=index, clock=lambda: 10.0, timezone=UTC)
    assert retrieval.search("   ").status == "empty"
    assert index.calls == []
    with pytest.raises(CameraSearchError, match="query_too_long"):
        retrieval.search("x" * 257)
    with pytest.raises(ValueError, match="limit"):
        retrieval.query(CameraFilter(limit=101))


def test_vault_failure_is_a_stable_degraded_result_without_path_or_secret_leak():
    result = _retrieval(error=CameraVaultError("C:/private/camera-vault/index.enc secret")).search(
        "person today"
    )
    assert result.status == "degraded"
    assert result.reason == "camera_index_unavailable"
    encoded = json.dumps(result.to_public()).lower()
    assert all(term not in encoded for term in ("private", "index.enc", "secret", "vault"))


def test_public_projection_is_metadata_only_and_has_no_snapshot_or_internal_reference_fields():
    result = _retrieval(
        (
            _event(
                "event-1",
                occurred_at=100.0,
                description="An anonymous person left a package.",
            ),
        ),
        now=100.0,
    ).query(CameraFilter())
    public = result.to_public()
    encoded = json.dumps(public).lower()
    assert public["events"][0]["anonymous"] is True
    assert all(
        term not in encoded
        for term in ("snapshot", "frame", "clip", "vault_id", ".blob", "rtsp", "credential")
    )
