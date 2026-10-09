"""Bounded local Python-toolchain probe adapted from pinned Hermes tools/env_probe.py.

Copied semantics: _python_version_of, _has_pip_module, _detect_pep668,
_pip_python_version, and _build_probe_line (upstream lines 89-174). This probe
is local-only; its caller gates it on an enabled local target. The subprocess
runner adapts upstream lines 54-86 to cap output and kill the process group on
timeout, without using capture pipes inherited by descendants.

MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess  # nosec B404  # fixed local interpreter/toolchain introspection argv
import tempfile

_MAX_PROBE_OUTPUT = 4096
_PROBE_TIMEOUT = 1.5


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Run a short local command; temp files prevent pipe-inheriting descendants hanging us."""
    try:
        with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
            process = subprocess.Popen(  # nosec B603  # fixed probe argv, shell=False; no model or task input
                cmd, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f,
                start_new_session=os.name != 'nt',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0,
            )
            try:
                returncode = process.wait(timeout=_PROBE_TIMEOUT)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=1)
                return -1, '', 'timeout'
            out_f.seek(0)
            err_f.seek(0)
            return (returncode,
                    out_f.read(_MAX_PROBE_OUTPUT).decode('utf-8', 'replace').strip(),
                    err_f.read(_MAX_PROBE_OUTPUT).decode('utf-8', 'replace').strip())
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return -1, '', 'unavailable'


def _py_out(binary: str, *args: str) -> str | None:
    """stdout of ``<binary> *args`` when the binary is on PATH and exits 0."""
    if not shutil.which(binary):
        return None
    rc, out, _err = _run([binary, *args])
    return out if rc == 0 else None


def _python_version_of(binary: str) -> str | None:
    """Return a short version string like ``3.12.4`` for ``binary``."""
    code = "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    return _py_out(binary, '-c', code) or None


def _has_pip_module(binary: str) -> bool:
    return _py_out(binary, '-m', 'pip', '--version') is not None


def _detect_pep668(binary: str) -> bool:
    code = ("import os; print('yes' if os.path.exists(os.path.join("
            "os.path.dirname(os.__file__), 'EXTERNALLY-MANAGED')) else 'no')")
    return (_py_out(binary, '-c', code) or '').strip() == 'yes'


def _pip_python_version() -> str | None:
    out = _py_out('pip', '--version') or ''
    if '(python ' in out and out.endswith(')'):
        return out.rsplit('(python ', 1)[1][:-1].strip()
    return None


def _build_probe_line() -> str:
    """Hermes-compatible one-line notice when the local Python toolchain has a trap."""
    py3_ver = _python_version_of('python3')
    py_ver = _python_version_of('python')
    py3_has_pip = _has_pip_module('python3') if py3_ver else False
    pip_bound_to = _pip_python_version()
    py3_pep668 = _detect_pep668('python3') if py3_ver else False
    has_uv = shutil.which('uv') is not None

    mismatch = bool(pip_bound_to and py3_ver and not py3_ver.startswith(pip_bound_to))
    if py3_ver is not None and py3_has_pip and not mismatch and (not py3_pep668 or has_uv):
        return ''
    bits: list[str] = []
    if py3_ver:
        bits.append(f'python3={py3_ver}' + ('' if py3_has_pip else ' (no pip module)'))
    else:
        bits.append('python3=missing')
    if py_ver and py_ver != py3_ver:
        bits.append(f'python={py_ver}')
    elif not py_ver and py3_ver:
        bits.append('python=missing (use python3)')
    if pip_bound_to:
        if mismatch:
            bits.append(f'pip→python{pip_bound_to} (mismatch)')
        elif not py3_has_pip:
            bits.append(f'pip→python{pip_bound_to}')
    elif not py3_has_pip:
        bits.append('pip=missing')
    if py3_pep668:
        bits.append('PEP 668=yes (use venv or uv)')
    if has_uv:
        bits.append('uv=installed')
    return 'Python toolchain: ' + ', '.join(bits) + '.'
