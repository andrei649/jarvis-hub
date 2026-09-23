"""H313 — the model may decide to say one thing aloud, in one room.

Hermes's ``text_to_speech`` hands the platform an audio file. Nerva's voice
subsystem already speaks a turn's *reply*; the gap was a model that decides to
speak a specific thing on a specific room's device. The adaptation is a gated
ToolRPC ``speak`` tool: bounded text is synthesized on the host's own TTS engine
and presented in ``announce`` mode through ``CapabilityActionAPI.perform(
"action:media.present")`` — the Action Kernel sees the effect, and the tool never
drives an output device itself. Registered only with the Media Director on,
offered only to the owner at the operator surface.
"""

import functools
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest  # noqa: E402

from agents.core import tool_profiles as tp  # noqa: E402
from agents.core.autonomy_coordinator import (  # noqa: E402
    _TRUSTED_TOOL_RPC_KINDS,
    AutonomyCoordinator,
)
from agents.core.channels.spoken_reply import MAX_SPOKEN_CHARS, SpokenReply  # noqa: E402
from agents.core.kernel import Decision, Verdict  # noqa: E402
from agents.core.media_director import (  # noqa: E402
    DeviceRegistry,
    MediaDevice,
    MediaDirector,
    MediaSession,
    SessionBoard,
)
from agents.core.routers import media_director as media_routes  # noqa: E402
from agents.core.voice import speak_tool  # noqa: E402

CLIP = b"ID3-hermetic-spoken-clip"


# ── fakes ────────────────────────────────────────────────────────────────────


class _Driver:
    """A speaker driver that records every actuation and reports honest status."""

    def __init__(self):
        self.calls = []
        self.now_playing = None

    def play(self, device, content):
        self.calls.append(("play", device.id, dict(content)))
        self.now_playing = dict(content)
        return {"ok": True, "state": "playing"}

    def stop(self, device):
        self.calls.append(("stop", device.id))
        self.now_playing = None
        return {"ok": True, "state": "idle"}

    def pause(self, device):
        return {"ok": True, "state": "paused"}

    def resume(self, device):
        return {"ok": True, "state": "playing"}

    def status(self, device):
        return {"ok": True, "state": "playing", "content": self.now_playing or {}}


class _Kernel:
    """Grants the ToolRPC gate; answers ``media.present`` with *present_verdict*."""

    def __init__(self, present_verdict=Verdict.QUEUE, reason="approval_required"):
        self.kinds = []
        self.actions = []
        self.present_verdict = present_verdict
        self.reason = reason

    def __call__(self, action, capability=None, budget=None):
        self.kinds.append(action.kind)
        self.actions.append(action)
        if action.kind == "media.present":
            return Decision(self.present_verdict, reason=self.reason, tier=2)
        return Decision(Verdict.GRANT, reason="allowed", tier=2)


def _director(root: Path, driver: _Driver, *, supports=("announce", "play"),
              presence_room: str = "kitchen") -> MediaDirector:
    registry = DeviceRegistry(path=None)
    registry.register(MediaDevice(
        id="speaker-kitchen", name="Kitchen speaker", kind="speaker",
        room="kitchen", supports=tuple(supports), room_default=True,
    ))
    registry.register(MediaDevice(
        id="tv-living", name="Living room TV", kind="tv", room="living", supports=("play",),
    ))
    return MediaDirector(
        registry=registry,
        sessions=SessionBoard(path=None),
        drivers={"speaker": driver, "tv": driver},
        local_roots=(root,),
        presence=lambda: None,  # no fresh presence signal unless a test gives one
        presence_room=presence_room,
    )


def _speaker(synth_log, *, available=True, clip=CLIP):
    async def synthesize(text, lang):
        synth_log.append((text, lang))
        path = Path(os.environ["SPEAK_TEST_TMP"]) / f"tts-{len(synth_log)}.mp3"
        path.write_bytes(clip)
        return str(path)

    return lambda: SpokenReply(synthesize=synthesize, available=available, backend="test-tts")


@pytest.fixture
def media_env(tmp_path, monkeypatch):
    """Media Director + unified API + kernel on, a hermetic director and TTS."""
    root = tmp_path / "media"
    root.mkdir()
    scratch = tmp_path / "tts"
    scratch.mkdir()
    monkeypatch.setenv("SPEAK_TEST_TMP", str(scratch))
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    driver = _Driver()
    director = _director(root, driver)
    monkeypatch.setattr(media_routes, "_director", director)
    synth_log = []
    monkeypatch.setattr(speak_tool, "default_speaker", _speaker(synth_log))
    # The proposal-time probe asks whether a speech backend is installed at all.
    monkeypatch.setattr(speak_tool, "tts_installed", lambda: True)
    return SimpleNamespace(root=root, driver=driver, director=director, synth=synth_log)


