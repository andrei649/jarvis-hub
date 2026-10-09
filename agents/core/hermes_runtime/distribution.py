"""Provision and verify the complete pinned Hermes Agent source and PM runtime."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess  # nosec B404 - fixed argv; managed interpreter and source checked before execution
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from agents.core.archive_safe import ArchiveLimits, ArchiveRejected, extract_tar_path

PIN_FILE = Path(__file__).resolve().parents[3] / "runtime/hermes/upstream.lock.json"
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_FILES = 100_000
_MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
_GENERATED_TOP_LEVEL = {".git", ".hermes", "__pycache__"}


def load_pin() -> dict:
    pin = json.loads(PIN_FILE.read_text(encoding="utf-8"))
    if pin.get("project") != "NousResearch/hermes-agent" or pin.get("commit") != "0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7":
        raise ValueError("Hermes source pin is invalid")
    if pin.get("archive_url") != f"https://codeload.github.com/NousResearch/hermes-agent/tar.gz/{pin['commit']}":
        raise ValueError("Hermes archive URL is not pinned")
    for key, size in (("archive_sha256", 64), ("source_sha256", 64), ("tree_sha1", 40)):
        value = pin.get(key, "")
        if len(value) != size or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"Invalid Hermes {key}")
    return pin


def _git_blob_sha1(path: Path) -> bytes:
    size = path.stat().st_size
    # Git's object format requires SHA-1; SHA-256 separately gates source security.
    # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
    digest = hashlib.sha1(f"blob {size}\0".encode(), usedforsecurity=False)  # nosec B324
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.digest()


def _git_tree_sha1(root: Path) -> str:
    """Compute Git's tree ID over every source file, including executable modes."""
    def tree(directory: Path, *, top: bool = False) -> bytes:
        entries = []
        for item in directory.iterdir():
            if top and item.name in _GENERATED_TOP_LEVEL:
                continue
            mode = item.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError(f"Hermes source contains symlink: {item}")
            if stat.S_ISDIR(mode):
                kind, object_id = b"40000", tree(item)
            elif stat.S_ISREG(mode):
                kind = b"100755" if mode & 0o111 else b"100644"
                object_id = _git_blob_sha1(item)
            else:
                raise ValueError(f"Hermes source contains non-file: {item}")
            entries.append((item.name.encode(), kind, object_id, stat.S_ISDIR(mode)))
        entries.sort(key=lambda entry: entry[0] + (b"/" if entry[3] else b""))
        body = b"".join(kind + b" " + name + b"\0" + object_id for name, kind, object_id, _ in entries)
        # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        return hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body, usedforsecurity=False).digest()  # nosec B324

    return tree(root, top=True).hex()


