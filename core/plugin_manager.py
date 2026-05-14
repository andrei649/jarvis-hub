import importlib
import logging
from pathlib import Path
from typing import Optional
from .permission_gate import PermissionGate

logger = logging.getLogger("plugins")


class PluginManifest:
    def __init__(self, name: str, module_path: str, allowed_domains: list[str] = None,
                 data_scope: str = "read-only", enabled: bool = True):
        self.name = name
        self.module_path = module_path
        self.allowed_domains = allowed_domains or []
        self.data_scope = data_scope
        self.enabled = enabled
        self.instance = None


class PluginManager:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = Path(plugins_dir)
        self.permission_gate = PermissionGate()
        self._registry: dict[str, PluginManifest] = {}

    async def load_all(self):
        if not self.plugins_dir.exists():
            logger.info("No plugins directory found, skipping plugin loading")
            return
        for f in sorted(self.plugins_dir.iterdir()):
            if f.name.startswith("_") or f.suffix not in (".py",):
                continue
            module_name = f.stem
            manifest = PluginManifest(
                name=module_name,
                module_path=f"plugins.{module_name}",
                allowed_domains=self._detect_domains(module_name),
                data_scope="read-write" if module_name in ("gmail_bridge", "calendar_bridge") else "read-only"
            )
            self._registry[module_name] = manifest
            logger.info(f"Registered plugin: {module_name}")

    async def enable(self, plugin_name: str) -> bool:
        manifest = self._registry.get(plugin_name)
        if not manifest:
            logger.warning(f"Plugin '{plugin_name}' not found")
            return False
        try:
            module = importlib.import_module(manifest.module_path)
            if hasattr(module, "create"):
                manifest.instance = module.create(self.permission_gate)
            manifest.enabled = True
            logger.info(f"Plugin '{plugin_name}' enabled")
            return True
        except Exception as e:
            logger.error(f"Failed to enable plugin '{plugin_name}': {e}")
            return False

    async def call(self, plugin_name: str, action: str, params: dict = None) -> Optional[dict]:
        manifest = self._registry.get(plugin_name)
        if not manifest or not manifest.enabled or not manifest.instance:
            return None
        if not self.permission_gate.check(plugin_name, action, params):
            logger.warning(f"Permission denied: {plugin_name}.{action}")
            return {"error": "permission_denied"}
        try:
            method = getattr(manifest.instance, action, None)
            if method:
                return await method(**(params or {}))
            return None
        except Exception as e:
            logger.error(f"Plugin call failed: {plugin_name}.{action}: {e}")
            return {"error": str(e)}

    async def shutdown_all(self):
        for name, manifest in self._registry.items():
            if manifest.instance and hasattr(manifest.instance, "shutdown"):
                try:
                    await manifest.instance.shutdown()
                except Exception as e:
                    logger.warning(f"Plugin shutdown error '{name}': {e}")

    def _detect_domains(self, module_name: str) -> list[str]:
        domain_map = {
            "telegram_bot": ["api.telegram.org"],
            "gmail_bridge": ["gmail.googleapis.com", "www.googleapis.com"],
            "calendar_bridge": ["www.googleapis.com"],
            "slack_bridge": ["slack.com", "hooks.slack.com"],
            "whatsapp_bridge": ["graph.facebook.com"],
            "homebridge": ["localhost:8581"],
            "spotify_control": ["api.spotify.com", "accounts.spotify.com"],
        }
        return domain_map.get(module_name, [])

    def list_plugins(self) -> list[dict]:
        return [
            {
                "name": m.name,
                "enabled": m.enabled,
                "allowed_domains": m.allowed_domains,
                "data_scope": m.data_scope
            }
            for m in self._registry.values()
        ]