class _RecordingQueue:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, *args, **kwargs):
        self.enqueued.append((args, kwargs))
        return len(self.enqueued)

    def get(self, _task_id):
        return None


_NO_KERNEL = object()


def _wired(kernel=None):
    queue = _RecordingQueue()
    orch = SimpleNamespace(agents={}, autonomy_queue=queue, secret_broker=None, intent_log=None)
    bound = _Kernel() if kernel is None else (None if kernel is _NO_KERNEL else kernel)
    AutonomyCoordinator(orch)._wire_agent_tool_runtime(action_kernel=bound)
    return orch, queue


# ── registration and posture ─────────────────────────────────────────────────


def test_speak_is_registered_gated_only_with_the_media_director_on(monkeypatch):
    monkeypatch.delenv("JARVIS_MEDIA_DIRECTOR", raising=False)
    orch, _queue = _wired()
    assert "speak" not in {t["name"] for t in orch.tool_rpc.tools()}

    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    orch, _queue = _wired()
    row = next(t for t in orch.tool_rpc.tools() if t["name"] == "speak")
    assert row["gated"] is True
    assert row["capability_id"] == "tool:speak"
    schema = row["input_schema"]
    assert schema["required"] == ["text", "target"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["text"]["maxLength"] == MAX_SPOKEN_CHARS
    assert schema["properties"]["target"]["maxLength"] == 120
    assert schema["properties"]["urgency"]["enum"] == ["normal", "high"]
    # The approved row runs only on the trusted, durably-approved rail.
    assert "toolrpc.speak" in _TRUSTED_TOOL_RPC_KINDS


def test_lang_choices_are_the_tts_engines_own_voice_map():
    from agents.core.voice.tts import TTSEngine

    assert set(speak_tool.SPEAK_LANGS) == set(TTSEngine.VOICE_MAP)


def test_inbound_and_guest_postures_never_offer_speak(monkeypatch):
    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")
    orch, _queue = _wired()
    tools = orch.tool_rpc.tools()
    defaults = lambda key, default: default  # noqa: E731
    for surface, principal in tp.POSTURES:
        offered, withheld = tp.resolve_tools(
            tools, posture=tp.ToolPosture(surface, principal), settings=defaults,
        )
        names = {t["name"] for t in offered}
        if (surface, principal) == ("operator", "owner"):
            assert "speak" in names
        else:
            assert "speak" not in names and "speak" in withheld, (surface, principal)
    # Even the llm.guest_tools allowlist cannot hand a guest a gated tool.
    guest = lambda key, default: ["speak"] if key == "llm.guest_tools" else default  # noqa: E731
    offered, _ = tp.resolve_tools(
        tools, posture=tp.ToolPosture("inbound", "guest"), settings=guest,
    )
    assert "speak" not in {t["name"] for t in offered}


def test_the_executor_routes_toolrpc_speak_to_the_trusted_rail(monkeypatch):
    from agents.core.autonomy.policy import AutonomyPolicy

    monkeypatch.setenv("JARVIS_MEDIA_DIRECTOR", "1")

    async def process(*_args, **_kwargs):
        return "ok"

    orch = SimpleNamespace(
        agents={}, audit=None, autonomy=SimpleNamespace(policy=AutonomyPolicy(), budget=None),
        autonomy_queue=_RecordingQueue(), budget_ledger=None, capabilities=None,
        channel_inbox=None, channel_manager=None, cognition=None, intent_log=None,
        kill_switch=None, loop_detector=None, permission_gate=None, plugins={},
        process=process, secret_broker=None,
        get_setting=lambda _key, default=None: default,
    )
    coordinator = AutonomyCoordinator(orch)
    executor = coordinator.build_executor()
    assert executor.resolve("toolrpc.speak") is coordinator._approved_desktop_tool_rpc_execute


# ── proposal-time preflight: named refusals, no card ─────────────────────────


async def _propose(orch, args):
    return await orch.tool_rpc.handle({"tool": "speak", "args": args}, actor="jarvis")


async def test_text_over_the_cap_is_refused_before_any_card(media_env):
    orch, queue = _wired()
    response = await _propose(orch, {"text": "a" * (MAX_SPOKEN_CHARS + 1), "target": "kitchen"})
    assert response == {"ok": False, "reason": "text_too_long", "tool": "speak"}
    assert queue.enqueued == []


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"text": "```\nprint(1)\n```", "target": "kitchen"}, "nothing_to_say"),
        ({"text": "   ", "target": "kitchen"}, "nothing_to_say"),
        ({"text": 7, "target": "kitchen"}, "invalid_text"),
        ({"text": "Dinner is ready.", "target": ""}, "invalid_target"),
        ({"text": "Dinner is ready.", "target": "x" * 121}, "invalid_target"),
        ({"text": "Dinner is ready.", "target": "kitchen\n"}, "invalid_target"),
        ({"text": "Dinner is ready.", "target": "kitchen", "urgency": "low"}, "invalid_urgency"),
        ({"text": "Dinner is ready.", "target": "kitchen", "lang": "fr"}, "unsupported_lang"),
        ({"text": "Dinner is ready.", "target": "attic"}, "target_unresolved"),
        # A room whose only device cannot announce: the refusal says so by name.
        ({"text": "Dinner is ready.", "target": "living"}, "unsupported_mode"),
        ({"text": "Dinner is ready.", "target": "tv-living"}, "unsupported_mode"),
        ({"text": "Dinner is ready.", "target": "kitchen", "volume": 11}, "unexpected_argument"),
    ],
)
async def test_preflight_refusals_are_named_and_enqueue_nothing(media_env, args, reason):
    orch, queue = _wired()
    response = await _propose(orch, args)
    assert response == {"ok": False, "reason": reason, "tool": "speak"}
    assert queue.enqueued == []


