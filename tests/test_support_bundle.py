"""0.55 — diagnostic support bundle: non-sensitive aggregates, defensive assembly."""

import json

import pytest

from agents.core import support_bundle


def test_bundle_has_all_sections_and_is_serializable():
    b = support_bundle.build_bundle(orch=None, now_iso="2026-06-28T00:00:00Z")
    assert set(b) >= {"meta", "posture", "capabilities", "egress", "audit", "routes"}
    json.dumps(b)  # must be plain-JSON (no exotic objects leaking through)


def test_meta_carries_version_and_generated_at():
    b = support_bundle.build_bundle(now_iso="STAMP")
    assert b["meta"]["generated_at"] == "STAMP"
    assert b["meta"].get("version") and b["meta"]["platform"]


def test_posture_reflects_default_off_hardened_and_balanced_profile(monkeypatch):
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    monkeypatch.delenv("JARVIS_SYSTEM_PROFILE", raising=False)
    p = support_bundle.build_bundle()["posture"]
    assert p["hardened"]["enabled"] is False
    assert p["product_posture"]["name"] == "off"
    assert "memory.recall_enabled" in p["product_posture"]["flags"]
    assert p["system_profile"]["active"] == "balanced"


def test_audit_uses_a_fake_orch_and_counts_by_type_only():
    class _Ev:
        def __init__(self, t): self.event_type = t

    class _Audit:
        def query(self, limit=100):
            return [_Ev("scan"), _Ev("scan"), _Ev("kernel_grant")]
        def verify_chain(self):
            return (True, None)

    class _Orch:
        audit = _Audit()

    a = support_bundle.build_bundle(_Orch())["audit"]
    assert a["recent_event_counts"] == {"scan": 2, "kernel_grant": 1}
    assert a["window"] == 3 and a["chain_ok"] is True
    # never leaks content/preview — only counts + integrity
    assert set(a) <= {"recent_event_counts", "window", "chain_ok", "chain_broken_at"}


def test_sections_degrade_to_unavailable_not_crash():
    class _Boom:
        @property
        def audit(self):
            raise RuntimeError("down")

    b = support_bundle.build_bundle(_Boom())
    assert b["audit"] == {"error": "unavailable"}      # one bad source never breaks the bundle
    assert "meta" in b and b["meta"]["platform"]


def test_no_obviously_sensitive_keys_anywhere():
    # H009: ``credentials`` lists key *variable names* (GEMINI_API_KEY) and ``overrides``
    # names changed settings (llm.max_tokens) — names on purpose, never values; the value
    # side is pinned by the sentinel tests below.
    bundle = support_bundle.build_bundle()
    bundle.pop("credentials")
    bundle["overrides"] = [item.get("value") for item in bundle["overrides"].get("settings", [])]
    blob = json.dumps(bundle).lower()
    for bad in ("token", "secret", "password", "api_key", "authorization", "private_key"):
        assert bad not in blob


