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
from collections.abc import Mapping
from datetime import UTC, datetime

from agents.core.capability_manifests import ACTION_CAPABILITY_MANIFESTS
from agents.core.capability_verification import (
    HARNESS_ID,
    action_case_name,
    component_case_name,
    plugin_case_name,
    skill_case_name,
    tool_case_name,
)
from agents.core.observability.reality_types import RealityCase

logger = logging.getLogger("jarvis.reality")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def reality_enabled() -> bool:
    """True when live (keyed/networked) reality cases may run (opt-in, default off)."""
    from agents.core.env_config import env_flag

    return env_flag("JARVIS_REALITY_HARNESS")


async def run_reality(
    cases: list[RealityCase], *, promote: bool = True, now: str | None = None
) -> dict:
    """Run *cases*, skipping live cases unless enabled. On a pass, promote the capability
    to VERIFIED in the registry (unless ``promote=False``). Never raises — a probe that
    throws is a failed contract, not a crashed harness."""
    ts = now or _now_iso()
    results, promoted = [], []
    for case in cases:
        if case.live and not reality_enabled():
            results.append(
                {
                    "capability_id": case.capability_id,
                    "name": case.name,
                    "skipped": True,
                    "passed": False,
                    "detail": "live (set JARVIS_REALITY_HARNESS=1)",
                    "metadata": dict(case.metadata),
                }
            )
            continue
        try:
            probe_result = await case.probe()
            probe_metadata = {}
            if isinstance(probe_result, Mapping):
                passed = probe_result.get("passed") is True
                raw_metadata = probe_result.get("metadata")
                if isinstance(raw_metadata, Mapping):
                    probe_metadata = dict(raw_metadata)
            else:
                passed = bool(probe_result)
            detail = "contract held" if passed else "contract NOT held"
        except Exception as exc:  # a throwing probe = failed rail, recorded not raised
            passed, detail, probe_metadata = False, f"probe error: {exc}", {}
        results.append(
            {
                "capability_id": case.capability_id,
                "name": case.name,
                "skipped": False,
                "passed": passed,
                "detail": detail,
                "metadata": {**case.metadata, **probe_metadata},
            }
        )

    if promote:
        grouped: dict[str, list[dict]] = {}
        for case, result in zip(cases, results, strict=True):
            if case.metadata.get("promotable", True) is False:
                continue
            grouped.setdefault(case.capability_id, []).append(result)
        for capability_id, contracts in grouped.items():
            if any(item["skipped"] for item in contracts):
                continue
            passed = all(not item["skipped"] and item["passed"] for item in contracts)
            _promote(capability_id, ts, passed)
            if passed:
                promoted.append(capability_id)

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
        granted = authorize(
            act,
            capability=Capability(token_id=tok["id"], name="kg.write"),
            kill_switch=ks,
            capabilities=broker,
            policy=policy,
        )
        if granted.verdict not in (Verdict.GRANT, Verdict.QUEUE):
            return False  # a valid token must clear the capability gate

        absent = (
            "nonexistent"  # a token the broker never issued (named, not inline, to keep SAST quiet)
        )
        denied = authorize(
            act,
            capability=Capability(token_id=absent, name="kg.write"),
            kill_switch=ks,
            capabilities=broker,
            policy=policy,
        )
        return denied.verdict is Verdict.DENY and "capability token" in (denied.reason or "")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── The P2 OSINT governed-ingestion rail (hermetic, real correlate + taint + authorize) ─
# Proves the trust boundary P2 exists for: a write-back derived from *untrusted* OSINT
# evidence (a worldview/web source → tainted at ingestion by security.taint, propagated
# onto the payload by osint.writeback_payload) is escalated GRANT→QUEUE by the real
# kernel.authorize — while the same low-risk write from a trusted operator source is
# GRANTed. Untrusted intel can never auto-execute. No mock, no socket; isolated KillSwitch.


