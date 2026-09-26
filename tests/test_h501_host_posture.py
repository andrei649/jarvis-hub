"""H501 — warn about a dangerous host posture before it becomes an incident.

Three read-only checks that never block: the hub runs as root (or elevated), sshd
accepts passwords (read with sshd's own precedence), and a container's data root is not
on a persistent mount. Each is logged once at start and reported by the doctor and the
security posture route; a check that cannot tell says so and is never shown as ok.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import host_posture as hp

ROOT = Path(__file__).resolve().parents[1]


# ── root ─────────────────────────────────────────────────────────────────────


def test_root_on_posix():
    warn = hp.check_root(platform="linux", geteuid=lambda: 0)
    assert warn["status"] == "warn" and warn["reason"] == "running_as_root" and warn["detail"] == "euid 0"
    assert warn["fix"] == hp.FIX["root"]
    ok = hp.check_root(platform="darwin", geteuid=lambda: 501)
    assert ok["status"] == "ok" and ok["reason"] == "unprivileged" and "fix" not in ok
    assert hp.check_root(platform="linux", geteuid=lambda: 1)["status"] == "ok", "only euid 0 is root"


def test_elevated_on_windows():
    assert hp.check_root(platform="win32", is_admin=lambda: 1)["status"] == "warn"
    ok = hp.check_root(platform="win32", is_admin=lambda: 0)
    assert ok["status"] == "ok"


def test_root_that_cannot_be_read_is_unknown_not_ok(monkeypatch):
    def boom():
        raise OSError("x")

    assert hp.check_root(platform="linux", geteuid=boom)["status"] == "unknown"
    assert hp.check_root(platform="win32", is_admin=boom)["status"] == "unknown"
    monkeypatch.delattr(os, "geteuid", raising=False)
    assert hp.check_root(platform="linux") == {"check": "root", "status": "unknown", "reason": "no_euid",
                                               "detail": ""}


# ── sshd ─────────────────────────────────────────────────────────────────────


def _sshd(tmp_path, main, drop=None):
    base = tmp_path / "ssh"
    (base / "sshd_config.d").mkdir(parents=True)
    (base / "sshd_config").write_text(main, encoding="utf-8")
    for name, text in (drop or {}).items():
        (base / "sshd_config.d" / name).write_text(text, encoding="utf-8")
    return hp.check_sshd(config=str(base / "sshd_config"), base=str(base))


def test_no_sshd_is_fine(tmp_path):
    got = hp.check_sshd(config=str(tmp_path / "missing"), base=str(tmp_path))
    assert got["status"] == "ok" and got["reason"] == "no_sshd_config"


def test_absent_means_the_sshd_default_yes(tmp_path):
    got = _sshd(tmp_path, "Port 22\n# PasswordAuthentication no\n")
    assert got["status"] == "warn" and got["reason"] == "password_auth_enabled"
    assert got["detail"] == "not set: the sshd default" and got["fix"] == hp.FIX["sshd_passwords"]


def test_explicit_values_and_where_they_came_from(tmp_path):
    got = _sshd(tmp_path, "Port 22\nPasswordAuthentication yes\n")
    assert got["status"] == "warn" and got["detail"].endswith("sshd_config:2")
    got = _sshd(tmp_path / "b", "PasswordAuthentication no\n")
    assert got["status"] == "ok" and got["reason"] == "password_auth_disabled"


@pytest.mark.parametrize("line", ["PasswordAuthentication=no", "passwordauthentication NO",
                                  "  PasswordAuthentication = no  ", "PasswordAuthentication no # keys only"])
def test_the_spellings_sshd_accepts(tmp_path, line):
    assert _sshd(tmp_path, line + "\n")["status"] == "ok"


def test_a_trailing_comment_is_not_an_argument(tmp_path):
    got = _sshd(tmp_path, "Include sshd_config.d/10-a.conf # sshd_config.d/05-b.conf\n",
                {"10-a.conf": "Port 22\n", "05-b.conf": "PasswordAuthentication no\n"})
    assert got["status"] == "warn" and got["reason"] == "password_auth_enabled", "05-b.conf is only named in a comment"


def test_the_first_value_wins(tmp_path):
    assert _sshd(tmp_path, "PasswordAuthentication no\nPasswordAuthentication yes\n")["status"] == "ok"
    assert _sshd(tmp_path / "b", "PasswordAuthentication yes\nPasswordAuthentication no\n")["status"] == "warn"


def test_an_include_at_the_top_overrides_the_main_file(tmp_path):
    """Debian and Ubuntu: `Include /etc/ssh/sshd_config.d/*.conf` first, so a drop-in's
    value is read before the main file's and wins."""
    got = _sshd(tmp_path, "Include sshd_config.d/*.conf\nPasswordAuthentication yes\n",
                {"50-cloud-init.conf": "PasswordAuthentication no\n"})
    assert got["status"] == "ok" and "50-cloud-init.conf:1" in got["detail"]
    got = _sshd(tmp_path / "b", "Include sshd_config.d/*.conf\nPasswordAuthentication no\n",
                {"50-cloud-init.conf": "PasswordAuthentication yes\n"})
    assert got["status"] == "warn" and "50-cloud-init.conf:1" in got["detail"]