async def test_media_director_off_refuses_even_a_registered_tool(media_env, monkeypatch):
    orch, queue = _wired()
    monkeypatch.delenv("JARVIS_MEDIA_DIRECTOR")
    response = await _propose(orch, {"text": "Dinner is ready.", "target": "kitchen"})
    assert response == {"ok": False, "reason": "media_director_disabled", "tool": "speak"}
    assert queue.enqueued == []


async def test_a_room_proposal_names_its_announce_device_on_the_card(media_env):
    kernel = _Kernel()
    orch, queue = _wired(kernel)
    response = await _propose(orch, {"text": "Dinner is ready.", "target": "kitchen"})
    assert response["reason"] == "approval_required"
    (args, kwargs), = queue.enqueued
    assert args[1] == "toolrpc.speak"
    assert kwargs["autonomy_level"] == "ask"
    # The owner approves the device that will speak, not a room the model named.
    assert kwargs["payload"]["args"] == {
        "text": "Dinner is ready.", "target": "speaker-kitchen", "urgency": "normal",
    }
    assert args[2].endswith("say aloud on speaker-kitchen")
    # The kernel was shown exactly the row that became the card, so the worker's
    # mediation bridge can bind that decision as the row's intake evidence.
    (proposal,) = kernel.actions
    assert (proposal.kind, proposal.agent, proposal.title) == ("toolrpc.speak", args[0], args[2])
    assert proposal.payload == kwargs["payload"]
    assert proposal.origin == kwargs["origin"]
    assert media_env.driver.calls == [] and media_env.synth == []


@pytest.mark.parametrize(
    ("breakage", "reason"),
    [
        ("unified_api_off", "unified_action_api_disabled"),
        ("kernel_off", "action_kernel_disabled"),
        ("no_kernel", "kernel_unavailable"),
        ("no_media_root", "media_root_unconfigured"),
        ("no_tts", "tts_unavailable"),
        ("no_driver", "no_media_driver"),
    ],
)
@pytest.mark.parametrize("target", ["kitchen", "speaker-kitchen", "presence:auto"])
async def test_a_card_that_could_only_be_refused_is_never_raised(
        media_env, monkeypatch, breakage, reason, target):
    # The owner is never asked to approve a speak the approved run can only refuse.
    kernel = None
    if breakage == "unified_api_off":
        monkeypatch.delenv("JARVIS_UNIFIED_ACTION_API")
    elif breakage == "kernel_off":
        monkeypatch.delenv("JARVIS_ACTION_KERNEL")
    elif breakage == "no_kernel":
        kernel = _NO_KERNEL
    elif breakage == "no_media_root":
        monkeypatch.setattr(media_env.director, "_local_roots", ())
    elif breakage == "no_tts":
        monkeypatch.setattr(speak_tool, "tts_installed", lambda: False)
    elif breakage == "no_driver":
        monkeypatch.setattr(media_env.director, "_drivers", {})
    orch, queue = _wired(kernel)
    response = await _propose(orch, {"text": "Dinner is ready.", "target": target})
    assert response == {"ok": False, "reason": reason, "tool": "speak"}
    assert queue.enqueued == []
    assert media_env.synth == [] and media_env.driver.calls == []


