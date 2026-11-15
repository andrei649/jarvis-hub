"""H084: owner chat reports egress evidence without resolving credentials."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import env_provenance, support_bundle
from agents.core.channels import outbound_safety
from agents.core.commands import Principal, build_default_registry
from agents.core.observability.egress_monitor import EGRESS_MONITOR

OWNER = Principal(channel="web", admin=True)
GUEST = Principal(channel="telegram", sender="guest", admin=False)
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "WSS_PROXY",
              "DISCORD_PROXY", "TELEGRAM_PROXY", "http_proxy", "https_proxy",
              "all_proxy", "no_proxy", "wss_proxy")


@pytest.fixture
def rig(monkeypatch):
    for key in PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)

    class Broker:
        def names(self):
            return ["github_token", "project.key"]

        @staticmethod
        def reference(name):
            return f"{{{{secret:{name}}}}}"

        def get(self, _name):
            pytest.fail("egress status must not resolve a secret")

        def inject(self, *_args, **_kwargs):
            pytest.fail("egress status must not inject a secret")

    orch = SimpleNamespace(secret_broker=Broker(), commands=build_default_registry())
    monkeypatch.setattr(EGRESS_MONITOR, "snapshot", lambda **_kw: {
        "external_egress_total": 4, "model_egress_total": 2,
        "ledger": {"persistent": True, "error": ""}, "clean": True,
    })
    monkeypatch.setattr(support_bundle, "_credentials", lambda: {
        "set": ["GEMINI_API_KEY"], "unset": ["OPENAI_API_KEY"],
    })
    monkeypatch.setattr(env_provenance, "provenance", lambda: {
        "GEMINI_API_KEY": {"layer": env_provenance.RUNTIME, "shadowed": []},
    })
    return orch


async def _dispatch(rig, text="/egress", principal=OWNER):
    return await rig.commands.dispatch(text, orch=rig, principal=principal)


async def test_owner_receives_bounded_status_guest_and_args_do_not_read(rig, monkeypatch):
    assert rig.commands.get("egress").tier == "admin"
    calls = []
    original = EGRESS_MONITOR.snapshot

    def observed(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(EGRESS_MONITOR, "snapshot", observed)
    denied = await _dispatch(rig, principal=GUEST)
    refused = await _dispatch(rig, "/egress https://example.com")
    assert denied.status == "refused" and "Usage" in refused.reply
    assert calls == []
    answer = await _dispatch(rig)
    assert answer.status == "answered" and calls == [{"limit": 0}]
    assert "persistent" in answer.reply.lower() and "4" in answer.reply
    assert "model" in answer.reply.lower() and "2" in answer.reply
    assert "instrumented model and plugin" in answer.reply.lower()
    assert "GEMINI_API_KEY" in answer.reply and "runtime" in answer.reply
    assert "{{secret:github_token}}" in answer.reply


async def test_proxy_env_is_configured_not_claimed_active_and_value_is_withheld(rig, monkeypatch):
    secret_url = "http://user:proxy-password-123@egress.internal:8080"
    monkeypatch.setenv("HTTPS_PROXY", secret_url)
    monkeypatch.setattr(env_provenance, "provenance", lambda: {
        "HTTPS_PROXY": {"layer": env_provenance.PROCESS, "shadowed": []},
        "GEMINI_API_KEY": {"layer": env_provenance.RUNTIME, "shadowed": []},
    })
    answer = (await _dispatch(rig)).reply
    assert "HTTPS_PROXY" in answer and "configured" in answer.lower()
    assert "unverified" in answer.lower() and "active proxy" not in answer.lower()
    assert secret_url not in answer and "proxy-password-123" not in answer
    assert "reverse proxy" not in answer.lower()


async def test_unavailable_ledger_does_not_report_zero_or_proof_of_no_egress(rig, monkeypatch):
    monkeypatch.setattr(EGRESS_MONITOR, "snapshot", lambda **_kw: {
        "ledger": {"persistent": False, "error": "read failed: OperationalError"},
    })
    answer = (await _dispatch(rig)).reply
    assert "unavailable" in answer.lower() and "process" in answer.lower()
    assert "external allowed attempts: 0" not in answer.lower()
    assert "no action" not in answer.lower()
    assert "/api/admin/network/calls" in answer

    monkeypatch.setattr(EGRESS_MONITOR, "snapshot", lambda **_kw: {
        "ledger": {"persistent": True, "error": ""},
    })
    answer = (await _dispatch(rig)).reply
    assert "external allowed attempts: unavailable" in answer.lower()
    assert "no action" not in answer.lower()


async def test_local_only_without_keys_is_not_told_to_add_cloud_credentials(rig, monkeypatch):
    monkeypatch.setattr(support_bundle, "_credentials", lambda: {"set": [], "unset": []})
    monkeypatch.setattr(EGRESS_MONITOR, "snapshot", lambda **_kw: {
        "external_egress_total": 0, "model_egress_total": 0,
        "ledger": {"persistent": True, "error": ""}, "clean": True,
    })
    answer = (await _dispatch(rig)).reply
    assert "set a cloud credential" not in answer.lower()
    assert "credential sources (environment layer only): none set" in answer.lower()
    assert "zero is not proof of no network egress" in answer.lower()
    assert (await _dispatch(rig, "/egress status")).reply == answer


async def test_names_are_allowlisted_bounded_and_never_resolved(rig, monkeypatch):
    names = [f"token_{i}" for i in range(50)] + ["bad name", "https://secret.example/x"]
    rig.secret_broker.names = lambda: names
    monkeypatch.setattr(support_bundle, "_credentials", lambda: {
        "set": [f"KEY_{i}" for i in range(50)] + ["bad name", "https://secret.example/x"],
    })
    answer = (await _dispatch(rig)).reply
    assert "{{secret:token_0}}" in answer and "{{secret:token_49}}" not in answer
    assert "KEY_0" in answer and "KEY_49" not in answer
    assert "bad name" not in answer and "secret.example" not in answer
    assert "+" in answer and len(answer) < 5000


async def test_missing_broker_and_failed_sources_are_honest(rig, monkeypatch):
    rig.secret_broker = None
    monkeypatch.setattr(support_bundle, "_credentials", lambda: {"error": "unavailable"})
    monkeypatch.setattr(EGRESS_MONITOR, "snapshot", lambda **_kw: (_ for _ in ()).throw(OSError()))
    answer = (await _dispatch(rig)).reply
    assert "unavailable" in answer.lower() and "{{secret:" not in answer
    assert "external allowed attempts: 0" not in answer.lower()


async def test_failed_final_redactor_withholds_status(rig, monkeypatch):
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda _text: 42)
    answer = (await _dispatch(rig)).reply
    assert "withheld" in answer.lower() and "GEMINI_API_KEY" not in answer
