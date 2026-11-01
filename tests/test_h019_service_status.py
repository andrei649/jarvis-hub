"""H019 — `nerva status` says whether a service manager runs the hub, and how many slots
are in use (Hermes `hermes status` → Gateway Service, Sessions → Slots).

`nerva status` printed version, backend, model, runnable verdict, busy agents, channels
and the e-stop, but nothing about the service manager (is the hub a systemd / launchd /
NSSM service, is the unit installed and active, its pid and uptime) and nothing about
concurrency (turns holding a session's lease, a channel's chat lanes against their cap,
sub-agents against theirs). `GET /status` now carries a `service` block
(`agents.core.service_status`) and a `slots` block, and the CLI prints both; a fact the
hub could not read is unknown, never ok. Who holds the turn slots (surface, session id,
age) is the user-guarded `GET /api/status/slots`, printed under `slots:`; an engaged
e-stop is a banner right under the header. The service manager's binary is never
looked up on PATH or in the current directory.

Hermetic: every OS read is a parameter or a monkeypatched seam; no systemctl, no network.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
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
from agents.core.commands import Principal  # noqa: E402
from agents.core.orchestrator import Orchestrator, bind_turn_principal, reset_turn_principal  # noqa: E402

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
           cgroup=SYSTEMD_CGROUP, registry=None, isfile=lambda path: True):
    calls = []

    def run(argv):
        calls.append(argv)
        return answer

    row = service_status.probe(
        env or {}, identity=ident, platform=platform, read_text=lambda path: cgroup,
        stat=_stat(present, unreadable), isfile=isfile, run=run,
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
    assert calls == [["C:\\Windows\\System32\\sc.exe", "query", "JarvisHub"]]

    absent, _ = _probe(_ident(), platform="win32", registry=lambda name: False)
    assert absent["state"] == "not_installed"
    unknown, _ = _probe(_ident(), platform="win32", registry=lambda name: None)
    assert unknown["state"] == "unknown"


# ── the service manager's binary is never searched for ───────────────────────

SC_EXE = "C:\\Windows\\System32\\sc.exe"


def _never_which(*_args, **_kwargs):
    raise AssertionError("shutil.which searched PATH (and, on Windows, the current directory)")


def test_systemctl_comes_only_from_the_fixed_system_folders(monkeypatch, tmp_path):
    planted = tmp_path / "systemctl"
    planted.write_text("#!/bin/sh\necho active\n")
    planted.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}.")
    monkeypatch.setattr(shutil, "which", _never_which)
    asked = []

    def isfile(path):
        asked.append(path)
        return path == "/usr/sbin/systemctl"

    assert service_status.systemctl_path(isfile=isfile) == "/usr/sbin/systemctl"
    assert asked == ["/usr/bin/systemctl", "/bin/systemctl", "/usr/sbin/systemctl"]
    assert service_status.systemctl_path(isfile=lambda path: False) is None


def test_a_planted_systemctl_on_path_or_in_the_cwd_is_never_run(monkeypatch, tmp_path):
    """The real lookup (no isfile seam): a systemctl planted in the current directory and
    on PATH is never what runs; only one in a system folder may be."""
    planted = tmp_path / "systemctl"
    planted.write_text("#!/bin/sh\necho active\n")
    planted.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}.")
    unit = "/etc/systemd/system/jarvis-hub.service"
    ran = []
    service_status.shipped_unit(platform="linux", stat=_stat({service_status.SD_BOOTED, unit}),
                                run=lambda argv: ran.append(argv) or "active\n")
    fixed = {f"{folder}/systemctl" for folder in service_status.POSIX_SYSTEM_BIN_DIRS}
    assert all(argv[0] in fixed for argv in ran), ran


def test_without_systemctl_in_a_system_folder_nothing_runs_and_the_state_is_unknown():
    unit = "/etc/systemd/system/jarvis-hub.service"
    row, calls = _probe(_ident(), present={service_status.SD_BOOTED, unit}, answer="active\n",
                        isfile=lambda path: path == "/home/u/bin/systemctl")
    assert calls == []
    assert (row["state"], row["installed"], row["active"]) == ("installed_not_managing", True, None)


def test_sc_exe_comes_only_from_system32():
    present = {"D:\\WinNT\\System32\\sc.exe", SC_EXE}
    asked = []

    def isfile(path):
        asked.append(path)
        return path in present

    assert service_status.sc_path({"SystemRoot": "D:\\WinNT"}, isfile=isfile) == "D:\\WinNT\\System32\\sc.exe"
    assert service_status.sc_path({}, isfile=isfile) == SC_EXE
    # A SystemRoot that is not an absolute drive path would point the lookup back at the
    # current directory (or a share): it is skipped for the C:\\Windows fallback.
    for root in (".", "Windows", "..\\x", "C:relative", "\\\\host\\share\\Windows", "\\Windows"):
        asked.clear()
        assert service_status.sc_path({"SystemRoot": root}, isfile=isfile) == SC_EXE, root
        assert asked == [SC_EXE], root
    # Named but missing there: the fallback is the only other place asked; then nothing.
    asked.clear()
    assert service_status.sc_path({"SystemRoot": "D:\\WinNT"}, isfile=lambda p: asked.append(p) and False) is None
    assert asked == ["D:\\WinNT\\System32\\sc.exe", SC_EXE]


def test_a_planted_sc_in_the_cwd_is_never_run_on_windows(monkeypatch):
    """review-H019 B1: `which("sc.exe")` on Windows finds a planted sc.exe/sc.bat in the
    folder `nerva status` runs from before System32's."""
    monkeypatch.setattr(shutil, "which", _never_which)
    ran = []

    def run(argv):
        ran.append(argv)
        return "SERVICE_NAME: JarvisHub\n        STATE              : 4  RUNNING\n"

    row = service_status.shipped_unit(platform="win32", env={"SystemRoot": "C:\\Windows"},
                                      registry=lambda name: True, isfile=lambda path: path == SC_EXE, run=run)
    assert ran == [[SC_EXE, "query", "JarvisHub"]] and row["active"] is True

    ran.clear()
    row = service_status.shipped_unit(platform="win32", env={}, registry=lambda name: True,
                                      isfile=lambda path: False, run=run)
    assert ran == [] and (row["installed"], row["active"]) == (True, None)


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


