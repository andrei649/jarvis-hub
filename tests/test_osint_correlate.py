"""P2 — OSINT pack: governed correlation over untrusted evidence (Track P).

The engine groups evidence by indicator into findings with a corroboration-based
confidence + a provenance chain, marks untrusted-source evidence tainted at ingestion,
and propagates that taint onto a write-back payload. The governance test then proves the
*rail* with real primitives: a tainted (untrusted-OSINT) write-back the policy would GRANT
is escalated to QUEUE by ``kernel.authorize`` — untrusted intel can never auto-execute.
"""

import os
import shutil
import tempfile

from agents.core.autonomy.policy import AutonomyPolicy, RiskTier
from agents.core.kernel import Action, Verdict, authorize
from agents.core.observability import capability_registry as cr
from agents.core.observability.reality_harness import CASES, run_reality
from agents.core.osint import build_brief, correlate, writeback_payload
from agents.core.security.capability import KillSwitch


# ── correlation engine ─────────────────────────────────────────────────────────
def test_groups_indicator_and_casefolds_token_kinds():
    out = correlate([
        {"source": "worldview", "kind": "domain", "value": "Evil.Example"},
        {"source": "web", "kind": "domain", "value": "evil.example"},  # same indicator, diff casing
        {"source": "manual", "kind": "ip", "value": "10.0.0.1"},
    ])
    assert out["counts"]["findings"] == 2          # one domain (merged) + one ip
    dom = next(f for f in out["findings"] if f["kind"] == "domain")
    assert dom["count"] == 2 and dom["sources"] == ["web", "worldview"]
    assert dom["value"] == "Evil.Example"          # first-seen casing preserved for display


def test_free_text_kind_is_not_casefolded():
    out = correlate([
        {"source": "rss", "kind": "alias", "value": "Night Owl"},
        {"source": "news", "kind": "alias", "value": "night owl"},   # different (exact match)
    ])
    assert out["counts"]["findings"] == 2


def test_taint_propagates_from_untrusted_evidence():
    out = correlate([
        {"source": "worldview", "kind": "domain", "value": "evil.example"},  # untrusted
        {"source": "manual", "kind": "ip", "value": "10.0.0.1"},             # trusted
    ])
    dom = next(f for f in out["findings"] if f["kind"] == "domain")
    ip = next(f for f in out["findings"] if f["kind"] == "ip")
    assert dom["tainted"] is True and ip["tainted"] is False
    assert out["untrusted_ingestion"] is True and out["counts"]["tainted"] == 1


def test_confidence_rises_with_distinct_corroborating_sources():
    one = correlate([{"source": "web", "kind": "ip", "value": "1.2.3.4"}])["findings"][0]
    two = correlate([
        {"source": "web", "kind": "ip", "value": "1.2.3.4"},
        {"source": "rss", "kind": "ip", "value": "1.2.3.4"},
    ])["findings"][0]
    assert two["confidence"] > one["confidence"]
    # all-untrusted findings are never certain (capped < 1.0) — they route through approval
    assert two["confidence"] <= 0.95


def test_trusted_source_lifts_cap_above_untrusted_ceiling():
    untrusted = ["web", "rss", "news", "osint", "worldview"]
    all_osint = correlate([{"source": s, "kind": "ip", "value": "9.9.9.9"} for s in untrusted])["findings"][0]
    with_op = correlate([{"source": s, "kind": "ip", "value": "8.8.8.8"}
                         for s in [*untrusted, "operator"]])["findings"][0]
    assert all_osint["confidence"] == 0.95       # pure OSINT is capped — never certain (approval-gated)
    assert with_op["confidence"] > 0.95          # a trusted corroborator lifts past the OSINT cap
    assert with_op["tainted"] is True            # still tainted (untrusted sources are present)


def test_empty_and_malformed_yield_no_findings():
    assert correlate([])["counts"]["findings"] == 0
    assert correlate(None)["counts"]["findings"] == 0
    # missing kind/value, wrong types → dropped, never invented
    assert correlate([{"source": "web"}, {"kind": "ip"}, "junk", 7])["counts"]["findings"] == 0


def test_brief_headline_and_top_n():
    ev = [{"source": "web", "kind": "ip", "value": f"1.1.1.{i}"} for i in range(12)]
    brief = build_brief(ev, top=5)
    assert len(brief["top"]) == 5 and brief["counts"]["findings"] == 12
    assert "from untrusted source" in brief["headline"]
    assert build_brief([])["headline"] == "no intel correlated"


# ── writeback payload carries (or omits) taint ─────────────────────────────────
def test_writeback_carries_taint_for_untrusted_finding():
    drawer = correlate([{"source": "worldview", "kind": "domain", "value": "evil.example"}])
    payload = writeback_payload(drawer["findings"][0])
    assert payload["tainted"] is True and payload["indicator"] == "evil.example"
    assert payload["kind"] == "domain"


def test_writeback_clean_for_trusted_only_finding():
    drawer = correlate([{"source": "manual", "kind": "domain", "value": "ok.example"}])
    payload = writeback_payload(drawer["findings"][0])
    assert "tainted" not in payload and payload["indicator"] == "ok.example"


# ── governance rail (the P2 contract, real primitives, hermetic) ───────────────
def _authorize(payload):
    d = tempfile.mkdtemp(prefix="osint-gov-")
    try:
        ks = KillSwitch(path=os.path.join(d, "kill.json"))  # isolated, not halted
        act = Action(kind="kg.write", title="osint writeback", scope="global", payload=payload)
        return authorize(act, kill_switch=ks, policy=AutonomyPolicy())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_untrusted_osint_writeback_is_escalated_to_queue():
    """The trust boundary: same low-risk write-back, GRANT when operator-sourced but QUEUE
    when it carries untrusted-OSINT taint — injected intel can't auto-execute."""
    rev = {"risk_tier": int(RiskTier.REVERSIBLE)}
    clean = writeback_payload(
        correlate([{"source": "manual", "kind": "domain", "value": "ok.example"}])["findings"][0],
        base=dict(rev))
    tainted = writeback_payload(
        correlate([{"source": "worldview", "kind": "domain", "value": "evil.example"}])["findings"][0],
        base=dict(rev))

    clean_dec = _authorize(clean)
    taint_dec = _authorize(tainted)
    assert clean_dec.verdict is Verdict.GRANT          # operator intel may auto-act
    assert taint_dec.verdict is Verdict.QUEUE           # untrusted intel is held for approval
    assert "tainted" in (taint_dec.reason or "")


# ── the reality case promotes the OSINT capability to VERIFIED ─────────────────
def teardown_function():
    cr.clear_verifications()
    cr._OVERRIDES.clear()


async def test_osint_reality_case_present_and_passes():
    case = next((c for c in CASES if c.name == "osint-untrusted-ingestion-queued"), None)
    assert case is not None, "the P2 OSINT governance reality case must be registered"
    assert case.capability_id == "plugin:worldview" and case.live is False
    out = await run_reality([case], now="2026-06-28T00:00:00+00:00")
    assert out["passed"] == 1 and out["total"] == 1
    assert "plugin:worldview" in out["promoted"]
