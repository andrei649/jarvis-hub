"""Tests for OAuth token-encryption key resolution (BACKLOG H22.10).

The key used to be generated and written in plaintext next to the ciphertext it
protected. Now it resolves from the vault/env first (key never on disk), and the
legacy file fallback is hardened to 0600. All offline.
"""

import os
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from cryptography.fernet import Fernet

import agents.core.plugins.oauth as oauth


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Point token storage at a tmp dir and reset the cached Fernet per test."""
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    monkeypatch.setattr(oauth, "_fernet", None)
    monkeypatch.delenv("JARVIS_TOKEN_KEY", raising=False)
    yield


def test_key_resolves_from_env_without_touching_disk(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv("JARVIS_TOKEN_KEY", key.decode())

    resolved = oauth._resolve_token_key()

    assert resolved == key
    assert not (tmp_path / ".encryption_key").exists()   # never written to disk


def test_env_key_roundtrips_a_token(monkeypatch):
    monkeypatch.setenv("JARVIS_TOKEN_KEY", Fernet.generate_key().decode())

    oauth.save_token("svc", {"access_token": "secret-abc", "refresh_token": "r-xyz"})
    loaded = oauth.load_token("svc")

    assert loaded["access_token"] == "secret-abc"
    assert loaded["refresh_token"] == "r-xyz"
    assert loaded["_encrypted"] is True


def test_file_fallback_is_created_with_0600(tmp_path):
    # No env key → legacy file path, but hardened.
    key = oauth._resolve_token_key()
    key_file = tmp_path / ".encryption_key"

    assert key_file.exists()
    assert key_file.read_bytes() == key
    if os.name == "posix":
        assert (key_file.stat().st_mode & 0o777) == 0o600


def test_persisted_file_is_stored_encrypted_not_plaintext(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_TOKEN_KEY", Fernet.generate_key().decode())
    oauth.save_token("svc", {"access_token": "topsecret"})

    raw = (tmp_path / "svc_token.json").read_text()
    assert "topsecret" not in raw          # ciphertext on disk, not the secret


# ── key material must never be minted twice (concurrency) ─────────────────────
#
# `_load_or_create_salt` / `_load_or_create_keyfile` were check-then-act:
# `if path.exists(): read` else `generate; write`. Two callers that interleave each
# mint DIFFERENT material and each write it. The last write wins — and anything the
# loser already encrypted with its own key can never be decrypted again.
#
# It is reachable: POST /api/admin/backup and /api/admin/backup/verify both offload
# to real worker threads via asyncio.to_thread, and each constructs a fresh
# SecretStore. On a first backup with JARVIS_BACKUP_KEY set as a passphrase, two
# concurrent requests race for the salt, and the archive written by the loser is
# unrecoverable — permanently, with verify reporting failure on it forever.

def test_concurrent_stores_agree_on_one_salt(tmp_path, monkeypatch):
    import threading

    from agents.core.secrets import SecretStore

    monkeypatch.setenv("JARVIS_SECRET_KEY", "a-passphrase-not-a-fernet-key")
    store_path = tmp_path / "secrets.enc"

    keys, errors, ready = [], [], threading.Barrier(8)

    def build():
        try:
            ready.wait(timeout=5)          # maximize the overlap
            keys.append(SecretStore(store_path)._key_b64)
        except Exception as exc:           # pragma: no cover - diagnostic
            errors.append(exc)

    threads = [threading.Thread(target=build) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert len(keys) == 8
    assert len(set(keys)) == 1, (
        "threads derived different keys from different salts — whatever the losers "
        "encrypted is now undecryptable"
    )


def test_concurrent_stores_agree_on_one_generated_keyfile(tmp_path, monkeypatch):
    """Same race on the no-configured-key path, which silently rotates the key
    under every other consumer sharing that store."""
    import threading

    from agents.core.secrets import SecretStore

    monkeypatch.delenv("JARVIS_SECRET_KEY", raising=False)
    store_path = tmp_path / "secrets.enc"

    keys, ready = [], threading.Barrier(8)

    def build():
        ready.wait(timeout=5)
        keys.append(SecretStore(store_path)._key_b64)

    threads = [threading.Thread(target=build) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(set(keys)) == 1, "concurrent first-use generated more than one key"


def test_a_value_encrypted_by_one_racer_is_readable_by_the_others(tmp_path, monkeypatch):
    """The consequence, stated as the user experiences it: what one writer
    encrypted must still decrypt afterwards."""
    import threading

    from agents.core.secrets import SecretStore

    monkeypatch.setenv("JARVIS_SECRET_KEY", "a-passphrase-not-a-fernet-key")
    store_path = tmp_path / "secrets.enc"
    ready = threading.Barrier(4)

    def build_and_write(i):
        ready.wait(timeout=5)
        SecretStore(store_path).set(f"token{i}", f"QAFAKE-value-{i}")

    threads = [threading.Thread(target=build_and_write, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    reader = SecretStore(store_path)
    for i in range(4):
        assert reader.get(f"token{i}") == f"QAFAKE-value-{i}", (
            f"token{i} was encrypted under a key that no longer exists"
        )


def test_the_key_file_is_owner_only(tmp_path, monkeypatch):
    """O_EXCL's mode argument is subject to umask, so the explicit chmod stays."""
    import stat as _stat

    from agents.core.secrets import SecretStore

    monkeypatch.delenv("JARVIS_SECRET_KEY", raising=False)
    store_path = tmp_path / "secrets.enc"
    SecretStore(store_path)
    key_file = store_path.with_suffix(store_path.suffix + ".key")
    assert key_file.exists()
    if os.name != "nt":  # POSIX permissions are meaningless on Windows
        assert _stat.S_IMODE(key_file.stat().st_mode) == 0o600


