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
import time
from collections.abc import Awaitable, Callable, Sequence
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

Spawn = Callable[..., Awaitable[Any]]


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
            return {"ok": False, "reason": "executable_not_found", "argv_sha256": fingerprint}
        except PermissionError:
            return {"ok": False, "reason": "executable_not_permitted", "argv_sha256": fingerprint}
        except OSError:
            return {"ok": False, "reason": "spawn_failed", "argv_sha256": fingerprint}

        try:
            (out_head, out_tail, out_total), (err_head, err_tail, err_total) = await asyncio.wait_for(
                asyncio.gather(
                    read_capped_stream(proc.stdout, max_content_bytes=cap),
                    read_capped_stream(proc.stderr, max_content_bytes=cap),
                ),
                timeout=bounded,
            )
            await asyncio.wait_for(proc.wait(), timeout=bounded)
        except TimeoutError:
            await self._kill(proc)
            return {
                "ok": False,
                "reason": "timeout",
                "exit_code": -1,
                "duration": round(time.monotonic() - start, 3),
                "timeout": bounded,
                "argv_sha256": fingerprint,
            }
        stdout = render_capped(out_head, out_tail, out_total, max_content_bytes=cap, label="STDOUT")
        stderr = render_capped(err_head, err_tail, err_total, max_content_bytes=cap, label="STDERR")
        exit_code = proc.returncode if isinstance(proc.returncode, int) else -1
        return {
            "ok": exit_code == 0,
            "exit_code": exit_code,
            "stdout": stdout.text,
            "stderr": stderr.text,
            "truncated": bool(stdout.truncated or stderr.truncated),
            "duration": round(time.monotonic() - start, 3),
            "cwd": str(workdir),
            "argv_sha256": fingerprint,
        }

    @staticmethod
    async def _kill(proc: Any) -> None:
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            return
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(proc.wait(), timeout=5)


__all__ = ["DEFAULT_MAX_OUTPUT_BYTES", "LocalHostTransport", "default_roots", "default_timeout"]
