"""Verifies the orchestrator wires the Signal Layer plugin + Argus facade at startup."""

import pytest

from agents.core.config import JarvisConfig
from agents.core.orchestrator import Orchestrator
from agents.core.argus import ArgusInterface
from agents.core.plugins.signal_layer import SignalLayerPlugin


async def test_orchestrator_wires_signal_layer_and_argus():
    orch = Orchestrator(JarvisConfig())
    await orch.load_agents()

    # Signal Layer plugin is registered at startup (no longer lazily created).
    assert isinstance(orch.plugins.get("signal-layer"), SignalLayerPlugin)

    # Argus facade is instantiated and wired to both backends.
    assert isinstance(orch.argus, ArgusInterface)
    caps = orch.argus.capabilities()
    assert caps["signal_layer"]["wired"] is True
    assert caps["worldview"]["wired"] is True
    # 'argus' is permitted on both manifests, so the facade can reach them.
    assert caps["signal_layer"]["permitted"] is True
    assert caps["worldview"]["permitted"] is True
    # (Fail-safe behavior of the facade itself is covered by test_argus_interface.py;
    # we avoid making a real world_brief() call here because resilient_call's shared
    # circuit breaker for "plugin:signal-layer" would leak across tests.)


async def test_orchestrator_constructs_the_governance_bridge_default_off():
    """DRA-19: the Signal Layer → approval-inbox bridge had no production constructor.

    Constructing it here is inert until the owner flips `JARVIS_SIGNAL_GOVERNANCE`,
    so this asserts both halves: the bridge exists, and it is off.
    """
    from agents.core.signal_governance import SignalGovernanceBridge

    orch = Orchestrator(JarvisConfig())

    bridge = getattr(orch, "signal_governance", None)
    assert bridge is not None, "orchestrator constructs no SignalGovernanceBridge (DRA-19)"
    assert isinstance(bridge, SignalGovernanceBridge)
    assert bridge.enabled is False              # off unless the owner says otherwise
    assert bridge.queue is orch.autonomy_queue  # the real decision inbox, not a copy
    # Queued previews are audited into the signed IntentLog, like every other
    # governed action — the sink was already there, the bridge just never used it.
    assert bridge.audit == orch.action_audit.log