def test_include_files_are_read_in_lexical_order_and_absolute_paths_work(tmp_path):
    base = tmp_path / "ssh"
    got = _sshd(tmp_path, f'Include "{base}/sshd_config.d/*.conf"\n',
                {"20-b.conf": "PasswordAuthentication no\n", "10-a.conf": "PasswordAuthentication yes\n"})
    assert got["status"] == "warn" and "10-a.conf" in got["detail"]


def test_an_include_that_matches_nothing_is_ignored(tmp_path):
    got = _sshd(tmp_path, "Include sshd_config.d/*.conf\nPasswordAuthentication no\n")
    assert got["status"] == "ok"


def test_a_match_block_is_not_the_global_setting(tmp_path):
    got = _sshd(tmp_path, "Match User backup\n    PasswordAuthentication no\n")
    assert got["status"] == "warn" and got["reason"] == "password_auth_enabled", "global stays the default yes"
    got = _sshd(tmp_path / "b", "PasswordAuthentication no\nMatch Address 10.0.0.0/8\n  PasswordAuthentication yes\n")
    assert got["status"] == "warn" and got["reason"] == "password_auth_in_match" and got["detail"].endswith(":3")
    got = _sshd(tmp_path / "c", "PasswordAuthentication no\nMatch User x\n  PasswordAuthentication no\n")
    assert got["status"] == "ok"


def test_a_match_in_an_included_file_ends_with_that_file(tmp_path):
    got = _sshd(tmp_path, "Include sshd_config.d/*.conf\nPasswordAuthentication no\n",
                {"10-x.conf": "Match User guest\n  PasswordAuthentication yes\n"})
    assert got["reason"] == "password_auth_in_match", "the main file's value after the include is global"
    got = _sshd(tmp_path / "b", "Match User x\nInclude sshd_config.d/*.conf\n",
                {"10-x.conf": "PasswordAuthentication no\n"})
    assert got["reason"] == "password_auth_enabled", "an include inside a Match block is conditional"


def test_an_unknown_value_is_not_read_as_either(tmp_path):
    got = _sshd(tmp_path, "PasswordAuthentication maybe\n")
    assert got["status"] == "unknown" and got["reason"] == "unrecognised_value"


def test_an_unreadable_config_is_unknown_not_ok(tmp_path):
    def denied(path):
        raise PermissionError(path)

    got = hp.check_sshd(config="/etc/ssh/sshd_config", base="/etc/ssh", read=denied)
    assert got["status"] == "unknown" and got["reason"] == "unreadable"


