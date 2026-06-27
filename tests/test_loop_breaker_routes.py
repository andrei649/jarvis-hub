"""K3 operability — /api/security/loop-breaker status + admin reset.

The loop circuit breaker stays open until reset; these give the operator a status read and
a recovery action. Reset is admin-guard-only and NOT kernel-mediated (like the kill-switch
disengage) so a tripped breaker / engaged halt can never block its own reset.
"""
import asyncio
import json

import agents.web as web
from agents.core.kernel.budget import LoopDetector
from agents.core.routers import security as secmod


def _orch(det):
    class _Orch:
        loop_detector = det
    return _Orch()


def _run(coro):
    return asyncio.run(coro)


def _status(resp):
    return getattr(resp, "status_code", 200)


def _body(resp):
    raw = getattr(resp, "body", None)
    return json.loads(raw) if raw is not None else resp


def test_status_reports_breaker(monkeypatch):
    monkeypatch.setattr(web, "orch", _orch(LoopDetector(max_repeats=7, window_seconds=30)))
    body = _body(_run(secmod.loop_breaker_status()))
    assert body["tripped"] is False
    assert body["max_repeats"] == 7 and body["window_seconds"] == 30
    assert body["recent_events"] == 0


def test_reset_closes_a_tripped_breaker(monkeypatch):
    det = LoopDetector(max_repeats=1)
    det.record("x")
    det.record("x")                       # 2nd > 1 → trips
    assert det.tripped is True
    monkeypatch.setattr(web, "orch", _orch(det))
    body = _body(_run(secmod.loop_breaker_reset()))
    assert body == {"ok": True, "was_tripped": True, "tripped": False}
    assert det.tripped is False           # genuinely reset on the live detector


def test_reset_is_idempotent_when_healthy(monkeypatch):
    monkeypatch.setattr(web, "orch", _orch(LoopDetector()))
    body = _body(_run(secmod.loop_breaker_reset()))
    assert body == {"ok": True, "was_tripped": False, "tripped": False}


def test_503_without_detector(monkeypatch):
    class _Orch:
        loop_detector = None
    monkeypatch.setattr(web, "orch", _Orch())
    assert _status(_run(secmod.loop_breaker_status())) == 503
    assert _status(_run(secmod.loop_breaker_reset())) == 503
