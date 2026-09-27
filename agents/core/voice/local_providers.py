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
    fingerprint and the executable identity (device, inode, size, mtime) recorded at
    approval: a replaced or upgraded binary needs approving again.

Every run is ``create_subprocess_exec`` with an argv list — never a shell — in a private
0700 run directory under the TTS temp dir, with a scrubbed environment, one deadline over
stdin, output and exit, and capped stdout/stderr. The text to speak never enters argv: it
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
import logging
import os
import re
import shutil
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

LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

SIDES = ("tts", "stt")
PLACEHOLDERS = frozenset({"{text_file}", "{output}", "{audio}", "{lang}"})
#: side → (placeholders allowed, the one that must appear exactly once)
SIDE_PLACEHOLDERS: dict[str, tuple[frozenset[str], str]] = {
    "tts": (frozenset({"{text_file}", "{output}", "{lang}"}), "{output}"),
    "stt": (frozenset({"{audio}", "{lang}"}), "{audio}"),
}
#: A program that runs another program or a command line: never a provider. Mirrors the
#: shell heads of ``environments/terminal_contract`` (private there) plus the launchers
#: that would hide what actually runs.
LAUNCHERS = frozenset({
    "sh", "bash", "dash", "zsh", "ksh", "mksh", "ash", "rbash", "fish", "csh", "tcsh", "busybox",
    "cmd", "powershell", "pwsh", "env", "sudo", "doas", "su", "pkexec", "runuser", "xargs",
    "nohup", "setsid", "timeout", "nice", "ionice", "stdbuf", "chroot", "unshare", "nsenter",
    "script", "taskset", "chrt", "flock", "watch", "exec", "eval", "ssh", "open", "start",
})
#: Interpreters take inline code (``-c``, ``-e``, ``--eval``): allowed only running a script
#: file named by absolute path right after them.
_INTERPRETER_RE = re.compile(
    r"^(python[0-9.]*w?|pypy[0-9.]*|perl[0-9.]*|ruby[0-9.]*|node(js)?|deno|bun|php[0-9.]*|lua[0-9.]*|luajit"
    r"|rscript|osascript|wscript|cscript|tclsh[0-9.]*|wish[0-9.]*|julia|java)$")

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


async def _kill(proc: Any) -> None:
    with contextlib.suppress(ProcessLookupError, OSError):
        proc.kill()
    with contextlib.suppress(TimeoutError, OSError):
        await asyncio.wait_for(proc.wait(), timeout=5)


