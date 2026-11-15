"""Known special files must be refused before opening a polling claim."""

import hashlib
import os

import pytest

from agents.core.channels import polling_claims


def test_windows_branch_locks_before_accessing_the_reserved_byte(tmp_path, monkeypatch):
    class WindowsBranch:
        name = "nt"

        def __getattr__(self, name):
            return getattr(os, name)

    locked = False
    original_content = polling_claims._fixed_content

    def lock(_fd):
        nonlocal locked
        locked = True

    def content(fd):
        assert locked, "a competing Windows handle cannot read a locked byte"
        original_content(fd)

    monkeypatch.setattr(polling_claims, "os", WindowsBranch())
    monkeypatch.setattr(polling_claims, "_open_windows",
                        lambda path: os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
    monkeypatch.setattr(polling_claims, "_lock", lock)
    monkeypatch.setattr(polling_claims, "_unlock", lambda _fd: None)
    monkeypatch.setattr(polling_claims, "_fixed_content", content)
    claim = polling_claims.acquire_telegram_claim("offline", root=tmp_path / "install")
    claim.release()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX named pipe fixture")
def test_existing_fifo_is_rejected_without_opening_it(tmp_path, monkeypatch):
    root = tmp_path / "install"
    directory = tmp_path / ".install-channel-claims"
    directory.mkdir(mode=0o700)
    digest = hashlib.sha256(b"offline-token").hexdigest()
    path = directory / f"telegram-{digest}.lock"
    os.mkfifo(path, 0o600)
    opened = []
    original = os.open

    def spy(target, *args, **kwargs):
        if os.fspath(target) == os.fspath(path):
            opened.append(target)
        return original(target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(polling_claims.os, "open", spy)
        with pytest.raises(polling_claims.ClaimUnavailable, match="unavailable"):
            polling_claims.acquire_telegram_claim("offline-token", root=root)
    assert opened == []