async def test_each_running_turn_is_a_holder_with_its_surface_session_and_age():
    orch = _bare_orch()
    gate = asyncio.Event()

    async def turn(principal, outer, inner=None):
        token = bind_turn_principal(principal) if principal is not None else None
        try:
            async with orch.turn_lease(outer):
                if inner is not None:
                    async with orch.turn_lease(inner):   # the channel turn's session lease
                        await gate.wait()
                else:
                    await gate.wait()
        finally:
            if token is not None:
                reset_turn_principal(token)

    assert orch.turn_holders() == []
    tasks = [asyncio.ensure_future(turn(Principal(channel="telegram", sender="42"),
                                        "ch_telegram_dm_abc", "ch_telegram_dm_abc_g1"))]
    await asyncio.sleep(0.01)
    tasks.append(asyncio.ensure_future(turn(Principal(channel="web", admin=True), "session-b")))
    await asyncio.sleep(0.01)
    tasks.append(asyncio.ensure_future(turn(None, "kanban-worker-7")))   # no channel bound
    await asyncio.sleep(0.01)
    rows = orch.turn_holders(now=orch.turn_holders()[0]["started_at"] + 65)
    assert [(row["surface"], row["session_id"]) for row in rows] == [
        ("telegram", "ch_telegram_dm_abc_g1"), ("web", "session-b"), ("unknown", "kanban-worker-7")]
    assert rows[0]["age_s"] == 65 and all(row["age_s"] >= 0 for row in rows)
    assert orch.turn_slots()["running"] == 3 == len(rows)
    gate.set()
    await asyncio.gather(*tasks)
    assert orch.turn_holders() == [] and orch.turn_slots()["running"] == 0


