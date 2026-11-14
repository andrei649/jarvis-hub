"""Ntfy subscription kernel ownership survives profile boundaries."""

import os
import subprocess
import sys

import pytest

from agents.core.channels import polling_claims

RESOURCE = '["https","offline.invalid",443,"/private-topic/json"]'


def test_other_profile_is_blocked_until_owner_process_exits(tmp_path):
    root = tmp_path / "install"
    env = {**os.environ, "JARVIS_HOME": str(root), "JARVIS_PROFILE": "other"}
    script = (
        "from agents.core.channels.polling_claims import acquire_ntfy_claim\n"
        f"claim = acquire_ntfy_claim({RESOURCE!r})\n"
        "print('ready', flush=True)\n"
        "input()\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script], env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert child.stdout.readline() == b"ready\n"
        with pytest.raises(polling_claims.ClaimUnavailable) as failure:
            polling_claims.acquire_ntfy_claim(RESOURCE, root=root)
        assert failure.value.reason == "busy"
        child.kill()
        child.wait(timeout=5)
        claim = polling_claims.acquire_ntfy_claim(RESOURCE, root=root)
        claim.release()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_ntfy_namespace_is_distinct_and_old_release_cannot_unlock_replacement(tmp_path):
    root = tmp_path / "install"
    first = polling_claims.acquire_ntfy_claim(RESOURCE, root=root)
    telegram = polling_claims.acquire_telegram_claim(RESOURCE, root=root)
    try:
        first.release()
        replacement = polling_claims.acquire_ntfy_claim(RESOURCE, root=root)
        try:
            first.release()
            with pytest.raises(polling_claims.ClaimUnavailable):
                polling_claims.acquire_ntfy_claim(RESOURCE, root=root)
            os.lseek(replacement._fd, 0, os.SEEK_SET)
            assert os.read(replacement._fd, 2) == b"\0"
            assert "private-topic" not in replacement._key
        finally:
            replacement.release()
    finally:
        first.release()
        telegram.release()
