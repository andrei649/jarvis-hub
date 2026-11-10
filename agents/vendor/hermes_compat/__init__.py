"""The compat layer the vendored Hermes files import (``agents/vendor/hermes/``).

Each module stands in for one Hermes interface (or one network SDK) the vendored files
use, and maps it onto a Nerva control: ``httpx`` onto the plugin egress client,
``web_search_provider.get_provider_env`` and ``os_env`` onto an env allowlist read through
``agents.core.env_config``, ``plugin_ctx`` onto Nerva's search-provider registry. Nothing
here owns a network client. Guide: ``docs/hermes/ADOPT_LANE.md``.
"""
