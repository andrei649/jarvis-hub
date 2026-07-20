"""Tests for the admin settings store (seeding, get/put, unknown-key handling)."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import settings_db
from agents.core.llm.model_config import (
    DEFAULT_CLAUDE_MODEL,
    RETIRED_CLAUDE_DEFAULT,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the settings store at a throwaway DB and reset module init state."""
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    return settings_db


def test_seeds_all_categories(temp_db):
    groups = temp_db.get_all()
    expected_categories = {d["category"] for d in settings_db.DEFAULTS}
    assert len(groups) == len(expected_categories)
    for cat in ("general", "llm", "voice", "security", "memory",
                "channels", "plugins", "skills", "system", "mcp", "product"):
        assert cat in groups, f"missing category: {cat}"


def test_get_category_returns_typed_values(temp_db):
    llm = temp_db.get_category("llm")
    by_key = {row["key"]: row for row in llm}
    assert by_key["max_tokens"]["value"] == 0             # int preserved (0 = auto)
    assert by_key["temperature"]["value"] == 0.7          # float preserved
    assert isinstance(by_key["backend_type"]["opts"], list)


def test_agent_tool_loop_defaults_are_seeded_default_off(temp_db):
    llm = {row["key"]: row for row in temp_db.get_category("llm")}

    assert llm["tool_loop_enabled"] == {
        "key": "tool_loop_enabled",
        "value": False,
        "label": "Agent tool loop (experimental)",
        "kind": "toggle",
        "opts": [],
    }
    assert llm["tool_loop_max_iterations"] == {
        "key": "tool_loop_max_iterations",
        "value": 8,
        "label": "Agent tool-loop model-turn cap",
        "kind": "number",
        "opts": [],
    }


def test_agent_tool_loop_defaults_upgrade_existing_db_without_overwriting_values(temp_db):
    temp_db.init_db()
    count, skipped = temp_db.put_category(
        "llm",
        {"tool_loop_enabled": True, "tool_loop_max_iterations": 0},
    )

    assert count == 2
    assert skipped == []

    # Simulate an older DB where one newly shipped row does not exist yet while
    # another already has an owner-selected value.
    conn = temp_db.get_conn()
    conn.execute(
        "DELETE FROM settings WHERE category=? AND key=?",
        ("llm", "tool_loop_max_iterations"),
    )
    conn.commit()
    conn.close()

    temp_db.init_db()
    llm = {row["key"]: row for row in temp_db.get_category("llm")}
    assert llm["tool_loop_enabled"]["value"] is True
    assert llm["tool_loop_max_iterations"]["value"] == 8


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
    assert len(groups) == len({d["category"] for d in settings_db.DEFAULTS})
    gen = {r["key"]: r for r in groups["general"]}
    # Custom values gone, defaults back
    assert gen["timezone"]["value"] != "Custom/Time"


def _set_raw_claude_model(temp_db, value):
    temp_db.init_db()
    conn = temp_db.get_conn()
    conn.execute(
        "UPDATE settings SET value=? WHERE category='llm' AND key='claude_model'",
        (json.dumps(value),),
    )
    conn.commit()
    conn.close()


def test_fresh_db_seeds_current_claude_default(temp_db):
    assert temp_db.get_value("llm", "claude_model") == DEFAULT_CLAUDE_MODEL


def test_retired_claude_default_migrates_exactly_once(temp_db):
    _set_raw_claude_model(temp_db, RETIRED_CLAUDE_DEFAULT)
    temp_db.init_db()
    assert temp_db.get_value("llm", "claude_model") == DEFAULT_CLAUDE_MODEL
    conn = temp_db.get_conn()
    try:
        assert temp_db._migrate_retired_claude_default(conn) is False
    finally:
        conn.close()


def test_custom_claude_model_value_remains_byte_identical(temp_db):
    custom = "  owner/custom-claude:model@v1  "
    _set_raw_claude_model(temp_db, custom)
    temp_db.init_db()
    assert temp_db.get_value("llm", "claude_model") == custom


def test_claude_migration_is_idempotent(temp_db):
    _set_raw_claude_model(temp_db, RETIRED_CLAUDE_DEFAULT)
    temp_db.init_db()
    temp_db.init_db()
    assert temp_db.get_value("llm", "claude_model") == DEFAULT_CLAUDE_MODEL


def test_force_init_reseeds_current_claude_default(temp_db):
    _set_raw_claude_model(temp_db, "owner/custom-model")
    temp_db.init_db(force=True)
    assert temp_db.get_value("llm", "claude_model") == DEFAULT_CLAUDE_MODEL


def test_concurrent_ensure_initialized_migrates_once(temp_db):
    _set_raw_claude_model(temp_db, RETIRED_CLAUDE_DEFAULT)
    temp_db._initialized = False
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: temp_db.ensure_initialized(), range(16)))
    assert temp_db.get_value("llm", "claude_model") == DEFAULT_CLAUDE_MODEL
