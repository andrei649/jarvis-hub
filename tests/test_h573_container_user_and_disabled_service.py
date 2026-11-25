"""H573 — deployment: the hub never runs as root in a container, a switched-off service
reads as down rather than crash-looping, and Docker Desktop for Windows has its own
compose file.

What the owner can do: run the image with PUID/PGID (or NERVA_UID/NERVA_GID) and get
files on a bind mount owned by their own user; switch the headless coordinator off with
JARVIS_RUNTIME_COORDINATOR=0 and see it recorded as down; start Nerva on Docker Desktop
for Windows without host networking.

What an attacker or a mistake cannot do: remap the hub to uid 0; make a switched-off
coordinator respawn forever; expose the Windows variant on the LAN or start it without
credentials. The entrypoint's behaviour is exercised against recording stubs (no user
database, chown or setpriv on this machine is touched); a real Docker run is not proven
here.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO / "deploy" / "docker" / "entrypoint.sh"
USERADD = "useradd --uid 1000 --user-group --no-create-home --home-dir /data --shell /usr/sbin/nologin nerva"
ENTRY = 'ENTRYPOINT ["sh", "/app/deploy/docker/entrypoint.sh"]'


def _instructions(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


# ── the image definitions ────────────────────────────────────────────────────

def test_the_published_image_creates_the_user_and_starts_through_the_entrypoint():
    lines = _instructions((REPO / "Dockerfile").read_text(encoding="utf-8"))
    assert f"RUN {USERADD}" in lines and ENTRY in lines
    assert lines.index(ENTRY) < lines.index('CMD ["python", "serve.py"]')
    # USER would make the remap impossible (the entrypoint must start as root to drop it).
    assert not any(line.upper().startswith("USER ") for line in lines)


@pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.quickstart.yml", "docker-compose.windows.yml"])
def test_every_compose_image_built_here_runs_through_the_entrypoint(name):
    services = yaml.safe_load((REPO / name).read_text(encoding="utf-8"))["services"]
    ours = [svc for svc in services.values()
            if isinstance(svc.get("build"), dict) and svc["build"].get("context") == "."]
    assert ours
    for svc in ours:
        inline = svc["build"]["dockerfile_inline"]
        assert f"RUN {USERADD}" in inline and ENTRY in inline
        assert "USER " not in inline


def test_the_windows_variant_publishes_on_loopback_and_its_bind_needs_a_token(monkeypatch):
    svc = yaml.safe_load((REPO / "docker-compose.windows.yml").read_text(encoding="utf-8"))["services"]["nerva"]
    assert "network_mode" not in svc
    assert svc["ports"] == ["127.0.0.1:8080:8080"]
    env = svc["environment"]
    assert env == {"JARVIS_HOST": "0.0.0.0", "JARVIS_PORT": "8080", "JARVIS_HOME": "/data"}
    assert svc["volumes"] == ["nerva_data:/data"]
    # The non-loopback bind inside the container is exactly what the boot guard refuses
    # without a credential, so the variant cannot come up open.
    from agents.core import boot_guards

    for name in ("JARVIS_USER_TOKEN", "JARVIS_ADMIN_TOKEN", "NERVA_USER_TOKEN", "NERVA_ADMIN_TOKEN",
                 "JARVIS_ALLOW_INSECURE_BIND", "NERVA_ALLOW_INSECURE_BIND"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as refused:
        boot_guards.assert_safe_bind(env["JARVIS_HOST"])
    assert "without authentication" in str(refused.value)
    monkeypatch.setenv("JARVIS_USER_TOKEN", "a-real-token")
    boot_guards.assert_safe_bind(env["JARVIS_HOST"])
    assert "--require-hashes -r requirements-beta.lock" in svc["build"]["dockerfile_inline"]


# ── the entrypoint, against recording stubs ──────────────────────────────────

STUBS = {
    "id": '''case "$*" in
  "-u") echo "$STUB_ID_U" ;;
  "-g") echo "${STUB_ID_G:-0}" ;;
  "-u nerva") echo "${STUB_NERVA_UID:-1000}" ;;
  "-g nerva") echo "${STUB_NERVA_GID:-1000}" ;;
  *) echo 0 ;;
esac''',
    "stat": 'echo "$STUB_STAT"',
    "groupmod": 'echo "groupmod $*" >> "$STUB_LOG"',
    "usermod": 'echo "usermod $*" >> "$STUB_LOG"',
    "chown": 'echo "chown $*" >> "$STUB_LOG"',
    "mkdir": 'echo "mkdir $*" >> "$STUB_LOG"',
    # Logs its options, then runs the rest as the dropped user would: `id` answers the
    # post-drop ids (STUB_AFTER_U/G), so the entrypoint's still-root check is exercised.
    "setpriv": '''opts=""
while [ "$1" != "--" ]; do opts="$opts $1"; shift; done
shift
echo "setpriv$opts" >> "$STUB_LOG"
STUB_ID_U="${STUB_AFTER_U:-1000}" STUB_ID_G="${STUB_AFTER_G:-1000}" exec "$@"''',
    "true-cmd": 'echo "direct $*" >> "$STUB_LOG"',
}


def _run(tmp_path, *, uid="0", stat="0:0", **env):
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    for name, body in STUBS.items():
        path = stubs / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    environ = {"PATH": f"{stubs}:/usr/bin:/bin", "STUB_LOG": str(log), "STUB_ID_U": uid,
               "STUB_STAT": stat, "JARVIS_HOME": str(tmp_path / "data"), **env}
    result = subprocess.run(["sh", str(ENTRYPOINT), "true-cmd", "serve"], env=environ,
                            capture_output=True, text=True, timeout=30)
    return result, log.read_text().splitlines()


def test_root_start_remaps_to_puid_pgid_hands_over_the_data_root_and_drops_privileges(tmp_path):
    result, calls = _run(tmp_path, PUID="1234", PGID="2345")
    assert result.returncode == 0, result.stderr
    data = str(tmp_path / "data")
    assert calls == [
        "groupmod -o -g 2345 nerva",
        "usermod -o -u 1234 -g 2345 nerva",
        f"mkdir -p {data}",
        f"chown -hR 1234:2345 {data}",
        "mkdir -p /app/logs",
        "chown -hR 1234:2345 /app/logs",
        "setpriv --reuid=1234 --regid=2345 --init-groups --inh-caps=-all --bounding-set=-all --no-new-privs",
        "direct serve",
    ]


def test_nerva_uid_beats_puid_and_an_already_owned_root_is_not_walked(tmp_path):
    result, calls = _run(tmp_path, stat="1500:1500", NERVA_UID="1500", NERVA_GID="1500",
                         PUID="1234", PGID="2345")
    assert result.returncode == 0
    assert not any(call.startswith("chown") for call in calls)
    assert calls[-2].startswith("setpriv --reuid=1500 --regid=1500 ") and calls[-1] == "direct serve"


def test_default_ids_need_no_remap(tmp_path):
    result, calls = _run(tmp_path, stat="1000:1000")
    assert result.returncode == 0
    assert calls == [f"mkdir -p {tmp_path / 'data'}", "mkdir -p /app/logs",
                     "setpriv --reuid=1000 --regid=1000 --init-groups --inh-caps=-all --bounding-set=-all --no-new-privs", "direct serve"]


@pytest.mark.parametrize("env", [{"PUID": "0"}, {"PGID": "0"}, {"NERVA_UID": "0", "PUID": "1000"},
                                 {"PUID": "1000; rm -rf /"}, {"PGID": "abc"}, {"PUID": "-5"}])
def test_root_ids_and_non_numbers_are_refused_before_anything_changes(tmp_path, env):
    result, calls = _run(tmp_path, **env)
    assert result.returncode == 64 and calls == []


@pytest.mark.parametrize("env", [
    {"PUID": "4294967295", "PGID": "4294967295"},   # (uid_t)-1: setpriv would leave root
    {"NERVA_UID": "4294967295"},
    {"PUID": "18446744073709551616"},              # past intmax: dash would mis-compare
    {"PGID": "99999999999999999999"},
    {"PUID": "2147483648"},
    {"PUID": "007"},
])
def test_out_of_range_ids_are_refused_before_anything_changes(tmp_path, env):
    # Review repro r4.
    result, calls = _run(tmp_path, **env)
    assert result.returncode == 64 and calls == [], (result.returncode, calls, result.stderr)


def test_the_largest_allowed_id_is_accepted(tmp_path):
    result, calls = _run(tmp_path, PUID="2147483647", PGID="2147483647", stat="2147483647:2147483647",
                         STUB_AFTER_U="2147483647", STUB_AFTER_G="2147483647")
    assert result.returncode == 0 and calls[-1] == "direct serve"


@pytest.mark.parametrize("env", [{"STUB_AFTER_U": "0"}, {"STUB_AFTER_G": "0"}])
def test_a_process_still_root_after_the_drop_refuses_to_start(tmp_path, env):
    result, calls = _run(tmp_path, stat="1000:1000", **env)
    assert result.returncode == 70 and "direct serve" not in calls and "still root" in result.stderr


@pytest.mark.parametrize("root", ["/", "//", "/app", "/app/", "data", "/data/../app", "/srv/./x"])
def test_a_data_root_that_would_hand_over_the_image_is_refused(tmp_path, root):
    result, calls = _run(tmp_path, JARVIS_HOME=root)
    assert result.returncode == 64 and calls == []


def test_nerva_home_is_the_data_root_it_names(tmp_path):
    result, calls = _run(tmp_path, stat="1000:1000", NERVA_HOME=str(tmp_path / "nerva-data"))
    assert result.returncode == 0 and calls[0] == f"mkdir -p {tmp_path / 'nerva-data'}"


def test_the_run_log_summary_reads_a_disabled_coordinator_as_down(tmp_path):
    from agents.core.observability.runtime_log import read_runtime_health as summarize

    log = tmp_path / "runtime.jsonl"
    now = time.time()
    log.write_text("\n".join(json.dumps({"supervisor_event": event, "at": now})
                             for event in ("spawned", "disabled", "stopped")) + "\n")
    summary = summarize(log, now=now)
    assert summary["disabled"] is True and summary["stale"] is True
    log.write_text(log.read_text() + json.dumps({"supervisor_event": "spawned", "at": now}) + "\n")
    assert "disabled" not in summarize(log, now=now)


def test_a_non_root_start_execs_the_command_unchanged(tmp_path):
    result, calls = _run(tmp_path, uid="1000", PUID="1234")
    assert result.returncode == 0 and calls == ["direct serve"]


# ── a switched-off coordinator reads as down ────────────────────────────────

def test_the_disabled_exit_status_is_one_number_in_both_scripts():
    import importlib.util

    def load(name):
        spec = importlib.util.spec_from_file_location(f"_h573_{name}", REPO / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    assert load("runtime_supervisor").SERVICE_DISABLED_EXIT == load("coordinator").SERVICE_DISABLED_EXIT == 125


def _supervisor(tmp_path, *args):
    child = tmp_path / "disabled_child.py"
    child.write_text("raise SystemExit(125)\n", encoding="utf-8")
    source = (REPO / "scripts" / "runtime_supervisor.py").read_text(encoding="utf-8")
    patched = source.replace('_COORDINATOR = str(_REPO_ROOT / "scripts" / "coordinator.py")',
                             f"_COORDINATOR = {str(child)!r}")
    assert patched != source
    script = tmp_path / "runtime_supervisor.py"
    script.write_text(patched, encoding="utf-8")
    log = tmp_path / "runtime.jsonl"
    env = {**os.environ, "JARVIS_RUNTIME_LOG": str(log), "JARVIS_RUNTIME_RESPAWN_DELAY": "0.05"}
    return subprocess.Popen([sys.executable, str(script), *args], env=env,
                            stderr=subprocess.PIPE, text=True), log


def _events(log):
    return [json.loads(line)["supervisor_event"] for line in log.read_text().splitlines()] if log.exists() else []


def test_with_exit_when_disabled_the_supervisor_stops_with_125_and_never_respawns(tmp_path):
    proc, log = _supervisor(tmp_path, "--exit-when-disabled")
    assert proc.wait(timeout=20) == 125
    assert _events(log) == ["spawned", "disabled"]
    assert "switched off" in proc.stderr.read()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal delivery")
def test_by_default_the_supervisor_holds_a_disabled_service_down_until_stopped(tmp_path):
    proc, log = _supervisor(tmp_path)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and "disabled" not in _events(log):
            time.sleep(0.05)
        time.sleep(0.5)
        assert proc.poll() is None                     # held, not exited for a restart policy
        assert _events(log) == ["spawned", "disabled"]  # and never respawned
    finally:
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    assert _events(log) == ["spawned", "disabled", "stopped"]


def test_the_coordinator_exits_125_when_switched_off(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith(("JARVIS_", "NERVA_"))}
    env.update({"JARVIS_RUNTIME_COORDINATOR": "0", "JARVIS_HOME": str(tmp_path),
                "JARVIS_RUNTIME_LOG": str(tmp_path / "runtime.jsonl"), "PYTHONPATH": str(REPO)})
    result = subprocess.run([sys.executable, str(REPO / "scripts" / "coordinator.py")], env=env, cwd=tmp_path,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 125, result.stderr[-2000:]
    assert "switched off" in result.stderr


def test_the_systemd_unit_treats_125_as_a_clean_stop_it_never_restarts():
    unit = (REPO / "deploy" / "systemd" / "jarvis-runtime.service").read_text(encoding="utf-8")
    assert re.search(r"^ExecStart=.*scripts/runtime_supervisor\.py --exit-when-disabled$", unit, re.M)
    assert re.search(r"^RestartPreventExitStatus=.*\b125\b", unit, re.M)
    assert re.search(r"^SuccessExitStatus=125$", unit, re.M)
