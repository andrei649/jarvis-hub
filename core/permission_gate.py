import logging
from typing import Optional

logger = logging.getLogger("permissions")


class Permission:
    def __init__(self, plugin: str, action: str, scope: str = "read-only",
                 allowed_domains: list[str] = None, requires_approval: bool = False):
        self.plugin = plugin
        self.action = action
        self.scope = scope
        self.allowed_domains = allowed_domains or []
        self.requires_approval = requires_approval


class PermissionGate:
    def __init__(self):
        self._permissions: dict[str, list[Permission]] = {}
        self._deny_all: set[str] = set()

    def grant(self, permission: Permission):
        if permission.plugin not in self._permissions:
            self._permissions[permission.plugin] = []
        self._permissions[permission.plugin].append(permission)

    def revoke_all(self, plugin: str):
        if plugin in self._permissions:
            del self._permissions[plugin]
        self._deny_all.add(plugin)

    def check(self, plugin: str, action: str, params: dict = None) -> bool:
        if plugin in self._deny_all:
            logger.info(f"Permission DENY (globally revoked): {plugin}.{action}")
            return False
        plugin_perms = self._permissions.get(plugin, [])
        for perm in plugin_perms:
            if perm.action == "*" or perm.action == action:
                if perm.requires_approval:
                    logger.info(f"Permission APPROVAL NEEDED: {plugin}.{action}")
                    return False
                return True
        logger.info(f"Permission DENY (no matching rule): {plugin}.{action}")
        return False

    def set_deny_all(self, plugin: str, denied: bool = True):
        if denied:
            self._deny_all.add(plugin)
        else:
            self._deny_all.discard(plugin)
