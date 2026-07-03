"""
test_o26_f2_settings_seed.py — ORIZONT 26 P0.3 (finding F2).

The flagship "knows you" layers were gated by settings the product could not
set: `cognition.*` and `memory.recall_enabled` were read (default False) but
absent from DEFAULTS, and `put_category` only UPDATEd existing rows — so the
admin UI could never insert them. Enabling recall/cognition required editing
SQLite by hand.

Pins: (1) the keys are seeded in DEFAULTS (init_db INSERT OR IGNORE brings
existing DBs up on next boot); (2) put_category UPSERTS spec-known keys while
still rejecting arbitrary rows; (3) the CognitionFacade wakes through the
settings path — flipping the single master enables the sub-capabilities.
"""

import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import settings_db  # noqa: E402


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Point the module at a throwaway DB and reset its init latch."""
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    yield
    monkeypatch.setattr(settings_db, "_initialized", False)


def _value(cat: str, key: str):
    rows = settings_db.get_category(cat)
    for row in rows:
        if row["key"] == key:
            return row["value"]
    return None


# ── (1) the spec now carries the flagship keys ───────────────────────────────

def test_defaults_seed_recall_and_cognition():
    spec = {(r["category"], r["key"]) for r in settings_db.DEFAULTS}
    assert ("memory", "recall_enabled") in spec
    assert ("memory", "recall_top_k") in spec
    assert ("cognition", "enabled") in spec
    for sub in ("honesty_enabled", "affect_enabled", "memory_enabled",
                "learning_enabled", "personality_enabled"):
        assert ("cognition", sub) in spec, f"cognition.{sub} not seeded"


def test_master_defaults_off_subs_default_on():
    """Default-off discipline on the master; one switch wakes the layer."""
    by_key = {(r["category"], r["key"]): r["value"] for r in settings_db.DEFAULTS}
    assert by_key[("cognition", "enabled")] is False
    assert by_key[("memory", "recall_enabled")] is False
    assert by_key[("cognition", "honesty_enabled")] is True
    assert by_key[("cognition", "affect_enabled")] is True


def test_fresh_db_serves_the_new_categories(isolated_db):
    assert _value("cognition", "enabled") is False
    assert _value("memory", "recall_enabled") is False


# ── (2) put_category: update, spec-upsert, reject-unknown ────────────────────

def test_admin_can_enable_cognition(isolated_db):
    updated, skipped = settings_db.put_category("cognition", {"enabled": True})
    assert updated == 1 and skipped == []
    assert _value("cognition", "enabled") is True


def test_put_category_upserts_spec_known_missing_row(isolated_db):
    """A pre-existing DB missing a newly-shipped key gains it on write."""
    settings_db.get_category("memory")  # trigger schema init on the tmp DB
    conn = settings_db.get_conn()
    conn.execute("DELETE FROM settings WHERE category='memory' AND key='recall_enabled'")
    conn.commit()
    conn.close()

    updated, skipped = settings_db.put_category("memory", {"recall_enabled": True})
    assert updated == 1 and skipped == []
    assert _value("memory", "recall_enabled") is True
    # The upserted row carries the spec's kind/label, not blanks.
    row = next(r for r in settings_db.get_category("memory") if r["key"] == "recall_enabled")
    assert row["kind"] == "toggle"


def test_put_category_still_rejects_arbitrary_rows(isolated_db):
    updated, skipped = settings_db.put_category("cognition", {"evil_new_key": True})
    assert updated == 0 and skipped == ["evil_new_key"]
    assert _value("cognition", "evil_new_key") is None


def test_validate_category_accepts_the_new_toggles(isolated_db):
    assert settings_db.validate_category("cognition", {"enabled": True}) == []
    assert settings_db.validate_category("memory", {"recall_top_k": 7}) == []
    assert settings_db.validate_category("cognition", {"enabled": "yes"}) != []


# ── (3) the facade wakes through the settings path ───────────────────────────

def test_cognition_facade_wakes_via_settings(isolated_db):
    from agents.core.cognition.facade import CognitionFacade

    def get_setting(key, default=None):
        cat, _, k = key.partition(".")
        v = _value(cat, k)
        return default if v is None else v

    cog = CognitionFacade(get_setting=get_setting)
    assert cog.enabled() is False, "master must default off"
    assert cog.sub_enabled("honesty_enabled") is False, "subs inert while master off"

    settings_db.put_category("cognition", {"enabled": True})
    assert cog.enabled() is True
    assert cog.sub_enabled("honesty_enabled") is True, (
        "one master switch must wake the pre-enabled sub-capabilities"
    )


def test_recall_block_reads_the_seeded_key(isolated_db):
    """orchestrator._recall_block is gated on exactly this settings key."""
    import inspect

    from agents.core import orchestrator as orch_mod

    src = inspect.getsource(orch_mod.Orchestrator._recall_block)
    assert "memory.recall_enabled" in src, (
        "the recall gate moved — update the seeded key to match"
    )


def test_values_round_trip_json(isolated_db):
    settings_db.put_category("memory", {"recall_top_k": 9})
    raw = settings_db.get_conn().execute(
        "SELECT value FROM settings WHERE category='memory' AND key='recall_top_k'"
    ).fetchone()[0]
    assert json.loads(raw) == 9
