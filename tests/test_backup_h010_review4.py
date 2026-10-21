"""H010 review round 4 — the in-place restore holds in every shipped deployment, and the
hub that performs it is proven the way the coordinator was.

Each test pins one finding of the fourth review:

* docker-compose.yml: the hub runs serve.py (the only entry that applies a staged restore
  and restarts itself), the hub and the coordinator share one data root, and they share
  one pid namespace so the pid marks (runtime.pid, hub.lock, the journal) are readable
  across the two containers;
* a coordinator that has built an orchestrator never clears its runtime mark — not on a
  SIGTERM stop and not when aclose() raises — so a waiting apply cannot start while its
  SQLite handles are still open;
* the hub's self-restart re-exec carries no descriptor into the new image, and the apply
  refuses to run (a recorded deferral) while the applying process holds a SQLite file under
  the root;
* a real ``serve.py`` hub restarts itself, applies the staged restore, and afterwards holds
  only the restored files (no "(deleted)" inode), even when a DB handle was inheritable.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import sqlite3
import subprocess  # nosec B404 - the test runs this interpreter on fixed scripts
import sys
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

from agents.core import backup as bk
from agents.core import hub_restart, install_identity

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts import coordinator  # noqa: E402

_LINUX_PROC = sys.platform.startswith("linux") and Path("/proc/self/fd").is_dir()


def _seed(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def _rows(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        conn.close()


def _wait_for(predicate, timeout: float = 120.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"{what} not reached in {timeout:g}s")
        time.sleep(0.1)


@pytest.fixture()
def root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _seed(data / "h010probe.db", 1)
    monkeypatch.setenv("JARVIS_HOME", str(data))
    monkeypatch.setenv("JARVIS_RESTORE_RUNTIME_WAIT_SECONDS", "0")
    monkeypatch.delenv("JARVIS_RESTORE_STAGE_TTL_HOURS", raising=False)
    monkeypatch.delenv("JARVIS_RUNTIME_RESTORE_GRACE_SECONDS", raising=False)
    hub_restart.reset()
    yield data
    hub_restart.reset()


# ── 1. docker-compose.yml can actually do the in-place restore ───────────────────

def _compose() -> dict:
    return yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))


def _command(service: dict) -> str:
    build = service.get("build") or {}
    inline = build.get("dockerfile_inline", "") if isinstance(build, dict) else ""
    cmd = [ln for ln in inline.splitlines() if ln.strip().startswith("CMD ")]
    if service.get("command"):
        return json.dumps(service["command"])
    return cmd[-1] if cmd else ""


def _env(service: dict) -> dict:
    env = service.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) for item in env)
    return {k: str(v) for k, v in env.items()}


def _mounts(service: dict) -> dict:
    """target path -> named volume, for the service's named-volume mounts."""
    out = {}
    for item in service.get("volumes") or []:
        source, _, target = str(item).partition(":")
        out[target.split(":")[0]] = source
    return out


def test_every_compose_service_that_opens_the_data_root_runs_a_restore_aware_entry():
    services = _compose()["services"]
    ours = {name: svc for name, svc in services.items()
            if isinstance(svc.get("build"), dict) and svc["build"].get("context") == "."}
    assert set(ours) == {"jarvis", "runtime-coordinator"}
    for name, svc in ours.items():
        cmd = _command(svc)
        assert "uvicorn" not in cmd, f"{name} runs raw uvicorn: a staged restore is never applied"
    assert '"serve.py"' in _command(ours["jarvis"])
    assert '"scripts/runtime_supervisor.py"' in _command(ours["runtime-coordinator"])


def test_the_compose_hub_and_coordinator_share_one_data_root_and_pid_namespace():
    services = _compose()["services"]
    hub, runtime = services["jarvis"], services["runtime-coordinator"]
    home = _env(hub).get("JARVIS_HOME")
    assert home and _env(runtime).get("JARVIS_HOME") == home
    assert _mounts(hub).get(home) and _mounts(hub)[home] == _mounts(runtime).get(home)
    assert _mounts(hub)[home] in (_compose().get("volumes") or {})
    # runtime.pid, hub.lock and the restore journal are pids: one namespace, or every
    # probe across the two containers reads "nobody there".
    assert runtime.get("pid") == "service:jarvis"
    assert hub.get("init") is True                       # orphans in that namespace are reaped


def test_the_compose_hub_keeps_the_loopback_posture_serve_py_enforces():
    hub = _compose()["services"]["jarvis"]
    assert hub.get("network_mode") == "host" and "ports" not in hub
    assert _env(hub).get("JARVIS_HOST") == "127.0.0.1"


