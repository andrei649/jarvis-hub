"""Explicit, hash-pinned bws installer for owner CLI use only.

Artifact URLs and SHA-256 pins adapted from Hermes pm/lock.json and
pm/security_packages.py at 59b2aeef6c7a (MIT). Never called by a fetch.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
import tempfile
import urllib.request
from pathlib import Path

from agents.core.archive_safe import ArchiveLimits, ArchiveRejected, extract_zip_bytes
from agents.core.paths import data_path

_VERSION = "2.0.0"
_BASE = f"https://github.com/bitwarden/sdk-sm/releases/download/bws-v{_VERSION}/"
_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_PINNED = {
    ("darwin", "arm64"): ("bws-macos-universal-2.0.0.zip", "67ab9bc345e2ec3b5dfddd116f938fdab79538042623a6bcca5ca0c1b0c42d95"),
    ("darwin", "x86_64"): ("bws-macos-universal-2.0.0.zip", "67ab9bc345e2ec3b5dfddd116f938fdab79538042623a6bcca5ca0c1b0c42d95"),
    ("linux", "aarch64"): ("bws-aarch64-unknown-linux-musl-2.0.0.zip", "de61bfbacbcf6e3648ddc8dbd6ca8bb2245438ccf5f94d54129997528f5a752d"),
    ("linux", "x86_64"): ("bws-x86_64-unknown-linux-musl-2.0.0.zip", "ea6eb18f1270388f12d15a35f919ccb3488d32a777433baefe883d561f46fc73"),
    ("win32", "arm64"): ("bws-aarch64-pc-windows-msvc-2.0.0.zip", "1a02fca3a855ba32d8f0c40813af8da705cf1e7cf9b932164959531e57eccbe0"),
    ("win32", "amd64"): ("bws-x86_64-pc-windows-msvc-2.0.0.zip", "4284944f3b0c7b97a4d4105c715cd814c744ceff0405481a213937955e31d866"),
}


def installed_bws_path() -> Path:
    return data_path("tools", "bws", _VERSION, "bws.exe" if sys.platform == "win32" else "bws")


def install_bws(*, destination: Path | None = None) -> Path:
    """Acquire one pinned release transactionally; errors leave previous binary intact."""
    target = (sys.platform, platform.machine().lower())
    if target not in _PINNED:
        raise RuntimeError("bws has no pinned artifact for this platform")
    filename, expected_sha = _PINNED[target]
    destination = destination or installed_bws_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bws-install-", dir=destination.parent) as tmp:
        stage = Path(tmp)
        archive = stage / filename
        digest = hashlib.sha256()
        total = 0
        # The URL is a fixed HTTPS GitHub release plus a closed-table filename;
        # the downloaded bytes must also match the table's SHA-256 pin.
        with urllib.request.urlopen(  # nosec B310  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            _BASE + filename, timeout=30
        ) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > _MAX_ARCHIVE_BYTES:
                    raise RuntimeError("bws archive exceeded size limit")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != expected_sha:
            raise RuntimeError("bws archive checksum mismatch")
        try:
            unpacked = stage / "unpacked"
            files = extract_zip_bytes(archive.read_bytes(), unpacked,
                                      limits=ArchiveLimits(max_members=256, max_bytes=_MAX_ARCHIVE_BYTES))
        except ArchiveRejected as exc:
            raise RuntimeError("bws archive is invalid") from exc
        matches = [parts for parts in files if parts[-1] == destination.name]
        if len(matches) != 1:
            raise RuntimeError("bws archive has no unique bounded executable")
        binary = unpacked.joinpath(*matches[0])
        binary.chmod(0o700)
        os.replace(binary, destination)
    return destination
