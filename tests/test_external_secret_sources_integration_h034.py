"""External managers reach the actual owner CLI and hub component factory."""

import io
import subprocess
from types import SimpleNamespace

import pytest

from agents.cli import nerva
from agents.cli import secrets as secrets_cli
from agents.core import component_registry, orchestrator, secrets
from agents.core.secrets import SecretStore
from agents.core.security import secret_sources
from agents.core.security.secret_sources import ExternalSecretSources


@pytest.mark.parametrize("provider", ["bitwarden", "onepassword"])
def test_main_cli_roundtrip_persists_encrypted_source_without_hub(tmp_path, monkeypatch, provider):
    store = SecretStore(tmp_path / "secrets.enc", key="synthetic-owner-key")
    binary = tmp_path / ("bws" if provider == "bitwarden" else "op")
    binary.write_text("")
    binary.chmod(0o700)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        output = '[{"key":"API_KEY","value":"synthetic-resolved"}]' if provider == "bitwarden" else "synthetic-resolved\n"
        return subprocess.CompletedProcess(argv, 0, output, "")

    sources = ExternalSecretSources(store, runner=run)
    monkeypatch.setattr(secrets_cli, "SecretStore", lambda: store)
    monkeypatch.setattr(secrets_cli, "ExternalSecretSources", lambda _store: sources)
    out, err = io.StringIO(), io.StringIO()
    context = nerva.Context(environ={}, out=out, err=err, inp=io.StringIO("synthetic-bootstrap\n"),
                            client_factory=lambda _env: pytest.fail("secret CLI must not call hub"))
    prefix = ["secrets", provider]
    setup = ["setup", "--binary-path", str(binary)]
    if provider == "bitwarden":
        setup += ["--project-id", "synthetic-project", "--region", "eu"]
    assert nerva.main(prefix + setup, context=context) == 0
    if provider == "onepassword":
        assert nerva.main(prefix + ["set", "API_KEY", "op://vault/item/field"], context=context) == 0
    assert nerva.main(prefix + ["token", "--token-stdin", "--no-verify"], context=context) == 0
    assert nerva.main(prefix + ["status"], context=context) == 0
    assert nerva.main(prefix + ["sync"], context=context) == 0
    assert "API_KEY" in out.getvalue()
    restarted = ExternalSecretSources(SecretStore(store.path, key="synthetic-owner-key"), runner=run)
    assert restarted.resolve("API_KEY", background=True) == "synthetic-resolved"
    assert nerva.main(prefix + ["disable"], context=context) == 0
    assert ExternalSecretSources(store, runner=run).resolve("API_KEY") is None
    for value in ("synthetic-bootstrap", "synthetic-resolved"):
        assert value not in out.getvalue() + err.getvalue()
        assert value.encode() not in store.path.read_bytes()
    assert calls


def test_real_hub_registration_attaches_sources_without_eager_vault_fetch(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "secrets.enc", key="synthetic-owner-key")
    binary = tmp_path / "bws"
    binary.write_text("")
    binary.chmod(0o700)
    sources = ExternalSecretSources(store, runner=lambda *_args, **_kwargs: pytest.fail("startup must not fetch a vault"))
    sources.configure("bitwarden", {"enabled": True, "project_id": "p", "binary_path": str(binary)})
    sources.set_token("bitwarden", "synthetic-bootstrap")
    captured = []

    class Registered(Exception):
        pass

    class Registry:
        def __init__(self, *_args):
            pass

        def add(self, *_args, **_kwargs):
            pass

        def register_group(self, *_args, **_kwargs):
            pass

        def register(self, name, factory, *_args):
            assert name == "secret_broker"
            captured.append(factory())
            raise Registered

    monkeypatch.setattr(component_registry, "ComponentRegistry", Registry)
    monkeypatch.setattr(orchestrator, "IntentRouter", lambda _config: None)
    monkeypatch.setattr(orchestrator, "HybridRouter", lambda **_kwargs: None)
    monkeypatch.setattr(orchestrator, "MemoryManager", lambda: None)
    monkeypatch.setattr("agents.core.settings_db.ensure_initialized", lambda: None)
    monkeypatch.setattr("agents.core.kernel.binding.make_budget_ledger", lambda: None)
    monkeypatch.setattr(secrets, "SecretStore", lambda: store)
    monkeypatch.setattr(secret_sources, "ExternalSecretSources", lambda _store: sources)
    with pytest.raises(Registered):
        orchestrator.Orchestrator(SimpleNamespace())
    [broker] = captured
    assert isinstance(broker._sources, ExternalSecretSources)
    assert broker._sources.store is store
    assert broker._sources.known_values() == {}
    from agents.core.kernel.syscalls import inject_guarded

    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, '[{"key":"K","value":"synthetic-runtime-value"}]', "")

    sources.runner = run
    kill = SimpleNamespace(is_halted=lambda _scope: False)
    assert inject_guarded(broker, kill, "{{secret:K}}", approved=False)["blocked"] == ["K"]
    assert not calls
    assert inject_guarded(broker, kill, "{{secret:K}}", approved=True)["text"] == "synthetic-runtime-value"
    assert len(calls) == 1
    kill.is_halted = lambda _scope: True
    result = inject_guarded(broker, kill, "{{secret:K}}", approved=True)
    assert result["blocked"] == ["K"] and result["quarantined"]
    assert len(calls) == 1
    assert "synthetic-runtime-value" not in broker.redact("synthetic-runtime-value")
