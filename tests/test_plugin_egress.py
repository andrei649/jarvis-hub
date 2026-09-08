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
from datetime import UTC


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
    # The page reader (webread, HA-5a) is the one built-in FULL manifest; assert the
    # policy branch on its own by temporarily setting an unrelated manifest to FULL.
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
    # SEC-5b: previously-unmanifested plugins with static hosts.
    "balance": ["api.ing.com", "api.libra.ro"],
    "analytics": ["analyticsdata.googleapis.com", "oauth2.googleapis.com"],
    "websearch": ["api.tavily.com", "html.duckduckgo.com"],
    "digest": ["hnrss.org", "www.reddit.com", "export.arxiv.org",
               "news.google.com", "www.youtube.com"],
    "social_x": ["api.twitter.com"],
    "writeback_notion": ["api.notion.com"],
    "writeback_github": ["api.github.com"],
    "writeback_google_calendar": ["www.googleapis.com"],
    "call_twilio": ["api.twilio.com"],
    "call_telnyx": ["api.telnyx.com"],
    "channel_whatsapp": ["graph.facebook.com"],
    "channel_google_chat": ["chat.googleapis.com"],
    # anchored subdomain match covers the per-tenant Teams webhook prefixes.
    "channel_teams": ["x.webhook.office.com", "prod-1.westus.logic.azure.com"],
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
        # SEC-5b: string-literal for_plugin ids living under agents/core/plugins.
        "balance", "analytics", "websearch", "n8n",
        # Hermes absorption 5a: the page reader dials under its own identity.
        "webread",
    }
    found = set()
    for f in plugins_dir.glob("*.py"):
        for m in re.finditer(r'for_plugin\(\s*"([^"]+)"', f.read_text(encoding="utf-8")):
            found.add(m.group(1))
    missing = EXPECTED - found
    assert not missing, f"expected manifest-id for_plugin names not found in plugins: {missing}"
    # every expected name is a real manifest id
    assert EXPECTED <= set(BUILTIN_PLUGINS), EXPECTED - set(BUILTIN_PLUGINS)


# ── SEC-5b: dynamic family ids + config/env-driven hosts ─────────────────────
def test_dynamic_family_ids_all_have_manifests():
    """Family plugins build their for_plugin id with an f-string
    (``for_plugin(f"social_{platform}")``), which the literal-regex scan above
    can't see. Pin every concrete family member to a manifest so a new member
    can't silently re-open the egress gap (SEC-5b)."""
    from agents.core.plugin_gate import BUILTIN_PLUGINS
    from agents.core.social import _CREDENTIAL as social_platforms
    from agents.core.writeback import _CREDENTIAL as writeback_targets
    from agents.core.autonomy.call_broker import _CREDENTIAL as call_providers
    from agents.core.channels.webhook_channels import SUPPORTED_CHANNELS

    expected = set()
    expected |= {f"social_{p}" for p in social_platforms}
    expected |= {f"writeback_{t}" for t in writeback_targets}
    expected |= {f"call_{p}" for p in call_providers}
    expected |= {f"channel_{c}" for c in SUPPORTED_CHANNELS}

    missing = expected - set(BUILTIN_PLUGINS)
    assert not missing, f"family plugins missing an egress manifest: {missing}"


def test_register_dynamic_domain_parses_url_and_bare_host():
    import agents.core.plugin_gate as pg
    from agents.core.plugin_gate import register_dynamic_domain, dynamic_domains
    pid = "test_dyn_xyz"
    pg._DYNAMIC_DOMAINS.pop(pid, None)
    try:
        register_dynamic_domain(pid, "https://Host.Example.COM:8443/path")  # full URL
        register_dynamic_domain(pid, "bare.example.org:9000")               # bare host:port
        register_dynamic_domain(pid, "")                                    # no-op
        register_dynamic_domain(pid, None)                                  # no-op
        assert set(dynamic_domains(pid)) == {"host.example.com", "bare.example.org"}
    finally:
        pg._DYNAMIC_DOMAINS.pop(pid, None)


def test_dynamic_domain_allows_registered_host_blocks_others_under_strict(monkeypatch):
    # n8n carries no static allowlist: only the registered config host may pass.
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    import agents.core.plugin_gate as pg
    monkeypatch.setitem(pg._DYNAMIC_DOMAINS, "n8n", {"n8n.internal.example"})
    c = PluginHTTPClient.for_plugin("n8n")
    c._enforce_egress("https://n8n.internal.example/api/v1/workflows")  # registered → ok
    with pytest.raises(PluginEgressError):
        c._enforce_egress("https://evil.example/api/v1/workflows")      # unregistered → blocked


