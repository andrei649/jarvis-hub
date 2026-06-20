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
