"""H248 — one effective-value view with the supplying plane per name.

``nerva config get NAME --explain`` (agents/core/config_resolve.py) answers what value is in
effect and which plane supplied it — default, store, environment reference, managed pin,
posture overlay; the environment's layers; the agent registry — and never prints a secret.
"""

from __future__ import annotations

import io
import json
import os

import pytest

from agents.cli.nerva import EXIT_FAILED, EXIT_OK, Context, main
from agents.core import config_resolve, env_config, managed_scope, settings_db

SECRET = "sk-h248-never-shown-0123456789"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("JARVIS_PROFILE", raising=False)
    monkeypatch.delenv("JARVIS_MANAGED_DIR", raising=False)
    monkeypatch.delenv("NERVA_MANAGED_DIR", raising=False)
    return tmp_path


def _run(argv, environ=None):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ=dict(environ or {}), out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: None)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def test_a_default_and_a_stored_value_name_their_plane(store):
    view = config_resolve.explain("llm.tool_loop_max_iterations")
    assert view["supplied_by"] == "default" and [layer["plane"] for layer in view["layers"]] == ["default", "store"]
    settings_db.put_category("llm", {"tool_loop_max_iterations": 12})
    view = config_resolve.explain("llm.tool_loop_max_iterations")
    assert view["value"] == 12 and view["supplied_by"] == "store"
    code, out, _ = _run(["config", "get", "llm.tool_loop_max_iterations", "--explain"])
    assert code == EXIT_OK
    assert "= 12  (supplied by: store)" in out and "← store" in out and "  default" in out


def test_an_environment_reference_is_the_supplying_plane_and_shows_no_value(store, monkeypatch):
    monkeypatch.setenv("H248_URL", "http://lms.local:1234")
    settings_db.put_category("llm", {"lm_studio_url": "${env:H248_URL}"})
    view = config_resolve.explain("llm.lm_studio_url")
    assert view["value"] == "http://lms.local:1234" and view["supplied_by"] == "environment reference"
    ref = next(layer for layer in view["layers"] if layer["plane"] == "environment reference")
    assert ref["names"] == [{"name": "H248_URL", "set": True}]
    store_layer = next(layer for layer in view["layers"] if layer["plane"] == "store")
    assert store_layer["value"] == "${env:H248_URL}"          # as written, never the expansion


def test_a_secret_setting_is_masked_in_every_plane(store):
    secret_key = sorted(settings_db.SECRET_KEYS)[0]
    category = next(c for (c, k) in settings_db._SPEC if k == secret_key)
    settings_db.put_category(category, {secret_key: SECRET})
    view = config_resolve.explain(f"{category}.{secret_key}")
    assert view["secret"] and SECRET not in json.dumps(view)
    code, out, err = _run(["config", "get", f"{category}.{secret_key}", "--explain", "--reveal"])
    assert code == EXIT_OK and SECRET not in out + err and config_resolve.MASK in out


def test_a_managed_pin_is_named_as_the_plane_in_effect(store, monkeypatch):
    directory = store / "etc-nerva"
    directory.mkdir()
    monkeypatch.setenv("NERVA_MANAGED_DIR", str(directory))
    monkeypatch.setattr(managed_scope, "_TRUST_ANY_OWNER_FOR_TESTS", True)
    monkeypatch.setattr("agents.core.settings_db._LAST_VALID_PIN", {})
    saved = env_config.pinned_environment()
    try:
        (directory / "config.yaml").write_text("llm:\n  cloud_fallback: never\n", encoding="utf-8")
        managed_scope.invalidate()
        view = config_resolve.explain("llm.cloud_fallback")
        assert view["supplied_by"] == "managed" and view["value"] == "never"
        assert any(layer["plane"] == "managed" and layer["applies"] for layer in view["layers"])
    finally:
        env_config.pin_environment(saved)
        managed_scope.invalidate()
        os.environ.pop("JARVIS_MANAGED_DIR", None)


def test_a_selected_posture_is_named_for_the_runtime(store):
    settings_db.put_category("product", {"posture": "companion_wave1"})
    view = config_resolve.explain("memory.recall_enabled")
    posture = next(layer for layer in view["layers"] if layer["plane"] == "posture")
    assert posture["source"] == "product.posture:companion_wave1" and posture["value"] is True
    assert view["runtime"] == {"value": True, "supplied_by": "posture"}
    code, out, _ = _run(["config", "get", "memory.recall_enabled", "--explain"])
    assert code == EXIT_OK and "the selected posture forces it" in out


def test_an_environment_variable_reports_layers_never_a_value(store):
    home = store / "home"
    home.mkdir()
    (home / ".env").write_text(f"NERVA_ADMIN_TOKEN={SECRET}\nNERVA_RATE_LIMIT=60\n", encoding="utf-8")
    environ = {"JARVIS_USER_HOME": str(home), "NERVA_RATE_LIMIT": "30"}
    view = config_resolve.explain("JARVIS_RATE_LIMIT", environ)
    assert view["name"] == "NERVA_RATE_LIMIT" and view["set"] and view["supplied_by"] == "process environment"
    planes = {layer["plane"]: layer.get("applies") for layer in view["layers"]}
    assert planes["process environment"] is True and planes["data-home .env"] is False
    assert any(layer["plane"] == "default" and layer["value"] == 120 for layer in view["layers"])
    code, out, err = _run(["config", "get", "NERVA_ADMIN_TOKEN", "--explain"], environ)
    assert code == EXIT_OK and "set  (supplied by: data-home .env)" in out
    assert SECRET not in out + err
    code, out, _ = _run(["config", "get", "NERVA_ADMIN_TOKEN", "--explain", "--json"], environ)
    assert SECRET not in out and json.loads(out)["kind"] == "environment"


def test_an_unknown_prefixed_name_is_said_to_be_unread(store):
    code, out, _ = _run(["config", "get", "NERVA_NOT_A_THING", "--explain"])
    assert code == EXIT_OK and "nothing in this build reads it" in out


def test_an_agent_field_comes_from_the_registry(store):
    view = config_resolve.explain("agents.jarvis.model")
    assert view["supplied_by"] == "agents.yaml" and isinstance(view["value"], str)
    assert config_resolve.explain("agents.jarvis.secret_field") is None
    assert config_resolve.explain("agents.nobody.model") is None


def test_an_unknown_setting_fails_with_a_suggestion(store):
    code, _, err = _run(["config", "get", "llm.tool_loop_max_iteration", "--explain"])
    assert code == EXIT_FAILED and "did you mean llm.tool_loop_max_iterations" in err
    assert config_resolve.explain("x" * 600) is None
