"""H12.13 — Opt-in E2E encrypted device sync. Real Fernet crypto, all offline."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.e2e_sync import E2ESync, E2ESyncError


def test_status_with_passphrase():
    s = E2ESync(passphrase="correct horse battery staple", device_id="A")
    assert s.available is True and s.backend == "fernet"


def test_unavailable_without_secret():
    s = E2ESync(device_id="A")  # no key, no passphrase, no env
    assert s.available is False and s.backend == "no-key"


def test_enabled_requires_env(monkeypatch):
    s = E2ESync(passphrase="pw", device_id="A")
    monkeypatch.delenv("JARVIS_E2E_SYNC", raising=False)
    assert s.enabled() is False           # available but flag off
    monkeypatch.setenv("JARVIS_E2E_SYNC", "1")
    assert s.enabled() is True


def test_encrypt_record_hides_plaintext():
    s = E2ESync(passphrase="pw", device_id="A")
    env = s.encrypt_record({"secret": "TOPSECRET123", "k": "v"})
    assert env["device"] == "A" and env["ct"]
    assert "TOPSECRET123" not in json.dumps(env)  # only ciphertext leaves


def test_encrypt_decrypt_round_trip():
    s = E2ESync(passphrase="pw", device_id="A")
    rec = {"a": 1, "b": ["x", "y"], "c": "ç"}
    assert s.decrypt_record(s.encrypt_record(rec)) == rec


def test_tamper_is_detected():
    s = E2ESync(passphrase="pw", device_id="A")
    env = s.encrypt_record({"a": 1})
    env["ct"] = env["ct"][:-4] + "AAAA"  # flip ciphertext
    with pytest.raises(E2ESyncError):
        s.decrypt_record(env)


def test_wrong_key_cannot_decrypt():
    a = E2ESync(passphrase="pw-one", device_id="A")
    b = E2ESync(passphrase="pw-two", device_id="B")
    env = a.encrypt_record({"a": 1})
    with pytest.raises(E2ESyncError):
        b.decrypt_record(env)


def test_encrypt_raises_when_unavailable():
    s = E2ESync(device_id="A")  # no key
    with pytest.raises(E2ESyncError):
        s.encrypt_record({"a": 1})


def test_build_push_disabled_when_flag_off(monkeypatch):
    monkeypatch.delenv("JARVIS_E2E_SYNC", raising=False)
    s = E2ESync(passphrase="pw", device_id="A")
    out = s.build_push([{"a": 1}])
    assert out["enabled"] is False and out["entries"] == []


def test_build_push_and_pull_cross_device(monkeypatch):
    monkeypatch.setenv("JARVIS_E2E_SYNC", "1")
    a = E2ESync(passphrase="shared", device_id="A")
    b = E2ESync(passphrase="shared", device_id="B")
    manifest = a.build_push([{"id": 1}, {"id": 2}], kind="memory")
    assert manifest["enabled"] is True and manifest["count"] == 2 and manifest["digest"]
    # B (same passphrase) decrypts A's push.
    assert b.apply_pull(manifest) == [{"id": 1}, {"id": 2}]
    # A skips its own push (no re-ingest).
    assert a.apply_pull(manifest) == []


def test_apply_pull_drops_unverifiable(monkeypatch):
    monkeypatch.setenv("JARVIS_E2E_SYNC", "1")
    a = E2ESync(passphrase="shared", device_id="A")
    b = E2ESync(passphrase="shared", device_id="B")
    manifest = a.build_push([{"id": 1}])
    manifest["entries"].append({"v": 1, "device": "C", "ct": "garbage", "ts": 0})
    assert b.apply_pull(manifest) == [{"id": 1}]  # bad entry dropped, good kept


def test_apply_pull_disabled_returns_empty(monkeypatch):
    monkeypatch.delenv("JARVIS_E2E_SYNC", raising=False)
    s = E2ESync(passphrase="pw", device_id="B")
    assert s.apply_pull({"entries": [{"device": "A", "ct": "x"}]}) == []