def test_an_unreadable_drop_in_is_unknown_unless_the_answer_is_elsewhere(tmp_path):
    files = {"/s/sshd_config": ["Include d/*.conf", "Port 22"], "/s/d/a.conf": None}

    def read(path):
        if files.get(path) is None:
            raise PermissionError(path)
        return files[path]

    got = hp.check_sshd(config="/s/sshd_config", base="/s", read=read, glob_fn=lambda p: ["/s/d/a.conf"])
    assert got["status"] == "unknown" and "a.conf" in got["detail"]
    files["/s/sshd_config"] = ["Include d/*.conf", "PasswordAuthentication no"]
    got = hp.check_sshd(config="/s/sshd_config", base="/s", read=read, glob_fn=lambda p: ["/s/d/a.conf"])
    assert got["status"] == "ok"


def test_include_loops_stop(tmp_path):
    base = tmp_path / "ssh"
    base.mkdir()
    (base / "sshd_config").write_text(f"Include {base}/sshd_config\n", encoding="utf-8")
    got = hp.check_sshd(config=str(base / "sshd_config"), base=str(base))
    assert got["status"] == "unknown" and "too deep" in got["detail"]


# ── container storage ────────────────────────────────────────────────────────

MOUNTINFO = """\
21 1 0:19 / / rw,relatime - overlay overlay rw,lowerdir=/l,upperdir=/u
not a mount line
1 2 3 - ext4 /dev/sdb rw
22 21 0:20 / /proc rw,nosuid - proc proc rw
30 21 8:1 /var/lib/docker/volumes/nerva/_data /data rw,relatime shared:5 - ext4 /dev/sda1 rw
31 21 0:30 / /scratch rw - tmpfs tmpfs rw
32 21 8:1 /home/me/my\\040data /my\\040data rw - ext4 /dev/sda1 rw
"""


def test_mountinfo_parsing():
    mounts = hp.parse_mountinfo(MOUNTINFO + "garbage line\n1 2 3\n")
    assert ("/", "overlay") in mounts and ("/data", "ext4") in mounts and ("/my data", "ext4") in mounts
    assert len(mounts) == 5


def test_the_mount_a_path_lives_on():
    mounts = hp.parse_mountinfo(MOUNTINFO)
    assert hp.mount_of("/data/memory", mounts) == ("/data", "ext4")
    assert hp.mount_of("/data", mounts) == ("/data", "ext4")
    assert hp.mount_of("/database", mounts) == ("/", "overlay"), "a name prefix is not a path prefix"
    assert hp.mount_of("/scratch/x", mounts) == ("/scratch", "tmpfs")
    stacked = mounts + [("/data", "tmpfs")]
    assert hp.mount_of("/data/x", stacked) == ("/data", "tmpfs"), "a later mount stacks over an earlier one"
    assert hp.mount_of("/x", []) is None


def _storage(tmp_path, data_root, text=MOUNTINFO, marker="/.dockerenv"):
    info = tmp_path / "mountinfo"
    info.write_text(text, encoding="utf-8")
    return hp.check_container_storage(data_root, marker=marker, mountinfo=str(info))


def test_outside_a_container_there_is_nothing_to_check(tmp_path):
    got = hp.check_container_storage("/anything", marker=None, mountinfo=str(tmp_path / "none"))
    assert got["status"] == "ok" and got["reason"] == "not_in_container"


def test_a_data_root_on_the_containers_own_filesystem_is_ephemeral(tmp_path):
    got = _storage(tmp_path, "/app/memory_logs")
    assert got["status"] == "warn" and got["reason"] == "data_root_on_container_root"
    assert "/.dockerenv" in got["detail"] and got["fix"] == hp.FIX["container_storage"]


def test_a_data_root_on_tmpfs_is_ephemeral(tmp_path):
    got = _storage(tmp_path, "/scratch/nerva")
    assert got["status"] == "warn" and got["reason"] == "data_root_on_tmpfs"


def test_a_data_root_on_a_volume_is_fine(tmp_path):
    got = _storage(tmp_path, "/data")
    assert got["status"] == "ok" and got["reason"] == "data_root_on_mount" and "/data (ext4)" in got["detail"]


