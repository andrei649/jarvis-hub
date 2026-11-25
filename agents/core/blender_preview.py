"""Bounded, native .blend library inventory from an installed Blender executable."""

from __future__ import annotations

import asyncio
import base64
import gzip
import io
import json
import os
import signal
import struct
import subprocess  # nosec B404: fixed trusted executable and argv
import sys
import tempfile
import time
import zlib
from pathlib import Path

from .env_config import env_str

MAX_BYTES = 64 * 1024 * 1024
CATEGORIES = ("scenes", "objects", "meshes", "materials", "collections", "cameras", "lights", "actions")
_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
_TIMEOUT_SECONDS = 25
_MAX_RESULT_BYTES = 256 * 1024
_MAX_THUMB_PREFIX = 2 * 1024 * 1024


class BlenderUnavailable(RuntimeError):
    """A trusted installed Blender runtime or process containment is unavailable."""


class BlenderPreviewError(ValueError):
    """The input cannot be safely previewed as a Blender library."""


def _blender_binary() -> Path | None:
    # The override is host configuration only; upload data never chooses an executable.
    configured = env_str("NERVA_BLENDER_EXECUTABLE")
    if configured:
        candidates = [Path(configured)]
    elif os.name == "nt":
        root = Path(env_str("PROGRAMFILES", r"C:\Program Files")) / "Blender Foundation"
        candidates = sorted(root.glob("Blender */blender.exe"), reverse=True)
    else:
        candidates = [Path("/usr/bin/blender"), Path("/usr/local/bin/blender"),
                      Path("/opt/blender/blender")]
    for candidate in candidates:
        if candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def _prefix(data: bytes) -> bytes:
    if data.startswith(b"BLENDER"):
        return data[:_MAX_THUMB_PREFIX]
    if data.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as source:
                return source.read(_MAX_THUMB_PREFIX)
        except (OSError, EOFError):
            return b""
    return b""


def _file_version(data: bytes) -> str | None:
    header = _prefix(data)[:17]
    if len(header) >= 17 and header.startswith(b"BLENDER17") and header[13:17].isdigit():
        return f"{int(header[13:15])}.{int(header[15:17])}"
    if len(header) >= 12 and header.startswith(b"BLENDER") and header[9:12].isdigit():
        return f"{int(header[9:10])}.{header[10:12].decode()}"
    return None


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def _thumbnail_png(data: bytes) -> str | None:
    prefix = _prefix(data)
    if not prefix.startswith(b"BLENDER") or len(prefix) < 12:
        return None
    if prefix.startswith(b"BLENDER17") and len(prefix) >= 17 and prefix[9:12] == b"-01":
        endian, block, offset = "<", struct.Struct("<4siQqq"), 17
        length_index = 3
    elif prefix[7:8] in (b"-", b"_") and prefix[8:9] in (b"v", b"V"):
        endian = "<" if prefix[8:9] == b"v" else ">"
        block = struct.Struct(endian + ("4siQii" if prefix[7:8] == b"-" else "4siIii"))
        offset, length_index = 12, 1
    else:
        return None
    while offset + block.size <= len(prefix):
        fields = block.unpack_from(prefix, offset)
        code, length = fields[0], fields[length_index]
        offset += block.size
        if length < 0 or offset + length > len(prefix):
            return None
        if code == b"TEST":
            if length < 12:
                return None
            width, height = struct.unpack_from(endian + "II", prefix, offset)
            if not (1 <= width <= 256 and 1 <= height <= 256 and length == 8 + width * height * 4):
                return None
            rgba = prefix[offset + 8:offset + length]
            scanlines = b"".join(b"\0" + rgba[row * width * 4:(row + 1) * width * 4]
                                 for row in range(height - 1, -1, -1))
            png = (b"\x89PNG\r\n\x1a\n"
                   + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                   + _png_chunk(b"IDAT", zlib.compress(scanlines)) + _png_chunk(b"IEND", b""))
            return base64.b64encode(png).decode("ascii")
        if code == b"ENDB":
            return None
        offset += length
    return None


def _clean_name(value: object) -> str:
    if not isinstance(value, str):
        raise BlenderPreviewError("invalid Blender inventory")
    return "".join(char if char.isprintable() else " " for char in value[:120])


def _format_inventory(inventory: dict, version: str | None) -> dict:
    if not isinstance(inventory, dict) or set(inventory) != set(CATEGORIES):
        raise BlenderPreviewError("invalid Blender inventory")
    segments = []
    overview = [f"Blender file version: {version}" if version else "Blender file version: unavailable"]
    for category in CATEGORIES:
        entry = inventory[category]
        if not isinstance(entry, dict) or type(entry.get("count")) is not int or entry["count"] < 0:
            raise BlenderPreviewError("invalid Blender inventory")
        names = entry.get("names")
        if not isinstance(names, list) or len(names) > 80 or entry["count"] < len(names):
            raise BlenderPreviewError("invalid Blender inventory")
        label = category.capitalize()
        overview.append(f"{label}: {entry['count']}")
        text = "\n".join(_clean_name(name) for name in names)
        segments.append({"label": label, "text": text, "truncated": entry["count"] > len(names)})
    return {"kind": "blend", "segments": [
        {"label": "Overview", "text": "\n".join(overview), "truncated": False}, *segments,
    ], "total_segments": 1 + len(CATEGORIES)}


