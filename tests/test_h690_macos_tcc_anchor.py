"""H690 — macOS TCC interpreter anchoring across install and hub updates."""

import ast
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agents.core import hub_update_apply, macos_tcc_anchor
from scripts import bootstrap, venv_ownership


def test_macos_tcc_anchor_uses_only_stdlib_and_old_grammar():
    src = Path(macos_tcc_anchor.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src, feature_version=(3, 8))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_non_macos_and_unmanaged_interpreters_are_noops(tmp_path):
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    src_py = tmp_path / "usr" / "bin" / "python3"
    src_py.parent.mkdir(parents=True)
    src_py.write_text("#!/bin/sh\n", encoding="utf-8")
    os.symlink(src_py, venv / "bin" / "python3")

    calls = []

    def bad_run(*args, **kwargs):
        calls.append(args)
        raise AssertionError("subprocess must not run on non-macOS or unmanaged interpreter")

    res_linux = macos_tcc_anchor.anchor_venv_interpreter(venv, platform_name="linux", run=bad_run)
    assert res_linux == {"ok": True, "anchored": False, "reason": "not_macos"}

    assert macos_tcc_anchor.is_managed_macos_python(Path("/usr/bin/python3")) is False
    assert macos_tcc_anchor.is_managed_macos_python(Path("/System/Library/Frameworks/Python.framework/Python")) is False

    res_unmanaged = macos_tcc_anchor.anchor_venv_interpreter(
        venv, python="/usr/bin/python3", platform_name="darwin", run=bad_run,
    )
    assert res_unmanaged["anchored"] is False
    assert res_unmanaged["reason"] in {"unmanaged_interpreter", "source_interpreter_unresolved"}
    assert os.path.islink(venv / "bin" / "python3")
    assert calls == []


def _make_fake_managed_python(tmp_path: Path):
    managed_root = tmp_path / ".local" / "share" / "uv" / "python" / "cpython-3.12.13-macos-aarch64"
    (managed_root / "bin").mkdir(parents=True)
    (managed_root / "lib").mkdir(parents=True)
    py_bin = managed_root / "bin" / "python3.12"
    py_bin.write_bytes(b"\xcf\xfa\xed\xfeFAKE_MACHO_PYTHON_BINARY")
    py_bin.chmod(0o755)
    dylib = managed_root / "lib" / "libpython3.12.dylib"
    dylib.write_bytes(b"\xcf\xfa\xed\xfeFAKE_LIBPYTHON_DYLIB")
    dylib.chmod(0o755)

    codesign = tmp_path / "codesign"
    codesign.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codesign.chmod(0o755)

    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(f"home = {managed_root / 'bin'}\n", encoding="utf-8")
    for name in ("python", "python3", "python3.12"):
        os.symlink(py_bin, venv / "bin" / name)
    return managed_root, py_bin, dylib, codesign, venv


def test_hermetic_anchor_replaces_symlinks_hardlinks_libpython_and_passes_ownership(tmp_path):
    _, py_bin, dylib, codesign, venv = _make_fake_managed_python(tmp_path)
    recorded = []

    def fake_run(argv, **kwargs):
        recorded.append(list(argv))
        # While codesign and boot gate run, live .venv/bin/python* must still be untouched symlinks!
        assert os.path.islink(venv / "bin" / "python")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    logs = []
    result = macos_tcc_anchor.anchor_venv_interpreter(
        venv,
        platform_name="darwin",
        codesign_bin=str(codesign),
        run=fake_run,
        log=logs.append,
    )
    assert result["ok"] is True
    assert result["anchored"] is True
    assert sorted(result["binaries"]) == ["python", "python3", "python3.12"]
    assert result["libpython"] == ["libpython3.12.dylib"]

    # 1. Real-file copies, never symlinks
    for name in ("python", "python3", "python3.12"):
        target = venv / "bin" / name
        assert not os.path.islink(target)
        assert stat.S_ISREG(os.lstat(target).st_mode)
        assert target.read_bytes() == py_bin.read_bytes()

    # 2. libpython hardlinked into venv/lib on same UID & filesystem
    anchored_lib = venv / "lib" / "libpython3.12.dylib"
    assert anchored_lib.is_file()
    assert not os.path.islink(anchored_lib)
    if os.name != "nt":
        assert os.stat(anchored_lib).st_ino == os.stat(dylib).st_ino

    # 3. Signature pinned with stable identifier + boot gate invoked on staged path
    assert len(recorded) == 2
    assert recorded[0][:6] == [str(codesign), "--force", "--sign", "-", "--identifier", "ai.nerva.python"]
    assert recorded[1][1] == "-c" and "import encodings" in recorded[1][2]

    # 4. Staged artifacts cleaned up and venv_ownership preflight passes
    leftover = [p.name for p in (venv / "bin").iterdir() if ".nerva-" in p.name]
    assert leftover == []
    if os.name != "nt":
        ownership = venv_ownership.preflight_venv(venv)
        assert ownership["ok"] is True, ownership


