"""Action-auth matrix gate (ORIZONT-24 Gate K seed; mirrors test_route_auth_matrix).

Routes have a runtime registry (app.routes) that the route-auth matrix introspects;
privileged *actions* don't, so this gates a curated registry whose enumeration is
runtime-derived from the brokers' KIND constants. Three tests, same shape as the
route-auth suite:

  1. registry matches its snapshot (a change must be conscious);
  2. every broker action kind is classified (a new privileged broker fails CI) —
     acceptance criterion 5;
  3. honest mediation: KERNEL kinds actually invoke the kernel; PENDING kinds don't.
"""

import inspect
import json
from pathlib import Path

import pytest

from agents.core.kernel import Decision, Verdict
from agents.core.kernel.registry import (
    ACTION_REGISTRY,
    Mediation,
    classify,
    known_broker_action_kinds,
)

SNAP = Path(__file__).parent / "_snapshots" / "action_auth.json"

_KERNEL_KINDS = sorted(k for k, m in ACTION_REGISTRY.items() if m is Mediation.KERNEL)


def test_action_registry_matches_snapshot():
    snap = json.loads(SNAP.read_text())
    live = {k: v.value for k, v in ACTION_REGISTRY.items()}
    new = sorted(set(live) - set(snap))
    gone = sorted(set(snap) - set(live))
    drift = sorted(k for k in live if k in snap and live[k] != snap[k])
    problems = []
    if new:
        problems.append(f"NEW kinds (classify + add to snapshot): {new}")
    if gone:
        problems.append(f"REMOVED kinds (drop from snapshot): {gone}")
    if drift:
        problems.append("DRIFT: " + ", ".join(f"{k}: {snap[k]}->{live[k]}" for k in drift))
    assert not problems, (
        "Action-auth registry changed. If intended, regenerate "
        "tests/_snapshots/action_auth.json from agents/core/kernel/registry.py.\n"
        + "\n".join(problems)
    )


def test_every_broker_kind_classified():
    """A new broker action kind that isn't in ACTION_REGISTRY fails CI — route it
    through the kernel (KERNEL) or list it as PENDING_KERNEL with a reason."""
    unclassified = sorted(k for k in known_broker_action_kinds() if k not in ACTION_REGISTRY)
    assert not unclassified, (
        "Privileged broker action kind(s) with no classification:\n" + "\n".join(unclassified)
    )


def test_desktop_step_is_registered_as_kernel_mediated():
    assert ACTION_REGISTRY.get("desktop.step") is Mediation.KERNEL


class _SpyKernel:
    """Stand-in for the bound kernel.authorize — records the Action it's handed."""

    def __init__(self, verdict=Verdict.GRANT):
        self.calls = []
        self._verdict = verdict

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self._verdict, reason="spy", tier=(action.payload or {}).get("risk_tier"))


