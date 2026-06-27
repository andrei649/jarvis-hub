"""H23.6 — minimal taint flag + kernel escalation (indirect-injection guard).

Content from an untrusted source is tainted; the kernel escalates a tainted action from
GRANT to QUEUE (approval) so injected content can't auto-execute.
"""

from types import SimpleNamespace

from agents.core import kernel
from agents.core.autonomy.policy import ACT
from agents.core.kernel import Action, Verdict
from agents.core.security import taint


# ── primitives ────────────────────────────────────────────────────────────────
def test_untrusted_source_classification():
    for s in ("web", "websearch", "RSS feed", "osint", "worldview", "inbound-channel"):
        assert taint.is_untrusted_source(s) is True
    for s in ("user", "local", "memory", "", None):
        assert taint.is_untrusted_source(s) is False


def test_mark_and_is_tainted():
    m = taint.mark({"k": 1}, source="web")
    assert m["tainted"] is True and m["taint_source"] == "web" and m["k"] == 1
    assert taint.is_tainted(m) is True
    assert taint.is_tainted({"k": 1}) is False
    assert taint.is_tainted(None) is False and taint.is_tainted("x") is False


def test_mark_if_untrusted_only_marks_untrusted():
    assert taint.is_tainted(taint.mark_if_untrusted({}, "websearch")) is True
    assert taint.is_tainted(taint.mark_if_untrusted({}, "user")) is False


# ── kernel enforcement ──────────────────────────────────────────────────────────
class _GrantPolicy:
    def decide(self, action):
        return SimpleNamespace(tier=0, outcome=ACT, reason="ok")


def test_clean_action_grants():
    d = kernel.authorize(Action(kind="x"), policy=_GrantPolicy())
    assert d.verdict is Verdict.GRANT


def test_tainted_action_is_escalated_to_approval():
    d = kernel.authorize(Action(kind="x", payload={"tainted": True}), policy=_GrantPolicy())
    assert d.verdict is Verdict.QUEUE
    assert "tainted" in d.reason.lower()
    assert d.card is not None
