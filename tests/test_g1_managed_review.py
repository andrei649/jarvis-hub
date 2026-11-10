"""G1 adversarial review (2026-11-10): the bypasses the review found, each closed.

M1 the local model switch, M2 MCP add/remove, M3 an untrusted managed folder or file,
m1 a pin its declaration refuses, m2/m4 the captured environment, m3 a pinned ${NAME} in a
view, m5 ManagedRefused is no OSError, m6/m7 refused before anything is recorded or
written, m8 managed mode on the model-setup routes, and the nits.
"""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.core import env_config, managed_scope, settings_db


@pytest.fixture
def managed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    monkeypatch.delenv("JARVIS_MANAGED_DIR", raising=False)
    monkeypatch.delenv("NERVA_MANAGED", raising=False)
    directory = tmp_path / "etc-nerva"
    directory.mkdir()
    monkeypatch.setenv("NERVA_MANAGED_DIR", str(directory))
    # a test process (a non-root CI runner) owns its temp folder: trusted here only
    monkeypatch.setattr(managed_scope, "_TRUST_ANY_OWNER_FOR_TESTS", True)
    monkeypatch.setattr("agents.core.settings_db._LAST_VALID_PIN", {})
    managed_scope.invalidate()
    managed_scope.reset_capture()
    saved = env_config.pinned_environment()
    settings_db.ensure_initialized()
    yield directory
    env_config.pin_environment(saved)
    managed_scope.reset_capture()
    managed_scope.invalidate()
    os.environ.pop("JARVIS_MANAGED_DIR", None)


def _pin(directory, text, name="config.yaml"):
    path = directory / name
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o644)
    managed_scope.invalidate()
    return path


class Audit:
    def __init__(self):
        self.rows = []

    def log(self, event):
        self.rows.append(event.action_taken)


# ── M1: the local model switch ───────────────────────────────────────────────

def _switch_env(monkeypatch, router):
    import agents.core.routers.admin as admin
    import agents.core.routers.models_llm as models_llm

    async def listing():
        return {"models": [{"id": "evil:latest", "provider": "ollama", "available": True},
                           {"id": "other:latest", "provider": "lm-studio", "available": True}]}

    audit = Audit()
    monkeypatch.setattr(models_llm, "get_orch", lambda: SimpleNamespace(llm_router=router))
    monkeypatch.setattr(admin, "get_orch", lambda: SimpleNamespace(audit=audit))
    monkeypatch.setattr(models_llm, "_web", lambda: SimpleNamespace(_list_local_models=listing))
    monkeypatch.setattr(models_llm, "invalidate_local_model_inventory_cache", MagicMock())
    monkeypatch.setattr(models_llm, "_model_switch_lock", asyncio.Lock())
    monkeypatch.setattr(models_llm, "put_category", settings_db.put_category)
    monkeypatch.setattr(models_llm, "get_value", settings_db.get_value)
    return models_llm, audit


def test_m1_a_pinned_model_is_not_switched_live(managed, monkeypatch):
    _pin(managed, "llm:\n  default_model: qwen3:7b\n")
    router = SimpleNamespace(active_model="qwen3:7b", _backend_name="ollama", backend_type="ollama")
    router.set_active_model = MagicMock(side_effect=lambda m: setattr(router, "active_model", m))
    router.detect = AsyncMock()
    models_llm, audit = _switch_env(monkeypatch, router)
    resp = asyncio.run(models_llm.models_local_switch(models_llm.LocalModelSwitch(model="evil:latest")))
    assert resp.status_code == 409 and json.loads(resp.body)["error"] == "managed"
    assert router.active_model == "qwen3:7b" and not router.set_active_model.called
    assert "settings_managed_refused" in audit.rows


def test_m1_a_rollback_never_counts_a_pinned_setting_as_lost(managed, monkeypatch):
    import agents.core.routers.models_llm as models_llm

    _pin(managed, "llm:\n  backend_type: ollama\n")
    router = SimpleNamespace(active_model="m", _backend_name="ollama", backend_type="ollama")
    router.set_active_model = MagicMock(side_effect=lambda m: setattr(router, "active_model", m))
    router.detect = AsyncMock()
    monkeypatch.setattr(models_llm, "put_category", settings_db.put_category)
    monkeypatch.setattr(models_llm, "get_value", settings_db.get_value)
    result = asyncio.run(models_llm._restore_local_provider(
        router, provider="ollama", backend_type="lm-studio", default_model="m", runtime_model="m"))
    assert result["ok"] is True                       # nothing refused, nothing "incomplete"


