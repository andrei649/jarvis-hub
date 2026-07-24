"""Tests for H34.2 — Desk presence + away notify.

Three contracts:
  1. OwnerPresence is a fail-calm desk-presence tracker: unknown/stale → not away.
  2. AwayNotifier fans a decision card out to the escalation channels ONLY when
     the owner is away, excluding the base (Telegram) channel, best-effort.
  3. The presence route + swarm feed surface the state; the coordinator wires the
     away-notifier so escalation rides inside the worker's single ≤4/day push.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy.escalation import AwayNotifier, EscalationRouter
from agents.core.autonomy.presence import (
    AWAY,
    IDLE,
    PRESENT,
    UNKNOWN,
    OwnerPresence,
    normalize_state,
)

# ── OwnerPresence — the pure tracker ──────────────────────────────────────────

def test_default_is_unknown_and_not_away():
    p = OwnerPresence(clock=lambda: 100.0)
    snap = p.snapshot()
    assert snap.state == UNKNOWN
    assert snap.away is False and p.is_away() is False
    assert snap.ever_reported is False
    # never-reported reads as stale (we simply don't know)
    assert snap.stale is True


def test_away_signal_marks_away():
    now = [1000.0]
    p = OwnerPresence(clock=lambda: now[0])
    snap = p.update(AWAY, source="win-daemon")
    assert snap.state == AWAY and snap.away is True
    assert p.is_away() is True
    assert snap.source == "win-daemon" and snap.ever_reported is True


def test_present_signal_clears_away():
    now = [1000.0]
    p = OwnerPresence(clock=lambda: now[0])
    p.update(AWAY)
    assert p.is_away() is True
    p.update(PRESENT)
    assert p.is_away() is False
    assert p.snapshot().state == PRESENT


def test_state_aliases_normalized():
    assert normalize_state("locked") == AWAY
    assert normalize_state("Active") == PRESENT
    assert normalize_state("INACTIVE") == IDLE
    assert normalize_state("offline") == AWAY
    p = OwnerPresence(clock=lambda: 5.0)
    assert p.update("locked").state == AWAY
    assert p.update("active").state == PRESENT


def test_bad_state_rejected():
    with pytest.raises(ValueError):
        normalize_state("dancing")
    with pytest.raises(ValueError):
        normalize_state(None)
    p = OwnerPresence(clock=lambda: 0.0)
    with pytest.raises(ValueError):
        p.update("teleporting")


def test_stale_signal_is_not_away():
    now = [0.0]
    p = OwnerPresence(ttl_seconds=300.0, clock=lambda: now[0])
    p.update(AWAY)
    now[0] = 299.0
    assert p.is_away() is True and p.snapshot().stale is False
    now[0] = 301.0  # past the TTL — the daemon has gone quiet
    snap = p.snapshot()
    assert snap.stale is True and snap.away is False
    assert p.is_away() is False


def test_idle_not_away_by_default_but_configurable():
    now = [0.0]
    p = OwnerPresence(clock=lambda: now[0])
    p.update(IDLE, idle_seconds=120)
    assert p.is_away() is False  # idle ≠ away by default

    p2 = OwnerPresence(idle_is_away=True, clock=lambda: now[0])
    p2.update(IDLE, idle_seconds=120)
    assert p2.is_away() is True


def test_since_only_moves_on_state_change():
    now = [10.0]
    p = OwnerPresence(clock=lambda: now[0])
    s1 = p.update(AWAY)
    now[0] = 20.0
    s2 = p.update(AWAY)          # same state → since unchanged, updated_at moves
    assert s2.since == s1.since == 10.0
    assert s2.updated_at == 20.0
    now[0] = 30.0
    s3 = p.update(PRESENT)       # state change → since resets
    assert s3.since == 30.0


def test_snapshot_dict_shape():
    p = OwnerPresence(clock=lambda: 42.0)
    d = p.update(AWAY, source="x", idle_seconds=5).to_dict()
    assert set(d) == {
        "state", "source", "since", "updated_at", "idle_seconds",
        "ttl_seconds", "stale", "away", "ever_reported",
    }
    assert d["idle_seconds"] == 5.0 and d["away"] is True


# ── AwayNotifier — presence-gated escalation ──────────────────────────────────

class _FakeChannel:
    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []

    async def send(self, message, **kwargs):
        self.sent.append(message)
        return self.ok


class _Presence:
    def __init__(self, away):
        self._away = away

    def is_away(self):
        return self._away


def _base_factory():
    calls = []

    async def base(task):
        calls.append(task)
        return True

    return base, calls


def _router_factory(channels, allow=None):
    return lambda: EscalationRouter(channels, allow=allow)


async def test_present_owner_skips_escalation():
    chans = {"telegram": _FakeChannel(), "whatsapp": _FakeChannel()}
    base, calls = _base_factory()
    notifier = AwayNotifier(base, _Presence(False), _router_factory(chans), exclude={"telegram"})
    ok = await notifier({"id": 1, "title": "t"})
    assert ok is True
    assert len(calls) == 1                       # base ran
    assert chans["whatsapp"].sent == []          # no escalation while present
    assert chans["telegram"].sent == []


async def test_away_owner_escalates_excluding_base_channel():
    chans = {"telegram": _FakeChannel(), "whatsapp": _FakeChannel(), "signal": _FakeChannel()}
    base, calls = _base_factory()
    notifier = AwayNotifier(base, _Presence(True), _router_factory(chans), exclude={"telegram"})
    ok = await notifier({"id": 7, "title": "Send report", "agent": "pepper", "kind": "send_email"})
    assert ok is True
    assert len(calls) == 1                        # base still ran (rich Telegram card)
    assert chans["whatsapp"].sent and chans["signal"].sent   # fanned out to away channels
    assert chans["telegram"].sent == []          # excluded — no duplicate on the base channel


async def test_away_escalation_honors_allowlist():
    chans = {"telegram": _FakeChannel(), "whatsapp": _FakeChannel(), "discord": _FakeChannel()}
    base, _ = _base_factory()
    # allowlist == the away channels only (mirrors autonomy.escalation_channels)
    notifier = AwayNotifier(base, _Presence(True),
                            _router_factory(chans, allow=["whatsapp"]), exclude={"telegram"})
    await notifier({"id": 1, "title": "t"})
    assert chans["whatsapp"].sent
    assert chans["discord"].sent == []           # not on the allowlist


async def test_away_returns_true_even_if_base_fails():
    chans = {"whatsapp": _FakeChannel(ok=True)}

    async def base(task):
        return False                             # Telegram push failed

    notifier = AwayNotifier(base, _Presence(True), _router_factory(chans))
    assert await notifier({"id": 1, "title": "t"}) is True   # escalation carried it


async def test_no_presence_object_is_base_only():
    chans = {"whatsapp": _FakeChannel()}
    base, calls = _base_factory()
    notifier = AwayNotifier(base, None, _router_factory(chans))
    assert await notifier({"id": 1, "title": "t"}) is True
    assert len(calls) == 1 and chans["whatsapp"].sent == []


async def test_away_with_no_reachable_channels_falls_back_to_base():
    base, _ = _base_factory()
    # only Telegram exists and it's excluded → nothing left to escalate to
    notifier = AwayNotifier(base, _Presence(True),
                            _router_factory({"telegram": _FakeChannel()}), exclude={"telegram"})
    assert await notifier({"id": 1, "title": "t"}) is True    # base carried it


# ── coordinator wiring: away-notifier rides the worker's single push ──────────

def test_coordinator_builds_away_notifier_over_live_channels():
    from agents.core.autonomy_coordinator import AutonomyCoordinator

    chans = {"telegram": _FakeChannel(), "whatsapp": _FakeChannel()}
    presence = OwnerPresence(clock=lambda: 0.0)
    presence.update(AWAY)
    orch = SimpleNamespace(
        channels=chans,
        owner_presence=presence,
        _runtime_settings={"autonomy": {"escalation_channels": ["whatsapp"]}},
    )
    coord = AutonomyCoordinator(orch)
    router = coord._escalation_router()
    assert router.targets() == ["whatsapp"]      # allowlist applied over live channels

    notifier = coord._away_notifier(None, exclude={"telegram"})
    assert isinstance(notifier, AwayNotifier)


async def test_away_escalation_rides_one_interrupt_slot(tmp_path):
    """End-to-end: an away decision card escalates via a *real* AutonomyWorker
    push, consuming exactly one ≤4/day interrupt slot — proving the away fan-out
    is inside the worker's budgeted push, not an extra interruption."""
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget

    q = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    try:
        chans = {"telegram": _FakeChannel(), "whatsapp": _FakeChannel()}
        base_calls = []

        async def base(task):                 # stand-in for the Telegram card
            base_calls.append(task.id)
            return True

        notifier = AwayNotifier(base, _Presence(True), _router_factory(chans),
                                exclude={"telegram"})
        budget = InterruptBudget(per_day=1)   # only ONE interruption allowed today
        worker = AutonomyWorker(
            q, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
            notifier=notifier, budget=budget,
        )
        assert budget.remaining() == 1

        t1 = await worker.submit("jarvis", "delete_file", "Delete old logs")
        assert t1.status == "blocked"
        assert base_calls == [t1.id]                      # base (Telegram) ran
        assert chans["whatsapp"].sent                     # AND escalated while away
        assert chans["telegram"].sent == []               # base channel not double-sent
        assert budget.remaining() == 0                    # exactly ONE slot consumed

        # Budget now exhausted → the next away card is held, and NOTHING escalates.
        before = list(chans["whatsapp"].sent)
        t2 = await worker.submit("jarvis", "delete_file", "Delete more logs")
        assert t2.status == "blocked"
        assert q.get(t2.id).pushed == 0                   # held for daily review
        assert chans["whatsapp"].sent == before           # no extra escalation
    finally:
        q.close()