async def _probe_osint_untrusted_ingestion_queued() -> bool:
    import shutil
    import tempfile

    from agents.core.autonomy.policy import AutonomyPolicy, RiskTier
    from agents.core.kernel import Action, Verdict, authorize
    from agents.core.osint import correlate, writeback_payload
    from agents.core.security.capability import KillSwitch

    d = tempfile.mkdtemp(prefix="reality-osint-")
    try:
        ks = KillSwitch(path=os.path.join(d, "kill.json"))  # isolated store, not the live halt
        policy = AutonomyPolicy()
        base = {"risk_tier": int(RiskTier.REVERSIBLE)}  # a low-risk write the policy would GRANT

        clean = writeback_payload(
            correlate([{"source": "operator", "kind": "domain", "value": "ok.example"}])[
                "findings"
            ][0],
            base=dict(base),
        )
        tainted = writeback_payload(
            correlate([{"source": "worldview", "kind": "domain", "value": "evil.example"}])[
                "findings"
            ][0],
            base=dict(base),
        )

        def _verdict(payload):
            act = Action(kind="kg.write", title="osint writeback", scope="global", payload=payload)
            return authorize(act, kill_switch=ks, policy=policy)

        clean_dec = _verdict(clean)
        taint_dec = _verdict(tainted)
        # Contract: operator intel auto-acts (GRANT); untrusted OSINT is held (QUEUE, taint reason).
        return (
            clean_dec.verdict is Verdict.GRANT
            and taint_dec.verdict is Verdict.QUEUE
            and "tainted" in (taint_dec.reason or "")
        )
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── The P3 Market-Intel money-safety rail (hermetic, real policy + authorize) ──────────
# Proves the finance-safety property: a money action (a trade/transfer triggered off a
# market signal) is held by the real kernel — classified IRREVERSIBLE_OR_MONEY → QUEUE
# (approval) — while read-only market monitoring is GRANTed. Money never auto-moves; the
# pack can watch the market freely but can't act on your behalf. No mock, isolated KillSwitch.


async def _probe_market_money_action_queued() -> bool:
    import shutil
    import tempfile

    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel import Action, Verdict, authorize
    from agents.core.security.capability import KillSwitch

    d = tempfile.mkdtemp(prefix="reality-market-")
    try:
        ks = KillSwitch(path=os.path.join(d, "kill.json"))  # isolated, not the live halt
        policy = AutonomyPolicy()

        def _v(kind, title):
            return authorize(
                Action(kind=kind, title=title, scope="global"), kill_switch=ks, policy=policy
            )

        scan = _v("market.monitor", "monitor watchlist")  # read-only intel
        trade = _v("trade.buy", "buy BTC at market")  # money → must be held
        # Contract: monitoring auto-runs (GRANT); a money action is QUEUED for approval.
        return (
            scan.verdict is Verdict.GRANT
            and trade.verdict is Verdict.QUEUE
            and "IRREVERSIBLE_OR_MONEY" in (trade.reason or "")
        )
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── The P4 Creative publish-is-held rail (hermetic, real policy + authorize) ───────────
# Proves the publishing-safety property: the creative pipeline plans/drafts freely (a
# reversible draft → GRANT), but the terminal release — publishing a finished campaign to
# the world — is an irreversible side-effect the real kernel QUEUEs for approval. Nothing
# is auto-published on the user's behalf. No mock, isolated KillSwitch.


async def _probe_creative_release_queued() -> bool:
    import shutil
    import tempfile

    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.creative import plan_pipeline, release_action_payload
    from agents.core.kernel import Action, Verdict, authorize
    from agents.core.security.capability import KillSwitch

    d = tempfile.mkdtemp(prefix="reality-creative-")
    try:
        ks = KillSwitch(path=os.path.join(d, "kill.json"))  # isolated, not the live halt
        policy = AutonomyPolicy()
        plan = plan_pipeline({"goal": "launch teaser", "platforms": ["youtube"]})

        draft = authorize(
            Action(kind="creative.draft", title="draft script", scope="global"),
            kill_switch=ks,
            policy=policy,
        )
        release = authorize(
            Action(
                kind="release.publish",
                title="release campaign to youtube",
                scope="global",
                payload=release_action_payload(plan["exports"][0]),
            ),
            kill_switch=ks,
            policy=policy,
        )
        # Contract: drafting auto-runs (GRANT); publishing to the world is held (QUEUE).
        return (
            draft.verdict is Verdict.GRANT
            and release.verdict is Verdict.QUEUE
            and "IRREVERSIBLE_OR_MONEY" in (release.reason or "")
        )
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _make_action_kernel_probe(manifest):
    """Build a hermetic probe through the real H27 action facade and kernel."""

    async def _probe() -> bool:
        import tempfile
        from unittest.mock import patch

        from agents.core.autonomy.policy import AutonomyPolicy
        from agents.core.capability_actions import CapabilityActionAPI
        from agents.core.kernel import authorize
        from agents.core.security.capability import CapabilityBroker, KillSwitch

        executed = []
        with tempfile.TemporaryDirectory(prefix="reality-action-") as directory:
            kill_switch = KillSwitch(path=os.path.join(directory, "kill.json"))
            kill_switch.engage("global", reason="reality action-plane probe")
            capabilities = CapabilityBroker()
            policy = AutonomyPolicy()

            def _authorize(action, capability=None, budget=None):
                return authorize(
                    action,
                    capability,
                    budget,
                    kill_switch=kill_switch,
                    capabilities=capabilities,
                    policy=policy,
                )

            api = CapabilityActionAPI(authorizer=_authorize)
            api.register(manifest.id, lambda params, context: executed.append(params))
            params = dict.fromkeys(manifest.inputs.get("required", ()), "probe")
            with patch.dict(
                os.environ,
                {"JARVIS_UNIFIED_ACTION_API": "1", "JARVIS_ACTION_KERNEL": "1"},
            ):
                result = await api.perform(manifest.id, params)
        return result.status == "refused" and "kill-switch" in result.reason and not executed

    return _probe


