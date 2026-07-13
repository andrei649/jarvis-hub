"""H29 hermetic media reality cases and causal evidence counters.

Imports stay dependency-neutral so the canonical reality harness can register the
pack without booting host adapters, media stores, or the action plane.  Each probe
imports its real runtime rails lazily and supplies only hermetic host edges.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agents.core.observability.reality_types import RealityCase

_MEDIA_METADATA = {
    "suite": "h29-media",
    "mode": "hermetic",
    "expected_ungoverned_actions": 0,
    "live_owner_validation": "required",
    "promotable": False,
}

_HOST_SEAMS = (
    "image_backend",
    "media_backend",
    "approval_queue",
    "downloader",
    "transcriber",
    "summarizer",
    "browser_driver",
    "media_driver",
)


class MediaEventLedger:
    """Small causal ledger shared by the H29 media probes."""

    _PHASES = {"attempt", "govern", "execute", "block", "host"}

    def __init__(self) -> None:
        self._events: list[dict[str, object]] = []
        self._host_calls = dict.fromkeys(_HOST_SEAMS, 0)

    def record(self, action_id: str, phase: str, seam: str) -> None:
        if not action_id or not seam or phase not in self._PHASES:
            raise ValueError("invalid media reality event")
        self._events.append(
            {
                "sequence": len(self._events) + 1,
                "action_id": action_id,
                "phase": phase,
                "seam": seam,
            }
        )

    def host_call(self, action_id: str, seam: str) -> None:
        if seam not in self._host_calls:
            raise ValueError("unknown media host seam")
        self.record(action_id, "host", seam)
        self._host_calls[seam] += 1

    def result(
        self, passed: bool, *, evidence: dict[str, object] | None = None
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

        for _action_id, action_events in actions.items():
            phases = [event["phase"] for event in action_events]
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
            host_or_execute = [
                event for event in action_events if event["phase"] in {"execute", "host"}
            ]
            if host_or_execute and (
                governance_sequence is None
                or attempt_sequence is None
                or not attempt_sequence < governance_sequence
                or any(governance_sequence >= int(event["sequence"]) for event in host_or_execute)
            ):
                ungoverned += 1

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
            and counters["attempted_actions"]
            == counters["executed_actions"] + counters["blocked_actions"]
        )
        host_calls = dict(self._host_calls)
        metadata = {
            "counters": counters,
            "events": events,
            "host_calls": host_calls,
            "host_call_count": sum(host_calls.values()),
        }
        metadata.update(dict(evidence or {}))
        return {
            "passed": bool(passed and invariant),
            "metadata": metadata,
        }


async def _probe_defaults_fail_closed() -> dict[str, object]:
    from agents.core.image_gen import ImageGenOrchestrator
    from agents.core.media_gen import MediaGenManager
    from agents.core.media_skill import MediaSummarizer

    ledger = MediaEventLedger()
    default_bindings = {}
    ambient_host_calls = {"network": 0, "process": 0, "urlopen": 0}

    def _tripwire(kind):
        def _fail(*_args, **_kwargs):
            ambient_host_calls[kind] += 1
            raise AssertionError(f"unexpected ambient {kind} host call")

        return _fail

    results = []
    with (
        patch("socket.socket", side_effect=_tripwire("network")),
        patch("subprocess.Popen", side_effect=_tripwire("process")),
        patch("urllib.request.urlopen", side_effect=_tripwire("urlopen")),
    ):
        image = ImageGenOrchestrator()
        media = MediaGenManager()
        summary = MediaSummarizer()
        default_bindings.update(
            {
                "image_backend": image._diff is not None,
                "llm_unload": image._unload is not None,
                "llm_load": image._load is not None,
                "media_backends": len(media._backends),
                "approval_queue": media._enqueue is not None,
                "media_catalog": media._catalog is not None,
                "local_guard": media._local_guard is not None,
                "downloader": summary._dl is not None,
                "transcriber": summary._tr is not None,
                "summarizer": summary._sum is not None,
                "url_guard": summary._url_guard is not None,
            }
        )
        probes = (
            ("default:image", image.generate("reality image")),
            ("default:media", media.generate("image", "reality image")),
            ("default:summary", summary.summarize_url("https://93.184.216.34/v")),
        )
        for action_id, awaitable in probes:
            ledger.record(action_id, "attempt", "default-constructor")
            result = await awaitable
            results.append(result)
            ledger.record(action_id, "block", str(result.get("reason", "refused"))[:64])
    passed = (
        all(result.get("ok") is False for result in results)
        and not any(bool(value) for value in default_bindings.values())
        and not any(ambient_host_calls.values())
    )
    return ledger.result(
        passed,
        evidence={
            "default_bindings": default_bindings,
            "ambient_host_calls": ambient_host_calls,
            "tripwire_scope": "construction-and-execution",
        },
    )


async def _probe_local_catalog_presentation() -> dict[str, object]:
    from agents.core.autonomy.policy import ACT, AutonomyPolicy, RiskTier
    from agents.core.capability_actions import CapabilityActionAPI, PerformContext
    from agents.core.kernel import authorize
    from agents.core.media_catalog import MediaCatalog
    from agents.core.media_director import (
        DeviceRegistry,
        MediaDevice,
        MediaDirector,
        SessionBoard,
        register_media_capability,
    )
    from agents.core.media_gen import MediaGenManager
    from agents.core.security.capability import CapabilityBroker, KillSwitch

    ledger = MediaEventLedger()
    with tempfile.TemporaryDirectory(prefix="reality-media-local-") as directory:
        root = Path(directory)
        artifact = root / "generated.png"
        catalog = MediaCatalog(root / "catalog.json")

        async def _backend(_prompt, _opts):
            ledger.host_call("local:generation", "media_backend")
            artifact.write_bytes(b"h29-media-reality")
            return {"path": str(artifact)}

        ledger.record("local:generation", "attempt", "media-gen.generate")

        def _local_guard(kind, prompt, opts):
            ledger.record("local:generation", "govern", "media-gen.local-guard")
            return (kind == "image" and bool(prompt) and isinstance(opts, dict), "")

        generated = await MediaGenManager(
            backends={"image": _backend},
            catalog=catalog,
            clock=lambda: 29.0,
            local_guard=_local_guard,
        ).generate("image", "H29 local reality")
        ledger.record(
            "local:generation",
            "execute" if generated.get("ok") else "block",
            "media-gen.result",
        )

        class _Driver:
            supports_duration = False

            def __init__(self) -> None:
                self.content = None

            def play(self, _device, content, *, duration_seconds=None):
                ledger.host_call("local:presentation", "media_driver")
                self.content = dict(content)
                return {"ok": True, "state": "playing"}

            def status(self, _device):
                ledger.host_call("local:presentation", "media_driver")
                return {"ok": True, "state": "playing", "content": dict(self.content or {})}

        driver = _Driver()
        registry = DeviceRegistry(path=None)
        registry.register(
            MediaDevice(
                id="reality-display",
                name="Reality display",
                kind="browser_tab",
                room="lab",
                supports=("show",),
            )
        )
        director = MediaDirector(
            registry=registry,
            sessions=SessionBoard(path=None),
            drivers={"browser_tab": driver},
            local_roots=(root,),
            catalog=catalog,
            clock=lambda: 30.0,
        )
        kill_switch = KillSwitch(path=str(root / "kill.json"))
        capabilities = CapabilityBroker()
        token = capabilities.issue(["media.present"])
        policy = AutonomyPolicy(tier_outcomes=dict.fromkeys(RiskTier, ACT))

        def _authorize(action, capability=None, budget=None):
            ledger.record("local:presentation", "govern", "action-kernel")
            return authorize(
                action,
                capability,
                budget,
                kill_switch=kill_switch,
                capabilities=capabilities,
                policy=policy,
            )

        api = CapabilityActionAPI(authorizer=_authorize)
        register_media_capability(api, director)
        ledger.record("local:presentation", "attempt", "media-director.present")
        with patch.dict(
            os.environ,
            {"JARVIS_UNIFIED_ACTION_API": "1", "JARVIS_ACTION_KERNEL": "1"},
        ):
            performed = await api.perform(
                "action:media.present",
                {
                    "content": {"type": "catalog", "value": generated.get("catalog_id", "")},
                    "target": "reality-display",
                    "mode": "show",
                    "privacy": "household",
                    "urgency": "normal",
                },
                PerformContext(
                    capability_token=token["id"],
                    capability_name="media.present",
                ),
            )
        presented = performed.output if isinstance(performed.output, dict) else {}
        ledger.record(
            "local:presentation",
            "execute" if performed.status == "completed" and presented.get("ok") else "block",
            "media-director.result",
        )
        passed = (
            generated.get("ok") is True
            and isinstance(generated.get("catalog_id"), str)
            and catalog.get(generated["catalog_id"]) is not None
            and performed.status == "completed"
            and presented.get("ok") is True
            and presented.get("verified") is True
            and presented.get("content", {}).get("provenance") == "catalog"
            and presented.get("content", {}).get("catalog_id") == generated["catalog_id"]
        )
    return ledger.result(passed)


async def _probe_cloud_approval_durable() -> dict[str, object]:
    from agents.core import media_gen
    from agents.core.autonomy.queue import TaskQueue

    ledger = MediaEventLedger()
    backend_calls = []

    async def _backend(_prompt, _opts):
        backend_calls.append(True)
        ledger.host_call("cloud:generation", "media_backend")
        return {"path": "must-not-exist"}

    with tempfile.TemporaryDirectory(prefix="reality-media-approval-") as directory:
        db_path = str(Path(directory) / "tasks.db")
        queue = TaskQueue(db_path).initialize()
        reopened = None

        def _enqueue(*args, **kwargs):
            ledger.host_call("cloud:generation", "approval_queue")
            return queue.enqueue(*args, **kwargs)

        real_contract = media_gen.MEDIA_GENERATION_CONTRACT

        class _MeasuredContract:
            def evaluate(self, payload=None, **kwargs):
                ledger.record("cloud:generation", "govern", "media-generation-contract")
                return real_contract.evaluate(payload, **kwargs)

        try:
            ledger.record("cloud:generation", "attempt", "media-gen.generate")
            with patch.object(media_gen, "MEDIA_GENERATION_CONTRACT", _MeasuredContract()):
                result = await media_gen.MediaGenManager(
                    backends={"image": _backend}, enqueue=_enqueue
                ).generate("image", "H29 cloud approval", cloud=True)
            ledger.record("cloud:generation", "block", "ask-tier-approval")
            task_id = int(result.get("task_id") or 0)
            queue.close()
            reopened = TaskQueue(db_path).initialize()
            task = reopened.get(task_id)
            passed = (
                result.get("ok") is False
                and result.get("reason") == "approval_required"
                and backend_calls == []
                and task is not None
                and task.kind == "media.image"
                and task.status == "proposed"
                and task.autonomy_level == "ask"
                and task.risk_tier == 2
                and task.origin == "generated"
            )
        finally:
            queue.close()
            if reopened is not None:
                reopened.close()
    return ledger.result(passed, evidence={"queue_reopen_count": 1})


async def _probe_summarizer_governed_download() -> dict[str, object]:
    from agents.core.browser_agent import BrowserPolicy
    from agents.core.media_skill import MediaSummarizer

    ledger = MediaEventLedger()
    url = "https://93.184.216.34/v"

    async def _download(_url):
        ledger.host_call("summary:guarded", "downloader")
        return "hermetic-audio"

    async def _transcribe(_audio):
        ledger.host_call("summary:guarded", "transcriber")
        return "hermetic transcript"

    async def _summarize(_transcript):
        ledger.host_call("summary:guarded", "summarizer")
        return "hermetic summary"

    ledger.record("summary:unguarded", "attempt", "media-summarizer")
    unguarded = await MediaSummarizer(_download, _transcribe, _summarize).summarize_url(url)
    ledger.record("summary:unguarded", "block", "url-guard-unavailable")

    policy = BrowserPolicy(["93.184.216.34"])

    def _url_guard(target):
        ledger.record("summary:guarded", "govern", "browser-policy.domain-allowed")
        return policy.domain_allowed(target)

    ledger.record("summary:guarded", "attempt", "media-summarizer")
    guarded = await MediaSummarizer(
        _download,
        _transcribe,
        _summarize,
        url_guard=_url_guard,
    ).summarize_url(url)
    ledger.record(
        "summary:guarded",
        "execute" if guarded.get("ok") else "block",
        "media-summarizer.result",
    )
    passed = (
        unguarded == {"ok": False, "reason": "url_guard_unavailable"}
        and guarded.get("ok") is True
        and guarded.get("summary") == "hermetic summary"
    )
    return ledger.result(passed)


async def _probe_kernel_halt_driver_deny() -> dict[str, object]:
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.capability_actions import CapabilityActionAPI
    from agents.core.kernel import authorize
    from agents.core.media_director import (
        DeviceRegistry,
        MediaDevice,
        MediaDirector,
        SessionBoard,
        register_media_capability,
    )
    from agents.core.security.capability import KillSwitch

    ledger = MediaEventLedger()

    class _Driver:
        supports_duration = False

        def play(self, _device, _content, *, duration_seconds=None):
            ledger.host_call("halt:presentation", "media_driver")
            return {"ok": True, "state": "playing"}

        def status(self, _device):
            ledger.host_call("halt:presentation", "media_driver")
            return {"ok": True, "state": "playing", "content": {}}

    with tempfile.TemporaryDirectory(prefix="reality-media-halt-") as directory:
        kill_switch = KillSwitch(path=os.path.join(directory, "kill.json"))
        kill_switch.engage("global", reason="H29 media reality")
        policy = AutonomyPolicy()

        def _authorize(action, capability=None, budget=None):
            ledger.record("halt:presentation", "govern", "action-kernel")
            return authorize(
                action,
                capability,
                budget,
                kill_switch=kill_switch,
                policy=policy,
            )

        registry = DeviceRegistry(path=None)
        registry.register(MediaDevice(id="halt-tv", name="Halt TV", kind="tv", room="lab"))
        api = CapabilityActionAPI(authorizer=_authorize)
        register_media_capability(
            api,
            MediaDirector(
                registry=registry,
                sessions=SessionBoard(path=None),
                drivers={"tv": _Driver()},
            ),
        )
        ledger.record("halt:presentation", "attempt", "capability-action-api")
        with patch.dict(
            os.environ,
            {"JARVIS_UNIFIED_ACTION_API": "1", "JARVIS_ACTION_KERNEL": "1"},
        ):
            result = await api.perform(
                "action:media.present",
                {
                    "content": {"type": "url", "value": "https://93.184.216.34/v"},
                    "target": "halt-tv",
                    "mode": "play",
                    "privacy": "household",
                    "urgency": "normal",
                },
            )
        ledger.record("halt:presentation", "block", "kernel-deny")
    return ledger.result(result.status == "refused" and "kill-switch" in result.reason)


H29_MEDIA_REALITY_CASES: list[RealityCase] = [
    RealityCase(
        "component:media_runtime",
        "media-defaults-fail-closed",
        "default wave-2 constructors refuse without invoking any host seam",
        _probe_defaults_fail_closed,
        metadata=dict(_MEDIA_METADATA),
    ),
    RealityCase(
        "action:media.present",
        "media-local-catalog-presentation",
        "local generation reaches a real catalog resolver and driver-verified presentation",
        _probe_local_catalog_presentation,
        metadata=dict(_MEDIA_METADATA),
    ),
    RealityCase(
        "component:media_gen",
        "media-cloud-approval-durable",
        "cloud generation calls no backend and creates a durable ask-tier approval task",
        _probe_cloud_approval_durable,
        metadata=dict(_MEDIA_METADATA),
    ),
    RealityCase(
        "skill:media_skill",
        "media-summarizer-governed-download",
        "media download requires an explicit fail-closed governed URL guard",
        _probe_summarizer_governed_download,
        metadata=dict(_MEDIA_METADATA),
    ),
    RealityCase(
        "operator:media-kernel-halt",
        "media-kernel-halt-driver-deny",
        "a real kernel halt denies presentation before any media driver call",
        _probe_kernel_halt_driver_deny,
        metadata=dict(_MEDIA_METADATA),
    ),
]