# ── 2. a coordinator that built an orchestrator never clears its mark ────────────

class _Orch:
    runtime_log = None

    def __init__(self, log, *, aclose_error: bool = False):
        self._runtime_settings = {}
        self._log = log
        self._aclose_error = aclose_error

    async def start_channels(self):
        self._log.append("start")

    async def stop_channels(self):
        self._log.append("stop")

    async def aclose(self):
        self._log.append("aclose")
        if self._aclose_error:
            raise RuntimeError("a store refused to close")


def _patch(monkeypatch, tmp_path, log, *, aclose_error=False, stops=None):
    async def _build():
        log.append("build")
        return _Orch(log, aclose_error=aclose_error)

    def _handlers(stop):
        if stops is not None:
            stops.append(stop)

    monkeypatch.setattr(coordinator, "_build_orchestrator", _build)
    monkeypatch.setattr(coordinator, "_open_root_files", lambda: [])
    if stops is not None:
        monkeypatch.setattr(coordinator, "_install_stop_handlers", _handlers)
    monkeypatch.setenv("JARVIS_RUNTIME_RESTORE_POLL", "0.05")
    monkeypatch.setenv("JARVIS_RUNTIME_LOG", str(tmp_path / "r.jsonl"))
    monkeypatch.setenv("JARVIS_RUNTIME_STATE", str(tmp_path / "s.json"))


def test_a_stop_after_the_build_keeps_the_mark_until_the_process_is_gone(root, monkeypatch, tmp_path):
    log: list = []
    stops: list = []
    _patch(monkeypatch, tmp_path, log, stops=stops)

    async def _scenario():
        task = asyncio.create_task(coordinator.run())
        for _ in range(200):
            if "start" in log:
                break
            await asyncio.sleep(0.01)
        stops[0].set()                                    # what SIGTERM does
        await asyncio.wait_for(task, 10)

    asyncio.run(_scenario())
    assert log.count("build") == 1 and "aclose" in log
    # The stores' handles close only when the process exits: the mark stays with this pid.
    assert (root / "runtime.pid").read_text().strip() == str(os.getpid())


def test_an_aclose_that_raises_keeps_the_mark(root, monkeypatch, tmp_path):
    log: list = []
    stops: list = []
    _patch(monkeypatch, tmp_path, log, aclose_error=True, stops=stops)
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name

    async def _scenario():
        task = asyncio.create_task(coordinator.run())
        for _ in range(200):
            if "start" in log:
                break
            await asyncio.sleep(0.01)
        bk.stage_restore(name, source_root=str(root))     # the yield path, then aclose raises
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(task, 10)

    asyncio.run(_scenario())
    assert (root / "runtime.pid").read_text().strip() == str(os.getpid())


def test_a_stop_before_anything_was_built_still_clears_the_mark(root, monkeypatch, tmp_path):
    log: list = []
    stops: list = []
    _patch(monkeypatch, tmp_path, log, stops=stops)
    bk.stage_restore(Path(bk.create_backup(source_root=str(root))["archive"]).name,
                     source_root=str(root))

    async def _scenario():
        task = asyncio.create_task(coordinator.run())
        await asyncio.sleep(0.2)                          # waiting on the stage, nothing open
        stops[0].set()
        await asyncio.wait_for(task, 10)

    asyncio.run(_scenario())
    assert log == [] and not (root / "runtime.pid").exists()


# ── 3. the hub's apply and its re-exec ───────────────────────────────────────────

@pytest.mark.skipif(not _LINUX_PROC, reason="reads open files from /proc")
def test_the_apply_defers_while_the_applying_process_holds_a_db_under_the_root(root):
    name = Path(bk.create_backup(source_root=str(root))["archive"]).name
    _seed(root / "h010probe.db", 2)                       # 3 rows live, 1 in the archive
    bk.stage_restore(name, source_root=str(root))
    conn = sqlite3.connect(str(root / "h010probe.db"))
    try:
        conn.execute("SELECT 1 FROM t").fetchone()
        result = bk.apply_pending_restore(root)
    finally:
        conn.close()
    assert result["status"] == "deferred", result
    assert "this process still holds" in result["reason"] and "h010probe.db" in result["reason"]
    assert bk.last_restore(root)["status"] == "deferred"  # recorded, not silent
    assert _rows(root / "h010probe.db") == 3 and bk.pending_restore(root)["name"] == name
    # Once nothing is held, the same stage applies.
    assert bk.apply_pending_restore(root)["status"] == "restored"
    assert _rows(root / "h010probe.db") == 1


