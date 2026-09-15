"""AUD-11 — the Docker sandbox actually CONTAINS code (real containment test).

The gating tests (test_sandbox_gating.py) only assert the default-off posture and
skip the moment Docker is present, so containment itself was never proven. These
run inside the real Docker backend and assert the guarantees the run flags claim:
no network (``--network none``) and a read-only filesystem (``--read-only`` +
``:ro`` workspace mount).

They run ONLY in the dedicated Docker CI lane (RUN_SANDBOX_ISOLATION=1) so the
parallel unit-test job isn't slowed by image pulls; elsewhere they skip.
"""
import os
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.sandbox import Sandbox

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SANDBOX_ISOLATION") != "1",
    reason="sandbox containment runs only in the dedicated Docker CI lane (set RUN_SANDBOX_ISOLATION=1)",
)


def _docker_sandbox_or_skip() -> Sandbox:
    s = Sandbox(timeout=60)
    if s.active_backend() != "docker":
        pytest.skip("no Docker backend on this runner")
    return s


async def _run(code: str) -> "object":
    s = _docker_sandbox_or_skip()
    result = await s.execute_python(code)
    if result.exit_code == 125:  # docker run couldn't start (image unavailable)
        pytest.skip("sandbox image unavailable on this runner")
    return result


async def test_active_backend_is_isolated():
    s = _docker_sandbox_or_skip()
    assert s.is_isolated() is True
    assert s.security_status()["insecure_host_exec"] is False


async def test_network_is_blocked():
    result = await _run(
        "import socket\n"
        "try:\n"
        "    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    sock.settimeout(3)\n"
        "    sock.connect(('1.1.1.1', 53))\n"
        "    print('CONNECTED')\n"
        "except OSError:\n"
        "    print('BLOCKED')\n"
    )
    assert "CONNECTED" not in result.stdout
    assert "BLOCKED" in result.stdout


async def test_root_filesystem_is_read_only():
    result = await _run(
        "try:\n"
        "    open('/escape.txt', 'w').write('x')\n"
        "    print('WROTE')\n"
        "except OSError:\n"
        "    print('READONLY')\n"
    )
    assert "WROTE" not in result.stdout
    assert "READONLY" in result.stdout


async def test_workspace_mount_is_read_only():
    result = await _run(
        "try:\n"
        "    open('/workspace/escape.txt', 'w').write('x')\n"
        "    print('WROTE')\n"
        "except OSError:\n"
        "    print('READONLY')\n"
    )
    assert "WROTE" not in result.stdout
    assert "READONLY" in result.stdout


@pytest.mark.asyncio
async def test_terminal_target_runs_inside_the_real_container(tmp_path):
    """GAP-9: a terminal.exec on the isolated-sandbox target truly executes in
    Docker — the policy plane's decision is audit-chained and the command runs
    with the sandbox's containment (the suite above proves --network none and
    read-only for this same engine)."""
    from agents.core.environments import (
        GovernedTargetRunner,
        TargetAuditChain,
        TargetRegistry,
        default_targets,
    )

    registry = TargetRegistry(
        default_targets(), audit=TargetAuditChain(path=tmp_path / "audit.jsonl")
    )
    runner = GovernedTargetRunner(registry, Sandbox())
    result = await runner.run(
        target="isolated-sandbox", agent="jarvis", command="echo governed"
    )
    assert result["ok"] is True, result
    assert result["backend"] == "docker"
    assert "governed" in result["stdout"]
    assert registry.audit.entries[-1]["outcome"] == "allow"


@pytest.mark.asyncio
async def test_detached_session_kernel_two_cells_reset_and_containment(tmp_path):
    """H660: real detached container, same digest resolved by the existing CI lane."""
    from types import SimpleNamespace

    from agents.core.detached_kernel import DetachedDockerBackend
    from agents.core.session_kernels import SessionKernelManager

    image = os.environ.get('JARVIS_ACQUISITION_SANDBOX_IMAGE', '')
    assert '@sha256:' in image, 'Docker lane must provide its resolved digest'
    backend = DetachedDockerBackend(image)
    manager = SessionKernelManager(backend, cell_timeout_seconds=60)
    invocation = SimpleNamespace(agent='test', principal='owner', session_id='docker',
                                 data_scope=None, expired=lambda: False)
    try:
        first = await manager.run(invocation, 'import math\nrows = [math.pi] * 3')
        assert first.ok, first.as_dict()
        second = await manager.run(invocation, "print(round(sum(rows), 3))\n"
            "try:\n open('/escape', 'w').write('bad')\nexcept OSError:\n print('READONLY')\n"
            "import socket\n"
            "try:\n socket.create_connection(('1.1.1.1', 53), timeout=2)\n print('CONNECTED')\n"
            "except OSError:\n print('BLOCKED')")
        assert second.ok and '9.425' in second.stdout
        assert 'READONLY' in second.stdout and 'BLOCKED' in second.stdout
        assert 'CONNECTED' not in second.stdout
        assert second.continuity == 'continued'
        assert await manager.reset(invocation)
        reset = await manager.run(invocation, "print('rows' in globals())")
        assert reset.ok and reset.state_lost and 'False' in reset.stdout
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_detached_session_cancel_removes_real_container_before_reuse(tmp_path):
    import asyncio
    from types import SimpleNamespace

    from agents.core.detached_kernel import DetachedDockerBackend
    from agents.core.session_kernels import SessionKernelManager

    image = os.environ.get('JARVIS_ACQUISITION_SANDBOX_IMAGE', '')
    assert '@sha256:' in image
    backend = DetachedDockerBackend(image)
    manager = SessionKernelManager(backend, cell_timeout_seconds=60)
    invocation = SimpleNamespace(agent='test', principal='owner', session_id='cancel',
                                 data_scope=None, expired=lambda: False)
    try:
        assert (await manager.run(invocation, 'marker = 1')).ok
        handle = next(iter(manager._records.values())).handle
        task = asyncio.create_task(manager.run(invocation, 'import time\ntime.sleep(60)'))
        await asyncio.sleep(.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Do not trust cached liveness: ask the real daemon for the old name.
        proc = await asyncio.create_subprocess_exec('docker', 'inspect', handle.name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        assert await proc.wait() != 0
        result = await manager.run(invocation, "print('marker' in globals())")
        assert result.ok and result.state_lost and 'False' in result.stdout
    finally:
        await manager.shutdown()
