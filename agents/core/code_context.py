"""Backend-local H595 execution context and bounded project projection.

``CHILD_CONTEXT_SOURCE`` contains only stdlib code. A backend can evaluate it in
its own Python process, then call ``resolve_child_context`` with a context dict.
The host must pass backend paths; this module never selects a host environment
for a Docker child. ``prepare_project`` copies an owner-selected source tree to
a fresh sandbox directory, while avoiding secrets, links, and generated trees.
"""

from __future__ import annotations

import inspect
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

from .file_tools import FileScope, FileScopeError, looks_secret_name


class ProjectSnapshotError(ValueError):
    """A bounded public reason for refusing a project projection."""


def normalize_mode(mode):
    """Accept the two execution modes; absent config means project mode."""
    if mode is None or mode == "":
        return "project"
    if mode not in ("project", "strict"):
        raise ValueError("invalid_mode")
    return mode


def _native_python_probe(candidate, env):
    """Probe Python 3.8+ without a shell, inherited stdin, or secret environment."""
    import subprocess  # nosec B404 - bounded backend-local interpreter probe below

    safe_env = {key: value for key, value in env.items()
                if key in ("PATH", "SYSTEMROOT", "WINDIR") and isinstance(value, str)}
    try:
        result = subprocess.run(  # nosec B603 - host-approved backend interpreter, no shell, scrubbed env
            [candidate, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=5, env=safe_env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def resolve_child_context(context, *, probe=None):
    """Resolve cwd and Python using only paths visible in the calling backend.

    ``context`` has ``mode``, ``cwd``, ``staging_dir`` and ``env`` fields. Strict
    always uses staging and this process's interpreter. Project mode uses a
    valid explicit cwd, then staging, and tries VIRTUAL_ENV then CONDA_PREFIX.
    ``probe(path) -> bool`` is injectable for deterministic tests.
    """
    import os
    import sys

    if not isinstance(context, dict):
        raise ValueError("invalid_context")
    mode = normalize_mode(context.get("mode"))
    stage = context.get("staging_dir")
    if not isinstance(stage, str) or not os.path.isabs(stage) or not os.path.isdir(stage):
        raise ValueError("missing_staging_dir")
    stage = os.path.abspath(stage)
    if mode == "strict":
        return {"mode": mode, "cwd": stage, "python": sys.executable}
    requested = context.get("cwd")
    cwd = (os.path.abspath(requested)
           if isinstance(requested, str) and os.path.isabs(requested) and os.path.isdir(requested)
           else stage)
    env = context.get("env")
    if not isinstance(env, dict):
        env = {}
    checker = probe if probe is not None else lambda candidate: _native_python_probe(candidate, env)
    subdir, names = (("Scripts", ("python.exe", "python3.exe")) if os.name == "nt"
                     else ("bin", ("python", "python3")))
    for variable in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        prefix = env.get(variable)
        if not isinstance(prefix, str) or not os.path.isabs(prefix):
            continue
        for name in names:
            candidate = os.path.join(prefix, subdir, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK) and checker(candidate):
                return {"mode": mode, "cwd": cwd, "python": candidate}
    return {"mode": mode, "cwd": cwd, "python": sys.executable}


# Source is assembled from the functions above so the child and in-process
# resolver share one implementation. The child only needs Python's stdlib.
CHILD_CONTEXT_SOURCE = "\n".join((
    "import os\nimport sys\nimport subprocess\n",
    inspect.getsource(normalize_mode),
    inspect.getsource(_native_python_probe),
    inspect.getsource(resolve_child_context),
))


_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".graft", "graft", ".cache", ".tox", ".nox", ".next", "dist",
    "build", "vendor", "third_party", "site-packages", "tool_results",
    "rpc_staging", ".nerva-rpc",
})
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_DIR_FLAGS = _READ_FLAGS | getattr(os, "O_DIRECTORY", 0)