# ── the Windows text-mode corruption of the very key material above ──────────
#
# `_read_or_create_atomically` opened the descriptor with O_WRONLY|O_CREAT|O_EXCL
# and no O_BINARY. On Windows the CRT then opens it in TEXT mode and expands every
# 0x0A byte to 0x0D 0x0A on write, so the creator returned the 16 random salt bytes
# it minted while every later reader read 17 different ones off disk — two different
# derived keys for the same store, ~6% of the time, reported only as
# "cannot decrypt secret (wrong key or corrupted)". Caught by three unrelated
# Windows CI failures on a docs-only PR; `vault.py` has always ORed O_BINARY in.


def test_the_creator_returns_exactly_what_lands_on_disk(tmp_path, monkeypatch):
    """The invariant the two halves of the function must agree on.

    Deterministic here (a salt forced to contain 0x0A); on Windows without
    O_BINARY the on-disk bytes come back one byte longer and different.
    """
    import agents.core.secrets as secrets_mod

    monkeypatch.setattr(
        secrets_mod._secrets, "token_bytes", lambda n: b"\x00\n\r\n\x1a" + b"A" * (n - 5)
    )
    store = secrets_mod.SecretStore(tmp_path / "s.enc", key="a-passphrase")
    salt_path = tmp_path / "s.enc.salt"

    returned = store._load_or_create_salt()          # re-read: file now exists
    assert returned == salt_path.read_bytes()
    assert b"\r\n\r\n" not in salt_path.read_bytes()  # no CRLF expansion
    assert len(salt_path.read_bytes()) == 16


def test_a_newline_bearing_salt_still_round_trips_across_instances(tmp_path, monkeypatch):
    """The consequence, as the owner meets it: a stored secret must decrypt later."""
    import agents.core.secrets as secrets_mod

    monkeypatch.setenv("JARVIS_SECRET_KEY", "a-passphrase-not-a-fernet-key")
    monkeypatch.setattr(
        secrets_mod._secrets, "token_bytes", lambda n: b"\n" * n
    )
    path = tmp_path / "s.enc"
    secrets_mod.SecretStore(path).set("X", "QAFAKE-value-x")

    assert secrets_mod.SecretStore(path).get("X") == "QAFAKE-value-x"


def test_the_binary_flag_is_requested_when_the_platform_has_one(tmp_path, monkeypatch):
    """Pins the fix itself, so a Linux-only run can still catch its removal.

    POSIX has no O_BINARY, so the round-trip tests above are green here whether or
    not the flag is passed — only Windows CI would notice. This asserts the flag is
    actually ORed in, by giving the platform one.
    """
    import agents.core.secrets as secrets_mod

    sentinel = 0x8000
    monkeypatch.setattr(os, "O_BINARY", sentinel, raising=False)
    seen: list[int] = []
    real_open = os.open

    def _spy(path, flags, *rest):
        seen.append(flags)
        return real_open(path, flags & ~sentinel, *rest)

    monkeypatch.setattr(os, "open", _spy)
    monkeypatch.delenv("JARVIS_SECRET_KEY", raising=False)
    secrets_mod.SecretStore(tmp_path / "s.enc")

    assert seen, "key material was created without going through os.open"
    assert all(f & sentinel for f in seen), "O_BINARY was not requested"