def _child_env(scratch: Path, binary: Path) -> dict[str, str]:
    env = {"HOME": str(scratch), "USERPROFILE": str(scratch), "TMP": str(scratch),
           "TEMP": str(scratch), "TMPDIR": str(scratch), "PYTHONNOUSERSITE": "1",
           "BLENDER_USER_CONFIG": str(scratch), "BLENDER_USER_SCRIPTS": str(scratch),
           "BLENDER_USER_DATAFILES": str(scratch), "BLENDER_SYSTEM_SCRIPTS": "",
           "PATH": str(binary.parent) if os.name == "nt" else "/usr/bin:/bin"}
    if os.name == "nt":
        env["SystemRoot"] = env_str("SYSTEMROOT", r"C:\Windows")
        env["WINDIR"] = env["SystemRoot"]
    return env


def _run_posix(command: list[str], scratch: Path, env: dict[str, str]) -> None:
    # A fixed isolated Python launcher sets the limit before exec; preexec_fn can deadlock
    # when the hub has other threads.
    launcher = ("import os,resource,sys; n=int(sys.argv[1]); "
                "resource.setrlimit(resource.RLIMIT_AS,(n,n)); "
                "os.execve(sys.argv[2],sys.argv[2:],os.environ)")
    try:
        child = subprocess.Popen([sys.executable, "-I", "-S", "-c", launcher,
                                  str(_MEMORY_BYTES), *command],
                                 cwd=scratch, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)  # nosec B603
    except (OSError, subprocess.SubprocessError) as exc:
        raise BlenderUnavailable("Blender process containment unavailable") from exc
    try:
        if child.wait(timeout=_TIMEOUT_SECONDS) != 0:
            raise BlenderPreviewError("Blender refused the input")
    except subprocess.TimeoutExpired as exc:
        raise BlenderPreviewError("Blender preview timed out") from exc
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


async def _run_windows_job(command: list[str], scratch: Path, env: dict[str, str]) -> None:
    from agents.core.workspace.win_job_process import OwnedJobProcess

    try:
        owner = OwnedJobProcess.spawn(command, cwd=str(scratch), env=env, memory_limit=_MEMORY_BYTES)
    except OSError as exc:
        raise BlenderUnavailable("Windows Blender process containment unavailable") from exc
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    output_bytes = 0
    try:
        await owner.start_io()
        owner.writer.close()
        while not owner.api.wait_process(owner.process_handle, 0):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BlenderPreviewError("Blender preview timed out")
            try:
                chunk = await asyncio.wait_for(owner.reader.read(4096), min(remaining, 0.1))
                output_bytes += len(chunk)
                if output_bytes > 64 * 1024:
                    raise BlenderPreviewError("Blender output exceeded limit")
            except TimeoutError:
                pass
    finally:
        await owner.terminate_and_drain()


def preview_blend(data: bytes) -> dict:
    """Inventory approved datablock names without loading a Blender scene."""
    if not isinstance(data, bytes) or not (12 <= len(data) <= MAX_BYTES):
        raise BlenderPreviewError("invalid Blender input")
    if not (data.startswith(b"BLENDER") or data.startswith(b"\x1f\x8b")
            or data.startswith(b"\x28\xb5\x2f\xfd")):
        raise BlenderPreviewError("unsupported Blender input")
    binary = _blender_binary()
    if binary is None:
        raise BlenderUnavailable("trusted Blender executable unavailable")
    child_script = Path(__file__).with_name("_blender_preview_child.py")
    if not child_script.is_file():
        raise BlenderUnavailable("Blender inventory script unavailable")
    with tempfile.TemporaryDirectory(prefix="nerva-blend-") as tmp:
        scratch = Path(tmp)
        source = scratch / "input.blend"
        destination = scratch / "inventory.json"
        source.write_bytes(data)
        command = [str(binary), "--background", "--factory-startup", "--disable-autoexec",
                   "--offline-mode", "--python-exit-code", "1", "--python", str(child_script),
                   "--", str(source), str(destination)]
        try:
            if os.name == "nt":
                asyncio.run(_run_windows_job(command, scratch, _child_env(scratch, binary)))
            else:
                _run_posix(command, scratch, _child_env(scratch, binary))
            if not destination.is_file() or destination.stat().st_size > _MAX_RESULT_BYTES:
                raise BlenderPreviewError("Blender inventory unavailable")
            result = _format_inventory(json.loads(destination.read_text(encoding="utf-8")),
                                       _file_version(data))
            thumbnail = _thumbnail_png(data)
            if thumbnail is not None:
                result["thumbnail_png"] = thumbnail
            return result
        except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError) as exc:
            if isinstance(exc, (BlenderUnavailable, BlenderPreviewError)):
                raise
            raise BlenderPreviewError("Blender preview failed") from exc