# ── M2: MCP add / remove ─────────────────────────────────────────────────────

@pytest.mark.parametrize("pin", [("config.yaml", "mcp:\n  servers: []\n"), (".managed", "locked\n")])
def test_m2_mcp_add_and_remove_refuse_before_the_live_manager_changes(managed, monkeypatch, pin):
    from agents.core import safe_mode
    from agents.core.routers import mcp as mcp_router

    servers: dict = {"kept": SimpleNamespace(close=AsyncMock())}
    orch = SimpleNamespace(audit=Audit(), mcp=SimpleNamespace(servers=servers, to_config=lambda: []))
    monkeypatch.setattr(mcp_router, "get_orch", lambda: orch)
    monkeypatch.setattr("agents.core.app_state.get_orch", lambda: orch)
    monkeypatch.setattr(safe_mode, "enabled", lambda: False)
    _pin(managed, pin[1], pin[0])
    body = mcp_router.MCPServerConfig(name="exfil", command="python -m evil", transport="stdio")
    added = asyncio.run(mcp_router.admin_mcp_add(body))
    removed = asyncio.run(mcp_router.admin_mcp_remove("kept"))
    assert added.status_code == removed.status_code == 409
    assert set(servers) == {"kept"}
    assert orch.audit.rows.count("settings_managed_refused") == 2


# ── M3: who may write the managed folder ─────────────────────────────────────

@pytest.mark.skipif(os.name == "nt" or os.geteuid() != 0, reason="needs root to change ownership")
def test_m3_a_managed_file_the_owner_can_write_is_refused(managed, monkeypatch):
    monkeypatch.setattr(managed_scope, "_TRUST_ANY_OWNER_FOR_TESTS", False)     # the real check
    path = _pin(managed, "llm:\n  cloud_fallback: never\n")
    os.chown(path, 1000, 1000)
    managed_scope.invalidate()
    assert any("not owned by root" in p for p in managed_scope.scope().problems)
    with pytest.raises(managed_scope.ManagedRefused):
        settings_db.put_category("llm", {"backend_type": "ollama"})
    os.chown(path, 0, 0)
    os.chmod(path, 0o666)
    managed_scope.invalidate()
    assert any("writable by its group or by others" in p for p in managed_scope.scope().problems)
    os.chmod(managed, 0o777)
    os.chmod(path, 0o644)
    managed_scope.invalidate()
    assert any(str(managed) in p and "writable" in p for p in managed_scope.scope().problems)
    os.chmod(managed, 0o755)


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership")
def test_round2_b1_the_real_check_refuses_a_folder_not_owned_by_root(managed, monkeypatch):
    """Any runner: the production check (not the test trust) refuses a non-root owner."""
    monkeypatch.setattr(managed_scope, "_TRUST_ANY_OWNER_FOR_TESTS", False)
    real = os.stat(managed)
    fake = os.stat_result((real.st_mode, real.st_ino, real.st_dev, real.st_nlink, 1001, 1001,
                           real.st_size, int(real.st_atime), int(real.st_mtime), int(real.st_ctime)))
    assert "not owned by root" in managed_scope._stat_problem(managed, fake)
    monkeypatch.setattr(managed_scope, "_TRUST_ANY_OWNER_FOR_TESTS", True)
    assert managed_scope._stat_problem(managed, fake) is None
    world = os.stat_result((0o40777, *list(fake)[1:]))
    assert "writable by its group or by others" in managed_scope._stat_problem(managed, world)
    assert managed_scope._TRUST_ANY_OWNER_FOR_TESTS is True and "TRUST_ANY" not in \
        (__import__("pathlib").Path(managed_scope.__file__).read_text().split("_TRUST_ANY_OWNER_FOR_TESTS = False")[1]
         .split("def ")[0])                                  # declared False, set nowhere else


def test_round2_w1_windows_owner_is_read_with_ctypes(tmp_path, monkeypatch):
    """No pywin32: the owner SID comes from advapi32 through ctypes; only Administrators or
    SYSTEM make the default folder count."""
    src = __import__("pathlib").Path(managed_scope.__file__).read_text()
    assert "win32security" not in src and "GetNamedSecurityInfoW" in src
    assert managed_scope._owner_sid_string(tmp_path) is None or os.name == "nt"   # off Windows: None
    for sid, trusted in (("S-1-5-32-544", True), ("S-1-5-18", True), ("S-1-5-21-1-2-3-1001", False), (None, False)):
        monkeypatch.setattr(managed_scope, "_owner_sid_string", lambda path, sid=sid: sid)
        assert managed_scope._windows_admin_owned(tmp_path) is trusted


