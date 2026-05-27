"""
Built-in plugins for Jarvis.
Each plugin is a scope-limited, permission-gated integration.
"""

from ..plugin_gate import (
    PermissionGate,
    PluginManifest,
    NetworkAccess,
    DataScope,
    BUILTIN_PLUGINS,
)

__all__ = [
    "PermissionGate",
    "PluginManifest",
    "NetworkAccess",
    "DataScope",
    "BUILTIN_PLUGINS",
]
