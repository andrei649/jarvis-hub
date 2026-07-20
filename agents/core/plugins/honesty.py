"""
honesty.py — per-plugin runtime honesty verdict.

The capability registry tracks *lifecycle* state (a plugin is WIRED into the app);
this adds the runtime bit the HUD needs to stop mock reading as real: is a plugin
actually going to return real data / perform real actions right now, or is it
running in a mock/degraded fallback because the owner hasn't supplied its keys?

`honesty_for` turns the `/plugins` `configured` signal into a single verdict per
plugin — ``live`` or ``needs_config`` — plus the exact settings/steps required to
make it live. This is the authoritative source the HUD "honesty badges" render.
"""
from __future__ import annotations

# Manifest plugin id → the config an owner must supply to move it from mock → live.
# Only plugins that have a real config gate appear here; keyless plugins
# (weather, news, stock-quotes, local analytics) are live with no setup.
_NEEDS: dict[str, list[str]] = {
    "iot-control": ["plugins.tuya_client_id", "plugins.tuya_secret", "plugins.tuya_device_id"],
    "balance": ["plugins.gecko_ing_client_id", "plugins.gecko_libra_token", "plugins.gecko_csv_path"],
    "sms-alerts": ["plugins.twilio_account_sid", "plugins.twilio_auth_token", "plugins.twilio_from_number"],
    "crm-sync": ["plugins.notion_integration_token", "plugins.notion_database_id"],
    "gmail": ["Google OAuth (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)"],
    "google-calendar": ["Google OAuth (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)"],
    "spotify": ["Spotify OAuth (SPOTIFY_CLIENT_ID / SPOTIFY_ACCESS_TOKEN)"],
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "whatsapp-bridge": ["WHATSAPP_BRIDGE_URL"],
    "apple-health": ["APPLE_HEALTH_BRIDGE_URL"],
    "homebridge": ["HOMEBRIDGE_URL", "HOMEBRIDGE_TOKEN"],
    "websearch": ["TAVILY_API_KEY", "or beautifulsoup4 for the keyless DuckDuckGo fallback"],
    "n8n": ["N8N_BASE_URL", "N8N_API_KEY"],
    "meta-ads": ["META_ADS_ACCESS_TOKEN"],
    "postiz": ["POSTIZ_API_KEY"],
    "revenuecat": ["REVENUECAT_API_KEY"],
}


def live_plugin_for(orch, plugin_id: str):
    """Resolve a manifest plugin id to its live instance in ``orch.plugins``.

    A couple of manifest ids don't match their live-registry key 1:1; the alias
    map covers those. Missing/unbuilt orchestrators resolve to ``None``.
    """
    live_plugins = getattr(orch, "plugins", {}) or {}
    aliases = {
        "whatsapp-bridge": "whatsapp",
    }
    return live_plugins.get(plugin_id) or live_plugins.get(aliases.get(plugin_id, ""))


def runtime_configuration(plugin) -> tuple[bool, str]:
    """Return whether a live plugin instance is actually owner-configured.

    The manifest says a plugin exists and is allowed; callers (the `/plugins`
    HUD listing, the capability registry) need the next bit of truth: whether
    the owner supplied keys / a LAN bridge / a local data file. Prefers each
    plugin's own ``configured`` / ``available`` / ``_configured`` contract when
    it has one; otherwise a constructed plugin is considered configured because
    there is no known extra setup signal.
    """
    if plugin is None:
        return False, "not-loaded"
    for attr_name in ("configured", "available", "_configured"):
        if not hasattr(plugin, attr_name):
            continue
        attr = getattr(plugin, attr_name)
        try:
            value = attr() if callable(attr) else attr
        except Exception:
            return False, f"{attr_name}-error"
        return bool(value), f"{attr_name}()"
    return True, "loaded"


def degradation_info(plugin) -> dict | None:
    """A live plugin's own honesty contract: ``None`` = live, else ``{reason, needs}``.

    Plugins whose calls silently fall back to mock data expose a
    ``degradation_info()`` method so callers can badge them instead of letting
    scaffold read as product. Absent method → no known mock path.
    """
    info_fn = getattr(plugin, "degradation_info", None)
    if not callable(info_fn):
        return None
    try:
        info = info_fn()
    except Exception:
        return {"reason": "degradation-introspection-error", "needs": []}
    return info if isinstance(info, dict) else None


def honesty_for(plugin_id: str, configured: bool,
                configuration_source: str = "") -> dict:
    """Runtime honesty verdict for one plugin.

    * ``live`` — configured (or keyless-by-design): returns real data / real actions.
    * ``needs_config`` — running in a mock/degraded fallback until the owner
      supplies the config listed in ``needs``.
    """
    if configured:
        keyless = configuration_source in ("", "loaded")
        return {
            "status": "live",
            "reason": "no setup required" if keyless else "configured",
            "needs": [],
        }
    return {
        "status": "needs_config",
        "reason": "running in mock/degraded mode until configured",
        "needs": _NEEDS.get(plugin_id, []),
    }
