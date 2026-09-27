"""local_providers.py — Piper TTS and the owner's command providers for TTS / STT (H613).

Two ways to keep speech on this machine without a code change:

* **Piper** (``piper:<model>`` voices, or bare ``piper``). The ``piper`` Python package
  when it imports, otherwise the ``piper`` binary found on ``PATH``. The model is always
  ``<model dir>/<name>.onnx`` with its ``.onnx.json``, where the directory is
  ``voice.piper_model_dir`` (empty: ``<data>/voice/piper``). A voice name only *selects*
  among files the owner put there: no path, no ``..``, no leading ``-``.
* **Command providers** (``voice.tts_command`` / ``voice.stt_command``). An argv template
  the owner approved, with whole-element placeholders ``{text_file}``, ``{output}``,
  ``{audio}`` and ``{lang}``. A setting that makes the hub run a program is a host-exec
  capability, so it is governed like one:

  - the rows are ROUTE_ONLY: the only writer is ``POST /api/admin/voice/commands``, which
    sends a set or a change to the approval queue's irreversible tier (H262); the model,
    an import, a reset, an undo and ``nerva config set`` cannot write them;
  - at run time they also need ``JARVIS_VOICE_COMMANDS=1`` in the hub's environment (no
    HTTP path can flip it, loopback included) and are off in safe mode;
  - every spawn re-validates the argv (absolute existing program, not a shell or a
    launcher, no placeholder in the program name, no inline-code interpreter, the
    hardline denylist, no credential in the command line) and checks it against the
    fingerprint and the identity of every file that runs — the program and, for an
    interpreter, the script it runs — recorded at approval: device, inode, size, mtime
    and the sha256 of the content. A replaced, upgraded or rewritten file needs approving
    again. The check runs once more after the concurrency slot is acquired, right before
    the spawn, and the freshly checked path is the one executed;
  - a bound file (and every directory above it) may not be writable by other users: a
    directory writable by the group or by everyone without the sticky bit lets someone
    else swap the file.

Every run is ``create_subprocess_exec`` with an argv list — never a shell — in a private
0700 run directory under the TTS temp dir, with a scrubbed environment, one deadline over
stdin, output and exit, and capped stdout/stderr. On POSIX the child leads its own process
group, and a timeout or a cancel ends the whole group (TERM, then KILL), so an engine a
wrapper script started does not outlive the run. The text to speak never enters argv: it
goes on stdin or into ``{text_file}``. The audio a provider writes is read back only when it
is a regular file inside the run directory, not empty, at most 8 MiB and a known audio
format by its magic bytes; it is copied to a fresh ``0600`` file in the temp dir, which is
the path the caller gets (and deletes).

This confines what Nerva reads back and returns. It is not a sandbox for the owner's
program, which runs as the hub's user — that is why the approval card names the program,
its argv and who it runs as.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.util
import logging
import os
import re
import shutil
import signal
import stat
import tempfile
import threading
import uuid
import wave
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.voice.local")

# ── limits ───────────────────────────────────────────────────────────────────────────

TTS_TIMEOUT_S = 30
STT_TIMEOUT_S = 120                      # a long recording takes a while to transcribe
TIMEOUT_ENV = "JARVIS_VOICE_COMMAND_TIMEOUT_S"
ARM_ENV = "JARVIS_VOICE_COMMANDS"
MAX_TIMEOUT_S = 600                      # environments/terminal_contract.MAX_TIMEOUT_S
MAX_TEXT_BYTES = 64 * 1024               # text handed to a provider
MAX_AUDIO_OUT_BYTES = 8 * 1024 * 1024    # channels/spoken_reply.MAX_AUDIO_BYTES
MAX_AUDIO_IN_BYTES = 64 * 1024 * 1024    # audio handed to an STT command
MAX_STREAM_BYTES = 64 * 1024             # stdout / stderr kept, each
MAX_TRANSCRIPT_CHARS = 4000              # channels/inbound_voice.MAX_TRANSCRIPT_CHARS
MAX_ARGV_ITEMS = 64
MAX_ARG_CHARS = 4000
MAX_MODEL_LISTING = 256
LOCAL_EXEC_CONCURRENCY = 2
MAX_BOUND_FILE_BYTES = 64 * 1024 * 1024  # a program or script the approval binds by its sha256
KILL_GRACE_S = 0.5                       # TERM to the process group, then KILL

LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

SIDES = ("tts", "stt")
PLACEHOLDERS = frozenset({"{text_file}", "{output}", "{audio}", "{lang}"})
#: side → (placeholders allowed, the one that must appear exactly once)
SIDE_PLACEHOLDERS: dict[str, tuple[frozenset[str], str]] = {
    "tts": (frozenset({"{text_file}", "{output}", "{lang}"}), "{output}"),
    "stt": (frozenset({"{audio}", "{lang}"}), "{audio}"),
}
#: Shells: never a provider, and never named by path anywhere in the argv (a program that
#: execs a later element would run it).
SHELLS = frozenset({
    "sh", "bash", "dash", "zsh", "ksh", "mksh", "ash", "rbash", "fish", "csh", "tcsh", "busybox",
    "toybox", "cmd", "powershell", "pwsh",
})
#: A program that runs another program, a command line or code taken from its arguments:
#: never a provider. The shell heads of ``environments/terminal_contract`` (private there),
#: the launchers that would hide what actually runs, and the tools that execute code from
#: an argument (``find -exec``, ``awk 'system()'``, ``git -c core.pager=``, an editor, a
#: debugger, a container runtime, the dynamic loader).
LAUNCHERS = SHELLS | frozenset({
    "env", "sudo", "doas", "su", "pkexec", "runuser", "xargs", "nohup", "setsid", "timeout", "nice",
    "ionice", "stdbuf", "chroot", "unshare", "nsenter", "script", "taskset", "chrt", "flock", "watch",
    "exec", "eval", "ssh", "open", "start", "find", "awk", "gawk", "mawk", "nawk", "sed", "gsed",
    "expect", "unbuffer", "r", "rscript", "osascript", "wscript", "cscript", "wine", "wine64", "docker",
    "podman", "nerdctl", "systemd-run", "flatpak", "snap", "make", "gmake", "git", "vim", "vi", "nvim",
    "view", "ex", "emacs", "less", "more", "man", "most", "gdb", "lldb", "strace", "ltrace", "valgrind",
    "time", "bwrap", "firejail", "setpriv", "capsh", "prlimit", "parallel", "tmux", "screen", "uv", "uvx",
    "npx", "pipx", "npm", "pnpm", "yarn",
})
#: Launcher families with a version or a platform in the name (``ld-linux-x86-64.so.2``,
#: ``ld-musl-x86_64.so.1``, ``ld.so``, ``tclsh8.6``).
_LAUNCHER_RE = re.compile(r"^(ld\.so.*|ld-linux.*|ld-musl.*|ld-.*\.so(\..*)?|tclsh[0-9.]*|wish[0-9.]*"
                          r"|expect[0-9.]*|wine(64)?[0-9.-]*)$")
#: Interpreters take inline code (``-c``, ``-e``, ``--eval``): allowed only running a script
#: file named by absolute path right after them — and that script is bound like the program.
_INTERPRETER_RE = re.compile(
    r"^(python[0-9.]*w?|pypy[0-9.]*|perl[0-9.]*|ruby[0-9.]*|node(js)?|deno|bun|php[0-9.]*|lua[0-9.]*|luajit"
    r"|julia|java)$")

#: Reasons ``command_ready`` answers with.
NOT_CONFIGURED = "not_configured"
NOT_ARMED = "not_armed"
SAFE_MODE = "safe_mode"
INVALID = "invalid"
FINGERPRINT_MISMATCH = "fingerprint_mismatch"
CHANGED_SINCE_APPROVAL = "changed_since_approval"
EXE_MISSING = "exe_missing"
TEMP_DIR_UNSAFE = "temp_dir_unsafe"

_logged: set[str] = set()
_logged_lock = threading.Lock()


def _log_once(key: str, message: str, *args: Any) -> None:
    with _logged_lock:
        if key in _logged:
            return
        _logged.add(key)
    logger.warning(message, *args)


def _setting(key: str, default: Any) -> Any:
    """``voice.<key>``, read now (never cached: the owner can change it at any time)."""
    try:
        from agents.core.settings_db import get_value

        return get_value("voice", key, default)
    except Exception:  # noqa: BLE001 — no settings: the declared default
        return default


def _safe_mode_on(layer: str) -> bool:
    try:
        from agents.core import safe_mode
    except Exception:  # noqa: BLE001 — pragma: no cover
        return False
    if not safe_mode.enabled():
        return False
    safe_mode.note(layer)
    return True


def armed() -> bool:
    """Whether the hub's environment arms command providers (``JARVIS_VOICE_COMMANDS``)."""
    from agents.core.env_config import env_flag

    return env_flag(ARM_ENV)


