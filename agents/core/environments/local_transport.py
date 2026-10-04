"""Local host terminal transport: argv only, cwd-jailed, capped, killable.

The host half of the governed terminal (GAP-9 → owner goal "use the computer as
a tool"). It executes exactly one argv on the machine Nerva runs on and nothing
else: no shell (never ``shell=True``, never ``sh -c``), no pipes, no globbing,
no environment secrets (``prepare_python_child_env`` scrubs them), no output
larger than the cap in host memory (``read_capped_stream`` keeps head+tail),
and no process that outlives its timeout (kill, then reap).

Layers the transport does NOT own, on purpose: the hardline denylist and the
``terminal.exec`` contract live in ``terminal_contract.py`` and are consulted
by the runner before this class is reached — but the transport re-checks the
hardline itself so a direct caller can never skip it.

Default-off. ``from_env()`` reads:

- ``JARVIS_TERMINAL_LOCAL_ROOTS`` — comma-separated cwd roots the child may run
  in (default: ``data_path("workspace")``).
- ``JARVIS_TERMINAL_TIMEOUT_S`` — default timeout in seconds (60, capped at
  ``MAX_TIMEOUT_S``).

The enabling flag ``JARVIS_TERMINAL_LOCAL_HOST`` is checked by the runner, not
here: a transport object existing is not a permission to run.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.core.env_config import env_int, env_list

from .output_limits import read_capped_stream, render_capped
from .terminal_contract import (
    DEFAULT_TIMEOUT_S,
    MAX_ARG_CHARS,
    MAX_ARGV_ITEMS,
    MAX_TIMEOUT_S,
    argv_fingerprint,
    hardline_match,
)

DEFAULT_MAX_OUTPUT_BYTES = 16_000
_MAX_OUTPUT_CEILING = 1_000_000
_CHECKPOINT_CANCEL_OBSERVE_S = 0.25

Spawn = Callable[..., Awaitable[Any]]


def _consume_background(task: asyncio.Task) -> None:
    """Observe a detached cleanup result even if its original caller is gone."""
    with contextlib.suppress(BaseException):
        task.result()


@dataclass(frozen=True)
class TerminalCheckpointIntent:
    """Runner-created observation request; it confers no execution authority."""

    history: Any
    argv: tuple[str, ...]
    cwd: str
    timeout: int
    current: Callable[[], bool]
    source_kind: str
    source_key: str
    target: str


def destructive_argv(argv: Sequence[str]) -> bool:
    """Recognize direct argv operations that can replace or remove local files."""
    if not argv:
        return False
    name = Path(argv[0]).name
    if name in {"rm", "rmdir", "mv", "cp", "install", "truncate", "dd", "shred"}:
        return True
    if name == "sed" and any(arg == "-i" or arg.startswith("-i") for arg in argv[1:]):
        return True
    if name == "git" and len(argv) > 1:
        return argv[1] in {"checkout", "restore", "reset", "clean"}
    return False


def default_roots() -> list[str]:
    """Roots from the env, else the workspace under the runtime-data root."""
    configured = env_list("JARVIS_TERMINAL_LOCAL_ROOTS")
    if configured:
        return configured
    from agents.core.paths import data_path

    return [str(data_path("workspace"))]


def default_timeout() -> int:
    return min(env_int("JARVIS_TERMINAL_TIMEOUT_S", DEFAULT_TIMEOUT_S, minimum=1), MAX_TIMEOUT_S)


class LocalHostTransport:
    """Run one argv on the host inside a cwd jail with bounded time and output."""

    backend = "local"

    def __init__(
        self,
        roots: Sequence[str | Path],
        *,
        default_timeout: int = DEFAULT_TIMEOUT_S,
        max_timeout: int = MAX_TIMEOUT_S,
        max_output: int = DEFAULT_MAX_OUTPUT_BYTES,
        spawn: Spawn | None = None,
        env_source: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        if isinstance(roots, (str, bytes, Path)) or not roots:
            raise ValueError("roots must be a non-empty sequence of directories")
        resolved: list[Path] = []
        for root in roots:
            text = str(root or "").strip()
            if not text:
                raise ValueError("roots must not contain blank entries")
            resolved.append(Path(text).expanduser().resolve())
        for label, value in (("default_timeout", default_timeout), ("max_timeout", max_timeout)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{label} must be a positive integer")
        if max_timeout > MAX_TIMEOUT_S:
            raise ValueError(f"max_timeout must not exceed {MAX_TIMEOUT_S}")
        if default_timeout > max_timeout:
            raise ValueError("default_timeout must not exceed max_timeout")
        if isinstance(max_output, bool) or not isinstance(max_output, int) or not (
            8 <= max_output <= _MAX_OUTPUT_CEILING
        ):
            raise ValueError("max_output must be between 8 and 1,000,000 bytes")
        self._roots = tuple(resolved)
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
        self.max_output = max_output
        self._spawn = spawn or asyncio.create_subprocess_exec
        self._env_source = env_source or (lambda: dict(os.environ))

    @classmethod
    def from_env(cls, **kwargs: Any) -> LocalHostTransport:
        """Build from ``JARVIS_TERMINAL_LOCAL_ROOTS`` / ``JARVIS_TERMINAL_TIMEOUT_S``."""
        roots = kwargs.pop("roots", None) or default_roots()
        if not env_list("JARVIS_TERMINAL_LOCAL_ROOTS"):
            # The default workspace lives under the runtime-data root; create it
            # so the very first owner command has a jail to run in.
            with contextlib.suppress(OSError):
                Path(roots[0]).mkdir(parents=True, exist_ok=True)
        kwargs.setdefault("default_timeout", default_timeout())
        return cls(roots, **kwargs)

    @property
    def roots(self) -> tuple[str, ...]:
        return tuple(str(root) for root in self._roots)

    def resolve_cwd(self, cwd: str | Path | None) -> Path | None:
        """Return the resolved cwd when it sits inside a root, else ``None``."""
        candidate = Path(str(cwd)).expanduser() if cwd else self._roots[0]
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            return None
        for root in self._roots:
            if resolved == root or root in resolved.parents:
                return resolved
        return None

    @staticmethod
    def validate_argv(argv: Any) -> str | None:
        if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence):
            return "invalid_argv"
        items = list(argv)
        if not items or len(items) > MAX_ARGV_ITEMS:
            return "invalid_argv"
        for item in items:
            if not isinstance(item, str) or item == "" or len(item) > MAX_ARG_CHARS:
                return "invalid_argv"
            if "\x00" in item:
                return "invalid_argv"
        return None

    def bound_timeout(self, timeout: int | None) -> int | None:
        if timeout is None:
            return self.default_timeout
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            return None
        if timeout > self.max_timeout:
            return None
        return timeout

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        timeout: int | None = None,
        max_output: int | None = None,
        checkpoint_intent: TerminalCheckpointIntent | None = None,
    ) -> dict[str, Any]:
        """Execute ``argv`` verbatim; every refusal is a named reason, never an exception."""
        invalid = self.validate_argv(argv)
        if invalid is not None:
            return {"ok": False, "reason": invalid}
        argv_list = [str(item) for item in argv]
        hardline = hardline_match(argv_list)
        if hardline is not None:
            return {"ok": False, "reason": f"hardline_denied:{hardline}"}
        bounded = self.bound_timeout(timeout)
        if bounded is None:
            return {"ok": False, "reason": "invalid_timeout"}
        cap = self.max_output if max_output is None else max_output
        if isinstance(cap, bool) or not isinstance(cap, int) or not (8 <= cap <= self.max_output):
            return {"ok": False, "reason": "invalid_max_output"}
        workdir = self.resolve_cwd(cwd)
        if workdir is None:
            return {"ok": False, "reason": "cwd_outside_roots"}
        if not workdir.is_dir():
            return {"ok": False, "reason": "cwd_missing"}

        from agents.core.environments import prepare_python_child_env

        env = prepare_python_child_env(self._env_source())
        fingerprint = argv_fingerprint(argv_list)
        start = time.monotonic()
        from .consent_dispatch import physical_gate as consent_physical_gate
        from .owner_once_dispatch import physical_gate
        checkpoint = None
        def same_checkpoint_root() -> bool:
            if checkpoint is None:
                return True
            try:
                info = os.stat(workdir, follow_symlinks=False)
                return (info.st_dev, info.st_ino) == checkpoint["root_identity"]
            except OSError:
                return False

        if checkpoint_intent is not None:
            intent = checkpoint_intent
            if (intent.argv != tuple(argv_list) or intent.cwd != str(workdir)
                    or intent.timeout != bounded or not intent.current()):
                return {"ok": False, "reason": "terminal_checkpoint_intent_changed",
                        "argv_sha256": fingerprint}
            abandoned = threading.Event()
            capture_task = asyncio.create_task(asyncio.to_thread(
                intent.history.begin_scope, workdir,
                source_kind=intent.source_kind, source_key=intent.source_key,
                target=intent.target, argv_sha256=fingerprint,
                cancelled=abandoned,
            ))
            try:
                checkpoint = await asyncio.shield(capture_task)
            except asyncio.CancelledError:
                abandoned.set()

                async def close_late_capture() -> None:
                    try:
                        captured = await capture_task
                    except BaseException:
                        # begin_scope durably marks a failed pre-capture itself.
                        return
                    try:
                        await asyncio.to_thread(
                            intent.history.mark_scope_no_process, captured["id"],
                            reason="capture_cancelled", run_id=captured["run_id"],
                        )
                    except Exception:
                        with contextlib.suppress(Exception):
                            await asyncio.to_thread(
                                intent.history.mark_scope_incomplete, captured["id"],
                                reason="late_capture_close_failed",
                                run_id=captured["run_id"],
                            )

                observer = asyncio.create_task(close_late_capture())
                observer.add_done_callback(_consume_background)
                await asyncio.wait({observer}, timeout=_CHECKPOINT_CANCEL_OBSERVE_S)
                raise
            except Exception:
                return {"ok": False, "reason": "terminal_checkpoint_unavailable",
                        "argv_sha256": fingerprint}
            if checkpoint["status"] not in {"ready", "running"}:
                return {"ok": False, "reason": "terminal_checkpoint_unavailable",
                        "argv_sha256": fingerprint}
            # Capture can be slow; all physical authority fences must still hold.
            if not intent.current() or not same_checkpoint_root():
                await asyncio.to_thread(intent.history.mark_scope_no_process,
                                        checkpoint["id"], reason="dispatch_revoked",
                                        run_id=checkpoint["run_id"])
                return {"ok": False, "reason": "terminal_dispatch_revoked",
                        "argv_sha256": fingerprint,
                        "checkpoint": {"id": checkpoint["id"], "status": "no_process"}}

        if consent_physical_gate(self, backend="local", argv=tuple(argv_list),
                                 cwd=str(workdir), timeout=bounded) is False:
            if checkpoint is not None:
                await asyncio.to_thread(checkpoint_intent.history.mark_scope_no_process,
                                        checkpoint["id"], reason="consent_dispatch_unavailable",
                                        run_id=checkpoint["run_id"])
            return {"ok": False, "reason": "consent_dispatch_unavailable",
                    "argv_sha256": fingerprint}
        if physical_gate(self, backend="local", argv=tuple(argv_list),
                         cwd=str(workdir), timeout=bounded) is False:
            if checkpoint is not None:
                await asyncio.to_thread(checkpoint_intent.history.mark_scope_no_process,
                                        checkpoint["id"], reason="owner_once_dispatch_unavailable",
                                        run_id=checkpoint["run_id"])
            return {"ok": False, "reason": "owner_once_dispatch_unavailable",
                    "argv_sha256": fingerprint}
        if not same_checkpoint_root():
            await asyncio.to_thread(checkpoint_intent.history.mark_scope_no_process,
                                    checkpoint["id"], reason="root_changed_before_spawn",
                                    run_id=checkpoint["run_id"])
            return {"ok": False, "reason": "terminal_checkpoint_root_changed",
                    "argv_sha256": fingerprint}

        async def finalize(*, reaped: bool) -> dict | None:
            if checkpoint is None or checkpoint_intent is None:
                return None

            async def settle_postscan() -> dict:
                try:
                    return await asyncio.to_thread(
                        checkpoint_intent.history.finish_scope, checkpoint["id"],
                        reaped=reaped, run_id=checkpoint["run_id"],
                    )
                except Exception:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(
                            checkpoint_intent.history.mark_scope_incomplete,
                            checkpoint["id"], reason="postscan_failed",
                            run_id=checkpoint["run_id"],
                        )
                    return {"id": checkpoint["id"], "status": "incomplete",
                            "reason": "postscan_failed"}

            job = asyncio.create_task(settle_postscan())
            job.add_done_callback(_consume_background)
            if asyncio.current_task().cancelling():
                # Cancellation may already have been caught while reading the
                # child. Shield alone would then wait indefinitely for postscan.
                await asyncio.wait({job}, timeout=_CHECKPOINT_CANCEL_OBSERVE_S)
                return job.result() if job.done() else None
            try:
                return await asyncio.shield(job)
            except asyncio.CancelledError:
                # The process is already exited/reaped. The postscan continues
                # in the observer without holding this cancellation indefinitely.
                await asyncio.wait({job}, timeout=_CHECKPOINT_CANCEL_OBSERVE_S)
                raise

        try:
            proc = await self._spawn(
                *argv_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=str(workdir),
                env=env,
            )
        except FileNotFoundError:
            if checkpoint is not None:
                await asyncio.to_thread(checkpoint_intent.history.mark_scope_no_process,
                                        checkpoint["id"], reason="executable_not_found",
                                        run_id=checkpoint["run_id"])
            return {"ok": False, "reason": "executable_not_found", "argv_sha256": fingerprint}
        except PermissionError:
            if checkpoint is not None:
                await asyncio.to_thread(checkpoint_intent.history.mark_scope_no_process,
                                        checkpoint["id"], reason="executable_not_permitted",
                                        run_id=checkpoint["run_id"])
            return {"ok": False, "reason": "executable_not_permitted", "argv_sha256": fingerprint}
        except OSError:
            if checkpoint is not None:
                await asyncio.to_thread(checkpoint_intent.history.mark_scope_no_process,
                                        checkpoint["id"], reason="spawn_failed",
                                        run_id=checkpoint["run_id"])
            return {"ok": False, "reason": "spawn_failed", "argv_sha256": fingerprint}
        except asyncio.CancelledError:
            if checkpoint is not None:
                await asyncio.to_thread(checkpoint_intent.history.mark_scope_incomplete,
                                        checkpoint["id"], reason="spawn_cancelled_uncertain",
                                        run_id=checkpoint["run_id"])
            raise

        if asyncio.current_task().cancelling():
            reaped = await self._kill(proc)
            await finalize(reaped=reaped)
            raise asyncio.CancelledError

        from .output_capture import OutputCapture
        capture = OutputCapture()
        try:
            (out_head, out_tail, out_total), (err_head, err_tail, err_total) = await asyncio.wait_for(
                asyncio.gather(
                    read_capped_stream(proc.stdout, max_content_bytes=cap, sink=capture.feed),
                    read_capped_stream(proc.stderr, max_content_bytes=cap),
                ),
                timeout=bounded,
            )
            await asyncio.wait_for(proc.wait(), timeout=bounded)
        except TimeoutError:
            reaped = await self._kill(proc)
            terminal_checkpoint = await finalize(reaped=reaped)
            return {
                "ok": False,
                "reason": "timeout",
                "exit_code": -1,
                "duration": round(time.monotonic() - start, 3),
                "timeout": bounded,
                "argv_sha256": fingerprint,
                **({"checkpoint": terminal_checkpoint} if terminal_checkpoint else {}),
            }
        except asyncio.CancelledError:
            reaped = await self._kill(proc)
            await finalize(reaped=reaped)
            raise
        terminal_checkpoint = await finalize(reaped=True)
        stdout = render_capped(out_head, out_tail, out_total, max_content_bytes=cap, label="STDOUT")
        stderr = render_capped(err_head, err_tail, err_total, max_content_bytes=cap, label="STDERR")
        exit_code = proc.returncode if isinstance(proc.returncode, int) else -1
        return {
            "ok": exit_code == 0,
            "exit_code": exit_code,
            "stdout": stdout.text,
            "stdout_capture": capture.seal(cap, successful=exit_code == 0),
            "stderr": stderr.text,
            "truncated": bool(stdout.truncated or stderr.truncated),
            "duration": round(time.monotonic() - start, 3),
            "cwd": str(workdir),
            "argv_sha256": fingerprint,
            **({"checkpoint": terminal_checkpoint} if terminal_checkpoint else {}),
        }

    @staticmethod
    async def _kill(proc: Any) -> bool:
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
            return True
        except (TimeoutError, OSError):
            return False


__all__ = ["DEFAULT_MAX_OUTPUT_BYTES", "LocalHostTransport", "default_roots", "default_timeout"]