async def test_presence_needs_a_configured_room_with_an_announce_speaker(media_env, monkeypatch):
    orch, queue = _wired()
    args = {"text": "Your call starts now.", "target": "presence:auto"}
    monkeypatch.setattr(media_env.director, "_presence_room", "")
    assert await _propose(orch, args) == {
        "ok": False, "reason": "presence_room_unconfigured", "tool": "speak"}
    monkeypatch.setattr(media_env.director, "_presence_room", "living")  # a TV, no announce
    assert await _propose(orch, args) == {
        "ok": False, "reason": "unsupported_mode", "tool": "speak"}
    monkeypatch.setattr(media_env.director, "_presence_room", "attic")
    assert await _propose(orch, args) == {
        "ok": False, "reason": "target_unresolved", "tool": "speak"}
    assert queue.enqueued == []


async def test_presence_target_is_kept_for_execution_time(media_env):
    orch, queue = _wired()
    await _propose(orch, {"text": "Your call starts now.", "target": "presence:auto",
                          "urgency": "high", "lang": "en"})
    (_args, kwargs), = queue.enqueued
    assert kwargs["payload"]["args"] == {
        "text": "Your call starts now.", "target": "presence:auto",
        "urgency": "high", "lang": "en",
    }


# ── the approved run: TTS → spool → kernel-mediated media.present/announce ────


@pytest.fixture
def durable(tmp_path):
    from agents.core.autonomy.executor import TaskExecutor
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker

    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()

    def build(kernel, *, intent_log=None, through_worker_gate=False):
        worker = AutonomyWorker(queue, policy=AutonomyPolicy())
        orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue,
                               secret_broker=None, intent_log=intent_log)
        coordinator = AutonomyCoordinator(orch)
        if through_worker_gate:
            # Production composition (build_executor's `_broker_kernel`): the bound
            # kernel sits behind the worker's mediation bridge.
            worker.bind_mediation(kernel, None)
            kernel = worker.kernel_gate
        coordinator._wire_agent_tool_runtime(action_kernel=kernel)
        generic = []

        async def generic_toolrpc(task):
            generic.append(task.kind)
            return {"status": "failed", "reason": "wrong_handler"}

        worker.executor = TaskExecutor().register("toolrpc", generic_toolrpc).register(
            "toolrpc.speak", coordinator._approved_desktop_tool_rpc_execute,
        ).execute
        return SimpleNamespace(orch=orch, worker=worker, queue=queue,
                               coordinator=coordinator, generic=generic)

    try:
        yield build
    finally:
        queue.close()


def _clips(root: Path) -> list[Path]:
    folder = root / speak_tool.SPOOL_DIRNAME
    return sorted(folder.glob("speak-*")) if folder.is_dir() else []


async def _approve_and_run(rig, task_id):
    await rig.worker.apply_decision(task_id, "accept", decided_by="andrei")
    await rig.worker.tick()
    return rig.queue.get(task_id)


async def test_approved_speak_presents_announce_through_the_kernel(media_env, durable):
    kernel = _Kernel(present_verdict=Verdict.QUEUE)
    rig = durable(kernel)
    proposed = await rig.orch.tool_rpc.handle(
        {"tool": "speak", "args": {"text": "Dinner is **ready**. See https://x.test/menu",
                                   "target": "kitchen"}},
        actor="jarvis",
    )
    task_id = proposed["task_id"]
    blocked = rig.queue.get(task_id)
    assert blocked.status == "blocked"

    # Nothing speaks before a human accepts the durable row, by any door.
    assert (await rig.orch.tool_rpc.execute(blocked))["reason"] == "trusted_execution_required"
    early = await rig.coordinator._approved_desktop_tool_rpc_execute(blocked)
    assert early["reason"] == "trusted_execution_required"
    assert media_env.driver.calls == [] and media_env.synth == []

    kernel.kinds.clear()
    done = await _approve_and_run(rig, task_id)

    assert rig.generic == []
    assert done.result["status"] == "ok", done.result
    result = done.result["result"]
    assert result["ok"] is True
    assert result["device"] == "speaker-kitchen"
    assert result["mode"] == "announce"
    assert result["verified"] is True
    assert result["backend"] == "test-tts"
    # The markup and the link are not read aloud; the owner's configured voice is used.
    assert media_env.synth == [("Dinner is ready. See link", "")]
    # The effect crossed the kernel as media.present, after the gated-tool check.
    assert kernel.kinds == ["tool.rpc", "media.present"]
    present = kernel.actions[-1]
    assert present.payload["mode"] == "announce"
    assert present.payload["target"] == "speaker-kitchen"
    assert present.payload["content"]["type"] == "local"
    assert present.origin == blocked.origin
    # And the device got a clip that lives under the owner's media root.
    (op, device_id, content), = media_env.driver.calls
    assert (op, device_id) == ("play", "speaker-kitchen")
    clip = Path(content["value"])
    assert clip.parent == (media_env.root / speak_tool.SPOOL_DIRNAME).resolve()
    assert clip.read_bytes() == CLIP
    session = media_env.director.sessions.get("speaker-kitchen")
    assert session.mode == "announce"


