"""WorldView bridge contract — hub (consumer) side.

Asserts the plugin can only do what docs/contracts/worldview-bridge.md says:
every URL it constructs matches a contract endpoint, it is GET-only, and it
degrades to {"status": "unavailable"} instead of raising or fabricating.
The provider-side twin lives in worldview/backend-api/test/bridgeContract.test.ts.
"""

import re
import sys
from pathlib import Path

import pytest
import yaml

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.plugins.worldview import WorldViewPlugin

CONTRACT = repo_root / "docs" / "contracts" / "worldview-bridge.md"
PLUGIN_SRC = repo_root / "agents" / "core" / "plugins" / "worldview.py"


def contract_endpoints() -> list[dict]:
    text = CONTRACT.read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(.*?)```", text, re.S).group(1)
    data = yaml.safe_load(block)
    assert data["version"] == 1
    return data["endpoints"]


def pattern_to_regex(path: str) -> re.Pattern:
    return re.compile("^" + re.sub(r":[A-Za-z]+", r"[^/]+", path) + "$")


class RecordingClient:
    """Captures every request the plugin makes; returns an empty-but-valid body."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []  # (method, path)

    async def get(self, url: str, params=None, **kwargs):  # **kwargs: F-06 added headers=
        self.calls.append(("GET", "/" + url.split("/", 3)[3]))  # strip http://host:port
        class _Resp:
            def raise_for_status(self):
                return None
            def json(self):
                return {}
        return _Resp()

    async def close(self):
        return None


async def _exercise_all(plugin: WorldViewPlugin):
    await plugin.state_at("adsb", 1718000000.0, bbox="1,2,3,4", lod="hi")
    await plugin.recon_windows(aoi="bucharest", from_t=1.0, to_t=2.0)
    await plugin.recon_alerts(lead=900)
    await plugin.provenance("ais", "IMO 9395044")
    await plugin.ontology_objects("vessel", limit=5)
    await plugin.ontology_links("vessel", "v 1")
    await plugin.recon_overview(lead=600)


async def test_every_plugin_call_is_in_the_contract():
    plugin = WorldViewPlugin()
    rec = RecordingClient()
    plugin.client = rec
    await _exercise_all(plugin)

    patterns = [(e["method"], pattern_to_regex(e["path"])) for e in contract_endpoints()]
    assert rec.calls, "plugin made no requests — recorder not wired"
    for method, path in rec.calls:
        assert any(m == method and rx.match(path) for m, rx in patterns), (
            f"{method} {path} is NOT in the bridge contract — "
            "update docs/contracts/worldview-bridge.md (version bump) or fix the plugin"
        )


async def test_bridge_is_read_only():
    # Behavioral: the recorder only implements get(); any other verb would crash above.
    # Static belt-and-braces: the plugin source must not reach for mutating verbs.
    src = PLUGIN_SRC.read_text(encoding="utf-8")
    for verb in (".post(", ".put(", ".delete(", ".patch("):
        assert "client" + verb not in src and "self.client" + verb not in src, (
            f"bridge guarantee broken: plugin uses {verb} — mutations belong only "
            "behind the capability-gated MCP server (contract §Guarantees 1)"
        )


async def test_unreachable_provider_degrades_never_raises():
    plugin = WorldViewPlugin()

    async def _down(path, params=None):
        raise RuntimeError("connection refused")

    plugin._get = _down  # below _safe_get, above the network — no retries/breaker in the way
    for call in (
        plugin.state_at("adsb", 1.0),
        plugin.recon_windows(),
        plugin.recon_alerts(),
        plugin.provenance("adsb", "x"),
        plugin.ontology_objects("vessel"),
        plugin.ontology_links("vessel", "v1"),
        plugin.recon_overview(),
    ):
        result = await call
        assert result["status"] == "unavailable", result


async def test_unknown_layer_rejected_client_side():
    plugin = WorldViewPlugin()
    plugin.client = RecordingClient()
    res = await plugin.state_at("nope", 1.0)
    assert res["status"] == "error" and plugin.client.calls == []
