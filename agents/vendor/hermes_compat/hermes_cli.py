"""The four ``hermes_cli`` leaf modules a vendored profile or ``providers/base.py`` touches
(rewrite rule ``hermes-cli-leaf``): ``version_info``, ``auth``, ``urllib_security`` and
``chat_catalog``.

* The user agent names Nerva, never Hermes Agent. Nerva's bridge drops a profile's
  ``User-Agent`` header anyway: the request headers are Nerva's.
* Hermes's credential pool does not exist here: keys come from Nerva's env registry, per
  provider, through the bridge. ``read_credential_pool`` answers an empty pool.
* ``open_credentialed_url`` (``ProviderProfile.fetch_models``) is refused: a vendored
  profile opens no connection. The model picker is Nerva's.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

_PRODUCT = "Nerva"


def get_version_info() -> Any:
    return SimpleNamespace(base_version="nerva")


def hermes_user_agent(product: str = "") -> str:
    return _PRODUCT


def read_credential_pool(name: str) -> list:
    return []


class CatalogFetchRefused(PermissionError):
    """A vendored profile tried to open a connection; profiles in Nerva open none."""


def open_credentialed_url(request: Any, timeout: float = 0.0) -> Any:
    raise CatalogFetchRefused("vendored provider profiles open no connection in Nerva")


def chat_catalog_ids(items: Any) -> list[str]:
    return []
