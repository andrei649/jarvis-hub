"""Owner retirement: Argus retains Signal Layer but exposes no WorldView tools."""
from types import SimpleNamespace

from agents.core.argus import ArgusInterface
from agents.core.plugin_gate import PermissionGate


def test_argus_advertises_only_the_retained_signal_layer():
    signal_layer = object()
    facade = ArgusInterface.from_orchestrator(SimpleNamespace(
        permission_gate=PermissionGate(),
        plugins={"signal-layer": signal_layer, "worldview": object()},
    ))
    assert facade.capabilities() == {
        "agent": "argus",
        "signal_layer": {
            "permitted": True,
            "wired": True,
            "methods": ["ask_world", "world_brief", "country_risk", "signals"],
        },
    }


def test_argus_no_longer_exposes_retired_read_or_write_tools():
    facade = ArgusInterface(PermissionGate())
    for method in ("worldview_state", "recon_overview", "watch_aoi", "reconstruct_event"):
        assert not hasattr(facade, method), method