def test_round2_a3_an_untrusted_file_is_never_applied_readers_keep_the_last_trusted(managed):
    settings_db.put_category("llm", {"cloud_fallback": "always"})
    path = _pin(managed, "llm:\n  cloud_fallback: never\n")
    assert settings_db.get_value("llm", "cloud_fallback") == "never"
    os.chmod(path, 0o666)                                   # an administrator's mistake …
    path.write_text("llm:\n  cloud_fallback: on-demand\n")  # … and anyone edits it
    managed_scope.invalidate()
    current = managed_scope.scope()
    assert any("writable" in p for p in current.problems)
    assert settings_db.get_value("llm", "cloud_fallback") == "always"   # never the untrusted content
    with pytest.raises(managed_scope.ManagedRefused):
        settings_db.put_category("llm", {"backend_type": "ollama"})


def test_round2_a3_last_trusted_parse_survives_an_untrusted_edit(managed):
    path = _pin(managed, "llm:\n  cloud_fallback: never\n")
    managed_scope.scope()                                   # read while trusted
    os.chmod(path, 0o666)
    path.write_text("llm:\n  cloud_fallback: on-demand\n")
    os.utime(path, None)
    current = managed_scope.scope()                         # cache kept, no invalidate
    assert current.settings["llm"]["cloud_fallback"] == "never"


@pytest.mark.skipif(os.name == "nt", reason="POSIX folders")
def test_round2_profile_folders_are_checked_too(managed, monkeypatch):
    folder = managed / "profiles" / "kids"
    folder.mkdir(parents=True)
    os.chmod(managed / "profiles", 0o777)
    monkeypatch.setenv("JARVIS_PROFILE", "kids")
    managed_scope.invalidate()
    assert any("profiles" in p and "writable" in p for p in managed_scope.scope().problems)
    os.chmod(managed / "profiles", 0o755)


# ── m1: a pin its declaration refuses ────────────────────────────────────────

def test_m1_an_invalid_pin_is_a_problem_writes_and_boot_refuse(managed):
    from agents.core import env_alias
    from agents.core import env_provenance as ep

    settings_db.put_category("llm", {"cloud_fallback": "always"})
    _pin(managed, "llm:\n  cloud_fallback: Never\n  no_such_setting: 1\n")
    info = managed_scope.describe()
    assert any("cloud_fallback is refused by its declaration" in p for p in info["problems"])
    assert not any("Never" in p for p in info["problems"])          # the value only in details
    assert any("Never" in d for d in info["details"])
    # round 2: an undeclared name warns (an upgrade renamed it?) and never stops the hub
    assert any("llm.no_such_setting is not a declared setting" in w for w in info["warnings"])
    assert not any("no_such_setting" in p for p in info["problems"])
    with pytest.raises(managed_scope.ManagedRefused):
        settings_db.put_category("llm", {"backend_type": "ollama"})
    with pytest.raises(env_alias.ConfigurationRefused):
        ep._apply_managed(refuse=True)
    ep._PROBLEMS[:] = [row for row in ep._PROBLEMS if row["kind"] != ep.MANAGED_UNREADABLE]


# ── m2 / m4: what the hub's load captured ────────────────────────────────────

def test_m2_an_inprocess_environ_write_moves_neither_the_folder_nor_managed_mode(managed, tmp_path, monkeypatch):
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    _pin(managed, "locked\n", ".managed")
    managed_scope.capture(force=True)                      # what load_hub_env does
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("NERVA_MANAGED_DIR", str(empty))
    managed_scope.invalidate()
    assert settings_db.get_value("llm", "cloud_fallback") == "never"
    with pytest.raises(managed_scope.ManagedRefused):
        settings_db.put_category("llm", {"cloud_fallback": "always"})


def test_m4_a_pinned_reference_never_expands_from_a_value_placed_after_the_load(managed, monkeypatch):
    monkeypatch.setenv("PIN_FROM_PROCESS", "admin-model")
    managed_scope.capture(force=True)                            # load_hub_env, before the .env files
    managed_scope.capture_process_env(dict(os.environ), force=True)   # and after them
    monkeypatch.setenv("PIN_MODEL_REF", "owner-controlled")      # e.g. an Integrations panel key
    _pin(managed, "llm:\n  default_model: ${PIN_MODEL_REF}\n  deep_model: ${PIN_FROM_PROCESS}\n")
    assert settings_db.get_value("llm", "default_model") == "${PIN_MODEL_REF}"
    assert settings_db.get_value("llm", "deep_model") == "admin-model"


