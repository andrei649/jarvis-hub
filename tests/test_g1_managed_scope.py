"""G1 (H249 / H267 / H629) — operator-pinned ("managed") configuration.

What the owner and the administrator can rely on, from the owner's side:

* a setting the administrator pins in ``<managed dir>/config.yaml`` is what every reader
  sees (the settings readers, the runtime settings, the job tool policy, the telegram
  owner binding), over the stored value and over the selected product posture;
* every writer refuses to change it, naming the managed file: the settings PUT route,
  ``settings_db.put_category``, an import, a reset, an undo, ``nerva config set|unset|edit``
  and the approval-mode writer; a bulk write leaves the pin out and says which;
* an environment value pinned in ``<managed dir>/.env`` beats the process environment and
  both ``.env`` files under either spelling, and stays what ``env_config`` answers even
  after an in-process write to ``os.environ``;
* a profile's own pins apply on top of the shared ones;
* a managed file that cannot be read refuses every write and stops the hub's load (fail
  closed), instead of silently unpinning; the managed-mode marker refuses every write and
  names the command that changes the configuration;
* the CLI and the HUD's routes show which values are managed (names, never an
  environment value).

Hermetic: temp data root, temp managed directory, no network.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path

import pytest

from agents.cli.nerva import Context, main
from agents.core import env_alias, env_config, managed_scope, settings_db
from agents.core import env_provenance as ep

# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def managed(tmp_path, monkeypatch):
    """A temp settings store and an empty managed directory named by NERVA_MANAGED_DIR."""
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    monkeypatch.delenv("JARVIS_MANAGED_DIR", raising=False)
    directory = tmp_path / "etc-nerva"
    directory.mkdir()
    monkeypatch.setenv("NERVA_MANAGED_DIR", str(directory))
    managed_scope.invalidate()
    saved = env_config.pinned_environment()
    yield directory
    env_config.pin_environment(saved)
    managed_scope.invalidate()
    # a load in a test folds NERVA_MANAGED_DIR onto JARVIS_MANAGED_DIR, which monkeypatch never set
    os.environ.pop("JARVIS_MANAGED_DIR", None)


def _pin(directory: Path, text: str, name: str = "config.yaml") -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    # a fresh stat signature even within one clock tick
    managed_scope.invalidate()
    return path


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ=dict(os.environ), out=out, err=err, inp=io.StringIO(""),
                  client_factory=lambda env: None)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


# ── the location ─────────────────────────────────────────────────────────────

def test_no_managed_dir_under_pytest_means_nothing_is_pinned(monkeypatch):
    monkeypatch.delenv("NERVA_MANAGED_DIR", raising=False)
    monkeypatch.delenv("JARVIS_MANAGED_DIR", raising=False)
    assert managed_scope.managed_dir() == (None, False)
    assert not managed_scope.scope().active
    managed_scope.check_setting_write("llm", "cloud_fallback", "always")      # nothing refused


def test_both_spellings_name_the_directory(managed, monkeypatch):
    monkeypatch.delenv("NERVA_MANAGED_DIR")
    monkeypatch.setenv("JARVIS_MANAGED_DIR", str(managed))
    assert managed_scope.managed_dir() == (managed, True)


def test_a_dotenv_file_cannot_move_the_managed_directory():
    """The owner's .env could otherwise point the administrator's pins at an empty folder."""
    assert "JARVIS_MANAGED_DIR" in ep.FROM_PROCESS_ONLY
    assert env_config.other_spelling("NERVA_MANAGED_DIR") == "JARVIS_MANAGED_DIR"


# ── settings: readers see the pin ────────────────────────────────────────────

def test_readers_see_the_pinned_setting_over_the_stored_value(managed):
    settings_db.put_category("llm", {"cloud_fallback": "always"})
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    assert settings_db.get_value("llm", "cloud_fallback") == "never"
    assert settings_db.read_setting("llm", "cloud_fallback") == (True, "never")
    row = next(r for r in settings_db.get_category("llm") if r["key"] == "cloud_fallback")
    assert row["value"] == "never"
    assert row["managed"]["source"] == str(managed / "config.yaml")
    every = {r["key"]: r for r in settings_db.get_all()["llm"]}
    assert every["cloud_fallback"]["value"] == "never" and "managed" in every["cloud_fallback"]
    assert "managed" not in every["backend_type"]                       # the rest stays the owner's


def test_a_json_setting_is_pinned_leaf_by_leaf(managed):
    base = {"enabled": True, "flags": {}, "platform_overrides": {}, "agents": {}}
    settings_db.put_category("llm", {"operating_guidance": {**base, "flags": {"terse": True}}})
    _pin(managed, "llm:\n  operating_guidance:\n    enabled: false\n")
    assert settings_db.get_value("llm", "operating_guidance") == {**base, "enabled": False, "flags": {"terse": True}}
    # a write that keeps the pinned leaf passes; one that changes it is refused
    settings_db.put_category("llm", {"operating_guidance": {**base, "enabled": False}})
    assert settings_db.get_value("llm", "operating_guidance") == {**base, "enabled": False}
    with pytest.raises(managed_scope.ManagedRefused) as refused:
        settings_db.put_category("llm", {"operating_guidance": base})
    assert refused.value.names == ["llm.operating_guidance.enabled"]
    row = next(r for r in settings_db.get_category("llm") if r["key"] == "operating_guidance")
    assert row["managed"]["leaves"] == ["enabled"]


def test_the_pin_beats_the_product_posture(managed):
    from agents.core import product_posture

    forced = next(iter(name for name in product_posture.POSTURES if product_posture.POSTURES[name].get("applies")))
    key, value = next(iter(product_posture.POSTURES[forced]["applies"].items()))
    category, setting = key.split(".", 1)
    other = (not value) if isinstance(value, bool) else value
    _pin(managed, f"{category}:\n  {setting}: {json.dumps(other)}\n")
    flat = product_posture.apply_to_runtime_settings({"product.posture": forced, key: other})
    assert flat[key] == other


def test_a_pinned_reference_expands_only_from_the_process_environment(managed, monkeypatch, tmp_path):
    """A ${VAR} in a pinned value never takes a value an owner's .env supplied."""
    monkeypatch.setenv("G1_PROCESS_MODEL", "process-model")
    _pin(managed, "llm:\n  gemini_model: ${env:G1_PROCESS_MODEL}\n  reasoning_effort: ${G1_FROM_DOTENV}\n")
    assert managed_scope.setting_pin("llm", "gemini_model")[0] == "process-model"
    repo = tmp_path / "repo.env"
    repo.write_text("G1_FROM_DOTENV=high\n", encoding="utf-8")
    try:
        ep.load_layered_env(repo, None)
        assert os.environ["G1_FROM_DOTENV"] == "high"
        assert managed_scope.setting_pin("llm", "reasoning_effort")[0] == "${G1_FROM_DOTENV}"
    finally:
        os.environ.pop("G1_FROM_DOTENV", None)