@pytest.mark.skipif(os.name == "nt", reason="the same-pid re-exec is POSIX only")
def test_the_self_restart_reexec_carries_no_descriptor_into_the_new_image(root, monkeypatch):
    import serve

    fd = os.open(root / "h010probe.db", os.O_RDONLY)
    os.set_inheritable(fd, True)
    seen = []
    monkeypatch.setattr(serve.os, "execv",
                        lambda exe, argv: seen.append(os.get_inheritable(fd)))
    monkeypatch.setattr(install_identity, "release_hub_lock", lambda: None)

    class _Server:
        should_exit = False

        def run(self):
            assert hub_restart.request("backup.restore") is True

    try:
        serve.run_server(_Server())
    finally:
        os.close(fd)
    assert seen == [False]


# ── 4. a real serve.py hub restarts itself and holds only the restored files ─────

_HUB = """
import os, sys, threading, time, pathlib, runpy
sys.path.insert(0, {repo!r})
trigger = pathlib.Path({trigger!r})
probe = {probe!r}

def _watch():
    while not trigger.exists():
        time.sleep(0.1)
    trigger.unlink()
    # A DB handle opened without close-on-exec: the kind a re-exec would carry over.
    fd = os.open(probe, os.O_RDWR)
    os.set_inheritable(fd, True)
    from agents.core import hub_restart
    hub_restart.request("backup.restore")

threading.Thread(target=_watch, daemon=True).start()
sys.argv = [{serve!r}]
runpy.run_path({serve!r}, run_name="__main__")
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as resp:  # nosec B310 - loopback
            return resp.status == 200
    except OSError:
        return False


def _root_fds(pid: int, root: Path) -> dict[str, str]:
    prefix = os.path.realpath(root) + os.sep
    out = {}
    for fd in os.listdir(f"/proc/{pid}/fd"):
        try:
            target = os.readlink(f"/proc/{pid}/fd/{fd}")
        except OSError:
            continue
        if target.startswith(prefix):
            out[fd] = target
    return out


@pytest.mark.skipif(not _LINUX_PROC, reason="reads open files from /proc")
def test_a_real_serve_hub_restarts_applies_the_restore_and_holds_only_restored_files(
        root, tmp_path):
    trigger = tmp_path / "restart-now"
    probe = root / "h010probe.db"
    wrapper = tmp_path / "hub.py"
    wrapper.write_text(_HUB.format(repo=str(REPO), trigger=str(trigger), probe=str(probe),
                                   serve=str(REPO / "serve.py")), encoding="utf-8")
    port = _free_port()
    env = {**os.environ, "JARVIS_HOME": str(root), "JARVIS_HOST": "127.0.0.1",
           "JARVIS_PORT": str(port), "JARVIS_RESTORE_RUNTIME_WAIT_SECONDS": "0",
           "JARVIS_SHUTDOWN_TIMEOUT": "2"}
    env.pop("NOTIFY_SOCKET", None)
    hub = subprocess.Popen([sys.executable, str(wrapper)], env=env,  # nosec B603
                           cwd=str(tmp_path))
    try:
        _wait_for(lambda: _ready(port), what="the hub serving")
        name = Path(bk.create_backup(source_root=str(root))["archive"]).name
        _seed(probe, 2)                                   # 3 rows live, 1 in the archive
        assert bk.stage_restore(name, source_root=str(root))["ok"]
        trigger.touch()
        _wait_for(lambda: (bk.last_restore(root) or {}).get("status") in
                  ("restored", "deferred", "failed"), what="the restore at the re-exec'd boot")
        result = bk.last_restore(root)
        assert result["status"] == "restored" and result["ok"] is True, result
        assert _rows(probe) == 1
        _wait_for(lambda: _ready(port), what="the restarted hub serving")
        assert hub.poll() is None                          # same process: a re-exec, not an exit
        fds = _root_fds(hub.pid, root)
        assert fds, "the restarted hub opened no store under the root"
        assert not [t for t in fds.values() if t.endswith("(deleted)")], fds
        for fd, target in fds.items():
            assert os.stat(f"/proc/{hub.pid}/fd/{fd}").st_ino == os.stat(target).st_ino, target
    finally:
        hub.send_signal(signal.SIGTERM)
        try:
            hub.wait(timeout=60)
        except subprocess.TimeoutExpired:
            hub.kill()
            hub.wait(timeout=30)