async def run_bounded(argv: list[str], *, cwd: Path, stdin_bytes: bytes | None, timeout: float) -> dict[str, Any]:
    """Run *argv* (no shell) in *cwd* under one deadline; never raises for a process failure.

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
    result["argv_sha256"] = argv_fingerprint(argv)
    async with _slot():
        try:
            proc = await _spawn(
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd), env=scrub_child_env(os.environ),
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

def trusted_program(path: str | os.PathLike) -> tuple[Path | None, str | None]:
    """The resolved program at *path*, when it is an absolute, existing, executable
    regular file that neither it nor its directory lets anyone write: ``(path, None)``,
    else ``(None, why)``."""
    raw = os.fspath(path)
    if not os.path.isabs(raw):
        return None, "the program must be an absolute path"
    try:
        exe = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "the program does not exist"
    try:
        info = os.stat(exe)
        parent = os.stat(exe.parent)
    except OSError:
        return None, "the program does not exist"
    if not stat.S_ISREG(info.st_mode):
        return None, "the program is not a regular file"
    if not os.access(exe, os.X_OK):
        return None, "the program is not executable"
    if info.st_mode & stat.S_IWOTH or parent.st_mode & stat.S_IWOTH:
        return None, "the program or its directory is writable by every user"
    return exe, None


def exe_identity(exe: Path) -> dict[str, Any] | None:
    """What the approval binds to: the path and ``(dev, ino, size, mtime_ns)``."""
    try:
        info = os.stat(exe)
    except OSError:
        return None
    return {"path": str(exe), "dev": int(info.st_dev), "ino": int(info.st_ino),
            "size": int(info.st_size), "mtime_ns": int(info.st_mtime_ns)}


def _command_name(token: str) -> str:
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


# ── Piper ────────────────────────────────────────────────────────────────────────────

def _import_piper():
    """``PiperVoice`` from the piper-tts package, or None (a seam tests replace)."""
    try:
        from piper import PiperVoice  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 — absent or broken: the binary, or nothing
        return None
    return PiperVoice


def piper_backend() -> tuple[str, Any] | None:
    """``("package", PiperVoice)``, ``("binary", absolute path)``, or None.

    The binary is a program found on ``PATH``, so it is off in safe mode; the in-process
    package stays on. A custom Piper location is a TTS command (the command gate)."""
    voice_cls = _import_piper()
    if voice_cls is not None:
        return "package", voice_cls
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


def pick_piper_model(lang: Any, model_dir: Path | None = None) -> str | None:
    """The first model whose name starts with ``<lang>_`` (``ro`` → ``ro_RO-…``), else the
    first model, else None."""
    names = _model_names(model_dir)
    if not names:
        return None
    primary = safe_lang(lang, "").split("-", 1)[0] if isinstance(lang, str) else ""
    for name in names:
        if primary and name.lower().startswith(f"{primary}_"):
            return name
    return names[0]


def piper_status() -> dict[str, Any]:
    backend = piper_backend()
    voices = list_piper_voices() if backend is not None else []
    return {"available": bool(backend and voices), "via": backend[0] if backend else None, "voices": voices}


_PKG_SLOT = threading.BoundedSemaphore(1)
_PKG_CACHE: OrderedDict[tuple[str, int], Any] = OrderedDict()
_PKG_CACHE_MAX = 2


def _synth_pkg(voice_cls: Any, model: Path, config: Path, line: str, out: Path) -> None:
    """Synthesize *line* to *out* with the package (runs in a worker thread)."""
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


async def speak_piper(text: str, voice: str, lang: Any, *, temp_dir: Path) -> str | None:
    """Synthesize *text* with Piper; the audio's path, or None (the caller falls back)."""
    backend = piper_backend()
    if backend is None:
        return None
    name = voice.split(":", 1)[1] if isinstance(voice, str) and ":" in voice else ""
    if not name:
        name = pick_piper_model(lang) or ""
    resolved = resolve_piper_model(name)
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
            try:
                await asyncio.wait_for(asyncio.to_thread(_synth_pkg, backend[1], model, config, line, out),
                                       timeout=timeout_for(TTS_TIMEOUT_S))
            except TimeoutError:
                logger.warning("voice: piper (package) timed out; falling back")
                return None
            except Exception as exc:  # noqa: BLE001 — a broken model is a fallback, not a crash
                logger.warning("voice: piper (package) failed (%s); falling back", type(exc).__name__)
                return None
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

def validate_command(argv: Any, side: str) -> tuple[list[str], Path | None]:
    """Every reason *argv* is not a runnable *side* command (``[]`` when it is), and the
    resolved program. The route, the approved apply and every spawn call this."""
    from agents.core.environments.terminal_contract import hardline_match
    from agents.core.settings_db import _looks_like_credential

    if side not in SIDE_PLACEHOLDERS:
        return ["side: tts or stt"], None
    shape = _argv_problem(argv)
    if shape is not None:
        return [shape], None
    problems: list[str] = []
    program = argv[0]
    if "\n" in program or "\r" in program:
        problems.append("argv[0]: the program name holds a line break")
    if "{" in program or "}" in program:
        problems.append("argv[0]: a placeholder cannot be (or be inside) the program name")
    exe: Path | None = None
    if not problems:
        exe, why = trusted_program(program)
        if exe is None:
            problems.append(f"argv[0]: {why}")
    names = {_command_name(program)} | ({_command_name(str(exe))} if exe is not None else set())
    if names & LAUNCHERS:
        problems.append(f"argv[0]: {sorted(names & LAUNCHERS)[0]} runs other programs or command lines "
                        "(a shell or a launcher is never a provider)")
    elif any(_INTERPRETER_RE.match(name) for name in names):
        script = argv[1] if len(argv) > 1 else ""
        if not (os.path.isabs(script) and os.path.isfile(script) and "{" not in script):
            problems.append("argv[1]: an interpreter runs only a script file named by absolute path "
                            "(no -c / -e inline code)")
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
    return problems, (exe if not problems else None)


