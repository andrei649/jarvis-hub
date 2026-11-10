"""``urllib.request`` for vendored code (rewrite rule ``urllib-request``).

``ProviderProfile.fetch_models`` builds a ``urllib.request.Request`` and hands it to
``open_credentialed_url``, which the compat ``hermes_cli`` refuses. This module gives the
vendored line its request object and nothing that can open one: no ``urlopen``, no opener.
"""

from __future__ import annotations

from types import SimpleNamespace


class Request:
    """An inert request description (URL and headers), never sent."""

    def __init__(self, url: str, *args: object, **kwargs: object) -> None:
        self.full_url = url
        self.headers: dict[str, str] = {}

    def add_header(self, key: str, value: str) -> None:
        self.headers[str(key)] = str(value)


request = SimpleNamespace(Request=Request)
