"""Standalone chat consent: synthetic context and intercepted provider dispatch only."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

spec = importlib.util.spec_from_file_location("jarvis_os_consent_test", repo_root / "apps/jarvis-os/server.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

PROVIDERS = ["auto", "claude_subscription", "anthropic", "gemini", "openai", "openrouter", "ollama"]
SYNTHETIC_NOTE = "SYNTHETIC-PRIVATE-CONTEXT"


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(engine, "DEFAULT_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setattr(engine, "DEFAULT_NERVA_PATH", str(tmp_path / "repo"))
    monkeypatch.delenv("JARVIS_OS_ALLOW_HARDLINKS", raising=False)
    monkeypatch.delenv("NERVA_OS_ALLOW_HARDLINKS", raising=False)
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(key, "synthetic-key")
    monkeypatch.setattr(engine, "retrieve_vault_context", lambda *a, **k: (SYNTHETIC_NOTE, []))
    # A transport/subprocess call is a test bug; all permitted providers below are fakes.
    monkeypatch.setattr(engine.urllib.request, "urlopen", lambda *a, **k: pytest.fail("real HTTP"))
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: pytest.fail("real CLI"))
    calls = []

    def fake(label):
        def call(payload, *a, **k):
            assert SYNTHETIC_NOTE in payload
            calls.append(label)
            return {"reply": "synthetic", "provider": label}
        return call

    for name, label in (("_call_claude_subscription", "claude_subscription"),
                        ("_call_anthropic_api", "anthropic"), ("_call_gemini_api", "gemini"),
                        ("_call_openai_compatible", "compatible"), ("_call_ollama", "ollama")):
        monkeypatch.setattr(engine, name, fake(label))
    return calls


def test_fresh_config_is_local_despite_inherited_keys(isolated):
    cfg = engine.load_config()
    assert cfg["preferredProvider"] == "ollama"
    assert cfg["cloudConsent"] is False
    assert cfg["anthropicKey"] == "synthetic-key"
    assert engine.call_llm("hello", "test", {}, cfg)["provider"] == "ollama"
    assert isolated == ["ollama"]


@pytest.mark.parametrize("provider", PROVIDERS + ["unknown", None, [], {}])
@pytest.mark.parametrize("consent", [None, False, "true", "false", 1, [], {}])
def test_selection_keys_or_login_never_grant_consent(isolated, provider, consent):
    cfg = engine.load_config()
    cfg.update(preferredProvider=provider, cloudConsent=consent)
    engine.call_llm("hello", "test", {}, cfg)
    assert isolated == ["ollama"]


@pytest.mark.parametrize("disk", [{"preferredProvider": "auto"}, {"preferredProvider": "anthropic"},
                                  {"cloudConsent": "true"}, {"cloudConsent": 1}, [], None, "bad"])
def test_legacy_or_malformed_disk_does_not_opt_in(isolated, disk):
    engine.CONFIG_PATH.write_text(json.dumps(disk), encoding="utf-8")
    cfg = engine.load_config()
    assert cfg["cloudConsent"] is False
    engine.call_llm("hello", "test", {}, cfg)
    assert isolated == ["ollama"]


@pytest.mark.parametrize("provider", PROVIDERS[:-1])
def test_cloud_selection_needs_explicit_boolean_consent(isolated, provider, monkeypatch):
    cfg = engine.load_config()
    engine.save_config({"cloudConsent": True})
    cfg.update(preferredProvider=provider, cloudConsent=True)
    if provider == "auto":
        def offline(*args):
            isolated.append("ollama")
            raise RuntimeError("synthetic offline")
        monkeypatch.setattr(engine, "_call_ollama", offline)
    engine.call_llm("hello", "test", {}, cfg)
    expected = {"auto": ["ollama", "claude_subscription"], "openai": ["compatible"],
                "openrouter": ["compatible"]}.get(provider, [provider])
    assert isolated == expected


def test_auto_local_success_never_uses_cloud_even_with_consent(isolated):
    cfg = engine.load_config()
    cfg.update(preferredProvider="auto", cloudConsent=True)
    engine.call_llm("hello", "test", {}, cfg)
    assert isolated == ["ollama"]


@pytest.mark.parametrize("consent", [False, True])
def test_local_only_failure_never_falls_back_to_cloud(isolated, monkeypatch, consent):
    def offline(*args):
        isolated.append("ollama")
        raise RuntimeError("synthetic offline")
    monkeypatch.setattr(engine, "_call_ollama", offline)
    cfg = engine.load_config()
    cfg.update(preferredProvider="ollama", cloudConsent=consent)
    assert engine.call_llm("hello", "test", {}, cfg)["provider"] == "vault_rag"
    assert isolated == ["ollama"]


@pytest.mark.parametrize("url", ["https://example.invalid", "http://localhost.evil.invalid",
    "http://127.0.0.1@evil.invalid", "http://evil.invalid/localhost", "http://[::1",
    "file:///tmp/model", None, [], {}])
def test_remote_or_malformed_ollama_cannot_bypass_consent(isolated, url):
    cfg = engine.load_config()
    cfg.update(ollamaUrl=url)
    engine.call_llm("hello", "test", {}, cfg)
    assert isolated == []


@pytest.mark.parametrize("value", ["true", "false", 1, None, [], {}])
def test_invalid_consent_save_is_rejected_without_writing(isolated, value):
    with pytest.raises(ValueError):
        engine.save_config({"cloudConsent": value})
    assert not engine.CONFIG_PATH.exists()


def test_save_consent_round_trip_and_revoke(isolated):
    engine.save_config({"cloudConsent": True, "preferredProvider": "anthropic"})
    assert engine.load_config()["cloudConsent"] is True
    engine.save_config({"cloudConsent": False})
    assert engine.load_config()["cloudConsent"] is False
    engine.call_llm("hello", "test", {}, engine.load_config())
    assert isolated == ["ollama"]


def test_unrelated_settings_save_preserves_blank_or_masked_keys(isolated):
    engine.save_config({"openrouterKey": "synthetic-saved", "elevenlabsKey": "synthetic-voice"})
    engine.save_config({"preferredProvider": "ollama", "openrouterKey": "", "elevenlabsKey": "***"})
    cfg = engine.load_config()
    assert cfg["openrouterKey"] == "synthetic-saved"
    assert cfg["elevenlabsKey"] == "synthetic-voice"


def test_documented_hardlink_config_round_trips_default_off(isolated):
    assert engine._allow_hardlinks(engine.load_config()) is False
    engine.CONFIG_PATH.write_text('{"allowHardLinks": true}', encoding="utf-8")
    assert engine._allow_hardlinks(engine.load_config()) is True
    engine.save_config({"allowHardLinks": False})
    assert engine.load_config()["allowHardLinks"] is False
    assert engine._allow_hardlinks(engine.load_config()) is False


@pytest.mark.parametrize("consent", [False, True])
def test_auto_failures_respect_consent_at_every_fallback(isolated, monkeypatch, consent):
    engine.save_config({"cloudConsent": consent})
    def failure(label):
        def call(*args, **kwargs):
            isolated.append(label)
            raise RuntimeError("synthetic failure")
        return call
    for name, label in (("_call_ollama", "ollama"), ("_call_claude_subscription", "cli"),
                        ("_call_anthropic_api", "anthropic"), ("_call_gemini_api", "gemini"),
                        ("_call_openai_compatible", "compatible")):
        monkeypatch.setattr(engine, name, failure(label))
    cfg = engine.load_config()
    cfg.update(preferredProvider="auto", cloudConsent=consent)
    assert engine.call_llm("hello", "test", {}, cfg)["provider"] == "vault_rag"
    assert isolated == (["ollama", "cli", "anthropic", "gemini", "compatible", "compatible"]
                        if consent else ["ollama"])


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("online", [False, True])
def test_status_advertises_only_permitted_engine(isolated, monkeypatch, provider, online):
    engine.save_config({"preferredProvider": provider})
    monkeypatch.setattr(engine, "check_claude_subscription", lambda **k: {"loggedIn": True})
    monkeypatch.setattr(engine, "check_ollama_status", lambda *a, **k: {
        "online": online, "models": ["qwen3.5:4b"], "localModels": ["qwen3.5:4b"]})
    handler = engine.JarvisRequestHandler.__new__(engine.JarvisRequestHandler)
    status = handler._build_status_payload()
    assert status["cloudConsent"] is False
    assert status["activeEngine"] == ("ollama (qwen3.5:4b)" if online else "vault_rag")
    assert "synthetic-key" not in json.dumps(status)


@pytest.mark.parametrize("value", ["unknown", None, [], {}, True])
def test_unknown_provider_save_is_rejected(isolated, value):
    with pytest.raises(ValueError):
        engine.save_config({"preferredProvider": value, "cloudConsent": True})
    assert not engine.CONFIG_PATH.exists()


def test_invalid_config_json_is_local(isolated):
    engine.CONFIG_PATH.write_text('{"cloudConsent": true, broken', encoding="utf-8")
    cfg = engine.load_config()
    assert cfg["cloudConsent"] is False
    engine.call_llm("hello", "test", {}, cfg)
    assert isolated == ["ollama"]


@pytest.mark.parametrize("revoke_at", ["ollama", "cli"])
def test_revoking_saved_consent_stops_later_cloud_fallbacks(isolated, monkeypatch, revoke_at):
    engine.save_config({"preferredProvider": "auto", "cloudConsent": True})
    cfg = engine.load_config()

    def fail_local(*args):
        isolated.append("ollama")
        if revoke_at == "ollama":
            engine.save_config({"cloudConsent": False})
        raise RuntimeError("synthetic local failure")

    def fail_cli(*args):
        isolated.append("cli")
        engine.save_config({"cloudConsent": False})
        raise RuntimeError("synthetic CLI failure")

    monkeypatch.setattr(engine, "_call_ollama", fail_local)
    monkeypatch.setattr(engine, "_call_claude_subscription", fail_cli)
    assert engine.call_llm("hello", "test", {}, cfg)["provider"] == "vault_rag"
    assert isolated == (["ollama"] if revoke_at == "ollama" else ["ollama", "cli"])


def test_new_consent_cannot_upgrade_an_inflight_local_request(isolated, monkeypatch):
    cfg = engine.load_config()
    cfg["preferredProvider"] = "auto"

    def local(*args):
        isolated.append("ollama")
        engine.save_config({"cloudConsent": True})
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(engine, "_call_ollama", local)
    assert engine.call_llm("hello", "test", {}, cfg)["provider"] == "vault_rag"
    assert isolated == ["ollama"]


def test_revocation_during_cli_status_check_blocks_prompt_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "CONFIG_PATH", tmp_path / "config.json")
    engine.save_config({"cloudConsent": True, "preferredProvider": "claude_subscription"})
    cfg = engine.load_config()

    def check():
        engine.save_config({"cloudConsent": False})
        return {"loggedIn": True, "bin": "synthetic-cli"}

    monkeypatch.setattr(engine, "check_claude_subscription", check)
    monkeypatch.setattr(engine, "retrieve_vault_context", lambda *a, **k: (SYNTHETIC_NOTE, []))
    monkeypatch.setattr(engine, "_call_ollama", lambda *a: {"provider": "ollama"})
    calls = []
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: calls.append(a))
    engine.call_llm("hello", "test", {}, cfg)
    assert calls == []
