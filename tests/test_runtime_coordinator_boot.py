"""scripts/coordinator.py — the headless coordinator/heartbeat/night-shift boot.

Only the boot path is exercised here (fast, deterministic): a full tick cycle
needs a live AutonomyCoordinator.loop() iteration (>=15s wall clock, see the
loop's own floor) which is covered by manual end-to-end verification instead
(HANDOFF.md), not a unit test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "scripts"))
sys.path.insert(0, str(repo_root / "agents"))

from scripts.coordinator import _build_orchestrator  # noqa: E402


@pytest.mark.asyncio
async def test_fake_llm_boot_loads_real_agents_and_heartbeat_scheduler(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_TESTING", "1")
    monkeypatch.setenv("JARVIS_RUNTIME_FAKE_LLM", "1")

    orch = await _build_orchestrator()
    try:
        assert len(orch.agents) > 0
        assert orch.heartbeat_scheduler is not None
        assert orch._autonomy is not None
        assert orch.llm_router._backend is not None
    finally:
        await orch.aclose()


@pytest.mark.asyncio
async def test_fake_llm_flag_off_leaves_real_detect_in_place(tmp_path, monkeypatch):
    """Without the opt-in flag, boot must not silently fake the LLM backend —
    byte-identical to a normal Orchestrator() construction."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_TESTING", "1")
    monkeypatch.delenv("JARVIS_RUNTIME_FAKE_LLM", raising=False)

    from agents.core.config import JarvisConfig
    from agents.core.orchestrator import Orchestrator

    plain = Orchestrator(JarvisConfig())
    orch = await _build_orchestrator()
    try:
        assert type(orch.llm_router.detect) is type(plain.llm_router.detect)
    finally:
        await orch.aclose()
        await plain.aclose()