async def test_a_turn_refused_as_busy_is_not_listed_as_a_holder():
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
        assert [row["session_id"] for row in orch.turn_holders()] == ["s"]
    gate.set()
    await task


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
    return _get(orch, monkeypatch, "/status", probe_row=probe_row).json()


def _get(orch, monkeypatch, path, *, probe_row=None, headers=None):
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
            return client.get(path, headers=headers or {})
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


HOLDER_ROWS = [
    {"surface": "telegram", "session_id": "ch_telegram_dm_abc", "started_at": 1_000.0, "age_s": 65},
    {"surface": "web", "session_id": "../../etc/passwd", "started_at": 1_100.0, "age_s": 3},
    {"surface": "\x1b[2Jevil", "session_id": "s2", "started_at": None, "age_s": -1},
    "junk",
]


def _holder_orch(rows=HOLDER_ROWS):
    return _orch(turn_holders=lambda: list(rows),
                 turn_slots=lambda: {"running": 3, "per_session": 1, "cap": None})


def test_the_public_status_never_carries_a_holder(monkeypatch):
    body = _status(_holder_orch(), monkeypatch)
    assert body["slots"]["turns"] == {"running": 3, "per_session": 1, "cap": None}
    text = json.dumps(body)
    assert "ch_telegram_dm_abc" not in text and "holders" not in text


def test_the_slot_holders_route_lists_one_row_per_holder(monkeypatch):
    response = _get(_holder_orch(), monkeypatch, "/api/status/slots")
    assert response.status_code == 200
    body = response.json()
    assert body["holders"] == [
        {"surface": "telegram", "session_id": "ch_telegram_dm_abc", "started_at": "1970-01-01T00:16:40Z", "age_s": 65},
        # an id the session store would refuse is not sent, nor a surface that is no channel id
        {"surface": "web", "session_id": None, "started_at": "1970-01-01T00:18:20Z", "age_s": 3},
        {"surface": "unknown", "session_id": "s2", "started_at": None, "age_s": None},
    ]
    assert body["holders_total"] == 3
    assert body["slots"]["turns"] == {"running": 3, "per_session": 1, "cap": None}
    assert "no-store" in response.headers["cache-control"]


def test_the_slot_holders_route_is_bounded_and_honest_when_it_cannot_list(monkeypatch):
    from agents.core.routers import status as status_router

    many = [{"surface": "web", "session_id": f"s{i}", "started_at": 1_000.0 + i, "age_s": 1}
            for i in range(status_router.SLOT_HOLDERS_LIMIT + 50)]
    body = _get(_holder_orch(many), monkeypatch, "/api/status/slots").json()
    assert len(body["holders"]) == status_router.SLOT_HOLDERS_LIMIT
    assert body["holders_total"] == status_router.SLOT_HOLDERS_LIMIT + 50

    body = _get(_orch(), monkeypatch, "/api/status/slots").json()   # an orchestrator that cannot list
    assert body["holders"] is None and body["holders_total"] is None

    broken = _orch(turn_holders=lambda: (_ for _ in ()).throw(RuntimeError("bug")))
    assert _get(broken, monkeypatch, "/api/status/slots").json()["holders"] is None

    odd = [{"surface": "web", "session_id": "s1", "started_at": start, "age_s": 1}
           for start in (float("inf"), float("nan"), 1e20, True, "1000")]
    rows = _get(_holder_orch(odd), monkeypatch, "/api/status/slots").json()["holders"]
    assert [row["started_at"] for row in rows] == [None] * len(odd), "a start that is no instant is unknown"


def test_the_slot_holders_route_needs_the_user_guard(monkeypatch):
    import agents.web as web
    from agents.core.routers._deps import user_guard

    web.app.dependency_overrides.pop(user_guard, None)     # the real guard, not conftest's bypass
    monkeypatch.setattr(web, "_user_credential_required", lambda: True)
    monkeypatch.setattr(web, "_user_credential_ok",
                        lambda user_supplied="", admin_supplied="": user_supplied == "user-test-token")
    refused = _get(_holder_orch(), monkeypatch, "/api/status/slots")
    assert refused.status_code == 401 and "ch_telegram_dm_abc" not in refused.text
    wrong = _get(_holder_orch(), monkeypatch, "/api/status/slots", headers={"X-User-Token": "nope"})
    assert wrong.status_code == 401
    allowed = _get(_holder_orch(), monkeypatch, "/api/status/slots", headers={"X-User-Token": "user-test-token"})
    assert allowed.status_code == 200 and allowed.json()["holders"][0]["session_id"] == "ch_telegram_dm_abc"
    # the public /status stays open and counts-only under the same posture
    public = _get(_holder_orch(), monkeypatch, "/status")
    assert public.status_code == 200 and "ch_telegram_dm_abc" not in public.text


