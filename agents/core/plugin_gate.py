"""
plugins.py — Plugin system for opt-in third-party integrations.

Each plugin declares a manifest with its network scope, data scope,
and which agents it serves. The core blocks any request outside the
declared permissions.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse

logger = logging.getLogger("jarvis.plugins")


class NetworkAccess(Enum):
    NONE = "none"          # No network access (default for Frigga)
    LAN = "lan"            # Local network only (Pi, printer, homebridge)
    RESTRICTED = "restricted"  # Specific domains only
    FULL = "full"          # Any outbound (use with caution)


class DataScope(Enum):
    LOCAL_ONLY = "local_only"     # Data never leaves the machine
    PROCESSED = "processed"       # Data is processed locally, only metadata/results sent
    TRANSMITTED = "transmitted"   # Data is transmitted to third-party (e.g., cloud LLM)


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    description: str
    network_access: NetworkAccess
    data_scope: DataScope
    allowed_domains: list[str] = field(default_factory=list)
    agents_served: list[str] = field(default_factory=list)
    enabled: bool = True


# Built-in plugin manifests
BUILTIN_PLUGINS = {
    "weather": PluginManifest(
        id="weather",
        name="Weather (wttr.in)",
        version="0.1.0",
        description="Real-time weather data from wttr.in",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["wttr.in"],
        agents_served=["all"],
    ),
    "news": PluginManifest(
        id="news",
        name="News (BBC RSS)",
        version="0.1.0",
        description="News headlines from BBC RSS feeds",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["feeds.bbci.co.uk", "www.hotnews.ro", "www.stiripesurse.ro"],
        agents_served=["all"],
    ),
    "cloud-llm": PluginManifest(
        id="cloud-llm",
        name="Cloud LLM Fallback",
        version="0.1.0",
        description="Optional Anthropic/OpenAI fallback for heavy reasoning",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com"],
        agents_served=["jarvis", "athena", "stark", "vision", "veronica"],
    ),
    "telegram": PluginManifest(
        id="telegram",
        name="Telegram Bot",
        version="0.1.0",
        description="Telegram bot for agent communication",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["api.telegram.org"],
        agents_served=["all"],
    ),
    "gmail": PluginManifest(
        id="gmail",
        name="Gmail API",
        version="0.1.0",
        description="Read and compose emails",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["gmail.googleapis.com", "www.googleapis.com", "oauth2.googleapis.com"],
        agents_served=["stark", "pepper", "veronica"],
    ),
    "google-calendar": PluginManifest(
        id="google-calendar",
        name="Google Calendar API",
        version="0.1.0",
        description="Read and manage calendar events",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["www.googleapis.com", "oauth2.googleapis.com"],
        agents_served=["pepper"],
    ),
    "whatsapp-bridge": PluginManifest(
        id="whatsapp-bridge",
        name="WhatsApp Local Bridge",
        version="0.1.0",
        description="Local WhatsApp bridge for Frigga (family data never leaves LAN)",
        network_access=NetworkAccess.LAN,
        data_scope=DataScope.LOCAL_ONLY,
        allowed_domains=[],
        agents_served=["frigga"],
    ),
    "spotify": PluginManifest(
        id="spotify",
        name="Spotify Control",
        version="0.1.0",
        description="Music playback control and playlist management",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["api.spotify.com", "accounts.spotify.com"],
        agents_served=["jerome"],
    ),
    "apple-health": PluginManifest(
        id="apple-health",
        name="Apple Health Sync",
        version="0.1.0",
        description="Read sleep, HRV, and activity data",
        network_access=NetworkAccess.LAN,
        data_scope=DataScope.LOCAL_ONLY,
        allowed_domains=[],
        agents_served=["hercules"],
    ),
    "homebridge": PluginManifest(
        id="homebridge",
        name="Homebridge Smart Home",
        version="0.1.0",
        description="Smart home device control via Homebridge",
        network_access=NetworkAccess.LAN,
        data_scope=DataScope.LOCAL_ONLY,
        allowed_domains=[],
        agents_served=["jarvis", "ultron"],
    ),
    "oracle-bridge": PluginManifest(
        id="oracle-bridge",
        name="Oracle Pipeline Weaver",
        version="0.1.0",
        description="Monitors GitHub for Claude commits, auto-pulls, runs tests, detects conflicts",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["api.github.com"],
        agents_served=["oracle"],
    ),
    "system-control": PluginManifest(
        id="system-control",
        name="System Control",
        version="0.1.0",
        description="Restart/recover local host services (allowlisted argv, local-only, no network)",
        network_access=NetworkAccess.NONE,
        data_scope=DataScope.LOCAL_ONLY,
        allowed_domains=[],
        agents_served=["steve", "ultron", "jarvis"],
    ),
    "sms-alerts": PluginManifest(
        id="sms-alerts",
        name="SMS Alerts & Notifications",
        version="0.1.0",
        description="Twilio-powered urgent offline SMS alerts and notifications",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["api.twilio.com"],
        agents_served=["steve", "ultron", "jarvis"],
    ),
    "crm-sync": PluginManifest(
        id="crm-sync",
        name="Notion CRM Sync",
        version="0.1.0",
        description="Notion CRM pipeline leads database ingestion synchronizer",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["api.notion.com"],
        agents_served=["stark", "veronica", "hephaestus"],
    ),
    "iot-control": PluginManifest(
        id="iot-control",
        name="Tuya SmartHome IoT Controller",
        version="0.1.0",
        description="Smart switch and local LAN loop Tuya socket command toggles",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.LOCAL_ONLY,
        allowed_domains=["openapi.tuya.com"],
        agents_served=["jarvis", "ultron"],
    ),
    "worldview": PluginManifest(
        id="worldview",
        name="WorldView 4D OSINT",
        version="0.1.0",
        description="Query the local WorldView 4D OSINT platform (as-of-T layers, recon windows, provenance)",
        network_access=NetworkAccess.LAN,
        data_scope=DataScope.LOCAL_ONLY,
        allowed_domains=[],
        agents_served=["jarvis", "athena", "stark", "vision", "argus"],
    ),
    # ── SEC-5b: previously-unmanifested networked plugins ─────────────────────
    # These reached the network with no manifest (→ fail-open / unrestricted).
    # Now each is gated by the egress boundary. Config/env-driven hosts (n8n,
    # SearXNG, Signal, Matrix) carry no static allowlist and are augmented at
    # init via register_dynamic_domain(); see the plugins' constructors.
    "balance": PluginManifest(
        id="balance",
        name="Bank Balance Reader",
        version="0.1.0",
        description="Read-only account balances from ING / Libra bank APIs",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["api.ing.com", "api.libra.ro"],
        agents_served=["all"],
    ),
    "analytics": PluginManifest(
        id="analytics",
        name="Google Analytics (GA4)",
        version="0.1.0",
        description="GA4 KPI reporting via the Analytics Data API",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["analyticsdata.googleapis.com", "oauth2.googleapis.com"],
        agents_served=["all"],
    ),
    "websearch": PluginManifest(
        id="websearch",
        name="Web Search",
        version="0.1.0",
        description="Web search via Tavily / DuckDuckGo / (optional) SearXNG",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        # SearXNG host is config-driven (SEARXNG_URL) → registered dynamically.
        allowed_domains=["api.tavily.com", "html.duckduckgo.com"],
        agents_served=["all"],
    ),
    "n8n": PluginManifest(
        id="n8n",
        name="n8n Workflow Designer",
        version="0.1.0",
        description="Create/list/activate n8n workflows via its REST API",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        # Base URL is config-driven (N8N_BASE_URL) → registered dynamically.
        allowed_domains=[],
        agents_served=["all"],
    ),
    "digest": PluginManifest(
        id="digest",
        name="Topic Digest Aggregator",
        version="0.1.0",
        description="Aggregate public RSS/Atom feeds (HN, Reddit, arXiv, YouTube, Google News)",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["hnrss.org", "www.reddit.com", "export.arxiv.org",
                         "news.google.com", "www.youtube.com"],
        agents_served=["all"],
    ),
    # Governed social writes (social.py) — one id per platform: social_<platform>.
    "social_x": PluginManifest(
        id="social_x",
        name="Social: X/Twitter",
        version="0.1.0",
        description="Governed X/Twitter post/reply/DM",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["api.twitter.com"],
        agents_served=["all"],
    ),
    # Governed write-back (writeback.py) — one id per target: writeback_<target>.
    "writeback_notion": PluginManifest(
        id="writeback_notion",
        name="Write-back: Notion",
        version="0.1.0",
        description="Governed Notion page/block write-back",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["api.notion.com"],
        agents_served=["all"],
    ),
    "writeback_github": PluginManifest(
        id="writeback_github",
        name="Write-back: GitHub",
        version="0.1.0",
        description="Governed GitHub issue/comment write-back",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["api.github.com"],
        agents_served=["all"],
    ),
    "writeback_google_calendar": PluginManifest(
        id="writeback_google_calendar",
        name="Write-back: Google Calendar",
        version="0.1.0",
        description="Governed Google Calendar event write-back",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["www.googleapis.com"],
        agents_served=["all"],
    ),
    # Governed outbound calls (autonomy/call_broker.py) — id per provider.
    "call_twilio": PluginManifest(
        id="call_twilio",
        name="Call: Twilio",
        version="0.1.0",
        description="Governed outbound voice via Twilio",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["api.twilio.com"],
        agents_served=["all"],
    ),
    "call_telnyx": PluginManifest(
        id="call_telnyx",
        name="Call: Telnyx",
        version="0.1.0",
        description="Governed outbound voice via Telnyx",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["api.telnyx.com"],
        agents_served=["all"],
    ),
    # Governed webhook channels (channels/webhook_channels.py) — id per channel.
    "channel_whatsapp": PluginManifest(
        id="channel_whatsapp",
        name="Channel: WhatsApp Cloud",
        version="0.1.0",
        description="WhatsApp Cloud API (Meta Graph) outbound",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["graph.facebook.com"],
        agents_served=["all"],
    ),
    "channel_google_chat": PluginManifest(
        id="channel_google_chat",
        name="Channel: Google Chat",
        version="0.1.0",
        description="Google Chat incoming-webhook outbound",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["chat.googleapis.com"],
        agents_served=["all"],
    ),
    "channel_teams": PluginManifest(
        id="channel_teams",
        name="Channel: Microsoft Teams",
        version="0.1.0",
        description="Microsoft Teams incoming-webhook outbound",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        # Teams webhook hosts (anchored subdomain match covers per-tenant prefixes);
        # a config-supplied webhook host is also registered dynamically.
        allowed_domains=["webhook.office.com", "logic.azure.com"],
        agents_served=["all"],
    ),
    "channel_signal": PluginManifest(
        id="channel_signal",
        name="Channel: Signal",
        version="0.1.0",
        description="Signal via signal-cli REST API (host from config base_url)",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=[],  # base_url is config-driven → registered dynamically
        agents_served=["all"],
    ),
    "channel_matrix": PluginManifest(
        id="channel_matrix",
        name="Channel: Matrix",
        version="0.1.0",
        description="Matrix client-server API (homeserver from config)",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=[],  # homeserver is config-driven → registered dynamically
        agents_served=["all"],
    ),
}


def host_in_allowlist(host: str, allowed_domains: list[str]) -> bool:
    """True if *host* exactly matches an allowed domain or is a sub-domain of one.

    F-07: replaces the old ``any(d in host)`` substring test, which let
    ``api.openai.com.evil.example`` slip past an allowlist of ``api.openai.com``.
    Matching is now anchored: ``host == d`` or ``host`` ends with ``"." + d``.
    """
    host = (host or "").lower().strip().rstrip(".")
    if not host:
        return False
    for d in allowed_domains or []:
        d = (d or "").lower().strip().rstrip(".")
        if d and (host == d or host.endswith("." + d)):
            return True
    return False


# ── SEC-5b: runtime allowlist augmentation ───────────────────────────────────
# Some networked plugins take their egress host from config/env (n8n
# N8N_BASE_URL, websearch SEARXNG_URL, Signal base_url, Matrix homeserver), so it
# can't be a static ``allowed_domains`` entry. Such a plugin registers its
# configured host once at init; the egress gate unions these in with the
# manifest's static allowlist. This keeps the strict-by-default boundary on
# (unregistered hosts are still blocked) without a FULL/unmanifested escape.
_DYNAMIC_DOMAINS: "dict[str, set[str]]" = {}


def register_dynamic_domain(plugin_id: str, url_or_host: str) -> None:
    """Allow *plugin_id* to reach the host in *url_or_host*.

    Accepts a full URL (``https://host:port/path``) or a bare host (``host:port``
    / ``host``). No-op on empty/unparseable input. Idempotent.
    """
    if not plugin_id or not url_or_host:
        return
    raw = str(url_or_host).strip()
    parsed = urlparse(raw if "//" in raw else "//" + raw)
    host = (parsed.hostname or "").lower().strip().rstrip(".")
    if host:
        _DYNAMIC_DOMAINS.setdefault(plugin_id, set()).add(host)


def dynamic_domains(plugin_id: str) -> list[str]:
    """Hosts registered at runtime for *plugin_id* (see register_dynamic_domain)."""
    return sorted(_DYNAMIC_DOMAINS.get(plugin_id, ()))


class PermissionGate:
    """
    Central gate that all agent-to-plugin calls pass through.
    Blocks any call that exceeds the plugin's declared permissions.
    """

    def __init__(self):
        self.plugins: dict[str, PluginManifest] = {}
        self._load_builtins()

    def _load_builtins(self):
        for plugin_id, manifest in BUILTIN_PLUGINS.items():
            self.register(manifest)

    def register(self, manifest: PluginManifest):
        self.plugins[manifest.id] = manifest
        logger.info(f"Registered plugin: {manifest.id} ({manifest.network_access.value})")

    def check_call(self, plugin_id: str, agent_id: str, target_domain: str = "") -> bool:
        """
        Check if an agent is allowed to call a plugin.
        Returns True if allowed, False if blocked.
        """
        manifest = self.plugins.get(plugin_id)
        if not manifest:
            logger.warning(f"Plugin {plugin_id} not found — blocked")
            return False

        if not manifest.enabled:
            logger.warning(f"Plugin {plugin_id} is disabled — blocked")
            return False

        if agent_id not in manifest.agents_served and "all" not in manifest.agents_served:
            logger.warning(f"Agent {agent_id} not served by plugin {plugin_id} — blocked")
            return False

        if manifest.network_access == NetworkAccess.NONE:
            return True  # local-only, always allowed

        if manifest.network_access == NetworkAccess.LAN:
            # In production: check if target is a LAN IP
            return True

        if manifest.network_access == NetworkAccess.RESTRICTED:
            if not target_domain:
                return True  # No domain specified = internal processing (URL-level egress is enforced in PluginHTTPClient)
            allowed = host_in_allowlist(target_domain, manifest.allowed_domains)
            if not allowed:
                logger.warning(f"Domain {target_domain} not allowed by plugin {plugin_id} — blocked")
            return allowed

        if manifest.network_access == NetworkAccess.FULL:
            return True  # Unrestricted (use with extreme caution)

        return False

    def enable(self, plugin_id: str):
        manifest = self.plugins.get(plugin_id)
        if manifest:
            manifest.enabled = True

    def disable(self, plugin_id: str):
        manifest = self.plugins.get(plugin_id)
        if manifest:
            manifest.enabled = False
            logger.info(f"Plugin {plugin_id} disabled")
