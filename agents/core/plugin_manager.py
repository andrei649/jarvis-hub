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

import asyncio
import importlib
import inspect
import logging

from agents.core.env_provenance import load_hub_env

from .argus import ArgusInterface
from .env_config import env_str
from .orchestrator_bindings import bind_external_orchestrator_attribute
from .plugins.oauth import init_from_env as _oauth_init
from .plugins.oauth import load_token as _load_token

logger = logging.getLogger("jarvis.plugins.manager")

#: Registry keys that are not the plugin's gate id.
_GATE_IDS = {"whatsapp": "whatsapp-bridge"}

# The names are also the historical module attributes patched by a few tests. A
# constructor is resolved only after the owner's boot load set admits its key.
_PLUGIN_CLASSES = {
    "AnalyticsPlugin": "analytics",
    "AppleHealthPlugin": "apple_health",
    "BalanceReaderPlugin": "balance",
    "CloudLLMPlugin": "cloud_llm",
    "CRMSyncPlugin": "crm_sync",
    "GmailPlugin": "gmail_plugin",
    "GoogleCalendarPlugin": "google_calendar",
    "HomebridgePlugin": "homebridge",
    "IoTControlPlugin": "iot_control",
    "MetaAdsPlugin": "meta_ads",
    "N8NPlugin": "n8n",
    "NewsPlugin": "news",
    "OracleBridgePlugin": "oracle_bridge",
    "OsintEnrichPlugin": "osint_enrich",
    "PostizPlugin": "postiz",
    "RevenueCatPlugin": "revenuecat",
    "SignalLayerPlugin": "signal_layer",
    "SMSAlertsPlugin": "sms_alerts",
    "SpotifyPlugin": "spotify_plugin",
    "StockQuotesPlugin": "stock_quotes",
    "TelegramBotPlugin": "telegram_bot",
    "WeatherPlugin": "weather",
    "WebSearchPlugin": "websearch",
    "WhatsAppBridgePlugin": "whatsapp_bridge",
}


def _plugin_class(name: str):
    if name in globals():
        return globals()[name]
    return getattr(importlib.import_module(f".plugins.{_PLUGIN_CLASSES[name]}", __package__), name)


def __getattr__(name: str):
    """Preserve external class lookup and monkeypatch without importing at module load."""
    if name in _PLUGIN_CLASSES:
        return _plugin_class(name)
    raise AttributeError(name)


class PluginLLMRefused(RuntimeError):
    """A plugin asked for a model call its manifest or the gate does not allow."""


#: The most pieces of a streamed answer queued for a plugin's callback at once, and how
#: long the stream waits for a callback to catch up when the answer is complete.
STREAM_QUEUE_LIMIT = 64
STREAM_DRAIN_SECONDS = 1.0


class _StreamObserver:
    """Hand a plugin's stream callback the answer's pieces without letting it slow them.

    The model's token loop only ever does ``put_nowait`` here. One worker task awaits the
    plugin's callback in order; when the callback falls behind and the bounded queue is
    full, the OLDEST queued piece is dropped (and counted), so a stalled or slow callback
    can neither stall generation nor grow memory. A callback that raises is logged and
    skipped, never propagated into the generation."""

    def __init__(self, callback, plugin_id: str) -> None:
        self._callback = callback
        self._plugin_id = plugin_id
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=STREAM_QUEUE_LIMIT)
        self._closed = False
        self._worker = asyncio.create_task(self._run())
        self._worker.add_done_callback(lambda task: task.cancelled() or task.exception())
        self.dropped = 0

    async def push(self, text: str) -> None:
        while True:
            try:
                self._queue.put_nowait(text)
                return
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    self.dropped += 1
                except asyncio.QueueEmpty:
                    pass

    async def _run(self) -> None:
        while not self._closed:
            text = await self._queue.get()
            try:
                result = self._callback(text)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.warning("plugin %s stream callback failed", self._plugin_id, exc_info=True)
            finally:
                self._queue.task_done()

    async def close(self) -> None:
        """Give the callback a bounded moment to drain, then stop it; never blocks longer."""
        try:
            await asyncio.wait_for(self._queue.join(), STREAM_DRAIN_SECONDS)
        except TimeoutError:
            logger.warning("plugin %s stream callback did not keep up; its remaining pieces were dropped",
                           self._plugin_id)
        finally:
            self._closed = True
            self._worker.cancel()
            # Bounded and cancel-safe: a callback that swallows its cancellation cannot hold
            # the stream open; the worker is abandoned (it exits at its next turn of the loop).
            _done, pending = await asyncio.wait({self._worker}, timeout=STREAM_DRAIN_SECONDS)
            if pending:
                logger.warning("plugin %s stream callback ignored cancellation; abandoned",
                               self._plugin_id)