def timeout_for(default: int) -> int:
    """*default*, or ``JARVIS_VOICE_COMMAND_TIMEOUT_S`` clamped to ``1..600``."""
    raw = (os.environ.get(TIMEOUT_ENV) or "").strip()
    if not raw:
        return default
    try:
        value = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(1, min(MAX_TIMEOUT_S, value))


def safe_lang(lang: Any, default: str = "en") -> str:
    """*lang* lowered when it is a language tag (``ro``, ``en-us``), else *default*."""
    if isinstance(lang, str):
        candidate = lang.strip().lower()
        if LANG_RE.match(candidate):
            return candidate
    fallback = default.strip().lower() if isinstance(default, str) else ""
    return fallback if LANG_RE.match(fallback) else "en"


# ── the private run directory ────────────────────────────────────────────────────────

def _safe_temp_root(temp_dir: Path) -> Path | None:
    """*temp_dir* when it is a real directory this process owns (made 0700), else None."""
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        info = os.lstat(temp_dir)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            return None
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            return None
        os.chmod(temp_dir, 0o700)
        return temp_dir
    except OSError:
        return None


@contextlib.asynccontextmanager
async def private_workdir(temp_dir: Path):
    """A fresh 0700 ``run-*`` directory under *temp_dir*, removed on exit (only it).
    Yields None when *temp_dir* is not safe to use (a symlink, someone else's)."""
    root = _safe_temp_root(Path(temp_dir))
    if root is None:
        _log_once(TEMP_DIR_UNSAFE, "voice: the TTS temp dir is not a private directory; local providers are off")
        yield None
        return
    workdir = Path(tempfile.mkdtemp(dir=root, prefix="run-"))
    try:
        yield workdir
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _write_private(path: Path, data: bytes) -> None:
    """A new file with mode 0600 (never an existing one, never through a link)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


# ── one bounded run ──────────────────────────────────────────────────────────────────

_sems: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _sems.get(loop)
    if sem is None:
        sem = _sems[loop] = asyncio.Semaphore(LOCAL_EXEC_CONCURRENCY)
    return sem


async def _spawn(*argv: str, **kwargs: Any):
    """The one spawn: an argv list, never a shell (a seam tests spy on)."""
    return await asyncio.create_subprocess_exec(*argv, **kwargs)


def _argv_problem(argv: Any) -> str | None:
    if not isinstance(argv, (list, tuple)) or not 1 <= len(argv) <= MAX_ARGV_ITEMS:
        return f"argv: a list of 1 to {MAX_ARGV_ITEMS} strings"
    for item in argv:
        if not isinstance(item, str):
            return "argv: every element must be a string"
        if len(item) > MAX_ARG_CHARS:
            return f"argv: an element longer than {MAX_ARG_CHARS} characters"
        if "\x00" in item:
            return "argv: an element holds a NUL byte"
    return None


_GROUPS = os.name == "posix" and hasattr(os, "killpg")


def _signal_group(proc: Any, signum: int) -> None:
    """*signum* to the child's whole process group (it leads one: ``start_new_session``)."""
    if not _GROUPS:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(int(proc.pid), signum)


