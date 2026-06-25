"""V1 — reality harness: a green probe (and only a green probe) promotes to VERIFIED.

Offline + deterministic: the framework mechanics use fake probes; the seeded CASES
exercise the *real* egress-policy rail hermetically (no socket). Live cases are skipped
unless JARVIS_REALITY_HARNESS=1.
"""

import pytest

from agents.core.observability import capability_registry as cr
from agents.core.observability import reality_harness as rh
from agents.core.observability.reality_harness import RealityCase, run_reality


def teardown_function():
    cr.clear_verifications()
    cr._OVERRIDES.clear()


async def _ok():
    return True


async def _bad():
    return False


async def _boom():
    raise RuntimeError("rail down")


# ── framework mechanics ────────────────────────────────────────────────────────
async def test_pass_promotes_fail_does_not(monkeypatch):
    monkeypatch.setattr(cr, "_plugin_records", lambda: [
        cr.CapabilityRecord(id="plugin:p_ok", kind="plugin", state=cr.WIRED),
        cr.CapabilityRecord(id="plugin:p_bad", kind="plugin", state=cr.WIRED),
    ])
    out = await run_reality([
        RealityCase("plugin:p_ok", "ok", "holds", _ok),
        RealityCase("plugin:p_bad", "bad", "fails", _bad),
    ], now="2026-06-25T00:00:00+00:00")
    assert out["passed"] == 1 and out["total"] == 2
    assert out["promoted"] == ["plugin:p_ok"]

    states = {r.id: r.state for r in cr.build_records()}
    assert states["plugin:p_ok"] == cr.VERIFIED
    assert states["plugin:p_bad"] == cr.WIRED  # unproven stays wired, never fabricated


async def test_throwing_probe_is_a_failed_contract_not_a_crash():
    out = await run_reality([RealityCase("plugin:x", "boom", "c", _boom)], promote=False)
    assert out["passed"] == 0 and out["total"] == 1
    assert "probe error" in out["results"][0]["detail"]


async def test_live_case_skipped_unless_enabled(monkeypatch):
    monkeypatch.delenv("JARVIS_REALITY_HARNESS", raising=False)
    out = await run_reality([RealityCase("plugin:x", "live", "c", _ok, live=True)])
    assert out["skipped"] == 1 and out["total"] == 0

    monkeypatch.setenv("JARVIS_REALITY_HARNESS", "1")
    out = await run_reality([RealityCase("plugin:x", "live", "c", _ok, live=True)], promote=False)
    assert out["skipped"] == 0 and out["passed"] == 1


async def test_verified_cannot_be_set_for_a_seam_rail(monkeypatch):
    # a green verdict on a capability that is only SEAM (rail not wired) must NOT promote
    monkeypatch.setattr(cr, "_plugin_records", lambda: [
        cr.CapabilityRecord(id="plugin:seamy", kind="plugin", state=cr.SEAM),
    ])
    await run_reality([RealityCase("plugin:seamy", "ok", "c", _ok)])
    assert cr.build_records()[0].state == cr.SEAM


async def test_manual_demote_overrides_a_verification(monkeypatch):
    monkeypatch.setattr(cr, "_plugin_records", lambda: [
        cr.CapabilityRecord(id="plugin:p", kind="plugin", state=cr.WIRED),
    ])
    await run_reality([RealityCase("plugin:p", "ok", "c", _ok)])
    assert cr.build_records()[0].state == cr.VERIFIED
    cr.set_override("plugin:p", cr.SEAM)  # human pulls it back down
    assert cr.build_records()[0].state == cr.SEAM


# ── the real seeded cases: prove the egress rail hermetically ───────────────────
async def test_seeded_cases_prove_egress_rail_and_promote():
    out = await run_reality(rh.CASES, now="2026-06-25T00:00:00+00:00")
    assert out["total"] == 2 and out["passed"] == 2  # both hermetic egress contracts hold
    snap = cr.snapshot()  # plugins derive statically (no orch needed)
    states = {c["id"]: c["state"] for c in snap["capabilities"]}
    assert states["plugin:system-control"] == cr.VERIFIED
    assert states["plugin:worldview"] == cr.VERIFIED
    assert snap["harness_pending"] is False  # something is now genuinely verified