@pytest.mark.parametrize("fail_step,expected_reason", [
    ("codesign", "codesign_failed"),
    ("boot", "boot_gate_failed"),
])
def test_rollback_restores_symlinks_and_removes_staged_files_when_gate_fails(tmp_path, fail_step, expected_reason):
    _, py_bin, _, codesign, venv = _make_fake_managed_python(tmp_path)

    def failing_run(argv, **kwargs):
        if fail_step == "codesign" and argv[0] == str(codesign):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="sign error")
        if fail_step == "boot" and len(argv) >= 2 and argv[1] == "-c":
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="encodings broken")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    res = macos_tcc_anchor.anchor_venv_interpreter(
        venv,
        platform_name="darwin",
        codesign_bin=str(codesign),
        run=failing_run,
    )
    assert res == {"ok": False, "anchored": False, "reason": expected_reason}

    # Live symlinks untouched, staged interpreter and staged libpython rolled back!
    for name in ("python", "python3", "python3.12"):
        entry = venv / "bin" / name
        assert os.path.islink(entry)
        assert Path(os.path.realpath(str(entry))) == py_bin.resolve()
    assert not (venv / "lib" / "libpython3.12.dylib").exists()
    assert [p.name for p in (venv / "bin").iterdir() if ".nerva-" in p.name] == []


def test_never_raises_on_subprocess_exception_or_corrupt_path(tmp_path):
    _, _, _, codesign, venv = _make_fake_managed_python(tmp_path)

    def raising_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["codesign"], timeout=30)

    res = macos_tcc_anchor.anchor_venv_interpreter(
        venv, platform_name="darwin", codesign_bin=str(codesign), run=raising_run,
    )
    assert res["anchored"] is False
    # hub_update_apply wrapper also never raises
    logs = []
    hub_update_apply._anchor_macos_venv(logs.append)


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/codesign").is_file(),
    reason="requires macOS host with /usr/bin/codesign",
)
def test_live_macos_venv_codesign_and_boot_gate_end_to_end(tmp_path):
    cand = Path(sys.base_prefix) / "bin" / f"python{sys.version_info[0]}.{sys.version_info[1]}"
    if not cand.exists():
        cand = Path(getattr(sys, "_base_executable", sys.executable))
    base_exe = os.path.realpath(str(cand))
    if not macos_tcc_anchor.is_managed_macos_python(Path(base_exe)):
        pytest.skip(f"host python {base_exe} is not a managed macOS interpreter")

    venv = tmp_path / ".venv"
    subprocess.run([base_exe, "-m", "venv", "--without-pip", str(venv)], check=True)
    assert os.path.islink(venv / "bin" / "python")

    res = bootstrap._anchor_macos_venv(venv, python=base_exe)
    assert res["ok"] is True and res["anchored"] is True, res

    for name in ("python", "python3"):
        p = venv / "bin" / name
        assert p.is_file() and not os.path.islink(p)
        verify = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(p)], capture_output=True, text=True)
        assert verify.returncode == 0, verify.stderr
        info = subprocess.run(["/usr/bin/codesign", "-dv", str(p)], capture_output=True, text=True)
        assert f"Identifier={macos_tcc_anchor.TCC_IDENTIFIER}" in info.stderr

    boot = subprocess.run(
        [str(venv / "bin" / "python"), "-c", "import encodings, pathlib, sys; print(pathlib.Path(sys.prefix).resolve())"],
        capture_output=True, text=True, check=True,
    )
    assert Path(boot.stdout.strip()) == venv.resolve()
    assert venv_ownership.preflight_venv(venv)["ok"] is True