def _windows_project_handle(path: Path, *, directory: bool = False,
                            shared_writes: bool = False):
    """Open one Windows object without following its final reparse point."""
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    create = api.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = api.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    final_name = api.GetFinalPathNameByHandleW
    final_name.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    final_name.restype = wintypes.DWORD
    attributes = api.GetFileInformationByHandleEx
    attributes.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    attributes.restype = wintypes.BOOL

    class AttributeTagInfo(ctypes.Structure):
        _fields_ = (("attributes", wintypes.DWORD), ("tag", wintypes.DWORD))

    flags = 0x00200000 | (0x02000000 if directory else 0)  # OPEN_REPARSE_POINT, BACKUP_SEMANTICS
    share = 0x1 | (0x2 | 0x4 if shared_writes else 0)
    handle = create(str(path), 0x80000000, share, None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ProjectSnapshotError("source_changed")
    try:
        info = AttributeTagInfo()
        if not attributes(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ProjectSnapshotError("source_changed")
        if info.attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise ProjectSnapshotError("source_changed")
        buffer = ctypes.create_unicode_buffer(32768)
        length = final_name(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise ProjectSnapshotError("source_changed")
        name = buffer.value
        if name.startswith("\\\\?\\UNC\\"):
            name = "\\\\" + name[8:]
        elif name.startswith("\\\\?\\"):
            name = name[4:]
        return handle, os.path.normcase(os.path.normpath(name)), close
    except BaseException:
        close(handle)
        raise


def _prepare_windows_project(root, destination, *, redact, max_files, max_bytes):
    """Copy only files whose opened handles still resolve inside the selected root."""
    import msvcrt

    root_handle = None
    close = None
    try:
        # Pin and inspect the exact configured directory before FileScope's
        # canonicalization could erase a junction at the root itself.
        source = Path(root).expanduser().absolute()
        root_handle, root_name, close = _windows_project_handle(source, directory=True)
        scope = FileScope([root])
        source = scope.resolve(str(scope.roots[0]))
        if os.path.normcase(os.path.normpath(str(source))) != root_name:
            raise ProjectSnapshotError("source_changed")
        destination = Path(destination).expanduser().absolute()
        if destination.exists() or destination.is_symlink():
            raise ProjectSnapshotError("destination_exists")
        if not destination.parent.is_dir():
            raise ProjectSnapshotError("missing_destination_parent")
    except ProjectSnapshotError:
        if root_handle is not None:
            close(root_handle)
        raise
    except (OSError, ValueError) as exc:
        if root_handle is not None:
            close(root_handle)
        raise ProjectSnapshotError("invalid_root") from exc

    files = []
    directories = []
    skipped = 0
    total_bytes = 0

    def inside_root(final):
        try:
            return os.path.commonpath((root_name, final)) == root_name and final != root_name
        except ValueError:
            return False

    def open_file(path, expected):
        handle, final, _ = _windows_project_handle(path)
        try:
            if not inside_root(final):
                raise ProjectSnapshotError("source_changed")
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            close(handle)
            raise
        try:
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino, current.st_size) != expected:
                raise ProjectSnapshotError("source_changed")
            return _read_file(fd, expected[2])
        finally:
            os.close(fd)

    def scan(directory, relative):
        nonlocal skipped, total_bytes
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda item: item.name)
        for item in children:
            name = item.name
            if looks_secret_name(name) or name.lower() in _EXCLUDED_DIRS:
                skipped += 1
                continue
            parts = (*relative, name)
            path = source.joinpath(*parts)
            try:
                scope.resolve(str(path))
            except FileScopeError:
                skipped += 1
                continue
            try:
                entry = path.lstat()
            except OSError as exc:
                raise ProjectSnapshotError("source_changed") from exc
            if stat.S_ISLNK(entry.st_mode) or getattr(entry, "st_file_attributes", 0) & 0x400:
                skipped += 1
                continue
            if stat.S_ISDIR(entry.st_mode):
                child_handle, final, _ = _windows_project_handle(path, directory=True)
                try:
                    if not inside_root(final):
                        raise ProjectSnapshotError("source_changed")
                    directories.append(parts)
                    scan(path, parts)
                finally:
                    close(child_handle)
                continue
            if not stat.S_ISREG(entry.st_mode):
                skipped += 1
                continue
            if len(files) >= max_files:
                raise ProjectSnapshotError("file_limit")
            if entry.st_size > max_bytes - total_bytes:
                raise ProjectSnapshotError("byte_limit")
            expected = (entry.st_dev, entry.st_ino, entry.st_size)
            if redact is not None:
                data = open_file(path, expected)
                try:
                    content = data.decode("utf-8")
                except UnicodeDecodeError:
                    pass
                else:
                    if redact(content) != content:
                        skipped += 1
                        continue
            files.append((parts, expected))
            total_bytes += entry.st_size

    try:
        scan(source, ())
        destination.mkdir(mode=0o700)
        try:
            for parts in directories:
                destination.joinpath(*parts).mkdir(mode=0o700)
            for parts, expected in files:
                data = open_file(source.joinpath(*parts), expected)
                if redact is not None:
                    try:
                        content = data.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
                    else:
                        if redact(content) != content:
                            raise ProjectSnapshotError("source_changed")
                destination.joinpath(*parts).write_bytes(data)
        except BaseException:
            shutil.rmtree(destination)
            raise
    except OSError as exc:
        raise ProjectSnapshotError("source_changed") from exc
    finally:
        close(root_handle)
    return {"files": len(files), "bytes": total_bytes, "skipped": skipped}


def _source_file(root_fd: int, parts: tuple[str, ...]) -> int:
    """Open an entry through no-follow directory fds anchored at the root."""
    parent_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        return os.open(parts[-1], _READ_FLAGS, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def _read_file(file_fd: int, size: int) -> bytes:
    """Read a regular file exactly once without silently accepting a size race."""
    chunks: list[bytes] = []
    remaining = size + 1
    while remaining:
        chunk = os.read(file_fd, min(remaining, 1_048_576))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) != size:
        raise ProjectSnapshotError("source_changed")
    return data


def prepare_project(
    root: str | Path,
    destination: str | Path,
    *,
    redact: Callable[[str], str] | None = None,
    max_files: int = 2000,
    max_bytes: int = 50_000_000,
) -> dict[str, int]:
    """Project only safe regular files into a new destination; refuse over-limit trees.

    The source is owner-selected and opened through root-relative no-follow fds.
    A changed or unreadable source aborts the entire projection. Text whose
    broker-redacted form differs is omitted; binary files are copied as bytes.
    Existing destinations are refused, so a caller never merges with old state.
    """
    if not isinstance(max_files, int) or max_files < 0 or not isinstance(max_bytes, int) or max_bytes < 0:
        raise ProjectSnapshotError("invalid_limits")
    if redact is not None and not callable(redact):
        raise ProjectSnapshotError("invalid_redactor")
    if os.name == "nt":
        return _prepare_windows_project(root, destination, redact=redact,
                                        max_files=max_files, max_bytes=max_bytes)
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ProjectSnapshotError("no_follow_unavailable")
    try:
        scope = FileScope([root])
        source = scope.resolve(str(scope.roots[0]))
        destination = Path(destination).expanduser().absolute()
        if destination.exists() or destination.is_symlink():
            raise ProjectSnapshotError("destination_exists")
        if not destination.parent.is_dir():
            raise ProjectSnapshotError("missing_destination_parent")
        root_fd = os.open(source, _DIR_FLAGS)
    except ProjectSnapshotError:
        raise
    except (OSError, ValueError) as exc:
        raise ProjectSnapshotError("invalid_root") from exc

    files: list[tuple[tuple[str, ...], int, int, int]] = []
    directories: list[tuple[str, ...]] = []
    skipped = 0
    total_bytes = 0

    def scan(directory_fd: int, relative: tuple[str, ...]) -> None:
        nonlocal skipped, total_bytes
        for name in sorted(os.listdir(directory_fd)):
            if looks_secret_name(name) or name.lower() in _EXCLUDED_DIRS:
                skipped += 1
                continue
            parts = (*relative, name)
            try:
                scope.resolve(str(source.joinpath(*parts)))
            except FileScopeError:
                skipped += 1
                continue
            try:
                entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise ProjectSnapshotError("source_changed") from exc
            if stat.S_ISLNK(entry.st_mode):
                skipped += 1
                continue
            if stat.S_ISDIR(entry.st_mode):
                try:
                    child_fd = os.open(name, _DIR_FLAGS, dir_fd=directory_fd)
                except OSError as exc:
                    raise ProjectSnapshotError("source_changed") from exc
                try:
                    current = os.fstat(child_fd)
                    if (current.st_dev, current.st_ino) != (entry.st_dev, entry.st_ino):
                        raise ProjectSnapshotError("source_changed")
                    directories.append(parts)
                    scan(child_fd, parts)
                finally:
                    os.close(child_fd)
                continue
            if not stat.S_ISREG(entry.st_mode):
                skipped += 1
                continue
            if len(files) >= max_files:
                raise ProjectSnapshotError("file_limit")
            if entry.st_size > max_bytes - total_bytes:
                raise ProjectSnapshotError("byte_limit")
            if redact is not None:
                file_fd = _source_file(root_fd, parts)
                try:
                    current = os.fstat(file_fd)
                    if (current.st_dev, current.st_ino, current.st_size) != (
                        entry.st_dev, entry.st_ino, entry.st_size,
                    ):
                        raise ProjectSnapshotError("source_changed")
                    data = _read_file(file_fd, entry.st_size)
                finally:
                    os.close(file_fd)
                try:
                    content = data.decode("utf-8")
                except UnicodeDecodeError:
                    pass
                else:
                    if redact(content) != content:
                        skipped += 1
                        continue
            files.append((parts, entry.st_size, entry.st_dev, entry.st_ino))
            total_bytes += entry.st_size

    try:
        scan(root_fd, ())
        destination.mkdir(mode=0o700)
        try:
            for parts in directories:
                (destination.joinpath(*parts)).mkdir(mode=0o700)
            for parts, size, device, inode in files:
                file_fd = _source_file(root_fd, parts)
                try:
                    current = os.fstat(file_fd)
                    if (current.st_dev, current.st_ino, current.st_size) != (device, inode, size):
                        raise ProjectSnapshotError("source_changed")
                    data = _read_file(file_fd, size)
                finally:
                    os.close(file_fd)
                if redact is not None:
                    try:
                        content = data.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
                    else:
                        if redact(content) != content:
                            raise ProjectSnapshotError("source_changed")
                target = destination.joinpath(*parts)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                output_fd = os.open(target, flags, 0o600)
                with os.fdopen(output_fd, "wb") as output:
                    output.write(data)
        except BaseException:
            shutil.rmtree(destination)
            raise
    except ProjectSnapshotError:
        raise
    except OSError as exc:
        raise ProjectSnapshotError("source_changed") from exc
    finally:
        os.close(root_fd)
    return {"files": len(files), "bytes": total_bytes, "skipped": skipped}


__all__ = ["CHILD_CONTEXT_SOURCE", "ProjectSnapshotError", "normalize_mode",
           "prepare_project", "resolve_child_context"]
