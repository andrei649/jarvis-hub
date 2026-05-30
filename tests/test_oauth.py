"""Tests for OAuth token management (no network calls)."""

import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.plugins import oauth


def _clear_state():
    oauth._pending_verifiers.clear()
    oauth._expected_states.clear()


def test_token_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    # reset Fernet singleton because key dir changed
    monkeypatch.setattr(oauth, "_fernet", None)
    oauth.save_token("test_service", {"access_token": "abc", "refresh_token": "def"})
    loaded = oauth.load_token("test_service")
    assert loaded is not None
    assert loaded["access_token"] == "abc"
    assert loaded["refresh_token"] == "def"
    assert loaded["_saved_at"] is not None
    assert loaded["_encrypted"] is True


def test_load_token_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    assert oauth.load_token("nonexistent") is None


def test_init_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "g-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "g-secret")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "s-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "s-secret")
    oauth.init_from_env()
    assert oauth.GOOGLE_CLIENT_ID == "g-id"
    assert oauth.GOOGLE_CLIENT_SECRET == "g-secret"
    assert oauth.SPOTIFY_CLIENT_ID == "s-id"
    assert oauth.SPOTIFY_CLIENT_SECRET == "s-secret"


def test_init_from_env_handles_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    oauth.init_from_env()
    assert oauth.GOOGLE_CLIENT_ID == ""
    assert oauth.SPOTIFY_CLIENT_ID == ""


def test_get_google_auth_url_contains_expected_params():
    _clear_state()
    oauth.GOOGLE_CLIENT_ID = "test-client-id"
    url = oauth.get_google_auth_url("gmail")
    assert "client_id=test-client-id" in url
    assert "accounts.google.com" in url
    assert "gmail.modify" in url
    assert "offline" in url
    assert "state=google%3Agmail%3A" in url or "state=google:gmail:" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url


def test_get_google_auth_url_calendar():
    _clear_state()
    oauth.GOOGLE_CLIENT_ID = "test-client-id"
    url = oauth.get_google_auth_url("calendar")
    assert "calendar" in url
    assert "state=google%3Acalendar%3A" in url or "state=google:calendar:" in url
    assert "code_challenge=" in url


def test_get_spotify_auth_url_contains_expected_params():
    _clear_state()
    oauth.SPOTIFY_CLIENT_ID = "test-spotify-id"
    url = oauth.get_spotify_auth_url()
    assert "client_id=test-spotify-id" in url
    assert "accounts.spotify.com" in url
    assert "state=spotify%3A" in url or "state=spotify:" in url
    assert "playlist" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url


def test_token_dir_created():
    assert oauth.TOKEN_DIR.exists()
    assert oauth.TOKEN_DIR.is_dir()


def test_redirect_uri_default():
    assert oauth.REDIRECT_URI == "http://127.0.0.1:8080/api/oauth/callback"


# ── PKCE tests ─────────────────────────────────────────────────────

def test_generate_pkce_verifier_length():
    verifier, challenge = oauth._generate_pkce()
    assert 43 <= len(verifier) <= 128
    assert len(challenge) == 43


def test_generate_pkce_challenge_is_base64url():
    import base64
    verifier, challenge = oauth._generate_pkce()
    decoded = base64.urlsafe_b64decode(challenge + "===")
    assert len(decoded) == 32


def test_generate_pkce_is_deterministic_relation():
    import hashlib
    import base64
    verifier, challenge = oauth._generate_pkce()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert challenge == expected


def test_make_state_format():
    state = oauth._make_state("spotify")
    assert state.startswith("spotify:")
    parts = state.split(":")
    assert len(parts) == 2


def test_make_state_google_format():
    state = oauth._make_state("google:gmail")
    assert state.startswith("google:gmail:")
    parts = state.split(":")
    assert len(parts) == 3


# ── State verification tests ───────────────────────────────────────

def test_verify_state_valid():
    _clear_state()
    state = oauth._make_state("spotify")
    oauth._expected_states.add(state)
    result = oauth.verify_state(state)
    assert result == "spotify"
    assert state not in oauth._expected_states