async def test_kernel_deny_produces_no_playback_and_no_clip(media_env, durable):
    kernel = _Kernel(present_verdict=Verdict.DENY, reason="kill-switch engaged for scope 'global'")
    rig = durable(kernel)
    proposed = await rig.orch.tool_rpc.handle(
        {"tool": "speak", "args": {"text": "Dinner is ready.", "target": "kitchen"}},
        actor="jarvis",
    )
    done = await _approve_and_run(rig, proposed["task_id"])

    assert done.result["status"] == "failed"
    assert done.result["reason"] == "kernel_denied"
    assert done.result["result"]["detail"] == "kill-switch engaged for scope 'global'"
    assert "media.present" in kernel.kinds
    assert media_env.driver.calls == []
    assert _clips(media_env.root) == []
    assert media_env.director.sessions.get("speaker-kitchen") is None


class _AuditSink:
    """An IntentLog-shaped sink: ``record(actor, action, why, cause, metadata)``."""

    def __init__(self):
        self.rows = []

    def record(self, actor, action, why, cause="", metadata=None, ts=None):
        self.rows.append({"actor": actor, "action": action, "why": why,
                          "metadata": dict(metadata or {})})
        return self.rows[-1]


def _real_kernel(tmp_path, audit):
    """The production front door: kernel.authorize bound to a kill switch and policy."""
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel import authorize
    from agents.core.security.capability import KillSwitch

    kill = KillSwitch(tmp_path / "kill_switch.json")
    bound = functools.partial(
        authorize, kill_switch=kill, capabilities=None, policy=AutonomyPolicy(), audit=audit,
    )
    return kill, bound


async def _speak(rig, text="Dinner is ready.", target="kitchen", **extra):
    proposed = await rig.orch.tool_rpc.handle(
        {"tool": "speak", "args": {"text": text, "target": target, **extra}}, actor="jarvis",
    )
    assert proposed["reason"] == "approval_required", proposed
    return proposed["task_id"]


async def test_the_real_kernel_mediates_and_audits_an_approved_speak(
        media_env, durable, tmp_path):
    audit = _AuditSink()
    _kill, kernel = _real_kernel(tmp_path, audit)
    rig = durable(kernel, intent_log=audit, through_worker_gate=True)
    task_id = await _speak(rig)
    done = await _approve_and_run(rig, task_id)

    assert done.result["status"] == "ok", done.result
    assert [c[:2] for c in media_env.driver.calls] == [("play", "speaker-kitchen")]
    kernel_rows = [r for r in audit.rows if r["actor"] == "kernel"]
    assert [r["action"] for r in kernel_rows][-1] == "authorize:media.present"
    assert "authorize:tool.rpc" in [r["action"] for r in kernel_rows]
    # The policy asked for approval of the present; the accepted row answered it, and
    # the chain says so — a queued present never executes without a record of why.
    assert kernel_rows[-1]["metadata"]["verdict"] == "queue"
    honoured = [r for r in audit.rows if r["action"] == "speak.durably_approved"]
    assert len(honoured) == 1, audit.rows
    assert honoured[0]["metadata"]["task_id"] == task_id
    assert honoured[0]["metadata"]["decided_by"] == "andrei"
    assert honoured[0]["metadata"]["target"] == "speaker-kitchen"