# ── m3: a view shows the reference, not the administrator's value ───────────

def test_m3_a_view_shows_a_pinned_reference_as_written(managed, monkeypatch):
    spec = next(s for s in settings_db.DEFAULTS if settings_db.is_secret_setting(s["category"], s["key"])
                and s["kind"] not in ("toggle", "select", "number", "slider", "json"))
    cat, key = spec["category"], spec["key"]
    monkeypatch.setenv("ADMIN_ONLY_SECRET", "s3cr3t-value-from-admin-env")
    _pin(managed, f"{cat}:\n  {key}: '${{ADMIN_ONLY_SECRET}}'\n")
    row = next(r for r in settings_db.get_category(cat) if r["key"] == key)
    assert row["value"] == "${ADMIN_ONLY_SECRET}"
    every = {r["key"]: r for r in settings_db.get_all()[cat]}
    assert every[key]["value"] == "${ADMIN_ONLY_SECRET}"
    assert settings_db.get_value(cat, key) == "s3cr3t-value-from-admin-env"     # readers: expanded
    used = {r["key"]: r for r in settings_db.interpolated(settings_db.get_all())[cat]}
    assert used[key]["value"] == "s3cr3t-value-from-admin-env"


# ── m5: no OSError, 409 everywhere ───────────────────────────────────────────

