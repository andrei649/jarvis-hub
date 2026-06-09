"""H11.4 — WASM (wasmtime) sandbox backend: detection + graceful fallback.

wasmtime is not installed in CI, so these verify the selection logic and the
graceful fallback (the real WASM execution is a host seam).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.sandbox import Sandbox


def test_wasm_unavailable_by_default():
    sb = Sandbox()                 # no wasm_runtime configured
    assert sb.wasm_available() is False


def test_wasm_unavailable_when_disabled(tmp_path):
    runtime = tmp_path / "python.wasm"
    runtime.write_text("fake")
    sb = Sandbox(allow_wasm=False, wasm_runtime=str(runtime))
    sb._has_wasmtime = True         # even if the binary were present...
    assert sb.wasm_available() is False   # ...allow_wasm=False wins


def test_wasm_available_requires_runtime_file():
    sb = Sandbox(allow_wasm=True, wasm_runtime="/nonexistent/python.wasm")
    sb._has_wasmtime = True
    assert sb.wasm_available() is False   # runtime path doesn't exist


def test_wasm_available_when_all_present(tmp_path):
    runtime = tmp_path / "python.wasm"
    runtime.write_text("fake")
    sb = Sandbox(allow_wasm=True, wasm_runtime=str(runtime))
    sb._has_wasmtime = True
    assert sb.wasm_available() is True


def test_build_wasm_command(tmp_path):
    runtime = tmp_path / "python.wasm"
    sb = Sandbox(wasm_runtime=str(runtime), work_dir=str(tmp_path))
    cmd = sb._build_wasm_command("script.py")
    assert cmd[0] == "wasmtime" and cmd[1] == "run"
    assert str(runtime) in cmd and cmd[-1] == "/workspace/script.py"


@pytest.mark.asyncio
async def test_wasm_falls_back_to_subprocess_when_binary_missing(tmp_path):
    # wasm "usable" (runtime file + flag) but the wasmtime *binary* is absent →
    # _execute_wasm_python hits FileNotFoundError and falls back to subprocess.
    runtime = tmp_path / "python.wasm"
    runtime.write_text("fake")
    sb = Sandbox(allow_subprocess=True, wasm_runtime=str(runtime), work_dir=str(tmp_path))
    sb._has_docker = False
    sb._has_wasmtime = True
    assert sb.wasm_available() is True
    res = await sb.execute_python("print('from-fallback')")
    assert res.success and "from-fallback" in res.stdout
    assert sb._has_wasmtime is False   # flipped off after the missing-binary fallback


@pytest.mark.asyncio
async def test_existing_behavior_preserved_without_wasm():
    # No docker, no wasm, subprocess disabled → same "disabled" result as before.
    sb = Sandbox(allow_subprocess=False)
    sb._has_docker = False
    res = await sb.execute_python("print('x')")
    assert not res.success and "disabled" in res.stderr.lower()
