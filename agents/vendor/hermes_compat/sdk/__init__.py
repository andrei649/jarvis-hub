"""Stand-ins for the vendor SDKs the adopted providers call (``exa_py``, ``parallel``).

The real SDKs build their own HTTP clients, which would be a bare route around Nerva's
egress layer, so they are never imported. Each stand-in implements only the calls the
vendored providers make, speaking the vendor's documented REST endpoint through the compat
``httpx`` (and so through the bound ``PluginHTTPClient``). Extraction calls are not
implemented: Nerva's ``web_extract`` has its own reader and does not use these providers.
"""
