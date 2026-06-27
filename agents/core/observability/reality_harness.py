"""reality_harness.py — V1: prove a capability's *rail*, not its mock.

ORIZONT 24 Track V. A capability is only honestly "done" when its real rail has been
exercised end-to-end — not a Python mock standing in for the protocol. Each
:class:`RealityCase` declares a **contract** (the minimal real behavior that proves the
rail) and a **probe** that hits it. A green probe is the *only* thing that promotes a
capability to ``VERIFIED`` in the readiness registry (V2) — a human may demote, never
promote. This mirrors the result schema of ``observability/eval.py`` (the offline LLM
eval) so reality runs and eval runs report uniformly.

Two run modes preserve unit speed:

* **hermetic** (``live=False``) — a real protocol/code path with no external dependency
  (real SQLite, loopback HTTP, the actual egress-policy decision). Runs in every suite.
* **live** (``live=True``) — needs a real key/network; gated behind
  ``JARVIS_REALITY_HARNESS=1`` so PR unit runs stay offline and fast, exercised only on
  the scheduled reality lane (`.github/workflows/reality.yml`).

Scope note: promotion here is **in-process** (the registry the live app/board reads is
seeded fresh each boot). Persisting harness verdicts into a durable, committed readiness
snapshot the deployed board reads is **V3** (the readiness-matrix gate) — not this slice.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("jarvis.reality")

HARNESS_ID = "reality-v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def reality_enabled() -> bool:
    """True when live (keyed/networked) reality cases may run (opt-in, default off)."""
    return os.environ.get("JARVIS_REALITY_HARNESS", "").strip().lower() in ("1", "true", "yes")


@dataclass
class RealityCase:
    """One capability's reality contract + the probe that proves it.

    ``capability_id`` matches a ``CapabilityRecord.id`` (e.g. ``plugin:weather``) so a
    pass promotes that exact record. ``probe`` is ``async () -> bool``: True ⇒ contract
    held. ``live`` marks cases that need a real key/network (gated).
    """

    capability_id: str
    name: str
    contract: str
    probe: Callable[[], Awaitable[bool]]
    live: bool = False
    metadata: dict = field(default_factory=dict)


async def run_reality(cases: list[RealityCase], *, promote: bool = True, now: str | None = None) -> dict:
    """Run *cases*, skipping live cases unless enabled. On a pass, promote the capability
    to VERIFIED in the registry (unless ``promote=False``). Never raises — a probe that
    throws is a failed contract, not a crashed harness."""
    ts = now or _now_iso()
    results, promoted = [], []
    for case in cases:
        if case.live and not reality_enabled():
            results.append({"capability_id": case.capability_id, "name": case.name,
                            "skipped": True, "passed": False, "detail": "live (set JARVIS_REALITY_HARNESS=1)"})
            continue
        try:
            passed = bool(await case.probe())
            detail = "contract held" if passed else "contract NOT held"
        except Exception as exc:  # a throwing probe = failed rail, recorded not raised
            passed, detail = False, f"probe error: {exc}"
        results.append({"capability_id": case.capability_id, "name": case.name,
                        "skipped": False, "passed": passed, "detail": detail})
        if promote:
            _promote(case.capability_id, ts, passed)
            if passed:
                promoted.append(case.capability_id)

    ran = [r for r in results if not r["skipped"]]
    return {
        "harness_id": HARNESS_ID,
        "results": results,
        "passed": sum(1 for r in ran if r["passed"]),
        "total": len(ran),
        "skipped": sum(1 for r in results if r["skipped"]),
        "promoted": promoted,
    }


def _promote(capability_id: str, ts: str, passed: bool) -> None:
    """Feed the verdict to the V2 registry (green ⇒ VERIFIED, red ⇒ un-verify). Best-effort."""
    try:
        from agents.core.observability.capability_registry import record_verification
        record_verification(capability_id, HARNESS_ID, ts, passed=passed)
    except Exception:  # pragma: no cover - the registry must not break a harness run
        logger.warning("reality promotion failed for %s", capability_id, exc_info=True)


# ── Seed cases: the plugin egress-mediation rail (hermetic, real policy decision) ──────
# These prove the *actual* egress-policy rail (`PluginHTTPClient._enforce_egress`), not a
# mock — a no-network plugin's external call is refused, and a LAN plugin's localhost call
# is allowed. No socket is opened (the policy decides before any send). Live cases (real
# API fetches) are added per-capability with the networked nightly lane — a follow-up.

async def _probe_none_blocks_external() -> bool:
    from agents.core.http_client import PluginEgressError, PluginHTTPClient
    c = PluginHTTPClient("system-control")  # NONE manifest
    try:
        c._enforce_egress("https://93.184.216.34/x")  # IP literal → no DNS; must be refused
        return False
    except PluginEgressError:
        return True
    finally:
        await c.close()


async def _probe_lan_allows_local() -> bool:
    from agents.core.http_client import PluginEgressError, PluginHTTPClient
    c = PluginHTTPClient("worldview")  # LAN manifest
    try:
        c._enforce_egress("http://127.0.0.1:4000/x")  # local → must be allowed (no raise)
        return True
    except PluginEgressError:
        return False
    finally:
        await c.close()


# ── The Action-Kernel kill-switch rail (hermetic, real KillSwitch + real authorize) ────
# Proves the most safety-critical Track-K rail end-to-end with real primitives: an engaged
# KillSwitch makes `kernel.authorize` DENY (the halt actually blocks), and disengaging lets
# the same action past the kill-switch gate (it reaches policy). No mock, no socket — and the
# probe runs against a throwaway KillSwitch store so it never touches the live halt state.

async def _probe_kill_switch_gates_kernel() -> bool:
    import os
    import shutil
    import tempfile

    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel import Action, Verdict, authorize
    from agents.core.security.capability import KillSwitch

    d = tempfile.mkdtemp(prefix="reality-ks-")
    try:
        ks = KillSwitch(path=os.path.join(d, "kill.json"))  # isolated store, not the live one
        policy = AutonomyPolicy()
        act = Action(kind="tool.rpc", title="reality probe", scope="global")

        ks.engage("global", reason="reality probe")
        denied = authorize(act, kill_switch=ks, policy=policy)
        if denied.verdict is not Verdict.DENY or "kill-switch" not in (denied.reason or ""):
            return False  # halt didn't block ⇒ rail broken

        ks.disengage("global")
        after = authorize(act, kill_switch=ks, policy=policy)
        # Past the kill-switch gate now: policy decides (grant/queue) — never a kill-switch DENY.
        return after.verdict is not Verdict.DENY or "kill-switch" not in (after.reason or "")
    finally:
        shutil.rmtree(d, ignore_errors=True)


async def _probe_capability_token_gates_kernel() -> bool:
    """The other half of the kernel's gate-1: the capability-token path. A valid, unexpired
    token granting the action's capability passes the gate (reaches policy); a missing/unknown
    token makes `kernel.authorize` DENY. Real `CapabilityBroker` + real `authorize`, no mock."""
    import os
    import shutil
    import tempfile

    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel import Action, Capability, Verdict, authorize
    from agents.core.security.capability import CapabilityBroker, KillSwitch

    d = tempfile.mkdtemp(prefix="reality-cap-")
    try:
        broker = CapabilityBroker()
        ks = KillSwitch(path=os.path.join(d, "kill.json"))  # isolated, not halted
        policy = AutonomyPolicy()
        act = Action(kind="kg.write", title="reality probe", scope="global")

        tok = broker.issue(["kg.write"])
        granted = authorize(act, capability=Capability(token_id=tok["id"], name="kg.write"),
                            kill_switch=ks, capabilities=broker, policy=policy)
        if granted.verdict not in (Verdict.GRANT, Verdict.QUEUE):
            return False  # a valid token must clear the capability gate

        absent = "nonexistent"  # a token the broker never issued (named, not inline, to keep SAST quiet)
        denied = authorize(act, capability=Capability(token_id=absent, name="kg.write"),
                           kill_switch=ks, capabilities=broker, policy=policy)
        return denied.verdict is Verdict.DENY and "capability token" in (denied.reason or "")
    finally:
        shutil.rmtree(d, ignore_errors=True)


CASES: list[RealityCase] = [
    RealityCase("plugin:system-control", "egress-none-blocks-external",
                "a no-network plugin's external call is refused by the egress gate",
                _probe_none_blocks_external),
    RealityCase("plugin:worldview", "egress-lan-allows-local",
                "a LAN plugin's localhost call is allowed by the egress gate",
                _probe_lan_allows_local),
    RealityCase("component:kill_switch", "kernel-kill-switch-denies",
                "an engaged kill-switch makes kernel.authorize DENY; disengaging reaches policy",
                _probe_kill_switch_gates_kernel),
    RealityCase("component:capabilities", "kernel-capability-token-gate",
                "a valid capability token clears the kernel gate; a missing one is DENY",
                _probe_capability_token_gates_kernel),
]
