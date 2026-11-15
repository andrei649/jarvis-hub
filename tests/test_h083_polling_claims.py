"""Offline kernel-lock tests for cross-profile Telegram polling claims."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agents.core.channels import polling_claims
from agents.core.channels.polling_claims import ClaimUnavailable, acquire_telegram_claim

TOKEN = "synthetic-offline-bot-token"


def _paths(root: Path, token: str = TOKEN) -> tuple[Path, Path]:
    directory = root.parent / f".{root.name}-channel-claims"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return directory, directory / f"telegram-{digest}.lock"


def _child(root: Path, *, profile: str = "second", fork_child: bool = False) -> subprocess.Popen:
    script = (
        "import sys\n"
        "from agents.core.channels.polling_claims import acquire_telegram_claim\n"
        "claim = acquire_telegram_claim(sys.argv[1])\n"
        + ("pid = __import__('os').fork()\n"
           "if pid == 0:\n"
           "    claim.release()\n"
           "    __import__('os')._exit(0)\n"
           "__import__('os').waitpid(pid, 0)\n" if fork_child else "")
        +
        "print('ready', flush=True)\n"
        "sys.stdin.buffer.read(1)\n"
        "claim.release()\n"
    )
    env = os.environ.copy()
    env["JARVIS_HOME"] = str(root)
    env["JARVIS_PROFILE"] = profile
    return subprocess.Popen(
        [sys.executable, "-c", script, TOKEN],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, text=False,
    )


def _ready(process: subprocess.Popen) -> None:
    assert process.stdout is not None
    assert process.stdout.readline() == b"ready\n", process.stderr.read().decode()


def test_cross_process_contention_and_crash_release(tmp_path):
    root = tmp_path / "install"
    process = _child(root)
    try:
        _ready(process)
        with pytest.raises(ClaimUnavailable) as error:
            acquire_telegram_claim(TOKEN, root=root)
        assert error.value.reason == "busy"
        process.kill()  # No user-space release: the kernel must release on death.
        process.wait(timeout=5)
        claim = acquire_telegram_claim(TOKEN, root=root)
        claim.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_same_process_owner_and_distinct_tokens(tmp_path):
    root = tmp_path / "install"
    first = acquire_telegram_claim(TOKEN, root=root)
    other = acquire_telegram_claim(TOKEN + " ", root=root)
    try:
        with pytest.raises(ClaimUnavailable) as error:
            acquire_telegram_claim(TOKEN, root=root)
        assert error.value.reason == "busy"
        first.release()
        replacement = acquire_telegram_claim(TOKEN, root=root)
        first.release()  # Stale handle must not release the replacement.
        try:
            with pytest.raises(ClaimUnavailable) as error:
                acquire_telegram_claim(TOKEN, root=root)
            assert error.value.reason == "busy"
        finally:
            replacement.release()
    finally:
        first.release()
        other.release()


def test_profiles_share_default_install_root(tmp_path, monkeypatch):
    root = tmp_path / "install"
    monkeypatch.setenv("JARVIS_HOME", str(root))
    monkeypatch.setenv("JARVIS_PROFILE", "alpha")
    claim = acquire_telegram_claim(TOKEN)
    try:
        monkeypatch.setenv("JARVIS_PROFILE", "beta")
        with pytest.raises(ClaimUnavailable) as error:
            acquire_telegram_claim(TOKEN)
        assert error.value.reason == "busy"
    finally:
        claim.release()


def test_private_fixed_metadata_and_noninherited_descriptor(tmp_path, caplog):
    root = tmp_path / "install"
    directory, path = _paths(root)
    claim = acquire_telegram_claim(TOKEN, root=root)
    try:
        if os.name != "nt":
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        # Windows byte-range locks deny a second handle, even in this process.
        os.lseek(claim._fd, 0, os.SEEK_SET)
        content = os.read(claim._fd, 2)
        assert content == b"\0"
        assert TOKEN not in str(path) + str(directory) + content.decode()
        assert TOKEN not in caplog.text
        assert os.get_inheritable(claim._fd) is False
    finally:
        claim.release()
    assert path.read_bytes() == b"\0"  # Stable inode, never unlinked.


@pytest.mark.parametrize("kind", ["symlink", "directory", "bad_content", "public_mode"])
def test_unsafe_existing_claim_file_is_refused_without_mutation(tmp_path, kind):
    if os.name == "nt" and kind in {"symlink", "public_mode"}:
        pytest.skip("Windows symlink permission and POSIX file mode")
    root = tmp_path / "install"
    directory, path = _paths(root)
    directory.mkdir(mode=0o700)
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(b"outside")
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"wrong" if kind == "bad_content" else b"\0")
        if kind == "public_mode":
            path.chmod(0o644)
    with pytest.raises(ClaimUnavailable) as error:
        acquire_telegram_claim(TOKEN, root=root)
    assert error.value.reason == "unavailable"
    if kind == "symlink":
        assert target.read_bytes() == b"outside"
    if kind == "bad_content":
        assert path.read_bytes() == b"wrong"


def test_unsafe_claim_directory_is_refused(tmp_path):
    root = tmp_path / "install"
    directory, _ = _paths(root)
    target = tmp_path / "elsewhere"
    target.mkdir()
    directory.symlink_to(target, target_is_directory=True)
    with pytest.raises(ClaimUnavailable) as error:
        acquire_telegram_claim(TOKEN, root=root)
    assert error.value.reason == "unavailable"
    assert list(target.iterdir()) == []


def test_lock_backend_error_is_unavailable_not_busy(tmp_path, monkeypatch):
    def unsupported(_fd):
        raise OSError(errno.ENOTSUP, "unsupported")

    monkeypatch.setattr(polling_claims, "_lock", unsupported)
    with pytest.raises(ClaimUnavailable) as error:
        acquire_telegram_claim(TOKEN, root=tmp_path / "install")
    assert error.value.reason == "unavailable"


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork only")
def test_fork_child_cannot_unlock_parent_claim(tmp_path):
    root = tmp_path / "install"
    process = _child(root, fork_child=True)
    try:
        _ready(process)
        with pytest.raises(ClaimUnavailable) as error:
            acquire_telegram_claim(TOKEN, root=root)
        assert error.value.reason == "busy"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
