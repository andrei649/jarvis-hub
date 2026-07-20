"""V1 — reality harness: a green probe (and only a green probe) promotes to VERIFIED.

Offline + deterministic: the framework mechanics use fake probes; the seeded CASES
exercise the *real* egress-policy rail hermetically (no socket). Live cases are skipped
unless JARVIS_REALITY_HARNESS=1.
"""

import pytest

from agents.core.observability import capability_registry as cr
from agents.core.observability import reality_harness as rh
from agents.core.observability.camera_reality import (
    H31_CAMERA_LIVE_CASES,
    H31_CAMERA_REALITY_CASES,
)
from agents.core.observability.house_reality import (
    H30_HOUSE_LIVE_CASES,
    H30_HOUSE_REALITY_CASES,
)
from agents.core.observability.media_reality import H29_MEDIA_REALITY_CASES
from agents.core.observability.reality_harness import RealityCase, run_reality


def teardown_function():
    cr.clear_verifications()
    cr._OVERRIDES.clear()


@pytest.mark.asyncio
async def test_boot_registry_reality_cases_hold_for_every_wired_capability():
    """Scheduled reality lane exercises dynamic registry cases, not only static CASES."""
    from agents.core.config import JarvisConfig
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator(JarvisConfig())
    orch.skills.discover()
    records = {
        record.id: record
        for record in cr.build_records(orch)
        if record.kind in {"plugin", "component", "skill"}
    }
    cases = rh.registry_reality_cases(orch)

    out = await rh.run_reality(cases, promote=False)
    results = {item["capability_id"]: item["passed"] for item in out["results"]}

    assert len(cases) == len(records) == 75
    assert {capability_id for capability_id, passed in results.items() if not passed} == {
        capability_id for capability_id, record in records.items() if record.state == cr.SEAM
    }


async def _ok():
    return True


async def _bad():
    return False


async def _boom():
    raise RuntimeError("rail down")


# ── framework mechanics ────────────────────────────────────────────────────────
async def test_pass_promotes_fail_does_not(monkeypatch):
    monkeypatch.setattr(
        cr,
        "_plugin_records",
        lambda orch=None: [
            cr.CapabilityRecord(id="plugin:p_ok", kind="plugin", state=cr.WIRED),
            cr.CapabilityRecord(id="plugin:p_bad", kind="plugin", state=cr.WIRED),
        ],
    )
    out = await run_reality(
        [
            RealityCase("plugin:p_ok", "ok", "holds", _ok),
            RealityCase("plugin:p_bad", "bad", "fails", _bad),
        ],
        now="2026-06-25T00:00:00+00:00",
    )
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
    monkeypatch.setattr(
        cr,
        "_plugin_records",
        lambda orch=None: [
            cr.CapabilityRecord(id="plugin:seamy", kind="plugin", state=cr.SEAM),
        ],
    )
    await run_reality([RealityCase("plugin:seamy", "ok", "c", _ok)])
    assert cr.build_records()[0].state == cr.SEAM


async def test_manual_demote_overrides_a_verification(monkeypatch):
    monkeypatch.setattr(
        cr,
        "_plugin_records",
        lambda orch=None: [
            cr.CapabilityRecord(id="plugin:p", kind="plugin", state=cr.WIRED),
        ],
    )
    await run_reality([RealityCase("plugin:p", "ok", "c", _ok)])
    assert cr.build_records()[0].state == cr.VERIFIED
    cr.set_override("plugin:p", cr.SEAM)  # human pulls it back down
    assert cr.build_records()[0].state == cr.SEAM


# ── the real seeded cases: prove the egress + kernel kill-switch rails hermetically ──
async def test_seeded_cases_prove_rails_and_promote():
    out = await run_reality(rh.CASES, now="2026-06-25T00:00:00+00:00")
    live_count = len(H30_HOUSE_LIVE_CASES) + len(H31_CAMERA_LIVE_CASES)
    hermetic_count = len(rh.CASES) - live_count
    assert out["total"] == out["passed"] == hermetic_count
    assert out["skipped"] == live_count
    assert {"component:kill_switch", "component:capabilities"} <= set(out["promoted"])
    snap = cr.snapshot()  # plugins derive statically (no orch needed)
    states = {c["id"]: c["state"] for c in snap["capabilities"]}
    assert states["plugin:system-control"] == cr.VERIFIED
    assert states["plugin:worldview"] == cr.VERIFIED
    assert snap["harness_pending"] is False  # something is now genuinely verified


def test_canonical_seeded_harness_registers_the_h29_media_pack_once():
    h29_names = [case.name for case in H29_MEDIA_REALITY_CASES]
    seeded_names = [case.name for case in rh.CASES]

    assert h29_names
    assert all(seeded_names.count(name) == 1 for name in h29_names)


def test_canonical_seeded_harness_registers_the_h30_house_pack_once():
    h30_names = [case.name for case in H30_HOUSE_REALITY_CASES + H30_HOUSE_LIVE_CASES]
    seeded_names = [case.name for case in rh.CASES]

    assert h30_names
    assert all(seeded_names.count(name) == 1 for name in h30_names)


def test_canonical_seeded_harness_registers_the_h31_camera_pack_once():
    h31_names = [case.name for case in H31_CAMERA_REALITY_CASES + H31_CAMERA_LIVE_CASES]
    seeded_names = [case.name for case in rh.CASES]

    assert h31_names
    assert all(seeded_names.count(name) == 1 for name in h31_names)


async def test_kill_switch_rail_is_a_real_hermetic_proof():
    # The kernel kill-switch case proves the deny rail with real primitives (no mock),
    # promotes component:kill_switch, and — crucially — leaves the LIVE kill-switch untouched.
    from agents.core.security.capability import KillSwitch

    out = await run_reality(
        [c for c in rh.CASES if c.capability_id == "component:kill_switch"],
        now="2026-06-25T00:00:00+00:00",
    )
    assert out["total"] == 1 and out["passed"] == 1
    assert out["promoted"] == ["component:kill_switch"]
    assert "component:kill_switch" in cr._VERIFICATIONS
    assert KillSwitch().is_halted("global") is False  # the probe's temp store stayed isolated


async def test_capability_token_rail_is_a_real_hermetic_proof():
    # The capability-token case proves the other half of the kernel gate-1 with a real
    # CapabilityBroker (valid token clears, missing token DENYs) and promotes the record.
    out = await run_reality(
        [c for c in rh.CASES if c.capability_id == "component:capabilities"],
        now="2026-06-25T00:00:00+00:00",
    )
    assert out["total"] == 1 and out["passed"] == 1
    assert out["promoted"] == ["component:capabilities"]
    assert "component:capabilities" in cr._VERIFICATIONS
