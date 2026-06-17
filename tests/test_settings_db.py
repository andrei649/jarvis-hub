"""Tests for the admin settings store (seeding, get/put, unknown-key handling)."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import settings_db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the settings store at a throwaway DB and reset module init state."""
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    return settings_db


def test_seeds_all_categories(temp_db):
    groups = temp_db.get_all()
    # 11 categories are defined in DEFAULTS (the empty "agents" category was removed)
    assert len(groups) == 11
    for cat in ("general", "llm", "voice", "security", "memory",
                "channels", "plugins", "skills", "system", "mcp"):
        assert cat in groups, f"missing category: {cat}"


def test_get_category_returns_typed_values(temp_db):
    llm = temp_db.get_category("llm")
    by_key = {row["key"]: row for row in llm}
    assert by_key["max_tokens"]["value"] == 0             # int preserved (0 = auto)
    assert by_key["temperature"]["value"] == 0.7          # float preserved
    assert isinstance(by_key["backend_type"]["opts"], list)


def test_put_category_updates_known_key(temp_db):
    count, skipped = temp_db.put_category("llm", {"max_tokens": 2048})
    assert count == 1
    assert skipped == []
    by_key = {r["key"]: r for r in temp_db.get_category("llm")}
    assert by_key["max_tokens"]["value"] == 2048


def test_put_category_ignores_unknown_key(temp_db):
    # Unknown keys must not be written and must not raise.
    count, skipped = temp_db.put_category("llm", {"does_not_exist": "x", "max_tokens": 512})
    assert count == 1
    assert skipped == ["does_not_exist"]
    by_key = {r["key"]: r for r in temp_db.get_category("llm")}
    assert "does_not_exist" not in by_key
    assert by_key["max_tokens"]["value"] == 512


def test_get_unknown_category_empty(temp_db):
    assert temp_db.get_category("nonexistent") == []


def test_logsafe_strips_newlines():
    # CWE-117: the admin category/keys are request-controlled and get logged;
    # CR/LF must be neutralized so a value can't forge extra log lines.
    out = settings_db._logsafe("evil\r\nINFO admin: forged line")
    assert "\n" not in out and "\r" not in out
    assert settings_db._logsafe(["a\nb", "c"]) .count("\n") == 0


def test_init_db_force_reseeds(temp_db):
    temp_db.put_category("llm", {"max_tokens": 9999})
    temp_db.init_db(force=True)
    llm = {r["key"]: r for r in temp_db.get_category("llm")}
    assert llm["max_tokens"]["value"] == 0


def test_init_db_force_restores_all_categories(temp_db):
    temp_db.put_category("general", {"timezone": "Custom/Time"})
    temp_db.init_db(force=True)
    groups = temp_db.get_all()
    assert len(groups) == 11  # all categories restored
    gen = {r["key"]: r for r in groups["general"]}
    # Custom values gone, defaults back
    assert gen["timezone"]["value"] != "Custom/Time"