async def _kill(proc: Any) -> None:
    """End the run: TERM to the process group, a short grace, then KILL to the group and
    the child, and reap it. A wrapper's engine (a grandchild) goes with it."""
    if _GROUPS:
        _signal_group(proc, signal.SIGTERM)
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE_S)
        _signal_group(proc, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError, OSError):
        proc.kill()
    with contextlib.suppress(TimeoutError, OSError):
        await asyncio.wait_for(proc.wait(), timeout=5)


#: ``prepare`` of :func:`run_bounded` answering None: the check inside the slot refused.
CHANGED_BEFORE_SPAWN = "changed_before_spawn"


async def run_bounded(argv: list[str], *, cwd: Path, stdin_bytes: bytes | None, timeout: float,
                      prepare: Any = None) -> dict[str, Any]:
    """Run *argv* (no shell) in *cwd* under one deadline; never raises for a process failure.

    *prepare*, when given, is awaited once the concurrency slot is held, right before the
    spawn: it answers the argv to run (checked again now), or None to run nothing.

    ``{ok, returncode, stdout, stderr_tail, timed_out, argv_sha256, reason}``."""
    from agents.core.environments import scrub_child_env
    from agents.core.environments.output_limits import read_capped_stream
    from agents.core.environments.terminal_contract import argv_fingerprint

    problem = _argv_problem(argv)
    result: dict[str, Any] = {"ok": False, "returncode": None, "stdout": b"", "stderr_tail": "",
                              "timed_out": False, "argv_sha256": None, "reason": None}
    if problem is not None:
        return {**result, "reason": "invalid_argv"}
    argv = [str(a) for a in argv]
    async with _slot():
        if prepare is not None:
            fresh = await prepare()
            if fresh is None:
                return {**result, "reason": CHANGED_BEFORE_SPAWN}
            if _argv_problem(fresh) is not None:
                return {**result, "reason": "invalid_argv"}
            argv = [str(a) for a in fresh]
        result["argv_sha256"] = argv_fingerprint(argv)
        extra: dict[str, Any] = {"start_new_session": True} if _GROUPS else {}
        try:
            proc = await _spawn(
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd), env=scrub_child_env(os.environ), **extra,
            )
        except (FileNotFoundError, PermissionError):
            return {**result, "reason": "executable_not_runnable"}
        except OSError:
            return {**result, "reason": "spawn_failed"}

        async def feed() -> None:
            if proc.stdin is None:
                return
            try:
                if stdin_bytes:
                    proc.stdin.write(stdin_bytes)
                    await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass                                   # a program that does not read its stdin
            finally:
                with contextlib.suppress(Exception):
                    proc.stdin.close()

        async def everything():
            out, err, _ = await asyncio.gather(
                read_capped_stream(proc.stdout, max_content_bytes=MAX_STREAM_BYTES),
                read_capped_stream(proc.stderr, max_content_bytes=MAX_STREAM_BYTES),
                feed())
            await proc.wait()
            return out, err

        try:
            (out_head, out_tail, out_total), (err_head, err_tail, _err_total) = await asyncio.wait_for(
                everything(), timeout=timeout)
        except TimeoutError:
            await _kill(proc)
            return {**result, "timed_out": True, "reason": "timeout"}
        except asyncio.CancelledError:
            await _kill(proc)
            raise
    stdout = out_head + out_tail if out_total <= MAX_STREAM_BYTES else out_head
    stderr_tail = (err_tail or err_head)[-2000:].decode("utf-8", errors="replace")
    code = proc.returncode if isinstance(proc.returncode, int) else -1
    return {**result, "ok": code == 0, "returncode": code, "stdout": stdout, "stderr_tail": stderr_tail,
            "reason": None if code == 0 else "nonzero_exit"}


# ── what a provider wrote ────────────────────────────────────────────────────────────

def sniff_audio(head: bytes) -> str | None:
    """The suffix an audio file's magic bytes say it is, or None."""
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    if head[:4] == b"OggS":
        return ".ogg"
    if head[:4] == b"fLaC":
        return ".flac"
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return ".mp3"
    return None


def sniff_input_audio(head: bytes) -> str:
    """The suffix to give audio handed to an STT command (a browser blob is webm)."""
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    return sniff_audio(head) or ".webm"


def claim_output(path: Path, workdir: Path, temp_dir: Path, kind: str) -> tuple[str | None, str | None]:
    """Copy the audio a provider wrote at *path* to a fresh 0600 file in *temp_dir*:
    ``(that path, None)``, or ``(None, why it was refused)``."""
    try:
        info = os.lstat(path)
    except OSError:
        return None, "no_output"
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return None, "not_a_regular_file"
    if info.st_size <= 0:
        return None, "empty_output"
    if info.st_size > MAX_AUDIO_OUT_BYTES:
        return None, "output_too_large"
    try:
        if not Path(path).resolve(strict=True).is_relative_to(Path(workdir).resolve(strict=True)):
            return None, "output_outside_run_dir"
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(MAX_AUDIO_OUT_BYTES + 1)
    except OSError:
        return None, "unreadable_output"
    if not data:
        return None, "empty_output"
    if len(data) > MAX_AUDIO_OUT_BYTES:
        return None, "output_too_large"
    suffix = sniff_audio(data[:16])
    if suffix is None:
        return None, "unknown_format"
    target = Path(temp_dir) / f"response_{kind}_{uuid.uuid4().hex}{suffix}"
    try:
        _write_private(target, data)
    except OSError:
        return None, "write_failed"
    return str(target), None


