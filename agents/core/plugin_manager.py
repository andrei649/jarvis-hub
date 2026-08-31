"""
plugin_manager.py — PluginManager: the live-plugin registry + lifecycle (CLN-2).

Extracted from the Orchestrator god-object so the "which third-party plugins exist
and how we build/close them" concern is decoupled from orchestration lifecycle.
The Orchestrator keeps a ``plugins`` property that delegates here, so existing
``orch.plugins[...]`` / ``orch.plugins.get(...)`` access is unchanged.

Mirrors the ChannelManager extraction exactly: the manager owns the registry dict
and the build/close lifecycle; the facade exposes it via a getter/setter property.
``build(orch)`` takes the orchestrator as a parameter (back-ref pattern) so it can
read live settings (``orch.get_setting``) and set the few orchestrator attributes
the rest of the app reads off the facade (``orch.oracle_bridge``, ``orch.argus``).
No top-level import of Orchestrator — no import cycle.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv

from .argus import ArgusInterface
from .env_config import env_str
from .orchestrator_bindings import bind_external_orchestrator_attribute
from .plugins.analytics import AnalyticsPlugin
from .plugins.apple_health import AppleHealthPlugin
from .plugins.balance import BalanceReaderPlugin
from .plugins.cloud_llm import CloudLLMPlugin
from .plugins.crm_sync import CRMSyncPlugin
from .plugins.gmail_plugin import GmailPlugin
from .plugins.google_calendar import GoogleCalendarPlugin
from .plugins.homebridge import HomebridgePlugin
from .plugins.iot_control import IoTControlPlugin
from .plugins.meta_ads import MetaAdsPlugin
from .plugins.n8n import N8NPlugin
from .plugins.news import NewsPlugin
from .plugins.oauth import init_from_env as _oauth_init
from .plugins.oauth import load_token as _load_token
from .plugins.oracle_bridge import OracleBridgePlugin
from .plugins.osint_enrich import OsintEnrichPlugin
from .plugins.postiz import PostizPlugin
from .plugins.revenuecat import RevenueCatPlugin
from .plugins.signal_layer import SignalLayerPlugin
from .plugins.sms_alerts import SMSAlertsPlugin
from .plugins.spotify_plugin import SpotifyPlugin
from .plugins.stock_quotes import StockQuotesPlugin
from .plugins.telegram_bot import TelegramBotPlugin
from .plugins.weather import WeatherPlugin
from .plugins.websearch import WebSearchPlugin
from .plugins.whatsapp_bridge import WhatsAppBridgePlugin
from .plugins.worldview import WorldViewPlugin

logger = logging.getLogger("jarvis.plugins.manager")


class PluginManager:
    """Owns the live-plugin registry (``orch.plugins``) + its build/close lifecycle."""

    def __init__(self):
        self.plugins: dict = {}

    def get(self, name: str):
        return self.plugins.get(name)

    def build(self, orch) -> None:
        """Construct every live plugin into the registry (was Orchestrator.load_agents
        inline). Byte-identical to the previous inline block: same order, same env /
        settings reads, same orchestrator attributes set (``orch.oracle_bridge``,
        ``orch.argus``)."""
        self.plugins["weather"] = WeatherPlugin()
        self.plugins["news"] = NewsPlugin()
        self.plugins["stock-quotes"] = StockQuotesPlugin()
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        load_dotenv(env_path)
        # Packaged installs / $JARVIS_USER_HOME: the owner's config lives in
        # <Documents/Jarvis>/.env. Loaded second with the default override=False,
        # so a repo .env (dev) keeps precedence and only unset keys are filled —
        # in a frozen install there is no repo .env, making this the config source.
        from agents.core.paths import user_home
        home = user_home()
        if home is not None and (home / ".env").exists():
            load_dotenv(home / ".env")
        self.plugins["cloud-llm"] = CloudLLMPlugin(
            anthropic_key=env_str("ANTHROPIC_API_KEY"),
            openai_key=env_str("OPENAI_API_KEY"),
            gemini_key=env_str("GEMINI_API_KEY"),
        )
        self.plugins["telegram"] = TelegramBotPlugin(
            token=env_str("TELEGRAM_BOT_TOKEN"),
        )
        _oauth_init()
        _gmail_token = env_str("GMAIL_ACCESS_TOKEN") or (_load_token("google") or {}).get("access_token", "")
        self.plugins["gmail"] = GmailPlugin(
            access_token=_gmail_token,
        )
        self.plugins["whatsapp"] = WhatsAppBridgePlugin(
            bridge_url=env_str("WHATSAPP_BRIDGE_URL", "http://192.168.1.100:3000"),
            configured=bool(env_str("WHATSAPP_BRIDGE_URL")),
        )
        _spotify_token = env_str("SPOTIFY_ACCESS_TOKEN") or (_load_token("spotify") or {}).get("access_token", "")
        _spotify_refresh = env_str("SPOTIFY_REFRESH_TOKEN") or (_load_token("spotify") or {}).get("refresh_token", "")
        self.plugins["spotify"] = SpotifyPlugin(
            client_id=env_str("SPOTIFY_CLIENT_ID"),
            client_secret=env_str("SPOTIFY_CLIENT_SECRET"),
            access_token=_spotify_token,
            refresh_token=_spotify_refresh,
        )
        _cal_token = env_str("GOOGLE_CALENDAR_TOKEN") or (_load_token("google") or {}).get("access_token", "")
        self.plugins["google-calendar"] = GoogleCalendarPlugin(
            access_token=_cal_token,
        )
        self.plugins["apple-health"] = AppleHealthPlugin(
            bridge_url=env_str("APPLE_HEALTH_BRIDGE_URL", "http://192.168.1.100:8081"),
            configured=bool(env_str("APPLE_HEALTH_BRIDGE_URL")),
        )
        self.plugins["homebridge"] = HomebridgePlugin(
            bridge_url=env_str("HOMEBRIDGE_URL", "http://192.168.1.100:8581"),
            api_token=env_str("HOMEBRIDGE_TOKEN"),
        )
        self.plugins["websearch"] = WebSearchPlugin(
            tavily_api_key=env_str("TAVILY_API_KEY"),
            searxng_url=env_str("SEARXNG_URL"),
        )
        # DRA-05: OSINT pivot enrichment. Constructed always, dark always — it makes no
        # outbound call until the owner sets JARVIS_OSINT_ENRICH.
        self.plugins["osint_enrich"] = OsintEnrichPlugin()

        self.plugins["balance"] = BalanceReaderPlugin(
            ing_client_id=orch.get_setting("plugins.gecko_ing_client_id", ""),
            ing_client_secret=orch.get_setting("plugins.gecko_ing_client_secret", ""),
            libra_token=orch.get_setting("plugins.gecko_libra_token", ""),
            csv_path=orch.get_setting("plugins.gecko_csv_path", ""),
            tx_csv_path=orch.get_setting("plugins.gecko_tx_csv_path", ""),
        )
        self.plugins["analytics"] = AnalyticsPlugin(
            ga4_service_account=orch.get_setting("plugins.stark_ga4_service_account", ""),
            ga4_property_id=orch.get_setting("plugins.stark_ga4_property_id", ""),
            # H22: local-first analytics is the default; the GA4 remote mirror is
            # opt-in and OFF unless explicitly enabled.
            ga4_enabled=bool(orch.get_setting("plugins.stark_ga4_enabled", False)),
        )

        self.plugins["oracle-bridge"] = OracleBridgePlugin(
            github_token=env_str("GITHUB_TOKEN"),
        )
        bind_external_orchestrator_attribute(
            orch, "oracle_bridge", self.plugins["oracle-bridge"]
        )
        self.plugins["n8n"] = N8NPlugin(
            base_url=env_str("N8N_BASE_URL"),
            api_key=env_str("N8N_API_KEY"),
        )
        self.plugins["sms-alerts"] = SMSAlertsPlugin(
            account_sid=orch.get_setting("plugins.twilio_account_sid", ""),
            auth_token=orch.get_setting("plugins.twilio_auth_token", ""),
            from_number=orch.get_setting("plugins.twilio_from_number", ""),
        )
        self.plugins["crm-sync"] = CRMSyncPlugin(
            integration_token=orch.get_setting("plugins.notion_integration_token", ""),
            database_id=orch.get_setting("plugins.notion_database_id", ""),
        )
        self.plugins["iot-control"] = IoTControlPlugin(
            client_id=orch.get_setting("plugins.tuya_client_id", ""),
            secret=orch.get_setting("plugins.tuya_secret", ""),
            device_id=orch.get_setting("plugins.tuya_device_id", ""),
        )
        # WorldView 4D OSINT (local-first; override host with WORLDVIEW_API_URL).
        self.plugins["worldview"] = WorldViewPlugin(
            api_url=env_str("WORLDVIEW_API_URL"),
        )
        # Signal Layer — provider-neutral world intelligence (local-first; :8787).
        # Read-only + fail-safe: a down service returns {"status":"unavailable"}.
        self.plugins["signal-layer"] = SignalLayerPlugin(
            api_url=env_str("SIGNAL_LAYER_API_URL"),
            api_token=env_str("SIGNAL_LAYER_API_TOKEN"),
        )
        # Guide-gap wave: business/marketing connectors (read-only / draft-first).
        self.plugins["revenuecat"] = RevenueCatPlugin(
            api_key=env_str("REVENUECAT_API_KEY"),
            project_id=env_str("REVENUECAT_PROJECT_ID"),
        )
        self.plugins["meta-ads"] = MetaAdsPlugin(
            access_token=env_str("META_ADS_ACCESS_TOKEN"),
            account_id=env_str("META_ADS_ACCOUNT_ID"),
        )
        self.plugins["postiz"] = PostizPlugin(
            base_url=env_str("POSTIZ_URL"),
            api_key=env_str("POSTIZ_API_KEY"),
        )
        # Argus — one governed facade over WorldView + Signal Layer for world-intel
        # queries. Built after both backends are registered; every call is gated.
        bind_external_orchestrator_attribute(
            orch, "argus", ArgusInterface.from_orchestrator(orch)
        )

    async def close_all(self) -> None:
        """Close all active plugins gracefully (was Orchestrator.stop_channels inline)."""
        for pid, plugin in self.plugins.items():
            if hasattr(plugin, "close"):
                try:
                    await plugin.close()
                except Exception as e:
                    logger.warning(f"Error closing plugin {pid}: {e}")
