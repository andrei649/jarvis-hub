"""HUD roster parity (BACKLOG GAP-9 follow-up): /api/agents must describe every
registry agent — including registry-only agents that the HUD's static seed corpus
never knew (howard, hestia) — by deriving tier/role from each agent's SOUL.md
front-matter when no curated meta row exists. The curated table keeps priority
for ids it knows, so its human-readable roles are not regressed."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture(scope="module")
def client():
    from agents.web import app
    with TestClient(app) as c:
        yield c


def _agents(client):
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    return {a["id"]: a for a in resp.json()["agents"]}


def test_registry_only_agents_are_served(client):
    agents = _agents(client)
    for aid in ("howard", "hestia", "argus"):
        assert aid in agents, f"{aid} missing from /api/agents"


def test_soul_frontmatter_derives_role_and_tier(client):
    agents = _agents(client)
    # howard: no curated row -> role comes from the SOUL.md archetype,
    # tier mapped from the front-matter word (foundation -> FND).
    assert agents["howard"]["role"] == "Digital Twin / Archive"
    assert agents["howard"]["tier"] == "FND"
    assert agents["hestia"]["role"] == "House Brain"
    assert agents["hestia"]["tier"] == "FND"
    # argus HAS a curated row; it must win over the raw archetype text.
    assert agents["argus"]["role"] == "Geospatial OSINT / Intel"
    assert agents["argus"]["tier"] == "BIZ"


def test_curated_roles_win_over_frontmatter_wording(client):
    agents = _agents(client)
    # The seed souls spell some archetypes with YAML-safe 'Plus'/'+' instead of
    # '&'; the curated table carries the human copy and must keep priority.
    assert agents["gecko"]["role"] == "Markets & Capital"
    assert agents["steve"]["role"] == "CTO / Builds"


def test_every_agent_has_nonempty_role_and_known_tier(client):
    agents = _agents(client)
    for aid, a in agents.items():
        assert a["role"], f"{aid} served an empty role"
        assert a["tier"] in {"CNS", "BIZ", "SEC", "FND"}, f"{aid} bad tier {a['tier']}"
