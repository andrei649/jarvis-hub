"""H595 one-shot context reaches the worker over stdin and stays isolated."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import venv
from pathlib import Path

import pytest

from agents.core.sandbox import Sandbox
from agents.core.tool_rpc import ToolRPCServer
from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime


def _test_host_sandbox(tmp_path: Path) -> Sandbox:
    sandbox = Sandbox(allow_subprocess=True, allow_wasm=False, work_dir=str(tmp_path / "run"), timeout=5)
    sandbox._has_docker = False
    sandbox._has_wasmtime = False
    sandbox._allow_host_context_for_tests = True
    return sandbox


@pytest.mark.asyncio
async def test_runtime_project_context_real_worker_import_data_and_env(tmp_path: Path) -> None:
    project = tmp_path / "owner-project"
    (project / "pkg").mkdir(parents=True)
    (project / "pkg" / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
    (project / "data.txt").write_text("local-data", encoding="utf-8")
    (project / ".env").write_text("OWNER_SECRET=private", encoding="utf-8")
    sandbox = _test_host_sandbox(tmp_path)
    runtime = ToolRPCSandboxRuntime(ToolRPCServer(), sandbox)
    checks: list[int] = []

    def check_current() -> bool:
        checks.append(1)
        return True

    code = (
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "import pkg\n"
        "print(json.dumps({'value': pkg.VALUE, 'data': Path('data.txt').read_text(), "
        "'env': os.environ.get('MODEL_NOTE'), 'secret': os.environ.get('OWNER_SECRET'), "
        "'cwd': os.getcwd(), 'python': sys.executable}))\n"
    )
    run = await runtime.run_python(code, execution_context={
        "mode": "project", "project_root": str(project),
        "env": {"MODEL_NOTE": "hello"}, "interpreter_env": {},
        "redact": lambda text: text, "check_current": check_current,
    })
    assert run.result.success, run.result.stderr
    assert run.tool_calls == 0
    answer = json.loads(run.result.stdout.strip())
    assert answer["value"] == 42
    assert answer["data"] == "local-data"
    assert answer["env"] == "hello"
    assert answer["secret"] is None
    assert Path(answer["cwd"]).name == "project"
    assert Path(answer["python"]).resolve() == Path(sys.executable).resolve()
    assert run.result.execution_context == {
        "mode": "project", "cwd": answer["cwd"], "python": answer["python"],
    }
    assert len(checks) == 2
    assert not list((sandbox.work_dir.parent / ".h595_context").glob("run-*"))
    assert not any("private" in path.read_text(errors="ignore") for path in sandbox.work_dir.rglob("*.py"))


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["native", "wasm"])
async def test_worker_cancel_reaps_process_before_return(tmp_path, monkeypatch, backend):
    sandbox = _test_host_sandbox(tmp_path)
    if backend == "wasm":
        # Real process, simulated WASM command adapter; no containment claim.
        monkeypatch.setattr(sandbox, "wasm_available", lambda: True)
        monkeypatch.setattr(sandbox, "_build_wasm_command",
                            lambda filename: [sys.executable, str(sandbox.work_dir / filename)])
    pid_file = tmp_path / "native.pid"
    task = asyncio.create_task(sandbox.execute_python(
        f"import os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\ntime.sleep(10)"))
    try:
        for _ in range(150):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        pid = int(pid_file.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if pid_file.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 9)


@pytest.mark.asyncio
async def test_strict_context_stays_in_staging_and_default_interpreter(tmp_path: Path) -> None:
    project = tmp_path / "owner-project"
    project.mkdir()
    (project / "project_only.py").write_text("VALUE = 1\n", encoding="utf-8")
    sandbox = _test_host_sandbox(tmp_path)
    run = await sandbox.execute_python(
        "import importlib.util, json, os, sys\n"
        "print(json.dumps({'found': importlib.util.find_spec('project_only') is not None, "
        "'cwd': os.getcwd(), 'python': sys.executable}))\n",
        execution_context={"mode": "strict", "project_root": str(project),
                           "env": {}, "interpreter_env": {}, "check_current": lambda: True},
    )
    assert run.success, run.stderr
    answer = json.loads(run.stdout.strip())
    assert answer["found"] is False
    assert Path(answer["cwd"]) == sandbox.work_dir
    assert Path(answer["python"]).resolve() == Path(sys.executable).resolve()
    assert run.execution_context == {
        "mode": "strict", "cwd": answer["cwd"], "python": answer["python"],
    }


@pytest.mark.asyncio
async def test_project_context_launches_real_virtualenv_interpreter(tmp_path: Path) -> None:
    environment = tmp_path / "project-venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    project = tmp_path / "owner-project"
    project.mkdir()
    sandbox = _test_host_sandbox(tmp_path)
    run = await sandbox.execute_python(
        "import json, sys\nprint(json.dumps({'prefix': sys.prefix, 'python': sys.executable}))\n",
        execution_context={"mode": "project", "project_root": str(project), "env": {},
                           "interpreter_env": {"VIRTUAL_ENV": str(environment)},
                           "check_current": lambda: True},
    )
    assert run.success, run.stderr
    answer = json.loads(run.stdout.strip())
    assert Path(answer["prefix"]).resolve() == environment.resolve()
    assert Path(answer["python"]).parent.parent.resolve() == environment.resolve()


@pytest.mark.asyncio
async def test_cancelled_real_virtualenv_worker_stops_descendant_before_cleanup(tmp_path: Path) -> None:
    environment = tmp_path / "project-venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    project = tmp_path / "owner-project"
    project.mkdir()
    sandbox = _test_host_sandbox(tmp_path)
    sandbox.timeout = 20
    heartbeat = tmp_path / "heartbeat.txt"
    code = (
        "import time\nfrom pathlib import Path\n"
        f"heartbeat = Path({str(heartbeat)!r})\n"
        "count = 0\n"
        "while True:\n"
        "    heartbeat.write_text(str(count))\n"
        "    count += 1\n"
        "    time.sleep(0.02)\n"
    )
    task = asyncio.create_task(sandbox.execute_python(code, execution_context={
        "mode": "project", "project_root": str(project), "env": {},
        "interpreter_env": {"VIRTUAL_ENV": str(environment)},
        "check_current": lambda: True,
    }))
    try:
        for _ in range(150):
            if heartbeat.exists():
                break
            await asyncio.sleep(0.02)
        assert heartbeat.exists()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await asyncio.sleep(0.15)
    stopped_at = heartbeat.read_text()
    await asyncio.sleep(0.15)
    assert heartbeat.read_text() == stopped_at
    assert not list((sandbox.work_dir.parent / ".h595_context").glob("run-*"))


@pytest.mark.asyncio
async def test_startup_pipe_is_within_execution_timeout(tmp_path: Path, monkeypatch) -> None:
    sandbox = _test_host_sandbox(tmp_path)
    sandbox.timeout = 0.2
    monkeypatch.setattr(sandbox, "_context_bootstrap_source",
                        lambda: "import time\ntime.sleep(5)\n")
    result = await sandbox.execute_python("x = 'a' * 500000", execution_context={
        "mode": "strict", "env": {}, "interpreter_env": {},
        "check_current": lambda: True,
    })
    assert not result.success
    assert "timed out" in result.stderr
    assert result.timed_out is True


@pytest.mark.asyncio
async def test_docker_context_uses_private_stdin_and_readonly_projection(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "owner-project"
    project.mkdir()
    (project / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    sandbox = Sandbox(work_dir=str(tmp_path / "run"), timeout=5)
    sandbox._has_docker = True
    calls: list[tuple[str, ...]] = []
    transmitted: list[bytes] = []
    checks: list[int] = []

    class Stdin:
        def write(self, data: bytes) -> None:
            transmitted.append(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    class Proc:
        returncode = 0
        stdin = Stdin()

        async def communicate(self):
            return b"ok\n", b""

        async def wait(self):
            return None

        def kill(self):
            return None

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return Proc()

    monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", fake_exec)

    def check_current() -> bool:
        checks.append(1)
        return True

    result = await sandbox.execute_python("print('owner-only-marker')", execution_context={
        "mode": "project", "project_root": str(project),
        "env": {"MODEL_NOTE": "private-env-value"}, "interpreter_env": {},
        "check_current": check_current,
    })
    assert result.success
    assert len(checks) == 2
    assert len(transmitted) == 1
    argv = list(calls[0])
    assert "private-env-value" not in " ".join(argv)
    assert "owner-only-marker" not in " ".join(argv)
    assert "-i" in argv
    assert any("dst=/project,readonly" in item for item in argv)
    assert any("dst=/workspace,readonly" in item for item in argv)
    assert any("dst=/context" in item and "readonly" not in item for item in argv)
    assert b"private-env-value" in transmitted[0]
    assert b"owner-only-marker" in transmitted[0]
    assert not list((sandbox.work_dir.parent / ".h595_context").glob("run-*"))


@pytest.mark.asyncio
async def test_context_refuses_wasm_and_host_fallback(tmp_path: Path) -> None:
    sandbox = Sandbox(allow_subprocess=True, work_dir=str(tmp_path / "run"))
    sandbox._has_docker = False
    sandbox._has_wasmtime = False
    result = await sandbox.execute_python("print('should-not-run')", execution_context={
        "mode": "project", "env": {}, "interpreter_env": {},
        "check_current": lambda: True,
    })
    assert not result.success
    assert result.refusal_reason == "context_backend_unsupported"


@pytest.mark.asyncio
async def test_revoked_after_backend_start_never_transmits_payload(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "owner-project"
    project.mkdir()
    (project / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    sandbox = Sandbox(work_dir=str(tmp_path / "run"), timeout=5)
    sandbox._has_docker = True
    writes: list[bytes] = []
    calls: list[tuple[str, ...]] = []
    checks = 0

    class Stdin:
        def write(self, data: bytes) -> None:
            writes.append(data)

    class Proc:
        returncode = -1
        stdin = Stdin()

        def kill(self):
            return None

        async def wait(self):
            return None

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return Proc()

    monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", fake_exec)

    def current() -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    result = await sandbox.execute_python("print('must-not-run')", execution_context={
        "mode": "project", "project_root": str(project), "env": {"NOTE": "sensitive"},
        "interpreter_env": {}, "check_current": current,
    })
    assert result.refusal_reason == "context_stale"
    assert checks == 2
    assert writes == []
    assert len(calls) == 2  # docker run, then docker kill
    assert calls[1][:2] == ("docker", "kill")
    assert not list((sandbox.work_dir.parent / ".h595_context").glob("run-*"))


def test_context_metadata_symlink_is_never_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text('{"mode":"project","cwd":"/tmp","python":"/python"}',
                       encoding="utf-8")
    sidecar = tmp_path / "result.json"
    sidecar.symlink_to(outside)
    assert Sandbox._read_context_metadata(sidecar) is None


@pytest.mark.asyncio
async def test_docker_startup_drain_timeout_stops_container_before_cleanup(tmp_path, monkeypatch):
    sandbox = Sandbox(work_dir=str(tmp_path / "run"), timeout=0.05)
    sandbox._has_docker = True
    calls = []

    class Stdin:
        def write(self, data):
            pass

        async def drain(self):
            await asyncio.Future()

    class Proc:
        stdin = Stdin()
        returncode = None

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    async def spawn(*argv, **kwargs):
        calls.append(argv)
        return Proc()

    monkeypatch.setattr("agents.core.sandbox.asyncio.create_subprocess_exec", spawn)
    try:
        result = await asyncio.wait_for(sandbox.execute_python("pass", execution_context={
            "mode": "strict", "env": {}, "interpreter_env": {},
            "check_current": lambda: True,
        }), timeout=0.5)
    except TimeoutError:
        pytest.fail("Docker startup drain exceeded the execution timeout")
    assert not result.success
    assert "timed out" in result.stderr
    assert any(argv[:2] == ("docker", "kill") for argv in calls)
    assert not list((sandbox.work_dir.parent / ".h595_context").glob("run-*"))
