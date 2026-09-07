"""scripts/bootstrap.py — the one-step native install (stdlib-only, fakes only).

Hermetic: every subprocess is a recording fake, every HTTP probe a fake opener. The
only real interpreter call is ``python -c`` for the "parseable by an old interpreter"
guard.
"""

import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from scripts import bootstrap  # noqa: E402


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    """Records argv lists; creates the venv interpreter file when asked to."""

    def __init__(self, *, venv_rc=0, pip_rc=0, smoke_rc=0, smoke_stdout=None, smoke_stderr=""):
        self.calls = []
        self.venv_rc = venv_rc
        self.pip_rc = pip_rc
        self.smoke_rc = smoke_rc
        self.smoke_stdout = smoke_stdout
        self.smoke_stderr = smoke_stderr

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list), "argv must be a list — never a shell string"
        assert "shell" not in kwargs, "no shell=True, ever"
        self.calls.append({"argv": list(argv), **kwargs})
        if argv[1:3] == ["-m", "venv"]:
            if self.venv_rc == 0:
                target = bootstrap.venv_python(Path(argv[3]).parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("#!/bin/sh\n", encoding="utf-8")
            return FakeProc(self.venv_rc)
        if argv[1:4] == ["-m", "pip", "install"]:
            return FakeProc(self.pip_rc)
        if argv[1].endswith("install_smoke.py"):
            out = self.smoke_stdout
            if out is None:
                out = json.dumps({"ok": True, "agents": 17, "ready_status": 200})
            return FakeProc(self.smoke_rc, stdout=out, stderr=self.smoke_stderr)
        raise AssertionError(f"unexpected subprocess: {argv}")


def _refusing_opener(url, timeout=None):
    raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "requirements-beta.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "requirements-beta.lock").write_text("# source-sha256: x\nfastapi==1\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "install_smoke.py").write_text("# fake\n", encoding="utf-8")
    return tmp_path


# ── version floor ──────────────────────────────────────────────────
def test_check_python_refuses_3_11_with_named_reason():
    ok, reason = bootstrap.check_python((3, 11, 9, "final", 0))
    assert ok is False
    assert reason == "python_too_old:3.11<3.12"


def test_check_python_accepts_floor_and_above():
    assert bootstrap.check_python((3, 12, 0, "final", 0)) == (True, "python_ok:3.12")
    assert bootstrap.check_python((3, 14, 1, "final", 0))[0] is True


def test_bootstrap_stops_at_python_step_when_too_old(root):
    runner = FakeRunner()
    report = bootstrap.bootstrap(root, run=runner, opener=_refusing_opener,
                                 version_info=(3, 11, 0, "final", 0))
    assert report["ok"] is False
    assert report["reason"] == "python_too_old:3.11<3.12"
    assert report["steps"] == [{"step": "python", "ok": False, "reason": "python_too_old:3.11<3.12"}]
    assert runner.calls == []  # nothing ran — no venv, no pip


def test_bootstrap_source_is_parseable_by_an_old_grammar():
    """The floor refusal must be a message, not a SyntaxError: the file uses no syntax
    newer than Python 3.8 (checked by compiling it with feature_version=(3, 8))."""
    src = (repo_root / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    import ast
    ast.parse(src, feature_version=(3, 8))


def test_bootstrap_imports_only_stdlib():
    import ast
    src = (repo_root / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


# ── venv ───────────────────────────────────────────────────────────
def test_ensure_venv_is_idempotent(root):
    runner = FakeRunner()
    py, created = bootstrap.ensure_venv(root, python="/usr/bin/python3", run=runner)
    assert created is True
    assert py == bootstrap.venv_python(root)
    assert runner.calls[0]["argv"] == ["/usr/bin/python3", "-m", "venv", str(root / ".venv")]

    py2, created2 = bootstrap.ensure_venv(root, python="/usr/bin/python3", run=runner)
    assert (py2, created2) == (py, False)
    assert len(runner.calls) == 1  # second call did not spawn anything


def test_ensure_venv_names_the_failure(root):
    with pytest.raises(bootstrap.BootstrapError) as ei:
        bootstrap.ensure_venv(root, run=FakeRunner(venv_rc=1))
    assert ei.value.reason == "venv_create_failed"


# ── deps ───────────────────────────────────────────────────────────
def test_pip_install_uses_hash_pinned_lock_by_default(root):
    runner = FakeRunner()
    argv = bootstrap.pip_install_locked(Path("/v/bin/python"), root, run=runner)
    assert "--require-hashes" in argv
    assert argv[-1].endswith("requirements-beta.lock")


def test_pip_install_unlocked_falls_back_to_txt_and_names_failure(root):
    runner = FakeRunner()
    argv = bootstrap.pip_install_locked(Path("/v/bin/python"), root, unlocked=True, run=runner)
    assert "--require-hashes" not in argv
    assert argv[-1].endswith("requirements-beta.txt")

    with pytest.raises(bootstrap.BootstrapError) as ei:
        bootstrap.pip_install_locked(Path("/v/bin/python"), root, run=FakeRunner(pip_rc=2))
    assert ei.value.reason == "pip_install_failed"


# ── runtimes ───────────────────────────────────────────────────────
def test_detect_runtimes_reports_named_reasons_and_probes_only_loopback():
    class Resp:
        status = 200

        def close(self):
            pass

    seen = []

    def opener(url, timeout=None):
        seen.append(url)
        if "11434" in url:
            return Resp()
        raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))

    rows = bootstrap.detect_runtimes(opener=opener)
    by = {r["name"]: r for r in rows}
    assert by["ollama"] == {"name": "ollama", "url": "http://127.0.0.1:11434/api/tags",
                            "reachable": True, "reason": "ok"}
    assert by["lm_studio"]["reachable"] is False
    assert by["lm_studio"]["reason"] == "connection_refused"
    assert all(u.startswith("http://127.0.0.1:") for u in seen)


def test_detect_runtimes_never_raises():
    def opener(url, timeout=None):
        raise TimeoutError("slow")

    rows = bootstrap.detect_runtimes(opener=opener)
    assert {r["reason"] for r in rows} == {"timeout"}

    def http_err(url, timeout=None):
        raise urllib.error.HTTPError(url, 503, "nope", {}, None)

    assert {r["reason"] for r in bootstrap.detect_runtimes(opener=http_err)} == {"http_status:503"}


def test_detect_gpu_is_report_only():
    assert bootstrap.detect_gpu(which=lambda _n: None, machine=lambda: "x86_64",
                                system=lambda: "Linux") == {
        "kind": "none_detected", "reason": "no_accelerator_tool_on_path"}
    assert bootstrap.detect_gpu(which=lambda n: "/usr/bin/nvidia-smi" if n == "nvidia-smi" else None,
                                machine=lambda: "x86_64", system=lambda: "Linux")["kind"] == "nvidia"
    assert bootstrap.detect_gpu(which=lambda _n: None, machine=lambda: "arm64",
                                system=lambda: "Darwin")["kind"] == "apple_silicon"


# ── smoke wiring ───────────────────────────────────────────────────
def test_run_install_smoke_wires_the_venv_and_parses_json(root):
    runner = FakeRunner(smoke_stdout="noise line\n" + json.dumps({"ok": True, "agents": 3}))
    payload = bootstrap.run_install_smoke(Path("/v/bin/python"), root, run=runner,
                                          env={"ANTHROPIC_API_KEY": "sk-secret", "PATH": "/bin"})
    assert payload == {"ok": True, "agents": 3}
    call = runner.calls[0]
    assert call["argv"] == ["/v/bin/python", str(root / "scripts" / "install_smoke.py"), "--json"]
    assert call["cwd"] == str(root)
    # The child environment pins loopback and carries no cloud key.
    assert call["env"]["JARVIS_HOST"] == "127.0.0.1"
    assert "ANTHROPIC_API_KEY" not in call["env"]
    assert call["env"]["PATH"] == "/bin"


def test_run_install_smoke_names_failures(root):
    with pytest.raises(bootstrap.BootstrapError) as ei:
        bootstrap.run_install_smoke(Path("/v/bin/python"), root,
                                    run=FakeRunner(smoke_rc=1, smoke_stderr="Install smoke failed: boom\n"))
    assert ei.value.reason == "smoke_failed"
    assert "boom" in ei.value.detail

    with pytest.raises(bootstrap.BootstrapError) as ei:
        bootstrap.run_install_smoke(Path("/v/bin/python"), root,
                                    run=FakeRunner(smoke_stdout="not json at all"))
    assert ei.value.reason == "smoke_output_unparseable"


def test_subprocess_env_scrubs_every_cloud_key_and_pins_loopback():
    env = bootstrap.subprocess_env({
        "JARVIS_HOST": "0.0.0.0", "OPENAI_API_KEY": "x", "FOO_API_KEY": "y",
        "HOME": "/home/u", "JARVIS_USER_TOKEN": "keep-me",
    })
    assert env["JARVIS_HOST"] == "127.0.0.1"
    assert "OPENAI_API_KEY" not in env and "FOO_API_KEY" not in env
    assert env["HOME"] == "/home/u"
    assert env["JARVIS_USER_TOKEN"] == "keep-me"  # a *local* auth token is not a cloud key


# ── end to end (fakes) ─────────────────────────────────────────────
def test_bootstrap_happy_path_ends_inside_the_command_center(root, capsys):
    runner = FakeRunner()
    report = bootstrap.bootstrap(root, python="/usr/bin/python3", run=runner,
                                 opener=_refusing_opener, version_info=(3, 12, 4, "final", 0))
    assert report["ok"] is True
    assert [s["step"] for s in report["steps"]] == ["python", "venv", "deps", "runtimes", "smoke"]
    assert report["venv_created"] is True
    assert report["lock"] == "requirements-beta.lock"
    assert report["smoke"]["agents"] == 17
    assert report["next_step_url"] == "http://127.0.0.1:8080/v2"

    text = bootstrap.print_next_step(root=root, out=io.StringIO())
    assert "http://127.0.0.1:8080/v2" in text
    assert "doctor.py" in text
    assert "0.0.0.0" not in text
    # Nothing was written besides the venv: no .env, no config.
    assert sorted(p.name for p in root.iterdir()) == [
        ".venv", "requirements-beta.lock", "requirements-beta.txt", "scripts"]


def test_bootstrap_second_run_reuses_venv_and_still_smokes(root):
    runner = FakeRunner()
    first = bootstrap.bootstrap(root, run=runner, opener=_refusing_opener,
                                version_info=(3, 12, 0, "final", 0))
    second = bootstrap.bootstrap(root, run=runner, opener=_refusing_opener,
                                 version_info=(3, 12, 0, "final", 0))
    assert first["venv_created"] is True and second["venv_created"] is False
    venv_calls = [c for c in runner.calls if c["argv"][1:3] == ["-m", "venv"]]
    assert len(venv_calls) == 1
    assert second["ok"] is True


def test_bootstrap_reports_smoke_failure_not_success(root):
    report = bootstrap.bootstrap(root, run=FakeRunner(smoke_rc=1, smoke_stderr="x: readyz 503"),
                                 opener=_refusing_opener, version_info=(3, 12, 0, "final", 0))
    assert report["ok"] is False
    assert report["steps"][-1] == {"step": "smoke", "ok": False, "reason": "smoke_failed"}


_original_bootstrap = bootstrap.bootstrap


def test_bootstrap_never_emits_a_non_loopback_bind(root, capsys, monkeypatch):
    """Whatever the operator's shell says, the bootstrap output and the environment it
    hands to children never carry 0.0.0.0 — the only bind it knows is 127.0.0.1."""
    monkeypatch.setenv("JARVIS_HOST", "0.0.0.0")
    runner = FakeRunner()
    monkeypatch.setattr(bootstrap, "bootstrap",
                        lambda root_, **kw: _original_bootstrap(
                            root_, run=runner, opener=_refusing_opener,
                            version_info=(3, 12, 0, "final", 0), **kw))
    rc = bootstrap.main(["--root", str(root)])
    out = capsys.readouterr()
    assert rc == 0
    assert "0.0.0.0" not in out.out + out.err
    smoke_envs = [c["env"] for c in runner.calls if c.get("env") is not None]
    assert smoke_envs and all(e["JARVIS_HOST"] == "127.0.0.1" for e in smoke_envs)
    src = (repo_root / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    assert "0.0.0.0" not in src


def test_main_json_and_exit_code(root, capsys, monkeypatch):
    monkeypatch.setattr(bootstrap, "bootstrap",
                        lambda root_, **kw: _original_bootstrap(
                            root_, run=FakeRunner(), opener=_refusing_opener,
                            version_info=(3, 11, 0, "final", 0), **kw))
    rc = bootstrap.main(["--root", str(root), "--json"])
    out = capsys.readouterr()
    assert rc == 1
    payload = json.loads(out.out)
    assert payload["ok"] is False and payload["reason"].startswith("python_too_old")
    assert "Install Python 3.12+" in out.err


def test_wrappers_delegate_to_bootstrap():
    """install.sh / INSTALL.bat are thin: they hand over to scripts/bootstrap.py and
    never run the full pytest suite as part of an install."""
    sh = (repo_root / "install.sh").read_text(encoding="utf-8")
    bat = (repo_root / "INSTALL.bat").read_text(encoding="utf-8")
    assert "scripts/bootstrap.py" in sh
    assert "set -euo pipefail" in sh
    assert "scripts\\bootstrap.py" in bat
    assert "-m pytest" not in bat
    assert "0.0.0.0" not in sh and "0.0.0.0" not in bat


def test_real_interpreter_runs_the_floor_check():
    """The one real subprocess: the running interpreter must pass its own floor."""
    proc = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(repo_root)!r}); from scripts import bootstrap; "
         "ok, r = bootstrap.check_python(); print(r); raise SystemExit(0 if ok else 3)"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("python_ok:")
