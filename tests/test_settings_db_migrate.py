"""H006 — ``settings_migrate``: the plan `nerva config migrate` prints and applies.

The retired-model table is data with a pinned shape; the planner reads the raw store
before any init so a dry run sees what a boot would change, and apply writes exactly the
plan — a seed, a changed shipped default, a retired model id — and nothing else.
"""

import json
import re
import sqlite3
from pathlib import Path

import pytest

from agents.core import settings_db, settings_migrate
from agents.core.llm.cost_estimator import MODELS as PRICED_MODELS
from agents.core.llm.model_config import DEFAULT_CLAUDE_MODEL, RETIRED_CLAUDE_DEFAULT

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    return settings_db


def _raw(conn_db, category, key):
    conn = sqlite3.connect(conn_db.DB_PATH)
    try:
        row = conn.execute("SELECT value FROM settings WHERE category=? AND key=?", (category, key)).fetchone()
    finally:
        conn.close()
    return None if row is None else json.loads(row[0])


def _execute(conn_db, sql, params=()):
    conn = sqlite3.connect(conn_db.DB_PATH)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# ── the retired-model table ──────────────────────────────────────────────────


def test_retired_models_table_has_the_pinned_shape():
    table = settings_migrate.RETIRED_MODELS
    assert isinstance(table, tuple) and table, "the table is data: a non-empty tuple"
    retired_ids = [row.retired for row in table]
    assert len(set(retired_ids)) == len(retired_ids), "one row per retired id"
    for row in table:
        assert isinstance(row, settings_migrate.RetiredModel)
        assert row.vendor and row.retired and row.replacement and row.source, row
        assert row.retired != row.replacement, row
        assert row.replacement not in retired_ids, f"{row.replacement} is itself retired"
        # A replacement the estimator can price: the hub's cost guards know it.
        assert row.replacement in PRICED_MODELS, row
        # Never from memory: the repo file named as the source holds the retired id, and
        # the date when one is recorded.
        recorded = (REPO / row.source).read_text(encoding="utf-8")
        assert row.retired in recorded or row.retired == RETIRED_CLAUDE_DEFAULT, row
        if row.since:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.since) and row.since in recorded, row
    # The shipped Claude default's own retirement is the first row and is single-sourced
    # from model_config, so the boot migration and this table can never disagree.
    assert (table[0].retired, table[0].replacement) == (RETIRED_CLAUDE_DEFAULT, DEFAULT_CLAUDE_MODEL)
    assert settings_migrate.replacement_for(RETIRED_CLAUDE_DEFAULT) == DEFAULT_CLAUDE_MODEL
    assert settings_migrate.replacement_for("not-a-retired-model") is None


def test_model_settings_are_declared_text_rows():
    for category, key in settings_migrate.MODEL_SETTINGS:
        spec = settings_db._SPEC[(category, key)]
        assert spec["kind"] in ("text", "model-select", "select"), (category, key)


# ── the plan ─────────────────────────────────────────────────────────────────


def test_no_store_plans_nothing_but_says_so(temp_db):
    assert not temp_db.DB_PATH.exists()
    assert settings_migrate.plan() is None


def test_a_current_store_has_nothing_to_migrate(temp_db):
    temp_db.init_db()
    assert settings_migrate.plan() == []


def test_plan_names_a_missing_default_a_changed_default_and_a_retired_model(temp_db):
    temp_db.init_db()
    _execute(temp_db, "DELETE FROM settings WHERE category='llm' AND key='tool_loop_max_iterations'")
    # The H315 changed default, as a store seeded by an older build holds it.
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='guest_tools'",
             (json.dumps(["echo", "time"]),))
    _execute(temp_db, "DELETE FROM settings_migrations WHERE name='llm.guest_tools+todo'")
    # A retired id wherever a model setting holds it — the shipped default row and an
    # owner's own pin on another row.
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='claude_model'",
             (json.dumps(RETIRED_CLAUDE_DEFAULT),))
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='autonomy' AND key='subagent_model'",
             (json.dumps(RETIRED_CLAUDE_DEFAULT),))

    changes = settings_migrate.plan()
    by_setting = {c.setting: c for c in changes}
    assert set(by_setting) == {"llm.tool_loop_max_iterations", "llm.guest_tools",
                               "llm.claude_model", "autonomy.subagent_model"}
    seed = by_setting["llm.tool_loop_max_iterations"]
    assert seed.kind == "seed" and seed.before is None and seed.after == 8
    changed = by_setting["llm.guest_tools"]
    assert changed.kind == "default" and changed.before == ["echo", "time"] and "todo" in changed.after
    retired = by_setting["llm.claude_model"]
    assert retired.kind == "retired" and (retired.before, retired.after) == (RETIRED_CLAUDE_DEFAULT, DEFAULT_CLAUDE_MODEL)
    assert "anthropic" in retired.why
    assert by_setting["autonomy.subagent_model"].after == DEFAULT_CLAUDE_MODEL
    # Planning wrote nothing.
    assert _raw(temp_db, "llm", "claude_model") == RETIRED_CLAUDE_DEFAULT
    assert _raw(temp_db, "llm", "tool_loop_max_iterations") is None


