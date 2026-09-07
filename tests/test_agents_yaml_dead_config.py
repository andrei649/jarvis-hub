"""Hermes absorption 0.6 — the canonical registry carries no config that nothing reads.

`agents/_system/agents.yaml` had a `general:` block (timezone, wake words, LLM backend and
endpoints, a cloud-LLM plugin mode, a `cloud_llm_agents` allowlist, a WhatsApp bridge mode).
`JarvisConfig` copied it into `.general` and no line of code ever consulted it, so every reader
— human or agent — was told the file controlled routing it did not. The block is gone; these
tests keep it gone and keep the top-level keys of the file to the ones the loader consumes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agents.core.config import JarvisConfig

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "agents" / "_system" / "agents.yaml"

# `JarvisConfig._load` reads exactly these; `jarvis:` is the file's own header.
CONSUMED_TOP_LEVEL_KEYS = {"agents", "plugins", "bench"}
HEADER_KEYS = {"jarvis"}


def _registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def test_the_registry_has_no_general_block():
    assert "general" not in _registry()
    assert JarvisConfig().general == {}


def test_every_top_level_registry_key_is_consumed_or_the_header():
    unread = set(_registry()) - CONSUMED_TOP_LEVEL_KEYS - HEADER_KEYS
    assert not unread, f"agents.yaml carries keys no code reads: {sorted(unread)}"


def test_the_dead_allowlist_is_not_documented_as_live():
    """The setup guide used to instruct configuring a list nothing read."""
    assert "cloud_llm_agents" not in REGISTRY.read_text(encoding="utf-8").split("# There is deliberately", 1)[1].split("\n\n", 1)[1]
    nerva = (REPO / "NERVA.md").read_text(encoding="utf-8")
    assert "Configure `cloud_llm_agents`" not in nerva
    assert "hybrid_router.py" in nerva


def test_the_routing_that_is_real_is_still_there():
    from agents.core.llm.hybrid_router import CLAUDE_AGENTS, LOCAL_ONLY_AGENTS

    assert "frigga" in LOCAL_ONLY_AGENTS
    assert CLAUDE_AGENTS