def _exercise(kind, spy, tmp_path, monkeypatch=None):
    """Drive the broker/route that owns *kind* through its real entry-point."""
    if kind == "call.outbound":
        from agents.core.autonomy.call_broker import CallBroker

        CallBroker(enqueue=lambda *a, **k: 1, kernel=spy).request(
            to="+15551234567", message="hi", provider="twilio"
        )
    elif kind == "social.*":
        from agents.core.social import SocialBroker

        SocialBroker(enqueue=lambda *a, **k: 1, kernel=spy).request("x", "post", {"text": "hi"})
    elif kind == "writeback.*":
        from agents.core.writeback import WriteBackBroker

        wb = WriteBackBroker(enqueue=lambda *a, **k: 1, kernel=spy)
        tgt = wb.targets()[0]
        wb.request(tgt["target"], tgt["action"], dict.fromkeys(tgt["required"], "x"))
    elif kind == "node.dispatch":
        from agents.core.node_mesh import NodeMesh
        from agents.core.security.capability import CapabilityBroker, KillSwitch

        nm = NodeMesh(
            capability_broker=CapabilityBroker(),
            kill_switch=KillSwitch(tmp_path / "kill.json"),
            enqueue=lambda *a, **k: 1,
            kernel=spy,
        )
        nm.register_node("n1", ["run"])
        nm.dispatch("n1", "run")
    elif kind == "payment":
        from agents.core.payments import PaymentBroker

        pb = PaymentBroker(path=str(tmp_path / "pay.json"), kernel=spy)
        # Only an *admissible* request reaches the kernel hook (mandate hard-caps gate
        # first), so set up a mandate that permits the request.
        m = pb.create_mandate(["acme"], per_payment_cap=100, total_cap=100, currency="EUR")
        pb.request_payment(m["id"], "acme", 10, currency="EUR")
    elif kind == "plugin.egress":
        # Not broker-backed: egress is mediated in http_client via an injected hook bound
        # to kernel.authorize. Drive the real _guard funnel with the production hook
        # wrapping the spy, then restore the global hook so other tests are unaffected.
        from agents.core import http_client as hc
        from agents.core.kernel.binding import make_egress_kernel_hook

        client = hc.PluginHTTPClient(plugin_name="egress_matrix_probe")
        hc.set_egress_kernel_hook(make_egress_kernel_hook(lambda: spy))
        try:
            client._guard("GET", "https://example.com/x")
        finally:
            hc.set_egress_kernel_hook(None)
    elif kind == "mcp.mutating":
        # An MCP mutating tool routes through the kernel after the identity gate.
        # Unlike legacy brokers, it now fails closed when the kernel flag is off;
        # that refusal is expected and still proves the spy was not consulted.
        import asyncio

        from agents.core.kernel import kernel_enabled
        from agents.core.mcp.route_tools import (
            MUTATING_ROUTE_ALLOWLIST,
            MutatingKernelError,
            MutatingRouteTool,
        )

        async def _invoke(_kwargs):
            return {"ok": True}

        tool = MutatingRouteTool(
            spec=MUTATING_ROUTE_ALLOWLIST[0],
            invoke=_invoke,
            auditor=type("_Audit", (), {"log": lambda self, _event: None})(),
            identity_check=lambda _t: True,
            kernel=spy,
        )
        try:
            asyncio.run(tool.call({"text": "x"}, token="ok"))
        except MutatingKernelError:
            if kernel_enabled():
                raise
    elif kind == "host.control":
        # Local-model start/load/unload crosses the shared lifecycle authorizer
        # immediately before controller execution. The authorizer is fail-closed
        # when the kernel rollout flag is off, so that matrix leg never consults
        # the spy and never reaches a host effect.
        from types import SimpleNamespace

        from agents.core.llm_control import authorize_local_model_lifecycle

        orch = SimpleNamespace(
            permission_gate=SimpleNamespace(
                check_call=lambda plugin, agent: (
                    plugin == "system-control" and agent == "jarvis"
                )
            ),
            audit=SimpleNamespace(log=lambda _event: None),
        )
        authorize_local_model_lifecycle(
            orch,
            "lmstudio",
            "load",
            "qwen2.5:7b",
            channel="web",
            kernel=spy,
        )
    elif kind == "tool.rpc":
        # A gated Tool-RPC call is mediated by the kernel before it can enqueue.
        import asyncio

        from agents.core.tool_rpc import ToolRPCServer

        async def _gated(_a):
            return {"ok": True}

        srv = ToolRPCServer(enqueue=lambda *a, **k: 1, kernel=spy)
        srv.register_tool("danger", _gated, gated=True)
        asyncio.run(srv.handle({"tool": "danger", "args": {}}))
    elif kind == "repo.sync":
        # Oracle external repo sync is an external-triggered host action. Use the real
        # bridge entry point, with git/test subprocess seams faked so the matrix stays
        # hermetic.
        import asyncio

        from agents.core.plugins import oracle_bridge
        from agents.core.plugins.oracle_bridge import OracleBridgePlugin

        monkeypatch.setattr(oracle_bridge, "SESSION_FILE", tmp_path / "oracle-sessions.json")
        monkeypatch.setattr(oracle_bridge, "FILE_HASH_FILE", tmp_path / "oracle-file-hashes.json")
        bridge = OracleBridgePlugin(github_token="", kernel=spy)
        bridge._git_pull = lambda: (True, "")
        bridge._scan_file_hashes = lambda: None
        bridge._run_tests = lambda: (1, 1, 0, "")
        asyncio.run(
            bridge._process_claude_commit(
                "c" * 40,
                "feat: external repo sync",
                author_login="claude",
                trigger_verified=True,
            )
        )
    elif kind in ("admin.kill_switch", "admin.capability_issue"):
        # HTTP routes (not brokers/hooks): drive the REAL handler with a stub Request +
        # a tmp_path-backed orch, injecting the spy by monkeypatching the production
        # binding (make_action_kernel) the helper calls — no test-only seam. Branch on the
        # EXACT kind so each handler emits its own action kind (the two share the 'admin'
        # prefix, which the matrix's prefix assertion can't otherwise distinguish).
        import asyncio

        import agents.web as web
        from agents.core.autonomy.policy import AutonomyPolicy
        from agents.core.routers import security as secmod
        from agents.core.security.capability import CapabilityBroker, KillSwitch

        class _Orch:
            kill_switch = KillSwitch(tmp_path / "kill.json")
            capabilities = CapabilityBroker()
            autonomy_policy = AutonomyPolicy()
            intent_log = None

        class _Req:
            def __init__(self, body):
                self._b, self.headers = body, {}

            async def json(self):
                return self._b

        monkeypatch.setattr(web, "orch", _Orch())
        monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel", lambda orch: spy)
        assert secmod.get_orch() is not None, "stub orch not visible to the handler"
        if kind == "admin.kill_switch":
            asyncio.run(secmod.kill_switch_set(_Req({"engage": True, "scope": "global"})))
        else:
            asyncio.run(secmod.capabilities_issue(_Req({"capabilities": ["x"]})))
    elif kind == "kg.write":
        # Externally-driven KG write (HTTP route): drive the REAL kg_upsert_entity handler.
        # The stub orch must carry memory.graph so _kg() resolves (else 503 before the gate).
        import asyncio

        import agents.web as web
        from agents.core.autonomy.policy import AutonomyPolicy
        from agents.core.memory.graph import InMemoryGraph
        from agents.core.routers import memory_kg as memkg
        from agents.core.security.capability import CapabilityBroker, KillSwitch

        class _Mem:
            graph = InMemoryGraph()

        class _Orch:
            memory = _Mem()
            kill_switch = KillSwitch(tmp_path / "kill.json")
            capabilities = CapabilityBroker()
            autonomy_policy = AutonomyPolicy()
            intent_log = None

        class _Req:
            def __init__(self, body):
                self._b, self.headers = body, {}

            async def json(self):
                return self._b

        monkeypatch.setattr(web, "orch", _Orch())
        monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel", lambda o: spy)
        assert memkg._kg() is not None, "stub graph not visible to the handler"
        asyncio.run(memkg.kg_upsert_entity(_Req({"name": "Probe", "type": "person"})))
    elif kind in ("media.present", "media.restore"):
        # O29: Media Director actuation routes through the O27 facade. Drive the REAL
        # route handlers with an in-memory director + fake driver; the facade builds
        # its authorizer via the production make_action_kernel binding (spy-patched).
        # Only the media/unified-API flags are set here — the kernel flag stays
        # owned by the calling test so the kernel-off matrix leg still proves the
        # facade never touches the spy when the kernel is disabled.
        import asyncio

        import agents.web as web
        from agents.core.autonomy.policy import AutonomyPolicy
        from agents.core.media_director import (
            DeviceRegistry,
            MediaDevice,
            MediaDirector,
            MediaSession,
            SessionBoard,
        )
        from agents.core.routers import media_director as media_routes
        from agents.core.security.capability import CapabilityBroker, KillSwitch

        class _Driver:
            def play(self, device, content):
                return {"ok": True, "state": "playing"}

            def status(self, device):
                return {"ok": True, "state": "playing", "content": {}}

            def pause(self, device):
                return {"ok": True, "state": "paused"}

            def resume(self, device):
                return {"ok": True, "state": "playing"}

            def stop(self, device):
                return {"ok": True, "state": "idle"}

        class _Orch:
            kill_switch = KillSwitch(tmp_path / "kill.json")
            capabilities = CapabilityBroker()
            autonomy_policy = AutonomyPolicy()
            intent_log = None

        registry = DeviceRegistry(path=None)
        registry.register(MediaDevice(id="tv-1", name="TV", kind="tv", room="living"))
        director = MediaDirector(
            registry=registry, sessions=SessionBoard(path=None), drivers={"tv": _Driver()}
        )
        monkeypatch.setattr(media_routes, "_director", director)
        monkeypatch.setattr(web, "orch", _Orch())
        monkeypatch.setattr("agents.core.kernel.binding.make_action_kernel", lambda o: spy)
        monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
        monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
        if kind == "media.present":
            body = media_routes.PresentBody(
                content={"type": "url", "value": "https://example.local/x"}, target="tv-1"
            )
            asyncio.run(media_routes.media_present(body))
        else:
            director.sessions.set(
                MediaSession(
                    device_id="tv-1",
                    content={"type": "url", "value": "https://example.local/x"},
                    mode="play",
                    privacy="household",
                    started_at=1.0,
                )
            )
            asyncio.run(media_routes.media_restore("tv-1"))
    elif kind in ("house.control", "house.security_control", "house.recovery"):
        # O30: bounded house commands cross CapabilityActionAPI immediately before
        # the HA driver. Security adds an exact one-shot owner confirmation.
        import asyncio
        from types import SimpleNamespace

        from agents.core.capability_actions import PerformContext
        from agents.core.house.actuation import HouseActuator
        from agents.core.house.confirmation import StrongConfirmationStore
        from agents.core.house.contracts import HouseEntity, HouseSnapshot
        from agents.core.security.secret_broker import SecretBroker

        class _House:
            def __init__(self, entity_id, state):
                self.entity_id, self.state = entity_id, state

            async def snapshot(self):
                entity = HouseEntity(
                    entity_id=self.entity_id,
                    domain=self.entity_id.split(".", 1)[0],
                    name=self.entity_id,
                    state=self.state,
                    updated_at=100.0,
                )
                return HouseSnapshot(
                    enabled=True, status="live", observed_at=100.0, entities=(entity,)
                )

            async def apply(self, command):
                self.state = {
                    "on": "on",
                    "unlock": "unlocked",
                    "off": "off",
                }.get(command["action"], self.state)
                return {"ok": True}

        monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
        security = kind == "house.security_control"
        house = _House(
            "lock.front_door" if security else "light.kitchen", "locked" if security else "off"
        )
        broker = SecretBroker()
        broker.put("house_confirmation_key", "matrix-confirmation-key-material-long-enough")
        confirmations = StrongConfirmationStore(
            tmp_path / f"{kind}.confirm.db", secret_broker=broker, clock=lambda: 100.0
        )
        actuator = HouseActuator(
            state_reader=house,
            driver=house,
            authorizer=spy,
            confirmation_store=confirmations,
            ledger_path=tmp_path / f"{kind}.actuation.db",
            clock=lambda: 100.0,
        )
        payload = {
            "version": 1,
            "control": "security" if security else "light",
            "entity_id": house.entity_id,
            "action": "unlock" if security else "on",
            "risk_tier": 3 if security else 1,
            "reversible": not security,
            "signal_quality": 1.0,
        }
        if kind == "house.recovery":
            asyncio.run(
                actuator._actions.perform(
                    "action:house.recovery",
                    payload,
                    PerformContext(capability_name="house.recovery"),
                )
            )
        else:
            task = SimpleNamespace(id=1, kind=kind, agent="jarvis", payload=payload)
            if security:
                challenge = actuator.mint_confirmation(task)
                actuator.confirm(challenge["token"], task)
            asyncio.run(actuator.execute_task(task))
    elif kind == "channel.reply":
        # Safe Comms: a governed reply request crosses the kernel before it can
        # enqueue a draft (ChannelReplyBroker checks kernel_enabled() itself).
        from agents.core.channel_inbox import ChannelInboxStore
        from agents.core.channel_reply import ChannelReplyBroker

        inbox = ChannelInboxStore(tmp_path / "inbox.json")
        message = inbox.record_inbound("telegram", "ping", metadata={"chat_id": 42})
        broker = ChannelReplyBroker(inbox=inbox, enqueue=lambda *a, **k: 1, kernel=spy)
        result = broker.request(message["thread_id"], "pong")
        assert result["ok"] is True, result
    elif kind == "skill.install":
        # O32: promoting an acquired capability crosses the kernel via the SAME
        # production gate binding (make_skill_install_kernel_gate) before a
        # proposal exists; the permanent owner-approval floor stays after it.
        import asyncio
        from dataclasses import asdict

        from agents.core.acquisition.generator import (
            CapabilityContract,
            ContractCase,
            StrictLocalGenerator,
        )
        from agents.core.acquisition.promotion import (
            PromotionBroker,
            PromotionJournal,
            PromotionStore,
            make_skill_install_kernel_gate,
        )
        from agents.core.acquisition.quarantine import QuarantineStore
        from agents.core.acquisition.receipt import make_receipt
        from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
        from agents.core.acquisition.store import CapabilityRequestStore

        contract = CapabilityContract(
            goal="parse items",
            entrypoint="run",
            cases=(ContractCase(input={"items": [{"id": 1}]}, expected=[1]),),
        )
        requests = CapabilityRequestStore(root=tmp_path / "requests")
        request = requests.capture(contract.goal, agent_id="jarvis", reason="tool_not_allowed")
        requests.transition(request.request_id, "researching", actor="research")
        requests.transition(request.request_id, "quarantined", actor="generator")

        async def _generate(_prompt):
            return {
                "name": "matrix_item_parser",
                "entrypoint": "run",
                "code": "def run(payload):\n    return [i['id'] for i in payload.get('items', [])]\n",
                "test": (
                    "import unittest\n"
                    "from main import run\n\n"
                    "class T(unittest.TestCase):\n"
                    "    def test_items(self):\n"
                    "        self.assertEqual(run({'items': [{'id': 2}]}), [2])\n"
                ),
            }

        package = asyncio.run(
            StrictLocalGenerator(generate=_generate, route="strict-local").generate(
                request=request,
                grounded_plan={"fully_grounded": True, "source_hash": "b" * 64},
                contract=contract,
            )
        )
        profile = AcquisitionSandboxProfile(image="python:3.12-slim@sha256:" + "a" * 64)
        receipt = make_receipt(
            package=package,
            contract=contract,
            profile=profile,
            generated_test_output="ok",
            contract_output="ok",
            mutation_output="detected",
            generated_test_exit=0,
            contract_exit=0,
            mutation_exit=1,
            started_at=1.0,
            finished_at=2.0,
        )
        quarantine = QuarantineStore(root=tmp_path / "quarantine")
        quarantine.put(package)
        quarantine.transition(package.artifact_id, "verified", receipt=asdict(receipt))
        broker = PromotionBroker(
            enabled=lambda: True,
            quarantine=quarantine,
            requests=requests,
            proposals=PromotionStore(root=tmp_path / "proposals"),
            packages=None,
            journal=PromotionJournal(root=tmp_path / "journal"),
            tool_rpc=None,
            runtime=None,
            marketplace=None,
            profile=profile,
            kernel_gate=make_skill_install_kernel_gate(spy),
        )
        proposal = broker.propose(package.artifact_id, contract=contract)
        assert proposal.status == "pending"  # the owner floor holds even on GRANT
    elif kind == "desktop.step":
        # The optional real host seam must cross CapabilityActionAPI immediately
        # before driver execution. The unified facade stays default-off; the outer
        # matrix test owns the Action Kernel flag for its enabled/disabled legs.
        import asyncio

        from agents.core.desktop_operator import DesktopActionExecutor, GovernedDesktop

        class _Driver:
            requires_kernel = True

            def __init__(self):
                self.calls = []

            async def perform(self, action, args):
                self.calls.append((action, args))
                return {"ok": True}

        async def _allow(_action, _args):
            return True

        monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
        driver = _Driver()
        executor = DesktopActionExecutor(driver, authorizer=spy)
        result = asyncio.run(
            GovernedDesktop(driver=driver, action_executor=executor).run(
                [{"action": "click", "args": {"query": "OK"}}],
                approver=_allow,
            )
        )
        if spy.calls:
            assert driver.calls == [("click", {"query": "OK"})]
            assert result["ran"][0]["status"] == "ran"
        else:
            assert driver.calls == []
            assert result["ran"][0]["status"] == "blocked"
    else:  # pragma: no cover - a new KERNEL kind needs an exerciser added here
        raise AssertionError(f"no exerciser for kernel-classified kind {kind!r}")


