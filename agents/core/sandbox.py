"""
sandbox.py — Sandboxed code execution for agent-generated skills.

Port of OpenJarvis's ContainerRunner + WasmRunner to pure Python.
Supports:
- Docker container execution (primary)
- Subprocess fallback with resource limits (when Docker unavailable)
"""

import asyncio
import contextlib
import json
import logging
import os
import platform
import secrets
import shutil
import signal
import stat
import sys
import time
import weakref
from pathlib import Path, PurePath, PurePosixPath

logger = logging.getLogger("jarvis.sandbox")


class SandboxError(Exception):
    pass


class ContextTeardownUnconfirmed(SandboxError):
    pass


def _bind_mount(source: str, target: str, *, readonly: bool) -> list[str]:
    """A Docker bind mount as ``--mount``, never ``-v``: a ``:`` in the host path (a data
    root such as ``/srv/a:b``) split ``-v`` into the wrong fields (review-H667 nit 4).
    Each field is CSV-quoted, so a ``,``, ``"`` or line break in the path is data, not
    syntax (review-H667b nit 1)."""
    def field(text: str) -> str:
        if any(ch in text for ch in ',"\n\r'):
            return '"' + text.replace('"', '""') + '"'
        return text

    fields = ["type=bind", f"src={source}", f"dst={target}"] + (["readonly"] if readonly else [])
    return ["--mount", ",".join(field(f) for f in fields)]


