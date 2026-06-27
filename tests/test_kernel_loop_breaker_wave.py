"""ORIZONT-24 K3 (loop-breaker slice) — the loop-wide circuit breaker is bound ONLY to
the broker (autonomy) action path, never to routes/egress.

The breaker keys on ``action.kind``: a runaway agent that re-requests the *same* governed
action past a threshold trips it (OWASP unbounded-consumption). But the high-frequency
route/egress paths legitimately repeat one kind (many egress calls / KG writes), so they
must NOT carry the detector — `make_action_kernel(orch)` omits it, and only the autonomy
coordinator passes `loop_detector=orch.loop_detector`.
"""
import pytest

from agents.core.kernel import Action, Verdict
from agents.core.kernel.binding import make_action_kernel
from agents.core.kernel.budget import LoopDetector


def _orch(tmp_path, *, detector=None):
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.security.capability import CapabilityBroker, KillSwitch

    class _Orch:
        autonomy_policy = AutonomyPolicy()
        kill_switch = KillSwitch(tmp_path / "kill.json")
        capabilities = CapabilityBroker()
        intent_log = None
        loop_detector = detector
    return _Orch()


# ── the breaker is bound on the broker path ────────────────────────────────────────
def test_broker_kernel_trips_on_runaway(tmp_path):
    det = LoopDetector(max_repeats=2)
    orch = _orch(tmp_path, detector=det)
    k = make_action_kernel(orch, loop_detector=orch.loop_detector)
    # first 2 of the same kind are healthy (not loop-denied); the 3rd trips the breaker
    for _ in range(2):
        d = k(Action(kind="call.outbound"))
        assert d.verdict is not Verdict.DENY or "loop" not in d.reason
    tripped = k(Action(kind="call.outbound"))
    assert tripped.verdict is Verdict.DENY and "loop circuit breaker" in tripped.reason
    # once open, it stays open (even a fresh kind is denied — loop-wide)
    assert k(Action(kind="social.post")).verdict is Verdict.DENY


def test_breaker_counts_per_signature_not_total(tmp_path):
    # max_repeats=5; 4 of each of two kinds = 8 total events, but NEITHER kind exceeds its
    # own threshold → no trip. (A total-count breaker would wrongly trip at 6.)
    det = LoopDetector(max_repeats=5)
    orch = _orch(tmp_path, detector=det)
    k = make_action_kernel(orch, loop_detector=orch.loop_detector)
    for _ in range(4):
        assert "loop circuit breaker" not in (k(Action(kind="call.outbound")).reason or "")
        assert "loop circuit breaker" not in (k(Action(kind="writeback.notion")).reason or "")
    assert det.tripped is False


# ── routes/egress kernels never carry the breaker ──────────────────────────────────
def test_route_kernel_has_no_loop_detector(tmp_path):
    orch = _orch(tmp_path, detector=LoopDetector(max_repeats=2))
    k = make_action_kernel(orch)          # the route/egress call shape: NO loop_detector
    # many identical kinds (as egress / kg.write legitimately do) must never loop-trip
    for _ in range(20):
        d = k(Action(kind="kg.write"))
        assert "loop circuit breaker" not in (d.reason or "")
    assert orch.loop_detector.tripped is False    # the orch's detector was never touched


# ── default-off: a None detector is inert ──────────────────────────────────────────
def test_none_detector_is_inert(tmp_path):
    orch = _orch(tmp_path, detector=None)
    k = make_action_kernel(orch, loop_detector=getattr(orch, "loop_detector", None))
    for _ in range(20):
        assert "loop circuit breaker" not in (k(Action(kind="payment")).reason or "")


# ── end-to-end: a real broker with the bound kernel refuses a runaway ───────────────
def test_real_broker_runaway_is_denied(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    from agents.core.autonomy.call_broker import CallBroker

    det = LoopDetector(max_repeats=3)
    orch = _orch(tmp_path, detector=det)
    k = make_action_kernel(orch, loop_detector=orch.loop_detector)
    broker = CallBroker(enqueue=lambda *a, **kw: 1, kernel=k)

    # the same outbound call requested over and over → the breaker eventually refuses it
    reasons = [broker.request(to="+15551234567", message="hi", provider="twilio").get("reason")
               for _ in range(6)]
    assert any(r and "loop circuit breaker" in r for r in reasons), reasons
