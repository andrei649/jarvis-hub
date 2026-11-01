"""H019 — `nerva status` says whether a service manager runs the hub, and how many slots
are in use (Hermes `hermes status` → Gateway Service, Sessions → Slots).

`nerva status` printed version, backend, model, runnable verdict, busy agents, channels
and the e-stop, but nothing about the service manager (is the hub a systemd / launchd /
NSSM service, is the unit installed and active, its pid and uptime) and nothing about
concurrency (turns holding a session's lease, a channel's chat lanes against their cap,
sub-agents against theirs). `GET /status` now carries a `service` block
(`agents.core.service_status`) and a `slots` block, and the CLI prints both; a fact the
hub could not read is unknown, never ok.

Hermetic: every OS read is a parameter or a monkeypatched seam; no systemctl, no network.
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from agents.cli.client import HubError, HubUnavailable  # noqa: E402
from agents.cli.nerva import EXIT_NO_HUB, EXIT_OK, Context, main  # noqa: E402
from agents.core import service_status  # noqa: E402
from agents.core.channels.chat_lanes import ChatLanes  # noqa: E402
from agents.core.channels.manager import ChannelManager  # noqa: E402
from agents.core.channels.telegram import TelegramChannel  # noqa: E402
from agents.core.orchestrator import Orchestrator  # noqa: E402

# ── the service block ────────────────────────────────────────────────────────

SYSTEMD_CGROUP = "0::/system.slice/jarvis-hub.service\n"


def _ident(supervisor="none", confirmed=False, detected=True):
    return SimpleNamespace(detected=detected, supervisor=supervisor, supervisor_confirmed=confirmed)


def _stat(present=(), unreadable=()):
    def stat(path):
        if path in unreadable:
            raise PermissionError(path)
        if path not in present:
            raise FileNotFoundError(path)
        return object()
    return stat


def _probe(ident, *, platform="linux", env=None, present=(), unreadable=(), answer=None,
           cgroup=SYSTEMD_CGROUP, registry=None, which=lambda name: f"/usr/bin/{name}"):
    calls = []

    def run(argv):
        calls.append(argv)
        return answer

    row = service_status.probe(
        env or {}, identity=ident, platform=platform, read_text=lambda path: cgroup,
        stat=_stat(present, unreadable), which=which, run=run,
        registry=registry or (lambda name: None), expanduser=lambda p: p.replace("~", "/home/u"))
    return row, calls


def test_a_hub_systemd_runs_reports_its_unit_running_and_managing():
    row, calls = _probe(_ident("systemd", confirmed=True))
    assert row == {"manager": "systemd", "confirmed": True, "unit": "jarvis-hub.service",
                   "installed": True, "active": True, "managing": True, "state": "managed"}
    assert calls == [], "a hub the manager runs asks it nothing"


def test_a_weak_signal_is_unconfirmed_and_says_nothing_about_the_unit():
    row, _calls = _probe(_ident("systemd", confirmed=False), cgroup="0::/user.slice/session-3.scope\n")
    assert row["state"] == "unconfirmed" and row["manager"] == "systemd"
    assert (row["unit"], row["installed"], row["active"], row["managing"]) == (None, None, None, None)


def test_installed_but_stopped_and_installed_not_managing_are_told_apart():
    unit = "/etc/systemd/system/jarvis-hub.service"
    stopped, calls = _probe(_ident(), present={service_status.SD_BOOTED, unit}, answer="inactive\n")
    assert stopped["state"] == "installed_stopped"
    assert (stopped["installed"], stopped["active"], stopped["managing"]) == (True, False, False)
    assert calls == [["/usr/bin/systemctl", "is-active", "jarvis-hub.service"]]

    other, _ = _probe(_ident(), present={service_status.SD_BOOTED, unit}, answer="active\n")
    assert other["state"] == "installed_not_managing" and other["active"] is True

    unanswered, _ = _probe(_ident(), present={service_status.SD_BOOTED, unit}, answer=None)
    assert unanswered["state"] == "installed_not_managing" and unanswered["active"] is None


def test_a_user_unit_is_asked_of_the_user_manager():
    user_unit = "/home/u/.config/systemd/user/jarvis-hub.service"
    row, calls = _probe(_ident(), present={service_status.SD_BOOTED, user_unit}, answer="failed")
    assert row["state"] == "installed_stopped"
    assert calls == [["/usr/bin/systemctl", "--user", "is-active", "jarvis-hub.service"]]


def test_not_installed_unsupported_and_unknown_are_honest():
    row, calls = _probe(_ident(), present={service_status.SD_BOOTED})
    assert (row["state"], row["installed"], row["active"]) == ("not_installed", False, False)
    assert calls == []

    no_systemd, _ = _probe(_ident())                         # systemd is not the init
    assert no_systemd["state"] == "unsupported" and no_systemd["installed"] is None
    assert no_systemd["unit"] is None

    mac, _ = _probe(_ident(), platform="darwin")
    assert mac["state"] == "unsupported"

    unreadable, _ = _probe(_ident(), present={service_status.SD_BOOTED},
                           unreadable={"/etc/systemd/system/jarvis-hub.service"})
    assert unreadable["state"] == "unknown" and unreadable["installed"] is None

    failed, _ = _probe(_ident(detected=False))
    assert failed == {"manager": "unknown", "confirmed": False, "unit": None, "installed": None,
                      "active": None, "managing": None, "state": "unknown"}


def test_launchd_names_its_job_label():
    row, _ = _probe(_ident("launchd", confirmed=True), platform="darwin",
                    env={"XPC_SERVICE_NAME": "ai.nerva.hub"})
    assert (row["state"], row["unit"]) == ("managed", "ai.nerva.hub")
    bad, _ = _probe(_ident("launchd", confirmed=True), platform="darwin",
                    env={"XPC_SERVICE_NAME": "evil\x1b[2J"})
    assert bad["unit"] is None


def test_windows_nssm_marker_and_the_service_registry():
    managed, _ = _probe(_ident(), platform="win32", env={"NERVA_SERVICE_WRAPPER": "nssm"})
    assert (managed["manager"], managed["state"], managed["managing"]) == ("nssm", "managed", True)

    stopped, calls = _probe(_ident(), platform="win32", registry=lambda name: name == "JarvisHub",
                            answer="SERVICE_NAME: JarvisHub\n        STATE              : 1  STOPPED\n")
    assert (stopped["state"], stopped["unit"]) == ("installed_stopped", "JarvisHub")
    assert calls == [["/usr/bin/sc.exe", "query", "JarvisHub"]]

    absent, _ = _probe(_ident(), platform="win32", registry=lambda name: False)
    assert absent["state"] == "not_installed"
    unknown, _ = _probe(_ident(), platform="win32", registry=lambda name: None)
    assert unknown["state"] == "unknown"


@pytest.mark.parametrize("text, unit", [
    ("0::/system.slice/jarvis-hub.service\n", "jarvis-hub.service"),
    ("0::/user.slice/user-1000.slice/user@1000.service/app.slice/nerva.service\n", "nerva.service"),
    ("12:pids:/x\n1:name=systemd:/system.slice/jarvis-hub.service\n", "jarvis-hub.service"),
    ("0::/user.slice/user-1000.slice/session-2.scope\n", None),
    ("0::/\n", None),
    ("", None),
])
def test_cgroup_unit(text, unit):
    assert service_status.cgroup_unit(text) == unit


@pytest.mark.parametrize("answer, active", [
    ("active\n", True), ("activating", True), ("inactive\n", False), ("failed", False),
    ("unknown\n", None), ("", None), (None, None),
])
def test_systemd_state(answer, active):
    assert service_status.systemd_state(answer) is active


def test_snapshot_adds_pid_and_uptime_and_never_guesses_them():
    row = {"manager": "none", "state": "unsupported"}
    block = service_status.snapshot(started_at=1_000.0, now=lambda: 4_725.5, pid=lambda: 4242,
                                    rows=lambda: dict(row))
    assert (block["pid"], block["uptime_s"], block["started_at"]) == (4242, 3725, "1970-01-01T00:16:40Z")
    for bad in (None, float("nan"), True, 9_999.0, -1.0, "1000"):
        block = service_status.snapshot(started_at=bad, now=lambda: 4_725.5, pid=lambda: 1,
                                        rows=lambda: dict(row))
        assert block["uptime_s"] is None and block["started_at"] is None


def test_the_probe_is_cached_and_a_failure_is_unknown(monkeypatch):
    service_status.reset_cache()
    calls = []

    def probe():
        calls.append(1)
        return {"manager": "none", "state": "not_installed"}

    monkeypatch.setattr(service_status, "probe", probe)
    clock = iter([0.0, 5.0, service_status.PROBE_TTL_S + 1])
    for _ in range(3):
        service_status.cached_probe(clock=lambda: next(clock))
    assert len(calls) == 2, "the HUD's polling reads the cache inside the TTL"

    service_status.reset_cache()
    monkeypatch.setattr(service_status, "probe", lambda: (_ for _ in ()).throw(RuntimeError("bug")))
    assert service_status.cached_probe()["state"] == "unknown"
    service_status.reset_cache()


# ── the slots ────────────────────────────────────────────────────────────────


def _bare_orch():
    orch = Orchestrator.__new__(Orchestrator)
    orch._channel_sessions = {}
    orch.session_id = "shared"
    return orch


async def test_a_turn_holding_two_leases_is_one_slot_and_slots_free_after():
    orch = _bare_orch()
    gate = asyncio.Event()

    async def turn(outer, inner=None):
        async with orch.turn_lease(outer):
            if inner is not None:
                async with orch.turn_lease(inner):   # a channel turn: its base key and its session
                    await gate.wait()
            else:
                await gate.wait()

    assert orch.turn_slots() == {"running": 0, "per_session": 1, "cap": None}
    first = asyncio.ensure_future(turn("base:telegram", "session-a"))
    second = asyncio.ensure_future(turn("session-b"))
    await asyncio.sleep(0.02)
    held = sorted(key for key, lock in orch._turn_leases.items() if lock.locked())
    assert held == ["base:telegram", "session-a", "session-b"]
    assert orch.turn_slots() == {"running": 2, "per_session": 1, "cap": None}
    gate.set()
    await asyncio.gather(first, second)
    assert orch.turn_slots()["running"] == 0


async def test_a_busy_session_does_not_take_a_slot():
    orch = _bare_orch()
    orch._turn_lease_max_wait = 0.01
    gate = asyncio.Event()

    async def hold():
        async with orch.turn_lease("s"):
            await gate.wait()

    task = asyncio.ensure_future(hold())
    await asyncio.sleep(0.01)
    async with orch.turn_lease("s") as acquired:
        assert acquired is False
        assert orch.turn_slots()["running"] == 1
    gate.set()
    await task
    assert orch.turn_slots()["running"] == 0


async def test_chat_lanes_report_running_queued_and_cap():
    lanes = ChatLanes(max_active=2)
    gate = asyncio.Event()

    async def turn():
        await gate.wait()

    for chat in ("a", "a", "b", "c"):
        lanes.submit(chat, turn)
    await asyncio.sleep(0.02)
    assert lanes.usage() == {"running": 2, "queued": 2, "lanes": 3, "cap": 2}
    gate.set()
    assert await lanes.drain(1.0) is True
    assert lanes.usage() == {"running": 0, "queued": 0, "lanes": 0, "cap": 2}


def test_telegram_reports_lanes_only_while_polling():
    channel = TelegramChannel("test-token")
    assert channel.lane_usage() is None
    channel._lanes = SimpleNamespace(usage=lambda: {"running": 1, "queued": 0, "lanes": 1, "cap": 8})
    assert channel.lane_usage() == {"running": 1, "queued": 0, "lanes": 1, "cap": 8}


# ── GET /status ──────────────────────────────────────────────────────────────


def _inventory():
    return {"providers": [], "configured_model": None, "backend": "none",
            "resident_models": [], "residency_state": "offline", "models": []}


def _status(orch, monkeypatch, probe_row=None):
    import agents.web as web

    service_status.reset_cache()
    monkeypatch.setattr(service_status, "probe", lambda: dict(probe_row or {
        "manager": "systemd", "confirmed": True, "unit": "jarvis-hub.service", "installed": True,
        "active": True, "managing": True, "state": "managed"}))
    try:
        with (
            TestClient(web.app) as client,
            patch.object(web, "orch", orch),
            patch.object(web, "_list_local_models", AsyncMock(return_value=_inventory())),
            patch.object(web, "_enrich_agents", return_value=[]),
            patch.object(web, "_sys_info", return_value={}),
            patch("agents.core.routers.status.get_gateway", return_value=None),
        ):
            return client.get("/status").json()
    finally:
        service_status.reset_cache()


def _orch(**extra):
    base = {"llm_router": None, "lmstudio": None, "model_info": None, "channel_manager": None,
            "channels": {}, "running_channels": []}
    base.update(extra)
    return SimpleNamespace(**base)


def test_status_carries_the_service_block_with_pid_and_uptime(monkeypatch):
    import os

    body = _status(_orch(), monkeypatch)
    service = body["service"]
    assert (service["manager"], service["state"], service["unit"]) == ("systemd", "managed", "jarvis-hub.service")
    assert service["pid"] == os.getpid()
    assert isinstance(service["uptime_s"], int) and service["uptime_s"] >= 0
    assert service["started_at"].endswith("Z")


def test_status_carries_slot_usage(monkeypatch):
    lanes = SimpleNamespace(lane_usage=lambda: {"running": 3, "queued": 1, "lanes": 3, "cap": 8})
    idle = SimpleNamespace(lane_usage=lambda: None)
    orch = _orch(channels={"telegram": lanes, "discord": SimpleNamespace(), "slack": idle},
                 turn_slots=lambda: {"running": 2, "per_session": 1, "cap": None},
                 subagents=SimpleNamespace(stats=lambda: {"active": 1, "cap": 3, "total": 9}))
    assert _status(orch, monkeypatch)["slots"] == {
        "turns": {"running": 2, "per_session": 1, "cap": None},
        "lanes": [{"channel": "telegram", "running": 3, "queued": 1, "lanes": 3, "cap": 8}],
        "subagents": {"running": 1, "cap": 3},
    }


def test_status_slots_unknown_when_the_hub_cannot_count(monkeypatch):
    broken = SimpleNamespace(stats=lambda: (_ for _ in ()).throw(RuntimeError("db")))
    bad_lane = SimpleNamespace(lane_usage=lambda: {"running": "x"})
    slots = _status(_orch(channels={"telegram": bad_lane}, subagents=broken), monkeypatch)["slots"]
    assert slots["turns"] is None and slots["subagents"] is None
    assert slots["lanes"] == [{"channel": "telegram", "running": None, "queued": None, "lanes": None, "cap": None}]


def test_status_reads_the_real_orchestrator_counters(monkeypatch):
    orch = _bare_orch()
    orch.channel_manager = ChannelManager()
    orch.channels = {}
    orch.running_channels = []
    orch.subagents = None
    slots = _status(orch, monkeypatch)["slots"]
    assert slots["turns"] == {"running": 0, "per_session": 1, "cap": None}


# ── nerva status ─────────────────────────────────────────────────────────────


class _Hub:
    def __init__(self, routes=None, *, down=False):
        self.routes = dict(routes or {})
        self.down = down
        self.base_url = "http://127.0.0.1:8080"

    def get(self, path):
        if self.down:
            raise HubUnavailable(self.base_url, "connection refused")
        if path not in self.routes:
            raise HubError(404, f"no fake route {path}")
        return self.routes[path]


def _cli(argv, hub):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


STATUS = {"version": "1.0.0", "llm_backend": "lm-studio", "loaded_model": "gemma-4", "model_state": "loaded",
          "agents": [], "agents_online": 0, "agents_total": 18, "channels": [{"id": "telegram"}]}


def _status_out(service=None, slots=None, **extra):
    body = dict(STATUS, **extra)
    if service is not None:
        body["service"] = service
    if slots is not None:
        body["slots"] = slots
    code, out, _err = _cli(["status"], _Hub({"/status": body, "/api/ops/estop": {"engaged": False}}))
    assert code == EXIT_OK
    return out


def _service(state, **fields):
    row = {"manager": "none", "confirmed": False, "unit": "jarvis-hub.service", "installed": None,
           "active": None, "managing": False, "state": state, "pid": 4242, "started_at": "x",
           "uptime_s": 3725}
    row.update(fields)
    return row


@pytest.mark.parametrize("block, line", [
    (_service("managed", manager="systemd", confirmed=True, managing=True),
     "service:     systemd — running as jarvis-hub.service · pid 4242 · up 1:02:05"),
    (_service("managed", manager="nssm", unit=None),
     "service:     nssm — running (unit name unknown) · pid 4242"),
    (_service("unconfirmed", manager="systemd", unit=None, managing=None),
     "service:     systemd? — not confirmed that it runs this hub · pid 4242"),
    (_service("installed_not_managing", installed=True, active=True),
     "service:     none detected — jarvis-hub.service is installed and active but not managing this hub"),
    (_service("installed_not_managing", installed=True, active=None),
     "jarvis-hub.service is installed (state unknown) but not managing this hub"),
    (_service("installed_stopped", installed=True, active=False),
     "service:     none detected — jarvis-hub.service is installed but stopped; this hub runs outside it"),
    (_service("not_installed", installed=False, active=False),
     "service:     none detected — jarvis-hub.service is not installed · pid 4242"),
    (_service("unsupported", unit=None),
     "service:     none detected — no service unit Nerva ships applies on this host"),
    (_service("unknown", manager="unknown", unit=None, pid=None, uptime_s=None),
     "service:     unknown — the service manager could not be read · pid unknown · up unknown"),
])
def test_status_prints_the_service_block(block, line):
    assert line in _status_out(service=block)


def test_status_never_prints_a_name_outside_systemds_characters():
    out = _status_out(service=_service("managed", manager="systemd", unit="x\x1b]0;pwned\x07.service"))
    assert "\x1b" not in out and "running (unit name unknown)" in out


def test_status_says_unknown_for_an_older_hub_without_the_blocks():
    out = _status_out()
    assert "service:     unknown (this hub does not report it)" in out
    assert "slots:       unknown (this hub does not report it)" in out


def test_status_prints_the_slots():
    out = _status_out(slots={
        "turns": {"running": 2, "per_session": 1, "cap": None},
        "lanes": [{"channel": "telegram", "running": 8, "queued": 3, "lanes": 9, "cap": 8}],
        "subagents": {"running": 1, "cap": 3},
    })
    assert ("slots:       turns 2 running (1 per session, no hub-wide cap) · telegram lanes 8/8 in use "
            "(full), 3 queued · sub-agents 1/3 in use") in out


def test_status_slots_unknown_parts_read_unknown():
    out = _status_out(slots={"turns": None, "lanes": [], "subagents": None})
    assert "slots:       turns unknown · sub-agents unknown" in out


def test_status_with_no_hub_says_what_the_service_unit_is_doing(monkeypatch):
    monkeypatch.setattr(service_status, "shipped_unit", lambda: {
        "applicable": True, "unit": "jarvis-hub.service", "installed": True, "active": False})
    code, out, err = _cli(["status"], _Hub(down=True))
    assert code == EXIT_NO_HUB
    assert "service:     jarvis-hub.service is installed but stopped" in out
    assert "Start the hub" in err

    monkeypatch.setattr(service_status, "shipped_unit", lambda: {
        "applicable": True, "unit": "jarvis-hub.service", "installed": None, "active": None})
    _code, out, _err = _cli(["status"], _Hub(down=True))
    assert "jarvis-hub.service: could not tell whether it is installed" in out


def test_status_with_no_hub_stays_quiet_off_this_machine_or_in_json(monkeypatch):
    asked = []
    monkeypatch.setattr(service_status, "shipped_unit", lambda: asked.append(1) or {
        "applicable": True, "unit": "jarvis-hub.service", "installed": True, "active": False})
    remote = _Hub(down=True)
    remote.base_url = "http://192.0.2.10:8080"
    code, out, _err = _cli(["status"], remote)
    assert code == EXIT_NO_HUB and out == "" and asked == [], "this box's unit says nothing of another"
    code, out, _err = _cli(["status", "--json"], _Hub(down=True))
    assert code == EXIT_NO_HUB and out == ""
    monkeypatch.setattr(service_status, "shipped_unit", lambda: {"applicable": False})
    code, out, _err = _cli(["status"], _Hub(down=True))
    assert code == EXIT_NO_HUB and out == ""