class PluginLLM:
    """H414 — the plugin LLM facade (Hermes' ``ctx.llm``) for a trusted in-tree plugin.

    Third-party extensions get no ``ctx`` at all (the sandbox never sees a host object),
    so this is the supported lane for the plugins the hub builds itself. ``complete()``
    and ``stream()`` go through ``run_oneshot`` on the auxiliary rail — the fail-closed
    local backend, the auxiliary consent boundary, job pins excluded, bounded budgets —
    labelled ``plugin:<id>`` in the usage ledger. The gate is asked at every call, never
    once at construction: the manifest must declare ``llm_access`` and the plugin must
    still be switched on (the load set and safe mode switch it off with the plugins).
    A stream hook is the plugin's own callable, fed from the same guarded scope.
    """

    def __init__(self, plugin_id: str, *, gate, router) -> None:
        self.plugin_id = plugin_id
        self._gate = gate            # callable -> PermissionGate | None
        self._router = router        # callable -> LLMRouter | None
        #: Pieces of streamed answers dropped because the plugin's callback fell behind.
        self.dropped_tokens = 0

    def _check(self):
        gate = self._gate()
        if gate is None:
            raise PluginLLMRefused("plugin model calls refused: no permission gate is bound")
        manifest = getattr(gate, "plugins", {}).get(self.plugin_id)
        if manifest is None:
            raise PluginLLMRefused(f"plugin model calls refused: unknown plugin {self.plugin_id}")
        if not manifest.enabled:
            raise PluginLLMRefused(f"plugin model calls refused: {self.plugin_id} is switched off")
        if not getattr(manifest, "llm_access", False):
            raise PluginLLMRefused(
                f"plugin model calls refused: {self.plugin_id} does not declare llm_access in its manifest")
        router = self._router()
        if router is None:
            raise PluginLLMRefused("plugin model calls refused: no model router is bound")
        return router

    async def complete(self, prompt: str, *, system: str | None = None,
                       max_tokens: int | None = None, temperature: float = 0.2) -> str:
        """One stateless completion on the auxiliary rail; never a session turn."""
        from .llm.auxiliary_text import DEFAULT_ONESHOT_TOKENS, run_oneshot

        router = self._check()
        return await run_oneshot(
            router, prompt, purpose=f"plugin:{self.plugin_id}", system=system,
            max_tokens=DEFAULT_ONESHOT_TOKENS if max_tokens is None else max_tokens,
            temperature=temperature)

    async def stream(self, prompt: str, *, on_token, system: str | None = None,
                     max_tokens: int | None = None, temperature: float = 0.2) -> str:
        """The same call, with each piece of the answer handed to ``on_token`` as it
        arrives; returns the whole answer.

        The callback runs on its own worker behind a bounded queue (``_StreamObserver``):
        it cannot stall generation, and when it falls behind the oldest pieces are
        dropped and counted in ``dropped_tokens``. The returned answer is always whole."""
        from .llm.auxiliary_text import DEFAULT_ONESHOT_TOKENS, run_oneshot

        router = self._check()
        observer = _StreamObserver(on_token, self.plugin_id)
        try:
            return await run_oneshot(
                router, prompt, purpose=f"plugin:{self.plugin_id}", system=system,
                max_tokens=DEFAULT_ONESHOT_TOKENS if max_tokens is None else max_tokens,
                temperature=temperature, on_token=observer.push)
        finally:
            await observer.close()
            self.dropped_tokens += observer.dropped


