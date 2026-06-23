"""AUD-1 / F2 — secret settings columns are encrypted at rest, decrypted on read.

Proves the credential-bearing keys (Twilio/Notion/Tuya/Gecko/Stark) never sit in
``settings.db`` as plaintext: the value column holds an opaque ``enc::`` token,
while reads (get_value / get_category / get_all) transparently decrypt — so the
plugin consumers that read via ``orch.get_setting`` are unaffected. A fixed
raw key keeps the cipher hermetic (works with or without ``cryptography``).
"""

import base64
import sqlite3
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import settings_db

# Raw 32-byte urlsafe-base64 keys → SecretStore uses them directly (no keyfile/salt).
_KEY = base64.urlsafe_b64encode(b"aud1-test-key-32-bytes-padding!!").decode()
_OTHER_KEY = base64.urlsafe_b64encode(b"aud1-OTHER-key-32-byte-padding!!").decode()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Throwaway settings DB + a hermetic at-rest cipher key."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_SECRET_KEY", _KEY)
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setattr(settings_db, "_field_cipher", None)
    return settings_db


def _raw_value(db, cat, key):
    """Read the stored value column directly (bypassing decryption)."""
    conn = sqlite3.connect(str(db.DB_PATH))
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE category=? AND key=?", (cat, key)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def test_secret_written_encrypted_at_rest(temp_db):
    secret = "twilio-super-secret-AUTH-token"
    temp_db.put_category("plugins", {"twilio_auth_token": secret})
    raw = _raw_value(temp_db, "plugins", "twilio_auth_token")
    assert secret not in raw                       # plaintext never hits the column
    assert temp_db._ENC_PREFIX in raw              # stored as an opaque enc:: token


def test_secret_roundtrips_via_get_value(temp_db):
    temp_db.put_category("plugins", {"notion_integration_token": "ntn_abc123"})
    assert temp_db.get_value("plugins", "notion_integration_token") == "ntn_abc123"


def test_secret_roundtrips_via_get_category_and_get_all(temp_db):
    temp_db.put_category("plugins", {"tuya_secret": "tuya-xyz"})
    cat = {r["key"]: r["value"] for r in temp_db.get_category("plugins")}
    assert cat["tuya_secret"] == "tuya-xyz"
    allg = {r["key"]: r["value"] for r in temp_db.get_all()["plugins"]}
    assert allg["tuya_secret"] == "tuya-xyz"


def test_all_secret_keys_are_encrypted(temp_db):
    for key in temp_db.SECRET_KEYS:
        temp_db.put_category("plugins", {key: f"val-for-{key}"})
        raw = _raw_value(temp_db, "plugins", key)
        assert f"val-for-{key}" not in raw, f"{key} stored in plaintext"
        assert temp_db.get_value("plugins", key) == f"val-for-{key}"


def test_non_secret_key_stays_plaintext(temp_db):
    temp_db.put_category("llm", {"lm_studio_url": "http://host:1234"})
    raw = _raw_value(temp_db, "llm", "lm_studio_url")
    assert "http://host:1234" in raw               # not a secret → not encrypted


def test_empty_secret_not_encrypted(temp_db):
    # The seeded default is "" — clearing a secret must not produce an enc token.
    temp_db.put_category("plugins", {"twilio_auth_token": ""})
    raw = _raw_value(temp_db, "plugins", "twilio_auth_token")
    assert temp_db._ENC_PREFIX not in raw
    assert temp_db.get_value("plugins", "twilio_auth_token") == ""


def test_decrypt_with_wrong_key_returns_empty(temp_db, monkeypatch):
    temp_db.put_category("plugins", {"gecko_libra_token": "libra-tok"})
    # Rotate the key out from under the stored value → reads fail closed to "".
    monkeypatch.setenv("JARVIS_SECRET_KEY", _OTHER_KEY)
    monkeypatch.setattr(temp_db, "_field_cipher", None)
    assert temp_db.get_value("plugins", "gecko_libra_token") == ""
