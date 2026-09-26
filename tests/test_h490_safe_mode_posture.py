"""H490 — safe mode takes the rest of Hermes' reduced posture.

H275 left the owner's customizations out (skills, MCP servers, acquired packages, plugin
grants, overlays, jobs). Hermes' safe mode also runs without plugins, without outbound
hooks, without memory, and with the loosened settings put back. Here: no plugin is
built and the gate refuses every one; the ntfy and webhook channels are not started,
a proactive send refuses and the inbound receiver answers 503; no recalled memory, core
block or memory tool reaches a turn; and each setting that loosens an approval or widens
a budget reads the stricter of the owner's value and its shipped default. The posture
route says it. Nerva runs no owner-configured shell hooks, so there are none to leave out.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import safe_mode, settings_db  # noqa: E402

REPO = repo_root


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    for var in ("JARVIS_SAFE_MODE", "JARVIS_USER_HOME"):
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var)
    safe_mode.reset()
    yield
    safe_mode.reset()


def _on(monkeypatch):
    monkeypatch.setenv(safe_mode.ENV_NAME, "1")


def _body(resp):
    return json.loads(resp.body)


# ── the layers ───────────────────────────────────────────────────────────────────

def test_the_new_layers_come_after_the_owners_in_boot_order():
    assert safe_mode.LAYERS[7:11] == ("plugins", "outbound_webhooks", "memory_injection", "settings_overrides")
    assert safe_mode.LAYERS[11:] == ("project_context",)                    # H594
    assert len(set(safe_mode.LAYERS)) == len(safe_mode.LAYERS) == 12


# ── settings: the stricter of the owner's value and the shipped default ──────────

def test_every_forced_and_unseeded_key_is_a_real_setting():
    keys = {f"{r['category']}.{r['key']}" for r in settings_db.DEFAULTS}
    assert set(safe_mode.FORCED_SETTINGS) <= keys
    assert not set(safe_mode.UNSEEDED_SETTINGS) & keys
    for key in safe_mode.FORCED_SETTINGS:
        default = safe_mode.shipped_default(key)
        # The shipped default is its own stricter value: safe mode never moves it.
        assert safe_mode.stricter(key, default, default) == default, key
    with pytest.raises(KeyError):
        safe_mode.shipped_default("llm.no_such_key")


@pytest.mark.parametrize("key,owner,shipped,expected", [
    # on loosens: off is stricter
    ("llm.tool_loop_enabled", True, False, False),
    ("llm.tool_loop_enabled", False, False, False),
    ("llm.tool_loop_enabled", True, True, True),
    ("llm.tool_loop_enabled", False, True, False),
    ("llm.tool_loop_enabled", "yes", True, True),         # a switch is read by truthiness
    ("llm.tool_loop_enabled", 0, True, False),
    ("llm.tool_loop_enabled", None, True, False),
    ("llm.tool_loop_enabled", "yes", False, False),
    # off loosens: on is stricter
    ("security.scan_input", False, True, True),
    ("security.scan_input", True, True, True),
    ("security.scan_input", True, False, True),
    ("security.scan_input", False, False, False),
    ("security.scan_input", "off", False, True),           # a switch is read by truthiness
    ("security.scan_input", 1, False, True),
    ("security.scan_input", 0, False, False),
    ("security.scan_input", None, True, True),
    # more loosens: the smaller number
    ("autonomy.daily_ceiling", 500, 200, 200),
    ("autonomy.daily_ceiling", 50, 200, 50),
    ("autonomy.daily_ceiling", 0, 200, 0),
    ("autonomy.daily_ceiling", 12.5, 200, 12.5),
    ("autonomy.daily_ceiling", True, 200, 200),            # a bool is not a number here
    ("autonomy.daily_ceiling", "9", 200, 200),
    # a list: only the shipped names the owner kept
    ("llm.guest_tools", ["echo", "shell", "time"], ["echo", "time", "todo"], ["echo", "time"]),
    ("llm.guest_tools", [], ["echo", "time"], []),
    ("llm.guest_tools", "shell", ["echo", "time"], ["echo", "time"]),
    # an order, strictest first
    ("llm.cloud_fallback", "always", "on-demand", "on-demand"),
    ("llm.cloud_fallback", "never", "on-demand", "never"),
    ("llm.cloud_fallback", "on-demand", "on-demand", "on-demand"),
    ("llm.cloud_fallback", "sometimes", "on-demand", "on-demand"),
    ("llm.cloud_fallback", "always", "never", "never"),
    ("product.posture", "design_partner", "off", "off"),
    ("product.posture", "companion_wave1", "design_partner", "companion_wave1"),
])
def test_stricter_takes_the_stricter_value(key, owner, shipped, expected):
    got = safe_mode.stricter(key, owner, shipped)
    assert got == expected and type(got) is type(expected)


def test_off_the_settings_are_served_as_they_are():
    flat = {"llm.tool_loop_enabled": True, "autonomy.agent_modes": {"x": 1}}
    assert safe_mode.override_settings(flat) is flat
    assert safe_mode.status()["skipped"] == []


def test_in_safe_mode_each_loosening_setting_is_put_back(monkeypatch):
    _on(monkeypatch)
    flat = {
        "llm.tool_loop_enabled": True, "security.scan_output": False, "autonomy.daily_ceiling": 999,
        "autonomy.interrupt_budget": 1, "llm.guest_tools": ["echo", "shell"],
        "llm.cloud_fallback": "always", "product.posture": "design_partner",
        "autonomy.agent_modes": {"jarvis": "autonomous"}, "learning.auto_promote": True,
        "llm.temperature": 1.3,
    }
    out = safe_mode.override_settings(flat)
    assert out is not flat and flat["llm.tool_loop_enabled"] is True     # a copy
    assert out["llm.tool_loop_enabled"] is False
    assert out["security.scan_output"] is True
    assert out["autonomy.daily_ceiling"] == 200
    assert out["autonomy.interrupt_budget"] == 1                         # the owner's tighter value
    assert out["llm.guest_tools"] == ["echo"]
    assert out["llm.cloud_fallback"] == "on-demand"
    assert out["product.posture"] == "off"
    assert "autonomy.agent_modes" not in out and "learning.auto_promote" not in out
    assert out["llm.temperature"] == 1.3                                 # not a loosening key
    for key in safe_mode.FORCED_SETTINGS:                                 # a missing key: the default
        assert key in out
    assert safe_mode.status()["skipped"] == ["settings_overrides"]


def test_nothing_moved_is_not_reported(monkeypatch):
    _on(monkeypatch)
    defaults = {k: safe_mode.shipped_default(k) for k in safe_mode.FORCED_SETTINGS}
    assert safe_mode.override_settings(dict(defaults)) == defaults
    assert safe_mode.override_settings({}) == defaults                    # filled, not moved
    assert safe_mode.override_settings({"autonomy.daily_ceiling": 3})["autonomy.daily_ceiling"] == 3
    assert safe_mode.status()["skipped"] == []


@pytest.mark.parametrize("key", safe_mode.UNSEEDED_SETTINGS)
def test_an_unseeded_key_alone_counts_as_moved(monkeypatch, key):
    _on(monkeypatch)
    assert key not in safe_mode.override_settings({key: "x"})
    assert safe_mode.status()["skipped"] == ["settings_overrides"]


def test_a_boot_read_takes_the_stricter_value(monkeypatch):
    settings_db.put_category("security", {"sandbox_timeout": 600, "sandbox_memory": 64})
    settings_db.put_category("llm", {"temperature": 1.1})
    assert safe_mode.get_value("security", "sandbox_timeout", 30) == 600
    _on(monkeypatch)
    assert safe_mode.get_value("security", "sandbox_timeout", 30) == 30
    assert safe_mode.status()["skipped"] == ["settings_overrides"]
    safe_mode.reset()
    assert safe_mode.get_value("security", "sandbox_memory", 256) == 64      # tightened: kept
    assert safe_mode.get_value("llm", "temperature", 0.7) == 1.1             # not forced
    assert safe_mode.status()["skipped"] == []


def test_the_orchestrator_reads_its_settings_through_safe_mode():
    source = (REPO / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    boot = source.split("self.bench = LatencyBenchmark()", 1)[1].split("self.sandbox = Sandbox(", 1)[0]
    assert "from .safe_mode import get_value as _gv" in boot
    loader = source.split("def load_runtime_settings(self):", 1)[1].split("self._runtime_settings = flat", 1)[0]
    assert ("flat = safe_mode.override_settings(apply_to_runtime_settings("
            "safe_mode.override_settings(flat)))") in loader


def test_the_runtime_settings_are_overridden_in_safe_mode(monkeypatch):
    from agents.core.orchestrator import Orchestrator

    settings_db.put_category("llm", {"tool_loop_enabled": True, "cloud_fallback": "always"})
    settings_db.put_category("product", {"posture": "design_partner"})
    fake = SimpleNamespace()
    Orchestrator.load_runtime_settings(fake)
    assert fake._runtime_settings["llm.tool_loop_enabled"] is True
    _on(monkeypatch)
    Orchestrator.load_runtime_settings(fake)
    flat = fake._runtime_settings
    assert flat["llm.tool_loop_enabled"] is False and flat["llm.cloud_fallback"] == "on-demand"
    assert flat["product.posture"] == "off"


# ── plugins ──────────────────────────────────────────────────────────────────────

def test_no_plugin_is_built_in_safe_mode(monkeypatch):
    from agents.core import env_provenance
    from agents.core.orchestrator import Orchestrator

    loads = []
    monkeypatch.setattr(env_provenance, "load_hub_env", lambda: loads.append(1))
    fake = SimpleNamespace(plugin_manager=MagicMock())
    Orchestrator._build_plugins(fake)
    fake.plugin_manager.build.assert_called_once_with(fake)
    assert loads == [] and safe_mode.status()["skipped"] == []
    fake.plugin_manager.build.reset_mock()
    _on(monkeypatch)
    Orchestrator._build_plugins(fake)
    fake.plugin_manager.build.assert_not_called()
    assert loads == [1]                         # the .env credentials still load
    assert safe_mode.status()["skipped"] == ["plugins"]
    source = (REPO / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    assert source.count("self._build_plugins()") == 1
    assert source.count("self.plugin_manager.build(self)") == 1              # only inside it


def test_the_gate_refuses_every_plugin_in_safe_mode(monkeypatch):
    from agents.core.plugin_gate import BUILTIN_PLUGINS, PermissionGate

    assert any(m.enabled for m in PermissionGate().plugins.values())
    _on(monkeypatch)
    gate = PermissionGate()
    assert set(gate.plugins) == set(BUILTIN_PLUGINS)
    assert not any(m.enabled for m in gate.plugins.values())
    assert any(m.enabled for m in BUILTIN_PLUGINS.values())                 # the shared table is untouched
    assert safe_mode.status()["skipped"] == ["plugins"]


_TOKEN = "h490-token"


def test_the_plugin_toggle_refuses_and_keeps_the_saved_choice(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import load_set
    from agents.core.plugin_gate import PermissionGate

    orch = MagicMock()
    orch.permission_gate = PermissionGate()
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    persisted = MagicMock(return_value=True)
    monkeypatch.setattr(load_set, "persist_plugin", persisted)
    client = TestClient(web.app)
    _on(monkeypatch)
    resp = client.put("/plugins/weather/toggle", headers={"X-Admin-Token": _TOKEN})
    assert resp.status_code == 409
    body = resp.json()
    assert body["id"] == "weather" and body["error"] == "safe_mode" and "safe mode" in body["message"]
    assert orch.permission_gate.plugins["weather"].enabled is True and persisted.call_count == 0
    assert client.put("/plugins/ghost/toggle", headers={"X-Admin-Token": _TOKEN}).status_code == 404
    monkeypatch.delenv(safe_mode.ENV_NAME)
    assert client.put("/plugins/weather/toggle", headers={"X-Admin-Token": _TOKEN}).json()["enabled"] is False


# ── outbound webhooks ────────────────────────────────────────────────────────────

def test_a_proactive_send_refuses_in_safe_mode(monkeypatch):
    from agents.core.channels import outbound

    adapter = MagicMock()
    orch = SimpleNamespace(channels={"telegram": adapter}, get_setting=lambda k, d=None: "7788",
                           action_audit=MagicMock(), channel_manager=None)
    _on(monkeypatch)
    result = asyncio.run(outbound.send_to_target(orch, "telegram", "hello"))
    assert result == {"ok": False, "reason": "outbound sends are off in safe mode"}
    adapter.send.assert_not_called()
    assert safe_mode.status()["skipped"] == ["outbound_webhooks"]


def test_the_inbound_receiver_answers_503_in_safe_mode(monkeypatch):
    from agents.core import webhooks as webhooks_mod
    from agents.core.routers import webhooks

    reads = []

    async def _state():
        reads.append(1)
        return True

    monkeypatch.setattr(webhooks_mod.RECEIVER, "astate", _state)
    assert asyncio.run(webhooks._receiver_refusal()) is None
    _on(monkeypatch)
    resp = asyncio.run(webhooks._receiver_refusal())
    assert resp.status_code == 503 and _body(resp) == {"error": "the webhook receiver is off in safe mode"}
    assert reads == [1]                        # the switch is not even read
    assert safe_mode.status()["skipped"] == ["outbound_webhooks"]


def test_the_lifespan_starts_no_ntfy_or_webhook_channel_in_safe_mode():
    source = (REPO / "agents/web.py").read_text(encoding="utf-8")
    ntfy = source.split("ntfy_ch = NtfyChannel.from_env(os.environ)", 1)[1].split("await orch.register_channel(ntfy_ch)", 1)[0]
    assert "if ntfy_ch is not None and safe_mode.enabled():" in ntfy
    assert 'safe_mode.note("outbound_webhooks")' in ntfy and "ntfy_ch = None" in ntfy
    hooks = source.split('wh_cfg = env_json_object("JARVIS_WEBHOOK_CHANNELS", {})', 1)[1].split("channels_from_config(", 1)[0]
    assert "if wh_cfg and safe_mode.enabled():" in hooks
    assert 'safe_mode.note("outbound_webhooks")' in hooks and "wh_cfg = {}" in hooks
    # safe_mode is bound in the lifespan before either read.
    lifespan = source.split("async def lifespan(application: FastAPI):", 1)[1]
    assert lifespan.index("safe_mode.enabled()") < lifespan.index("NtfyChannel.from_env")


# ── memory ───────────────────────────────────────────────────────────────────────

def _recall_self(hits):
    from agents.core.orchestrator import Orchestrator

    fake = MagicMock(spec=Orchestrator)
    fake.get_setting = lambda key, default=None: True if key == "memory.recall_enabled" else default
    fake._recall_runtime.return_value = SimpleNamespace(erasing=False, generation=0)

    async def _hits(text, generation):
        return hits

    fake._bounded_recall_hits = _hits
    fake._living_memory_rerank_hits = lambda h: h
    fake._keep_warm_recall = lambda *a: None
    return fake


def test_no_recalled_memory_enters_a_prompt_in_safe_mode(monkeypatch):
    from agents.core.orchestrator import Orchestrator

    hit = {"text": "the owner lives in Cluj", "source": "memory", "score": 0.9}
    fake = _recall_self([hit])
    block = asyncio.run(Orchestrator._recall_block(fake, "where do I live?"))
    assert "Cluj" in block
    _on(monkeypatch)
    assert asyncio.run(Orchestrator._recall_block(fake, "where do I live?")) == ""
    assert safe_mode.status()["skipped"] == ["memory_injection"]


def test_recall_switched_off_is_not_reported_as_left_out(monkeypatch):
    from agents.core.orchestrator import Orchestrator

    fake = _recall_self([])
    fake.get_setting = lambda key, default=None: default
    _on(monkeypatch)
    assert asyncio.run(Orchestrator._recall_block(fake, "hello there friend")) == ""
    assert safe_mode.status()["skipped"] == []


def test_no_core_block_enters_a_prompt_in_safe_mode(monkeypatch):
    from agents.core.learning import core_block
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setattr(core_block, "render_core_block", lambda living: "CORE: the owner prefers tea")
    cog = MagicMock()
    cog.sub_enabled.return_value = True
    fake = SimpleNamespace(cognition=cog, session_id="s1")
    assert Orchestrator._living_core_memory_block(fake) == "CORE: the owner prefers tea"
    fake = SimpleNamespace(cognition=cog, session_id="s2")
    _on(monkeypatch)
    assert Orchestrator._living_core_memory_block(fake) == ""
    assert not hasattr(fake, "_core_block_cache")          # nothing cached for later either
    assert safe_mode.status()["skipped"] == ["memory_injection"]
    cog.sub_enabled.return_value = False
    safe_mode.reset()
    assert Orchestrator._living_core_memory_block(fake) == ""
    assert safe_mode.status()["skipped"] == []


def test_the_memory_tool_reads_as_switched_off_in_safe_mode(monkeypatch, tmp_path):
    from agents.core import memory_tool
    from agents.core.cognition.memory import CoreMemory
    from agents.core.tool_rpc import ToolRPCServer

    living = SimpleNamespace(core=CoreMemory(cap=5, path=tmp_path / "core.json"),
                             user_core=CoreMemory(cap=5, path=tmp_path / "user.json"))
    living.core.put("the owner prefers tea")
    server = ToolRPCServer()
    memory_tool.register_memory_tool(server, living=lambda: living, audit=MagicMock,
                                     posture=lambda: "operator/owner", origin=lambda: "generated",
                                     store=memory_tool.UndoStore(tmp_path / "undo.json"))

    def _read():
        return asyncio.run(server.handle({"tool": "memory", "args": {}}, actor="jarvis"))["result"]

    def _desc():
        return next(r for r in server.tools() if r["name"] == "memory")["description"]

    assert _read()["memory"] == ["the owner prefers tea"] and _desc() == memory_tool.DESCRIPTION
    _on(monkeypatch)
    assert _read() == {"ok": False, "reason": "memory_disabled", "detail": "memory is switched off on this hub"}
    assert _desc() == memory_tool.OFF_DESCRIPTION
    assert safe_mode.status()["skipped"] == ["memory_injection"]


# ── it is said ───────────────────────────────────────────────────────────────────

def test_the_security_posture_says_it(monkeypatch):
    from agents.core.routers import security

    assert security._safe_mode_status() == {"enabled": False, "skipped": []}
    _on(monkeypatch)
    safe_mode.note("plugins")
    assert security._safe_mode_status() == {"enabled": True, "skipped": ["plugins"]}
    source = (REPO / "agents/core/routers/security.py").read_text(encoding="utf-8")
    route = source.split("async def security_posture():", 1)[1].split("def _safe_mode_status", 1)[0]
    assert '"safe_mode": _safe_mode_status(),' in route


def test_the_boot_log_names_the_new_layers():
    source = (REPO / "agents/web.py").read_text(encoding="utf-8")
    line = source.split('"SAFE MODE: ', 1)[1].split("(JARVIS_SAFE_MODE)", 1)[0]
    for words in ("plugins", "outbound webhooks", "memory in prompts", "loosened settings"):
        assert words in line


def test_the_banner_names_every_layer():
    source = (REPO / "frontend/src/safe-mode-banner.tsx").read_text(encoding="utf-8")
    labels = source.split("LABELS", 1)[1].split("}", 1)[0]
    for layer in safe_mode.LAYERS:
        assert f"{layer}:" in labels, layer