async def test_the_real_kill_switch_engaged_after_approval_silences_the_speak(
        media_env, durable, tmp_path):
    audit = _AuditSink()
    kill, kernel = _real_kernel(tmp_path, audit)
    rig = durable(kernel, intent_log=audit, through_worker_gate=True)
    task_id = await _speak(rig)
    kill.engage(reason="owner stop")
    done = await _approve_and_run(rig, task_id)

    # ToolRPC's execution-time kernel re-check refuses before the handler runs...
    assert done.result["status"] == "failed"
    assert done.result["reason"] == "kernel_denied"
    assert "kill-switch" in done.result["detail"]
    assert media_env.driver.calls == [] and media_env.synth == []
    assert _clips(media_env.root) == []
    assert not [r for r in audit.rows if r["action"] == "speak.durably_approved"]

    # ...and past it, the present itself is refused by the same kernel, clip dropped.
    task = SimpleNamespace(kind="toolrpc.speak", agent="jarvis", origin="generated",
                           id=task_id, decided_by="andrei")
    tool = speak_tool.SpeakTool(
        director=lambda: media_env.director, approved_task=lambda: task,
        authorizer=kernel, audit=lambda: audit,
    )
    result = await tool.execute({"text": "Dinner is ready.", "target": "speaker-kitchen"})
    assert result["reason"] == "kernel_denied"
    assert "kill-switch" in result["detail"]
    assert media_env.driver.calls == []
    assert _clips(media_env.root) == []
    assert audit.rows[-1]["action"] == "authorize:media.present"
    assert audit.rows[-1]["metadata"]["verdict"] == "deny"


async def test_the_real_kill_switch_refuses_the_card_itself(media_env, durable, tmp_path):
    audit = _AuditSink()
    kill, kernel = _real_kernel(tmp_path, audit)
    rig = durable(kernel, intent_log=audit, through_worker_gate=True)
    kill.engage(reason="owner stop")
    proposed = await rig.orch.tool_rpc.handle(
        {"tool": "speak", "args": {"text": "Dinner is ready.", "target": "kitchen"}},
        actor="jarvis",
    )
    assert proposed == {"ok": False, "reason": "kernel_denied", "tool": "speak"}
    assert rig.queue.list() == []
    assert audit.rows[-1]["action"] == "authorize:toolrpc.speak"
    assert audit.rows[-1]["metadata"]["verdict"] == "deny"


async def test_back_to_back_normal_speaks_on_one_device_both_play(media_env, durable, tmp_path):
    _kill, kernel = _real_kernel(tmp_path, None)
    rig = durable(kernel, through_worker_gate=True)
    budget = _CountingBudget()
    rig.worker.budget = budget
    first = await _approve_and_run(rig, await _speak(rig, "Dinner is ready."))
    second = await _approve_and_run(rig, await _speak(rig, "The door is open."))
    third = await _approve_and_run(rig, await _speak(rig, "The laundry is done.", "speaker-kitchen"))

    for done in (first, second, third):
        assert done.result["status"] == "ok", done.result
    assert [c[:2] for c in media_env.driver.calls] == [("play", "speaker-kitchen")] * 3
    assert budget.spent == 0
    session = media_env.director.sessions.get("speaker-kitchen")
    assert session.mode == "announce" and session.previous is None


async def test_speaking_over_music_keeps_the_music_as_the_restore_point(
        media_env, durable, tmp_path):
    music = {"type": "url", "value": "https://radio.example/stream", "provenance": "direct"}
    media_env.director.sessions.set(MediaSession(
        device_id="speaker-kitchen", content=music, mode="play", privacy="household",
        started_at=1.0,
    ))
    _kill, kernel = _real_kernel(tmp_path, None)
    rig = durable(kernel, through_worker_gate=True)
    budget = _CountingBudget()
    rig.worker.budget = budget

    # Normal urgency does not cut into the owner's music...
    polite = await _approve_and_run(rig, await _speak(rig, "Dinner is ready."))
    assert polite.result["reason"] == "session_etiquette"
    assert budget.spent == 0
    # ...high urgency does, once, and pays for it once.
    urgent = await _approve_and_run(rig, await _speak(rig, "Dinner is ready.", urgency="high"))
    follow = await _approve_and_run(rig, await _speak(rig, "Really, it is ready."))
    again = await _approve_and_run(rig, await _speak(rig, "Last call.", urgency="high"))

    for done in (urgent, follow, again):
        assert done.result["status"] == "ok", done.result
    assert budget.spent == 1
    session = media_env.director.sessions.get("speaker-kitchen")
    assert session.mode == "announce"
    assert session.previous["content"] == music and session.previous["mode"] == "play"


async def test_kernel_off_refuses_rather_than_driving_the_device(media_env, durable, monkeypatch):
    kernel = _Kernel(present_verdict=Verdict.GRANT)
    rig = durable(kernel)
    proposed = await rig.orch.tool_rpc.handle(
        {"tool": "speak", "args": {"text": "Dinner is ready.", "target": "kitchen"}},
        actor="jarvis",
    )
    monkeypatch.delenv("JARVIS_UNIFIED_ACTION_API")
    done = await _approve_and_run(rig, proposed["task_id"])
    assert done.result["reason"] == "unified_action_api_disabled"
    assert media_env.driver.calls == [] and media_env.synth == []
    assert _clips(media_env.root) == []


