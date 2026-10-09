"""An owner declaration is scoped to the selected image route and model."""

import pytest

from agents.core import settings_db
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.providers import DEFAULT_REGISTRY
from agents.core.llm.vlm import VLMNotConfigured
from agents.core.routers.composer_vision import _main_candidate


def _row(*, backend="custom", base_url="https://owner.example/v1",
         model="owner/model", supports_vision=False):
    return {"backend": backend, "base_url": base_url, "model": model,
            "supports_vision": supports_vision}


def _backend(*, base_url="https://owner.example/v1", model="owner/model"):
    backend = OpenRouterBackend(
        api_key="selected-key", base_url=base_url, client=object(),
        profile=DEFAULT_REGISTRY.get("openai-compatible"),
    )
    backend.model_vision_capabilities = {model: False}
    return backend


@pytest.mark.parametrize("rows", [
    [_row()],
    [_row(supports_vision=True)],
    [_row(backend="lmstudio", base_url="http://127.0.0.1:1234/v1")],
    [_row(), _row(model="other/model", supports_vision=True)],
])
def test_owner_setting_accepts_exact_bounded_rows(rows):
    assert settings_db.validate_category("llm", {"vision_model_capabilities": rows}) == []


@pytest.mark.parametrize("rows", [
    {"custom": {"owner/model": False}},
    [_row(supports_vision="false")],
    [_row(supports_vision=0)],
    [_row(model=" owner/model")],
    [_row(base_url="https://other.example/v1?secret=x")],
    [_row(base_url="https://user:pass@owner.example/v1")],
    [_row(backend="unknown")],
    [{**_row(), "extra": "x"}],
    [_row(), _row()],
    [_row()] * 129,
])
def test_owner_setting_rejects_malformed_or_ambiguous_rows(rows):
    assert settings_db.validate_category("llm", {"vision_model_capabilities": rows})


@pytest.mark.parametrize("changed", [
    {"backend": "openrouter"},
    {"base_url": "https://owner.example/other"},
    {"model": "Owner/model"},
])
def test_owner_declaration_never_leaks_to_another_route(monkeypatch, changed):
    row = _row(**changed)
    monkeypatch.setattr(settings_db, "read_setting", lambda *_: (True, [row]))
    backend = _backend()
    backend.model_vision_capabilities = {}

    assert _main_candidate(backend, "owner/model", "cloud-compatible") is not None


def test_owner_false_suppresses_selected_main_and_true_overrides_snapshot(monkeypatch):
    rows = [_row()]
    monkeypatch.setattr(settings_db, "read_setting", lambda *_: (True, rows))
    backend = _backend()
    assert _main_candidate(backend, "owner/model", "cloud-compatible") is None

    rows[:] = [_row(supports_vision=True)]
    assert _main_candidate(backend, "owner/model", "cloud-compatible") is not None


def test_missing_declaration_preserves_backend_snapshot(monkeypatch):
    monkeypatch.setattr(settings_db, "read_setting", lambda *_: (True, []))
    backend = _backend()
    assert _main_candidate(backend, "owner/model", "cloud-compatible") is None
    backend.model_vision_capabilities = {}
    assert _main_candidate(backend, "owner/model", "cloud-compatible") is not None


def test_unreadable_or_corrupt_owner_setting_fails_closed(monkeypatch):
    backend = _backend()
    backend.model_vision_capabilities = {}
    monkeypatch.setattr(settings_db, "read_setting", lambda *_: (True, [_row(supports_vision="false")]))
    with pytest.raises(VLMNotConfigured, match="vlm_capability_unreadable"):
        _main_candidate(backend, "owner/model", "cloud-compatible")

    def unreadable(*_):
        raise settings_db.SettingsUnreadable("test DB outage")
    monkeypatch.setattr(settings_db, "read_setting", unreadable)
    with pytest.raises(VLMNotConfigured, match="vlm_capability_unreadable"):
        _main_candidate(backend, "owner/model", "cloud-compatible")


def test_owner_declaration_round_trips_through_admin_settings_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    rows = [_row()]

    assert settings_db.validate_category("llm", {"vision_model_capabilities": rows}) == []
    assert settings_db.put_category("llm", {"vision_model_capabilities": rows}) == (1, [])
    assert settings_db.read_setting("llm", "vision_model_capabilities") == (True, rows)
    backend = _backend()
    backend.model_vision_capabilities = {}
    assert _main_candidate(backend, "owner/model", "cloud-compatible") is None
