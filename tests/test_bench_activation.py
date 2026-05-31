"""Tests for H3.6 — Bench Agent Activation.

Covers:
- promote_bench_agent creates a routable agent with a SOUL stub
- idempotency (calling twice is a no-op)
- auto_promote OFF → no promotion happens, but suggestions are still returned by /learning
- auto_promote ON → _record_interactions triggers promotion automatically

LLM calls are never made (no live backend required).
"""

import sys
from pathlib import Path
import asyncio

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.config import JarvisConfig
from agents.core.orchestrator import Orchestrator


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_orch(tmp_path) -> Orchestrator:
    """Build an Orchestrator using a tmp_path for any SOUL stubs written."""
    cfg = JarvisConfig()
    orch = Orchestrator(cfg)
    # Redirect SOUL.md stubs to tmp_path so tests don't pollute the repo.
    # We monkey-patch by overriding the Path used inside promote_bench_agent.
    # The cleanest way: patch the cwd so relative paths land in tmp_path.
    return orch


def _seed(orch, agent_id, n, success=True):
    for _ in range(n):
        orch.learning.record(
            agent_id=agent_id, task="t", response="r",
            success=success, latency=0.1,
        )


# ── promote_bench_agent: basic promotion ──────────────────────────────────────

def test_promote_bench_agent_returns_true_and_registers(tmp_path, monkeypatch):
    """promote_bench_agent should add the bench agent to self.agents and the routing table."""
    monkeypatch.chdir(tmp_path)
    # Copy agents/_system/agents.yaml to tmp_path so config loads from here,
    # and create a minimal agents dir so the SOUL stub path is writable.
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)

    assert "bruce" not in orch.agents
    result = orch.promote_bench_agent("bruce")

    assert result is True
    assert "bruce" in orch.agents
    agent = orch.agents["bruce"]
    assert agent.id == "bruce"
    assert agent.name == "Bruce"


def test_promote_bench_agent_adds_to_routing_table(tmp_path, monkeypatch):
    """The promoted agent should be wake-word routable."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)

    assert "bruce" not in orch.router.ROUTING_TABLE
    orch.promote_bench_agent("bruce")
    assert "bruce" in orch.router.ROUTING_TABLE
    assert orch.router.ROUTING_TABLE["bruce"] == ["bruce"]


def test_promote_bench_agent_writes_soul_stub(tmp_path, monkeypatch):
    """When no SOUL.md exists, a stub should be created."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)

    soul_path = tmp_path / "agents" / "bruce" / "SOUL.md"
    assert not soul_path.exists()

    orch.promote_bench_agent("bruce")

    assert soul_path.exists()
    content = soul_path.read_text()
    assert "Bruce" in content
    assert "Data Science" in content  # archetype from agents.yaml


def test_promote_bench_agent_soul_not_overwritten(tmp_path, monkeypatch):
    """If a SOUL.md already exists it should be left untouched."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )
    # Pre-create SOUL.md with known content.
    soul_dir = tmp_path / "agents" / "bruce"
    soul_dir.mkdir(parents=True)
    soul_path = soul_dir / "SOUL.md"
    custom_content = "# Custom SOUL\nThis is my custom content."
    soul_path.write_text(custom_content)

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)
    orch.promote_bench_agent("bruce")

    assert soul_path.read_text() == custom_content  # unchanged


# ── idempotency ────────────────────────────────────────────────────────────────

def test_promote_bench_agent_idempotent(tmp_path, monkeypatch):
    """Calling promote_bench_agent twice returns False on second call, no crash."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)

    first = orch.promote_bench_agent("bruce")
    second = orch.promote_bench_agent("bruce")

    assert first is True
    assert second is False
    # Still exactly one bruce in agents.
    assert list(orch.agents.keys()).count("bruce") == 1


def test_promote_bench_agent_routing_table_idempotent(tmp_path, monkeypatch):
    """Double promotion doesn't duplicate the routing table entry."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)

    orch.promote_bench_agent("bruce")
    orch.promote_bench_agent("bruce")

    assert orch.router.ROUTING_TABLE["bruce"] == ["bruce"]


# ── unknown bench agent ───────────────────────────────────────────────────────

def test_promote_unknown_bench_agent_returns_false():
    """A bench_id not in the config returns False gracefully."""
    cfg = JarvisConfig()
    orch = Orchestrator(cfg)
    result = orch.promote_bench_agent("doesnotexist")
    assert result is False
    assert "doesnotexist" not in orch.agents


# ── auto_promote OFF ──────────────────────────────────────────────────────────

def test_auto_promote_off_no_promotion_but_suggestions_visible(tmp_path, monkeypatch):
    """With auto_promote OFF (default), _record_interactions must NOT promote
    even when the threshold is crossed, but suggestions are still returned."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)
    # Ensure auto_promote is OFF (default).
    orch._runtime_settings["learning.auto_promote"] = False

    # Seed enough vision interactions to cross the bruce threshold (20).
    _seed(orch, "vision", 21)

    # Simulate _record_interactions with a no-op response dict.
    # We only need the auto-promotion hook logic to run; agent calls are irrelevant.
    orch._record_interactions("test", {}, "")

    # Bruce must NOT have been promoted.
    assert "bruce" not in orch.agents

    # But suggestions should still be available.
    suggestions = orch.learning.suggest_promotions(active_ids=set(orch.agents.keys()))
    assert any(s["bench_agent"] == "bruce" for s in suggestions)


# ── auto_promote ON ───────────────────────────────────────────────────────────

def test_auto_promote_on_promotes_when_threshold_met(tmp_path, monkeypatch):
    """With auto_promote ON, _record_interactions must promote bruce once the
    vision threshold (20) is crossed."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)
    orch._runtime_settings["learning.auto_promote"] = True

    # Seed 21 vision interactions — above threshold.
    _seed(orch, "vision", 21)

    orch._record_interactions("test", {}, "")

    # Bruce should now be in active agents.
    assert "bruce" in orch.agents
    assert "bruce" in orch.router.ROUTING_TABLE


def test_auto_promote_on_below_threshold_no_promotion(tmp_path, monkeypatch):
    """auto_promote ON but below threshold: still no promotion."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)
    orch._runtime_settings["learning.auto_promote"] = True

    # Only 19 interactions — below threshold of 20.
    _seed(orch, "vision", 19)
    orch._record_interactions("test", {}, "")

    assert "bruce" not in orch.agents


# ── router classify after promotion ───────────────────────────────────────────

def test_promoted_agent_is_wake_word_routable(tmp_path, monkeypatch):
    """After promotion, the router should resolve 'bruce' as a wake word."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents" / "_system").mkdir(parents=True)
    import shutil
    shutil.copy(
        str(repo_root / "agents" / "_system" / "agents.yaml"),
        str(tmp_path / "agents" / "_system" / "agents.yaml"),
    )

    cfg = JarvisConfig(path=str(tmp_path / "agents" / "_system" / "agents.yaml"))
    orch = Orchestrator(cfg)
    orch.promote_bench_agent("bruce")

    async def _classify():
        return await orch.router.classify("bruce, analyse this dataset", orch.agents)

    intent = asyncio.run(_classify())
    assert intent.target_agents == ["bruce"]
    assert intent.context.get("source") == "wake_word"