def _source_sha256(root: Path) -> str:
    """Hash all executable modes, relative names and file bytes independently of Git SHA-1."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] in _GENERATED_TOP_LEVEL:
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(f"Hermes source contains non-file: {path}")
        name = relative.as_posix().encode("utf-8")
        digest.update((b"X" if mode & 0o111 else b"F") + len(name).to_bytes(4, "big") + name)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def verify_source(source: Path) -> dict:
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Hermes source must be a real directory")
    if (source / ".git").exists() or (source / ".git").is_symlink():
        raise ValueError("Hermes source must not contain Git metadata or hooks")
    if (source / ".hermes").is_symlink():
        raise ValueError("Hermes source has an unsafe generated launcher path")
    pin = load_pin()
    content_identity = _source_sha256(source)
    if content_identity != pin["source_sha256"]:
        raise ValueError("Hermes source identity differs from pinned upstream")
    identity = _git_tree_sha1(source)
    if identity != pin["tree_sha1"]:
        raise ValueError("Hermes source identity differs from pinned upstream")
    return {"commit": pin["commit"], "tree_sha1": identity, "source_sha256": content_identity, "source": str(source.resolve())}


def _extract_archive(archive: Path, destination: Path, archive_root: str) -> None:
    """Use the sole product extractor, then restore pinned executable metadata.

    archive_safe deliberately ignores untrusted Unix modes. The donor's small
    executable manifest is shipped with the pin; full SHA-256/tree verification
    after extraction binds these modes to the exact archive content.
    """
    if destination.exists() or destination.is_symlink():
        raise ValueError("Hermes extraction destination already exists")
    with tempfile.TemporaryDirectory(prefix=".hermes-extract-", dir=destination.parent) as temporary:
        unpacked = Path(temporary) / "unpacked"
        unpacked.mkdir(mode=0o700)
        try:
            extract_tar_path(archive, unpacked, compression="gz",
                             limits=ArchiveLimits(max_members=_MAX_FILES, max_bytes=_MAX_EXTRACTED_BYTES))
        except ArchiveRejected as exc:
            raise ValueError(f"Hermes archive refused: {exc}") from exc
        if {entry.name for entry in unpacked.iterdir()} != {archive_root}:
            raise ValueError("Unsafe Hermes archive root")
        root = unpacked / archive_root
        if not root.is_dir():
            raise ValueError("Unsafe Hermes archive root")
        executable_paths = json.loads(PIN_FILE.with_name("executable-paths.json").read_text(encoding="utf-8"))
        for relative in executable_paths:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe Hermes executable metadata")
            target = root / path
            if target.is_file():
                target.chmod(0o755)
        root.rename(destination)


def prepare_source(destination: Path) -> Path:
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        verify_source(destination)
        return destination
    pin = load_pin()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hermes-download-", dir=destination.parent) as temporary:
        archive = Path(temporary) / "source.tar.gz"
        digest = hashlib.sha256()
        size = 0
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(pin["archive_url"], timeout=45) as response, archive.open("wb") as file:  # nosec B310
            for block in iter(lambda: response.read(1024 * 1024), b""):
                size += len(block)
                if size > _MAX_ARCHIVE_BYTES:
                    raise ValueError("Hermes archive too large")
                digest.update(block)
                file.write(block)
        if digest.hexdigest() != pin["archive_sha256"]:
            raise ValueError("Hermes archive hash differs from pin")
        staged = Path(temporary) / "source"
        _extract_archive(archive, staged, pin["archive_root"])
        verify_source(staged)
        staged.rename(destination)
    return destination


def runtime_environment(home: Path, *, for_install: bool = False) -> dict[str, str]:
    from agents.core.env_config import env_str

    home = Path(home).expanduser().absolute()
    # Deliberately do not copy os.environ: provider and operator secrets are ambient there.
    env = {
        "HOME": str(home), "HERMES_HOME": str(home),
        "HERMES_RUNTIME_DIR": str(home / "tools"),
        "PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
    }
    for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        if os.name == "nt" and name in os.environ:
            env[name] = env_str(name)
    if for_install:
        certificate = env_str("SSL_CERT_FILE")
        if certificate and Path(certificate).is_file():
            env["SSL_CERT_FILE"] = certificate
        for name in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
            value = env_str(name)
            if value and len(value) < 2048:
                parsed = urlsplit(value)
                if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
                    env[name] = value
        for name in ("NO_PROXY", "no_proxy"):
            value = env_str(name)
            if value and len(value) < 2048:
                env[name] = value
    return env


def validate_python(python: Path, source: Path, home: Path) -> Path:
    python, source, home = Path(python).absolute(), Path(source).resolve(), Path(home).resolve()
    key = hashlib.sha256(str(source).encode()).hexdigest()[:16]
    generations = home / "installs" / key / "environments"
    if not python.is_relative_to(generations) or not python.is_file():
        raise ValueError("Hermes Python is not a managed environment interpreter")
    facts_path = home / "installs" / key / "facts.json"
    try:
        selected = json.loads(facts_path.read_text(encoding="utf-8"))["packages"]["venv"]["environment"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Hermes managed environment has no valid PM selection") from exc
    if Path(selected).absolute() != python.parent.parent:
        raise ValueError("Hermes Python differs from selected PM environment")
    if not (python.parent.parent / "pyvenv.cfg").is_file():
        raise ValueError("Hermes Python managed environment is incomplete")
    real = python.resolve()
    if not (real.is_relative_to(generations) or real.is_relative_to(home / "tools")):
        raise ValueError("Hermes Python points outside managed runtime")
    result = subprocess.run([str(python), "-I", "-S", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],  # nosec B603 - managed path and fixed version probe
                            env=runtime_environment(home), capture_output=True, text=True, timeout=10, check=False)
    if result.returncode or result.stdout.strip() != "3.14":
        raise ValueError("Hermes requires managed Python 3.14")
    doctor = subprocess.run([sys.executable, "-B", "-m", "pm.cli", "doctor"],  # nosec B603 - fixed read-only upstream PM integrity check
                            cwd=source, env=runtime_environment(home), capture_output=True,
                            text=True, timeout=120, check=False)
    if doctor.returncode:
        raise ValueError(f"Hermes managed tool integrity failed: {(doctor.stderr or doctor.stdout)[-1000:]}")
    return python


def provision_runtime(source: Path, home: Path) -> Path:
    """Use upstream's PM to install its locked tools and all Python extras."""
    source, home = Path(source).absolute(), Path(home).absolute()
    verify_source(source)
    if home == source or home.is_relative_to(source) or source.is_relative_to(home):
        raise ValueError("Hermes source and private home must be separate")
    if home.is_symlink():
        raise ValueError("Hermes home must not be a symlink")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    home.chmod(0o700)
    # Upstream's PM is its supported environment manager. The clean env keeps
    # host credentials and Python package paths out of the installer.
    command = [sys.executable, "-B", "-m", "pm.cli", "install"]
    result = subprocess.run(command, cwd=source, env=runtime_environment(home, for_install=True),  # nosec B603 - fixed upstream PM command
                            text=True, capture_output=True, timeout=1800, check=False)
    if result.returncode:
        raise RuntimeError(f"Hermes PM install failed: {(result.stderr or result.stdout)[-3000:]}")
    key = hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:16]
    facts_path = home / "installs" / key / "facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    selected = facts["packages"]["venv"]["environment"]
    python = Path(selected) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    validate_python(python, source, home)
    verify_source(source)
    return python