async def test_the_handler_alone_still_takes_the_facades_refusal(media_env, monkeypatch):
    # The execution-time preflight catches a flag flipped after acceptance; the handler
    # itself still cannot reach a driver without the facade, and drops its clip.
    task = SimpleNamespace(kind="toolrpc.speak", agent="jarvis", origin="generated")
    tool = speak_tool.SpeakTool(
        director=lambda: media_env.director, approved_task=lambda: task,
        authorizer=_Kernel(present_verdict=Verdict.GRANT),
    )
    monkeypatch.delenv("JARVIS_ACTION_KERNEL")
    result = await tool.execute({"text": "Dinner is ready.", "target": "speaker-kitchen"})
    assert result == {"ok": False, "reason": "action_kernel_disabled"}
    assert media_env.driver.calls == []
    assert _clips(media_env.root) == []


async def test_no_tts_backend_is_named_and_nothing_is_presented(media_env, durable, monkeypatch):
    monkeypatch.setattr(speak_tool, "default_speaker", _speaker([], available=False))
    kernel = _Kernel(present_verdict=Verdict.GRANT)
    rig = durable(kernel)
    proposed = await rig.orch.tool_rpc.handle(
        {"tool": "speak", "args": {"text": "Dinner is ready.", "target": "kitchen"}},
        actor="jarvis",
    )
    kernel.kinds.clear()
    done = await _approve_and_run(rig, proposed["task_id"])
    assert done.result["reason"] == "tts_unavailable"
    assert "media.present" not in kernel.kinds
    assert media_env.driver.calls == []


async def test_an_engine_that_produces_no_audio_is_named_and_nothing_is_presented(
        media_env, durable, monkeypatch):
    # The third named refusal: a backend is installed but the synthesis yields nothing.
    async def silent(_text, _lang):
        return None

    monkeypatch.setattr(speak_tool, "default_speaker",
                        lambda: SpokenReply(synthesize=silent, available=True, backend="test-tts"))
    kernel = _Kernel(present_verdict=Verdict.GRANT)
    rig = durable(kernel)
    proposed = await rig.orch.tool_rpc.handle(
        {"tool": "speak", "args": {"text": "Dinner is ready.", "target": "kitchen"}},
        actor="jarvis",
    )
    kernel.kinds.clear()
    done = await _approve_and_run(rig, proposed["task_id"])
    assert done.result["reason"] == "tts_failed"
    assert "media.present" not in kernel.kinds
    assert media_env.driver.calls == []
    assert _clips(media_env.root) == []


async def test_no_owner_media_root_is_named(media_env, durable, monkeypatch):
    kernel = _Kernel(present_verdict=Verdict.GRANT)
    rig = durable(kernel)
    proposed = await rig.orch.tool_rpc.handle(
        {"tool": "speak", "args": {"text": "Dinner is ready.", "target": "kitchen"}},
        actor="jarvis",
    )
    monkeypatch.setattr(media_env.director, "_local_roots", ())
    done = await _approve_and_run(rig, proposed["task_id"])
    assert done.result["reason"] == "media_root_unconfigured"
    assert media_env.synth == [] and media_env.driver.calls == []


async def test_a_device_without_a_driver_is_named_and_the_clip_is_dropped(
        media_env, durable, monkeypatch):
    kernel = _Kernel(present_verdict=Verdict.GRANT)
    rig = durable(kernel)
    proposed = await rig.orch.tool_rpc.handle(
        {"tool": "speak", "args": {"text": "Dinner is ready.", "target": "kitchen"}},
        actor="jarvis",
    )
    monkeypatch.setattr(media_env.director, "_drivers", {})  # NullMediaDriver: refuses honestly
    done = await _approve_and_run(rig, proposed["task_id"])
    assert done.result["reason"] == "no_media_driver"
    assert media_env.synth == []
    assert _clips(media_env.root) == []

    # Reached past the preflight, the director's own refusal is named and the clip dropped.
    task = SimpleNamespace(kind="toolrpc.speak", agent="jarvis", origin="generated")
    tool = speak_tool.SpeakTool(
        director=lambda: media_env.director, approved_task=lambda: task,
        authorizer=_Kernel(present_verdict=Verdict.GRANT),
    )
    result = await tool.execute({"text": "Dinner is ready.", "target": "speaker-kitchen"})
    assert result == {"ok": False, "reason": "no_media_driver"}
    assert len(media_env.synth) == 1
    assert _clips(media_env.root) == []