def test_the_job_tool_policy_and_owner_binding_see_pins(managed):
    settings_db.ensure_initialized()
    _pin(managed, "autonomy:\n  allow_agent_scheduling: true\n  owner_chat_id: '42'\n")
    assert settings_db.read_job_tool_policy()["allow_agent_scheduling"] is True
    assert settings_db.read_telegram_owner_binding()["autonomy.owner_chat_id"] == "42"


def test_an_invalid_pin_is_a_problem_that_refuses_every_write(managed):
    """Review m1: not a silent fallback — the problem is listed, every write is refused
    (the hub's load refuses too, tests/test_g1_managed_review.py), and the value a reader
    gets is never the invalid one."""
    settings_db.ensure_initialized()
    _pin(managed, "llm:\n  cloud_fallback: sometimes\n")
    row = next(r for r in settings_db.get_category("llm") if r["key"] == "cloud_fallback")
    assert row["value"] == "on-demand" and row["managed"]["invalid"]
    assert any("cloud_fallback" in p for p in managed_scope.describe()["problems"])
    with pytest.raises(managed_scope.ManagedRefused) as refused:
        settings_db.put_category("llm", {"backend_type": "ollama"})          # not even this one
    assert "cannot be read" in str(refused.value) or "refused by its declaration" in str(refused.value)


# ── settings: every writer refuses ──────────────────────────────────────────

