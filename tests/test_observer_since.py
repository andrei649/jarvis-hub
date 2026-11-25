"""Phase B (B2): Observer.status() says since when each unhealthy key has been unhealthy.

The HUD's verdict ("down since 10:40") reads `unhealthy[].since` from GET /autonomy/observer.
It is recorded when a key flips healthy -> unhealthy, never refreshed by a later unhealthy
sample, and dropped on recovery. A key with no recorded flip carries no `since` at all.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy import ProactiveObserver, Severity, Signal  # noqa: E402


class _Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


def _down(key="service.docker", detail="docker down"):
    return Signal(key, healthy=False, severity=Severity.CRITICAL, detail=detail)


def _up(key="service.docker"):
    return Signal(key, healthy=True, detail="up")


def _observer(clock):
    return ProactiveObserver(worker=None, probes=[], clock=clock)


def test_since_is_recorded_when_the_key_flips_unhealthy():
    clock = _Clock(datetime(2026, 11, 23, 10, 40, 5, tzinfo=timezone.utc))
    obs = _observer(clock)
    obs.evaluate([_down()])
    row = obs.status()["unhealthy"][0]
    assert row["key"] == "service.docker"
    assert row["since"] == "2026-11-23T10:40:05+00:00"
    assert datetime.fromisoformat(row["since"]).tzinfo is not None


def test_since_is_not_refreshed_by_later_unhealthy_samples():
    clock = _Clock(datetime(2026, 11, 23, 10, 40, tzinfo=timezone.utc))
    obs = _observer(clock)
    obs.evaluate([_down()])
    clock.advance(minutes=30)
    obs.evaluate([_down(detail="still down")])
    row = obs.status()["unhealthy"][0]
    assert row["since"] == "2026-11-23T10:40:00+00:00"
    assert row["detail"] == "still down"


def test_since_is_dropped_on_recovery_and_set_afresh_on_the_next_flip():
    clock = _Clock(datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc))
    obs = _observer(clock)
    obs.evaluate([_down()])
    clock.advance(minutes=10)
    obs.evaluate([_up()])
    assert obs.status()["unhealthy"] == []
    clock.advance(minutes=5)
    obs.evaluate([_down()])
    assert obs.status()["unhealthy"][0]["since"] == "2026-11-23T10:15:00+00:00"


def test_each_unhealthy_key_has_its_own_since():
    clock = _Clock(datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc))
    obs = _observer(clock)
    obs.evaluate([_down("service.qdrant", "qdrant down")])
    clock.advance(hours=1)
    obs.evaluate([_down("service.qdrant", "qdrant down"), _down("service.neo4j", "neo4j down")])
    since = {u["key"]: u["since"] for u in obs.status()["unhealthy"]}
    assert since == {"service.qdrant": "2026-11-23T09:00:00+00:00", "service.neo4j": "2026-11-23T10:00:00+00:00"}


def test_since_is_utc_even_when_the_clock_is_not():
    eet = timezone(timedelta(hours=2))
    obs = _observer(_Clock(datetime(2026, 11, 23, 12, 0, tzinfo=eet)))
    obs.evaluate([_down()])
    assert obs.status()["unhealthy"][0]["since"] == "2026-11-23T10:00:00+00:00"


def test_default_clock_stamps_a_parseable_utc_time():
    obs = ProactiveObserver(worker=None, probes=[])
    obs.evaluate([_down()])
    since = datetime.fromisoformat(obs.status()["unhealthy"][0]["since"])
    assert abs((datetime.now(timezone.utc) - since).total_seconds()) < 60


def test_a_key_with_no_recorded_flip_carries_no_since():
    obs = _observer(_Clock(datetime(2026, 11, 23, tzinfo=timezone.utc)))
    obs.evaluate([_down()])
    obs._since.clear()   # a state the observer cannot reach by itself; the field must not be invented
    assert "since" not in obs.status()["unhealthy"][0]


# ── route level: GET /autonomy/observer carries `since` to the HUD ────────────────────────────
def test_observer_route_returns_since_for_each_unhealthy_key():
    import pytest
    from fastapi.testclient import TestClient

    import agents.web as web

    headers = {"X-Admin-Token": "test-secret"}
    old_token = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    try:
        with TestClient(web.app) as client:
            observer = web.orch.observer
            if observer is None:
                pytest.skip("observer not initialised in this app")
            observer._since.clear()
            observer.evaluate([_down("service.route_since", "route_since down")])
            body = client.get("/autonomy/observer", headers=headers).json()
            row = next(r for r in body["unhealthy"] if r["key"] == "service.route_since")
            since = datetime.fromisoformat(row["since"])
            assert since.tzinfo is not None
            assert abs((datetime.now(timezone.utc) - since).total_seconds()) < 60
            observer.evaluate([_up("service.route_since")])
    finally:
        web.ADMIN_TOKEN = old_token
