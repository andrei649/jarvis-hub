"""Tests for OAuth token management (no network calls)."""

import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.plugins import oauth


def test_token_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "TOKEN_DIR", tmp_path)
    oauth.save_token("test_service", {"access_token": "abc", "refresh_token": "def"})
    loaded = oauth.load_token("test_service")
    assert loaded is not None
    assert loaded["access_token"] == "abc"
    assert loaded["refresh_token"] == "def"
    assert "_saved_at" in loaded


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
    oauth.GOOGLE_CLIENT_ID = "test-client-id"
    url = oauth.get_google_auth_url("gmail")
    assert "client_id=test-client-id" in url
    assert "accounts.google.com" in url
    assert "gmail.modify" in url
    assert "offline" in url
    assert "state=google:gmail" in url


def test_get_google_auth_url_calendar():
    oauth.GOOGLE_CLIENT_ID = "test-client-id"
    url = oauth.get_google_auth_url("calendar")
    assert "calendar" in url
    assert "state=google:calendar" in url


def test_get_spotify_auth_url_contains_expected_params():
    oauth.SPOTIFY_CLIENT_ID = "test-spotify-id"
    url = oauth.get_spotify_auth_url()
    assert "client_id=test-spotify-id" in url
    assert "accounts.spotify.com" in url
    assert "state=spotify" in url
    assert "playlist" in url


def test_token_dir_created():
    assert oauth.TOKEN_DIR.exists()
    assert oauth.TOKEN_DIR.is_dir()


def test_redirect_uri_default():
    assert oauth.REDIRECT_URI == "http://127.0.0.1:8080/api/oauth/callback"
