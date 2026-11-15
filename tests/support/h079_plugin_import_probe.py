"""Fresh-process proof that an excluded connector is never imported or built."""

import json
import os
import sys
from types import SimpleNamespace

from agents.core import integration_keys, load_set  # noqa: E402
from agents.core import plugin_manager as module
from agents.core.plugin_gate import PermissionGate  # noqa: E402

module.load_hub_env = lambda: None
module._oauth_init = lambda: None
module._load_token = lambda _provider: None
integration_keys.apply_stored = lambda: None
mode = os.environ.get("V42_MODE", "only")
load_set.declared = lambda _kind: ({"disabled": [], "only": ["news"]}
                                    if mode == "only" else
                                    {"disabled": ["gmail", "spotify"], "only": []})

before = {key for key in sys.modules if key.startswith("agents.core.plugins.")}
manager = module.PluginManager()
orch = SimpleNamespace(get_setting=lambda _key, default=None: default,
                       permission_gate=PermissionGate(), plugins=manager.plugins)
manager.build(orch)
after = {key for key in sys.modules if key.startswith("agents.core.plugins.")}
print(json.dumps({"keys": list(manager.plugins), "imported": sorted(after - before),
                  "gmail_absent": "agents.core.plugins.gmail_plugin" not in after,
                  "spotify_absent": "agents.core.plugins.spotify_plugin" not in after,
                  "news_concrete": type(manager.plugins["news"]).__name__ == "NewsPlugin"}))
