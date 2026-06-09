"""
secrets_vault.py — H21.A Secrets outside .env (vaultwarden resolver).

Resolve API keys from a self-hosted vault (vaultwarden) instead of plaintext
.env, with an **explicit** fallback. Ties into the secret-broker (H15.4) /
key-hygiene (HF-5), local-first. The vault client is injected (the live HTTP
client to vaultwarden is the host seam); resolution + fallback are offline-testable.
"""

from __future__ import annotations

import os
from typing import Optional


class VaultResolver:
    """Resolve secrets from a vault, falling back to the environment explicitly."""

    def __init__(self, client=None, fallback_env: bool = True, prefix: str = "") -> None:
        self._client = client      # client.get(key) -> value | None
        self.fallback_env = fallback_env
        self.prefix = prefix

    def available(self) -> bool:
        return self._client is not None

    def resolve(self, key: str, default: Optional[str] = None) -> dict:
        if self._client is not None:
            try:
                v = self._client.get(key)
                if v:
                    return {"value": v, "source": "vault"}
            except Exception:
                pass
        if self.fallback_env:
            v = os.environ.get(self.prefix + key) or os.environ.get(key)
            if v:
                return {"value": v, "source": "env"}
        return {"value": default, "source": "default" if default is not None else "missing"}