def test_an_owner_value_that_is_not_the_old_default_is_left_alone(temp_db):
    temp_db.init_db()
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='guest_tools'",
             (json.dumps(["echo"]),))
    _execute(temp_db, "DELETE FROM settings_migrations WHERE name='llm.guest_tools+todo'")
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='claude_model'",
             (json.dumps("claude-opus-4-6"),))
    assert settings_migrate.plan() == []


def test_skill_switch_rows_are_never_reseeded_once_observed(temp_db):
    """H329: a missing switch row on a store the switches have observed is damage the
    strict reader must report, so the planner lists it as kept, not as a seed."""
    temp_db.init_db()
    _execute(temp_db, "CREATE TABLE IF NOT EXISTS skill_switch_revision (revision TEXT)")
    _execute(temp_db, "DELETE FROM settings WHERE category='skills' AND key='disabled'")
    changes = settings_migrate.plan()
    assert [c.setting for c in changes] == ["skills.disabled"]
    assert changes[0].kind == "kept" and "skill" in changes[0].why
    settings_migrate.apply(changes)
    assert _raw(temp_db, "skills", "disabled") is None


# ── apply ────────────────────────────────────────────────────────────────────


def test_apply_writes_exactly_the_plan_and_records_the_default_change(temp_db):
    temp_db.init_db()
    _execute(temp_db, "DELETE FROM settings WHERE category='llm' AND key='tool_loop_max_iterations'")
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='guest_tools'",
             (json.dumps(["echo", "time"]),))
    _execute(temp_db, "DELETE FROM settings_migrations WHERE name='llm.guest_tools+todo'")
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='claude_model'",
             (json.dumps(RETIRED_CLAUDE_DEFAULT),))
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='tool_loop_enabled'",
             (json.dumps(True),))

    seen = []
    temp_db.on_change(lambda cat, values: seen.append((cat, values)))
    try:
        changes = settings_migrate.plan()
        applied = settings_migrate.apply(changes)
    finally:
        temp_db._change_listeners.remove(temp_db._change_listeners[-1])
    assert [c.setting for c in applied] == [c.setting for c in changes if c.kind != "kept"]
    assert _raw(temp_db, "llm", "tool_loop_max_iterations") == 8
    assert "todo" in _raw(temp_db, "llm", "guest_tools")
    assert _raw(temp_db, "llm", "claude_model") == DEFAULT_CLAUDE_MODEL
    assert _raw(temp_db, "llm", "tool_loop_enabled") is True          # an owner's value: untouched
    assert settings_migrate.plan() == []
    assert any(cat == "llm" and "claude_model" in values for cat, values in seen)
    # The marker row keeps a later boot from re-applying the default change.
    conn = sqlite3.connect(temp_db.DB_PATH)
    try:
        assert conn.execute("SELECT 1 FROM settings_migrations WHERE name='llm.guest_tools+todo'").fetchone()
    finally:
        conn.close()


def test_apply_on_a_store_without_the_migrations_table(temp_db):
    """A store from before ``settings_migrations`` existed: the plan still reads it and
    apply creates the table before it records anything."""
    temp_db.init_db()
    _execute(temp_db, "DROP TABLE settings_migrations")
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='guest_tools'",
             (json.dumps(["echo", "time"]),))
    changes = settings_migrate.plan()
    assert [c.setting for c in changes] == ["llm.guest_tools"]
    settings_migrate.apply(changes)
    assert "todo" in _raw(temp_db, "llm", "guest_tools")
    assert settings_migrate.plan() == []


def test_a_retired_id_in_the_compatible_model_is_rewritten_and_others_are_not(temp_db):
    """The vendor-specific half (`hermes migrate xai`) is data: a table row for an xAI id
    rewrites llm.compatible_model; an id the table does not list is the owner's."""
    temp_db.init_db()
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='compatible_provider'",
             (json.dumps("xai"),))
    _execute(temp_db, "UPDATE settings SET value=? WHERE category='llm' AND key='compatible_model'",
             (json.dumps("grok-old"),))
    injected = (settings_migrate.RetiredModel("xai", "grok-old", "grok-4.6", "test table"),)
    changes = settings_migrate.plan(table=injected)
    assert [(c.setting, c.before, c.after, c.kind) for c in changes] == [
        ("llm.compatible_model", "grok-old", "grok-4.6", "retired")]
    assert settings_migrate.plan() == []                        # the real table lists no xAI id
    settings_migrate.apply(changes)
    assert _raw(temp_db, "llm", "compatible_model") == "grok-4.6"
    assert _raw(temp_db, "llm", "compatible_provider") == "xai"
    assert settings_migrate.plan(table=injected) == []          # an id not in the table: left alone


def test_the_table_lists_only_anthropic_because_no_other_retirement_is_recorded():
    assert {row.vendor for row in settings_migrate.RETIRED_MODELS} == {"anthropic"}
    assert "xAI" in (settings_migrate.__doc__ or "") + Path(settings_migrate.__file__).read_text(encoding="utf-8")