class PluginManager:
    """Owns the live-plugin registry (``orch.plugins``) + its build/close lifecycle."""

    def __init__(self):
        self.plugins: dict = {}
        self._llm_orch = None

    def get(self, name: str):
        return self.plugins.get(name)

    # ── H414: the plugin LLM facade ─────────────────────────────────────────────
    def bind_llm(self, orch) -> None:
        """Remember where the gate and the router live; both are read at call time."""
        self._llm_orch = orch

    def llm_for(self, plugin_id: str) -> PluginLLM:
        """The facade for *plugin_id* (its gate id). Cheap, and grants nothing: every
        call re-checks the manifest and the gate."""
        if plugin_id in _GATE_IDS:
            plugin_id = _GATE_IDS[plugin_id]

        def gate():
            if self._llm_orch is None:
                raise PluginLLMRefused("plugin model calls refused: the plugin manager is not bound")
            return getattr(self._llm_orch, "permission_gate", None)

        return PluginLLM(plugin_id, gate=gate,
                         router=lambda: getattr(self._llm_orch, "llm_router", None))

    def attach_llm(self) -> None:
        """Hand the facade to every built plugin that asks for it (``attach_llm``). A
        plugin never imports the rail: the manager gives it the facade, and the gate
        decides at each call whether the facade answers."""
        for key, plugin in self.plugins.items():
            attach = getattr(plugin, "attach_llm", None)
            if callable(attach):
                attach(self.llm_for(key))

    def build(self, orch) -> None:
        """Construct admitted concrete plugins in their historical registry order."""
        # Packaged installs / $JARVIS_USER_HOME: the owner's config lives in
        # <Documents/Jarvis>/.env. Loaded second with override=False, so a repo
        # .env (dev) keeps precedence and only unset keys are filled — in a frozen
        # install there is no repo .env, making this the config source. H273: the
        # load records which layer supplied each key (names only), for the admin
        # route, the doctor and the HUD. The hub's entries (serve.py, the lifespan)
        # have loaded the files before anything they read, so this is their table; an
        # entry that did not (agents/run.py before its main) loads here, once.
        load_hub_env()
        # The HUD's Integrations panel keys (encrypted store), where .env left a name unset.
        from .integration_keys import apply_stored
        apply_stored()

        from . import load_set

        lists = load_set.declared("plugins")

        def permitted(key: str) -> bool:
            return load_set.permits("plugins", _GATE_IDS.get(key, key), lists=lists)

        if permitted("weather"):
            self.plugins["weather"] = _plugin_class("WeatherPlugin")()
        if permitted("news"):
            self.plugins["news"] = _plugin_class("NewsPlugin")()
        if permitted("stock-quotes"):
            self.plugins["stock-quotes"] = _plugin_class("StockQuotesPlugin")()
        if permitted("cloud-llm"):
            self.plugins["cloud-llm"] = _plugin_class("CloudLLMPlugin")(
                anthropic_key=env_str("ANTHROPIC_API_KEY"),
                openai_key=env_str("OPENAI_API_KEY"),
                gemini_key=env_str("GEMINI_API_KEY"),
            )
        if permitted("telegram"):
            self.plugins["telegram"] = _plugin_class("TelegramBotPlugin")(
                token=env_str("TELEGRAM_BOT_TOKEN"),
            )
        _oauth_init()
        if permitted("gmail"):
            gmail_token = env_str("GMAIL_ACCESS_TOKEN") or (_load_token("google") or {}).get("access_token", "")
            self.plugins["gmail"] = _plugin_class("GmailPlugin")(
                access_token=gmail_token,
            )
        if permitted("whatsapp"):
            self.plugins["whatsapp"] = _plugin_class("WhatsAppBridgePlugin")(
                bridge_url=env_str("WHATSAPP_BRIDGE_URL", "http://192.168.1.100:3000"),
                configured=bool(env_str("WHATSAPP_BRIDGE_URL")),
            )
        if permitted("spotify"):
            spotify_token = env_str("SPOTIFY_ACCESS_TOKEN") or (_load_token("spotify") or {}).get("access_token", "")
            spotify_refresh = env_str("SPOTIFY_REFRESH_TOKEN") or (_load_token("spotify") or {}).get("refresh_token", "")
            self.plugins["spotify"] = _plugin_class("SpotifyPlugin")(
                client_id=env_str("SPOTIFY_CLIENT_ID"),
                client_secret=env_str("SPOTIFY_CLIENT_SECRET"),
                access_token=spotify_token,
                refresh_token=spotify_refresh,
            )
        if permitted("google-calendar"):
            cal_token = env_str("GOOGLE_CALENDAR_TOKEN") or (_load_token("google") or {}).get("access_token", "")
            self.plugins["google-calendar"] = _plugin_class("GoogleCalendarPlugin")(
                access_token=cal_token,
            )
        if permitted("apple-health"):
            self.plugins["apple-health"] = _plugin_class("AppleHealthPlugin")(
                bridge_url=env_str("APPLE_HEALTH_BRIDGE_URL", "http://192.168.1.100:8081"),
                configured=bool(env_str("APPLE_HEALTH_BRIDGE_URL")),
            )
        if permitted("homebridge"):
            self.plugins["homebridge"] = _plugin_class("HomebridgePlugin")(
                bridge_url=env_str("HOMEBRIDGE_URL", "http://192.168.1.100:8581"),
                api_token=env_str("HOMEBRIDGE_TOKEN"),
            )
        if permitted("websearch"):
            self.plugins["websearch"] = _plugin_class("WebSearchPlugin")(
                tavily_api_key=env_str("TAVILY_API_KEY"),
                searxng_url=env_str("SEARXNG_URL"),
            )
        # DRA-05: OSINT pivot enrichment stays dark until the owner sets
        # JARVIS_OSINT_ENRICH; the load set may also exclude construction.
        if permitted("osint_enrich"):
            self.plugins["osint_enrich"] = _plugin_class("OsintEnrichPlugin")()

        if permitted("balance"):
            self.plugins["balance"] = _plugin_class("BalanceReaderPlugin")(
                ing_client_id=orch.get_setting("plugins.gecko_ing_client_id", ""),
                ing_client_secret=orch.get_setting("plugins.gecko_ing_client_secret", ""),
                libra_token=orch.get_setting("plugins.gecko_libra_token", ""),
                csv_path=orch.get_setting("plugins.gecko_csv_path", ""),
                tx_csv_path=orch.get_setting("plugins.gecko_tx_csv_path", ""),
            )
        if permitted("analytics"):
            self.plugins["analytics"] = _plugin_class("AnalyticsPlugin")(
                ga4_service_account=orch.get_setting("plugins.stark_ga4_service_account", ""),
                ga4_property_id=orch.get_setting("plugins.stark_ga4_property_id", ""),
                # H22: local-first analytics is the default; the GA4 remote mirror is
                # opt-in and OFF unless explicitly enabled.
                ga4_enabled=bool(orch.get_setting("plugins.stark_ga4_enabled", False)),
            )

        if permitted("oracle-bridge"):
            self.plugins["oracle-bridge"] = _plugin_class("OracleBridgePlugin")(
                github_token=env_str("GITHUB_TOKEN"),
            )
        if permitted("n8n"):
            self.plugins["n8n"] = _plugin_class("N8NPlugin")(
                base_url=env_str("N8N_BASE_URL"),
                api_key=env_str("N8N_API_KEY"),
            )
        if permitted("sms-alerts"):
            self.plugins["sms-alerts"] = _plugin_class("SMSAlertsPlugin")(
                account_sid=orch.get_setting("plugins.twilio_account_sid", ""),
                auth_token=orch.get_setting("plugins.twilio_auth_token", ""),
                from_number=orch.get_setting("plugins.twilio_from_number", ""),
            )
        if permitted("crm-sync"):
            self.plugins["crm-sync"] = _plugin_class("CRMSyncPlugin")(
                integration_token=orch.get_setting("plugins.notion_integration_token", ""),
                database_id=orch.get_setting("plugins.notion_database_id", ""),
            )
        if permitted("iot-control"):
            self.plugins["iot-control"] = _plugin_class("IoTControlPlugin")(
                client_id=orch.get_setting("plugins.tuya_client_id", ""),
                secret=orch.get_setting("plugins.tuya_secret", ""),
                device_id=orch.get_setting("plugins.tuya_device_id", ""),
            )
        # Signal Layer — provider-neutral world intelligence (local-first; :8787).
        # Read-only + fail-safe: a down service returns {"status":"unavailable"}.
        if permitted("signal-layer"):
            self.plugins["signal-layer"] = _plugin_class("SignalLayerPlugin")(
                api_url=env_str("SIGNAL_LAYER_API_URL"),
                api_token=env_str("SIGNAL_LAYER_API_TOKEN"),
            )
        # Guide-gap wave: business/marketing connectors (read-only / draft-first).
        if permitted("revenuecat"):
            self.plugins["revenuecat"] = _plugin_class("RevenueCatPlugin")(
                api_key=env_str("REVENUECAT_API_KEY"),
                project_id=env_str("REVENUECAT_PROJECT_ID"),
            )
        if permitted("meta-ads"):
            self.plugins["meta-ads"] = _plugin_class("MetaAdsPlugin")(
                access_token=env_str("META_ADS_ACCESS_TOKEN"),
                account_id=env_str("META_ADS_ACCOUNT_ID"),
            )
        if permitted("postiz"):
            self.plugins["postiz"] = _plugin_class("PostizPlugin")(
                base_url=env_str("POSTIZ_URL"),
                api_key=env_str("POSTIZ_API_KEY"),
            )
        self._drop_switched_off()
        # H414: the plugin LLM facade, for the plugins that ask for one.
        self.bind_llm(orch)
        self.attach_llm()
        bind_external_orchestrator_attribute(
            orch, "oracle_bridge", self.plugins.get("oracle-bridge")
        )
        # Argus — one governed facade over Signal Layer for world-intel
        # queries. Built after its backend is registered; every call is gated.
        bind_external_orchestrator_attribute(
            orch, "argus", ArgusInterface.from_orchestrator(orch)
        )

    def _drop_switched_off(self) -> None:
        """H285: a plugin the owner's load set switches off is not kept, as safe mode
        keeps none: the probes and the dashboard reach ``orch.plugins``
        without asking the gate. The lists name gate ids."""
        from . import load_set

        lists = load_set.declared("plugins")
        for key in [k for k in self.plugins if not load_set.permits("plugins", _GATE_IDS.get(k, k), lists=lists)]:
            del self.plugins[key]
            logger.info("Plugin %s not loaded: switched off by the load set", key)

    async def close_all(self) -> None:
        """Close all active plugins gracefully (was Orchestrator.stop_channels inline)."""
        for pid, plugin in self.plugins.items():
            if hasattr(plugin, "close"):
                try:
                    await plugin.close()
                except Exception as e:
                    logger.warning(f"Error closing plugin {pid}: {e}")
