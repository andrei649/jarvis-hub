"""H33.1 allowlisted digital adapters and source ownership."""

from __future__ import annotations

import json

import pytest

from agents.core.ambient.adapters import (
    LEGACY_SOURCE_OWNERSHIP,
    SourceOwnershipManager,
    digital_signal_event,
)
from agents.core.ambient.contracts import MonitorDefinition, MonitorPredicate
from agents.core.ambient.engine import AmbientEngine
from agents.core.ambient.registry import MonitorRegistry
from agents.core.ambient.store import AmbientStore
from agents.core.autonomy.observer import Remediation, Severity, Signal


def test_digital_signal_projection_drops_detail_host_and_remediation_payload():
    signal = Signal(
        key="service.backup",
        healthy=False,
        severity=Severity.CRITICAL,
        detail="backup failed on secret-host.example",
        value=1,
        remediation=Remediation(
            kind="restart_service",
            title="Restart secret service?",
            payload={"host": "secret-host.example", "cmd": "danger"},
        ),
    )
    event = digital_signal_event(signal, observed_at=1_000, sequence=3)
    encoded = json.dumps(event.to_dict()).lower()
    assert event.attributes == (("healthy", False), ("severity", "critical"), ("value", 1.0))
    assert not any(term in encoded for term in ("secret-host", "restart", "danger", "detail", "remediation"))


def test_source_ownership_cutover_is_atomic_and_rollback_preserves_watermark(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_000.0)
    manager = SourceOwnershipManager(store)
    calls: list[str] = []

    claimed = manager.claim(
        "digital.backups",
        watermark="cursor-42",
        health_check=lambda: True,
        disable_legacy=lambda: calls.append("disable"),
    )
    assert claimed["status"] == "claimed"
    assert calls == ["disable"]
    assert store.ownership("digital.backups")["watermark"] == "cursor-42"

    rolled_back = manager.rollback(
        "digital.backups",
        resume_legacy=lambda watermark: calls.append(f"resume:{watermark}"),
    )
    assert rolled_back["status"] == "legacy"
    assert calls[-1] == "resume:cursor-42"

    with pytest.raises(RuntimeError, match="health_check_failed"):
        manager.claim(
            "digital.calendar",
            watermark="cursor-1",
            health_check=lambda: False,
            disable_legacy=lambda: calls.append("must-not-disable"),
        )
    assert "must-not-disable" not in calls
    assert {row["legacy_owner"] for row in LEGACY_SOURCE_OWNERSHIP} == {
        "ProactiveObserver",
        "EventWatcher",
    }
    store.close()