def test_put_category_refuses_a_pinned_key_and_writes_nothing(managed):
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    with pytest.raises(managed_scope.ManagedRefused) as refused:
        settings_db.put_category("llm", {"cloud_fallback": "always", "backend_type": "ollama"})
    assert "managed by your administrator" in str(refused.value)
    assert str(managed / "config.yaml") in str(refused.value)
    assert settings_db.get_value("llm", "backend_type") == "auto"          # nothing written


def test_put_category_leaves_out_a_key_sent_with_its_pinned_value(managed):
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    updated, skipped = settings_db.put_category("llm", {"cloud_fallback": "never", "backend_type": "ollama"})
    assert updated == 1 and skipped == ["cloud_fallback"]


def test_import_reset_and_undo_leave_pins_out_and_name_them(managed):
    settings_db.put_category("llm", {"cloud_fallback": "always", "backend_type": "ollama"})
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    changes, names = managed_scope.strip_settings({"llm": {"cloud_fallback": "always", "backend_type": "auto"}})
    assert changes == {"llm": {"backend_type": "auto"}} and names == ["llm.cloud_fallback"]
    assert settings_db.apply_import({"llm": {"cloud_fallback": "always"}}) == 0
    plan = settings_db.plan_reset("llm")
    assert "cloud_fallback" not in plan.get("llm", {}) and plan["llm"]["backend_type"] == "auto"
    moved, _snap = settings_db.reset_settings("llm")
    assert "cloud_fallback" not in moved["llm"]
    assert settings_db.managed_setting_names("llm") == ["llm.cloud_fallback"]


def test_undo_skips_a_setting_pinned_since_the_reset(managed):
    settings_db.put_category("llm", {"backend_type": "ollama"})
    settings_db.reset_settings("llm")
    _pin(managed, "llm:\n  backend_type: lm-studio\n")
    undone = settings_db.undo_last_reset()
    assert {"setting": "llm.backend_type",
            "reason": f"managed by your administrator ({managed / 'config.yaml'})"} in undone["skipped"]
    assert settings_db.get_value("llm", "backend_type") == "lm-studio"


def test_the_settings_put_route_refuses_with_409_naming_the_source(managed):
    from agents.core.routers import admin

    _pin(managed, "llm:\n  cloud_fallback: never\n")
    response = asyncio.run(admin.admin_put_category("llm", admin.AdminPutBody(values={"cloud_fallback": "always"})))
    assert response.status_code == 409
    body = json.loads(response.body)
    assert body["error"] == "managed" and body["managed"] == ["llm.cloud_fallback"]
    assert body["source"] == str(managed / "config.yaml")
    ok = asyncio.run(admin.admin_put_category("llm", admin.AdminPutBody(values={"cloud_fallback": "never"})))
    assert ok["managed"] == ["cloud_fallback"] and ok["updated"] == 0


def test_the_approval_mode_writer_refuses_a_pinned_mode(managed):
    from agents.core.autonomy import mode as approval_mode

    _pin(managed, "autonomy:\n  mode: ask\n")
    with pytest.raises(approval_mode.ModeManaged) as refused:
        approval_mode.set_global_mode(None, "auto", actor="owner", surface="test")
    assert "managed by your administrator" in str(refused.value)
    assert settings_db.get_value("autonomy", "mode") == "ask"
    _pin(managed, "autonomy:\n  agent_modes: {}\n")
    with pytest.raises(approval_mode.ModeManaged):
        approval_mode.set_agent_mode(None, "jarvis", "auto", actor="owner", surface="test")


# ── the CLI ──────────────────────────────────────────────────────────────────

def test_cli_config_set_and_unset_exit_1_naming_the_administrator(managed):
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    for argv in (["config", "set", "llm.cloud_fallback", "always"], ["config", "set", "llm.cloud_fallback", "never"],
                 ["config", "unset", "llm.cloud_fallback"]):
        code, _out, err = _run(argv)
        assert code == 1, argv
        assert "managed by your administrator" in err and str(managed / "config.yaml") in err
    assert settings_db.get_value("llm", "cloud_fallback") == "never"
    code, _out, _err = _run(["config", "set", "llm.backend_type", "ollama"])        # the rest stays writable
    assert code == 0