# ── programs ─────────────────────────────────────────────────────────────────────────

def _loose_ancestor(path: Path) -> Path | None:
    """The first directory above *path* that another user could change an entry of: one
    writable by the group or by everyone without the sticky bit (or one that cannot be
    read). None when there is none."""
    for folder in path.parents:
        try:
            mode = os.stat(folder).st_mode
        except OSError:
            return folder
        if mode & (stat.S_IWGRP | stat.S_IWOTH) and not mode & stat.S_ISVTX:
            return folder
    return None


def trusted_program(path: str | os.PathLike, *, executable: bool = True,
                    what: str = "the program") -> tuple[Path | None, str | None]:
    """The resolved file at *path*, when it is an absolute, existing (and, for a program,
    executable) regular file of at most 64 MiB that neither it nor its directory lets
    everyone write, and no directory above it lets another user swap: ``(path, None)``,
    else ``(None, why)``. An interpreter's script goes through here too
    (``executable=False``, ``what="the script"``)."""
    raw = os.fspath(path)
    if not os.path.isabs(raw):
        return None, f"{what} must be an absolute path"
    try:
        exe = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError):
        return None, f"{what} does not exist"
    try:
        info = os.stat(exe)
        parent = os.stat(exe.parent)
    except OSError:
        return None, f"{what} does not exist"
    if not stat.S_ISREG(info.st_mode):
        return None, f"{what} is not a regular file"
    if executable and not os.access(exe, os.X_OK):
        return None, f"{what} is not executable"
    if info.st_mode & stat.S_IWOTH or parent.st_mode & stat.S_IWOTH:
        return None, f"{what} or its directory is writable by every user"
    loose = _loose_ancestor(exe)
    if loose is not None:
        return None, (f"{what} sits under {loose}, which another user can write (group- or world-writable "
                      "without the sticky bit)")
    if info.st_size > MAX_BOUND_FILE_BYTES:
        return None, f"{what} is larger than 64 MiB (the approval binds its content)"
    return exe, None


_IDENTITY_KEYS = ("path", "dev", "ino", "size", "mtime_ns")


