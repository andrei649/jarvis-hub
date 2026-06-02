"""
sandbox.py — Sandboxed code execution for agent-generated skills.

Port of OpenJarvis's ContainerRunner + WasmRunner to pure Python.
Supports:
- Docker container execution (primary)
- Subprocess fallback with resource limits (when Docker unavailable)
"""

import asyncio
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

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
    ):
        self.docker_image = docker_image
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp())
        self._has_docker = self._check_docker()
        self.allow_subprocess = allow_subprocess

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

    async def execute_python(self, code: str, filename: str = "script.py") -> SandboxResult:
        if self._has_docker:
            return await self._execute_docker_python(code, filename)
        if not self.allow_subprocess:
            return SandboxResult(
                stderr="Subprocess execution disabled — set DEV_MODE=1 or configure allow_subprocess=True",
                exit_code=-1,
            )
        return await self._execute_subprocess_python(code, filename)

    async def execute_shell(self, command: str) -> SandboxResult:
        if self._has_docker:
            return await self._execute_docker_shell(command)
        if not self.allow_subprocess:
            return SandboxResult(
                stderr="Subprocess execution disabled — set DEV_MODE=1 or configure allow_subprocess=True",
                exit_code=-1,
            )
        return await self._execute_subprocess_shell(command)

    async def _execute_docker_python(self, code: str, filename: str) -> SandboxResult:
        return await self._run_docker([
            "python", f"/workspace/{filename}",
        ], {filename: code})

    async def _execute_docker_shell(self, command: str) -> SandboxResult:
        return await self._run_docker([
            "sh", "-c", command,
        ])

    async def _run_docker(self, cmd: list[str], files: dict[str, str] = None) -> SandboxResult:
        import subprocess
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
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
                duration = time.monotonic() - start
                return SandboxResult(
                    stdout=stdout.decode("utf-8", errors="replace"),
                    stderr=stderr.decode("utf-8", errors="replace"),
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
        except FileNotFoundError:
            logger.warning("Docker not found")
            self._has_docker = False
            if self.allow_subprocess:
                return await self._execute_subprocess_python(
                    files.get("script.py", ""), "script.py"
                )
            return SandboxResult(
                stderr="Docker not available and subprocess execution disabled — set DEV_MODE=1",
                exit_code=-1,
            )
        except Exception as e:
            duration = time.monotonic() - start
            return SandboxResult(
                stderr=str(e), exit_code=-1, duration=duration
            )

    async def _execute_subprocess_python(self, code: str, filename: str) -> SandboxResult:
        start = time.monotonic()
        fpath = self.work_dir / filename
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(code, encoding="utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable if platform.system() == "Windows" else "python3",
                str(fpath),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.work_dir),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
                duration = time.monotonic() - start
                return SandboxResult(
                    stdout=stdout.decode("utf-8", errors="replace"),
                    stderr=stderr.decode("utf-8", errors="replace"),
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
        start = time.monotonic()
        shell_cmd = ["cmd", "/c", command] if platform.system() == "Windows" else ["sh", "-c", command]

        try:
            proc = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.work_dir),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
                duration = time.monotonic() - start
                return SandboxResult(
                    stdout=stdout.decode("utf-8", errors="replace"),
                    stderr=stderr.decode("utf-8", errors="replace"),
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
