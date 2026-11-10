"""``tools.web_tools`` for vendored code: only the SDK client cache slots.

``plugins/web/_common.cached_sdk_client`` keeps ``(api_key, client)`` here so a key change
rebuilds the client. The clients cached here are the compat SDK stand-ins, which own no
network client (see ``hermes_compat.sdk``).
"""

_exa_client = None
_parallel_client = None
_async_parallel_client = None