def test_the_slot_holders_route_is_pinned_to_the_user_tier():
    import agents.web as web
    from agents.core.routers._deps import admin_guard, user_guard
    from tests._route_introspect import iter_effective_routes

    routes = [r for r in iter_effective_routes(web.app) if getattr(r, "path", "") == "/api/status/slots"]
    assert len(routes) == 1 and routes[0].methods == {"GET"}
    calls = {dep.call for dep in routes[0].dependant.dependencies}
    assert user_guard in calls and admin_guard not in calls
    assert "/api/status/slots" in web._NO_STORE_PATHS


async def test_the_slot_holders_route_reads_a_real_turn_lease(monkeypatch):
    orch = _bare_orch()
    orch.channel_manager = ChannelManager()
    orch.channels = {}
    orch.running_channels = []
    orch.subagents = None
    gate, held = asyncio.Event(), asyncio.Event()

    async def turn():
        token = bind_turn_principal(Principal(channel="telegram"))
        try:
            async with orch.turn_lease("ch_telegram_dm_abc"):
                held.set()
                await gate.wait()
        finally:
            reset_turn_principal(token)

    from agents.core.routers import status as status_router

    task = asyncio.ensure_future(turn())
    await held.wait()
    monkeypatch.setattr(status_router, "get_orch", lambda: orch)
    response = await status_router.status_slots()
    body = json.loads(response.body)
    gate.set()
    await task
    assert [(row["surface"], row["session_id"]) for row in body["holders"]] == [("telegram", "ch_telegram_dm_abc")]
    assert body["slots"]["turns"]["running"] == 1


async def test_the_slot_holders_route_is_503_before_the_hub_is_up(monkeypatch):
    from agents.core.routers import status as status_router

    monkeypatch.setattr(status_router, "get_orch", lambda: None)
    response = await status_router.status_slots()
    assert response.status_code == 503


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
        answer = self.routes[path]
        if isinstance(answer, HubError):
            raise answer
        return answer


def _cli(argv, hub):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: hub)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


STATUS = {"version": "1.0.0", "llm_backend": "lm-studio", "loaded_model": "gemma-4", "model_state": "loaded",
          "agents": [], "agents_online": 0, "agents_total": 18, "channels": [{"id": "telegram"}]}


def _status_out(service=None, slots=None, *, holders=None, estop=None, **extra):
    body = dict(STATUS, **extra)
    if service is not None:
        body["service"] = service
    if slots is not None:
        body["slots"] = slots
    routes = {"/status": body, "/api/ops/estop": estop if estop is not None else {"engaged": False}}
    if holders is not None:
        routes["/api/status/slots"] = holders
    code, out, _err = _cli(["status"], _Hub(routes))
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


# ── nerva status: the slot holders ───────────────────────────────────────────

SLOTS = {"turns": {"running": 2, "per_session": 1, "cap": None}, "lanes": [], "subagents": {"running": 0, "cap": 3}}
INDENT = " " * 15


def _lines_after(out, prefix):
    lines = out.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    return lines[index + 1:]


def test_status_prints_one_row_per_slot_holder_under_slots():
    out = _status_out(slots=SLOTS, holders={"slots": SLOTS, "holders_total": 3, "holders": [
        {"surface": "telegram", "session_id": "ch_telegram_dm_abc", "started_at": "x", "age_s": 65},
        {"surface": "web", "session_id": None, "started_at": "x", "age_s": 3},
    ]})
    after = _lines_after(out, "  slots:       ")
    assert after[0] == f"{INDENT}{'telegram':<17} {'ch_telegram_dm_abc':<24} held 0:01:05"
    assert after[1] == f"{INDENT}{'web':<17} {'?':<24} held 0:00:03"
    assert after[2] == f"{INDENT}… and 1 more"
    assert after[3].startswith("  e-stop:")


