"""H30 hermetic House Brain reality pack with causal zero-bypass evidence."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agents.core.observability.reality_types import RealityCase

_HOUSE_METADATA = {
    "suite": "h30-house",
    "mode": "hermetic",
    "expected_ungoverned_actions": 0,
    "live_owner_validation": "required",
    "promotable": False,
}
_HOUSE_LIVE_METADATA = {
    "suite": "h30-house",
    "mode": "owner-live",
    "expected_ungoverned_actions": 0,
    "promotable": False,
}
_HOST_SEAMS = ("ha_rest_read", "ha_websocket", "ha_service", "media_driver")
_NOW = 1_000.0
_HA_TOKEN = "-".join(("hermetic", "home-assistant", "fixture"))
_PRIVATE_KEY = "hermetic-house-private-key-material-that-is-long-enough"
_CONFIRM_KEY = "hermetic-house-confirm-key-material-that-is-long-enough"
_SATELLITE_TOKEN = "-".join(("hermetic", "paired-satellite", "fixture"))
_SATELLITE_PEER = "192.168.50.21"


class HouseEventLedger:
    """Causal mutation ledger; HA service calls also require an approved task."""

    _PHASES = {"attempt", "govern", "execute", "block", "host"}

    def __init__(self) -> None:
        self._events: list[dict[str, object]] = []
        self._host_calls = dict.fromkeys(_HOST_SEAMS, 0)
        self._approved_actions: dict[str, int] = {}
        self._active_action = ""

    @property
    def active_action(self) -> str:
        return self._active_action

    def activate(self, action_id: str) -> None:
        self._active_action = str(action_id)

    def clear_active(self, action_id: str = "") -> None:
        if not action_id or self._active_action == action_id:
            self._active_action = ""

    def approve(self, action_id: str, *, task_id: int, status: str) -> None:
        if status not in {"approved", "running"} or task_id <= 0:
            raise ValueError("house mutation does not originate from an approved task")
        self._approved_actions[str(action_id)] = int(task_id)

    def record(self, action_id: str, phase: str, seam: str) -> None:
        if not action_id or not seam or phase not in self._PHASES:
            raise ValueError("invalid house reality event")
        self._events.append(
            {
                "sequence": len(self._events) + 1,
                "action_id": str(action_id),
                "phase": phase,
                "seam": str(seam),
            }
        )

    def host_call(self, action_id: str, seam: str, *, governed: bool) -> None:
        if seam not in self._host_calls:
            raise ValueError("unknown house host seam")
        self._host_calls[seam] += 1
        if governed:
            self.record(action_id, "host", seam)

    def observe_host(self, seam: str) -> None:
        self.host_call("", seam, governed=False)

    def result(
        self,
        passed: bool,
        *,
        evidence: dict[str, object] | None = None,
    ) -> dict[str, object]:
        events = list(self._events)
        actions: dict[str, list[dict[str, object]]] = {}
        for event in events:
            actions.setdefault(str(event["action_id"]), []).append(event)

        attempted = [event for event in events if event["phase"] == "attempt"]
        governed = [event for event in events if event["phase"] == "govern"]
        executed = [event for event in events if event["phase"] == "execute"]
        blocked = [event for event in events if event["phase"] == "block"]
        causal = True
        ungoverned = 0
        unapproved = 0

        for action_id, action_events in actions.items():
            phases = [str(event["phase"]) for event in action_events]
            if phases.count("attempt") != 1 or phases.count("govern") > 1:
                causal = False
            if phases.count("execute") + phases.count("block") != 1:
                causal = False
            attempt_sequence = next(
                (int(event["sequence"]) for event in action_events if event["phase"] == "attempt"),
                None,
            )
            governance_sequence = next(
                (int(event["sequence"]) for event in action_events if event["phase"] == "govern"),
                None,
            )
            terminal_sequence = next(
                (
                    int(event["sequence"])
                    for event in action_events
                    if event["phase"] in {"execute", "block"}
                ),
                None,
            )
            causal = bool(
                causal
                and attempt_sequence is not None
                and terminal_sequence is not None
                and attempt_sequence < terminal_sequence
            )
            mutation_events = [
                event
                for event in action_events
                if event["phase"] in {"host", "execute"}
            ]
            if mutation_events and (
                governance_sequence is None
                or attempt_sequence is None
                or not attempt_sequence < governance_sequence
                or any(governance_sequence >= int(event["sequence"]) for event in mutation_events)
            ):
                ungoverned += 1
            if any(event["seam"] == "ha_service" for event in action_events) and (
                action_id not in self._approved_actions
            ):
                unapproved += 1

        counters = {
            "attempted_actions": len(attempted),
            "governance_checks": len(governed),
            "executed_actions": len(executed),
            "blocked_actions": len(blocked),
            "ungoverned_actions": ungoverned,
        }
        invariant = (
            causal
            and ungoverned == 0
            and unapproved == 0
            and counters["attempted_actions"]
            == counters["executed_actions"] + counters["blocked_actions"]
        )
        host_calls = dict(self._host_calls)
        metadata: dict[str, object] = {
            "counters": counters,
            "events": events,
            "host_calls": host_calls,
            "host_call_count": sum(host_calls.values()),
            "unapproved_host_actions": unapproved,
            "approved_task_bindings": dict(self._approved_actions),
        }
        metadata.update(dict(evidence or {}))
        return {"passed": bool(passed and invariant), "metadata": metadata}


class _Response:
    def __init__(self, payload, *, status: int = 200, url: str = "") -> None:
        self._payload = payload
        self.status_code = status
        self.url = url

    def json(self):
        return self._payload


class _WSConnection:
    def __init__(self, frames) -> None:
        self.frames = list(frames)
        self.sent: list[dict] = []
        self.closed = False

    async def recv(self):
        if not self.frames:
            raise ConnectionError("hermetic websocket closed")
        frame = self.frames.pop(0)
        if isinstance(frame, BaseException):
            raise frame
        return json.dumps(frame) if isinstance(frame, dict) else frame

    async def send(self, frame) -> None:
        self.sent.append(json.loads(frame))

    async def close(self) -> None:
        self.closed = True


class _WebsocketTransport:
    def __init__(self, simulator: _HomeAssistantSimulator) -> None:
        self._simulator = simulator
        self.connections: list[object] = []

    async def connect(self, _url: str, **_kwargs):
        self._simulator.ledger.observe_host("ha_websocket")
        if not self.connections:
            raise ConnectionError("hermetic HA websocket offline")
        connection = self.connections.pop(0)
        if isinstance(connection, BaseException):
            raise connection
        return connection


class _HomeAssistantSimulator:
    """In-memory REST/WS host edge reached by the real H30 adapter/driver."""

    def __init__(
        self,
        ledger: HouseEventLedger,
        *,
        entity_id: str = "light.kitchen",
        state: str = "off",
    ) -> None:
        self.ledger = ledger
        self.entity_id = entity_id
        self.state = state
        self.attributes: dict[str, object] = {}
        self.now = _NOW
        self.offline = False
        self.jam_primary_once = False
        self.service_calls: list[tuple[str, str, dict]] = []
        self.websocket = _WebsocketTransport(self)

    def _states(self) -> list[dict]:
        domain = self.entity_id.split(".", 1)[0]
        return [
            {
                "entity_id": self.entity_id,
                "state": self.state,
                "last_updated": self.now,
                "attributes": {
                    "friendly_name": self.entity_id,
                    "area_id": "kitchen",
                    "area_name": "Kitchen",
                    "device_class": domain,
                    **self.attributes,
                },
            }
        ]

    def _mutate(self, domain: str, service: str, data: dict) -> None:
        if domain == "light" and service in {"turn_on", "turn_off"}:
            if self.jam_primary_once and service == "turn_on":
                self.state = "jammed"
                self.jam_primary_once = False
            else:
                self.state = "on" if service == "turn_on" else "off"
            if "brightness_pct" in data:
                self.attributes["brightness_pct"] = data["brightness_pct"]
        elif domain == "lock" and service in {"lock", "unlock"}:
            self.state = "locked" if service == "lock" else "unlocked"
        else:
            raise AssertionError(f"unexpected hermetic HA service: {domain}.{service}")
        self.now += 1.0

    async def request(self, method: str, url: str, **kwargs):
        if method == "GET" and url.endswith("/api/states"):
            self.ledger.observe_host("ha_rest_read")
            if self.offline:
                raise ConnectionError("hermetic HA offline")
            return _Response(self._states(), url="http://192.168.1.44:8123/api/states")
        if method == "POST" and "/api/services/" in url:
            action_id = self.ledger.active_action or "unguarded-ha-service"
            self.ledger.host_call(action_id, "ha_service", governed=True)
            if not self.ledger.active_action:
                raise AssertionError("HA mutation attempted without an active kernel action")
            path = url.split("/api/services/", 1)[1]
            domain, service = path.split("/", 1)
            data = dict(kwargs.get("json") or {})
            self.service_calls.append((domain, service, data))
            self._mutate(domain, service, data)
            self.ledger.record(action_id, "execute", "home-assistant-service")
            self.ledger.clear_active(action_id)
            return _Response({}, url=url)
        raise AssertionError(f"unexpected hermetic HA request: {method} {url}")


def _resolver(host: str, _port: int) -> list[str]:
    if host != "ha.home.local":
        raise AssertionError(f"unexpected HA host: {host}")
    return ["192.168.1.44"]


def _secret_broker():
    from agents.core.security.secret_broker import SecretBroker

    broker = SecretBroker()
    broker.put("home_assistant_token", _HA_TOKEN)
    broker.put("house_private_key", _PRIVATE_KEY)
    broker.put("house_confirmation_key", _CONFIRM_KEY)
    return broker


def _adapter(simulator: _HomeAssistantSimulator, *, sleep=None):
    from agents.core.house.home_assistant import HomeAssistantAdapter

    return HomeAssistantAdapter(
        env={
            "JARVIS_HOUSE_BRAIN": "1",
            "JARVIS_HOME_ASSISTANT": "1",
            "JARVIS_HA_URL": "http://ha.home.local:8123",
            "JARVIS_HA_TOKEN_REF": "{{secret:" + "home_assistant_token}}",
            "JARVIS_HA_ALLOWED_HOSTS": "ha.home.local",
        },
        resolver=_resolver,
        rest=simulator,
        websocket=simulator.websocket,
        secret_broker=_secret_broker(),
        clock=lambda: simulator.now,
        sleep=sleep,
    )


class _MeasuredAuthorizer:
    def __init__(
        self,
        ledger: HouseEventLedger,
        *,
        prefix: str,
        task=None,
        kill_switch=None,
    ) -> None:
        self.ledger = ledger
        self.prefix = prefix
        self.task = task
        self.kill_switch = kill_switch
        self.count = 0
        self.last_action_id = ""

    def __call__(self, action, capability=None, budget=None):
        from agents.core.autonomy.policy import ACT, AutonomyPolicy, RiskTier
        from agents.core.kernel import Verdict, authorize

        self.count += 1
        action_id = f"{self.prefix}:{self.count}:{action.kind}"
        self.last_action_id = action_id
        self.ledger.record(action_id, "attempt", "capability-action-api")
        decision = authorize(
            action,
            capability,
            budget,
            kill_switch=self.kill_switch,
            policy=AutonomyPolicy(tier_outcomes=dict.fromkeys(RiskTier, ACT)),
        )
        self.ledger.record(action_id, "govern", "action-kernel")
        if self.task is not None:
            self.ledger.approve(
                action_id,
                task_id=int(self.task.id),
                status=str(self.task.status),
            )
        if decision.verdict is Verdict.GRANT:
            self.ledger.activate(action_id)
        else:
            self.ledger.record(action_id, "block", f"kernel-{decision.verdict.value}")
            self.ledger.clear_active(action_id)
        return decision


def _control_payload(entity_id: str = "light.kitchen", action: str = "on") -> dict:
    return {
        "version": 1,
        "control": "light",
        "entity_id": entity_id,
        "action": action,
        "risk_tier": 1,
        "reversible": True,
        "signal_quality": 1.0,
    }


def _security_payload() -> dict:
    return {
        "version": 1,
        "control": "security",
        "entity_id": "lock.front_door",
        "action": "unlock",
        "risk_tier": 3,
        "reversible": False,
        "signal_quality": 1.0,
    }


def _approved_task(queue, *, kind: str, payload: dict):
    from agents.core.autonomy.queue import TaskStatus

    task_id = queue.enqueue(
        "jarvis",
        kind,
        f"reality {kind}",
        payload=payload,
        risk_tier=int(payload["risk_tier"]),
        autonomy_level="ask",
        origin="generated",
    )
    return queue.transition(task_id, TaskStatus.APPROVED, decided_by="owner", decision="approve")


def _actuator(
    root: Path,
    simulator: _HomeAssistantSimulator,
    task,
    *,
    kill_switch=None,
    confirmations=None,
):
    from agents.core.house.actuation import HomeAssistantServiceDriver, HouseActuator

    adapter = _adapter(simulator)
    authorizer = _MeasuredAuthorizer(
        simulator.ledger,
        prefix=f"task-{task.id}",
        task=task,
        kill_switch=kill_switch,
    )
    actuator = HouseActuator(
        state_reader=adapter,
        driver=HomeAssistantServiceDriver(adapter=adapter),
        authorizer=authorizer,
        confirmation_store=confirmations,
        ledger_path=root / f"actuation-{task.id}.db",
        clock=lambda: simulator.now,
    )
    return actuator, authorizer


async def _probe_adapter_read_reconnect_offline() -> dict[str, object]:
    ledger = HouseEventLedger()
    simulator = _HomeAssistantSimulator(ledger)
    event = {
        "id": 7,
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "time_fired": simulator.now + 1,
            "data": {
                "entity_id": simulator.entity_id,
                "old_state": simulator._states()[0],
                "new_state": {**simulator._states()[0], "state": "on"},
            },
        },
    }
    connection = _WSConnection(
        [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
            event,
        ]
    )
    simulator.websocket.connections = [
        ConnectionError("first"),
        ConnectionError("second"),
        connection,
    ]
    delays: list[float] = []

    async def _sleep(delay: float) -> None:
        delays.append(delay)

    adapter = _adapter(simulator, sleep=_sleep)
    live = await adapter.snapshot()
    events = await adapter.collect_events(limit=1, reconnect_attempts=3)
    simulator.offline = True
    offline = await adapter.snapshot()
    passed = (
        live.status == "live"
        and len(live.entities) == 1
        and len(events) == 1
        and events[0].entity_id == "light.kitchen"
        and delays == [0.25, 0.5]
        and connection.closed
        and offline.status == "degraded"
        and offline.entities == ()
    )
    return ledger.result(passed, evidence={"reconnect_delays": delays})


async def _probe_graph_presence_privacy_purge() -> dict[str, object]:
    from agents.core.house.graph import HouseGraph
    from agents.core.house.presence import PresenceEvidence, PresenceInference
    from agents.core.house.private_store import PrivateHouseStore
    from agents.core.memory.graph import InMemoryGraph

    ledger = HouseEventLedger()
    simulator = _HomeAssistantSimulator(ledger)
    snapshot = await _adapter(simulator).snapshot()
    graph = HouseGraph(InMemoryGraph(), clock=lambda: simulator.now)
    projected = graph.project_snapshot(snapshot)
    with tempfile.TemporaryDirectory(prefix="reality-house-private-") as directory:
        private = PrivateHouseStore(
            Path(directory) / "private.enc",
            secret_broker=_secret_broker(),
            clock=lambda: simulator.now,
        )
        inference = PresenceInference(
            private,
            clock=lambda: simulator.now,
            private_rooms={"kitchen"},
        )
        outcome = inference.infer(
            "Alice Example",
            [
                PresenceEvidence(
                    source_event_id="reality-bluetooth",
                    category="bluetooth",
                    state="present",
                    room_id="kitchen",
                    occupant_ref="Alice Example",
                    observed_at=simulator.now - 5,
                    confidence=0.95,
                ),
                PresenceEvidence(
                    source_event_id="reality-motion",
                    category="motion",
                    state="present",
                    room_id="kitchen",
                    observed_at=simulator.now - 5,
                    confidence=0.95,
                ),
            ],
        )
        purged = private.purge_occupant(
            "Alice Example",
            consent_version="consent-v2",
            purged_at=simulator.now,
        )
        facts_after = private.query()
        passed = (
            projected["status"] == "projected"
            and graph.query_state(room_id="kitchen")["devices"][0]["entity_id"]
            == "light.kitchen"
            and outcome.decision.status == "present"
            and outcome.decision.room_id == ""
            and outcome.decision.privacy_context == "private"
            and purged["status"] == "purged"
            and facts_after == []
        )
    return ledger.result(
        passed,
        evidence={"private_facts_after_purge": len(facts_after)},
    )


async def _probe_approved_reversible_actuation() -> dict[str, object]:
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.house.actuation import HOUSE_CONTROL_KIND, register_house_handlers

    ledger = HouseEventLedger()
    simulator = _HomeAssistantSimulator(ledger)
    with tempfile.TemporaryDirectory(prefix="reality-house-control-") as directory:
        root = Path(directory)
        queue = TaskQueue(str(root / "tasks.db")).initialize()
        try:
            task = _approved_task(queue, kind=HOUSE_CONTROL_KIND, payload=_control_payload())
            actuator, _authorizer = _actuator(root, simulator, task)
            executor = register_house_handlers(TaskExecutor(), actuator)
            with patch.dict(
                os.environ,
                {"JARVIS_ACTION_KERNEL": "1", "JARVIS_UNIFIED_ACTION_API": "1"},
            ):
                result = await executor.execute(task)
            passed = (
                result.get("status") == "verified"
                and simulator.state == "on"
                and len(simulator.service_calls) == 1
                and executor.resolve(HOUSE_CONTROL_KIND) is not None
            )
        finally:
            queue.close()
    return ledger.result(passed, evidence={"approved_task_executor": passed})


async def _probe_security_strong_confirmation() -> dict[str, object]:
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.house.actuation import (
        HOUSE_SECURITY_KIND,
        HouseActuationError,
        register_house_handlers,
    )
    from agents.core.house.confirmation import StrongConfirmationStore

    ledger = HouseEventLedger()
    simulator = _HomeAssistantSimulator(
        ledger,
        entity_id="lock.front_door",
        state="locked",
    )
    with tempfile.TemporaryDirectory(prefix="reality-house-security-") as directory:
        root = Path(directory)
        queue = TaskQueue(str(root / "tasks.db")).initialize()
        try:
            task = _approved_task(queue, kind=HOUSE_SECURITY_KIND, payload=_security_payload())
            confirmations = StrongConfirmationStore(
                root / "confirm.db",
                secret_broker=_secret_broker(),
                clock=lambda: simulator.now,
            )
            actuator, _authorizer = _actuator(
                root,
                simulator,
                task,
                confirmations=confirmations,
            )
            executor = register_house_handlers(TaskExecutor(), actuator)
            floor_id = f"task-{task.id}:strong-confirmation-floor"
            ledger.record(floor_id, "attempt", "task-executor")
            ledger.record(floor_id, "govern", "strong-confirmation")
            with patch.dict(
                os.environ,
                {"JARVIS_ACTION_KERNEL": "1", "JARVIS_UNIFIED_ACTION_API": "1"},
            ):
                try:
                    await executor.execute(task)
                except HouseActuationError as exc:
                    floor_refused = "strong_confirmation_required" in str(exc)
                else:
                    floor_refused = False
                ledger.record(floor_id, "block", "strong-confirmation")
                challenge = actuator.mint_confirmation(task)
                actuator.confirm(challenge["token"], task)
                verified = await executor.execute(task)
            consumed = not confirmations.consume(
                task_id=task.id,
                capability=HOUSE_SECURITY_KIND,
                target="lock.front_door",
                intended_state="unlocked",
            )
            passed = (
                floor_refused
                and verified.get("status") == "verified"
                and simulator.state == "unlocked"
                and len(simulator.service_calls) == 1
                and consumed
            )
        finally:
            queue.close()
    return ledger.result(passed, evidence={"strong_confirmation_consumed": consumed})


async def _probe_verification_rollback() -> dict[str, object]:
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.house.actuation import (
        HOUSE_CONTROL_KIND,
        HouseActuationError,
        register_house_handlers,
    )

    ledger = HouseEventLedger()
    simulator = _HomeAssistantSimulator(ledger)
    simulator.jam_primary_once = True
    with tempfile.TemporaryDirectory(prefix="reality-house-rollback-") as directory:
        root = Path(directory)
        queue = TaskQueue(str(root / "tasks.db")).initialize()
        try:
            task = _approved_task(queue, kind=HOUSE_CONTROL_KIND, payload=_control_payload())
            actuator, _authorizer = _actuator(root, simulator, task)
            executor = register_house_handlers(TaskExecutor(), actuator)
            with patch.dict(
                os.environ,
                {"JARVIS_ACTION_KERNEL": "1", "JARVIS_UNIFIED_ACTION_API": "1"},
            ):
                try:
                    await executor.execute(task)
                except HouseActuationError as exc:
                    failed_honestly = "verification_failed" in str(exc)
                else:
                    failed_honestly = False
                cached = await actuator.execute_task(task)
            rollback_status = str(cached.get("rollback", {}).get("status", ""))
            passed = (
                failed_honestly
                and cached.get("status") == "failed"
                and cached.get("verified") is False
                and rollback_status == "verified"
                and simulator.state == "off"
                and len(simulator.service_calls) == 2
            )
        finally:
            queue.close()
    return ledger.result(passed, evidence={"rollback_status": rollback_status})


async def _probe_kernel_halt() -> dict[str, object]:
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.house.actuation import (
        HOUSE_CONTROL_KIND,
        HouseActuationError,
        register_house_handlers,
    )
    from agents.core.security.capability import KillSwitch

    ledger = HouseEventLedger()
    simulator = _HomeAssistantSimulator(ledger)
    with tempfile.TemporaryDirectory(prefix="reality-house-halt-") as directory:
        root = Path(directory)
        queue = TaskQueue(str(root / "tasks.db")).initialize()
        try:
            task = _approved_task(queue, kind=HOUSE_CONTROL_KIND, payload=_control_payload())
            kill_switch = KillSwitch(path=str(root / "kill.json"))
            kill_switch.engage("global", reason="H30 house reality")
            actuator, _authorizer = _actuator(
                root,
                simulator,
                task,
                kill_switch=kill_switch,
            )
            executor = register_house_handlers(TaskExecutor(), actuator)
            with patch.dict(
                os.environ,
                {"JARVIS_ACTION_KERNEL": "1", "JARVIS_UNIFIED_ACTION_API": "1"},
            ):
                try:
                    await executor.execute(task)
                except HouseActuationError as exc:
                    refused = "kernel_denied" in str(exc)
                else:
                    refused = False
            passed = refused and simulator.service_calls == [] and simulator.state == "off"
        finally:
            queue.close()
    return ledger.result(
        passed,
        evidence={"ha_service_calls": len(simulator.service_calls)},
    )


def _reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


class _PeerWriter:
    def __init__(self) -> None:
        self.buf = bytearray()

    def write(self, data: bytes) -> None:
        self.buf.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_extra_info(self, name: str, default=None):
        return (_SATELLITE_PEER, 10700) if name == "peername" else default


async def _probe_room_output_governed() -> dict[str, object]:
    from agents.core.capability_actions import CapabilityActionAPI, PerformContext
    from agents.core.media_director import (
        DeviceRegistry,
        MediaDevice,
        MediaDirector,
        SessionBoard,
        register_media_capability,
    )
    from agents.core.satellite_hub import SatelliteHub, SatellitePairing
    from agents.core.voice.wyoming import (
        RoomVoiceContextResolver,
        WyomingEvent,
        WyomingServer,
        encode_event,
        read_event,
    )

    ledger = HouseEventLedger()
    authorizer = _MeasuredAuthorizer(ledger, prefix="room-media")
    resolved_targets: list[str] = []
    performed = []

    class _Driver:
        supports_duration = False

        def __init__(self) -> None:
            self.content = None

        def play(self, _device, content, *, duration_seconds=None):
            ledger.host_call(ledger.active_action, "media_driver", governed=True)
            self.content = dict(content)
            return {"ok": True, "state": "playing"}

        def status(self, _device):
            ledger.host_call(ledger.active_action, "media_driver", governed=True)
            return {"ok": True, "state": "playing", "content": dict(self.content or {})}

    pairing = SatellitePairing.from_token(
        satellite_id="sat-kitchen",
        room_id="kitchen",
        token=_SATELLITE_TOKEN,
        allowed_peer=_SATELLITE_PEER,
        allowed_transport="wyoming",
        expires_at=_NOW + 600,
    )
    hub = SatelliteHub(pairings=(pairing,), clock=lambda: _NOW)

    with tempfile.TemporaryDirectory(prefix="reality-house-room-") as directory:
        root = Path(directory)
        media = root / "announcement.wav"
        media.write_bytes(b"hermetic-room-announcement")
        registry = DeviceRegistry(path=None)
        registry.register(
            MediaDevice(
                id="speaker-kitchen",
                name="Kitchen speaker",
                kind="speaker",
                room="kitchen",
                supports=("announce",),
                room_default=True,
            )
        )
        api = CapabilityActionAPI(authorizer=authorizer)
        register_media_capability(
            api,
            MediaDirector(
                registry=registry,
                sessions=SessionBoard(path=None),
                drivers={"speaker": _Driver()},
                local_roots=(root,),
                clock=lambda: _NOW,
            ),
        )

        async def _handler(_text, context):
            resolved_targets.append(context.default_media_target)
            result = await api.perform(
                "action:media.present",
                {
                    "content": {"type": "local", "value": str(media)},
                    "target": context.default_media_target,
                    "mode": "announce",
                    "privacy": "household",
                    "urgency": "normal",
                },
                PerformContext(agent="jarvis", title="room announcement", origin="user"),
            )
            performed.append(result)
            ledger.record(
                authorizer.last_action_id,
                "execute" if result.status == "completed" else "block",
                "media-director-result",
            )
            ledger.clear_active(authorizer.last_action_id)
            return "announced"

        server = WyomingServer.room_aware(
            enabled=True,
            satellite_hub=hub,
            context_resolver=RoomVoiceContextResolver(
                registry,
                privacy_provider=lambda _room: "normal",
            ),
            handler=_handler,
        )

        def _auth(nonce: str, credential: str = _SATELLITE_TOKEN) -> WyomingEvent:
            return WyomingEvent(
                "satellite-auth",
                {
                    "satellite_id": "sat-kitchen",
                    "credential": credential,
                    "nonce": nonce,
                    "timestamp": _NOW,
                    "room_id": "spoofed-room",
                },
            )

        async def _run(server_instance, *events):
            writer = _PeerWriter()
            wire = b"".join(encode_event(event) for event in events)
            await server_instance.handle_connection(_reader(wire), writer)
            responses = []
            response_reader = _reader(bytes(writer.buf))
            while True:
                response = await read_event(response_reader)
                if response is None:
                    return responses
                responses.append(response)

        with patch.dict(
            os.environ,
            {"JARVIS_ACTION_KERNEL": "1", "JARVIS_UNIFIED_ACTION_API": "1"},
        ):
            good = await _run(
                server,
                _auth("room-nonce-good"),
                WyomingEvent("transcript", {"text": "announce dinner"}),
            )
            spoofed = await _run(server, _auth("room-nonce-spoof", "wrong-token"))

            ambiguous_registry = DeviceRegistry(path=None)
            for device_id in ("speaker-a", "speaker-b"):
                ambiguous_registry.register(
                    MediaDevice(
                        id=device_id,
                        name=device_id,
                        kind="speaker",
                        room="kitchen",
                        supports=("announce",),
                    )
                )
            ambiguous = WyomingServer.room_aware(
                enabled=True,
                satellite_hub=hub,
                context_resolver=RoomVoiceContextResolver(
                    ambiguous_registry,
                    privacy_provider=lambda _room: "normal",
                ),
                handler=_handler,
            )
            ambiguous_result = await _run(
                ambiguous,
                _auth("room-nonce-ambiguous"),
                WyomingEvent("transcript", {"text": "announce dinner"}),
            )

        output = performed[0].output if performed else {}
        passed = (
            [event.type for event in good] == ["satellite-auth-ok", "synthesize"]
            and spoofed[0].type == "satellite-auth-refused"
            and ambiguous_result[1].type == "voice-context-refused"
            and resolved_targets == ["speaker-kitchen"]
            and performed[0].status == "completed"
            and isinstance(output, dict)
            and output.get("verified") is True
        )
    return ledger.result(
        passed,
        evidence={
            "identity_refusals": 2,
            "resolved_target": resolved_targets[0] if resolved_targets else "",
        },
    )


def _live_secret_broker():
    """Seed a broker with the owner-live HA token.

    The adapter resolves its bearer token through a `SecretBroker` handle, so an
    adapter built without one can never authenticate: `_token()` raises
    `credential_unavailable` before the first request and `snapshot()` reports
    `degraded`. That is exactly how this probe used to be constructed, which made
    the owner-live read case unpassable against a *working* Home Assistant.

    Returns None when the run is not configured, so the caller degrades honestly
    instead of reporting a transport failure it never attempted.
    """
    from agents.core.env_config import env_str
    from agents.core.house.home_assistant import _SECRET_HANDLE
    from agents.core.security.secret_broker import SecretBroker

    match = _SECRET_HANDLE.fullmatch(env_str("JARVIS_HA_TOKEN_REF").strip())
    token = env_str("JARVIS_H30_HA_TOKEN").strip()
    if match is None or not token:
        return None
    broker = SecretBroker()
    broker.put(match.group(1), token)
    return broker


async def _probe_owner_live_read() -> dict[str, object]:
    from agents.core.env_config import env_flag
    from agents.core.house.home_assistant import HomeAssistantAdapter

    if not env_flag("JARVIS_H30_HA_LIVE"):
        return {
            "passed": False,
            "metadata": {"status": "degraded", "reason": "owner_live_opt_in_missing"},
        }
    broker = _live_secret_broker()
    if broker is None:
        return {
            "passed": False,
            "metadata": {"status": "degraded", "reason": "owner_live_credential_missing"},
        }
    snapshot = await HomeAssistantAdapter(secret_broker=broker).snapshot()
    return {
        "passed": snapshot.status == "live",
        "metadata": {
            "status": snapshot.status,
            "reason": snapshot.reason or "",
            "entities": len(snapshot.entities),
            "areas": len(snapshot.areas),
            "mutation_probe": False,
        },
    }


async def _probe_owner_live_actuation() -> dict[str, object]:
    """Drive one reversible light through the real HA REST service API.

    The hermetic pack already proves the governance chain against a simulator;
    what no offline case can prove is the *protocol*: that our POST body, auth
    header, pinned-origin rewrite and Host header are accepted by a real Home
    Assistant, and that the mutation is observable in a subsequent read. This
    probe covers exactly that seam and restores the prior state afterwards.
    """
    from agents.core.env_config import env_flag
    from agents.core.house.actuation import HomeAssistantServiceDriver
    from agents.core.house.home_assistant import HomeAssistantAdapter

    if not env_flag("JARVIS_H30_HA_LIVE"):
        return {
            "passed": False,
            "metadata": {"status": "degraded", "reason": "owner_live_opt_in_missing"},
        }
    broker = _live_secret_broker()
    if broker is None:
        return {
            "passed": False,
            "metadata": {"status": "degraded", "reason": "owner_live_credential_missing"},
        }

    adapter = HomeAssistantAdapter(secret_broker=broker)
    before = await adapter.snapshot()
    if before.status != "live":
        return {
            "passed": False,
            "metadata": {"status": before.status, "reason": before.reason or "read_failed"},
        }

    lights = [entity for entity in before.entities if entity.entity_id.startswith("light.")]
    target = next((entity for entity in lights if entity.state == "off"), None)
    if target is None:
        return {
            "passed": False,
            "metadata": {"status": "degraded", "reason": "no_off_light_available"},
        }

    driver = HomeAssistantServiceDriver(adapter=adapter)
    applied = await driver.apply(
        {"control": "light", "entity_id": target.entity_id, "action": "on"}
    )

    async def _state_of(entity_id: str) -> str:
        snap = await adapter.snapshot()
        for entity in snap.entities:
            if entity.entity_id == entity_id:
                return entity.state
        return ""

    observed = await _state_of(target.entity_id)

    # Restore unconditionally: a failed verification must not leave the device on.
    restored = await driver.apply(
        {"control": "light", "entity_id": target.entity_id, "action": "off"}
    )
    rolled_back = await _state_of(target.entity_id)

    # A lock is not representable through the light control mapping — the
    # allowlist refuses to synthesise a service for it at all.
    lock_refused = False
    try:
        HomeAssistantServiceDriver._service(
            {"control": "light", "entity_id": "lock.front_door", "action": "on"}
        )
    except ValueError:
        lock_refused = True

    passed = bool(
        applied.get("ok")
        and observed == "on"
        and restored.get("ok")
        and rolled_back == "off"
        and lock_refused
    )
    return {
        "passed": passed,
        "metadata": {
            "status": "live" if passed else "degraded",
            "entity": target.entity_id,
            "observed_after_apply": observed,
            "observed_after_rollback": rolled_back,
            "lock_refused_by_allowlist": lock_refused,
            "mutation_probe": True,
        },
    }


H30_HOUSE_REALITY_CASES: list[RealityCase] = [
    RealityCase(
        "component:house_adapter",
        "house-adapter-read-reconnect-offline",
        "the real HA adapter reads, reconnects with bounded backoff, and degrades offline",
        _probe_adapter_read_reconnect_offline,
        metadata=dict(_HOUSE_METADATA),
    ),
    RealityCase(
        "component:house_graph",
        "house-graph-presence-privacy-purge",
        "HA topology projects publicly while private presence is withheld and purgeable",
        _probe_graph_presence_privacy_purge,
        metadata=dict(_HOUSE_METADATA),
    ),
    RealityCase(
        "action:house.control",
        "house-approved-reversible-actuation",
        "an approved durable task reaches TaskExecutor, kernel, HA, and state verification",
        _probe_approved_reversible_actuation,
        metadata=dict(_HOUSE_METADATA),
    ),
    RealityCase(
        "action:house.security_control",
        "house-security-strong-confirmation",
        "security control stays blocked until an exact one-shot owner confirmation is consumed",
        _probe_security_strong_confirmation,
        metadata=dict(_HOUSE_METADATA),
    ),
    RealityCase(
        "action:house.recovery",
        "house-verification-rollback",
        "a lying success is refused and compensated through a second kernel-mediated HA action",
        _probe_verification_rollback,
        metadata=dict(_HOUSE_METADATA),
    ),
    RealityCase(
        "operator:house-kernel-halt",
        "house-kernel-halt",
        "an engaged real kill switch denies an approved task before any HA service call",
        _probe_kernel_halt,
        metadata=dict(_HOUSE_METADATA),
    ),
    RealityCase(
        "component:room_voice",
        "house-room-output-governed",
        "paired room voice resolves one target and reaches only the H29 governed media rail",
        _probe_room_output_governed,
        metadata=dict(_HOUSE_METADATA),
    ),
]

H30_HOUSE_LIVE_CASES: list[RealityCase] = [
    RealityCase(
        "component:house_adapter",
        "house-owner-live-read",
        "the owner-gated live Home Assistant host returns a real bounded snapshot",
        _probe_owner_live_read,
        live=True,
        metadata=dict(_HOUSE_LIVE_METADATA),
    ),
    RealityCase(
        "action:house.control",
        "house-owner-live-actuation",
        "a reversible light reaches a real HA service call, is observed, and rolls back",
        _probe_owner_live_actuation,
        live=True,
        metadata=dict(_HOUSE_LIVE_METADATA),
    ),
]