def test_cli_list_and_managed_show_which_values_are_managed(managed):
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    _pin(managed, "NERVA_STRICT_EGRESS=1\n", ".env")
    code, out, _err = _run(["config", "list", "llm"])
    assert code == 0
    line = next(line for line in out.splitlines() if line.startswith("llm.cloud_fallback"))
    assert "managed by your administrator" in line
    code, out, _err = _run(["config", "managed"])
    assert code == 0
    assert "setting  llm.cloud_fallback" in out and "env      JARVIS_STRICT_EGRESS" in out
    assert "=1" not in out                                                  # never an env value
    code, out, _err = _run(["config", "managed", "--json"])
    doc = json.loads(out)
    assert doc["settings"][0]["name"] == "llm.cloud_fallback" and doc["env"][0]["name"] == "JARVIS_STRICT_EGRESS"


def test_cli_edit_offers_no_line_for_a_managed_setting(managed):
    from agents.cli import nerva

    _pin(managed, "llm:\n  cloud_fallback: never\n")
    document, editable = nerva._edit_document(settings_db)
    assert "llm.cloud_fallback" not in editable
    assert "# llm.cloud_fallback: managed by your administrator" in document


# ── the environment ──────────────────────────────────────────────────────────

def test_managed_env_beats_the_process_environment_and_both_dotenv_files(managed, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")                       # the shell export
    repo = tmp_path / "repo.env"
    repo.write_text("NERVA_LOG_LEVEL=DEBUG\nG1_PLAIN=from-dotenv\n", encoding="utf-8")
    _pin(managed, "NERVA_STRICT_EGRESS=1\nJARVIS_LOG_LEVEL=WARNING\nG1_PLAIN=pinned\n", ".env")
    try:
        ep.load_layered_env(repo, None)
        applied = ep._apply_managed()
        assert applied == {"JARVIS_STRICT_EGRESS": "1", "JARVIS_LOG_LEVEL": "WARNING", "G1_PLAIN": "pinned"}
        assert os.environ["JARVIS_STRICT_EGRESS"] == "1" and os.environ["G1_PLAIN"] == "pinned"
        assert env_config.env_flag("NERVA_STRICT_EGRESS") is True
        assert env_config.env_str("JARVIS_LOG_LEVEL") == "WARNING"
        prov = ep.provenance()
        assert prov["JARVIS_STRICT_EGRESS"] == {"layer": "managed", "shadowed": ["process"]}
        assert prov["JARVIS_LOG_LEVEL"] == {"layer": "managed", "shadowed": ["repo_env"]}
        # authoritative in-process: a later write to os.environ does not change the readers
        os.environ["JARVIS_STRICT_EGRESS"] = "0"
        assert env_config.env_flag("JARVIS_STRICT_EGRESS") is True
        assert ep.hub_value("NERVA_LOG_LEVEL") == "WARNING"
    finally:
        for name in ("G1_PLAIN", "JARVIS_LOG_LEVEL"):
            os.environ.pop(name, None)


def test_a_managed_env_never_moves_the_hubs_own_files(managed):
    _pin(managed, "JARVIS_HOME=/srv/elsewhere\nNERVA_PROFILE=other\n", ".env")
    before = os.environ.get("JARVIS_HOME")
    applied = ep._apply_managed()
    assert applied == {} and os.environ.get("JARVIS_HOME") == before


def test_env_writers_consult_the_predicate(managed):
    _pin(managed, "NERVA_STRICT_EGRESS=1\nOPENAI_API_KEY=sk-admin\n", ".env")
    assert managed_scope.is_env_managed("JARVIS_STRICT_EGRESS")
    assert managed_scope.is_env_managed("NERVA_STRICT_EGRESS")
    assert managed_scope.is_env_managed("OPENAI_API_KEY")
    with pytest.raises(managed_scope.ManagedRefused) as refused:
        managed_scope.check_env_write("OPENAI_API_KEY")
    assert str(refused.value) == (f"cannot set OPENAI_API_KEY: it is managed by your administrator "
                                  f"({managed / '.env'}) and cannot be changed")
    managed_scope.check_env_write("ANTHROPIC_API_KEY")                     # not pinned: allowed


def test_env_sources_route_marks_the_managed_layer(managed):
    from agents.core.routers import admin

    _pin(managed, "NERVA_STRICT_EGRESS=1\n", ".env")
    response = asyncio.run(admin.admin_env_sources())
    body = json.loads(response.body)
    assert body["managed"]["env"] == [{"name": "JARVIS_STRICT_EGRESS", "source": str(managed / ".env")}]
    assert ep.LABELS["managed"] == "managed by your administrator"


# ── profile scope ────────────────────────────────────────────────────────────

def test_a_profiles_pins_apply_on_top_of_the_shared_ones(managed, monkeypatch):
    _pin(managed, "llm:\n  cloud_fallback: never\n  backend_type: ollama\n")
    (managed / "profiles" / "kids").mkdir(parents=True)
    _pin(managed / "profiles" / "kids", "llm:\n  backend_type: lm-studio\n")
    _pin(managed / "profiles" / "kids", "JARVIS_STRICT_EGRESS=1\n", ".env")
    assert managed_scope.setting_pin("llm", "backend_type")[0] == "ollama"
    assert not managed_scope.is_env_managed("JARVIS_STRICT_EGRESS")
    monkeypatch.setenv("JARVIS_PROFILE", "kids")
    current = managed_scope.scope()
    assert current.profile == "kids"
    assert managed_scope.setting_pin("llm", "backend_type", current)[0] == "lm-studio"
    assert managed_scope.setting_pin("llm", "cloud_fallback", current)[0] == "never"
    assert managed_scope.is_env_managed("JARVIS_STRICT_EGRESS", current)
    monkeypatch.setenv("JARVIS_PROFILE", "work")
    assert not managed_scope.is_env_managed("JARVIS_STRICT_EGRESS")


# ── fail closed, and managed mode ───────────────────────────────────────────

@pytest.mark.parametrize("name, text", [
    ("config.yaml", "llm: [not, a, mapping]\n"),
    ("config.yaml", "llm:\n  cloud_fallback: [unclosed\n"),
    (".env", "this line is not KEY=VALUE\n"),
    (".env", "NERVA_STRICT_EGRESS=1\nJARVIS_STRICT_EGRESS=0\n"),
])
def test_an_unreadable_managed_file_refuses_every_write(managed, name, text):
    _pin(managed, text, name)
    with pytest.raises(managed_scope.ManagedRefused) as refused:
        settings_db.put_category("llm", {"backend_type": "ollama"})          # not even pinned
    assert "cannot be read" in str(refused.value) and str(managed / name) in str(refused.value)
    with pytest.raises(managed_scope.ManagedRefused):
        managed_scope.check_env_write("ANYTHING")
    with pytest.raises(managed_scope.ManagedRefused):
        settings_db.reset_settings("llm")
    code, _out, err = _run(["config", "set", "llm.backend_type", "ollama"])
    assert code == 1 and "cannot be read" in err


def test_a_directory_in_place_of_a_managed_file_fails_closed(managed):
    (managed / "config.yaml").mkdir()
    with pytest.raises(managed_scope.ManagedRefused):
        managed_scope.check_writable()


def test_a_missing_explicit_managed_dir_fails_closed(managed, monkeypatch, tmp_path):
    monkeypatch.setenv("NERVA_MANAGED_DIR", str(tmp_path / "typo"))
    with pytest.raises(managed_scope.ManagedRefused):
        settings_db.put_category("llm", {"backend_type": "ollama"})


def test_the_hub_load_refuses_to_start_on_an_unreadable_managed_file(managed):
    _pin(managed, "bad line\n", ".env")
    with pytest.raises(env_alias.ConfigurationRefused):
        ep._apply_managed(refuse=True)
    assert any(row["kind"] == ep.MANAGED_UNREADABLE for row in ep.problems())
    ep._PROBLEMS[:] = [row for row in ep._PROBLEMS if row["kind"] != ep.MANAGED_UNREADABLE]


def test_readers_keep_the_last_good_pin_when_the_file_breaks(managed):
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    assert settings_db.get_value("llm", "cloud_fallback") == "never"
    path = managed / "config.yaml"
    path.write_text("llm: [broken\n", encoding="utf-8")
    assert settings_db.get_value("llm", "cloud_fallback") == "never"        # still pinned for readers
    with pytest.raises(managed_scope.ManagedRefused):
        settings_db.put_category("llm", {"cloud_fallback": "always"})


def test_the_managed_mode_marker_refuses_every_write_and_names_the_rebuild_command(managed):
    _pin(managed, "# set by the NixOS module\nsudo nixos-rebuild switch\n", ".managed")
    with pytest.raises(managed_scope.ManagedRefused) as refused:
        settings_db.put_category("llm", {"backend_type": "ollama"})
    assert "sudo nixos-rebuild switch" in str(refused.value)
    code, _out, err = _run(["config", "set", "llm.backend_type", "ollama"])
    assert code == 1 and "sudo nixos-rebuild switch" in err
    code, out, _err = _run(["config", "managed"])
    assert "managed mode" in out


# ── the HUD's routes, through the app ────────────────────────────────────────

@pytest.fixture
def client(managed, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import admin

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-g1")
    rows = []

    class Audit:
        def log(self, event):
            rows.append(event)

    monkeypatch.setattr(admin, "get_orch", lambda: type("O", (), {"audit": Audit()})())
    c = TestClient(web.app)
    c.rows = rows
    return c


HEADERS = {"X-Admin-Token": "adm-g1", "Content-Type": "application/json"}


def test_routes_refuse_audit_and_name_pins(client, managed):
    settings_db.put_category("llm", {"cloud_fallback": "always", "backend_type": "ollama"})
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    got = client.put("/api/admin/settings/llm", json={"values": {"cloud_fallback": "always"}}, headers=HEADERS)
    assert got.status_code == 409 and got.json()["error"] == "managed"
    assert any(row.action_taken == "settings_managed_refused" for row in client.rows)
    listed = client.get("/api/admin/settings/llm", headers=HEADERS).json()["llm"]
    assert next(r for r in listed if r["key"] == "cloud_fallback")["managed"]["source"] == str(managed / "config.yaml")
    imported = client.post("/api/admin/settings/import", headers=HEADERS,
                           content=json.dumps({"settings": {"llm": {"cloud_fallback": "on-demand",
                                                                    "backend_type": "auto"}}}))
    assert imported.status_code == 200, imported.text
    assert imported.json()["managed"] == ["llm.cloud_fallback"] and imported.json()["updated"] == 1
    reset = client.post("/api/admin/settings/llm/reset", headers=HEADERS, content="{}")
    assert reset.status_code == 200 and reset.json()["managed"] == ["llm.cloud_fallback"]
    assert settings_db.get_value("llm", "cloud_fallback") == "never"
    _pin(managed, "llm: [broken\n")
    refused = client.post("/api/admin/settings/llm/reset", headers=HEADERS, content="{}")
    assert refused.status_code == 409 and "cannot be read" in refused.json()["detail"]


def test_nerva_managed_turns_on_managed_mode_without_a_directory(managed, monkeypatch):
    """Hermes's HERMES_MANAGED: the package that installs Nerva says what manages it."""
    monkeypatch.delenv("NERVA_MANAGED_DIR")
    monkeypatch.setenv("NERVA_MANAGED", "nix")
    with pytest.raises(managed_scope.ManagedRefused) as refused:
        settings_db.put_category("llm", {"backend_type": "ollama"})
    assert "managed by nix" in str(refused.value)
    code, _out, err = _run(["config", "migrate"])
    assert code == 1 and "managed by nix" in err
    monkeypatch.setenv("NERVA_MANAGED", "0")
    settings_db.put_category("llm", {"backend_type": "ollama"})


def test_subsystem_writers_consult_the_managed_layer(managed):
    from agents.core import appearance

    settings_db.ensure_initialized()
    _pin(managed, "appearance:\n  preferences:\n    accent: amber\n")
    with pytest.raises(managed_scope.ManagedRefused):
        appearance.update_appearance({"accent": "green"})
    assert appearance.update_appearance({"accent": "amber"})       # keeps the pinned leaf
    assert appearance.read_appearance()["preferences"]["accent"] == "amber"
    _pin(managed, "appearance:\n  preferences:\n    accent: violet\n")    # pinned after the write
    assert appearance.read_appearance()["preferences"]["accent"] == "violet"
