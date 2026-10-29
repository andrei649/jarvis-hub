"""Opt-in PDF/DOCX process containment; no shell, pickle, or parser on the hub loop.

The child gets only document bytes, kind and deadline. Its temporary files belong
to a parent-owned directory, so even a hard kill cleans up unpacked Office parts.
This is resource containment, not a filesystem/network sandbox.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import signal

# Fixed-argv owned extraction child and bounded system ps sampler only.
import subprocess  # nosec B404
import sys
import tempfile
import threading
from contextlib import nullcontext, suppress
from pathlib import Path
from typing import TYPE_CHECKING

from agents.core.env_config import env_flag

if TYPE_CHECKING:
    from agents.core.workspace.extract import Extracted

MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
RSS_POLL_SECONDS = 0.1
_SLOTS = threading.BoundedSemaphore(2)  # shared across request event loops
_REPO = Path(__file__).resolve().parents[3]
_PS_BINARIES = ('/bin/ps', '/usr/bin/ps') if sys.platform == 'darwin' else ('/usr/bin/ps', '/bin/ps')
# 10 million permitted Unicode codepoints can expand to 120 MiB of ASCII JSON
# when every codepoint needs a surrogate-pair escape.
_MAX_FRAME_BYTES = 128 * 1024 * 1024
# Native Windows acceptance (Job atomicity, IOCP pipes and real OCR) has not
# run. This is an internal source gate, deliberately not an environment flag.
_WINDOWS_OCR_NATIVE_ACCEPTED = False


def _bounded_ocr_page_deadline(raw: object, *, now: float, document_deadline: float) -> float:
    """The parent owns the page cap; a child frame may only shorten it."""
    from agents.core.workspace.extract import OCR_PAGE_TIMEOUT_SECONDS

    if type(raw) not in (int, float):
        raise ValueError('invalid OCR page deadline')
    try:
        child_deadline = float(raw)
    except OverflowError as exc:
        raise ValueError('invalid OCR page deadline') from exc
    if not math.isfinite(child_deadline):
        raise ValueError('invalid OCR page deadline')
    return min(document_deadline, now + OCR_PAGE_TIMEOUT_SECONDS, child_deadline)


def _apply_memory_limit() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("wall_time", "memory_unavailable")
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    ceiling = min(hard, MEMORY_LIMIT_BYTES) if hard != resource.RLIM_INFINITY else MEMORY_LIMIT_BYTES
    try:
        resource.setrlimit(resource.RLIMIT_AS, (
            min(soft, ceiling) if soft != resource.RLIM_INFINITY else ceiling, ceiling))
    except (OSError, ValueError):
        # macOS can reject RLIMIT_AS even when getrlimit reports infinity.
        # The parent samples RSS there. Other POSIX failures are a refusal.
        if sys.platform != "darwin":
            raise
        return ("wall_time", "memory_unavailable")
    return ("wall_time", "address_space")


def _session_members(sid: int) -> list[tuple[int, int, int]] | None:
    """Return (pid, pgid, RSS bytes) for the child's isolated POSIX session.

    Checking each live PID with the kernel avoids identifying work by process name
    or killing a recycled page group from an unrelated session.
    """
    try:
        ps = next((path for path in _PS_BINARIES if os.path.isfile(path)
                   and os.access(path, os.X_OK)), None)
        if ps is None:
            return None
        # Fixed absolute system executable and option-only argv; no shell.
        result = subprocess.run(  # nosec B603
            [ps, "-A", "-o", "pid=,rss="], capture_output=True,
            text=True, timeout=1, check=False, shell=False)
        if result.returncode != 0:
            return None
        members = []
        for line in result.stdout.splitlines():
            pid_text, rss_text = line.split()
            pid = int(pid_text)
            try:
                if os.getsid(pid) == sid:
                    members.append((pid, os.getpgid(pid), int(rss_text) * 1024))
            except (ProcessLookupError, PermissionError):
                continue
        return members
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _kernel_session_members(sid: int) -> list[tuple[int, int, int]] | None:
    """Enumerate live session members without ps when process listing is unavailable.

    This is for termination only; RSS still comes from the regular sampler.
    libproc supplies PIDs on macOS and /proc supplies them on Linux. Each PID is
    checked against the kernel's current session and group before use.
    """
    try:
        if sys.platform == "darwin":
            import ctypes

            list_pids = ctypes.CDLL("/usr/lib/libproc.dylib").proc_listallpids
            list_pids.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
            list_pids.restype = ctypes.c_int
            count = list_pids(None, 0)
            if count <= 0:
                return None
            for _ in range(3):
                capacity = count + 256
                buffer = (ctypes.c_int * capacity)()
                found = list_pids(buffer, ctypes.sizeof(buffer))
                if found <= 0:
                    return None
                if found < capacity:
                    pids = buffer[:found]
                    break
                count = found
            else:
                return None
        elif sys.platform.startswith("linux"):
            pids = [int(entry) for entry in os.listdir("/proc") if entry.isdigit()]
        else:
            return None
        members = []
        for pid in pids:
            try:
                if os.getsid(pid) == sid:
                    members.append((pid, os.getpgid(pid), 0))
            except (ProcessLookupError, PermissionError):
                continue
        return members
    except (OSError, ValueError):
        return None


def _cleanup_members(sid: int) -> list[tuple[int, int, int]]:
    members = _session_members(sid)
    if members is None:
        members = _kernel_session_members(sid)
    if members is None:
        raise OSError("cannot verify extraction session ownership")
    return members


def _kill_verified_groups(sid: int, members: list[tuple[int, int, int]]) -> None:
    """Recheck a live member immediately before signaling its owned group."""
    for pgid in {group for _, group, _ in members}:
        for pid, group, _ in members:
            if group != pgid:
                continue
            try:
                if os.getsid(pid) == sid and os.getpgid(pid) == pgid:
                    os.killpg(pgid, signal.SIGKILL)
                    break
            except (ProcessLookupError, PermissionError):
                continue


def _kill_session_groups(sid: int) -> None:
    """Reap legacy extraction session groups after a worker exits."""
    if os.getsid(0) == sid:
        raise RuntimeError("refusing to kill the parent's own session")
    _kill_verified_groups(sid, _cleanup_members(sid))


async def _watch_memory(sid: int, stop: asyncio.Event, fault: list[str]) -> None:
    """macOS fallback: sampled session RSS, including page groups and descendants."""
    while not stop.is_set():
        members = await asyncio.to_thread(_session_members, sid)
        if members is None:
            fault.append("invalid_file")
        elif sum(rss for _, _, rss in members) > MEMORY_LIMIT_BYTES:
            fault.append("too_much_text")
        if fault:
            with suppress(OSError):
                _kill_session_groups(sid)
            return
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), RSS_POLL_SECONDS)


def _worker(argv: list[str] | None = None) -> None:
    # Apply the cap before importing pypdf or reading the upload. Never import the hub.
    limits = _apply_memory_limit()
    from agents.core.workspace.extract import ExtractionError, _extract_bytes_in_child

    args = sys.argv[1:] if argv is None else argv
    kind, seconds = args[:2]
    posix_owned = len(args) > 2 and args[2] == "--owned-ocr"
    windows_owned = len(args) > 3 and args[2] == "--owned-win-job-ocr"
    owned = posix_owned or windows_owned
    proof = None
    if windows_owned:
        from agents.core.workspace.win_job_process import claim_child

        proof = claim_child(args[3])
        if proof is None:
            sys.stdout.write(json.dumps({"event": "result", "payload": {
                "error": "invalid_file", "page_count": None}}) + "\n")
            sys.stdout.flush()
            return
        limits = ("wall_time", "job_commit")

    def progress(event: str, page: int, page_deadline: float, count: int) -> None:
        frame = {"event": event, "page": page, "page_count": count}
        if event == "page_start":
            frame["deadline"] = page_deadline
        sys.stdout.write(json.dumps(frame, ensure_ascii=True) + "\n")
        sys.stdout.flush()

    try:
        if windows_owned:
            from agents.core.workspace.win_job_process import child_scope

            scope = child_scope(proof)
        else:
            scope = nullcontext()
        with scope:
            result = _extract_bytes_in_child(
                sys.stdin.buffer.read(), kind, timeout=float(seconds),
                progress=progress if owned else None)
        payload = {"segments": [[s.page, s.text] for s in result.segments],
                   "page_count": result.page_count, "limits": limits + result.limits}
    except ExtractionError as exc:
        payload = {"error": exc.code, "page_count": exc.page_count}
    except MemoryError:
        payload = {"error": "too_much_text", "page_count": None}
    if owned:
        payload = {"event": "result", "payload": payload}
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + ("\n" if owned else ""))
    sys.stdout.flush()


async def _reap(process: asyncio.subprocess.Process) -> None:
    # A native OCR process can outlive its worker while inheriting stdout. Killing
    # only a live leader would leave communicate() waiting on that descendant.
    cleanup_error = None
    try:
        if sys.platform == "win32":
            with suppress(OSError):
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/F", "/T", "/PID", str(process.pid),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
        else:
            _kill_session_groups(process.pid)
    except OSError as exc:
        cleanup_error = exc
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        try:
            await asyncio.wait_for(process.communicate(), timeout=1)
        except TimeoutError:
            # A still-running descendant may hold an inherited pipe open when
            # enumeration itself failed. Close our pipe ends before reaping.
            for fd in (0, 1, 2):
                pipe = process._transport.get_pipe_transport(fd)
                if pipe is not None:
                    pipe.close()
            await process.wait()
            if cleanup_error is None:
                cleanup_error = OSError("extraction descendant kept a pipe open")
    if cleanup_error is not None:
        raise cleanup_error


def _owned_command() -> list[str]:
    return ([sys.executable, "--nerva-workspace-extract-worker"]
            if getattr(sys, "frozen", False) else
            [sys.executable, "-m", "agents.core.workspace.extract_process"])


def _spawn_owned(kind: str, seconds: float, env: dict[str, str]) -> subprocess.Popen[bytes]:
    """Retain the isolated session leader until the owner signals its group."""
    # _owned_command supplies the current Python executable and fixed module;
    # kind/deadline are separate argv elements, with owned cwd/env and no shell.
    return subprocess.Popen(  # nosec B603
        [*_owned_command(), kind, str(seconds), "--owned-ocr"],
        cwd=_REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True, shell=False)


async def _fd_ready(fd: int, *, write: bool = False) -> None:
    loop = asyncio.get_running_loop()
    ready = loop.create_future()

    def wake() -> None:
        if not ready.done():
            ready.set_result(None)

    if write:
        loop.add_writer(fd, wake)
    else:
        loop.add_reader(fd, wake)
    try:
        await ready
    finally:
        if write:
            loop.remove_writer(fd)
        else:
            loop.remove_reader(fd)


async def _send_owned_input(process: subprocess.Popen[bytes], data: bytes) -> None:
    if process.stdin is None:
        raise OSError('owned extraction input pipe unavailable')
    fd = process.stdin.fileno()
    os.set_blocking(fd, False)
    source = memoryview(data)
    offset = 0
    try:
        while offset < len(source):
            try:
                offset += os.write(fd, source[offset:offset + 65536])
            except BlockingIOError:
                await _fd_ready(fd, write=True)
            except BrokenPipeError:
                return
    finally:
        with suppress(OSError):
            process.stdin.close()


async def _read_owned_line(process: subprocess.Popen[bytes], buffer: bytearray) -> bytes | None:
    if process.stdout is None:
        raise OSError('owned extraction output pipe unavailable')
    fd = process.stdout.fileno()
    os.set_blocking(fd, False)
    search_from = 0
    while True:
        end = buffer.find(b"\n", search_from)
        if end >= 0:
            line = bytes(buffer[:end])
            del buffer[:end + 1]
            return line
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            await _fd_ready(fd)
            continue
        if not chunk:
            if buffer:
                line = bytes(buffer)
                buffer.clear()
                return line
            return None
        search_from = len(buffer)
        buffer.extend(chunk)
        if len(buffer) > _MAX_FRAME_BYTES:
            raise OSError("extraction child frame exceeds output budget")


async def _watch_owned_memory(sid: int, stop: asyncio.Event, fault: list[str],
                              signaled: list[bool]) -> None:
    """Sample RSS; signal the reserved group directly if accounting fails."""
    while not stop.is_set():
        members = await asyncio.to_thread(_session_members, sid)
        if members is None:
            fault.append("invalid_file")
        elif sum(rss for _, _, rss in members) > MEMORY_LIMIT_BYTES:
            fault.append("too_much_text")
        if fault:
            with suppress(ProcessLookupError):
                os.killpg(sid, signal.SIGKILL)
                signaled[0] = True
            return
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), RSS_POLL_SECONDS)


def _signal_owned_group(process: subprocess.Popen[bytes], *, signaled: bool = False) -> None:
    """Signal while the unreaped leader still reserves the group ID."""
    if os.getsid(0) == process.pid:
        raise RuntimeError("refusing to kill the parent's own process group")
    if not signaled:
        # macOS returns EPERM for an unreaped zombie-only group. OCR children
        # do not change UID; no same-UID member is signalable in that case.
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)


async def _drain_owned(process: subprocess.Popen[bytes]) -> None:
    for pipe in (process.stdin, process.stdout):
        if pipe is not None:
            with suppress(OSError):
                pipe.close()
    await asyncio.to_thread(process.wait)


async def _extract_owned_ocr(data: bytes, kind: str, *, timeout: float) -> Extracted:
    """Parent-enforced OCR page clocks with one retained POSIX group owner."""
    from agents.core.workspace.extract import ERROR_CODES, Extracted, ExtractionError, Segment

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    acquired = False
    process = None
    launch = None
    writer = None
    watcher = None
    watch_stop = asyncio.Event()
    memory_fault: list[str] = []
    group_signaled = [False]
    try:
        async with asyncio.timeout_at(deadline):
            while not (acquired := _SLOTS.acquire(blocking=False)):
                await asyncio.sleep(0.01)
            with tempfile.TemporaryDirectory(prefix="nerva-ws-extract-") as scratch:
                try:
                    env = dict(os.environ, TMPDIR=scratch, TEMP=scratch, TMP=scratch)
                    launch = asyncio.create_task(asyncio.to_thread(
                        _spawn_owned, kind, max(0.0, deadline - loop.time()), env))
                    process = await asyncio.shield(launch)
                    writer = asyncio.create_task(_send_owned_input(process, data))
                    watcher = asyncio.create_task(_watch_owned_memory(
                        process.pid, watch_stop, memory_fault, group_signaled))
                    buffer = bytearray()
                    active_page = None
                    page_deadline = None
                    page_count = None
                    while True:
                        try:
                            if page_deadline is None:
                                line = await _read_owned_line(process, buffer)
                            else:
                                async with asyncio.timeout_at(page_deadline):
                                    line = await _read_owned_line(process, buffer)
                        except TimeoutError as exc:
                            raise ExtractionError("timeout", "OCR page deadline",
                                                  page_count=page_count) from exc
                        if memory_fault:
                            raise ExtractionError(memory_fault[0], "extraction memory monitor")
                        if page_deadline is not None and loop.time() >= page_deadline:
                            raise ExtractionError("timeout", "OCR page deadline",
                                                  page_count=page_count)
                        if line is None:
                            raise ExtractionError("invalid_file", "extraction child ended")
                        try:
                            frame = json.loads(line)
                            event = frame["event"]
                            if event == "page_start" and active_page is None:
                                active_page = int(frame["page"])
                                page_count = int(frame["page_count"])
                                page_deadline = _bounded_ocr_page_deadline(
                                    frame["deadline"], now=loop.time(), document_deadline=deadline)
                                if loop.time() >= page_deadline:
                                    raise ExtractionError("timeout", "OCR page deadline",
                                                          page_count=page_count)
                            elif event == "page_done" and active_page == frame.get("page"):
                                if loop.time() > page_deadline:
                                    raise ExtractionError("timeout", "OCR page deadline",
                                                          page_count=page_count)
                                active_page = None
                                page_deadline = None
                            elif event == "result":
                                payload = frame["payload"]
                                if active_page is not None and "error" not in payload:
                                    raise ValueError("OCR page lacked completion frame")
                                if "error" in payload:
                                    code = payload["error"]
                                    raise ExtractionError(
                                        code if code in ERROR_CODES else "invalid_file",
                                        "child refused extraction", page_count=payload.get("page_count"))
                                limits = tuple(payload["limits"]) + ("rss_sampled",)
                                return Extracted(tuple(Segment(*s) for s in payload["segments"]),
                                                 payload["page_count"], limits)
                            else:
                                raise ValueError("invalid extraction progress frame")
                        except (ValueError, KeyError, TypeError) as exc:
                            raise ExtractionError("invalid_file", "invalid extraction frame") from exc
                finally:
                    async def cleanup() -> None:
                        child = process if process is not None else await launch if launch else None
                        if child is not None:
                            _signal_owned_group(child, signaled=group_signaled[0])
                        watch_stop.set()
                        try:
                            if watcher is not None:
                                await watcher
                        finally:
                            if writer is not None:
                                writer.cancel()
                                await asyncio.gather(writer, return_exceptions=True)
                            if child is not None:
                                await _drain_owned(child)

                    cleanup_task = asyncio.create_task(cleanup())
                    cancelled = False
                    while not cleanup_task.done():
                        try:
                            await asyncio.shield(cleanup_task)
                        except asyncio.CancelledError:
                            cancelled = True
                    cleanup_task.result()
                    if cancelled:
                        raise asyncio.CancelledError
    except TimeoutError as exc:
        raise ExtractionError("timeout", f"no result within {timeout:g} s") from exc
    except OSError as exc:
        raise ExtractionError("invalid_file", "extraction child unavailable") from exc
    finally:
        if acquired:
            _SLOTS.release()


def _spawn_windows_owned(kind: str, seconds: float, env: dict[str, str], *, api=None):
    from agents.core.workspace.win_job_process import OwnedJobProcess, new_child_nonce

    nonce = new_child_nonce()
    child_env = dict(env, NERVA_WORKSPACE_JOB_NONCE=nonce)
    return OwnedJobProcess.spawn(
        [*_owned_command(), kind, str(seconds), "--owned-win-job-ocr", nonce],
        cwd=str(_REPO), env=child_env, memory_limit=MEMORY_LIMIT_BYTES, api=api)


async def _extract_windows_ocr(data: bytes, kind: str, *, timeout: float, api=None) -> Extracted:
    """Gated Job-owned OCR controller; tests inject a fake API on non-Windows."""
    from agents.core.workspace.extract import ERROR_CODES, Extracted, ExtractionError, Segment

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    acquired = False
    scratch = None
    owner = launch = writer = None
    verified = False
    try:
        async with asyncio.timeout_at(deadline):
            while not (acquired := _SLOTS.acquire(blocking=False)):
                await asyncio.sleep(0.01)
            scratch = tempfile.mkdtemp(prefix="nerva-ws-extract-")
            try:
                env = dict(os.environ, TMPDIR=scratch, TEMP=scratch, TMP=scratch)
                launch = asyncio.create_task(asyncio.to_thread(
                    _spawn_windows_owned, kind, max(0.0, deadline - loop.time()), env,
                    api=api))
                owner = await asyncio.shield(launch)
                await owner.start_io()
                writer = asyncio.create_task(owner.send(data))
                buffer = bytearray()
                active_page = page_deadline = page_count = None
                while True:
                    try:
                        if page_deadline is None:
                            line = await owner.read_line(buffer)
                        else:
                            async with asyncio.timeout_at(page_deadline):
                                line = await owner.read_line(buffer)
                    except TimeoutError as exc:
                        raise ExtractionError("timeout", "OCR page deadline",
                                              page_count=page_count) from exc
                    if page_deadline is not None and loop.time() >= page_deadline:
                        raise ExtractionError("timeout", "OCR page deadline",
                                              page_count=page_count)
                    if line is None:
                        raise ExtractionError("invalid_file", "Windows OCR child ended")
                    try:
                        frame = json.loads(line)
                        event = frame["event"]
                        if event == "page_start" and active_page is None:
                            active_page = int(frame["page"])
                            page_count = int(frame["page_count"])
                            page_deadline = _bounded_ocr_page_deadline(
                                frame["deadline"], now=loop.time(), document_deadline=deadline)
                            if loop.time() >= page_deadline:
                                raise ExtractionError("timeout", "OCR page deadline",
                                                      page_count=page_count)
                        elif event == "page_done" and active_page == frame.get("page"):
                            if loop.time() > page_deadline:
                                raise ExtractionError("timeout", "OCR page deadline",
                                                      page_count=page_count)
                            active_page = page_deadline = None
                        elif event == "result":
                            payload = frame["payload"]
                            if active_page is not None and "error" not in payload:
                                raise ValueError("OCR page lacked completion frame")
                            if "error" in payload:
                                code = payload["error"]
                                raise ExtractionError(
                                    code if code in ERROR_CODES else "invalid_file",
                                    "child refused extraction", page_count=payload.get("page_count"))
                            limits = tuple(payload["limits"])
                            if "job_commit" not in limits:
                                raise ValueError("Windows Job commit proof missing")
                            return Extracted(tuple(Segment(*s) for s in payload["segments"]),
                                             payload["page_count"], limits)
                        else:
                            raise ValueError("invalid Windows OCR progress frame")
                    except (ValueError, KeyError, TypeError) as exc:
                        raise ExtractionError("invalid_file", "invalid Windows OCR frame") from exc
            finally:
                async def cleanup():
                    from agents.core.workspace.win_job_process import JobCleanupUnverified

                    try:
                        child = owner if owner is not None else await launch if launch else None
                    except JobCleanupUnverified:
                        raise
                    except OSError:
                        # Spawn finished and cleaned every handle before raising.
                        return
                    if writer is not None:
                        writer.cancel()
                        await asyncio.gather(writer, return_exceptions=True)
                    if child is not None:
                        await child.terminate_and_drain()

                cleanup_task = asyncio.create_task(cleanup())
                cancelled = False
                while not cleanup_task.done():
                    try:
                        await asyncio.shield(cleanup_task)
                    except asyncio.CancelledError:
                        cancelled = True
                cleanup_task.result()
                verified = True
                if cancelled:
                    raise asyncio.CancelledError
    except TimeoutError as exc:
        raise ExtractionError("timeout", "Windows OCR document deadline") from exc
    except OSError as exc:
        raise ExtractionError("invalid_file", "Windows OCR Job unavailable") from exc
    finally:
        # If cleanup cannot prove ActiveProcesses=0, preserve the scratch and
        # occupied slot instead of admitting another native OCR attempt.
        if verified or launch is None:
            try:
                if scratch is not None:
                    shutil.rmtree(scratch)
            finally:
                if acquired:
                    _SLOTS.release()


async def extract_in_child(data: bytes, kind: str, *, timeout: float) -> Extracted:
    from agents.core.workspace.extract import ERROR_CODES, Extracted, ExtractionError, Segment

    if kind == "pdf" and env_flag("NERVA_WORKSPACE_OCR", False):
        if sys.platform != "win32":
            return await _extract_owned_ocr(data, kind, timeout=timeout)
        if _WINDOWS_OCR_NATIVE_ACCEPTED:
            return await _extract_windows_ocr(data, kind, timeout=timeout)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    acquired = False
    process = None
    launch = None
    watch_task = None
    watch_stop = asyncio.Event()
    memory_fault: list[str] = []
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
                        stderr=asyncio.subprocess.DEVNULL,
                        start_new_session=sys.platform != "win32"))
                    # Cancellation during launch must still obtain and reap the child.
                    process = await asyncio.shield(launch)
                    # macOS needs sampled memory for every child. OCR adds a
                    # second process on Linux, so sample aggregate session RSS
                    # there as well as retaining each process's RLIMIT_AS.
                    if sys.platform == "darwin" or (sys.platform != "win32" and kind == "pdf"
                                                     and env_flag("NERVA_WORKSPACE_OCR", False)):
                        watch_task = asyncio.create_task(_watch_memory(
                            process.pid, watch_stop, memory_fault))
                    output, _ = await process.communicate(data)
                    if memory_fault:
                        raise ExtractionError(memory_fault[0], "extraction memory monitor")
                    if process.returncode != 0:
                        raise ExtractionError("invalid_file", "extraction child failed")
                    try:
                        payload = json.loads(output)
                        if "error" in payload:
                            code = payload["error"]
                            raise ExtractionError(code if code in ERROR_CODES else "invalid_file",
                                                  "child refused extraction",
                                                  page_count=payload.get("page_count"))
                        limits = tuple(payload["limits"])
                        if watch_task is not None:
                            limits += ("rss_sampled",)
                        return Extracted(tuple(Segment(*s) for s in payload["segments"]),
                                         payload["page_count"], limits)
                    except (ValueError, KeyError, TypeError) as exc:
                        raise ExtractionError("invalid_file", "invalid extraction result") from exc
                finally:
                    async def cleanup():
                        watch_stop.set()
                        if watch_task is not None:
                            await watch_task
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
