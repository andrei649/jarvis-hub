"""Tests for H10.29 — Agent Templates Library."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.agent_templates import (
    AGENT_TEMPLATES, list_templates, get_template, build_agent_config,
)


def test_catalog_nonempty_and_shaped():
    cat = list_templates()
    assert len(cat) == len(AGENT_TEMPLATES)
    for t in cat:
        assert {"key", "name", "role", "tier", "model", "plugins"} <= set(t)


def test_get_template_known_and_unknown():
    assert get_template("researcher")["role"]
    assert get_template("RESEARCHER") is not None      # case-insensitive
    assert get_template("nope") is None


def test_build_config_defaults_and_slug():
    cfg = build_agent_config("coder")
    assert cfg["id"] == "coder"
    assert cfg["model"] == AGENT_TEMPLATES["coder"]["model"]
    assert cfg["status"] == "active"
    assert "SOUL" in cfg["soul"]


def test_build_config_name_and_overrides():
    cfg = build_agent_config("researcher", name="Vega Prime",
                             overrides={"model": "custom:1b", "plugins": ["news"]})
    assert cfg["name"] == "Vega Prime"
    assert cfg["id"] == "vega_prime"                   # slugified
    assert cfg["model"] == "custom:1b"
    assert cfg["plugins"] == ["news"]


def test_build_config_unknown_raises():
    with pytest.raises(KeyError):
        build_agent_config("does-not-exist")


# ── endpoints ───────────────────────────────────────────────────────────────

def test_templates_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        r = c.get("/api/agent-templates")
        assert r.status_code == 200
        assert len(r.json()["templates"]) == len(AGENT_TEMPLATES)

        ok = c.post("/api/agent-templates/instantiate",
                    json={"template": "analyst", "name": "Stark Jr"})
        assert ok.status_code == 200
        cfg = ok.json()["config"]
        assert cfg["id"] == "stark_jr" and cfg["template"] == "analyst"

        missing = c.post("/api/agent-templates/instantiate", json={"template": "ghost"})
        assert missing.status_code == 404