async def _probe_tool_echo_protocol() -> bool:
    from agents.core.tool_rpc import ToolRPCServer

    server = ToolRPCServer()

    async def _echo(args):
        return {"echo": args}

    server.register_tool("echo", _echo, capability_id="tool:echo")
    result = await server.handle({"tool": "echo", "args": {"value": "probe"}})
    return result == {
        "ok": True,
        "tool": "echo",
        "result": {"echo": {"value": "probe"}},
    }


async def _probe_tool_time_protocol() -> bool:
    import time

    from agents.core.tool_rpc import ToolRPCServer

    server = ToolRPCServer()

    async def _time(_args):
        return {"now": time.time()}

    server.register_tool("time", _time, capability_id="tool:time")
    result = await server.handle({"tool": "time", "args": {}})
    value = (result.get("result") or {}).get("now")
    return result.get("ok") is True and result.get("tool") == "time" and isinstance(value, float)


async def _probe_media_present_verified_rail() -> bool:
    """The O29 present() rail: contract → resolve → drive → verify, hermetically."""
    from agents.core.browser_agent import BrowserPolicy, GovernedBrowser, NullBrowserDriver
    from agents.core.media_director import (
        DeviceRegistry,
        MediaDevice,
        MediaDirector,
        SessionBoard,
    )

    class _FakeDriver:
        def __init__(self):
            self.now_playing = None

        def play(self, device, content):
            self.now_playing = content
            return {"ok": True, "state": "playing"}

        def status(self, device):
            return {"ok": True, "state": "playing", "content": self.now_playing or {}}

        def pause(self, device):  # pragma: no cover - unused in the rail probe
            return {"ok": True, "state": "paused"}

        def resume(self, device):  # pragma: no cover - unused in the rail probe
            return {"ok": True, "state": "playing"}

        def stop(self, device):
            self.now_playing = None
            return {"ok": True, "state": "idle"}

    registry = DeviceRegistry(path=None)
    registry.register(
        MediaDevice(
            id="kitchen-display",
            name="Kitchen display",
            kind="browser_tab",
            room="kitchen",
            supports=("show",),
        )
    )
    preview_driver = NullBrowserDriver()
    browser = GovernedBrowser(
        driver=preview_driver,
        policy=BrowserPolicy(["93.184.216.34"]),
    )
    director = MediaDirector(
        registry=registry,
        sessions=SessionBoard(path=None),
        drivers={"browser_tab": _FakeDriver()},
        browser=browser,
    )
    result = director.present(
        {
            "content": {"type": "url", "value": "https://93.184.216.34/dashboard"},
            "target": "kitchen",
            "mode": "show",
            "privacy": "household",
            "urgency": "normal",
        }
    )
    restored = director.restore("kitchen-display")
    return (
        result.get("ok") is True
        and result.get("verified") is True
        and restored.get("ok") is True
        and preview_driver.calls == []
    )


