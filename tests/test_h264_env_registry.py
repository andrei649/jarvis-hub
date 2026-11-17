"""H264 — an enumerated, inspectable environment-variable surface.

The registry (agents/core/env_registry.json) is generated from the source and the docs and
must stay fresh; it covers every hub variable; it never carries a credential's value or
default; ``nerva config env`` / ``config check`` and the doctor report set vs unset, what a
variable is for, and the .env names nothing reads — and never print a value.
"""

from __future__ import annotations

import io
import json

import pytest

from agents.cli.nerva import EXIT_OK, Context, main
from agents.core import env_alias, env_config, env_registry, settings_db
from scripts import gen_env_registry

SECRET = "sk-h264-never-printed-0123456789"


def test_the_committed_registry_is_what_the_generator_writes():
    assert gen_env_registry.render(gen_env_registry.build()) == env_registry.REGISTRY_FILE.read_text(encoding="utf-8"), \
        "run python scripts/gen_env_registry.py"


def test_every_hub_variable_is_declared_with_both_spellings_and_a_type():
    entries = env_registry.entries()
    for suffix in env_config.HUB_ENV_SUFFIXES:
        entry = entries["NERVA_" + suffix]
        assert entry["aliases"] == ["JARVIS_" + suffix]
        assert entry["type"] in {"flag", "text", "list", "int", "float", "json", "int_map", "path", "credential"}
        assert env_registry.canonical("JARVIS_" + suffix) == "NERVA_" + suffix
    # run-time families are known too
    assert env_registry.is_known("NERVA_ROLE_VISION_MODEL") and env_registry.is_known("JARVIS_VLM_PRESET_X")


def test_types_and_defaults_are_measured_from_the_typed_reads():
    entries = env_registry.entries()
    assert entries["NERVA_RATE_LIMIT"]["type"] == "int" and entries["NERVA_RATE_LIMIT"]["default"] == 120
    assert entries["NERVA_STRICT_EGRESS"]["type"] == "flag" and entries["NERVA_STRICT_EGRESS"]["default"] is True
    assert entries["NERVA_HOME"]["type"] == "path"


def test_a_credential_never_carries_a_default_and_is_classified():
    entries = env_registry.entries()
    for suffix in env_alias.CREDENTIALS:
        assert entries["NERVA_" + suffix]["type"] == "credential"
        assert entries["NERVA_" + suffix]["default"] is None
    # names outside the hub's namespace that .env.example declares are listed too
    assert entries["OPENAI_API_KEY"]["namespace"] == "other"
    assert entries["OPENAI_API_KEY"]["type"] == "credential"


def test_purposes_come_from_the_docs_and_required_is_named():
    admin = env_registry.entries()["NERVA_ADMIN_TOKEN"]
    assert "admin" in admin["purpose"].lower() and "REQUIRED" in admin["required_when"]
    assert env_registry.entries()["NERVA_ACTION_KERNEL"]["purpose"]


def test_prose_that_mentions_an_assignment_is_not_a_declaration():
    # ".env.example: '# NERVA_HARDENED=1 ignores the list.' sits above TLS_INSECURE_TARGETS"
    assert "certificate" not in env_registry.entries()["NERVA_HARDENED"]["purpose"].lower()


def test_status_says_set_and_where_never_the_value():
    table = {"JARVIS_RATE_LIMIT": {"layer": "repo_env", "shadowed": []},
             "JARVIS_ADMIN_TOKEN": {"layer": "process", "shadowed": []}}
    rows = {row["name"]: row for row in env_registry.status(table)}
    assert rows["NERVA_RATE_LIMIT"]["set"] and rows["NERVA_RATE_LIMIT"]["layer"] == "repo_env"
    assert rows["NERVA_ADMIN_TOKEN"]["set"] and "default" not in rows["NERVA_ADMIN_TOKEN"]
    assert not rows["NERVA_STRICT_LOCAL"]["set"]
    assert all(set(row) <= {"name", "set", "layer", "namespace", "type", "purpose", "required_when",
                            "section", "default"} for row in rows.values())