class SandboxResult:
    def __init__(self, stdout: str = "", stderr: str = "", exit_code: int = -1,
                 duration: float = 0.0, execution_context: dict | None = None,
                 refusal_reason: str = "", timed_out: bool = False):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.duration = duration
        self.execution_context = execution_context
        self.refusal_reason = refusal_reason
        self.timed_out = timed_out

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
        # H667: a run directory under the managed cache (<data root>/cache/exec), or the
        # owner's chosen root, never the system temp root (tmpfs on many distros). Its
        # lock, held while this sandbox lives, keeps the cache's prune away from it.
        self._work_lock = None
        self.work_dir_managed = False
        if work_dir:
            self.work_dir = Path(work_dir)
        else:
            from . import exec_cache

            self.work_dir, self.work_dir_managed = exec_cache.new_work_dir()
            # Only the managed cache is pruned, so only its run directories take a lock.
            self._work_lock = exec_cache.hold(self.work_dir) if self.work_dir_managed else None
            self._release = weakref.finalize(self, exec_cache.release, self._work_lock,
                                             self.work_dir)
        self._has_docker = self._check_docker()
        self.allow_subprocess = allow_subprocess
        # H11.4 — WASM (wasmtime) backend: isolation without a Docker daemon.
        # Needs the wasmtime binary + a Python-compiled-to-WASM runtime; both are
        # host-provided, so when either is missing the backend degrades silently
        # to the existing Docker/subprocess path (no behavior change).
        self.allow_wasm = allow_wasm
        self.wasm_runtime = wasm_runtime or os.environ.get("JARVIS_WASM_PYTHON", "")
        self._has_wasmtime = self._check_wasmtime() if allow_wasm else False

    def ensure_work_dir(self) -> None:
        """A run directory removed under a live sandbox is made again private (0700),
        and its lock taken again, never re-created world-readable (review-H667 m6). A
        managed one that is there without its lock, or wider than 0700 (made again by
        another path first: review-H667b m2), is made right too, and so is one whose
        first lock could not be taken."""
        missing = not self.work_dir.is_dir()
        if missing:
            self.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.work_dir_managed:
            return
        from . import exec_cache

        with contextlib.suppress(OSError):
            if stat.S_IMODE(os.stat(self.work_dir).st_mode) & 0o077:
                os.chmod(self.work_dir, 0o700)  # nosec B103  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        # A lock that is not there (never taken, or removed) is taken now (review-H667c nit 5).
        if missing or not exec_cache._lock_path(self.work_dir).is_file():
            self._release.detach()
            exec_cache.release(self._work_lock, self.work_dir)
            self._work_lock = exec_cache.hold(self.work_dir)
            self._release = weakref.finalize(self, exec_cache.release, self._work_lock,
                                             self.work_dir)

    _ensure_work_dir = ensure_work_dir

    @staticmethod
    def _probe_binary(argv: list[str], missing_note: str) -> bool:
        """Run a `--version`-style probe; True when the tool answers cleanly.

        Docker and wasmtime are both *optional* host tools — the class comment
        above promises the backend "degrades silently" when either is absent. It
        did not: every failure was logged with `exc_info=True`, so a host that
        simply does not have wasmtime installed greeted the operator with a
        `FileNotFoundError: [WinError 2]` traceback at every startup, for a
        configuration that is entirely supported.

        A binary that is not on PATH is the ordinary case and gets one line. A
        probe that fails for any other reason (a permission problem, a hung
        daemon) is genuinely unexpected and keeps its traceback.
        """
        import subprocess

        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        except (FileNotFoundError, NotADirectoryError):
            logger.info("%s is not installed — %s", argv[0], missing_note)
            return False
        except Exception:
            logger.warning(
                "%s availability check failed — %s", argv[0], missing_note, exc_info=True
            )
            return False
        if result.returncode != 0:
            logger.info("%s is installed but not usable — %s", argv[0], missing_note)
            return False
        return True

    def _check_docker(self) -> bool:
        return self._probe_binary(
            ["docker", "info"], "falling back to the subprocess sandbox"
        )

    def _check_wasmtime(self) -> bool:
        return self._probe_binary(
            ["wasmtime", "--version"], "the WASM sandbox is unavailable"
        )

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

    async def _read_output_capped(self, proc, sinks=None) -> tuple[str, str]:
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

        # H305/H595: when the caller wants the complete stream kept, every chunk goes
        # to its sink on the way past. What this function *returns* is capped exactly
        # as before; the sink is the separate, lossless copy.
        out_sink = getattr(sinks, "stdout", None)
        err_sink = getattr(sinks, "stderr", None)

        out_stream = getattr(proc, "stdout", None)
        err_stream = getattr(proc, "stderr", None)
        if out_stream is None and err_stream is None:
            # The process exposes no pipe streams to read incrementally (a test
            # double, or a non-PIPE spawn). Fall back to communicate(); the
            # sandbox always spawns with stdout/stderr=PIPE, so real children
            # take the memory-bounded streaming path below.
            stdout_b, stderr_b = await proc.communicate()
            # This branch buffers, so spooling saves nothing on memory here — but the
            # caller asked for the complete stream and this is where it exists.
            if out_sink is not None and stdout_b:
                out_sink(stdout_b)
            if err_sink is not None and stderr_b:
                err_sink(stderr_b)
            return (
                truncate_text(stdout_b.decode("utf-8", errors="replace"),
                              max_content_bytes=self.max_output_bytes, label="OUTPUT").text,
                truncate_text(stderr_b.decode("utf-8", errors="replace"),
                              max_content_bytes=self.max_output_bytes, label="ERROR").text,
            )

        async def _drain(stream, sink) -> tuple[bytes, bytes, int]:
            if stream is None:
                return b"", b"", 0
            return await read_capped_stream(
                stream, max_content_bytes=self.max_output_bytes, sink=sink,
            )

        (h_out, t_out, tot_out), (h_err, t_err, tot_err) = await asyncio.gather(
            _drain(out_stream, out_sink), _drain(err_stream, err_sink)
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
        sinks=None,
        execution_context: dict | None = None,
    ) -> SandboxResult:
        """``sinks`` (an ``output_limits.StreamSinks``) spools the child's streams.

        What comes back in the ``SandboxResult`` is capped exactly as before; the
        sinks are the separate, complete copy, written as the streams arrive so
        nothing is ever held whole. Every fallback below re-routes at spawn time,
        before a byte has been read, so a sink can never receive two runs' output.

        Each run writes a file of its own (``script-<random>.py`` for ``script.py``) and
        removes it afterwards: the orchestrator shares one Sandbox across every turn, and
        two runs that wrote one name overwrote each other's code, so one ran the other's
        script, against the other's tool-RPC mailbox, and answered it to the wrong
        caller (review-H315g).
        """
        # The suffix comes off the file's own name only: a dot in a directory ("a.d/run")
        # made a new directory per run, left behind (review-H315h n4).
        path = PurePath(filename)
        if not path.name:
            # "", "." or "/": no name to keep; the default one runs (review-H315i n3).
            path = PurePath("script.py")
        stem, dot, ext = path.name.rpartition(".")
        name = (f"{stem}-{secrets.token_hex(8)}.{ext}" if dot and stem
                else f"{path.name}-{secrets.token_hex(8)}")
        run_name = str(path.with_name(name))
        try:
            if execution_context is not None:
                return await self._execute_context_python(
                    code, run_name, writable_paths=writable_paths, sinks=sinks,
                    execution_context=execution_context,
                )
            return await self._execute_python_file(code, run_name, writable_paths=writable_paths,
                                                   sinks=sinks)
        finally:
            with contextlib.suppress(OSError):
                (self.work_dir / run_name).unlink()

    @staticmethod
    def _context_refusal(check_current) -> str:
        if not callable(check_current):
            return "context_stale"
        try:
            return "context_stale" if check_current() is False else ""
        except Exception as exc:
            reason = getattr(exc, "reason", "")
            if isinstance(reason, str) and reason.isidentifier() and len(reason) <= 64:
                return reason
            return "context_stale"

    @staticmethod
    def _context_bootstrap_source() -> str:
        """Constant worker source. Code and environment arrive only on stdin."""
        from .code_context import CHILD_CONTEXT_SOURCE

        return CHILD_CONTEXT_SOURCE + """
import json

def _h595_main():
    raw = sys.stdin.buffer.read()
    payload = json.loads(raw)
    selected = resolve_child_context(payload["context"])
    if (not payload.get("reexecuted") and
            os.path.abspath(selected["python"]) != os.path.abspath(sys.executable)):
        payload["reexecuted"] = True
        child_env = payload["env"]
        result = subprocess.run([selected["python"], __file__],
                                input=json.dumps(payload).encode("utf-8"),
                                env=child_env, check=False)
        raise SystemExit(result.returncode)
    os.chdir(selected["cwd"])
    os.environ.clear()
    os.environ.update(payload["env"])
    sys.path.insert(0, selected["cwd"])
    metadata_path = payload.get("metadata_path")
    if metadata_path:
        metadata_tmp = metadata_path + ".tmp"
        with open(metadata_tmp, "x", encoding="utf-8") as output:
            json.dump({"mode": selected["mode"], "cwd": os.getcwd(),
                       "python": sys.executable}, output)
        os.replace(metadata_tmp, metadata_path)
    scope = {"__name__": "__main__", "__file__": "<execute_code>"}
    exec(compile(payload["code"], "<execute_code>", "exec"), scope)

if __name__ == "__main__":
    _h595_main()
"""

    async def _execute_context_python(self, code: str, filename: str,
                                      *, writable_paths=None, sinks=None,
                                      execution_context: dict) -> SandboxResult:
        """Prepare a bounded project mirror, then start a context-aware worker."""
        from .code_context import ProjectSnapshotError, normalize_mode, prepare_project

        context = execution_context
        check_current = context.get("check_current") if isinstance(context, dict) else None
        refusal = self._context_refusal(check_current)
        if refusal:
            return SandboxResult(stderr="Execution context is no longer current",
                                 refusal_reason=refusal)
        try:
            mode = normalize_mode(context.get("mode"))
            env = context.get("env", {})
            interpreter_env = context.get("interpreter_env", {})
            if not isinstance(env, dict) or not isinstance(interpreter_env, dict):
                raise ValueError("invalid_environment")
            if any(not isinstance(k, str) or not isinstance(v, str)
                   for mapping in (env, interpreter_env) for k, v in mapping.items()):
                raise ValueError("invalid_environment")
            exposed_env = dict(env)
            exposed_env.setdefault("PYTHONIOENCODING", "utf-8")
            exposed_env.setdefault("PYTHONUTF8", "1")
        except (AttributeError, ValueError) as exc:
            return SandboxResult(stderr="Invalid execution context", refusal_reason=str(exc))

        backend = self.active_backend()
        if backend == "wasm" or backend == "disabled" or (
            backend == "subprocess-host" and
            not getattr(self, "_allow_host_context_for_tests", False)
        ):
            return SandboxResult(stderr="Execution context requires an isolated Docker backend",
                                 refusal_reason="context_backend_unsupported")

        self._ensure_work_dir()
        snapshot = None
        context_dir = self.work_dir.parent / ".h595_context" / f"run-{secrets.token_hex(8)}"
        context_dir.mkdir(mode=0o700, parents=True)
        metadata_dir = context_dir / "metadata"
        metadata_dir.mkdir(mode=0o700, parents=True)
        metadata_file = metadata_dir / "result.json"
        keep_context = False
        try:
            if mode == "project" and context.get("project_root"):
                source_root = Path(context["project_root"]).expanduser().resolve()
                if (self.work_dir.resolve().is_relative_to(source_root) or
                        context_dir.resolve().is_relative_to(source_root)):
                    return SandboxResult(stderr="Project includes sandbox cache",
                                         refusal_reason="project_contains_sandbox_cache")
                snapshot = context_dir / "project"
                prepare_project(context["project_root"], snapshot, redact=context.get("redact"))
            stage = "/workspace" if backend == "docker" else str(self.work_dir)
            project_cwd = ("/project" if backend == "docker" else str(snapshot)) if snapshot else stage
            payload = {
                "code": code,
                "env": exposed_env,
                "context": {"mode": mode, "cwd": project_cwd, "staging_dir": stage,
                            "env": interpreter_env},
                "metadata_path": "/context/result.json" if backend == "docker" else str(metadata_file),
            }
            startup = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if len(startup) > 1_000_000:
                return SandboxResult(stderr="Execution context is too large",
                                     refusal_reason="context_too_large")
            bootstrap = self._context_bootstrap_source()
            if backend == "docker":
                mounts = [(str(snapshot), "/project")] if snapshot else []
                result = await self._run_docker(
                    ["python", f"/workspace/{filename}"], {filename: bootstrap},
                    writable_paths=writable_paths, readonly_mounts=mounts,
                    context_writable_mount=(str(metadata_dir), "/context"),
                    startup_data=startup, check_current=check_current,
                    context_run=True, sinks=sinks,
                )
            else:
                result = await self._execute_context_test_subprocess(
                    bootstrap, filename, startup, check_current, sinks=sinks,
                )
            result.execution_context = self._read_context_metadata(metadata_file)
            return result
        except ContextTeardownUnconfirmed:
            keep_context = True
            return SandboxResult(stderr="Execution context teardown unconfirmed",
                                 refusal_reason="context_teardown_unconfirmed")
        except ProjectSnapshotError as exc:
            return SandboxResult(stderr="Project projection refused",
                                 refusal_reason=str(exc))
        finally:
            if not keep_context:
                shutil.rmtree(context_dir, ignore_errors=True)

    @staticmethod
    def _read_context_metadata(path: Path) -> dict | None:
        """Read an untrusted, bounded informational sidecar without following links."""
        from .code_context import ProjectSnapshotError

        try:
            if os.name == "nt":
                import msvcrt

                from .code_context import _windows_project_handle

                root, root_name, close = _windows_project_handle(path.parent, directory=True)
                try:
                    handle, final, _ = _windows_project_handle(path)
                    if os.path.commonpath((root_name, final)) != root_name:
                        close(handle)
                        return None
                    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                finally:
                    close(root)
            else:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                metadata_stat = os.fstat(fd)
                if not stat.S_ISREG(metadata_stat.st_mode) or metadata_stat.st_size > 4096:
                    return None
                raw = os.read(fd, 4097)
            finally:
                os.close(fd)
            if len(raw) > 4096:
                return None
            value = json.loads(raw)
        except (OSError, UnicodeError, ValueError, TypeError, ProjectSnapshotError):
            return None
        if not isinstance(value, dict) or value.get("mode") not in ("project", "strict"):
            return None
        if any(not isinstance(value.get(key), str) or len(value[key]) > 2048 or
               not os.path.isabs(value[key]) for key in ("cwd", "python")):
            return None
        return {key: value[key] for key in ("mode", "cwd", "python")}

    async def _execute_python_file(self, code: str, filename: str,
                                   writable_paths: list[str | Path] | None = None,
                                   sinks=None) -> SandboxResult:
        if self._has_docker:
            return await self._execute_docker_python(
                code,
                filename,
                writable_paths=writable_paths,
                sinks=sinks,
            )
        if self.wasm_available():
            return await self._execute_wasm_python(code, filename, sinks=sinks)
        if not self.allow_subprocess:
            return SandboxResult(
                stderr="Code execution disabled: no Docker/WASM isolation and the host "
                       "fallback is off (allow_subprocess=False).",
                exit_code=-1,
            )
        return await self._execute_subprocess_python(code, filename, sinks=sinks)

    async def _execute_wasm_python(self, code: str, filename: str,
                                   sinks=None) -> SandboxResult:
        start = time.monotonic()
        self._ensure_work_dir()
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
                    self._read_output_capped(proc, sinks), timeout=self.timeout)
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
                    exit_code=-1, duration=time.monotonic() - start, timed_out=True,
                )
            except asyncio.CancelledError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
                raise
        except FileNotFoundError:
            logger.warning("wasmtime not found at execution — falling back")
            self._has_wasmtime = False
            if self.allow_subprocess:
                return await self._execute_subprocess_python(code, filename, sinks=sinks)
            return SandboxResult(
                stderr="WASM runtime unavailable and subprocess execution disabled",
                exit_code=-1, duration=time.monotonic() - start,
            )
        except Exception as e:
            return SandboxResult(stderr=str(e), exit_code=-1, duration=time.monotonic() - start)

    async def execute_shell(self, command: str) -> SandboxResult:
        if self._has_docker:
            return await self._execute_docker_shell(command)
        from .environments.consent_dispatch import consent_dispatch_scope_present
        from .environments.legacy_terminal_dispatch import legacy_terminal_scope_present
        from .environments.owner_once_dispatch import owner_once_scope_present

        if legacy_terminal_scope_present():
            return SandboxResult(stderr="Legacy terminal Docker backend unavailable", exit_code=-1)
        if owner_once_scope_present():
            return SandboxResult(stderr="Owner-once Docker backend unavailable", exit_code=-1)
        if consent_dispatch_scope_present():
            return SandboxResult(stderr="Consented Docker backend unavailable", exit_code=-1)
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
        sinks=None,
    ) -> SandboxResult:
        return await self._run_docker([
            "python", f"/workspace/{filename}",
        ], {filename: code}, writable_paths=writable_paths, sinks=sinks)

    async def _execute_docker_shell(self, command: str) -> SandboxResult:
        return await self._run_docker([
            "sh", "-c", command,
        ])

    async def _run_docker(
        self,
        cmd: list[str],
        files: dict[str, str] = None,
        writable_paths: list[str | Path] | None = None,
        sinks=None,
        readonly_mounts: list[tuple[str, str]] | None = None,
        context_writable_mount: tuple[str, str] | None = None,
        startup_data: bytes | None = None,
        check_current=None,
        context_run: bool = False,
    ) -> SandboxResult:
        start = time.monotonic()

        # Random suffix, not just a whole-second timestamp: two runs started in
        # the same second would otherwise collide on --name and the second
        # `docker run` would fail with a daemon name-conflict.
        container_name = f"cabinet-sandbox-{int(time.time())}-{secrets.token_hex(4)}"
        self._ensure_work_dir()
        workdir_path = str(self.work_dir)

        for fname, content in (files or {}).items():
            fpath = Path(workdir_path) / fname
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")

        docker_cmd = [
            "docker", "run", *(["-i"] if startup_data is not None else []), "--rm",
            "--name", container_name,
            "--network", "none",
            "--memory", f"{self.max_memory_mb}m",
            "--memory-swap", f"{self.max_memory_mb}m",
            "--cpus", "1",
            "--pids-limit", "50",
            "--read-only",
            *_bind_mount(workdir_path, "/workspace", readonly=True),
            *(item for source, target in (readonly_mounts or [])
              for item in _bind_mount(source, target, readonly=True)),
            *self._docker_writable_mount_args(writable_paths),
            *(_bind_mount(*context_writable_mount, readonly=False)
              if context_writable_mount is not None else []),
            "-w", "/workspace",
            self.docker_image,
        ] + cmd

        from .environments.consent_dispatch import physical_gate as consent_physical_gate

        if consent_physical_gate(self, backend="docker", argv=tuple(cmd), cwd="/workspace",
                                 timeout=self.timeout) is False:
            return SandboxResult(stderr="Consent dispatch unavailable", exit_code=-1,
                                 duration=time.monotonic() - start)
        from .environments.owner_once_dispatch import physical_gate

        if physical_gate(self, backend="docker", argv=tuple(cmd), cwd="/workspace",
                         timeout=self.timeout) is False:
            return SandboxResult(stderr="Owner-once dispatch unavailable", exit_code=-1,
                                 duration=time.monotonic() - start)
        from .environments.legacy_terminal_dispatch import physical_gate as legacy_terminal_gate

        if legacy_terminal_gate(self, backend="docker", argv=tuple(cmd), cwd="/workspace",
                                timeout=self.timeout) is False:
            return SandboxResult(stderr="Legacy terminal dispatch unavailable", exit_code=-1,
                                 duration=time.monotonic() - start)

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                **({"stdin": asyncio.subprocess.PIPE} if startup_data is not None else {}),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                if startup_data is not None:
                    refusal = self._context_refusal(check_current)
                    if refusal:
                        await self._stop_docker_context(proc, container_name)
                        return SandboxResult(stderr="Execution context is no longer current",
                                             refusal_reason=refusal)
                    try:
                        async def send_startup():
                            proc.stdin.write(startup_data)
                            await proc.stdin.drain()
                            proc.stdin.close()
                            await proc.stdin.wait_closed()

                        await asyncio.wait_for(send_startup(), timeout=max(
                            0.001, self.timeout - (time.monotonic() - start)))
                    except asyncio.TimeoutError:
                        raise
                    except asyncio.CancelledError:
                        await self._stop_docker_context(proc, container_name)
                        raise
                    except Exception:
                        await self._stop_docker_context(proc, container_name)
                        return SandboxResult(stderr="Execution context startup failed",
                                             refusal_reason="context_startup_failed")
                if asyncio.current_task().cancelling():
                    raise asyncio.CancelledError
                out_text, err_text = await asyncio.wait_for(
                    self._read_output_capped(proc, sinks),
                    timeout=(max(0.001, self.timeout - (time.monotonic() - start))
                             if startup_data is not None else self.timeout),
                )
                duration = time.monotonic() - start
                return SandboxResult(
                    stdout=out_text,
                    stderr=err_text,
                    exit_code=proc.returncode or 0,
                    duration=duration,
                )
            except asyncio.TimeoutError:
                if context_run:
                    await self._stop_docker_context(proc, container_name)
                    return SandboxResult(stderr=f"Execution timed out after {self.timeout}s",
                                         exit_code=-1, duration=time.monotonic() - start,
                                         timed_out=True)
                proc.kill()
                await proc.wait()
                # Killing the docker *client* detaches it; the daemon-side
                # container keeps running (burning a full CPU under --cpus 1)
                # until it exits on its own. Kill the container by name too, or
                # a `while True` sandbox survives its own timeout indefinitely.
                with contextlib.suppress(Exception):
                    killer = await asyncio.create_subprocess_exec(
                        "docker", "kill", container_name,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await killer.wait()
                duration = time.monotonic() - start
                logger.warning(f"Docker sandbox timed out after {self.timeout}s")
                return SandboxResult(
                    stderr=f"Execution timed out after {self.timeout}s",
                    exit_code=-1,
                    duration=duration, timed_out=True,
                )
            except asyncio.CancelledError:
                if context_run:
                    await self._stop_docker_context(proc, container_name)
                    raise
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
            if context_run:
                if proc is not None:
                    await self._stop_docker_context(proc, container_name)
                return SandboxResult(stderr="Context Docker backend unavailable",
                                     exit_code=-1, refusal_reason="context_backend_unsupported")
            from .environments.consent_dispatch import consent_dispatch_scope_present
            from .environments.legacy_terminal_dispatch import legacy_terminal_scope_present
            from .environments.owner_once_dispatch import owner_once_scope_present

            if legacy_terminal_scope_present():
                return SandboxResult(stderr="Legacy terminal Docker backend unavailable",
                                     exit_code=-1, duration=time.monotonic() - start)
            if owner_once_scope_present():
                return SandboxResult(stderr="Owner-once Docker backend unavailable",
                                     exit_code=-1, duration=time.monotonic() - start)
            if consent_dispatch_scope_present():
                return SandboxResult(stderr="Consented Docker backend unavailable",
                                     exit_code=-1, duration=time.monotonic() - start)
            if not self.allow_subprocess:
                return SandboxResult(
                    stderr="Code execution disabled: Docker not available and the host "
                           "fallback is off (allow_subprocess=False).",
                    exit_code=-1,
                )
            # Route the host fallback from the actual request, not a hardcoded
            # script.py: a shell run has files=None (would AttributeError) and a
            # python run may use any filename (script.py → empty-script false success).
            if cmd[:2] == ["sh", "-c"] and len(cmd) >= 3:
                return await self._execute_subprocess_shell(cmd[2], sinks=sinks)
            if files:
                fname, code = next(iter(files.items()))
                return await self._execute_subprocess_python(code, fname, sinks=sinks)
            return SandboxResult(
                stderr="Code execution disabled: Docker not available and no runnable "
                       "input to fall back to.",
                exit_code=-1,
            )
        except ContextTeardownUnconfirmed:
            raise
        except Exception as e:
            if context_run and proc is not None:
                await self._stop_docker_context(proc, container_name)
            duration = time.monotonic() - start
            return SandboxResult(
                stderr="Execution context backend failed" if context_run else str(e),
                exit_code=-1, duration=duration,
                refusal_reason="context_backend_failed" if context_run else "",
            )

    @staticmethod
    async def _stop_docker_context(proc, container_name: str, *, timeout: float = 5) -> None:
        """Bound teardown and prove the named container is no longer running."""
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout)
        except (OSError, asyncio.TimeoutError) as exc:
            raise ContextTeardownUnconfirmed from exc

        async def docker(*args):
            cli = await asyncio.wait_for(asyncio.create_subprocess_exec(
                "docker", *args, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL), timeout)
            try:
                output, _ = await asyncio.wait_for(cli.communicate(), timeout)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    cli.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(cli.wait(), timeout)
                raise
            return cli.returncode, output

        try:
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                await docker("kill", container_name)
            status, running = await docker(
                "ps", "--filter", f"name=^/{container_name}$", "--format", "{{.ID}}")
            if status != 0 or running.strip():
                raise ContextTeardownUnconfirmed
        except (OSError, asyncio.TimeoutError) as exc:
            raise ContextTeardownUnconfirmed from exc

    async def _execute_context_test_subprocess(self, bootstrap: str, filename: str,
                                               startup: bytes, check_current,
                                               *, sinks=None) -> SandboxResult:
        """Test-only host worker; production context never routes to this backend."""
        start = time.monotonic()
        fpath = self.work_dir / filename
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(bootstrap, encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(fpath), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self.work_dir), env={"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"},
            start_new_session=os.name != "nt",
        )
        try:
            refusal = self._context_refusal(check_current)
            if refusal:
                await self._stop_host_context(proc)
                return SandboxResult(stderr="Execution context is no longer current",
                                     refusal_reason=refusal)

            async def complete() -> tuple[str, str]:
                proc.stdin.write(startup)
                await proc.stdin.drain()
                proc.stdin.close()
                await proc.stdin.wait_closed()
                return await self._read_output_capped(proc, sinks)

            try:
                out_text, err_text = await asyncio.wait_for(
                    complete(), timeout=self.timeout,
                )
            except asyncio.TimeoutError:
                await self._stop_host_context(proc)
                return SandboxResult(stderr=f"Execution timed out after {self.timeout}s",
                                     duration=time.monotonic() - start, timed_out=True)
            return SandboxResult(stdout=out_text, stderr=err_text,
                                 exit_code=proc.returncode or 0,
                                 duration=time.monotonic() - start)
        except asyncio.CancelledError:
            await self._stop_host_context(proc)
            raise
        except Exception:
            await self._stop_host_context(proc)
            return SandboxResult(stderr="Execution context worker failed",
                                 refusal_reason="context_worker_failed")

    @staticmethod
    async def _stop_host_context(proc) -> None:
        """Test-only host worker and its selected-interpreter descendant form one group."""
        if os.name == "nt" and getattr(proc, "pid", None):
            with contextlib.suppress(OSError):
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(proc.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
                await asyncio.wait_for(killer.wait(), 5)
        elif getattr(proc, "pid", None):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()

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
            args.extend(_bind_mount(str(host_path), target, readonly=False))

        return args

    async def _execute_subprocess_python(self, code: str, filename: str,
                                         sinks=None) -> SandboxResult:
        logger.warning("Sandbox: running Python on the HOST with no Docker isolation "
                       "(allow_subprocess=True) — do not enable in production (HF-6)")
        start = time.monotonic()
        self._ensure_work_dir()
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
                    self._read_output_capped(proc, sinks), timeout=self.timeout
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
                    duration=duration, timed_out=True,
                )
            except asyncio.CancelledError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
                raise
        except Exception as e:
            duration = time.monotonic() - start
            return SandboxResult(stderr=str(e), exit_code=-1, duration=duration)

    async def _execute_subprocess_shell(self, command: str, sinks=None) -> SandboxResult:
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
                    self._read_output_capped(proc, sinks), timeout=self.timeout
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
                    duration=time.monotonic() - start, timed_out=True,
                )
        except Exception as e:
            return SandboxResult(stderr=str(e), exit_code=-1, duration=time.monotonic() - start)
