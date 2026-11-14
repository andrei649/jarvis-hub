"""Slack Socket Mode has independent app- and bot-token kernel claims."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys

import pytest

from agents.core.channels.polling_claims import (
    ClaimUnavailable,
    acquire_discord_claim,
    acquire_slack_app_claim,
    acquire_slack_bot_claim,
    acquire_telegram_claim,
)

APP = "synthetic-offline-app-token"
BOT = "synthetic-offline-bot-token"


def _holder(root):
    script = (
        "import sys\n"
        "from agents.core.channels.polling_claims import acquire_slack_app_claim, acquire_slack_bot_claim\n"
        "app = acquire_slack_app_claim(sys.argv[1])\n"
        "bot = acquire_slack_bot_claim(sys.argv[2])\n"
        "print('ready', flush=True)\n"
        "sys.stdin.buffer.read(1)\n"
        "bot.release()\n"
        "app.release()\n"
    )
    env = os.environ.copy()
    env["JARVIS_HOME"] = str(root)
    env["JARVIS_PROFILE"] = "another-profile"
    return subprocess.Popen(
        [sys.executable, "-c", script, APP, BOT], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )


def test_both_slack_overlap_axes_block_across_profiles_and_crash_releases(tmp_path):
    root = tmp_path / "install"
    holder = _holder(root)
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline() == b"ready\n"
        with pytest.raises(ClaimUnavailable) as app_error:
            acquire_slack_app_claim(APP, root=root)
        with pytest.raises(ClaimUnavailable) as bot_error:
            acquire_slack_bot_claim(BOT, root=root)
        assert app_error.value.reason == bot_error.value.reason == "busy"
        independent_app = acquire_slack_app_claim(APP + "-other", root=root)
        independent_bot = acquire_slack_bot_claim(BOT + "-other", root=root)
        independent_bot.release()
        independent_app.release()
        holder.kill()  # Kernel release, with no application cleanup call.
        holder.wait(timeout=5)
        app = acquire_slack_app_claim(APP, root=root)
        bot = acquire_slack_bot_claim(BOT, root=root)
        bot.release()
        app.release()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_same_opaque_value_in_four_namespaces_has_four_distinct_claims(tmp_path):
    root = tmp_path / "install"
    token = "one-opaque-value"
    claims = [
        acquire_telegram_claim(token, root=root),
        acquire_discord_claim(token, root=root),
        acquire_slack_app_claim(token, root=root),
        acquire_slack_bot_claim(token, root=root),
    ]
    try:
        for acquire in (acquire_telegram_claim, acquire_discord_claim,
                        acquire_slack_app_claim, acquire_slack_bot_claim):
            with pytest.raises(ClaimUnavailable) as error:
                acquire(token, root=root)
            assert error.value.reason == "busy"
        assert len(list((root.parent / f".{root.name}-channel-claims").iterdir())) == 4
    finally:
        for claim in reversed(claims):
            claim.release()


def test_slack_claims_keep_exact_bytes_and_private_fixed_metadata(tmp_path):
    root = tmp_path / "install"
    app = acquire_slack_app_claim(APP, root=root)
    bot = acquire_slack_bot_claim(BOT, root=root)
    spaced = acquire_slack_app_claim(APP + " ", root=root)
    try:
        directory = root.parent / f".{root.name}-channel-claims"
        for token, namespace, claim in ((APP, "slack-app", app), (BOT, "slack-bot", bot)):
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            path = directory / f"{namespace}-{digest}.lock"
            os.lseek(claim._fd, 0, os.SEEK_SET)
            content = os.read(claim._fd, 2)  # Windows forbids a second handle on its locked byte.
            assert path.is_file() and content == b"\0"
            assert token not in str(path) + content.decode(errors="replace")
            assert os.get_inheritable(claim._fd) is False
            if os.name != "nt":
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
        if os.name != "nt":
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert len(list(directory.iterdir())) == 3
    finally:
        spaced.release()
        bot.release()
        app.release()


@pytest.mark.parametrize("acquire", [acquire_slack_app_claim, acquire_slack_bot_claim])
@pytest.mark.parametrize("bad", [None, 17, ""])
def test_slack_claim_invalid_token_has_fixed_reason(tmp_path, acquire, bad):
    with pytest.raises(ClaimUnavailable) as error:
        acquire(bad, root=tmp_path / "install")
    assert error.value.reason == str(error.value) == "unavailable"