def test_unread_names_get_a_suggestion_and_known_names_none():
    found = env_registry.unread(["NERVA_STRICT_EGRES", "JARVIS_NOPE_NOTHING", "NERVA_RATE_LIMIT",
                                 "PATH", "JARVIS_RPC_SOCKET", "NERVA_ROLE_DEEP_MODEL"])
    assert found == [{"name": "JARVIS_NOPE_NOTHING", "did_you_mean": None},
                     {"name": "NERVA_STRICT_EGRES", "did_you_mean": "NERVA_STRICT_EGRESS"}]
    long = env_registry.unread(["NERVA_" + "X" * 10_000])
    assert len(long[0]["name"]) == 128


def test_introduced_since_names_what_an_earlier_build_did_not_list():
    names = list(env_registry.entries())
    assert env_registry.introduced_since([]) == []
    assert env_registry.introduced_since(names) == []
    assert env_registry.introduced_since(names[1:]) == [names[0]]


# ── the CLI ──────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    return tmp_path


def _run(argv, environ):
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ=environ, out=out, err=err, inp=io.StringIO(""), client_factory=lambda env: None)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def _environ(tmp_path, dotenv: str):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(dotenv, encoding="utf-8")
    return {"JARVIS_USER_HOME": str(home), "NERVA_ADMIN_TOKEN": SECRET, "NERVA_STRICT_LOCLA": "1"}


def test_config_env_lists_set_and_unset_with_purpose_never_a_value(temp_settings):
    environ = _environ(temp_settings, f"NERVA_RATE_LIMIT=60\nNERVA_TYPO_KNOB=1\nOPENAI_API_KEY={SECRET}\n")
    code, out, err = _run(["config", "env"], environ)
    assert code == EXIT_OK, err
    assert SECRET not in out + err
    assert "✓ NERVA_ADMIN_TOKEN  (process environment)" in out
    assert "✓ NERVA_RATE_LIMIT  (data-home .env)" in out
    assert "✓ OPENAI_API_KEY  (data-home .env)" in out
    assert "○ NERVA_STRICT_EGRESS  (default true)" in out
    assert "NERVA_TYPO_KNOB is set but nothing reads it" in out
    assert "NERVA_STRICT_LOCLA is set but nothing reads it — did you mean NERVA_STRICT_LOCAL?" in out

    code, out, _ = _run(["config", "env", "--set", "--json"], environ)
    doc = json.loads(out)
    assert code == EXIT_OK and SECRET not in out
    assert {row["name"] for row in doc["variables"]} >= {"NERVA_ADMIN_TOKEN", "NERVA_RATE_LIMIT", "OPENAI_API_KEY"}
    assert all(row["set"] for row in doc["variables"])
    assert {item["name"] for item in doc["unread"]} == {"NERVA_TYPO_KNOB", "NERVA_STRICT_LOCLA"}


def test_config_check_adds_the_environment_lines_without_failing_on_them(temp_settings):
    environ = _environ(temp_settings, "NERVA_TYPO_KNOB=1\n")
    code, out, err = _run(["config", "check"], environ)
    assert code == EXIT_OK, err
    assert "matches its declared schema" in out
    assert "declared variables set" in out and "NERVA_TYPO_KNOB is set but nothing reads it" in out
    assert SECRET not in out + err


def test_the_doctor_warns_about_an_unread_dotenv_name(tmp_path):
    from scripts import doctor

    repo_env = tmp_path / ".env"
    repo_env.write_text("NERVA_STRICT_EGRES=1\nNERVA_RATE_LIMIT=60\n", encoding="utf-8")
    check = doctor.check_config_sources(tmp_path, {})
    assert check.status == doctor.WARN
    assert "unread_env_names:1" in check.reason and "NERVA_STRICT_EGRESS" in check.reason
    assert check.data["unread"] == [{"name": "NERVA_STRICT_EGRES", "did_you_mean": "NERVA_STRICT_EGRESS"}]


# ── review m7: the .env reads behind these views are bounded and never follow a link ──────


def test_a_symlinked_or_oversized_dotenv_is_not_read(tmp_path):
    from agents.core import env_provenance as ep

    real = tmp_path / "real.env"
    real.write_text("NERVA_RATE_LIMIT=1\n", encoding="utf-8")
    link = tmp_path / "link.env"
    link.symlink_to(real)
    assert ep.env_file_keys(real) == ["NERVA_RATE_LIMIT"]
    assert ep.env_file_keys(link) == []
    big = tmp_path / "big.env"
    big.write_text("NERVA_RATE_LIMIT=1\n" + "#" * (ep.MAX_ENV_FILE_BYTES + 10) + "\n", encoding="utf-8")
    assert ep.env_file_keys(big) == []