def test_diagnostics_stay_local_there_is_no_upload_path():
    """H242: Hermes's ``diagnostics.share_nous`` uploads a debug bundle to the vendor;
    Nerva refused that path. The bundle is assembled in-process and served to the owner
    over one admin GET — no network client in either module, no write verb on the route."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    network = {"urllib", "http", "httpx", "requests", "aiohttp", "socket", "ftplib", "smtplib"}
    for rel in ("agents/core/support_bundle.py", "agents/core/routers/support.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        assert not imported & network, (rel, imported & network)

    from agents.core.routers.support import router

    verbs = {(method, route.path) for route in router.routes for method in route.methods}
    assert verbs == {("GET", "/api/support/bundle")}


# ── H009: model/provider, set key names, non-default overrides, the CLI verb ──


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    from agents.core import settings_db
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "data"))
    return settings_db


def test_model_section_names_the_selected_backend_and_models(temp_settings):
    temp_settings.put_category("llm", {"backend_type": "ollama", "default_model": "qwen3:8b"})
    model = support_bundle.build_bundle()["model"]
    assert model["backend_type"] == "ollama" and model["default_model"] == "qwen3:8b"
    # a base URL can carry credentials, so the model section never lists one
    assert set(model) == set(support_bundle._MODEL_KEYS)
    assert not any(k.endswith("_url") for k in model)


def test_credentials_list_names_only_never_a_value():
    sentinel = "sk-SENTINEL-do-not-leak-4242"
    env = {"GEMINI_API_KEY": sentinel, "ANTHROPIC_API_KEYS": f"{sentinel},{sentinel}2", "OPENAI_API_KEY": "  "}
    bundle = support_bundle.build_bundle(environ=env)
    creds = bundle["credentials"]
    assert "GEMINI_API_KEY" in creds["set"] and "ANTHROPIC_API_KEYS" in creds["set"]
    assert "OPENAI_API_KEY" in creds["unset"]          # blank is not set
    assert set(creds) == {"set", "unset"}
    assert "SENTINEL" not in json.dumps(bundle) and "SENTINEL" not in support_bundle.render_text(bundle)


def test_overrides_show_plain_values_and_withhold_free_text_and_secrets(temp_settings):
    temp_settings.put_category("llm", {"temperature": 0.2, "lm_studio_url": "http://u:pw@lan:1234"})
    temp_settings.put_category("integrations", {"twilio_auth_token": "tw-SENTINEL-secret"})
    over = support_bundle.build_bundle()["overrides"]
    by_name = {item["name"]: item for item in over["settings"]}
    assert by_name["llm.temperature"] == {"name": "llm.temperature", "source": "set", "value": 0.2}
    assert by_name["llm.lm_studio_url"]["withheld"] is True and "value" not in by_name["llm.lm_studio_url"]
    assert over["count"] == len(over["settings"])
    blob = json.dumps(over)
    assert "pw@lan" not in blob and "SENTINEL" not in blob
    assert all(item["source"] != "default" for item in over["settings"])


def test_render_text_is_a_short_pasteable_report(temp_settings):
    temp_settings.put_category("llm", {"backend_type": "ollama", "temperature": 0.2})
    bundle = support_bundle.build_bundle(now_iso="STAMP", environ={"GEMINI_API_KEY": "x"}, route_count=7)
    text = support_bundle.render_text(bundle)
    assert text.startswith("Nerva ") and "STAMP" in text
    assert "backend_type=ollama" in text and "keys set: GEMINI_API_KEY" in text
    assert "llm.temperature = 0.2  [set]" in text and "routes: 7" in text
    # a section that could not be read says so instead of vanishing
    assert "audit: unavailable" in text


def test_nerva_support_bundle_reads_the_hub_route_and_writes_an_owner_only_file(tmp_path):
    import io
    import stat

    from agents.cli.nerva import EXIT_OK, Context, command_tree, main

    calls = []

    class _Hub:
        def get(self, path):
            calls.append(path)
            return support_bundle.build_bundle(now_iso="HUB", route_count=3, environ={})

    out, err = io.StringIO(), io.StringIO()
    target = tmp_path / "bundle.txt"
    ctx = Context(environ={}, out=out, err=err, client_factory=lambda env: _Hub())
    assert main(["support", "bundle", "--out", str(target)], context=ctx) == EXIT_OK
    assert calls == ["/api/support/bundle"]
    assert "HUB" in out.getvalue() and "routes: 3" in out.getvalue()
    assert target.read_text(encoding="utf-8") == out.getvalue()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert command_tree()["support"] == ["bundle"]

    out = io.StringIO()
    ctx = Context(environ={}, out=out, err=io.StringIO(), client_factory=lambda env: _Hub())
    assert main(["support", "bundle", "--json"], context=ctx) == EXIT_OK
    assert json.loads(out.getvalue())["meta"]["generated_at"] == "HUB"


def test_nerva_support_bundle_offline_needs_no_hub(temp_settings):
    import io

    from agents.cli.nerva import EXIT_OK, Context, main

    def _no_hub(env):
        raise AssertionError("--offline must not open a hub client")

    out = io.StringIO()
    ctx = Context(environ={"ANTHROPIC_API_KEY": "k"}, out=out, err=io.StringIO(), client_factory=_no_hub)
    assert main(["support", "bundle", "--offline", "--json"], context=ctx) == EXIT_OK
    bundle = json.loads(out.getvalue())
    assert bundle["credentials"]["set"] == ["ANTHROPIC_API_KEY"]
    assert bundle["audit"] == {"error": "unavailable"} and bundle["routes"] is None
