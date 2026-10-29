"""Endpoint-scoped Fernet vault with a distinct custom authority domain.

The existing protected envelope/HWM implementation is reused as a crypto
primitive. Custom bindings never impersonate signed package artifacts.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .custom_endpoints import classify_url
from .providers.credentials import ProviderCredentialStore
from .providers.packages import ProviderPackageError

_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")


@dataclass(frozen=True, slots=True)
class CustomCredentialBinding:
    home: str
    key: str
    endpoint: str
    auth_type: str
    authority: str = "custom-endpoint-owner-v1"

    def __post_init__(self):
        if (self.authority != "custom-endpoint-owner-v1"
                or type(self.home) is not str or not 1 <= len(self.home) <= 2048
                or type(self.key) is not str or not _KEY.fullmatch(self.key)
                or self.auth_type not in {"none", "bearer", "api-key"}):
            raise ProviderPackageError("invalid custom credential binding")
        classify_url(self.endpoint)


class CustomCredentialStore(ProviderCredentialStore):
    """The envelope and high-water anchor remain private to a custom root."""

    def path(self, binding: CustomCredentialBinding) -> Path:
        if type(binding) is not CustomCredentialBinding:
            raise ProviderPackageError("exact custom credential binding required")
        payload = json.dumps(asdict(binding), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode()
        return self.root / (hashlib.sha256(b"custom-credential-v1\0" + payload).hexdigest() + ".enc")
