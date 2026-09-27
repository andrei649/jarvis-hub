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

import ast
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
    assert safe_mode.LAYERS[11:12] == ("project_context",)                  # H594
    assert safe_mode.LAYERS[12:] == ("voice_piper_binary", "voice_commands")  # H613
    assert len(set(safe_mode.LAYERS)) == len(safe_mode.LAYERS) == 14


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
    ("channels.rate_limit", 10000, 10, 10),
    ("learning.review_daily_budget", 1000, 20, 20),
    ("learning.review_daily_budget", 0, 20, 0),            # 0 is no reviews at all
    # more loosens, and under 1 is no cap at all: the shipped cap
    ("security.sandbox_memory", 0, 256, 256),              # Docker reads --memory 0m as unlimited
    ("security.sandbox_memory", 0.5, 256, 256),            # int(0.5) is 0
    ("security.sandbox_memory", -5, 256, 256),
    ("security.sandbox_memory", 1, 256, 1),
    ("security.sandbox_memory", 128, 256, 128),
    ("security.sandbox_memory", 1024, 256, 256),
    ("autonomy.max_subagent_spawns_per_boot", 0, 50, 50),  # 0 is unbounded
    ("autonomy.max_subagent_spawns_per_boot", 100000, 50, 50),
    ("autonomy.max_subagent_spawns_per_boot", 10, 50, 10),
    # a list: only the shipped names the owner kept, in the owner's order
    ("llm.guest_tools", ["echo", "shell", "time"], ["echo", "time", "todo"], ["echo", "time"]),
    ("llm.guest_tools", ["time", "shell", "echo"], ["echo", "time", "todo"], ["time", "echo"]),
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
    reordered = ["todo", "echo", "time"]                                  # the same names, reordered
    assert safe_mode.override_settings({"llm.guest_tools": reordered})["llm.guest_tools"] == reordered
    assert safe_mode.status()["skipped"] == []


#: Seeded numbers that are not forced, each reviewed: a size, a time of day, a timeout
#: or a cadence of the owner's own work rather than an approval or a budget of actions,
#: messages or spend; a knob read only by a layer safe mode switches off; or one whose
#: shipped default is already the loosest value.
_NUMBERS_NOT_FORCED = {
    # the tool loop and the pre-turn recall are off in safe mode
    "llm.tool_loop_max_iterations", "llm.tool_loop_context_tokens", "llm.tool_loop_per_tool_cap",
    "memory.recall_top_k", "memory.recall_timeout_s",
    # the shipped default is already the loosest value (0 = no cap)
    "llm.daily_cost_cap_usd",
    # sizes, routing thresholds and timeouts of a model call
    "llm.max_tokens", "llm.deep_max_tokens", "llm.ollama_num_ctx", "llm.hybrid_local_max",
    "llm.hybrid_flash_max", "agents.agent_timeout_seconds", "agents.reasoning_timeout_seconds",
    # the conversation's own history, its compression and the owner's backups
    "memory.max_turns", "memory.auto_archive_days", "memory.context_window",
    "memory.compression_max_tokens", "memory.compression_keep_first",
    "memory.compaction_protect_last", "memory.backup_keep", "memory.compression_summary_max_tokens",
    "memory.compression_max_turn_hold_seconds", "memory.compression_summary_idle_seconds",
    # the size and cadence of one review (how many a day is forced)
    "learning.review_max_tokens", "learning.review_every_n", "learning.review_idle_gap_s",
    "learning.review_max_facts",
    # housekeeping, cadences and times of day
    "security.sandbox_temp_max_age_hours", "jobs.media_send_timeout_seconds", "skills.max_skills",
    "system.poll_interval", "system.log_max_mb", "system.log_backups", "system.battery_defer_percent",
    "system.startup_warmup_timeout_seconds", "system.autonomy_tick", "autonomy.running_ttl_seconds",
    "autonomy.night_start", "autonomy.night_end", "autonomy.calendar_lead_time",
    "autonomy.tech_scout_interval_hours", "ambient.generation", "ambient.quiet_hours_start",
    "ambient.quiet_hours_end",
    # the owner's own alert thresholds
    "autonomy.finance_min_ron", "autonomy.finance_min_eur", "autonomy.health_min_sleep",
    "autonomy.health_min_hrv",
    # retention windows: how long data is kept, not what may run
    "retention.artifact_ttl_days", "retention.conversation_ttl_days", "retention.audit_ttl_days",
    "retention.ingestion_ttl_days", "retention.min_interval_hours", "retention.min_vacuum_interval_days",
}


def test_every_seeded_number_is_forced_or_reviewed():
    numbers = {f"{r['category']}.{r['key']}" for r in settings_db.DEFAULTS if r["kind"] == "number"}
    assert numbers - set(safe_mode.FORCED_SETTINGS) - _NUMBERS_NOT_FORCED == set()
    assert not _NUMBERS_NOT_FORCED & set(safe_mode.FORCED_SETTINGS)
    assert numbers >= _NUMBERS_NOT_FORCED                                 # no stale name


#: Raw reads of a forced key that are reviewed: what the selected product posture
#: forces, listed beside a settings reset, reads the stored choice on purpose.
_REVIEWED_RAW_READS = {("agents/core/settings_db.py", "product.posture")}


_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)