def test_a_symlinked_data_root_is_judged_where_it_points(tmp_path):
    real = tmp_path / "vol"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    info = f"1 0 0:1 / / rw - overlay overlay rw\n2 1 8:1 / {real} rw - ext4 /dev/sda1 rw\n"
    got = _storage(tmp_path, link, text=info)
    assert got["status"] == "ok" and str(real) in got["detail"]


def test_no_mountinfo_or_no_mount_is_unknown(tmp_path):
    got = hp.check_container_storage("/data", marker="/.dockerenv", mountinfo=str(tmp_path / "missing"))
    assert got["status"] == "unknown" and got["reason"] == "no_mountinfo"
    empty = _storage(tmp_path, "/data", text="")
    assert empty["status"] == "unknown" and empty["reason"] == "no_mount_found"


def test_container_markers(tmp_path):
    marker = tmp_path / ".dockerenv"
    cgroup = tmp_path / "cgroup"
    cgroup.write_text("0::/\n", encoding="utf-8")
    assert hp.in_container(files=(str(marker),), cgroup=str(cgroup)) is None
    marker.write_text("", encoding="utf-8")
    assert hp.in_container(files=(str(marker),), cgroup=str(cgroup)) == str(marker)
    for text in ("12:pids:/docker/abc\n", "0::/kubepods/besteffort/pod1\n", "1:name=systemd:/machine.slice/libpod-1\n"):
        cgroup.write_text(text, encoding="utf-8")
        assert hp.in_container(files=(), cgroup=str(cgroup)).startswith(str(cgroup))
    assert hp.in_container(files=(), cgroup=str(tmp_path / "gone")) is None


def test_the_container_check_detects_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(hp, "in_container", lambda: "/run/.containerenv")
    got = _storage(tmp_path, "/app/x", marker=True)
    assert got["status"] == "warn" and "/run/.containerenv" in got["detail"]


# ── together ─────────────────────────────────────────────────────────────────


def test_run_checks_is_the_three_checks_in_order(monkeypatch, tmp_path):
    monkeypatch.setattr(hp, "check_root", lambda: hp._finding("root", "warn", "running_as_root", "euid 0"))
    monkeypatch.setattr(hp, "check_sshd", lambda: hp._finding("sshd_passwords", "ok", "no_sshd_config"))
    seen = []
    monkeypatch.setattr(hp, "check_container_storage", lambda root: seen.append(root) or
                        hp._finding("container_storage", "ok", "not_in_container"))
    checks = hp.run_checks(tmp_path)
    assert [c["check"] for c in checks] == ["root", "sshd_passwords", "container_storage"]
    assert seen == [tmp_path]
    rep = hp.report(tmp_path)
    assert rep["warnings"] == 1 and len(rep["checks"]) == 3


def test_the_data_root_defaults_to_the_hubs(monkeypatch):
    import agents.core.paths as paths

    seen = []
    monkeypatch.setattr(paths, "data_root", lambda: Path("/hub/data"))
    monkeypatch.setattr(hp, "check_container_storage", lambda root: seen.append(root) or
                        hp._finding("container_storage", "ok", "not_in_container"))
    hp.run_checks()
    assert seen == [Path("/hub/data")]


def test_a_failing_check_never_breaks_the_others(monkeypatch):
    def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(hp, "check_root", boom)
    checks = hp.run_checks("/tmp")
    assert checks[0] == {"check": "unknown", "status": "unknown", "reason": "check_failed", "detail": "RuntimeError"}
    assert [c["check"] for c in checks[1:]] == ["sshd_passwords", "container_storage"]


def test_warnings_are_logged_once_per_process(monkeypatch, caplog):
    monkeypatch.setattr(hp, "_logged", __import__("threading").Event())
    monkeypatch.setattr(hp, "run_checks", lambda root=None: [
        hp._finding("root", "warn", "running_as_root", "euid 0"),
        hp._finding("sshd_passwords", "ok", "password_auth_disabled", "x:1")])
    caplog.set_level(logging.WARNING, logger="jarvis.host_posture")
    assert len(hp.log_startup()) == 2
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 1 and "running_as_root" in lines[0] and hp.FIX["root"] in lines[0]
    assert hp.log_startup() == [], "once per process"
    assert len(hp.log_startup(force=True)) == 2