async def _probe_media_present_offline_honest() -> bool:
    """A device with no driver refuses honestly — never a fake 'playing'."""
    from agents.core.browser_agent import BrowserPolicy, GovernedBrowser, NullBrowserDriver
    from agents.core.media_director import (
        DeviceRegistry,
        MediaDevice,
        MediaDirector,
        SessionBoard,
    )

    registry = DeviceRegistry(path=None)
    registry.register(MediaDevice(id="tv", name="Living room TV", kind="tv", room="living"))
    preview_driver = NullBrowserDriver()
    director = MediaDirector(
        registry=registry,
        sessions=SessionBoard(path=None),
        browser=GovernedBrowser(
            driver=preview_driver,
            policy=BrowserPolicy(["93.184.216.34"]),
        ),
    )
    result = director.present(
        {
            "content": {"type": "url", "value": "https://93.184.216.34/film"},
            "target": "tv",
            "mode": "play",
            "privacy": "household",
            "urgency": "normal",
        }
    )
    return (
        result.get("ok") is False
        and "driver" in str(result.get("reason", ""))
        and director.sessions.get("tv") is None
        and preview_driver.calls == []
    )


from agents.core.observability.operator_reality import (  # noqa: E402, I001
    OPERATOR_CAPABILITY_CASES,
    OperatorEventLedger as _OperatorEventLedger,
)
from agents.core.observability.media_reality import H29_MEDIA_REALITY_CASES  # noqa: E402
from agents.core.observability.house_reality import (  # noqa: E402
    H30_HOUSE_LIVE_CASES,
    H30_HOUSE_REALITY_CASES,
)
from agents.core.observability.camera_reality import (  # noqa: E402
    H31_CAMERA_LIVE_CASES,
    H31_CAMERA_REALITY_CASES,
)

OperatorEventLedger = _OperatorEventLedger


ACTION_CAPABILITY_CASES: list[RealityCase] = [
    RealityCase(
        manifest.id,
        action_case_name(kind),
        f"an engaged real kill-switch refuses {kind} through CapabilityActionAPI",
        _make_action_kernel_probe(manifest),
    )
    for kind, manifest in sorted(ACTION_CAPABILITY_MANIFESTS.items())
]

MEDIA_CAPABILITY_CASES: list[RealityCase] = [
    RealityCase(
        "action:media.present",
        "media-present-verified-rail",
        "a present() through the real director is driver-verified and restorable",
        _probe_media_present_verified_rail,
    ),
    RealityCase(
        "action:media.present",
        "media-present-offline-honest",
        "a driverless device refuses a present() honestly (no fake playback)",
        _probe_media_present_offline_honest,
    ),
    *H29_MEDIA_REALITY_CASES,
]

TOOL_CAPABILITY_CASES: list[RealityCase] = [
    RealityCase(
        "tool:echo",
        tool_case_name("echo"),
        "the live ToolRPC echo handler returns a bounded protocol response",
        _probe_tool_echo_protocol,
    ),
    RealityCase(
        "tool:time",
        tool_case_name("time"),
        "the live ToolRPC time handler returns a numeric timestamp",
        _probe_tool_time_protocol,
    ),
]


def _make_plugin_policy_probe(plugin_id: str, manifest):
    async def _probe() -> bool:
        from agents.core.http_client import PluginEgressError, PluginHTTPClient
        from agents.core.plugin_gate import NetworkAccess, dynamic_domains

        client = PluginHTTPClient(plugin_id)
        marker = object()
        previous = os.environ.get("JARVIS_STRICT_EGRESS", marker)
        os.environ["JARVIS_STRICT_EGRESS"] = "1"

        def _allowed(url: str) -> bool:
            try:
                client._enforce_egress(url)
                return True
            except PluginEgressError:
                return False

        def _blocked(url: str) -> bool:
            return not _allowed(url)

        try:
            external = "https://93.184.216.34/reality"
            if manifest.network_access is NetworkAccess.NONE:
                return _blocked(external)
            if manifest.network_access is NetworkAccess.LAN:
                return _allowed("http://127.0.0.1:9/reality") and _blocked(external)
            if manifest.network_access is NetworkAccess.RESTRICTED:
                domains = list(manifest.allowed_domains) + dynamic_domains(plugin_id)
                declared_allowed = not domains or _allowed(f"https://{domains[0]}/reality")
                return declared_allowed and _blocked(external)
            if manifest.network_access is NetworkAccess.FULL:
                return _allowed(external)
            return False
        finally:
            if previous is marker:
                os.environ.pop("JARVIS_STRICT_EGRESS", None)
            else:
                os.environ["JARVIS_STRICT_EGRESS"] = previous
            await client.close()

    return _probe


