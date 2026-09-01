"""DRA-15 backend defect 4: the auto-file safety net failed silently.

`cognition_trace.update_cognition` flags low-scoring turns for human review via
`orch.review_queue.auto_flag(...)`, guarded by `if getattr(orch, "review_queue", None)
is not None`. When the component is absent — a construction exception swallowed by
ComponentRegistry is enough — every low-scoring turn is still scored into the quality
ring and then dropped: no review row, no warning, nothing an operator could notice. The
net that exists to catch bad output is the one thing whose absence was unobservable.

Fixing this means saying so once, at WARNING, naming the score that went unflagged —
not per-turn spam, and not silence.
"""

import logging

import pytest

from agents.core import cognition_trace


class _Tracer:
    def __init__(self):
        self.records = []

    def record(self, trace):
        self.records.append(trace)
        return f"t{len(self.records)}"


class _Quality:
    """Scores every turn below the threshold, so auto_flag would always fire."""

    threshold = 0.6

    def record(self, trace):
        return {"score": 0.1}


class _Flagging:
    def __init__(self):
        self.flagged = []

    def auto_flag(self, trace, score, threshold):
        if score is not None and score < threshold:
            self.flagged.append((trace.get("id"), score))
            return {"id": "r1"}
        return None


class _Orch:
    def __init__(self, review_queue):
        self.agents = {}
        self.cognition = None
        self.tracer = _Tracer()
        self.quality = _Quality()
        self.review_queue = review_queue
        self._last_channel = "web"
        self.last_cognition = {}


def _turn(orch, reply="a poor answer"):
    intent = type("I", (), {"target_agents": ["jarvis"], "confidence": 0.9,
                            "source": "test", "context": {}})()
    cognition_trace.update_cognition(orch, "a question", intent, {}, reply, 1, 1, 1, 1)


@pytest.fixture(autouse=True)
def _reset_warning_state():
    cognition_trace.reset_autofile_warning()
    yield
    cognition_trace.reset_autofile_warning()


def test_a_missing_review_queue_is_reported_once_at_warning(caplog):
    orch = _Orch(review_queue=None)
    with caplog.at_level(logging.WARNING, logger="jarvis.cognition_trace"):
        _turn(orch)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "a low-scoring turn was dropped with no warning at all"
    assert "review_queue" in caplog.text
    assert "0.1" in caplog.text and "0.6" in caplog.text, "the unflagged score must be named"


def test_the_warning_does_not_repeat_every_turn(caplog):
    orch = _Orch(review_queue=None)
    with caplog.at_level(logging.WARNING, logger="jarvis.cognition_trace"):
        for _ in range(5):
            _turn(orch)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, f"expected one warning for five turns, got {len(warnings)}"


def test_a_healthy_turn_flags_and_warns_about_nothing(caplog):
    rq = _Flagging()
    orch = _Orch(review_queue=rq)
    with caplog.at_level(logging.WARNING, logger="jarvis.cognition_trace"):
        _turn(orch)
    assert len(rq.flagged) == 1, "the low score should have been flagged for review"
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_a_turn_that_would_not_be_flagged_is_not_warned_about(caplog):
    """Only a turn the net WOULD have caught is worth a warning."""
    class _Good(_Quality):
        def record(self, trace):
            return {"score": 0.9}          # above threshold: auto_flag would no-op

    orch = _Orch(review_queue=None)
    orch.quality = _Good()
    with caplog.at_level(logging.WARNING, logger="jarvis.cognition_trace"):
        _turn(orch)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_the_warning_re_arms_if_the_component_comes_back_and_goes_again(caplog):
    """The absence is a state, not a one-off event: a later outage must be reported too."""
    with caplog.at_level(logging.WARNING, logger="jarvis.cognition_trace"):
        _turn(_Orch(review_queue=None))                    # warns
        _turn(_Orch(review_queue=_Flagging()))             # healthy again -> re-arms
        _turn(_Orch(review_queue=None))                    # warns again
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 2, f"expected two warnings across an outage/recovery/outage, got {len(warnings)}"