def test_signal_channel_registers_its_config_host():
    import agents.core.plugin_gate as pg
    from agents.core.channels.webhook_channels import SignalChannel
    pg._DYNAMIC_DOMAINS.pop("channel_signal", None)
    try:
        SignalChannel(config={"base_url": "http://signal.local:8080", "number": "+1"})
        assert "signal.local" in pg.dynamic_domains("channel_signal")
    finally:
        pg._DYNAMIC_DOMAINS.pop("channel_signal", None)


def test_matrix_channel_registers_its_config_host():
    import agents.core.plugin_gate as pg
    from agents.core.channels.webhook_channels import MatrixChannel
    pg._DYNAMIC_DOMAINS.pop("channel_matrix", None)
    try:
        MatrixChannel(config={"homeserver": "https://matrix.example.org", "token": "x"})
        assert "matrix.example.org" in pg.dynamic_domains("channel_matrix")
    finally:
        pg._DYNAMIC_DOMAINS.pop("channel_matrix", None)


# ── the owner's TLS trust anchor (JARVIS_CA_BUNDLE) ──────────────────────────
# Every plugin client is built `trust_env=False`, so it verifies against certifi alone
# and a TLS-inspecting proxy or a private CA makes every outbound call fail silently
# (web_search answers count: 0). The anchor names the missing root. It may only ADD.

def _self_signed_ca(tmp_path):
    """A throwaway CA PEM whose subject we can look for in the loaded context."""
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nerva-test-anchor")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "extra-ca.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


def test_no_anchor_configured_keeps_the_default_trust_store(monkeypatch):
    from agents.core.http_client import CA_BUNDLE_ENV, tls_verify

    monkeypatch.delenv(CA_BUNDLE_ENV, raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    assert tls_verify() is True          # httpx's own default: certifi


def test_the_anchor_is_added_to_the_default_store_never_swapped_for_it(monkeypatch, tmp_path):
    import ssl

    from agents.core.http_client import CA_BUNDLE_ENV, tls_verify

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv(CA_BUNDLE_ENV, str(_self_signed_ca(tmp_path)))
    context = tls_verify()

    assert isinstance(context, ssl.SSLContext)
    subjects = [
        value
        for cert in context.get_ca_certs()
        for rdn in cert.get("subject", ())
        for _key, value in rdn
    ]
    assert "nerva-test-anchor" in subjects, "the owner's anchor is missing"
    # and the anchors the box already trusted are still there — this ADDS
    assert len(context.get_ca_certs()) > 1, "the default store was replaced, not extended"


def test_verification_stays_on_for_every_value_the_variable_can_take(monkeypatch, tmp_path):
    """There must be no spelling of this knob that turns certificate checking off —
    a knob that could would make every SSRF and egress guard in the module decorative."""
    import ssl

    from agents.core.http_client import CA_BUNDLE_ENV, tls_verify

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    for value in ("0", "false", "off", "no", "none", "-1", "/dev/null",
                  "/nope/missing.pem", str(_self_signed_ca(tmp_path)), " "):
        monkeypatch.setenv(CA_BUNDLE_ENV, value)
        verdict = tls_verify()
        assert verdict is not False, value
        if isinstance(verdict, ssl.SSLContext):
            assert verdict.verify_mode == ssl.CERT_REQUIRED, value
            assert verdict.check_hostname is True, value
        else:
            assert verdict is True, value


def test_an_unreadable_or_malformed_bundle_degrades_to_the_default_and_says_so(
    monkeypatch, tmp_path, caplog,
):
    from agents.core.http_client import CA_BUNDLE_ENV, tls_verify

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv(CA_BUNDLE_ENV, str(tmp_path / "does-not-exist.pem"))
    with caplog.at_level("WARNING"):
        assert tls_verify() is True
    assert any(CA_BUNDLE_ENV in record.getMessage() for record in caplog.records)

    junk = tmp_path / "junk.pem"
    junk.write_text("not a certificate", encoding="utf-8")
    monkeypatch.setenv(CA_BUNDLE_ENV, str(junk))
    caplog.clear()
    with caplog.at_level("WARNING"):
        assert tls_verify() is True
    assert any(CA_BUNDLE_ENV in record.getMessage() for record in caplog.records)


def test_ssl_cert_file_is_the_second_spelling(monkeypatch, tmp_path):
    import ssl

    from agents.core.http_client import CA_BUNDLE_ENV, tls_verify

    monkeypatch.delenv(CA_BUNDLE_ENV, raising=False)
    monkeypatch.setenv("SSL_CERT_FILE", str(_self_signed_ca(tmp_path)))
    assert isinstance(tls_verify(), ssl.SSLContext)
