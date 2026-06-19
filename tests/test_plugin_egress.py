"""F-07 — plugin egress boundary.

Two layers:
* PermissionGate domain matching is now anchored (exact host or sub-domain),
  closing the old ``any(d in host)`` substring bypass.
* PluginHTTPClient enforces each plugin's manifest per request: NONE always
  blocks; LAN/RESTRICTED violations are blocked (SEC-5: strict by default;
  JARVIS_STRICT_EGRESS=0 downgrades to a warning); FULL and unmanifested clients
  are unrestricted. (The suite's conftest sets JARVIS_STRICT_EGRESS=0; the strict
  tests here opt back in via monkeypatch.)
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.plugin_gate import host_in_allowlist
from agents.core.http_client import PluginHTTPClient, PluginEgressError


# ── gate matching (anchored host/sub-domain) ─────────────────────────────────
def test_host_in_allowlist_exact_and_subdomain():
    assert host_in_allowlist("api.openai.com", ["api.openai.com"]) is True
    assert host_in_allowlist("v1.api.openai.com", ["api.openai.com"]) is True
    assert host_in_allowlist("API.OpenAI.Com", ["api.openai.com"]) is True  # case-insensitive


def test_host_in_allowlist_rejects_substring_bypass():
    # the bug F-07 fixes: a look-alike suffix must not pass
    assert host_in_allowlist("api.openai.com.evil.example", ["api.openai.com"]) is False
    assert host_in_allowlist("notopenai.com", ["openai.com"]) is False
    assert host_in_allowlist("evil-api.openai.com.attacker.net", ["api.openai.com"]) is False
    assert host_in_allowlist("", ["api.openai.com"]) is False


# ── PluginHTTPClient egress enforcement ──────────────────────────────────────
def test_restricted_allows_listed_host():
    c = PluginHTTPClient.for_plugin("weather")  # RESTRICTED → wttr.in
    c._enforce_egress("https://wttr.in/Bucharest?format=j1")  # must not raise


def test_restricted_blocks_unlisted_by_default(monkeypatch):
    # SEC-5: strict is the default now (env unset → enforce).
    monkeypatch.delenv("JARVIS_STRICT_EGRESS", raising=False)
    c = PluginHTTPClient.for_plugin("weather")
    with pytest.raises(PluginEgressError):
        c._enforce_egress("https://evil.example/x")


def test_restricted_warns_when_opted_out(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")  # escape hatch → warn, no raise
    c = PluginHTTPClient.for_plugin("weather")
    c._enforce_egress("https://evil.example/x")


def test_restricted_blocks_unlisted_and_lookalike_under_strict(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    c = PluginHTTPClient.for_plugin("weather")
    with pytest.raises(PluginEgressError):
        c._enforce_egress("https://evil.example/x")
    with pytest.raises(PluginEgressError):
        c._enforce_egress("https://wttr.in.evil.example/x")  # substring bypass closed


def test_none_plugin_always_blocks():
    c = PluginHTTPClient.for_plugin("system-control")  # NONE
    with pytest.raises(PluginEgressError):
        c._enforce_egress("https://anything.example/x")  # blocks even without strict mode


def test_lan_allows_localhost_blocks_public_under_strict(monkeypatch):
    c = PluginHTTPClient.for_plugin("worldview")  # LAN
    c._enforce_egress("http://localhost:4000/history/adsb")  # local → ok
    c._enforce_egress("http://192.168.1.50:8080/x")          # private IP → ok
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    with pytest.raises(PluginEgressError):
        c._enforce_egress("http://example.com/x")            # public → blocked


def test_unmanifested_client_is_unrestricted(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    c = PluginHTTPClient.for_plugin("some_internal_client_xyz")  # no manifest
    c._enforce_egress("https://anywhere.example/x")  # no policy → no raise


def test_full_plugin_is_unrestricted(monkeypatch):
    # No built-in plugin is FULL today; assert the policy branch is permissive by
    # constructing a client whose manifest we temporarily set to FULL.
    import agents.core.plugin_gate as pg
    from dataclasses import replace
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    monkeypatch.setitem(pg.BUILTIN_PLUGINS, "weather",
                        replace(pg.BUILTIN_PLUGINS["weather"], network_access=pg.NetworkAccess.FULL))
    c = PluginHTTPClient.for_plugin("weather")
    c._enforce_egress("https://anywhere.example/x")  # FULL → no raise


# ── SEC-5 self-consistency: every manifested plugin's REAL hosts pass strict ──
# Sourced from the F-07/SEC-5 egress audit (each plugin's actual outbound hosts).
# If a host a plugin genuinely needs is dropped from its allowlist, this fails —
# preventing a strict-by-default runtime breakage from sneaking in.
REAL_HOSTS = {
    "weather": ["wttr.in"],
    "news": ["feeds.bbci.co.uk", "www.hotnews.ro", "www.stiripesurse.ro"],
    "cloud-llm": ["api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com"],
    "telegram": ["api.telegram.org"],
    "gmail": ["gmail.googleapis.com", "www.googleapis.com", "oauth2.googleapis.com"],
    "google-calendar": ["www.googleapis.com", "oauth2.googleapis.com"],
    "spotify": ["api.spotify.com", "accounts.spotify.com"],
    "sms-alerts": ["api.twilio.com"],
    "crm-sync": ["api.notion.com"],
    "iot-control": ["openapi.tuya.com"],
    "oracle-bridge": ["api.github.com"],
    # LAN plugins — representative local hosts they bind to.
    "whatsapp-bridge": ["192.168.1.100", "localhost"],
    "apple-health": ["192.168.1.100"],
    "homebridge": ["192.168.1.100"],
    "worldview": ["localhost"],
}


def test_documented_hosts_pass_under_strict(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    for plugin, hosts in REAL_HOSTS.items():
        client = PluginHTTPClient.for_plugin(plugin)
        for host in hosts:
            client._enforce_egress(f"https://{host}/some/path")  # must not raise


def test_real_for_plugin_names_match_a_manifest():
    # The renames (SEC-5) must hold: each plugin module's for_plugin id is a
    # manifest id, otherwise enforcement silently doesn't apply.
    import re
    from pathlib import Path
    from agents.core.plugin_gate import BUILTIN_PLUGINS
    plugins_dir = Path(__file__).resolve().parent.parent / "agents" / "core" / "plugins"
    # plugins whose for_plugin id should resolve to a manifest (exclude unmanifested-by-design)
    EXPECTED = {
        "weather", "news", "cloud-llm", "telegram", "gmail", "google-calendar",
        "spotify", "sms-alerts", "crm-sync", "iot-control", "oracle-bridge",
        "whatsapp-bridge", "apple-health", "homebridge", "worldview",
    }
    found = set()
    for f in plugins_dir.glob("*.py"):
        for m in re.finditer(r'for_plugin\(\s*"([^"]+)"', f.read_text(encoding="utf-8")):
            found.add(m.group(1))
    missing = EXPECTED - found
    assert not missing, f"expected manifest-id for_plugin names not found in plugins: {missing}"
    # every expected name is a real manifest id
    assert EXPECTED <= set(BUILTIN_PLUGINS), EXPECTED - set(BUILTIN_PLUGINS)
