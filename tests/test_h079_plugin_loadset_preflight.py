"""Excluded built-in connectors are filtered before imports and construction."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from agents.core import integration_keys, load_set
from agents.core import plugin_manager as pm

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "tests" / "support" / "h079_plugin_import_probe.py"


def _orch(manager):
    return SimpleNamespace(get_setting=lambda _key, default=None: default,
                           permission_gate=object(), plugins=manager.plugins)


def test_only_list_avoids_excluded_connector_modules_in_fresh_process():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    proc = subprocess.run([sys.executable, "-B", str(PROBE)],
                          cwd=REPO, env=env, check=True,
                          text=True, capture_output=True, timeout=20)
    result = json.loads(proc.stdout)
    assert result["keys"] == ["news"]
    assert result["news_concrete"] and result["gmail_absent"] and result["spotify_absent"]
    assert result["imported"] == ["agents.core.plugins.news"]


def test_disabled_list_avoids_excluded_connector_modules_in_fresh_process():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    env["V42_MODE"] = "disabled"
    proc = subprocess.run([sys.executable, "-B", str(PROBE)],
                          cwd=REPO, env=env, check=True,
                          text=True, capture_output=True, timeout=20)
    result = json.loads(proc.stdout)
    assert "news" in result["keys"] and "gmail" not in result["keys"] and "spotify" not in result["keys"]
    assert result["gmail_absent"] and result["spotify_absent"]


def test_env_and_stored_keys_precede_snapshot_and_patched_class(monkeypatch):
    seen = []
    monkeypatch.setattr(pm, "load_hub_env", lambda: seen.append("env"))
    monkeypatch.setattr(integration_keys, "apply_stored", lambda: seen.append("stored"))

    def declared(_kind):
        seen.append("snapshot")
        return {"disabled": [], "only": ["cloud-llm"]}

    monkeypatch.setattr(load_set, "declared", declared)
    monkeypatch.setattr(pm, "_oauth_init", lambda: None)
    built = object()
    monkeypatch.setattr(pm, "CloudLLMPlugin", lambda **_kwargs: seen.append("construct") or built)
    manager = pm.PluginManager()
    orch = _orch(manager)
    manager.build(orch)
    assert seen == ["env", "stored", "snapshot", "construct", "snapshot"]
    assert manager.plugins == {"cloud-llm": built}
    assert orch.oracle_bridge is None
    assert orch.argus.signal_layer is None


def test_final_recheck_drops_plugin_disabled_during_construction(monkeypatch):
    states = iter([{"disabled": [], "only": ["weather"]},
                   {"disabled": ["weather"], "only": ["weather"]}])
    monkeypatch.setattr(load_set, "declared", lambda _kind: next(states))
    monkeypatch.setattr(integration_keys, "apply_stored", lambda: None)
    monkeypatch.setattr(pm, "load_hub_env", lambda: None)
    monkeypatch.setattr(pm, "_oauth_init", lambda: None)
    manager = pm.PluginManager()
    manager.build(_orch(manager))
    assert manager.plugins == {}


def test_allowed_plugins_remain_concrete_and_close(monkeypatch):
    from agents.core.autonomy.watchers import EmailProbe

    monkeypatch.setattr(load_set, "declared", lambda _kind: {"disabled": [], "only": ["gmail", "signal-layer"]})
    monkeypatch.setattr(integration_keys, "apply_stored", lambda: None)
    monkeypatch.setattr(pm, "load_hub_env", lambda: None)
    monkeypatch.setattr(pm, "_oauth_init", lambda: None)
    monkeypatch.setattr(pm, "_load_token", lambda _provider: None)
    manager = pm.PluginManager()
    orch = _orch(manager)
    manager.build(orch)
    assert list(manager.plugins) == ["gmail", "signal-layer"]
    assert type(manager.get("gmail")).__name__ == "GmailPlugin"
    assert type(manager.get("signal-layer")).__name__ == "SignalLayerPlugin"
    assert EmailProbe(gmail_plugin=manager.get("gmail")).plugin is manager.get("gmail")
    assert orch.argus.signal_layer is manager.get("signal-layer")
    closed = []
    for key, plugin in manager.plugins.items():
        original = plugin.close

        async def close(*, original=original, key=key):
            await original()
            closed.append(key)

        monkeypatch.setattr(plugin, "close", close)
    asyncio.run(manager.close_all())
    assert closed == ["gmail", "signal-layer"]