async def test_the_handler_refuses_without_the_approved_speak_row(media_env):
    tool = speak_tool.SpeakTool(
        director=lambda: media_env.director, approved_task=lambda: None,
        authorizer=_Kernel(present_verdict=Verdict.GRANT),
    )
    result = await tool.execute({"text": "Dinner is ready.", "target": "speaker-kitchen"})
    assert result == {"ok": False, "reason": "approval_required"}
    assert media_env.synth == [] and media_env.driver.calls == []


@pytest.mark.parametrize("kind", ["toolrpc.file_write", "toolrpc.desktop_run", "tool.rpc", None])
async def test_an_approved_row_of_another_kind_cannot_speak(media_env, kind):
    # ToolRPC takes the tool name from the payload, and the trusted-context check admits
    # every trusted kind: only a row approved *as* toolrpc.speak may say anything.
    task = SimpleNamespace(kind=kind, agent="jarvis", origin="generated",
                           payload={"tool": "speak", "args": {}})
    tool = speak_tool.SpeakTool(
        director=lambda: media_env.director, approved_task=lambda: task,
        authorizer=_Kernel(present_verdict=Verdict.GRANT),
    )
    result = await tool.execute({"text": "Dinner is ready.", "target": "speaker-kitchen"})
    assert result == {"ok": False, "reason": "approval_required"}
    assert media_env.synth == [] and media_env.driver.calls == []


class _CountingBudget:
    """The autonomy interrupt budget, counting every spend."""

    def __init__(self, allow=True):
        self.spent = 0
        self.allow = allow

    def consume(self):
        self.spent += 1
        return self.allow


async def test_the_spool_stays_bounded(media_env):
    task = SimpleNamespace(kind="toolrpc.speak", agent="jarvis", origin="generated")
    budget = _CountingBudget()
    tool = speak_tool.SpeakTool(
        director=lambda: media_env.director, approved_task=lambda: task,
        authorizer=_Kernel(present_verdict=Verdict.GRANT), interrupt_budget=lambda: budget,
    )
    # Normal urgency, back to back on one device: an announcement never holds the
    # speaker against the next one, and no interrupt is spent on cutting into one.
    for n in range(speak_tool.MAX_SPOOL_CLIPS + 3):
        result = await tool.execute({"text": f"Reminder {n}.", "target": "speaker-kitchen"})
        assert result["ok"] is True, result
    assert len(_clips(media_env.root)) == speak_tool.MAX_SPOOL_CLIPS
    assert budget.spent == 0


async def test_stale_partial_clips_are_pruned_but_a_fresh_one_is_left(media_env):
    folder = media_env.root / speak_tool.SPOOL_DIRNAME
    folder.mkdir(mode=0o700)
    stale = folder / ".speak-1-deadbeef0000.mp3.part"
    stale.write_bytes(b"crashed mid-write")
    old = time.time() - 3600
    os.utime(stale, (old, old))
    fresh = folder / ".speak-2-deadbeef0001.mp3.part"  # another speak still writing
    fresh.write_bytes(b"in flight")
    task = SimpleNamespace(kind="toolrpc.speak", agent="jarvis", origin="generated")
    tool = speak_tool.SpeakTool(
        director=lambda: media_env.director, approved_task=lambda: task,
        authorizer=_Kernel(present_verdict=Verdict.GRANT),
    )
    result = await tool.execute({"text": "Dinner is ready.", "target": "speaker-kitchen"})
    assert result["ok"] is True, result
    assert not stale.exists()
    assert fresh.exists()


async def test_a_room_with_two_announce_speakers_and_no_default_is_not_guessed(media_env):
    for device_id in ("hall-a", "hall-b"):
        media_env.director.registry.register(MediaDevice(
            id=device_id, name=device_id, kind="speaker", room="hall", supports=("announce",),
        ))
    orch, queue = _wired()
    response = await _propose(orch, {"text": "Dinner is ready.", "target": "hall"})
    assert response == {"ok": False, "reason": "ambiguous_room_media_target", "tool": "speak"}
    assert queue.enqueued == []


async def test_presence_without_a_fresh_signal_is_refused_by_the_director(media_env):
    task = SimpleNamespace(kind="toolrpc.speak", agent="jarvis", origin="generated")
    tool = speak_tool.SpeakTool(
        director=lambda: media_env.director, approved_task=lambda: task,
        authorizer=_Kernel(present_verdict=Verdict.GRANT),
    )
    result = await tool.execute({"text": "Your call starts now.", "target": "presence:auto"})
    # Where the owner is cannot be guessed: no presence store, a named refusal, no clip left.
    assert result == {"ok": False, "reason": "presence_unknown"}
    assert media_env.driver.calls == []
    assert _clips(media_env.root) == []
