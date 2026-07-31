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

# Plugins that are genuinely live with no configuration at all. This used to be a comment
# on _NEEDS ("keyless plugins … are live with no setup") and nothing but a comment, so the
# code could not tell "keyless by design" apart from "exposes no contract, so we know
# nothing" — and resolved both to LIVE. Splitting them is what lets the unknown case stop
# claiming to work without turning these correct greens grey.
_KEYLESS: frozenset[str] = frozenset({
    "weather",
    "news",
    "stock-quotes",
    "analytics",
})

# Manifest plugin id → the config an owner must supply to move it from mock → live.
# Only plugins that have a real config gate appear here; the keyless ones are in
# _KEYLESS above.
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
                configuration_source: str = "", degraded: bool = False) -> dict:
    """Runtime honesty verdict for one plugin.

    * ``live`` — configured (or keyless-by-design): returns real data / real actions.
    * ``needs_config`` — running in a mock/degraded fallback until the owner
      supplies the config listed in ``needs``.
    * ``unknown`` — the plugin exposes no configuration contract and we have no other
      evidence. Not the same claim as ``live``, and it must not render as one.

    The adversarial audit (2026-07-25) found this wrong in BOTH directions, on exactly the
    plugins it was written for. Three fixes, and none of them is the same fix:

    1. ``degraded`` overrides. A plugin whose own ``degradation_info()`` says it is
       returning mock data is not live, whatever ``configured`` claims. This is the
       cheapest and widest of the three.
    2. ``"loaded"`` no longer means keyless. ``plugin_configured`` returns
       ``(True, "loaded")`` when a class exposes none of
       ``configured``/``available``/``_configured`` — i.e. when it has told us *nothing*.
       Reading that as "live, no setup required" is the core error, and it is why plugins
       whose ids appear in ``_NEEDS`` — the table in this very module naming the key each
       one requires — badged green on a keyless boot. A plugin with no contract now
       resolves against ``_NEEDS``: named there → ``needs_config``; absent → ``unknown``.
    3. ``needs`` is never empty on a ``needs_config`` verdict without saying why. An amber
       chip whose tooltip lists nothing tells the owner to configure something and cannot
       say what — which is how the one keyless-but-real plugin was reported.
    """
    if degraded:
        # The plugin's own contract beats an inferred `configured`: it is telling us it
        # will return mock data on the next call.
        return {
            "status": "needs_config",
            "reason": "running on a mock/degraded fallback",
            "needs": _NEEDS.get(plugin_id, []) or ["see the plugin's degradation details"],
        }

    contract_less = configuration_source in ("", "loaded")
    if configured and not contract_less:
        return {"status": "live", "reason": "configured", "needs": []}

    if configured and contract_less:
        if plugin_id in _KEYLESS:
            # Genuinely keyless by design, declared rather than inferred from the absence
            # of a contract — which is the distinction that makes `unknown` safe to add.
            return {"status": "live", "reason": "no setup required", "needs": []}
        needs = _NEEDS.get(plugin_id)
        if needs:
            # The module contradicts itself if we return "live" here: _NEEDS names the key
            # this plugin requires, and the plugin exposes nothing that could ever report
            # configured=False.
            return {
                "status": "needs_config",
                "reason": "exposes no configuration contract, but this module lists "
                          "config it requires — treat as not configured",
                "needs": list(needs),
            }
        return {
            "status": "unknown",
            "reason": "exposes no configuration contract and declares no required config",
            "needs": [],
        }

    return {
        "status": "needs_config",
        "reason": "running in mock/degraded mode until configured",
        "needs": _NEEDS.get(plugin_id, []) or ["config required, but none is declared "
                                               "for this plugin — see its module"],
    }
