"""Opt-in PDF/DOCX process containment; no shell, pickle, or parser on the hub loop.

The child gets only document bytes, kind and deadline. Its temporary files belong
to a parent-owned directory, so even a hard kill cleans up unpacked Office parts.
This is resource containment, not a filesystem/network sandbox.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.core.workspace.extract import Extracted

MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
_SLOTS = threading.BoundedSemaphore(2)  # shared across request event loops
_REPO = Path(__file__).resolve().parents[3]


def _apply_memory_limit() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("wall_time", "memory_unavailable")
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    ceiling = min(hard, MEMORY_LIMIT_BYTES) if hard != resource.RLIM_INFINITY else MEMORY_LIMIT_BYTES
    resource.setrlimit(resource.RLIMIT_AS, (
        min(soft, ceiling) if soft != resource.RLIM_INFINITY else ceiling, ceiling))
    return ("wall_time", "address_space")


def _worker(argv: list[str] | None = None) -> None:
    # Apply the cap before importing pypdf or reading the upload. Never import the hub.
    limits = _apply_memory_limit()
    from agents.core.workspace.extract import ExtractionError, extract_bytes

    kind, seconds = (sys.argv[1:] if argv is None else argv)[:2]
    try:
        result = extract_bytes(sys.stdin.buffer.read(), kind, timeout=float(seconds))
        payload = {"segments": [[s.page, s.text] for s in result.segments],
                   "page_count": result.page_count, "limits": limits}
    except ExtractionError as exc:
        payload = {"error": exc.code, "page_count": exc.page_count}
    except MemoryError:
        payload = {"error": "too_much_text", "page_count": None}
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))


async def _reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()  # SIGKILL on POSIX, TerminateProcess on Windows
    await process.communicate()  # drain pipes as well as reaping; wait() alone can block


async def extract_in_child(data: bytes, kind: str, *, timeout: float) -> Extracted:
    from agents.core.workspace.extract import ERROR_CODES, Extracted, ExtractionError, Segment

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    acquired = False
    process = None
    launch = None
    try:
        async with asyncio.timeout_at(deadline):
            while not (acquired := _SLOTS.acquire(blocking=False)):
                await asyncio.sleep(0.01)
            with tempfile.TemporaryDirectory(prefix="nerva-ws-extract-") as scratch:
                try:
                    env = dict(os.environ, TMPDIR=scratch, TEMP=scratch, TMP=scratch)
                    command = ([sys.executable, "--nerva-workspace-extract-worker"]
                               if getattr(sys, "frozen", False) else
                               [sys.executable, "-m", "agents.core.workspace.extract_process"])
                    launch = asyncio.create_task(asyncio.create_subprocess_exec(
                        *command,
                        kind, str(max(0.0, deadline - loop.time())), cwd=_REPO, env=env,
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL))
                    # Cancellation during launch must still obtain and reap the child.
                    process = await asyncio.shield(launch)
                    output, _ = await process.communicate(data)
                    if process.returncode != 0:
                        raise ExtractionError("invalid_file", "extraction child failed")
                    try:
                        payload = json.loads(output)
                        if "error" in payload:
                            code = payload["error"]
                            raise ExtractionError(code if code in ERROR_CODES else "invalid_file",
                                                  "child refused extraction",
                                                  page_count=payload.get("page_count"))
                        return Extracted(tuple(Segment(*s) for s in payload["segments"]),
                                         payload["page_count"], tuple(payload["limits"]))
                    except (ValueError, KeyError, TypeError) as exc:
                        raise ExtractionError("invalid_file", "invalid extraction result") from exc
                finally:
                    async def cleanup():
                        child = process if process is not None else await launch if launch else None
                        if child is not None:
                            await _reap(child)

                    cleanup_task = asyncio.create_task(cleanup())
                    cancelled = False
                    # Repeated cancellations cannot release the slot or scratch files early.
                    while not cleanup_task.done():
                        try:
                            await asyncio.shield(cleanup_task)
                        except asyncio.CancelledError:
                            cancelled = True
                    cleanup_task.result()
                    if cancelled:
                        raise asyncio.CancelledError
    except TimeoutError as exc:
        memory = "unavailable (Windows)" if sys.platform == "win32" else "512 MiB RLIMIT_AS"
        raise ExtractionError("timeout", f"no result within {timeout:g} s; memory={memory}") from exc
    except OSError as exc:
        raise ExtractionError("invalid_file", "extraction child unavailable") from exc
    finally:
        if acquired:
            _SLOTS.release()


if __name__ == "__main__":
    _worker()
