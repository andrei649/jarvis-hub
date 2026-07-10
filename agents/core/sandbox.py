"""
sandbox.py — Sandboxed code execution for agent-generated skills.

Port of OpenJarvis's ContainerRunner + WasmRunner to pure Python.
Supports:
- Docker container execution (primary)
- Subprocess fallback with resource limits (when Docker unavailable)
"""

import asyncio
import contextlib
import logging
import os
import platform
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

logger = logging.getLogger("jarvis.sandbox")


class SandboxError(Exception):
    pass


class SandboxResult:
    def __init__(self, stdout: str = "", stderr: str = "", exit_code: int = -1, duration: float = 0.0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.duration = duration

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        return self.stdout or self.stderr


class Sandbox:
    def __init__(
        self,
        docker_image: str = "python:3.12-slim",
        timeout: int = 30,
        max_memory_mb: int = 256,
        work_dir: str = "",
        allow_subprocess: bool = False,
        allow_wasm: bool = True,
        wasm_runtime: str = "",
        max_output_bytes: int = 50_000,
    ):
        self.docker_image = docker_image
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.max_output_bytes = max(8, int(max_output_bytes))
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp())
        self._has_docker = self._check_docker()
        self.allow_subprocess = allow_subprocess
        # H11.4 — WASM (wasmtime) backend: isolation without a Docker daemon.
        # Needs the wasmtime binary + a Python-compiled-to-WASM runtime; both are
        # host-provided, so when either is missing the backend degrades silently
        # to the existing Docker/subprocess path (no behavior change).
        self.allow_wasm = allow_wasm
        self.wasm_runtime = wasm_runtime or os.environ.get("JARVIS_WASM_PYTHON", "")
        self._has_wasmtime = self._check_wasmtime() if allow_wasm else False

    def _check_docker(self) -> bool:
        try:
            import subprocess
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            logger.warning("Docker availability check failed — falling back to subprocess sandbox", exc_info=True)
            return False

    def _check_wasmtime(self) -> bool:
        try:
            import subprocess
            result = subprocess.run(
                ["wasmtime", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            logger.warning("wasmtime availability check failed — WASM sandbox unavailable", exc_info=True)
            return False

    def wasm_available(self) -> bool:
        """True only if wasmtime AND a Python WASM runtime are usable right now."""
        return bool(
            self.allow_wasm and self._has_wasmtime and self.wasm_runtime
            and Path(self.wasm_runtime).exists()
        )

    def active_backend(self) -> str:
        """Which backend ``execute_*`` will actually use right now.

        One of ``docker`` / ``wasm`` (isolated), ``subprocess-host`` (NOT isolated —
        code runs directly on the host) or ``disabled`` (no isolated backend and the
        host fallback is off).
        """
        if self._has_docker:
            return "docker"
        if self.wasm_available():
            return "wasm"
        if self.allow_subprocess:
            return "subprocess-host"
        return "disabled"

    def is_isolated(self) -> bool:
        """True only if the active backend isolates code from the host."""
        return self.active_backend() in ("docker", "wasm")

    async def _read_output_capped(self, proc) -> tuple[str, str]:
        """Drain a child's stdout/stderr with bounded peak host memory.

        Replaces ``proc.communicate()``, which reads the child to EOF into host
        memory before truncating — so a runaway/hostile sandboxed child (this
        runs agent-generated code) could balloon host RSS for the whole timeout
        window. Here only head+tail within ``max_output_bytes`` are retained per
        stream, so peak memory is bounded while the returned (truncated) output
        and its honest byte-omission notice are unchanged.
        """
        from agents.core.environments.output_limits import (
            read_capped_stream,
            render_capped,
            truncate_text,
        )

        out_stream = getattr(proc, "stdout", None)
        err_stream = getattr(proc, "stderr", None)
        if out_stream is None and err_stream is None:
            # The process exposes no pipe streams to read incrementally (a test
            # double, or a non-PIPE spawn). Fall back to communicate(); the
            # sandbox always spawns with stdout/stderr=PIPE, so real children
            # take the memory-bounded streaming path below.
            stdout_b, stderr_b = await proc.communicate()
            return (
                truncate_text(stdout_b.decode("utf-8", errors="replace"),
                              max_content_bytes=self.max_output_bytes, label="OUTPUT").text,
                truncate_text(stderr_b.decode("utf-8", errors="replace"),
                              max_content_bytes=self.max_output_bytes, label="ERROR").text,
            )

        async def _drain(stream) -> tuple[bytes, bytes, int]:
            if stream is None:
                return b"", b"", 0
            return await read_capped_stream(
                stream, max_content_bytes=self.max_output_bytes
            )

        (h_out, t_out, tot_out), (h_err, t_err, tot_err) = await asyncio.gather(
            _drain(out_stream), _drain(err_stream)
        )
        await proc.wait()
        return (
            render_capped(h_out, t_out, tot_out,
                          max_content_bytes=self.max_output_bytes, label="OUTPUT").text,
            render_capped(h_err, t_err, tot_err,
                          max_content_bytes=self.max_output_bytes, label="ERROR").text,
        )

    def security_status(self) -> dict:
        """HF-6 — explicit isolation posture so the HUD / ``/status`` can surface
        when code would run on the HOST with no isolation. ``insecure_host_exec`` is
        the bit that matters: it's only True when the host fallback is the active
        backend (``allow_subprocess=True`` *and* neither Docker nor WASM is usable)."""
        backend = self.active_backend()
        insecure = backend == "subprocess-host"
        return {
            "backend": backend,
            "isolated": backend in ("docker", "wasm"),
            "insecure_host_exec": insecure,
            "docker": self._has_docker,
            "wasm": self.wasm_available(),
            "allow_subprocess": self.allow_subprocess,
            "warning": (
                "Code runs on the HOST with no isolation (allow_subprocess=True and "
                "neither Docker nor WASM is available). Do not enable in production (HF-6)."
            ) if insecure else "",
        }

    def _build_wasm_command(self, script_rel: str) -> list[str]:
        # Grant the runtime read access to the workdir only (no network, no other
        # FS) — the WASM module is sandboxed by wasmtime by construction.
        return ["wasmtime", "run", "--dir", str(self.work_dir),
                self.wasm_runtime, f"/workspace/{script_rel}"]

    async def execute_python(
        self,
        code: str,
        filename: str = "script.py",
        writable_paths: list[str | Path] | None = None,
    ) -> SandboxResult:
        if self._has_docker:
            return await self._execute_docker_python(
                code,
                filename,
                writable_paths=writable_paths,
            )
        if self.wasm_available():
            return await self._execute_wasm_python(code, filename)
        if not self.allow_subprocess:
            return SandboxResult(
                stderr="Code execution disabled: no Docker/WASM isolation and the host "
                       "fallback is off (allow_subprocess=False).",
                exit_code=-1,
            )
        return await self._execute_subprocess_python(code, filename)

    async def _execute_wasm_python(self, code: str, filename: str) -> SandboxResult:
        start = time.monotonic()
        fpath = self.work_dir / filename
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(code, encoding="utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._build_wasm_command(filename),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out_text, err_text = await asyncio.wait_for(
                    self._read_output_capped(proc), timeout=self.timeout)
                return SandboxResult(
                    stdout=out_text,
                    stderr=err_text,
                    exit_code=proc.returncode or 0,
                    duration=time.monotonic() - start,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    stderr=f"Execution timed out after {self.timeout}s",
                    exit_code=-1, duration=time.monotonic() - start,
                )
        except FileNotFoundError:
            logger.warning("wasmtime not found at execution — falling back")
            self._has_wasmtime = False
            if self.allow_subprocess:
                return await self._execute_subprocess_python(code, filename)
            return SandboxResult(
                stderr="WASM runtime unavailable and subprocess execution disabled",
                exit_code=-1, duration=time.monotonic() - start,
            )
        except Exception as e:
            return SandboxResult(stderr=str(e), exit_code=-1, duration=time.monotonic() - start)

    async def execute_shell(self, command: str) -> SandboxResult:
        if self._has_docker:
            return await self._execute_docker_shell(command)
        if not self.allow_subprocess:
            return SandboxResult(
                stderr="Code execution disabled: no Docker/WASM isolation and the host "
                       "fallback is off (allow_subprocess=False).",
                exit_code=-1,
            )
        return await self._execute_subprocess_shell(command)

    async def _execute_docker_python(
        self,
        code: str,
        filename: str,
        writable_paths: list[str | Path] | None = None,
    ) -> SandboxResult:
        return await self._run_docker([
            "python", f"/workspace/{filename}",
        ], {filename: code}, writable_paths=writable_paths)

    async def _execute_docker_shell(self, command: str) -> SandboxResult:
        return await self._run_docker([
            "sh", "-c", command,
        ])

    async def _run_docker(
        self,
        cmd: list[str],
        files: dict[str, str] = None,
        writable_paths: list[str | Path] | None = None,
    ) -> SandboxResult:
        start = time.monotonic()

        container_name = f"cabinet-sandbox-{int(time.time())}"
        workdir_path = str(self.work_dir)

        for fname, content in (files or {}).items():
            fpath = Path(workdir_path) / fname
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")

        docker_cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--network", "none",
            "--memory", f"{self.max_memory_mb}m",
            "--memory-swap", f"{self.max_memory_mb}m",
            "--cpus", "1",
            "--pids-limit", "50",
            "--read-only",
            "-v", f"{workdir_path}:/workspace:ro",
            *self._docker_writable_mount_args(writable_paths),
            "-w", "/workspace",
            self.docker_image,
        ] + cmd

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out_text, err_text = await asyncio.wait_for(
                    self._read_output_capped(proc), timeout=self.timeout
                )
                duration = time.monotonic() - start
                return SandboxResult(
                    stdout=out_text,
                    stderr=err_text,
                    exit_code=proc.returncode or 0,
                    duration=duration,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                duration = time.monotonic() - start
                logger.warning(f"Docker sandbox timed out after {self.timeout}s")
                return SandboxResult(
                    stderr=f"Execution timed out after {self.timeout}s",
                    exit_code=-1,
                    duration=duration,
                )
            except asyncio.CancelledError:
                # A caller (e.g. the file-RPC runtime's outer service window)
                # cancelled us. Kill the child AND the named container so neither
                # is orphaned, then propagate the cancellation. (contextlib.suppress
                # does not swallow BaseException, so a nested cancel still surfaces.)
                with contextlib.suppress(Exception):
                    proc.kill()
                with contextlib.suppress(Exception):
                    await proc.wait()
                with contextlib.suppress(Exception):
                    killer = await asyncio.create_subprocess_exec(
                        "docker", "kill", container_name,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await killer.wait()
                raise
        except FileNotFoundError:
            logger.warning("Docker not found")
            self._has_docker = False
            if self.allow_subprocess:
                return await self._execute_subprocess_python(
                    files.get("script.py", ""), "script.py"
                )
            return SandboxResult(
                stderr="Code execution disabled: Docker not available and the host "
                       "fallback is off (allow_subprocess=False).",
                exit_code=-1,
            )
        except Exception as e:
            duration = time.monotonic() - start
            return SandboxResult(
                stderr=str(e), exit_code=-1, duration=duration
            )

    def _docker_writable_mount_args(self, paths: list[str | Path] | None) -> list[str]:
        args: list[str] = []
        workdir = self.work_dir.resolve()

        for raw_path in paths or []:
            host_path = Path(raw_path).resolve()
            try:
                rel = host_path.relative_to(workdir)
            except ValueError as exc:
                raise SandboxError(
                    "Docker writable paths must be inside the sandbox work_dir"
                ) from exc

            host_path.mkdir(parents=True, exist_ok=True)
            target = PurePosixPath("/workspace", *rel.parts).as_posix()
            args.extend(["-v", f"{host_path}:{target}:rw"])

        return args

    async def _execute_subprocess_python(self, code: str, filename: str) -> SandboxResult:
        logger.warning("Sandbox: running Python on the HOST with no Docker isolation "
                       "(allow_subprocess=True) — do not enable in production (HF-6)")
        start = time.monotonic()
        fpath = self.work_dir / filename
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(code, encoding="utf-8")

        try:
            from agents.core.environments import prepare_python_child_env
            proc = await asyncio.create_subprocess_exec(
                sys.executable if platform.system() == "Windows" else "python3",
                str(fpath),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.work_dir),
                env=prepare_python_child_env(os.environ),
            )
            try:
                out_text, err_text = await asyncio.wait_for(
                    self._read_output_capped(proc), timeout=self.timeout
                )
                duration = time.monotonic() - start
                return SandboxResult(
                    stdout=out_text,
                    stderr=err_text,
                    exit_code=proc.returncode or 0,
                    duration=duration,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                duration = time.monotonic() - start
                return SandboxResult(
                    stderr=f"Execution timed out after {self.timeout}s",
                    exit_code=-1,
                    duration=duration,
                )
        except Exception as e:
            duration = time.monotonic() - start
            return SandboxResult(stderr=str(e), exit_code=-1, duration=duration)

    async def _execute_subprocess_shell(self, command: str) -> SandboxResult:
        logger.warning("Sandbox: running a shell command on the HOST with no Docker isolation "
                       "(allow_subprocess=True) — do not enable in production (HF-6)")
        start = time.monotonic()
        shell_cmd = ["cmd", "/c", command] if platform.system() == "Windows" else ["sh", "-c", command]

        try:
            from agents.core.environments import prepare_python_child_env
            proc = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.work_dir),
                env=prepare_python_child_env(os.environ),
            )
            try:
                out_text, err_text = await asyncio.wait_for(
                    self._read_output_capped(proc), timeout=self.timeout
                )
                duration = time.monotonic() - start
                return SandboxResult(
                    stdout=out_text,
                    stderr=err_text,
                    exit_code=proc.returncode or 0,
                    duration=duration,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    stderr=f"Execution timed out after {self.timeout}s",
                    exit_code=-1,
                    duration=time.monotonic() - start,
                )
        except Exception as e:
            return SandboxResult(stderr=str(e), exit_code=-1, duration=time.monotonic() - start)
