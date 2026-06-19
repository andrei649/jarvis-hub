"""
plugins.py — Plugin system for opt-in third-party integrations.

Each plugin declares a manifest with its network scope, data scope,
and which agents it serves. The core blocks any request outside the
declared permissions.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

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
        allowed_domains=["feeds.bbci.co.uk"],
        agents_served=["all"],
    ),
    "cloud-llm": PluginManifest(
        id="cloud-llm",
        name="Cloud LLM Fallback",
        version="0.1.0",
        description="Optional Anthropic/OpenAI fallback for heavy reasoning",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.TRANSMITTED,
        allowed_domains=["api.anthropic.com", "api.openai.com"],
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
        allowed_domains=["gmail.googleapis.com", "www.googleapis.com"],
        agents_served=["stark", "pepper", "veronica"],
    ),
    "google-calendar": PluginManifest(
        id="google-calendar",
        name="Google Calendar API",
        version="0.1.0",
        description="Read and manage calendar events",
        network_access=NetworkAccess.RESTRICTED,
        data_scope=DataScope.PROCESSED,
        allowed_domains=["www.googleapis.com"],
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