@pytest.mark.parametrize("kind", _KERNEL_KINDS)
def test_kernel_kinds_actually_invoke_kernel(kind, monkeypatch, tmp_path):
    """Ground truth: a kind declared KERNEL must really route through the facade —
    a snapshot can't claim 'kernel' while the broker bypasses it."""
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel()
    _exercise(kind, spy, tmp_path, monkeypatch)
    assert spy.calls, f"{kind} is classified KERNEL but request() did not invoke the kernel"
    if kind.endswith(".*"):
        assert spy.calls[-1].kind.startswith(kind[:-1])
    else:
        assert spy.calls[-1].kind == kind


def test_kernel_off_does_not_invoke_kernel(monkeypatch, tmp_path):
    """Default-off: with the flag unset, no broker touches the kernel."""
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    for kind in _KERNEL_KINDS:
        spy = _SpyKernel()
        _exercise(kind, spy, tmp_path, monkeypatch)
        assert not spy.calls, f"{kind} invoked the kernel with the flag OFF"


def test_broker_kernel_wiring_matches_classification():
    """Honest mapping (ground truth) for the broker-backed kinds that aren't covered by
    the parametrized invoke test's exercisers: a KERNEL classification means the broker
    really accepts a `kernel` hook; a PENDING one means it genuinely doesn't yet — so the
    snapshot can never claim more (or less) migration than the code carries."""
    from agents.core.payments import PaymentBroker

    # kind → broker class (extend as more broker-backed kinds migrate).
    brokers = {"payment": PaymentBroker}
    for kind, cls in brokers.items():
        has_hook = "kernel" in inspect.signature(cls.__init__).parameters
        med = classify(kind)
        if med is Mediation.KERNEL:
            assert has_hook, f"{kind} is classified KERNEL but {cls.__name__} has no kernel hook"
        elif med is Mediation.PENDING_KERNEL:
            assert not has_hook, f"{kind} is PENDING_KERNEL but {cls.__name__} is already wired"