def test_status_holder_rows_never_print_a_control_sequence():
    out = _status_out(slots=SLOTS, holders={"holders": [
        {"surface": "\x1b]0;pwned\x07", "session_id": "s\x1b[2J", "age_s": None}], "holders_total": 1})
    assert "\x1b" not in out
    assert f"{INDENT}{'unknown':<17} {'?':<24} held unknown" in out


def test_status_without_the_holders_route_prints_no_rows():
    out = _status_out(slots=SLOTS)                       # an older hub: 404
    assert _lines_after(out, "  slots:       ")[0].startswith("  e-stop:")


def test_status_says_why_holders_are_missing_when_the_hub_refuses_them():
    out = _status_out(slots=SLOTS, holders=HubError(401, "user token required"))
    assert f"{INDENT}holders (needs JARVIS_USER_TOKEN or JARVIS_ADMIN_TOKEN to read)" in out
    idle = dict(SLOTS, turns={"running": 0, "per_session": 1, "cap": None})
    out = _status_out(slots=idle, holders=HubError(401, "user token required"))
    assert "holders (" not in out, "nothing is held, so nothing is hidden"


def test_status_json_carries_the_slot_holders():
    detail = {"slots": SLOTS, "holders": [], "holders_total": 0}
    code, out, _err = _cli(["status", "--json"], _Hub({"/status": STATUS, "/api/ops/estop": {"engaged": False},
                                                        "/api/status/slots": detail}))
    assert code == EXIT_OK and json.loads(out)["slot_holders"] == detail
    code, out, _err = _cli(["status", "--json"], _Hub({"/status": STATUS, "/api/ops/estop": {"engaged": False}}))
    assert code == EXIT_OK and json.loads(out)["slot_holders"] is None


# ── nerva status: the e-stop banner ──────────────────────────────────────────

ENGAGED = {"engaged": True, "state": {"engaged_at": "2026-11-01T09:00:00Z", "reason": "smoke"}}


def test_an_engaged_estop_is_a_banner_right_under_the_header():
    lines = _status_out(estop=ENGAGED).splitlines()
    assert lines[0] == "nerva 1.0.0 — http://127.0.0.1:8080"
    assert lines[1] == ("  PAUSED — emergency stop ENGAGED since 2026-11-01T09:00:00Z — smoke; "
                        "`nerva estop resume` lifts it")
    assert lines[2].startswith("  backend:")
    # the e-stop line keeps its place and wording
    assert lines[-1] == "  e-stop:      ENGAGED since 2026-11-01T09:00:00Z — smoke"


def test_no_banner_when_the_estop_is_off_or_unreadable():
    lines = _status_out().splitlines()
    assert lines[1].startswith("  backend:") and not any("PAUSED" in line for line in lines)
    assert lines[-1] == "  e-stop:      not engaged"
    code, out, _err = _cli(["status"], _Hub({"/status": STATUS,
                                             "/api/ops/estop": HubError(401, "user token required")}))
    assert code == EXIT_OK and "PAUSED" not in out and out.splitlines()[1].startswith("  backend:")


def test_the_banner_never_prints_a_control_sequence_from_the_hub():
    hostile = {"engaged": True, "state": {"engaged_at": "t0\x1b[2J", "reason": "x\x1b]0;pwned\x07"}}
    out = _status_out(estop=hostile)
    assert "\x1b" not in out and "\x07" not in out
    assert out.splitlines()[1].startswith("  PAUSED — emergency stop ENGAGED since t0 [2J — x ]0;pwned ;")
    no_reason = _status_out(estop={"engaged": True, "state": None}).splitlines()
    assert no_reason[1] == "  PAUSED — emergency stop ENGAGED since ? — no reason given; `nerva estop resume` lifts it"
