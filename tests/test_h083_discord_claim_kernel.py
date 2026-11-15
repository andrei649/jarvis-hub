"""Discord and Telegram claims share one private root without sharing a token lock."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys

import pytest

from agents.core.channels import polling_claims
from agents.core.channels.polling_claims import (
    ClaimUnavailable,
    acquire_discord_claim,
    acquire_telegram_claim,
)

TOKEN = "synthetic-offline-shared-token"


def _holder(root):
    script = (
        "import sys\n"
        "from agents.core.channels.polling_claims import acquire_discord_claim\n"
        "claim = acquire_discord_claim(sys.argv[1])\n"
        "print('ready', flush=True)\n"
        "sys.stdin.buffer.read(1)\n"
        "claim.release()\n"
    )
    env = os.environ.copy()
    env["JARVIS_HOME"] = str(root)
    env["JARVIS_PROFILE"] = "other"
    return subprocess.Popen(
        [sys.executable, "-c", script, TOKEN], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )


def test_discord_cross_profile_contention_and_crash_release(tmp_path):
    root = tmp_path / "install"
    holder = _holder(root)
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline() == b"ready\n"
        with pytest.raises(ClaimUnavailable) as error:
            acquire_discord_claim(TOKEN, root=root)
        assert error.value.reason == "busy"
        holder.kill()
        holder.wait(timeout=5)
        claim = acquire_discord_claim(TOKEN, root=root)
        claim.release()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_identical_token_has_independent_channel_namespaces(tmp_path):
    root = tmp_path / "install"
    telegram = acquire_telegram_claim(TOKEN, root=root)
    discord = acquire_discord_claim(TOKEN, root=root)
    try:
        with pytest.raises(ClaimUnavailable) as error:
            acquire_discord_claim(TOKEN, root=root)
        assert error.value.reason == "busy"
        with pytest.raises(ClaimUnavailable) as error:
            acquire_telegram_claim(TOKEN, root=root)
        assert error.value.reason == "busy"
        telegram.release()
        with pytest.raises(ClaimUnavailable) as error:
            acquire_discord_claim(TOKEN, root=root)
        assert error.value.reason == "busy"
        replacement = acquire_telegram_claim(TOKEN, root=root)
        replacement.release()
    finally:
        telegram.release()
        discord.release()


def test_discord_private_metadata_and_exact_fingerprint(tmp_path):
    root = tmp_path / "install"
    claim = acquire_discord_claim(TOKEN, root=root)
    spaced = acquire_discord_claim(TOKEN + " ", root=root)
    try:
        directory = root.parent / f".{root.name}-channel-claims"
        digest = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()
        path = directory / f"discord-{digest}.lock"
        os.lseek(claim._fd, 0, os.SEEK_SET)
        content = os.read(claim._fd, 2)
        assert path.is_file() and content == b"\0"
        assert TOKEN not in str(path) + content.decode(errors="replace")
        assert len(list(directory.iterdir())) == 2
        if os.name != "nt":
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert os.get_inheritable(claim._fd) is False
    finally:
        claim.release()
        spaced.release()


@pytest.mark.parametrize("bad", [None, 123, ""])
def test_discord_bad_token_has_fixed_unavailable_reason(tmp_path, bad):
    with pytest.raises(ClaimUnavailable) as error:
        acquire_discord_claim(bad, root=tmp_path / "install")
    assert error.value.reason == str(error.value) == "unavailable"


def test_private_channel_allowlist_cannot_become_a_path_argument(tmp_path):
    root = tmp_path / "install"
    with pytest.raises(ClaimUnavailable) as error:
        polling_claims._acquire_claim("../other", TOKEN, root=root)
    assert error.value.reason == "unavailable"
    assert not (root.parent / f".{root.name}-channel-claims").exists()
