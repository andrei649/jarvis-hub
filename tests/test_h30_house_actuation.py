"""H30.4 — governed Home Assistant actuation and strong confirmation."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
from types import SimpleNamespace

import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.house.actuation import (
    HOUSE_CONTROL_KIND,
    HOUSE_RECOVERY_KIND,
    HOUSE_SECURITY_KIND,
    HomeAssistantServiceDriver,
    HouseActuationError,
    HouseActuator,
    register_house_handlers,
)
from agents.core.house.confirmation import ConfirmationError, StrongConfirmationStore
from agents.core.house.contracts import HouseEntity, HouseSnapshot
from agents.core.kernel import Decision, Verdict
from agents.core.kernel.binding import MediationKernelBridge
from agents.core.security.secret_broker import SecretBroker

_CONFIRM_SECRET = "house-confirmation-key-material-that-is-long-enough"


def _broker() -> SecretBroker:
    broker = SecretBroker()
    broker.put("house_confirmation_key", _CONFIRM_SECRET)
    return broker


class _Kernel:
    def __init__(self, verdict=Verdict.GRANT):
        self.verdict = verdict
        self.actions = []

    def __call__(self, action, capability=None):
        self.actions.append((action, capability))
        return Decision(self.verdict, reason=f"kernel-{self.verdict.value}", tier=1)


class _Simulator:
    def __init__(self, *, entity_id="light.kitchen", state="off", now=100.0):
        self.entity_id = entity_id
        self.state = state
        self.attributes = {}
        self.now = now
        self.status = "live"
        self.calls = []
        self.apply_updates = True
        self.raise_after_apply = False
        self.forced_state_after_apply = None

    async def snapshot(self):
        entity = HouseEntity(
            entity_id=self.entity_id,
            domain=self.entity_id.split(".", 1)[0],
            name=self.entity_id,
            state=self.state,
            updated_at=self.now,
            attributes=tuple((key, str(value)) for key, value in self.attributes.items()),
        )
        return HouseSnapshot(
            enabled=True,
            status=self.status,
            observed_at=self.now,
            entities=(entity,),
        )

    async def apply(self, command):
        self.calls.append(dict(command))
        if self.apply_updates:
            action = command["action"]
            value = command.get("value")
            if command["control"] == "light":
                self.state = "on" if action == "on" else "off"
                if command.get("brightness_pct") is not None:
                    self.attributes["brightness_pct"] = command["brightness_pct"]
            elif command["control"] == "climate":
                if action == "set_mode":
                    self.state = str(value)
                else:
                    self.attributes["temperature"] = value
            elif command["control"] == "security":
                self.state = {
                    "lock": "locked",
                    "unlock": "unlocked",
                    "arm_home": "armed_home",
                    "arm_away": "armed_away",
                    "disarm": "disarmed",
                    "open": "open",
                    "close": "closed",
                }[action]
            if self.forced_state_after_apply is not None:
                self.state = self.forced_state_after_apply
                self.forced_state_after_apply = None
            self.now += 1.0
        if self.raise_after_apply:
            raise OSError("driver response lost")
        return {"ok": True, "transport_status": 200}


def _confirmation(tmp_path, *, clock=lambda: 100.0):
    return StrongConfirmationStore(tmp_path / "confirm.db", secret_broker=_broker(), clock=clock)


def _actuator(
    tmp_path,
    simulator,
    *,
    kernel=None,
    enqueue=None,
    outcomes=None,
    confirmation=None,
):
    return HouseActuator(
        state_reader=simulator,
        driver=simulator,
        authorizer=kernel or _Kernel(),
        enqueue=enqueue,
        outcome_provider=(lambda _cap: outcomes or {"total": 0, "confidence": 0.0}),
        confirmation_store=confirmation,
        ledger_path=tmp_path / "actuation.db",
        clock=lambda: simulator.now,
    )


@pytest.mark.asyncio
async def test_intake_is_canonical_bounded_and_never_actuates_inline(tmp_path):
    sim = _Simulator()
    actuator = _actuator(tmp_path, sim)

    preview = await actuator.request_light("light.kitchen", state="on", brightness_pct=35)

    assert preview["ok"] is True and preview["queued"] is False
    assert preview["payload"] == {
        "version": 1,
        "control": "light",
        "entity_id": "light.kitchen",
        "action": "on",
        "brightness_pct": 35,
        "risk_tier": 1,
        "reversible": True,
        "signal_quality": 1.0,
    }
    assert preview["preview"]["requires_approval"] is True
    assert sim.calls == []
    with pytest.raises(ValueError, match="entity"):
        await actuator.request_light("switch.kitchen", state="on")
    with pytest.raises(ValueError, match="brightness"):
        await actuator.request_light("light.kitchen", state="on", brightness_pct=101)
    with pytest.raises(ValueError, match="temperature"):
        await actuator.request_climate("climate.home", action="set_temperature", value=45)
    assert not hasattr(actuator, "call_service")


@pytest.mark.asyncio
async def test_low_confidence_waits_but_evidence_qualified_control_can_auto_queue(tmp_path):
    queued = []

    def enqueue(*args, **kwargs):
        queued.append((args, kwargs))
        return len(queued)

    sim = _Simulator()
    low = _actuator(tmp_path / "low", sim, enqueue=enqueue)
    earned = _actuator(
        tmp_path / "earned",
        sim,
        enqueue=enqueue,
        outcomes={"total": 20, "confidence": 0.9},
    )

    first = await low.request_light("light.kitchen", state="on")
    second = await earned.request_light("light.kitchen", state="on")

    assert first["autonomy_level"] == "ask"
    assert second["autonomy_level"] == "act"
    assert queued[0][1]["autonomy_level"] == "ask"
    assert queued[1][1]["autonomy_level"] == "act"


@pytest.mark.asyncio
async def test_security_hard_floor_never_auto_approves_even_with_perfect_outcomes(tmp_path):
    queued = []

    def enqueue(*args, **kwargs):
        queued.append(kwargs)
        return 7

    sim = _Simulator(entity_id="lock.front_door", state="locked")
    actuator = _actuator(
        tmp_path,
        sim,
        enqueue=enqueue,
        outcomes={"total": 1_000_000, "confidence": 1.0},
        confirmation=_confirmation(tmp_path),
    )

    result = await actuator.request_security("lock.front_door", action="unlock")

    assert result["task_id"] == 7
    assert result["autonomy_level"] == "ask"
    assert result["strong_confirmation_required"] is True
    assert queued[0]["risk_tier"] == 3
    assert queued[0]["autonomy_level"] == "ask"
    assert sim.calls == []


def test_confirmation_is_exact_expiring_durable_and_stores_only_receipt_hash(tmp_path):
    now = [100.0]
    store = _confirmation(tmp_path, clock=lambda: now[0])
    binding = {
        "task_id": 41,
        "capability": HOUSE_SECURITY_KIND,
        "target": "lock.front_door",
        "intended_state": "unlocked",
    }
    challenge = store.mint(**binding, ttl_seconds=30)

    with pytest.raises(ConfirmationError, match="binding"):
        store.confirm(challenge["token"], **{**binding, "target": "lock.back_door"})
    with pytest.raises(ConfirmationError, match="token"):
        store.confirm(challenge["token"] + "forged", **binding)

    confirmed = store.confirm(challenge["token"], **binding)
    receipt = confirmed["receipt"]
    raw_db = (tmp_path / "confirm.db").read_bytes()
    assert receipt.encode() not in raw_db
    assert store.consume(**{**binding, "task_id": 42}) is False

    restarted = _confirmation(tmp_path, clock=lambda: now[0])
    assert restarted.consume(**binding) is True
    assert restarted.consume(**binding) is False

    expired = restarted.mint(**{**binding, "task_id": 43}, ttl_seconds=5)
    now[0] = 200.0
    with pytest.raises(ConfirmationError, match="expired"):
        restarted.confirm(expired["token"], **{**binding, "task_id": 43})


@pytest.mark.asyncio
async def test_confirmation_atomic_consume_allows_only_one_concurrent_winner(tmp_path):
    store = _confirmation(tmp_path)
    binding = {
        "task_id": 50,
        "capability": HOUSE_SECURITY_KIND,
        "target": "lock.front_door",
        "intended_state": "unlocked",
    }
    challenge = store.mint(**binding)
    store.confirm(challenge["token"], **binding)

    async def consume():
        return await asyncio.to_thread(store.consume, **binding)

    assert sorted(await asyncio.gather(consume(), consume())) == [False, True]


@pytest.mark.asyncio
async def test_task_executor_revalidates_and_crosses_kernel_before_driver(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    sim = _Simulator()
    kernel = _Kernel()
    actuator = _actuator(tmp_path, sim, kernel=kernel)
    executor = register_house_handlers(TaskExecutor(), actuator)
    task = SimpleNamespace(
        id=1,
        kind=HOUSE_CONTROL_KIND,
        agent="jarvis",
        payload={
            "version": 1,
            "control": "light",
            "entity_id": "light.kitchen",
            "action": "on",
            "risk_tier": 1,
            "reversible": True,
            "signal_quality": 1.0,
        },
    )

    result = await executor.execute(task)

    assert result["status"] == "verified"
    assert [action.kind for action, _cap in kernel.actions] == [HOUSE_CONTROL_KIND]
    assert sim.calls and sim.state == "on"
    forged = SimpleNamespace(
        **{**task.__dict__, "id": 2, "payload": {**task.payload, "domain": "lock"}}
    )
    assert (await actuator.execute_task(forged))["reason"] == "invalid_payload"
    with pytest.raises(HouseActuationError, match="invalid_payload"):
        await executor.execute(forged)


@pytest.mark.asyncio
async def test_kernel_deny_or_queue_never_reaches_driver(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    payload = {
        "version": 1,
        "control": "light",
        "entity_id": "light.kitchen",
        "action": "on",
        "risk_tier": 1,
        "reversible": True,
        "signal_quality": 1.0,
    }
    for verdict in (Verdict.DENY, Verdict.QUEUE):
        sim = _Simulator()
        result = await _actuator(
            tmp_path / verdict.value, sim, kernel=_Kernel(verdict)
        ).execute_task(
            SimpleNamespace(id=10, kind=HOUSE_CONTROL_KIND, agent="jarvis", payload=payload)
        )
        assert result["status"] == "failed"
        assert result["reason"] == "kernel_denied"
        assert sim.calls == []


@pytest.mark.asyncio
async def test_security_execution_requires_exact_owner_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    sim = _Simulator(entity_id="lock.front_door", state="locked")
    confirmation = _confirmation(tmp_path)
    actuator = _actuator(tmp_path, sim, confirmation=confirmation)
    task = SimpleNamespace(
        id=70,
        kind=HOUSE_SECURITY_KIND,
        agent="jarvis",
        payload={
            "version": 1,
            "control": "security",
            "entity_id": "lock.front_door",
            "action": "unlock",
            "risk_tier": 3,
            "reversible": False,
            "signal_quality": 1.0,
        },
    )
    assert (await actuator.execute_task(task))["reason"] == "strong_confirmation_required"
    challenge = actuator.mint_confirmation(task)
    actuator.confirm(challenge["token"], task)

    verified = await actuator.execute_task(task)

    assert verified["status"] == "verified"
    assert sim.state == "unlocked"
    edited = SimpleNamespace(
        **{**task.__dict__, "id": 71, "payload": {**task.payload, "action": "lock"}}
    )
    assert (await actuator.execute_task(edited))["reason"] == "strong_confirmation_required"


@pytest.mark.asyncio
async def test_transport_success_without_state_change_rolls_back_and_never_claims_success(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    sim = _Simulator()
    sim.apply_updates = False
    actuator = _actuator(tmp_path, sim)
    task = SimpleNamespace(
        id=80,
        kind=HOUSE_CONTROL_KIND,
        agent="jarvis",
        payload={
            "version": 1,
            "control": "light",
            "entity_id": "light.kitchen",
            "action": "on",
            "risk_tier": 1,
            "reversible": True,
            "signal_quality": 1.0,
        },
    )

    result = await actuator.execute_task(task)

    assert result["status"] == "failed"
    assert result["verified"] is False
    assert result["reason"] == "verification_failed"
    assert result["rollback"]["status"] in {"not_needed", "verified"}


@pytest.mark.asyncio
async def test_lost_driver_response_is_decided_by_fresh_state_not_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    sim = _Simulator()
    sim.raise_after_apply = True
    actuator = _actuator(tmp_path, sim)
    task = SimpleNamespace(
        id=805,
        kind=HOUSE_CONTROL_KIND,
        agent="jarvis",
        payload={
            "version": 1,
            "control": "light",
            "entity_id": "light.kitchen",
            "action": "on",
            "risk_tier": 1,
            "reversible": True,
            "signal_quality": 1.0,
        },
    )

    result = await actuator.execute_task(task)

    assert result["status"] == "verified"
    assert sim.state == "on"


@pytest.mark.asyncio
async def test_climate_temperature_is_verified_from_fresh_attributes(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    sim = _Simulator(entity_id="climate.home", state="heat")
    actuator = _actuator(tmp_path, sim)
    task = SimpleNamespace(
        id=806,
        kind=HOUSE_CONTROL_KIND,
        agent="jarvis",
        payload={
            "version": 1,
            "control": "climate",
            "entity_id": "climate.home",
            "action": "set_temperature",
            "value": 22.5,
            "risk_tier": 1,
            "reversible": True,
            "signal_quality": 1.0,
        },
    )

    result = await actuator.execute_task(task)

    assert result["status"] == "verified"
    assert sim.attributes["temperature"] == 22.5


@pytest.mark.asyncio
async def test_partial_mutation_uses_kernel_mediated_verified_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    sim = _Simulator()
    sim.forced_state_after_apply = "jammed"
    kernel = _Kernel()
    actuator = _actuator(tmp_path, sim, kernel=kernel)
    task = SimpleNamespace(
        id=807,
        kind=HOUSE_CONTROL_KIND,
        agent="jarvis",
        payload={
            "version": 1,
            "control": "light",
            "entity_id": "light.kitchen",
            "action": "on",
            "risk_tier": 1,
            "reversible": True,
            "signal_quality": 1.0,
        },
    )

    result = await actuator.execute_task(task)

    assert result["status"] == "failed"
    assert result["rollback"] == {"status": "verified"}
    assert result["manual_recovery_required"] is False
    assert sim.state == "off"
    assert [action.kind for action, _cap in kernel.actions] == [
        HOUSE_CONTROL_KIND,
        HOUSE_RECOVERY_KIND,
    ]


@pytest.mark.asyncio
async def test_policy_change_can_block_recovery_and_marks_manual_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")

    class Kernel(_Kernel):
        def __call__(self, action, capability=None):
            self.actions.append((action, capability))
            verdict = Verdict.GRANT if action.kind == HOUSE_CONTROL_KIND else Verdict.DENY
            return Decision(verdict, reason="changed policy", tier=1)

    sim = _Simulator()
    sim.apply_updates = False
    actuator = _actuator(tmp_path, sim, kernel=Kernel())
    task = SimpleNamespace(
        id=81,
        kind=HOUSE_CONTROL_KIND,
        agent="jarvis",
        payload={
            "version": 1,
            "control": "light",
            "entity_id": "light.kitchen",
            "action": "on",
            "risk_tier": 1,
            "reversible": True,
            "signal_quality": 1.0,
        },
    )

    result = await actuator.execute_task(task)

    assert result["manual_recovery_required"] is False  # pre-state never changed
    sim.state = "on"
    sim.apply_updates = True
    sim.forced_state_after_apply = "jammed"
    second = await _actuator(tmp_path / "changed", sim, kernel=Kernel()).execute_task(
        SimpleNamespace(**{**task.__dict__, "id": 82, "payload": {**task.payload, "action": "off"}})
    )
    assert second["manual_recovery_required"] is True
    assert second["rollback"]["reason"] == "kernel_denied"


@pytest.mark.asyncio
async def test_retry_is_idempotent_and_stale_or_degraded_state_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    sim = _Simulator()
    actuator = _actuator(tmp_path, sim)
    task = SimpleNamespace(
        id=90,
        kind=HOUSE_CONTROL_KIND,
        agent="jarvis",
        payload={
            "version": 1,
            "control": "light",
            "entity_id": "light.kitchen",
            "action": "on",
            "risk_tier": 1,
            "reversible": True,
            "signal_quality": 1.0,
        },
    )
    first = await actuator.execute_task(task)
    second = await _actuator(tmp_path, sim).execute_task(task)
    assert first == second
    assert len(sim.calls) == 1

    sim.status = "degraded"
    blocked = await actuator.execute_task(SimpleNamespace(**{**task.__dict__, "id": 91}))
    assert blocked["reason"] == "house_state_not_live"
    sim.status = "live"
    sim.now = 1_000.0
    stale_reader = _Simulator(now=100.0)
    stale_actuator = HouseActuator(
        state_reader=stale_reader,
        driver=stale_reader,
        authorizer=_Kernel(),
        ledger_path=tmp_path / "stale.db",
        clock=lambda: 1_000.0,
    )
    assert (await stale_actuator.execute_task(SimpleNamespace(**{**task.__dict__, "id": 92})))[
        "reason"
    ] == "house_state_stale"


@pytest.mark.asyncio
async def test_home_assistant_driver_uses_narrow_service_mapping_only():
    calls = []

    async def service_call(domain, service, data):
        calls.append((domain, service, data))
        return {"ok": True, "transport_status": 200}

    driver = HomeAssistantServiceDriver(service_call=service_call)
    await driver.apply(
        {
            "control": "light",
            "entity_id": "light.kitchen",
            "action": "on",
            "brightness_pct": 45,
        }
    )
    await driver.apply(
        {
            "control": "security",
            "entity_id": "lock.front_door",
            "action": "unlock",
        }
    )

    assert calls == [
        ("light", "turn_on", {"entity_id": "light.kitchen", "brightness_pct": 45}),
        ("lock", "unlock", {"entity_id": "lock.front_door"}),
    ]
    with pytest.raises(ValueError, match="command"):
        await driver.apply({"control": "raw", "domain": "shell_command"})


@pytest.mark.asyncio
async def test_execution_ledger_releases_sqlite_handles_after_each_operation(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    simulator = _Simulator()
    actuator = _actuator(tmp_path, simulator)
    task = SimpleNamespace(
        id=999,
        kind=HOUSE_CONTROL_KIND,
        agent="jarvis",
        payload={
            "version": 1,
            "control": "light",
            "entity_id": "light.kitchen",
            "action": "on",
            "risk_tier": 1,
            "reversible": True,
            "signal_quality": 1.0,
        },
    )

    assert (await actuator.execute_task(task))["status"] == "verified"
    actuator._ledger.path.unlink()
    assert actuator._ledger.path.exists() is False


def test_confirmation_store_releases_sqlite_handles_after_each_operation(tmp_path):
    store = _confirmation(tmp_path)
    challenge = store.mint(
        task_id=1,
        capability=HOUSE_SECURITY_KIND,
        target="lock.front_door",
        intended_state="unlocked",
    )
    store.confirm(
        challenge["token"],
        task_id=1,
        capability=HOUSE_SECURITY_KIND,
        target="lock.front_door",
        intended_state="unlocked",
    )
    assert store.consume(
        task_id=1,
        capability=HOUSE_SECURITY_KIND,
        target="lock.front_door",
        intended_state="unlocked",
    )

    store.path.unlink()
    assert store.path.exists() is False


@pytest.mark.asyncio
async def test_default_off_house_intake_skips_worker_kernel_gate_and_enqueues_normally(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    simulator = _Simulator()
    queued = []

    def kernel_gate(_action):
        raise AssertionError("default-off house request reached worker.kernel_gate")

    def enqueue(*args, **kwargs):
        queued.append((args, kwargs))
        return 41

    actuator = HouseActuator(
        state_reader=simulator,
        driver=simulator,
        authorizer=_Kernel(),
        intake_authorizer=kernel_gate,
        enqueue=enqueue,
        ledger_path=tmp_path / "actuation.db",
        clock=lambda: simulator.now,
    )

    result = await actuator.request_light("light.kitchen", state="on")

    assert result["ok"] is True
    assert result["queued"] is True
    assert result["task_id"] == 41
    assert len(queued) == 1


@pytest.mark.asyncio
async def test_house_requests_have_authenticated_intake_evidence_and_preserve_execution_controls(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    class _House:
        now = 100.0

        def __init__(self):
            self.states = {"light.kitchen": "off", "lock.front_door": "locked"}
            self.calls = []

        async def snapshot(self):
            return HouseSnapshot(
                enabled=True,
                status="live",
                observed_at=self.now,
                entities=tuple(
                    HouseEntity(
                        entity_id=entity_id,
                        domain=entity_id.split(".", 1)[0],
                        name=entity_id,
                        state=state,
                        updated_at=self.now,
                    )
                    for entity_id, state in self.states.items()
                ),
            )

        async def apply(self, command):
            self.calls.append(dict(command))
            self.states[command["entity_id"]] = {
                "on": "on",
                "unlock": "unlocked",
            }[command["action"]]
            self.now += 1.0
            return {"ok": True}

    sim = _House()
    intake = _Kernel()
    execution = _Kernel()
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(
        queue,
        policy=type(
            "Policy",
            (), {"decide": lambda _self, _action: SimpleNamespace(outcome="act", tier=1, reason="ok")},
        )(),
        kernel=MediationKernelBridge(intake),
        mediation_signer=DetachedHMACSigner(
            lambda data: hmac.new(b"house-qa4-signer", data, hashlib.sha256).hexdigest()
        ),
        mediation_clock_ms=lambda: 1_786_662_000_000,
    )
    actuator = HouseActuator(
        state_reader=sim,
        driver=sim,
        authorizer=execution,
        intake_authorizer=worker.kernel_gate,
        enqueue=worker.govern_enqueue,
        confirmation_store=_confirmation(tmp_path),
        ledger_path=tmp_path / "actuation.db",
        clock=lambda: sim.now,
    )
    executor = register_house_handlers(TaskExecutor(execution_guard=worker.execution_allowed), actuator)
    worker.executor = executor.execute

    light = await actuator.request_light("light.kitchen", state="on")
    security = await actuator.request_security("lock.front_door", action="unlock")
    await worker.apply_decision(light["task_id"], "accept")
    security_task = queue.get(security["task_id"])
    challenge = actuator.mint_confirmation(security_task)
    actuator.confirm(challenge["token"], security_task)
    await worker.apply_decision(security_task.id, "accept")

    summary = await worker.tick()

    assert light["queued"] is security["queued"] is True
    assert queue.get(light["task_id"]).kernel_intake_evidence is not None
    assert queue.get(security["task_id"]).kernel_intake_evidence is not None
    assert summary["done"] == 2
    assert [action.kind for action, _capability in intake.actions] == [
        HOUSE_CONTROL_KIND,
        HOUSE_SECURITY_KIND,
    ]
    assert [action.kind for action, _capability in execution.actions] == [
        HOUSE_CONTROL_KIND,
        HOUSE_SECURITY_KIND,
    ]


@pytest.mark.asyncio
async def test_queued_house_intake_cannot_be_auto_approved_by_permissive_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    simulator = _Simulator()
    intake = _Kernel(Verdict.QUEUE)
    execution = _Kernel()
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(
        queue,
        policy=type(
            "Policy",
            (),
            {"decide": lambda _self, _action: SimpleNamespace(outcome="act", tier=1, reason="ok")},
        )(),
        kernel=MediationKernelBridge(intake),
    )
    actuator = HouseActuator(
        state_reader=simulator,
        driver=simulator,
        authorizer=execution,
        intake_authorizer=worker.kernel_gate,
        enqueue=worker.govern_enqueue,
        outcome_provider=lambda _capability: {"total": 20, "confidence": 0.9},
        ledger_path=tmp_path / "actuation.db",
        clock=lambda: simulator.now,
    )
    executor = register_house_handlers(TaskExecutor(execution_guard=worker.execution_allowed), actuator)
    worker.executor = executor.execute

    request = await actuator.request_light("light.kitchen", state="on")
    task = queue.get(request["task_id"])
    summary = await worker.tick()

    assert request["autonomy_level"] == "act"
    assert task.status == "blocked"
    assert task.autonomy_level == "ask"
    assert summary["ran"] == 0
    assert simulator.calls == []
