"""H30 owner-live cases against a real Home Assistant.

Skipped everywhere except a run that has deliberately pointed `JARVIS_HA_URL` at a
real Home Assistant and set `JARVIS_H30_HA_LIVE=1` — the scheduled reality lane's
`home-assistant-live` job, or an owner running it against their own box.

This is the tier the hermetic pack cannot reach. `house_reality.py` injects a
simulator in place of the REST/WebSocket transports, and
`tests/test_h30_ha_live_probe.py` drives a stand-in we wrote ourselves, so both
agree with our own idea of Home Assistant's payload shapes. Only a real HA can
disagree with us — which is the whole point of running it.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.env_config import env_flag  # noqa: E402
from agents.core.observability.house_reality import (  # noqa: E402
    _probe_owner_live_actuation,
    _probe_owner_live_read,
)

pytestmark = pytest.mark.skipif(
    not env_flag("JARVIS_H30_HA_LIVE"),
    reason="owner-live Home Assistant opt-in (JARVIS_H30_HA_LIVE) is not set",
)


def _require_config() -> None:
    missing = [
        name
        for name in ("JARVIS_HA_URL", "JARVIS_HA_TOKEN_REF", "JARVIS_H30_HA_TOKEN")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        pytest.fail(f"owner-live run is missing configuration: {', '.join(missing)}")


def test_live_read_against_real_home_assistant():
    _require_config()

    result = asyncio.run(_probe_owner_live_read())

    assert result["passed"] is True, result
    meta = result["metadata"]
    assert meta["status"] == "live"
    # A demo-configured HA exposes many entities; an empty read means the token
    # authenticated but the payload was not what the adapter expects.
    assert meta["entities"] > 0, meta


def test_live_actuation_against_real_home_assistant():
    _require_config()

    result = asyncio.run(_probe_owner_live_actuation())

    assert result["passed"] is True, result
    meta = result["metadata"]
    assert meta["observed_after_apply"] == "on", meta
    assert meta["observed_after_rollback"] == "off", meta
    assert meta["lock_refused_by_allowlist"] is True, meta


def test_area_projection_is_reported_honestly():
    """Records whether real HA's /api/states carries the area_id the adapter reads.

    `_normalize_entity` derives `HouseArea` from `attributes.area_id`. Home
    Assistant's REST `/api/states` is entity-state oriented and does not
    necessarily carry registry area assignments, so this asserts only that the
    read succeeded and prints what came back. If areas are consistently 0 against
    a real HA with areas configured, the device→room projection §N asks for is
    reading from the wrong source, and that is a finding — not a test failure to
    paper over here.
    """
    _require_config()

    result = asyncio.run(_probe_owner_live_read())

    assert result["passed"] is True, result
    meta = result["metadata"]
    print(f"live HA read: entities={meta['entities']} areas={meta['areas']}")