def _scope_of(parents, node):
    node = parents.get(node)
    while not isinstance(node, _SCOPES):
        node = parents[node]
    return node


def _reader_module(tree, parents, call):
    """The module a ``(category, key)`` reader comes from: ``x`` of ``x.get_value``, or
    the module of the nearest earlier import of the name in the innermost enclosing
    function, then outwards."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.value.id if isinstance(func.value, ast.Name) else None
    if not isinstance(func, ast.Name):
        return None
    scope = call
    while scope is not tree:
        scope = _scope_of(parents, scope)
        binds = [n for n in ast.walk(scope) if isinstance(n, ast.ImportFrom)
                 and n.lineno < call.lineno and _scope_of(parents, n) is scope
                 and any((a.asname or a.name) == func.id for a in n.names)]
        if binds:
            return max(binds, key=lambda n: n.lineno).module
    return None


def _raw_forced_reads():
    """Every ``(category, key)`` read of a forced setting under agents/ whose reader is
    not ``safe_mode.get_value``."""
    found = set()
    for path in sorted((REPO / "agents").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and len(call.args) >= 2):
                continue
            first, second = call.args[:2]
            if not all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in (first, second)):
                continue
            key = f"{first.value}.{second.value}"
            module = _reader_module(tree, parents, call) or ""
            if key in safe_mode.FORCED_SETTINGS and module.rpartition(".")[2] != "safe_mode":
                found.add((path.relative_to(REPO).as_posix(), key, call.lineno))
    return found


def test_no_forced_setting_is_read_past_safe_mode():
    raw = {(rel, key) for rel, key, _ in _raw_forced_reads()}
    assert raw - _REVIEWED_RAW_READS == set(), sorted(_raw_forced_reads())
    assert raw >= _REVIEWED_RAW_READS                                     # no stale entry


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


def test_the_orchestrator_boots_with_the_stricter_caps(monkeypatch):
    from agents.core.config import JarvisConfig
    from agents.core.orchestrator import Orchestrator

    settings_db.put_category("security", {"sandbox_timeout": 600, "sandbox_memory": 4096})
    settings_db.put_category("autonomy", {"cap_per_action": 5000, "daily_ceiling": 99999,
                                          "earned_autonomy_enabled": True})
    _on(monkeypatch)
    orch = Orchestrator(JarvisConfig())
    assert (orch.sandbox.timeout, orch.sandbox.max_memory_mb) == (30, 256)
    policy = orch.autonomy.policy
    assert (policy.cap_per_action, policy.daily_ceiling) == (50.0, 200.0)
    assert policy.earned_autonomy_enabled is False


def test_the_runtime_settings_loader_overrides_around_the_posture():
    source = (REPO / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    loader = source.split("def load_runtime_settings(self):", 1)[1].split("self._runtime_settings = flat", 1)[0]
    assert ("flat = safe_mode.override_settings(apply_to_runtime_settings("
            "safe_mode.override_settings(flat)))") in loader


def test_the_model_pull_cap_takes_the_stricter_value(monkeypatch):
    from agents.core.llm.model_setup import ModelSetupService
    from agents.core.routers import model_setup

    settings_db.put_category("llm", {"model_pull_max_gb": 500})
    assert model_setup._max_gb() == 500
    _on(monkeypatch)
    assert model_setup._max_gb() == 20
    assert ModelSetupService(max_gb=model_setup._max_gb).max_bytes() == 20 * 1024 ** 3
    assert safe_mode.status()["skipped"] == ["settings_overrides"]


def test_a_router_re_detect_keeps_the_stricter_cloud_fallback(monkeypatch):
    from agents.core.llm.hybrid_router import HybridRouter

    for var in ("JARVIS_LM_STUDIO_URL", "JARVIS_OLLAMA_URL"):
        monkeypatch.delenv(var, raising=False)
    settings_db.put_category("llm", {"cloud_fallback": "always"})
    router = HybridRouter(gemini_api_key="")

    async def _down(*_a, **_k):
        return False

    monkeypatch.setattr(router, "_check", _down)
    monkeypatch.setattr(router, "_fetch_loaded_model", _down)
    asyncio.run(router.detect())
    assert router._cloud_fallback_mode == "always"
    _on(monkeypatch)
    router.set_cloud_fallback_mode("on-demand")                          # the settings watcher's push
    asyncio.run(router.detect())                                         # a backend came or went
    assert router._cloud_fallback_mode == "on-demand"
    assert safe_mode.status()["skipped"] == ["settings_overrides"]


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


def test_howard_recalls_no_archive_into_a_prompt_in_safe_mode(monkeypatch):
    from agents.core.agent import Agent
    from agents.core.ingestion import pipeline

    searches = []

    def _search(text, k, only_me):
        searches.append(text)
        return [SimpleNamespace(text="am ales varianta simpla", score=0.9)]

    monkeypatch.setattr(pipeline, "get_shared_pipeline", lambda: SimpleNamespace(search_similar=_search))
    howard = Agent("howard", {"name": "Howard", "model": "howard-lora", "plugins": []})
    assert "am ales varianta simpla" in howard.build_prompt("ce ai ales?", {})
    _on(monkeypatch)
    assert "am ales varianta simpla" not in howard.build_prompt("ce ai ales?", {})
    assert searches == ["ce ai ales?"]                     # the archive is not even searched
    assert safe_mode.status()["skipped"] == ["memory_injection"]


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