def test_the_hub_logs_them_at_start_after_logging_is_set_up():
    from agents import web

    life = inspect.getsource(web.lifespan)
    assert life.index("setup_logging()") < life.index("host_posture.log_startup")
    assert "await asyncio.to_thread(host_posture.log_startup)" in life


def test_nothing_here_blocks_or_changes_the_host():
    src = (ROOT / "agents" / "core" / "host_posture.py").read_text(encoding="utf-8")
    for forbidden in ("SystemExit", "raise RuntimeError", "subprocess", "os.chmod", "os.remove", "unlink(",
                      "write_text", "open(path, \"w"):
        assert forbidden not in src, forbidden


# ── the posture route ────────────────────────────────────────────────────────


def test_the_security_posture_reports_the_host(monkeypatch):
    from agents.core.routers import security

    monkeypatch.setattr(hp, "report", lambda data_root=None: {"checks": [{"check": "root"}], "warnings": 1})
    orch = SimpleNamespace(skills=None, sandbox=None, get_setting=lambda k, d=None: d, _runtime_settings={})
    monkeypatch.setattr(security, "get_orch", lambda: orch)
    response = asyncio.run(security.security_posture())
    import json

    body = json.loads(response.body)
    assert body["host"] == {"checks": [{"check": "root"}], "warnings": 1}


# ── the doctor ───────────────────────────────────────────────────────────────


def test_the_doctor_reports_each_check_and_never_fails_on_one(tmp_path, monkeypatch):
    from scripts import doctor

    monkeypatch.setattr(doctor, "resolve_data_root", lambda root, env=None: tmp_path / "home")

    findings = [hp._finding("root", "warn", "running_as_root", "euid 0"),
                hp._finding("sshd_passwords", "unknown", "unreadable", "/etc/ssh/sshd_config: PermissionError"),
                hp._finding("container_storage", "ok", "not_in_container"),
                {"check": "other", "status": "warn", "reason": "x"}]
    seen = []
    rows = doctor.check_host_posture(tmp_path, {}, run=lambda root: seen.append(root) or findings)
    assert seen == [tmp_path / "home"]
    assert [(r.name, r.status, r.reason) for r in rows] == [
        ("host_not_root", doctor.WARN, "running_as_root"),
        ("sshd_no_passwords", doctor.SKIP, "unreadable"),
        ("container_storage", doctor.OK, "not_in_container"),
    ]
    assert rows[0].detail == f"euid 0; fix: {hp.FIX['root']}"
    for name in doctor.HOST_CHECK_NAMES.values():
        assert name in doctor.ADVISORY and name not in doctor.REQUIRED


def test_the_doctor_skips_the_host_checks_when_they_cannot_run(tmp_path):
    from scripts import doctor

    def boom(root):
        raise ImportError("no agents package")

    rows = doctor.check_host_posture(tmp_path, {}, run=boom)
    assert [(r.name, r.status, r.reason) for r in rows] == [
        (name, doctor.SKIP, "host_posture_unavailable") for name in doctor.HOST_CHECK_NAMES.values()]


def test_a_warning_with_no_detail_still_names_the_fix(tmp_path):
    from scripts import doctor

    rows = doctor.check_host_posture(tmp_path, {}, run=lambda root: [hp._finding("root", "warn", "running_as_root")])
    assert rows[0].detail == f"fix: {hp.FIX['root']}"


def test_run_doctor_ends_with_the_host_rows(monkeypatch, tmp_path):
    from scripts import doctor

    report = doctor.run_doctor(ROOT, env={"JARVIS_HOME": str(tmp_path)},
                               opener=lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    names = [c.name for c in report.checks]
    assert names[-3:] == ["host_not_root", "sshd_no_passwords", "container_storage"]
    assert names == list(doctor.REQUIRED) + list(doctor.ADVISORY)