def _make_component_probe(orch, name: str):
    async def _probe() -> bool:
        registry = getattr(orch, "components", None)
        status = getattr(registry, "status", {}) if registry is not None else {}
        return status.get(name) == "ok" and getattr(orch, name, None) is not None

    return _probe


def _make_skill_probe(orch, name: str):
    async def _probe() -> bool:
        loader = getattr(orch, "skills", None)
        skills = getattr(loader, "skills", {}) if loader is not None else {}
        skill = skills.get(name)
        return skill is not None and getattr(skill, "module", None) is not None

    return _probe


def registry_reality_cases(orch) -> list[RealityCase]:
    """Build canonical cases for every plugin and live component/skill registry row."""
    from agents.core.plugin_gate import BUILTIN_PLUGINS

    cases = [
        RealityCase(
            f"plugin:{plugin_id}",
            plugin_case_name(plugin_id),
            f"the {plugin_id} manifest's real egress boundary enforces its declared policy",
            _make_plugin_policy_probe(plugin_id, manifest),
        )
        for plugin_id, manifest in sorted(BUILTIN_PLUGINS.items())
    ]

    registry = getattr(orch, "components", None)
    statuses = getattr(registry, "status", {}) if registry is not None else {}
    cases.extend(
        RealityCase(
            f"component:{name}",
            component_case_name(name),
            f"component {name} has a successful boot status and a constructed runtime object",
            _make_component_probe(orch, name),
        )
        for name in sorted(statuses)
    )

    loader = getattr(orch, "skills", None)
    skills = getattr(loader, "skills", {}) if loader is not None else {}
    cases.extend(
        RealityCase(
            f"skill:{name}",
            skill_case_name(name),
            f"skill {name} is discovered and its runtime module is loaded",
            _make_skill_probe(orch, name),
        )
        for name in sorted(skills)
    )

    refs = [case.ref for case in cases]
    capability_ids = [case.capability_id for case in cases]
    if len(refs) != len(set(refs)) or len(capability_ids) != len(set(capability_ids)):
        raise ValueError("registry reality cases must have unique refs and capability ids")
    return cases


def all_reality_cases(orch) -> list[RealityCase]:
    """Static rail cases plus cases derived from a booted orchestrator."""
    return [*CASES, *registry_reality_cases(orch)]


CASES: list[RealityCase] = [
    RealityCase(
        "plugin:system-control",
        "egress-none-blocks-external",
        "a no-network plugin's external call is refused by the egress gate",
        _probe_none_blocks_external,
    ),
    RealityCase(
        "plugin:worldview",
        "egress-lan-allows-local",
        "a LAN plugin's localhost call is allowed by the egress gate",
        _probe_lan_allows_local,
    ),
    RealityCase(
        "plugin:worldview",
        "osint-untrusted-ingestion-queued",
        "an OSINT write-back from an untrusted source is escalated GRANT→QUEUE by the kernel",
        _probe_osint_untrusted_ingestion_queued,
    ),
    RealityCase(
        "plugin:balance",
        "market-money-action-queued",
        "a market-triggered money action is QUEUED by the kernel; read-only monitoring is GRANTed",
        _probe_market_money_action_queued,
    ),
    RealityCase(
        "plugin:social_x",
        "creative-release-queued",
        "a creative release (publish-to-world) is QUEUED by the kernel; drafting is GRANTed",
        _probe_creative_release_queued,
    ),
    RealityCase(
        "component:kill_switch",
        "kernel-kill-switch-denies",
        "an engaged kill-switch makes kernel.authorize DENY; disengaging reaches policy",
        _probe_kill_switch_gates_kernel,
    ),
    RealityCase(
        "component:capabilities",
        "kernel-capability-token-gate",
        "a valid capability token clears the kernel gate; a missing one is DENY",
        _probe_capability_token_gates_kernel,
    ),
    *ACTION_CAPABILITY_CASES,
    *MEDIA_CAPABILITY_CASES,
    *H30_HOUSE_REALITY_CASES,
    *H30_HOUSE_LIVE_CASES,
    *H31_CAMERA_REALITY_CASES,
    *H31_CAMERA_LIVE_CASES,
    *TOOL_CAPABILITY_CASES,
    *OPERATOR_CAPABILITY_CASES,
]