# ── endpoints + swarm feed ────────────────────────────────────────────────────

def _client():
    from fastapi.testclient import TestClient

    from agents import web
    return web, TestClient(web.app)


def test_get_presence_requires_orch(monkeypatch):
    web, client = _client()
    monkeypatch.setattr(web, "orch", None)
    assert client.get("/api/presence/owner").status_code == 503


def test_post_presence_admin_guarded_and_updates(monkeypatch):
    web, client = _client()
    orch = SimpleNamespace(owner_presence=OwnerPresence())
    monkeypatch.setattr(web, "orch", orch)
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "sekret"
    try:
        # unauthenticated write is rejected
        assert client.post("/api/presence/owner", json={"state": "away"}).status_code == 401
        # authenticated write updates the tracker
        r = client.post("/api/presence/owner", json={"state": "locked", "source": "win"},
                        headers={"X-Admin-Token": "sekret"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["state"] == "away" and body["away"] is True
        # readable at the user tier (conftest disables the user guard)
        g = client.get("/api/presence/owner")
        assert g.status_code == 200 and g.json()["state"] == "away"
        # a bad state is a 422, not a silent unknown
        assert client.post("/api/presence/owner", json={"state": "nope"},
                           headers={"X-Admin-Token": "sekret"}).status_code == 422
    finally:
        web.ADMIN_TOKEN = old


def test_swarm_summary_carries_presence(monkeypatch):
    from agents.core.routers import swarm

    # no orchestrator → presence is None (shape still present)
    s0 = swarm.build_swarm_summary(None)
    assert "presence" in s0 and s0["presence"] is None

    presence = OwnerPresence(clock=lambda: 0.0)
    presence.update(AWAY, source="daemon")
    orch = SimpleNamespace(owner_presence=presence)
    s1 = swarm.build_swarm_summary(orch)
    assert s1["presence"]["state"] == AWAY and s1["presence"]["away"] is True