@dataclass(frozen=True)
class Ready:
    ok: bool
    reason: str | None
    argv: tuple[str, ...] = ()
    exe: Path | None = None
    problems: tuple[str, ...] = field(default_factory=tuple)


def stored_command(side: str) -> dict[str, Any]:
    value = _setting(f"{side}_command", {})
    return value if isinstance(value, dict) else {}


def command_ready(side: str) -> Ready:
    """Whether the approved *side* command may run now (read fresh, every spawn)."""
    from agents.core.environments.terminal_contract import argv_fingerprint

    value = stored_command(side)
    argv = value.get("argv")
    if not value or not argv:
        return Ready(False, NOT_CONFIGURED)
    if not armed():
        return _not_ready(side, NOT_ARMED)
    if _safe_mode_on("voice_commands"):
        return _not_ready(side, SAFE_MODE)
    problems, exe = validate_command(argv, side)
    if problems or exe is None:
        if any("does not exist" in p for p in problems):
            return _not_ready(side, EXE_MISSING, problems)
        return _not_ready(side, INVALID, problems)
    if argv_fingerprint(argv) != value.get("fingerprint"):
        return _not_ready(side, FINGERPRINT_MISMATCH)
    identity, recorded = exe_identity(exe), value.get("exe")
    if identity is None or not isinstance(recorded, dict) or any(
            recorded.get(k) != identity[k] for k in ("path", "dev", "ino", "size", "mtime_ns")):
        return _not_ready(side, CHANGED_SINCE_APPROVAL)
    return Ready(True, None, tuple(argv), exe)


def _not_ready(side: str, reason: str, problems: list[str] | None = None) -> Ready:
    _log_once(f"{side}:{reason}", "voice: the %s command provider is not used (%s)", side, reason)
    return Ready(False, reason, problems=tuple(problems or ()))


def command_status(side: str) -> dict[str, Any]:
    value = stored_command(side)
    ready = command_ready(side)
    return {"configured": bool(value.get("argv")), "ready": ready.ok, "reason": ready.reason}


def _substitute(ready: Ready, values: dict[str, str]) -> list[str]:
    return [str(ready.exe)] + [values.get(item, item) if item in PLACEHOLDERS else item for item in ready.argv[1:]]


async def speak_command(text: str, lang: Any, *, temp_dir: Path, default_lang: str = "en") -> str | None:
    """Synthesize *text* with the approved TTS command; the audio's path, or None."""
    ready = command_ready("tts")
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
                                timeout=timeout_for(TTS_TIMEOUT_S))
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


async def transcribe_command(audio: Any, language: Any, *, temp_dir: Path, default_lang: str = "en") -> str:
    """Transcribe with the approved STT command: the text, or one of the STT sentinels."""
    from agents.core.voice.hallucination import is_hallucination

    ready = command_ready("stt")
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
                                timeout=timeout_for(STT_TIMEOUT_S))
    if run["timed_out"]:
        return "[STT error: command timed out]"
    if not run["ok"]:
        if run["returncode"] is None:
            return f"[STT error: command {run['reason']}]"
        return f"[STT error: command exited {run['returncode']}]"
    text = _CONTROL_RE.sub(" ", run["stdout"].decode("utf-8", errors="replace"))
    text = " ".join(text.split())[:MAX_TRANSCRIPT_CHARS]
    if not text or is_hallucination(text, audio_seconds=None):
        return "[silence]"
    return text


def stt_mode() -> str:
    value = _setting("stt_engine", "auto")
    return value if value in ("auto", "whisper", "command") else "auto"


def local_only() -> bool:
    return bool(_setting("local_only", False))


__all__ = [
    "ARM_ENV", "MAX_AUDIO_OUT_BYTES", "MAX_TEXT_BYTES", "Ready", "STT_TIMEOUT_S", "TIMEOUT_ENV", "TTS_TIMEOUT_S",
    "armed", "claim_output", "command_ready", "command_status", "exe_identity", "list_piper_voices",
    "local_only", "pick_piper_model", "piper_backend", "piper_model_dir", "piper_status", "private_workdir",
    "resolve_piper_model", "run_bounded", "safe_lang", "sniff_audio", "speak_command", "speak_piper",
    "stored_command", "stt_mode", "transcribe_command", "trusted_program", "validate_command",
]
