"""Custom credentials use a distinct durable scope and never enter settings."""
import pytest

from agents.core import settings_db
from agents.core.llm.providers.packages import ProviderPackageError


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    from agents.core.llm.custom_endpoint_credentials import CustomCredentialStore
    return CustomCredentialStore(tmp_path / "custom-vault")


def test_custom_scopes_generations_and_non_echo(vault):
    from agents.core.llm.custom_endpoint_credentials import CustomCredentialBinding

    one = CustomCredentialBinding("owner-home", "one", "https://one.invalid/v1", "bearer")
    two = CustomCredentialBinding("owner-home", "two", "https://two.invalid/v1", "bearer")
    assert vault.status(one) == {"configured": False, "generation": 0}
    first = vault.put(one, "synthetic-private-one")
    second = vault.put(two, "synthetic-private-two")
    assert first == {"configured": True, "generation": 1}
    assert second == {"configured": True, "generation": 1}
    assert vault.read(one, 1) == "synthetic-private-one"
    assert vault.read(two, 1) == "synthetic-private-two"
    assert "synthetic-private-one" not in str(vault.status(one))
    assert "synthetic-private-two" not in str(vault.status(two))
    assert vault.delete(one) == {"configured": False, "generation": 2}
    with pytest.raises(ProviderPackageError):
        vault.read(one, 1)
    assert vault.read(two, 1) == "synthetic-private-two"


def test_custom_vault_replay_refuses_older_ciphertext(vault):
    from agents.core.llm.custom_endpoint_credentials import CustomCredentialBinding

    binding = CustomCredentialBinding("owner-home", "one", "https://one.invalid/v1", "bearer")
    vault.put(binding, "synthetic-old")
    old = vault.path(binding).read_bytes()
    vault.put(binding, "synthetic-new")
    vault.path(binding).write_bytes(old)
    with pytest.raises(ProviderPackageError):
        vault.read(binding, 2)