def test_verify_state_google():
    _clear_state()
    state = oauth._make_state("google:gmail")
    oauth._expected_states.add(state)
    result = oauth.verify_state(state)
    assert result == "google:gmail"


def test_verify_state_invalid():
    _clear_state()
    assert oauth.verify_state("bogus") is None


def test_verify_state_replay():
    _clear_state()
    state = oauth._make_state("spotify")
    oauth._expected_states.add(state)
    assert oauth.verify_state(state) == "spotify"
    assert oauth.verify_state(state) is None


# ── Token encryption tests ─────────────────────────────────────────

def test_token_encryption_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    monkeypatch.setattr(oauth, "_fernet", None)
    oauth.save_token("svc", {"access_token": "secret123", "refresh_token": "refresh456"})
    loaded = oauth.load_token("svc")
    assert loaded["access_token"] == "secret123"
    assert loaded["refresh_token"] == "refresh456"
    assert loaded["_encrypted"] is True


def test_token_at_rest_is_encrypted(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    monkeypatch.setattr(oauth, "_fernet", None)
    oauth.save_token("svc", {"access_token": "plaintext-secret"})
    raw = json.loads(oauth._token_path("svc").read_text(encoding="utf-8"))
    assert raw["access_token"] != "plaintext-secret"
    assert raw["_encrypted"] is True


def test_token_encryption_key_is_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    monkeypatch.setattr(oauth, "_fernet", None)
    f1 = oauth._get_fernet()
    monkeypatch.setattr(oauth, "_fernet", None)
    f2 = oauth._get_fernet()
    token = f1.encrypt(b"test-data")
    assert f2.decrypt(token) == b"test-data"


def test_token_backward_compat_unencrypted(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    monkeypatch.setattr(oauth, "_fernet", None)
    path = oauth._token_path("legacy")
    path.write_text(
        json.dumps({"access_token": "oldstyle", "refresh_token": "oldrefresh"}),
        encoding="utf-8",
    )
    loaded = oauth.load_token("legacy")
    assert loaded["access_token"] == "oldstyle"
    assert loaded["refresh_token"] == "oldrefresh"


def test_token_backward_compat_migrates_on_save(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    monkeypatch.setattr(oauth, "_fernet", None)
    path = oauth._token_path("migrate_me")
    path.write_text(
        json.dumps({"access_token": "pre-encryption"}),
        encoding="utf-8",
    )
    loaded = oauth.load_token("migrate_me")
    assert loaded["access_token"] == "pre-encryption"
    oauth.save_token("migrate_me", loaded)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["access_token"] != "pre-encryption"
    assert raw["_encrypted"] is True
    reloaded = oauth.load_token("migrate_me")
    assert reloaded["access_token"] == "pre-encryption"


# ── State + PKCE integration tests ─────────────────────────────────

def test_auth_url_stores_verifier_and_state():
    _clear_state()
    oauth.GOOGLE_CLIENT_ID = "cid"
    url = oauth.get_google_auth_url("gmail")
    assert len(oauth._pending_verifiers) == 1
    assert len(oauth._expected_states) == 1

    state = next(iter(oauth._expected_states))
    verifier = oauth._pending_verifiers[state]
    assert len(verifier) >= 43
    assert f"state={state}" in url or f"state={state.replace(':', '%3A')}" in url


def test_spotify_auth_url_stores_verifier_and_state():
    _clear_state()
    oauth.SPOTIFY_CLIENT_ID = "sid"
    url = oauth.get_spotify_auth_url()
    assert len(oauth._pending_verifiers) == 1
    assert len(oauth._expected_states) == 1


def test_exchange_pops_verifier(monkeypatch):
    _clear_state()
    monkeypatch.setattr(oauth, "_expected_states", {"teststate"})
    assert oauth.verify_state("teststate") == "teststate"
    assert len(oauth._expected_states) == 0
