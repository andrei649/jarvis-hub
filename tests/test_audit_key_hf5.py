"""HF-5: the audit HMAC signing key must not live in the log directory.

IntentLog._resolve_key prefers, in order: an explicit key → JARVIS_AUDIT_KEY →
a key in the secure dir (JARVIS_KEY_DIR, else ~/.config/jarvis) → a legacy
co-located <log>.key (honoured for existing installs, with a warning). So write
access to the log tree alone can't read the key and forge + re-sign the chain.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.security.anchor import IntentLog  # noqa: E402


def test_default_key_lands_in_secure_dir_not_log_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    keydir, logdir = tmp_path / "secure", tmp_path / "logs"
    monkeypatch.setenv("JARVIS_KEY_DIR", str(keydir))
    log = IntentLog(path=logdir / "intent_log.json")
    log.record("a", "act", "why")
    assert log.verify()["ok"] is True
    assert (keydir / "intent_log.key").exists()          # key in the secure dir…
    assert not (logdir / "intent_log.key").exists()      # …not next to the log


def test_key_is_stable_across_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "secure"))
    p = tmp_path / "logs" / "intent_log.json"
    IntentLog(path=p).record("a", "act", "why")
    # A fresh instance must read the same persisted key and verify the chain.
    assert IntentLog(path=p).verify()["ok"] is True


def test_legacy_colocated_key_is_honoured_with_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "secure"))  # empty secure dir
    p = tmp_path / "logs" / "intent_log.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.with_suffix(".key").write_text("legacykey")
    with caplog.at_level("WARNING"):
        log = IntentLog(path=p)
    log.record("a", "act", "why")
    assert log.verify()["ok"] is True
    assert any("co-located" in r.getMessage() for r in caplog.records)
    # Did not silently mint a secure-dir key behind the legacy one this run.
    assert not (tmp_path / "secure" / "intent_log.key").exists()


def test_env_key_overrides_files(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "envkey")
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "secure"))
    log = IntentLog(path=tmp_path / "logs" / "intent_log.json")
    log.record("a", "act", "why")
    assert log.verify()["ok"] is True
    assert not (tmp_path / "secure" / "intent_log.key").exists()  # env supplies it


def test_explicit_key_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "envkey")
    p = tmp_path / "logs" / "intent_log.json"
    IntentLog(path=p, secret_key="explicit").record("a", "act", "why")
    # A reader with the *env* key (not 'explicit') must fail to verify the signature.
    assert IntentLog(path=p, secret_key="envkey").verify()["ok"] is False
    assert IntentLog(path=p, secret_key="explicit").verify()["ok"] is True
