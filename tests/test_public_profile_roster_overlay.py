"""Tests for the NERVA_PUBLIC_PROFILE public-demo roster overlay (H23.30 R2 / DRA-07)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from agents.core.config import JarvisConfig
from agents.core.llm.hybrid_router import LOCAL_ONLY_AGENTS

REPO = Path(__file__).resolve().parent.parent
PUBLIC_OVERLAY = REPO / "agents" / "_system" / "agents.public.yaml"
EXTERNAL_OR_PERSONAL_PLUGINS = {
    "telegram",
    "gmail",
    "google-calendar",
    "spotify",
    "apple-health",
    "whatsapp",
    "social_x",
}


def test_default_profile_loads_full_shipped_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NERVA_PUBLIC_PROFILE", raising=False)
    cfg = JarvisConfig()
    active_ids = {agent.id for agent in cfg.get_active_agents()}
    assert len(active_ids) >= 16
    assert {"jarvis", "frigga", "howard", "ultron"}.issubset(active_ids)


def test_public_profile_loads_only_cloud_safe_demo_roster(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "1")
    cfg = JarvisConfig()
    active_ids = {agent.id for agent in cfg.get_active_agents()}
    assert active_ids == {"jarvis", "athena", "veronica", "vision"}
    assert active_ids.isdisjoint(LOCAL_ONLY_AGENTS)
    assert cfg.bench == {}
    assert cfg.get_promotion_rules() == {}

    for agent in cfg.agents.values():
        assert agent.has_heartbeat is False
        assert agent.llm_policy != "local"
        assert agent.channel != "local-only"
        assert EXTERNAL_OR_PERSONAL_PLUGINS.isdisjoint(agent.plugins)


def test_public_profile_ignores_owner_agent_roster_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agents.core.agent_roster as agent_roster

    roster_file = tmp_path / "agent_roster.json"
    roster_file.write_text(
        '{"schema": 1, "agents": {"custom_private": {"created": true, "name": "Private", "status": "active"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_roster, "roster_path", lambda: roster_file)
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "true")

    cfg = JarvisConfig()
    assert "custom_private" not in cfg.agents
    assert set(cfg.agents) == {"jarvis", "athena", "veronica", "vision"}


def test_public_profile_fails_closed_if_overlay_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shutil.copy(REPO / "agents" / "_system" / "agents.yaml", tmp_path / "agents.yaml")
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "1")
    with pytest.raises(FileNotFoundError, match="agents.public.yaml"):
        JarvisConfig(str(tmp_path / "agents.yaml"))


def test_public_profile_refuses_local_only_agent_in_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shutil.copy(REPO / "agents" / "_system" / "agents.yaml", tmp_path / "agents.yaml")
    bad_overlay = yaml.safe_load(PUBLIC_OVERLAY.read_text(encoding="utf-8"))
    bad_overlay["agents"]["frigga"] = {
        "name": "Frigga",
        "status": "active",
        "tier": "foundation",
        "channel": "local-only",
        "heartbeat": "no",
        "llm_policy": "local",
        "plugins": [],
    }
    (tmp_path / "agents.public.yaml").write_text(yaml.safe_dump(bad_overlay), encoding="utf-8")
    monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "1")
    with pytest.raises(RuntimeError, match="unreadable; refusing startup"):
        JarvisConfig(str(tmp_path / "agents.yaml"))