def file_identity(path: Path, *, content: bool = True) -> dict[str, Any] | None:
    """What the approval binds a file to: its path, ``(dev, ino, size, mtime_ns)`` and the
    sha256 of its content (read through one descriptor, and refused when the file changed
    while it was read, is not a regular file or is over 64 MiB). ``content=False`` leaves
    the digest out: a cheap probe for availability reports, never for a spawn."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as fh:
            before = os.fstat(fh.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BOUND_FILE_BYTES:
                return None
            identity: dict[str, Any] = {"path": str(path), "dev": int(before.st_dev), "ino": int(before.st_ino),
                                        "size": int(before.st_size), "mtime_ns": int(before.st_mtime_ns)}
            if not content:
                return identity
            digest, total = hashlib.sha256(), 0
            while chunk := fh.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BOUND_FILE_BYTES:
                    return None
                digest.update(chunk)
            after = os.fstat(fh.fileno())
    except OSError:
        return None
    if total != before.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            before.st_size, before.st_mtime_ns, before.st_ctime_ns):
        return None                                   # it changed while it was read
    return {**identity, "sha256": digest.hexdigest()}


def exe_identity(exe: Path) -> dict[str, Any] | None:
    """The identity of a program (:func:`file_identity`, with its content digest)."""
    return file_identity(exe)


def _same_identity(recorded: Any, now: dict[str, Any] | None) -> bool:
    """Whether *now* matches what the approval *recorded* (every key *now* carries)."""
    if now is None or not isinstance(recorded, dict):
        return False
    if "sha256" in now and not isinstance(recorded.get("sha256"), str):
        return False
    return all(recorded.get(key) == value for key, value in now.items())


def shown_file(identity: dict[str, Any]) -> dict[str, Any]:
    """A bound file as the approval card shows it: path, size, sha256."""
    return {"path": identity.get("path"), "size": identity.get("size"), "sha256": identity.get("sha256")}


def _command_name(token: str) -> str:
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


# ── Piper ────────────────────────────────────────────────────────────────────────────

_PIPER_LOCK = threading.Lock()
_PIPER_CLASS: Any = None
_PIPER_BROKEN = False


def _piper_spec() -> bool:
    """Whether a ``piper`` package is installed (a module lookup, nothing imported)."""
    try:
        return importlib.util.find_spec("piper") is not None
    except (ImportError, ValueError):
        return False


def _import_piper():
    """``PiperVoice`` from the piper-tts package, or None (a seam tests replace).

    Imported once and cached (it pulls onnxruntime and numpy): callers reach it from a
    worker thread (``speak_piper``, the capabilities probe), never the event loop. A
    package that is installed but does not import stays refused until a restart."""
    global _PIPER_CLASS, _PIPER_BROKEN
    with _PIPER_LOCK:
        if _PIPER_CLASS is not None:
            return _PIPER_CLASS
        if _PIPER_BROKEN or not _piper_spec():
            return None
        try:
            from piper import PiperVoice  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001 — broken: the binary, or nothing
            _PIPER_BROKEN = True
            return None
        _PIPER_CLASS = PiperVoice
        return PiperVoice


def piper_backend(*, load: bool = True) -> tuple[str, Any] | None:
    """``("package", PiperVoice)``, ``("binary", absolute path)``, or None.

    The binary is a program found on ``PATH``, so it is off in safe mode; the in-process
    package stays on. A custom Piper location is a TTS command (the command gate).
    ``load=False`` is the probe for an availability report on the event loop: the package
    counts when it is installed (``("package", None)``), without importing it."""
    if load:
        voice_cls = _import_piper()
        if voice_cls is not None:
            return "package", voice_cls
    elif _PIPER_CLASS is not None or (not _PIPER_BROKEN and _piper_spec()):
        return "package", None
    found = shutil.which("piper")
    if not found:
        return None
    exe, _why = trusted_program(os.path.abspath(found))
    if exe is None:
        return None
    if _safe_mode_on("voice_piper_binary"):
        return None
    return "binary", exe


def piper_model_dir() -> Path:
    """``voice.piper_model_dir``, or ``<data>/voice/piper`` when it is empty."""
    configured = _setting("piper_model_dir", "")
    if isinstance(configured, str) and configured.strip() and os.path.isabs(configured.strip()):
        return Path(configured.strip())
    from agents.core.paths import data_path

    return data_path("voice", "piper")


def valid_model_name(name: Any) -> bool:
    return isinstance(name, str) and bool(MODEL_RE.match(name)) and ".." not in name


def resolve_piper_model(name: Any, model_dir: Path | None = None) -> tuple[Path, Path] | None:
    """``(model .onnx, config .onnx.json)`` for *name* in the model directory, both regular
    files that resolve inside it, else None."""
    if not valid_model_name(name):
        return None
    base = model_dir or piper_model_dir()
    try:
        root = base.resolve(strict=True)
        model = (base / f"{name}.onnx").resolve(strict=True)
        config = (base / f"{name}.onnx.json").resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    for path in (model, config):
        if not path.is_relative_to(root) or not path.is_file():
            return None
    return model, config


def _model_names(model_dir: Path | None = None) -> list[str]:
    base = model_dir or piper_model_dir()
    names: list[str] = []
    try:
        with os.scandir(base) as entries:
            for n, entry in enumerate(entries):
                if n >= MAX_MODEL_LISTING:
                    break
                if entry.name.endswith(".onnx"):
                    names.append(entry.name[: -len(".onnx")])
    except OSError:
        return []
    return sorted(name for name in names if resolve_piper_model(name, base) is not None)


def list_piper_voices(model_dir: Path | None = None) -> list[str]:
    """``["piper:<model>", ...]`` for every usable model in the directory."""
    return [f"piper:{name}" for name in _model_names(model_dir)]


_MODEL_LANG_RE = re.compile(r"^([a-z]{2,3})_[A-Za-z]{2}\b")


def model_lang(voice: Any) -> str | None:
    """The language a Piper model's name starts with: ``ro`` for ``ro_RO-mihai-medium``
    (or ``piper:ro_RO-…``), else None."""
    if not isinstance(voice, str):
        return None
    name = voice.split(":", 1)[1] if voice.lower().startswith("piper:") else voice
    match = _MODEL_LANG_RE.match(name.strip())
    return match.group(1) if match else None


def _persona_flagged(name: str) -> bool:
    """Whether the persona/cloned-voice consent gate would flag ``piper:<name>``."""
    from .tts import is_persona_or_cloned_voice

    return is_persona_or_cloned_voice(f"piper:{name}")


def pick_piper_model(lang: Any, model_dir: Path | None = None, *, allow_persona: bool = False) -> str | None:
    """The first model whose name starts with ``<lang>_`` (``ro`` → ``ro_RO-…``), else the
    first model, else None. A model the persona/cloned-voice consent gate would flag is
    never picked unless *allow_persona* (the owner's consent is granted)."""
    names = [name for name in _model_names(model_dir) if allow_persona or not _persona_flagged(name)]
    if not names:
        return None
    primary = safe_lang(lang, "").split("-", 1)[0] if isinstance(lang, str) else ""
    for name in names:
        if primary and name.lower().startswith(f"{primary}_"):
            return name
    return names[0]


def piper_status(*, load: bool = True) -> dict[str, Any]:
    """Whether Piper can speak (a backend and at least one model), how, and its voices.
    ``load=False``: the probe that never imports the package (see :func:`piper_backend`)."""
    backend = piper_backend(load=load)
    voices = list_piper_voices() if backend is not None else []
    return {"available": bool(backend and voices), "via": backend[0] if backend else None, "voices": voices}


_PKG_SLOT = threading.BoundedSemaphore(1)
_PKG_CACHE: OrderedDict[tuple[str, int], Any] = OrderedDict()
_PKG_CACHE_MAX = 2


class _SlotHandoff:
    """Who releases ``_PKG_SLOT``: the worker once it starts (a runaway synthesis keeps the
    slot until it ends), or the caller when the job never started (it was cancelled or
    timed out while queued in the executor, so the worker will never run)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = "queued"                       # queued → running | abandoned


def _synth_pkg(voice_cls: Any, model: Path, config: Path, line: str, out: Path,
               handoff: _SlotHandoff | None = None) -> None:
    """Synthesize *line* to *out* with the package (runs in a worker thread)."""
    if handoff is not None:
        with handoff.lock:
            if handoff.state == "abandoned":        # the caller gave up and released the slot
                return
            handoff.state = "running"
    try:
        key = (str(model), os.stat(model).st_mtime_ns)
        voice = _PKG_CACHE.get(key)
        if voice is None:
            voice = voice_cls.load(str(model), config_path=str(config))
            _PKG_CACHE[key] = voice
            while len(_PKG_CACHE) > _PKG_CACHE_MAX:
                _PKG_CACHE.popitem(last=False)
        synth = getattr(voice, "synthesize_wav", None) or voice.synthesize
        with wave.open(str(out), "wb") as wav_file:
            synth(line, wav_file)
    finally:
        _PKG_SLOT.release()


def _piper_target(voice: Any, lang: Any, allow_persona: bool) -> tuple[str, tuple[Path, Path] | None]:
    """The model a Piper voice names (bare ``piper``: the one for *lang*), resolved."""
    name = voice.split(":", 1)[1] if isinstance(voice, str) and ":" in voice else ""
    if not name:
        name = pick_piper_model(lang, allow_persona=allow_persona) or ""
    return name, resolve_piper_model(name)


async def speak_piper(text: str, voice: str, lang: Any, *, temp_dir: Path,
                      allow_persona: bool = False) -> str | None:
    """Synthesize *text* with Piper; the audio's path, or None (the caller falls back).

    The package import, the model listing and the lookup run in a worker thread. Bare
    ``piper`` never picks a model the consent gate would flag unless *allow_persona*."""
    backend = await asyncio.to_thread(piper_backend)
    if backend is None:
        return None
    name, resolved = await asyncio.to_thread(_piper_target, voice, lang, allow_persona)
    if resolved is None:
        _log_once(f"piper_model:{name[:64]!r}", "voice: no usable Piper model for that voice; using the default voice")
        return None
    model, config = resolved
    # --output_file rewrites the file once per stdin line: one line, so nothing is lost.
    line = " ".join(str(text).split())
    if not line or len(line.encode("utf-8")) > MAX_TEXT_BYTES:
        return None
    async with private_workdir(temp_dir) as workdir:
        if workdir is None:
            return None
        out = workdir / "out.wav"
        if backend[0] == "package":
            if not _PKG_SLOT.acquire(blocking=False):   # a runaway synthesis still holds it
                logger.warning("voice: piper (package) is still busy; falling back")
                return None
            handoff = _SlotHandoff()
            try:
                await asyncio.wait_for(asyncio.to_thread(_synth_pkg, backend[1], model, config, line, out, handoff),
                                       timeout=timeout_for(TTS_TIMEOUT_S))
            except TimeoutError:
                logger.warning("voice: piper (package) timed out; falling back")
                return None
            except Exception as exc:  # noqa: BLE001 — a broken model is a fallback, not a crash
                logger.warning("voice: piper (package) failed (%s); falling back", type(exc).__name__)
                return None
            finally:                                    # every path, a cancel included
                with handoff.lock:
                    if handoff.state == "queued":       # it never started: nobody else releases it
                        handoff.state = "abandoned"
                        _PKG_SLOT.release()
        else:
            argv = [str(backend[1]), "--model", str(model), "--config", str(config), "--output_file", str(out)]
            run = await run_bounded(argv, cwd=workdir, stdin_bytes=(line + "\n").encode("utf-8"),
                                    timeout=timeout_for(TTS_TIMEOUT_S))
            if not run["ok"]:
                logger.warning("voice: piper failed (%s); falling back", run["reason"])
                return None
        path, why = claim_output(out, workdir, temp_dir, "piper")
        if path is None or not path.endswith(".wav"):
            if path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(path)
            logger.warning("voice: piper output refused (%s); falling back", why or "not_wav")
            return None
        return path


# ── command providers ────────────────────────────────────────────────────────────────

def _inspect(argv: Any, side: str) -> tuple[list[str], Path | None, Path | None]:
    """``(problems, the resolved program, the resolved script an interpreter runs)``."""
    from agents.core.environments.terminal_contract import hardline_match
    from agents.core.settings_db import _looks_like_credential

    if side not in SIDE_PLACEHOLDERS:
        return ["side: tts or stt"], None, None
    shape = _argv_problem(argv)
    if shape is not None:
        return [shape], None, None
    problems: list[str] = []
    program = argv[0]
    if "\n" in program or "\r" in program:
        problems.append("argv[0]: the program name holds a line break")
    if "{" in program or "}" in program:
        problems.append("argv[0]: a placeholder cannot be (or be inside) the program name")
    exe: Path | None = None
    script_path: Path | None = None
    if not problems:
        exe, why = trusted_program(program)
        if exe is None:
            problems.append(f"argv[0]: {why}")
    names = {_command_name(program)} | ({_command_name(str(exe))} if exe is not None else set())
    launchers = sorted((names & LAUNCHERS) | {name for name in names if _LAUNCHER_RE.match(name)})
    if launchers:
        problems.append(f"argv[0]: {launchers[0]} runs other programs, command lines or code from its "
                        "arguments (a shell or a launcher is never a provider)")
    elif any(_INTERPRETER_RE.match(name) for name in names):
        # For an interpreter, argv[1] is the program that actually runs: bound like argv[0].
        script = argv[1] if len(argv) > 1 else ""
        if not script or script.startswith("-") or "{" in script or not os.path.isabs(script):
            problems.append("argv[1]: an interpreter runs only a script file named by absolute path "
                            "(no -c / -e inline code)")
        else:
            script_path, why = trusted_program(script, executable=False, what="the script")
            if script_path is None:
                problems.append(f"argv[1]: {why}")
    for n, item in enumerate(argv[1:], start=1):
        if ("/" in item or "\\" in item) and _command_name(item) in SHELLS:
            problems.append(f"argv[{n}]: names a shell ({_command_name(item)}); a provider never hands its "
                            "work to one")
    allowed, required = SIDE_PLACEHOLDERS[side]
    seen: dict[str, int] = {}
    for n, item in enumerate(argv[1:], start=1):
        if item in PLACEHOLDERS:
            if item not in allowed:
                problems.append(f"argv[{n}]: {item} is not a {side} placeholder ({', '.join(sorted(allowed))})")
            seen[item] = seen.get(item, 0) + 1
        elif "{" in item or "}" in item:
            problems.append(f"argv[{n}]: embedded_or_unknown_placeholder — a placeholder is a whole "
                            f"element, one of {', '.join(sorted(allowed))}")
    if seen.get(required, 0) != 1:
        problems.append(f"{required} must appear exactly once")
    for name, count in seen.items():
        if name != "{lang}" and name != required and count > 1:
            problems.append(f"{name} may appear at most once")
    hit = hardline_match(list(argv))
    if hit is not None:
        problems.append(f"hardline_denied:{hit}")
    # The program and a file that exists are paths, not keys (a long path reads as entropy).
    if any(_looks_like_credential(item) for item in argv[1:]
           if item not in PLACEHOLDERS and not (os.path.isabs(item) and os.path.exists(item))):
        problems.append("a command line is visible to every process on this host; put the key in the "
                        "program's own config")
    if problems:
        return problems, None, None
    return problems, exe, script_path


def validate_command(argv: Any, side: str) -> tuple[list[str], Path | None]:
    """Every reason *argv* is not a runnable *side* command (``[]`` when it is), and the
    resolved program. The route, the approved apply and every spawn call this."""
    problems, exe, _script = _inspect(argv, side)
    return problems, exe


def bound_files(argv: Any, side: str) -> list[Path] | None:
    """The files a valid *argv* runs, resolved: the program, then (for an interpreter) the
    script. None when *argv* is not a valid command. The approval binds each one."""
    problems, exe, script = _inspect(argv, side)
    if problems or exe is None:
        return None
    return [exe] + ([script] if script is not None else [])


def bound_identities(files: list[Path]) -> list[dict[str, Any]] | None:
    """:func:`file_identity` of every bound file (with its digest), or None when one is
    unreadable, over 64 MiB or changed while it was read."""
    identities = [file_identity(path) for path in files]
    return None if any(identity is None for identity in identities) else identities  # type: ignore[return-value]


@dataclass(frozen=True)
class Ready:
    ok: bool
    reason: str | None
    argv: tuple[str, ...] = ()
    exe: Path | None = None
    problems: tuple[str, ...] = field(default_factory=tuple)
    #: Every bound file, resolved: the program, then an interpreter's script.
    files: tuple[Path, ...] = ()


def stored_command(side: str) -> dict[str, Any]:
    value = _setting(f"{side}_command", {})
    return value if isinstance(value, dict) else {}


def command_ready(side: str, *, verify_content: bool = True) -> Ready:
    """Whether the approved *side* command may run now (read fresh, every spawn): the argv
    still valid, its fingerprint the approved one, and every bound file — the program and
    an interpreter's script — the file approved, down to the sha256 of its content.

    ``verify_content=False`` skips the digests (the stat identity is still compared): the
    cheap probe an availability report uses on the event loop. A spawn never uses it."""
    from agents.core.environments.terminal_contract import argv_fingerprint

    value = stored_command(side)
    argv = value.get("argv")
    if not value or not argv:
        return Ready(False, NOT_CONFIGURED)
    if not armed():
        return _not_ready(side, NOT_ARMED)
    if _safe_mode_on("voice_commands"):
        return _not_ready(side, SAFE_MODE)
    problems, exe, script = _inspect(argv, side)
    if problems or exe is None:
        if any("does not exist" in p for p in problems):
            return _not_ready(side, EXE_MISSING, problems)
        return _not_ready(side, INVALID, problems)
    if argv_fingerprint(argv) != value.get("fingerprint"):
        return _not_ready(side, FINGERPRINT_MISMATCH)
    files = [exe] + ([script] if script is not None else [])
    recorded = value.get("bound")
    if not isinstance(recorded, list) or len(recorded) != len(files):
        return _not_ready(side, CHANGED_SINCE_APPROVAL)
    for path, then in zip(files, recorded, strict=True):
        if not _same_identity(then, file_identity(path, content=verify_content)):
            return _not_ready(side, CHANGED_SINCE_APPROVAL)
    return Ready(True, None, tuple(argv), exe, files=tuple(files))


def _not_ready(side: str, reason: str, problems: list[str] | None = None) -> Ready:
    _log_once(f"{side}:{reason}", "voice: the %s command provider is not used (%s)", side, reason)
    return Ready(False, reason, problems=tuple(problems or ()))


def command_status(side: str) -> dict[str, Any]:
    value = stored_command(side)
    ready = command_ready(side)
    return {"configured": bool(value.get("argv")), "ready": ready.ok, "reason": ready.reason}


def _substitute(ready: Ready, values: dict[str, str]) -> list[str]:
    """The argv to spawn: the checked program path, the checked script path (an
    interpreter's argv[1]), then the rest with the placeholders filled in."""
    head = [str(path) for path in ready.files] if ready.files else [str(ready.exe)]
    rest = ready.argv[len(head):]
    return head + [values.get(item, item) if item in PLACEHOLDERS else item for item in rest]


def _recheck(side: str, ready: Ready, values: dict[str, str]):
    """The ``prepare`` of :func:`run_bounded`: the command checked again once the slot is
    held (every bound file, digest included), and the argv of *that* check, or None."""
    async def prepare() -> list[str] | None:
        fresh = await asyncio.to_thread(command_ready, side)
        if not fresh.ok or fresh.argv != ready.argv:
            logger.warning("voice: the %s command changed while it waited to run (%s); not run",
                           side, fresh.reason or "argv")
            return None
        return _substitute(fresh, values)
    return prepare


async def speak_command(text: str, lang: Any, *, temp_dir: Path, default_lang: str = "en") -> str | None:
    """Synthesize *text* with the approved TTS command; the audio's path, or None."""
    ready = await asyncio.to_thread(command_ready, "tts")
    if not ready.ok:
        return None
    data = str(text).encode("utf-8")
    if not data or len(data) > MAX_TEXT_BYTES:
        return None
    async with private_workdir(temp_dir) as workdir:
        if workdir is None:
            return None
        out = workdir / "out.wav"
        values = {"{output}": str(out), "{lang}": safe_lang(lang, default_lang)}
        stdin: bytes | None = data
        if "{text_file}" in ready.argv:
            text_file = workdir / "text.txt"
            _write_private(text_file, data)
            values["{text_file}"] = str(text_file)
            stdin = None
        run = await run_bounded(_substitute(ready, values), cwd=workdir, stdin_bytes=stdin,
                                timeout=timeout_for(TTS_TIMEOUT_S), prepare=_recheck("tts", ready, values))
        if not run["ok"]:
            logger.warning("voice: the TTS command failed (%s); falling back", run["reason"])
            return None
        path, why = claim_output(out, workdir, temp_dir, "command")
        if path is None:
            logger.warning("voice: the TTS command's output was refused (%s); falling back", why)
        return path


def _read_audio(audio: Any) -> bytes | None:
    """The recording's bytes (a copy: ``{audio}`` always lives in the run directory)."""
    if isinstance(audio, (bytes, bytearray, memoryview)):
        data = bytes(audio)
    elif isinstance(audio, (str, os.PathLike)):
        try:
            with open(audio, "rb") as fh:
                data = fh.read(MAX_AUDIO_IN_BYTES + 1)
        except OSError:
            return None
    elif callable(getattr(audio, "read", None)):
        data = audio.read(MAX_AUDIO_IN_BYTES + 1)
        if not isinstance(data, (bytes, bytearray)):
            return None
        data = bytes(data)
    else:
        return None
    return data if 0 < len(data) <= MAX_AUDIO_IN_BYTES else None


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
#: whisper.cpp's segment prefix, ``[00:00:00.000 --> 00:00:02.500]`` (printed without ``-nt``).
_TIMESTAMP_RE = re.compile(r"^\s*\[\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?\s*-->\s*"
                           r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?\s*\]\s*")
#: whisper.cpp's marker for a stretch with no speech.
_BLANK_AUDIO_RE = re.compile(r"\[\s*BLANK_AUDIO\s*\]", re.IGNORECASE)


def is_stt_sentinel(text: Any) -> bool:
    """Whether a transcript is an engine sentinel, not speech: exactly ``[silence]``, or
    ``[STT error…]`` / ``[STT unavailable…]``. Other bracketed text (``[laughs] hi``) is
    what was said."""
    if not isinstance(text, str):
        return False
    t = text.strip()
    if t == "[silence]":
        return True
    return t.endswith("]") and (t.startswith("[STT error") or t.startswith("[STT unavailable"))


def _transcript(stdout: bytes) -> str:
    """The command's stdout as one line of text: whisper.cpp timestamps and blank-audio
    markers dropped, control characters gone, whitespace collapsed, capped."""
    lines = [_TIMESTAMP_RE.sub("", line) for line in stdout.decode("utf-8", errors="replace").splitlines()]
    text = _BLANK_AUDIO_RE.sub(" ", _CONTROL_RE.sub(" ", " ".join(lines)))
    return " ".join(text.split())[:MAX_TRANSCRIPT_CHARS]


async def transcribe_command(audio: Any, language: Any, *, temp_dir: Path, default_lang: str = "en") -> str:
    """Transcribe with the approved STT command: the text, or one of the STT sentinels."""
    from agents.core.voice.hallucination import is_hallucination

    ready = await asyncio.to_thread(command_ready, "stt")
    if not ready.ok:
        return "[STT unavailable]"
    data = _read_audio(audio)
    if data is None:
        return "[STT error: no audio]"
    async with private_workdir(temp_dir) as workdir:
        if workdir is None:
            return "[STT unavailable]"
        audio_path = workdir / f"audio{sniff_input_audio(data[:16])}"
        _write_private(audio_path, data)
        values = {"{audio}": str(audio_path), "{lang}": safe_lang(language, default_lang)}
        run = await run_bounded(_substitute(ready, values), cwd=workdir, stdin_bytes=None,
                                timeout=timeout_for(STT_TIMEOUT_S), prepare=_recheck("stt", ready, values))
    if run["timed_out"]:
        return "[STT error: command timed out]"
    if not run["ok"]:
        if run["returncode"] is None:
            return f"[STT error: command {run['reason']}]"
        return f"[STT error: command exited {run['returncode']}]"
    text = _transcript(run["stdout"])
    if not text or is_hallucination(text, audio_seconds=None):
        return "[silence]"
    return text


def stt_mode() -> str:
    value = _setting("stt_engine", "auto")
    return value if value in ("auto", "whisper", "command") else "auto"


def stt_available(has_whisper: bool) -> bool:
    """Whether speech can be transcribed as ``voice.stt_engine`` asks: ``whisper`` only
    Whisper, ``command`` only the approved command, ``auto`` either (a cheap probe: the
    spawn checks the command again, digests included)."""
    mode = stt_mode()
    if mode == "whisper":
        return bool(has_whisper)
    command = command_ready("stt", verify_content=False).ok
    return command if mode == "command" else bool(has_whisper or command)


def local_only() -> bool:
    """``voice.local_only``: speech stays on this machine (Piper, Kokoro or XTTS). The TTS
    command is never run then: the hub cannot check where a command sends the text."""
    return bool(_setting("local_only", False))


__all__ = [
    "ARM_ENV", "MAX_AUDIO_OUT_BYTES", "MAX_BOUND_FILE_BYTES", "MAX_TEXT_BYTES", "Ready", "STT_TIMEOUT_S",
    "TIMEOUT_ENV", "TTS_TIMEOUT_S", "armed", "bound_files", "bound_identities", "claim_output", "command_ready",
    "command_status", "exe_identity", "file_identity", "is_stt_sentinel", "list_piper_voices", "local_only",
    "model_lang", "pick_piper_model", "piper_backend", "piper_model_dir", "piper_status", "private_workdir",
    "resolve_piper_model", "run_bounded", "safe_lang", "shown_file", "sniff_audio", "speak_command",
    "speak_piper", "stored_command", "stt_available", "stt_mode", "transcribe_command", "trusted_program",
    "validate_command",
]