def test_m5_managed_refused_is_not_an_os_error_and_a_route_answers_409(managed, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web

    assert not issubclass(managed_scope.ManagedRefused, OSError)
    _pin(managed, "appearance:\n  preferences:\n    accent: amber\n")
    orch = SimpleNamespace(audit=Audit())
    monkeypatch.setattr("agents.core.app_state.get_orch", lambda: orch)
    client = TestClient(web.app, raise_server_exceptions=False)
    got = client.put("/api/preferences/appearance", json={"accent": "green"})
    assert got.status_code == 409 and got.json()["error"] == "managed"
    assert orch.audit.rows == ["settings_managed_refused"]


# ── m6 / m7: refused before anything is recorded or written ──────────────────

def test_m6_memory_write_approval_is_refused_before_the_intent_log_records_it(managed):
    from agents.core.learning import memory_proposals

    _pin(managed, "memory:\n  write_approval: true\n")
    recorded = []
    log = SimpleNamespace(record=lambda **kw: recorded.append(kw))
    with pytest.raises(managed_scope.ManagedRefused):
        memory_proposals.set_write_approval(False, audit=log)
    assert recorded == []


def test_m7_the_self_improvement_bundle_is_all_or_nothing(managed, monkeypatch):
    from agents.core.routers import self_improvement

    _pin(managed, "autonomy:\n  tech_scout_enabled: false\n")
    before = settings_db.get_value("cognition", "enabled")
    with pytest.raises(managed_scope.ManagedRefused):
        asyncio.run(self_improvement.self_improvement_enable())
    assert settings_db.get_value("cognition", "enabled") == before


def test_m7_a_plugin_toggle_is_judged_before_it_writes(managed):
    from agents.core import load_set

    _pin(managed, "loadset:\n  plugins_disabled: ''\n")
    with pytest.raises(managed_scope.ManagedRefused):
        load_set.persist_plugin("fooplug", False)
    assert settings_db.get_value("loadset", "plugins_disabled") == ""


# ── m8: managed mode on the model-setup routes ───────────────────────────────

def test_m8_model_setup_routes_are_refused_in_managed_mode(managed):
    _pin(managed, "sudo nixos-rebuild switch\n", ".managed")
    for selection in (True, False):
        with pytest.raises(managed_scope.ManagedRefused) as refused:
            managed_scope.check_llm_write(selection=selection)
        assert "sudo nixos-rebuild switch" in str(refused.value)


def test_m8_a_pinned_model_choice_refuses_provider_selection(managed):
    _pin(managed, "llm:\n  compatible_provider: ''\n")
    with pytest.raises(managed_scope.ManagedRefused):
        managed_scope.check_llm_write(selection=True)
    managed_scope.check_llm_write(selection=False)        # credentials stay the owner's


def test_m8_the_routes_call_the_gate():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "agents" / "core" / "routers"
    for name in ("custom_endpoints.py", "provider_selection.py", "provider_credentials.py"):
        assert "check_llm_write(" in (root / name).read_text(encoding="utf-8"), name


# ── nits ─────────────────────────────────────────────────────────────────────

def test_chat_approvals_names_the_managed_file(managed, monkeypatch):
    from agents.core.autonomy import mode as approval_mode

    path = _pin(managed, "autonomy:\n  mode: ask\n")
    with pytest.raises(approval_mode.ModeManaged) as refused:
        approval_mode.set_global_mode(None, "auto", actor="owner", surface="chat")
    assert str(path) in str(refused.value)
    src = (__import__("pathlib").Path(__file__).resolve().parents[1] / "agents/core/commands.py").read_text()
    assert "except approval_mode.ModeManaged as exc" in src


# ── round 2: A1, A2, A4, undeclared names, 409 bodies, provider packages ────

def test_round2_a1_a_pin_made_invalid_while_running_keeps_the_last_valid_pin(managed):
    settings_db.put_category("llm", {"cloud_fallback": "always"})
    _pin(managed, "llm:\n  cloud_fallback: never\n")
    assert settings_db.get_value("llm", "cloud_fallback") == "never"
    _pin(managed, "llm:\n  cloud_fallback: Never\n")              # the administrator's typo
    assert managed_scope.scope().problems
    assert settings_db.get_value("llm", "cloud_fallback") == "never"   # not the owner's "always"


def test_round2_a2_the_check_uses_what_readers_expand_from(managed, monkeypatch):
    settings_db.put_category("llm", {"cloud_fallback": "always"})
    managed_scope.capture(force=True)
    monkeypatch.setenv("FALLBACK_REF", "never")                    # an owner .env value
    _pin(managed, "llm:\n  cloud_fallback: ${FALLBACK_REF}\n")
    env = dict(os.environ)
    env.pop("FALLBACK_REF")                                        # not the process environment
    managed_scope.capture_process_env(env, force=True)
    assert managed_scope.scope().problems                          # judged with the capture
    with pytest.raises(managed_scope.ManagedRefused):
        settings_db.put_category("llm", {"backend_type": "ollama"})


def test_round2_a2_the_load_captures_before_it_judges():
    src = (__import__("pathlib").Path(__file__).resolve().parents[1] / "agents/core/env_provenance.py").read_text()
    body = src.split("def _apply_managed")[1]
    assert body.index("capture_process_env()") < body.index("env_pins(strict=True)")


def test_round2_a4_a_restart_hands_on_the_process_environment_only(monkeypatch):
    from agents.core import env_provenance as ep
    from agents.core import integration_keys

    monkeypatch.setitem(ep._TABLE, "G1_FROM_DOTENV", {"layer": ep.USER_ENV, "shadowed": []})
    monkeypatch.setitem(ep._LOADED, "G1_FROM_DOTENV", (ep.USER_ENV, ep._digest("dotenv")))
    monkeypatch.setitem(ep._TABLE, "G1_PINNED", {"layer": ep.MANAGED, "shadowed": []})
    monkeypatch.setitem(ep._LOADED, "G1_PINNED", (ep.MANAGED, ep._digest("pinned")))
    monkeypatch.setitem(ep._TABLE, "G1_PROCESS", {"layer": ep.PROCESS, "shadowed": []})
    monkeypatch.setitem(integration_keys._PLACED, "G1_PANEL", integration_keys._digest("panel"))
    monkeypatch.setenv("G1_PANEL", "panel")
    env = {"G1_FROM_DOTENV": "dotenv", "G1_PINNED": "pinned", "G1_PROCESS": "kept", "G1_PANEL": "panel"}
    assert ep.successor_environ(env) == {"G1_PROCESS": "kept"}
    src = (__import__("pathlib").Path(__file__).resolve().parents[1] / "serve.py").read_text()
    assert src.count("successor_environ(os.environ)") == 2           # exec and spawn


def test_round2_provider_packages_are_refused_in_managed_mode(managed):
    from agents.core.routers import models_llm

    _pin(managed, "locked\n", ".managed")
    with pytest.raises(managed_scope.ManagedRefused):
        models_llm._refuse_package_change_when_managed()
    src = __import__("pathlib").Path(models_llm.__file__).read_text()
    for route in ("provider_packages_promote", "provider_packages_revoke"):
        assert "_refuse_package_change_when_managed()" in src.split(f"def {route}")[1].split("@router")[0]
    assert {"stage", "propose", "decide"} <= models_llm._PACKAGE_MUTATIONS
