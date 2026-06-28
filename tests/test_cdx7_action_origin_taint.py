"""CDX-7 (action-taint) — the kernel escalates a GRANT to QUEUE when an action's
declared *origin* is an untrusted source.

You can't propagate taint *through* an LLM (it launders content), so the honest
signal is the caller's declared provenance: an action built from an external HTTP
write (`origin="external"`), an inbound channel, or a web/rss/osint/worldview feed
can't silently auto-execute — it's routed to approval. The default origin
"generated" (an in-house action) stays trusted, so normal actions are unaffected.
"""

import pytest

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import Action, Verdict, authorize
from agents.core.security.capability import KillSwitch
from agents.core.security.taint import mark


def _kill(tmp_path):
    return KillSwitch(tmp_path / "kill.json")


def _decide(tmp_path, **action_kw):
    # risk_tier 1 (REVERSIBLE) is a write the policy GRANTs — so any escalation we see
    # is the taint guard, not the risk tier.
    payload = action_kw.pop("payload", {"risk_tier": 1})
    return authorize(
        Action(kind="kg.write", payload=payload, **action_kw),
        kill_switch=_kill(tmp_path), policy=AutonomyPolicy(),
    )


def test_default_generated_origin_is_trusted_and_grants(tmp_path):
    d = _decide(tmp_path)                                    # origin defaults to "generated"
    assert d.verdict is Verdict.GRANT


def test_external_origin_escalates_to_queue(tmp_path):
    d = _decide(tmp_path, origin="external")
    assert d.verdict is Verdict.QUEUE
    assert "untrusted origin" in d.reason and "external" in d.reason
    assert d.card is not None                                # an approval card is minted


@pytest.mark.parametrize("origin", ["osint", "worldview", "inbound", "channel", "web", "rss"])
def test_untrusted_origins_all_escalate(tmp_path, origin):
    assert _decide(tmp_path, origin=origin).verdict is Verdict.QUEUE


def test_tainted_payload_still_escalates_and_is_labelled(tmp_path):
    d = _decide(tmp_path, payload=mark({"risk_tier": 1}, source="worldview"))
    assert d.verdict is Verdict.QUEUE and "tainted payload" in d.reason


def test_taint_only_escalates_a_grant_never_overrides_a_deny(tmp_path):
    ks = _kill(tmp_path)
    ks.engage("global")                                     # halt → DENY takes precedence
    d = authorize(Action(kind="kg.write", payload={"risk_tier": 1}, origin="external"),
                  kill_switch=ks, policy=AutonomyPolicy())
    assert d.verdict is Verdict.DENY                        # not QUEUE — the taint check runs only on GRANT


def test_memory_kg_external_write_declares_untrusted_origin():
    # the real external-HTTP kg-write site declares origin="external" (so the kernel
    # escalates it) — guard that the declaration doesn't silently regress.
    import inspect

    from agents.core.routers import memory_kg
    src = inspect.getsource(memory_kg)
    assert 'origin="external"' in src and 'kind="kg.write"' in src
