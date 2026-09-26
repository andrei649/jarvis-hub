"""H182 — keep the machine awake while a turn runs, and know when it is on battery.

The power assertion is off by default, gated as ``host.control`` (permission, contract,
Action Kernel GRANT, durable audit) once per process, shared by concurrent turns and
released on the reply, on an error and when the hub quits. The power state (battery,
resume from sleep) is read, served and streamed; heavy background jobs skip their run on
battery below ``system.battery_defer_percent``; the desktop shell keeps a streaming turn
running when its window is in the background.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import power
from agents.core.action_origin import INBOUND_ACTION_ORIGIN, bind_action_origin, reset_action_origin
from agents.core.kernel import Decision, Verdict

ROOT = Path(__file__).resolve().parents[1]


# ── the OS mechanism ─────────────────────────────────────────────────────────


def test_backend_is_the_platforms_own_and_only_when_its_binary_exists():
    have = lambda name: f"/usr/bin/{name}"      # noqa: E731
    none = lambda name: None                    # noqa: E731
    assert power.backend_name("darwin", have) == "caffeinate"
    assert power.backend_name("darwin", none) == ""
    assert power.backend_name("linux", have) == "systemd-inhibit"
    assert power.backend_name("linux", none) == ""
    assert power.backend_name("win32", none) == "windows"
    assert power.backend_name("freebsd13", have) == ""


def test_the_helper_ends_with_the_hub_even_when_the_hub_is_killed():
    mac = power.backend_argv("caffeinate", 4242)
    assert mac == ["caffeinate", "-i", "-w", "4242"]
    linux = power.backend_argv("systemd-inhibit", 4242)
    assert linux[0] == "systemd-inhibit"
    assert "--what=idle:sleep" in linux and "--mode=block" in linux
    assert linux[-4:] == ["tail", "--pid=4242", "-f", "/dev/null"]   # not `sleep infinity`
    assert power.backend_argv("windows", 4242) == []
    assert power.backend_argv("", 4242) == []


# ── the shared assertion ─────────────────────────────────────────────────────


class _Proc:
    def __init__(self, pid=777):
        self.pid = pid
        self.code = None
        self.terminated = 0
        self.killed = 0
        self.waited = []

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated += 1
        self.code = -15

    def kill(self):
        self.killed += 1
        self.code = -9

    def wait(self, timeout=None):
        self.waited.append(timeout)
        if self.code is None:
            self.code = -15
        return self.code


class _Spawner:
    def __init__(self, fail=None):
        self.calls = []
        self.procs = []
        self.fail = fail

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.fail:
            raise self.fail
        proc = _Proc(pid=900 + len(self.procs))
        self.procs.append(proc)
        return proc


def _keeper(*, enabled=True, platform="linux", spawn=None, which=lambda n: "/usr/bin/" + n,
            set_state=None, killpg=None):
    groups = []
    keeper = power.KeepAwake(
        enabled=lambda: enabled, spawn=spawn or _Spawner(), platform=platform, which=which,
        set_state=set_state, pid=lambda: 4242,
        killpg=killpg if killpg is not None else (lambda pid, sig: groups.append((pid, sig))),
    )
    return keeper, groups


def test_off_by_default_asks_nothing_and_starts_nothing(monkeypatch):
    monkeypatch.delenv(power.KEEP_AWAKE_ENV, raising=False)
    assert power.keep_awake_enabled() is False
    spawn = _Spawner()
    keeper = power.KeepAwake(spawn=spawn, platform="linux", which=lambda n: "/usr/bin/" + n)
    asked = []
    assert keeper.acquire(lambda: asked.append(1)) is False
    assert asked == [] and spawn.calls == []
    assert keeper.status()["enabled"] is False and keeper.status()["active"] is False


def test_the_documented_flag_turns_it_on(monkeypatch):
    monkeypatch.setenv(power.KEEP_AWAKE_ENV, "1")
    assert power.keep_awake_enabled() is True


def test_a_turn_holds_one_assertion_and_concurrent_turns_share_it():
    spawn = _Spawner()
    keeper, groups = _keeper(spawn=spawn)
    asked = []
    assert keeper.acquire(lambda: asked.append(1)) is True
    assert keeper.acquire(lambda: asked.append(1)) is True
    assert len(spawn.calls) == 1, "a second turn shares the running assertion"
    assert asked == [1], "authorized once per process"
    argv, kw = spawn.calls[0]
    assert argv == power.backend_argv("systemd-inhibit", 4242)
    assert kw["start_new_session"] is True, "its own group, so release reaches its child"
    assert kw["stdin"] is subprocess.DEVNULL and kw["stdout"] is subprocess.DEVNULL
    status = keeper.status()
    assert status["active"] is True and status["holders"] == 2 and status["backend"] == "systemd-inhibit"

    keeper.release()
    assert groups == [] and keeper.status()["active"] is True, "one turn still runs"
    keeper.release()
    proc = spawn.procs[0]
    assert groups == [(proc.pid, signal.SIGTERM)], "the whole helper group is ended"
    assert proc.waited == [power._STOP_TIMEOUT]
    assert keeper.status()["active"] is False and keeper.status()["holders"] == 0

    keeper.release()                       # an extra release is harmless
    assert keeper.status()["holders"] == 0 and len(groups) == 1

    assert keeper.acquire(lambda: asked.append(1)) is True
    assert len(spawn.calls) == 2 and asked == [1], "the next turn starts a fresh helper, not a fresh ask"


def test_a_helper_that_already_exited_is_reaped_by_its_handle_not_its_group():
    spawn = _Spawner()
    keeper, groups = _keeper(spawn=spawn)
    keeper.acquire(lambda: None)
    spawn.procs[0].code = 1                 # gave up on its own; its pid may be reused
    status = keeper.status()
    assert status["active"] is False
    assert status["error"] == "keep-awake helper exited (code 1)"
    keeper.release()
    assert groups == [], "never signal a group whose leader is gone"
    assert spawn.procs[0].terminated == 1


def test_a_stubborn_helper_is_killed():
    class _Stubborn(_Proc):
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("x", timeout)

    stubborn = _Stubborn()
    keeper, _ = _keeper(spawn=lambda argv, **kw: stubborn)
    keeper.acquire(lambda: None)
    keeper.release()
    assert stubborn.killed == 1


def test_a_refusal_keeps_it_off_until_the_next_start_and_says_why():
    spawn = _Spawner()
    keeper, _ = _keeper(spawn=spawn)
    asked = []

    def refuse():
        asked.append(1)
        return "Jarvis is not permitted to use system-control"

    assert keeper.acquire(refuse) is False
    assert keeper.acquire(refuse) is False
    assert asked == [1], "not re-asked every turn"
    assert spawn.calls == []
    status = keeper.status()
    assert status["refused"] == "Jarvis is not permitted to use system-control"
    assert status["active"] is False and status["holders"] == 0
    keeper.release()                         # the turn's release after a refused hold
    assert keeper.status()["holders"] == 0
    keeper.reset()
    assert keeper.status()["refused"] is None


def test_a_missing_binary_or_mechanism_never_fails_the_turn():
    keeper, _ = _keeper(spawn=_Spawner(fail=FileNotFoundError("systemd-inhibit")))
    assert keeper.acquire(lambda: None) is True
    status = keeper.status()
    assert status["active"] is False and status["error"] == "keep-awake did not start (FileNotFoundError)"
    keeper.release()
    assert keeper.status()["holders"] == 0

    none, _ = _keeper(which=lambda n: None)
    assert none.acquire(lambda: None) is True
    assert none.status()["error"] == "no keep-awake mechanism on this system"
    assert none.status()["active"] is False


def test_windows_holds_and_clears_the_execution_state():
    states = []
    keeper, _ = _keeper(platform="win32", set_state=states.append)
    keeper.acquire(lambda: None)
    assert states == [power._ES_CONTINUOUS | power._ES_SYSTEM_REQUIRED]
    assert keeper.status()["active"] is True and keeper.status()["backend"] == "windows"
    keeper.release()
    assert states[-1] == power._ES_CONTINUOUS
    assert keeper.status()["active"] is False


def test_quitting_drops_every_hold():
    spawn = _Spawner()
    keeper, groups = _keeper(spawn=spawn)
    keeper.acquire(lambda: None)
    keeper.acquire(lambda: None)
    keeper.release_all()
    assert keeper.status()["holders"] == 0 and len(groups) == 1
    keeper.release()                        # a turn ending after the quit
    assert keeper.status()["holders"] == 0 and len(groups) == 1


def test_the_process_wide_hold_is_released_at_exit_and_on_shutdown():
    src = (ROOT / "agents" / "core" / "power.py").read_text(encoding="utf-8")
    assert "atexit.register(KEEP_AWAKE.release_all)" in src
    from agents import web

    life = inspect.getsource(web.lifespan)
    after_yield = life.split("\n    yield\n", 1)[1]
    assert "power.KEEP_AWAKE.release_all()" in after_yield


@pytest.mark.skipif(os.name != "posix" or not Path("/bin/sh").exists(), reason="a POSIX process group")
def test_release_ends_the_helper_and_whatever_it_started():
    """A real helper that forks a child (as systemd-inhibit does): both are gone after release."""
    started = []

    def spawn(argv, **kw):
        proc = subprocess.Popen(["/bin/sh", "-c", "sleep 60 & echo $!; wait"], stdout=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=kw["start_new_session"])
        started.append(proc)
        return proc

    keeper = power.KeepAwake(enabled=lambda: True, spawn=spawn, platform="linux", which=lambda n: "/x")
    assert keeper.acquire(lambda: None) is True
    proc = started[0]
    child = int(proc.stdout.readline())
    keeper.release()
    assert proc.poll() is not None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child, signal.SIGKILL)
        pytest.fail("the helper's child outlived the release")
    proc.stdout.close()


# ── authorization: host.control ──────────────────────────────────────────────


class _Gate:
    def __init__(self, allowed=True, raises=False):
        self.allowed = allowed
        self.raises = raises
        self.calls = []

    def check_call(self, plugin, agent):
        self.calls.append((plugin, agent))
        if self.raises:
            raise RuntimeError("gate down")
        return self.allowed


class _Kernel:
    def __init__(self, verdict=Verdict.GRANT, raises=False):
        self.verdict = verdict
        self.raises = raises
        self.actions = []

    def __call__(self, action):
        self.actions.append(action)
        if self.raises:
            raise RuntimeError("kernel down")
        return Decision(self.verdict, reason="test policy", tier=1)


class _Audit:
    def __init__(self, raises=False):
        self.raises = raises
        self.events = []

    def log(self, event):
        if self.raises:
            raise OSError("disk")
        self.events.append(event)


def _orch(**kw):
    return SimpleNamespace(permission_gate=kw.get("gate", _Gate()), audit=kw.get("audit", _Audit()))


@pytest.fixture
def kernel_on(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")


def test_a_grant_is_the_only_yes_and_it_is_audited(kernel_on):
    orch, kernel = _orch(), _Kernel()
    assert power.authorize_keep_awake(orch, kernel=kernel) is None
    assert orch.permission_gate.calls == [("system-control", "jarvis")]
    action = kernel.actions[0]
    assert action.kind == "host.control" and action.agent == "jarvis"
    assert action.payload["action"] == "power.keep_awake"
    assert action.payload["reversible"] is True and action.payload["risk_tier"] == 1
    assert action.origin == "generated"
    event = orch.audit.events[0]
    assert event.action_taken == "power.keep_awake authorized"
    assert event.content_preview == "power keep-awake"


def test_the_origin_is_the_owners_switch_not_the_turn_that_asked_first(kernel_on):
    kernel = _Kernel()
    token = bind_action_origin(INBOUND_ACTION_ORIGIN)
    try:
        assert power.authorize_keep_awake(_orch(), kernel=kernel) is None
    finally:
        reset_action_origin(token)
    assert kernel.actions[0].origin == "generated"


@pytest.mark.parametrize("gate, reason", [
    (_Gate(allowed=False), "Jarvis is not permitted to use system-control"),
    (_Gate(raises=True), "system-control permission gate is unavailable"),
    (None, "system-control permission gate is unavailable"),
])
def test_the_owners_permission_comes_first(kernel_on, gate, reason):
    kernel = _Kernel()
    assert power.authorize_keep_awake(_orch(gate=gate), kernel=kernel) == reason
    assert kernel.actions == []


def test_the_host_control_contract_names_keep_awake_and_refuses_what_it_does_not(kernel_on, monkeypatch):
    from agents.core.autonomy import remediation

    view = {"kind": "host.control", "action": "power.keep_awake", "agent": "jarvis", "target": "keep-awake"}
    assert remediation.HOST_CONTROL_CONTRACT.evaluate(view).admissible is True
    assert remediation.HOST_CONTROL_CONTRACT.evaluate({**view, "action": "power.shutdown"}).admissible is False

    real = remediation.HOST_CONTROL_CONTRACT

    class _Deny:
        def evaluate(self, view):
            return real.evaluate({**view, "action": "power.other"})

    monkeypatch.setattr(remediation, "HOST_CONTROL_CONTRACT", _Deny())
    kernel = _Kernel()
    reason = power.authorize_keep_awake(_orch(), kernel=kernel)
    assert reason.startswith("host-control contract denied:")
    assert kernel.actions == []

    class _Broken:
        def evaluate(self, view):
            raise RuntimeError("x")

    monkeypatch.setattr(remediation, "HOST_CONTROL_CONTRACT", _Broken())
    assert power.authorize_keep_awake(_orch(), kernel=kernel) == "host-control contract is unavailable"


def test_the_kernel_must_be_on_and_must_grant(monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    orch = _orch()
    assert power.authorize_keep_awake(orch, kernel=_Kernel()) == \
        "Action Kernel is required to keep the machine awake"
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    assert power.authorize_keep_awake(orch, kernel=_Kernel(Verdict.QUEUE)) == "approval required: test policy"
    assert power.authorize_keep_awake(orch, kernel=_Kernel(Verdict.DENY)) == "Action Kernel denied it: test policy"
    assert power.authorize_keep_awake(orch, kernel=_Kernel(raises=True)) == "Action Kernel is unavailable"
    assert orch.audit.events == [], "nothing is audited as authorized unless granted"


def test_anything_but_a_grant_refuses_even_a_malformed_decision(kernel_on):
    odd = lambda action: SimpleNamespace(verdict=None, reason="no verdict")   # noqa: E731
    orch = _orch()
    assert power.authorize_keep_awake(orch, kernel=odd) == "Action Kernel denied it: no verdict"
    assert orch.audit.events == []


def test_an_unbound_kernel_refuses(kernel_on, monkeypatch):
    from agents.core.kernel import binding

    monkeypatch.setattr(binding, "make_action_kernel", lambda orch: None)
    assert power.authorize_keep_awake(_orch()) == "Action Kernel is unavailable"


@pytest.mark.parametrize("audit, reason", [
    (None, "durable audit is unavailable"),
    (_Audit(raises=True), "durable audit rejected the authorization row"),
])
def test_no_durable_audit_no_assertion(kernel_on, audit, reason):
    assert power.authorize_keep_awake(_orch(audit=audit), kernel=_Kernel()) == reason


# ── the turn ─────────────────────────────────────────────────────────────────


@pytest.fixture
def turn_log(monkeypatch):
    log = []
    monkeypatch.setattr(power, "hold_for_turn", lambda orch: log.append(("hold", orch)) or True)
    monkeypatch.setattr(power, "release_for_turn", lambda held: log.append(("release", held)))
    return log


def _turn_orch(log, *, fail=None):
    async def body(*a, **kw):
        log.append(("body",))
        if fail:
            raise fail
        return "reply"

    return SimpleNamespace(_handle_input=body, _handle_input_stream=body, _start_title_upgrades=lambda t: None,
                           agents={"jarvis": object()},
                           _call_agents_parallel=lambda *a, **kw: _parallel(log, fail))


async def _parallel(log, fail):
    log.append(("body",))
    if fail:
        raise fail
    return {"jarvis": "done"}


@pytest.mark.parametrize("entry", ["handle_input", "handle_input_stream", "process"])
def test_every_turn_entry_holds_from_start_to_end(turn_log, entry):
    from agents.core.orchestrator import Orchestrator

    orch = _turn_orch(turn_log)
    reply = asyncio.run(getattr(Orchestrator, entry)(orch, "hi"))
    assert reply in ("reply", "done")
    assert turn_log == [("hold", orch), ("body",), ("release", True)]


@pytest.mark.parametrize("entry", ["handle_input", "handle_input_stream", "process"])
def test_an_error_releases_the_hold(turn_log, entry):
    from agents.core.orchestrator import Orchestrator

    orch = _turn_orch(turn_log, fail=ValueError("boom"))
    if entry == "process":
        assert asyncio.run(Orchestrator.process(orch, "hi")) == ""
    else:
        with pytest.raises(ValueError):
            asyncio.run(getattr(Orchestrator, entry)(orch, "hi"))
    assert turn_log[-1] == ("release", True)


def test_a_cancelled_turn_releases_the_hold(turn_log):
    from agents.core.orchestrator import Orchestrator

    orch = _turn_orch(turn_log, fail=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(Orchestrator.handle_input_stream(orch, "hi"))
    assert turn_log[-1] == ("release", True)


def test_hold_and_release_never_raise(monkeypatch):
    class _Boom:
        def acquire(self, authorize):
            raise RuntimeError("x")

        def release(self):
            raise RuntimeError("y")

    monkeypatch.setattr(power, "KEEP_AWAKE", _Boom())
    assert power.hold_for_turn(object()) is False
    power.release_for_turn(True)
    power.release_for_turn(False)


def test_hold_asks_host_control_for_this_orchestrator(monkeypatch):
    seen = []
    monkeypatch.setattr(power, "authorize_keep_awake", lambda orch: seen.append(orch) or None)
    keeper, _ = _keeper()
    monkeypatch.setattr(power, "KEEP_AWAKE", keeper)
    orch = object()
    assert power.hold_for_turn(orch) is True
    assert seen == [orch]
    power.release_for_turn(True)
    assert keeper.status()["holders"] == 0
    power.release_for_turn(False)
    assert keeper.status()["holders"] == 0
    assert power.hold_for_turn(orch) is True                 # another turn holds
    power.release_for_turn(False)                            # a turn that held nothing ends
    assert keeper.status()["holders"] == 1, "it must not drop the other turn's hold"
    power.release_for_turn(True)


# ── the power state ──────────────────────────────────────────────────────────


def test_battery_reading():
    assert power.read_battery(lambda: None) == {"battery": False, "on_battery": False, "percent": None,
                                                "plugged": None}

    def boom():
        raise OSError("no sensors")

    assert power.read_battery(boom)["battery"] is False
    on = power.read_battery(lambda: SimpleNamespace(percent=42.44, power_plugged=False, secsleft=10))
    assert on == {"battery": True, "on_battery": True, "percent": 42.4, "plugged": False}
    plugged = power.read_battery(lambda: SimpleNamespace(percent=80, power_plugged=True))
    assert plugged["on_battery"] is False and plugged["plugged"] is True and plugged["percent"] == 80.0
    unknown = power.read_battery(lambda: SimpleNamespace(percent="n/a", power_plugged=None))
    assert unknown == {"battery": True, "on_battery": False, "percent": None, "plugged": None}


def test_a_resume_from_sleep_is_the_wall_clock_running_ahead_of_the_monotonic_one():
    clock = {"wall": 1000.0, "mono": 50.0}
    mon = power.PowerMonitor(read=lambda: {"on_battery": False}, wall=lambda: clock["wall"],
                             mono=lambda: clock["mono"])
    first = mon.tick()
    assert first["resumed_at"] is None and first["seq"] == 1
    clock["wall"] += 30
    clock["mono"] += 30
    assert mon.tick()["seq"] == 1, "nothing changed, the sequence stays"
    clock["wall"] += power.RESUME_GAP_SECONDS + 5       # asleep: wall moved, monotonic did not
    clock["mono"] += 1
    woke = mon.tick()
    assert woke["resumed_at"] == clock["wall"] and woke["seq"] == 2
    clock["wall"] += power.RESUME_GAP_SECONDS           # a short nap is not a resume
    clock["mono"] += 1
    assert mon.tick()["resumed_at"] == woke["resumed_at"]
    assert mon.snapshot()["resumed_at"] == woke["resumed_at"]
    clock["wall"] = woke["resumed_at"] + power.RESUME_SHOWN_SECONDS + 1
    clock["mono"] += power.RESUME_SHOWN_SECONDS + 1 - power.RESUME_GAP_SECONDS
    later = mon.tick()
    assert later["resumed_at"] is None and later["seq"] == 3


def test_a_battery_change_moves_the_sequence():
    state = {"on_battery": False}
    mon = power.PowerMonitor(read=lambda: dict(state))
    assert mon.tick()["seq"] == 1
    state["on_battery"] = True
    moved = mon.tick()
    assert moved["seq"] == 2 and moved["on_battery"] is True


@pytest.mark.parametrize("raw, pct", [
    (None, 50), (True, 50), ("abc", 50), ("30", 30), (-5, 0), (150, 100), (0, 0), (100, 100), (35.9, 35),
])
def test_defer_percent(raw, pct):
    assert power.defer_percent(raw) == pct


@pytest.mark.parametrize("state, pct, deferred", [
    ({"on_battery": True, "percent": 40.0}, 50, True),
    ({"on_battery": True, "percent": 50.0}, 50, False),
    ({"on_battery": True, "percent": 49.9}, 50, True),
    ({"on_battery": False, "percent": 5.0}, 50, False),
    ({"on_battery": True, "percent": 5.0}, 0, False),
    ({"on_battery": True, "percent": 99.0}, 100, True),
    ({"on_battery": True, "percent": None}, 50, True),
    ({"on_battery": True, "percent": None}, 0, False),      # 0 is never, even not knowing the charge
    ({"on_battery": True, "percent": 100.0}, 100, True),    # 100 is always on battery, even full
    ({}, 50, False),
])
def test_should_defer(state, pct, deferred):
    assert power.should_defer(state, pct) is deferred


def test_defer_background_reads_the_setting_and_the_battery(monkeypatch):
    monkeypatch.setattr(power, "MONITOR", power.PowerMonitor(read=lambda: {"on_battery": True, "percent": 30.0}))
    asked = []

    def setting(key, default):
        asked.append((key, default))
        return 25

    assert power.defer_background(setting) is False
    assert asked == [("system.battery_defer_percent", 50)]
    assert power.defer_background(lambda k, d: 40) is True
    assert power.defer_background(None) is True, "no settings: the default 50"


def test_public_state(monkeypatch):
    monkeypatch.setattr(power, "MONITOR", power.PowerMonitor(read=lambda: {"on_battery": True, "percent": 20.0}))
    keeper, _ = _keeper(enabled=False)
    monkeypatch.setattr(power, "KEEP_AWAKE", keeper)
    state = power.public_state(lambda k, d: 30)
    assert state["power"]["on_battery"] is True and state["power"]["percent"] == 20.0
    assert state["defer_percent"] == 30 and state["background_deferred"] is True
    assert state["keep_awake"]["enabled"] is False
    assert power.public_state(None)["defer_percent"] == 50


def test_the_setting_row_exists_with_its_default():
    from agents.core import settings_db

    rows = [r for r in settings_db.DEFAULTS if r["category"] == "system" and r["key"] == "battery_defer_percent"]
    assert len(rows) == 1 and rows[0]["value"] == power.DEFAULT_DEFER_PERCENT and rows[0]["kind"] == "number"


# ── background work on battery ───────────────────────────────────────────────


class _Living:
    def __init__(self):
        self.calls = []

    async def consolidate(self, kind):
        self.calls.append(kind)
        return {}


def _sched_orch(**kw):
    living = _Living()
    cog = SimpleNamespace(sub_enabled=lambda name: True, module=lambda name: living)
    calls = []

    async def learn():
        calls.append("learn")
        return []

    async def evolve():
        calls.append("evolve")
        return []

    async def kg():
        calls.append("kg")
        return {"synced": 1}

    scout = SimpleNamespace(queries=[], scan=None)

    async def scan(**k):
        calls.append("scout")
        return {"ok": True}

    scout.scan = scan
    orch = SimpleNamespace(cognition=cog, get_setting=lambda k, d=None: d, tech_scout=scout,
                           _run_learning_loop=learn, _run_prompt_evolution=evolve, _run_worldview_kg_sync=kg,
                           **kw)
    return orch, living, calls


@pytest.mark.parametrize("job", ["run_learning_loop", "run_prompt_evolution", "run_worldview_kg_sync",
                                 "run_tech_scout", "run_memory_maintenance"])
def test_heavy_jobs_skip_their_run_on_battery(monkeypatch, job):
    from agents.core.scheduler_health import _returned_status
    from agents.core.scheduler_service import DEFERRED_ON_BATTERY, SchedulerService

    monkeypatch.setattr(power, "defer_background", lambda get_setting: True)
    orch, living, calls = _sched_orch()
    result = asyncio.run(getattr(SchedulerService(orch), job)())
    assert result == DEFERRED_ON_BATTERY and result is not DEFERRED_ON_BATTERY
    assert result["reason"] == "deferred_on_battery"
    assert _returned_status(result) == "skipped"
    assert calls == [] and living.calls == []


@pytest.mark.parametrize("job, ran", [("run_learning_loop", "learn"), ("run_prompt_evolution", "evolve"),
                                      ("run_worldview_kg_sync", "kg"), ("run_tech_scout", "scout")])
def test_heavy_jobs_run_when_plugged_in_or_when_the_state_is_unknown(monkeypatch, job, ran):
    from agents.core.scheduler_service import SchedulerService

    orch, _, calls = _sched_orch()
    monkeypatch.setattr(power, "defer_background", lambda get_setting: False)
    asyncio.run(getattr(SchedulerService(orch), job)())
    assert calls == [ran]

    def broken(get_setting):
        raise RuntimeError("no power state")

    monkeypatch.setattr(power, "defer_background", broken)
    asyncio.run(getattr(SchedulerService(orch), job)())
    assert calls == [ran, ran]


def test_the_deferral_reads_the_live_setting(monkeypatch):
    from agents.core.scheduler_service import SchedulerService

    seen = []
    monkeypatch.setattr(power, "defer_background", lambda get_setting: seen.append(get_setting) or False)
    orch, _, _ = _sched_orch()
    asyncio.run(SchedulerService(orch).run_learning_loop())
    assert seen == [orch.get_setting]


def test_the_scheduled_jobs_go_through_the_deferral():
    from agents.core.scheduler_service import SchedulerService

    class _Sched:
        def __init__(self):
            self.jobs = {}

        def add_job(self, fn, *a, **kw):
            self.jobs[kw["id"]] = fn

    sched = _Sched()
    orch, _, _ = _sched_orch(heartbeat_scheduler=SimpleNamespace(scheduler=sched),
                             config={"autonomy": {"learning_loop_interval_hours": 168}})
    service = SchedulerService(orch)
    service.schedule_learning_loop()
    assert sched.jobs["learning-loop-promotions"] == service.run_learning_loop
    assert sched.jobs["learning-loop-prompt-evolution"] == service.run_prompt_evolution
    src = inspect.getsource(SchedulerService.schedule_worldview_kg_sync)
    assert "self.run_worldview_kg_sync" in src and "self._orch._run_worldview_kg_sync" not in src


def test_the_power_monitor_ticks_every_minute(monkeypatch):
    from agents.core.scheduler_service import SchedulerService

    class _Sched:
        def __init__(self):
            self.jobs = {}

        def add_job(self, fn, *a, **kw):
            self.jobs[kw["id"]] = (fn, a, kw)

    sched = _Sched()
    orch = SimpleNamespace(heartbeat_scheduler=SimpleNamespace(scheduler=sched))
    service = SchedulerService(orch)
    monkeypatch.setenv("JARVIS_TESTING", "1")
    service.schedule_power_monitor()
    assert sched.jobs == {}
    monkeypatch.delenv("JARVIS_TESTING")
    service.schedule_power_monitor()
    fn, args, kw = sched.jobs["power-monitor"]
    assert fn == service.run_power_tick and args == ("interval",) and kw["seconds"] == 60
    monkeypatch.setattr(power, "MONITOR", power.PowerMonitor(read=lambda: {"on_battery": True}))
    assert asyncio.run(service.run_power_tick()) == {"on_battery": True}
    assert power.MONITOR.snapshot()["seq"] == 1


# ── routes ───────────────────────────────────────────────────────────────────


def test_get_power_answers_the_live_state(monkeypatch):
    from agents.core.routers import power as route

    monkeypatch.setattr(power, "MONITOR", power.PowerMonitor(read=lambda: {"on_battery": True, "percent": 10.0}))
    monkeypatch.setattr(route, "get_orch", lambda: SimpleNamespace(get_setting=lambda k, d: 20))
    response = asyncio.run(route.power_state())
    body = json.loads(response.body)
    assert body["power"]["on_battery"] is True and body["defer_percent"] == 20
    assert body["background_deferred"] is True
    assert set(body["keep_awake"]) >= {"enabled", "active", "holders", "backend", "refused", "error"}
    assert "no-store" in response.headers.get("cache-control", "")

    monkeypatch.setattr(route, "get_orch", lambda: None)
    assert json.loads(asyncio.run(route.power_state()).body)["defer_percent"] == 50


def test_the_stream_sends_a_frame_per_change_and_keeps_alive_between():
    from agents.core.routers import power as route

    states = iter([{"a": 1}, {"a": 1}, {"a": 1}, {"a": 2}, None, RuntimeError("x"), {"a": 2}])

    def read():
        item = next(states)
        if isinstance(item, Exception):
            raise item
        return item

    async def nosleep(_):
        return None

    async def collect():
        return [f async for f in route.power_events(read, sleep=nosleep, heartbeat_every=2, max_iterations=7)]

    frames = asyncio.run(collect())
    # a1 · same (idle 1) · same (idle 2: keepalive) · a2 · none (idle 1) · error (idle 2: keepalive)
    # · a2 again (idle 3: nothing — unchanged is not news)
    assert frames == [
        'data: {"type": "power", "a": 1}\n\n',
        ": keepalive\n\n",
        'data: {"type": "power", "a": 2}\n\n',
        ": keepalive\n\n",
    ]


def test_a_change_restarts_the_keepalive_count():
    from agents.core.routers import power as route

    states = iter([{"a": 1}, {"a": 1}, {"a": 2}, {"a": 2}])

    async def nosleep(_):
        return None

    async def collect():
        return [f async for f in route.power_events(lambda: next(states), sleep=nosleep, heartbeat_every=2,
                                                    max_iterations=4)]

    # one idle tick before the change and one after: never two in a row, so no keepalive
    assert asyncio.run(collect()) == ['data: {"type": "power", "a": 1}\n\n', 'data: {"type": "power", "a": 2}\n\n']


def test_the_routes_are_user_guarded():
    snapshot = json.loads((ROOT / "tests" / "_snapshots" / "route_auth.json").read_text(encoding="utf-8"))
    assert snapshot["GET /api/power"] == "user" and snapshot["GET /api/power/stream"] == "user"
    from agents import web
    from tests._route_introspect import iter_effective_routes

    found = {r.path: r for r in iter_effective_routes(web.app)
             if getattr(r, "path", "") in ("/api/power", "/api/power/stream") and hasattr(r, "dependant")}
    assert set(found) == {"/api/power", "/api/power/stream"}
    for r in found.values():
        assert "user_guard" in {getattr(d.call, "__name__", "") for d in r.dependant.dependencies}


# ── the desktop shell ────────────────────────────────────────────────────────


def test_the_desktop_windows_keep_a_streaming_turn_running_in_the_background():
    main = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert "mod throttling;" in main
    assert main.count(".background_throttling(throttle.clone())") == 1   # not Copy: the first window clones
    assert main.count(".background_throttling(throttle)") == 1, "both the HUD and the floating chat"
    assert "use tauri::utils::config::BackgroundThrottlingPolicy;" in main
    module = (ROOT / "desktop" / "src-tauri" / "src" / "throttling.rs").read_text(encoding="utf-8")
    assert '"NERVA_DESKTOP_BACKGROUND_THROTTLING"' in module
    for word in ('"disabled"', '"throttle"', '"suspend"'):
        assert word in module


@pytest.mark.skipif(sys.platform == "win32", reason="rustc test harness on POSIX CI hosts")
def test_the_throttling_parser_under_rustc(tmp_path):
    import shutil as _sh

    rustc = _sh.which("rustc")
    if rustc is None:
        pytest.skip("rustc is not installed")
    src = ROOT / "desktop" / "src-tauri" / "src" / "throttling.rs"
    out = tmp_path / "throttling_tests"
    built = subprocess.run([rustc, "--edition", "2021", "--test", str(src), "-o", str(out)],
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(out)], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "test result: ok" in ran.stdout
